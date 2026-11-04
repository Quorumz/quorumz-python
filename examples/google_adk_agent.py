"""A Google ADK agent with Quorumz as function tools.

    pip install quorumz google-adk
    export QUORUMZ_API_KEY=qz_pk_live_...
    export GOOGLE_API_KEY=...

Put this file in an ADK agent folder as agent.py (next to an __init__.py
containing `from . import agent`), then run `adk run <folder>` or `adk web`.

ADK turns a plain Python function into a tool: its name, type hints and
docstring become the tool's schema.
"""

from google.adk.agents import Agent

from quorumz import PaymentRequiredError, Quorumz

qz = Quorumz()


def quorumz_viewpoints(country: str, limit: int = 5) -> dict:
    """What people are saying about a country: the current stories, each split
    into the distinct viewpoints held about it, with how many media, social and
    on-the-ground posts support each viewpoint.

    Args:
        country: ISO 3166 alpha-2 country code, for example "LB" for Lebanon.
        limit: how many stories to return (each one is charged $0.01).
    """
    try:
        return dict(qz.quorums(country, limit=limit))
    except PaymentRequiredError as error:
        return {"error": str(error)}


def quorumz_alpha(country: str, limit: int = 5) -> dict:
    """Early signals about a country that are ahead of the wider press.

    Args:
        country: ISO 3166 alpha-2 country code.
        limit: how many signals to return (each one is charged $0.02).
    """
    try:
        return dict(qz.events("alpha", country=country, limit=limit))
    except PaymentRequiredError as error:
        return {"error": str(error)}


root_agent = Agent(
    name="news_analyst",
    model="gemini-2.5-flash",
    description="Answers questions about world events with the viewpoints behind each story.",
    instruction=(
        "Use quorumz_viewpoints to find the positions people hold on a story and how well each is "
        "supported, and quorumz_alpha for early signals. Report the viewpoints, not one headline."
    ),
    tools=[quorumz_viewpoints, quorumz_alpha],
)
