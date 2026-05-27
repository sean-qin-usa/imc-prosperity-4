"""Deep research session 8: hunt for new alpha categories beyond retunes.

Tests (all per-product where applicable; all on round-3 data days 0-2):

  A. Volatility clustering: |Δmid|, AR(1)..AR(20), and squared-Δmid AR
  B. Trade-flow leading indicator: signed_volume(t-K..t) → Δmid(t..t+K)
  C. Time-of-day patterns: per-decile-of-day mean Δmid, |Δmid|, fill rate
  D. End-of-day reversal: last 1k ticks vs first 1k ticks
  E. Basket / smile arb: butterfly (5300 - 2*5400 + 5500) and skew (5500 - 5300)
     stationarity, pair-trade attractiveness
  F. IV-smile-tilt → spot: ΔIV_skew → next-tick VFE Δmid
  G. Cross-strike block returns at K = {5, 20, 100, 500}
  H. Time-weighted VFE carry: last quarter only (drift accelerates near EOD?)
"""
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "round3"

PRODUCTS = [
    "HYDROGEL_PACK", "VELVETFRUIT_EXTRACT",
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
    "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
    "VEV_6000", "VEV_6500",
]


def load_prices(day: int):
    """Returns dict[product] = list of (ts, mid, bb, ba, bv, av, spread)."""
    out = {p: [] for p in PRODUCTS}
    with open(DATA / f"prices_round_3_day_{day}.csv") as f:
        rdr = csv.DictReader(f, delimiter=";")
        for r in rdr:
            p = r["product"]
            if p not in out:
                continue
            try:
                ts = int(r["timestamp"])
                bb = float(r["bid_price_1"]) if r["bid_price_1"] else float("nan")
                ba = float(r["ask_price_1"]) if r["ask_price_1"] else float("nan")
                bv = float(r["bid_volume_1"]) if r["bid_volume_1"] else 0
                av = float(r["ask_volume_1"]) if r["ask_volume_1"] else 0
                mid = float(r["mid_price"])
            except Exception:
                continue
            out[p].append((ts, mid, bb, ba, bv, av, ba - bb))
    for p in out:
        out[p].sort()
    return out


def load_trades(day: int):
    """Returns dict[product] = list of (ts, price, quantity)."""
    out = {p: [] for p in PRODUCTS}
    with open(DATA / f"trades_round_3_day_{day}.csv") as f:
        rdr = csv.DictReader(f, delimiter=";")
        for r in rdr:
            p = r["symbol"]
            if p not in out:
                continue
            try:
                ts = int(r["timestamp"])
                price = float(r["price"])
                qty = float(r["quantity"])
            except Exception:
                continue
            out[p].append((ts, price, qty))
    return out


def ar_k(xs, k):
    n = len(xs)
    if n <= k:
        return 0.0, n
    m = sum(xs) / n
    num = sum((xs[i] - m) * (xs[i - k] - m) for i in range(k, n))
    den = sum((x - m) ** 2 for x in xs)
    return (num / den if den > 0 else 0.0), n - k


def section_a_vol_clustering(prices_all):
    """A. Volatility clustering: AR(K) on |Δmid| and Δmid² across products."""
    print("\n" + "=" * 70)
    print("A. VOLATILITY CLUSTERING — AR(K) on |Δmid| and Δmid²")
    print("=" * 70)
    print(f"{'product':>22}  {'|Δm| AR1':>9} {'AR5':>7} {'AR20':>7}  {'Δm² AR1':>9} {'AR5':>7} {'AR20':>7}  std(|Δm|)")
    for prod in PRODUCTS:
        all_dm = []
        for day in (0, 1, 2):
            mids = [r[1] for r in prices_all[day][prod]]
            dm = [mids[i] - mids[i - 1] for i in range(1, len(mids))]
            all_dm.extend(dm)
        if not all_dm:
            continue
        abs_dm = [abs(x) for x in all_dm]
        sq_dm = [x * x for x in all_dm]
        a1, _ = ar_k(abs_dm, 1)
        a5, _ = ar_k(abs_dm, 5)
        a20, _ = ar_k(abs_dm, 20)
        s1, _ = ar_k(sq_dm, 1)
        s5, _ = ar_k(sq_dm, 5)
        s20, _ = ar_k(sq_dm, 20)
        std_a = statistics.pstdev(abs_dm)
        print(f"{prod:>22}  {a1:>+9.4f} {a5:>+7.4f} {a20:>+7.4f}  {s1:>+9.4f} {s5:>+7.4f} {s20:>+7.4f}  {std_a:.3f}")
    print("\nInterp: AR(K) > 0.05 on |Δm| or Δm² => exploitable vol clustering.")


def section_b_trade_flow(prices_all, trades_all):
    """B. Trade flow → next-tick Δmid (signed flow, lag 1..5)."""
    print("\n" + "=" * 70)
    print("B. TRADE FLOW → NEXT-TICK Δmid")
    print("=" * 70)
    print("Sign convention: trade @ ask = +qty (buy aggression), @ bid = -qty.")
    print(f"{'product':>22}  {'corr lag1':>10} {'lag2':>7} {'lag5':>7}  {'#bins':>6}")
    for prod in PRODUCTS:
        # Per-tick signed flow (binned into 100-ts buckets matching prices)
        flows_per_day = []
        dmids_per_day = []
        for day in (0, 1, 2):
            prices = prices_all[day][prod]
            trades = trades_all[day][prod]
            if not prices or not trades:
                continue
            ts_to_idx = {p[0]: i for i, p in enumerate(prices)}
            flow_by_idx = defaultdict(float)
            for t_ts, t_p, t_q in trades:
                # Find the latest ts in prices <= t_ts
                # Trades happen between ticks; assign to next tick
                bucket_ts = (t_ts // 100) * 100
                # Use prices[i] = current best bid/ask before trade
                idx = ts_to_idx.get(bucket_ts)
                if idx is None:
                    continue
                bb, ba = prices[idx][2], prices[idx][3]
                if math.isnan(bb) or math.isnan(ba):
                    continue
                mid = (bb + ba) / 2
                if t_p >= mid:
                    flow_by_idx[idx] += t_q
                else:
                    flow_by_idx[idx] -= t_q
            mids = [p[1] for p in prices]
            flow = [flow_by_idx.get(i, 0.0) for i in range(len(mids))]
            dm = [mids[i] - mids[i - 1] for i in range(1, len(mids))]
            flows_per_day.append(flow[:-1])
            dmids_per_day.append(dm)
        if not flows_per_day:
            print(f"{prod:>22}  no data")
            continue
        flow_all = [f for d in flows_per_day for f in d]
        dm_all = [x for d in dmids_per_day for x in d]
        n = min(len(flow_all), len(dm_all))
        flow_all = flow_all[:n]
        dm_all = dm_all[:n]
        c1 = corr(flow_all, dm_all)
        # lag 2: flow at t-1 vs Δm at t+1
        c2 = corr(flow_all[:-1], dm_all[1:])
        c5 = corr(flow_all[:-4], dm_all[4:])
        nz = sum(1 for f in flow_all if f != 0)
        print(f"{prod:>22}  {c1:>+10.4f} {c2:>+7.4f} {c5:>+7.4f}  {nz:>6}")
    print("\nInterp: |corr| > 0.05 at lag>=1 => leading-indicator alpha (trade flow")
    print("at t predicts Δmid at t+1). Beware: aggressor flow is co-incident with")
    print("Δmid at lag 0 by definition; we want LEAD effect.")


def section_c_time_of_day(prices_all):
    """C. Per-decile time-of-day patterns."""
    print("\n" + "=" * 70)
    print("C. TIME-OF-DAY — per-decile Δmid mean and |Δmid| mean")
    print("=" * 70)
    bucket_n = 10
    print(f"{'product':>22}  decile-mean Δmid (×10): each col is 10% of day")
    print(f"{'':>22}  d0  d1  d2  d3  d4  d5  d6  d7  d8  d9")
    for prod in PRODUCTS:
        means = []
        for day in (0, 1, 2):
            prices = prices_all[day][prod]
            mids = [p[1] for p in prices]
            n = len(mids)
            if n < 100:
                continue
            for b in range(bucket_n):
                start = (n * b) // bucket_n
                end = (n * (b + 1)) // bucket_n
                if end - start < 2:
                    continue
                dm = [mids[i] - mids[i - 1] for i in range(start + 1, end)]
                if dm:
                    means.append((b, sum(dm) / len(dm)))
        # Aggregate per bucket across days
        by_b = defaultdict(list)
        for b, m in means:
            by_b[b].append(m)
        row = "  ".join(f"{statistics.mean(by_b[b]):>+5.3f}" for b in range(bucket_n) if b in by_b)
        print(f"{prod:>22}  {row}")
    print("\nInterp: large positive last-decile mean and large negative first-decile")
    print("mean => EOD/SOD predictability.")


def section_d_eod_reversal(prices_all):
    """D. End-of-day vs start-of-day cumulative drift."""
    print("\n" + "=" * 70)
    print("D. END-OF-DAY vs START-OF-DAY CUMULATIVE DRIFT")
    print("=" * 70)
    print(f"{'product':>22}  day  first1k  last1k  full   first1k_mean   last1k_mean")
    for prod in PRODUCTS:
        for day in (0, 1, 2):
            prices = prices_all[day][prod]
            mids = [p[1] for p in prices]
            if len(mids) < 2000:
                continue
            first1k = mids[1000] - mids[0]
            last1k = mids[-1] - mids[-1000]
            full = mids[-1] - mids[0]
            f_mean = first1k / 1000
            l_mean = last1k / 1000
            print(f"{prod:>22}  {day:>3}  {first1k:>+7.1f} {last1k:>+7.1f} {full:>+5.1f}   {f_mean:>+10.4f}   {l_mean:>+10.4f}")
    print("\nInterp: consistent sign in last-1k mean across days => EOD trend signal.")


def section_e_basket_smile(prices_all):
    """E. Basket / smile arbitrage: butterfly (5300 - 2*5400 + 5500) and skew."""
    print("\n" + "=" * 70)
    print("E. BASKET / SMILE — butterfly (5300 - 2*5400 + 5500) and skew (5500-5300)")
    print("=" * 70)
    for day in (0, 1, 2):
        p_5300 = prices_all[day]["VEV_5300"]
        p_5400 = prices_all[day]["VEV_5400"]
        p_5500 = prices_all[day]["VEV_5500"]
        # Align by timestamp
        d3 = {p[0]: p[1] for p in p_5300}
        d4 = {p[0]: p[1] for p in p_5400}
        d5 = {p[0]: p[1] for p in p_5500}
        common = sorted(set(d3) & set(d4) & set(d5))
        if not common:
            continue
        butterfly = [d3[t] - 2 * d4[t] + d5[t] for t in common]
        skew = [d5[t] - d3[t] for t in common]
        # Stationarity proxy: AR(1) of butterfly + skew
        bf_ar1, _ = ar_k(butterfly, 1)
        sk_ar1, _ = ar_k(skew, 1)
        # Stationarity proxy: full-day std and persistence
        bf_mean = statistics.mean(butterfly)
        bf_std = statistics.pstdev(butterfly)
        sk_mean = statistics.mean(skew)
        sk_std = statistics.pstdev(skew)
        print(f"day {day}  butterfly: mean={bf_mean:+.3f} std={bf_std:.3f} AR1={bf_ar1:+.3f}   skew(5500-5300): mean={sk_mean:+.3f} std={sk_std:.3f} AR1={sk_ar1:+.3f}")
    print("\nInterp: low-std butterfly with bounded range => mean-revertable basket;")
    print("AR(1) far from 1 = stationary, > 0.95 = near-random walk.")


def section_f_skew_spot(prices_all):
    """F. ΔIV_skew → next-tick VFE Δmid."""
    print("\n" + "=" * 70)
    print("F. SKEW → SPOT — Δskew(5500-5300) lead-lag vs VFE Δmid")
    print("=" * 70)
    for day in (0, 1, 2):
        p_5300 = {p[0]: p[1] for p in prices_all[day]["VEV_5300"]}
        p_5500 = {p[0]: p[1] for p in prices_all[day]["VEV_5500"]}
        p_vfe = {p[0]: p[1] for p in prices_all[day]["VELVETFRUIT_EXTRACT"]}
        ts_common = sorted(set(p_5300) & set(p_5500) & set(p_vfe))
        if len(ts_common) < 100:
            continue
        skew = [p_5500[t] - p_5300[t] for t in ts_common]
        vfe = [p_vfe[t] for t in ts_common]
        d_sk = [skew[i] - skew[i - 1] for i in range(1, len(skew))]
        d_vfe = [vfe[i] - vfe[i - 1] for i in range(1, len(vfe))]
        # lag 0 (concurrent) and lag +1 (skew leads vfe by 1)
        c0 = corr(d_sk, d_vfe)
        c1 = corr(d_sk[:-1], d_vfe[1:])
        c2 = corr(d_sk[:-2], d_vfe[2:])
        cm1 = corr(d_sk[1:], d_vfe[:-1])  # vfe leads skew
        print(f"day {day}  Δskew vs ΔVFE corr: lag0={c0:+.4f}  +1={c1:+.4f}  +2={c2:+.4f}  -1={cm1:+.4f}")
    print("\nInterp: lag>=1 corr => Δskew leads ΔVFE; lag-1 corr => the reverse.")


def section_g_block_returns(prices_all):
    """G. Block-return autocorrelation at K = {5, 20, 100, 500}."""
    print("\n" + "=" * 70)
    print("G. BLOCK-RETURN AUTOCORRELATION (Δmid over K-tick blocks)")
    print("=" * 70)
    print(f"{'product':>22}  {'AR1@K=5':>9} {'K=20':>9} {'K=100':>9} {'K=500':>9}")
    for prod in PRODUCTS:
        rows = []
        for K in (5, 20, 100, 500):
            all_blocks = []
            for day in (0, 1, 2):
                mids = [p[1] for p in prices_all[day][prod]]
                blocks = [mids[i + K] - mids[i] for i in range(0, len(mids) - K, K)]
                all_blocks.extend(blocks)
            if len(all_blocks) > 5:
                a, _ = ar_k(all_blocks, 1)
                rows.append(f"{a:>+9.4f}")
            else:
                rows.append("    n/a")
        print(f"{prod:>22}  {' '.join(rows)}")
    print("\nInterp: AR(1) on K-tick blocks > +0.05 => trend at horizon K (carry);")
    print("< -0.05 => mean-reversion at horizon K (MR signal).")


def section_h_time_weighted_carry(prices_all):
    """H. VFE drift by quarter-of-day."""
    print("\n" + "=" * 70)
    print("H. VFE DRIFT BY QUARTER OF DAY (time-weighted carry)")
    print("=" * 70)
    print(f"{'day':>3}  Q1 Δmid    Q2 Δmid    Q3 Δmid    Q4 Δmid    Q1-Q4 acceleration")
    for day in (0, 1, 2):
        prices = prices_all[day]["VELVETFRUIT_EXTRACT"]
        mids = [p[1] for p in prices]
        n = len(mids)
        if n < 4:
            continue
        q = [n // 4 * i for i in range(5)]
        deltas = [mids[q[i + 1] - 1] - mids[q[i]] for i in range(4)]
        accel = deltas[3] - deltas[0]
        print(f"{day:>3}  {deltas[0]:>+8.1f}  {deltas[1]:>+8.1f}  {deltas[2]:>+8.1f}  {deltas[3]:>+8.1f}  Q4-Q1: {accel:+.1f}")
    print("\nInterp: if Q4 drift consistently larger than Q1 => time-weighted carry")
    print("(more aggressive long bias in last quarter).")


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
    print("LOADING data days 0/1/2 ...")
    prices_all = {d: load_prices(d) for d in (0, 1, 2)}
    trades_all = {d: load_trades(d) for d in (0, 1, 2)}
    print("LOADED.")
    section_a_vol_clustering(prices_all)
    section_b_trade_flow(prices_all, trades_all)
    section_c_time_of_day(prices_all)
    section_d_eod_reversal(prices_all)
    section_e_basket_smile(prices_all)
    section_f_skew_spot(prices_all)
    section_g_block_returns(prices_all)
    section_h_time_weighted_carry(prices_all)


if __name__ == "__main__":
    main()
