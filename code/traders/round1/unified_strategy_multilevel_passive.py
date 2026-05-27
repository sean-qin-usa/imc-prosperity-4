"""Round 1 unified strategy candidate with time-bucketed PEPPER quote ladder.

This keeps the current unified production strategy intact and only changes the
PEPPER passive entry logic:
- keep the main `+2` inside passive bid
- add a smaller `+3` inside completion bid while still below the core target
- taper the secondary level from early session to mid session, then disable it
"""

import importlib.util
from pathlib import Path
from typing import List, Optional

from datamodel import Order, OrderDepth


_BASE_PATH = Path(__file__).with_name("unified_strategy.py")
_BASE_SPEC = importlib.util.spec_from_file_location("unified_strategy", _BASE_PATH)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load base trader from {_BASE_PATH}")

_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)


class Trader(_BASE_MODULE.Trader):
    IPR_SECONDARY_BID_DISTANCE = 3
    IPR_SECONDARY_BID_EARLY_SIZE = 3
    IPR_SECONDARY_BID_MID_SIZE = 2
    IPR_SECONDARY_BID_EARLY_END = 33_333
    IPR_SECONDARY_BID_MID_END = 66_666

    def _secondary_bid_size(
        self,
        timestamp: int,
        working_position: int,
        total_bid_qty: int,
    ) -> int:
        if working_position >= self.IPR_CORE_TARGET:
            return 0
        if timestamp < self.IPR_SECONDARY_BID_EARLY_END:
            return min(self.IPR_SECONDARY_BID_EARLY_SIZE, total_bid_qty)
        if timestamp < self.IPR_SECONDARY_BID_MID_END:
            return min(self.IPR_SECONDARY_BID_MID_SIZE, total_bid_qty)
        return 0

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

        if working_position < limit and best_ask <= benchmark_path + self.IPR_BAND_RELOAD_EDGE:
            qty = min(limit - working_position, self.IPR_BAND_QTY, abs(int(sell_orders[best_ask])))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                working_position += qty

        if (not sold_this_tick) and working_position < limit and spread > self.IPR_PASSIVE_BID_DISTANCE:
            remaining_capacity = limit - working_position
            primary_bid_price = min(best_bid + self.IPR_PASSIVE_BID_DISTANCE, best_ask - 1)
            total_bid_qty = min(self.IPR_PASSIVE_BID_SIZE, remaining_capacity)
            secondary_bid_price = min(best_bid + self.IPR_SECONDARY_BID_DISTANCE, best_ask - 1)
            secondary_bid_qty = 0
            if (
                total_bid_qty > 0
                and spread > self.IPR_SECONDARY_BID_DISTANCE
                and secondary_bid_price < best_ask
                and secondary_bid_price > primary_bid_price
            ):
                secondary_bid_qty = self._secondary_bid_size(
                    timestamp,
                    working_position,
                    total_bid_qty,
                )

            primary_bid_qty = max(0, total_bid_qty - secondary_bid_qty)
            if primary_bid_qty > 0 and primary_bid_price < best_ask:
                orders.append(Order(product, primary_bid_price, primary_bid_qty))
            if secondary_bid_qty > 0 and secondary_bid_price < best_ask:
                orders.append(Order(product, secondary_bid_price, secondary_bid_qty))

        sigma = max(1.0, (max(0.0, float(ipr_var))) ** 0.5)
        residual = touch_mid - benchmark_path
        zscore = residual / sigma
        current_buy = sum(max(0, int(order.quantity)) for order in orders)
        current_sell = sum(max(0, -int(order.quantity)) for order in orders)
        working_after_orders = position + current_buy - current_sell
        if (
            timestamp > self.IPR_EARLY_TAKE_WINDOW
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
