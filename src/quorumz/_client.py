"""The sync and async clients. Both share :class:`_BaseClient`, which builds
requests and turns responses into results or errors; the subclasses only do
the I/O."""

from __future__ import annotations

import base64
import binascii
import json
import os
from typing import Any, Literal, cast, overload
from urllib.parse import quote

import httpx

from ._version import __version__
from .errors import (
    DOCS_URL,
    KEYS_URL,
    APIError,
    NotFoundError,
    PaymentRequiredError,
    RateLimitError,
)
from .types import AlphaPage, Article, Catalog, NewsPage, Quorum, QuorumPage
from .x402 import X402Payer, decode_payment_required, usd

DEFAULT_BASE_URL = "https://api.quorumz.com"
DEFAULT_TIMEOUT = 30.0
API_KEY_ENV = "QUORUMZ_API_KEY"
BASE_URL_ENV = "QUORUMZ_BASE_URL"

_HOW_TO_PAY = (
    f"Get an API key at {KEYS_URL} (free trial: 100 calls over 7 days, then credits by card) and pass "
    f"Quorumz(api_key=...) or set {API_KEY_ENV}; or pay per call in USDC with x402: "
    'pip install "quorumz[x402]" and pass Quorumz(x402=X402Payer(private_key)).'
)


def _params(**values: Any) -> dict[str, str]:
    return {key: str(value) for key, value in values.items() if value is not None and value != ""}


def _path_id(value: str, what: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{what} must not be empty")
    return quote(text, safe="")


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text or None


def _server_reason(body: Any) -> str | None:
    if isinstance(body, dict):
        for key in ("error", "detail", "message"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        if body.get("detail") is not None:
            return json.dumps(body["detail"])[:300]
    if isinstance(body, str) and body.strip():
        return body.strip()[:300]
    return None


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _decode_receipt(header: str | None) -> dict[str, Any] | None:
    if not header:
        return None
    try:
        parsed = json.loads(base64.b64decode(header.strip()))
    except (binascii.Error, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


class _BaseClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str | None,
        timeout: float,
        x402: X402Payer | None,
    ) -> None:
        if api_key is None:
            api_key = os.environ.get(API_KEY_ENV)
        self.api_key: str | None = (api_key or "").strip() or None
        self.base_url = (base_url or os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.x402 = x402

    def __repr__(self) -> str:  # never the key
        key = "set" if self.api_key else "none"
        return f"{type(self).__name__}(base_url={self.base_url!r}, api_key={key}, x402={self.x402!r})"

    # -- requests -----------------------------------------------------------

    def _url(self, path: str) -> str:
        return self.base_url + path

    def _headers(self, *, with_key: bool = True) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": f"quorumz-python/{__version__}"}
        if with_key and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payment_headers(self, response: httpx.Response) -> dict[str, str] | None:
        """The headers of the paid retry, when this 402 can be paid with x402.

        The retry carries no API key: the server checks a key before a payment,
        so a key without credits would answer 402 to the paid retry too.
        """
        if response.status_code != 402 or self.x402 is None:
            return None
        challenge = decode_payment_required(response.headers.get("payment-required"), _json(response))
        if challenge is None:
            return None
        headers = self._headers(with_key=False)
        headers["PAYMENT-SIGNATURE"] = self.x402.create_payment_header(challenge)
        return headers

    # -- responses ----------------------------------------------------------

    def _result(self, response: httpx.Response, *, paid_with_x402: bool) -> Any:
        if response.is_success:
            body = _json(response)
            if not isinstance(body, dict):
                raise APIError(
                    f"Quorumz returned a non-JSON response (HTTP {response.status_code}).",
                    status_code=response.status_code,
                    body=body,
                )
            receipt = _decode_receipt(response.headers.get("payment-response"))
            if receipt is not None:
                payment = body.get("payment")
                body["payment"] = {**payment, "receipt": receipt} if isinstance(payment, dict) else {"receipt": receipt}
            return body
        raise self._error(response, paid_with_x402=paid_with_x402)

    def _error(self, response: httpx.Response, *, paid_with_x402: bool) -> APIError:
        status = response.status_code
        body = _json(response)
        reason = _server_reason(body)
        if status == 401:
            return PaymentRequiredError(
                f"Quorumz rejected the API key ({reason or 'unauthorized'}). Check the key you passed or "
                f"{API_KEY_ENV}, or get one at {KEYS_URL}.",
                status_code=status,
                body=body,
                reason=reason,
            )
        if status == 402:
            return self._payment_error(response, body, reason, paid_with_x402=paid_with_x402)
        if status == 429:
            retry_after = _retry_after(response)
            wait = f" Retry after {retry_after:g} seconds." if retry_after is not None else " Slow down and retry."
            return RateLimitError(
                f"Quorumz rate limit hit (HTTP 429).{wait}", body=body, retry_after=retry_after
            )
        if status == 404:
            return NotFoundError(
                f"Not found ({reason or 'not_found'}). A missing quorum or article is not charged.",
                status_code=status,
                body=body,
            )
        return APIError(f"Quorumz API error (HTTP {status}): {reason or response.reason_phrase}", status_code=status, body=body)

    def _payment_error(
        self, response: httpx.Response, body: Any, reason: str | None, *, paid_with_x402: bool
    ) -> PaymentRequiredError:
        challenge = decode_payment_required(response.headers.get("payment-required"), body)
        price: float | None = None
        if challenge:
            for entry in challenge.get("accepts") or []:
                if isinstance(entry, dict) and str(entry.get("amount", "")).isdigit():
                    price = usd(entry["amount"])
                    break
        if isinstance(body, dict) and isinstance(body.get("get_a_key"), str):
            keys_url = body["get_a_key"]
        else:
            keys_url = KEYS_URL
        costs = f"This call costs ${price:.6g}. " if price is not None else ""
        if paid_with_x402:
            message = (
                f"Quorumz did not accept the x402 payment ({reason or 'payment_invalid'}). {costs}"
                f"Check that the paying wallet holds enough USDC on the chosen network, or use an API key from {keys_url}."
            )
        elif self.api_key and reason in ("no_credits", "trial_over"):
            message = (
                f"This API key has no free calls or credits left ({reason}). {costs}"
                f"Add credits by card at {keys_url}, or pay per call with x402: "
                'pip install "quorumz[x402]" and pass Quorumz(x402=X402Payer(private_key)).'
            )
        else:
            message = f"Payment required. {costs}{_HOW_TO_PAY} Docs: {DOCS_URL}"
        return PaymentRequiredError(
            message,
            status_code=402,
            body=body,
            reason=reason,
            price_usd=price,
            payment_required=challenge,
            keys_url=keys_url,
        )


def _events_params(
    stream: str, country: str | None, cell: str | None, limit: int | None, cursor: str | None
) -> dict[str, str]:
    if stream not in ("alpha", "news"):
        raise ValueError('stream must be "alpha" or "news"')
    if cell and stream != "alpha":
        raise ValueError('cell filters the alpha stream only; use stream="alpha" or drop cell')
    return _params(stream=stream, country=country, cell=cell, limit=limit, cursor=cursor)


class Quorumz(_BaseClient):
    """Client for the Sense by Quorumz agent API.

    Args:
        api_key: your API key (``qz_pk_live_...``). Defaults to the
            ``QUORUMZ_API_KEY`` environment variable. Get one at
            https://sense.quorumz.com/agents/keys.
        x402: an :class:`~quorumz.x402.X402Payer` to pay calls with USDC when
            the API answers 402 (no key, or a key with no credits left).
        base_url: defaults to ``QUORUMZ_BASE_URL`` or https://api.quorumz.com.
        timeout: seconds per request.
        http_client: an ``httpx.Client`` to use instead of the client's own.

    Every paid route takes an API key or an x402 payment. Without either, a
    call that would return results raises :class:`PaymentRequiredError`.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        x402: X402Payer | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(api_key, base_url=base_url, timeout=timeout, x402=x402)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = self._url(path)
        response = self._http.get(url, params=params, headers=self._headers())
        retry = self._payment_headers(response)
        if retry is not None:
            response = self._http.get(url, params=params, headers=retry)
        return self._result(response, paid_with_x402=retry is not None)

    def catalog(self) -> Catalog:
        """The free catalog: streams, routes, per-item prices and ways to pay."""
        return cast(Catalog, self._get("/api/agent/v1"))

    def quorums(
        self, country: str | None = None, *, limit: int | None = None, cursor: str | None = None
    ) -> QuorumPage:
        """Recent quorums, newest first: stories split into viewpoints.

        Args:
            country: ISO 3166 alpha-2 code, e.g. ``"LB"``. None for the world.
            limit: quorums per page (the server caps it at 50). $0.01 each.
            cursor: the ``next_cursor`` of the previous page, for older ones.
        """
        return cast(QuorumPage, self._get("/api/agent/v1/quorums", _params(country=country, limit=limit, cursor=cursor)))

    @overload
    def events(
        self,
        stream: Literal["alpha"] = ...,
        *,
        country: str | None = ...,
        cell: str | None = ...,
        limit: int | None = ...,
        cursor: str | None = ...,
    ) -> AlphaPage: ...
    @overload
    def events(
        self,
        stream: Literal["news"],
        *,
        country: str | None = ...,
        cell: None = ...,
        limit: int | None = ...,
        cursor: str | None = ...,
    ) -> NewsPage: ...
    def events(
        self,
        stream: str = "alpha",
        *,
        country: str | None = None,
        cell: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AlphaPage | NewsPage:
        """Alpha signals or news articles, newest first.

        Args:
            stream: ``"alpha"`` ($0.02 per event) or ``"news"`` ($0.005 per event).
            country: ISO 3166 alpha-2 code, e.g. ``"LB"``.
            cell: a geohash of precision 3, 4 or 5 (alpha only).
            limit: events per page (the server caps it at 50).
            cursor: the ``next_cursor`` of the previous page.
        """
        params = _events_params(stream, country, cell, limit, cursor)
        return cast("AlphaPage | NewsPage", self._get("/api/agent/v1/events", params))

    def quorum(self, quorum_id: str) -> Quorum:
        """One quorum and its viewpoints ($0.01). Raises NotFoundError (not charged) for a missing id."""
        return cast(Quorum, self._get(f"/api/agent/v1/quorums/{_path_id(quorum_id, 'quorum_id')}"))

    def article(self, article_id: str) -> Article:
        """One news article and the quorums on it ($0.005). Raises NotFoundError (not charged) for a missing id."""
        return cast(Article, self._get(f"/api/agent/v1/articles/{_path_id(article_id, 'article_id')}"))

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Quorumz:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class AsyncQuorumz(_BaseClient):
    """Async client for the Sense by Quorumz agent API. Same arguments and
    methods as :class:`Quorumz`; the methods are coroutines."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        x402: X402Payer | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key, base_url=base_url, timeout=timeout, x402=x402)
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = self._url(path)
        response = await self._http.get(url, params=params, headers=self._headers())
        retry = self._payment_headers(response)
        if retry is not None:
            response = await self._http.get(url, params=params, headers=retry)
        return self._result(response, paid_with_x402=retry is not None)

    async def catalog(self) -> Catalog:
        """The free catalog: streams, routes, per-item prices and ways to pay."""
        return cast(Catalog, await self._get("/api/agent/v1"))

    async def quorums(
        self, country: str | None = None, *, limit: int | None = None, cursor: str | None = None
    ) -> QuorumPage:
        """Recent quorums, newest first. See :meth:`Quorumz.quorums`."""
        params = _params(country=country, limit=limit, cursor=cursor)
        return cast(QuorumPage, await self._get("/api/agent/v1/quorums", params))

    @overload
    async def events(
        self,
        stream: Literal["alpha"] = ...,
        *,
        country: str | None = ...,
        cell: str | None = ...,
        limit: int | None = ...,
        cursor: str | None = ...,
    ) -> AlphaPage: ...
    @overload
    async def events(
        self,
        stream: Literal["news"],
        *,
        country: str | None = ...,
        cell: None = ...,
        limit: int | None = ...,
        cursor: str | None = ...,
    ) -> NewsPage: ...
    async def events(
        self,
        stream: str = "alpha",
        *,
        country: str | None = None,
        cell: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AlphaPage | NewsPage:
        """Alpha signals or news articles, newest first. See :meth:`Quorumz.events`."""
        params = _events_params(stream, country, cell, limit, cursor)
        return cast("AlphaPage | NewsPage", await self._get("/api/agent/v1/events", params))

    async def quorum(self, quorum_id: str) -> Quorum:
        """One quorum and its viewpoints ($0.01)."""
        return cast(Quorum, await self._get(f"/api/agent/v1/quorums/{_path_id(quorum_id, 'quorum_id')}"))

    async def article(self, article_id: str) -> Article:
        """One news article and the quorums on it ($0.005)."""
        return cast(Article, await self._get(f"/api/agent/v1/articles/{_path_id(article_id, 'article_id')}"))

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncQuorumz:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
