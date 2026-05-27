# Round 1 — Tutorial-class MM + intraday path anchor

**Products:** `ASH_COATED_OSMIUM` (ACO) and `INTARIAN_PEPPER_ROOT` (IPR). Position limit 80 on each. The round reuses the same market roles as the tutorial but the microstructure differs enough that direct wrapper reuse leaves real money on the table.

**Final ship:** [`traders/round1/pepper_benchmark_push_core70_completion_early.py`](./code/traders/round1/pepper_benchmark_push_core70_completion_early.py), pointed at by [`current_strategy.py`](./code/traders/round1/current_strategy.py).

## Generative-process read

Two different stories, two different strategies:

| Product | Story | Implication |
|---|---|---|
| ACO | Stationary anchor ≈ 10 000 + mean-reverting noise (residual sd ≈ 4.86) | Static-fair MM with mean-reversion taking; inventory skew toward flat |
| IPR | Repeated intraday path shape with a roughly +1000 / day upward shift | Normalized intraday path anchor, not a Kalman fair |

The IPR fact is the load-bearing observation for the round. The uploaded round 1 report shows normalized-path correlations above 0.9999 between days, and day 0 vs day -1 + 1000 has RMSE ≈ 3.24. A pure wall-mid model from the tutorial misses this entirely; a Kalman fair tracks too slowly and the carry leaks.

## ACO leg — clipped anchor MM

Fair = `10_000 + clip(micro − 10_000, ±4)`. The clipped anchor handles two regimes correctly: at typical spread the anchor dominates and the strategy mean-reverts; under a walked book the micro-price tilt re-enters. Layered on top:

- **Take** at fair if the touch crosses by ≥ 0; passive at `±1` inside.
- **Inventory skew** of `−0.06 × position` on the effective fair (≈ 4.8 pts at full inventory — a credible inside-the-spread move).
- **Imbalance size skew**: at `|imb| > 0.30`, boost the favorable-side quote 1.8× and shrink the adverse-side 0.2×.

## IPR leg — normalized intraday path anchor

Each tick, the fair is read off the previous day's normalized path shifted by the cumulative day drift. The execution overlay:

- **Microstructure adjustment** is allowed to nudge fair but never pull it more than a few ticks off the path; earlier variants that let micro dominate over the anchor produced unstable backtests despite clean offline signal plots.
- **Take** when the offered ask falls below the path anchor by more than the residual sd.
- **Passive quote** stacked inside the touch (`best_bid + 1`, `best_bid + 2`) when spread > 4; secondary skipped if `imb < −0.30` (book about to drop) or if it would breach the limit.

## Drift carry — under-built in R1, paid for in R2

In retrospect, the IPR story already implied a +0.001 / ts drift, which under R2's mechanics is worth ≈ +80 k / day at limit. R1 didn't price this as cleanly: I unwound IPR too eagerly mid-day and treated the upward shape as forecast rather than carry. The R2 recipe ([round_2.md](./round_2.md)) corrects this — IPR stays at +80 long for ~99 % of the day with EOD unwind.

## Backtest results (same-tick local, days −2 / −1 / 0)

| Strategy | Total PnL | Note |
|---|---:|---|
| `current_strategy` (`core70_completion_early`) | **211,501** | Final ship |
| `path_anchor_strategy` | 210,262 | Path-anchor-only baseline |
| `kalman_benchmark` | 183,221 | Kalman fair on IPR — leaks carry |
| `tut` (tutorial wrapper port) | 160,190 | Naive reuse from tutorial |

Per-product decomposition vs the Kalman baseline (older `tut_try_trades_normalized` numbers): ACO total 47,834 (tied — same execution); IPR total 162,428 vs 135,387 (+27,041). The IPR lift is the whole story.

Under the **official-bundle fill calibration** (`tools/calibrations/combined_official_passive_profile.json`) on the hidden day `115164`, the same strategy scores 8,351.5. The local-to-live drop is the first version of a recurring story this competition: local backtesters over-fill passive quotes, and *the calibration matters more than the strategy*. Section 4 of [lessons_learned.md](./lessons_learned.md) is mostly about this.

## Manual challenge — "An Intarian Welcome"

A two-product opening auction with a guaranteed buyback (`DRYLAND_FLAX` at 30, `EMBER_MUSHROOM` at 20 with a 0.10/unit fee). Because submission is last and no other bids arrive, this is a pure best-response to a known sealed book.

I didn't deep-dive this one — the EV-maximizing bid is the lowest price that fills the desired quantity, and over-thinking the auction-clearing rule was a distraction the night before round 2 opened. I posted a thin-margin bid at the floor of the known support and moved on. If I ran R1 again I'd at least back out the marginal-fill probability per cent on each grid step and confirm the bid quantity sits on the right side of the price/volume tradeoff.

## What I'd change

1. **Price IPR as carry, not forecast.** The +1000/day drift is mechanically the dominant alpha; the path anchor is a small refinement on top. R2 reframed this correctly; R1 did not.
2. **Tighter ACO passive quoting in the typical regime.** The `core70_completion_early` variant lifted day 0 from 55,652 to 57,811 by tightening passive size inside the touch — there was probably another 5–10 k / day available if I'd done the full sensitivity earlier instead of layering "core66/67/68/69/70" variants reactively.
3. **Calibrate against the official bundle earlier.** The local same-tick numbers and the calibrated-bundle numbers diverged by an order of magnitude. I should have built the calibration harness during the tutorial week instead of mid-round.
