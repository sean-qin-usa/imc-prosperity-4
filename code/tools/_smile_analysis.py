"""Quick smile analysis for R4 voucher strikes.

Goal: see if a per-strike IV exhibits a fittable smile shape that ship_r4_v1's
flat sigma=0.252 misses. If yes, we can scalp deviations from the smile fit.

Output: per-day per-strike avg IV, std IV, and residual stats vs:
  (a) flat sigma=0.252 (current model)
  (b) linear fit IV ~ a + b*moneyness
  (c) quadratic fit IV ~ a + b*m + c*m^2
"""
from __future__ import annotations
import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

_N = NormalDist()
DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "round4"

VEV_STRIKES = {
    "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000,
    "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300,
    "VEV_5400": 5400, "VEV_5500": 5500,
}
TTE_DAYS_LIVE = 4.0
DAYS_PER_YEAR = 365


def bs_call(S, K, T, sig):
    if T <= 0 or sig <= 0:
        return max(0.0, S - K)
    sq = sig * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / sq
    d2 = d1 - sq
    return S * _N.cdf(d1) - K * _N.cdf(d2)


def bs_vega(S, K, T, sig):
    if T <= 0 or sig <= 0:
        return 1e-9
    sq = sig * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / sq
    return S * _N.pdf(d1) * math.sqrt(T)


def implied_vol(price, S, K, T, hi=2.0, lo=0.001):
    """Newton-Raphson on call IV. Returns None if non-convergent or absurd."""
    intrinsic = max(0.0, S - K)
    if price <= intrinsic + 1e-9:
        return None
    if price >= S - 1e-9:
        return None
    sig = 0.3
    for _ in range(60):
        c = bs_call(S, K, T, sig)
        diff = c - price
        if abs(diff) < 1e-6:
            return sig
        v = bs_vega(S, K, T, sig)
        if v < 1e-9:
            return None
        sig -= diff / v
        if sig < lo:
            sig = lo
        if sig > hi:
            sig = hi
    return sig if lo < sig < hi else None


def tte_years(ts):
    tte_days = TTE_DAYS_LIVE - ts / 1e6
    return max(0.0, tte_days) / DAYS_PER_YEAR


def load_day(day):
    path = DATA_ROOT / f"prices_round_4_day_{day}.csv"
    by_ts = defaultdict(dict)
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            ts = int(row["timestamp"])
            prod = row["product"]
            try:
                bb = int(row["bid_price_1"])
                ba = int(row["ask_price_1"])
                mid = 0.5 * (bb + ba)
            except ValueError:
                continue
            by_ts[ts][prod] = mid
    return by_ts


def fit_quadratic(xs, ys):
    """y = a + b*x + c*x^2 via normal equations."""
    n = len(xs)
    if n < 3:
        return None
    sx = sum(xs); sx2 = sum(x*x for x in xs); sx3 = sum(x**3 for x in xs); sx4 = sum(x**4 for x in xs)
    sy = sum(ys); sxy = sum(x*y for x, y in zip(xs, ys)); sx2y = sum(x*x*y for x, y in zip(xs, ys))
    # 3x3 system
    A = [[n, sx, sx2], [sx, sx2, sx3], [sx2, sx3, sx4]]
    b = [sy, sxy, sx2y]
    # Cramer's rule
    def det3(m):
        return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
              - m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
              + m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))
    D = det3(A)
    if abs(D) < 1e-12:
        return None
    Da = det3([[b[0], A[0][1], A[0][2]],[b[1], A[1][1], A[1][2]],[b[2], A[2][1], A[2][2]]])
    Db = det3([[A[0][0], b[0], A[0][2]],[A[1][0], b[1], A[1][2]],[A[2][0], b[2], A[2][2]]])
    Dc = det3([[A[0][0], A[0][1], b[0]],[A[1][0], A[1][1], b[1]],[A[2][0], A[2][1], b[2]]])
    return Da/D, Db/D, Dc/D


def main():
    for day in [1, 2, 3]:
        print(f"\n===== DAY {day} =====")
        ticks = load_day(day)
        ts_list = sorted(ticks)
        n_ticks = len(ts_list)
        print(f"Loaded {n_ticks} ticks")

        per_strike_iv = defaultdict(list)
        per_strike_residual = defaultdict(list)  # vs flat sigma=0.252
        smile_resids = []  # (per-tick) list of dicts {strike: resid_vs_quad}

        SAMPLE = max(1, n_ticks // 1000)  # 1000 samples per day for speed

        for i, ts in enumerate(ts_list):
            if i % SAMPLE != 0:
                continue
            row = ticks[ts]
            S = row.get("VELVETFRUIT_EXTRACT")
            if S is None:
                continue
            T = tte_years(ts)
            if T <= 0:
                continue

            ivs = {}
            ms = {}
            for name, K in VEV_STRIKES.items():
                price = row.get(name)
                if price is None:
                    continue
                iv = implied_vol(price, S, K, T)
                if iv is None:
                    continue
                ivs[name] = iv
                ms[name] = math.log(K / S)  # log-moneyness
                per_strike_iv[name].append(iv)
                # residual vs flat 0.252
                bs_at_flat = bs_call(S, K, T, 0.252)
                per_strike_residual[name].append(price - bs_at_flat)

            # Fit quadratic on this tick's smile
            if len(ivs) >= 4:
                xs = list(ms.values())
                ys = list(ivs.values())
                fit = fit_quadratic(xs, ys)
                if fit:
                    a, b, c = fit
                    tick_resids = {}
                    for name in ivs:
                        m_v = ms[name]
                        iv_fit = a + b * m_v + c * m_v * m_v
                        tick_resids[name] = ivs[name] - iv_fit
                    smile_resids.append((ts, S, tick_resids))

        print(f"Sampled {len(smile_resids)} smile fits")

        # Per-strike IV stats
        print(f"\nPer-strike IV (mean / std):")
        for name in sorted(VEV_STRIKES):
            xs = per_strike_iv[name]
            if not xs:
                continue
            m = sum(xs)/len(xs)
            v = sum((x-m)**2 for x in xs)/len(xs)
            sd = math.sqrt(v)
            r = per_strike_residual[name]
            r_m = sum(r)/len(r) if r else 0
            r_sd = math.sqrt(sum((x-r_m)**2 for x in r)/len(r)) if r else 0
            print(f"  {name}: IV={m:.4f}±{sd:.4f}  ({len(xs)} pts)  resid_vs_flat={r_m:+.2f}±{r_sd:.2f}")

        # Smile residual stats (deviation from per-tick quadratic fit)
        print(f"\nSmile-fit residual std (per strike, in IV units):")
        per_strike_smile_resid = defaultdict(list)
        for ts, S, td in smile_resids:
            for k, v in td.items():
                per_strike_smile_resid[k].append(v)
        for name in sorted(VEV_STRIKES):
            xs = per_strike_smile_resid[name]
            if not xs:
                continue
            m = sum(xs)/len(xs)
            v = sum((x-m)**2 for x in xs)/len(xs)
            sd = math.sqrt(v)
            print(f"  {name}: resid_iv={m:+.5f}±{sd:.5f}  ({len(xs)} pts)")


if __name__ == "__main__":
    main()
