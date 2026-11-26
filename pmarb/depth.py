"""How much can be sold on the crypto level markets near the quoted price, live.

python3 -m pmarb.depth [--snapshot NAME]
For each market priced 5c-95c: the spread, and the dollars of NO that selling YES at most 1c below the best bid
would buy. The snapshot only lists the markets; prices and depth come from books fetched now and saved next to the
snapshot as depth_<time>.json.gz.
"""
import argparse
import re
import statistics
from datetime import datetime, timezone

from pmarb import snapshot
from pmarb.forks import tokens

KINDS = (("above on a date", r"^(Bitcoin|Ethereum) above ___ on"), ("hit in a period", r"^What price will (Bitcoin|Ethereum) hit"))


def measure(events, books, pattern):
    spreads, depth = [], []
    for e in events:
        if not re.match(pattern, e["title"]):
            continue
        for m in e["markets"]:
            if not (m.get("acceptingOrders") and not m.get("closed") and m.get("active")):
                continue
            bids, asks = books.bids(tokens(m)[0]), books.asks(tokens(m)[0])
            if not bids or not asks or not .05 <= (bids[0][0] + asks[0][0]) / 2 <= .95:
                continue
            best = bids[0][0]
            spreads.append(asks[0][0] - best)
            depth.append(sum(size * (1 - p) for p, size in bids if p >= best - .01))
    return sorted(spreads), sorted(depth)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot")
    path = snapshot.resolve(ap.parse_args(argv).snapshot)
    events = snapshot.load(path / "polymarket_events.json.gz")
    books = snapshot.Books(path / ("depth_%s.json.gz" % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")), live=True)
    for name, pattern in KINDS:
        sp, dep = measure(events, books, pattern)
        if sp:
            print("%-16s markets %d, spread median %.3f p75 %.3f | NO dollars within 1c of the best bid: median $%.0f p75 $%.0f"
                  % (name, len(sp), statistics.median(sp), sp[int(.75 * len(sp))], statistics.median(dep), dep[int(.75 * len(dep))]))
    books.save()


if __name__ == "__main__":
    main()
