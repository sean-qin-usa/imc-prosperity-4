"""
Round 3 baseline v2 — 2026-04-24.

Rewrites v1 with two fixes learned on backtest:

(1) HYDROGEL_PACK now mirrors the known-good strat_284364 ACO routine
    (fair = anchor + clip(touch_mid - anchor, ±clip); inventory-skewed
    take + inside-touch make with ACO_PENNY_EDGE inside_touch offset).
    Parameter rescale vs ACO (limit 50, std 2.5):
      - limit 200, std 26 → clip 20, skew 0.035, size 60, passive_offset 8

(2) VELVETFRUIT_EXTRACT goes **take-only** for v2 (no passive MM).
    Inside-touch MM on the 5-tick spread bleeds from adverse selection
    (v1: -60k/day). We only cross the book when the touch crosses our
    fair by >= 1 tick (genuine mispricing).

Vouchers still disabled — the v1 isolation test showed HYDROGEL alone
at +21.7k total. v2 target is to improve HYDROGEL (especially day 2) and
not bleed VELVETFRUIT.
"""
from typing import Dict, List, Optional
import math

from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
        "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
        "VEV_6500": 300,
    }

    # HYDROGEL_PACK — ACO-class MR, rescaled for limit 200 / std ~26
    H_ANCHOR = 9990.0
    H_CLIP = 20.0                   # fair_adjust_clip; ACO=2, HYDROGEL std ~26
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 1.0
    H_PENNY_EDGE = 1.5
    H_INV_SKEW = 0.035              # scaled down from ACO 0.06 (limit 200 vs 50)
    H_MAX_POST_SIZE = 60
    H_PASSIVE_OFFSET = 8.0          # scaled 8 vs ACO 3.5 (spread same mode 16)
    H_WIDE_SPREAD = 8
    H_LATE_UNWIND_START = 985_000
    H_LATE_UNWIND_TARGET = 40
    H_LATE_UNWIND_MAX = 20
    H_LATE_UNWIND_EDGE = 1.0

    # VELVETFRUIT_EXTRACT — TAKE-ONLY for v2
    V_ANCHOR = 5248.0               # slow EMA feed; seeded with mean
    V_EMA_ALPHA = 0.02
    V_CLIP = 8.0
    V_TAKE_EDGE = 1.0
    V_REDUCE_EDGE = 1.0
    V_INV_SKEW = 0.015

    # ---------- book helpers ----------
    def _book(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys); ba = min(sells)
        return {
            "buys": dict(sorted(buys.items(), reverse=True)),
            "sells": dict(sorted(sells.items())),
            "bb": bb, "ba": ba,
            "bv": buys[bb], "av": sells[ba],
            "spread": ba - bb, "touch_mid": 0.5 * (bb + ba),
        }

    def _cap_size(self, max_size: int, pos: int, side: str, cap: int) -> int:
        """Mirror strat_284364 cap logic: shrink quote as |pos| grows."""
        if cap <= 0:
            return 0
        ratio = 1.0 - min(0.7, abs(pos) / 200.0)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    # ---------- HYDROGEL_PACK (ACO-class) ----------
    def _trade_hydrogel(self, od: OrderDepth, pos: int, ts: int) -> List[Order]:
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]; touch_mid = book["touch_mid"]

        fair_adj = max(-self.H_CLIP, min(self.H_CLIP, touch_mid - self.H_ANCHOR))
        fair = self.H_ANCHOR + fair_adj
        working = pos
        orders: List[Order] = []

        # TAKE asks
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - self.H_INV_SKEW * working
            if ap <= skew - self.H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q

        # TAKE bids
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair - self.H_INV_SKEW * working
            if bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q

        # LATE UNWIND — within last 1.5 % of day ticks
        if ts >= self.H_LATE_UNWIND_START:
            if working > self.H_LATE_UNWIND_TARGET and bb >= math.floor(fair - self.H_LATE_UNWIND_EDGE):
                q = min(self.H_LATE_UNWIND_MAX, working - self.H_LATE_UNWIND_TARGET, book["bv"])
                if q > 0:
                    orders.append(Order(prod, bb, -q)); working -= q
            elif working < -self.H_LATE_UNWIND_TARGET and ba <= math.ceil(fair + self.H_LATE_UNWIND_EDGE):
                q = min(self.H_LATE_UNWIND_MAX, abs(working) - self.H_LATE_UNWIND_TARGET, book["av"])
                if q > 0:
                    orders.append(Order(prod, ba, q)); working += q

        # MAKE inside-touch
        skew = fair - self.H_INV_SKEW * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.H_MAX_POST_SIZE, working, "buy", buy_cap)
        ask_size = self._cap_size(self.H_MAX_POST_SIZE, working, "sell", sell_cap)

        if spread >= self.H_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - self.H_PENNY_EDGE))
            ask_price = max(ba - 1, math.ceil(skew + self.H_PENNY_EDGE))
        else:
            bid_price = math.floor(skew - self.H_PASSIVE_OFFSET)
            ask_price = math.ceil(skew + self.H_PASSIVE_OFFSET)

        # Safety: never post through fair, never cross touch
        bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
        ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)

        if bid_price < ask_price:
            if bid_size > 0:
                orders.append(Order(prod, bid_price, bid_size))
            if ask_size > 0:
                orders.append(Order(prod, ask_price, -ask_size))
        return orders

    # ---------- VELVETFRUIT_EXTRACT (take-only) ----------
    def _trade_velvet(self, od: OrderDepth, pos: int, saved: Dict) -> List[Order]:
        prod = "VELVETFRUIT_EXTRACT"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        touch_mid = book["touch_mid"]

        # Slow EMA anchor, ±8 clip
        prev = saved.get("v_anchor", self.V_ANCHOR)
        anchor = (1 - self.V_EMA_ALPHA) * prev + self.V_EMA_ALPHA * touch_mid
        saved["v_anchor"] = anchor
        fair_adj = max(-self.V_CLIP, min(self.V_CLIP, touch_mid - anchor))
        fair = anchor + fair_adj
        working = pos
        orders: List[Order] = []

        # TAKE only — no MM on tight 5-spread
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - self.V_INV_SKEW * working
            if ap <= skew - self.V_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + self.V_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q

        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair - self.V_INV_SKEW * working
            if bp >= skew + self.V_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.V_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q
        return orders

    # ---------- dispatch ----------
    def run(self, state: TradingState):
        import json
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        pos = state.position

        if "HYDROGEL_PACK" in state.order_depths:
            result["HYDROGEL_PACK"] = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0), state.timestamp,
            )
        if "VELVETFRUIT_EXTRACT" in state.order_depths:
            result["VELVETFRUIT_EXTRACT"] = self._trade_velvet(
                state.order_depths["VELVETFRUIT_EXTRACT"],
                pos.get("VELVETFRUIT_EXTRACT", 0), saved,
            )

        return result, 0, json.dumps(saved)
