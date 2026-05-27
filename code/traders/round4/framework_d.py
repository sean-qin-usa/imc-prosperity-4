"""
Framework D — pure trader-mirror at full size. NO chassis overlay.

Design principle: position is a direct function of cumulative named-trader
signal score. NO Citadel z-score MR, NO HYDROGEL anchor MM, NO IV-residual,
NO smile-EMA, NO voucher MR. Only trader-signal-driven directional sizing.

Per-product signal weights from R4 counterparty scan:
  VFE:      Mark 67 buy  +1.97 / Mark 49 sell -1.81 / Mark 22 sell +1.27
  HYDROGEL: Mark 22 sell +3.13 / Mark 14 buy +0.15 / Mark 38 buy -0.09
  VEV_4000: Mark 38 buy  +0.05 (too weak)
  VEV_5xxx-6xxx: Mark 01/22 systematic flow with edge ~0 (no signal)

Active products: VFE + HYDROGEL only. Everything else: no orders posted.
This is a deliberate volume reduction (~10% of baseline orders) — testing
whether trader-ID alpha alone clears the bar without chassis support.

Expected bt result: lower than 440k baseline (we drop ~150k of voucher PnL).
Bet: live conversion of trader-ID alpha is HIGHER than chassis MM because
named-flow predicts actual price moves, not statistical noise.
"""
from typing import Dict, List
import math
import json

from datamodel import Order, OrderDepth, TradingState

# Per-trader-per-side directional weights (from round4_counterparty_signal_report.md)
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

    # Decay per tick. score *= DECAY each tick. HL = ln(0.5)/ln(DECAY).
    DECAY = 0.985            # HL ≈ 46 ticks
    SIZE_K = 4.0             # target_pos = K * signed_score (clipped to limit)
    MIN_SCORE_ABS = 2.0      # ignore tiny scores
    MAX_TAKE_PER_TICK = 20   # aggressive take to reach target fast

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

    def _take_to_target(self, symbol, od, cur_pos, target):
        """Take aggressively (cross spread) to reach target position."""
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        diff = target - cur_pos
        if diff == 0:
            return []
        cap = min(abs(diff), self.MAX_TAKE_PER_TICK)
        limit = self.LIMITS[symbol]
        orders: List[Order] = []
        if diff > 0:
            cap = min(cap, limit - cur_pos)
            if cap <= 0:
                return []
            for ap in sorted(od.sell_orders.keys()):
                if cap <= 0:
                    break
                avail = abs(int(od.sell_orders[ap]))
                if avail <= 0:
                    continue
                q = min(avail, cap)
                orders.append(Order(symbol, int(ap), q))
                cap -= q
        else:
            cap = min(cap, limit + cur_pos)
            if cap <= 0:
                return []
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                if cap <= 0:
                    break
                avail = int(od.buy_orders[bp])
                if avail <= 0:
                    continue
                q = min(avail, cap)
                orders.append(Order(symbol, int(bp), -q))
                cap -= q
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

            if abs(score) < self.MIN_SCORE_ABS:
                # Score too small — flatten any inventory we built.
                cur = pos.get(symbol, 0)
                if cur != 0 and od is not None:
                    target = 0
                    orders = self._take_to_target(symbol, od, cur, target)
                    if orders:
                        result[symbol] = orders
                continue

            limit = self.LIMITS[symbol]
            raw = score * self.SIZE_K
            target = max(-limit, min(limit, int(raw)))
            orders = self._take_to_target(symbol, od, pos.get(symbol, 0), target)
            if orders:
                result[symbol] = orders

        return result, 0, json.dumps(saved, separators=(",", ":"))
