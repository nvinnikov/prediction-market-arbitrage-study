# Prediction markets: forks and a hedged bet

Can a basket of Polymarket outcomes, the same outcome bought on Polymarket and on Kalshi, or a Polymarket bet on a
crypto level hedged with the coin's perpetual, pay whatever happens, after fees and on real order books?
**Status: closed, negative result. No real money.**

## In short

- **Internal forks.** In all 17,473 open Polymarket events (152,441 markets) on 26 Nov 2026, the forks that still paid after fees, with the order books walked, came to **$29 of profit on $5,710** of capital, most of it locked for about a year or more. The first scan a day earlier gave the same: $29 on about $5,300.
- **Polymarket against Kalshi.** 422 event pairs on 26 Nov; with both fees on real books, 251 outcomes showed a basket that pays: **$4,177 on $1.24M**, almost all of it in markets that end months or years away. Of the short-dated ones, post counts over different weeks, one award matched to another award and a group winner matched to the tournament winner were different questions. The same questions were three sports matches: 2.0-3.6c on $10,232 of depth, **$138 in total**, before reading their resolution rules or checking that one account can use both venues. In the 25 Nov run every short-dated candidate was a different question, and the long-dated same questions paid 0.5-4.7% a year.
- **Polymarket against Deribit options.** On 51 'above' levels within 16 hours of a Deribit expiry, Polymarket's mid sat on average within **1.6c** of a digital priced from Deribit's implied volatility. The smile cut the bias from +2.8c to +0.4c on 25 Nov and from +1.1c to -0.2c on 26 Nov. The largest gaps, 4-5c, are where the smile slope between two neighbouring strikes moves the model by as much. Not a fork; the option spread that would hedge one was not priced.
- **A bet hedged with a perpetual.** The rule fixed before the run passed on paper: **+3.20c per $1 contract** (90% interval +0.87 to +5.69). A control added afterwards sold every YES whatever the gap, with the same hedge, and made **+2.75c**. The money came from Bitcoin falling from 118,592 to 58,437 over the sample, not from the gap. Hedged finely enough to remove that, the trade loses: **-2.25c** on 'above' markets, **-3.34c** on 'touch' markets.
- **Depth.** Daily 'above' markets priced 5-95c: median spread 2c, and a median **$186** of NO within 1c of the best bid on 26 Nov ($33 on 25 Nov). Weekly and monthly 'hit' markets: 1c and $719.

## Results

| Idea | Data | After fees, on real books | Verdict |
|---|---|---|---|
| Buy every outcome of a complete list, or every NO when the bids add up to more than 1 | 4,978 mutually exclusive events | 2 positions with an edge, $4 of capital | nothing |
| Ladders: 'by June 30' bid above 'by September 30' ask, 'above $10B' bid above 'above $8B' ask | 764 ladders, 13,316 ordered pairs | 21 positions, $29 on $5,707; the largest pays 0.8% to January 2028 | nothing |
| Same outcome YES on one venue, NO on the other | 422 event pairs, 2,953 shared outcomes | 251 outcomes pay, $4,177 on $1.24M; same-question and short-dated: 3 sports matches, $138 on $10,232 | small, and the rules of each pair decide |
| Polymarket 'above' against a digital priced off Deribit's smile | 51 levels within 16h of an expiry | mid within 1.6c of the model on average; 4 levels outside the book by more than 4c | not a fork |
| Polymarket price against a lognormal model, delta-hedged every 4 hours | 2,338 'above' and 649 'touch' trades, 69 and 78 weeks | +3.20c and -1.29c; control +2.75c and -2.03c | the gap adds nothing over the control |
| The same, hedged every hour with the hedge uncapped | same | -2.25c and -3.34c | negative |

Full tables: [results/HEDGE.md](results/HEDGE.md). Figures in the bullets come from the reruns of this code: the
snapshot stages on the cached 25 Nov data reproduce the first runs exactly (17,455 events, 4,761 exclusive lists,
13,296 ladder pairs, 378 Kalshi pairs, 403 quoted gaps; one buy-all candidate fewer, the one the completeness rule now
rejects), and the hedged study reproduces to the hundredth of a cent. The book stages were rerun live on 26 Nov.

## What looked like a fork and was not

| Looked like | Was | Rule now |
|---|---|---|
| Buying all outcomes of a daily temperature market for 0.3c, a 'profit' of $10,207 | The winning market had already resolved and closed; the remaining outcomes were worthless | A list with any closed market is not complete ([forks.py](pmarb/forks.py)) |
| Buying all outcomes of a tournament list below 1 | Augmented lists keep placeholder and 'Other' outcomes | Augmented and 'Other' lists are skipped |
| A date ladder whose 'December 31' was read as the wrong year | A deadline without a year | Deadlines are read only with a year ([parse.py](pmarb/parse.py)) |
| A strike taken from the dates in 'reach $100k November 24-30' | The number was a date | In a question only a $-number is a strike |
| A match on one venue against its halftime market on the other | Different questions | Titles must carry the same qualifiers (halftime, set, map...) |
| Short-dated cross-venue gaps of several cents | Same names, different questions, for example post counts over different weeks | Read the rules of every candidate; text matching only proposes pairs |
| Polymarket 2.8 points above a flat-volatility option model | The smile: a digital is not N(d2) at one volatility | The skew term -F n(d1) sqrt(T) dIV/dK ([digital.py](pmarb/digital.py)) |

## Method

- **Rules before results.** The hedged test's threshold, hedge interval, hedge cap and pass conditions are written in [hedge.py](pmarb/hedge.py) as they were fixed before the first run. What was added later is labelled so.
- **Costs first.** Polymarket's per-market taker fee, Kalshi's fee with the series multiplier, a half spread on Polymarket and the perpetual's taker fee in the hedged test.
- **Real books.** A fork counts only if it pays after the books are walked level by level; the best bid and ask only propose candidates.
- **Controls.** Selling or buying every contract regardless of the signal, the same trades without a hedge, the same rule split by the coin's direction.
- **Clusters.** Markets resolving in the same week share the coin's path, so intervals resample whole weeks.
- **Errors are kept.** Each false fork above became a rule and a test.

## Limits

- The Kalshi fee is assumed: 0.07 * multiplier * p(1-p) per contract, without Kalshi's rounding up to the cent. Access to Kalshi was not checked.
- A snapshot is one moment; books move by the second. The order books of the 25 Nov run were not saved, so its book-stage numbers exist only in its log; the 26 Nov rerun saves its books next to the snapshot.
- The hedged study uses Polymarket prices at 12-hour fidelity (the first point in each entry window), DVOL as the volatility for every strike, and assumed costs: 1c half spread (0.5c in the tails) plus 1% * p(1-p) on Polymarket, 0.05% taker on the perpetual.
- The sell-all control and the finer hedges were added after the first run of the rule.
- Matching events across venues by text is a heuristic; every candidate still needs its rules read.
- Code and text were drafted with an AI assistant.

## Run

Python 3.9+, standard library only. Raw data goes to `data/raw`, which is not committed.

```bash
python3 -m unittest                   # tests
python3 -m pmarb.fetch                # snapshot of open Polymarket and Kalshi events, about 10 minutes
python3 -m pmarb.forks --live-books   # internal forks; books are saved with the snapshot
python3 -m pmarb.cross --live-books   # Polymarket against Kalshi
python3 -m pmarb.deribit              # Polymarket against Deribit options, live
python3 -m pmarb.depth                # spread and depth of the crypto level markets, live
python3 -m pmarb.history              # resolved crypto level markets since Sep 2024, about an hour
python3 -m pmarb.hedge                # hedged study, writes results/HEDGE.md
```

Without `--live-books` the scans replay the books saved with the snapshot, or stop after the candidate stage.

Not investment advice. No orders are sent.
