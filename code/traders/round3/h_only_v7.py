"""
HYDROGEL-only v7 — joint optimum from v6 sweep + new lever knobs.

Joint optimum from sweep_combo:  154,656  (sk=0.015, rd=0.0, ar=0.15, sz=20).

New levers added (off by default; sweep them next):
  CLIP_VOL_K       — adaptive CLIP = base + k * rolling_std (0 = off, fixed CLIP)
  ANCHOR_EMA_ALPHA — slow EMA on touch_mid (0 = off, fixed anchor)
  ASYM_REDUCE      — reduce more aggressively on long side vs short (0 = sym)
  LAYER2_FRACTION  — re-tune the layered quote (was 0.5)
  TAKE_FREE_AT_FAIR — take any fill at exactly fair (1 = on)
"""
from typing import Dict, List
import math
import json
from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {"HYDROGEL_PACK": 200}

    H_ANCHOR = 9990.0
    H_CLIP = 30.0
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 0.0          # was 1.0; sweep winner
    H_PENNY_EDGE = 1.5
    H_INV_SKEW = 0.015           # plateau
    H_MAX_POST_SIZE = 20
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8

    AR1_BETA = 0.15              # was 0.13; sweep winner
    TYPICAL_SPREAD = 16
    LAYER2_OFFSET = 3
    LAYER2_FRACTION = 0.0        # disable; sweep showed no help

    # ---- v7 NEW knobs (default = off / no-op)
    CLIP_VOL_K = 0.0             # if > 0, CLIP = H_CLIP + k * rolling_std
    ANCHOR_EMA_ALPHA = 0.0       # if > 0, anchor = (1-α)·anchor + α·touch_mid
    ASYM_REDUCE_LONG = 0.0       # extra reduce_edge added when working > 0 (eager to sell longs)
    ASYM_REDUCE_SHORT = 0.0      # extra reduce_edge added when working < 0
    TAKE_AT_FAIR_FLOOR = 0       # if 1, treat take threshold as < (not <=) so we take at fair

    DMID_HISTORY = 20

    # ---------- helpers ----------
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
        spread = book["spread"]
        if spread < self.TYPICAL_SPREAD:
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

    def _trade_hydrogel(self, od, pos, last_dmid, anchor_state, dmid_hist):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None, anchor_state
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]; tm = book["touch_mid"]

        # adaptive anchor
        if self.ANCHOR_EMA_ALPHA > 0:
            anchor_state = (1 - self.ANCHOR_EMA_ALPHA) * anchor_state + self.ANCHOR_EMA_ALPHA * tm
            anchor = anchor_state
        else:
            anchor = self.H_ANCHOR
            anchor_state = self.H_ANCHOR

        # adaptive CLIP
        if self.CLIP_VOL_K > 0 and len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mean_d = sum(dmid_hist) / n
            var = sum((d - mean_d) ** 2 for d in dmid_hist) / n
            clip = self.H_CLIP + self.CLIP_VOL_K * math.sqrt(var)
        else:
            clip = self.H_CLIP

        fair_input = self._fair_input(book)
        fair_adj = max(-clip, min(clip, fair_input - anchor))
        fair = anchor + fair_adj
        if last_dmid is not None:
            fair -= self.AR1_BETA * last_dmid

        working = pos
        orders: List[Order] = []

        # asymmetric reduce edges
        red_long = self.H_REDUCE_EDGE + self.ASYM_REDUCE_LONG
        red_short = self.H_REDUCE_EDGE + self.ASYM_REDUCE_SHORT

        # ---- TAKE ----
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0: break
            skew = fair - self.H_INV_SKEW * working
            take_thresh = skew - self.H_TAKE_EDGE
            cond = (ap < take_thresh) if self.TAKE_AT_FAIR_FLOOR else (ap <= take_thresh)
            if cond:
                q = min(av, cap)
                if q > 0: orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + red_short:
                q = min(av, cap, abs(working))
                if q > 0: orders.append(Order(prod, ap, q)); working += q
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0: break
            skew = fair - self.H_INV_SKEW * working
            take_thresh = skew + self.H_TAKE_EDGE
            cond = (bp > take_thresh) if self.TAKE_AT_FAIR_FLOOR else (bp >= take_thresh)
            if cond:
                q = min(bv, cap)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - red_long:
                q = min(bv, cap, working)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q

        # ---- MAKE ----
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
            if self.LAYER2_FRACTION > 0 and spread >= self.H_WIDE_SPREAD + self.LAYER2_OFFSET:
                bid2 = bid_price - self.LAYER2_OFFSET
                ask2 = ask_price + self.LAYER2_OFFSET
                bid2_sz = max(0, int(round(bid_size * self.LAYER2_FRACTION)))
                ask2_sz = max(0, int(round(ask_size * self.LAYER2_FRACTION)))
                bid2_sz = min(bid2_sz, max(0, limit - (working + bid_size)))
                ask2_sz = min(ask2_sz, max(0, limit + (working - ask_size)))
                if bid2 < ask2:
                    if bid2_sz > 0: orders.append(Order(prod, bid2, bid2_sz))
                    if ask2_sz > 0: orders.append(Order(prod, ask2, -ask2_sz))

        return orders, tm, anchor_state

    def run(self, state: TradingState):
        saved = {}
        if state.traderData:
            try: saved = json.loads(state.traderData)
            except Exception: saved = {}
        last_mid = saved.get("last_mid_H")
        last_dmid = saved.get("last_dmid_H", 0.0)
        anchor_state = saved.get("anchor_H", self.H_ANCHOR)
        dmid_hist = saved.get("dmid_hist_H", [])

        result: Dict[str, List[Order]] = {}
        new_mid = None
        if "HYDROGEL_PACK" in state.order_depths:
            orders, tm, anchor_state = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                state.position.get("HYDROGEL_PACK", 0),
                last_dmid, anchor_state, dmid_hist,
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
            saved["anchor_H"] = anchor_state
            saved["dmid_hist_H"] = dmid_hist
        return result, 0, json.dumps(saved)
