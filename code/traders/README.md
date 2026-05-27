# Traders — per-round strategies

One folder per round, plus a few auxiliary folders. Each round folder contains:

- The **shipped strategy** (file name varies by round — see the per-round README)
- Several to many **variants** from the experimentation ladder
- A **`README.md`** explaining the round at a glance
- A **`RESEARCH_LOG.md`** with the chronological build progression
- A **`ROUND<N>_RECIPE.md`** (where applicable) capturing the final reasoning in one document

## Shipped strategies per round

| Round | Shipped file | Headline result |
|---|---|---|
| 1 | [`round1/pepper_benchmark_push_core70_completion_early.py`](./round1/pepper_benchmark_push_core70_completion_early.py) | 211,501 local 3-day backtest |
| 2 | [`round2/final_strat.py`](./round2/final_strat.py) | ~420 k / 3-day on `local_bundles_profile.json` |
| 3 | [`round3/combined_ship_v29_mirror.py`](./round3/combined_ship_v29_mirror.py) | 582,866 bt / **442,794 live** |
| 4 | [`round4/current_strategy.py`](./round4/current_strategy.py) | 440,853 / 3-day jmerle backtest |
| 5 | [`round5/final_strategy.py`](./round5/final_strategy.py) | Directional MM; basket variant in `ll_pair_base_561965.py` reached **$561,965 live** |

These same files are duplicated (with round-prefixed names for skim-ability) at the top-level [`submissions/`](../../submissions/).

## Variant naming conventions

The variant filenames look noisy on first read; they aren't random. The conventions are:

| Suffix / prefix | Meaning |
|---|---|
| `current_strategy.py` / `final_strat.py` / `final_strategy.py` | The file actually shipped for that round |
| `*_v1.py`, `*_v2.py`, … | Sequential iteration of the same idea; later usually subsumes earlier |
| `*_aco_*`, `*_pepper_*`, `*_vfe_*`, `*_hydrogel_*` | Product-scoped — only that product's logic differs from the base |
| `*__best_locked.py` / `*__best_probe_locked.py` | Protected high-water-mark snapshot; do not overwrite |
| `*_uploadsafe_v1.py` | Same logic with stripped imports for the live-submission environment |
| `*_completion_early.py` | Variant with an early-session completion quote layered on the base |
| `combined_ship_v<N>` (round 3) | The shipping ladder for the multi-sleeve strategy. See [`round3/README.md`](./round3/README.md). |

If a file is named in a round's `RESEARCH_LOG.md` it's a real research artifact; if it isn't named there, treat it as a dead-end variant preserved for provenance.

## Auxiliary folders

- [`p3_fresh/`](./p3_fresh/) — prior-year (Prosperity 3) reference port used as scaffolding for the R3 voucher chain. Structural code transferable; numeric values not. See [`p3_fresh/README.md`](./p3_fresh/README.md).
- [`round2_fresh/`](./round2_fresh/) — clean-rebuild experiments on R1 → R2. Not the shipped R2 strategy (that's in `round2/`). See [`round2_fresh/README.md`](./round2_fresh/README.md).
- [`_utils/`](./_utils/) — shared trader utilities. `nothing_trader.py` is a no-op baseline.
- [`_scratch/`](./_scratch/) — preserved scratchpad files; not production code.
- [`round0/`](./round0/) — tutorial-round work.
- [`nothing_trader.py`](./_utils/nothing_trader.py) and the two R3 bot files (`round3_insider_bot.py`, `round3_quant_bot.py`) were moved into `round3/` and `_utils/` during cleanup; they're listed for completeness here.
