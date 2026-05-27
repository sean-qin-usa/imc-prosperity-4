# HYDROGEL_PACK Stand-Alone — Recipe (v19, 2026-04-25)

## TL;DR

`traders/round3/h_only_v19.py` ships at **190,880** over 3 historical
days (69,241 / 54,182 / 67,457). That is **+18,990 (+11.05 %)** over
v8 (171,890), and +8,977 over v17 (181,903). Big gains on day 0
(+5,473) and day 2 (+3,206); day 1 small (+298 — fundamentally hard
trending day).

```
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/jmerle_backtester.py traders/round3/h_only_v19.py 3 --merge-pnl --no-out
```

The hidden submission day (file `391745`) is the first 100k of day 2's
1M ticks. Day 2 gain on local (+9,823 vs v8) should carry over.

## What changed vs v8

Eleven-knob retune (10 from v17 + 2 new in v19: ASYM long/short skew).
Code flow same as v17 except inv_skew is now sign-conditional.

| Param | v8 | v15 | v16 | v17 | v19 | Notes |
|---|---|---|---|---|---|---|
| `H_ANCHOR` | 9985 | 9983 | 9983 | 9983 | **9983** | cliffs at 9982 / 9986 |
| `H_INV_SKEW_LONG` | (=0.015) | (=0.014) | (=0.014) | (=0.014) | **−0.015** | **v19 NEW; biggest lever (+9k joint)**; cliff at ≤−0.017 (day 1 craters −30k) |
| `H_INV_SKEW_SHORT` | (=0.015) | (=0.014) | (=0.014) | (=0.014) | **+0.014** | **v19 NEW**; cliff at <0.013 (day 0+2 crater) and >0.0145 (day 2 craters) |
| `CLIP_VOL_K` | 0.3 | 0.75 | 0.76 | 0.76 | **0.76** | **dominant single-knob** (+5.4k vs v8); cliff at 0.78+ |
| `DMID_HISTORY` | 20 | 50 | 150 | 150 | **150** | smoother std; plateau 100-300 |
| `H_PENNY_EDGE` | 2.0 | 3.0 | 3.0 | 3.0 | **4.0** | v19: 3→4 (+0.5k under asym); cliff at 2 (-30k day 2) |
| `H_TAKE_EDGE` | 0.0 | 0.0 | 0.5 | 0.5 | **0.3** | v19: 0.5→0.3 (asym handles exit pressure); plateau 0.3-0.4 |
| `H_REDUCE_EDGE` | 0.0 | 0.0 | 0.0 | 0.0 | **0.0** | MUST stay 0 with TE>0 |
| `AR1_BETA` | 0.18 | 0.18 | 0.17 | 0.17 | **0.20** | v19: 0.17→0.20 |
| `H_POST_VOL_K` | 0 | 0 | 0 | 1.0 | **1.0** | v17 lever held; cliff at ≤0.8 with asym (-30k day 0!) |
| `H_POST_MIN/MAX` | 18/18 | 18/18 | 18/18 | 12/18 | **12/18** | clamp range |

## Why ASYMMETRIC inv_skew is the v19 lever

`skew = fair − (LONG if pos>0, SHORT if pos<0) · pos`

In v17 (symmetric skew=0.014), every long inventory unit pulled fair
DOWN by 0.014 — penalising further longs and pulling sells closer.
But the strategy already biases short via `H_ANCHOR=9983` (7 below
the empirical mid mean of ~9990). When mid does fall below anchor
and we accumulate longs, those longs are *high-conviction* mean-
reversion bets. Penalising them with positive skew talks the
strategy out of holding through the recovery.

In v19, `H_INV_SKEW_LONG = -0.015` flips the sign on the long side:
when long, fair shifts UP, so the strategy holds longs through the
bounce instead of unwinding into a half-mean-reversion. SHORT side
keeps the +0.014 penalty so shorts don't run away on a true uptrend.

Sweep is asymmetric and cliffy. The plateau is narrow:

  L = -0.005, S = 0.014 → 185,853  (entry plateau)
  L = -0.015, S = 0.014 → 187,582  (mid plateau, robust)
  L = -0.015, S = 0.013 → 189,048
  L = -0.016, S = 0.013 → 190,363  (peak, but cliff-adjacent)
  L = -0.017, S = 0.013 → 159,897  (CLIFF: day 1 craters −30k)
  L = -0.018, S = 0.013 → 153,831  (worse)

Joint re-tune (TE, AR1, PE, vk all moved within plateau):

  TE = 0.3, vk = 0.76, AR1 = 0.20, PE = 4.0 → **190,880** (peak)

Day 0 +5,473 vs v17 / day 1 +298 / day 2 +3,206. Day 1 fundamentally
hard (mid spends 17% of ticks 50+ ticks from anchor — trending day,
mean reversion delayed).

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
11. **H_POST_VOL_K ≤ 0.8 with v19 asym**: day 0 craters from 69k → 39k.
12. **H_INV_SKEW_LONG ≤ -0.017**: day 1 craters from 54k → 24k (-30k).
13. **H_INV_SKEW_SHORT < 0.013**: day 0 + day 2 crater.
14. **H_INV_SKEW_SHORT > 0.0145**: day 2 craters.
15. **H_PENNY_EDGE = 2 with v19 asym**: day 2 craters to 37k.

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
| **distance-adaptive inv_skew** (skew·(1 + K·\|drift\|/norm)) | monotonic loss for K>0; v19 asym is the right per-pos formulation | (v19 sweep) |
| **vol-adaptive TAKE_EDGE** (TE = base + K·std) | every (base, K) ≤ fixed TE=0.5 (v17) or TE=0.3 (v19) | (v19 sweep) |
| **range-position fair lean** (lean toward midpoint of last N-tick high/low) | every K>0 monotonic loss; static anchor wins | (v19 sweep) |
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
| `h_only_v19.py` | **SHIP** — 190,880 (+18,990 vs v8, +11.05%) |
| `h_only_v17.py` | prev ship — 181,903 |
| `h_only_v16.py` | older — 181,675 |
| `h_only_v15.py` | older — 180,233 |
| `h_only_v14.py` | intermediate (anchor/skew only retune) — 175,497 |
| `h_only_v13.py` | abandoned (VFE crash overlay) — 170,139 |
| `h_only_v12.py` | abandoned (position-cap on add) — best 171,689 |
| `h_only_v11.py` | abandoned (cap-flattener alone) — 98,117 |
| `h_only_v10.py` | abandoned (full v18 risk machinery) — 102,845 |
| `h_only_v9.py` | abandoned (L3 imbalance fair) — 152,499 |
| `h_only_v8.py` | older ship — 171,890 |
| `HYDROGEL_ONLY_RECIPE.md` | v8 recipe |
| `HYDROGEL_ONLY_RECIPE_v16.md` | v16 recipe |
| `HYDROGEL_ONLY_RECIPE_v17.md` | v17 recipe |
| `HYDROGEL_ONLY_RECIPE_v19.md` | this file |

## Reproduction

```bash
# Final ship
python3 tools/jmerle_backtester.py traders/round3/h_only_v19.py 3 --merge-pnl --no-out
# Expected: total 190,880  (69,241 / 54,182 / 67,457)

# Verify forbidden-imports check
grep -nE "^import os|^from os|import subprocess|exec\(|eval\(" traders/round3/h_only_v19.py
# Expected: empty
```
