"""Vectorized P4 R3 Bio-Pod solver.

Per-gardener EV(b1, b2, A) where A=avg_b2:

  Let n1 = #{R : R <= b1},  n2 = #{R : b1 < R <= b2}.
  Profit/gardener = [ n1*(920-b1) + n2*(920-b2) * mu(b2,A) ] / 51
  where mu(b2,A) = 1 if b2 >= A else ((920-A)/(920-b2))^3.
"""
from __future__ import annotations

import numpy as np

RESERVES = np.arange(670, 925, 5)        # 51 values
SALE = 920


def n_le(b):
    """Number of reserves <= b. Vectorizable in b."""
    b = np.asarray(b)
    return np.sum(RESERVES[None, :] <= b[..., None], axis=-1)


def ev_grid(b1, b2, A):
    """EV per gardener. b1, b2, A may be scalar or numpy arrays (broadcastable)."""
    b1 = np.asarray(b1, dtype=float)
    b2 = np.asarray(b2, dtype=float)
    A  = np.asarray(A,  dtype=float)
    n1 = n_le(b1)
    n2_total = n_le(b2)
    n2 = n2_total - n1
    n2 = np.maximum(n2, 0)

    pay1 = (SALE - b1) * n1
    eps = 1e-9
    safe_denom = np.maximum(SALE - b2, eps)
    mu = np.where(b2 >= A, 1.0, ((SALE - A) / safe_denom) ** 3)
    # Clip mu to [0,1] for the penalty branch (safety)
    mu = np.where(b2 >= A, 1.0, np.clip(mu, 0.0, 1.0))
    pay2 = (SALE - b2) * mu * n2
    return (pay1 + pay2) / len(RESERVES)


# ---- Field model -----------------------------------------------------

def _expand_dist(d):
    keys = np.array(list(d.keys()), dtype=float)
    probs = np.array(list(d.values()), dtype=float)
    probs /= probs.sum()
    return keys, probs


def normalize(d): return {k: v/sum(d.values()) for k, v in d.items()}

CLUSTERS = [
    # Each: (name, weight, b1_dist, b2_dist)
    # Calibration based on:
    # - R2 case study: post-filter survivors (~4050), AI cluster grows to ~12-18%
    # - P3 R3: avg_b2=287 was only 3 over math optimum 284 (90% of teams math-only)
    # - P4 R3 is 2 years later, AIs are smarter, sim cluster grows
    ("dropout_low", 0.04,
        normalize({0: 0.4, 700: 0.3, 750: 0.3}),
        normalize({0: 0.4, 800: 0.3, 850: 0.3})),
    # AI default — math optimum, no game theory. Big cluster at b1∈{790,795},
    # b2 either at unconstrained peak (855) or naive Nash (~870-880).
    ("ai_default_math", 0.18,
        normalize({785: 1, 790: 4, 795: 3, 800: 1.5}),
        normalize({855: 1, 860: 1.5, 865: 1.2, 870: 2.5, 875: 1.5, 880: 1.5, 850: 0.7, 890: 0.5})),
    # AI nash-overbid
    ("ai_nash_overbid", 0.07,
        normalize({785: 1, 790: 2, 800: 1}),
        normalize({880: 2, 885: 2, 890: 2, 895: 1, 900: 0.5, 875: 1})),
    # Nice-numbers humans (post-filter shrinkage applied)
    ("nice_numbers", 0.10,
        normalize({770: 1, 780: 1, 790: 1, 800: 3, 850: 1, 750: 1}),
        normalize({800: 0.5, 850: 1, 875: 1, 880: 1, 890: 1, 900: 3, 910: 0.7, 920: 0.3})),
    # Hyper-conservative (bank the floor on b1, take 920 ceiling on b2)
    ("conservative", 0.05,
        normalize({770: 0.5, 780: 1, 790: 1, 800: 1}),
        normalize({895: 0.5, 900: 1.5, 905: 0.5, 910: 1, 915: 0.5, 920: 0.5})),
    # Simulator cluster — runs MC, finds Nash-ish equilibrium ~870-890
    ("simulator", 0.25,
        normalize({780: 1.5, 785: 2, 790: 2.5, 795: 1.5, 800: 1}),
        normalize({855: 0.5, 865: 0.8, 870: 1.5, 875: 2, 880: 2.5, 885: 2, 890: 1.5, 895: 0.8})),
    # "Just past the herd" sophisticates
    ("anti_cluster", 0.06,
        normalize({775: 1, 780: 1.5, 785: 1, 800: 1}),
        normalize({880: 0.7, 885: 1, 890: 1.5, 895: 1.5, 900: 1})),
    # Aggressive overbidders
    ("overbid", 0.04,
        normalize({800: 1, 810: 1, 820: 1, 830: 0.5}),
        normalize({895: 0.5, 900: 1, 905: 1, 910: 1, 915: 0.5})),
    # Mid-range fill
    ("midrange_guesser", 0.21,
        normalize({b: 1.0 for b in range(750, 821, 5)}),
        normalize({b: 1.0 for b in range(820, 911, 5)})),
]


def field_avg_b2_dist(rng, n_runs=5000, n_teams=4050, clusters=CLUSTERS):
    """Vectorized: return n_runs samples of avg_b2 across simulated fields."""
    weights = np.array([c[1] for c in clusters])
    weights /= weights.sum()
    out = np.empty(n_runs)
    for k in range(n_runs):
        cluster_idx = rng.choice(len(clusters), size=n_teams, p=weights)
        b2s = np.empty(n_teams)
        for ci in range(len(clusters)):
            mask = cluster_idx == ci
            n = mask.sum()
            if n == 0: continue
            keys, probs = _expand_dist(clusters[ci][3])
            b2s[mask] = rng.choice(keys, size=n, p=probs)
        out[k] = b2s.mean()
    return out


def field_avg_b2_dist_fast(rng, n_runs=5000, n_teams=4050, clusters=CLUSTERS):
    """Even faster — directly compute mean of mixture at each draw using LLN.

    For large n_teams, avg_b2 ≈ mixture mean + N(0, std/sqrt(n)).
    But we want to model parameter uncertainty too — use a Dirichlet over
    cluster weights to allow our priors to be wrong.
    """
    cluster_means = np.array([
        sum(k * v for k, v in c[3].items()) / sum(c[3].values())
        for c in clusters
    ])
    cluster_stds = np.array([
        (sum(k**2 * v for k, v in c[3].items()) / sum(c[3].values())
         - (sum(k * v for k, v in c[3].items()) / sum(c[3].values()))**2) ** 0.5
        for c in clusters
    ])
    base_w = np.array([c[1] for c in clusters])
    base_w /= base_w.sum()

    # Dirichlet concentration — looser = more weight uncertainty
    alpha = base_w * 50.0  # moderate uncertainty
    out = np.empty(n_runs)
    for k in range(n_runs):
        w = rng.dirichlet(alpha)
        # mean across mixture
        mu = (w * cluster_means).sum()
        # variance of mixture mean (bigger than within-cluster)
        within_var = (w * cluster_stds**2).sum()
        between_var = (w * (cluster_means - mu)**2).sum()
        var_per_team = within_var + between_var
        sample_se = np.sqrt(var_per_team / n_teams)
        out[k] = mu + rng.normal() * sample_se
    return out


# ---- Strategy evaluation ---------------------------------------------

def evaluate(b1, b2, avg_samples):
    evs = ev_grid(b1, b2, avg_samples)
    return {
        "mean": float(evs.mean()),
        "p05":  float(np.percentile(evs, 5)),
        "p25":  float(np.percentile(evs, 25)),
        "p50":  float(np.percentile(evs, 50)),
        "p75":  float(np.percentile(evs, 75)),
        "p95":  float(np.percentile(evs, 95)),
        "min":  float(evs.min()),
        "std":  float(evs.std()),
    }


def sweep(avg_samples, b1_grid=range(770, 815), b2_grid=range(840, 920)):
    rows = []
    A = avg_samples
    for b1 in b1_grid:
        for b2 in b2_grid:
            if b2 <= b1: continue
            evs = ev_grid(b1, b2, A)
            rows.append((b1, b2, evs.mean(), float(np.percentile(evs,5)),
                         float(np.percentile(evs,95)), float(evs.min()),
                         float(evs.std())))
    return rows


def topk_by(rows, key_idx, k=20, descending=True):
    return sorted(rows, key=lambda r: -r[key_idx] if descending else r[key_idx])[:k]


# ---- Main -----------------------------------------------------------

if __name__ == "__main__":
    rng = np.random.default_rng(42)
    print("=== P4 R3 Bio-Pod Solver (vectorized) ===\n")

    # Cluster summary
    print("Field clusters and per-cluster avg_b2 means:")
    for name, wgt, b1d, b2d in CLUSTERS:
        b2mean = sum(k * v for k, v in b2d.items()) / sum(b2d.values())
        b1mean = sum(k * v for k, v in b1d.items()) / sum(b1d.values())
        print(f"  {name:20s} wt={wgt:.3f}  b1_mean={b1mean:6.1f}  b2_mean={b2mean:6.1f}")
    print()

    # Field MC (sampling-based)
    print("Sampling 3000 fields (n=4050 teams)...")
    avgs_sample = field_avg_b2_dist(rng, n_runs=3000, n_teams=4050)
    print(f"  avg_b2 dist: mean={avgs_sample.mean():.3f}, std={avgs_sample.std():.3f}")
    print(f"  pcts: p05={np.percentile(avgs_sample,5):.2f}  p25={np.percentile(avgs_sample,25):.2f}  p50={np.percentile(avgs_sample,50):.2f}  p75={np.percentile(avgs_sample,75):.2f}  p95={np.percentile(avgs_sample,95):.2f}\n")

    # Wider distribution with Dirichlet weight uncertainty
    rng2 = np.random.default_rng(7)
    avgs_dirichlet = field_avg_b2_dist_fast(rng2, n_runs=10000, n_teams=4050)
    print(f"Dirichlet-weighted (parameter uncertainty):")
    print(f"  avg_b2 dist: mean={avgs_dirichlet.mean():.3f}, std={avgs_dirichlet.std():.3f}")
    print(f"  pcts: p05={np.percentile(avgs_dirichlet,5):.2f}  p25={np.percentile(avgs_dirichlet,25):.2f}  p50={np.percentile(avgs_dirichlet,50):.2f}  p75={np.percentile(avgs_dirichlet,75):.2f}  p95={np.percentile(avgs_dirichlet,95):.2f}\n")

    # Use the wider one
    A_samples = avgs_dirichlet

    # Full sweep
    print("Sweeping (b1, b2) pairs in [770..814] x [840..919]:")
    rows = sweep(A_samples)
    print(f"  total pairs: {len(rows)}")
    print()

    print("Top-20 by mean EV:")
    print(f"  {'b1':>4} {'b2':>4}   mean    p05    p95    min   std")
    for r in topk_by(rows, key_idx=2, k=20):
        b1, b2, m, p05, p95, mn, st = r
        print(f"  {b1:>4} {b2:>4}  {m:6.3f} {p05:6.3f} {p95:6.3f} {mn:6.3f} {st:5.3f}")
    print()

    print("Top-15 by min EV (max-min worst case):")
    print(f"  {'b1':>4} {'b2':>4}   mean    p05    p95    min   std")
    for r in topk_by(rows, key_idx=5, k=15):
        b1, b2, m, p05, p95, mn, st = r
        print(f"  {b1:>4} {b2:>4}  {m:6.3f} {p05:6.3f} {p95:6.3f} {mn:6.3f} {st:5.3f}")
    print()

    print("Top-15 by p05 (5%-tile worst case):")
    print(f"  {'b1':>4} {'b2':>4}   mean    p05    p95    min   std")
    for r in topk_by(rows, key_idx=3, k=15):
        b1, b2, m, p05, p95, mn, st = r
        print(f"  {b1:>4} {b2:>4}  {m:6.3f} {p05:6.3f} {p95:6.3f} {mn:6.3f} {st:5.3f}")
    print()

    # Showdown
    print("Candidate showdown:")
    cands = [
        (790, 855, "AI default unconstrained"),
        (790, 870, "AI Nash naive"),
        (790, 875, "above-AI by 5"),
        (790, 880, "above herd"),
        (790, 885, "above sim cluster"),
        (790, 890, "above sim cluster +5"),
        (790, 895, "approach all-weather"),
        (790, 900, "all-weather"),
        (785, 880, "anti-cluster b1"),
        (785, 885, "anti-cluster b1 +5"),
        (785, 890, "anti-cluster v2"),
        (785, 895, "anti-cluster v3"),
        (780, 885, "below b1 herd + above b2"),
        (780, 890, "RECIPE primary"),
        (780, 895, "RECIPE midweather"),
        (780, 900, "RECIPE all-weather"),
        (775, 885, "RECIPE aggressive"),
        (775, 890, "aggressive +5"),
        (795, 885, "above b1 + above sim"),
        (795, 890, "above b1 + above sim +5"),
        (800, 895, "high b1 + above-Nash"),
        (800, 900, "high b1 + all-weather"),
    ]
    print(f"  {'b1':>4} {'b2':>4} {'label':28s}    mean    p05    p95    min   std")
    for b1, b2, lbl in cands:
        s = evaluate(b1, b2, A_samples)
        print(f"  {b1:>4} {b2:>4} {lbl:28s}   {s['mean']:6.3f} {s['p05']:6.3f} {s['p95']:6.3f} {s['min']:6.3f} {s['std']:5.3f}")
