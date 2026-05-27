"""Official-site PEPPER probe for regime-aware passive fill discovery.

Use this on the Prosperity site when the goal is not immediate PnL, but learning
which early INTARIAN_PEPPER_ROOT passive entries are worth promoting.

This probe focuses on the specific question that remains unresolved after the
offline residual / imbalance analysis:

- is `+1` or `+2` inside better when PEPPER is path-cheap?
- does the answer change when top-of-book imbalance is supportive?

The PEPPER leg therefore:
- estimates a simple benchmark path and residual z-score online
- classifies the current state into four regimes:
  - both: cheap path residual and supportive imbalance
  - cheap_only
  - support_only
  - control
- alternates `+1` and `+2` inside bids by time slice within those regimes
- keeps regime-specific inventory caps so weaker regimes stay small

This file is intentionally standalone so it can be pasted into the official
site runner without relying on sibling imports or `__file__`.
"""

import json
import math
from typing import Any, Dict, List, Optional

from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    ACO_FAIR_VALUE = 10000
    ACO_TAKE_EDGE = 0.0
    ACO_REDUCE_EDGE = 1.0
    ACO_PENNY_EDGE = 1.5
    ACO_INVENTORY_SKEW_PER_UNIT = 0.06
    ACO_MAX_POST_SIZE = 8
    ACO_PASSIVE_OFFSET = 3.5

    IPR_DRIFT_PER_TIMESTAMP = 0.001
    IPR_VAR_ALPHA = 0.06
    IPR_ZSCORE_CHEAP_THRESHOLD = -1.0
    IPR_IMBALANCE_SUPPORT_THRESHOLD = 0.30

    IPR_PHASE_LENGTH = 5_000
    IPR_PROBE_WINDOW_END = 45_000
    IPR_POST_PROBE_HOLD = 8
    IPR_FLATTEN_START = 99_000
    IPR_MAX_NET_LONG = 20

    IPR_REGIME_TARGETS = {
        "both": 20,
        "cheap_only": 14,
        "support_only": 10,
        "control": 6,
    }
    IPR_REGIME_SIZES = {
        "both": 6,
        "cheap_only": 5,
        "support_only": 4,
        "control": 3,
    }

    def run(self, state: TradingState):
        saved_state = self._load_state(state.traderData)
        last_ts = saved_state.get("last_ts")
        day_reset = last_ts is not None and state.timestamp < last_ts

        result: Dict[str, List[Order]] = {}

        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self.trade_aco_probe(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
            )

        ipr_anchor = saved_state.get("ipr_anchor")
        ipr_var = float(saved_state.get("ipr_var", 9.0))
        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            ipr_orders, ipr_anchor, ipr_var = self.trade_ipr_probe(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                state.timestamp,
                ipr_anchor,
                ipr_var,
                day_reset,
            )
            result["INTARIAN_PEPPER_ROOT"] = ipr_orders

        trader_data = json.dumps(
            {
                "ipr_anchor": ipr_anchor,
                "ipr_var": ipr_var,
                "last_ts": state.timestamp,
            },
            separators=(",", ":"),
        )
        return result, 0, trader_data

    def _load_state(self, trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return {"ipr_anchor": None, "ipr_var": 9.0, "last_ts": None}
        try:
            payload = json.loads(trader_data)
        except Exception:
            return {"ipr_anchor": None, "ipr_var": 9.0, "last_ts": None}
        return {
            "ipr_anchor": payload.get("ipr_anchor"),
            "ipr_var": float(payload.get("ipr_var", 9.0)),
            "last_ts": payload.get("last_ts"),
        }

    def _sorted_buy_orders(self, order_depth: OrderDepth) -> Dict[int, int]:
        return {
            int(price): abs(int(volume))
            for price, volume in sorted(
                order_depth.buy_orders.items(),
                key=lambda item: item[0],
                reverse=True,
            )
        }

    def _sorted_sell_orders(self, order_depth: OrderDepth) -> Dict[int, int]:
        return {
            int(price): abs(int(volume))
            for price, volume in sorted(order_depth.sell_orders.items(), key=lambda item: item[0])
        }

    def _book_state(self, order_depth: OrderDepth) -> Optional[Dict[str, Any]]:
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None

        buy_orders = self._sorted_buy_orders(order_depth)
        sell_orders = self._sorted_sell_orders(order_depth)
        if not buy_orders or not sell_orders:
            return None

        best_bid = max(buy_orders.keys())
        best_ask = min(sell_orders.keys())
        best_bid_qty = abs(int(buy_orders[best_bid]))
        best_ask_qty = abs(int(sell_orders[best_ask]))
        qty_denom = best_bid_qty + best_ask_qty
        imbalance = 0.0 if qty_denom <= 0 else (best_bid_qty - best_ask_qty) / float(qty_denom)
        return {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": best_ask - best_bid,
            "l1_imbalance": imbalance,
        }

    def _cap_post_size(
        self,
        base_size: int,
        working_position: int,
        side: str,
        capacity: int,
    ) -> int:
        size = base_size
        if side == "buy" and working_position > 0:
            size = max(2, size - working_position // 10)
        elif side == "sell" and working_position < 0:
            size = max(2, size - abs(working_position) // 10)
        return max(0, min(capacity, size))

    def trade_aco_probe(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        state = self._book_state(order_depth)
        if state is None:
            return orders

        product = "ASH_COATED_OSMIUM"
        limit = self.LIMITS[product]
        buy_orders: Dict[int, int] = state["buy_orders"]
        sell_orders: Dict[int, int] = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        spread = int(state["spread"])

        if position > 6:
            qty = min(position, buy_orders[best_bid])
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
            return orders

        if position < -6:
            qty = min(abs(position), sell_orders[best_ask])
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
            return orders

        fair_value = float(self.ACO_FAIR_VALUE)
        working_position = position

        for ask_price, ask_volume in sell_orders.items():
            buy_capacity = limit - working_position
            if buy_capacity <= 0:
                break

            fair_skewed = fair_value - self.ACO_INVENTORY_SKEW_PER_UNIT * working_position

            if ask_price <= fair_skewed - self.ACO_TAKE_EDGE:
                qty = min(ask_volume, buy_capacity)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty
            elif working_position < 0 and ask_price <= fair_skewed + self.ACO_REDUCE_EDGE:
                qty = min(ask_volume, buy_capacity, abs(working_position))
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty

        for bid_price, bid_volume in buy_orders.items():
            sell_capacity = limit + working_position
            if sell_capacity <= 0:
                break

            fair_skewed = fair_value - self.ACO_INVENTORY_SKEW_PER_UNIT * working_position

            if bid_price >= fair_skewed + self.ACO_TAKE_EDGE:
                qty = min(bid_volume, sell_capacity)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    working_position -= qty
            elif working_position > 0 and bid_price >= fair_skewed - self.ACO_REDUCE_EDGE:
                qty = min(bid_volume, sell_capacity, working_position)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    working_position -= qty

        fair_skewed = fair_value - self.ACO_INVENTORY_SKEW_PER_UNIT * working_position
        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)

        bid_size = self._cap_post_size(self.ACO_MAX_POST_SIZE, working_position, "buy", buy_capacity)
        ask_size = self._cap_post_size(self.ACO_MAX_POST_SIZE, working_position, "sell", sell_capacity)

        if spread >= 8:
            bid_price = min(best_bid + 1, math.floor(fair_skewed - self.ACO_PENNY_EDGE))
            ask_price = max(best_ask - 1, math.ceil(fair_skewed + self.ACO_PENNY_EDGE))
        else:
            bid_price = math.floor(fair_skewed - self.ACO_PASSIVE_OFFSET)
            ask_price = math.ceil(fair_skewed + self.ACO_PASSIVE_OFFSET)

        bid_price = min(int(bid_price), best_ask - 1, self.ACO_FAIR_VALUE - 1)
        ask_price = max(int(ask_price), best_bid + 1, self.ACO_FAIR_VALUE + 1)

        if bid_price < ask_price:
            if bid_size > 0:
                orders.append(Order(product, bid_price, bid_size))
            if ask_size > 0:
                orders.append(Order(product, ask_price, -ask_size))

        return orders

    def trade_ipr_probe(
        self,
        order_depth: OrderDepth,
        position: int,
        timestamp: int,
        anchor: Optional[float],
        ipr_var: float,
        day_reset: bool,
    ):
        orders: List[Order] = []
        product = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders, anchor, ipr_var

        buy_orders: Dict[int, int] = state["buy_orders"]
        sell_orders: Dict[int, int] = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        spread = int(state["spread"])
        imbalance = float(state.get("l1_imbalance", 0.0))

        touch_mid = 0.5 * (best_bid + best_ask)
        if anchor is None or day_reset:
            anchor = touch_mid

        benchmark_path = float(anchor) + self.IPR_DRIFT_PER_TIMESTAMP * timestamp
        residual = touch_mid - benchmark_path
        ipr_var = (1.0 - self.IPR_VAR_ALPHA) * float(ipr_var) + self.IPR_VAR_ALPHA * (residual * residual)
        sigma = max(1.0, math.sqrt(max(0.0, ipr_var)))
        zscore = residual / sigma

        if timestamp >= self.IPR_FLATTEN_START:
            if position > 0:
                qty = min(position, buy_orders[best_bid])
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))
            elif position < 0:
                qty = min(abs(position), sell_orders[best_ask])
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            return orders, anchor, ipr_var

        if timestamp >= self.IPR_PROBE_WINDOW_END:
            if position > self.IPR_POST_PROBE_HOLD:
                qty = min(position - self.IPR_POST_PROBE_HOLD, buy_orders[best_bid])
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))
            return orders, anchor, ipr_var

        cheap = zscore <= self.IPR_ZSCORE_CHEAP_THRESHOLD
        supportive = imbalance >= self.IPR_IMBALANCE_SUPPORT_THRESHOLD
        if cheap and supportive:
            regime = "both"
        elif cheap:
            regime = "cheap_only"
        elif supportive:
            regime = "support_only"
        else:
            regime = "control"

        phase_index = (timestamp // self.IPR_PHASE_LENGTH) % 2
        distance = 1 if phase_index == 0 else 2
        quote_size = int(self.IPR_REGIME_SIZES[regime])
        target_inventory = min(int(self.IPR_REGIME_TARGETS[regime]), self.IPR_MAX_NET_LONG)

        if position < target_inventory and spread > distance:
            remaining = min(limit - position, target_inventory - position)
            if remaining > 0:
                price = min(best_bid + distance, best_ask - 1)
                qty = min(quote_size, remaining)
                if qty > 0 and price < best_ask:
                    orders.append(Order(product, price, qty))

        return orders, anchor, ipr_var
