"""A Polymarket bet on a crypto level, hedged with the coin's perpetual: does the gap to a lognormal model pay?

python3 -m pmarb.hedge     (needs python3 -m pmarb.history first; writes results/HEDGE.md)

Rules fixed before the first run: trade when |price - model| > 3c, sell YES when the price is above the model and
buy it when below, delta-hedge every 4 hours with the hedge capped at 3 coins' worth of notional per $1 contract,
taker 0.05% on the perpetual. Pass: mean >= 2c per contract after costs, 90% interval above 0, both halves above 0,
for 'above on a date' and 'touch' markets separately. The sell-all control and the finer hedges were added after
the first run.
"""
import bisect
import collections
import json
import pathlib
import re
from datetime import datetime, timezone

from pmarb import digital, parse, snapshot
from pmarb.stats import cents, summary

HISTORY = snapshot.RAW / "history"
RESULTS = pathlib.Path(__file__).resolve().parent.parent / "results"
GAP = .03
WINDOWS = {"above": (("48h", 36, 60), ("24h", 12, 36)), "month": (("month 21d", 20 * 24, 22 * 24),),
           "week": (("week 4d", 84, 108),)}
PERP_FEE = .0005


class Coin:
    """5-minute candles (time, open, high, low, close) and the hourly DVOL index."""

    def __init__(self, bars, dvol):
        self.bars = [tuple(b) for b in bars]
        self.times = [b[0] for b in self.bars]
        self.dvol = {int(k): v for k, v in dvol.items()}
        self.vol_times = sorted(self.dvol)

    def spot(self, t):
        """Open of the 5-minute bar that contains t."""
        i = bisect.bisect_right(self.times, t) - 1
        return self.bars[i][1] if i >= 0 and t - self.times[i] < 900 else None

    def vol(self, t):
        """DVOL published at least an hour before t (and at most six), as a fraction."""
        i = bisect.bisect_right(self.vol_times, t - 3600) - 1
        return self.dvol[self.vol_times[i]] / 100 if i >= 0 and t - self.vol_times[i] < 6 * 3600 else None


def contract_cost(p):
    """Polymarket cost per $1 contract: half spread of 1c (0.5c below 10c and above 90c) plus 1% * p(1-p)."""
    return (.01 if .1 <= p <= .9 else .005) + .01 * p * (1 - p)


def model(kind, spot, strike, vol, years, up):
    return digital.above(spot, strike, vol, years) if kind == "above" else digital.touch(spot, strike, vol, years, up)


def trade(coin, row, sign, price, t, vol, cost, hedge=True, step=4 * 3600, cap=3):
    """Result per $1 contract of buying (sign 1) or selling (sign -1) YES at `price` at time t, held to resolution,
    with the coin delta-hedged every `step` seconds. A touch market stops at the first candle through the barrier."""
    kind, strike, up, end = row["kind"], row["strike"], row["up"], row["end"]
    value = lambda s, tt: model(kind, s, strike, vol, (end - tt) / digital.YEAR, up)
    s = coin.spot(t)
    if s is None:
        return None
    pos = pnl = 0.0
    tt = t
    if hedge:
        while tt < end:
            delta = max(min((value(s * 1.001, tt) - value(s * .999, tt)) / (.002 * s), cap / s), -cap / s)
            new = -sign * delta
            pnl -= PERP_FEE * abs(new - pos) * s
            pos = new
            nxt = min(tt + step, end)
            hit = None
            if kind == "touch":
                for q in range(bisect.bisect_right(coin.times, tt), min(bisect.bisect_right(coin.times, nxt), len(coin.times))):
                    if (coin.bars[q][2] >= strike) if up else (coin.bars[q][3] <= strike):
                        hit = q
                        break
            s2 = strike if hit is not None else coin.spot(nxt)
            if s2 is None:
                return None
            pnl += pos * (s2 - s)
            s, tt = s2, nxt
            if hit is not None:
                break
        pnl -= PERP_FEE * abs(pos) * s
    return sign * (row["outcome"] - price) - cost + pnl


def describe(e, m):
    """(coin, kind, strike, up) of a level market, or None."""
    coin = "BTC" if "itcoin" in e["title"] else "ETH"
    label, q = m.get("groupItemTitle") or "", m["question"]
    k = parse.strike(label, q)
    if k is None:
        return None
    if "above" in e["title"].lower():
        return coin, "above", k, True
    text = label + " " + q
    if re.search(r"↑|reach|hit \$|above", text):
        return coin, "touch", k, True
    if re.search(r"↓|dip|fall|below", text):
        return coin, "touch", k, False
    return None


def rows(events, prices, coins):
    """One row per resolved market and entry window: the first price inside the window and the model at that time."""
    out, dropped = [], collections.Counter()
    for e in events:
        for m in e["markets"]:
            h = prices.get(m["id"]) or []
            z = describe(e, m)
            try:
                outcome = float(json.loads(m["outcomePrices"])[0])
            except Exception:
                dropped["no outcome"] += 1
                continue
            if not m.get("closed") or outcome not in (0.0, 1.0):
                dropped["unresolved"] += 1
                continue
            if not h or not z or not m.get("endDate"):
                dropped["no history or strike"] += 1
                continue
            c, kind, strike, up = z
            end = int(datetime.fromisoformat(m["endDate"].replace("Z", "+00:00")).timestamp())
            if kind == "above" and end % 86400 not in (57600, 61200):  # noon New York: 16:00 or 17:00 UTC
                winter = datetime.fromtimestamp(end, timezone.utc).month in (12, 1, 2)
                end = (end // 86400) * 86400 + (61200 if winter else 57600)
            series = "above" if kind == "above" else ("month" if "hit in" in e["title"].lower() else "week")
            for window, lo, hi in WINDOWS[series]:
                points = [(t, p) for t, p in h if lo * 3600 < end - t <= hi * 3600]
                if not points:
                    dropped["no point in window"] += 1
                    continue
                t, p = points[0]
                s, vol = coins[c].spot(t), coins[c].vol(t)
                if s is None or vol is None:
                    dropped["no spot or vol"] += 1
                    continue
                if not .05 <= p <= .95:
                    continue
                mdl = model(kind, s, strike, vol, (end - t) / digital.YEAR, up)
                if kind == "touch" and mdl >= 1:
                    dropped["already touched"] += 1
                    continue
                out.append(dict(kind=kind, window=window, coin=c, strike=strike, up=up, t=t, end=end, price=p, model=mdl,
                                vol=vol, outcome=outcome,
                                week=datetime.fromtimestamp(end, timezone.utc).strftime("%G-%V")))
    return out, dropped


def results(rs, coins, sign=None, **kw):
    """Trade every row: by the gap rule (sign None) or always the same side (the controls)."""
    x, w = [], []
    for r in rs:
        g = (-1 if r["price"] > r["model"] else 1) if sign is None else sign
        v = trade(coins[r["coin"]], r, g, r["price"], r["t"], r["vol"], contract_cost(r["price"]), **kw)
        if v is not None:
            x.append(v)
            w.append(r["week"])
    return summary(x, w)


def coin_move(coin, r, days=7):
    a, b = coin.spot(r["end"] - days * 86400), coin.spot(r["end"])
    return b / a - 1 if a and b else 0


def study(events, prices, coins):
    rs, dropped = rows(events, prices, coins)
    lines = ["# Hedged bet: results", "", "Generated by `python3 -m pmarb.hedge`. Cents per $1 contract after costs;"
             " intervals resample whole weeks of resolution.", "",
             "Rows: %d (dropped: %s)." % (len(rs), ", ".join("%s %d" % kv for kv in sorted(dropped.items()))), ""]
    lines += ["## Calibration, no costs", "", "| Markets | n | Price minus outcome | Brier, price | Brier, model |", "|---|---|---|---|---|"]
    for kind in ("above", "touch"):
        for window in sorted({r["window"] for r in rs if r["kind"] == kind}):
            z = [r for r in rs if r["kind"] == kind and r["window"] == window]
            mean = lambda f: sum(f(r) for r in z) / len(z)
            lines.append("| %s %s | %d | %+.2fc | %.4f | %.4f |" % (kind, window, len(z), 100 * mean(lambda r: r["price"] - r["outcome"]),
                                                                  mean(lambda r: (r["price"] - r["outcome"]) ** 2),
                                                                  mean(lambda r: (r["model"] - r["outcome"]) ** 2)))
    out = {}
    for kind in ("above", "touch"):
        z = [r for r in rs if r["kind"] == kind]
        gap = [r for r in z if abs(r["price"] - r["model"]) > GAP]
        lines += ["", "## %s: %d markets, %d with a gap over 3c" % (kind.capitalize(), len(z), len(gap)), "",
                  "| Hedge | Trades | Result |", "|---|---|---|"]
        spec = [("rule: every 4h, cap 3", gap, None, dict()), ("control: sell all, every 4h, cap 3", z, -1, dict()),
                ("control: buy all, every 4h, cap 3", z, 1, dict()), ("no hedge", gap, None, dict(hedge=False))]
        for step, cap in ((3600, 3), (3600, 10), (3600, 40), (900, 40)):
            spec += [("every %dmin, cap %d" % (step // 60, cap), gap, None, dict(step=step, cap=cap)),
                     ("control: sell all, every %dmin, cap %d" % (step // 60, cap), z, -1, dict(step=step, cap=cap))]
        if kind == "above":
            spec += [("rule, coin up over the last 7 days", [r for r in gap if coin_move(coins[r["coin"]], r) > 0], None, dict()),
                     ("rule, coin down over the last 7 days", [r for r in gap if coin_move(coins[r["coin"]], r) <= 0], None, dict())]
        for name, sample, sign, kw in spec:
            s = results(sample, coins, sign, **kw)
            out[(kind, name)] = s
            lines.append("| %s | %s | %s |" % (name, s["n"] if s else len(sample), cents(s)))
    first = min(r["t"] for r in rs if r["kind"] == "above")
    lines += ["", "BTC at the first entry %.0f, at the end of the data %.0f." % (coins["BTC"].spot(first), coins["BTC"].bars[-1][4]), ""]
    return out, lines


def load_coins(raw=HISTORY):
    return {c: Coin(snapshot.load(raw / ("%s5m.json.gz" % c)), snapshot.load(raw / ("%sdvol.json.gz" % c))) for c in ("BTC", "ETH")}


def main():
    out, lines = study(snapshot.load(HISTORY / "events.json.gz"), snapshot.load(HISTORY / "prices.json.gz"), load_coins())
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "HEDGE.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
