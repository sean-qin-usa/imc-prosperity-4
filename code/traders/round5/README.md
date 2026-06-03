# Round 5 — 50-product sentiment-directional + basket-MM

**Products:** 50 new products across 10 themed families (Galaxy Sounds, Sleep Pods, Microchips, Pebbles, Robots, UV Visors, Translators, Panels, Oxygen Shakes, Snackpacks). Per-product position limit **10**.

**Shipped:** [`final_strategy.py`](./final_strategy.py) — intentionally-simple directional MM driven by per-product sentiment side-bias and an imbalance-gated passive layer.

For the narrative, see [`../../../round_5.md`](../../../round_5.md). The news-trading manual analysis is at [`../../analysis/round5/manual/README.md`](../../analysis/round5/manual/README.md).

## Two architectures, only one shipped

This folder has two distinct strategy classes:

### 1. Directional MM (shipped) — `final_strategy.py`

Per-product side bias (buy / sell, derived from the round-5 uplink transcript) + take-aggressive-to-target + imbalance-gated passive quoting. Constants `DIRECTIONAL_TARGET=6, TAKE_SIZE=8, PASSIVE_SIZE=4, IMPROVEMENT=1, IMB_THR=0.3`. Per-product limit 10 so target ±6 leaves 4 units of room for passive-make on the same side.

### 2. Universal basket MM (not shipped, but extensively tested) — `ll_pair_base_561965.py` + variants

A layered basket / family-pair-trade overlay built up by adding one signal at a time. The base file's docstring documents the full build progression with backtest numbers:

| Stage | Signal added | Backtest 3-day | Per-day |
|---|---|---:|---:|
| v1 | 1-tick BBO improvement on every leg | $401 k | $134 k |
| v2 | + per-leg L1 imbalance skew | $433 k | $144 k |
| v3 | + category-basket-z overlay (Robots/UV/Translators) | $510 k | $170 k |
| v4 | + per-leg-mid-z on 5 snack-pack legs | $556 k | $185 k |
| **v5** | per-leg-mid-z on 13 robust mean-reverters | **$693 k** | **$231 k** |
| **v5_safe** (`ll_pair_base_561965`) | v5 + PEBBLES Σmid kill-switch | same as v5 in bt | **cumulative live $561,965** |

The `_561965` in the filename is the cumulative live PnL — what this basket-MM variant scored when run live during R5. **It was not the final R5 ship.** The directional `final_strategy.py` was the file I selected as my final R5 submission; this basket-MM variant is preserved as evidence that the structurally correct strategy was built and run during R5. See [`../../../lessons_learned.md` §0d](../../../lessons_learned.md) on why I didn't select it as the final ship.

The `ll_pair_variant_v1.py` through `v5_pair_plus_xl.py` files were modification probes off v5_safe. All small regressions on the local backtest — almost certainly a calibration issue rather than a strategy issue.

## Files in this folder

- **[`final_strategy.py`](./final_strategy.py)** — shipped directional MM.
- **[`ll_pair_base_561965.py`](./ll_pair_base_561965.py)** — basket-MM base ship (v5_safe). The `_561965` in the filename is the cumulative live PnL from running this variant during R5; it was not the file selected as the final R5 ship.
- **[`ll_pair_variant_v1.py`](./ll_pair_variant_v1.py) … [`v5_pair_plus_xl.py`](./ll_pair_variant_v5_pair_plus_xl.py)** — 5 variants on the basket base. Brief result notes in [`../../../round_5.md`](../../../round_5.md).
