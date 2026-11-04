# quorumz

Python client for the [Sense by Quorumz](https://sense.quorumz.com/agents) agent API.

Quorumz is geo-tagged world news in which each story is a **quorum**: the distinct viewpoints being expressed about it. Each viewpoint carries a summary and a `support_count`, split into media, social and on-the-ground (iWitness) posts. **Alpha** events flag stories that are ahead of the wider press. **News** events are articles, each with its quorums.

```bash
pip install quorumz                 # sync + async clients (httpx only)
pip install "quorumz[x402]"         # + pay per call in USDC (eth-account)
pip install "quorumz[langchain]"    # + LangChain tools
```

Python 3.10+.

## Paying for calls

The catalog is free. Every other route is paid per item returned, and an empty page is free. You can pay in two ways.

**1. An API key, paid by card.** Sign up at **https://sense.quorumz.com/agents/keys**. Sign-in is by email, and no card is needed for the trial. The key comes with a free 7-day trial of 100 calls. After that, calls are paid from credits you buy by card or PayPal on the same page. Pass the key as `Quorumz(api_key=...)` or set the `QUORUMZ_API_KEY` environment variable. The client sends it as `Authorization: Bearer <key>`.

**2. x402, in USDC.** No account is needed. A call that is not paid answers HTTP 402 with an x402 challenge. With an `X402Payer`, the client signs an exact USDC payment (an EIP-3009 `transferWithAuthorization`) on Base, Polygon or Arbitrum and retries the call once. The wallet needs USDC but no gas, because the facilitator submits the transfer. Use a dedicated hot wallet that holds only what you mean to spend.

| Route | Method | Price |
|---|---|---|
| `GET /api/agent/v1` | `catalog()` | free |
| `GET /api/agent/v1/quorums` | `quorums()` | $0.01 per quorum |
| `GET /api/agent/v1/quorums/{id}` | `quorum(id)` | $0.01 |
| `GET /api/agent/v1/events?stream=alpha` | `events("alpha")` | $0.02 per event |
| `GET /api/agent/v1/events?stream=news` | `events("news")` | $0.005 per event |
| `GET /api/agent/v1/articles/{id}` | `article(id)` | $0.005 |

A missing quorum or article returns 404 and is not charged.

## Examples

### What are people saying about Lebanon?

```python
from quorumz import Quorumz

client = Quorumz()  # reads QUORUMZ_API_KEY

page = client.quorums("LB", limit=3)
for quorum in page["quorums"]:
    print(quorum["headline"])
    for view in quorum["viewpoints"]:
        src = view["support_by_source"]
        print(f"  {view['label']}: {view['support_count']} posts "
              f"(media {src['media']}, social {src['socials']}, iWitness {src['iwitness']})")
```

### Page through alpha signals

```python
cursor = None
for _ in range(3):  # each page is charged, so cap the pages
    page = client.events("alpha", country="UA", limit=10, cursor=cursor)
    for event in page["events"]:
        print(event["detected_at"], event["alpha_kind"], event["rationale"])
    cursor = page["next_cursor"]
    if not cursor:
        break
```

`cell=` narrows alpha to a geohash of precision 3 to 5. For example, `cell="sv8s"` is roughly 40 km by 20 km.

### Pay per call with x402

```python
import os
from quorumz import Quorumz, X402Payer

payer = X402Payer(os.environ["WALLET_PRIVATE_KEY"], network="base", max_payment_usd=0.25)
client = Quorumz(x402=payer)

page = client.events("news", country="IL", limit=5)
print(page["payment"]["receipt"]["transaction"])  # the settlement transaction
```

`network` takes `"base"`, `"polygon"` or `"arbitrum"`, or a list in order of preference. The default is whichever the server lists first. Before anything is signed, the payer checks three things:

- the asset is the known USDC contract for that network;
- the EIP-712 domain is pinned to "USD Coin", version "2", the chain id and the USDC contract;
- the price is at most `max_payment_usd` (default $1.00).

If you also pass an API key, the key is tried first. x402 pays only when the key has no free calls or credits left.

## Async

```python
import asyncio
from quorumz import AsyncQuorumz

async def main():
    async with AsyncQuorumz() as client:
        page = await client.quorums("LB", limit=3)
        print([q["headline"] for q in page["quorums"]])

asyncio.run(main())
```

## Errors

```python
from quorumz import PaymentRequiredError, RateLimitError, NotFoundError

try:
    client.quorums("LB")
except PaymentRequiredError as e:   # 401 bad key, or 402 payment needed
    print(e)                        # says how to get a key or pay
    print(e.reason, e.price_usd, e.keys_url)
except RateLimitError as e:         # 429
    print("retry after", e.retry_after)
except NotFoundError:               # 404, not charged
    ...
```

All of these are subclasses of `quorumz.APIError` (`status_code`, `body`), which is itself a `quorumz.QuorumzError`. `X402Error` means a payment could not be built, so nothing was signed or sent. Network failures are raised by httpx.

## LangChain

```python
from quorumz import Quorumz
from quorumz.langchain import create_tools

tools = create_tools(Quorumz())   # quorumz_quorums, quorumz_events, quorumz_quorum, quorumz_article
agent_llm = llm.bind_tools(tools)
```

Payment and rate-limit errors are returned to the model as the tool result, so the agent can tell its user how to get a key.

## Google ADK

ADK wraps a plain Python function as a tool:

```python
from google.adk.agents import Agent
from quorumz import Quorumz

qz = Quorumz()

def quorumz_viewpoints(country: str) -> dict:
    """What people are saying about a country: current stories, each split into
    viewpoints with how many media, social and on-the-ground posts support each.

    Args:
        country: ISO 3166 alpha-2 code, for example "LB".
    """
    return dict(qz.quorums(country, limit=5))

root_agent = Agent(
    name="news_analyst",
    model="gemini-2.5-flash",
    instruction="Answer questions about world events with quorumz_viewpoints.",
    tools=[quorumz_viewpoints],
)
```

The [`examples/`](examples) folder has runnable scripts for all of the above.

## Links

- Agent API docs: https://sense.quorumz.com/agents/docs
- Get an API key: https://sense.quorumz.com/agents/keys
- OpenAPI: https://api.quorumz.com/openapi.json
- x402 discovery: https://api.quorumz.com/.well-known/x402
- Machine summary: https://sense.quorumz.com/llms.txt
- x402 protocol: https://docs.x402.org
- Support: support@quorumz.com

## License

MIT
