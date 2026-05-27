"""Compare HYDROGEL volatility regime across days 0/1/2.

Goal: identify what makes day 1 underperform.
"""
import csv
import math
import statistics
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "round3"


def load_day(day: int):
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
                bv = float(r["bid_volume_1"])
                av = float(r["ask_volume_1"])
                mid = float(r["mid_price"])
            except Exception:
                continue
            rows.append((ts, mid, bb, ba, bv, av, ba - bb))
    rows.sort()
    return rows


def ar1(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    num = sum((xs[i] - m) * (xs[i - 1] - m) for i in range(1, n))
    den = sum((x - m) ** 2 for x in xs)
    return num / den if den > 0 else 0.0


def stats(rows, label):
    mids = [r[1] for r in rows]
    spreads = [r[6] for r in rows]
    dmid = [mids[i] - mids[i - 1] for i in range(1, len(mids))]
    abs_dmid = [abs(d) for d in dmid]
    n = len(dmid)

    def roll_std(window):
        out = []
        for i in range(window, len(dmid)):
            chunk = dmid[i - window:i]
            m = sum(chunk) / window
            v = sum((x - m) ** 2 for x in chunk) / window
            out.append(math.sqrt(v))
        return out

    s50 = roll_std(50)
    s150 = roll_std(150)
    clip_v16 = [33 + 0.76 * s for s in s150]
    clip_v8 = [33 + 0.3 * s for s in s50]

    print(f"\n=== Day {label} ===")
    print(f"  ticks               : {len(rows)}")
    print(f"  mid range           : [{min(mids):.0f}, {max(mids):.0f}]  (range={max(mids)-min(mids):.0f})")
    print(f"  mid mean / median   : {sum(mids)/len(mids):.2f}  /  {statistics.median(mids):.2f}")
    print(f"  mid std (full)      : {statistics.pstdev(mids):.2f}")
    print(f"  |Δmid| mean         : {sum(abs_dmid)/n:.4f}")
    print(f"  Δmid std            : {statistics.pstdev(dmid):.4f}")
    print(f"  Δmid AR(1)          : {ar1(dmid):+.4f}")
    print(f"  spread mean         : {sum(spreads)/len(spreads):.2f}")
    print(f"  spread mode (16)    : {sum(1 for s in spreads if s == 16)/len(spreads):.1%}")
    print(f"  spread <16 share    : {sum(1 for s in spreads if s < 16)/len(spreads):.1%}")
    print(f"  spread >16 share    : {sum(1 for s in spreads if s > 16)/len(spreads):.1%}")
    print(f"  rolling50 std mean  : {sum(s50)/len(s50):.3f}")
    print(f"  rolling150 std mean : {sum(s150)/len(s150):.3f}")
    print(f"  CLIP_v16 mean       : {sum(clip_v16)/len(clip_v16):.2f}  median {statistics.median(clip_v16):.2f}  max {max(clip_v16):.2f}")
    print(f"  CLIP_v8 mean        : {sum(clip_v8)/len(clip_v8):.2f}  median {statistics.median(clip_v8):.2f}")

    # Drift / runs analysis
    big_jump = sum(1 for d in abs_dmid if d >= 5)
    print(f"  |Δmid|>=5  : {big_jump}  ({big_jump/n:.1%})")

    # 5-tick block returns (drift in 5-tick windows)
    block5 = [mids[i+5]-mids[i] for i in range(0, len(mids)-5, 5)]
    block20 = [mids[i+20]-mids[i] for i in range(0, len(mids)-20, 20)]
    block100 = [mids[i+100]-mids[i] for i in range(0, len(mids)-100, 100)]
    print(f"  block5  mean/std     : {sum(block5)/len(block5):+.3f} / {statistics.pstdev(block5):.3f}")
    print(f"  block20 mean/std     : {sum(block20)/len(block20):+.3f} / {statistics.pstdev(block20):.3f}")
    print(f"  block100 mean/std    : {sum(block100)/len(block100):+.3f} / {statistics.pstdev(block100):.3f}")

    # Distance-from-anchor distribution (vs H_ANCHOR=9983)
    devs = [m - 9983 for m in mids]
    devs_sorted = sorted([abs(d) for d in devs])
    nm = len(devs)
    print(f"  |mid-9983| q50/q90/q95/q99/max: {devs_sorted[nm//2]:.0f} / {devs_sorted[int(nm*0.9)]:.0f} / {devs_sorted[int(nm*0.95)]:.0f} / {devs_sorted[int(nm*0.99)]:.0f} / {max(devs_sorted):.0f}")
    print(f"  mid > 9983+33 share : {sum(1 for d in devs if d > 33)/len(devs):.1%}")
    print(f"  mid < 9983-33 share : {sum(1 for d in devs if d < -33)/len(devs):.1%}")
    return rows, dmid, spreads


def windows(label, rows, dmid, win_ticks=2000):
    print(f"\n  --- per-{win_ticks}tick windows on day {label} ---")
    n = len(dmid)
    print(f"   bucket   tick_range          mid_avg   |Δmid|mean   std    |Δmid|>=5  s>16%   spread<16%")
    spreads = [r[6] for r in rows]
    mids = [r[1] for r in rows]
    for i in range(0, n, win_ticks):
        c = dmid[i:i+win_ticks]
        if not c:
            continue
        adm = [abs(x) for x in c]
        m = sum(adm) / len(c)
        std = math.sqrt(sum((x - sum(c)/len(c))**2 for x in c) / len(c))
        big = sum(1 for x in adm if x >= 5)
        sp = spreads[i:i+win_ticks]
        sp_wide = sum(1 for s in sp if s > 16) / max(1, len(sp))
        sp_tight = sum(1 for s in sp if s < 16) / max(1, len(sp))
        mc = mids[i:i+win_ticks]
        mid_avg = sum(mc) / len(mc)
        print(f"   {i//win_ticks:>2}     [{i:>5}-{i+win_ticks:>5}]    {mid_avg:7.1f}    {m:6.3f}      {std:6.3f}  {big:>5}     {sp_wide:.1%}    {sp_tight:.1%}")


def main():
    for d in (0, 1, 2):
        rows = load_day(d)
        _, dmid, _ = stats(rows, d)
        windows(d, rows, dmid)


if __name__ == "__main__":
    main()
