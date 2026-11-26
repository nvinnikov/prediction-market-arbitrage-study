"""History for the hedged study: resolved Bitcoin / Ethereum level markets on Polymarket since September 2024,
their price history (twice a day), Binance 5-minute candles and the Deribit volatility index (DVOL).
Writes data/raw/history/*.json.gz. About an hour, mostly price histories."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from pmarb import snapshot
from pmarb.client import BINANCE, DERIBIT, FAILURES, POLYMARKET_CLOB, POLYMARKET_GAMMA, get_json
from pmarb.fetch import EVENT_KEYS, MARKET_KEYS, trim

OUT = snapshot.RAW / "history"
MONTHS = "january february march april may june july august september october november december".split()
START = datetime(2024, 9, 1)


def slugs(end):
    """Event slugs of the daily 'above', weekly 'hit' and monthly 'hit in' series, with and without the year."""
    out, d = set(), START
    while d < end:
        md = "%s-%d" % (MONTHS[d.month - 1], d.day)
        e = d + timedelta(6)
        week = "%s-%s" % (md, e.day if e.month == d.month else "%s-%d" % (MONTHS[e.month - 1], e.day))
        for coin in ("bitcoin", "ethereum"):
            for y in ("", "-%d" % d.year):
                out.add("%s-above-on-%s%s" % (coin, md, y))
                out.add("what-price-will-%s-hit-%s%s" % (coin, week, y))
                if d.day == 1:
                    out.add("what-price-will-%s-hit-in-%s%s" % (coin, MONTHS[d.month - 1], y))
        d += timedelta(1)
    return sorted(out)


def events(names):
    def page(chunk):
        return get_json(POLYMARKET_GAMMA + "/events?limit=50&" + "&".join("slug=" + s for s in chunk)) or []
    found = {}
    with ThreadPoolExecutor(4) as pool:
        for rows in pool.map(page, [names[i:i + 40] for i in range(0, len(names), 40)]):
            for e in rows:
                found[e["id"]] = dict(trim(e, EVENT_KEYS), markets=[trim(m, MARKET_KEYS) for m in e.get("markets") or []])
    return list(found.values())


def price_histories(evs):
    """Market id -> [(unix time, price of YES)], 12-hour fidelity (finer fidelity returns nothing for closed markets)."""
    markets = [(m["id"], json.loads(m["clobTokenIds"])[0]) for e in evs for m in e["markets"]
               if m.get("closed") and m.get("clobTokenIds")]

    def one(x):
        h = get_json(POLYMARKET_CLOB + "/prices-history?market=%s&interval=max&fidelity=720" % x[1]) or {}
        return x[0], [(z["t"], z["p"]) for z in h.get("history", [])]
    with ThreadPoolExecutor(5) as pool:
        return dict(pool.map(one, markets))


def candles(symbol, t0, t1):
    out, t = [], t0
    while t < t1:
        x = get_json(BINANCE + "/klines?symbol=%s&interval=5m&limit=1000&startTime=%d" % (symbol, t))
        if not x:
            break
        out += [(q[0] // 1000, float(q[1]), float(q[2]), float(q[3]), float(q[4])) for q in x]
        t = x[-1][0] + 300000
        time.sleep(.05)
    return out


def dvol(currency, t0, t1):
    out, t = {}, t0
    while t < t1:
        x = get_json(DERIBIT + "/get_volatility_index_data?currency=%s&start_timestamp=%d&end_timestamp=%d&resolution=3600"
                     % (currency, t, min(t + 900 * 3600000, t1)))
        for q in (x or {}).get("result", {}).get("data", []):
            out[q[0] // 1000] = q[4]
        t += 900 * 3600000
        time.sleep(.1)
    return out


def main():
    now = datetime.now(timezone.utc)
    evs = events(slugs(now.replace(tzinfo=None)))
    snapshot.save(OUT / "events.json.gz", evs)
    print("events", len(evs), flush=True)
    hist = price_histories(evs)
    snapshot.save(OUT / "prices.json.gz", hist)
    print("markets with history", sum(bool(v) for v in hist.values()), flush=True)
    t0, t1 = int(START.replace(tzinfo=timezone.utc).timestamp() * 1000), int(now.timestamp() * 1000)
    for symbol, coin in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH")):
        snapshot.save(OUT / ("%s5m.json.gz" % coin), candles(symbol, t0, t1))
        snapshot.save(OUT / ("%sdvol.json.gz" % coin), dvol(coin, t0, t1))
    print("failed requests", dict(FAILURES))


if __name__ == "__main__":
    main()
