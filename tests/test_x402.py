"""Building x402 v2 payments from the 402 the live API answers."""

from __future__ import annotations

import base64
import copy
import json
from typing import Any

import httpx
import pytest
import respx

from quorumz import PaymentRequiredError, Quorumz, X402Error
from quorumz.x402 import decode_payment_required

eth_account = pytest.importorskip("eth_account")
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_typed_data  # noqa: E402

from quorumz import X402Payer  # noqa: E402

from .conftest import BASE, QUORUM  # noqa: E402

# A throwaway key used only by these tests. It holds nothing.
TEST_KEY = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
NOW = 1_793_000_000
NONCE = bytes(range(32))
POLYGON_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
PAY_TO = "0x9ce92953d33237af061c6b1aa29c597c8656b547"


def challenge(fixture: dict[str, Any]) -> dict[str, Any]:
    decoded = decode_payment_required(fixture["headers"]["payment-required"])
    assert decoded is not None
    return decoded


def test_header_and_body_carry_the_same_challenge(quorums_402: dict[str, Any]) -> None:
    from_header = challenge(quorums_402)
    from_body = decode_payment_required(None, quorums_402["body"])
    assert from_header["x402Version"] == 2
    assert from_header == from_body


def test_builds_a_v2_exact_payment_on_the_preferred_network(quorums_402: dict[str, Any]) -> None:
    required = challenge(quorums_402)
    payer = X402Payer(TEST_KEY, network="polygon")
    payment = payer.create_payment(required, now=NOW, nonce=NONCE)

    assert payment["x402Version"] == 2
    # resource and extensions are echoed from the 402 unchanged
    assert payment["resource"] == required["resource"]
    assert payment["extensions"] == required["extensions"]
    # accepted is the Polygon accepts entry, verbatim
    polygon = next(a for a in required["accepts"] if a["network"] == "eip155:137")
    assert payment["accepted"] == polygon

    authorization = payment["payload"]["authorization"]
    assert authorization == {
        "from": payer.address,
        "to": "0x9CE92953d33237AF061c6B1aA29c597c8656B547",  # EIP-55 of payTo
        "value": "20000",
        "validAfter": str(NOW - 600),
        "validBefore": str(NOW + 300),
        "nonce": "0x" + NONCE.hex(),
    }
    assert authorization["to"].lower() == PAY_TO

    # The signature recovers to the payer under the USDC EIP-712 domain,
    # built here independently of the package.
    typed = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ],
        },
        "primaryType": "TransferWithAuthorization",
        "domain": {"name": "USD Coin", "version": "2", "chainId": 137, "verifyingContract": POLYGON_USDC},
        "message": {
            "from": payer.address,
            "to": authorization["to"],
            "value": 20000,
            "validAfter": NOW - 600,
            "validBefore": NOW + 300,
            "nonce": NONCE,
        },
    }
    signature = payment["payload"]["signature"]
    assert signature.startswith("0x") and len(signature) == 132
    assert Account.recover_message(encode_typed_data(full_message=typed), signature=signature) == payer.address

    # Signed for another chain it would not recover: the chain id is bound.
    typed["domain"]["chainId"] = 8453
    assert Account.recover_message(encode_typed_data(full_message=typed), signature=signature) != payer.address


def test_header_is_base64_json_of_the_payment(quorums_402: dict[str, Any]) -> None:
    payer = X402Payer(TEST_KEY, network="base")
    header = payer.create_payment_header(challenge(quorums_402))
    decoded = json.loads(base64.b64decode(header))
    assert decoded["accepted"]["network"] == "eip155:8453"
    assert decoded["payload"]["authorization"]["from"] == payer.address


def test_network_preference_order_and_default(quorums_402: dict[str, Any]) -> None:
    required = challenge(quorums_402)
    assert X402Payer(TEST_KEY, network=["arbitrum", "base"]).select(required)["network"] == "eip155:42161"
    assert X402Payer(TEST_KEY).select(required)["network"] == "eip155:8453"  # the server's first
    assert X402Payer(TEST_KEY, network="eip155:137").select(required)["network"] == "eip155:137"


def test_refuses_unknown_asset_unoffered_network_and_overpriced_calls(quorums_402: dict[str, Any]) -> None:
    required = challenge(quorums_402)

    swapped = copy.deepcopy(required)
    for entry in swapped["accepts"]:
        if entry["network"] == "eip155:137":
            entry["asset"] = "0x000000000000000000000000000000000000dEaD"
    with pytest.raises(X402Error, match="No x402 payment option"):
        X402Payer(TEST_KEY, network="polygon").select(swapped)

    only_base = {**required, "accepts": [a for a in required["accepts"] if a["network"] == "eip155:8453"]}
    with pytest.raises(X402Error, match="eip155:8453"):
        X402Payer(TEST_KEY, network="arbitrum").select(only_base)

    with pytest.raises(X402Error, match="max_payment_usd"):
        X402Payer(TEST_KEY, max_payment_usd=0.01).select(required)  # the page costs $0.02

    with pytest.raises(X402Error, match="Unsupported x402 network"):
        X402Payer(TEST_KEY, network="solana")

    with pytest.raises(X402Error, match="version"):
        X402Payer(TEST_KEY).select({**required, "x402Version": 1})


def test_repr_hides_the_private_key() -> None:
    payer = X402Payer(TEST_KEY)
    assert TEST_KEY[2:] not in repr(payer)
    assert payer.address in repr(payer)


@respx.mock
def test_client_pays_the_402_and_retries_without_the_key(quorums_402: dict[str, Any]) -> None:
    receipt = {"success": True, "transaction": "0xabc", "network": "eip155:8453", "payer": "0x1"}
    paid_body = {
        "stream": "quorum", "filter": {"country": "LB"}, "quorums": [QUORUM, QUORUM], "next_cursor": "c2",
        "payment": {"status": "enforced", "charged_events": 2, "settled": True},
    }
    route = respx.get(f"{BASE}/api/agent/v1/quorums").mock(
        side_effect=[
            httpx.Response(402, json=quorums_402["body"], headers=quorums_402["headers"]),
            httpx.Response(
                200,
                json=paid_body,
                headers={"PAYMENT-RESPONSE": base64.b64encode(json.dumps(receipt).encode()).decode()},
            ),
        ]
    )
    payer = X402Payer(TEST_KEY, network="base")
    result = Quorumz(api_key="qz_pk_live_no_credits", x402=payer).quorums("LB", limit=2)

    first, retry = route.calls[0].request, route.calls[1].request
    assert first.headers["Authorization"] == "Bearer qz_pk_live_no_credits"
    assert "PAYMENT-SIGNATURE" not in first.headers
    assert "Authorization" not in retry.headers  # a key would make the server ignore the payment
    assert retry.url == first.url  # the same request, paid
    payment = json.loads(base64.b64decode(retry.headers["PAYMENT-SIGNATURE"]))
    assert payment["accepted"]["network"] == "eip155:8453"
    assert payment["payload"]["authorization"]["from"] == payer.address
    assert result["payment"]["receipt"] == receipt
    assert result["payment"]["settled"] is True


@respx.mock
def test_rejected_payment_raises_with_the_reason(quorums_402: dict[str, Any]) -> None:
    rejected = {**quorums_402["body"], "error": "insufficient_funds"}
    route = respx.get(f"{BASE}/api/agent/v1/quorums").mock(
        side_effect=[
            httpx.Response(402, json=quorums_402["body"], headers=quorums_402["headers"]),
            httpx.Response(402, json=rejected),
        ]
    )
    with pytest.raises(PaymentRequiredError) as caught:
        Quorumz(x402=X402Payer(TEST_KEY)).quorums("LB", limit=2)
    assert route.call_count == 2  # one paid retry, never a loop
    assert caught.value.reason == "insufficient_funds"
    assert "did not accept the x402 payment" in str(caught.value)


@respx.mock
def test_over_the_cap_nothing_is_signed_or_sent(quorums_402: dict[str, Any]) -> None:
    route = respx.get(f"{BASE}/api/agent/v1/quorums").mock(
        return_value=httpx.Response(402, json=quorums_402["body"], headers=quorums_402["headers"])
    )
    with pytest.raises(X402Error):
        Quorumz(x402=X402Payer(TEST_KEY, max_payment_usd=0.01)).quorums("LB", limit=2)
    assert route.call_count == 1


def test_an_authorization_never_outlives_an_hour(quorums_402: dict[str, Any]) -> None:
    """The server sets maxTimeoutSeconds; a hostile one must not get a signature valid for years."""
    required = challenge(quorums_402)
    required["accepts"] = [{**a, "maxTimeoutSeconds": 10**9} for a in required["accepts"]]
    payment = X402Payer(TEST_KEY, network="polygon").create_payment(required, now=NOW, nonce=NONCE)
    assert int(payment["payload"]["authorization"]["validBefore"]) == NOW + 3600
