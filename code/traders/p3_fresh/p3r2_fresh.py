"""
Prosperity 3 Round 2 — fresh strategy written 2026-04-23.

Built from SIGNALS_PLAYBOOK.md + ROUND2_RECIPE.md only; no past P3
strategies read.  Goal: beat Timo's R2 total (~100-120k SeaShells
across 3 days = baskets 40-60k + resin ~39k + kelp ~30k + croissants 20k).

§0.1 generative-process hypotheses (from analysis/fresh_scan_p3r2.py):

  RAINFOREST_RESIN  — anchored at 10 000, residual sd ≈ 2, AR(1) = −0.50,
                     mode spread 16, imb_r = +0.68.  Identical to P4 ACO.
                     → recipe's ACO handler directly (with limit 50).
  KELP              — short-term mean-reverting around slowly-moving anchor,
                     residual sd 2-4, AR(1) = −0.48, mode spread 3,
                     imb_r = +0.56.  Tighter spreads and weaker anchor than
                     Resin — use rolling-EMA fair + MM, smaller step.
  PICNIC_BASKET1    — 6C + 3J + 1D.  Persistent premium +30 to +70, sd 80,
                     spread_t to spread_{t+1} persistence 0.999 (slow
                     mean-revert).  Story #4: fixed-threshold spread trade,
                     NO constituent hedge.
  PICNIC_BASKET2    — 4C + 2J.  Premium ≈ +40, sd 55.  Same story.
  CROISSANTS, JAMS, DJEMBES — used as basket legs; not traded standalone
                     in this first pass (keep strategy surface-area small).
  SQUID_INK         — high vol, AR(1) near 0; informed-bot edge would
                     require bot-detection logic.  SKIP in v1.

Strategy (§7 order of ops):

  - Resin: ACO handler from recipe, limit 50, size 40, walked-extra 25.
  - Kelp: simple MM with micro-price fair + EMA anchor; smaller size.
  - Basket1: if mid − synth > +UPPER, take basket bid (short basket);
             if mid − synth < −LOWER, take basket ask (long basket).
             Thresholds set to top/bottom 5 % of historical distribution.
  - Basket2: same but with its own thresholds.

Position limits:
  RESIN 50, KELP 50, PB1 60, PB2 100.
"""
from typing import Dict, List, Optional
import json
import math

from datamodel import Order, OrderDepth, TradingState


class Trader:
    # Basket composition
    B1_W = {"CROISSANTS": 6, "JAMS": 3, "DJEMBES": 1}
    B2_W = {"CROISSANTS": 4, "JAMS": 2}

    LIMITS = {
        "RAINFOREST_RESIN": 50, "KELP": 50, "SQUID_INK": 50,
        "CROISSANTS": 250, "JAMS": 350, "DJEMBES": 60,
        "PICNIC_BASKET1": 60, "PICNIC_BASKET2": 100,
    }

    # Resin (static-anchor MM)
    RESIN_FAIR = 10_000
    RESIN_FAIR_CLIP = 4.0
    RESIN_TYPICAL_SPREAD = 16
    RESIN_WALKED_FAIR_CLIP = 6.0
    RESIN_INV_SKEW = 0.10  # higher skew since limit is smaller (50 vs 80)
    RESIN_MM_SIZE = 40
    RESIN_PENNY_EDGE = 1.0
    RESIN_WALKED_EXTRA = 25

    # Kelp (rolling-anchor MM)
    KELP_EMA_ALPHA = 0.10
    KELP_FAIR_CLIP = 3.0
    KELP_MM_SIZE = 20
    KELP_INV_SKEW = 0.10

    # Baskets — fixed thresholds, no hedging
    B1_UPPER = 80.0   # short basket1 when premium > +80
    B1_LOWER = -40.0  # long basket1 when premium < -40
    B2_UPPER = 80.0
    B2_LOWER = -40.0
    BASKET_TRADE_SIZE = 15  # per-tick aggression

    IMB_STRONG = 0.30
    IMB_BOOST = 1.8
    IMB_SHRINK = 0.2

    # ---- helpers ----
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

    # ---- Resin (ACO clone) ----
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

    # ---- Kelp ----
    def _trade_kelp(self, od, pos, kelp_ema):
        prod = "KELP"
        limit = self.LIMITS[prod]
        book = self._book(od, 2)  # at spread <= 2 use mid; else micro
        if not book: return [], kelp_ema
        bb, ba = book["bb"], book["ba"]
        micro, imb, spread = book["micro"], book["imb"], book["spread"]
        # Update EMA from the micro-price
        if kelp_ema is None: kelp_ema = micro
        else: kelp_ema = (1 - self.KELP_EMA_ALPHA) * kelp_ema + self.KELP_EMA_ALPHA * micro
        fair = kelp_ema + max(-self.KELP_FAIR_CLIP,
                              min(self.KELP_FAIR_CLIP, micro - kelp_ema))
        orders: List[Order] = []
        skewed = fair - self.KELP_INV_SKEW * pos
        # Takes at favorable price
        for ap, av in book["sells"].items():
            if limit - pos <= 0: break
            if ap <= skewed:
                qty = min(av, limit - pos)
                if qty > 0: orders.append(Order(prod, ap, qty)); pos += qty
        for bp, bv in book["buys"].items():
            if limit + pos <= 0: break
            skewed = fair - self.KELP_INV_SKEW * pos
            if bp >= skewed:
                qty = min(bv, limit + pos)
                if qty > 0: orders.append(Order(prod, bp, -qty)); pos -= qty
        # Passive MM (1-tick inside when possible)
        skewed = fair - self.KELP_INV_SKEW * pos
        bid_px = min(bb + 1, math.floor(skewed - 1))
        ask_px = max(ba - 1, math.ceil(skewed + 1))
        bid_px = min(int(bid_px), ba - 1)
        ask_px = max(int(ask_px), bb + 1)
        buy_cap = max(0, limit - pos); sell_cap = max(0, limit + pos)
        bid_sz = min(self.KELP_MM_SIZE, buy_cap)
        ask_sz = min(self.KELP_MM_SIZE, sell_cap)
        if imb > self.IMB_STRONG:
            ask_sz = max(0, int(round(ask_sz * self.IMB_SHRINK)))
            bid_sz = min(buy_cap, int(round(bid_sz * self.IMB_BOOST)))
        elif imb < -self.IMB_STRONG:
            bid_sz = max(0, int(round(bid_sz * self.IMB_SHRINK)))
            ask_sz = min(sell_cap, int(round(ask_sz * self.IMB_BOOST)))
        if bid_px < ask_px:
            if bid_sz > 0: orders.append(Order(prod, bid_px, bid_sz))
            if ask_sz > 0: orders.append(Order(prod, ask_px, -ask_sz))
        return orders, kelp_ema

    # ---- Basket arb ----
    def _basket_orders(self, od_basket, od_legs, weights, pos_basket, limit, upper, lower):
        """Fixed-threshold basket vs synthetic spread trade, no hedging."""
        bb = self._book(od_basket, -1)
        if bb is None: return []
        basket_bid = bb["bb"]; basket_ask = bb["ba"]
        basket_mid = (basket_bid + basket_ask) / 2
        synth_mid = 0.0
        for leg, w in weights.items():
            if leg not in od_legs: return []
            lb = self._book(od_legs[leg], -1)
            if lb is None: return []
            synth_mid += w * ((lb["bb"] + lb["ba"]) / 2)
        spread = basket_mid - synth_mid
        orders: List[Order] = []
        prod = None
        for name, od_ in [("PICNIC_BASKET1", od_basket), ("PICNIC_BASKET2", od_basket)]:
            # determined below
            pass
        # Determine product name from weights keys-composition to avoid passing it twice
        prod_name = "PICNIC_BASKET1" if weights == self.B1_W else "PICNIC_BASKET2"
        if spread > upper and pos_basket > -limit:
            # SHORT the basket: hit the best bid
            qty = min(self.BASKET_TRADE_SIZE, limit + pos_basket, bb["buys"].get(basket_bid, 0))
            if qty > 0: orders.append(Order(prod_name, basket_bid, -qty))
        elif spread < lower and pos_basket < limit:
            # LONG the basket: lift the best ask
            qty = min(self.BASKET_TRADE_SIZE, limit - pos_basket, bb["sells"].get(basket_ask, 0))
            if qty > 0: orders.append(Order(prod_name, basket_ask, qty))
        return orders

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        # Load traderData for EMA state
        saved = {"kelp_ema": None}
        if state.traderData:
            try: saved.update(json.loads(state.traderData))
            except Exception: pass

        od = state.order_depths
        pos = state.position

        if "RAINFOREST_RESIN" in od:
            result["RAINFOREST_RESIN"] = self._trade_resin(od["RAINFOREST_RESIN"], pos.get("RAINFOREST_RESIN", 0))
        # KELP disabled — EMA MM was adverse-selected (−8 to −11 k/day in v1).
        # Symptom suggests chasing the anchor at tight spread.  Parked for v2.
        if "PICNIC_BASKET1" in od:
            legs = {k: od[k] for k in self.B1_W if k in od}
            if len(legs) == len(self.B1_W):
                result["PICNIC_BASKET1"] = self._basket_orders(
                    od["PICNIC_BASKET1"], legs, self.B1_W,
                    pos.get("PICNIC_BASKET1", 0), self.LIMITS["PICNIC_BASKET1"],
                    self.B1_UPPER, self.B1_LOWER,
                )
        if "PICNIC_BASKET2" in od:
            legs = {k: od[k] for k in self.B2_W if k in od}
            if len(legs) == len(self.B2_W):
                result["PICNIC_BASKET2"] = self._basket_orders(
                    od["PICNIC_BASKET2"], legs, self.B2_W,
                    pos.get("PICNIC_BASKET2", 0), self.LIMITS["PICNIC_BASKET2"],
                    self.B2_UPPER, self.B2_LOWER,
                )
        return result, 0, json.dumps(saved, separators=(",", ":"))
