"""
Framework D-post — trader-mirror via POSTING (not taking).

Insight from D-take (-51k): per Mark 67 fire, edge=+1.97 ticks but spread
cost=5 ticks → take-side LOSES 3 ticks per cycle. Switch to posting:
when score is long-favored, post bid at bb+1 (improve by 1), capture
half-spread minus 1 tick. When forced seller (Mark 22) crosses, we win.

Posting strategy per product:
- score >  THR: post bid at bb+1, sized large; pull ask
- score < -THR: post ask at ba-1, sized large; pull bid
- |score| < THR: pull all orders, flatten any inventory

Active products: VFE + HYDROGEL only.

Volume profile: posts every tick when |score| > THR. Many posts cancel
unfilled. Different from baseline chassis: no slow MR, no anchor MM,
no Citadel, no IV-residual. Pure trader-driven posts.
"""
from typing import Dict, List
import math
import json

from datamodel import Order, OrderDepth, TradingState

WEIGHTS = {
    "VELVETFRUIT_EXTRACT": {
        ("Mark 67", "buy"):  +1.97,
        ("Mark 49", "sell"): -1.81,
        ("Mark 22", "sell"): +1.27,
    },
    "HYDROGEL_PACK": {
        ("Mark 22", "sell"): +3.13,
        ("Mark 14", "buy"):  +0.15,
        ("Mark 38", "buy"):  -0.09,
    },
}


class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
        "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
        "VEV_6500": 300,
    }

    DECAY = 0.985             # HL ≈ 46 ticks
    SCORE_THR = 4.0           # |score| above this triggers posting
    POST_SIZE = 60            # qty per post (capped by limit)
    EXIT_HOLD_TICKS = 0       # exit immediately at touch when score flips
    MAX_DIRECTIONAL_POS = 100 # cap on directional inventory accumulation

    def _update_score(self, market_trades, weights, prev_score):
        score = prev_score * self.DECAY
        for tr in (market_trades or []):
            qty = abs(int(getattr(tr, "quantity", 0)))
            if qty <= 0:
                continue
            buyer = getattr(tr, "buyer", None)
            seller = getattr(tr, "seller", None)
            w_buy = weights.get((buyer, "buy"))
            if w_buy is not None:
                score += w_buy * qty
            w_sell = weights.get((seller, "sell"))
            if w_sell is not None:
                score += w_sell * qty
        return score

    def _flatten_at_touch(self, symbol, od, cur_pos):
        """Cross spread to flatten cur_pos toward zero."""
        if cur_pos == 0 or od is None or not od.buy_orders or not od.sell_orders:
            return []
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        orders: List[Order] = []
        if cur_pos > 0:
            avail = abs(int(od.buy_orders[bb]))
            q = min(cur_pos, avail)
            if q > 0:
                orders.append(Order(symbol, int(bb), -q))
        else:
            avail = abs(int(od.sell_orders[ba]))
            q = min(-cur_pos, avail)
            if q > 0:
                orders.append(Order(symbol, int(ba), q))
        return orders

    def _trade_one(self, symbol, od, cur_pos, score):
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        if bb >= ba:
            return []

        # Score too small — flatten and stop posting.
        if abs(score) < self.SCORE_THR:
            return self._flatten_at_touch(symbol, od, cur_pos)

        limit = self.LIMITS[symbol]
        orders: List[Order] = []

        if score > 0:
            # Long-favored: post bid at bb+1 (improve), no ask.
            # Cap directional accumulation at MAX_DIRECTIONAL_POS.
            if cur_pos < self.MAX_DIRECTIONAL_POS:
                room = self.MAX_DIRECTIONAL_POS - cur_pos
                room = min(room, limit - cur_pos)
                qty = min(self.POST_SIZE, room)
                if qty > 0 and bb + 1 < ba:
                    orders.append(Order(symbol, int(bb + 1), qty))
            # If we're long, also post sell at ba-1 to take profit on rises
            if cur_pos > 0 and ba - 1 > bb:
                # Take profit posts: ask at ba-1
                qty = min(self.POST_SIZE, cur_pos + limit)
                qty = min(qty, cur_pos)  # don't go short via take-profit
                if qty > 0:
                    orders.append(Order(symbol, int(ba - 1), -qty))
        else:
            # Short-favored: post ask at ba-1 (improve), no bid.
            if cur_pos > -self.MAX_DIRECTIONAL_POS:
                room = self.MAX_DIRECTIONAL_POS + cur_pos
                room = min(room, limit + cur_pos)
                qty = min(self.POST_SIZE, room)
                if qty > 0 and ba - 1 > bb:
                    orders.append(Order(symbol, int(ba - 1), -qty))
            if cur_pos < 0 and bb + 1 < ba:
                qty = min(self.POST_SIZE, limit - cur_pos)
                qty = min(qty, -cur_pos)
                if qty > 0:
                    orders.append(Order(symbol, int(bb + 1), qty))

        return orders

    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        pos = state.position
        market_trades = getattr(state, "market_trades", {}) or {}

        for symbol, weights in WEIGHTS.items():
            od = state.order_depths.get(symbol)
            prev_score = float(saved.get(f"score_{symbol}", 0.0))
            score = self._update_score(market_trades.get(symbol, []), weights, prev_score)
            saved[f"score_{symbol}"] = score
            orders = self._trade_one(symbol, od, pos.get(symbol, 0), score)
            if orders:
                result[symbol] = orders

        return result, 0, json.dumps(saved, separators=(",", ":"))
