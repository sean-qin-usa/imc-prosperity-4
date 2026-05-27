"""
Pair-trade independence test for HYDROGEL_PACK vs every other Round-3 product.

For each cross product X:
  1. OLS  mid_H = a + b*mid_X  (per day, then full-pool)
  2. Build residual e_t = mid_H - (a + b*mid_X)
  3. Dickey-Fuller test: regress  Δe_t = ρ * e_{t-1} + const + ε
        ADF t-stat = ρ̂ / SE(ρ̂).  Reject unit root (=> stationary residual)
        if t < -2.86 (5%) or < -3.43 (1%).
  4. Half-life of mean reversion via AR1 of residual:
        e_t = α + φ * e_{t-1};  HL = -ln(2)/ln(φ)  if 0<φ<1.
  5. Paper pair-trade backtest:
        rolling z = (e_t - μ_W)/σ_W   (W = 2000 ticks)
        enter long-spread (long H, short β shares X)  at z <= -ENTRY
        enter short-spread                            at z >= +ENTRY
        exit when |z| <= EXIT
        PnL = Δ(spread) cumulated over holding window, in price units.
        ENTRY=2.0, EXIT=0.5, no costs, no slippage  (upper-bound).

Run all 3 days separately + pooled. Print sortable summary table.
"""

import csv
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

DATA = "/Users/sean_tsu_/Downloads/prosperity/IMCP2026/data/round3"
DAYS = [0, 1, 2]
H = "HYDROGEL_PACK"


def load_day(day):
    path = f"{DATA}/prices_round_3_day_{day}.csv"
    df = pd.read_csv(path, sep=";")
    # pivot on (timestamp, product) -> mid_price
    piv = df.pivot_table(index="timestamp", columns="product",
                         values="mid_price", aggfunc="last")
    return piv.dropna(how="all")


def ols_ab(y, x):
    """y = a + b*x.  return (a, b)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    sx = x.sum(); sy = y.sum()
    sxx = (x * x).sum(); sxy = (x * y).sum()
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, 0.0
    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n
    return a, b


def adf_t(e):
    """Augmented DF (lag 0) with constant.
    Δe_t = α + ρ * e_{t-1} + ε.
    Return ρ̂, t-stat(ρ̂), φ̂ (=1+ρ), HL.
    """
    e = np.asarray(e, dtype=float)
    de = np.diff(e)
    el = e[:-1]
    n = len(de)
    # OLS Δe ~ const + el
    X = np.column_stack([np.ones(n), el])
    XtX = X.T @ X
    XtY = X.T @ de
    try:
        beta = np.linalg.solve(XtX, XtY)
    except np.linalg.LinAlgError:
        return np.nan, np.nan, np.nan, np.nan
    resid = de - X @ beta
    sigma2 = (resid @ resid) / (n - 2)
    cov = sigma2 * np.linalg.inv(XtX)
    rho = beta[1]
    se_rho = np.sqrt(cov[1, 1])
    t = rho / se_rho if se_rho > 0 else np.nan
    phi = 1.0 + rho
    if 0 < phi < 1:
        hl = -np.log(2.0) / np.log(phi)
    else:
        hl = np.nan
    return rho, t, phi, hl


def pair_backtest(mid_h, mid_x, beta, window=2000, entry=2.0, exit_=0.5):
    """Paper backtest a z-score pair trade.
    spread_t = mid_h_t - beta * mid_x_t
    z_t = (spread_t - rolling_mean_W) / rolling_std_W

    Position pos in {-1, 0, +1}:
      pos=+1  => long  H, short β·X  (we expect spread to rise)
      pos=-1  => short H, long  β·X
    Enter when |z| crosses entry (counter-trend);  exit at |z| <= exit.
    PnL accrues per tick: pos * Δspread.
    Returns (pnl_total, n_trades, hit_rate, max_drawdown).
    """
    mh = np.asarray(mid_h, dtype=float)
    mx = np.asarray(mid_x, dtype=float)
    sp = mh - beta * mx
    n = len(sp)
    # rolling mean / std
    s = pd.Series(sp)
    mu = s.rolling(window, min_periods=window).mean().values
    sd = s.rolling(window, min_periods=window).std(ddof=0).values
    z = np.where(sd > 0, (sp - mu) / sd, np.nan)

    pos = 0
    entry_price = 0.0
    pnl = 0.0
    eq = []
    trades = []   # (pnl_per_trade,)
    for t in range(n):
        if np.isnan(z[t]):
            eq.append(pnl); continue
        # mark to market
        if pos != 0 and t > 0:
            pnl += pos * (sp[t] - sp[t - 1])
        # entry
        if pos == 0:
            if z[t] <= -entry:
                pos = +1; entry_price = sp[t]
            elif z[t] >= +entry:
                pos = -1; entry_price = sp[t]
        else:
            # exit
            if abs(z[t]) <= exit_:
                trades.append(pos * (sp[t] - entry_price))
                pos = 0
        eq.append(pnl)
    # close any open position at end
    if pos != 0:
        trades.append(pos * (sp[-1] - entry_price))
        pnl += pos * (sp[-1] - sp[-2])
    eq = np.asarray(eq)
    if len(trades):
        wins = sum(1 for x in trades if x > 0)
        hit = wins / len(trades)
    else:
        hit = np.nan
    dd = 0.0
    if len(eq):
        peak = np.maximum.accumulate(eq)
        dd = float((eq - peak).min())
    return float(pnl), len(trades), hit, dd


def run():
    days_data = {d: load_day(d) for d in DAYS}
    products = sorted(set().union(*[set(p.columns) for p in days_data.values()]))
    if H not in products:
        print(f"FATAL: {H} missing"); sys.exit(1)
    cross = [p for p in products if p != H]

    rows = []
    # pool all 3 days for one regression + ADF
    pool = pd.concat([days_data[d] for d in DAYS], axis=0).reset_index(drop=True)
    pool = pool.dropna(subset=[H])

    print(f"\n=== POOLED (3 days, n={len(pool)}) ===")
    print(f"{'product':<24}{'beta':>10}{'r2':>8}{'ADFt':>8}{'phi':>8}{'HL':>10}{'pnl':>12}{'#trd':>7}{'hit':>7}")
    for x in cross:
        d = pool[[H, x]].dropna()
        if len(d) < 5000:
            continue
        a, b = ols_ab(d[H].values, d[x].values)
        e = d[H].values - (a + b * d[x].values)
        # R²
        sst = ((d[H].values - d[H].values.mean()) ** 2).sum()
        ssr = (e ** 2).sum()
        r2 = 1 - ssr / sst if sst > 0 else np.nan
        rho, t, phi, hl = adf_t(e)
        pnl, ntr, hit, dd = pair_backtest(d[H].values, d[x].values, b)
        rows.append((x, b, r2, t, phi, hl, pnl, ntr, hit, dd))
        print(f"{x:<24}{b:>10.4f}{r2:>8.3f}{t:>8.2f}{phi:>8.4f}"
              f"{(f'{hl:.0f}' if not np.isnan(hl) else '   nan'):>10}"
              f"{pnl:>12.1f}{ntr:>7d}{(f'{hit:.2f}' if not np.isnan(hit) else 'nan'):>7}")

    print("\nADF crit values: 5% = -2.86, 1% = -3.43.  t < -2.86 => stationary residual (pair-tradable).")
    print("HL = mean-reversion half-life in ticks (NaN means not mean-reverting).")
    print("PnL = paper z-score pair trade (entry=2, exit=0.5, W=2000), no costs, in price units across 3 days.")

    # also per day to check stability
    print("\n=== PER DAY (entry/exit identical) ===")
    print(f"{'product':<24}{'day':>4}{'beta':>10}{'ADFt':>8}{'HL':>10}{'pnl':>12}{'#trd':>7}")
    for x in cross:
        for d in DAYS:
            df = days_data[d][[H, x]].dropna()
            if len(df) < 2500:
                continue
            a, b = ols_ab(df[H].values, df[x].values)
            e = df[H].values - (a + b * df[x].values)
            rho, tstat, phi, hl = adf_t(e)
            pnl, ntr, hit, dd = pair_backtest(df[H].values, df[x].values, b)
            print(f"{x:<24}{d:>4}{b:>10.4f}{tstat:>8.2f}"
                  f"{(f'{hl:.0f}' if not np.isnan(hl) else '   nan'):>10}"
                  f"{pnl:>12.1f}{ntr:>7d}")


if __name__ == "__main__":
    run()
