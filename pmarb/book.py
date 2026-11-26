"""Walking order books: how much of a basket can be bought before it stops paying."""


def walk(legs, payout=1.0, min_edge=0.0):
    """Buy one share of every leg at a time, each at its next ask, while the guaranteed payout minus the cost of one
    set (prices plus fees) stays at least `min_edge`.

    legs: list of (asks, fee) with asks = [(price, size), ...] sorted from the best price and fee(price) per share.
    Returns (edge of the first set, dollars spent, profit) or None when a leg has no asks.
    """
    if not legs or any(not asks for asks, _ in legs):
        return None
    level = [0] * len(legs)
    left = [asks[0][1] for asks, _ in legs]
    first = payout - sum(asks[0][0] + fee(asks[0][0]) for asks, fee in legs)
    spent = profit = 0.0
    while all(i < len(asks) for i, (asks, _) in zip(level, legs)):
        cost = sum(asks[i][0] + fee(asks[i][0]) for i, (asks, fee) in zip(level, legs))
        if payout - cost < min_edge:
            break
        qty = min(left)
        spent += qty * cost
        profit += qty * (payout - cost)
        for j, (asks, _) in enumerate(legs):
            left[j] -= qty
            if left[j] <= 1e-9:
                level[j] += 1
                if level[j] < len(asks):
                    left[j] = asks[level[j]][1]
    return first, spent, profit
