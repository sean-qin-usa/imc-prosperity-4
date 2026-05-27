# Round 1 Strategy Notes

Running experiment ledger: see `RESEARCH_LOG.md` in this folder for the up-to-date "tried / evidence / potential" record.

Round 1 uses the same market roles as the tutorial round, but the microstructure is different enough that direct wrapper reuse leaves money on the table.

## File Layout

- `current_strategy.py`: stable entrypoint for the current official-benchmark-calibrated strategy. It currently points at `pepper_benchmark_push_core70_completion_early.py`.
- `unified_strategy.py`: unified entrypoint now promoted onto the same `pepper_benchmark_push_core70_completion_early.py` baseline as `current_strategy.py`.
- `pepper_benchmark_push_core70_completion_early.py`: current promoted production target; keeps the `core70` PEPPER carry line and adds a small early-session completion quote that survived both local fill models.
- `pepper_benchmark_push_core70.py`: plain `core70` control beneath the promoted wrapper; inherits the `best_locked` PEPPER passive-entry shape and raises the PEPPER core target to `70`.
- `pepper_benchmark_push_core67.py`: neighboring PEPPER core-target candidate in the same live family.
- `pepper_benchmark_push_core68.py`: stronger same-tick neighbor in the same live family.
- `pepper_benchmark_push_robust_band.py`: simplification candidate that replaces the fixed PEPPER core target with a small adaptive `66-68` band and lightly recenters the opening path anchor.
- `path_anchor_strategy.py`: historical official-benchmark-calibrated base and strongest earlier path-anchor reference, but no longer the active production target.
- `kalman_benchmark.py`: useful comparison base; it can look strong under generic local official-hybrid assumptions, but it was less robust once the passive-fill model was recalibrated from official bundles.
- `pepper_kalman_hybrid.py`: diagnostic hybrid with current ACO and Kalman IPR, used to isolate the pepper lift.
- `exchange_fill_probe.py`: low-risk probe strategy intended for official-site submission to learn fill behavior by size and inside-spread distance.
- `pepper_benchmark_push__best_locked.py`: protected snapshot of the best current PEPPER-first benchmark candidate. Keep this as the locked reference copy.
- `pepper_benchmark_push_plus2_passive.py`: preserved historical `+2` passive PEPPER branch; this is the old inline logic that used to live in `unified_strategy.py`.
- `pepper_benchmark_push_plus2_passive_v2.py`: `+2` passive PEPPER production candidate with a late-session PEPPER no-reload / forced-unwind path to avoid finishing with a large open long.
- `tutorial_wrapper_reference.py`: legacy tutorial-wrapper reference carried over from earlier work.
- `normalized_path_legacy.py`: historical snapshot of the path-anchor strategy kept for provenance and backtest-name continuity.

Symbol role mapping used in the wrappers:

- `ASH_COATED_OSMIUM` -> `EMERALDS`
- `INTARIAN_PEPPER_ROOT` -> `TOMATOES`

## What Held Up In Data

- `ASH_COATED_OSMIUM` is a stable fixed-fair product around `10000`.
- Filtered round-1 price data puts ACO at `mid_std ~= 4.86` with `spread_mean ~= 16.18`.
- The signal `10000 - mid` is predictive for ACO. On the uploaded analysis, 10-step correlation is about `0.3595`.
- `INTARIAN_PEPPER_ROOT` is not a static-fair product. Its intraday shape repeats almost perfectly each day with an upward day shift of about `+1000`.
- The uploaded Round 1 report shows normalized-path correlations above `0.9999` between days, and day `0` versus `day -1 + 1000` has RMSE about `3.24`.
- Top-of-book imbalance is useful for both products, but the naive path-anchor execution variant was unstable in backtest even though the offline signal plots looked strong.

## Historical Same-Tick Best Strategy

- Historical entrypoint at the time: `IMCP2026/traders/round1/current_strategy.py`
- Historical implementation: `IMCP2026/traders/round1/path_anchor_strategy.py`
- Backtest: `211,501` total PnL on `round1_csv`
- Run: `gen/backtests/20260414_122648__current_strategy__same-tick__all__round1_csv`

Historical note: the earlier path-anchor run was recorded as `tut_try_trades_normalized` because that was the filename at the time of that run.

Design:

- `ASH_COATED_OSMIUM`: keep the stronger fixed-fair reversion / market-making leg.
- `INTARIAN_PEPPER_ROOT`: replace the Kalman fair value with a normalized intraday path anchor, then layer in flow and cancellation signals for execution.

Why this won on the same-tick local backtester:

- ACO was already solved well by the stronger execution logic carried over from the earlier variants.
- IPR responded better to a path-normalized fair model than to a Kalman fair model.
- The path anchor captured the steady intraday drift, while the microstructure signals still handled local entry and quoting.

PnL decomposition versus the previous best hybrid:

- `tut_try_trades_normalized` ACO total: `47,834`
- `kalman_benchmark` ACO total: `47,834`
- `tut_try_trades_normalized` IPR total: `162,428`
- `kalman_benchmark` IPR total: `135,387`
- Net improvement over `kalman_benchmark`: `+27,041`

Latest tuning pass:

- tightened ACO passive quoting slightly while keeping aggressive taking at fair
- increased ACO inventory skew a bit and reduced posted size
- this lifted total Round 1 PnL from `210,262` to `211,501`
- shifted IPR slightly more toward the intraday drift anchor
- kept some microstructure adjustment, but reduced its ability to pull fair value away from the path
- this improved Day `0` from `55,652` to `57,811` while also lifting the total result

## Official-Benchmark Calibration

- When the objective is the hidden official-site day data collected via no-trade submissions, the saved local market log must be paired with a fill model calibrated from real official bundles.
- The current `tools/calibrations/combined_official_passive_profile.json` is the recent-market profile: it layers fresh official evidence from `131422` and `163569` on top of the earlier blended `125928` / `131923` snapshot with `prior-weight=125`, because that matched the latest official bundles best.
- Under that combined calibration on the hidden day `115164`, the current `path_anchor_strategy.py` configuration reaches `8,351.5`.

## Same-Tick Ranking

Same-tick fills, `match-trades=all`, summed over day `-2/-1/0`:

- `current_strategy`: `211,501`
- `tut_try_trades_normalized`: `210,262`
- `kalman_benchmark`: `183,221`
- `tut`: `160,190`
- `tut_try_og`: `134,353`
- `tut_try_trades_adaptive`: `112,295.5`
- `tut_try`: `111,898.5`
- `tut_try_trades_wallvol`: `111,636.5`
- `tut_try_trades`: `111,464.5`

Full leaderboard:

- `IMCP2026/analysis/round1_strategy_backtest_summary.csv`

## Useful Variations

- `current_strategy.py`: current benchmark / official-hybrid entrypoint on the promoted `core70_completion_early` branch.
- `unified_strategy.py`: same promoted `core70_completion_early` branch under the historical unified filename.
- `pepper_benchmark_push_core70_completion_early.py`: current promoted production target in the PEPPER carry family.
- `pepper_benchmark_push_robust_band.py`: de-overfit carry candidate that stays close to the tuned PEPPER line without depending on one exact core target.
- `pepper_benchmark_push_core70.py`: plain `core70` control and direct implementation under the promoted wrapper.
- `pepper_benchmark_push_core67.py`: nearby PEPPER core-target compromise candidate.
- `pepper_benchmark_push_core68.py`: nearby PEPPER core-target candidate with the strongest clean same-tick result in the band.
- `path_anchor_strategy.py`: active official-benchmark-calibrated base and strongest historical same-tick path-anchor variant.
- `kalman_benchmark.py`: useful alternate benchmark leg for direct replay comparisons.
- `pepper_kalman_hybrid.py`: isolates the pepper improvement while keeping the newer ACO leg.
- `exchange_fill_probe.py`: submit this to the official site when you want richer fill-calibration evidence instead of production PnL.
- `pepper_fill_probe.py`: submit this when the bottleneck is PEPPER early passive long fills rather than total production PnL.
- `pepper_benchmark_push.py`: best current PEPPER-first benchmark candidate under the calibrated official-hybrid simulator.
- `pepper_benchmark_push__best_locked.py`: protected do-not-overwrite copy of `pepper_benchmark_push.py`.
- `pepper_fill_probe_followup_late_exit_plus2_only__best_probe_locked.py`: final PEPPER-only probe winner after confirming `+2` inside and late exit.
- `pepper_benchmark_push_plus2_passive.py`: preserved first production splice that applies the confirmed `+2` passive PEPPER entry to the benchmark push trader.
- `pepper_benchmark_push_plus2_passive_v2.py`: safer production splice that keeps the `+2` PEPPER entry, blocks late PEPPER reloads, and force-sells PEPPER into the close.
- `tutorial_wrapper_reference.py`: older normalization / execution reference base.
- `normalized_path_legacy.py`: historical predecessor of `path_anchor_strategy.py`.

## Variations To Avoid For Now

- Purely static wrapper reuse across both products.
- Naive `prev_day + 1000` execution anchoring inside the live trader without stronger inventory and quoting controls.
- Pure wall-mid normalization for IPR without an explicit intraday drift anchor.

That first path idea is real as a forecasting feature, but it only worked once it was integrated into a stronger execution framework. The pure wall-mid model from the tutorial round was not enough by itself for IPR because the dominant Round 1 effect is the repeated upward intraday path.
