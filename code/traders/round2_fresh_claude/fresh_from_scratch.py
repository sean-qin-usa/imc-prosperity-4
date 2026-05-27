"""
Round 2 — written from scratch on 2026-04-23 using SIGNALS_PLAYBOOK §0–§1 only.
No past strategies were read.

Generative hypotheses (§0.1):
    ASH_COATED_OSMIUM (ACO):  flat anchor ≈ 9985, residual sd ≈ 400, AR(1) = −0.5.
        → symmetric mean-reverting market make around micro-price.
    INTARIAN_PEPPER_ROOT (IPR):  linear drift +1000/day (+0.001/ts),
        residual sd ≈ 500, AR(1) = −0.5.
        → DRIFT CARRY (target +80 long all day) + make-on-top.

Captured edges (§1):
    L1 imbalance → next-tick Δmid:  P(up | imb>+0.5) = 88-96% on both products.
    Captured by setting fair = micro-price = (ask·V_bid + bid·V_ask)/(V_bid+V_ask).
    This is algebraically mid + (spread/2)·imb, so no extra logic needed.

Two knobs per product (§8 discipline):
    ACO:  take_edge = 1, passive_depth = 20.
    IPR:  sell_edge = 2 (asymmetric — bias long),  passive_depth = 20.
"""
from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState


class Trader:
    POSITION_LIMITS: Dict[str, int] = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    def bid(self) -> int:
        return 0

    @staticmethod
    def _best(od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        bb_vol = od.buy_orders[bb]
        ba_vol = abs(od.sell_orders[ba])
        denom = bb_vol + ba_vol
        micro = (ba * bb_vol + bb * ba_vol) / denom if denom > 0 else (bb + ba) / 2
        return bb, ba, bb_vol, ba_vol, micro

    def _trade_symmetric(
        self, prod: str, od: OrderDepth, pos: int, take_edge: float
    ) -> List[Order]:
        """Symmetric mean-reverting MM around micro-price. Used for ACO."""
        limit = self.POSITION_LIMITS[prod]
        out: List[Order] = []
        info = self._best(od)
        if info is None:
            return out
        bb, ba, _bv, _av, micro = info

        buy_cap = limit - pos
        sell_cap = limit + pos

        # Takes — walk the book in price-favorable order.
        for ask_px in sorted(od.sell_orders.keys()):
            if buy_cap <= 0 or ask_px > micro - take_edge:
                break
            avol = abs(od.sell_orders[ask_px])
            qty = min(buy_cap, avol)
            if qty > 0:
                out.append(Order(prod, int(ask_px), qty))
                buy_cap -= qty
        for bid_px in sorted(od.buy_orders.keys(), reverse=True):
            if sell_cap <= 0 or bid_px < micro + take_edge:
                break
            bvol = od.buy_orders[bid_px]
            qty = min(sell_cap, bvol)
            if qty > 0:
                out.append(Order(prod, int(bid_px), -qty))
                sell_cap -= qty

        # Passive make — 1-tick inside when spread allows.
        spread = ba - bb
        depth = 20
        if spread >= 2:
            if buy_cap > 0:
                out.append(Order(prod, bb + 1, min(buy_cap, depth)))
            if sell_cap > 0:
                out.append(Order(prod, ba - 1, -min(sell_cap, depth)))
        return out

    def _trade_drift_long(
        self, prod: str, od: OrderDepth, pos: int, sell_edge: float
    ) -> List[Order]:
        """Drift-carry long bias for IPR.  Buy eagerly; sell only with clear edge."""
        limit = self.POSITION_LIMITS[prod]
        out: List[Order] = []
        info = self._best(od)
        if info is None:
            return out
        bb, ba, _bv, _av, micro = info

        buy_cap = limit - pos
        sell_cap = limit + pos

        # Aggressive buys: take any ask ≤ micro (zero take_edge) — drift dominates.
        for ask_px in sorted(od.sell_orders.keys()):
            if buy_cap <= 0 or ask_px > micro:
                break
            avol = abs(od.sell_orders[ask_px])
            qty = min(buy_cap, avol)
            if qty > 0:
                out.append(Order(prod, int(ask_px), qty))
                buy_cap -= qty

        # Conservative sells: only if bid ≥ micro + sell_edge (harvest overbids).
        for bid_px in sorted(od.buy_orders.keys(), reverse=True):
            if sell_cap <= 0 or bid_px < micro + sell_edge:
                break
            bvol = od.buy_orders[bid_px]
            qty = min(sell_cap, bvol)
            if qty > 0:
                out.append(Order(prod, int(bid_px), -qty))
                sell_cap -= qty

        spread = ba - bb
        depth = 20
        if spread >= 2:
            # Always post aggressive passive buy 1-tick inside; we want the fills.
            if buy_cap > 0:
                out.append(Order(prod, bb + 1, min(buy_cap, depth)))
            # Passive sell only when already past target long (pos > 0) and spread wide.
            if sell_cap > 0 and pos > 0 and spread >= 4:
                out.append(Order(prod, ba - 1, -min(sell_cap, depth)))
        return out

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}
        for prod, od in state.order_depths.items():
            pos = state.position.get(prod, 0)
            if prod == "ASH_COATED_OSMIUM":
                result[prod] = self._trade_symmetric(prod, od, pos, take_edge=1.0)
            elif prod == "INTARIAN_PEPPER_ROOT":
                result[prod] = self._trade_drift_long(prod, od, pos, sell_edge=2.0)
            else:
                result[prod] = []
        return result, 0, state.traderData or ""
