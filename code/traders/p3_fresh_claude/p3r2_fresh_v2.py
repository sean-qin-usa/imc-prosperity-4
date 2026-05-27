"""
P3 R2 v2 — rolling-centered basket spread + soft stop-reduce.

Overfit-reduction changes vs v1:
  - Hardcoded +80/-40 thresholds replaced with `center ± K` where
    `center` is an EMA of the spread (absorbs daily mean drift).
  - Two parameters across both baskets (EMA alpha, K) instead of four.
  - Soft stop-reduce: if at position limit and spread continues to
    widen by > 2K from center, trim by 25 % — caps runaway loss days
    like R2 day 0 PB2 (−10 k when spread went to −120).

Resin handler unchanged from v1 (already recipe-scaled).
"""
from typing import Dict, List, Optional
import json
import math

from datamodel import Order, OrderDepth, TradingState


class Trader:
    B1_W = {"CROISSANTS": 6, "JAMS": 3, "DJEMBES": 1}
    B2_W = {"CROISSANTS": 4, "JAMS": 2}

    LIMITS = {
        "RAINFOREST_RESIN": 50, "KELP": 50, "SQUID_INK": 50,
        "CROISSANTS": 250, "JAMS": 350, "DJEMBES": 60,
        "PICNIC_BASKET1": 60, "PICNIC_BASKET2": 100,
    }

    # Resin (unchanged)
    RESIN_FAIR = 10_000
    RESIN_FAIR_CLIP = 4.0
    RESIN_TYPICAL_SPREAD = 16
    RESIN_WALKED_FAIR_CLIP = 6.0
    RESIN_INV_SKEW = 0.10
    RESIN_MM_SIZE = 40
    RESIN_PENNY_EDGE = 1.0
    RESIN_WALKED_EXTRA = 25

    # Baskets — rolling-centered (2 shared params)
    BASKET_EMA_ALPHA = 0.002   # ~500-tick effective window
    BASKET_K = 60              # trade when |spread - center| > K
    BASKET_TRADE_SIZE = 15
    BASKET_STOP_MULT = 2.0     # start trim-down at |spread - center| > STOP_MULT * K

    IMB_STRONG = 0.30
    IMB_BOOST = 1.8
    IMB_SHRINK = 0.2

    def _book(self, od: OrderDepth, gate_mid: int = -1) -> Optional[Dict]:
        if not od.buy_orders or not od.sell_orders: return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys); ba = min(sells)
        bv, av = buys[bb], sells[ba]
        tot = bv + av
        imb = (bv - av) / tot if tot else 0.0
        spread = ba - bb
        if gate_mid >= 0 and spread <= gate_mid:
            micro = 0.5 * (bb + ba)
        else:
            micro = (ba * bv + bb * av) / tot if tot else 0.5 * (bb + ba)
        return {
            "buys": dict(sorted(buys.items(), reverse=True)),
            "sells": dict(sorted(sells.items())),
            "bb": bb, "ba": ba, "imb": imb, "micro": micro, "spread": spread,
        }

    def _walked_fair(self, bb, ba, micro, anchor, typical, clip):
        spread = ba - bb
        if spread <= typical:
            return anchor + max(-clip, min(clip, micro - anchor))
        bid_gap = anchor - bb; ask_gap = ba - anchor
        half = typical / 2
        if bid_gap > ask_gap + 0.5: trusted = ba - half
        elif ask_gap > bid_gap + 0.5: trusted = bb + half
        else: trusted = 0.5 * (bb + ba)
        return anchor + max(-clip, min(clip, trusted - anchor))

    def _trade_resin(self, od, pos):
        prod = "RAINFOREST_RESIN"
        limit = self.LIMITS[prod]
        book = self._book(od, self.RESIN_TYPICAL_SPREAD)
        if not book: return []
        bb, ba = book["bb"], book["ba"]
        micro, imb, spread = book["micro"], book["imb"], book["spread"]
        fair = self._walked_fair(bb, ba, micro, float(self.RESIN_FAIR),
                                 self.RESIN_TYPICAL_SPREAD, self.RESIN_WALKED_FAIR_CLIP)
        orders: List[Order] = []
        skewed = fair - self.RESIN_INV_SKEW * pos
        for ap, av in book["sells"].items():
            if limit - pos <= 0: break
            if ap <= skewed:
                qty = min(av, limit - pos)
                if qty > 0: orders.append(Order(prod, ap, qty)); pos += qty
        for bp, bv in book["buys"].items():
            if limit + pos <= 0: break
            skewed = fair - self.RESIN_INV_SKEW * pos
            if bp >= skewed:
                qty = min(bv, limit + pos)
                if qty > 0: orders.append(Order(prod, bp, -qty)); pos -= qty
        skewed = fair - self.RESIN_INV_SKEW * pos
        if spread >= 4:
            bid_px = min(bb + 1, math.floor(skewed - self.RESIN_PENNY_EDGE))
            ask_px = max(ba - 1, math.ceil(skewed + self.RESIN_PENNY_EDGE))
        else:
            bid_px = math.floor(skewed - 1); ask_px = math.ceil(skewed + 1)
        bid_px = min(int(bid_px), ba - 1, math.floor(fair) - 1)
        ask_px = max(int(ask_px), bb + 1, math.ceil(fair) + 1)
        buy_cap = max(0, limit - pos); sell_cap = max(0, limit + pos)
        bid_sz = min(self.RESIN_MM_SIZE, buy_cap)
        ask_sz = min(self.RESIN_MM_SIZE, sell_cap)
        if imb > self.IMB_STRONG:
            ask_sz = max(0, int(round(ask_sz * self.IMB_SHRINK)))
            bid_sz = min(buy_cap, int(round(bid_sz * self.IMB_BOOST)))
        elif imb < -self.IMB_STRONG:
            bid_sz = max(0, int(round(bid_sz * self.IMB_SHRINK)))
            ask_sz = min(sell_cap, int(round(ask_sz * self.IMB_BOOST)))
        if bid_px < ask_px:
            if bid_sz > 0: orders.append(Order(prod, bid_px, bid_sz))
            if ask_sz > 0: orders.append(Order(prod, ask_px, -ask_sz))
        if spread > self.RESIN_TYPICAL_SPREAD:
            bid_gap = self.RESIN_FAIR - bb; ask_gap = ba - self.RESIN_FAIR
            if bid_gap > ask_gap + 0.5 and pos < limit:
                wx = bb + 1
                if wx < math.floor(fair):
                    sz = min(self.RESIN_WALKED_EXTRA, limit - pos)
                    if sz > 0 and wx != bid_px: orders.append(Order(prod, wx, sz))
            elif ask_gap > bid_gap + 0.5 and pos > -limit:
                wx = ba - 1
                if wx > math.ceil(fair):
                    sz = min(self.RESIN_WALKED_EXTRA, limit + pos)
                    if sz > 0 and wx != ask_px: orders.append(Order(prod, wx, -sz))
        return orders

    def _basket_orders_v2(self, basket_name, od_basket, od_legs, weights,
                          pos_basket, limit, center):
        """Rolling-centered basket arb.

        Trade when spread deviates > K from rolling center.
        Reduce position by 25 % when spread has drifted > STOP_MULT · K
        from center (runaway-loss guard).

        Returns (orders, new_center).
        """
        bb = self._book(od_basket, -1)
        if bb is None: return [], center
        basket_bid = bb["bb"]; basket_ask = bb["ba"]
        basket_mid = (basket_bid + basket_ask) / 2
        synth_mid = 0.0
        for leg, w in weights.items():
            if leg not in od_legs: return [], center
            lb = self._book(od_legs[leg], -1)
            if lb is None: return [], center
            synth_mid += w * ((lb["bb"] + lb["ba"]) / 2)
        spread = basket_mid - synth_mid

        # Update rolling center
        if center is None: center = spread
        else: center = (1 - self.BASKET_EMA_ALPHA) * center + self.BASKET_EMA_ALPHA * spread

        dev = spread - center
        K = self.BASKET_K
        orders: List[Order] = []

        # Runaway-loss guard: trim into adverse move.
        if dev > self.BASKET_STOP_MULT * K and pos_basket < 0:
            # We are short the basket and spread keeps widening — BUY to trim.
            trim = min(abs(pos_basket) // 4 + 1, bb["sells"].get(basket_ask, 0))
            if trim > 0:
                orders.append(Order(basket_name, basket_ask, trim))
                return orders, center
        elif dev < -self.BASKET_STOP_MULT * K and pos_basket > 0:
            trim = min(pos_basket // 4 + 1, bb["buys"].get(basket_bid, 0))
            if trim > 0:
                orders.append(Order(basket_name, basket_bid, -trim))
                return orders, center

        # Entry
        if dev > K and pos_basket > -limit:
            qty = min(self.BASKET_TRADE_SIZE, limit + pos_basket, bb["buys"].get(basket_bid, 0))
            if qty > 0: orders.append(Order(basket_name, basket_bid, -qty))
        elif dev < -K and pos_basket < limit:
            qty = min(self.BASKET_TRADE_SIZE, limit - pos_basket, bb["sells"].get(basket_ask, 0))
            if qty > 0: orders.append(Order(basket_name, basket_ask, qty))
        return orders, center

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        saved = {"b1_center": None, "b2_center": None}
        if state.traderData:
            try: saved.update(json.loads(state.traderData))
            except Exception: pass

        od = state.order_depths
        pos = state.position

        if "RAINFOREST_RESIN" in od:
            result["RAINFOREST_RESIN"] = self._trade_resin(
                od["RAINFOREST_RESIN"], pos.get("RAINFOREST_RESIN", 0))

        if "PICNIC_BASKET1" in od:
            legs = {k: od[k] for k in self.B1_W if k in od}
            if len(legs) == len(self.B1_W):
                result["PICNIC_BASKET1"], saved["b1_center"] = self._basket_orders_v2(
                    "PICNIC_BASKET1", od["PICNIC_BASKET1"], legs, self.B1_W,
                    pos.get("PICNIC_BASKET1", 0), self.LIMITS["PICNIC_BASKET1"],
                    saved.get("b1_center"))

        if "PICNIC_BASKET2" in od:
            legs = {k: od[k] for k in self.B2_W if k in od}
            if len(legs) == len(self.B2_W):
                result["PICNIC_BASKET2"], saved["b2_center"] = self._basket_orders_v2(
                    "PICNIC_BASKET2", od["PICNIC_BASKET2"], legs, self.B2_W,
                    pos.get("PICNIC_BASKET2", 0), self.LIMITS["PICNIC_BASKET2"],
                    saved.get("b2_center"))

        return result, 0, json.dumps(saved, separators=(",", ":"))
