"""
Test "just past the AI cluster" bids.

Hypothesis: Modal LLM 2026 outputs for this exact problem are:
  - Naive math: (790, 855) — math optimum ignoring penalty
  - Nash naive:  (790, 870) — bid Nash fixed point
  - Buffer:      (790, 880) — buffer above avg
  - Careful:     (780, 890) — our own recipe, also a likely AI cluster

Test bidding ONE TICK PAST each cluster, on integer grid (not just step-5).
Also test "between cluster" bids like 876, 881, 886, 891.
"""
from __future__ import annotations

import numpy as np
from biopod_fast import (
    ev_grid, evaluate, CLUSTERS, normalize, _expand_dist,
    field_avg_b2_dist_fast,
)


def make_avg(mean, std, n=10000, seed=0):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(mean, std, n), 800, 915)


# Build "AI-cluster-aware" mixture: assume crowd has 4 modal AI clusters
# plus 30% non-AI fill.

def field_with_ai_clusters(n_runs=5000, n_teams=4050, seed=0,
                            ai_share=0.55):
    """Field where 'ai_share' of teams bid in AI clusters at:
       b2 ∈ {855, 870, 880, 890} with weights (10/25/30/35).
       The rest follow our default mixture.
    """
    rng = np.random.default_rng(seed)
    out = np.empty(n_runs)
    base_w = np.array([c[1] for c in CLUSTERS])
    base_w /= base_w.sum()

    ai_b2_keys = np.array([855, 870, 880, 890])
    ai_b2_p = np.array([0.10, 0.25, 0.30, 0.35])

    for k in range(n_runs):
        n_ai = int(round(ai_share * n_teams))
        n_other = n_teams - n_ai
        ai_bids = rng.choice(ai_b2_keys, size=n_ai, p=ai_b2_p)
        # other = our cluster mix
        other_bids = np.empty(n_other)
        cluster_idx = rng.choice(len(CLUSTERS), size=n_other, p=base_w)
        for ci in range(len(CLUSTERS)):
            mask = cluster_idx == ci
            n = mask.sum()
            if n == 0: continue
            keys, probs = _expand_dist(CLUSTERS[ci][3])
            other_bids[mask] = rng.choice(keys, size=n, p=probs)
        out[k] = (np.sum(ai_bids) + np.sum(other_bids)) / n_teams
    return out


if __name__ == "__main__":
    # Build AI-aware prior
    A_ai = field_with_ai_clusters(n_runs=2000, n_teams=4050, seed=42, ai_share=0.55)
    print(f"AI-cluster-aware avg_b2: mean={A_ai.mean():.3f} std={A_ai.std():.3f}")
    print(f"  pcts: p05={np.percentile(A_ai,5):.2f} p25={np.percentile(A_ai,25):.2f} p50={np.percentile(A_ai,50):.2f} p75={np.percentile(A_ai,75):.2f} p95={np.percentile(A_ai,95):.2f}")

    # Test fine-grained b2 around each AI anchor
    print("\nFine grid: b1=775, b2 in [855..900]:")
    print(f"  {'b2':>4}    mean    p05    p95    min   std")
    b1 = 775
    for b2 in range(855, 901):
        s = evaluate(b1, b2, A_ai)
        marker = ""
        if b2 in (855, 870, 880, 890): marker = " <- AI cluster"
        if b2 in (856, 871, 881, 891): marker = " <- one past"
        print(f"  {b2:>4}  {s['mean']:6.3f} {s['p05']:6.3f} {s['p95']:6.3f} {s['min']:6.3f} {s['std']:5.3f}{marker}")

    # Try different b1 anchors with the most promising b2 picks
    print("\n\nb1 sweep, b2 ∈ {870, 871, 875, 876, 880, 881, 890, 891}:")
    print(f"  {'b1':>4} {'b2':>4}    mean    p05    p95    min   std")
    for b1 in [765, 770, 775, 776, 780, 781, 785, 786, 790]:
        for b2 in [870, 871, 875, 876, 880, 881, 885, 886, 890, 891]:
            if b2 <= b1: continue
            s = evaluate(b1, b2, A_ai)
            print(f"  {b1:>4} {b2:>4}  {s['mean']:6.3f} {s['p05']:6.3f} {s['p95']:6.3f} {s['min']:6.3f} {s['std']:5.3f}")

    # Final showdown across two prior views
    print("\n\nFINAL SHOWDOWN: AI-aware vs default Dirichlet:")
    rng2 = np.random.default_rng(7)
    A_default = field_avg_b2_dist_fast(rng2, n_runs=10000, n_teams=4050)
    A_p3analog = make_avg(858, 4, seed=1)

    # Also a pessimistic "field went up" prior
    A_high = make_avg(880, 8, seed=8)

    cands = [
        (790, 855, "naive math"),
        (790, 871, "1 past Nash"),
        (790, 876, "1 past 875 cluster"),
        (790, 881, "1 past 880 cluster"),
        (790, 891, "1 past 890 cluster"),
        (775, 871, "lower b1 + 871"),
        (775, 876, "lower b1 + 876"),
        (775, 881, "lower b1 + 881"),
        (775, 886, "lower b1 + 886"),
        (775, 891, "lower b1 + 891"),
        (770, 870, "770/870 max-mean"),
        (770, 876, "770/876 robust"),
        (780, 890, "RECIPE primary"),
        (780, 891, "RECIPE primary +1"),
        (785, 876, "anti b1 cluster + anti b2"),
        (785, 881, "anti b1 + 881"),
        (785, 886, "anti b1 + 886"),
        (765, 871, "very low b1 + 871"),
        (765, 876, "very low b1 + 876"),
    ]
    print(f"  {'pair':>10} {'label':<25} {'AI-aware':>10} {'Default':>10} {'P3-analog':>10} {'High':>10}")
    for b1, b2, lbl in cands:
        e_ai = evaluate(b1, b2, A_ai)['mean']
        e_de = evaluate(b1, b2, A_default)['mean']
        e_p3 = evaluate(b1, b2, A_p3analog)['mean']
        e_hi = evaluate(b1, b2, A_high)['mean']
        avg = (e_ai + e_de + e_p3 + e_hi) / 4
        worst = min(e_ai, e_de, e_p3, e_hi)
        print(f"  ({b1},{b2}) {lbl:<25} {e_ai:>10.3f} {e_de:>10.3f} {e_p3:>10.3f} {e_hi:>10.3f}    avg={avg:6.3f}  worst={worst:6.3f}")
