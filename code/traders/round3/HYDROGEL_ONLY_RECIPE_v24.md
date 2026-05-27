# HYDROGEL_PACK Stand-Alone — Recipe (v24, 2026-04-25)

## TL;DR

`traders/round3/h_only_v24.py` ships at **196,853** over 3 historical
days (69,480 / 57,488 / 69,885). That is **+24,963 (+14.52 %)** over
v8 (171,890), and +368 over v23 (196,485). Marginal day-1-only gain
from mag-thresh on POST_VK.

```
cd /Users/sean_tsu_/Downloads/prosperity/IMCP2026
python3 tools/jmerle_backtester.py traders/round3/h_only_v24.py 3 --merge-pnl --no-out
```

The hidden submission day (file `391745`) is the first 100k of day 2's
1M ticks. Day 2 gain on local (+12,251 vs v8) should carry over.

## What changed vs v8

Sixteen-knob retune (15 from v23 + 1 new in v24: POST_VK now
mag-thresholded).

| Param | v8 | v19 | v22 | v23 | v24 | Notes |
|---|---|---|---|---|---|---|
| `H_ANCHOR` | 9985 | 9983 | 9983 | 9983 | **9983** | cliffs at 9982 / 9986 |
| `H_INV_SKEW_LONG` | (=0.015) | −0.015 | −0.015 | −0.015 | **−0.015** | v19 lever |
| `H_INV_SKEW_SHORT` | (=0.015) | +0.014 | +0.014 | +0.014 | **+0.014** | v19 lever |
| `H_VK_UP` | (=0.3) | (=0.76) | 0.78 | 0.78 | **0.78** | upper CLIP vol scaling |
| `H_VK_DN_HIGH` | — | — | — | 12.0 | **12.0** | vk when pos > 120 |
| `H_VK_DN_LOW` | — | — | (=2.7) | 2.7 | **2.7** | vk when 0 < pos ≤ 120 |
| `H_POS_THR` | — | — | — | 120 | **120** | v23 mag threshold |
| `H_VK_DN_SHORT` | — | — | 0.85 | 0.85 | **0.85** | when pos < 0 |
| `H_POST_VK_HIGH` | — | — | — | (=1.0) | **1.0** | post_vk when \|pos\|>160 (= v23) |
| `H_POST_VK_LOW` | — | — | — | (=1.0) | **0.0** | **v24 NEW** (+368): no shrink at moderate \|pos\| |
| `H_POST_ABS_POS_THR` | — | — | — | — | **160** | v24 NEW threshold |
| `DMID_HISTORY` | 20 | 150 | 150 | 150 | **150** | cliff at 200 |
| `H_PENNY_EDGE` | 2.0 | 4.0 | 4.0 | 4.0 | **4.0** | cliff at 2 / 4.5+ |
| `H_TAKE_EDGE` | 0.0 | 0.3 | 0.3 | 0.3 | **0.3** | plateau 0.3–0.35 |
| `H_REDUCE_EDGE` | 0.0 | 0.0 | 0.0 | 0.0 | **0.0** | MUST stay 0 |
| `AR1_BETA` | 0.18 | 0.20 | 0.20 | 0.20 | **0.20** | cliff at 0.25 |
| `_cap_size` linear | 0.7 | 0.7 | 0.5 | 0.5 | **0.5** | v20 lever |

## Why mag-thresholded POST_VK is the v24 lever

The v17 vol-shrink (POST_VOL_K=1.0) was justified for protection
against adverse-selection at extreme position. But it also shrank
post sizes at moderate position, where larger posts capture more
mean-reversion fills. v24 splits this:

  |pos| > 160 → POST_VK_HIGH = 1.0  (= v23, vol-shrink for protection)
  |pos| ≤ 160 → POST_VK_LOW  = 0.0  (no shrink, full size 18)

Effect: at moderate position, the strategy posts size 18 (max) every
tick. At extreme position, the strategy still gets the v17 vol-shrink
(which day 0 critically requires).

Symmetric POST_VK<1.0 craters day 0 by -30k (verified). The threshold
gate IS what makes this work — it's the only way to get the larger-
posts-at-moderate benefit without paying the day-0 cost.

Sweep is wide-plateau-narrow-cliff:
  POST_VK_HIGH < 1.0 (any) → -30k day 0 (cliff)
  POST_VK_LOW ∈ {0.0, 0.3, 0.5, 0.8} → all give exactly 196,853
  POST_ABS_POS_THR ∈ {160, 170, 180} → all give 196,853
  POST_ABS_POS_THR ≤ 140 → no win (collapses to baseline)
  POST_ABS_POS_THR > 200 → never triggers (no win)

The +368 lands entirely on day 1 (single-tick fill effect). Marginal
but free; no day 0 / day 2 cost.

## Why magnitude-thresholded vk_dn_long is the v23 lever

v22's `H_VK_DN_LONG=2.7` fired at any pos>0 — including small positions
where the brake is unnecessary. The brake is most needed when already
deep long during a persistent down-trend (where adverse selection
dominates). v23 splits the LONG side by magnitude:

  pos > 120     → vk_dn = 12.0  (extreme brake; fair drifts way below
                                  anchor, bid posts go very deep)
  0 < pos ≤ 120 → vk_dn = 2.7   (= v22 LONG value)
  pos < 0       → vk_dn = 0.85  (= v22 SHORT, unchanged)
  pos = 0       → vk_dn = 0.87  (legacy fallback)

Effect: at moderate longs (≤120), strategy stays aggressive and
captures normal mean reversion. At extreme longs (>120), the brake
fires hard and the strategy refuses to stack more inventory into
the trend.

Sweep is sharp:
  thr = 115 → 190,073 (-6.4k! day 0 craters from 69k → 63k)
  thr = 120 → 196,485 (peak)
  thr = 125 → 196,448 (close)
  thr = 130 → 196,425 (close)
  thr = 135+ → marginal regression
  vh = 10 → 195,940 (small loss)
  vh = 12 → 196,485 (peak)
  vh = 15 → 191,494 (-5k! day 2 craters)

Trade-off: sacrifices Day 0 (-1,378) for Day 1 (+1,043) and Day 2
(+1,824). Net positive, and shifts the bias toward day-2-like
regimes (which is the hidden-day source).

## Why pos-conditional vk_dn is the v22 lever

v21 widened the lower CLIP scaling symmetrically (vk_dn=0.87 always),
mostly to give the strategy more room when mid drops below anchor and
the v19 negL skew piles on longs. But the wider lower CLIP only helps
when the strategy is actually about to over-buy — i.e., when it's
already long. When flat or short, the wider lower CLIP just lets fair
drift further than necessary, which doesn't help and slightly hurts.

In v22 we make the lower-CLIP scaling position-aware:

  `H_VK_DN_LONG  = 2.7`  (when working > 0)  — much wider
  `H_VK_DN_SHORT = 0.85` (when working < 0)  — back to v20-ish
  `H_VK_DN       = 0.87` (when working == 0; rare fallback)

Effect: when already long, vk_dn jumps 3.5x. The lower CLIP grows
much faster in vol bursts → fair drifts much further below anchor →
bid price posts much deeper → strategy STOPS adding more longs into
the falling market. When short or flat, no change vs v21.

Sweep is broad-plateau on vk_long (1.5–2.7 all gain, peak at 2.7),
sharp cliff at vk_long=2.8 (-3k day 1). vk_short cliff at 0.90 (-18k
day 0!).

This addresses the same trap as the v19 asym INV_SKEW (over-buying
when long during a down-trend) but with a different mechanism — and
the two stack additively. Day 0 +1,088, Day 1 +1,084, Day 2 +253.

## Why asymmetric CLIP_VOL_K is the v21 lever

The v19 negative LONG skew biases the strategy aggressively long when
mid drops below anchor. Combined with the symmetric `CLIP_VOL_K=0.78`,
in vol bursts during a down-trend the lower CLIP grows too modestly —
fair stays close to anchor while we keep buying into a falling market.

In v21 we split the scaling:
  `H_VK_UP = 0.78` (upper CLIP scaling — same as v20)
  `H_VK_DN = 0.87` (lower CLIP grows faster in vol)

Effect: when std spikes during a down-move, the lower CLIP opens to
~33 + 0.87·σ instead of 33 + 0.78·σ. Fair drifts further below anchor,
the bid posts get pushed deeper, and the strategy stops over-buying
into the trend. Day 1 (the trending day) gains the most (+439). Day 0
and day 2 also improve marginally (+148 / +233).

Sweep is sharp:
  vk_dn = 0.80, 0.82 → ≈191,750 (no help)
  vk_dn = 0.85       → 192,432 (+681)
  vk_dn = 0.87       → 192,571 (peak)
  vk_dn = 0.90       → CRATER day 0 to 53k (-16k total)

vk_up plateau is broader (0.70-0.85 all close, 0.78 best with vk_dn=0.87).

## Why softer LIN_CAP is the v20 lever

v8/v17/v19 had `_cap_size` reducing post size by `1 - min(0.7, |pos|/limit)`,
so at moderate position (e.g., |pos|=70 = 35% of limit) the size was cut
by 35%. Combined with the additional `-0.3` reduction on the adding side,
the cap was overly conservative.

With v19's asym INV_SKEW already controlling add-side accumulation, the
old 0.7 linear factor was redundant. Lowering to 0.5 lets the
**reduce-side** post bigger sizes at moderate position — the strategy
captures more opportunistic exits without buying any extra inventory.

Sweep is broad-plateau:
  LIN_CAP = 0.7 → 190,880 (v19 baseline)
  LIN_CAP in [0.3, 0.6] → all 191,677 (+797)
  LIN_CAP = 0.65       → 191,635
  LIN_CAP = 0.85       → CRATER (size goes to ~0)

Removing the asym `-0.3` add-side reduction entirely (treat add and
reduce sides identically) → CRATER on day 0. So the asym piece matters
in some specific ticks; it's the linear cap that was the redundant
overhead.

`CLIP_VOL_K` plateau also shifts under LC=0.5: 0.78 was a CLIFF in v19
but now adds another +74. New peak is 0.78. (vk=0.80 still craters.)

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
16. **v22: H_VK_DN_LONG ≥ 2.8**: day 1 craters from 56k → 53k (-3k).
17. **v22: H_VK_DN_SHORT ≥ 0.90**: day 0 craters from 70.8k → 53k (-18k!).
18. **v23: H_POS_THR ≤ 115**: day 0 craters from 69k → 63k (-6k+).
19. **v23: H_VK_DN_HIGH ≥ 15**: day 2 craters from 70k → 64k (-6k).
20. **v23: H_VK_DN_LOW ≠ 2.7**: -3k+ in any direction; very narrow plateau.
21. **v24: H_POST_VK_HIGH < 1.0**: day 0 craters from 69k → 39k (-30k!).
22. **v24: H_POST_ABS_POS_THR ≤ 140**: collapses to v23 baseline (no win).
23. **v24: H_POST_ABS_POS_THR > 200**: never triggers (no win).

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
| **asym TAKE_EDGE** (TE_buy vs TE_sell) | sym TE=0.3 always wins; TE_buy<0.3 catastrophic on day 1 | (v20 sweep) |
| **asym PENNY_EDGE** (PE_bid vs PE_ask) | PE(5,4) gives +109 standalone but fully negates LIN_CAP=0.5 win when stacked | (v20 sweep) |
| **asym AR1** (AR_pos vs AR_neg lean) | AR(0.30, 0.15) gives +96 standalone; -2.5k when stacked with LIN_CAP=0.5 | (v20 sweep) |
| **asym CLIP** (CLIP_up vs CLIP_down) | every variation worse than sym=33; e.g. (40, 33)=124k (day 1 craters) | (v20 sweep) |
| **vol-adaptive PENNY_EDGE** (PE = base + K·std) | every (base, K) ≤ fixed PE=4.0; cliff at vk≥0.5 | (v21 sweep) |
| **pos-conditional PE** (different PE_BID/PE_ASK by position sign) | +16 noise standalone; uniform PE wins | (v21 sweep) |
| **asym BID/ASK base post size** (BID_BASE vs ASK_BASE) | sym=18 wins; BID>18 craters day 0 (-30k); ASK clamped by POST_MAX | (v22 sweep) |
| **TOD-conditional vk_dn** (early/late session split) | best +27 noise; sym across session is best | (v22 sweep) |
| **layer-2 passive quotes** (deeper bid+ask layer in addition to L1) | catastrophic at any L2 size > 0; day 1 craters from 55k → 25k | (v22 sweep) |
| **pos-conditional VK_UP** (vk_up_long vs vk_up_short) | sym vk_up=0.78 wins; only 1 cell tied baseline | (v23 sweep) |
| **mag-thresh VK_UP for SHORT side** (HIGH when pos<-THR) | best +27 noise; sym wins | (v24 sweep) |
| **mag-thresh PE** (deeper PE at extreme \|pos\|) | every variant ≤ baseline | (v24 sweep) |
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
| `h_only_v24.py` | **SHIP** — 196,853 (+24,963 vs v8, +14.52%) |
| `h_only_v23.py` | prev ship — 196,485 |
| `h_only_v22.py` | older — 194,996 |
| `h_only_v21.py` | older — 192,571 |
| `h_only_v20.py` | older — 191,751 |
| `h_only_v19.py` | older — 190,880 |
| `h_only_v17.py` | older — 181,903 |
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
| `HYDROGEL_ONLY_RECIPE_v19.md` | v19 recipe |
| `HYDROGEL_ONLY_RECIPE_v20.md` | v20 recipe |
| `HYDROGEL_ONLY_RECIPE_v21.md` | v21 recipe |
| `HYDROGEL_ONLY_RECIPE_v22.md` | v22 recipe |
| `HYDROGEL_ONLY_RECIPE_v23.md` | v23 recipe |
| `HYDROGEL_ONLY_RECIPE_v24.md` | this file |

## Reproduction

```bash
# Final ship
python3 tools/jmerle_backtester.py traders/round3/h_only_v24.py 3 --merge-pnl --no-out
# Expected: total 196,853  (69,480 / 57,488 / 69,885)

# Verify forbidden-imports check
grep -nE "^import os|^from os|import subprocess|exec\(|eval\(" traders/round3/h_only_v24.py
# Expected: empty
```
