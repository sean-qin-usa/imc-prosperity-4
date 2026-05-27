"""Deep research session 8 part E — partial-corr test of skew-residual signal.

s8d found: residual(V5500-V5000) corr with ΔVFE_{t+1} ≈ -0.23 across all days.
But MEMORY warns: cross-product corrs spuriously inflate via own AR(1) bid/ask
bounce. So we must:
  1. Compute VFE Δm AR(1) explicitly.
  2. Control out ΔVFE_t when predicting ΔVFE_{t+1} from residual_t.
  3. Compare partial-corr to raw corr.

Spurious mechanism: residual = sig - (a + b*VFE). With b<0, residual is
positively correlated with VFE. If VFE has negative Δ-AR(1), then high VFE_t
=> low ΔVFE_{t+1}, AND high residual_t => low ΔVFE_{t+1} (inflated).

Also test:
  - Δresidual vs ΔVFE_{t+1} (instead of level)
  - Residual mean reversion: residual_t vs Δresidual_{t+1}
  - Toy PnL only if partial-corr survives
"""
import csv
import math
import statistics
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "round3"


def load_prices(day):
    out = {}
    with open(DATA / f"prices_round_3_day_{day}.csv") as f:
        rdr = csv.DictReader(f, delimiter=";")
        for r in rdr:
            p = r["product"]
            try:
                ts = int(r["timestamp"])
                mid = float(r["mid_price"])
            except Exception:
                continue
            out.setdefault(p, {})[ts] = mid
    return out


def fit_a_b(vfe, signal):
    n = len(vfe)
    if n < 2:
        return 0.0, 0.0
    mvfe = sum(vfe) / n; msig = sum(signal) / n
    sxx = sum((v - mvfe) ** 2 for v in vfe)
    sxy = sum((vfe[i] - mvfe) * (signal[i] - msig) for i in range(n))
    b = sxy / sxx if sxx > 0 else 0.0
    a = msig - b * mvfe
    return a, b


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


def partial_corr(x, y, z):
    """Partial correlation of x, y given z."""
    rxy = corr(x, y); rxz = corr(x, z); ryz = corr(y, z)
    den = math.sqrt(max(0.0, (1 - rxz**2) * (1 - ryz**2)))
    if den < 1e-9:
        return 0.0
    return (rxy - rxz * ryz) / den


def main():
    print("LOADING ...")
    prices_all = {d: load_prices(d) for d in (0, 1, 2)}
    print("LOADED.")

    print("\n" + "=" * 70)
    print("VFE own AR(1) on Δmid (controls)")
    print("=" * 70)
    for day in (0, 1, 2):
        p = prices_all[day]
        ts = sorted(p["VELVETFRUIT_EXTRACT"].keys())
        vfe = [p["VELVETFRUIT_EXTRACT"][t] for t in ts]
        dvfe = [vfe[i] - vfe[i - 1] for i in range(1, len(vfe))]
        n = len(dvfe)
        m = sum(dvfe) / n
        num = sum((dvfe[i] - m) * (dvfe[i - 1] - m) for i in range(1, n))
        den = sum((d - m) ** 2 for d in dvfe)
        ar1 = num / den if den > 0 else 0.0
        print(f"  day {day}: VFE Δm AR(1) = {ar1:+.4f}  std(Δm)={statistics.pstdev(dvfe):.3f}")

    print("\n" + "=" * 70)
    print("Partial-corr test: ΔVFE_{t+1} ~ residual_t + ΔVFE_t")
    print("Compare raw corr(residual_t, ΔVFE_{t+1}) to partial-corr controlling ΔVFE_t.")
    print("=" * 70)

    # Test multiple skew definitions; the strongest from s8d was V5500-V5000
    DEFS = [
        ("V5500-V5000", "VEV_5500", "VEV_5000"),
        ("V5500-V5100", "VEV_5500", "VEV_5100"),
        ("V5500-V5200", "VEV_5500", "VEV_5200"),
        ("V5500-V5300", "VEV_5500", "VEV_5300"),
        ("V5300-V5000", "VEV_5300", "VEV_5000"),
    ]

    for label, hi, lo in DEFS:
        print(f"\n--- {label} ---")
        for day in (0, 1, 2):
            p = prices_all[day]
            keys = ["VELVETFRUIT_EXTRACT", hi, lo]
            ts = sorted(set.intersection(*(set(p[k]) for k in keys)))
            vfe = [p["VELVETFRUIT_EXTRACT"][t] for t in ts]
            sig = [p[hi][t] - p[lo][t] for t in ts]
            a, b = fit_a_b(vfe, sig)
            residual = [sig[i] - (a + b * vfe[i]) for i in range(len(sig))]
            dvfe = [vfe[i] - vfe[i - 1] for i in range(1, len(vfe))]
            # We want: corr(residual_t, ΔVFE_{t+1}) — i.e. residual_t vs dvfe[t]
            # where dvfe is ΔVFE indexed at t (= vfe[t+1]-vfe[t]).
            # Align: residual_t for t in [0..n-2], ΔVFE_{t+1} = dvfe[t].
            res_aligned = residual[:-1]
            dvfe_lag1 = dvfe  # length n-1
            # ΔVFE_t = dvfe[t-1] = lagged version
            dvfe_lag0 = [0.0] + dvfe[:-1]  # ΔVFE at time t
            # match lengths
            n = min(len(res_aligned), len(dvfe_lag1), len(dvfe_lag0))
            res_aligned = res_aligned[:n]
            dvfe_lag1 = dvfe_lag1[:n]
            dvfe_lag0 = dvfe_lag0[:n]
            raw = corr(res_aligned, dvfe_lag1)
            partial = partial_corr(res_aligned, dvfe_lag1, dvfe_lag0)
            # Also: Δresidual vs ΔVFE_{t+1} controlling ΔVFE_t
            d_res = [residual[i] - residual[i - 1] for i in range(1, len(residual))]
            # dr_t corresponds to t in [1..n-1]. predict dvfe_lag1[t-1] = ΔVFE_t (concurrent).
            # We want lag-1 prediction: d_res_t -> dvfe_{t+1}
            # dvfe_lag1 already lag1 (vfe[t+1]-vfe[t]); aligned with t in [0..n-2]
            # So d_res[1:n-1] vs dvfe_lag1[1:n-1] is "Δres_t -> ΔVFE_{t+1}"
            mn = min(len(d_res) - 1, len(dvfe_lag1) - 1, len(dvfe_lag0) - 1)
            if mn < 5:
                continue
            d_res_a = d_res[1:1 + mn]
            dvfe_l1_a = dvfe_lag1[1:1 + mn]
            dvfe_l0_a = dvfe_lag0[1:1 + mn]
            d_raw = corr(d_res_a, dvfe_l1_a)
            d_partial = partial_corr(d_res_a, dvfe_l1_a, dvfe_l0_a)
            print(f"  day {day}: raw_corr(res_t, ΔVFE_{'{t+1}'})={raw:+.4f}  partial(|ΔVFE_t)={partial:+.4f}    Δres: raw={d_raw:+.4f}  partial={d_partial:+.4f}")

    print("\n" + "=" * 70)
    print("Toy paper-trade IF partial-corr survives (conservative scale)")
    print("=" * 70)
    # Use V5500-V5000 (strongest raw signal)
    for day in (0, 1, 2):
        p = prices_all[day]
        keys = ["VELVETFRUIT_EXTRACT", "VEV_5500", "VEV_5000"]
        ts = sorted(set.intersection(*(set(p[k]) for k in keys)))
        vfe = [p["VELVETFRUIT_EXTRACT"][t] for t in ts]
        sig = [p["VEV_5500"][t] - p["VEV_5000"][t] for t in ts]
        a, b = fit_a_b(vfe, sig)
        residual = [sig[i] - (a + b * vfe[i]) for i in range(len(sig))]
        # Also build a "control" predictor: just lagged ΔVFE (pure AR(1))
        dvfe = [vfe[i] - vfe[i - 1] for i in range(1, len(vfe))]
        # Position = -k * residual_t. PnL_t = pos * (vfe[t+1] - vfe[t])
        # k chosen such that max |position| = 100 (sub-LIMIT) — sweep k.
        # For comparison, also try AR(1)-only strategy: pos = -j * dvfe[t-1].
        max_res = max(abs(r) for r in residual)
        max_dvfe = max(abs(d) for d in dvfe) or 1.0
        k_res = 100.0 / max_res if max_res > 0 else 0.0
        k_dvfe = 100.0 / max_dvfe
        # PnL of skew-residual strategy
        pnls_skew = []
        for i in range(len(vfe) - 1):
            pos = -k_res * residual[i]
            pos = max(-200, min(200, pos))
            pnls_skew.append(pos * (vfe[i + 1] - vfe[i]))
        # PnL of AR(1)-only strategy (same scale)
        pnls_ar = []
        for i in range(1, len(vfe) - 1):
            pos = -k_dvfe * dvfe[i - 1]
            pos = max(-200, min(200, pos))
            pnls_ar.append(pos * (vfe[i + 1] - vfe[i]))
        print(f"  day {day}:")
        print(f"    skew-residual strategy: cum_PnL = {sum(pnls_skew):+.0f}  avg|pos|=peak limited")
        print(f"    AR(1) baseline strategy: cum_PnL = {sum(pnls_ar):+.0f}")
        print(f"    skew - AR(1) edge: {sum(pnls_skew) - sum(pnls_ar):+.0f}")


if __name__ == "__main__":
    main()
