"""Read the free catalog, then the current quorums for a country.

    export QUORUMZ_API_KEY=qz_pk_live_...   # https://sense.quorumz.com/agents/keys
    python examples/quickstart.py LB
"""

import sys

from quorumz import PaymentRequiredError, Quorumz

country = sys.argv[1] if len(sys.argv) > 1 else "LB"

with Quorumz() as client:
    catalog = client.catalog()  # free
    for stream in catalog["streams"]:
        print(f"{stream['name']:7} ${stream['unit_price_usd']} per item  {stream['description']}")

    try:
        page = client.quorums(country, limit=3)
    except PaymentRequiredError as error:
        sys.exit(str(error))

    for quorum in page["quorums"]:
        print(f"\n{quorum['headline']}  ({quorum['support_count']} posts)")
        for view in quorum["viewpoints"]:
            src = view["support_by_source"]
            print(
                f"  - {view['label']}: {view['support_count']} "
                f"(media {src['media']}, social {src['socials']}, iWitness {src['iwitness']})"
            )
    print("\npayment:", page.get("payment", {}).get("plan"), page.get("payment", {}).get("trial"))
