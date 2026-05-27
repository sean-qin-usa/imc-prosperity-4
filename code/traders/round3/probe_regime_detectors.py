"""Probe regime detectors that should distinguish day 1 (drift) from day 0/2.

For each detector, we score:
  - mean & max absolute value per day  (we want day 1 strictly > day 0/2)
  - what fraction of ticks would 'fire' at thresholds T

Detectors:
  A) EMA(touch_mid - anchor) with windows {500, 1000, 2000, 5000}
  B) block-100 directional drift = mid[i] - mid[i-100]
  C) recent-N |mid - anchor| moving average for N in {500, 2000}
"""
import csv
import math
import statistics
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "round3"
ANCHOR = 9983.0


def load_day(day):
    rows = []
    with open(DATA / f"prices_round_3_day_{day}.csv") as f:
        rdr = csv.DictReader(f, delimiter=";")
        for r in rdr:
            if r["product"] != "HYDROGEL_PACK":
                continue
            try:
                ts = int(r["timestamp"])
                bb = float(r["bid_price_1"])
                ba = float(r["ask_price_1"])
                tm = 0.5 * (bb + ba)
            except Exception:
                continue
            rows.append((ts, tm))
    rows.sort()
    return [r[1] for r in rows]


def ema_series(xs, alpha):
    out = []
    e = xs[0]
    for x in xs:
        e = alpha * x + (1 - alpha) * e
        out.append(e)
    return out


def summarize_arr(arr, label):
    abs_arr = [abs(x) for x in arr]
    return {
        "label": label,
        "n": len(arr),
        "mean_abs": sum(abs_arr) / len(arr),
        "median_abs": statistics.median(abs_arr),
        "p90_abs": sorted(abs_arr)[int(len(abs_arr) * 0.9)],
        "p99_abs": sorted(abs_arr)[int(len(abs_arr) * 0.99)],
        "max_abs": max(abs_arr),
        "signed_mean": sum(arr) / len(arr),
    }


def main():
    mids = {d: load_day(d) for d in (0, 1, 2)}
    devs = {d: [m - ANCHOR for m in mids[d]] for d in (0, 1, 2)}

    print("\n=== A) EMA(touch_mid - anchor) ===")
    print("alpha corresponds to a half-life of about ln(2)/alpha ticks; window ~ 1/alpha")
    for win in (500, 1000, 2000, 5000):
        alpha = 1.0 / win
        print(f"\n  --- window={win}  alpha={alpha:.5f} ---")
        for d in (0, 1, 2):
            ema = ema_series(devs[d], alpha)
            s = summarize_arr(ema, f"day{d}")
            print(f"  day{d}: signed_mean {s['signed_mean']:+7.2f}  mean|x| {s['mean_abs']:6.2f}  p90 {s['p90_abs']:6.2f}  p99 {s['p99_abs']:6.2f}  max {s['max_abs']:6.2f}")

    print("\n=== B) block-100 drift = mid[i] - mid[i-100] ===")
    for d in (0, 1, 2):
        m = mids[d]
        b100 = [m[i] - m[i - 100] for i in range(100, len(m))]
        s = summarize_arr(b100, f"day{d}")
        print(f"  day{d}: signed_mean {s['signed_mean']:+7.3f}  mean|x| {s['mean_abs']:6.2f}  p90 {s['p90_abs']:6.2f}  p99 {s['p99_abs']:6.2f}")

    print("\n=== B') block-500 drift = mid[i] - mid[i-500] ===")
    for d in (0, 1, 2):
        m = mids[d]
        b = [m[i] - m[i - 500] for i in range(500, len(m))]
        s = summarize_arr(b, f"day{d}")
        print(f"  day{d}: signed_mean {s['signed_mean']:+7.3f}  mean|x| {s['mean_abs']:6.2f}  p90 {s['p90_abs']:6.2f}  p99 {s['p99_abs']:6.2f}")

    print("\n=== C) rolling-N |mid - anchor| mean ===")
    for N in (500, 2000):
        print(f"\n  --- N={N} ---")
        for d in (0, 1, 2):
            v = devs[d]
            absdev = [abs(x) for x in v]
            # Moving average over absolute deviation
            roll = []
            csum = 0.0
            from collections import deque
            q = deque()
            for x in absdev:
                q.append(x)
                csum += x
                if len(q) > N:
                    csum -= q.popleft()
                roll.append(csum / len(q))
            s = summarize_arr(roll, f"day{d}")
            print(f"  day{d}: signed_mean {s['signed_mean']:+6.2f}  mean {s['mean_abs']:6.2f}  p90 {s['p90_abs']:6.2f}  max {s['max_abs']:6.2f}")

    # Rank detectors: contrast = day1 / max(day0, day2) on mean_abs of EMA
    print("\n=== Discriminator quality (day1 mean_abs / max(day0, day2) mean_abs) ===")
    print("Higher = better (day 1 stands out)")
    for win in (500, 1000, 2000, 5000):
        alpha = 1.0 / win
        emas = {d: ema_series(devs[d], alpha) for d in (0, 1, 2)}
        means = {d: sum(abs(x) for x in emas[d]) / len(emas[d]) for d in (0, 1, 2)}
        contrast = means[1] / max(means[0], means[2])
        print(f"  EMA win {win}:  d0={means[0]:6.2f}  d1={means[1]:6.2f}  d2={means[2]:6.2f}   contrast={contrast:.2f}")

    # Show fraction-of-ticks where |EMA| > threshold T
    print("\n=== Fraction of ticks with |EMA(window=2000)| > T ===")
    alpha = 1.0 / 2000
    emas = {d: ema_series(devs[d], alpha) for d in (0, 1, 2)}
    for T in (5, 10, 15, 20, 30):
        print(f"  T={T:3d}:  d0={sum(1 for x in emas[0] if abs(x)>T)/len(emas[0]):.1%}   d1={sum(1 for x in emas[1] if abs(x)>T)/len(emas[1]):.1%}   d2={sum(1 for x in emas[2] if abs(x)>T)/len(emas[2]):.1%}")


if __name__ == "__main__":
    main()
