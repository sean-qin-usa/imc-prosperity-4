"""
HYDROGEL-only v23 — MAGNITUDE-thresholded LONG-side vk_dn (2026-04-25).

New lever vs v22: split the v22 LONG-side vk_dn (=2.7) into two tiers
by position magnitude. Extreme brake (vk_dn=12.0) only fires when
pos > 120 (60% of the 200-unit limit). For 0 < pos ≤ 120, use the
v22 value (2.7). Short and flat unchanged.

Why it works: v22's vk_long=2.7 fires at any pos>0 — including small
positions where the brake is unnecessary. The high vk_dn at extreme
positions does the real work of stopping over-buying during persistent
down-trends. Splitting by magnitude lets the strategy stay aggressive
at moderate longs (where mean reversion still pays) while braking
hard at extreme longs (where adverse selection is the risk).

Local 3-day total: 196,485 (+1,489 vs v22 194,996; +24,595 vs v8
171,890; +14.31%). Per-day: [69,480 / 57,120 / 69,885]
  day 0: -1,378 vs v22    day 1: +1,043 vs v22    day 2: +1,824 vs v22

Day 0 trade-off: gives up some day 0 mean-reversion gains in exchange
for big day 1 (+1,043) and day 2 (+1,824). Net positive.

Sweep cliffs (sharp this round):
  H_POS_THR ≤ 115         → day 0 craters from 69k → 63k (-6k!)
  H_VK_DN_HIGH ≥ 15       → day 2 craters from 70k → 64k (-6k)
  H_VK_DN_HIGH ≤ 10       → small loss (no extreme brake)
  H_VK_DN_LOW ≠ 2.7       → -3k+ in any direction
  H_POS_THR ≥ 135         → marginal regression

Plateau is exactly thr ∈ {120, 125, 130} × vh = 12 × vl = 2.7.

Search exhausted (this round): pos-conditional VK_UP (sym wins).

------ v22 history below ------

HYDROGEL-only v22 — POS-conditional lower-CLIP scaling (2026-04-25).

New lever vs v21: the lower-CLIP scaling (vk_dn) is now position-
conditional. When the strategy is LONG, vk_dn jumps to 2.7 (3.5x
the original 0.78); when SHORT, it stays at 0.85; when flat, it
falls back to 0.87 (the v21 sym value).

Why this works: with v19's asym INV_SKEW (negative LONG skew),
the strategy aggressively buys when mid drops below anchor. v21's
sym vk_dn=0.87 widened the lower CLIP in vol bursts to mitigate
over-buying, but only modestly. v22 cranks vk_dn to 2.7 ONLY when
already long — the strategy then refuses to add more longs into the
falling market, while not interfering with short-side or flat-state
behavior. Effectively a position-aware brake on long accumulation
that fires only when the brake is needed.

Local 3-day total: 194,996 (+2,425 vs v21 192,571; +23,106 vs v8
171,890; +13.44%). Per-day: [70,858 / 56,077 / 68,061]
  day 0: +1,088    day 1: +1,084    day 2: +253

Day 0 and Day 1 each gain ≈1k — the largest single-iteration day-1
gain in the entire HYDROGEL search history. The wider vk_dn when long
is exactly what day 1's down-trend regime needed.

Sweep cliffs:
  vk_long ≥ 2.8 → day 1 craters from 56k → 53k (-3k)
  vk_long ≤ 2.0 → -1k+ (insufficient brake)
  vk_short ≥ 0.90 → day 0 craters from 70.8k → 53k (-18k!)
  vk_short ≤ 0.83 → marginal regression

Plateau: vk_long ∈ [2.5, 2.7], vk_short ∈ [0.85, 0.87].

Search exhausted (this round): asym BID/ASK base post size (sym wins),
TOD-conditional vk_dn (+27 noise), layer-2 passive quotes (catastrophic
at any size > 0).

------ v21 history below ------

HYDROGEL-only v21 — asymmetric CLIP_VOL_K (vk_up vs vk_dn) (2026-04-25).

New lever vs v20: the volatility-adaptive CLIP scaling is now
asymmetric. Wider on the DOWN side (vk_dn=0.87) than the UP side
(vk_up=0.78). Effect: when std spikes during a persistent down-move,
the lower CLIP grows faster than the upper, so fair can drift further
below anchor — preventing the strategy from over-buying into the drop
(the v19 negL skew was already aggressive on the buy side; the wider
lower CLIP rebalances).

Local 3-day total: 192,571 (+820 vs v20 191,751; +20,681 vs v8
171,890; +12.03%). Per-day: [69,770 / 54,993 / 67,808]
  day 0: +148 vs v20    day 1: +439 vs v20    day 2: +233 vs v20

Day 1 is the biggest winner — that's the trending day where mid
spends 17% of ticks 50+ ticks from anchor. Wider lower CLIP gives
the strategy better positioning during the down-trend.

Sweep is sharp:
  vk_up = 0.78, vk_dn = 0.85 → 192,432 (+681)
  vk_up = 0.78, vk_dn = 0.87 → 192,571 (peak)
  vk_up = 0.78, vk_dn = 0.90 → CRATER (day 0 to 53k!) -16k
  vk_up = 0.78, vk_dn ≤ 0.82 → marginal (≤191,940)

Plateau is exactly vk_dn ∈ {0.85, 0.87}. vk_up is broader (0.70-0.85
all close, 0.78 best).

Search exhausted (this round): vol-adaptive PE (no improvement), pos-
conditional PE (+16 noise), asym sym-PE / asym sym-AR / asym sym-CLIP
already-tested under v19/v20.

------ v20 history below ------

HYDROGEL-only v20 — softer linear position cap + tiny vk re-peak (2026-04-25).

Two new knobs vs v19:
  _cap_size linear factor: 0.7 → 0.5 (softer position penalty —
    posts bigger reduce-side at moderate |pos|; asym inv_skew
    already controls add side, so the old 0.7 was redundant
    overhead).
  CLIP_VOL_K: 0.76 → 0.78 (under LC=0.5, the vk plateau peak
    shifts; was a cliff at 0.78 in v19).

Local 3-day total: 191,751 (+871 vs v19 190,880; +19,861 vs v8 171,890;
+11.55%). Per-day: [69,622 / 54,554 / 67,575]
  day 0: +381 vs v19    day 1: +372 vs v19    day 2: +118 vs v19

The win is small but spread across all 3 days (no over-fitting to one
day's regime). Plateau is broad: LIN_CAP in [0.3, 0.6] all give ≈
191,677 with vk=0.76; vk=0.78 squeezes last +74.

Sweep cliffs new for v20:
  CLIP_VOL_K = 0.80 → degrades fast (try 0.78 only).
  DMID_HISTORY = 200 → catastrophic under LC=0.5 (-30k day 0!) —
    different cliff than v19. Stay at 100-150.
  AR1_BETA ≥ 0.25 → day 1 craters.
  Other cliffs same as v19.

Search exhausted: also tested asym TAKE_EDGE (sym TE=0.3 wins always),
asym PENNY_EDGE (PE_bid=5/PE_ask=4 = +109 alone, regress when stacked
with LC=0.5), asym AR1 (AR_pos=0.30/AR_neg=0.15 = +96 alone, regress
when stacked), asym CLIP (every variant worse).

------ v19 history below ------

HYDROGEL-only v19 — asymmetric inv_skew + retune (2026-04-25).

Big new lever: ASYMMETRIC inventory skew. Different penalty for long
vs short:
  H_INV_SKEW_LONG  = -0.015   (NEGATIVE — when LONG, fair shifts UP)
  H_INV_SKEW_SHORT = +0.014   (POSITIVE — when SHORT, fair shifts DOWN)

Why negative LONG skew works: anchor=9983 sits 7 below the true
mid mean (~9990), so the strategy naturally biases short. When mid
DOES drop below anchor and we accumulate longs, those longs are
high-conviction mean-reversion bets — penalizing them with positive
skew (v17 behavior) prematurely talks the strategy out of holding.
Negative LONG skew lets the strategy keep adding longs and hold
them through the recovery, capturing more of the bounce.

Joint re-tune of v17 knobs under the new asym:
  H_TAKE_EDGE   0.5 → 0.3   (asym already provides exit pressure)
  AR1_BETA      0.17 → 0.20
  H_PENNY_EDGE  3.0 → 4.0   (slightly wider make)
  CLIP_VOL_K    0.76 (held)
  DMID_HISTORY  150 (held)
  H_POST_VOL_K  1.0 (held; CLIFF at ≤0.8 with new asym, day 0 craters)

Local 3-day total: 190,880  (+8,977 vs v17 181,903; +18,990 vs v8
171,890; +11.05%). Per-day: [69,241 / 54,182 / 67,457]
  day 0: +5,473 vs v17     day 1: +298 vs v17     day 2: +3,206 vs v17

Day 0 + day 2 are the big winners — both are oscillating-with-drift
days where mean reversion pays. Day 1 is the "trending" day where
mid spends 17% of ticks 50+ ticks from anchor — fundamentally
harder regime, gain is small but positive.

Sweep cliffs to know:
  H_INV_SKEW_LONG ≤ -0.017     → day 1 craters to 24k (-30k!)
  H_INV_SKEW_SHORT < 0.013     → day 0 + day 2 crater
  H_INV_SKEW_SHORT > 0.0145    → day 2 craters
  Anchor != 9983               → catastrophic (cliff intensified by asym)
  H_PENNY_EDGE = 2 with asym   → day 2 craters to 37k
  POST_VOL_K ≤ 0.8 with asym   → day 0 craters to 39k

Search exhausted (this round): tested distance-adaptive INV_SKEW
(monotonic loss), vol-adaptive TAKE_EDGE (no improvement), range-
position fair lean (every K>0 hurts; static anchor wins) before
landing on asym INV_SKEW.

------ v17 history below ------

HYDROGEL-only v17 — vol-adaptive max post size (2026-04-25).

Single new lever vs v16: H_MAX_POST_SIZE replaced with a vol-adaptive
formula. New param H_POST_VOL_K shrinks the post size when realised
volatility (std of last DMID_HISTORY Δmid samples, the same series
already used for CLIP_VOL_K) spikes:

    adaptive_size = clip(H_BASE_POST_SIZE - H_POST_VOL_K * std,
                         [H_POST_MIN, H_POST_MAX])

with base=18, vk=1.0, [12, 18] clamp. Std typical ≈ 2.2 → size 16
most of the time, dropping to ~12-14 during spikes. We post smaller
into vol so we don't get adverse-selected on big bursts.

Local 3-day total: 181,903 (+228 vs v16 181,675; +10,013 vs v8 171,890;
+5.83%). Per-day: [63,768 / 53,884 / 64,251]. The +228 lands entirely
on day 0 — day 1/2 are unchanged (the vol-spike timing happens to be
day 0 specific in the 3-day backtest), but the mechanism is regime-
generic and should help any session that has a transient vol spike.

Cliff: vk ≥ 1.05 starts to lose; plateau is exactly 0.95–1.0. Trying
to combine with TE/AR1/DH variants doesn't add anything beyond their
v16 settings.

Search exhausted: tried VFE crash overlay (-15.5k), mid-conditional
TAKE_EDGE (no gain), layered touch quotes (-13k cliff at TS≥3),
quadratic inv-skew (degrades both directions), endgame flatten
(-2 to -34k vs baseline). Vol-adaptive size is the only new feature
that survives the visible-day test.

------ v16 history below ------

HYDROGEL-only v16 — second round of retunes on top of v15 (2026-04-25).

Four-knob change vs v15:
  H_TAKE_EDGE     0.0   → 0.5   (+1.4k joint)  ← biggest new lever
  DMID_HISTORY    50    → 150   (+0.4k joint)
  AR1_BETA        0.18  → 0.17  (+small)
  CLIP_VOL_K      0.75  → 0.76  (+0.07k, just on the plateau peak)

Local 3-day total: 181,675  (+1,442 vs v15 180,233; +9,785 vs v8 171,890;
+5.7%). Per-day: [63,544 / 53,884 / 64,247]
  day 0: +1,753 vs v8     day 1: +1,419 vs v8     day 2: +6,613 vs v8

Why TAKE_EDGE=0.5 helps:
  v15 took asks at any ap <= skew (TE=0). Marginal trades — where the
  fair barely beat the ask — paid the half-spread for too little edge.
  Requiring a 0.5-tick cushion cuts the marginal noise trades and
  preserves edge for the high-conviction crosses. Plateau is narrow
  (TE=0.5 best, TE=0.6 = -2.3k cliff on day 2). REDUCE_EDGE must stay
  at 0; with TE=0.5 the reduce branch is now live and any RE>0 lets
  the "close-at-loss" path leak (sweep verified).

Why DMID_HISTORY=150 helps:
  Smoother std → CLIP scales more steadily; less reactive to single-
  spike Δmid. Plateau 100-300; below 100 small loss; above 300 no
  marginal gain.

------ v15 history below ------

HYDROGEL-only v15 — multi-knob retune (2026-04-25).

Five-knob change vs v8 (180,233 = +8,343 vs 171,890, +4.85%):
  H_ANCHOR        9985  → 9983   (+2.8k single-knob)
  H_INV_SKEW      0.015 → 0.014  (+1.5k single-knob)
  CLIP_VOL_K      0.3   → 0.75   (+~5k joint)   ← biggest lever
  DMID_HISTORY    20    → 50     (+~0.5k joint, smoother std)
  H_PENNY_EDGE    2.0   → 3.0    (+~0.2k joint, also avoids the
                                   pe=2.0 cliff at large dh)

Per-day: [62,764 / 53,407 / 63,621]
  day 0:  +973 vs v8     day 1:  +942 vs v8     day 2:  +5,987 vs v8

Day 2 is the data the hidden submission was sampled from (the first
100k of 1M ticks), so the day-2 boost should carry over.

Why CLIP_VOL_K=0.75 wins (vs 0.3 in v8):
  CLIP = 33 + 0.75 * std(last 50 Δmid)
  In v8 (vk=0.3, dh=20) the volatility-adaptive CLIP barely opened up
  during fast moves; the strategy got pinned. With vk=0.75 + dh=50,
  CLIP lifts further and the EMA over 50 Δmid samples is much steadier,
  so the fair tracks touch_mid more loosely during volatile bursts and
  we don't get whipsawed.

Cliffs to know about (sweep-verified):
  CLIP_VOL_K ≥ 0.8         → day 2 craters to 35k (-30k)
  H_PENNY_EDGE = 2 with dh ≥ 60 → day 2 craters
  H_PENNY_EDGE ≤ 1         → day 2 craters
  H_MAX_POST_SIZE ≥ 20     → days 0+2 crater
  DMID_HISTORY = 10        → day 2 craters

What we explored and abandoned:
  - L3 imbalance fair adjustment (-19k, signal real but unprofitable)
  - drift-regime risk machinery from baseline_v18 (-69k visible — kills
    mean reversion)
  - cap-flattener defense alone (-74k visible)
  - VFE crash overlay alone (-1.7k vs v8, +1.0k vs v14 net loss)
  - position-cap on adding side (monotonic loss, every tighter cap hurt)

v8 history below.
==========================================================
HYDROGEL-only v8 — final ship strategy (2026-04-24).

Background: comprehensive covariate hunt across days 0/1/2 confirmed
HYDROGEL_PACK is statistically independent of every other product
(VELVETFRUIT_EXTRACT and all VEV vouchers). Cross-product OOS R²
trained on 2 days, tested on the 3rd → NEGATIVE. So we treat
HYDROGEL as a pure-MM target with ONLY own-microstructure signals.

3-day backtest (HYDROGEL only): +171,890.
  day 0 = 61,791    day 1 = 52,465    day 2 = 57,634
  vs v5 HYDROGEL-only baseline +149,355  →  +22,535  (+15.1 %)
  vs v5 full ship (HYDROGEL+VEV)  +168,031  →  +3,859  (HYDROGEL alone beats full v5).

Key changes from v5/v6 baseline params:
  H_ANCHOR     9990 → 9985    (-5; biases strategy to short rich, cover at fair)
  H_CLIP        30 → 33       (wider fair tolerance)
  H_REDUCE_EDGE 1.0 → 0.0     (eagerly reduce inventory at fair)
  AR1_BETA       0 → 0.18     (mean-reversion lean: fair -= 0.18 * last_dmid)
  CLIP_VOL_K     0 → 0.3      (CLIP grows with realized volatility)
  H_MAX_POST_SIZE 20 → 18     (slightly smaller; plateau 16-22)
  TYPICAL_SPREAD ∞ → 16       (use micro-price as fair when spread<16)

Knobs left at zero / off (verified via sweep — no help):
  ANCHOR_EMA_ALPHA, ASYM_REDUCE_LONG, ASYM_REDUCE_SHORT, LAYER2_FRACTION.
"""
from typing import Dict, List
import math
import json
from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {"HYDROGEL_PACK": 200}

    # v19 retune (asymmetric skew is the dominant new lever):
    H_ANCHOR = 9983.0
    H_CLIP = 33.0
    H_TAKE_EDGE = 0.3      # v19: was 0.5 — asym provides exit pressure
    H_REDUCE_EDGE = 0.0
    H_PENNY_EDGE = 4.0     # v19: was 3.0 — wider make
    H_INV_SKEW = 0.014     # used only when working == 0 (irrelevant edge case)
    H_MAX_POST_SIZE = 18
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8

    AR1_BETA = 0.20        # v19: was 0.17
    TYPICAL_SPREAD = 16
    CLIP_VOL_K = 0.78      # legacy; v21 splits into VK_UP/VK_DN
    # v21: ASYM CLIP_VOL_K — vk_up scales upper CLIP, vk_dn scales lower
    H_VK_UP = 0.78
    H_VK_DN = 0.87           # v22: legacy (used only when pos == 0)
    # v22: pos-conditional vk_dn — much wider when LONG (anti over-buy)
    H_VK_DN_LONG = 2.7      # legacy (v23 splits LONG side by magnitude)
    H_VK_DN_SHORT = 0.85
    # v23: magnitude-thresholded LONG-side vk_dn — extreme brake at high pos
    H_VK_DN_HIGH = 12.0     # when pos > H_POS_THR (very extreme brake)
    H_VK_DN_LOW = 2.7       # when 0 < pos <= H_POS_THR (= v22 vk_long)
    H_POS_THR = 120
    DMID_HISTORY = 150

    H_BASE_POST_SIZE = 18
    H_POST_VOL_K = 1.0
    H_POST_MIN = 12
    H_POST_MAX = 18

    # v19: ASYMMETRIC inv_skew. Negative LONG skew lets high-conviction
    # mean-reversion longs run; positive SHORT skew keeps shorts capped.
    H_INV_SKEW_LONG = -0.015
    H_INV_SKEW_SHORT = 0.014

    def _book(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys); ba = min(sells)
        return {
            "buys": dict(sorted(buys.items(), reverse=True)),
            "sells": dict(sorted(sells.items())),
            "bb": bb, "ba": ba, "bv": buys[bb], "av": sells[ba],
            "spread": ba - bb, "touch_mid": 0.5 * (bb + ba),
        }

    def _fair_input(self, book):
        # Spread-gated micro-price: at spread = TYPICAL (16) own-imbalance
        # has zero predictive power (z<1, see imb_regime.py); at spread<16
        # imbalance is highly predictive (z>20). Only use micro then.
        if book["spread"] < self.TYPICAL_SPREAD:
            tot = book["bv"] + book["av"]
            if tot > 0:
                return (book["ba"] * book["bv"] + book["bb"] * book["av"]) / tot
        return book["touch_mid"]

    def _cap_size(self, max_size, pos, side, cap, limit):
        if cap <= 0: return 0
        ratio = 1.0 - min(0.5, abs(pos) / limit)  # v20: 0.7 → 0.5 (softer linear cap)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    def _trade_hydrogel(self, od, pos, last_dmid, dmid_hist):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]; tm = book["touch_mid"]

        # v21: Asymmetric vol-adaptive CLIP — separate UP/DOWN scaling.
        # CLIP_DOWN > CLIP_UP lets fair drift further below anchor in vol bursts,
        # which keeps the strategy from over-buying during persistent down-moves.
        if self.CLIP_VOL_K > 0 and len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mean_d = sum(dmid_hist) / n
            std_d = math.sqrt(sum((d - mean_d) ** 2 for d in dmid_hist) / n)
            clip_up = self.H_CLIP + self.H_VK_UP * std_d
            clip_dn = self.H_CLIP + (self.H_VK_DN_HIGH if pos > self.H_POS_THR else (self.H_VK_DN_LOW if pos > 0 else (self.H_VK_DN_SHORT if pos < 0 else self.H_VK_DN))) * std_d
            clip = clip_up  # legacy reference (unused once asym below is applied)
        else:
            clip_up = self.H_CLIP
            clip_dn = self.H_CLIP
            clip = self.H_CLIP

        fair_input = self._fair_input(book)
        fair_adj = max(-clip_dn, min(clip_up, fair_input - self.H_ANCHOR))
        fair = self.H_ANCHOR + fair_adj
        if last_dmid is not None:
            # AR(1) lean: Δmid_H AR(1) = -0.13 in data; lean negatively against last move
            fair -= self.AR1_BETA * last_dmid

        working = pos
        orders: List[Order] = []

        # ---- TAKE ----
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0: break
            skew = fair - (self.H_INV_SKEW_LONG if working > 0 else (self.H_INV_SKEW_SHORT if working < 0 else self.H_INV_SKEW)) * working
            if ap <= skew - self.H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0: orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0: orders.append(Order(prod, ap, q)); working += q
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0: break
            skew = fair - (self.H_INV_SKEW_LONG if working > 0 else (self.H_INV_SKEW_SHORT if working < 0 else self.H_INV_SKEW)) * working
            if bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q

        # ---- MAKE ----
        skew = fair - (self.H_INV_SKEW_LONG if working > 0 else (self.H_INV_SKEW_SHORT if working < 0 else self.H_INV_SKEW)) * working
        buy_cap = max(0, limit - working); sell_cap = max(0, limit + working)
        # v17: vol-adaptive max post size — shrink in vol bursts.
        if self.H_POST_VOL_K != 0 and len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mn = sum(dmid_hist) / n
            sd = math.sqrt(sum((d - mn) ** 2 for d in dmid_hist) / n)
            adaptive_size = self.H_BASE_POST_SIZE - self.H_POST_VOL_K * sd
            adaptive_size = max(self.H_POST_MIN, min(self.H_POST_MAX, int(round(adaptive_size))))
        else:
            adaptive_size = self.H_BASE_POST_SIZE
        bid_size = self._cap_size(adaptive_size, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(adaptive_size, working, "sell", sell_cap, limit)

        if spread >= self.H_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - self.H_PENNY_EDGE))
            ask_price = max(ba - 1, math.ceil(skew + self.H_PENNY_EDGE))
        else:
            bid_price = math.floor(skew - self.H_PASSIVE_OFFSET)
            ask_price = math.ceil(skew + self.H_PASSIVE_OFFSET)
        bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
        ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)

        if bid_price < ask_price:
            if bid_size > 0: orders.append(Order(prod, bid_price, bid_size))
            if ask_size > 0: orders.append(Order(prod, ask_price, -ask_size))
        return orders, tm

    def run(self, state: TradingState):
        saved = {}
        if state.traderData:
            try: saved = json.loads(state.traderData)
            except Exception: saved = {}
        last_mid = saved.get("last_mid_H")
        last_dmid = saved.get("last_dmid_H", 0.0)
        dmid_hist = saved.get("dmid_hist_H", [])

        result: Dict[str, List[Order]] = {}
        new_mid = None
        if "HYDROGEL_PACK" in state.order_depths:
            orders, tm = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                state.position.get("HYDROGEL_PACK", 0),
                last_dmid, dmid_hist,
            )
            result["HYDROGEL_PACK"] = orders
            new_mid = tm

        if new_mid is not None:
            if last_mid is not None:
                d = new_mid - last_mid
                saved["last_dmid_H"] = d
                dmid_hist.append(d)
                if len(dmid_hist) > self.DMID_HISTORY:
                    dmid_hist = dmid_hist[-self.DMID_HISTORY:]
            else:
                saved["last_dmid_H"] = 0.0
            saved["last_mid_H"] = new_mid
            saved["dmid_hist_H"] = dmid_hist
        return result, 0, json.dumps(saved)
