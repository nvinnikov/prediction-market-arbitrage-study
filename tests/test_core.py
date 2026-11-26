import json
import math
import unittest

from pmarb import cross, digital, forks, hedge, parse
from pmarb.book import walk
from pmarb.fees import kalshi_fee, polymarket_fee
from pmarb.stats import cluster_bootstrap, summary

FREE = lambda p: 0.0


class Books:
    """Synthetic books by token id."""

    def __init__(self, asks):
        self.data = asks
        self.missing = 0

    def asks(self, token):
        return self.data.get(token)


def market(i, bid, ask, **kw):
    m = dict(id=str(i), question="Q%d" % i, groupItemTitle="Name %d" % i, clobTokenIds=json.dumps(["y%d" % i, "n%d" % i]),
             bestBid=str(bid), bestAsk=str(ask), enableOrderBook=True, acceptingOrders=True, active=True, closed=False,
             endDate="2026-12-31T00:00:00Z")
    m.update(kw)
    return m


class Fees(unittest.TestCase):
    def test_polymarket(self):
        m = {"feesEnabled": True, "feeSchedule": {"rate": .05, "exponent": 1}}
        self.assertAlmostEqual(polymarket_fee(m, .5), .0125)
        self.assertAlmostEqual(polymarket_fee(m, .9), .0045)
        self.assertEqual(polymarket_fee({"feesEnabled": False, "feeSchedule": {"rate": .05}}, .5), 0.0)

    def test_kalshi_assumed(self):
        self.assertAlmostEqual(kalshi_fee(.5), .0175)
        self.assertAlmostEqual(kalshi_fee(.5, .5), .00875)


class Walk(unittest.TestCase):
    A = [(.40, 100), (.45, 50)]
    B = [(.50, 60), (.52, 100)]

    def test_walks_both_books(self):
        first, usd, profit = walk([(self.A, FREE), (self.B, FREE)])
        self.assertAlmostEqual(first, .10)
        self.assertAlmostEqual(usd, 60 * .90 + 40 * .92 + 50 * .97)
        self.assertAlmostEqual(profit, 60 * .10 + 40 * .08 + 50 * .03)

    def test_min_edge_and_fees_stop_early(self):
        self.assertAlmostEqual(walk([(self.A, FREE), (self.B, FREE)], min_edge=.05)[2], 60 * .10 + 40 * .08)
        fee = lambda p: .05
        self.assertAlmostEqual(walk([(self.A, fee), (self.B, fee)])[0], 0.0)

    def test_empty_leg(self):
        self.assertIsNone(walk([(self.A, FREE), ([], FREE)]))
        self.assertIsNone(walk([(self.A, FREE), (None, FREE)]))


class Exclusive(unittest.TestCase):
    def event(self, **kw):
        e = dict(title="Who wins?", negRisk=True, markets=[market(1, .28, .30), market(2, .30, .32), market(3, .33, .35)])
        e.update(kw)
        return e

    def books(self):
        return Books({"y1": [(.30, 10)], "y2": [(.32, 10)], "y3": [(.35, 10)]})

    def test_buy_all_complete_list(self):
        found, stats = forks.exclusive([self.event()], self.books())
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0]["profit"], 10 * (1 - .97))

    def test_placeholder_outcomes_excluded(self):
        self.assertEqual(forks.exclusive([self.event(negRiskAugmented=True)], self.books())[0], [])
        e = self.event()
        e["markets"][2]["negRiskOther"] = True
        self.assertEqual(forks.exclusive([e], self.books())[0], [])

    def test_closed_market_makes_list_incomplete(self):
        e = self.event()
        e["markets"].append(market(4, 0, 0, closed=True, acceptingOrders=False))
        found, stats = forks.exclusive([e], self.books())
        self.assertEqual(found, [])
        self.assertEqual(stats["incomplete lists skipped"], 1)

    def test_sell_all_pays_n_minus_one(self):
        e = dict(title="Who wins?", negRisk=True, markets=[market(1, .40, .42), market(2, .35, .37), market(3, .30, .32)])
        books = Books({"n1": [(.58, 5)], "n2": [(.63, 5)], "n3": [(.68, 5)]})
        found, _ = forks.exclusive([e], books)
        self.assertEqual(found[0]["kind"], "sell all")
        self.assertAlmostEqual(found[0]["profit"], 5 * (2 - 1.89))


class Ladders(unittest.TestCase):
    def test_date_ladder(self):
        hard = market(1, .20, .22, question="Will X launch a token by June 30, 2027?")
        easy = market(2, .15, .18, question="Will X launch a token by September 30, 2027?")
        e = dict(title="Will X launch a token by ___?", negRisk=False, markets=[hard, easy])
        found, stats = forks.ladders([e], Books({"n1": [(.80, 10)], "y2": [(.18, 10)]}))
        self.assertEqual(stats["date ladders"], 1)
        self.assertAlmostEqual(found[0]["profit"], 10 * .02)

    def test_level_ladder(self):
        hard = market(1, .15, .16, question="FDV above $10B one day after launch?", groupItemTitle="$10B")
        easy = market(2, .13, .14, question="FDV above $8B one day after launch?", groupItemTitle="$8B")
        e = dict(title="FDV above ___ one day after launch?", negRisk=False, markets=[hard, easy])
        found, stats = forks.ladders([e], Books({"n1": [(.85, 10)], "y2": [(.14, 10)]}))
        self.assertEqual(stats["level ladders"], 1)
        self.assertAlmostEqual(found[0]["first"], .01)


class Parse(unittest.TestCase):
    def test_deadline_needs_a_year(self):
        self.assertIsNone(parse.by_date("Will it happen by December 31?"))
        self.assertEqual(parse.by_date("Will it happen by December 31, 2026?"), (2026, 12, 31))
        self.assertEqual(parse.by_date("by the end of June 30 2027"), (2027, 6, 30))

    def test_levels(self):
        self.assertEqual(parse.level("↑ 180,000"), 180000)
        self.assertEqual(parse.level("$10B"), 1e10)
        self.assertEqual(parse.level("40+"), 40)
        self.assertEqual(parse.level("1.40"), 1.4)
        self.assertIsNone(parse.level("Other"))
        self.assertIsNone(parse.level("Dec 31"))

    def test_strike_ignores_dates_in_the_question(self):
        self.assertEqual(parse.strike("", "Will Bitcoin reach $100k November 24-30?"), 100000)
        self.assertEqual(parse.strike("↑ 120,000", "Will Bitcoin reach $120,000 November 24-30?"), 120000)
        self.assertIsNone(parse.strike("", "Will Bitcoin reach a new high November 24-30?"))

    def test_number_template(self):
        self.assertEqual(parse.number_template("Will BTC hit $100k in 2026?"), parse.number_template("Will BTC hit $90k in 2026?"))

    def test_upward(self):
        self.assertTrue(parse.is_upward("Will ETH reach $5,000?"))
        self.assertFalse(parse.is_upward("Will ETH dip below $2,000?"))

    def test_names(self):
        self.assertEqual(parse.normalize_name("Atlético Madrid FC"), "atletico madrid")

    def test_same_event(self):
        self.assertFalse(parse.same_event("Watford vs. Leicester", "Watford vs Leicester halftime winner", 2, 0))
        self.assertTrue(parse.same_event("Watford vs. Leicester", "Watford vs Leicester winner", 2, 1))
        self.assertFalse(parse.same_event("Watford vs. Leicester", "Watford vs Leicester winner", 2, 5))
        self.assertFalse(parse.same_event("Champion 2026", "Champion 2027", 8, 10))


class Cross(unittest.TestCase):
    def test_gap_on_best_prices(self):
        m = market(1, .40, .42)
        km = {"ticker": "K-1", "yes_bid_dollars": "0.45", "yes_ask_dollars": "0.47"}
        pairs = [(0, {"title": "t"}, {"title": "t"}, ["a"], {"a": (.41, m, 0)}, {"a": (.46, km)}, 0)]
        candidates, diff = cross.quoted_gaps(pairs)
        self.assertAlmostEqual(diff[0], .05)
        self.assertAlmostEqual(candidates[0][0], 1 - .42 - (1 - .45))


class Digital(unittest.TestCase):
    def test_above_at_the_money(self):
        self.assertAlmostEqual(digital.above(100, 100, .5, 1), digital.norm_cdf(-.25), places=12)
        self.assertEqual(digital.above(101, 100, .5, 0), 1.0)

    def test_skew_hand_check(self):
        flat = digital.norm_cdf(-.25)
        self.assertAlmostEqual(digital.above_with_skew(100, 100, .5, 0, 1), flat, places=12)
        self.assertAlmostEqual(digital.above_with_skew(100, 100, .5, -.001, 1), flat + 100 * digital.norm_pdf(.25) * .001,
                               places=12)
        self.assertAlmostEqual(digital.above_with_skew(100, 100, .5, -.001, 1), 0.43996, places=4)

    def test_touch_bounds(self):
        t, a = digital.touch(100, 110, .5, .25, True), digital.above(100, 110, .5, .25)
        self.assertGreater(t, a)
        self.assertLessEqual(t, 100 / 110)  # Doob: a martingale reaches B with probability at most S/B
        self.assertEqual(digital.touch(111, 110, .5, .25, True), 1.0)
        self.assertEqual(digital.touch(100, 110, .5, 0, True), 0.0)
        self.assertGreater(digital.touch(100, 90, .5, .25, False), digital.touch(100, 80, .5, .25, False))

    def test_smile(self):
        iv, slope = digital.smile_at([(90, .6), (100, .5), (110, .45)], 105)
        self.assertAlmostEqual(iv, .475)
        self.assertAlmostEqual(slope, -.005)
        self.assertIsNone(digital.smile_at([(90, .6), (100, .5)], 120))


class Stats(unittest.TestCase):
    def test_bootstrap_is_deterministic(self):
        x = [math.sin(i) for i in range(50)]
        c = [i // 5 for i in range(50)]
        self.assertEqual(cluster_bootstrap(x, c), cluster_bootstrap(x, c))
        s = summary(x, c)
        self.assertEqual(s["clusters"], 10)
        self.assertLess(s["lo"], s["mean"])
        self.assertLess(s["mean"], s["hi"])
        self.assertIsNone(summary(x[:5], c[:5]))


class Hedge(unittest.TestCase):
    def coin(self):
        bars = [(t, 100.0, 100.5, 99.5, 100.0) for t in range(0, 30 * 86400, 300)]
        return hedge.Coin(bars, {str(t): 50.0 for t in range(0, 30 * 86400, 3600)})

    def test_unhedged_is_the_bet(self):
        row = dict(kind="above", strike=100.0, up=True, end=10 * 86400, outcome=1.0)
        self.assertAlmostEqual(hedge.trade(self.coin(), row, 1, .4, 86400, .5, .01, hedge=False), .59)
        self.assertAlmostEqual(hedge.trade(self.coin(), row, -1, .4, 86400, .5, .01, hedge=False), -.61)

    def test_flat_coin_hedge_costs_only_fees(self):
        row = dict(kind="above", strike=100.0, up=True, end=10 * 86400, outcome=1.0)
        v = hedge.trade(self.coin(), row, 1, .4, 86400, .5, .01)
        self.assertLess(v, .59)
        self.assertGreater(v, .59 - .05)

    def test_cost(self):
        self.assertAlmostEqual(hedge.contract_cost(.5), .0125)
        self.assertAlmostEqual(hedge.contract_cost(.05), .005 + .000475)

    def test_describe(self):
        e = {"title": "What price will Bitcoin hit November 24-30?"}
        self.assertEqual(hedge.describe(e, {"groupItemTitle": "↑ 120,000", "question": "Will Bitcoin reach $120,000?"}),
                         ("BTC", "touch", 120000, True))
        self.assertEqual(hedge.describe(e, {"groupItemTitle": "↓ 80,000", "question": "Will Bitcoin dip to $80,000?"}),
                         ("BTC", "touch", 80000, False))
        self.assertEqual(hedge.describe({"title": "Ethereum above ___ on November 30?"},
                                        {"groupItemTitle": "3,000", "question": "Will Ethereum be above $3,000?"}),
                         ("ETH", "above", 3000, True))


if __name__ == "__main__":
    unittest.main()
