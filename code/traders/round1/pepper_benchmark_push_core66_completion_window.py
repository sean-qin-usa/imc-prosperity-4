"""Core-66 benchmark-push variant with a windowed PEPPER completion quote.

This keeps the validated `+1` inside passive PEPPER quote from
`pepper_benchmark_push__best_locked.py` and optionally adds a smaller `+2`
completion quote in a configurable time window.

The secondary order is only posted while the strategy is below the configured
PEPPER core target, and it is capped by the remaining shortfall. This is meant
to study whether a small deeper quote helps complete the carry build without
replacing the stronger primary `+1` quote.
"""

import importlib.util
from pathlib import Path
from typing import List, Optional

from datamodel import Order, OrderDepth


_BASE_PATH = Path(__file__).with_name("pepper_benchmark_push__best_locked.py")
_BASE_SPEC = importlib.util.spec_from_file_location("pepper_benchmark_push__best_locked", _BASE_PATH)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load base trader from {_BASE_PATH}")

_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)


class Trader(_BASE_MODULE.Trader):
    IPR_CORE_TARGET = 66
    IPR_COMPLETION_BID_DISTANCE = 2
    IPR_COMPLETION_BID_SIZE = 3
    IPR_COMPLETION_WINDOW_START = 66_666
    IPR_COMPLETION_WINDOW_END = 100_000

    def _completion_bid_qty(
        self,
        timestamp: int,
        working_position: int,
        primary_bid_qty: int,
        limit: int,
        spread: int,
    ) -> int:
        if not (self.IPR_COMPLETION_WINDOW_START <= timestamp < self.IPR_COMPLETION_WINDOW_END):
            return 0
        if spread <= self.IPR_COMPLETION_BID_DISTANCE:
            return 0

        shortfall_to_core = self.IPR_CORE_TARGET - working_position
        if shortfall_to_core <= 0:
            return 0

        remaining_capacity = limit - working_position - primary_bid_qty
        if remaining_capacity <= 0:
            return 0

        return max(
            0,
            min(
                self.IPR_COMPLETION_BID_SIZE,
                shortfall_to_core,
                remaining_capacity,
            ),
        )

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

        if (not sold_this_tick) and working_position < limit and spread > 2:
            primary_bid_price = min(best_bid + 1, best_ask - 1)
            primary_bid_qty = min(self.IPR_PASSIVE_BID_SIZE, limit - working_position)
            if primary_bid_qty > 0 and primary_bid_price < best_ask:
                orders.append(Order(product, primary_bid_price, primary_bid_qty))

                completion_bid_price = min(best_bid + self.IPR_COMPLETION_BID_DISTANCE, best_ask - 1)
                completion_bid_qty = 0
                if completion_bid_price > primary_bid_price and completion_bid_price < best_ask:
                    completion_bid_qty = self._completion_bid_qty(
                        timestamp,
                        working_position,
                        primary_bid_qty,
                        limit,
                        spread,
                    )
                if completion_bid_qty > 0:
                    orders.append(Order(product, completion_bid_price, completion_bid_qty))

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
