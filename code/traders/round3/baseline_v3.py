"""
Round 3 baseline v3 — 2026-04-24.

Changes from v2:

(1) HYDROGEL_PACK peak parameters from 3-day grid search:
    anchor=9990, CLIP=30, inv_skew=0.015, size=20, penny_edge=1.5,
    passive_offset=8, take_edge=0. All 3 days positive. 3-day total ≈
    149k in local backtest.

(2) VELVETFRUIT_EXTRACT take-only removed. It is -EV on every knob
    we tried (take edge 0.5→3, clip 3→15). On this tight spread the
    underlying is better left as a **reference for voucher fair
    values** only. Passive MM was also -EV in v1.

(3) NEW: synthetic-underlying MM on VEV_4000 and VEV_4500. Basis
    std < 1 tick to VELVETFRUIT. Their L1 spreads (21 and 16) give
    room to quote bb+1/ba-1 with ~9.5 ticks of theoretical edge per
    round-trip.

    Fair(VEV_K) = VELVETFRUIT_mid - K for K in {4000, 4500}. Inventory
    skew applied. Position limit 300 each → total delta-1 capacity is
    300+300 = 600 (vs 200 on the underlying), without ever touching
    the underlying book.

(4) Vouchers 5000-6500 still untouched. That's the next layer.
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

    # HYDROGEL_PACK peak params (3-day grid, plateau center)
    H_ANCHOR = 9990.0
    H_CLIP = 30.0
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 1.0
    H_PENNY_EDGE = 1.5
    H_INV_SKEW = 0.015
    H_MAX_POST_SIZE = 20
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8

    # VEV_4000 / VEV_4500 synthetic-underlying MM
    VEV_SYNTH_STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500}
    VS_TAKE_EDGE = 1.0              # take when mispriced by >=1 tick vs synthetic fair
    VS_PENNY_EDGE = 2.0             # quote offset from fair
    VS_INV_SKEW = 0.01              # skew per unit pos (limit 300 → scale down)
    VS_MAX_POST_SIZE = 30
    VS_WIDE_SPREAD = 8

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

    def _cap_size(self, max_size: int, pos: int, side: str, cap: int, limit: int) -> int:
        if cap <= 0:
            return 0
        ratio = 1.0 - min(0.7, abs(pos) / limit)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    # ---------- HYDROGEL_PACK ----------
    def _trade_hydrogel(self, od: OrderDepth, pos: int) -> List[Order]:
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

        skew = fair - self.H_INV_SKEW * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
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
            if bid_size > 0:
                orders.append(Order(prod, bid_price, bid_size))
            if ask_size > 0:
                orders.append(Order(prod, ask_price, -ask_size))
        return orders

    # ---------- VEV_4000 / VEV_4500 synthetic-underlying MM ----------
    def _trade_synth_voucher(self, name: str, K: int, od: OrderDepth,
                             pos: int, under_mid: float) -> List[Order]:
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]

        # Fair for deep-ITM call ≈ S - K (intrinsic). Time value ~0.
        fair = under_mid - K
        working = pos
        orders: List[Order] = []

        # TAKE — if market is mispriced vs synthetic fair
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - self.VS_INV_SKEW * working
            if ap <= skew - self.VS_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(name, ap, q)); working += q
            elif working < 0 and ap <= skew:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(name, ap, q)); working += q

        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair - self.VS_INV_SKEW * working
            if bp >= skew + self.VS_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q
            elif working > 0 and bp >= skew:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q

        # MAKE inside-touch when spread is wide
        skew = fair - self.VS_INV_SKEW * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.VS_MAX_POST_SIZE, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(self.VS_MAX_POST_SIZE, working, "sell", sell_cap, limit)

        if spread >= self.VS_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - self.VS_PENNY_EDGE))
            ask_price = max(ba - 1, math.ceil(skew + self.VS_PENNY_EDGE))
            # Safety: never post through fair, never cross the touch
            bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
            ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)
            if bid_price < ask_price:
                if bid_size > 0:
                    orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0:
                    orders.append(Order(name, ask_price, -ask_size))
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

        # HYDROGEL_PACK
        if "HYDROGEL_PACK" in state.order_depths:
            result["HYDROGEL_PACK"] = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0),
            )

        # Synthetic-underlying MM needs the underlying mid as fair anchor.
        u_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if u_od is not None:
            u_book = self._book(u_od)
            if u_book is not None:
                u_mid = u_book["touch_mid"]
                for name, K in self.VEV_SYNTH_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is not None:
                        result[name] = self._trade_synth_voucher(
                            name, K, od, pos.get(name, 0), u_mid,
                        )

        return result, 0, json.dumps(saved)
