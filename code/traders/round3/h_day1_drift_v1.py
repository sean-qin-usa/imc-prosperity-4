"""HYDROGEL with day-1 drift detection (range-gated CLIP widening).

Hypothesis: Day-1 underperformance (53,884 vs 63k+ on days 0/2) is driven by
a sustained drift regime where the mid spends 40% of ticks outside ±33 of
H_ANCHOR (vs 21%/33% on days 0/2). The classic CLIP=33 + 0.76*std pins
fair to anchor±33 and aggressively fades a drift that doesn't revert
within the strategy's horizon.

Day-1 specific findings (analyze_h_day1.py):
  mid std (full)  : 37.61 (d1) vs 25.33 (d0), 31.62 (d2)
  mid range       : 170 (d1) vs 143 (d0), 160 (d2)
  block100 drift  : +0.687 (d1) vs ~0 elsewhere
  AR(1)           : -0.124 (d1) vs -0.138 (d0), -0.125 (d2)
  bucket 6 PnL d1 : -3,066 (mid jumps 9976→10032)
  bucket 9 PnL d1 : -1,589

Lever: when recent mid RANGE (max-min over last MID_RANGE_HISTORY ticks)
exceeds threshold, widen CLIP_VOL_K. This widening is gated, NOT applied
universally — single-knob CLIP_VOL_K=1.0 has a day-2 cliff of -30k on the
v15 chassis (DMID_HISTORY=50); the v16 chassis (DMID_HISTORY=150) needs
re-verification.

DRIFT_GATE_RANGE = 60: trip when last 200 mid samples span >60 ticks
DRIFT_CLIP_BOOST = 1.0: multiply CLIP_VOL_K by (1+boost) when tripped
                       i.e., 0.76 → 1.52 in drift regime, 0.76 unchanged otherwise

Falls back to v16 exactly (181,675) when no drift is detected.
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

    # New: drift-regime detection
    MID_RANGE_HISTORY = 200      # ticks of touch_mid history
    DRIFT_GATE_RANGE = 60        # range threshold (ticks)
    DRIFT_CLIP_BOOST = 1.0       # extra multiplier on CLIP_VOL_K when tripped

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

    def _trade_hydrogel(self, od, pos, last_dmid, dmid_hist, mid_hist):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]; tm = book["touch_mid"]

        # Standard volatility-adaptive CLIP
        clip_vol_k = self.CLIP_VOL_K

        # Drift-regime gate: widen CLIP_VOL_K when touch_mid range has been
        # large recently (drift detected, not reversion).
        if len(mid_hist) >= self.MID_RANGE_HISTORY // 2:
            lo = min(mid_hist); hi = max(mid_hist)
            if hi - lo > self.DRIFT_GATE_RANGE:
                clip_vol_k *= (1.0 + self.DRIFT_CLIP_BOOST)

        if clip_vol_k > 0 and len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mean_d = sum(dmid_hist) / n
            std_d = math.sqrt(sum((d - mean_d) ** 2 for d in dmid_hist) / n)
            clip = self.H_CLIP + clip_vol_k * std_d
        else:
            clip = self.H_CLIP

        fair_input = self._fair_input(book)
        fair_adj = max(-clip, min(clip, fair_input - self.H_ANCHOR))
        fair = self.H_ANCHOR + fair_adj
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
        mid_hist = saved.get("mid_hist_H", [])

        result: Dict[str, List[Order]] = {}
        new_mid = None
        if "HYDROGEL_PACK" in state.order_depths:
            orders, tm = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                state.position.get("HYDROGEL_PACK", 0),
                last_dmid, dmid_hist, mid_hist,
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
            mid_hist.append(new_mid)
            if len(mid_hist) > self.MID_RANGE_HISTORY:
                mid_hist = mid_hist[-self.MID_RANGE_HISTORY:]
            saved["last_mid_H"] = new_mid
            saved["dmid_hist_H"] = dmid_hist
            saved["mid_hist_H"] = mid_hist
        return result, 0, json.dumps(saved)
