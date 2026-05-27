"""Stress test: what if (775, 875) becomes a MAJOR AI cluster?

The user noted Codex returned (775, 875). If 10-40% of the 4k field
runs a strong AI agent with similar tooling, b2=875 itself becomes a
focal point. Question: does that pull avg_b2 above 875 and trigger
penalty for our pick?

Counter-clusters to consider:
  - "anti-Codex" teams who see (775, 875) and bid one past: (775, 876),
    (775, 880), (780, 880), etc.
  - All the prior AI clusters still exist: 855, 870, 880, 890.
"""
from __future__ import annotations

import numpy as np
from biopod_fast import ev_grid, evaluate


def avg_under_codex_cluster(codex_share, anti_codex_share, n_teams=4050,
                             n_runs=2000, seed=0):
    """Simulate avg_b2 under various Codex-cluster shares."""
    rng = np.random.default_rng(seed)
    out = np.empty(n_runs)
    for k in range(n_runs):
        # Codex cluster bids exactly 875
        n_codex = int(round(codex_share * n_teams))
        # Anti-codex cluster bids 876-885 (just past)
        n_anti = int(round(anti_codex_share * n_teams))
        # Remaining "other" field — mixture of historical clusters
        n_other = n_teams - n_codex - n_anti
        # Other field bids: AI defaults (855/870/880/890) + naive crowd
        # Weighted to give mean ~870 (consistent with AI-aware prior)
        other_keys = np.array([855, 860, 865, 870, 875, 880, 885, 890, 895, 900, 850])
        other_p = np.array([0.10, 0.07, 0.05, 0.18, 0.05, 0.20, 0.10, 0.13, 0.05, 0.04, 0.03])
        other_p /= other_p.sum()
        other_bids = rng.choice(other_keys, size=n_other, p=other_p)
        anti_keys = np.array([876, 880, 881, 885, 890])
        anti_p = np.array([0.30, 0.25, 0.20, 0.15, 0.10])
        anti_bids = rng.choice(anti_keys, size=n_anti, p=anti_p)
        codex_bids = np.full(n_codex, 875)
        all_bids = np.concatenate([codex_bids, anti_bids, other_bids])
        out[k] = all_bids.mean()
    return out


if __name__ == "__main__":
    print("=== Codex-cluster stress test ===\n")
    print("How does avg_b2 shift under various Codex-share scenarios?\n")

    # Sweep over codex cluster share
    print(f"  {'codex%':>7}  {'anti%':>6}  {'avg_mean':>9}  {'avg_p95':>8}  "
          f"{'EV(775,875)':>12}  {'EV(770,875)':>12}  {'EV(780,880)':>12}  {'EV(775,876)':>12}  {'EV(775,879)':>12}")
    for codex_share in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40]:
        for anti_share in [0.05, 0.15, 0.30]:
            if codex_share + anti_share >= 0.7: continue
            A = avg_under_codex_cluster(codex_share, anti_share, seed=int(codex_share*100+anti_share*10))
            ev_pick = evaluate(775, 875, A)['mean']
            ev_770_875 = evaluate(770, 875, A)['mean']
            ev_780_880 = evaluate(780, 880, A)['mean']
            ev_775_876 = evaluate(775, 876, A)['mean']
            ev_775_879 = evaluate(775, 879, A)['mean']
            print(f"  {codex_share:>7.2f}  {anti_share:>6.2f}  {A.mean():>9.3f}  "
                  f"{np.percentile(A,95):>8.3f}  {ev_pick:>12.3f}  {ev_770_875:>12.3f}  "
                  f"{ev_780_880:>12.3f}  {ev_775_876:>12.3f}  {ev_775_879:>12.3f}")

    # Worst-case extreme: 50% bid (775, 875), 0% anti, rest pushes higher
    print("\n=== EXTREME: 40% Codex cluster + 30% anti-Codex (just past 875) ===")
    A = avg_under_codex_cluster(0.40, 0.30, seed=99)
    print(f"avg_b2: mean={A.mean():.3f} p05={np.percentile(A,5):.2f} p95={np.percentile(A,95):.2f}")
    cands = [(775, 875), (770, 875), (780, 880), (775, 876), (775, 879),
             (775, 880), (775, 881), (775, 885), (780, 890), (775, 870),
             (775, 882), (775, 884)]
    for b1, b2 in cands:
        s = evaluate(b1, b2, A)
        print(f"  ({b1}, {b2}): mean={s['mean']:.3f}  p05={s['p05']:.3f}  p95={s['p95']:.3f}")

    # If half the field bids 875 specifically
    print("\n=== EXTREME: 50% Codex cluster, no anti, rest mid-range ===")
    A = avg_under_codex_cluster(0.50, 0.0, seed=100)
    print(f"avg_b2: mean={A.mean():.3f} p05={np.percentile(A,5):.2f} p95={np.percentile(A,95):.2f}")
    for b1, b2 in cands:
        s = evaluate(b1, b2, A)
        print(f"  ({b1}, {b2}): mean={s['mean']:.3f}  p05={s['p05']:.3f}  p95={s['p95']:.3f}")
