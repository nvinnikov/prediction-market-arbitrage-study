"""Cluster bootstrap and the one-line summaries used in the results."""
import collections
import random
import statistics


def cluster_bootstrap(values, clusters, n=2000, seed=1):
    """90% interval of the mean, resampling whole clusters (weeks) with replacement. Returns (low, high, clusters)."""
    groups = collections.defaultdict(list)
    for v, c in zip(values, clusters):
        groups[c].append(v)
    keys = sorted(groups)
    rnd = random.Random(seed)
    means = []
    for _ in range(n):
        sample = [v for k in (rnd.choice(keys) for _ in keys) for v in groups[k]]
        means.append(sum(sample) / len(sample))
    means.sort()
    return means[int(.05 * n)], means[int(.95 * n)], len(keys)


def summary(values, clusters):
    """Mean, interval, halves split at the middle cluster, share of winners; None for fewer than 10 values."""
    if len(values) < 10:
        return None
    lo, hi, k = cluster_bootstrap(values, clusters)
    order = sorted(set(clusters))
    mid = order[len(order) // 2]
    first = [v for v, c in zip(values, clusters) if c < mid] or [0]
    second = [v for v, c in zip(values, clusters) if c >= mid] or [0]
    return dict(n=len(values), clusters=k, mean=statistics.mean(values), lo=lo, hi=hi, sd=statistics.pstdev(values),
                first=statistics.mean(first), second=statistics.mean(second),
                win=sum(v > 0 for v in values) / len(values))


def cents(s):
    """Summary as a line, in cents per $1 contract."""
    if not s:
        return "too few"
    return "n=%-5d weeks %-3d mean %+.2fc [%+.2f, %+.2f] halves %+.2f / %+.2f win %d%%" % (
        s["n"], s["clusters"], 100 * s["mean"], 100 * s["lo"], 100 * s["hi"], 100 * s["first"], 100 * s["second"],
        round(100 * s["win"]))
