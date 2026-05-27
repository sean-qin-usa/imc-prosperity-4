"""Probe-informed benchmark push production candidate with PEPPER late unwind.

This keeps the current benchmark push structure intact, preserves the confirmed
`+2` passive PEPPER bid improvement, and adds late-session PEPPER-only risk
controls so the strategy stops reloading late and actively drains inventory
into the close.
"""

import json
import math
from typing import Any, Dict, List, Optional, Tuple

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
    ACO_MAX_POST_SIZE = 19
    ACO_PASSIVE_OFFSET = 3.5

    IPR_DRIFT_PER_TIMESTAMP = 0.001
    IPR_EARLY_TAKE_TARGET = 64
    IPR_CORE_TARGET = 64
    IPR_BAND_SELL_EDGE = 3.0
    IPR_BAND_RELOAD_EDGE = 1.0
    IPR_BAND_QTY = 6
    IPR_PASSIVE_BID_SIZE = 10
    IPR_PASSIVE_BID_DISTANCE = 2
    IPR_EARLY_TAKE_WINDOW = 500
    IPR_VAR_ALPHA = 0.06
    IPR_BOTTOM_ZSCORE_THRESHOLD = -1.10
    IPR_BOTTOM_EXTRA_QTY = 4
    IPR_BOTTOM_PATH_CAP = 1.5

    # PEPPER late-session controls derived from the official `136167` failure:
    # the strategy kept reloading after 92k and finished with a large long.
    IPR_NO_RELOAD_START = 93000
    IPR_LATE_UNWIND_START = 98000
    IPR_LATE_UNWIND_TARGET = 64
    IPR_LATE_UNWIND_MAX_QTY = 24
    IPR_FINAL_UNWIND_START = 98500
    IPR_FINAL_UNWIND_TARGET = 0
    IPR_FINAL_UNWIND_MAX_QTY = 80

    def run(self, state: TradingState):
        saved_state = self._load_state(state.traderData)
        last_ts = saved_state.get("last_ts")
        day_reset = last_ts is not None and state.timestamp < last_ts

        result: Dict[str, List[Order]] = {}

        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self.trade_aco_mean_reversion(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
            )

        ipr_anchor = saved_state.get("ipr_anchor")
        ipr_var = float(saved_state.get("ipr_var", 9.0))
        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            ipr_state = self._book_state(state.order_depths["INTARIAN_PEPPER_ROOT"])
            if ipr_state is not None:
                touch_mid = 0.5 * (ipr_state["best_bid"] + ipr_state["best_ask"])
                resolved_anchor = touch_mid if (ipr_anchor is None or day_reset) else float(ipr_anchor)
                residual = touch_mid - (
                    resolved_anchor + self.IPR_DRIFT_PER_TIMESTAMP * state.timestamp
                )
                ipr_var = (
                    (1.0 - self.IPR_VAR_ALPHA) * ipr_var
                    + self.IPR_VAR_ALPHA * (residual * residual)
                )
            ipr_orders, ipr_anchor = self.trade_ipr_core_band(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                ipr_anchor,
                state.timestamp,
                day_reset,
                ipr_var,
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
            return {"ipr_anchor": None, "last_ts": None}
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
        bid_wall = min(buy_orders.keys())
        ask_wall = max(sell_orders.keys())

        return {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_wall": bid_wall,
            "ask_wall": ask_wall,
            "spread": best_ask - best_bid,
        }

    def _cap_post_size(self, base_size: int, working_position: int, side: str, capacity: int) -> int:
        size = base_size
        if side == "buy" and working_position > 0:
            size = max(2, size - working_position // 10)
        elif side == "sell" and working_position < 0:
            size = max(2, size - abs(working_position) // 10)
        return max(0, min(capacity, size))

    def _sell_into_bids(
        self,
        product: str,
        buy_orders: Dict[int, int],
        working_position: int,
        target_position: int,
        max_qty: int,
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []
        qty_remaining = min(max_qty, max(0, working_position - target_position))

        for bid_price, bid_volume in buy_orders.items():
            if qty_remaining <= 0:
                break
            qty = min(qty_remaining, abs(int(bid_volume)))
            if qty <= 0:
                continue
            orders.append(Order(product, bid_price, -qty))
            working_position -= qty
            qty_remaining -= qty

        return orders, working_position

    def trade_aco_mean_reversion(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        product = "ASH_COATED_OSMIUM"
        limit = self.LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders

        buy_orders: Dict[int, int] = state["buy_orders"]
        sell_orders: Dict[int, int] = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        spread = int(state["spread"])

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

    def trade_ipr_core_band(
        self,
        order_depth: OrderDepth,
        position: int,
        anchor: Optional[float],
        timestamp: int,
        day_reset: bool,
        ipr_var: float,
    ):
        orders: List[Order] = []
        product = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders, anchor

        buy_orders = state["buy_orders"]
        sell_orders = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        spread = int(state["spread"])

        touch_mid = 0.5 * (best_bid + best_ask)
        if anchor is None or day_reset:
            anchor = touch_mid

        benchmark_path = float(anchor) + self.IPR_DRIFT_PER_TIMESTAMP * timestamp
        working_position = position
        sold_this_tick = False
        allow_reloads = timestamp < self.IPR_NO_RELOAD_START

        if timestamp <= self.IPR_EARLY_TAKE_WINDOW:
            for ask_price, ask_volume in sell_orders.items():
                if working_position >= self.IPR_EARLY_TAKE_TARGET:
                    break
                buy_capacity = limit - working_position
                if buy_capacity <= 0:
                    break
                qty = min(
                    ask_volume,
                    buy_capacity,
                    self.IPR_EARLY_TAKE_TARGET - working_position,
                    12,
                )
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty

        excess_inventory = max(0, working_position - self.IPR_CORE_TARGET)
        if excess_inventory > 0 and best_bid >= benchmark_path + self.IPR_BAND_SELL_EDGE:
            qty = min(excess_inventory, self.IPR_BAND_QTY, abs(int(buy_orders[best_bid])))
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                working_position -= qty
                sold_this_tick = True

        unwind_target: Optional[int] = None
        unwind_max_qty = 0
        if timestamp >= self.IPR_FINAL_UNWIND_START:
            unwind_target = self.IPR_FINAL_UNWIND_TARGET
            unwind_max_qty = self.IPR_FINAL_UNWIND_MAX_QTY
        elif timestamp >= self.IPR_LATE_UNWIND_START:
            unwind_target = self.IPR_LATE_UNWIND_TARGET
            unwind_max_qty = self.IPR_LATE_UNWIND_MAX_QTY

        if unwind_target is not None and working_position > unwind_target:
            unwind_orders, working_position = self._sell_into_bids(
                product,
                buy_orders,
                working_position,
                unwind_target,
                unwind_max_qty,
            )
            if unwind_orders:
                orders.extend(unwind_orders)
                sold_this_tick = True

        if allow_reloads and working_position < limit and best_ask <= benchmark_path + self.IPR_BAND_RELOAD_EDGE:
            qty = min(limit - working_position, self.IPR_BAND_QTY, abs(int(sell_orders[best_ask])))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                working_position += qty

        if (
            allow_reloads
            and (not sold_this_tick)
            and working_position < limit
            and spread > self.IPR_PASSIVE_BID_DISTANCE
        ):
            bid_price = min(best_bid + self.IPR_PASSIVE_BID_DISTANCE, best_ask - 1)
            bid_qty = min(self.IPR_PASSIVE_BID_SIZE, limit - working_position)
            if bid_qty > 0 and bid_price < best_ask:
                orders.append(Order(product, bid_price, bid_qty))

        sigma = max(1.0, math.sqrt(max(0.0, float(ipr_var))))
        residual = touch_mid - benchmark_path
        zscore = residual / sigma
        current_buy = sum(max(0, int(order.quantity)) for order in orders)
        current_sell = sum(max(0, -int(order.quantity)) for order in orders)
        working_after_orders = position + current_buy - current_sell
        if (
            allow_reloads
            and timestamp > self.IPR_EARLY_TAKE_WINDOW
            and working_after_orders < limit
            and zscore <= self.IPR_BOTTOM_ZSCORE_THRESHOLD
            and best_ask <= benchmark_path + self.IPR_BOTTOM_PATH_CAP
        ):
            qty = min(
                self.IPR_BOTTOM_EXTRA_QTY,
                limit - working_after_orders,
                abs(int(sell_orders[best_ask])),
            )
            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        return orders, anchor
