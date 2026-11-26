"""Internal forks on Polymarket: baskets of outcomes that pay at least what they cost whatever happens.

python3 -m pmarb.forks [--snapshot NAME] [--live-books]
Candidates come from the best bid and ask in the snapshot; a candidate counts only if it still pays after fees when
the real order books are walked. With --live-books the books are fetched now and saved next to the snapshot.
"""
import argparse
import collections
import json
from datetime import datetime, timezone

from pmarb import parse, snapshot
from pmarb.book import walk
from pmarb.client import FAILURES
from pmarb.fees import polymarket_fee


def tradable(m):
    return bool(m.get("enableOrderBook") and m.get("acceptingOrders") and not m.get("closed") and m.get("active"))


def num(v):
    return float(v) if v not in (None, "") else None


def tokens(m):
    """Token ids: [YES, NO]."""
    return json.loads(m["clobTokenIds"])


def fee_of(m):
    return lambda p: polymarket_fee(m, p)


def is_complete_list(e, tradable_markets):
    """Buying every YES pays 1 only if exactly one listed outcome wins. Not so when the event keeps a placeholder or
    'Other' outcome (augmented neg-risk events), or when a market of the event is already closed: a closed winner
    leaves the remaining markets worthless (seen on a daily temperature market)."""
    return (len(tradable_markets) == len(e["markets"]) and not e.get("negRiskAugmented")
            and not any(m.get("negRiskOther") for m in tradable_markets))


def exclusive(events, books):
    """Mutually exclusive outcome lists (neg-risk events). Sell all: buy every NO when the YES bids add up to more
    than 1; the basket pays n - 1. Buy all: buy every YES of a complete list when the asks add up to less than 1."""
    found, stats = [], collections.Counter()
    for e in events:
        ms = [m for m in e["markets"] if tradable(m)]
        if not e.get("negRisk") or len(ms) < 2:
            continue
        stats["events"] += 1
        legs = [m for m in ms if (num(m.get("bestBid")) or 0) > 0]
        bids = sum(num(m["bestBid"]) for m in legs)
        if bids > 1:
            stats["exclusive candidates"] += 1
            r = walk([(books.asks(tokens(m)[1]), fee_of(m)) for m in legs], payout=len(legs) - 1)
            add(found, "sell all", e, r, "%d legs, YES bids add up to %.3f" % (len(legs), bids), e.get("endDate"))
        asks = [num(m.get("bestAsk")) for m in ms]
        if all(asks) and sum(asks) < 1:
            if not is_complete_list(e, ms):
                stats["incomplete lists skipped"] += 1
                continue
            stats["exclusive candidates"] += 1
            r = walk([(books.asks(tokens(m)[0]), fee_of(m)) for m in ms], payout=1)
            add(found, "buy all", e, r, "%d legs, YES asks add up to %.3f" % (len(ms), sum(asks)), e.get("endDate"))
    return found, stats


def ordered_pairs(rungs):
    """(harder, easier) pairs of one ladder: an earlier deadline or a higher level is harder to reach."""
    for i in range(len(rungs)):
        for j in range(len(rungs)):
            if rungs[i][0] < rungs[j][0]:
                yield rungs[i][1], rungs[j][1]


def ladders(events, books):
    """Ladders inside one event: 'by June 30' cannot be likelier than 'by September 30', 'above $10B' cannot be
    likelier than 'above $8B'. When the harder rung bids more than the easier one asks, buy NO on the harder and
    YES on the easier: the pair pays at least 1."""
    found, stats = [], collections.Counter()
    for e in events:
        ms = [m for m in e["markets"] if tradable(m)]
        if len(ms) < 2 or e.get("negRisk"):
            continue
        by_deadline, by_level = collections.defaultdict(list), collections.defaultdict(list)
        for m in ms:
            q = m["question"]
            d = parse.by_date(q)
            if d:
                by_deadline[parse.date_template(q)].append((d, m))
            v = parse.level(m.get("groupItemTitle"))
            if v is not None and parse.is_upward(q):
                by_level[parse.number_template(q) + "|" + str(m.get("endDate"))].append((-v, m))
        for groups, kind in ((by_deadline, "date"), (by_level, "level")):
            for rungs in groups.values():
                if len(rungs) < 2:
                    continue
                stats[kind + " ladders"] += 1
                for hard, easy in ordered_pairs(rungs):
                    stats["pairs"] += 1
                    b, a = num(hard.get("bestBid")), num(easy.get("bestAsk"))
                    if b and a and b > a:
                        stats["ladder candidates"] += 1
                        r = walk([(books.asks(tokens(hard)[1]), fee_of(hard)), (books.asks(tokens(easy)[0]), fee_of(easy))])
                        add(found, "ladder " + kind, e, r, "%s over %s: bid %.3f > ask %.3f" % (
                            hard.get("groupItemTitle"), easy.get("groupItemTitle"), b, a),
                            max(hard["endDate"], easy["endDate"]))
    return found, stats


def add(found, kind, e, r, detail, end):
    if r and r[0] > 0:
        found.append(dict(kind=kind, title=e["title"], detail=detail, first=r[0], usd=r[1], profit=r[2], end=end))


def days_left(end, now):
    if not end:
        return None
    return max((datetime.fromisoformat(end.replace("Z", "+00:00")) - now).total_seconds() / 86400, .04)


def snapshot_time(path):
    return datetime.strptime(path.name, "%Y-%m-%dT%H%M").replace(tzinfo=timezone.utc)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot")
    ap.add_argument("--live-books", action="store_true")
    a = ap.parse_args(argv)
    path = snapshot.resolve(a.snapshot)
    now = snapshot_time(path)
    events = snapshot.load(path / "polymarket_events.json.gz")
    books = snapshot.Books(path / "polymarket_books.json.gz", live=a.live_books)
    print(path.name, "events", len(events), "open markets", sum(tradable(m) for e in events for m in e["markets"]))
    found, stats = exclusive(events, books)
    ladder_found, ladder_stats = ladders(events, books)
    found += ladder_found
    stats.update(ladder_stats)
    books.save()
    print(dict(stats))
    if books.missing:
        print("books not in the snapshot:", books.missing, "- run with --live-books to price the candidates")
        return
    found.sort(key=lambda x: -x["profit"])
    usd, profit = sum(x["usd"] for x in found), sum(x["profit"] for x in found)
    big = [x for x in found if x["first"] >= .02 and x["usd"] >= 500]
    print("positive after fees on real books: %d, capital $%.0f, profit $%.2f; 2c+ edge and $500+: %d"
          % (len(found), usd, profit, len(big)))
    for x in found[:15]:
        d = days_left(x["end"], now)
        print("  %-9s | %-55s | first %+.3f $%.0f profit $%.2f, %s days" % (
            x["kind"], x["title"][:55], x["first"], x["usd"], x["profit"], "%.0f" % d if d else "?"))
    print("failed requests", dict(FAILURES))


if __name__ == "__main__":
    main()
