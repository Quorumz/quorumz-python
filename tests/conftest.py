from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://api.quorumz.com"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read a developer's real key or base URL."""
    monkeypatch.delenv("QUORUMZ_API_KEY", raising=False)
    monkeypatch.delenv("QUORUMZ_BASE_URL", raising=False)


@pytest.fixture
def quorums_402() -> dict[str, Any]:
    """The 402 answered live by /api/agent/v1/quorums?country=LB&limit=2."""
    return load_fixture("quorums_402.json")


QUORUM: dict[str, Any] = {
    "quorum_id": "qrm_7c1e",
    "headline": "Border crossing closed after flood damage",
    "summary": "Two readings of the closure.",
    "category": "infrastructure",
    "countries": ["LB"],
    "support_count": 55,
    "confidence": 0.68,
    "is_alpha": True,
    "updated_at": "2026-10-27T09:40:00Z",
    "viewpoints": [
        {
            "viewpoint_id": "opn_8f2c",
            "label": "The closure is temporary",
            "summary": "Officials say it reopens once repairs finish.",
            "support_count": 38,
            "support_by_source": {"media": 11, "socials": 25, "iwitness": 2},
            "confidence": 0.74,
            "is_alpha": False,
        }
    ],
    "article_url": "https://sense.quorumz.com/quorum/qrm_7c1e",
}
