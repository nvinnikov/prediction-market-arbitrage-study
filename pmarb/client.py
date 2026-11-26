"""JSON over HTTP with gzip, retries and a log of failures (standard library only)."""
import collections
import gzip
import json
import time
import urllib.error
import urllib.request

HEADERS = {"User-Agent": "research-script", "Accept-Encoding": "gzip"}
FAILURES = collections.Counter()

POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB = "https://clob.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
DERIBIT = "https://www.deribit.com/api/v2/public"
BINANCE = "https://data-api.binance.vision/api/v3"


def get_json(url, tries=4, timeout=60):
    """Parsed JSON, or None after `tries` attempts. Client errors are not retried; every failure is counted in FAILURES.
    The Polymarket gamma API answers 406 to large pages unless gzip is accepted, so the header is always sent."""
    err = None
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return json.loads(body)
        except urllib.error.HTTPError as e:
            err = "HTTP %d" % e.code
            if e.code in (400, 404, 406, 422):
                break
        except Exception as e:  # network errors: retry
            err = type(e).__name__
        time.sleep(2 + 2 * k)
    FAILURES[url.split("?")[0][:70] + " " + str(err)] += 1
    return None
