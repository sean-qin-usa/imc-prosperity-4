"""Unified PEPPER soft-close candidate.

Keeps the unified production base and only blocks very-late PEPPER inventory
re-extensions above the core target. This is tuned to the official `163569`
shape, where the strategy sat at +64 for most of the close and only added a
small extra passive fill at 99.5k.
"""

import importlib.util
from pathlib import Path
from typing import List, Optional, Tuple

from datamodel import Order, OrderDepth


_BASE_PATH = Path(__file__).with_name("unified_strategy.py")
_BASE_SPEC = importlib.util.spec_from_file_location("unified_strategy", _BASE_PATH)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load base trader from {_BASE_PATH}")

_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)
_BaseTrader = _BASE_MODULE.Trader


class Trader(_BaseTrader):
    IPR_LATE_EXTENSION_STOP_START = 99500
    IPR_LATE_EXTENSION_CAP = 64

    def trade_ipr_core_band(
        self,
        order_depth: OrderDepth,
        position: int,
        anchor: Optional[float],
        timestamp: int,
        day_reset: bool,
        ipr_var: float,
    ) -> Tuple[List[Order], Optional[float]]:
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
        late_buy_cap = (
            self.IPR_LATE_EXTENSION_CAP
            if timestamp >= self.IPR_LATE_EXTENSION_STOP_START
            else limit
        )

        if timestamp <= self.IPR_EARLY_TAKE_WINDOW:
            for ask_price, ask_volume in sell_orders.items():
                if working_position >= self.IPR_EARLY_TAKE_TARGET:
                    break
                buy_capacity = min(limit, late_buy_cap) - working_position
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

        buy_capacity = max(0, min(limit, late_buy_cap) - working_position)
        if buy_capacity > 0 and best_ask <= benchmark_path + self.IPR_BAND_RELOAD_EDGE:
            qty = min(buy_capacity, self.IPR_BAND_QTY, abs(int(sell_orders[best_ask])))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                working_position += qty

        passive_buy_capacity = max(0, min(limit, late_buy_cap) - working_position)
        if (not sold_this_tick) and passive_buy_capacity > 0 and spread > self.IPR_PASSIVE_BID_DISTANCE:
            bid_price = min(best_bid + self.IPR_PASSIVE_BID_DISTANCE, best_ask - 1)
            bid_qty = min(self.IPR_PASSIVE_BID_SIZE, passive_buy_capacity)
            if bid_qty > 0 and bid_price < best_ask:
                orders.append(Order(product, bid_price, bid_qty))

        sigma = max(1.0, float(ipr_var) ** 0.5)
        residual = touch_mid - benchmark_path
        zscore = residual / sigma
        current_buy = sum(max(0, int(order.quantity)) for order in orders)
        current_sell = sum(max(0, -int(order.quantity)) for order in orders)
        working_after_orders = position + current_buy - current_sell
        extra_buy_capacity = max(0, min(limit, late_buy_cap) - working_after_orders)
        if (
            timestamp > self.IPR_EARLY_TAKE_WINDOW
            and extra_buy_capacity > 0
            and zscore <= self.IPR_BOTTOM_ZSCORE_THRESHOLD
            and best_ask <= benchmark_path + self.IPR_BOTTOM_PATH_CAP
        ):
            qty = min(
                self.IPR_BOTTOM_EXTRA_QTY,
                extra_buy_capacity,
                abs(int(sell_orders[best_ask])),
            )
            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        return orders, anchor
