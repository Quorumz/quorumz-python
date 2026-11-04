"""LangChain tools for the Quorumz agent API.

Needs the ``langchain`` extra::

    pip install "quorumz[langchain]"

Usage::

    from quorumz import Quorumz
    from quorumz.langchain import create_tools

    tools = create_tools(Quorumz())          # key from QUORUMZ_API_KEY
    llm_with_tools = llm.bind_tools(tools)

An error the API answers (no key, no credits, rate limit, a missing id) goes
back to the model as the tool's result, so it can tell the user what to do.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

try:
    from langchain_core.tools import BaseTool, StructuredTool, ToolException
    from pydantic import BaseModel, Field
except ImportError as error:  # pragma: no cover - exercised without the extra
    raise ImportError('The LangChain tools need the langchain extra: pip install "quorumz[langchain]"') from error

from ._client import AsyncQuorumz, Quorumz
from .errors import QuorumzError

__all__ = ["create_tools"]

_COUNTRY = "ISO 3166 alpha-2 country code, for example 'LB' for Lebanon. Omit for the whole world."
_LIMIT = "How many results to return (1-50). Each result is charged, so ask only for what you need."
_CURSOR = "The next_cursor of a previous page, to read older results. Omit for the newest."


class QuorumsInput(BaseModel):
    country: str | None = Field(default=None, description=_COUNTRY)
    limit: int = Field(default=5, ge=1, le=50, description=_LIMIT + " $0.01 per quorum.")
    cursor: str | None = Field(default=None, description=_CURSOR)


class EventsInput(BaseModel):
    stream: Literal["alpha", "news"] = Field(
        default="alpha",
        description="'alpha' for early signals ahead of the wider press ($0.02 each), "
        "'news' for news articles with their quorums ($0.005 each).",
    )
    country: str | None = Field(default=None, description=_COUNTRY)
    cell: str | None = Field(
        default=None, description="Geohash of precision 3, 4 or 5 to narrow alpha to an area. Alpha only."
    )
    limit: int = Field(default=5, ge=1, le=50, description=_LIMIT)
    cursor: str | None = Field(default=None, description=_CURSOR)


class QuorumInput(BaseModel):
    quorum_id: str = Field(description="A quorum_id from a previous Quorumz result, for example 'qrm_7c1e'.")


class ArticleInput(BaseModel):
    article_id: str = Field(description="A news event id from quorumz_events(stream='news').")


class CatalogInput(BaseModel):
    pass


def _guard(call: Callable[..., Any]) -> Callable[..., Any]:
    def run(**kwargs: Any) -> Any:
        try:
            return call(**kwargs)
        except (QuorumzError, ValueError) as error:
            raise ToolException(str(error)) from error

    return run


def _aguard(call: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    async def run(**kwargs: Any) -> Any:
        try:
            return await call(**kwargs)
        except (QuorumzError, ValueError) as error:
            raise ToolException(str(error)) from error

    return run


def create_tools(
    client: Quorumz | None = None,
    *,
    async_client: AsyncQuorumz | None = None,
    include_catalog: bool = False,
) -> list[BaseTool]:
    """LangChain tools for quorums, events, one quorum and one article.

    Args:
        client: the sync client the tools call. Default: ``Quorumz()``, which
            reads ``QUORUMZ_API_KEY``.
        async_client: used when the agent runs the tools async. Without it,
            async calls run the sync client in a thread.
        include_catalog: also add a free ``quorumz_catalog`` tool.
    """
    client = client or Quorumz()
    specs: list[tuple[str, str, type[BaseModel], Callable[..., Any], Callable[..., Awaitable[Any]] | None]] = [
        (
            "quorumz_quorums",
            "Current stories about a country or the world, each split into the distinct viewpoints "
            "people hold, with how many media, social and on-the-ground posts support each viewpoint. "
            "Use it when the user asks what people are saying about a country, a conflict or a public story.",
            QuorumsInput,
            client.quorums,
            async_client.quorums if async_client else None,
        ),
        (
            "quorumz_events",
            "Geo-tagged world news: 'alpha' signals that are ahead of the wider press, or 'news' articles "
            "with the viewpoints on each. Use it for what is happening now in a country or area.",
            EventsInput,
            client.events,
            async_client.events if async_client else None,
        ),
        (
            "quorumz_quorum",
            "One story (quorum) by its quorum_id: its viewpoints, their summaries and support counts.",
            QuorumInput,
            client.quorum,
            async_client.quorum if async_client else None,
        ),
        (
            "quorumz_article",
            "One news article by its id, with the quorums and viewpoints related to it.",
            ArticleInput,
            client.article,
            async_client.article if async_client else None,
        ),
    ]
    if include_catalog:
        specs.append(
            (
                "quorumz_catalog",
                "Free: the Quorumz streams, filters, per-item prices and how to pay.",
                CatalogInput,
                client.catalog,
                async_client.catalog if async_client else None,
            )
        )
    return [
        StructuredTool.from_function(
            func=_guard(func),
            coroutine=_aguard(coroutine) if coroutine else None,
            name=name,
            description=description,
            args_schema=schema,
            handle_tool_error=True,
        )
        for name, description, schema, func, coroutine in specs
    ]
