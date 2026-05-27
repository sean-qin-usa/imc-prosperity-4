# Round 3 — version ladder

The most-iterated round in the competition: 100+ variant files across `combined_ship_v*.py`, `combined_v*.py`, `h_only_v*.py`, `baseline_v*.py`, `fundamental_*.py`, and `_<probe>_v*.py`. This file distills the ladder into a one-screen scan.

For the narrative, see [`../../../round_3.md`](../../../round_3.md). For the full recipe, see [`ROUND3_RECIPE.md`](./ROUND3_RECIPE.md). For the chronological build, see [`RESEARCH_LOG.md`](./RESEARCH_LOG.md) and [`RESEARCH_LOG_session8_deep.md`](./RESEARCH_LOG_session8_deep.md).

## Main shipping ladder — `combined_ship_v*.py`

The actual production track. Each step is one shipping decision with live PnL where verified.

| Ship | Backtest 3-day | Live | Conversion | What changed |
|---|---:|---:|---:|---|
| `combined_ship_v1.py` | 268,008 | 393,037 | 1.47× | HYDROGEL_PACK + VEV_4000/4500 synth-MM + VEV_5000/5100/5200/5300 IV-residual MR + VFE underlying MR (Timo P3R3 port) |
| `combined_ship_v2.py` | 279 k | 395,505 | — | `combined = ema_o_dev + 2.25 * iv_dev` (was 1.0). IV residual is ~2× more predictive than underlying-EMA. |
| `combined_ship_v4.py` | 312,124 | 395,880 | — | HYDROGEL retune + ATM smile-EMA MM on 5400/5500 + lottery on 6000/6500 |
| `combined_ship_v10.py` / `v11.py` | 341,808 / 428,754 | 398,980 / 399,113 | — | v11 ships HYDROGEL retune + synth IMB sizing (prior live best at this point) |
| `combined_ship_v12.py` | 429,028 | — | — | 4-knob HYDROGEL joint micro-tune over v11 |
| `combined_ship_v14.py` | 429,016 | — | — | HYDROGEL retune + synth IMB sizing, before VFE drift carry |
| **`combined_ship_v15.py`** | **443,484** | **417,605** | **0.942×** | + VFE passive drift carry (biggest live-converting step in the ladder) |
| `combined_ship_v20.py` | 443,484 | — | — | Multi-level VFE carry + synth V4000/V4500 carry — live-defensive on top of v15 |
| `combined_ship_v22.py` | 447,042 | — | — | Conservative ship: v15_hdrift + VEV carry only, no asym INV_SKEW |
| `combined_ship_v23.py` | 451,331 | — | — | + v15_hdrift drift-regime CLIP gate + VEV drift carry on V5000-5300 (target=300) + asym INV_SKEW |
| `combined_ship_v25.py` | 497,324 | 425,560 | 0.856× | + Citadel cap=15 deep-ITM mirror |
| `combined_ship_v26.py` | 511 k | — | — | v24 + cap=8 — pared-back Citadel |
| `427141.py` (v27 chassis port) | 516,679 | 427,141 | 0.827× | Chassis port |
| `combined_ship_v28_warmup65.py` | 519,679 | 442,623 | 0.852× | + **WARMUP=65** retune — biggest single-knob live win (+15,482 live from +3 k bt) |
| **`combined_ship_v29_mirror.py`** | **582,866** | **442,794** | **0.760×** | + V4000/V4500 Citadel mirror at TARGET=282/282, cap=10 — final ship. Added +63 k bt for only +171 live; mirror is mostly matching-engine wallpaper. |
| `combined_ship_v30.py` … `v31.py` | — | — | — | Post-R3 experiments folded into R4 chassis. |

## HYDROGEL-only iteration — `h_only_v*.py`

HYDROGEL is the load-bearing sleeve (~99 % of live PnL). These iterate it in isolation to tune without contamination from voucher signals.

| Family | Files | Notes |
|---|---|---|
| Core ladder | `h_only_v5.py` … `v26_test.py` | Sequential tuning of `H_ANCHOR / H_CLIP / H_INV_SKEW / H_MAX_POST_SIZE / H_PENNY_EDGE / H_PASSIVE_OFFSET`. Plateau at size ∈ {15–30}, skew ∈ {0.010–0.020}, CLIP ∈ {28–30}. |
| `h_only_v8.py` | Live 391,745 (172 k bt → 2.27× converter) — HYDROGEL alone. |
| `h_only_v17_walkedrebound.py` | Adds R2-style walked-spread rebound to the HYDROGEL sleeve. |

The recipe markdowns `HYDROGEL_ONLY_RECIPE_v16.md` … `v25.md` document the per-version reasoning.

## Early experimentation — `combined_v*.py`

Pre-shipping ladder. v1 through v71 — most of these were dead ends. The shipping line forked off at `combined_ship_v1` once the structural answer was clear. v60–v71 are mostly experimental probes.

## Fundamental / IV-surface experiments — `fundamental_*.py`

Voucher-chain pricing experiments testing different fair-value frameworks:

| File family | Approach |
|---|---|
| `fundamental_v1.py` | Baseline fundamental fair-value calculator. |
| `fundamental_basis_coupled_*` | Couples underlying basis to voucher fair. |
| `fundamental_consensus_hedged_*` | Consensus across strikes; hedged. |
| `fundamental_drift_basis_hedged_*` | + drift carry. |
| `fundamental_drift_guard_*` | Drift-guard gating. |
| `fundamental_spot_anchor_*` | Spot-anchored fair (multiple variants — regime guard, surface gate, smile gate, etc.). |
| `fundamental_surface_*` | Surface-level / surface-slope-guarded variants. |
| `*_uploadsafe_v1.py` | Each above, stripped of unsafe imports for the live submission environment. |

All preserved for the research record. None shipped over the `combined_ship_v*` line.

## Probe files (`_*.py`)

Short-lived experimental probes. Leading underscore is the convention for "exploratory, not for shipping":

| Family | Notes |
|---|---|
| `_adaptive_v1.py` / `_adaptive_v2.py` | Adaptive parameter probes. |
| `_drift_v1.py` … `_drift_v4.py` / `_drift_decay_v1.py` | Drift-only probes. |
| `_decay_v1.py` … `_decay_v3.py` / `_decaypcap_v1.py` / `_decayvclip_v1.py` | Decay-rate probes. |
| `_composite_v1.py` | Composite-signal probe. |
| `_gated_*` (`_t1000_p0.py`, `_t1000_pneg2k.py`, `_t2000_p0.py`, `_t500_p0.py`) | Time / position gated probes. |
| `_pcap_v1.py` … `_pcap_v4.py` | Position-cap probes. |
| `_combined_*` (`dd10k_pneg5k`, `dd15k_pneg3k`) | Drawdown × profit-negative gating. |
| `_reset*.py`, `_trail_*` | Reset and trailing-stop probes. |
| `_resetanchor1000.py` | Anchor-reset probe. |
| `_scan_tmp.py` | Throwaway scan harness. |

None of these graduated into a ship; all are kept for provenance.

## Voucher-only iteration — `voucher_only_baseline_v*.py`

Voucher chain in isolation (no HYDROGEL, no VFE underlying), used to test the voucher sleeves cleanly.

- `voucher_only_baseline_v5.py` / `v17.py`
- `voucher_only_baseline_v17_no_lottery.py` / `_outer_only.py` / `_smile_only.py` — ablations on lottery / outer-strike / smile components.
- `voucher_iv_surface_all_v1.py` / `voucher_iv_surface_liquid_v1.py` — IV-surface fitting variants.

## Timo-port reference — `timo_clone_*.py`

Direct clones of Timo Diehm's published P3 R3 strategy, used as a reference oracle for the IV-residual MR logic before adapting numbers to P4 data.

- `timo_clone_v1.py` / `v2.py` / `v3.py` / `FINAL.py`

## What I'd change about the iteration

Two things, expanded in [`../../../lessons_learned.md`](../../../lessons_learned.md):

1. **Shipping-version conversion-check** — between v25 and v29_mirror, backtest added 86 k but live added only 17 k. Should have run a conversion-check at each shipping decision.
2. **Ship cutoff well before the 50%-time mark** — most of the 100+ probe files were chased during the back half of the round, after the v15 ship had already converted at 0.942×. A hard cutoff at ~16-18 hours of the 48-hour round would have replaced that with validation time and freed up the back-half for the R4 regime-gated VFE sleeve.
