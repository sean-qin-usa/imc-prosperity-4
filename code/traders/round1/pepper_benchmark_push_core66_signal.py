"""Core-66 benchmark-push variant with residual and imbalance-aware PEPPER logic."""

import importlib.util
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from datamodel import Order, OrderDepth


_BASE_PATH = Path(__file__).with_name("pepper_benchmark_push__best_locked.py")
_BASE_SPEC = importlib.util.spec_from_file_location("pepper_benchmark_push__best_locked", _BASE_PATH)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load base trader from {_BASE_PATH}")

_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)


class Trader(_BASE_MODULE.Trader):
    IPR_CORE_TARGET = 66

    IPR_IMBALANCE_CLIP = 0.75
    IPR_IMBALANCE_PATH_SHIFT = 0.75
    IPR_NEG_IMBALANCE_RELOAD_PENALTY = 0.35
    IPR_POS_IMBALANCE_RELOAD_BONUS = 0.35
    IPR_RELOAD_MAX_ZSCORE = 0.90
    IPR_RELOAD_DIP_SIZE_BONUS = 2
    IPR_RELOAD_IMBALANCE_THRESHOLD = 0.35

    IPR_PASSIVE_MIN_IMBALANCE = -0.35
    IPR_PASSIVE_MAX_ZSCORE = 1.00
    IPR_PASSIVE_POS_IMBALANCE_THRESHOLD = 0.45
    IPR_PASSIVE_POS_SIZE_BONUS = 2
    IPR_PASSIVE_DIP_ZSCORE = -0.80
    IPR_PASSIVE_DIP_SIZE_BONUS = 2

    IPR_DIP_IMBALANCE_THRESHOLD = 0.35
    IPR_DIP_SIZE_BONUS = 2

    def _book_state(self, order_depth: OrderDepth) -> Optional[Dict[str, Any]]:
        state = super()._book_state(order_depth)
        if state is None:
            return None

        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        best_bid_qty = abs(int(state["buy_orders"][best_bid]))
        best_ask_qty = abs(int(state["sell_orders"][best_ask]))
        denom = best_bid_qty + best_ask_qty
        imbalance = 0.0 if denom <= 0 else (best_bid_qty - best_ask_qty) / float(denom)
        state["l1_imbalance"] = max(-self.IPR_IMBALANCE_CLIP, min(self.IPR_IMBALANCE_CLIP, imbalance))
        return state

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
        imbalance = float(state.get("l1_imbalance", 0.0))

        touch_mid = 0.5 * (best_bid + best_ask)
        if anchor is None or day_reset:
            anchor = touch_mid

        benchmark_path = float(anchor) + self.IPR_DRIFT_PER_TIMESTAMP * timestamp
        positive_imbalance = max(0.0, imbalance)
        signal_path = benchmark_path + self.IPR_IMBALANCE_PATH_SHIFT * positive_imbalance
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

        reload_edge = (
            self.IPR_BAND_RELOAD_EDGE
            + self.IPR_POS_IMBALANCE_RELOAD_BONUS * positive_imbalance
            - self.IPR_NEG_IMBALANCE_RELOAD_PENALTY * max(0.0, -imbalance)
        )
        if (
            working_position < limit
            and zscore <= self.IPR_RELOAD_MAX_ZSCORE
            and best_ask <= signal_path + reload_edge
        ):
            reload_qty = self.IPR_BAND_QTY
            if zscore <= self.IPR_BOTTOM_ZSCORE_THRESHOLD or imbalance >= self.IPR_RELOAD_IMBALANCE_THRESHOLD:
                reload_qty += self.IPR_RELOAD_DIP_SIZE_BONUS
            qty = min(limit - working_position, reload_qty, abs(int(sell_orders[best_ask])))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                working_position += qty

        if (
            (not sold_this_tick)
            and working_position < limit
            and spread > 2
            and zscore <= self.IPR_PASSIVE_MAX_ZSCORE
            and imbalance >= self.IPR_PASSIVE_MIN_IMBALANCE
        ):
            bid_price = min(best_bid + 1, best_ask - 1)
            bid_qty = self.IPR_PASSIVE_BID_SIZE
            if imbalance >= self.IPR_PASSIVE_POS_IMBALANCE_THRESHOLD:
                bid_qty += self.IPR_PASSIVE_POS_SIZE_BONUS
            if zscore <= self.IPR_PASSIVE_DIP_ZSCORE:
                bid_qty += self.IPR_PASSIVE_DIP_SIZE_BONUS
            bid_qty = min(bid_qty, limit - working_position)
            if bid_qty > 0 and bid_price < best_ask:
                orders.append(Order(product, bid_price, bid_qty))

        current_buy = sum(max(0, int(order.quantity)) for order in orders)
        current_sell = sum(max(0, -int(order.quantity)) for order in orders)
        working_after_orders = position + current_buy - current_sell
        dip_qty = self.IPR_BOTTOM_EXTRA_QTY
        if imbalance >= self.IPR_DIP_IMBALANCE_THRESHOLD:
            dip_qty += self.IPR_DIP_SIZE_BONUS
        if (
            timestamp > self.IPR_EARLY_TAKE_WINDOW
            and working_after_orders < limit
            and zscore <= self.IPR_BOTTOM_ZSCORE_THRESHOLD
            and best_ask <= signal_path + self.IPR_BOTTOM_PATH_CAP
        ):
            qty = min(
                dip_qty,
                limit - working_after_orders,
                abs(int(sell_orders[best_ask])),
            )
            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        return orders, anchor
