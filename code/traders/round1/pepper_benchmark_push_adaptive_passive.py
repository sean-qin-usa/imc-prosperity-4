"""Benchmark-push variant with adaptive PEPPER passive bid distance.

Hypothesis:
- the current calibration favors `+1` inside on wider PEPPER spreads
- official probe evidence still argues that `+2` can matter in narrower regimes
- choose the passive distance from current spread and inventory regime instead of
  hard-coding one distance everywhere
"""

import importlib.util
import math
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
    IPR_PASSIVE_WIDE_SPREAD_THRESHOLD = 13
    IPR_PASSIVE_CORE_BUFFER = 8
    IPR_PASSIVE_NEG_ZSCORE_THRESHOLD = -0.35

    def _passive_bid_distance(
        self,
        spread: int,
        working_position: int,
        zscore: float,
    ) -> int:
        if spread >= self.IPR_PASSIVE_WIDE_SPREAD_THRESHOLD:
            return 1
        if working_position < (self.IPR_CORE_TARGET - self.IPR_PASSIVE_CORE_BUFFER):
            return 1
        if zscore <= self.IPR_PASSIVE_NEG_ZSCORE_THRESHOLD:
            return 1
        return 2

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
        sigma = max(1.0, math.sqrt(max(0.0, float(ipr_var))))
        residual = touch_mid - benchmark_path
        zscore = residual / sigma

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

        passive_distance = self._passive_bid_distance(spread, working_position, zscore)
        if (not sold_this_tick) and working_position < limit and spread > passive_distance:
            bid_price = min(best_bid + passive_distance, best_ask - 1)
            bid_qty = min(self.IPR_PASSIVE_BID_SIZE, limit - working_position)
            if bid_qty > 0 and bid_price < best_ask:
                orders.append(Order(product, bid_price, bid_qty))

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
