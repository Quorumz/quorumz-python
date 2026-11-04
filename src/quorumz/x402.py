"""Pay per call with x402 (v2, ``exact`` scheme, USDC).

An unpaid call answers HTTP 402 with a ``PAYMENT-REQUIRED`` header: base64
JSON whose ``accepts`` list one USDC payment per network. :class:`X402Payer`
picks the entry for a network you hold USDC on, signs an EIP-3009
``transferWithAuthorization`` for exactly that amount, and the client retries
the request with the payment in the ``PAYMENT-SIGNATURE`` header. Nothing is
sent on-chain by this package: the server's facilitator settles the
authorization, and the receipt comes back in ``PAYMENT-RESPONSE``.

Signing needs the ``x402`` extra::

    pip install "quorumz[x402]"

Safety rails, all checked before anything is signed:

- only USDC on Base, Polygon and Arbitrum is signed, at the USDC contract
  pinned here for each network, whatever the 402 names;
- the EIP-712 domain is pinned too (name "USD Coin", version "2", the
  chain id, the USDC contract);
- the amount must be at most ``max_payment_usd``.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .errors import X402Error

__all__ = ["NETWORKS", "UsdcNetwork", "X402Payer", "decode_payment_required", "encode_header", "network_id"]

X402_VERSION = 2
DEFAULT_MAX_PAYMENT_USD = 1.0
# How far back validAfter reaches, to tolerate clock skew between the payer,
# the facilitator and the chain. The x402 reference clients use 600 seconds.
VALID_AFTER_SKEW_SECONDS = 600


@dataclass(frozen=True)
class UsdcNetwork:
    """Native USDC on one EVM network, as the x402 ``exact`` scheme signs it."""

    network: str  # CAIP-2 id, as in the 402's accepts[].network
    name: str
    chain_id: int
    usdc: str  # the USDC contract: EIP-712 verifyingContract and accepts[].asset
    domain_name: str = "USD Coin"
    domain_version: str = "2"


NETWORKS: dict[str, UsdcNetwork] = {
    "eip155:8453": UsdcNetwork("eip155:8453", "Base", 8453, "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
    "eip155:137": UsdcNetwork("eip155:137", "Polygon", 137, "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"),
    "eip155:42161": UsdcNetwork("eip155:42161", "Arbitrum", 42161, "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"),
}
_ALIASES = {
    "base": "eip155:8453",
    "polygon": "eip155:137",
    "matic": "eip155:137",
    "arbitrum": "eip155:42161",
    "arbitrum-one": "eip155:42161",
}

_TRANSFER_WITH_AUTHORIZATION = [
    {"name": "from", "type": "address"},
    {"name": "to", "type": "address"},
    {"name": "value", "type": "uint256"},
    {"name": "validAfter", "type": "uint256"},
    {"name": "validBefore", "type": "uint256"},
    {"name": "nonce", "type": "bytes32"},
]
_EIP712_DOMAIN = [
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]


def network_id(network: str) -> str:
    """``"base"`` or ``"eip155:8453"`` -> ``"eip155:8453"``."""
    key = network.strip().lower()
    resolved = _ALIASES.get(key, key)
    if resolved not in NETWORKS:
        known = ", ".join(f"{n.name.lower()} ({n.network})" for n in NETWORKS.values())
        raise X402Error(f"Unsupported x402 network {network!r}. Supported: {known}.")
    return resolved


def encode_header(value: dict[str, Any]) -> str:
    """Base64 of compact JSON, as x402 v2 headers carry it."""
    return base64.b64encode(json.dumps(value, separators=(",", ":")).encode()).decode()


def decode_payment_required(header: str | None, body: Any = None) -> dict[str, Any] | None:
    """The x402 challenge of a 402: the ``PAYMENT-REQUIRED`` header, else the
    JSON body when it is an x402 v2 challenge. None when neither is."""
    if header:
        try:
            parsed = json.loads(base64.b64decode(header.strip(), validate=False))
        except (binascii.Error, ValueError):
            parsed = None
        if isinstance(parsed, dict) and "accepts" in parsed:
            return parsed
    if isinstance(body, dict) and "accepts" in body and "x402Version" in body:
        return body
    return None


def usd(atomic: int | str) -> float:
    """Atomic USDC (6 decimals) -> dollars."""
    return int(atomic) / 1_000_000


class X402Payer:
    """Signs x402 ``exact`` payments in USDC with an EVM private key.

    Args:
        private_key: a hex private key, or an ``eth_account`` ``LocalAccount``.
            Use a dedicated hot wallet that holds only the USDC you mean to
            spend on calls. No gas is needed: the facilitator submits the
            transfer.
        network: the network(s) to pay on, in order of preference: ``"base"``,
            ``"polygon"``, ``"arbitrum"`` or CAIP-2 ids such as
            ``"eip155:8453"``. Default: any of the three, in the server's order.
        max_payment_usd: refuse to sign a single call above this amount.
            Default 1.00, the most one page can cost (50 alpha events).
    """

    def __init__(
        self,
        private_key: Any,
        *,
        network: str | Sequence[str] | None = None,
        max_payment_usd: float = DEFAULT_MAX_PAYMENT_USD,
    ) -> None:
        try:
            from eth_account import Account
        except ImportError as error:  # pragma: no cover - exercised without the extra
            raise ImportError(
                'x402 payments need the x402 extra: pip install "quorumz[x402]"'
            ) from error
        if hasattr(private_key, "sign_message") and hasattr(private_key, "address"):
            self._account = private_key
        else:
            self._account = Account.from_key(private_key)
        if network is None:
            self.networks: tuple[str, ...] = ()
        elif isinstance(network, str):
            self.networks = (network_id(network),)
        else:
            self.networks = tuple(network_id(n) for n in network)
        if max_payment_usd <= 0:
            raise ValueError("max_payment_usd must be positive")
        self.max_payment_usd = float(max_payment_usd)

    def __repr__(self) -> str:  # never the key
        networks = ", ".join(self.networks) if self.networks else "any"
        return f"X402Payer(address={self.address!r}, networks={networks}, max_payment_usd={self.max_payment_usd})"

    @property
    def address(self) -> str:
        """The paying address (EIP-55 checksummed)."""
        return str(self._account.address)

    def select(self, payment_required: dict[str, Any]) -> dict[str, Any]:
        """The ``accepts`` entry this payer will sign, or raise :class:`X402Error`."""
        version = payment_required.get("x402Version")
        if version != X402_VERSION:
            raise X402Error(f"Unsupported x402 version {version!r}; this client speaks x402 v{X402_VERSION}.")
        accepts = payment_required.get("accepts") or []
        usable: dict[str, dict[str, Any]] = {}
        for entry in accepts:
            if not isinstance(entry, dict) or entry.get("scheme") != "exact":
                continue
            known = NETWORKS.get(str(entry.get("network")))
            if known is None or str(entry.get("asset", "")).lower() != known.usdc.lower():
                continue  # not USDC on a network we know: never sign it
            usable.setdefault(known.network, entry)
        order = self.networks or tuple(usable)
        for network in order:
            if network in usable:
                entry = usable[network]
                self._check_amount(entry)
                return entry
        offered = ", ".join(str(e.get("network")) for e in accepts if isinstance(e, dict)) or "nothing"
        wanted = ", ".join(self.networks) if self.networks else "Base, Polygon or Arbitrum USDC"
        raise X402Error(f"No x402 payment option matches this payer: the server accepts {offered}; the payer pays on {wanted}.")

    def _check_amount(self, entry: dict[str, Any]) -> None:
        try:
            amount = int(entry["amount"])
        except (KeyError, TypeError, ValueError) as error:
            raise X402Error(f"The 402 has no valid amount: {entry.get('amount')!r}") from error
        if amount <= 0:
            raise X402Error(f"The 402 asks for a non-positive amount: {amount}")
        if amount > round(self.max_payment_usd * 1_000_000):
            raise X402Error(
                f"This call costs ${usd(amount):.6g}, above max_payment_usd=${self.max_payment_usd:.6g}. "
                "Ask for fewer results (limit=) or raise max_payment_usd."
            )

    def create_payment(
        self,
        payment_required: dict[str, Any],
        *,
        now: int | None = None,
        nonce: bytes | None = None,
    ) -> dict[str, Any]:
        """The x402 v2 ``PaymentPayload`` for a decoded 402 challenge.

        ``resource`` and ``extensions`` are echoed from the 402, ``accepted``
        is the chosen ``accepts`` entry unchanged, and ``payload`` is the
        signed EIP-3009 authorization.
        """
        from eth_account.messages import encode_typed_data
        from eth_utils.address import to_checksum_address

        entry = self.select(payment_required)
        network = NETWORKS[entry["network"]]
        now = int(time.time()) if now is None else int(now)
        nonce = os.urandom(32) if nonce is None else nonce
        if len(nonce) != 32:
            raise ValueError("nonce must be 32 bytes")
        timeout = int(entry.get("maxTimeoutSeconds") or 300)
        authorization = {
            "from": self.address,
            "to": to_checksum_address(entry["payTo"]),
            "value": str(int(entry["amount"])),
            "validAfter": str(now - VALID_AFTER_SKEW_SECONDS),
            "validBefore": str(now + timeout),
            "nonce": "0x" + nonce.hex(),
        }
        typed_data = {
            "types": {"EIP712Domain": _EIP712_DOMAIN, "TransferWithAuthorization": _TRANSFER_WITH_AUTHORIZATION},
            "primaryType": "TransferWithAuthorization",
            "domain": {
                "name": network.domain_name,
                "version": network.domain_version,
                "chainId": network.chain_id,
                "verifyingContract": network.usdc,
            },
            "message": {
                "from": authorization["from"],
                "to": authorization["to"],
                "value": int(authorization["value"]),
                "validAfter": int(authorization["validAfter"]),
                "validBefore": int(authorization["validBefore"]),
                "nonce": nonce,
            },
        }
        signed = self._account.sign_message(encode_typed_data(full_message=typed_data))
        payload: dict[str, Any] = {"x402Version": X402_VERSION}
        if "resource" in payment_required:
            payload["resource"] = payment_required["resource"]
        payload["accepted"] = entry
        payload["payload"] = {"signature": "0x" + bytes(signed.signature).hex(), "authorization": authorization}
        if "extensions" in payment_required:
            payload["extensions"] = payment_required["extensions"]
        return payload

    def create_payment_header(self, payment_required: dict[str, Any]) -> str:
        """The ``PAYMENT-SIGNATURE`` header value: the payment, base64 JSON."""
        return encode_header(self.create_payment(payment_required))
