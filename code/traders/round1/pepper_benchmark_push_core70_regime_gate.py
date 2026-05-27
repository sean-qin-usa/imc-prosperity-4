"""Core-70 PEPPER carry with regime-gated long acquisition.

This branch keeps the current balanced ACO settings and the stronger
`core70_completion_early` PEPPER baseline, but rewrites the PEPPER execution
shape into clearer regimes:

- build: still lean hard on the proven `+1` passive quote while under core
- carry: stop stacking visible reloads and passive buys on the same tick
- harvest: suppress new longs when PEPPER is already full and rich to path

The goal is to test a structural execution gate around the existing carry path,
not another narrow parameter tweak.
"""

import importlib.util
from pathlib import Path
from typing import List, Optional

from datamodel import Order, OrderDepth


_BASE_PATH = Path(__file__).with_name("pepper_benchmark_push_core70_completion_early.py")
_BASE_SPEC = importlib.util.spec_from_file_location(
    "pepper_benchmark_push_core70_completion_early",
    _BASE_PATH,
)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load base trader from {_BASE_PATH}")

_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)


class Trader(_BASE_MODULE.Trader):
    # Only suppress the extra deep-dip add when another visible PEPPER buy
    # already happened and the branch is not materially below its carry target.
    IPR_BOTTOM_STACK_SHORTFALL = 4

    # Once PEPPER is at/near core, only reload visibly on clearer cheap-to-path
    # states. The main `+1` passive quote stays intact; the structural change is
    # about reducing stacked visible long sources around that quote.
    IPR_CHEAP_ZSCORE = -0.65
    IPR_CARRY_RELOAD_EDGE = 0.0
    IPR_CARRY_RELOAD_QTY = 3

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
        sigma = max(1.0, (max(0.0, float(ipr_var))) ** 0.5)
        residual = touch_mid - benchmark_path
        zscore = residual / sigma

        working_position = position
        sold_this_tick = False
        bought_visibly_this_tick = False

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
                    bought_visibly_this_tick = True

        excess_inventory = max(0, working_position - self.IPR_CORE_TARGET)
        if excess_inventory > 0 and best_bid >= benchmark_path + self.IPR_BAND_SELL_EDGE:
            qty = min(excess_inventory, self.IPR_BAND_QTY, abs(int(buy_orders[best_bid])))
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                working_position -= qty
                sold_this_tick = True

        shortfall_to_core = max(0, self.IPR_CORE_TARGET - working_position)
        cheap_to_path = zscore <= self.IPR_CHEAP_ZSCORE

        reload_qty_cap = 0
        reload_edge = self.IPR_BAND_RELOAD_EDGE
        if shortfall_to_core > 0:
            reload_qty_cap = self.IPR_BAND_QTY
        elif cheap_to_path and working_position < self.IPR_CORE_TARGET + 1:
            reload_qty_cap = self.IPR_CARRY_RELOAD_QTY
            reload_edge = self.IPR_CARRY_RELOAD_EDGE

        if reload_qty_cap > 0 and working_position < limit and best_ask <= benchmark_path + reload_edge:
            qty = min(limit - working_position, reload_qty_cap, abs(int(sell_orders[best_ask])))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                working_position += qty
                bought_visibly_this_tick = True

        if (not sold_this_tick) and working_position < limit and spread > 2:
            bid_qty = min(self.IPR_PASSIVE_BID_SIZE, limit - working_position)
            primary_bid_price = min(best_bid + 1, best_ask - 1)
            if bid_qty > 0 and primary_bid_price < best_ask:
                orders.append(Order(product, primary_bid_price, bid_qty))

                completion_bid_price = min(best_bid + self.IPR_COMPLETION_BID_DISTANCE, best_ask - 1)
                completion_bid_qty = 0
                if completion_bid_price > primary_bid_price and completion_bid_price < best_ask:
                    completion_bid_qty = self._completion_bid_qty(
                        timestamp,
                        working_position,
                        bid_qty,
                        limit,
                        spread,
                    )
                if completion_bid_qty > 0:
                    orders.append(Order(product, completion_bid_price, completion_bid_qty))

        current_buy = sum(max(0, int(order.quantity)) for order in orders)
        current_sell = sum(max(0, -int(order.quantity)) for order in orders)
        working_after_orders = position + current_buy - current_sell
        shortfall_after_orders = max(0, self.IPR_CORE_TARGET - working_after_orders)
        allow_bottom_stack = (not bought_visibly_this_tick) or (
            shortfall_after_orders > self.IPR_BOTTOM_STACK_SHORTFALL
        )
        if (
            timestamp > self.IPR_EARLY_TAKE_WINDOW
            and working_after_orders < limit
            and zscore <= self.IPR_BOTTOM_ZSCORE_THRESHOLD
            and best_ask <= benchmark_path + self.IPR_BOTTOM_PATH_CAP
            and allow_bottom_stack
        ):
            qty = min(
                self.IPR_BOTTOM_EXTRA_QTY,
                limit - working_after_orders,
                abs(int(sell_orders[best_ask])),
            )
            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        return orders, anchor
