"""Snapshots on disk: gzipped JSON under data/raw (never committed), and order books that can be replayed."""
import gzip
import json
import pathlib
import time

from pmarb.client import KALSHI, POLYMARKET_CLOB, get_json

RAW = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"
LIVE = RAW / "live"


def save(path, obj):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        json.dump(obj, f)


def load(path):
    with gzip.open(path, "rt") as f:
        return json.load(f)


def latest():
    """The newest live snapshot directory."""
    dirs = sorted(p for p in LIVE.glob("*") if (p / "polymarket_events.json.gz").exists())
    if not dirs:
        raise SystemExit("no snapshot: run python3 -m pmarb.fetch first")
    return dirs[-1]


def resolve(name=None):
    return LIVE / name if name else latest()


def polymarket_book(token):
    b = get_json(POLYMARKET_CLOB + "/book?token_id=" + token) or {}
    time.sleep(.04)
    return {"bids": sorted(((float(x["price"]), float(x["size"])) for x in b.get("bids", [])), reverse=True),
            "asks": sorted((float(x["price"]), float(x["size"])) for x in b.get("asks", []))}


def kalshi_book(ticker):
    """Asks to buy YES come from the NO bids (price 1 - p) and the other way round."""
    x = get_json(KALSHI + "/markets/%s/orderbook?depth=50" % ticker) or {}
    o = x.get("orderbook_fp") or x.get("orderbook") or {}
    asks = lambda bids: sorted((round(1 - float(p), 4), float(s)) for p, s in bids)
    return {"yes_asks": asks(o.get("no_dollars") or []), "no_asks": asks(o.get("yes_dollars") or [])}


class Books:
    """Order books by key. In live mode a missing book is fetched and kept, so the run can be saved and replayed
    offline; offline, a missing book is None and counted in `missing`."""

    def __init__(self, path=None, live=False, fetch=polymarket_book):
        self.path, self.live, self.fetch, self.missing = path, live, fetch, 0
        self.data = load(path) if path and pathlib.Path(path).exists() else {}

    def get(self, key):
        if key not in self.data:
            if not self.live:
                self.missing += 1
                return None
            self.data[key] = self.fetch(key)
        return self.data[key]

    def asks(self, token):
        b = self.get(token)
        return [tuple(x) for x in b["asks"]] if b else None

    def bids(self, token):
        b = self.get(token)
        return [tuple(x) for x in b["bids"]] if b else None

    def save(self):
        if self.path and self.live:
            save(self.path, self.data)
