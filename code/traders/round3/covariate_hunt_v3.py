"""
Covariate hunt v3 — final pressure test.

Now we know cross-product correlations are ≤ 0.05 and unstable across
days. Final tests before declaring HYDROGEL independent:

  T1 — Out-of-sample CV: fit a linear predictor of ΔH using ALL
       cross-product features on day 0+1, score on day 2 (and rotate).
       If R²_oos > 0 we have a real signal; if ≤ 0 we don't.
  T2 — Information coefficient: use ΔX as a sign-only signal,
       check if hit rate on next 5 ticks > 50% (binomial test).
  T3 — Hour-of-day buckets (10 buckets): is there a stable diurnal
       structure that ANY cross product taps into?
  T4 — Aggregate composite: Σ_p sign(Δp) → predicts ΔH? (basket index)
  T5 — Spread of HYDROGEL bid/ask vs VEV/VEV_voucher events
"""
from __future__ import annotations
import csv, math
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

DATA_DIR = Path("/Users/sean_tsu_/Downloads/prosperity/IMCP2026/data/round3")
DAYS = [0, 1, 2]
PRODS = [
    "VELVETFRUIT_EXTRACT",
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", "VEV_5200",
    "VEV_5300", "VEV_5400", "VEV_5500",
]

def load_prices(day):
    rows = defaultdict(list)
    fp = DATA_DIR / f"prices_round_3_day_{day}.csv"
    with fp.open() as fh:
        rd = csv.DictReader(fh, delimiter=";")
        for r in rd:
            try:
                p = r["product"]; ts = int(r["timestamp"])
                bid1 = float(r["bid_price_1"]) if r["bid_price_1"] else None
                ask1 = float(r["ask_price_1"]) if r["ask_price_1"] else None
                bv1 = float(r["bid_volume_1"]) if r["bid_volume_1"] else 0.0
                av1 = float(r["ask_volume_1"]) if r["ask_volume_1"] else 0.0
                mid = float(r["mid_price"]) if r["mid_price"] else None
            except (KeyError, ValueError):
                continue
            spread = (ask1 - bid1) if (bid1 is not None and ask1 is not None) else None
            rows[p].append((ts, mid, bid1, ask1, bv1, av1, spread))
    for p in rows: rows[p].sort()
    return rows

def align(series, ts_grid):
    out = [None] * len(ts_grid); j = 0; last = None
    for i, ts in enumerate(ts_grid):
        while j < len(series) and series[j][0] <= ts:
            last = series[j]; j += 1
        out[i] = last
    return out

def diff(s): return [None if (a is None or b is None) else (a - b)
                     for a, b in zip(s[1:], s[:-1])]

def lag(s, k):
    if k == 0: return list(s)
    if k > 0: return s[k:] + [None] * k
    k = -k
    return [None] * k + s[:-k]

def ols_multivar(X, y):
    """Plain normal-equations multi-var OLS. X is list of feature columns. Returns coefs (intercept first)."""
    # build augmented matrix [1, x1, x2, ...]
    n = len(y); k = len(X)
    A = [[1.0] + [X[j][i] for j in range(k)] for i in range(n)]
    # mask Nones
    valid = [i for i in range(n) if y[i] is not None and all(X[j][i] is not None for j in range(k))]
    if len(valid) < k + 5:
        return None, 0
    yv = [y[i] for i in valid]
    Av = [A[i] for i in valid]
    # Normal eqs: (A^T A) β = A^T y
    K = k + 1
    AtA = [[0.0] * K for _ in range(K)]
    Aty = [0.0] * K
    for row, yi in zip(Av, yv):
        for a in range(K):
            Aty[a] += row[a] * yi
            for b in range(K):
                AtA[a][b] += row[a] * row[b]
    # Gauss-Jordan
    M = [row[:] + [Aty[i]] for i, row in enumerate(AtA)]
    for c in range(K):
        # pivot
        pivot = max(range(c, K), key=lambda r: abs(M[r][c]))
        M[c], M[pivot] = M[pivot], M[c]
        if abs(M[c][c]) < 1e-12:
            return None, 0
        inv = 1.0 / M[c][c]
        for j in range(c, K + 1):
            M[c][j] *= inv
        for r in range(K):
            if r == c: continue
            factor = M[r][c]
            for j in range(c, K + 1):
                M[r][j] -= factor * M[c][j]
    return [M[r][K] for r in range(K)], len(valid)

def predict(beta, X, i):
    if beta is None: return None
    if any(X[j][i] is None for j in range(len(X))):
        return None
    return beta[0] + sum(beta[j + 1] * X[j][i] for j in range(len(X)))

def main():
    # Load all 3 days
    dd = {}
    for day in DAYS:
        prices = load_prices(day)
        h_rows = prices.get("HYDROGEL_PACK", [])
        ts = [r[0] for r in h_rows]
        h_mid = [r[1] for r in h_rows]
        h_dmid = diff(h_mid)
        # Build one feature per cross product: Δmid, lagged Δmid, lvl, imb
        feats = []
        names = []
        for p in PRODS:
            ser = prices.get(p, [])
            aligned = align(ser, ts)
            mids = [a[1] if a else None for a in aligned]
            bvs = [a[4] if a else 0.0 for a in aligned]
            avs = [a[5] if a else 0.0 for a in aligned]
            imb = [(b - a) / (b + a) if (b + a) > 0 else 0.0 for b, a in zip(bvs, avs)]
            dm = diff(mids)
            feats.append(dm); names.append(f"Δ{p}_t")
            feats.append(lag(dm, -1)); names.append(f"Δ{p}_t-1")
            feats.append(lag(dm, -2)); names.append(f"Δ{p}_t-2")
            feats.append(imb[:-1]); names.append(f"imb({p})_t")
        dd[day] = dict(ts=ts, h_dmid=h_dmid, feats=feats, names=names, h_mid=h_mid)

    # T1 — Train on 2 days, test on 1, rotate
    print("=" * 80)
    print("[T1] Out-of-sample R² of cross-product OLS predicting ΔH")
    print("=" * 80)
    for held_out in DAYS:
        train_days = [d for d in DAYS if d != held_out]
        # Concatenate train data
        y = []
        Xcols = [[] for _ in dd[held_out]["feats"]]
        for d in train_days:
            y.extend(dd[d]["h_dmid"])
            for j, c in enumerate(dd[d]["feats"]):
                Xcols[j].extend(c)
        beta, n_used = ols_multivar(Xcols, y)
        if beta is None:
            print(f"  held-out day {held_out}: OLS failed (n={n_used})")
            continue
        # In-sample R²
        ss_res_in = 0.0; ss_tot_in = 0.0; my = mean(v for v in y if v is not None)
        for i, yi in enumerate(y):
            if yi is None: continue
            yp = predict(beta, Xcols, i)
            if yp is None: continue
            ss_res_in += (yi - yp) ** 2
            ss_tot_in += (yi - my) ** 2
        r2_in = 1 - ss_res_in / ss_tot_in if ss_tot_in > 0 else 0.0
        # OOS R²
        y_oos = dd[held_out]["h_dmid"]
        X_oos = dd[held_out]["feats"]
        my_oos = mean(v for v in y_oos if v is not None)
        ss_res = 0.0; ss_tot = 0.0; n_pred = 0
        for i, yi in enumerate(y_oos):
            if yi is None: continue
            yp = predict(beta, X_oos, i)
            if yp is None: continue
            ss_res += (yi - yp) ** 2
            ss_tot += (yi - my_oos) ** 2
            n_pred += 1
        r2_oos = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        print(f"  held-out day {held_out}: train n={n_used}  R²_in={r2_in:+.5f}  R²_oos={r2_oos:+.5f}  n_pred={n_pred}")
        # Print top 5 |coef|
        feature_pairs = sorted(zip(dd[held_out]["names"], beta[1:]), key=lambda p: -abs(p[1]))[:6]
        for nm, b in feature_pairs:
            print(f"      coef {nm:34s} = {b:+.5f}")

    # T2 — Information coefficient: sign hit-rate
    print("\n" + "=" * 80)
    print("[T2] Sign-only IC: P(sign(ΔH_{t+1..+5}) == sign(ΔX_t))  vs 0.5")
    print("=" * 80)
    for p in PRODS:
        for K in [1, 5, 20]:
            hits = 0; tot = 0
            for day in DAYS:
                m = dd[day]["h_mid"]
                # find p_idx in feats: every product is 4 cols; feature index = idx*4 = Δp_t
                p_idx = PRODS.index(p) * 4
                xd = dd[day]["feats"][p_idx]
                n = len(m)
                for i in range(n - K):
                    if xd[i] is None or m[i + K] is None or m[i] is None: continue
                    if abs(xd[i]) < 1e-9: continue
                    fwd = m[i + K] - m[i]
                    if abs(fwd) < 1e-9: continue
                    if (xd[i] > 0) == (fwd > 0):
                        hits += 1
                    tot += 1
            if tot > 100:
                hr = hits / tot
                # binomial z
                z = (hr - 0.5) / math.sqrt(0.25 / tot)
                tag = "★" if abs(z) > 4 else " "
                print(f"  {tag} {p:24s} K={K:>3d}  HR={hr:.4f}  n={tot}  z={z:+.2f}")

    # T3 — Hour-of-day buckets — does HYDROGEL drift have a daily structure?
    print("\n" + "=" * 80)
    print("[T3] Hour-of-day mean ΔH (10 buckets) — same across days?")
    print("=" * 80)
    BUCKETS = 10
    by_day = []
    for day in DAYS:
        ts = dd[day]["ts"]
        hd = dd[day]["h_dmid"]
        sums = [0.0] * BUCKETS; counts = [0] * BUCKETS
        for i, h in enumerate(hd):
            if h is None: continue
            b = min(BUCKETS - 1, int(ts[i] / (1_000_000 / BUCKETS)))
            sums[b] += h; counts[b] += 1
        by_day.append([sums[b] / counts[b] if counts[b] > 0 else 0.0 for b in range(BUCKETS)])
    print("  bucket  d0_mean  d1_mean  d2_mean")
    for b in range(BUCKETS):
        print(f"   {b:>2d}     {by_day[0][b]:+8.4f}  {by_day[1][b]:+8.4f}  {by_day[2][b]:+8.4f}")

    # T4 — Aggregate basket: signed sum of all ΔX → predict ΔH?
    print("\n" + "=" * 80)
    print("[T4] Composite basket Σ sign(ΔX) vs ΔH (sign hit-rate)")
    print("=" * 80)
    for K in [1, 5, 20, 50]:
        hits = 0; tot = 0
        for day in DAYS:
            m = dd[day]["h_mid"]
            comp = []
            n = len(m)
            for i in range(n - 1):
                s = 0
                for p in PRODS:
                    p_idx = PRODS.index(p) * 4
                    xd = dd[day]["feats"][p_idx]
                    if xd[i] is None: continue
                    if xd[i] > 0: s += 1
                    elif xd[i] < 0: s -= 1
                comp.append(s)
            for i in range(len(comp) - K):
                if m[i + K] is None or m[i] is None: continue
                if comp[i] == 0: continue
                fwd = m[i + K] - m[i]
                if abs(fwd) < 1e-9: continue
                if (comp[i] > 0) == (fwd > 0):
                    hits += 1
                tot += 1
        if tot > 100:
            hr = hits / tot
            z = (hr - 0.5) / math.sqrt(0.25 / tot)
            tag = "★" if abs(z) > 4 else " "
            print(f"  {tag} basket K={K:>3d}  HR={hr:.4f}  n={tot}  z={z:+.2f}")


if __name__ == "__main__":
    main()
