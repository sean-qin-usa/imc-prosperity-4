# HYDROGEL_PACK Stand-Alone — Recipe (v17, 2026-04-25)

## TL;DR

`traders/round3/h_only_v17.py` ships at **181,903** over 3 historical
days (63,768 / 53,884 / 64,251). That is **+10,013 (+5.83 %)** over
v8 (171,890), and +228 over v16 (181,675). Day 0 +224 (the only day
where the new vol-adapt lever fires), days 1/2 unchanged.

```
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/jmerle_backtester.py traders/round3/h_only_v17.py 3 --merge-pnl --no-out
```

The hidden submission day (file `391745`) is the first 100k of day 2's
1M ticks. Day 2 gain (+6,617 vs v8) should carry over; day 0 gain
(+1,977 vs v8) is regime-specific (vol spikes) and may or may not
appear on the hidden window.

## What changed vs v8

Nine-knob retune (5 from v15 + 3 in v16 + 1 new in v17). Same code
flow except for the vol-adaptive size formula in MAKE.

| Param | v8 | v15 | v16 | v17 | Notes |
|---|---|---|---|---|---|
| `H_ANCHOR` | 9985 | 9983 | 9983 | **9983** | cliffs at 9982 / 9986 |
| `H_INV_SKEW` | 0.015 | 0.014 | 0.014 | **0.014** | plateau 0.013-0.014 |
| `CLIP_VOL_K` | 0.3 | 0.75 | 0.76 | **0.76** | **biggest single lever** (+5.4k); cliff at 0.78+ |
| `DMID_HISTORY` | 20 | 50 | 150 | **150** | smoother std; plateau 100-300 |
| `H_PENNY_EDGE` | 2.0 | 3.0 | 3.0 | **3.0** | avoids pe=2 cliff at dh≥60 |
| `H_TAKE_EDGE` | 0.0 | 0.0 | 0.5 | **0.5** | cuts marginal crosses; cliff at 0.55+ |
| `H_REDUCE_EDGE` | 0.0 | 0.0 | 0.0 | **0.0** | MUST stay 0 with TE>0 |
| `AR1_BETA` | 0.18 | 0.18 | 0.17 | **0.17** | tiny refinement |
| `H_BASE_POST_SIZE` | (=18) | (=18) | (=18) | **18** | replaces fixed `H_MAX_POST_SIZE` |
| `H_POST_VOL_K` | 0 | 0 | 0 | **1.0** | **v17 NEW** (+228): post smaller in vol bursts |
| `H_POST_MIN/MAX` | 18/18 | 18/18 | 18/18 | **12/18** | clamp range for adaptive size |

## Why H_POST_VOL_K=1.0 is the v17 lever

`adaptive_size = clip(H_BASE_POST_SIZE - H_POST_VOL_K * std,
                       [H_POST_MIN, H_POST_MAX])`

reuses the same std EMA (DMID_HISTORY=150) that drives `CLIP_VOL_K`.
With base=18, vk=1.0, std≈2.2 typical, adaptive_size ≈ 16 in normal
regime, dropping toward 12 during bursts. Posting smaller into vol
bursts avoids adverse-selected fills when book is moving fast.

Sweep is sharp:
  vk = 0.85, 0.90 → 181,659 (back to baseline)
  vk = 0.95, 1.00 → 181,903 (peak, +228)
  vk = 1.05      → 180,963 (-714)
  vk ≥ 1.10      → degrades further

Combining with TE/AR1/DH variants doesn't add anything beyond their
v16 settings. Day-0-specific gain — day 1/2 unchanged because their
realised vol stays near std=2.2 throughout (size stays at 16).

## Why TAKE_EDGE=0.5 is the v16 lever

In v15 (TE=0) we took every ask at price ≤ skew. Many of those
crosses are marginal — fair barely beat ask, and after rounding the
trade was a coin-flip net of the half-spread we paid. Requiring a
0.5-tick cushion (ap ≤ skew - 0.5) culls the noise crosses while
keeping the high-conviction ones. Sweep is cliff-shaped: TE=0.4 →
+1.16k, TE=0.5 → +1.44k (peak), TE=0.55 → -2.36k (day 2 craters).

REDUCE_EDGE has to stay at 0 once TE=0.5 is on. The reduce-only
branch was dead in v15 (it required ap ≤ skew + RE while the main
take already accepted ap ≤ skew); now ap ∈ (skew-0.5, skew+RE] is
the reduce-only band. Letting RE>0 means we cover at *worse* than
fair, which leaks PnL: RE=0.5 = -2.8k, RE=1 = -8.9k.

## Why CLIP_VOL_K=0.76 is the dominant single lever (held from v15)

`CLIP = 33 + CLIP_VOL_K * std(last DMID_HISTORY Δmid samples)`.

- v8: vk=0.3 over 20 samples → CLIP barely opens up during fast
  bursts. Strategy gets pinned long while mid keeps moving away.
- v16: vk=0.76 over 150 samples → CLIP lifts further AND the std EMA
  is steadier. Fair tracks touch_mid more loosely during volatile
  spurts. We don't get whipsawed.

This single parameter explains the bulk of the v8 → v15 jump (+5.4k
single-knob). Anchor/skew tweak captured a few k. v16 added another
+1.4k from TE.

## Sweep cliffs — DO NOT cross these

Discovered via combined vk×dh×pe×te sweeps:

1. **CLIP_VOL_K ≥ 0.78**: day 2 craters from 64k → 35k (-30k). Plateau
   is exactly 0.6–0.77.
2. **DMID_HISTORY ≤ 10**: same day-2 cliff. Need ≥ 15 samples.
3. **H_PENNY_EDGE ≤ 1**: day 2 craters (posting too aggressively
   skips fills).
4. **H_PENNY_EDGE = 2 with DMID_HISTORY ≥ 60**: day 2 craters; pe ≥ 3
   is the safe joint setting.
5. **H_MAX_POST_SIZE ≥ 20**: days 0+2 both crater. Plateau 16–18.
6. **H_ANCHOR = 9982 with H_INV_SKEW ≤ 0.014**: days 0+2 crater. Need
   anchor ≥ 9983 OR skew = 0.015.
7. **H_TAKE_EDGE ≥ 0.55** (with the rest of v16 stack): day 2 craters
   to 61.8k. Plateau is exactly 0.3–0.5.
8. **H_REDUCE_EDGE > 0 with TE > 0**: covers at worse than fair, leaks
   PnL: RE=0.5 = -2.8k, RE=1 = -8.9k.
9. **H_POST_VOL_K ≥ 1.05**: starts to lose; plateau 0.95-1.0.
10. **H_POST_VOL_K ≥ 1.5**: -2.0k+; oversize the vol response.

## What we tested and abandoned

| Idea | Result | File |
|---|---|---|
| **L3 deep-book imbalance** as fair adjust at narrow spread | `r²=0.79` in OLS but **-19k** when traded; mid moves only 4 ticks while half-spread is also 4 → no exploit. | `h_only_v9.py` |
| **drift-regime risk machinery** from baseline_v18 (drift veto + cap-flatten + 3x inv_skew) | -69k visible — kills the mean-reversion gains v8 lives on | `h_only_v10.py` |
| **cap-flattener alone** at-limit defense | -74k visible — fires during normal mean-reversion swings, locks in losses | `h_only_v11.py` |
| **position-cap on adding side** (no add when |pos|≥X) | monotonic loss; tighter cap = bigger loss; v8 hits cap during normal accumulation that DOES revert | `h_only_v12.py` |
| **VFE crash-state overlay** (VELVETFRUIT_EXTRACT mom20 regime tag) | -1.7k vs v8; -15.5k vs v16 chassis; doesn't transfer to retuned anchor | `h_only_v13.py` |
| **mid-level conditional TAKE_EDGE** (smaller TE far from anchor) | uniform TE=0.5 wins; aggressive take at extremes always loses | (v17 sweep) |
| **layered touch quotes** (small order at bb+1 + deep at floor(skew-PE)) | day 0 craters at touch-size ≥ 3 (-13k); spread is too wide for touch posting | (v17 sweep) |
| **quadratic inv-skew** (skew = base*pos + quad*pos*\|pos\|/limit) | degrades both directions; linear is optimal | (v17 sweep) |
| **endgame flatten** (force-reduce at last X% of session) | -2k to -34k; sells longs into late-day recovery | (v17 sweep) |
| Trade-flow signal (signed market-trade volume) | r=±0.01 across days, sign-flipping noise | (analysis only) |
| Multi-lag AR (lags 2–7) | All |r| ≤ 0.02; only AR(1) is real | (analysis only) |

## L3 imbalance result — file it for posterity

At narrow spread (spread<15, ~3.5% of ticks) the deep L3 layer is
present on exactly ONE side (the bid-side has 3 levels OR the ask-side
has 3 levels, never both). The "L3 imbalance" therefore reduces to a
binary flag of which side is deeper:

- bid side deeper → next-tick Δmid mean = -3.9 (mid drops by 4)
- ask side deeper → next-tick Δmid mean = +4.0 (mid rises by 4)

OLS slope is rock-stable (-4.0 ± 0.1) across all 3 days, R² = 0.79–0.84.
**But it's not exploitable**: the predicted move size (4) equals the
half-spread (4) at narrow spread. Selling the bid hoping for a 4-tick
drop earns 0 net of the half-spread. Confirmed by sweep — every L3
beta from -0.5 to -6 either hurts or matches v8.

## File map

| File | Status |
|---|---|
| `h_only_v17.py` | **SHIP** — 181,903 (+10,013 vs v8, +5.83%) |
| `h_only_v16.py` | prev ship — 181,675 (+9,785 vs v8) |
| `h_only_v15.py` | older — 180,233 (+8,343 vs v8) |
| `h_only_v14.py` | intermediate (anchor/skew only retune) — 175,497 |
| `h_only_v13.py` | abandoned (VFE crash overlay) — 170,139 |
| `h_only_v12.py` | abandoned (position-cap on add) — best 171,689 |
| `h_only_v11.py` | abandoned (cap-flattener alone) — 98,117 |
| `h_only_v10.py` | abandoned (full v18 risk machinery) — 102,845 |
| `h_only_v9.py` | abandoned (L3 imbalance fair) — 152,499 |
| `h_only_v8.py` | older ship — 171,890 |
| `HYDROGEL_ONLY_RECIPE.md` | v8 recipe |
| `HYDROGEL_ONLY_RECIPE_v16.md` | v16 recipe |
| `HYDROGEL_ONLY_RECIPE_v17.md` | this file |

## Reproduction

```bash
# Final ship
python3 tools/jmerle_backtester.py traders/round3/h_only_v17.py 3 --merge-pnl --no-out
# Expected: total 181,903  (63,768 / 53,884 / 64,251)

# Verify forbidden-imports check
grep -nE "^import os|^from os|import subprocess|exec\(|eval\(" traders/round3/h_only_v17.py
# Expected: empty
```
