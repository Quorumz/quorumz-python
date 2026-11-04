"""A LangChain agent that answers with Quorumz viewpoints.

    pip install "quorumz[langchain]" langchain langchain-anthropic
    export QUORUMZ_API_KEY=qz_pk_live_...
    export ANTHROPIC_API_KEY=...
    python examples/langchain_agent.py "What are people saying about Lebanon's border?"
"""

import sys

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic

from quorumz import AsyncQuorumz, Quorumz
from quorumz.langchain import create_tools

tools = create_tools(Quorumz(), async_client=AsyncQuorumz())
agent = create_agent(
    ChatAnthropic(model="claude-opus-5-5"),
    tools=tools,
    system_prompt=(
        "You answer questions about world events. Use the Quorumz tools to find the current "
        "stories and the distinct viewpoints on them, and say how well supported each one is."
    ),
)

question = sys.argv[1] if len(sys.argv) > 1 else "What are people saying about Lebanon right now?"
result = agent.invoke({"messages": [{"role": "user", "content": question}]})
print(result["messages"][-1].content)
