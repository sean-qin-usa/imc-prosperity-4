# Final submissions

This folder contains the **exact algorithm file shipped on each round** plus a one-line summary. The full reasoning lives in the per-round writeups at the repo root; the code-tree snapshot lives in [`../code/`](../code/) for context.

| Round | Algorithm | Writeup | Result | Manual submission |
|---|---|---|---|---|
| 1 | [`round_1__pepper_benchmark_push_core70_completion_early.py`](./round_1__pepper_benchmark_push_core70_completion_early.py) | [`round_1.md`](../round_1.md) | 211,501 local 3-day backtest; 8,351.5 on hidden day under official-bundle calibration | "An Intarian Welcome": thin-margin bid at the floor of the known support |
| 2 | [`round_2__final_strat.py`](./round_2__final_strat.py) | [`round_2.md`](../round_2.md) | ~420 k / 3 days (~140 k / day) on `local_bundles_profile.json` | Research / Scale / Speed: **`19 / 60 / 21`** — one step past the AI-default cluster ([analysis](../code/analysis/round2/manual/summary.md)) |
| 3 | [`round_3__combined_ship_v29_mirror.py`](./round_3__combined_ship_v29_mirror.py) | [`round_3.md`](../round_3.md) | 582,866 backtest / **442,794 live** (conversion 0.760×) | Ornamental Bio-Pod: **`(775, 875)`** — cluster-aware shift from textbook-optimal `(751, 836)` ([analysis](../code/analysis/round3/manual/RECOMMENDATION.md)) |
| 4 | [`round_4__current_strategy.py`](./round_4__current_strategy.py) | [`round_4.md`](../round_4.md) | 440,853 / 3-day jmerle backtest (TTE-only update over R3 chassis) | Aether Crystal options: EV-optimal Black-Scholes allocation — math was right, made ~0 PnL on the seeded path. Variance lesson in [lessons_learned.md §0b](../lessons_learned.md). |
| 5 | [`round_5__final_strategy.py`](./round_5__final_strategy.py) | [`round_5.md`](../round_5.md) | Directional ship; pair-trade overlay variants were the right structural answer and weren't shipped — see [lessons §0d](../lessons_learned.md) | News Trading: `Lava cake −27 / Ashes −19 / Obsidian −14 / Thermalite +14 / Pyroflex −13 / Magma +8 / Sulfur +5` ([analysis](../code/analysis/round5/manual/README.md)) |

## How to read these

- The algorithm filename in `code/traders/round_N/` is preserved here with a `round_N__` prefix so the provenance is obvious.
- Each file is self-contained — it imports only the competition's `datamodel` (`Order`, `OrderDepth`, `TradingState`) and runs as the `Trader` class.
- Constants and tuning rationale are in the recipe markdown alongside each algorithm in [`../code/traders/round_N/`](../code/traders/).
