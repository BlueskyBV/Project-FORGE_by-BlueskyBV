"""How sure a measured error rate is.

"No wrong parts in 30" doesn't mean the rate is zero. It means the rate is
probably below some bound, and the bound depends on how many parts were
graded. Every rate V2 reports carries its 95% upper bound (plan, section 1.3),
computed here exactly rather than from a normal approximation, which is wrong
precisely where it matters: few failures, small samples.

For ``k`` failures in ``n`` trials, the one-sided Clopper-Pearson upper bound
at confidence ``c`` is the rate ``p`` at which seeing ``k`` or fewer failures
would have probability ``1 - c``. With no failures it has a closed form,
``1 - (1 - c) ** (1 / n)``, which is close to the "rule of three", ``3 / n``.

>>> round(upper_bound(0, 300), 5)
0.00994
>>> trials_needed(0.01)
299
"""

from __future__ import annotations

import math

__all__ = ["binomial_cdf", "trials_needed", "upper_bound"]


def binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p), summed in log space."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValueError("n must be a whole number, 0 or more")
    if not 0.0 <= p <= 1.0:  # also refuses NaN
        raise ValueError("p must be a probability")
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    log_p, log_q = math.log(p), math.log1p(-p)
    terms = [
        math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
        + i * log_p + (n - i) * log_q
        for i in range(k + 1)
    ]  # fmt: skip
    peak = max(terms)
    return min(1.0, math.exp(peak) * math.fsum(math.exp(t - peak) for t in terms))


def _check(failures: int, trials: int, confidence: float) -> None:
    for name, number in (("failures", failures), ("trials", trials)):
        if isinstance(number, bool) or not isinstance(number, int):
            raise TypeError(f"{name} must be a whole number")
    if trials < 1:
        raise ValueError("a bound needs at least one trial")
    if not 0 <= failures <= trials:
        raise ValueError("failures must be between 0 and the number of trials")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1")


def upper_bound(failures: int, trials: int, confidence: float = 0.95) -> float:
    """The one-sided upper confidence bound on a failure rate.

    >>> round(upper_bound(1, 474), 4)
    0.01
    """
    _check(failures, trials, confidence)
    if failures == trials:
        return 1.0
    alpha = 1.0 - confidence
    if failures == 0:
        return -math.expm1(math.log(alpha) / trials)
    low, high = 0.0, 1.0
    for _ in range(200):  # bisection: the CDF falls as p rises
        mid = (low + high) / 2
        if binomial_cdf(failures, trials, mid) > alpha:
            low = mid
        else:
            high = mid
        if high - low < 1e-15:
            break
    return high


def trials_needed(rate: float, failures: int = 0, confidence: float = 0.95) -> int:
    """The fewest trials whose upper bound is at most ``rate``, given ``failures``.

    >>> trials_needed(0.01, failures=1)
    473
    """
    if not 0.0 < rate < 1.0:
        raise ValueError("rate must be strictly between 0 and 1")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1")
    if isinstance(failures, bool) or not isinstance(failures, int) or failures < 0:
        raise ValueError("failures must be a whole number, 0 or more")
    if failures == 0:
        guess = math.ceil(math.log(1.0 - confidence) / math.log1p(-rate))
        n = max(1, guess - 2)
    else:
        n = failures + 1
        while upper_bound(failures, n, confidence) > rate:
            n *= 2
        low, high = n // 2, n
        while low + 1 < high:
            mid = (low + high) // 2
            if upper_bound(failures, mid, confidence) > rate:
                low = mid
            else:
                high = mid
        n = max(failures + 1, low)
    while upper_bound(failures, n, confidence) > rate:
        n += 1
    return n
