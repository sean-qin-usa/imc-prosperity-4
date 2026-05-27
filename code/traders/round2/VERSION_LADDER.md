# Round 2 — version ladder

One-screen view of the R2 iteration. Backtest on `tools/calibrations/local_bundles_profile.json` (real-data proxy, ~10 % optimistic vs real submission). Shipped variant is **bold**.

For the narrative, see [`../../../round_2.md`](../../../round_2.md). For the recipe, see [`ROUND2_RECIPE.md`](./ROUND2_RECIPE.md).

## Headline ranking

| Strategy | 3-day total | Per-day | Notes |
|---|---:|---:|---|
| Pure micro-price MM, size 20, no carry | ~210 k | ~70 k | Reference floor — what naive reuse of R1 micro-price logic produces with no carry. |
| **`final_strat.py`** (recipe ship) | **~420 k** | **~140 k** | The recipe in `ROUND2_RECIPE.md` — clipped anchor + drift carry + large-size MM + walked-spread rebound. |
| `clean_alpha.py` v10 (best clean) | ~441 k | ~147 k | Slightly more aggressive than the ship; comparable on the calibrated profile. |
| `final_strat_aco_max80_chunk1.py` (DO NOT SHIP) | ~785 k | — | 1-lot child-order chunking variant. **Local backtester artifact** — produced 27–30 k on real submission. Preserved as a research artifact. |

## Variant list

| File | Branch | Notes |
|---|---|---|
| **`final_strat.py`** | Ship | Promoted from the best validated R1 core (`pepper_benchmark_push_core70_completion_early`) with R2-specific drift-carry, micro-spread-gate, walked-rebound, and EOD unwind. |
| `final_strat_baseline_20260420.py` | Frozen baseline | Snapshot before the ACO execution-knob experiments. |
| `final_strat_aco_split.py` | ACO passive split | `10 + 9` split passive — improves local replay without changing fair. |
| `final_strat_aco_max80_chunk1.py` | DO NOT SHIP | 1-lot child orders, exploits matching engine. ~785 k local vs ~30 k real. |
| `final_strat_aco_split_chunk1.py` / `final_strat_aco_split_chunk5.py` | Chunking + split | Hybrid of split and chunking — also matching-engine-biased. |
| `final_strat_aco_max80_chunk1.py` / `final_strat_all_chunk1.py` | Aggressive chunking | Preserved as research artifacts. |
| `final_strat_split_both.py` | Both products split | Symmetric ACO + IPR split passive. |
| `clean_alpha.py` | Pre-ship reference | "Clean" version (no chunking artifacts); used as upper-bound check. |
| `strat_284364.py` | File-id-tagged variant | Submission probe with PnL ID encoded in filename. |
| `matured_market_experiment.py` | Mature-market analog | Tests how the same strategy would behave if the book matured (wider spreads, more depth). |

## Cross-round notes

- The `final_strat.py` ship inherits the PEPPER (=IPR) carry from R1 (~80 k/day at limit 80) and adds an R2-specific 2-level IPR passive layer + ACO walked-rebound.
- Documented dead-ends in this round (tight-spread micro-price gate, conditional imbalance by book depth, L1 absolute-depth direction, first/last-N-tick anomalies, ACO top-of-book Markov skew, IPR z-score MR) are in [`RESEARCH_LOG.md`](./RESEARCH_LOG.md).
- Manual challenge analysis (Research / Scale / Speed → `19 / 60 / 21`): [`../../analysis/round2/manual/summary.md`](../../analysis/round2/manual/summary.md).
