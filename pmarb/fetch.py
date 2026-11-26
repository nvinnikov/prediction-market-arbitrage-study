"""Live snapshot of every open Polymarket and Kalshi event, trimmed to the fields the study reads.
Writes data/raw/live/<UTC time>/{polymarket,kalshi}_events.json.gz. About ten minutes."""
import time

from pmarb import snapshot
from pmarb.client import FAILURES, KALSHI, POLYMARKET_GAMMA, get_json

EVENT_KEYS = ("id", "title", "negRisk", "negRiskAugmented", "endDate")
MARKET_KEYS = ("id", "question", "groupItemTitle", "outcomes", "outcomePrices", "clobTokenIds", "bestBid", "bestAsk",
               "enableOrderBook", "acceptingOrders", "closed", "active", "endDate", "feesEnabled", "feeSchedule",
               "negRiskOther")
KALSHI_EVENT_KEYS = ("event_ticker", "series_ticker", "title", "sub_title")
KALSHI_MARKET_KEYS = ("ticker", "status", "yes_sub_title", "yes_bid_dollars", "yes_ask_dollars",
                      "expected_expiration_time", "close_time")


def trim(obj, keys):
    return {k: obj.get(k) for k in keys if k in obj}


def polymarket_events(max_pages=200):
    """Open events through the keyset endpoint: offsets past a few thousand return 422."""
    events, cursor = [], ""
    for _ in range(max_pages):
        x = get_json(POLYMARKET_GAMMA + "/events/keyset?active=true&closed=false&limit=100"
                     + ("&after_cursor=" + cursor if cursor else ""))
        rows = (x or {}).get("events") or []
        events += [dict(trim(e, EVENT_KEYS), markets=[trim(m, MARKET_KEYS) for m in e.get("markets") or []])
                   for e in rows]
        cursor = (x or {}).get("next_cursor") or ""
        if not cursor or not rows:
            break
    seen = set()
    return [e for e in events if not (e["id"] in seen or seen.add(e["id"]))]


def kalshi_events(max_pages=150):
    events, cursor = [], ""
    for _ in range(max_pages):
        x = get_json(KALSHI + "/events?status=open&with_nested_markets=true&limit=200"
                     + ("&cursor=" + cursor if cursor else ""))
        if not x:
            break
        events += [dict(trim(e, KALSHI_EVENT_KEYS), markets=[trim(m, KALSHI_MARKET_KEYS) for m in e.get("markets") or []])
                   for e in x.get("events") or []]
        cursor = x.get("cursor") or ""
        if not cursor:
            break
        time.sleep(.15)
    return events


def main():
    out = snapshot.LIVE / time.strftime("%Y-%m-%dT%H%M", time.gmtime())
    p = polymarket_events()
    snapshot.save(out / "polymarket_events.json.gz", p)
    k = kalshi_events()
    snapshot.save(out / "kalshi_events.json.gz", k)
    print(out.name, "polymarket events", len(p), "kalshi events", len(k), "failed", dict(FAILURES))


if __name__ == "__main__":
    main()
