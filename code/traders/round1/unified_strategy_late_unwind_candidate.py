"""Unified PEPPER late-unwind candidate.

Keeps the current unified production base intact and narrows the experiment to
PEPPER late-session behavior: stop reloading late and actively drain inventory
into the close.
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
    IPR_NO_RELOAD_START = 93000
    IPR_LATE_UNWIND_START = 98000
    IPR_LATE_UNWIND_TARGET = 64
    IPR_LATE_UNWIND_MAX_QTY = 24
    IPR_FINAL_UNWIND_START = 98500
    IPR_FINAL_UNWIND_TARGET = 0
    IPR_FINAL_UNWIND_MAX_QTY = 80

    def _sell_into_bids(
        self,
        product: str,
        buy_orders: dict[int, int],
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

        sigma = max(1.0, float(ipr_var) ** 0.5)
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
