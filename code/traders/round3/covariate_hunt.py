"""
HYDROGEL covariate hunt.

Question: is HYDROGEL_PACK truly independent of VEV / VELVETFRUIT /
strike vouchers / volume / spread / time-of-day? Or are there any
contemporaneous OR lagged signals we can exploit?

We run a battery of regressions / correlations across days {0,1,2}.

Levels checked:
  L1  — Δmid_t(H) vs Δmid_t(X) at lags ∈ {-50..+50} (each X)
  L2  — mid_t(H) vs mid_t(X) — level cointegration check
  L3  — sign(Δmid_t(H)) vs sign(Δmid_t(X)) — Spearman
  L4  — Δmid_t(H) vs L1 imbalance, spread, volume of X
  L5  — Δmid_t(H) vs HYDROGEL's own spread, L1 imbalance, time-of-day
  L6  — Δmid(H) vs trade volume / signed trade flow in X
  L7  — block returns: H over [t, t+50] vs aggregate signal over [t-50, t]
  L8  — cross-product Granger (lag 1..5)
  L9  — non-linear: |ΔX| vs |ΔH|, sign(ΔX) only when |ΔX|>k

Print top-K signals by |t-stat| / |R|, with lag.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev


DATA_DIR = Path("/Users/sean_tsu_/Downloads/prosperity/IMCP2026/data/round3")
DAYS = [0, 1, 2]
PRODUCTS_OF_INTEREST = [
    "HYDROGEL_PACK",
    "VELVETFRUIT_EXTRACT",
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", "VEV_5200",
    "VEV_5300", "VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500",
]


def load_prices(day: int):
    """Return dict[product] -> list of (ts, mid, bid, ask, bv1, av1, spread)."""
    rows = defaultdict(list)
    fp = DATA_DIR / f"prices_round_3_day_{day}.csv"
    with fp.open() as fh:
        rd = csv.DictReader(fh, delimiter=";")
        for r in rd:
            try:
                p = r["product"]
                ts = int(r["timestamp"])
                bid1 = float(r["bid_price_1"]) if r["bid_price_1"] else None
                ask1 = float(r["ask_price_1"]) if r["ask_price_1"] else None
                bv1 = float(r["bid_volume_1"]) if r["bid_volume_1"] else 0.0
                av1 = float(r["ask_volume_1"]) if r["ask_volume_1"] else 0.0
                mid = float(r["mid_price"]) if r["mid_price"] else None
            except (KeyError, ValueError):
                continue
            spread = (ask1 - bid1) if (bid1 is not None and ask1 is not None) else None
            rows[p].append((ts, mid, bid1, ask1, bv1, av1, spread))
    for p in rows:
        rows[p].sort()
    return rows


def load_trades(day: int):
    rows = defaultdict(list)
    fp = DATA_DIR / f"trades_round_3_day_{day}.csv"
    with fp.open() as fh:
        rd = csv.DictReader(fh, delimiter=";")
        for r in rd:
            try:
                ts = int(r["timestamp"])
                sym = r["symbol"]
                price = float(r["price"])
                qty = float(r["quantity"])
            except (KeyError, ValueError):
                continue
            rows[sym].append((ts, price, qty))
    for sym in rows:
        rows[sym].sort()
    return rows


def align_to_grid(series, ts_grid):
    """Forward-fill series onto ts_grid. series: list of (ts, val[, ...])."""
    out = [None] * len(ts_grid)
    j = 0
    last = None
    for i, ts in enumerate(ts_grid):
        while j < len(series) and series[j][0] <= ts:
            last = series[j]
            j += 1
        out[i] = last
    return out


def trades_per_bin(trades, ts_grid, bin_w=100):
    """Sum qty in each bin around ts_grid (ts_grid[i] = bin center)."""
    out = [0.0] * len(ts_grid)
    if not trades:
        return out
    j = 0
    for i, ts in enumerate(ts_grid):
        lo = ts - bin_w + 1
        hi = ts
        while j < len(trades) and trades[j][0] < lo:
            j += 1
        k = j
        s = 0.0
        while k < len(trades) and trades[k][0] <= hi:
            s += trades[k][2]
            k += 1
        out[i] = s
    return out


def pearson(x, y):
    n = 0
    sx = sy = sxx = syy = sxy = 0.0
    for xi, yi in zip(x, y):
        if xi is None or yi is None:
            continue
        n += 1
        sx += xi; sy += yi
        sxx += xi * xi; syy += yi * yi
        sxy += xi * yi
    if n < 30:
        return 0.0, n
    mx = sx / n; my = sy / n
    cov = sxy - n * mx * my
    vx = sxx - n * mx * mx
    vy = syy - n * my * my
    if vx <= 0 or vy <= 0:
        return 0.0, n
    return cov / math.sqrt(vx * vy), n


def t_stat(r, n):
    if n <= 2 or abs(r) >= 0.999:
        return float("inf") if abs(r) >= 0.999 else 0.0
    return r * math.sqrt((n - 2) / max(1e-12, 1.0 - r * r))


def diff(series):
    return [None if (a is None or b is None) else (a - b)
            for a, b in zip(series[1:], series[:-1])]


def lag(series, k):
    """Return series shifted by k (positive = future of series). Use to align Δh_t with ΔX_{t+k}."""
    if k == 0:
        return list(series)
    if k > 0:
        return series[k:] + [None] * k
    k = -k
    return [None] * k + series[:-k]


def main():
    print("=" * 80)
    print("HYDROGEL COVARIATE HUNT — Round 3, days 0/1/2")
    print("=" * 80)

    # Load all 3 days, build a master ts grid (every 100 ticks), align mids.
    all_results = []  # (label, R, n, t)

    for day in DAYS:
        print(f"\n--- DAY {day} ---")
        prices = load_prices(day)
        trades = load_trades(day)
        # ts grid: union of all HYDROGEL ts, step 100
        h_rows = prices.get("HYDROGEL_PACK", [])
        if not h_rows:
            print("  (no HYDROGEL data)")
            continue
        ts_grid = [r[0] for r in h_rows]
        n_grid = len(ts_grid)
        print(f"  HYDROGEL ticks: {n_grid}, ts range {ts_grid[0]}..{ts_grid[-1]}")

        # Aligned mid + microstructure for each product
        mids = {}
        spreads = {}
        imbs = {}
        for p in PRODUCTS_OF_INTEREST:
            ser = prices.get(p, [])
            if not ser:
                mids[p] = [None] * n_grid
                spreads[p] = [None] * n_grid
                imbs[p] = [None] * n_grid
                continue
            aligned = align_to_grid(ser, ts_grid)
            mids[p] = [a[1] if a else None for a in aligned]
            spreads[p] = [a[6] if a else None for a in aligned]
            def _imb(a):
                if not a or a[2] is None or a[3] is None:
                    return None
                bv, av = a[4], a[5]
                if (bv + av) <= 0:
                    return 0.0
                return (bv - av) / (bv + av)
            imbs[p] = [_imb(a) for a in aligned]

        # Trade flow per product per bin
        flows = {}
        for p in PRODUCTS_OF_INTEREST:
            tr = trades.get(p, [])
            flows[p] = trades_per_bin(tr, ts_grid, bin_w=100)

        h_mid = mids["HYDROGEL_PACK"]
        h_dmid = diff(h_mid)  # length n_grid - 1; index i = mid[i+1] - mid[i]

        # ============================================================
        # L1 — Δmid(H) vs Δmid(X) at multiple lags
        # ============================================================
        print(f"\n  [L1] Δmid(H_t) vs Δmid(X_{{t+k}})  (positive k => X leads ΔH)")
        for p in PRODUCTS_OF_INTEREST:
            if p == "HYDROGEL_PACK":
                continue
            x_dmid = diff(mids[p])
            best = (0.0, 0, 0)
            for k in range(-5, 6):
                xk = lag(x_dmid, k)
                r, n = pearson(h_dmid, xk)
                t = t_stat(r, n)
                if abs(r) > abs(best[0]):
                    best = (r, k, n)
                if abs(t) > 4.0:
                    all_results.append(
                        (f"day{day} L1 ΔH ~ ΔX(lag={k:+d})  X={p}", r, n, t)
                    )
            r, k, n = best
            t = t_stat(r, n)
            print(f"    {p:24s} best k={k:+d}  R={r:+.4f}  t={t:+.2f}  n={n}")

        # ============================================================
        # L2 — level co-movement (cointegration sniff)
        # ============================================================
        print(f"\n  [L2] level mid(H) vs mid(X)")
        for p in PRODUCTS_OF_INTEREST:
            if p == "HYDROGEL_PACK":
                continue
            r, n = pearson(h_mid, mids[p])
            t = t_stat(r, n)
            print(f"    {p:24s}            R={r:+.4f}  t={t:+.2f}  n={n}")
            if abs(t) > 4.0:
                all_results.append((f"day{day} L2 mid(H)~mid({p})", r, n, t))

        # ============================================================
        # L4 — Δmid(H) vs imbalance(X), spread(X), |Δmid(X)|
        # ============================================================
        print(f"\n  [L4] ΔH vs micro features of X")
        for p in PRODUCTS_OF_INTEREST:
            x_imb = imbs[p]
            x_imb_t = lag(x_imb[:-1], 0)  # align to ΔH index
            r, n = pearson(h_dmid, x_imb_t)
            if abs(t_stat(r, n)) > 3.0:
                print(f"    ΔH ~ imb({p})       R={r:+.4f}  t={t_stat(r, n):+.2f} n={n}")
                all_results.append((f"day{day} L4 ΔH~imb({p})", r, n, t_stat(r, n)))

            x_spr = spreads[p][:-1]
            r, n = pearson(h_dmid, x_spr)
            if abs(t_stat(r, n)) > 3.0:
                print(f"    ΔH ~ spread({p})    R={r:+.4f}  t={t_stat(r, n):+.2f} n={n}")
                all_results.append((f"day{day} L4 ΔH~spread({p})", r, n, t_stat(r, n)))

            x_abs = [None if v is None else abs(v) for v in diff(mids[p])]
            r, n = pearson([None if v is None else abs(v) for v in h_dmid], x_abs)
            if abs(t_stat(r, n)) > 3.0:
                print(f"    |ΔH| ~ |ΔX|({p}) R={r:+.4f}  t={t_stat(r, n):+.2f} n={n}")
                all_results.append((f"day{day} L4 |ΔH|~|ΔX|({p})", r, n, t_stat(r, n)))

        # ============================================================
        # L5 — Δmid(H) vs HYDROGEL's own state
        # ============================================================
        print(f"\n  [L5] Δmid(H) vs own H features")
        h_imb = imbs["HYDROGEL_PACK"]
        # contemporaneous and 1-step-lead
        for k in [-1, 0, 1, 2, 3]:
            h_imb_k = lag(h_imb[:-1], k)
            r, n = pearson(h_dmid, h_imb_k)
            t = t_stat(r, n)
            print(f"    ΔH ~ imb(H, k={k:+d})   R={r:+.4f}  t={t:+.2f}  n={n}")
            if abs(t) > 4.0:
                all_results.append((f"day{day} L5 ΔH~imb(H,k={k:+d})", r, n, t))

        # AR(1) on Δmid
        h_dlag = lag(h_dmid, 1)
        r, n = pearson(h_dmid, h_dlag)
        t = t_stat(r, n)
        print(f"    AR(1) Δmid(H)            R={r:+.4f}  t={t:+.2f}  n={n}")
        if abs(t) > 4.0:
            all_results.append((f"day{day} L5 AR1 ΔH", r, n, t))

        # spread(H) vs |ΔH|
        h_spr = spreads["HYDROGEL_PACK"][:-1]
        r, n = pearson([None if v is None else abs(v) for v in h_dmid], h_spr)
        t = t_stat(r, n)
        print(f"    |ΔH| ~ spread(H)         R={r:+.4f}  t={t:+.2f}  n={n}")
        if abs(t) > 4.0:
            all_results.append((f"day{day} L5 |ΔH|~spread(H)", r, n, t))

        # mid level vs time-of-day
        ts_norm = [t / 1_000_000 for t in ts_grid]
        r, n = pearson(h_mid, ts_norm)
        t = t_stat(r, n)
        print(f"    mid(H) ~ time-of-day     R={r:+.4f}  t={t:+.2f}  n={n}")
        if abs(t) > 4.0:
            all_results.append((f"day{day} L5 mid(H)~time", r, n, t))

        # ============================================================
        # L6 — ΔH vs trade flow in X (signed if possible: take buy vs take sell)
        # ============================================================
        print(f"\n  [L6] ΔH vs |trade vol| in X (100-tick bins)")
        for p in PRODUCTS_OF_INTEREST:
            f = flows[p][:-1]
            r, n = pearson([None if v is None else abs(v) for v in h_dmid], f)
            t = t_stat(r, n)
            if abs(t) > 3.0:
                print(f"    |ΔH| ~ vol({p})    R={r:+.4f}  t={t:+.2f}  n={n}")
                all_results.append((f"day{day} L6 |ΔH|~vol({p})", r, n, t))

        # ============================================================
        # L7 — block returns: H over k forward ticks vs X over k backward
        # ============================================================
        print(f"\n  [L7] forward H return (k=10) vs backward X return (k=10)")
        K = 10
        h_fwd = [None if (h_mid[i + K] is None or h_mid[i] is None) else (h_mid[i + K] - h_mid[i])
                 for i in range(n_grid - K)]
        for p in PRODUCTS_OF_INTEREST:
            if p == "HYDROGEL_PACK":
                continue
            x_back = [None if (mids[p][i] is None or mids[p][i - K] is None)
                      else (mids[p][i] - mids[p][i - K])
                      for i in range(K, n_grid)]
            # align to h_fwd window: h_fwd index 0 = mid[K]-mid[0]; x_back index 0 = mid[K]-mid[0]
            r, n = pearson(h_fwd, x_back[:len(h_fwd)])
            t = t_stat(r, n)
            tag = "*" if abs(t) > 4.0 else " "
            print(f"   {tag} H_fwd10 ~ X_back10({p}) R={r:+.4f}  t={t:+.2f}  n={n}")
            if abs(t) > 4.0:
                all_results.append((f"day{day} L7 Hfwd10~Xback10({p})", r, n, t))

        # ============================================================
        # L8 — Granger lag 1..5 of ΔX leading ΔH
        # ============================================================
        print(f"\n  [L8] forward leadership: corr(ΔH_t, ΔX_{{t-k}}) for k=1..10")
        for p in PRODUCTS_OF_INTEREST:
            if p == "HYDROGEL_PACK":
                continue
            x_dmid = diff(mids[p])
            best = (0.0, 0, 0)
            for k in range(1, 11):
                xk = lag(x_dmid, -k)  # ΔX_{t-k}
                r, n = pearson(h_dmid, xk)
                if abs(r) > abs(best[0]):
                    best = (r, k, n)
            r, k, n = best
            t = t_stat(r, n)
            tag = "*" if abs(t) > 4.0 else " "
            print(f"   {tag} ΔH_t ~ ΔX_{{t-{k}}}({p}) R={r:+.4f}  t={t:+.2f}  n={n}")
            if abs(t) > 4.0:
                all_results.append((f"day{day} L8 ΔH~ΔX(lag-{k})({p})", r, n, t))

        # ============================================================
        # L9 — non-linear: large ΔX → ΔH ?
        # ============================================================
        print(f"\n  [L9] non-linear: ΔH conditional on |ΔX|>k")
        for p in ["VELVETFRUIT_EXTRACT", "VEV_4000", "VEV_4500"]:
            x_dmid = diff(mids[p])
            for thresh in [1, 2, 3, 5]:
                pos_h = []
                neg_h = []
                for dh, dx in zip(h_dmid, x_dmid):
                    if dh is None or dx is None:
                        continue
                    if dx > thresh:
                        pos_h.append(dh)
                    elif dx < -thresh:
                        neg_h.append(dh)
                if len(pos_h) > 20 and len(neg_h) > 20:
                    m_pos = mean(pos_h); m_neg = mean(neg_h)
                    s_pos = pstdev(pos_h) if len(pos_h) > 1 else 0.0
                    s_neg = pstdev(neg_h) if len(neg_h) > 1 else 0.0
                    se = math.sqrt(
                        s_pos * s_pos / len(pos_h) + s_neg * s_neg / len(neg_h)
                    )
                    if se > 0:
                        z = (m_pos - m_neg) / se
                        if abs(z) > 2.5:
                            print(f"    X={p} thresh={thresh}: m+={m_pos:+.3f} (n={len(pos_h)})  "
                                  f"m-={m_neg:+.3f} (n={len(neg_h)})  z={z:+.2f}")
                            all_results.append(
                                (f"day{day} L9 X={p} t={thresh}: m+={m_pos:.2f} m-={m_neg:.2f} z={z:+.2f}",
                                 z / 100, len(pos_h) + len(neg_h), z)
                            )

    # ============================================================
    # Summary
    # ============================================================
    print("\n" + "=" * 80)
    print("SUMMARY — strong findings (|t| > 4.0)")
    print("=" * 80)
    if not all_results:
        print("\n  *** NO COVARIATES FOUND ABOVE |t|>4.0 ***\n")
    else:
        all_results.sort(key=lambda r: -abs(r[3]))
        for label, R, n, t in all_results[:60]:
            print(f"  |t|={abs(t):6.2f}  R={R:+.4f}  n={n}  | {label}")


if __name__ == "__main__":
    main()
