from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
import respx

pytest.importorskip("langchain_core")

from quorumz import AsyncQuorumz, Quorumz  # noqa: E402
from quorumz.langchain import create_tools  # noqa: E402

from .conftest import BASE, QUORUM  # noqa: E402


def test_tools_have_names_and_schemas() -> None:
    tools = {tool.name: tool for tool in create_tools(Quorumz(api_key="k"), include_catalog=True)}
    assert set(tools) == {"quorumz_quorums", "quorumz_events", "quorumz_quorum", "quorumz_article", "quorumz_catalog"}
    assert set(tools["quorumz_events"].args) == {"stream", "country", "cell", "limit", "cursor"}
    assert "viewpoint" in tools["quorumz_quorums"].description


@respx.mock
def test_tool_calls_the_api() -> None:
    page = {"stream": "quorum", "filter": {"country": "LB"}, "quorums": [QUORUM], "next_cursor": None}
    route = respx.get(f"{BASE}/api/agent/v1/quorums").mock(return_value=httpx.Response(200, json=page))
    tools = {tool.name: tool for tool in create_tools(Quorumz(api_key="k"))}
    result: Any = tools["quorumz_quorums"].invoke({"country": "LB", "limit": 2})
    assert result["quorums"][0]["quorum_id"] == "qrm_7c1e"
    assert dict(route.calls.last.request.url.params) == {"country": "LB", "limit": "2"}


@respx.mock
def test_payment_errors_go_back_to_the_model() -> None:
    respx.get(f"{BASE}/api/agent/v1/events").mock(
        return_value=httpx.Response(402, json={"x402Version": 2, "accepts": [], "error": "x"})
    )
    tools = {tool.name: tool for tool in create_tools(Quorumz())}
    message = tools["quorumz_events"].invoke({"stream": "alpha", "country": "LB"})
    assert "https://sense.quorumz.com/agents/keys" in message


@respx.mock
def test_async_tool_uses_the_async_client() -> None:
    page = {"stream": "news", "filter": {}, "events": [], "next_cursor": None, "charged_events": 0}
    route = respx.get(f"{BASE}/api/agent/v1/events").mock(return_value=httpx.Response(200, json=page))
    tools = {t.name: t for t in create_tools(Quorumz(api_key="k"), async_client=AsyncQuorumz(api_key="k"))}
    result = asyncio.run(tools["quorumz_events"].ainvoke({"stream": "news"}))
    assert result["stream"] == "news"
    assert route.calls.last.request.url.params["stream"] == "news"
