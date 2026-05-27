"""
Framework E — HFT L1-imbalance scalper. NO trader IDs, NO chassis.

Design principle: at every tick, on every product, look at L1 imbalance
(bv - av) / (bv + av). When imbalance is strong:
  imb > +THR: bid is heavy → take the ask (asks will lift), exit at touch+N
  imb < -THR: ask is heavy → take the bid (bids will collapse), exit at touch+N

Hold for HOLD_TICKS or until imb flips. Cycle continuously across all 12
products. Volume profile: 5-10x baseline trade count.

Bet: micro-structure noise (book imbalance) has a small per-cycle edge that
compounds over thousands of cycles per day. Documented in P3 work but
never built into a standalone strategy.
"""
from typing import Dict, List
import json

from datamodel import Order, OrderDepth, TradingState

LIMITS = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
    "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
    "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
    "VEV_6500": 300,
}


class Trader:
    IMB_THR = 0.4              # |imbalance| above this triggers entry
    IMB_FLATTEN = 0.15         # |imbalance| below this flattens position
    TAKE_QTY = 8               # qty per cycle
    MAX_SLEEVE_POS = 40        # cap directional inventory per product

    def _scalp_one(self, symbol, od, cur_pos, sleeve_pos, ticks_held, ts):
        if od is None or not od.buy_orders or not od.sell_orders:
            return [], sleeve_pos, ticks_held
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        if bb >= ba:
            return [], sleeve_pos, ticks_held
        bv = abs(int(od.buy_orders[bb]))
        av = abs(int(od.sell_orders[ba]))
        tot = bv + av
        if tot <= 0:
            return [], sleeve_pos, ticks_held
        imb = (bv - av) / tot

        orders: List[Order] = []
        limit = LIMITS[symbol]

        # Exit logic — flatten when imb decays
        if sleeve_pos != 0 and abs(imb) < self.IMB_FLATTEN:
            if sleeve_pos > 0:
                q = min(sleeve_pos, bv)
                if q > 0:
                    orders.append(Order(symbol, int(bb), -q))
                    sleeve_pos -= q
            else:
                q = min(-sleeve_pos, av)
                if q > 0:
                    orders.append(Order(symbol, int(ba), q))
                    sleeve_pos += q
            return orders, sleeve_pos, 0

        # Entry logic
        if imb > self.IMB_THR and sleeve_pos < self.MAX_SLEEVE_POS:
            room = self.MAX_SLEEVE_POS - sleeve_pos
            limit_room = limit - cur_pos
            q = min(self.TAKE_QTY, room, limit_room, av)
            if q > 0:
                orders.append(Order(symbol, int(ba), q))
                sleeve_pos += q
                ticks_held = 0
        elif imb < -self.IMB_THR and sleeve_pos > -self.MAX_SLEEVE_POS:
            room = self.MAX_SLEEVE_POS + sleeve_pos
            limit_room = limit + cur_pos
            q = min(self.TAKE_QTY, room, limit_room, bv)
            if q > 0:
                orders.append(Order(symbol, int(bb), -q))
                sleeve_pos -= q
                ticks_held = 0

        return orders, sleeve_pos, ticks_held + 1

    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        pos = state.position

        for symbol in LIMITS:
            od = state.order_depths.get(symbol)
            sleeve_pos = int(saved.get(f"sp_{symbol}", 0))
            ticks_held = int(saved.get(f"th_{symbol}", 0))
            orders, sleeve_pos, ticks_held = self._scalp_one(
                symbol, od, pos.get(symbol, 0), sleeve_pos, ticks_held, state.timestamp,
            )
            saved[f"sp_{symbol}"] = sleeve_pos
            saved[f"th_{symbol}"] = ticks_held
            if orders:
                result[symbol] = orders

        return result, 0, json.dumps(saved, separators=(",", ":"))
