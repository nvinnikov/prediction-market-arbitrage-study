"""Polymarket against Kalshi: the same outcome bought YES on one venue and NO on the other pays 1 whatever happens.

python3 -m pmarb.cross [--snapshot NAME] [--live-books]
Events are paired by shared outcome names, then by title (see parse.same_event). The gap is first measured on the
best bid and ask of the snapshot; with --live-books both order books are walked with both fees.
"""
import argparse
import collections
import json
import re
import statistics
from datetime import datetime

from pmarb import snapshot
from pmarb.book import walk
from pmarb.client import FAILURES, KALSHI, get_json
from pmarb.fees import kalshi_fee, polymarket_fee
from pmarb.forks import num, snapshot_time, tradable
from pmarb.parse import SIDE_MARKET, normalize_name, same_event


def when(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def kalshi_price(m, key):
    return num(m.get(key + "_dollars"))


def polymarket_outcomes(events):
    """Per event: outcome name -> (mid, market, index of the token that pays on that name).
    Neg-risk lists give one market per name; two-way markets with named sides (team A or team B) give both names.
    Totals, spreads and period markets are left out."""
    out = []
    for e in events:
        ms = [m for m in e["markets"] if tradable(m) and num(m.get("bestBid")) is not None
              and num(m.get("bestAsk")) is not None]
        if e.get("negRisk") and len(ms) >= 2:
            d = {normalize_name(m.get("groupItemTitle")): ((num(m["bestBid"]) + num(m["bestAsk"])) / 2, m, 0)
                 for m in ms if m.get("groupItemTitle")}
            if len(d) >= 2:
                out.append((e, d))
        for m in ms:
            o = json.loads(m.get("outcomes") or "[]")
            if len(o) == 2 and {x.lower() for x in o} != {"yes", "no"} and not SIDE_MARKET.search(
                    (m["question"] + " ".join(o)).lower()):
                mid = (num(m["bestBid"]) + num(m["bestAsk"])) / 2
                out.append((e, {normalize_name(o[0]): (mid, m, 0), normalize_name(o[1]): (1 - mid, m, 1)}))
    return out


def kalshi_outcomes(events):
    out = []
    for e in events:
        d = {}
        for m in e.get("markets") or []:
            b, a = kalshi_price(m, "yes_bid"), kalshi_price(m, "yes_ask")
            if m.get("status") == "active" and b is not None and a and 0 < a <= 1:
                d[normalize_name(m.get("yes_sub_title"))] = ((a + b) / 2, m)
        if len(d) >= 2:
            out.append((e, d))
    return out


def match(poly, kalshi):
    """Strict event pairs: at least two shared names and half of the smaller list, mids within 12c, then the title
    check. One Kalshi event per Polymarket entry, the one with most shared names and the closest end."""
    index = collections.defaultdict(set)
    for i, (_, d) in enumerate(kalshi):
        for name in d:
            index[name].add(i)
    pairs = []
    for n, (e, d) in enumerate(poly):
        hits = collections.Counter(i for name in d for i in index.get(name, ()))
        for i, k in hits.most_common(8):
            ke, kd = kalshi[i]
            shared = sorted(set(d) & set(kd))
            if k < 2 or k < .5 * min(len(d), len(kd)):
                continue
            pm, km = [d[x][0] for x in shared], [kd[x][0] for x in shared]
            if max(abs(x - y) for x, y in zip(pm, km)) > .12 or max(pm) < .02:
                continue
            if len(d) == 2 and not re.search("win|vs|game|match", (ke.get("title") or "").lower()):
                continue
            first = kd[shared[0]][1]
            te, tk = when(d[shared[0]][1].get("endDate")), when(first.get("expected_expiration_time") or first.get("close_time"))
            gap = abs((te - tk).total_seconds()) / 86400 if te and tk else 999
            if len(d) == 2 and gap > 8:
                continue
            pairs.append((n, e, ke, shared, d, kd, gap))
    before = len(pairs)
    pairs = [p for p in pairs if same_event(p[1]["title"], (p[2].get("title") or "") + " " + (p[2].get("sub_title") or ""),
                                            len(p[4]), p[6])]
    best = {}
    for p in pairs:
        score = (len(p[3]), -p[6])
        if p[0] not in best or score > best[p[0]][0]:
            best[p[0]] = (score, p)
    return [p for _, p in best.values()], before


def quoted_gaps(pairs):
    """Gap of the better of the two baskets on best prices, before fees: 1 - YES ask on one venue - NO ask on the other."""
    candidates, mid_diff = [], []
    for _, e, ke, shared, d, kd, gap in pairs:
        for name in shared:
            _, m, ix = d[name]
            km = kd[name][1]
            pb, pa = num(m["bestBid"]), num(m["bestAsk"])
            if ix == 1:
                pb, pa = 1 - pa, 1 - pb
            b, a = kalshi_price(km, "yes_bid"), kalshi_price(km, "yes_ask")
            mid_diff.append(abs((pa + pb) / 2 - (a + b) / 2))
            g = max(1 - pa - (1 - b) if b > 0 else -1, 1 - (1 - pb) - a if pb > 0 else -1)
            if g > 0:
                candidates.append((g, e, ke, name, m, ix, km, gap))
    return candidates, mid_diff


def series_multiplier(cache, ticker):
    if ticker not in cache:
        s = (get_json(KALSHI + "/series/" + ticker) or {}).get("series") or {}
        cache[ticker] = num(s.get("fee_multiplier")) if s.get("fee_multiplier") is not None else 1.0
    return cache[ticker]


def price_on_books(candidates, poly_books, kalshi_books, multipliers, limit=900):
    out = []
    for g, e, ke, name, m, ix, km, gap in sorted(candidates, key=lambda x: -x[0])[:limit]:
        t = json.loads(m["clobTokenIds"])
        yes, no = poly_books.asks(t[ix]), poly_books.asks(t[1 - ix])
        kb = kalshi_books.get(km["ticker"])
        if yes is None or kb is None:
            continue
        mu = multipliers.get(ke.get("series_ticker") or km["ticker"].split("-")[0])
        if mu is None:
            mu = series_multiplier(multipliers, ke.get("series_ticker") or km["ticker"].split("-")[0])
        fk, fp = (lambda p, mu=mu: kalshi_fee(p, mu)), (lambda p, m=m: polymarket_fee(m, p))
        for side, A, B in (("Polymarket YES + Kalshi NO", yes, [tuple(x) for x in kb["no_asks"]]),
                           ("Polymarket NO + Kalshi YES", no, [tuple(x) for x in kb["yes_asks"]])):
            r = walk([(A, fp), (B, fk)])
            if r and r[0] > 0:
                end = max(t_ for t_ in (when(m.get("endDate")), when(km.get("expected_expiration_time") or km.get("close_time"))) if t_)
                out.append(dict(side=side, title=e["title"], name=name, first=r[0], usd=r[1], profit=r[2], end=end))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot")
    ap.add_argument("--live-books", action="store_true")
    a = ap.parse_args(argv)
    path = snapshot.resolve(a.snapshot)
    now = snapshot_time(path)
    poly = polymarket_outcomes(snapshot.load(path / "polymarket_events.json.gz"))
    kalshi = kalshi_outcomes(snapshot.load(path / "kalshi_events.json.gz"))
    pairs, before = match(poly, kalshi)
    print(path.name, "pairs before the title check", before, "| strict event pairs", len(pairs),
          "shared outcomes", sum(len(p[3]) for p in pairs))
    candidates, mid_diff = quoted_gaps(pairs)
    mid_diff.sort()
    print("mid difference: median %.3f p90 %.3f | gap > 0 on best prices before fees: %d"
          % (statistics.median(mid_diff), mid_diff[int(.9 * len(mid_diff))], len(candidates)))
    poly_books = snapshot.Books(path / "polymarket_books.json.gz", live=a.live_books)
    kalshi_books = snapshot.Books(path / "kalshi_books.json.gz", live=a.live_books, fetch=snapshot.kalshi_book)
    mult_path = path / "kalshi_fee_multipliers.json.gz"
    multipliers = snapshot.load(mult_path) if mult_path.exists() else {}
    if not a.live_books and not kalshi_books.data:
        print("books not in the snapshot - run with --live-books to price the candidates")
        return
    res = price_on_books(candidates, poly_books, kalshi_books, multipliers)
    poly_books.save()
    kalshi_books.save()
    if a.live_books:
        snapshot.save(mult_path, multipliers)
    for limit, label in ((7, "ending within 7 days"), (45, "within 45 days"), (99999, "all")):
        z = [x for x in res if (x["end"] - now).total_seconds() / 86400 <= limit]
        big = [x for x in z if x["first"] >= .02 and x["usd"] >= 500]
        print("%-21s positive after both fees %d, capital $%.0f, profit $%.0f | 2c+ and $500+: %d"
              % (label, len(z), sum(x["usd"] for x in z), sum(x["profit"] for x in z), len(big)))
    print("failed requests", dict(FAILURES))


if __name__ == "__main__":
    main()
