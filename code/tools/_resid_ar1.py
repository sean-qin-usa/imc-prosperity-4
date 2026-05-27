"""Compute residual = mid - BS_theo per VEV strike, then AR1 of Δresidual.

Confirms whether a residual-AR1 lean is mathematically sound (vs the raw
Δmid lean which double-counts the BS-driven spot move).
"""
import csv, math
from pathlib import Path
from statistics import NormalDist

DATA = Path(__file__).resolve().parent.parent / "data" / "round3"
N = NormalDist()
SIGMA = 0.16  # match shipped v27
TTE_DAYS_LIVE = 7
DAYS_PER_YEAR = 365


def bs_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K)
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sq
    d2 = d1 - sq
    return S * N.cdf(d1) - K * N.cdf(d2)


def autocorr(x, lag):
    pairs = [(x[i - lag], x[i]) for i in range(lag, len(x))
             if x[i] is not None and x[i - lag] is not None]
    if len(pairs) < 50:
        return None
    a = [p[0] for p in pairs]; b = [p[1] for p in pairs]
    ma = sum(a)/len(a); mb = sum(b)/len(b)
    num = sum((ai-ma)*(bi-mb) for ai,bi in zip(a,b))
    da = math.sqrt(sum((ai-ma)**2 for ai in a))
    db = math.sqrt(sum((bi-mb)**2 for bi in b))
    if da == 0 or db == 0: return None
    return num / (da * db)


def diff(seq):
    out = []; last = None
    for v in seq:
        if v is None:
            out.append(None); last = None; continue
        out.append(v - last if last is not None else 0.0)
        last = v
    return out


STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500,
           "VEV_5000": 5000, "VEV_5100": 5100, "VEV_5200": 5200,
           "VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500}

print(f"{'strike':>10}  {'day':>3}  {'AR1(Δmid)':>10}  {'AR1(Δres)':>10}  {'AR1(res)':>9}  {'std(res)':>9}  {'mean(res)':>10}")
for d in (0, 1, 2):
    f = DATA / f"prices_round_3_day_{d}.csv"
    series = {p: {} for p in list(STRIKES) + ["VELVETFRUIT_EXTRACT"]}
    with f.open() as fh:
        r = csv.DictReader(fh, delimiter=";")
        for row in r:
            p = row["product"]
            if p not in series: continue
            try: m = float(row["mid_price"])
            except: continue
            series[p][int(row["timestamp"])] = m
    timestamps = sorted({ts for v in series.values() for ts in v})
    vfe_mid = [series["VELVETFRUIT_EXTRACT"].get(ts) for ts in timestamps]

    for sk, K in STRIKES.items():
        sk_mid = [series[sk].get(ts) for ts in timestamps]
        residuals = []
        for i, ts in enumerate(timestamps):
            S = vfe_mid[i]; m = sk_mid[i]
            if S is None or m is None:
                residuals.append(None); continue
            tte_days = TTE_DAYS_LIVE - ts / 1e6
            T = max(0.0, tte_days) / DAYS_PER_YEAR
            theo = bs_call(S, K, T, SIGMA)
            residuals.append(m - theo)
        dres = diff(residuals)
        dmid = diff(sk_mid)
        ar_mid = autocorr(dmid, 1)
        ar_dres = autocorr(dres, 1)
        ar_res = autocorr(residuals, 1)
        clean = [r for r in residuals if r is not None]
        sd = math.sqrt(sum((r - sum(clean)/len(clean))**2 for r in clean) / len(clean)) if clean else 0
        mn = sum(clean)/len(clean) if clean else 0
        print(f"{sk:>10}  {d:>3}  {ar_mid if ar_mid is not None else '-- ':>10.3f}  "
              f"{ar_dres if ar_dres is not None else '-- ':>10.3f}  "
              f"{ar_res if ar_res is not None else '-- ':>9.3f}  {sd:>9.2f}  {mn:>10.2f}")
