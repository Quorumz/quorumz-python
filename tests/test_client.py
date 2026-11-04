from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
import respx

from quorumz import (
    APIError,
    AsyncQuorumz,
    NotFoundError,
    PaymentRequiredError,
    Quorumz,
    RateLimitError,
)

from .conftest import BASE, QUORUM, load_fixture

QUORUMS = f"{BASE}/api/agent/v1/quorums"
EVENTS = f"{BASE}/api/agent/v1/events"


def page(next_cursor: str | None = "c2") -> dict[str, Any]:
    return {"stream": "quorum", "filter": {"country": "LB"}, "quorums": [QUORUM], "next_cursor": next_cursor}


# -- the API key ---------------------------------------------------------------


@respx.mock
def test_key_from_argument_is_sent_as_bearer() -> None:
    route = respx.get(QUORUMS).mock(return_value=httpx.Response(200, json=page()))
    Quorumz(api_key="qz_pk_live_arg").quorums("LB")
    assert route.calls.last.request.headers["Authorization"] == "Bearer qz_pk_live_arg"


@respx.mock
def test_key_from_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUORUMZ_API_KEY", "qz_pk_live_env")
    route = respx.get(QUORUMS).mock(return_value=httpx.Response(200, json=page()))
    Quorumz().quorums("LB")
    assert route.calls.last.request.headers["Authorization"] == "Bearer qz_pk_live_env"


@respx.mock
def test_argument_beats_env_and_no_key_sends_no_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUORUMZ_API_KEY", "qz_pk_live_env")
    route = respx.get(QUORUMS).mock(return_value=httpx.Response(200, json=page()))
    Quorumz(api_key="qz_pk_live_arg").quorums()
    assert route.calls.last.request.headers["Authorization"] == "Bearer qz_pk_live_arg"
    Quorumz(api_key="").quorums()  # an explicit empty key opts out of the env var
    assert "Authorization" not in route.calls.last.request.headers


def test_repr_never_shows_the_key() -> None:
    assert "qz_pk_live_secret" not in repr(Quorumz(api_key="qz_pk_live_secret"))


# -- pagination and parameters -----------------------------------------------------


@respx.mock
def test_quorums_pagination_cursor_round_trip() -> None:
    route = respx.get(QUORUMS).mock(
        side_effect=[httpx.Response(200, json=page("c_page2")), httpx.Response(200, json=page(None))]
    )
    client = Quorumz(api_key="k")
    first = client.quorums("LB", limit=1)
    assert first["next_cursor"] == "c_page2"
    assert first["quorums"][0]["viewpoints"][0]["support_by_source"]["socials"] == 25
    second = client.quorums("LB", limit=1, cursor=first["next_cursor"])
    assert second["next_cursor"] is None
    first_params = route.calls[0].request.url.params
    second_params = route.calls[1].request.url.params
    assert dict(first_params) == {"country": "LB", "limit": "1"}
    assert dict(second_params) == {"country": "LB", "limit": "1", "cursor": "c_page2"}


@respx.mock
def test_events_sends_stream_filters_and_cursor() -> None:
    body = {"stream": "alpha", "filter": {}, "events": [], "next_cursor": None, "charged_events": 0}
    route = respx.get(EVENTS).mock(return_value=httpx.Response(200, json=body))
    Quorumz(api_key="k").events("alpha", country="LB", cell="sv8s", limit=3, cursor="c1")
    assert dict(route.calls.last.request.url.params) == {
        "stream": "alpha", "country": "LB", "cell": "sv8s", "limit": "3", "cursor": "c1",
    }
    Quorumz(api_key="k").events("news")
    assert dict(route.calls.last.request.url.params) == {"stream": "news"}


def test_events_rejects_bad_stream_and_news_cell() -> None:
    client = Quorumz(api_key="k")
    with pytest.raises(ValueError, match="alpha"):
        client.events("tweets")  # type: ignore[call-overload]
    with pytest.raises(ValueError, match="alpha stream only"):
        client.events("news", cell="sv8s")  # type: ignore[call-overload]


@respx.mock
def test_ids_are_path_escaped() -> None:
    route = respx.get(url__startswith=f"{BASE}/api/agent/v1/").mock(return_value=httpx.Response(200, json=QUORUM))
    client = Quorumz(api_key="k")
    client.quorum("qrm_7c1e")
    assert route.calls.last.request.url.raw_path == b"/api/agent/v1/quorums/qrm_7c1e"
    client.article("a/b?c")
    assert route.calls.last.request.url.raw_path == b"/api/agent/v1/articles/a%2Fb%3Fc"
    with pytest.raises(ValueError):
        client.quorum(" ")


@respx.mock
def test_catalog_is_free_and_typed() -> None:
    respx.get(f"{BASE}/api/agent/v1").mock(return_value=httpx.Response(200, json=load_fixture("catalog.json")))
    catalog = Quorumz().catalog()
    assert {s["name"] for s in catalog["streams"]} == {"quorum", "alpha", "news"}
    assert catalog["payment"]["status"] == "enforced"


@respx.mock
def test_base_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUORUMZ_BASE_URL", "https://api-dev.example.com/")
    route = respx.get("https://api-dev.example.com/api/agent/v1").mock(return_value=httpx.Response(200, json={}))
    Quorumz().catalog()
    assert route.called


# -- error mapping ---------------------------------------------------------------


@respx.mock
def test_402_without_key_explains_both_ways_to_pay(quorums_402: dict[str, Any]) -> None:
    respx.get(QUORUMS).mock(
        return_value=httpx.Response(402, json=quorums_402["body"], headers=quorums_402["headers"])
    )
    with pytest.raises(PaymentRequiredError) as caught:
        Quorumz().quorums("LB", limit=2)
    error = caught.value
    assert error.status_code == 402
    assert error.price_usd == pytest.approx(0.02)
    assert error.payment_required is not None and len(error.payment_required["accepts"]) == 3
    message = str(error)
    assert "https://sense.quorumz.com/agents/keys" in message
    assert "QUORUMZ_API_KEY" in message
    assert "quorumz[x402]" in message
    assert "$0.02" in message


@respx.mock
def test_402_for_a_key_without_credits(quorums_402: dict[str, Any]) -> None:
    body = {**quorums_402["body"], "error": "no_credits", "get_a_key": "https://sense.quorumz.com/agents/keys"}
    respx.get(QUORUMS).mock(return_value=httpx.Response(402, json=body))
    with pytest.raises(PaymentRequiredError) as caught:
        Quorumz(api_key="k").quorums()
    assert caught.value.reason == "no_credits"
    assert "no free calls or credits left" in str(caught.value)
    assert "Add credits by card" in str(caught.value)


@respx.mock
def test_401_invalid_key() -> None:
    respx.get(QUORUMS).mock(
        return_value=httpx.Response(
            401, json={"error": "invalid api key", "get_a_key": "https://sense.quorumz.com/agents/keys"}
        )
    )
    with pytest.raises(PaymentRequiredError) as caught:
        Quorumz(api_key="bad").quorums()
    assert caught.value.status_code == 401
    assert caught.value.reason == "invalid api key"
    assert "rejected the API key" in str(caught.value)
    assert "https://sense.quorumz.com/agents/keys" in str(caught.value)


@respx.mock
def test_429_rate_limit_with_retry_after() -> None:
    respx.get(QUORUMS).mock(
        return_value=httpx.Response(429, json={"error": "rate_limited"}, headers={"Retry-After": "12"})
    )
    with pytest.raises(RateLimitError) as caught:
        Quorumz(api_key="k").quorums()
    assert caught.value.status_code == 429
    assert caught.value.retry_after == 12
    assert "Retry after 12 seconds" in str(caught.value)


@respx.mock
def test_404_and_other_errors() -> None:
    respx.get(f"{BASE}/api/agent/v1/quorums/missing").mock(
        return_value=httpx.Response(404, json={"error": "not_found"})
    )
    respx.get(EVENTS).mock(return_value=httpx.Response(400, json={"error": "cell must be a geohash"}))
    respx.get(QUORUMS).mock(return_value=httpx.Response(502, text="Bad gateway"))
    client = Quorumz(api_key="k")
    with pytest.raises(NotFoundError):
        client.quorum("missing")
    with pytest.raises(APIError, match="cell must be a geohash") as bad:
        client.events(cell="zz")
    assert bad.value.status_code == 400
    with pytest.raises(APIError) as gateway:
        client.quorums()
    assert gateway.value.status_code == 502


# -- async ---------------------------------------------------------------------


@respx.mock
def test_async_client_sends_key_and_maps_errors(quorums_402: dict[str, Any]) -> None:
    route = respx.get(QUORUMS).mock(
        side_effect=[
            httpx.Response(200, json=page("c_next")),
            httpx.Response(402, json=quorums_402["body"], headers=quorums_402["headers"]),
        ]
    )

    async def run() -> None:
        async with AsyncQuorumz(api_key="qz_pk_live_async") as client:
            result = await client.quorums("LB", limit=1)
            assert result["next_cursor"] == "c_next"
            with pytest.raises(PaymentRequiredError):
                await client.quorums("LB", cursor="c_next")

    asyncio.run(run())
    assert route.calls[0].request.headers["Authorization"] == "Bearer qz_pk_live_async"
    assert route.calls[1].request.url.params["cursor"] == "c_next"
