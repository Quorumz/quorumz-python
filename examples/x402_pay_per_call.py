"""Pay per call in USDC with x402: no account, no API key.

    pip install "quorumz[x402]"
    export WALLET_PRIVATE_KEY=0x...   # a hot wallet holding a little USDC on Base
    python examples/x402_pay_per_call.py

The wallet needs USDC on the chosen network and no gas: the server's
facilitator submits the transfer you sign.
"""

import os

from quorumz import Quorumz, X402Payer

payer = X402Payer(
    os.environ["WALLET_PRIVATE_KEY"],
    network=["base", "polygon", "arbitrum"],  # in order of preference
    max_payment_usd=0.10,  # refuse to sign any single call above this
)
print("paying from", payer.address)

client = Quorumz(x402=payer)
page = client.events("news", country="LB", limit=2)  # 2 x $0.005

for event in page["events"]:
    print(event["title"])
    for quorum in event["quorums"]:
        print("  quorum:", quorum["headline"], [v["label"] for v in quorum["viewpoints"]])

receipt = page.get("payment", {}).get("receipt", {})
print("settled on", receipt.get("network"), "tx", receipt.get("transaction"))
