"""V2 solver with FULL bid grid. Fixes the v1 mistake of restricting b1
to [770, 815] which missed the true 1/3, 2/3 joint optimum at (750, 835).

Field model now reflects bimodal crowd:
  - "Sequential" crowd (most humans / naive LLMs): solves b1 first then
    b2 conditionally → (790, 855) cluster.
  - "Joint" crowd (Codex / brute-force solvers): solves jointly →
    (750, 835) cluster.
  - "Buffer" crowd: adds Nash buffer → b2 in 870-890.
"""
from __future__ import annotations

import numpy as np

RESERVES = np.arange(670, 925, 5)
SALE = 920
n_le = lambda b: (RESERVES <= b).sum() if np.isscalar(b) else np.sum(RESERVES[None, :] <= np.asarray(b)[..., None], axis=-1)


def per_gardener_ev(b1, b2, A):
    n1 = n_le(b1) if np.isscalar(b1) else np.array([n_le(x) for x in np.atleast_1d(b1)])
    n_total = n_le(b2) if np.isscalar(b2) else np.array([n_le(x) for x in np.atleast_1d(b2)])
    n2 = np.maximum(n_total - n1, 0)
    b1, b2, A = float(b1), float(b2), np.asarray(A, dtype=float)
    pay1 = (SALE - b1) * n1
    safe = np.maximum(SALE - b2, 1e-9)
    mu = np.where(b2 >= A, 1.0, np.clip(((SALE-A)/safe)**3, 0, 1))
    pay2 = (SALE - b2) * mu * n2
    return (pay1 + pay2) / 51


def evaluate(b1, b2, A):
    evs = per_gardener_ev(b1, b2, A)
    return {"mean": float(evs.mean()),
            "p05":  float(np.percentile(evs, 5)),
            "p50":  float(np.percentile(evs, 50)),
            "p95":  float(np.percentile(evs, 95)),
            "min":  float(evs.min())}


# ---- Field models (updated to reflect bimodal crowd) -----------------

def make_field(seq_share, joint_share, buffer_share, n_runs=5000, n_teams=4050,
                seq_b2_mean=855, joint_b2_mean=835, buffer_b2_mean=880,
                seed=0):
    """Sample avg_b2 from a bimodal+buffer mixture."""
    rng = np.random.default_rng(seed)
    other_share = max(0, 1 - seq_share - joint_share - buffer_share)
    out = np.empty(n_runs)
    for k in range(n_runs):
        # Each team picks a cluster
        cluster_p = [seq_share, joint_share, buffer_share, other_share]
        # Team-level bid distributions within cluster (small jitter around modal value)
        cl = rng.choice(4, size=n_teams, p=cluster_p)
        bids = np.empty(n_teams)
        # Sequential cluster: tight peak at 855, some at 850/860
        seq_choices = np.array([845, 850, 855, 860, 865])
        seq_p = np.array([0.05, 0.20, 0.50, 0.20, 0.05])
        bids[cl==0] = rng.choice(seq_choices, size=(cl==0).sum(), p=seq_p)
        # Joint cluster: peak at 835, some at 830/840
        joint_choices = np.array([825, 830, 835, 840, 845])
        joint_p = np.array([0.10, 0.20, 0.40, 0.20, 0.10])
        bids[cl==1] = rng.choice(joint_choices, size=(cl==1).sum(), p=joint_p)
        # Buffer cluster: spread 870-895
        buf_choices = np.array([870, 875, 880, 885, 890, 895, 900])
        buf_p = np.array([0.10, 0.20, 0.25, 0.20, 0.15, 0.07, 0.03])
        bids[cl==2] = rng.choice(buf_choices, size=(cl==2).sum(), p=buf_p)
        # Other cluster: mid-range fill
        other_choices = np.arange(810, 916, 5)
        bids[cl==3] = rng.choice(other_choices, size=(cl==3).sum())
        out[k] = bids.mean()
    return out


def sweep_full(A, b1_grid=range(710, 815), b2_grid=range(800, 905)):
    """Full sweep over a wider b1 range to catch joint optimum."""
    rows = []
    for b1 in b1_grid:
        for b2 in b2_grid:
            if b2 <= b1: continue
            evs = per_gardener_ev(b1, b2, A)
            rows.append((b1, b2, float(evs.mean()),
                         float(np.percentile(evs, 5)),
                         float(np.percentile(evs, 95)),
                         float(evs.min()),
                         float(evs.std())))
    return rows


def topk(rows, idx, k=10, asc=False):
    return sorted(rows, key=lambda r: r[idx] * (-1 if not asc else 1))[:k]


# ---- Main -----------------------------------------------------------

if __name__ == "__main__":
    print("=== P4 R3 V2: full grid + bimodal crowd ===\n")

    # Test multiple field compositions
    field_models = [
        ("F1: 70%seq/15%joint/15%buf",  0.70, 0.15, 0.15),
        ("F2: 60%seq/25%joint/15%buf",  0.60, 0.25, 0.15),  # mid joint
        ("F3: 50%seq/35%joint/15%buf",  0.50, 0.35, 0.15),  # high joint
        ("F4: 30%seq/55%joint/15%buf",  0.30, 0.55, 0.15),  # joint dominant
        ("F5: 80%seq/5%joint/15%buf",   0.80, 0.05, 0.15),  # naive dominant
        ("F6: 60%seq/15%joint/25%buf",  0.60, 0.15, 0.25),  # buffer-heavy
    ]

    field_avgs = []
    for name, s, j, b in field_models:
        A = make_field(s, j, b, n_runs=2000, seed=hash(name) % 1000)
        field_avgs.append((name, A))
        print(f"{name}: avg_b2 mean={A.mean():.2f} std={A.std():.2f} "
              f"p05={np.percentile(A,5):.1f} p95={np.percentile(A,95):.1f}")
    print()

    # For each field model, find top picks
    cands = [
        (750, 835, "Joint Nash (Codex)"),
        (750, 836, "Joint Nash + 1"),
        (755, 840, "near-joint"),
        (760, 855, "Seq+joint hybrid"),
        (760, 856, "hybrid + 1"),
        (765, 855, "balanced"),
        (770, 855, "balanced higher b1"),
        (770, 860, "above-seq"),
        (770, 865, "buffer"),
        (770, 870, "above buffer"),
        (770, 871, "above buffer + 1"),
        (770, 875, "775/875 alt"),
        (775, 855, "single-plateau b1, seq b2"),
        (775, 860, ""),
        (775, 865, ""),
        (775, 870, ""),
        (775, 871, "above 870 cluster"),
        (775, 875, "MY OLD PICK"),
        (775, 876, "anti-cluster"),
        (775, 880, ""),
        (775, 885, ""),
        (780, 855, ""),
        (780, 860, ""),
        (780, 870, ""),
        (780, 880, ""),
        (780, 890, "all-weather"),
        (785, 855, ""),
        (790, 855, "naive sequential"),
        (790, 870, "naive Nash"),
    ]

    print("=" * 130)
    print("Cross-field EV table (mean per gardener):")
    header = f"{'pair':>10} {'label':<30}"
    for name, _ in field_avgs:
        header += f" {name[:8]:>9}"
    header += f" {'AVG':>7} {'MIN':>7}"
    print(header)
    print("-" * 130)
    rows_for_summary = []
    for b1, b2, lbl in cands:
        line = f"{f'({b1},{b2})':>10} {lbl:<30}"
        means = []
        for name, A in field_avgs:
            m = float(per_gardener_ev(b1, b2, A).mean())
            means.append(m)
            line += f" {m:>9.2f}"
        avg = sum(means)/len(means)
        mn = min(means)
        line += f" {avg:>7.2f} {mn:>7.2f}"
        print(line)
        rows_for_summary.append((b1, b2, lbl, avg, mn, means))

    print("\n=== Best pick by AVERAGE across F1..F6 ===")
    rows_for_summary.sort(key=lambda r: -r[3])
    for b1, b2, lbl, avg, mn, _ in rows_for_summary[:8]:
        print(f"  ({b1},{b2}) {lbl:<30}  avg={avg:.3f}  min={mn:.3f}")

    print("\n=== Best pick by WORST-CASE across F1..F6 ===")
    rows_for_summary.sort(key=lambda r: -r[4])
    for b1, b2, lbl, avg, mn, _ in rows_for_summary[:8]:
        print(f"  ({b1},{b2}) {lbl:<30}  avg={avg:.3f}  min={mn:.3f}")

    # Full sweep under "central" prior (F2)
    print("\n=== Full grid sweep under F2 prior (avg≈848) ===")
    A_central = field_avgs[1][1]
    rows = sweep_full(A_central)
    print("Top-15 by mean EV:")
    for r in topk(rows, 2, 15):
        b1, b2, m, p05, p95, mn, st = r
        print(f"  ({b1},{b2}) mean={m:.3f} p05={p05:.3f} p95={p95:.3f} std={st:.3f}")
    print("Top-15 by min EV:")
    for r in topk(rows, 5, 15):
        b1, b2, m, p05, p95, mn, st = r
        print(f"  ({b1},{b2}) mean={m:.3f} p05={p05:.3f} p95={p95:.3f} min={mn:.3f}")
