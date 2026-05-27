# Round 1 — version ladder

One-screen view of the `pepper_benchmark_push_*` and `path_anchor_*` iteration. Same-tick local backtest summed over days `-2 / -1 / 0` unless noted; the shipped variant is **bold**.

For the narrative, see [`../../../round_1.md`](../../../round_1.md). For the reasoning, see [`README.md`](./README.md) and [`RESEARCH_LOG.md`](./RESEARCH_LOG.md).

## Headline ranking (same-tick, all-day, all-match)

| Strategy | PnL | Notes |
|---|---:|---|
| **`current_strategy.py` (= `pepper_benchmark_push_core70_completion_early.py`)** | **211,501** | Ship; PEPPER carry at core=70 + early-session completion quote |
| `path_anchor_strategy.py` | 210,262 | Earlier baseline; IPR normalized intraday path anchor + ACO clipped-anchor MM |
| `kalman_benchmark.py` | 183,221 | Kalman fair on IPR — leaks the drift carry |
| `tut` (tutorial wrapper port) | 160,190 | Naive reuse of tutorial wrapper |
| `tut_try_og` | 134,353 | Earlier tutorial-wrapper variant |
| `tut_try_trades_adaptive` | 112,295.5 | Pre-anchor adaptive variant |
| `tut_try` / `tut_try_trades_wallvol` / `tut_try_trades` | ~111,500–111,900 | Various pre-anchor sanity baselines |

## PEPPER carry family (the variant zoo this round)

The `pepper_benchmark_push_core<N>_*` variants iterate the PEPPER (= IPR) inventory-carry target. Plateau at `core ∈ {68, 69, 70}`; below 66 leaves carry on the floor, above 70 starts to lose to drawdown.

| Family | Variant suffix | Notes |
|---|---|---|
| Core targets | `_core60`, `_core62`, `_core66`, `_core67`, `_core68`, `_core69`, `_core70`, `_core71` | Sweep of the PEPPER carry target; **`core70`** sits at the knee of the PnL curve. |
| Plateau de-overfit | `_robust_band` | Replaces fixed core target with adaptive `66-68` band; insensitive within the plateau. |
| Inside-spread completion | `_completion_early`, `_completion_window`, `_completion_late`, `_completion_mid`, `_completion_early6`, `core69_completion_early`, `core70_completion_early` | Early-session inside-spread quote variants. `core70_completion_early` is the ship. |
| Sell-side variants | `_sell25`, `_sell35` | Sell-side aggression knobs; preserved for provenance, not active. |
| Regime gating | `_regime_gate`, `core70_early68`, `core70_early70` | Adaptive regime-switch variants. |
| Late-band probes | `_lateband2`, `core68_lateband2`, `_lateband_start92000`, `_lateband_start95000` | Late-session band controls. |
| ACO inside-spread | `_aco_hybrid`, `_aco_midclip`, `_aco_reduce_spread4`, `_aco_reduce_spread6`, `_aco_skew06`, `_aco_smallclip`, `_aco_wide_take05`, `_aco_wide_take05_spread5`, `_aco_wide_take05_spread8`, `_aco_wide_take075_spread8`, `_aco_wide_take1`, `_aco_wide_take15`, `_aco_wide_take1_spread8` | ACO-side knobs; tested but not promoted into the carry-family ship. |
| Passive depth | `_plus2_passive`, `_plus2_passive_v2`, `_adaptive_passive`, `_microclip`, `_smallclip` | `+2`-inside passive layer; v2 adds late-session no-reload + force-unwind. |
| Locked snapshots | `*__best_locked.py` | Protected copies of high-water-mark variants. **Do not overwrite.** |
| Official-bundle probes | `_official_core66`, `_official_core67`, `_official_core68` | Variants tuned against the calibrated official-bundle profile. |

## Fill-probe family

Submit-to-learn-fills variants. Not designed for PnL — designed to expose the live exchange's fill model.

| File | Purpose |
|---|---|
| `exchange_fill_probe.py` | Low-risk probe for exchange-side fill behavior by size / inside-spread distance. |
| `pepper_fill_probe.py` | PEPPER-only fill probe. |
| `pepper_fill_probe_followup.py` / `_late_exit.py` / `_late_exit_more_capacity.py` / `_late_exit_plus2_only.py` | Follow-up probes once early data came back. |
| `pepper_fill_probe_followup_late_exit_plus2_only__best_probe_locked.py` | Final probe winner after confirming `+2` inside + late exit. |

## What survived under official-bundle calibration

Local same-tick numbers diverged from the hidden official-bundle scoring by an order of magnitude. Under `tools/calibrations/combined_official_passive_profile.json` on the hidden day `115164`, the same `current_strategy.py` configuration scored only **8,351.5**.

That delta is the recurring lesson of the competition — see [`../../../lessons_learned.md` §1](../../../lessons_learned.md).
