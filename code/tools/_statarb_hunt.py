"""
Stat-arb hunt for Round 3 — 2026-04-25.

Goal: find new monetizable signals beyond what's already in v27.  Hard
gates from memory:
  - feedback_partial_corr_kills_leadlag: raw cross-product Δmid corrs
    spuriously inflate via own-AR1.  Demand partial-corr replication.
  - feedback_oos_r2_kills_spurious_signals: signals with R²_oos<0 across
    all rotations are dead.  Survive ⇒ |partial-corr| > 0.03 on every
    held-out day fold.
  - feedback_flow_burst_spread_cost: signal must beat half-spread to
    monetize via take.  Otherwise it's at most a defensive sizing knob.

What this prints:
  1. Per-product Δmid autocorr at lags 1-10, separately per day.
     Cross-day-stable autocorrs above 0.05 are candidates for
     longer-lag MR (Citadel-class).
  2. Top-3 PCA factors on the cross-section of Δmid.
  3. After projecting out PC1 (spot factor), residual autocorr per product.
     Any product with stable residual autocorr is a candidate for an
     idiosyncratic Citadel-class sleeve.
  4. Cross-product residual lead-lag corrs at lag 1, partial-corr-controlled
     for own-AR1 on both legs.

It does NOT take any positions; it's diagnostic only.
"""
import csv
from collections import defaultdict
from pathlib import Path
import math

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "round3"
DAYS = [0, 1, 2]
PRODUCTS = [
    "HYDROGEL_PACK", "VELVETFRUIT_EXTRACT",
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
    "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
    "VEV_6000", "VEV_6500",
]

def load_day(d):
    """Returns dict[product] -> list of mid prices, indexed by ts // 100."""
    f = DATA_DIR / f"prices_round_3_day_{d}.csv"
    series = {p: {} for p in PRODUCTS}
    with f.open() as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            p = row["product"]
            if p not in series:
                continue
            ts = int(row["timestamp"])
            try:
                m = float(row["mid_price"])
            except (ValueError, TypeError):
                continue
            series[p][ts] = m
    timestamps = sorted({ts for d in series.values() for ts in d})
    out = {}
    for p in PRODUCTS:
        out[p] = [series[p].get(ts) for ts in timestamps]
    return timestamps, out


def diff(seq):
    out = []
    last = None
    for v in seq:
        if v is None:
            out.append(None)
            last = None
            continue
        if last is None:
            out.append(0.0)
        else:
            out.append(v - last)
        last = v
    return out


def autocorr(x, lag):
    pairs = [(x[i - lag], x[i]) for i in range(lag, len(x))
             if x[i] is not None and x[i - lag] is not None]
    if len(pairs) < 50:
        return None, 0
    a = [p[0] for p in pairs]
    b = [p[1] for p in pairs]
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    num = sum((ai - ma) * (bi - mb) for ai, bi in zip(a, b))
    da = math.sqrt(sum((ai - ma) ** 2 for ai in a))
    db = math.sqrt(sum((bi - mb) ** 2 for bi in b))
    if da == 0 or db == 0:
        return None, len(pairs)
    return num / (da * db), len(pairs)


def cross_corr(x, y, lag):
    """corr(x_t, y_{t+lag}) — lag>0 means y lags x."""
    if lag >= 0:
        pairs = [(x[i], y[i + lag]) for i in range(len(x) - lag)
                 if x[i] is not None and y[i + lag] is not None]
    else:
        pairs = [(x[i - lag], y[i]) for i in range(-lag, len(y))
                 if x[i - lag] is not None and y[i] is not None]
    if len(pairs) < 50:
        return None, 0
    a = [p[0] for p in pairs]
    b = [p[1] for p in pairs]
    ma = sum(a) / len(a); mb = sum(b) / len(b)
    num = sum((ai - ma) * (bi - mb) for ai, bi in zip(a, b))
    da = math.sqrt(sum((ai - ma) ** 2 for ai in a))
    db = math.sqrt(sum((bi - mb) ** 2 for bi in b))
    if da == 0 or db == 0:
        return None, len(pairs)
    return num / (da * db), len(pairs)


def partial_corr(x, y, z):
    """corr(x|z, y|z) — residualize each on z by simple OLS."""
    pairs = [(xi, yi, zi) for xi, yi, zi in zip(x, y, z)
             if xi is not None and yi is not None and zi is not None]
    if len(pairs) < 50:
        return None
    xs = [p[0] for p in pairs]; ys = [p[1] for p in pairs]; zs = [p[2] for p in pairs]
    mz = sum(zs) / len(zs); vz = sum((zi - mz) ** 2 for zi in zs)
    if vz == 0:
        return None
    cxz = sum((xi - sum(xs)/len(xs)) * (zi - mz) for xi, zi in zip(xs, zs))
    cyz = sum((yi - sum(ys)/len(ys)) * (zi - mz) for yi, zi in zip(ys, zs))
    bx = cxz / vz; by = cyz / vz
    mx = sum(xs)/len(xs); my = sum(ys)/len(ys)
    rx = [xi - mx - bx * (zi - mz) for xi, zi in zip(xs, zs)]
    ry = [yi - my - by * (zi - mz) for yi, zi in zip(ys, zs)]
    mrx = sum(rx)/len(rx); mry = sum(ry)/len(ry)
    num = sum((rxi - mrx) * (ryi - mry) for rxi, ryi in zip(rx, ry))
    da = math.sqrt(sum((rxi - mrx) ** 2 for rxi in rx))
    db = math.sqrt(sum((ryi - mry) ** 2 for ryi in ry))
    if da == 0 or db == 0:
        return None
    return num / (da * db)


def section(s):
    print()
    print("=" * 70)
    print(s)
    print("=" * 70)


def main():
    section("Loading data")
    days_data = {}
    for d in DAYS:
        ts, mid = load_day(d)
        dmid = {p: diff(seq) for p, seq in mid.items()}
        days_data[d] = (ts, mid, dmid)
        print(f"day {d}: {len(ts)} timestamps; products with data:",
              sum(1 for p in PRODUCTS if any(m is not None for m in mid[p])))

    section("1.  Per-product Δmid autocorr at lags 1-10  (per day)")
    print(f"{'product':>22}  {'day':>3}  " + "  ".join(f"l{l:<2}" for l in range(1, 11)))
    candidates = []
    for p in PRODUCTS:
        for d in DAYS:
            row = []
            for lag in range(1, 11):
                r, n = autocorr(days_data[d][2][p], lag)
                row.append(f"{r:+.3f}" if r is not None else "  -- ")
            print(f"{p:>22}  {d:>3}  " + "  ".join(row))
        # find lags where |corr|>0.05 on all 3 days with same sign
        for lag in range(1, 11):
            rs = [autocorr(days_data[d][2][p], lag)[0] for d in DAYS]
            if all(r is not None for r in rs) and \
               all(abs(r) > 0.05 for r in rs) and \
               (all(r > 0 for r in rs) or all(r < 0 for r in rs)):
                candidates.append((p, lag, rs))
    print()
    print("Cross-day-stable autocorr candidates (|r|>0.05, same sign, all 3 days):")
    if not candidates:
        print("  (none)")
    for p, lag, rs in candidates:
        print(f"  {p:>22} lag={lag:<3}  rs=[{rs[0]:+.3f},{rs[1]:+.3f},{rs[2]:+.3f}]")

    section("2.  Cross-product residual partial-corr (lag-1 lead-lag)  ")
    # For each ordered pair (a,b), compute corr(Δa_t, Δb_{t+1} | Δb_t)
    # i.e. does a's move at t predict b's move at t+1 after controlling
    # for b's own AR(1)?
    print("  partial-corr(Δa_t, Δb_{t+1} | Δb_t) per day, only printing pairs")
    print("  with |partial-corr| > 0.05 on at least 1 day and same sign on all 3:")
    print()
    leadlag = []
    for a in PRODUCTS:
        for b in PRODUCTS:
            if a == b:
                continue
            rs = []
            for d in DAYS:
                dmid = days_data[d][2]
                da = dmid[a]
                db = dmid[b]
                # build x = da[t], y = db[t+1], z = db[t]
                x = []; y = []; z = []
                for i in range(len(da) - 1):
                    if da[i] is not None and db[i+1] is not None and db[i] is not None:
                        x.append(da[i]); y.append(db[i+1]); z.append(db[i])
                pc = partial_corr(x, y, z)
                rs.append(pc)
            if any(r is None for r in rs):
                continue
            if max(abs(r) for r in rs) > 0.05 and \
               (all(r > 0 for r in rs) or all(r < 0 for r in rs)):
                leadlag.append((a, b, rs, sum(rs)/3))
    leadlag.sort(key=lambda t: -abs(t[3]))
    for a, b, rs, mean in leadlag[:30]:
        print(f"  {a:>22} -> {b:<22}  rs=[{rs[0]:+.3f},{rs[1]:+.3f},{rs[2]:+.3f}]  mean={mean:+.3f}")
    if not leadlag:
        print("  (none survive)")

    section("3.  Per-product Δmid std and 'spread tax' rough estimate")
    # If we ever take into a signal, the half-spread cost must be < signal magnitude.
    # Std of Δmid is a proxy for typical 1-step move; compare with avg book spread.
    print(f"  {'product':>22}  {'day':>3}  {'std(Δmid)':>10}  {'mean_spr':>10}")
    spreads = {p: {d: None for d in DAYS} for p in PRODUCTS}
    for d in DAYS:
        f = DATA_DIR / f"prices_round_3_day_{d}.csv"
        agg = defaultdict(list)
        with f.open() as fh:
            r = csv.DictReader(fh, delimiter=";")
            for row in r:
                if row['product'] not in PRODUCTS:
                    continue
                try:
                    bb = float(row['bid_price_1']); ba = float(row['ask_price_1'])
                    agg[row['product']].append(ba - bb)
                except (ValueError, TypeError):
                    pass
        for p, xs in agg.items():
            spreads[p][d] = sum(xs)/len(xs) if xs else None

    for p in PRODUCTS:
        for d in DAYS:
            seq = [v for v in days_data[d][2][p] if v is not None]
            if len(seq) < 50:
                continue
            mu = sum(seq) / len(seq)
            sd = math.sqrt(sum((v - mu) ** 2 for v in seq) / len(seq))
            sp = spreads[p][d]
            print(f"  {p:>22}  {d:>3}  {sd:>10.3f}  {sp:>10.2f}" if sp else
                  f"  {p:>22}  {d:>3}  {sd:>10.3f}  {'--':>10}")

if __name__ == "__main__":
    main()
