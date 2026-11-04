"""Page through alpha signals (or news) with next_cursor.

    export QUORUMZ_API_KEY=qz_pk_live_...
    python examples/paginate_events.py UA alpha
"""

import sys

from quorumz import Quorumz

country = sys.argv[1] if len(sys.argv) > 1 else "UA"
stream = sys.argv[2] if len(sys.argv) > 2 else "alpha"
MAX_PAGES = 3  # every page with results is charged

client = Quorumz()
cursor = None
for _ in range(MAX_PAGES):
    page = client.events(stream, country=country, limit=10, cursor=cursor)  # type: ignore[call-overload]
    for event in page["events"]:
        if stream == "alpha":
            print(event["detected_at"], event["alpha_kind"], event["rationale"])
        else:
            print(event["updated_at"], event["title"])
    cursor = page["next_cursor"]
    if not cursor:
        break
