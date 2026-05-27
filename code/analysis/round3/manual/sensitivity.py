"""Sensitivity analysis: how does the optimum change under alternative
priors over avg_b2?

Scenarios:
  S1 = "P3 R3 analog": crowd ~3 above naive math optimum.
       Naive math b2 (single bid) = 855; so avg_b2 ~ 858.
  S2 = "naive AI" — most teams just paste LLM answer at math optimum 855.
  S3 = "default" — our calibrated mixture (mean 862).
  S4 = "sophisticated" — avg drifts up to 875 (teams learned).
  S5 = "very sophisticated" — avg = 885.
  S6 = "wide tail" — heavy right tail (teams overbid in panic).
"""
from __future__ import annotations

import numpy as np
from biopod_fast import (
    ev_grid, evaluate, sweep, topk_by, CLUSTERS, normalize, _expand_dist,
    field_avg_b2_dist, field_avg_b2_dist_fast,
)


def make_avg_samples(name, mean, std, n=10000, seed=0):
    rng = np.random.default_rng(seed)
    # Truncated normal in [840, 915]
    x = rng.normal(mean, std, n)
    x = np.clip(x, 800, 915)
    return x


def show_scenario(name, A, top_n=10):
    print(f"\n=== {name} ===")
    print(f"avg_b2: mean={A.mean():.2f} std={A.std():.2f} p05={np.percentile(A,5):.1f} p95={np.percentile(A,95):.1f}")
    rows = sweep(A, b1_grid=range(770, 805), b2_grid=range(840, 905))
    print(f"Top-{top_n} by mean EV:")
    for r in topk_by(rows, key_idx=2, k=top_n):
        b1, b2, m, p05, p95, mn, st = r
        print(f"  ({b1}, {b2}) mean={m:.3f}  p05={p05:.3f}  p95={p95:.3f}  min={mn:.3f}  std={st:.3f}")
    print(f"Top-{top_n} by p05 (worst-case):")
    for r in topk_by(rows, key_idx=3, k=top_n):
        b1, b2, m, p05, p95, mn, st = r
        print(f"  ({b1}, {b2}) mean={m:.3f}  p05={p05:.3f}  p95={p95:.3f}  min={mn:.3f}  std={st:.3f}")
    return rows


CANDIDATES = [
    (770, 870), (770, 875), (770, 876), (770, 880),
    (775, 870), (775, 875), (775, 880), (775, 883), (775, 885),
    (780, 870), (780, 875), (780, 876), (780, 880), (780, 883), (780, 885), (780, 890),
    (785, 875), (785, 880), (785, 883), (785, 885), (785, 890),
    (790, 855), (790, 870), (790, 875), (790, 880), (790, 885), (790, 890),
    (795, 880), (795, 885), (795, 890),
    (800, 880), (800, 890), (800, 895),
]


def candidate_table(scenarios):
    """Cross-scenario robustness table."""
    rows = []
    for b1, b2 in CANDIDATES:
        line = [(b1, b2)]
        for name, A in scenarios:
            evs = ev_grid(b1, b2, A)
            line.append((name, float(evs.mean()), float(np.percentile(evs, 5))))
        rows.append(line)
    return rows


if __name__ == "__main__":
    rng = np.random.default_rng(42)

    # Build scenarios
    scenarios = []

    # S1: P3 R3 analog — crowd just above naive
    A1 = make_avg_samples("p3r3_analog", mean=858, std=4, seed=1)
    show_scenario("S1: P3 R3 analog (avg≈858, low spread)", A1)
    scenarios.append(("S1_p3analog", A1))

    # S2: AI-anchor at 855
    A2 = make_avg_samples("ai_anchor_855", mean=855, std=6, seed=2)
    show_scenario("S2: AI anchor (avg≈855)", A2)
    scenarios.append(("S2_ai855", A2))

    # S3: our calibrated default
    rng3 = np.random.default_rng(7)
    A3 = field_avg_b2_dist_fast(rng3, n_runs=10000, n_teams=4050)
    show_scenario("S3: Calibrated default (Dirichlet mixture)", A3)
    scenarios.append(("S3_default", A3))

    # S4: sophisticated push to 875
    A4 = make_avg_samples("soph_875", mean=875, std=8, seed=4)
    show_scenario("S4: Sophisticated avg≈875", A4)
    scenarios.append(("S4_soph875", A4))

    # S5: very sophisticated 885
    A5 = make_avg_samples("very_soph_885", mean=885, std=8, seed=5)
    show_scenario("S5: Very sophisticated avg≈885", A5)
    scenarios.append(("S5_vsoph885", A5))

    # S6: heavy tail — 70% at 860, 25% at 880, 5% at 905
    rng6 = np.random.default_rng(6)
    cluster_pick = rng6.choice([860, 880, 905], size=10000, p=[0.7, 0.25, 0.05])
    A6 = cluster_pick + rng6.normal(0, 4, 10000)
    show_scenario("S6: Bimodal heavy-tail (70/25/5 at 860/880/905)", A6)
    scenarios.append(("S6_heavytail", A6))

    # Cross-scenario candidate table
    print("\n\n========== CROSS-SCENARIO TABLE (mean EV / p05 EV) ==========")
    print(f"{'pair':>10}  " + "  ".join(f"{name[:14]:>14}" for name, _ in scenarios))
    for line in candidate_table(scenarios):
        b1, b2 = line[0]
        cells = []
        for name, m, p05 in line[1:]:
            cells.append(f"{m:5.2f}/{p05:5.2f}")
        print(f"  ({b1},{b2})  " + "   ".join(f"{c:>13}" for c in cells))

    # Aggregate (max worst-case across scenarios)
    print("\n\n========== AGGREGATE (worst mean across S1..S6) ==========")
    rows = []
    for b1, b2 in CANDIDATES:
        means = []
        for _, A in scenarios:
            evs = ev_grid(b1, b2, A)
            means.append(float(evs.mean()))
        rows.append((b1, b2, min(means), sum(means)/len(means), max(means)))
    rows.sort(key=lambda r: -r[2])  # worst-case (max-min)
    print(f"  {'pair':>10}  {'min':>7}  {'mean':>7}  {'max':>7}")
    for r in rows[:15]:
        b1, b2, mn, avg, mx = r
        print(f"  ({b1},{b2})  {mn:7.3f}  {avg:7.3f}  {mx:7.3f}")
    print("\nAggregate (max average across all scenarios):")
    rows.sort(key=lambda r: -r[3])
    for r in rows[:15]:
        b1, b2, mn, avg, mx = r
        print(f"  ({b1},{b2})  {mn:7.3f}  {avg:7.3f}  {mx:7.3f}")
