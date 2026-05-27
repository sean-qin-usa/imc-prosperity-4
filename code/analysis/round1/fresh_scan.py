"""
First-principles §0.2 scan for P4 Round 1.
Run: python3 analysis/fresh_scan_round1.py
Implements SIGNALS_PLAYBOOK §0.2 + §1a + §1b — reusable for any round
by changing DATA / DAYS / filename pattern.
"""
import csv
from collections import defaultdict
from pathlib import Path

DATA = Path("/Users/sean_tsu_/Downloads/prosperity/IMCP2026/data/round1")
DAYS = [-2, -1, 0]
FILE_PATTERN = "prices_round_1_day_{d}.csv"


def load_day(day):
    path = DATA / FILE_PATTERN.format(d=day)
    out = defaultdict(list)
    with path.open() as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            bp1 = int(row["bid_price_1"]) if row["bid_price_1"] else None
            ap1 = int(row["ask_price_1"]) if row["ask_price_1"] else None
            if bp1 is None or ap1 is None: continue
            out[row["product"]].append({
                "ts": int(row["timestamp"]),
                "bp1": bp1,
                "bv1": int(row["bid_volume_1"]) if row["bid_volume_1"] else 0,
                "ap1": ap1,
                "av1": int(row["ask_volume_1"]) if row["ask_volume_1"] else 0,
                "mid": float(row["mid_price"]),
            })
    return out


def ols(xs, ys):
    n = len(xs); mx = sum(xs)/n; my = sum(ys)/n
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    den = sum((x-mx)**2 for x in xs)
    return (num/den if den else 0, my - (num/den if den else 0)*mx)


def pearson(xs, ys):
    n = len(xs)
    if n < 2: return 0.0
    mx = sum(xs)/n; my = sum(ys)/n
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx = (sum((x-mx)**2 for x in xs))**0.5
    dy = (sum((y-my)**2 for y in ys))**0.5
    return num/(dx*dy) if dx and dy else 0.0


def summarize(prod, rows, day):
    ts = [r["ts"] for r in rows]
    mids = [r["mid"] for r in rows]
    s, i = ols(ts, mids)
    resid = [m - (s*t + i) for t, m in zip(ts, mids)]
    rm = sum(resid)/len(resid)
    rsd = (sum((r-rm)**2 for r in resid)/len(resid))**0.5
    dm = [mids[k+1]-mids[k] for k in range(len(mids)-1)]
    ar1 = pearson(dm[:-1], dm[1:]) if len(dm) > 2 else 0
    spreads = [r["ap1"]-r["bp1"] for r in rows]
    imbs, dms = [], []
    for k in range(len(rows)-1):
        t = rows[k]["bv1"] + rows[k]["av1"]
        if t:
            imbs.append((rows[k]["bv1"]-rows[k]["av1"])/t)
            dms.append(rows[k+1]["mid"]-rows[k]["mid"])
    ir = pearson(imbs, dms)
    up = [d for im,d in zip(imbs,dms) if im > 0.5]
    dn = [d for im,d in zip(imbs,dms) if im < -0.5]
    up_p = sum(1 for d in up if d>0)/len(up) if up else 0
    dn_p = sum(1 for d in dn if d<0)/len(dn) if dn else 0
    sc = defaultdict(int)
    for sp in spreads: sc[sp] += 1
    top_sp = sorted(sc.items(), key=lambda kv: -kv[1])[:5]
    by_sp = defaultdict(list)
    for k in range(len(rows)-1):
        sp = rows[k]["ap1"]-rows[k]["bp1"]
        by_sp[sp].append(rows[k+1]["mid"]-rows[k]["mid"])
    print(f"\n== {prod} day {day}  n={len(rows)} ==")
    print(f"  drift slope = {s*1_000_000:+.4f} per 1e6 ts  (full-day {s*ts[-1]:+.2f})")
    print(f"  residual sd {rsd:.3f}  AR(1) {ar1:.3f}")
    print(f"  mid mean={sum(mids)/len(mids):.2f} first={mids[0]:.1f} last={mids[-1]:.1f}")
    print(f"  spread: min={min(spreads)} max={max(spreads)} avg={sum(spreads)/len(spreads):.2f}")
    print(f"  top spreads: {[(sp,c) for sp,c in top_sp]}")
    print(f"  imb→Δmid r={ir:.3f}  n={len(imbs)}")
    if up: print(f"    imb>+0.5 E[Δ]={sum(up)/len(up):+.2f} P(up)={up_p:.1%} n={len(up)}")
    if dn: print(f"    imb<-0.5 E[Δ]={sum(dn)/len(dn):+.2f} P(dn)={dn_p:.1%} n={len(dn)}")
    # imb r by spread bucket (the key R2 caveat — check for dead zone)
    print(f"  imb→Δmid r by spread (scan E):")
    for sp in sorted(by_sp):
        sample_ids = [k for k in range(len(rows)-1) if rows[k]["ap1"]-rows[k]["bp1"] == sp and (rows[k]["bv1"]+rows[k]["av1"]) > 0]
        if len(sample_ids) < 100: continue
        im_s = [(rows[k]["bv1"]-rows[k]["av1"])/(rows[k]["bv1"]+rows[k]["av1"]) for k in sample_ids]
        dm_s = [rows[k+1]["mid"]-rows[k]["mid"] for k in sample_ids]
        print(f"    spread={sp:3d} n={len(sample_ids):5d} r={pearson(im_s,dm_s):+.3f}")


if __name__ == "__main__":
    for d in DAYS:
        print(f"\n########## DAY {d} ##########")
        data = load_day(d)
        for prod in sorted(data):
            summarize(prod, data[prod], d)
