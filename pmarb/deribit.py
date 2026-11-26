"""Polymarket 'Bitcoin / Ethereum above X on <date>' against Deribit options on the same expiry, live.

python3 -m pmarb.deribit [--snapshot NAME]
The options give a digital price with the smile; a fork would need the model outside Polymarket's bid and ask by
more than the costs of trading the options. The snapshot only lists the markets: their books are fetched at the same
time as the Deribit marks, and both are saved next to the snapshot as deribit_<time>.json.gz.
"""
import argparse
import collections
import math
import re
import statistics
from datetime import datetime, timezone

from pmarb import digital, snapshot
from pmarb.client import DERIBIT, get_json
from pmarb.forks import tokens, tradable


def option_smiles(currency):
    """Expiry (08:00 UTC) -> [(strike, mark iv, underlying)] of the calls, sorted by strike."""
    out = collections.defaultdict(list)
    for x in get_json(DERIBIT + "/get_book_summary_by_currency?currency=%s&kind=option" % currency)["result"]:
        p = x["instrument_name"].split("-")
        if p[3] == "C" and x.get("mark_iv"):
            expiry = datetime.strptime(p[1], "%d%b%y").replace(hour=8, tzinfo=timezone.utc)
            out[expiry].append((float(p[2]), x["mark_iv"] / 100, x["underlying_price"]))
    return {k: sorted(v) for k, v in out.items()}


def compare(events, now, books, smiles_by_coin, max_shift_hours=16):
    """Rows of (model outside the book, flat model, smile model, bid, ask) for markets near a Deribit expiry."""
    rows = []
    for currency, word in (("BTC", "bitcoin"), ("ETH", "ethereum")):
        smiles = smiles_by_coin[currency]
        expiries = sorted(smiles)
        for e in events:
            t = e["title"].lower()
            if word not in t or "above" not in t:
                continue
            for m in e["markets"]:
                if not tradable(m):
                    continue
                g = re.sub("[^0-9.]", "", m.get("groupItemTitle") or "")
                if not g or not m.get("endDate"):
                    continue
                strike = float(g)
                end = datetime.fromisoformat(m["endDate"].replace("Z", "+00:00"))
                years = (end - now).total_seconds() / digital.YEAR
                if years * 8766 < 6:
                    continue
                x = min(expiries, key=lambda z: abs((z - end).total_seconds()))
                if abs((x - end).total_seconds()) > max_shift_hours * 3600:
                    continue
                s = digital.smile_at(smiles[x], strike)
                if not s:
                    continue
                bids, asks = books.bids(tokens(m)[0]), books.asks(tokens(m)[0])
                if not bids or not asks:
                    continue
                b, a = bids[0][0], asks[0][0]
                iv, slope = s
                forward = smiles[x][0][2]
                sd = iv * math.sqrt(years)
                flat = digital.norm_cdf((math.log(forward / strike) - sd * sd / 2) / sd)
                skew = digital.above_with_skew(forward, strike, iv, slope, years)
                rows.append(dict(outside=max(b - skew, skew - a), flat=flat, skew=skew, bid=b, ask=a))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot")
    path = snapshot.resolve(ap.parse_args(argv).snapshot)
    now = datetime.now(timezone.utc)
    out = path / ("deribit_%s.json.gz" % now.strftime("%Y-%m-%dT%H%M"))
    books = snapshot.Books(out, live=True)
    smiles = {c: option_smiles(c) for c in ("BTC", "ETH")}
    rows = compare(snapshot.load(path / "polymarket_events.json.gz"), now, books, smiles)
    snapshot.save(out, dict(books.data, _smiles={c: [[k.isoformat(), v] for k, v in s.items()] for c, s in smiles.items()}))
    print(len(rows), "levels within 16h of a Deribit expiry")
    if not rows:
        return
    mid = lambda r: (r["bid"] + r["ask"]) / 2
    print("mid minus model: flat %+.3f, with skew %+.3f | mean abs %.3f vs %.3f" % (
        statistics.mean(mid(r) - r["flat"] for r in rows), statistics.mean(mid(r) - r["skew"] for r in rows),
        statistics.mean(abs(mid(r) - r["flat"]) for r in rows), statistics.mean(abs(mid(r) - r["skew"]) for r in rows)))
    print("model outside the bid/ask by > 0: %d, > 2c: %d, > 4c: %d" % tuple(
        sum(r["outside"] > k for r in rows) for k in (0, .02, .04)))


if __name__ == "__main__":
    main()
