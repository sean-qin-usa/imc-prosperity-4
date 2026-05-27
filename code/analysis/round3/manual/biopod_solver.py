"""
P4 R3 Bio-Pod manual challenge solver.

Mechanics
---------
Reserves R uniform on {670, 675, ..., 920} (51 values, step 5).
Resale 920. Two bids (b1, b2). Per-gardener payoff:

  if b1 >= R:                          profit = (920 - b1)
  elif b1 < R <= b2 and b2 >  avg_b2:  profit = (920 - b2)
  elif b1 < R <= b2 and b2 == avg_b2:  profit = (920 - b2)
  elif b1 < R <= b2 and b2 <  avg_b2:  E[profit] = (920 - b2) * ((920-avg_b2)/(920-b2))**3
                                                = (920 - avg_b2)**3 / (920 - b2)**2
  else:                                no trade

The penalty term equals the prob of trade (always <=1 in this branch).

We compute per-gardener EV. Total PnL scales linearly in the unknown
gardener count N, so we just compare EV/gardener across (b1,b2) pairs.

Field model (the hard part)
---------------------------
avg_b2 is endogenous — depends on the whole field's choices. Given the
P3 R3 historical record (avg ended up at 287, ~3 above the naive math
optimum of 284), we model the field as a mixture of clusters and
sample avg_b2 from them.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass

RESERVES = np.arange(670, 925, 5)      # 670..920 inclusive, 51 values
SALE = 920


def per_gardener_ev(b1: float, b2: float, avg_b2: float) -> float:
    """Expected profit per gardener for one (b1,b2) pair given the
    realized field-mean of second bids."""
    profit = 0.0
    for R in RESERVES:
        if b1 >= R:
            profit += (SALE - b1)
        elif b2 >= R:
            if b2 > avg_b2:
                profit += (SALE - b2)
            elif b2 == avg_b2:
                profit += (SALE - b2)
            else:
                # penalty branch (b2 < avg_b2)
                if SALE - b2 <= 0:
                    continue  # can't profit
                penalty = ((SALE - avg_b2) / (SALE - b2)) ** 3
                profit += (SALE - b2) * penalty
        # else: no trade
    return profit / len(RESERVES)


def best_response_b2(b1: float, avg_b2: float, grid_step: int = 1) -> tuple[int, float]:
    """Best b2 for a given (b1, avg_b2)."""
    best_b2, best_ev = b1, -np.inf
    for b2 in range(int(b1) + 1, SALE):
        ev = per_gardener_ev(b1, b2, avg_b2)
        if ev > best_ev:
            best_ev, best_b2 = ev, b2
    return best_b2, best_ev


def grid_eval(avg_b2: float):
    """Return EV grid over (b1, b2) integer pairs given avg_b2."""
    b1_range = range(700, 870)
    b2_range = range(800, 920)
    grid = np.full((len(b1_range), len(b2_range)), -np.inf)
    for i, b1 in enumerate(b1_range):
        for j, b2 in enumerate(b2_range):
            if b2 <= b1:
                continue
            grid[i, j] = per_gardener_ev(b1, b2, avg_b2)
    return list(b1_range), list(b2_range), grid


# ---- Field model: mixture of clusters ---------------------------------

@dataclass
class FieldCluster:
    """A subset of the field with bid distribution (b1, b2)."""
    name: str
    weight: float                   # share of field
    b1_dist: dict                   # {bid: probability}
    b2_dist: dict


def normalize(d: dict) -> dict:
    s = sum(d.values())
    return {k: v / s for k, v in d.items()}


# Cluster priors built from:
# - Round 2 case study (4k post-filter survivors, AI cluster grows to ~12-18%)
# - P3 R3 historical: avg(b2) was ~287, only 3 over math-optimum 284.
#   Suggests most teams play near math-optimum, NOT nash-style.
# - In P4 R3 (more complex than P3 R3), AI/sim clusters likely 25-30% combined.
# - The naive "math optimum" answer for THIS problem (b1,b2) ignoring the
#   game theory is computed below; that's the AI-default cluster.

# Standalone math optimum analysis (printed when running):
#   - Best b1 (single bid): {790,795} tie at EV 63.73 per gardener
#   - Best b2 ignoring penalty (assume b1=790): 855 at EV 16.57
#   - "Nash" b2 fixed-point with b1=790: ~870

CLUSTERS = [
    # 1. Pure dropouts / very low - small in post-R2 survivor field
    FieldCluster(
        name="dropout_low",
        weight=0.04,
        b1_dist=normalize({0: 1, 700: 0.5, 750: 0.5}),
        b2_dist=normalize({0: 1, 800: 0.5, 850: 0.5}),
    ),
    # 2. AI default: math-optimum, no game theory
    #    Most LLMs solve b1 first then b2 unconditionally (peak 855)
    #    or with naive Nash (b2 ~ 870-880).
    FieldCluster(
        name="ai_default_math",
        weight=0.18,                  # large in post-filter R3 field
        b1_dist=normalize({790: 4, 795: 3, 800: 1.5, 785: 1}),
        b2_dist=normalize({855: 1, 860: 1.5, 870: 2.5, 880: 2, 875: 1.5, 850: 0.7, 865: 0.8}),
    ),
    # 3. AI nash-overbid: LLM that "thinks about it" pushes b2 up
    FieldCluster(
        name="ai_nash_overbid",
        weight=0.07,
        b1_dist=normalize({790: 2, 800: 1, 785: 1}),
        b2_dist=normalize({880: 2, 885: 2, 890: 2, 895: 1, 900: 0.7}),
    ),
    # 4. Nice-numbers humans (filtered down ~2x)
    FieldCluster(
        name="nice_numbers",
        weight=0.10,
        b1_dist=normalize({800: 3, 750: 1, 850: 1, 770: 1, 780: 1, 790: 1}),
        b2_dist=normalize({900: 3, 850: 1, 875: 1, 880: 1, 890: 1, 910: 0.7, 800: 0.5}),
    ),
    # 5. Hyper-conservative bank-the-floor
    FieldCluster(
        name="conservative",
        weight=0.05,
        b1_dist=normalize({780: 1, 790: 1, 800: 1, 770: 0.5}),
        b2_dist=normalize({900: 1, 910: 1, 905: 0.5, 895: 0.5}),
    ),
    # 6. Simulator cluster - did MC, found Nash-ish equilibrium ~870-890
    FieldCluster(
        name="simulator",
        weight=0.25,                  # grows in R3 post-filter
        b1_dist=normalize({780: 1.5, 785: 2, 790: 2.5, 795: 1.5, 800: 1}),
        b2_dist=normalize({870: 1.5, 875: 2, 880: 2.5, 885: 2, 890: 1.5, 895: 0.8}),
    ),
    # 7. "Just past the herd" sophisticates (uses our framework)
    FieldCluster(
        name="anti_cluster",
        weight=0.06,
        b1_dist=normalize({780: 1.5, 775: 1, 800: 1, 785: 1}),
        b2_dist=normalize({885: 1, 890: 1.5, 895: 1.5, 900: 1, 880: 0.7}),
    ),
    # 8. Overbidders / aggressive
    FieldCluster(
        name="overbid",
        weight=0.04,
        b1_dist=normalize({800: 1, 810: 1, 820: 1, 830: 0.5}),
        b2_dist=normalize({900: 1, 910: 1, 905: 1, 915: 0.5, 895: 0.5}),
    ),
    # 9. Mid-range guesser fill (smooth distribution)
    FieldCluster(
        name="midrange_guesser",
        weight=0.21,
        b1_dist=normalize({b: 1 for b in range(750, 821, 5)}),
        b2_dist=normalize({b: 1 for b in range(820, 911, 5)}),
    ),
]


def sample_field(rng, n_teams=4050, clusters=CLUSTERS):
    """Draw a sample field of (b1, b2) for n_teams teams."""
    # First assign each team to a cluster
    weights = np.array([c.weight for c in clusters])
    weights /= weights.sum()
    cluster_idx = rng.choice(len(clusters), size=n_teams, p=weights)
    b1s = np.empty(n_teams)
    b2s = np.empty(n_teams)
    for i, ci in enumerate(cluster_idx):
        c = clusters[ci]
        b1_keys = np.array(list(c.b1_dist.keys()))
        b1_p = np.array(list(c.b1_dist.values()))
        b2_keys = np.array(list(c.b2_dist.keys()))
        b2_p = np.array(list(c.b2_dist.values()))
        b1s[i] = rng.choice(b1_keys, p=b1_p)
        b2s[i] = rng.choice(b2_keys, p=b2_p)
    return b1s, b2s


def field_avg_b2_dist(rng, n_runs=2000, n_teams=4050, clusters=CLUSTERS):
    """Return distribution of avg_b2 across simulated fields."""
    avgs = np.empty(n_runs)
    for k in range(n_runs):
        _, b2s = sample_field(rng, n_teams, clusters)
        # Avg of NON-zero second bids? The problem says "the global mean of
        # second bids across all players." We interpret as all submitted
        # second bids including any zeros from dropouts.
        avgs[k] = np.mean(b2s)
    return avgs


# ---- Robust optimization over avg_b2 distribution ---------------------

def evaluate_strategy(b1, b2, avg_b2_samples):
    """Compute mean and percentile EVs across the avg_b2 distribution."""
    evs = np.array([per_gardener_ev(b1, b2, a) for a in avg_b2_samples])
    return {
        "mean": evs.mean(),
        "p05": np.percentile(evs, 5),
        "p25": np.percentile(evs, 25),
        "p50": np.percentile(evs, 50),
        "p75": np.percentile(evs, 75),
        "p95": np.percentile(evs, 95),
        "min": evs.min(),
        "std": evs.std(),
    }


def find_best_pairs(avg_b2_samples, top_k=20,
                    b1_grid=range(750, 815),
                    b2_grid=range(840, 915)):
    """Sweep integer (b1, b2) pairs, score by mean EV across field draws."""
    results = []
    for b1 in b1_grid:
        for b2 in b2_grid:
            if b2 <= b1:
                continue
            stats = evaluate_strategy(b1, b2, avg_b2_samples)
            results.append((b1, b2, stats))
    results.sort(key=lambda x: -x[2]["mean"])
    return results[:top_k]


def find_max_min_pairs(avg_b2_samples, top_k=20,
                       b1_grid=range(750, 815),
                       b2_grid=range(840, 915)):
    """Worst-case (max-min) optimization."""
    results = []
    for b1 in b1_grid:
        for b2 in b2_grid:
            if b2 <= b1:
                continue
            stats = evaluate_strategy(b1, b2, avg_b2_samples)
            results.append((b1, b2, stats))
    results.sort(key=lambda x: -x[2]["min"])
    return results[:top_k]


# ---- Main ------------------------------------------------------------

if __name__ == "__main__":
    rng = np.random.default_rng(42)
    print("=== P4 R3 Bio-Pod Manual: Solver ===\n")

    # Sanity: standalone b1 optimum
    print("Standalone b1 optima (no b2):")
    for b1 in [780, 785, 790, 795, 800, 805]:
        ev = per_gardener_ev(b1, b1, 0)
        print(f"  b1={b1}: EV = {ev:.3f}/gardener")
    print()

    # Sanity: best b2 ignoring penalty (avg_b2 set to 0 means full profit always)
    print("b2 grid given b1=790, avg_b2=0 (no penalty):")
    for b2 in range(840, 891, 5):
        ev = per_gardener_ev(790, b2, 0)
        print(f"  b2={b2}: total EV = {ev:.3f}")
    print()

    # Best response curves: given various avg_b2, best (b1,b2)
    print("Best response (b1=790 fixed) for various avg_b2:")
    for avg in [820, 840, 855, 870, 880, 885, 890, 895, 900, 910]:
        best_b2, best_ev = best_response_b2(790, avg, 1)
        print(f"  avg_b2={avg}: best b2 = {best_b2}, EV = {best_ev:.3f}")
    print()

    # Field simulation: avg_b2 distribution
    print("Simulating field of 4050 teams across 2000 draws...")
    avgs = field_avg_b2_dist(rng, n_runs=2000, n_teams=4050)
    print(f"  avg_b2 distribution: mean={avgs.mean():.2f}, std={avgs.std():.2f}")
    print(f"  percentiles: p05={np.percentile(avgs,5):.2f}, p25={np.percentile(avgs,25):.2f}, p50={np.percentile(avgs,50):.2f}, p75={np.percentile(avgs,75):.2f}, p95={np.percentile(avgs,95):.2f}")
    print()

    # Top-20 pairs by mean EV
    print("Top-20 (b1,b2) by mean EV across field draws:")
    top = find_best_pairs(avgs, top_k=20)
    for b1, b2, s in top:
        print(f"  ({b1},{b2}): mean={s['mean']:.3f}, p05={s['p05']:.3f}, p95={s['p95']:.3f}")
    print()

    # Worst-case
    print("Top-15 by max-min (worst case across field):")
    mm = find_max_min_pairs(avgs, top_k=15)
    for b1, b2, s in mm:
        print(f"  ({b1},{b2}): min={s['min']:.3f}, mean={s['mean']:.3f}")
    print()

    # Compare specific candidate sets
    print("Candidate showdown (per-gardener EV stats):")
    cands = [
        (790, 855, "naive AI default"),
        (795, 860, "math optimum joint"),
        (790, 870, "Nash-ish"),
        (790, 880, "above-Nash"),
        (790, 885, "above herd"),
        (780, 890, "RECIPE primary"),
        (775, 885, "RECIPE aggressive"),
        (780, 900, "RECIPE all-weather"),
        (785, 895, "RECIPE anti-cluster"),
        (785, 890, "anti-cluster v2"),
        (800, 890, "high b1 + above herd"),
        (800, 895, "high b1 + safer b2"),
        (790, 895, "790 + safer b2"),
        (795, 895, "795 + safer b2"),
        (795, 900, "795 + all-weather"),
    ]
    for b1, b2, label in cands:
        s = evaluate_strategy(b1, b2, avgs)
        print(f"  ({b1},{b2}) {label:25s}: mean={s['mean']:.3f}, p05={s['p05']:.3f}, p95={s['p95']:.3f}, min={s['min']:.3f}")
