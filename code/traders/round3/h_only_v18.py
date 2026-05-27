"""HYDROGEL-only v18 — NEGATIVE RESULT: regime-aware anchor shift fails (2026-04-25).

ATTEMPT: regime-aware anchor shift to fix day-1 underperformance in v16.

HYPOTHESIS:
  v16 baseline 181,675  (day 0 63,544 / day 1 53,884 / day 2 64,247).
  Day 1 underperforms by ~10k vs days 0/2. Day 1 mid wanders to 10079,
  far above H_ANCHOR=9983 +H_CLIP=33 cap, so fair gets pinned at
  9983+33=10016 while true touch is much higher. ASK sits below true
  touch on day 1 -> adverse fills.

REGIME DETECTOR (probe_regime_detectors.py): EMA window 2000 of
  (touch_mid - ANCHOR) has the cleanest cross-day discriminator:
    day0 max |EMA|  18.6 (never crosses 20)
    day1 max |EMA|  36.4 (~55% of ticks > 20)
    day2 max |EMA|  28.8 (~31% > 20, never > 30)
  Window=2000 contrast d1/max(d0,d2) = 1.35.

CHANGE: ANCHOR_SHIFT_ALPHA = 1/window  (slow EMA of touch_mid - anchor)
        eff_anchor = H_ANCHOR + slow_ema_dev
        clip still applied around eff_anchor.

SWEEP RESULT (per-day: d0 / d1 / d2):
  alpha=0     (window=inf, = v16): 63,544 / 53,884 / 64,247  total 181,675
  alpha=5e-5  (win 20000)         : 63,231 / 52,379 / 60,210  total 175,820  (-5,855)
  alpha=1e-4  (win 10000)         : 60,801 / 49,356 / 58,749  total 168,906 (-12,769)
  alpha=1.5e-4 (win  6667)        : 60,755 / 45,725 / 57,099  total 163,579 (-18,096)
  alpha=2e-4  (win  5000)         : 60,419 / 43,123 / 52,988  total 156,530 (-25,145)
  alpha=3e-4  (win  3333)         : 55,786 / 41,895 / 46,411  total 144,092 (-37,583)
  alpha=5e-4  (win  2000)         : 53,115 / 41,468 / 41,406  total 135,989 (-45,686)
  alpha=1e-3  (win  1000)         : 48,176 / 44,691 / 31,734  total 124,601 (-57,074)

FINDING: every nonzero ANCHOR_SHIFT_ALPHA strictly REGRESSES every day,
  including day 1 itself (the day we were trying to help). Day 1 PnL
  drops monotonically from 53,884 -> 52,379 -> 49,356 ... -> 41,468.

WHY (post-hoc):
  HYDROGEL is a strong mean-reverter. The strategy makes money by
  fading deviations from a STATIC anchor (combined with AR1 lean
  and inv-skew). Letting the anchor drift WITH the price kills the
  mean-reversion edge: when mid wanders to 9983+50, a fair anchored
  there bets that price stays at 50, so we accumulate inventory at
  the wandered level and lose when it eventually reverts.

  The day-1 pinning is not the bug -- it's the FEATURE. Day 1's
  drifting mid eventually returns toward the band (range ends at
  9979 from a 10079 peak), and the static anchor harvests that
  reversion. Anchor-shifting cancels the reversion harvest.

  The original observation (mid > anchor+33 on 25.5% of day-1 ticks)
  is correct but the implication (we should track the price) is wrong.
  The strategy is already correctly designed for it: when mid is far,
  inv-skew limits exposure, and the static anchor lets the eventual
  reversion be profitable.

DECISION: keep v16 as the ship. v18 stays here as a negative-result
  artifact. ANCHOR_SHIFT_ALPHA = 0.0 below makes this file behaviorally
  identical to v16 (do NOT ship this file unless alpha=0 confirmed).

Compute waste avoided: do NOT try
  - dynamic CLIP expansion based on slow EMA (CLIP_VOL_K cliff at 0.8
    on day 2 already known; expanding only on day 1 still costs day 0/2)
  - block-100/500 drift gating (already adjacent to anchor-shift; same
    problem -- shifting the anchor against mean-reversion edge)
  - threshold-gated shift "only when |EMA| > 30" (alpha=5e-5 already
    rarely fires in the targeted regime and still loses 5.8k)
"""
from typing import Dict, List
import math
import json
from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {"HYDROGEL_PACK": 200}

    H_ANCHOR = 9983.0
    H_CLIP = 33.0
    H_TAKE_EDGE = 0.5
    H_REDUCE_EDGE = 0.0
    H_PENNY_EDGE = 3.0
    H_INV_SKEW = 0.014
    H_MAX_POST_SIZE = 18
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8

    AR1_BETA = 0.17
    TYPICAL_SPREAD = 16
    CLIP_VOL_K = 0.76
    DMID_HISTORY = 150

    # 0 = identical to v16. ANY positive value regresses all days; see header.
    ANCHOR_SHIFT_ALPHA = 0.0

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
        if book["spread"] < self.TYPICAL_SPREAD:
            tot = book["bv"] + book["av"]
            if tot > 0:
                return (book["ba"] * book["bv"] + book["bb"] * book["av"]) / tot
        return book["touch_mid"]

    def _cap_size(self, max_size, pos, side, cap, limit):
        if cap <= 0: return 0
        ratio = 1.0 - min(0.7, abs(pos) / limit)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    def _trade_hydrogel(self, od, pos, last_dmid, dmid_hist, anchor_shift):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]; tm = book["touch_mid"]

        if self.CLIP_VOL_K > 0 and len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mean_d = sum(dmid_hist) / n
            std_d = math.sqrt(sum((d - mean_d) ** 2 for d in dmid_hist) / n)
            clip = self.H_CLIP + self.CLIP_VOL_K * std_d
        else:
            clip = self.H_CLIP

        eff_anchor = self.H_ANCHOR + anchor_shift  # alpha=0 -> shift=0 -> = H_ANCHOR

        fair_input = self._fair_input(book)
        fair_adj = max(-clip, min(clip, fair_input - eff_anchor))
        fair = eff_anchor + fair_adj
        if last_dmid is not None:
            fair -= self.AR1_BETA * last_dmid

        working = pos
        orders: List[Order] = []

        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0: break
            skew = fair - self.H_INV_SKEW * working
            if ap <= skew - self.H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0: orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0: orders.append(Order(prod, ap, q)); working += q
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0: break
            skew = fair - self.H_INV_SKEW * working
            if bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q

        skew = fair - self.H_INV_SKEW * working
        buy_cap = max(0, limit - working); sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.H_MAX_POST_SIZE, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(self.H_MAX_POST_SIZE, working, "sell", sell_cap, limit)

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
        anchor_shift = saved.get("anchor_shift_H", 0.0)

        result: Dict[str, List[Order]] = {}
        new_mid = None
        if "HYDROGEL_PACK" in state.order_depths:
            orders, tm = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                state.position.get("HYDROGEL_PACK", 0),
                last_dmid, dmid_hist, anchor_shift,
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
            if self.ANCHOR_SHIFT_ALPHA > 0:
                a = self.ANCHOR_SHIFT_ALPHA
                anchor_shift = (1 - a) * anchor_shift + a * (new_mid - self.H_ANCHOR)
            saved["last_mid_H"] = new_mid
            saved["dmid_hist_H"] = dmid_hist
            saved["anchor_shift_H"] = anchor_shift
        return result, 0, json.dumps(saved)
