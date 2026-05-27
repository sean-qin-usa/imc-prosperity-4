# Round 1 Research Log

This file is the running record for Round 1 strategy work.

Rule for future turns:
- Update this file every conversation when strategy work continues.
- Record what was tried, the evidence we have, and whether it still looks worth time.
- Prefer concrete backtest references over vague impressions.

## Method Notes

- `current_strategy.py` is currently a wrapper that imports `pepper_benchmark_push_core70_completion_early.py`.
- `unified_strategy.py` is now also a wrapper that imports `pepper_benchmark_push_core70_completion_early.py`.
- `round1_csv` `run_summary.csv` files contain one row per day (`-2`, `-1`, `0`), not one aggregate row.
- For `round1_csv`, evaluate total performance by summing `final_total_pnl` across all rows in the file.
- Be careful not to rank strategies off the day `0` row alone.
- For `official-hybrid` archive comparisons, check both the strategy hash and the calibration context.
- Run manifests currently store the calibration file path, but not a hash of the calibration file contents.
- That means older `official-hybrid` PnL can become imperfectly comparable across dates if `tools/calibrations/combined_official_passive_profile.json` changed in between runs.
- In the current local dataset discovery, `115164` is directly runnable, but older hidden-day slices like `125928` and `131422` appear only through archived run artifacts unless extra inputs are provided.

## Current Read

- The `round1_csv` methodology correction matters: compare strategies on the sum across days `-2/-1/0`, not the last row in `run_summary.csv`.
- The strongest family right now is the PEPPER carry / benchmark-push line, not the pure Kalman or pure path-anchor line.
- With that correction applied, the PEPPER carry / benchmark-push family is still clearly ahead of the path/Kalman families on full `official-hybrid` evidence.
- `unified_strategy.py` is no longer part of the old inline `+2` passive branch after the PEPPER carry promotions.
- `pepper_benchmark_push_plus2_passive.py` now serves as the preserved executable reference for that older `+2` passive branch.
- `current_strategy.py` and `unified_strategy.py` now point at the same promoted `core70_completion_early` baseline.
- Historical direct reruns of the old unified / `+2` passive branch put:
- `pepper_benchmark_push_plus2_passive.py` at `310991.0` on `official-hybrid`
- `pepper_benchmark_push_plus2_passive.py` at `291041.0` on `same-tick`
- Current promoted wrapper-equivalent baseline now puts:
- `current_strategy.py` / `unified_strategy.py` / `pepper_benchmark_push_core70_completion_early.py` at `314454.0` on `official-hybrid`
- `current_strategy.py` / `unified_strategy.py` / `pepper_benchmark_push_core70_completion_early.py` at `292669.0` on `same-tick`
- Nearby direct comparison runs under explicit `official-hybrid` settings put:
- `pepper_benchmark_push.py` at `310331.0`
- `pepper_benchmark_push__best_locked.py` at `313680.0`
- `pepper_benchmark_push_aco_skew06.py` at `312661.0`
- Nearby direct comparison runs under `same-tick` put:
- `pepper_benchmark_push__best_locked.py` at `291844.0`
- `pepper_benchmark_push_aco_skew06.py` at `289945.0`
- Fresh PEPPER core-target sweep off `best_locked` now puts:
- `core60`: `313184.0` official-hybrid
- `core62`: `313525.0` official-hybrid
- `core64` (`best_locked`): `313680.0` official-hybrid, `291844.0` same-tick
- `core66`: `313904.0` official-hybrid, `292219.0` same-tick
- `core67`: `313817.0` official-hybrid, `292343.0` same-tick
- `core68`: `313862.0` official-hybrid, `292492.0` same-tick
- `core69`: `314078.0` official-hybrid, `292565.0` same-tick
- `core70`: `314439.0` official-hybrid, `292639.0` same-tick
- `core71`: `313623.0` official-hybrid, `292532.0` same-tick
- `current_strategy.py` now points at `pepper_benchmark_push_core70_completion_early.py`, so the stable entrypoint tracks the best balanced PEPPER carry branch.
- Fresh post-promotion wrapper rerun:
- `current_strategy.py` at `314454.0` on `official-hybrid round1_csv`
- `current_strategy.py` at `292669.0` on `same-tick round1_csv`
- The older `current_strategy.py` `201455.5` wrapper result is stale; a fresh wrapper rerun now sums to `310991.0`.
- The older symmetric fair-vs-touch families still matter as diagnostics, but they look regime-dependent and not robust enough to be the main PEPPER engine.
- The current/unified branch is not obviously winning because its PEPPER leg is stronger.
- On the clean rerun, `pepper_benchmark_push.py` has slightly better PEPPER end-of-day PnL on days `-1` and `0`, but the current/unified line makes that back mostly through a stronger ACO leg.
- `pepper_benchmark_push__best_locked.py` was the first clear PEPPER-side improvement over the old current/unified line, but it is no longer the live leader.
- The best current live result in the workspace is now `pepper_benchmark_push_core70_completion_early.py`.
- `pepper_benchmark_push_aco_skew06.py` is still useful as a diagnostic, but the ACO-only splice is not robust enough to promote on its own because it falls back below the current/unified line under `same-tick`.
- The PEPPER core target was not actually optimized at `64`.
- The completed sweep says the best PEPPER core is around `70`:
- totals rise smoothly from `66` through `70`
- `71` rolls over
- `72` is much worse
- The reproducible hidden-style `115164` checks support the same move upward:
- `official-hybrid`: `core64 10630.0`, `core66 10632.0`, `core68 10629.0`, `core70 10650.0`
- `same-tick`: `core66 10234.5`, `core68 10245.5`, `core70 10254.5`
- Raising the early visible-take cap above `64` does not improve the promoted `core70` baseline on full-round data:
- `core70_early68`: `314439.0` official-hybrid, `292602.0` same-tick
- `core70_early70`: `314436.0` official-hybrid, `292577.0` same-tick
- Lower average fill by itself is not evidence of a real exploitable branch:
- the strongest low-fill ACO screen (`aco_wide_take05_spread8`) drops official-hybrid average fill from `4.975` to `4.776`, but same-tick falls to `288723.0` and hidden-style `115164` falls to `10469.0`
- A deliberately less-tuned PEPPER carry splice can still stay close to the leader:
- `pepper_benchmark_push_robust_band.py` scored `312263.0` on `official-hybrid round1_csv`, `291249.0` on `same-tick round1_csv`, and `10461.0` on `official-hybrid 115164`
- That is below `core70`, but only by about `2.2k` on `official-hybrid`, `1.4k` on `same-tick`, and `189` on `115164`
- So the main PEPPER edge is still structural carry/path logic, not just one fixed magic core target, even though the tuned fixed target still wins
- Small-clip benchmark-push variants are clearly inferior and can be deprioritized.
- Fresh standalone checks on `171689.py` put:
- `316008.0` on `official-hybrid round1_csv`
- `287622.0` on `same-tick round1_csv`
- `10453.0` on `official-hybrid 115164`
- `10264.5` on `same-tick 115164`
- That makes `171689.py` a strong visible `official-hybrid` branch, but not a balanced production leader:
- rank `3` on `official-hybrid round1_csv`
- rank `20` on `same-tick round1_csv`
- rank `23` on `official-hybrid 115164`
- Product decomposition versus the promoted `current_strategy.py` / `pepper_benchmark_push_core70_completion_early.py` branch says:
- on `official-hybrid round1_csv`, `171689.py` wins mostly through ACO:
- `171689.py` ACO `74553.0` versus current `71206.0` (`+3347.0`)
- `171689.py` IPR `241455.0` versus current `243248.0` (`-1793.0`)
- net `+1554.0`
- on `same-tick round1_csv`, `171689.py` loses on both legs:
- `171689.py` ACO `45648.0` versus current `48040.0` (`-2392.0`)
- `171689.py` IPR `241974.0` versus current `244629.0` (`-2655.0`)
- net `-5047.0`
- Hidden-style `115164` `official-hybrid` points in the same direction:
- `171689.py` ACO `2872.0` versus current `3102.0` (`-230.0`)
- `171689.py` IPR `7581.0` versus current `7530.0` (`+51.0`)
- net `-179.0`
- So `171689.py` looks like a fill-model-sensitive visible-benchmark splice, not the most robust live submission candidate.
- Fresh direct reruns also say `171689.py` is not even the best current member of its own standalone `core72` family:
- `pepper_benchmark_push.py` scored `316516.0` on `official-hybrid round1_csv` and `288723.0` on `same-tick round1_csv`
- its IPR totals match `171689.py` exactly on both visible runs
- the whole gap comes from ACO: `+508.0` on `official-hybrid`, `+1101.0` on `same-tick`
- that points directly at the wide-spread ACO take guard in `pepper_benchmark_push.py` as the difference, not the PEPPER leg
- Fresh hidden-day bundle `213509` adds a more nuanced read:
- `/Users/sean_tsu_/Downloads/213509/213509.py` is functionally identical to `pepper_benchmark_push_core70_completion_early.py` (same file except trailing newline), so the official `213509` result is direct evidence on the promoted branch.
- The official-site `213509.json` score for that promoted branch is `10136.96875`.
- Local replay of that exact uploaded file on `213509.log` under `official-hybrid` gives `10052.0`, so the calibrated local model is directionally useful but not exact on absolute level.
- On the exact same `213509.log` hidden-day replay:
- `171689.py` scores `10748.5` on `official-hybrid`
- `pepper_benchmark_push_core70_completion_early.py` scores `10052.0` on `official-hybrid`
- `171689.py` wins there by `696.5`
- Product split on `213509` `official-hybrid` says `171689.py` wins on both legs:
- ACO `3180.0` versus `2591.0` (`+589.0`)
- IPR `7568.5` versus `7461.0` (`+107.5`)
- But the same hidden day under `same-tick` still slightly favors the promoted branch:
- `171689.py` `10218.5`
- `pepper_benchmark_push_core70_completion_early.py` `10236.5`
- So `213509` is not clean evidence that `171689.py` is universally better; it is evidence that `171689.py` can outperform on a real hidden day under the calibrated official-hybrid assumptions, while the simpler fill model still leans slightly toward the promoted branch.
- Updated practical read:
- Before `213509`, `171689.py` looked mostly like a higher-variance visible-benchmark branch.
- After `213509`, it is no longer fair to dismiss it as pure noise or simulator overfit.
- The right framing now is:
- `pepper_benchmark_push_core70_completion_early.py` remains the more broadly validated / robustness-first branch across the existing round1 suite.
- `171689.py` is the more aggressive branch with fresher hidden-day evidence in its favor, but with materially worse historical same-tick robustness.

## Strategy Ledger

### `unified_strategy.py`

Status:
- Wrapper entrypoint
- Promoted unified alias of the live production baseline

What it is:
- Historical unified filename promoted onto `pepper_benchmark_push_core70_completion_early.py`.
- Keeps the unified entrypoint aligned with the strongest validated PEPPER carry branch while preserving the old inline `+2` logic in `pepper_benchmark_push_plus2_passive.py`.

Evidence:
- Historical direct runs before promotion:
- `official-hybrid`, `round1_csv`, summed over `-2/-1/0`: `309836.0`
- Run: `gen/backtests/20260415_154606__unified_strategy__official-hybrid__all__round1_csv__baseline_unified_official_hybrid_multilevel_cmp/run_summary.csv`
- `same-tick`, `round1_csv`, summed: `291041.0`
- Run: `gen/backtests/20260415_154606__unified_strategy__same-tick__all__round1_csv__baseline_unified_same_tick_multilevel_cmp/run_summary.csv`
- Promoted wrapper-equivalent baseline:
- `pepper_benchmark_push_core70_completion_early.py` at `314454.0` on `official-hybrid round1_csv`
- `pepper_benchmark_push_core70_completion_early.py` at `292669.0` on `same-tick round1_csv`
- Matching wrapper entrypoint evidence:
- `current_strategy.py` at `314454.0` on `official-hybrid round1_csv`
- Run: `gen/backtests/20260415_171310__current_strategy__official-hybrid__all__round1_csv__baseline_current_official/run_summary.csv`
- `current_strategy.py` at `292669.0` on `same-tick round1_csv`
- Run: `gen/backtests/20260415_171310__current_strategy__same-tick__all__round1_csv__baseline_current_same_tick/run_summary.csv`

Take:
- The unified filename now resolves to the best balanced live branch in the workspace.
- Use `pepper_benchmark_push_plus2_passive.py` when you specifically want the older inline unified behavior for archived comparison.

### `pepper_benchmark_push_plus2_passive.py`

Status:
- Highest potential in stored `official-hybrid` full-dataset results
- Strong reference implementation

What it is:
- PEPPER-first carry framework with the probe-confirmed `+2` passive PEPPER bid entry.

Evidence:
- `official-hybrid`, `round1_csv`, summed: `325033.0`
- Run: `gen/backtests/20260414_214400__pepper_benchmark_push_plus2_passive__official-hybrid__all__round1_csv__baseline_plus2_official_hybrid_seq/run_summary.csv`
- Clean rerun, `official-hybrid`, `round1_csv`, summed: `310991.0`
- Run: `gen/backtests/20260415_160035__pepper_benchmark_push_plus2_passive__official-hybrid__all__round1_csv/run_summary.csv`
- `same-tick`, `round1_csv`, summed: `291041.0`
- Run: `gen/backtests/20260414_213522__pepper_benchmark_push_plus2_passive__same-tick__all__round1_csv__premerge_benchmark_push_plus2/run_summary.csv`

Take:
- Best stored archived `official-hybrid` result.
- The `+2` passive entry looks real and worth preserving.
- This is one of the main lines to protect and compare against.
- Note: this file preserves the old inline unified implementation after `unified_strategy.py` was promoted to the `core70_completion_early` wrapper.

### `pepper_benchmark_push.py`

Status:
- High potential
- Still live for tuning

What it is:
- Cleaner PEPPER benchmark-carry strategy without the full splice packaging.

Evidence:
- Latest stored variant, `official-hybrid`, `round1_csv`, summed: `311597.0`
- Run: `gen/backtests/20260415_145939__pepper_benchmark_push__official-hybrid__all__round1_csv__push_core72_lateband2_seq/run_summary.csv`
- Clean rerun, `official-hybrid`, `round1_csv`, summed: `310331.0`
- Run: `gen/backtests/20260415_160035__pepper_benchmark_push__official-hybrid__all__round1_csv/run_summary.csv`
- Nearby tuning variants:
- `push_core72_seq`: `313374.0`
- Run: `gen/backtests/20260415_142614__pepper_benchmark_push__official-hybrid__all__round1_csv__push_core72_seq/run_summary.csv`
- `push_core72_lateband3_seq`: `312147.0`
- Run: `gen/backtests/20260415_145324__pepper_benchmark_push__official-hybrid__all__round1_csv__push_core72_lateband3_seq/run_summary.csv`

Take:
- Strong family.
- The recent late-band reductions did not beat the plain `core72` sequence on full summed `round1_csv`.
- Worth continued tuning, but changes need to beat the stored `313374.0` bar, not just improve day `0`.
- On the clean rerun it sits only `660.0` behind the current/unified line, so it is still a very live branch.
- Its PEPPER leg is actually a bit more selective and slightly stronger into the close; the gap appears to come mostly from ACO.

### `pepper_benchmark_push__best_locked.py`

Status:
- Historical PEPPER breakthrough
- Still high-value reference branch

What it is:
- Benchmark-push carry with:
- stronger ACO settings
- `IPR_CORE_TARGET = 64`
- main PEPPER passive bid effectively at `+1` inside the spread

Evidence:
- Fresh `official-hybrid`, `round1_csv`, summed: `313680.0`
- Run: `gen/backtests/20260415_161035__pepper_benchmark_push__best_locked__official-hybrid__all__round1_csv/run_summary.csv`
- Fresh `same-tick`, `round1_csv`, summed: `291844.0`
- Run: `gen/backtests/20260415_161922__pepper_benchmark_push__best_locked__same-tick__all__round1_csv/run_summary.csv`
- Hidden day `115164`: `10630.0`
- Run: `gen/backtests/20260415_141205__pepper_benchmark_push__best_locked__official-hybrid__all__115164__site_locked_115164/run_summary.csv`

Take:
- This was the first best completed live PEPPER branch in the current workspace.
- It beat the old current/unified branch on both `official-hybrid` and `same-tick`.
- Compared with the current/unified line, the ACO PnL is identical day by day on both clean reruns.
- The entire gain comes from better PEPPER PnL, which points directly at the PEPPER passive-entry shape rather than ACO.
- Relative to the current/unified line on the clean `official-hybrid` rerun, PEPPER shifts toward more passive buy reloads and away from some visible buy-taking:
- passive PEPPER buy qty `697` versus `492`
- visible PEPPER buy qty `1568` versus `1727`
- visible PEPPER sell qty `2036` versus `1993`
- The key executable difference versus the current/unified branch is the PEPPER passive bid quoting at `+1` inside instead of `+2`.
- Follow-up sweep note:
- `best_locked` was a real improvement, but not the end of the PEPPER tuning line.
- The next clean knob after `+1` passive entry turned out to be `IPR_CORE_TARGET`.

### `pepper_benchmark_push_core6x.py`

Status:
- High potential
- Best current PEPPER tuning direction

What it is:
- Minimal variants that inherit `pepper_benchmark_push__best_locked.py`
- Change only `IPR_CORE_TARGET`

Evidence:
- `core60`
- `official-hybrid`, `round1_csv`, summed: `313184.0`
- Run: `gen/backtests/20260415_163022__pepper_benchmark_push_core60__official-hybrid__all__round1_csv/run_summary.csv`
- `core62`
- `official-hybrid`, `round1_csv`, summed: `313525.0`
- Run: `gen/backtests/20260415_163022__pepper_benchmark_push_core62__official-hybrid__all__round1_csv/run_summary.csv`
- `core66`
- `official-hybrid`, `round1_csv`, summed: `313904.0`
- Run: `gen/backtests/20260415_163022__pepper_benchmark_push_core66__official-hybrid__all__round1_csv/run_summary.csv`
- `same-tick`, `round1_csv`, summed: `292219.0`
- Run: `gen/backtests/20260415_163315__pepper_benchmark_push_core66__same-tick__all__round1_csv/run_summary.csv`
- `official-hybrid`, `115164`: `10632.0`
- Run: `gen/backtests/20260415_163459__pepper_benchmark_push_core66__official-hybrid__all__115164/run_summary.csv`
- `core67`
- `official-hybrid`, `round1_csv`, summed: `313817.0`
- Run: `gen/backtests/20260415_163527__pepper_benchmark_push_core67__official-hybrid__all__round1_csv/run_summary.csv`
- `same-tick`, `round1_csv`, summed: `292343.0`
- Run: `gen/backtests/20260415_163527__pepper_benchmark_push_core67__same-tick__all__round1_csv/run_summary.csv`
- `core68`
- `official-hybrid`, `round1_csv`, summed: `313862.0`
- Run: `gen/backtests/20260415_163022__pepper_benchmark_push_core68__official-hybrid__all__round1_csv/run_summary.csv`
- `same-tick`, `round1_csv`, summed: `292492.0`
- Run: `gen/backtests/20260415_163315__pepper_benchmark_push_core68__same-tick__all__round1_csv/run_summary.csv`
- `official-hybrid`, `115164`: `10629.0`
- Run: `gen/backtests/20260415_163459__pepper_benchmark_push_core68__official-hybrid__all__115164/run_summary.csv`
- `same-tick`, `115164`: `10245.5`
- Run: `gen/backtests/20260415_164615__pepper_benchmark_push_core68__same-tick__all__115164/run_summary.csv`
- `core69`
- `official-hybrid`, `round1_csv`, summed: `314078.0`
- Run: `gen/backtests/20260415_164652__pepper_benchmark_push_core69__official-hybrid__all__round1_csv/run_summary.csv`
- `same-tick`, `round1_csv`, summed: `292565.0`
- Run: `gen/backtests/20260415_164652__pepper_benchmark_push_core69__same-tick__all__round1_csv/run_summary.csv`
- `core70`
- `official-hybrid`, `round1_csv`, summed: `314439.0`
- Run: `gen/backtests/20260415_164652__pepper_benchmark_push_core70__official-hybrid__all__round1_csv/run_summary.csv`
- `same-tick`, `round1_csv`, summed: `292639.0`
- Run: `gen/backtests/20260415_164652__pepper_benchmark_push_core70__same-tick__all__round1_csv/run_summary.csv`
- `official-hybrid`, `115164`: `10650.0`
- Run: `gen/backtests/20260415_165839__pepper_benchmark_push_core70__official-hybrid__all__115164/run_summary.csv`
- `same-tick`, `115164`: `10254.5`
- Run: `gen/backtests/20260415_165839__pepper_benchmark_push_core70__same-tick__all__115164/run_summary.csv`
- `core71`
- `official-hybrid`, `round1_csv`, summed: `313623.0`
- Run: `gen/backtests/20260415_165206__pepper_benchmark_push_core71__official-hybrid__all__round1_csv/run_summary.csv`
- `same-tick`, `round1_csv`, summed: `292532.0`
- Run: `gen/backtests/20260415_165206__pepper_benchmark_push_core71__same-tick__all__round1_csv/run_summary.csv`

Take:
- This is the strongest new finding from the latest pass.
- The PEPPER carry line improves further when `IPR_CORE_TARGET` moves above `64`.
- The curve is smooth, which is what you want from a real parameter:
- lower than `64` gets worse
- `66-70` improve progressively
- `71` rolls over
- `72` is much worse
- `core70` is now the best completed candidate on both full fill models.
- The `115164` hidden-style checks also move in the same direction and now favor `core70`.
- The correct conclusion is:
- the PEPPER core target should be centered at `70`, with `71` already too far and `72` clearly too high
- This is a better use of research time than returning to the Kalman-fair add-on.

### `pepper_benchmark_push_robust_band.py`

Status:
- Medium-high potential
- Good de-overfit reference candidate

What it is:
- `best_locked` carry structure with two deliberate simplifications:
- replace the fixed PEPPER core target with a small adaptive `66-68` band
- allow a light early-session anchor recentering so the path is less dependent on the exact opening print

Evidence:
- `official-hybrid`, `round1_csv`, summed: `312263.0`
- Run: `gen/backtests/20260415_170235__pepper_benchmark_push_robust_band__official-hybrid__all__round1_csv__robust_band_oh/run_summary.csv`
- `same-tick`, `round1_csv`, summed: `291249.0`
- Run: `gen/backtests/20260415_170235__pepper_benchmark_push_robust_band__same-tick__all__round1_csv__robust_band_st/run_summary.csv`
- `official-hybrid`, `115164`: `10461.0`
- Run: `gen/backtests/20260415_170235__pepper_benchmark_push_robust_band__official-hybrid__all__115164__robust_band_115164/run_summary.csv`
- Fresh rerun confirmation on `2026-04-15` reproduced the same totals:
- `same-tick`, `round1_csv`: `291249.0`
- Run: `gen/backtests/20260415_200114__pepper_benchmark_push_robust_band__same-tick__all__round1_csv__robust_band_st/run_summary.csv`
- `official-hybrid`, `round1_csv`: `312263.0`
- Run: `gen/backtests/20260415_200427__pepper_benchmark_push_robust_band__official-hybrid__all__round1_csv__robust_band_oh/run_summary.csv`
- `official-hybrid`, `115164`: `10461.0`
- Run: `gen/backtests/20260415_200812__pepper_benchmark_push_robust_band__official-hybrid__all__115164__robust_band_115164/run_summary.csv`

Take:
- This does not beat the tuned `core70` production line.
- But it stays surprisingly close on both replay styles without depending on one exact fixed PEPPER inventory target.
- The simplification mainly trades away some PEPPER fill aggressiveness:
- fewer inside-spread PEPPER reloads
- lower turnover
- slightly weaker hidden-day carry capture
- Keep this as the honest answer to "can we reproduce the shape without obvious overfit?"

### `current_strategy.py`

Status:
- Wrapper entrypoint
- Production target is now explicit and stable

What it is:
- Stable entrypoint that now imports `pepper_benchmark_push_core70_completion_early.py`.
- Production wrapper for the current promoted PEPPER carry baseline.

Evidence:
- Older stored `official-hybrid`, `round1_csv`, summed wrapper run: `201455.5`
- Run: `gen/backtests/20260414_215707__current_strategy__official-hybrid__all__round1_csv__current_strategy_compare/run_summary.csv`
- Stored `same-tick`, `round1_csv`, summed wrapper run: `291041.0`
- Run: `gen/backtests/20260415_134934__current_strategy__same-tick__all__round1_csv/run_summary.csv`
- Fresh `official-hybrid`, `round1_csv`, summed wrapper rerun on `2026-04-15`: `310991.0`
- Run: `gen/backtests/20260415_154920__current_strategy__official-hybrid__all__round1_csv/run_summary.csv`
- Fresh promoted-wrapper rerun, `official-hybrid`, `round1_csv`, summed: `314454.0`
- Run: `gen/backtests/20260415_171310__current_strategy__official-hybrid__all__round1_csv__baseline_current_official/run_summary.csv`
- Fresh promoted-wrapper rerun, `same-tick`, `round1_csv`, summed: `292669.0`
- Run: `gen/backtests/20260415_171310__current_strategy__same-tick__all__round1_csv__baseline_current_same_tick/run_summary.csv`
- Promoted target:
- `pepper_benchmark_push_core70_completion_early.py` at `314454.0` on `official-hybrid round1_csv`
- `pepper_benchmark_push_core70_completion_early.py` at `292669.0` on `same-tick round1_csv`
- Plain `core70` control:
- `pepper_benchmark_push_core70.py` at `314439.0` on `official-hybrid round1_csv`
- `pepper_benchmark_push_core70.py` at `292639.0` on `same-tick round1_csv`

Take:
- The old wrapper comparison is stale.
- The wrapper has now been promoted onto the `core70_completion_early` PEPPER carry baseline.
- The wrapper matches the promoted target exactly on both local replay styles.
- The direct `core70` file remains the right control when you want to isolate the tiny completion-order effect.
- When in doubt, compare the underlying implementation file directly or rerun the wrapper after base changes.

### Branch Identity Note

Current equivalence:
- `current_strategy.py` is a wrapper entrypoint that imports `pepper_benchmark_push_core70_completion_early.py`.
- `unified_strategy.py` is now also a wrapper entrypoint that imports `pepper_benchmark_push_core70_completion_early.py`.
- `pepper_benchmark_push_plus2_passive.py` preserves the historical inline `+2` passive PEPPER branch that used to sit in `unified_strategy.py`.

Implication:
- The tree has fewer truly distinct live PEPPER branches than it first appears.
- Treat `current_strategy.py` and `unified_strategy.py` as one promoted `core70_completion_early` branch.
- Treat `pepper_benchmark_push_plus2_passive.py` as the preserved old `+2` passive branch.

### `path_anchor_strategy.py`

Status:
- Medium potential
- Good diagnostic and historical reference

What it is:
- Symmetric path-anchor fair with flow and cancel adjustments, plus fair-vs-touch taking and passive quoting.

Evidence:
- `same-tick`, `round1_csv`, summed: `210468.0`
- Run: `gen/backtests/20260415_134934__path_anchor_strategy__same-tick__all__round1_csv/run_summary.csv`
- Hidden-day slices:
- `115164`: `8184.0`
- `125928`: `5027.0`
- `131422`: `6687.0`

Take:
- Better than raw Kalman on some regimes, worse on others.
- Useful as a reference for symmetric fair-based execution.
- Not the leading PEPPER production family under the current official-hybrid evidence.

### `kalman_benchmark.py`

Status:
- Medium potential as a conditional signal source
- Low potential as the full primary PEPPER strategy

What it is:
- Pure two-sided Kalman fair mean reversion:
- Buy when `best_ask < fair - threshold`
- Sell when `best_bid > fair + threshold`
- Post around `fair +/- offset`

Evidence:
- `same-tick`, `round1_csv`, summed: `183221.0`
- Run: `gen/backtests/20260415_134951__kalman_benchmark__same-tick__all__round1_csv/run_summary.csv`
- Hidden-day slices:
- `115164`: `5704.5`
- `125928`: `8275.5`
- `131422`: no stored run in the current workspace snapshot

Take:
- This idea is not nonsense.
- It clearly works in some regimes, especially `125928`.
- But it is too unstable to trust as the main PEPPER engine.
- Best use is likely as a sidecar filter or a gated trim/add module, not a full replacement.

### `pepper_first_principles.py`

Status:
- Medium-low potential

What it is:
- More guarded Kalman-style PEPPER execution with wider spread-aware thresholds and stronger inventory controls.

Evidence:
- Hidden-day slices:
- `115164`: `7505.0`
- Run: `gen/backtests/20260414_173538__pepper_first_principles__official-hybrid__all__115164/run_summary.csv`
- `131422`: `5620.5`
- Run: `gen/backtests/20260414_172205__pepper_first_principles__official-hybrid__all__131422/run_summary.csv`

Take:
- Better than the raw benchmark on some slices.
- Still not enough evidence that the Kalman-fair family beats the carry family on the full Round 1 dataset.

### `pepper_kalman_hybrid.py`

Status:
- Medium-low potential

What it is:
- Keeps newer ACO execution while isolating a Kalman-based PEPPER lift.

Evidence:
- `official-hybrid`, `round1_csv`, summed: `182728.5`
- Run: `gen/backtests/20260414_165553__pepper_kalman_hybrid__official-hybrid__all__round1_csv/run_summary.csv`

Take:
- Useful diagnostic.
- Clearly below the current PEPPER carry winners.

### `pepper_kalman_tuned.py`

Status:
- Low potential

What it is:
- Narrow refinement of the Kalman PEPPER benchmark:
- day reset handling
- modest inventory skew
- stricter same-side taking than opposite-side reduction

Evidence:
- Fresh `official-hybrid`, `115164`: `5292.5`
- Run: `gen/backtests/20260415_160300__pepper_kalman_tuned__official-hybrid__all__115164/run_summary.csv`

Take:
- This did not even beat the raw `kalman_benchmark` on the same hidden-day slice.
- Good evidence that “tune the Kalman branch harder” is not a high-value path right now.

### `unified_strategy_opening_multilevel_passive.py`

Status:
- Low-medium potential

What it is:
- Unified baseline with a PEPPER opening `+2/+3` multilevel accumulation ladder.

Evidence:
- `official-hybrid`, `round1_csv`, summed: `310263.0`
- Run: `gen/backtests/20260415_160245__unified_strategy_opening_multilevel_pass__official-hybrid__all__round1_csv__opening_multilevel_official_hybrid_cmp/run_summary.csv`
- `same-tick`, `round1_csv`, summed: `290858.0`
- Run: `gen/backtests/20260415_160245__unified_strategy_opening_multilevel_pass__same-tick__all__round1_csv__opening_multilevel_same_tick_cmp/run_summary.csv`

Take:
- Very close to the current/unified baseline, but still slightly worse.
- Not dead, but it did not produce a clean lift.

### `pepper_benchmark_push_aco_skew06.py`

Status:
- High potential
- New live candidate

What it is:
- Keep the PEPPER benchmark-push logic unchanged.
- Change only `ACO_INVENTORY_SKEW_PER_UNIT` from `0.04` to `0.06`.

Evidence:
- Fresh `official-hybrid`, `115164`: `10683.0`
- Run: `gen/backtests/20260415_161200__pepper_benchmark_push_aco_skew06__official-hybrid__all__115164/run_summary.csv`
- Fresh `official-hybrid`, `round1_csv`, summed: `312661.0`
- Run: `gen/backtests/20260415_161200__pepper_benchmark_push_aco_skew06__official-hybrid__all__round1_csv/run_summary.csv`
- Fresh `same-tick`, `round1_csv`, summed: `289945.0`
- Run: `gen/backtests/20260415_161922__pepper_benchmark_push_aco_skew06__same-tick__all__round1_csv/run_summary.csv`
- This beats:
- `pepper_benchmark_push` on `115164`: `10516.5`
- `current_strategy` on `115164`: `10518.5`

Take:
- First genuinely promising new isolate from this pass.
- Strong evidence that the current/unified edge over the push branch is heavily tied to the stronger ACO skew rather than a fundamentally better PEPPER engine.
- On full `round1_csv`, it does beat the current/unified line.
- But on the clean `same-tick` rerun it falls back to `289945.0`, below the current/unified line at `291041.0`.
- But it still trails `pepper_benchmark_push__best_locked.py`, which means the best current combination is not “push PEPPER plus stronger ACO” alone; the PEPPER passive-entry shape still matters.
- Net: keep this file as evidence about ACO, not as the production promotion candidate.

### `pepper_benchmark_push_smallclip.py`

Status:
- Low potential

Evidence:
- Fresh `official-hybrid`, `round1_csv`, summed: `283781.0`
- Run: `gen/backtests/20260415_161035__pepper_benchmark_push_smallclip__official-hybrid__all__round1_csv/run_summary.csv`

Take:
- Smaller clips cost too much edge.
- Not worth more time right now.

### `pepper_benchmark_push_microclip.py`

Status:
- Low potential

Evidence:
- Fresh `official-hybrid`, `round1_csv`, summed: `276274.5`
- Run: `gen/backtests/20260415_161035__pepper_benchmark_push_microclip__official-hybrid__all__round1_csv/run_summary.csv`

Take:
- Aggressively smaller clips are worse still.
- This branch can be dropped from the active tree.

### `pepper_benchmark_push_aco_smallclip.py`

Status:
- Low potential

Evidence:
- Fresh `official-hybrid`, `round1_csv`, summed: `282698.0`
- Run: `gen/backtests/20260415_161035__pepper_benchmark_push_aco_smallclip__official-hybrid__all__round1_csv/run_summary.csv`

Take:
- Shrinking only the ACO clips does not help enough to justify the complexity.
- Not a promising direction.

### `pepper_simple_core.py`

Status:
- Low potential

What it is:
- Simpler PEPPER carry/path model intended to retain the core thesis with less execution complexity.

Evidence:
- `official-hybrid`, `round1_csv`, summed: `104937.0`
- `same-tick`, `round1_csv`, summed: `68886.0`
- Runs:
- `gen/backtests/20260414_220148__pepper_simple_core__official-hybrid__all__round1_csv__pepper_simple_core_v2/run_summary.csv`
- `gen/backtests/20260414_220148__pepper_simple_core__same-tick__all__round1_csv__pepper_simple_core_v2/run_summary.csv`

Take:
- Simplification cost too much edge.
- Not promising as a production direction right now.

### `pepper_simple_plus.py`

Status:
- Low potential

What it is:
- Simpler path/carry model with softer execution.

Evidence:
- `official-hybrid`, `round1_csv`, summed: `96388.0`
- `same-tick`, `round1_csv`, summed: `61877.0`
- Runs:
- `gen/backtests/20260414_225148__pepper_simple_plus__official-hybrid__all__round1_csv__pepper_simple_plus_v2/run_summary.csv`
- `gen/backtests/20260414_225148__pepper_simple_plus__same-tick__all__round1_csv__pepper_simple_plus_v2/run_summary.csv`

Take:
- No clear case to spend more time here unless a very specific subcomponent is being extracted.

### `pepper_benchmark_push_plus2_passive_v2.py`

Status:
- Low potential in current form

What it is:
- `+2` passive PEPPER production candidate with stronger late no-reload / forced-unwind logic.

Evidence:
- `official-hybrid`, `round1_csv`, summed: `105206.0`
- `same-tick`, `round1_csv`, summed: `69060.0`
- Runs:
- `gen/backtests/20260414_215853__pepper_benchmark_push_plus2_passive_v2__official-hybrid__all__round1_csv__push_v2_compare/run_summary.csv`
- `gen/backtests/20260415_134951__pepper_benchmark_push_plus2_passive_v2__same-tick__all__round1_csv/run_summary.csv`

Take:
- The late-session safety logic was too expensive.
- Good cautionary example that inventory protection can destroy the PEPPER carry economics if it is too aggressive.

### `unified_strategy_soft_close_candidate.py`

Status:
- Medium-low potential

What it is:
- Softer close handling variant of the unified PEPPER strategy.

Evidence:
- `same-tick`, `round1_csv`, summed: `244107.0`
- Run: `gen/backtests/20260415_135918__unified_strategy_soft_close_candidate__same-tick__all__round1_csv/run_summary.csv`

Take:
- Not a disaster, but clearly below the best same-tick PEPPER carry line.
- May still contain salvageable close-handling ideas.

### `unified_strategy_multilevel_passive.py`

Status:
- Low incremental potential so far

What it is:
- Variant layered on top of `unified_strategy.py` with multilevel passive behavior.

Evidence:
- `official-hybrid`, `round1_csv`, summed: `309836.0`
- `same-tick`, `round1_csv`, summed: `291041.0`
- Runs:
- `gen/backtests/20260415_154606__unified_strategy_multilevel_passive__official-hybrid__all__round1_csv__multilevel_official_hybrid_cmp/run_summary.csv`
- `gen/backtests/20260415_154606__unified_strategy_multilevel_passive__same-tick__all__round1_csv__multilevel_same_tick_cmp/run_summary.csv`

Take:
- No measured lift over the base `unified_strategy` in the stored comparisons.
- Not worth extra attention unless a future fill model rewards the additional passive structure.

### Probe / calibration files

Files:
- `exchange_fill_probe.py`
- `pepper_fill_probe.py`
- `pepper_fill_probe_followup*.py`

Status:
- High potential for learning
- Low potential as direct production PnL strategies

Take:
- These are valuable when the main question is fill behavior or official-site calibration.
- Do not confuse them with production candidates.

## Mean-Reversion Idea Review

Question:
- Does “sell when market is rich vs Kalman fair, buy back later” deserve to become a subpart of the best current strategy?

Current answer:
- Yes as a research direction.
- No as a raw always-on module.

Why:
- The fully raw version already exists in `kalman_benchmark.py`.
- The more guarded Kalman version exists in `pepper_first_principles.py`.
- The stronger symmetric fair-vs-touch implementation exists in `path_anchor_strategy.py`.
- None of those families currently beat the best PEPPER carry / benchmark-push family on the full official-hybrid `round1_csv` evidence.

Best framing:
- Use spread as an execution filter, not as standalone alpha.
- Treat Kalman richness/cheapness as conditional side signals.
- If tested again, prefer a small top-side trim module above PEPPER core inventory rather than a full symmetric replacement.

## Current Differential Diagnosis

Clean rerun:
- `current_strategy.py`: `310991.0`
- `pepper_benchmark_push_plus2_passive.py`: `310991.0`
- `pepper_benchmark_push.py`: `310331.0`
- `pepper_benchmark_push_aco_skew06.py`: `312661.0`
- `pepper_benchmark_push__best_locked.py`: `313680.0`
- `pepper_benchmark_push_core66.py`: `313904.0`
- `pepper_benchmark_push_core67.py`: `313817.0`
- `pepper_benchmark_push_core68.py`: `313862.0`
- `pepper_benchmark_push_core69.py`: `314078.0`
- `pepper_benchmark_push_core70.py`: `314439.0`
- `pepper_benchmark_push_core71.py`: `313623.0`

Clean `same-tick` rerun:
- `current_strategy.py`: `291041.0`
- `pepper_benchmark_push_aco_skew06.py`: `289945.0`
- `pepper_benchmark_push__best_locked.py`: `291844.0`
- `pepper_benchmark_push_core66.py`: `292219.0`
- `pepper_benchmark_push_core67.py`: `292343.0`
- `pepper_benchmark_push_core68.py`: `292492.0`
- `pepper_benchmark_push_core69.py`: `292565.0`
- `pepper_benchmark_push_core70.py`: `292639.0`
- `pepper_benchmark_push_core71.py`: `292532.0`

What that means:
- The current/unified line and the `+2` passive file are the same live branch.
- The push branch is still very close.
- The remaining question is not “Kalman vs path vs carry” anymore.
- The useful question is “which ACO settings and which PEPPER carry settings splice together best.”

Product-level read from the clean rerun:
- `pepper_benchmark_push.py` trades far less PEPPER volume than the current/unified branch.
- Its PEPPER average fill size is about `2.34` versus about `4.24` for the current/unified branch.
- Despite trading less PEPPER, it ends with slightly better PEPPER PnL on days `-1` and `0`.
- The current/unified line gets back ahead mostly through stronger ACO PnL.
- `pepper_benchmark_push_aco_skew06.py` confirms the ACO diagnosis: just importing the stronger ACO skew lifts the push branch above the current/unified line.
- `pepper_benchmark_push__best_locked.py` then goes one step further: its edge over `aco_skew06` is entirely PEPPER-side, not ACO-side.
- Compared with `current_strategy.py`, `pepper_benchmark_push__best_locked.py` has identical ACO PnL and better PEPPER PnL.
- The same ACO-versus-PEPPER split survives under `same-tick`: `best_locked` beats `current_strategy.py` with identical ACO day-level PnL and better PEPPER day-level PnL on all three days.
- Once the PEPPER passive-entry shape was fixed at `+1`, the next meaningful PEPPER knob was `IPR_CORE_TARGET`, not more ACO work.
- The completed sweep says the PEPPER engine wants a materially higher core than `64`, with `70` as the current best full-dataset answer and `72` clearly too high.

Implication:
- The best next research path is splice isolation inside the top carry family, not more work on the Kalman family.
- The leading live hypothesis is now:
- stronger current-style ACO skew
- benchmark-push-style PEPPER carry
- `+1` main PEPPER passive bid, not `+2`
- PEPPER core target at `70`

## Next Things Worth Testing

- Promote the `best_locked` PEPPER passive-entry shape into the main production entrypoint or make an equivalent minimal patch in the current/unified branch.
- Treat the PEPPER core target as the highest-value solved knob in the live family for now.
- If more PEPPER work continues, stay local:
- hold ACO fixed at `0.06`
- keep the `+1` PEPPER passive entry
- use `core70` as the new PEPPER baseline
- if testing continues, move to adjacent execution gates rather than reopening a wide core-target sweep
- Stop spending main research time on ACO-only splices unless they improve under both `official-hybrid` and `same-tick`.
- Keep using full summed `round1_csv` totals for major decisions.
- Use `115164` as the reproducible hidden-style spot check in the current local setup.

## Update 2026-04-15

What was explored today:
- Rechecked the old Kalman mean-reversion idea against the current Round 1 PEPPER stack.
- Compared hidden-day stored runs for `current_strategy`, `path_anchor_strategy`, `kalman_benchmark`, and `pepper_first_principles`.
- Corrected the `round1_csv` ranking methodology to sum all day rows instead of reading day `0` only.
- Rebuilt the current map of which files still have real upside.
- Ran clean apples-to-apples `official-hybrid round1_csv` reruns for the live PEPPER carry contenders.
- Decomposed the current/unified versus push gap by product and by day.
- Created and tested a surgical ACO-only splice candidate: `pepper_benchmark_push_aco_skew06.py`.
- Completed full `official-hybrid round1_csv` reruns for the new splice candidates.
- Identified `pepper_benchmark_push__best_locked.py` as the best current live branch.
- Ruled out the small-clip benchmark-push family.
- Completed full `same-tick round1_csv` reruns for `pepper_benchmark_push__best_locked.py` and `pepper_benchmark_push_aco_skew06.py`.
- Reconfirmed under `same-tick` that the win is PEPPER-side, not ACO-side.
- Ran a clean PEPPER `IPR_CORE_TARGET` sweep at `60/62/66/67/68` off the `best_locked` base.
- Found that the optimal region moved into the high-60s rather than staying at `64`.

Main takeaway:
- Pure fair-fade PEPPER ideas have signal, but the current evidence says they are better used as guarded side signals than as the core production strategy.
- The most important bookkeeping fix from this pass was to sum all `round1_csv` day rows before comparing strategies; once corrected, the earlier high-level conclusion did not change.
- The `current_strategy.py` wrapper was also revalidated and is no longer represented by the stale archived `201455.5` number.
- Another useful cleanup from this pass: a few filenames represent the same live PEPPER implementation, so future comparisons should focus on genuinely different code paths rather than duplicate wrappers/copies.
- Archived `official-hybrid` numbers also need to be read with calibration drift in mind; a same-code rerun can legitimately move if the default combined passive-fill profile changed after the earlier run.
- The new promising direction is not a Kalman add-on. It is a cleaner splice inside the carry family: keep the push-style PEPPER behavior and import the stronger current ACO skew.
- The current best live conclusion is sharper than that:
- the winning splice is already on disk in `pepper_benchmark_push__best_locked.py`
- its edge over the current/unified line is PEPPER-side
- the most likely key PEPPER difference is returning the main passive PEPPER bid from `+2` to `+1`
- That conclusion now has support from both `official-hybrid` and `same-tick`, not just one fill model.
- The newest refinement is that `best_locked` is probably not the terminal PEPPER baseline anymore.
- The current strongest PEPPER tuning band is `core66-core68`, with:
- `core66` best on full `official-hybrid`
- `core68` best on full `same-tick`
- `core67` between them on both

## Update 2026-04-15 Promotion

What changed:
- Promoted `current_strategy.py` from the stale unified `+2` passive branch to `pepper_benchmark_push_core66.py`.
- Rechecked the PEPPER passive-entry delta and confirmed that the live edge over the old current/unified branch is PEPPER-side, not ACO-side.
- Tested an adaptive `+1/+2` passive-distance variant and found it still trailed pure `+1`.

Why this promotion was made:
- `core66` is the best current `official-hybrid round1_csv` result in the repo at `313904.0`.
- It remains strong on `same-tick` at `292219.0`.
- The hidden-style `115164` check is flat across the `64-68` band, so it does not contradict the move.

Current production view:
- `current_strategy.py` should now be interpreted as the promoted `core66` PEPPER carry baseline.
- `unified_strategy.py` remains a useful comparison branch, but it is no longer the stable production entrypoint.

Clarification:
- The raw idea "sell when rich vs Kalman fair, buy back later" is unlikely to improve PnL if bolted directly onto the current best strategy.
- Similar full-strategy versions already underperform the best PEPPER carry / benchmark-push family on the summed `official-hybrid` evidence.
- If revisited, it should be tested only as a small, gated sidecar module, not as an always-on core behavior.

## Update 2026-04-15: PEPPER Multilevel Timing

What was explored:
- Tested time-windowed PEPPER completion ladders on top of the stronger `core66` / `+1` passive-entry branch.
- Added a shared probe base: `pepper_benchmark_push_core66_completion_window.py`.
- Added window wrappers:
- `pepper_benchmark_push_core66_completion_early.py`
- `pepper_benchmark_push_core66_completion_mid.py`
- `pepper_benchmark_push_core66_completion_late.py`

Key result:
- The first strict version, which only posted the extra `+2` quote when even a full `+1` fill would still leave PEPPER below core, was a dead branch:
- early/mid/late all matched the plain `core66` control exactly.
- After relaxing the rule to allow a small `+2` completion quote whenever PEPPER was below core:
- `early`: `313947`
- `mid`: `313904`
- `late`: `313904`
- Control `pepper_benchmark_push_core66.py`: `313904`

Interpretation:
- The only time-of-day bucket that did anything was the early window.
- Mid and late completion ladders were inert on this branch because the strategy was already at or near its PEPPER carry core by then.
- Even in the early bucket, the multilevel effect was small:
- one direct early `+2` passive buy fill for `1` lot
- early passive `+1` buy fills increased from `19` to `26`
- total gain versus `core66` was only `+43`, and it came entirely from day `0`

Take:
- The practical edge is still the primary quote choice, not the multilevel timing.
- In the current calibrated setup, moving the main PEPPER passive bid from `+2` to `+1` matters a lot more than adding deeper completion levels.
- If multilevel quoting is kept at all, the only live version from this pass is a small early-session completion order rather than a mid/late ladder.

## Update 2026-04-15: PEPPER Core70 Promotion

What was explored:
- Extended the PEPPER `IPR_CORE_TARGET` sweep beyond the earlier `66-68` band.
- Added and ran `core69`, `core70`, and `core71` on full `official-hybrid round1_csv` and full `same-tick round1_csv`.
- Validated `core70` on the reproducible hidden-style `115164` slice under both fill models.
- Promoted `current_strategy.py` from `pepper_benchmark_push_core66.py` to `pepper_benchmark_push_core70.py`.

Key result:
- The PEPPER carry curve kept improving past `68`:
- `core69`: `314078.0` official-hybrid, `292565.0` same-tick
- `core70`: `314439.0` official-hybrid, `292639.0` same-tick
- `core71`: `313623.0` official-hybrid, `292532.0` same-tick
- `core72` was already known much worse:
- `312661.0` official-hybrid, `289945.0` same-tick
- Hidden-style validation also favored `core70`:
- `115164 official-hybrid`: `10650.0`
- `115164 same-tick`: `10254.5`

Interpretation:
- The optimum is no longer best described as “high-60s.”
- The data now says the PEPPER core should be centered at `70`.
- `71` already rolls over, so the peak is narrow enough to stop the sweep here.
- The drop from `70` to `72` is structural rather than noisy:
- PEPPER fill volume drops sharply
- PEPPER realized rotation drops
- unrealized inventory drag rises a lot

Current production view:
- `current_strategy.py` should now be interpreted as the promoted `core70` PEPPER carry baseline.
- `pepper_benchmark_push_core70.py` is the best current live branch in the workspace.
- The next research step should move away from broad core-target sweeps and into smaller execution-gate or reload-shape tests around the `core70` baseline.

## Update 2026-04-15: Core70 Early-Take Check

What was explored:
- Tested whether the promoted `core70` branch should also raise `IPR_EARLY_TAKE_TARGET` above the inherited `64`.
- Added two surgical variants:
- `pepper_benchmark_push_core70_early68.py`
- `pepper_benchmark_push_core70_early70.py`

Key result:
- Full-round results did not beat the `core70` baseline:
- Baseline `core70`: `314439.0` official-hybrid, `292639.0` same-tick
- `early68`: `314439.0` official-hybrid, `292602.0` same-tick
- `early70`: `314436.0` official-hybrid, `292577.0` same-tick
- Hidden-style `115164` was mixed:
- `early68`: `10594.0` official-hybrid, `10284.5` same-tick
- `early70`: `10606.0` official-hybrid, `10296.5` same-tick
- Baseline `core70`: `10650.0` official-hybrid, `10254.5` same-tick

Interpretation:
- The mismatch is real: baseline `core70` reaches exactly `64` by timestamp `500` on each day, so the early rule is binding.
- But forcing more early visible-taking does not improve the full dataset.
- Mildly higher early takes can help the less-calibrated hidden same-tick slice, but they either tie or lose on the full calibrated evidence.
- The current `core70` result therefore appears to benefit from letting later reload logic, not more aggressive early visible taking, complete the carry.

Take:
- Keep `IPR_EARLY_TAKE_TARGET = 64` on the production `core70` branch.
- The next PEPPER research step should move to other nearby execution gates rather than revisiting this early-take cap immediately.

## Update 2026-04-15: Core70 Sell-Edge Slice Check

What was explored:
- Tested whether the `core70` PEPPER sell trigger should move slightly off the inherited `IPR_BAND_SELL_EDGE = 3.0`.
- Added two slice-only probes:
- `pepper_benchmark_push_core70_sell25.py`
- `pepper_benchmark_push_core70_sell35.py`

Key result:
- On the reproducible `115164` slice, both probes were completely inert.
- `sell25 official-hybrid`: `10650.0`
- `sell25 same-tick`: `10254.5`
- `sell35 official-hybrid`: `10650.0`
- `sell35 same-tick`: `10254.5`
- Baseline `core70` was exactly the same on both fill models.

Interpretation:
- Around the current `core70` baseline, the small `2.5/3.5` sell-edge perturbation does not bind on this slice.
- That makes this a low-priority direction for full-round reruns right now.

Take:
- Do not spend the next PEPPER pass on tiny `IPR_BAND_SELL_EDGE` perturbations unless another dataset suggests the trigger is active more often.

## Update 2026-04-15: Higher PEPPER Core Sweep

What was explored:
- Continued the `best_locked` PEPPER core-target sweep upward.
- Completed fresh `round1_csv` runs for:
- `pepper_benchmark_push_core69.py`
- `pepper_benchmark_push_core70.py`
- `pepper_benchmark_push_core71.py`
- Tested the small early-session completion quote on the new leading completed branch:
- `pepper_benchmark_push_core70_completion_early.py`

Core sweep result:
- `core69`: `314078` official-hybrid, `292565` same-tick
- `core70`: `314439` official-hybrid, `292639` same-tick
- `core71`: `313623` official-hybrid, `292532` same-tick

Interpretation:
- The PEPPER carry optimum did not stop at `66-68`.
- In the current local setup, `core70` is the best completed core target on both fill models.
- `core71` gives back enough on both models that the sweep now looks peaked rather than flat.

Early completion result on the new control:
- `pepper_benchmark_push_core70_completion_early.py`:
- `314454` official-hybrid
- `292669` same-tick
- Versus plain `core70`, the deltas were:
- official-hybrid: `+15`
- same-tick: `+30`

Behavior note:
- Just like the earlier `core66` result, the gain is tiny and concentrated:
- official-hybrid improved only on day `-2`
- same-tick improved only on day `-2`
- The effect is therefore real across both local models, but still second-order.

Current best completed PEPPER branch:
- `pepper_benchmark_push_core70_completion_early.py`
- It is the top completed branch in the current workspace on both major local fills:
- `314454` official-hybrid
- `292669` same-tick

Take:
- The main edge is still the closer primary PEPPER quote plus the higher core target.
- The multilevel idea survives only as a very small early-session completion clip.
- If more PEPPER work continues, the right baseline is now `core70_completion_early`, not the older `core66` family.

## Update 2026-04-15: Production Promotion And ACO Overfit Check

What changed:
- Promoted the current stable wrapper `current_strategy.py` to import `pepper_benchmark_push_core70_completion_early.py`.
- Cleaned older generated backtests out of `gen/backtests` so local disk pressure stopped interfering with new runs.

Balanced production candidate:
- `pepper_benchmark_push_core70_completion_early.py`
- Best completed balanced local branch:
- `314454` official-hybrid
- `292669` same-tick

Wrapper note:
- Before the wrapper promotion, the fresh `current_strategy.py` rerun matched plain `core70` on official-hybrid:
- `314439`
- The wrapper now points at the slightly stronger `core70_completion_early` file instead.

ACO overfit screen:
- `pepper_benchmark_push_aco_wide_take05.py` produced a very large local official-hybrid gain:
- `316595` official-hybrid
- But it failed the robustness checks that matter here:
- `288959` same-tick
- `10463` on hidden-style `115164`
- Baseline `core70` on the same hidden-style check was `10650`

Interpretation:
- The wide-spread ACO take relaxation at `0.5` is almost certainly an official-hybrid overfit in the current local setup.
- It should not replace the balanced production line unless later evidence rehabilitates it on both same-tick and hidden-style checks.

Current shipping view:
- Keep `current_strategy.py` on the balanced `core70_completion_early` branch.
- Treat the aggressive ACO-wide-take line as a separate research branch, not the production default.

## Update 2026-04-15: Early-Take Neighbor Screen And Low-Fill Read

What was checked:
- Surfaced and summarized the stored `core70` neighbor runs that were not yet folded back into the main read:
- `pepper_benchmark_push_core70_early68.py`
- `pepper_benchmark_push_core70_early70.py`
- Recompared them against the live wrapper and direct promoted target:
- `current_strategy.py`
- `pepper_benchmark_push_core70_completion_early.py`
- Re-read the lower-fill ACO-wide-take branch through the fill-stat lens:
- `pepper_benchmark_push_aco_wide_take05_spread8.py`
- `pepper_benchmark_push_aco_wide_take05_spread5.py`

Key PEPPER-side result:
- The promoted branch still wins the balanced comparison:
- `current_strategy.py` / `core70_completion_early`: `314454.0` official-hybrid, `292669.0` same-tick
- `core70_early68`: `314439.0` official-hybrid, `292602.0` same-tick
- `core70_early70`: `314436.0` official-hybrid, `292577.0` same-tick
- Hidden-style checks do not rescue the early-take neighbors:
- `core70`: `10650.0` official-hybrid, `10254.5` same-tick on `115164`
- `core70_early68`: `10594.0` official-hybrid, `10284.5` same-tick on `115164`
- `core70_early70`: `10606.0` official-hybrid, `10296.5` same-tick on `115164`

Run references:
- `gen/backtests/20260415_171310__current_strategy__official-hybrid__all__round1_csv__baseline_current_official/run_summary.csv`
- `gen/backtests/20260415_171310__current_strategy__same-tick__all__round1_csv__baseline_current_same_tick/run_summary.csv`
- `gen/backtests/20260415_170922__pepper_benchmark_push_core70_early68__official-hybrid__all__round1_csv/run_summary.csv`
- `gen/backtests/20260415_170922__pepper_benchmark_push_core70_early70__official-hybrid__all__round1_csv/run_summary.csv`
- `gen/backtests/20260415_171850__pepper_benchmark_push_core70_early68__official-hybrid__all__115164/run_summary.csv`
- `gen/backtests/20260415_171851__pepper_benchmark_push_core70_early70__official-hybrid__all__115164/run_summary.csv`

Low-fill read:
- The strongest low-average-fill branch in the workspace is still the ACO-wide-take screen, not a PEPPER breakthrough:
- `aco_wide_take05_spread8`: `316516.0` official-hybrid on `round1_csv`
- But the same branch still fails the robustness checks:
- `288723.0` on `same-tick round1_csv`
- `10469.0` on `official-hybrid 115164`
- Versus the promoted branch, the lower total average fill comes mostly from PEPPER fill collapse rather than from a cleaner cross-model edge:
- `current_strategy.py` official-hybrid `round1_csv`: avg fill `4.975`, PEPPER avg fill `4.063`, ACO avg fill `5.318`
- `aco_wide_take05_spread8.py` official-hybrid `round1_csv`: avg fill `4.776`, PEPPER avg fill `2.336`, ACO avg fill `5.737`

Interpretation:
- Lower average fill on its own is not evidence that another team found a durable exploitable pattern.
- In the current local evidence, the most obvious low-fill branch is exactly the one that overperforms under official-hybrid and then breaks under same-tick and hidden-style checks.
- The safe read is:
- low average fill can be a symptom of a more selective branch
- but until it survives cross-model and hidden-style validation, it should be treated as likely calibration-sensitive overfit

Next-step bias:
- Keep `current_strategy.py` on `core70_completion_early`.
- If PEPPER work continues, prefer branches that preserve the balanced fill profile and hidden-style strength instead of chasing lower average fill directly.

## Update 2026-04-16: Final Submission File Selection

What changed:
- Filled `top_strat.py` with a standalone upload-ready copy of `pepper_benchmark_push_core70_completion_early.py`.

Selection:
- `top_strat.py` is now the final submission file.
- The choice is the robustness-first promoted branch, not the highest-variance visible-leader branch.

Why this branch:
- Best balanced completed local evidence in the workspace:
- `314454.0` on `official-hybrid round1_csv`
- `292669.0` on `same-tick round1_csv`
- Stronger historical robustness read than `171689.py` across the existing suite.
- `171689.py` remains the aggressive alternate because it improved on hidden bundle `213509` under local `official-hybrid`, but it still lags materially on the longer same-tick history and on prior hidden-style checks like `115164`.

Practical submission note:
- Use `top_strat.py` when you want the final upload artifact.
- Keep `171689.py` only as the risk-on fallback if you intentionally want to trade robustness for upside variance.

## Update 2026-04-16: Live End-Of-Day Gate Clarification

What changed:
- Reverted the broad timestamp rescale.
- Kept only the explicit late-session gate adjustment in `171689.py`.

Clarified live-specific edit:
- `171689.py` `IPR_LATE_BAND_START`: `90_000` -> `900_000`

Practical read:
- `top_strat.py` stays unchanged because it does not have a separate end-of-day cutoff.
- The final submission file remains `top_strat.py`.

## Update 2026-04-16: ACO Fair Clip Promotion

What was explored:
- Kept ACO's structural default fair at `10000`.
- Added a small clipped touch-mid recenter on top of that default:
- `fair_value = 10000 + clip(touch_mid - 10000, [-2, +2])`
- Updated ACO passive quote clamps to respect the adjusted fair instead of the raw hardcoded anchor.

Files updated:
- `top_strat.py`
- `pepper_benchmark_push_core70_completion_early.py`

Result:
- Fresh `top_strat.py` reruns improved materially on every check completed:
- `318685.0` on `official-hybrid round1_csv`
- `296694.0` on `same-tick round1_csv`
- `10747.0` on `official-hybrid 115164`

Baseline comparison:
- previous promoted branch:
- `314454.0` on `official-hybrid round1_csv`
- `292669.0` on `same-tick round1_csv`
- fresh clipped-fair branch gains:
- `+4231.0` official-hybrid on `round1_csv`
- `+4025.0` same-tick on `round1_csv`

Take:
- This is not just an `official-hybrid` simulator bump; it also improved the stricter same-tick replay and the reproducible hidden-style `115164` check.
- The right read is:
- keep the fixed `10000` anchor as the structural default
- allow a small bounded local recenter when the book is a few ticks away from that anchor
- This ACO tweak is strong enough to treat as a promotion, not just a side experiment.

## Update 2026-04-16: IPR Path Clip Rejected

What was explored:
- Tried the IPR analogue of the ACO fair clip.
- Kept the benchmark drift path as the default model.
- Added a small clipped execution-path adjustment:
- `execution_path = benchmark_path + clip(touch_mid - benchmark_path, [-2, +2])`
- Used that adjusted path only for PEPPER sell/reload/path-cap execution gates.

Result:
- The change failed all three validation checks and was reverted:
- `314956.0` on `official-hybrid round1_csv` versus promoted clipped-ACO baseline `318685.0`
- `291558.0` on `same-tick round1_csv` versus promoted clipped-ACO baseline `296694.0`
- `10723.0` on `official-hybrid 115164` versus promoted clipped-ACO baseline `10747.0`

Take:
- The IPR path model does not benefit from this kind of small execution recenter in the same way ACO benefited from a clipped fair recenter.
- Keep IPR on the original benchmark path logic.

## Update 2026-04-16: 235973 ACO Hybrid Comparison

What was explored:
- Built `top_strat_235973_aco_hybrid.py`.
- Kept the promoted `top_strat` PEPPER leg unchanged.
- Replaced only the ACO leg with the `235973.py` EMA taker sleeve plus its older benchmark MM parameters.

Visible-suite result:
- `official-hybrid round1_csv`: `322354.0`
- `same-tick round1_csv`: `295019.0`
- `official-hybrid 115164`: `10681.0`

Comparison versus promoted `top_strat.py`:
- `top_strat.py`: `318685.0` official-hybrid, `296694.0` same-tick, `10747.0` on `115164`
- hybrid deltas:
- `+3669.0` on `official-hybrid round1_csv`
- `-1675.0` on `same-tick round1_csv`
- `-66.0` on `official-hybrid 115164`

235973 hidden-bundle replay:
- On the exact `235973.log` hidden day under local replay, the hybrid beat both the uploaded `235973.py` and current `top_strat.py`:
- `official-hybrid`:
- hybrid `11595.0`
- `235973.py` `11403.5`
- `top_strat.py` `10990.0`
- `same-tick`:
- hybrid `10476.5`
- `235973.py` `10454.5`
- `top_strat.py` `10284.5`

But graph-fit quality on `235973` still leaned worse than `top_strat.py`:
- hybrid `official-hybrid` MAE `782.3`, RMSE `877.0`
- `top_strat.py` `official-hybrid` MAE `324.8`, RMSE `386.2`
- hybrid `same-tick` MAE `252.5`, RMSE `306.4`
- `top_strat.py` `same-tick` MAE `145.2`, RMSE `212.1`

Take:
- The hidden-day advantage in `235973.py` does look heavily ACO-driven, because swapping its ACO onto the current PEPPER leg preserved and slightly improved that `235973` replay edge.
- But the splice is still not a clean production promotion:
- it improves the calibrated official-hybrid visible run
- but it gives back too much on the broader same-tick suite and on `115164`
- Keep `top_strat.py` as the default robust submission.
- Keep `top_strat_235973_aco_hybrid.py` as the risk-on alternate if we want a branch that leans harder into the newer hidden-day ACO behavior.
- Implementation note:
- `top_strat_235973_aco_hybrid.py` is now a fully standalone upload-safe file; the earlier inheritance/import version could fail on the official site because it depended on local sibling files.
