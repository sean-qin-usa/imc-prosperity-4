"""
HYDROGEL covariate hunt — pass 2.

Goal: rule out cross-product covariates with multi-day stability and
regime conditioning. Pass 1 showed |R| ≤ 0.05 cross-product, |R| ≥ 0.30
own-microstructure. Now we pressure-test the cross-product side:

  P1 — sign-flip test: same lag/window across days. Real signals
       should NOT flip sign across days.
  P2 — regime-gated: only when spread(H) > 16 (walked book)
  P3 — signed trade flow (using last_print vs touch_mid)
  P4 — long-horizon block returns (K = 50, 200, 500)
  P5 — pooled OLS across all 3 days with day-fixed effects
  P6 — partial correlation: ΔH | imb(H) controlled out, vs ΔX
  P7 — regression of HYDROGEL future PnL of a passive MM on cross-feature
"""

from __future__ import annotations

import csv
import math
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


def load_trades(day):
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


def align(series, ts_grid):
    out = [None] * len(ts_grid)
    j = 0; last = None
    for i, ts in enumerate(ts_grid):
        while j < len(series) and series[j][0] <= ts:
            last = series[j]; j += 1
        out[i] = last
    return out


def signed_flow(trades, ts_grid, mids, bin_w=100):
    """Signed trade flow: +q if trade above touch_mid, -q if below."""
    out = [0.0] * len(ts_grid)
    if not trades:
        return out
    j = 0
    for i, ts in enumerate(ts_grid):
        m = mids[i]
        if m is None:
            continue
        lo, hi = ts - bin_w + 1, ts
        while j < len(trades) and trades[j][0] < lo:
            j += 1
        k = j; s = 0.0
        while k < len(trades) and trades[k][0] <= hi:
            tp, tq = trades[k][1], trades[k][2]
            sign = 1.0 if tp > m else (-1.0 if tp < m else 0.0)
            s += sign * tq
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
    mx, my = sx / n, sy / n
    cov = sxy - n * mx * my
    vx = sxx - n * mx * mx; vy = syy - n * my * my
    if vx <= 0 or vy <= 0:
        return 0.0, n
    return cov / math.sqrt(vx * vy), n


def t_stat(r, n):
    if n <= 2:
        return 0.0
    if abs(r) >= 0.999:
        return float("inf")
    return r * math.sqrt((n - 2) / (1 - r * r))


def diff(s):
    return [None if (a is None or b is None) else (a - b)
            for a, b in zip(s[1:], s[:-1])]


def lag(s, k):
    if k == 0: return list(s)
    if k > 0: return s[k:] + [None] * k
    k = -k
    return [None] * k + s[:-k]


def residualize(y, x):
    """Return y - β·x where β is OLS slope. Both lists same length, may have None."""
    n = 0; sx = sy = sxx = sxy = 0.0
    for xi, yi in zip(x, y):
        if xi is None or yi is None: continue
        n += 1
        sx += xi; sy += yi; sxx += xi * xi; sxy += xi * yi
    if n < 30:
        return list(y)
    mx, my = sx / n, sy / n
    vx = sxx - n * mx * mx
    if vx <= 0:
        return list(y)
    beta = (sxy - n * mx * my) / vx
    alpha = my - beta * mx
    return [None if (xi is None or yi is None) else (yi - alpha - beta * xi)
            for xi, yi in zip(x, y)]


def main():
    print("=" * 80)
    print("HYDROGEL COVARIATE HUNT v2 — sign stability + regime + flow + horizon")
    print("=" * 80)

    # Per-day storage
    day_data = {}
    for day in DAYS:
        prices = load_prices(day)
        trades = load_trades(day)
        h_rows = prices.get("HYDROGEL_PACK", [])
        ts_grid = [r[0] for r in h_rows]
        n = len(ts_grid)

        h_mid = [r[1] for r in h_rows]
        h_bid = [r[2] for r in h_rows]
        h_ask = [r[3] for r in h_rows]
        h_bv = [r[4] for r in h_rows]
        h_av = [r[5] for r in h_rows]
        h_spr = [r[6] for r in h_rows]
        h_imb = [
            (bv - av) / (bv + av) if (bv + av) > 0 else 0.0
            for bv, av in zip(h_bv, h_av)
        ]
        h_dmid = diff(h_mid)

        prod_data = {}
        for p in PRODS:
            ser = prices.get(p, [])
            aligned = align(ser, ts_grid)
            mids = [a[1] if a else None for a in aligned]
            bids = [a[2] if a else None for a in aligned]
            asks = [a[3] if a else None for a in aligned]
            bvs = [a[4] if a else 0.0 for a in aligned]
            avs = [a[5] if a else 0.0 for a in aligned]
            sprs = [a[6] if a else None for a in aligned]
            imb = [(b - a) / (b + a) if (b + a) > 0 else 0.0 for b, a in zip(bvs, avs)]
            dmid = diff(mids)
            sflow = signed_flow(trades.get(p, []), ts_grid, mids)
            prod_data[p] = dict(
                mid=mids, bid=bids, ask=asks, spr=sprs, imb=imb, dmid=dmid, sflow=sflow,
            )
        day_data[day] = dict(
            ts=ts_grid, n=n,
            h_mid=h_mid, h_dmid=h_dmid, h_imb=h_imb, h_spr=h_spr,
            prods=prod_data,
        )
        print(f"  loaded day {day}: n={n}")

    # ============================================================
    # P1 — Sign stability across days for ΔH ~ ΔX (lag-ranged)
    # ============================================================
    print("\n[P1] Sign stability across 3 days  ΔH_t ~ ΔX_{t+k}, lag k ∈ {-3..+3}")
    print("     → if a real signal: same sign on all 3 days at the same lag")
    for p in PRODS:
        rows = []
        for k in range(-3, 4):
            sgns = []
            rs = []
            for day in DAYS:
                hd = day_data[day]["h_dmid"]
                xd = lag(day_data[day]["prods"][p]["dmid"], k)
                r, n = pearson(hd, xd)
                rs.append(r)
                if abs(t_stat(r, n)) > 2.0:
                    sgns.append(1 if r > 0 else -1)
                else:
                    sgns.append(0)
            rows.append((k, rs, sgns))
        # find any lag where all 3 days agree |t|>2 same sign
        hits = [r for r in rows if abs(sum(r[2])) == 3]
        if hits:
            print(f"  ★ {p}  STABLE-SIGNED LAGS:")
            for k, rs, sgns in hits:
                print(f"      k={k:+d}  R = {rs[0]:+.4f}, {rs[1]:+.4f}, {rs[2]:+.4f}  (signs {sgns})")
        else:
            best = max(rows, key=lambda r: sum(abs(x) for x in r[1]))
            k, rs, sgns = best
            print(f"    {p:24s} no stable lag.  best k={k:+d}  R={rs[0]:+.3f},{rs[1]:+.3f},{rs[2]:+.3f}  signs={sgns}")

    # ============================================================
    # P2 — Regime-gated: cross-corr only when spread(H) is wide
    # ============================================================
    print("\n[P2] Regime gating: cross-corr ΔH~ΔX only when spread(H) > 16 (walked)")
    for p in PRODS:
        for day in DAYS:
            hd = day_data[day]["h_dmid"]
            xd = day_data[day]["prods"][p]["dmid"]
            hs = day_data[day]["h_spr"][:-1]
            for sthresh in [16, 17, 18]:
                hd_g = [h if (s is not None and s > sthresh) else None
                        for h, s in zip(hd, hs)]
                r, n = pearson(hd_g, xd)
                t = t_stat(r, n)
                if abs(t) > 4.0 and n > 200:
                    print(f"   ★ day{day} p={p} spr>{sthresh}  R={r:+.4f}  t={t:+.2f}  n={n}")

    # ============================================================
    # P3 — Signed trade flow in X vs ΔH
    # ============================================================
    print("\n[P3] Signed trade flow in X (100-tick bin) vs Δmid(H), and lag-1 lead")
    for p in PRODS:
        for day in DAYS:
            hd = day_data[day]["h_dmid"]
            sf = day_data[day]["prods"][p]["sflow"][:-1]
            r, n = pearson(hd, sf)
            t = t_stat(r, n)
            if abs(t) > 3.0:
                tag = "★" if abs(t) > 4 else " "
                print(f"   {tag} day{day} ΔH ~ sflow({p})  R={r:+.4f}  t={t:+.2f}  n={n}")
            sf_lag = lag(day_data[day]["prods"][p]["sflow"], -1)[:-1]
            r, n = pearson(hd, sf_lag)
            t = t_stat(r, n)
            if abs(t) > 3.0:
                tag = "★" if abs(t) > 4 else " "
                print(f"   {tag} day{day} ΔH ~ sflow({p})_{{t-1}}  R={r:+.4f}  t={t:+.2f}  n={n}")

    # ============================================================
    # P4 — Block returns at K = 50, 200, 500
    # ============================================================
    print("\n[P4] Block returns: forward-K H vs backward-K X (K = 50, 200, 500)")
    for K in [50, 200, 500]:
        print(f"  K = {K}:")
        for p in PRODS:
            agg = []
            for day in DAYS:
                m = day_data[day]["h_mid"]
                xm = day_data[day]["prods"][p]["mid"]
                n = len(m)
                hf = [None if (m[i + K] is None or m[i] is None)
                      else (m[i + K] - m[i]) for i in range(n - K)]
                xb = [None if (xm[i] is None or xm[i - K] is None)
                      else (xm[i] - xm[i - K]) for i in range(K, n)]
                xb = xb[:len(hf)]
                r, nn = pearson(hf, xb)
                agg.append((r, nn))
            sgns = [1 if r > 0 else -1 for r, _ in agg]
            stable = (sgns[0] == sgns[1] == sgns[2])
            tag = "★" if stable and all(abs(t_stat(r, n)) > 3 for r, n in agg) else " "
            print(f"   {tag} {p:24s} R d0/d1/d2 = {agg[0][0]:+.3f} / {agg[1][0]:+.3f} / {agg[2][0]:+.3f}")

    # ============================================================
    # P5 — Pooled regression with day-FE
    # ============================================================
    print("\n[P5] Pooled (3-day, demeaned) ΔH ~ ΔX  (both demeaned by day)")
    for p in PRODS:
        ys = []
        xs = []
        for day in DAYS:
            hd = day_data[day]["h_dmid"]
            xd = day_data[day]["prods"][p]["dmid"]
            # demean each day's residual sequences
            hd_v = [v for v in hd if v is not None]
            xd_v = [v for v in xd if v is not None]
            mh = mean(hd_v) if hd_v else 0
            mx = mean(xd_v) if xd_v else 0
            for h, x in zip(hd, xd):
                if h is None or x is None:
                    continue
                ys.append(h - mh); xs.append(x - mx)
        r, n = pearson(xs, ys)
        t = t_stat(r, n)
        tag = "★" if abs(t) > 4.0 else " "
        print(f"   {tag} {p:24s}  R={r:+.4f}  t={t:+.2f}  n={n}")

    # ============================================================
    # P6 — Partial correlation: control out own-imbalance
    # ============================================================
    print("\n[P6] Partial corr: ΔH residualized on (imb_H, imb_H_lag, AR1) vs ΔX")
    for p in PRODS:
        agg = []
        for day in DAYS:
            hd = day_data[day]["h_dmid"]
            hi = day_data[day]["h_imb"][:-1]
            hi1 = lag(day_data[day]["h_imb"], +1)[:-1]
            ar1 = lag(hd, -1)
            # residualize sequentially
            r_hd = residualize(hd, hi)
            r_hd = residualize(r_hd, hi1)
            r_hd = residualize(r_hd, ar1)
            xd = day_data[day]["prods"][p]["dmid"]
            for k in [-1, 0, 1]:
                xk = lag(xd, k)
                r, n = pearson(r_hd, xk)
                t = t_stat(r, n)
                agg.append((day, k, r, n, t))
        # show any with |t|>3.5
        sig = [a for a in agg if abs(a[4]) > 3.5]
        if sig:
            for day, k, r, n, t in sig:
                print(f"   ★ {p} day{day} k={k:+d}  R_partial={r:+.4f}  t={t:+.2f}")
        else:
            best = max(agg, key=lambda a: abs(a[4]))
            day, k, r, n, t = best
            print(f"     {p:24s} best (residual) day{day} k={k:+d}  R={r:+.4f}  t={t:+.2f}")

    # ============================================================
    # P7 — Realized predictive utility: use ΔX as a fair-bias on H
    #      Simulate: bias fair_H by α·ΔX_t. Measure forward Δmid_H_{t+1..+K}.
    #      If α has predictive use, conditional fwd > unconditional.
    # ============================================================
    print("\n[P7] Predictive utility: E[Δmid(H)_{t+1..+5} | ΔX_t > thresh] vs unconditional")
    for p in ["VELVETFRUIT_EXTRACT", "VEV_4000", "VEV_4500", "VEV_5200", "VEV_5400"]:
        for day in DAYS:
            m = day_data[day]["h_mid"]
            xd = day_data[day]["prods"][p]["dmid"]
            n = len(m)
            for K in [1, 5, 20]:
                pos, neg, all_ = [], [], []
                for i in range(n - K):
                    if i >= len(xd) or xd[i] is None or m[i + K] is None or m[i] is None:
                        continue
                    fwd = m[i + K] - m[i]
                    all_.append(fwd)
                    if xd[i] >= 1:
                        pos.append(fwd)
                    elif xd[i] <= -1:
                        neg.append(fwd)
                if len(pos) > 100 and len(neg) > 100:
                    mp, mn = mean(pos), mean(neg)
                    sp = pstdev(pos) if len(pos) > 1 else 1
                    sn = pstdev(neg) if len(neg) > 1 else 1
                    se = math.sqrt(sp ** 2 / len(pos) + sn ** 2 / len(neg))
                    z = (mp - mn) / se if se > 0 else 0
                    if abs(z) > 2.0:
                        print(f"   day{day} p={p} K={K}: fwdH|ΔX≥+1 = {mp:+.3f} (n={len(pos)})  "
                              f"fwdH|ΔX≤-1 = {mn:+.3f} (n={len(neg)})  z={z:+.2f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
