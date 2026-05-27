"""Deep research session 8 part B — OOS-validate the top signals from part A.

Top hypotheses to validate:
  1. K=500 block MR is universal (AR(1) ≈ -0.35) — does it hold per-day?
  2. VEV_5500 K=5 MR (AR1 = -0.22) — does it hold per-day?
  3. VEV_4000/4500/5500 vol clustering — does it hold per-day?

Then test simple toy strategies for #1 and #2:
  - Rolling-mean MR overlay on each product (track 500-tick mean,
    sell when mid > mean+T, buy when mid < mean-T)
  - Quote-width vol-clustering: predict next |Δm| from prev |Δm|
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
]


def load_prices(day: int):
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


def ar_k(xs, k):
    n = len(xs)
    if n <= k:
        return 0.0, n
    m = sum(xs) / n
    num = sum((xs[i] - m) * (xs[i - k] - m) for i in range(k, n))
    den = sum((x - m) ** 2 for x in xs)
    return (num / den if den > 0 else 0.0), n - k


def per_day_block_ar(prices_all, K):
    print(f"\nBlock K={K}: AR(1) per-day per-product")
    print(f"{'product':>22}  {'day0':>8} {'day1':>8} {'day2':>8} {'pooled':>8}  {'#blocks':>9}")
    for prod in PRODUCTS:
        per_day = []
        all_blocks = []
        for day in (0, 1, 2):
            mids = [p[1] for p in prices_all[day][prod]]
            blocks = [mids[i + K] - mids[i] for i in range(0, len(mids) - K, K)]
            if len(blocks) < 5:
                per_day.append("    n/a")
                continue
            a, _ = ar_k(blocks, 1)
            per_day.append(f"{a:>+8.4f}")
            all_blocks.extend(blocks)
        if all_blocks:
            ap, n = ar_k(all_blocks, 1)
            print(f"{prod:>22}  {' '.join(per_day)} {ap:>+8.4f}  {n:>9}")


def per_day_vol_cluster(prices_all):
    print(f"\nVol clustering: AR(1) on |Δm| per-day per-product")
    print(f"{'product':>22}  {'day0':>8} {'day1':>8} {'day2':>8} {'pooled':>8}")
    for prod in PRODUCTS:
        per_day = []
        all_abs = []
        for day in (0, 1, 2):
            mids = [p[1] for p in prices_all[day][prod]]
            dm = [abs(mids[i] - mids[i - 1]) for i in range(1, len(mids))]
            if len(dm) < 100:
                per_day.append("    n/a")
                continue
            a, _ = ar_k(dm, 1)
            per_day.append(f"{a:>+8.4f}")
            all_abs.extend(dm)
        if all_abs:
            ap, _ = ar_k(all_abs, 1)
            print(f"{prod:>22}  {' '.join(per_day)} {ap:>+8.4f}")


def section_toy_block_mr(prices_all, K=500, threshold_std=1.0):
    """Toy strategy: at each tick, observe last K-tick block return; lean fair
    by -beta * block_return. Compute Sharpe over a simple PnL.
    Concretely: if last K-tick block return > 0, predict next K-tick to be
    negative. Take position prop to -beta * block_return, hold for K ticks.
    """
    print(f"\nToy block-MR strategy at K={K}: predict next-K return = -alpha * prev-K return")
    print(f"{'product':>22}  {'day':>3}  {'beta':>6}  {'cum PnL @ unit_pos':>18}  {'sharpe':>7}")
    for prod in PRODUCTS:
        per_day_pnl = []
        for day in (0, 1, 2):
            mids = [p[1] for p in prices_all[day][prod]]
            n = len(mids)
            if n < 3 * K:
                continue
            # Compute non-overlapping blocks, fit beta on day data, compute
            # cumulative PnL of trading -beta*prev_block.
            blocks = [mids[i + K] - mids[i] for i in range(0, n - K, K)]
            if len(blocks) < 4:
                continue
            # Beta from regression of next vs prev (no intercept for simplicity)
            num = 0.0; den = 0.0
            for i in range(1, len(blocks)):
                num += blocks[i] * blocks[i - 1]
                den += blocks[i - 1] ** 2
            beta = num / den if den > 0 else 0.0
            # PnL: at each block, position = -beta * prev_block; PnL = pos * curr_block
            pnls = [(-beta * blocks[i - 1]) * blocks[i] for i in range(1, len(blocks))]
            cum = sum(pnls)
            mean_p = cum / len(pnls)
            std_p = statistics.pstdev(pnls) if len(pnls) > 1 else 0.0
            sharpe = mean_p / std_p if std_p > 0 else 0.0
            per_day_pnl.append((day, beta, cum, sharpe))
        for day, beta, cum, sharpe in per_day_pnl:
            print(f"{prod:>22}  {day:>3}  {beta:>+6.3f}  {cum:>+18.2f}  {sharpe:>+7.3f}")


def section_toy_short_mr_5500(prices_all):
    """Toy 5-tick MR strategy on VEV_5500."""
    print(f"\nToy short-horizon MR on VEV_5500 (block K=5):")
    for day in (0, 1, 2):
        mids = [p[1] for p in prices_all[day]["VEV_5500"]]
        n = len(mids)
        if n < 100:
            continue
        # 5-tick block returns, non-overlapping
        K = 5
        blocks = [mids[i + K] - mids[i] for i in range(0, n - K, K)]
        # Fit AR(1) beta
        num = 0.0; den = 0.0
        for i in range(1, len(blocks)):
            num += blocks[i] * blocks[i - 1]
            den += blocks[i - 1] ** 2
        beta = num / den if den > 0 else 0.0
        pnls = [(-beta * blocks[i - 1]) * blocks[i] for i in range(1, len(blocks))]
        cum = sum(pnls)
        mean_p = cum / len(pnls)
        std_p = statistics.pstdev(pnls) if len(pnls) > 1 else 0.0
        sharpe = mean_p / std_p if std_p > 0 else 0.0
        print(f"  day {day}: beta={beta:+.3f}  cum_PnL_per_unit_pos={cum:+.2f}  sharpe={sharpe:+.3f}  #blocks={len(blocks)}")
    print("\nInterp: cum_PnL > 0 with consistent beta sign across days = real MR alpha.")


def section_oos_block_mr(prices_all, K=500):
    """OOS test: fit beta on 2 days, test on 3rd, rotate."""
    print(f"\nOOS block-MR validation at K={K}: train 2 days, test 3rd, rotate")
    print(f"{'product':>22}  {'train_d':>9} {'test_d':>7} {'beta_train':>10} {'PnL_test':>10} {'sharpe':>7}")
    for prod in PRODUCTS:
        all_blocks_per_day = {}
        for day in (0, 1, 2):
            mids = [p[1] for p in prices_all[day][prod]]
            blocks = [mids[i + K] - mids[i] for i in range(0, len(mids) - K, K)]
            all_blocks_per_day[day] = blocks
        for test_day in (0, 1, 2):
            train_days = [d for d in (0, 1, 2) if d != test_day]
            train_blocks = []
            for d in train_days:
                train_blocks.extend(all_blocks_per_day[d])
            # Fit on train (treating as one stream)
            num = 0.0; den = 0.0
            for i in range(1, len(train_blocks)):
                num += train_blocks[i] * train_blocks[i - 1]
                den += train_blocks[i - 1] ** 2
            beta = num / den if den > 0 else 0.0
            test_blocks = all_blocks_per_day[test_day]
            if len(test_blocks) < 4:
                continue
            pnls = [(-beta * test_blocks[i - 1]) * test_blocks[i] for i in range(1, len(test_blocks))]
            cum = sum(pnls)
            mean_p = cum / len(pnls) if pnls else 0.0
            std_p = statistics.pstdev(pnls) if len(pnls) > 1 else 0.0
            sharpe = mean_p / std_p if std_p > 0 else 0.0
            print(f"{prod:>22}  {','.join(map(str, train_days)):>9} {test_day:>7} {beta:>+10.4f} {cum:>+10.2f} {sharpe:>+7.3f}")


def section_vol_cluster_quote_width(prices_all):
    """Test: when |Δm| at t-1 is large, |Δm| at t is also large.
    If true, we can widen quotes (or post smaller) right after a big move.
    Quantify: predict |Δm(t)| using OLS on |Δm(t-1)|; report R²."""
    print(f"\nVol-clustering predictability: predict |Δm(t)| from |Δm(t-1)|")
    print(f"{'product':>22}  {'day':>3}  R² {'b0':>8} {'b1':>6}")
    for prod in PRODUCTS:
        for day in (0, 1, 2):
            mids = [p[1] for p in prices_all[day][prod]]
            adm = [abs(mids[i] - mids[i - 1]) for i in range(1, len(mids))]
            if len(adm) < 100 or sum(adm) == 0:
                continue
            x = adm[:-1]
            y = adm[1:]
            n = len(x)
            mx = sum(x) / n; my = sum(y) / n
            sxx = sum((xi - mx) ** 2 for xi in x)
            sxy = sum((x[i] - mx) * (y[i] - my) for i in range(n))
            syy = sum((yi - my) ** 2 for yi in y)
            if sxx <= 0 or syy <= 0:
                continue
            b1 = sxy / sxx
            b0 = my - b1 * mx
            yhat = [b0 + b1 * xi for xi in x]
            ss_res = sum((y[i] - yhat[i]) ** 2 for i in range(n))
            ss_tot = syy
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
            print(f"{prod:>22}  {day:>3}  {r2:>+5.3f}  {b0:>+8.3f} {b1:>+6.3f}")


def main():
    print("LOADING data days 0/1/2 ...")
    prices_all = {d: load_prices(d) for d in (0, 1, 2)}
    print("LOADED.")

    print("\n" + "=" * 70)
    print("OOS VALIDATION — per-day block AR(1)")
    print("=" * 70)
    for K in (5, 20, 100, 500):
        per_day_block_ar(prices_all, K)

    print("\n" + "=" * 70)
    print("OOS VOL CLUSTERING — per-day AR(1) on |Δm|")
    print("=" * 70)
    per_day_vol_cluster(prices_all)

    print("\n" + "=" * 70)
    print("TOY MR STRATEGIES (in-sample beta)")
    print("=" * 70)
    section_toy_block_mr(prices_all, K=500)
    section_toy_block_mr(prices_all, K=100)
    section_toy_short_mr_5500(prices_all)

    print("\n" + "=" * 70)
    print("OOS MR strategy — train 2 days, test 3rd")
    print("=" * 70)
    section_oos_block_mr(prices_all, K=500)
    section_oos_block_mr(prices_all, K=100)
    section_oos_block_mr(prices_all, K=20)

    print("\n" + "=" * 70)
    print("VOL CLUSTERING quote-width predictability")
    print("=" * 70)
    section_vol_cluster_quote_width(prices_all)


if __name__ == "__main__":
    main()
