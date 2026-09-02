"""Statistics for the E17 30-seed sweep, in numpy + stdlib only.

`scipy` is not in the pinned environment and this analysis is not a reason to
mutate a lockfile that the runtime measurements depend on. Wilcoxon signed-rank,
Holm-Bonferroni, BCa bootstrap and Spearman are short enough to implement
directly, and doing so keeps the analysis auditable.
"""

from __future__ import annotations

from statistics import NormalDist

import numpy as np

_N = NormalDist()
BOOTSTRAP_B = 10_000
BOOTSTRAP_SEED = 20260731


def _rank_with_ties(a: np.ndarray) -> np.ndarray:
    """Average ranks, 1-based."""
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), dtype=float)
    sorted_a = a[order]
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        ranks[order[i : j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return ranks


def wilcoxon_signed_rank(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """Two-sided paired signed-rank test, normal approximation.

    n = 30 after dropping zero differences is well past the range where the
    exact distribution matters; ties and continuity are both corrected. Zero
    differences are dropped (Wilcoxon's original handling) and the reduced n is
    reported, because with a saturating metric they are common and silently
    keeping them would inflate the test.
    """
    d = np.asarray(x, float) - np.asarray(y, float)
    d = d[np.isfinite(d)]
    n_all = len(d)
    d = d[d != 0.0]
    n = len(d)
    if n == 0:
        return {"n": 0, "n_dropped": n_all, "W": float("nan"), "z": float("nan"), "p": 1.0}
    r = _rank_with_ties(np.abs(d))
    w_plus = float(r[d > 0].sum())
    w_minus = float(r[d < 0].sum())
    w = min(w_plus, w_minus)
    mean_w = n * (n + 1) / 4.0
    _, counts = np.unique(np.abs(d), return_counts=True)
    tie_term = float(((counts**3 - counts).sum())) / 48.0
    var_w = n * (n + 1) * (2 * n + 1) / 24.0 - tie_term
    if var_w <= 0:
        return {"n": n, "n_dropped": n_all - n, "W": w, "z": float("nan"), "p": 1.0}
    z = (w - mean_w + 0.5) / np.sqrt(var_w)  # continuity correction toward the mean
    p = 2.0 * _N.cdf(z)
    return {
        "n": n,
        "n_dropped": n_all - n,
        "W": w,
        "W_plus": w_plus,
        "W_minus": w_minus,
        "z": float(z),
        "p": float(min(1.0, max(0.0, p))),
    }


def holm_bonferroni(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, dict[str, float]]:
    """Step-down Holm correction. Returns adjusted p and the reject flag."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out: dict[str, dict[str, float]] = {}
    running = 0.0
    for i, (key, p) in enumerate(items):
        adj = min(1.0, (m - i) * p)
        running = max(running, adj)  # enforce monotonicity
        out[key] = {"p_raw": p, "p_holm": running, "reject": bool(running < alpha)}
    return out


def bca_median_ci(
    d: np.ndarray, alpha: float = 0.05, b: int = BOOTSTRAP_B, seed: int = BOOTSTRAP_SEED
) -> dict[str, float]:
    """BCa bootstrap CI for the median of `d`.

    Degenerate inputs are reported as degenerate rather than forced to produce
    an interval: if every value is identical the median has no sampling spread
    and the honest answer is a point, not a fabricated width.
    """
    d = np.asarray(d, float)
    d = d[np.isfinite(d)]
    n = len(d)
    theta = float(np.median(d))
    if n < 2 or np.ptp(d) == 0.0:
        return {"median": theta, "lo": theta, "hi": theta, "degenerate": True, "n": n}

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(b, n))
    boot = np.median(d[idx], axis=1)

    prop = float((boot < theta).mean())
    if prop <= 0.0 or prop >= 1.0:
        # z0 undefined; fall back to the percentile interval and say so.
        lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
        return {
            "median": theta, "lo": float(lo), "hi": float(hi),
            "degenerate": False, "method": "percentile_fallback", "n": n,
        }
    z0 = _N.inv_cdf(prop)

    jack = np.array([np.median(np.delete(d, i)) for i in range(n)])
    dev = jack.mean() - jack
    denom = 6.0 * (float((dev**2).sum()) ** 1.5)
    a = 0.0 if denom == 0 else float((dev**3).sum()) / denom

    out = []
    for q in (alpha / 2, 1 - alpha / 2):
        zq = _N.inv_cdf(q)
        num = z0 + zq
        adj = z0 + num / (1.0 - a * num)
        out.append(100.0 * _N.cdf(adj))
    lo, hi = np.percentile(boot, [min(out), max(out)])
    return {
        "median": theta, "lo": float(lo), "hi": float(hi),
        "degenerate": False, "method": "BCa", "z0": z0, "a": a, "n": n,
    }


def spearman(x: np.ndarray, y: np.ndarray, b: int = BOOTSTRAP_B, seed: int = BOOTSTRAP_SEED) -> dict[str, float]:
    """Spearman rho with a permutation p-value.

    Permutation rather than the t approximation because the regime covariate is
    strongly clustered by policy and is nothing like normal.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = len(x)
    if n < 3 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return {"rho": float("nan"), "p": float("nan"), "n": n}
    rx, ry = _rank_with_ties(x), _rank_with_ties(y)
    rho = float(np.corrcoef(rx, ry)[0, 1])
    rng = np.random.default_rng(seed)
    null = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(min(b, 10_000))])
    p = float((np.abs(null) >= abs(rho)).mean())
    return {"rho": rho, "p": p, "n": n, "n_perm": len(null)}
