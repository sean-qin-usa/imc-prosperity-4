# Round 3 Voucher Empirical Note

Data source: `IMCP2026/data/round3/prices_round_3_day_{0,1,2}.csv`

Reference plots:
- [average_extra_premium_by_strike.png](/Users/sean_tsu_/Downloads/prosperity/IMCP2026/analysis/round3_voucher_empirical/average_extra_premium_by_strike.png)
- [extra_premium_decay_by_day.png](/Users/sean_tsu_/Downloads/prosperity/IMCP2026/analysis/round3_voucher_empirical/extra_premium_decay_by_day.png)
- broader market visualizer: [report_interactive.html](/Users/sean_tsu_/Downloads/prosperity/IMCP2026/analysis/visualizer_report_round3/report_interactive.html)

## Bottom line

- `Black-Scholes` is useful here as a **level model**, not as a direct trading rule.
- The chain is **not** “intrinsic only” and it is **not** “expiry free”:
  average extra premium decays materially from day 0 to day 2.
- A flat-sigma BS fit on the liquid strikes `5000..5500` is very stable:
  `sigma ≈ 0.232 / 0.233 / 0.232` for days `0 / 1 / 2`.
- But raw “best ask below fair, buy it” / “best bid above fair, sell it”
  is still negative after spreads on this dataset.

## Empirical time value map

Average extra premium over intrinsic `max(S-K, 0)` using quoted mid:

| Strike | Avg extra premium |
|---|---:|
| 4000 | 0.012 |
| 4500 | 0.011 |
| 5000 | 4.924 |
| 5100 | 16.707 |
| 5200 | 45.450 |
| 5300 | 46.760 |
| 5400 | 15.952 |
| 5500 | 6.641 |
| 6000 | 0.500 |
| 6500 | 0.500 |

Interpretation:

- `VEV_4000` and `VEV_4500` are basically synthetic spot: time value is ~0.
- `VEV_5200` and `VEV_5300` carry the biggest time value.
- `VEV_6000` and `VEV_6500` are pinned at `0.5` mid and behave like lottery tickets.

## Expiry is visible in the data

Average extra premium declines across days:

- `5000`: `6.749 -> 4.871 -> 3.153`
- `5100`: `21.597 -> 16.591 -> 11.933`
- `5200`: `50.961 -> 46.736 -> 38.655`
- `5300`: `48.892 -> 46.909 -> 44.478`
- `5400`: `18.467 -> 15.654 -> 13.734`
- `5500`: `8.059 -> 6.571 -> 5.294`

That is empirical time decay. So the simulator is artificial, but the
price process still contains a real expiry-like premium term.

## What BS gets right

Flat-sigma fit on `5000..5500`:

- day 0: `sigma = 0.2320`
- day 1: `sigma = 0.2330`
- day 2: `sigma = 0.2320`

This means BS is a decent coordinate transform for:

- mapping strike to rough fair level
- separating intrinsic from time value
- comparing residual richness across strikes

## What BS gets wrong as a trading rule

Residuals vs the flat-sigma BS fair are highly persistent:

- `5000`: lag-1 autocorr `0.360 / 0.633 / 0.276`
- `5100`: `0.712 / 0.912 / 0.824`
- `5200`: `0.859 / 0.951 / 0.963`
- `5300`: `0.926 / 0.886 / 0.975`
- `5400`: `0.992 / 0.984 / 0.968`
- `5500`: `0.840 / 0.977 / 0.978`

So the residual is not clean instant mean reversion. It is mostly a
slow-moving surface bias. That is why EMA-style residual trading can
work better than naive BS-gap taking.

## Order book / taker implication

Using empirical fair = `intrinsic + mean_extra(day, strike)` and
marking to quoted mid 20 ticks later:

- aggressive buys are negative on average for every tested threshold
- aggressive sells are also negative on average for every tested threshold

Overall 20-tick hold results:

- buy when `fair - ask >= 2`: avg PnL `-1.257`
- buy when `fair - ask >= 4`: avg PnL `-1.213`
- sell when `bid - fair >= 2`: avg PnL `-1.192`
- sell when `bid - fair >= 4`: avg PnL `-1.204`

Even “stale-like” quotes, approximated by the same best quote surviving
3 ticks while edge is at least 4, are still negative:

- stale-like buys: avg PnL `-0.924`
- stale-like sells: avg PnL `-1.099`

## Practical conclusion

- Use BS here as a **baseline fair surface**, not as proof that a taker
  trade is good.
- Treat `4000/4500` as synthetic spot first, options second.
- Treat `5000..5500` as a **surface + residual** problem.
- If you want to take, require more than “quote is cheap vs fair”:
  you need a residual regime / EMA / mean-reversion signal on top.
