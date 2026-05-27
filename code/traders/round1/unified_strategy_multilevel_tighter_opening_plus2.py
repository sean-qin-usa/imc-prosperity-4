"""Round 1 unified candidate with a tight PEPPER opening `+2` residual only.

This keeps the stronger late split-ladder PEPPER logic and only changes the
opening residual accumulation:
- visible-take to 60 in the first 500 timestamps
- give the last 4 units a brief `+2` inside-spread chance
- avoid the opening `+3` level because it did not add value in the tighter test
"""

import importlib.util
import math
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
    IPR_EARLY_TAKE_TARGET = 60
    IPR_OPENING_RESIDUAL_TARGET = 64
    IPR_OPENING_RESIDUAL_END = 3_500
    IPR_OPENING_PRIMARY_DISTANCE = 2
    IPR_OPENING_PRIMARY_SIZE = 4

    IPR_SECONDARY_BID_DISTANCE = 3
    IPR_SECONDARY_BID_EARLY_SIZE = 3
    IPR_SECONDARY_BID_MID_SIZE = 2
    IPR_SECONDARY_BID_EARLY_END = 33_333
    IPR_SECONDARY_BID_MID_END = 66_666

    def _late_secondary_bid_size(
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

        residual_opening_phase = (
            timestamp > self.IPR_EARLY_TAKE_WINDOW
            and timestamp <= self.IPR_OPENING_RESIDUAL_END
            and working_position < self.IPR_OPENING_RESIDUAL_TARGET
        )

        if residual_opening_phase:
            remaining_capacity = limit - working_position
            remaining_target = self.IPR_OPENING_RESIDUAL_TARGET - working_position
            bid_qty = min(self.IPR_OPENING_PRIMARY_SIZE, remaining_capacity, remaining_target)
            if bid_qty > 0 and spread > self.IPR_OPENING_PRIMARY_DISTANCE:
                bid_price = min(best_bid + self.IPR_OPENING_PRIMARY_DISTANCE, best_ask - 1)
                if bid_price < best_ask:
                    orders.append(Order(product, bid_price, bid_qty))
        else:
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
                    secondary_bid_qty = self._late_secondary_bid_size(
                        timestamp,
                        working_position,
                        total_bid_qty,
                    )

                primary_bid_qty = max(0, total_bid_qty - secondary_bid_qty)
                if primary_bid_qty > 0 and primary_bid_price < best_ask:
                    orders.append(Order(product, primary_bid_price, primary_bid_qty))
                if secondary_bid_qty > 0 and secondary_bid_price < best_ask:
                    orders.append(Order(product, secondary_bid_price, secondary_bid_qty))

        sigma = max(1.0, math.sqrt(max(0.0, float(ipr_var))))
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
