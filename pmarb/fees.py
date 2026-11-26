"""Taker fees per share or contract, in dollars, at a price between 0 and 1."""


def polymarket_fee(market, price):
    """Polymarket taker fee: rate * (p(1-p))**exponent, from the market's own feeSchedule (rate up to 0.05,
    exponent 1 in every market seen). Markets without feesEnabled charge nothing; makers pay nothing."""
    if not market.get("feesEnabled"):
        return 0.0
    schedule = market.get("feeSchedule") or {}
    return schedule.get("rate", 0) * (price * (1 - price)) ** schedule.get("exponent", 1)


def kalshi_fee(price, multiplier=1.0):
    """Kalshi taker fee as ASSUMED here: 0.07 * multiplier * p(1-p), with the series fee multiplier from the API.
    Kalshi rounds the fee of each order up to the cent; that rounding is not modelled."""
    return 0.07 * multiplier * price * (1 - price)
