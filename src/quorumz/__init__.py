"""Python client for the Sense by Quorumz agent API.

Geo-tagged news where each story is a quorum: the distinct viewpoints being
expressed about it, with the media, social and on-the-ground posts behind
each one. Docs: https://sense.quorumz.com/agents/docs
"""

from ._client import AsyncQuorumz, Quorumz
from ._version import __version__
from .errors import (
    APIError,
    NotFoundError,
    PaymentRequiredError,
    QuorumzError,
    RateLimitError,
    X402Error,
)
from .types import (
    AlphaEvent,
    AlphaPage,
    Article,
    Catalog,
    NewsEvent,
    NewsPage,
    PaymentInfo,
    Quorum,
    QuorumPage,
    SupportBySource,
    Viewpoint,
)
from .x402 import X402Payer

__all__ = [
    "APIError",
    "AlphaEvent",
    "AlphaPage",
    "Article",
    "AsyncQuorumz",
    "Catalog",
    "NewsEvent",
    "NewsPage",
    "NotFoundError",
    "PaymentInfo",
    "PaymentRequiredError",
    "Quorum",
    "QuorumPage",
    "Quorumz",
    "QuorumzError",
    "RateLimitError",
    "SupportBySource",
    "Viewpoint",
    "X402Error",
    "X402Payer",
    "__version__",
]
