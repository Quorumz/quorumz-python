"""Typed shapes of the API's JSON responses.

They are ``TypedDict``s: the results are the plain dicts the API returns, so
a field the API adds later is still there, and ``json.dumps(result)`` works.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class SupportBySource(TypedDict):
    """How many posts support a viewpoint, by kind of source."""

    media: int
    socials: int
    iwitness: int


class Viewpoint(TypedDict):
    """One position people hold about a story."""

    viewpoint_id: str
    label: str
    summary: str | None
    support_count: int
    support_by_source: SupportBySource
    confidence: float | None  # 0-1: how well sourced the viewpoint is
    is_alpha: bool


class PaymentInfo(TypedDict, total=False):
    """How a call was paid. Attached by the API to every paid response."""

    status: str  # "enforced" or "preview"
    scheme: str
    network: str
    networks: list[str]
    pay_to: str
    asset: str
    facilitator: str
    prices_usd: dict[str, float]
    charged_events: int
    settled: bool  # True when an x402 payment settled on-chain
    plan: str  # API key calls: "trial", "credits" or "internal"
    trial: dict[str, Any]  # trial calls left, when paid by a trial key
    credits: dict[str, Any]  # charged_usd and balance_usd, when paid by credits
    receipt: dict[str, Any]  # the decoded PAYMENT-RESPONSE header (x402)


class _QuorumFields(TypedDict):
    quorum_id: str
    headline: str
    summary: str | None
    category: str | None
    countries: list[str]
    support_count: int
    confidence: float | None
    is_alpha: bool
    updated_at: str | None
    viewpoints: list[Viewpoint]
    article_url: str


class Quorum(_QuorumFields, total=False):
    """One story split into the viewpoints being expressed about it."""

    payment: PaymentInfo  # only on the result of ``quorum(id)``


class AlphaEvent(TypedDict):
    """A signal ahead of the wider press."""

    id: str
    type: Literal["alpha.created"]
    cursor: str
    country: str | None
    lat: float | None
    lon: float | None
    alpha_kind: str | None
    alpha_score: float | None
    rationale: str | None
    detected_at: str | None
    quorum: Quorum | None  # the quorum behind the story, when one exists


class NewsEvent(TypedDict):
    """A news article with the quorums related to it."""

    id: str
    type: Literal["news.created"]
    cursor: str
    title: str
    summary: str | None
    countries: list[str]
    updated_at: str | None
    quorums: list[Quorum]
    article_url: str


class _ArticleFields(TypedDict):
    article_id: str
    title: str
    summary: str | None
    category: str | None
    countries: list[str]
    updated_at: str | None
    quorums: list[Quorum]
    article_url: str


class Article(_ArticleFields, total=False):
    """One news article and the quorums on it."""

    payment: PaymentInfo


class _QuorumPageFields(TypedDict):
    stream: Literal["quorum"]
    filter: dict[str, Any]
    quorums: list[Quorum]
    next_cursor: str | None  # pass back as ``cursor`` for older results


class QuorumPage(_QuorumPageFields, total=False):
    """A page of ``quorums()``."""

    payment: PaymentInfo


class _AlphaPageFields(TypedDict):
    stream: Literal["alpha"]
    filter: dict[str, Any]
    events: list[AlphaEvent]
    next_cursor: str | None
    charged_events: int


class AlphaPage(_AlphaPageFields, total=False):
    """A page of ``events(stream="alpha")``."""

    payment: PaymentInfo


class _NewsPageFields(TypedDict):
    stream: Literal["news"]
    filter: dict[str, Any]
    events: list[NewsEvent]
    next_cursor: str | None
    charged_events: int


class NewsPage(_NewsPageFields, total=False):
    """A page of ``events(stream="news")``."""

    payment: PaymentInfo


class Catalog(TypedDict, total=False):
    """The free catalog: streams, routes, prices and the ways to pay."""

    service: str
    differentiator: str
    streams: list[dict[str, Any]]
    routes: list[dict[str, Any]]
    filters: list[str]
    access: list[dict[str, Any]]
    docs: str
    landing: str
    payment: dict[str, Any]


Stream = Literal["alpha", "news"]
