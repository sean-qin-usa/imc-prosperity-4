"""Deep research session 8 part D — skew residual as VFE signal.

Hypothesis: smile-residual (skew minus delta-fit) predicts VFE returns.
Test residual LEVEL → ΔVFE at horizons K = 1, 5, 20, 100.
Test toy strategy: short VFE when residual high, long when low.
"""
import csv
import math
import statistics
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "round3"


def load_prices(day: int):
    out = {}
    with open(DATA / f"prices_round_3_day_{day}.csv") as f:
        rdr = csv.DictReader(f, delimiter=";")
        for r in rdr:
            p = r["product"]
            try:
                ts = int(r["timestamp"])
                mid = float(r["mid_price"])
                bb = float(r["bid_price_1"]) if r["bid_price_1"] else float("nan")
                ba = float(r["ask_price_1"]) if r["ask_price_1"] else float("nan")
            except Exception:
                continue
            out.setdefault(p, {})[ts] = (mid, bb, ba)
    return out


def corr(xs, ys):
    n = min(len(xs), len(ys))
    if n < 5:
        return 0.0
    xs = xs[:n]; ys = ys[:n]
    mx = sum(xs) / n; my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def main():
    print("LOADING ...")
    prices_all = {d: load_prices(d) for d in (0, 1, 2)}
    print("LOADED.")

    # Try multiple skew/butterfly definitions
    DEFS = [
        ("V5500-V5300", lambda p, t: p["VEV_5500"][t][0] - p["VEV_5300"][t][0]),
        ("V5500-V5200", lambda p, t: p["VEV_5500"][t][0] - p["VEV_5200"][t][0]),
        ("V5500-V5100", lambda p, t: p["VEV_5500"][t][0] - p["VEV_5100"][t][0]),
        ("V5500-V5000", lambda p, t: p["VEV_5500"][t][0] - p["VEV_5000"][t][0]),
        ("BFLY 5300-2x5400+5500", lambda p, t: p["VEV_5300"][t][0] - 2*p["VEV_5400"][t][0] + p["VEV_5500"][t][0]),
        ("V5300-V5000", lambda p, t: p["VEV_5300"][t][0] - p["VEV_5000"][t][0]),
        ("V5400-V5200", lambda p, t: p["VEV_5400"][t][0] - p["VEV_5200"][t][0]),
    ]

    for label, fn in DEFS:
        print(f"\n=== {label} as VFE signal ===")
        # Pool fit & test
        for day in (0, 1, 2):
            p = prices_all[day]
            keys_needed = ["VELVETFRUIT_EXTRACT", "VEV_5000", "VEV_5100", "VEV_5200",
                           "VEV_5300", "VEV_5400", "VEV_5500"]
            ts_common = sorted(set.intersection(*(set(p[k]) for k in keys_needed if k in p)))
            if len(ts_common) < 100:
                continue
            try:
                signal = [fn(p, t) for t in ts_common]
            except Exception:
                continue
            vfe = [p["VELVETFRUIT_EXTRACT"][t][0] for t in ts_common]
            n = len(signal)
            mvfe = sum(vfe) / n; msig = sum(signal) / n
            sxx = sum((vfe[i] - mvfe) ** 2 for i in range(n))
            sxy = sum((vfe[i] - mvfe) * (signal[i] - msig) for i in range(n))
            b = sxy / sxx if sxx > 0 else 0.0
            a = msig - b * mvfe
            residual = [signal[i] - (a + b * vfe[i]) for i in range(n)]
            # Residual level vs forward VFE return (K = 1, 5, 20, 100)
            # Forward VFE Δmid over K ticks: vfe[i+K] - vfe[i]
            corrs = []
            for K in (1, 5, 20, 100):
                if len(vfe) <= K + 1:
                    continue
                fwd = [vfe[i + K] - vfe[i] for i in range(len(vfe) - K)]
                res = residual[:len(fwd)]
                c = corr(res, fwd)
                corrs.append(f"K={K}:{c:+.4f}")
            print(f"  day {day}: a={a:+.1f} b={b:+.4f}  residual→fwd_VFE: {' '.join(corrs)}")


if __name__ == "__main__":
    main()
