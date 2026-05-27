"""
§0.2 scan on Prosperity 3 Round 2 data.
Applies SIGNALS_PLAYBOOK §0.1 + §0.2 + basket-spread analysis (§0.1 story #4).
"""
import csv
from collections import defaultdict
from pathlib import Path

DATA = Path("/Users/sean_tsu_/Downloads/prosperity/practice/winners/carter-prosperity-3/data/round-2-island-data-bottle")
DAYS = [-1, 0, 1]


def load_day(day):
    path = DATA / f"prices_round_2_day_{day}.csv"
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
    sc = defaultdict(int)
    for sp in spreads: sc[sp] += 1
    top_sp = sorted(sc.items(), key=lambda kv: -kv[1])[:3]
    print(f"  {prod} d{day} n={len(rows)} drift={s*1_000_000:+.3f}/1e6 rsd={rsd:.2f} ar1={ar1:+.3f} mid[{mids[0]:.1f}->{mids[-1]:.1f}] sp={[(sp,c) for sp,c in top_sp]} imb_r={ir:+.3f}")


def basket_spread(day_data, day):
    """Trade story #4: basket mid vs synthetic (6C+3J+1D or 4C+2J)."""
    need = ["PICNIC_BASKET1", "PICNIC_BASKET2", "CROISSANTS", "JAMS", "DJEMBES"]
    mids = {p: {r["ts"]: r["mid"] for r in day_data.get(p, [])} for p in need}
    if not all(mids.values()): return
    common_ts = set(mids[need[0]].keys())
    for p in need[1:]: common_ts &= set(mids[p].keys())
    tslist = sorted(common_ts)
    diff1 = [mids["PICNIC_BASKET1"][t] - (6*mids["CROISSANTS"][t] + 3*mids["JAMS"][t] + 1*mids["DJEMBES"][t]) for t in tslist]
    diff2 = [mids["PICNIC_BASKET2"][t] - (4*mids["CROISSANTS"][t] + 2*mids["JAMS"][t]) for t in tslist]
    print(f"  day {day}  PB1 - synth:  mean={sum(diff1)/len(diff1):+.2f}  sd={(sum((d-sum(diff1)/len(diff1))**2 for d in diff1)/len(diff1))**0.5:.2f}  min={min(diff1):+.1f} max={max(diff1):+.1f}")
    print(f"  day {day}  PB2 - synth:  mean={sum(diff2)/len(diff2):+.2f}  sd={(sum((d-sum(diff2)/len(diff2))**2 for d in diff2)/len(diff2))**0.5:.2f}  min={min(diff2):+.1f} max={max(diff2):+.1f}")
    # AR(1) of the spread — does it mean-revert tick-to-tick?
    for name, d in [("PB1-synth", diff1), ("PB2-synth", diff2)]:
        dm = [d[i+1]-d[i] for i in range(len(d)-1)]
        ar = pearson(dm[:-1], dm[1:]) if len(dm) > 2 else 0
        # and persistence: corr(d_t, d_{t+1})
        pers = pearson(d[:-1], d[1:])
        print(f"    {name}: diff-AR(1)={ar:+.3f}  persistence(d_t, d_t+1)={pers:+.3f}")


if __name__ == "__main__":
    for d in DAYS:
        print(f"\n########## DAY {d} ##########")
        data = load_day(d)
        for prod in sorted(data):
            summarize(prod, data[prod], d)
        print("  -- basket spread --")
        basket_spread(data, d)
