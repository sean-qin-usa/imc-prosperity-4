"""Deep research session 8 part C — cross-product flow & smile signals.

Hypotheses:
  1. VEV trade flow leads VFE Δmid? (Cross-product leading indicator)
  2. Aggregated VEV signed-volume → VFE mid-move
  3. Skew-shift residual after delta-removal: any predictability?
  4. Vol clustering on VFE: does it help predict NEXT 5-tick block?
"""
import csv
import math
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
    out = {p: {} for p in PRODUCTS}
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
                mid = float(r["mid_price"])
            except Exception:
                continue
            out[p][ts] = (mid, bb, ba)
    return out


def load_trades(day: int):
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


def section_voucher_flow_leads_vfe(prices_all, trades_all):
    """Aggregate signed VEV flow per tick; check if it predicts next-tick VFE Δmid."""
    print("\n" + "=" * 70)
    print("Cross-product: aggregated VEV flow → next-tick VFE Δmid")
    print("=" * 70)
    voucher_strikes = ["VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
                       "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
                       "VEV_6000", "VEV_6500"]
    for day in (0, 1, 2):
        vfe_prices = prices_all[day]["VELVETFRUIT_EXTRACT"]
        ts_sorted = sorted(vfe_prices.keys())
        # Aggregate VEV signed flow per timestamp bucket
        flow_by_ts = defaultdict(float)
        for v in voucher_strikes:
            v_prices = prices_all[day][v]
            for t_ts, t_p, t_q in trades_all[day][v]:
                bucket_ts = (t_ts // 100) * 100
                if bucket_ts not in v_prices:
                    continue
                _, bb, ba = v_prices[bucket_ts]
                if math.isnan(bb) or math.isnan(ba):
                    continue
                mid = (bb + ba) / 2
                if t_p >= mid:
                    flow_by_ts[bucket_ts] += t_q
                else:
                    flow_by_ts[bucket_ts] -= t_q
        # Build flow & VFE Δmid time series
        vfe_mids = [vfe_prices[t][0] for t in ts_sorted]
        flow = [flow_by_ts.get(t, 0.0) for t in ts_sorted[:-1]]
        dvfe = [vfe_mids[i] - vfe_mids[i - 1] for i in range(1, len(vfe_mids))]
        # Lag 0 (concurrent) and lag 1 (flow leads)
        c0 = corr(flow, dvfe)
        c1 = corr(flow[:-1], dvfe[1:])
        c2 = corr(flow[:-2], dvfe[2:])
        c3 = corr(flow[:-3], dvfe[3:])
        # Also flow-net predict 5-tick forward
        n = min(len(flow), len(dvfe))
        d5 = [vfe_mids[i + 5] - vfe_mids[i] for i in range(len(vfe_mids) - 5)]
        c5 = corr(flow[:len(d5)], d5)
        nz = sum(1 for f in flow if f != 0)
        print(f"day {day}  VEV_flow → VFE: lag0={c0:+.4f}  +1={c1:+.4f}  +2={c2:+.4f}  +3={c3:+.4f}  →ΔVFE_5tick={c5:+.4f}  nz={nz}")


def section_vfe_flow_leads_voucher(prices_all, trades_all):
    """Check if VFE flow leads each voucher's Δmid (lag 1)."""
    print("\n" + "=" * 70)
    print("Cross-product: VFE flow → next-tick voucher Δmid (per strike)")
    print("=" * 70)
    for day in (0, 1, 2):
        vfe_prices = prices_all[day]["VELVETFRUIT_EXTRACT"]
        ts_sorted = sorted(vfe_prices.keys())
        # VFE signed flow per timestamp
        flow_by_ts = defaultdict(float)
        for t_ts, t_p, t_q in trades_all[day]["VELVETFRUIT_EXTRACT"]:
            bucket_ts = (t_ts // 100) * 100
            if bucket_ts not in vfe_prices:
                continue
            _, bb, ba = vfe_prices[bucket_ts]
            if math.isnan(bb) or math.isnan(ba):
                continue
            mid = (bb + ba) / 2
            if t_p >= mid:
                flow_by_ts[bucket_ts] += t_q
            else:
                flow_by_ts[bucket_ts] -= t_q
        flow = [flow_by_ts.get(t, 0.0) for t in ts_sorted[:-1]]
        for v in PRODUCTS:
            if v == "VELVETFRUIT_EXTRACT":
                continue
            v_prices = prices_all[day][v]
            v_mids = [v_prices.get(t, (float("nan"),))[0] for t in ts_sorted]
            if all(math.isnan(m) for m in v_mids):
                continue
            dvm = []
            for i in range(1, len(v_mids)):
                if math.isnan(v_mids[i]) or math.isnan(v_mids[i - 1]):
                    dvm.append(0.0)
                else:
                    dvm.append(v_mids[i] - v_mids[i - 1])
            c1 = corr(flow[:-1], dvm[1:])
            print(f"day {day}  VFE_flow → {v}: lag1 corr={c1:+.4f}")


def section_vfe_vol_cluster_block(prices_all):
    """VFE vol clustering: predict next 5-tick |Δmid| from prev 5-tick |Δmid|."""
    print("\n" + "=" * 70)
    print("VFE vol clustering at K=5 blocks: predict |block(t)| from |block(t-1)|")
    print("=" * 70)
    for day in (0, 1, 2):
        prices = prices_all[day]["VELVETFRUIT_EXTRACT"]
        ts_sorted = sorted(prices.keys())
        mids = [prices[t][0] for t in ts_sorted]
        K = 5
        blocks = [mids[i + K] - mids[i] for i in range(0, len(mids) - K, K)]
        abs_blk = [abs(b) for b in blocks]
        # AR1 on abs_blk
        n = len(abs_blk)
        m = sum(abs_blk) / n
        num = sum((abs_blk[i] - m) * (abs_blk[i - 1] - m) for i in range(1, n))
        den = sum((x - m) ** 2 for x in abs_blk)
        ar1 = num / den if den > 0 else 0.0
        # OLS
        x = abs_blk[:-1]; y = abs_blk[1:]
        nn = len(x)
        mx = sum(x) / nn; my = sum(y) / nn
        sxx = sum((xi - mx) ** 2 for xi in x)
        syy = sum((yi - my) ** 2 for yi in y)
        sxy = sum((x[i] - mx) * (y[i] - my) for i in range(nn))
        b1 = sxy / sxx if sxx > 0 else 0.0
        b0 = my - b1 * mx
        yhat = [b0 + b1 * xi for xi in x]
        ss_res = sum((y[i] - yhat[i]) ** 2 for i in range(nn))
        r2 = 1 - ss_res / syy if syy > 0 else 0.0
        print(f"day {day}  K=5 blocks: AR1={ar1:+.4f}  b0={b0:+.3f} b1={b1:+.3f} R²={r2:.4f}  n={nn}")


def section_skew_residual(prices_all):
    """Skew minus its delta-implied prediction. Does residual mean-revert?"""
    print("\n" + "=" * 70)
    print("Skew residual after delta-fit: stationarity check")
    print("=" * 70)
    for day in (0, 1, 2):
        p_5300 = prices_all[day]["VEV_5300"]
        p_5500 = prices_all[day]["VEV_5500"]
        p_vfe = prices_all[day]["VELVETFRUIT_EXTRACT"]
        ts_common = sorted(set(p_5300) & set(p_5500) & set(p_vfe))
        if len(ts_common) < 100:
            continue
        skew = [p_5500[t][0] - p_5300[t][0] for t in ts_common]
        vfe = [p_vfe[t][0] for t in ts_common]
        # OLS skew = a + b * vfe
        n = len(skew)
        mvfe = sum(vfe) / n; mskew = sum(skew) / n
        sxx = sum((vfe[i] - mvfe) ** 2 for i in range(n))
        sxy = sum((vfe[i] - mvfe) * (skew[i] - mskew) for i in range(n))
        b = sxy / sxx if sxx > 0 else 0.0
        a = mskew - b * mvfe
        residual = [skew[i] - (a + b * vfe[i]) for i in range(n)]
        # AR(1) on residual
        m = sum(residual) / n
        num = sum((residual[i] - m) * (residual[i - 1] - m) for i in range(1, n))
        den = sum((x - m) ** 2 for x in residual)
        ar1 = num / den if den > 0 else 0.0
        # Residual std (in-sample R²)
        sse = sum(r * r for r in residual)
        ss_tot = sum((s - mskew) ** 2 for s in skew)
        r2 = 1 - sse / ss_tot if ss_tot > 0 else 0.0
        # Predict Δresidual → ΔVFE
        dres = [residual[i] - residual[i - 1] for i in range(1, n)]
        dvfe = [vfe[i] - vfe[i - 1] for i in range(1, n)]
        c1 = corr(dres[:-1], dvfe[1:])
        c0 = corr(dres, dvfe)
        print(f"day {day}  skew=a+b*VFE: a={a:+.2f} b={b:+.4f}  resid R²={r2:.4f}  AR1(resid)={ar1:+.4f}  Δresid→ΔVFE: lag0={c0:+.4f} lag1={c1:+.4f}")


def main():
    print("LOADING data days 0/1/2 ...")
    prices_all = {d: load_prices(d) for d in (0, 1, 2)}
    trades_all = {d: load_trades(d) for d in (0, 1, 2)}
    print("LOADED.")
    section_voucher_flow_leads_vfe(prices_all, trades_all)
    section_vfe_flow_leads_voucher(prices_all, trades_all)
    section_vfe_vol_cluster_block(prices_all)
    section_skew_residual(prices_all)


if __name__ == "__main__":
    main()
