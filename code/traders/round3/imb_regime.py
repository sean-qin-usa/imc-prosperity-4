"""Quick check: own L1 imbalance → next-tick ΔH conditional on spread."""
import csv, math
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path("/Users/sean_tsu_/Downloads/prosperity/IMCP2026/data/round3")

def load(day):
    rows = []
    fp = DATA_DIR / f"prices_round_3_day_{day}.csv"
    with fp.open() as fh:
        rd = csv.DictReader(fh, delimiter=";")
        for r in rd:
            if r["product"] != "HYDROGEL_PACK":
                continue
            try:
                bb = float(r["bid_price_1"]); ba = float(r["ask_price_1"])
                bv = float(r["bid_volume_1"]); av = float(r["ask_volume_1"])
                m = float(r["mid_price"])
                rows.append((int(r["timestamp"]), m, bb, ba, bv, av))
            except (KeyError, ValueError):
                pass
    rows.sort()
    return rows

def main():
    print("Own L1 imbalance → next-tick ΔH, conditional on spread")
    print("imb = (bv-av)/(bv+av).  Buckets: imb in {<-0.5, -0.5..0, 0..+0.5, >+0.5}")
    for day in [0, 1, 2]:
        print(f"\n--- DAY {day} ---")
        rows = load(day)
        for spr_lo, spr_hi in [(0, 7), (8, 15), (16, 16), (17, 50)]:
            buckets = {(-1, -0.5): [], (-0.5, 0): [], (0, 0.5): [], (0.5, 1): []}
            for i in range(len(rows) - 1):
                ts, m, bb, ba, bv, av = rows[i]
                spr = ba - bb
                if not (spr_lo <= spr <= spr_hi): continue
                if (bv + av) <= 0: continue
                imb = (bv - av) / (bv + av)
                next_m = rows[i + 1][1]
                if next_m is None or m is None: continue
                fwd = next_m - m
                for (lo, hi), vals in buckets.items():
                    if lo <= imb < hi or (hi == 1 and imb >= 0.5):
                        vals.append(fwd); break
            print(f"  spread {spr_lo}-{spr_hi}:")
            for (lo, hi), vals in buckets.items():
                if vals:
                    n = len(vals); m = sum(vals) / n
                    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / n) if n > 1 else 0
                    se = sd / math.sqrt(n) if n > 1 else 0
                    z = m / se if se > 0 else 0
                    print(f"    imb [{lo:+.1f},{hi:+.1f})  n={n:5d}  E[ΔH]={m:+.4f}  z={z:+.2f}")

    # Also: micro-price vs touch-mid agreement with next-tick mid
    print("\n\n>>> Micro-price as fair input: how often does it predict NEXT mid better than touch_mid?")
    for day in [0, 1, 2]:
        rows = load(day)
        better = 0; equal = 0; worse = 0; total = 0
        for i in range(len(rows) - 1):
            ts, m, bb, ba, bv, av = rows[i]
            if (bv + av) <= 0: continue
            tm = (bb + ba) / 2
            mp = (ba * bv + bb * av) / (bv + av)  # micro-price
            next_m = rows[i + 1][1]
            if next_m is None: continue
            d_tm = abs(next_m - tm)
            d_mp = abs(next_m - mp)
            if d_mp < d_tm: better += 1
            elif d_mp > d_tm: worse += 1
            else: equal += 1
            total += 1
        print(f"  day {day}:  micro better {better/total:.3f}  equal {equal/total:.3f}  worse {worse/total:.3f}  (n={total})")

if __name__ == "__main__":
    main()
