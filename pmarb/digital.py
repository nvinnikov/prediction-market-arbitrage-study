"""Prices of binary outcomes on a coin price under a driftless lognormal model (volatility per year, time in years)."""
import math

YEAR = 31557600  # seconds


def norm_cdf(x):
    return .5 * (1 + math.erf(x / math.sqrt(2)))


def norm_pdf(x):
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def above(spot, strike, vol, years):
    """Probability that the price is above the strike at expiry: N(d2) with the forward equal to the spot."""
    if years <= 0:
        return float(spot > strike)
    sd = vol * math.sqrt(years)
    return norm_cdf((math.log(spot / strike) - sd * sd / 2) / sd)


def touch(spot, barrier, vol, years, up):
    """Probability that the price touches the barrier before expiry (reflection formula with drift -vol^2/2)."""
    if (spot >= barrier) if up else (spot <= barrier):
        return 1.0
    if years <= 0:
        return 0.0
    sd = vol * math.sqrt(years)
    drift = -vol * vol / 2
    x = math.log(spot / barrier) if up else math.log(barrier / spot)
    mu = drift * years if up else -drift * years
    return min(1.0, norm_cdf((x + mu) / sd) + (spot / barrier) * norm_cdf((x - mu) / sd))


def above_with_skew(forward, strike, iv, iv_slope, years):
    """Digital call priced off a volatility smile: N(d2) - F n(d1) sqrt(T) dIV/dK.
    Without the skew term a flat-volatility model put Polymarket 2.8 points too high on average."""
    sd = iv * math.sqrt(years)
    d2 = (math.log(forward / strike) - sd * sd / 2) / sd
    d1 = d2 + sd
    return norm_cdf(d2) - forward * norm_pdf(d1) * math.sqrt(years) * iv_slope


def smile_at(smile, strike):
    """(iv, dIV/dK) by linear interpolation in a [(strike, iv, ...)] list sorted by strike; None outside it."""
    ks = [s[0] for s in smile]
    if not ks[0] < strike < ks[-1]:
        return None
    j = max(next(i for i, k in enumerate(ks) if k >= strike), 1)
    a, b = smile[j - 1], smile[j]
    w = (strike - a[0]) / (b[0] - a[0])
    return a[1] * (1 - w) + b[1] * w, (b[1] - a[1]) / (b[0] - a[0])
