# HYDROGEL_PACK Stand-Alone — Recipe (v16, 2026-04-25)

## TL;DR

`traders/round3/h_only_v16.py` ships at **181,675** over 3 historical
days (63,544 / 53,884 / 64,247). That is **+9,785 (+5.69 %)** over
v8 (171,890), and +1,442 over v15 (180,233). Every day improves vs v8;
day 2 alone gains +6,613 (+11.5 %).

```
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/jmerle_backtester.py traders/round3/h_only_v16.py 3 --merge-pnl --no-out
```

The hidden submission day (file `391745`) is the first 100k of day 2's
1M ticks, so the day-2 gain should carry over.

## What changed vs v8

Eight-knob retune (5 from v15 + 3 new in v16). Code-flow IDENTICAL to
v8 — only param values changed. No new features.

| Param | v8 | v15 | v16 | Notes |
|---|---|---|---|---|
| `H_ANCHOR` | 9985 | 9983 | **9983** | cliffs at 9982 / 9986 |
| `H_INV_SKEW` | 0.015 | 0.014 | **0.014** | plateau 0.013-0.014 |
| `CLIP_VOL_K` | 0.3 | 0.75 | **0.76** | **biggest single lever** (+5.4k); cliff at 0.78+ (-30k day 2) |
| `DMID_HISTORY` | 20 | 50 | **150** | smoother std; plateau 100-300; cliff at ≤10 |
| `H_PENNY_EDGE` | 2.0 | 3.0 | **3.0** | avoids pe=2 cliff at dh≥60 |
| `H_TAKE_EDGE` | 0.0 | 0.0 | **0.5** | v16 NEW (+1.4k joint): cuts marginal noise crosses; cliff at 0.55+ (-2.3k day 2) |
| `H_REDUCE_EDGE` | 0.0 | 0.0 | **0.0** | MUST stay 0 with TE=0.5 (any RE>0 leaks PnL: RE=1 = -8.9k) |
| `AR1_BETA` | 0.18 | 0.18 | **0.17** | tiny refinement |

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

## What we tested and abandoned

| Idea | Result | File |
|---|---|---|
| **L3 deep-book imbalance** as fair adjust at narrow spread | `r²=0.79` in OLS but **-19k** when traded; mid moves only 4 ticks while half-spread is also 4 → no exploit. | `h_only_v9.py` |
| **drift-regime risk machinery** from baseline_v18 (drift veto + cap-flatten + 3x inv_skew) | -69k visible — kills the mean-reversion gains v8 lives on | `h_only_v10.py` |
| **cap-flattener alone** at-limit defense | -74k visible — fires during normal mean-reversion swings, locks in losses | `h_only_v11.py` |
| **position-cap on adding side** (no add when |pos|≥X) | monotonic loss; tighter cap = bigger loss; v8 hits cap during normal accumulation that DOES revert | `h_only_v12.py` |
| **VFE crash-state overlay** (VELVETFRUIT_EXTRACT mom20 regime tag) | -1.7k vs v8; was a +0.5k win on `baseline_v17` chassis but doesn't transfer to v8 chassis with anchor=9985 | `h_only_v13.py` |
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
| `h_only_v16.py` | **SHIP** — 181,675 (+9,785 vs v8, +5.69%) |
| `h_only_v15.py` | prev ship — 180,233 (+8,343 vs v8) |
| `h_only_v14.py` | intermediate (anchor/skew only retune) — 175,497 |
| `h_only_v13.py` | abandoned (VFE crash overlay) — 170,139 |
| `h_only_v12.py` | abandoned (position-cap on add) — best 171,689 |
| `h_only_v11.py` | abandoned (cap-flattener alone) — 98,117 |
| `h_only_v10.py` | abandoned (full v18 risk machinery) — 102,845 |
| `h_only_v9.py` | abandoned (L3 imbalance fair) — 152,499 |
| `h_only_v8.py` | older ship — 171,890 |
| `HYDROGEL_ONLY_RECIPE.md` | v8 recipe |
| `HYDROGEL_ONLY_RECIPE_v16.md` | this file |

## Reproduction

```bash
# Final ship
python3 tools/jmerle_backtester.py traders/round3/h_only_v16.py 3 --merge-pnl --no-out
# Expected: total 181,675  (63,544 / 53,884 / 64,247)

# Verify forbidden-imports check
grep -nE "^import os|^from os|import subprocess|exec\(|eval\(" traders/round3/h_only_v16.py
# Expected: empty
```
