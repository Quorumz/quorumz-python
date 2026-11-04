"""Exceptions raised by the Quorumz clients.

Every error the API answers is an :class:`APIError`. The two you are most
likely to handle have their own class:

- :class:`PaymentRequiredError` for HTTP 401 and 402: the call needs an API
  key, credits, or an x402 payment. Its message says which and how.
- :class:`RateLimitError` for HTTP 429.

Network failures (timeouts, DNS, TLS) are raised by httpx unchanged.
"""

from __future__ import annotations

from typing import Any

KEYS_URL = "https://sense.quorumz.com/agents/keys"
DOCS_URL = "https://sense.quorumz.com/agents/docs"


class QuorumzError(Exception):
    """Base class for every error raised by this package."""


class X402Error(QuorumzError):
    """An x402 payment could not be built, so nothing was signed or sent.

    Raised before any money moves: no accepted network matches the payer,
    the asset is not the known USDC contract, or the price is above
    ``max_payment_usd``.
    """


class APIError(QuorumzError):
    """The API answered with an HTTP error status."""

    def __init__(self, message: str, *, status_code: int, body: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body


class PaymentRequiredError(APIError):
    """HTTP 401 or 402: the call needs an API key, credits, or an x402 payment.

    Attributes:
        status_code: 401 (the key was rejected) or 402 (payment required).
        reason: the server's reason, for example ``"invalid api key"``,
            ``"no_credits"``, ``"trial_over"`` or an x402 verification error.
        price_usd: what the call costs, when the server quoted it.
        payment_required: the decoded x402 ``PAYMENT-REQUIRED`` challenge
            (402 only), with its ``accepts`` list.
        keys_url: where to get an API key or buy credits.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: Any = None,
        reason: str | None = None,
        price_usd: float | None = None,
        payment_required: dict[str, Any] | None = None,
        keys_url: str = KEYS_URL,
    ) -> None:
        super().__init__(message, status_code=status_code, body=body)
        self.reason = reason
        self.price_usd = price_usd
        self.payment_required = payment_required
        self.keys_url = keys_url


class RateLimitError(APIError):
    """HTTP 429: too many requests. ``retry_after`` is in seconds, when sent."""

    def __init__(
        self, message: str, *, status_code: int = 429, body: Any = None, retry_after: float | None = None
    ) -> None:
        super().__init__(message, status_code=status_code, body=body)
        self.retry_after = retry_after


class NotFoundError(APIError):
    """HTTP 404: no quorum or article with that id. A 404 is never charged."""
