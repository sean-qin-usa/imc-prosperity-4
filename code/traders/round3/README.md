# Round 3 — HYDROGEL anchor MM + VEV voucher chain

48-hour round. PnL resets to zero for the GOAT (R3 + R4 + R5) leg.

**Products:** `HYDROGEL_PACK` (stationary ≈ 9990, limit 200), `VELVETFRUIT_EXTRACT` (VFE, ≈ 5248, limit 200), `VEV_*` voucher chain at strikes 4000 / 4500 / 5000 / 5100 / 5200 / 5300 / 5400 / 5500 / 6000 / 6500 (limit 300 each).

**Shipped:** [`combined_ship_v29_mirror.py`](./combined_ship_v29_mirror.py) — bt **582,866**, live **442,794** (0.760× conversion).

For the narrative, see [`../../../round_3.md`](../../../round_3.md). For the complete reasoning, see [`ROUND3_RECIPE.md`](./ROUND3_RECIPE.md). For the chronological build, see [`RESEARCH_LOG.md`](./RESEARCH_LOG.md).

## The ladder at a glance

This folder is intentionally large — it preserves every shipping decision across 9 working sessions. The version ladder for the multi-sleeve strategy:

| Ship | Backtest 3-day | Live | Conversion | What changed |
|---|---:|---:|---:|---|
| v11 | 428,754 | 399,113 | 0.931× | HYDROGEL retune + synth IMB sizing |
| v15 | 443,484 | 417,605 | **0.942×** | + VFE passive drift carry |
| v25 | 497,324 | 425,560 | 0.856× | + Citadel cap=15 deep-ITM mirror |
| `427141` | 516,679 | 427,141 | 0.827× | v27 chassis port |
| `v28_warmup65` | 519,679 | 442,623 | 0.852× | + WARMUP=65 retune (biggest live-converter, +15,482 from a 1-knob change) |
| **v29_mirror (final)** | **582,866** | **442,794** | **0.760×** | + V4000/V4500 Citadel mirror — added backtest but converted at ~1 % live |

The conversion ratio is the key story — see [`../../../lessons_learned.md` §1](../../../lessons_learned.md).

## Three product classes, three sleeves

| Sleeve | Products | Strategy | Implementation |
|---|---|---|---|
| Stationary MM anchor | HYDROGEL_PACK | Clipped-anchor MM at 9990 (NOT 10000); CLIP=30, skew=0.015, post size 20 | The `h_only_v*.py` files iterate this in isolation |
| Delta-1 underlying | VFE | Hedge only — take-only is −EV at every threshold | Mostly used as vega-bearer for the voucher chain |
| Voucher chain | VEV_4000…6500 | Strike-conditional: ITM synthetic-MM, ATM IV-residual MR (Timo P3R3 port), OTM lottery / skip | Per-strike-family code embedded in the `combined_ship_v*.py` ladder |

## Notable subdirectories of files

- **`combined_ship_v1.py` … `v31.py`** — the main shipping ladder. Each file's docstring says what changed vs the prior version.
- **`h_only_v5.py` … `v26_test.py`** — HYDROGEL-only iterations, used to tune the load-bearing sleeve without contamination from other products.
- **`combined_v1.py` … `v71.py`** — the early-session experimentation ladder, before the `combined_ship_*` line was forked off as the production track. v60+ are mostly dead-ends.
- **`fundamental_*.py`** — voucher-chain pricing experiments (spot-anchor, surface-gate, drift-guard, etc.). The `*_uploadsafe_v1.py` variants are the live-submission-ready versions.
- **`baseline_v1.py` … `v20.py`** — baseline references for relative measurement of the more elaborate ships.
- **`_*` files** (`_adaptive_v1.py`, `_drift_v1.py`, …) — short-lived experimental probes, named with a leading underscore. Most are no-result.
- **`HYDROGEL_ONLY_RECIPE_v*.md`** — recipe markdowns for the HYDROGEL sleeve at each shipping point.
- **`VOUCHER_*.md`, `VFE_*.md`** — voucher-chain findings (regime breakdowns, IV surface, drift carry).

## Cross-round transfer

This round is structurally **Prosperity 3 Round 3** (one delta-1 underlying + voucher chain). The P3 reference port lives in [`../p3_fresh/`](../p3_fresh/) — copy the *structure* (BS theo, IV-EMA, ITM-MR), refit the *numbers*. See [`P3R3_TRANSFER_NOTE.md`](./P3R3_TRANSFER_NOTE.md) for the explicit mapping.

## Manual challenge

The Bio-Pod two-bid auction analysis lives in [`../../analysis/round3/manual/`](../../analysis/round3/manual/) (six-scenario prior sweep) and [`../../analysis/round3/manual_from_scratch/`](../../analysis/round3/manual_from_scratch/) (clean first-principles derivation). Submitted `(775, 875)` — see [`../../../round_3.md`](../../../round_3.md) for the reasoning.
