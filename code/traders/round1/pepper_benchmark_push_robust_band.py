"""Benchmark-push PEPPER carry with a small adaptive core band.

This variant keeps the structural edge from the best benchmark-push family:
- deterministic PEPPER drift path
- core-long carry inventory
- trim rich deviations and reload cheap deviations

It deliberately avoids leaning on a single fixed PEPPER core target. Instead it
uses a narrow adaptive band around the empirically stable 66-68 region and lets
the opening path anchor recenter slightly early in the day.
"""

import importlib.util
import json
import math
from pathlib import Path
from typing import Dict, List, Optional

from datamodel import Order, OrderDepth, TradingState


_BASE_PATH = Path(__file__).with_name("pepper_benchmark_push__best_locked.py")
_BASE_SPEC = importlib.util.spec_from_file_location(
    "pepper_benchmark_push__best_locked",
    _BASE_PATH,
)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load base trader from {_BASE_PATH}")

_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)


class Trader(_BASE_MODULE.Trader):
    IPR_BASE_CORE_TARGET = 67
    IPR_CORE_TARGET_BAND = 1
    IPR_CHEAP_ZSCORE = -0.45
    IPR_RICH_ZSCORE = 0.80

    IPR_ANCHOR_UPDATE_END = 12_000
    IPR_ANCHOR_UPDATE_ALPHA = 0.02
    IPR_ANCHOR_RESIDUAL_CLIP = 3.0

    IPR_RICH_RELOAD_QTY = 2
    IPR_RICH_PASSIVE_BID_SIZE = 4

    def _update_ipr_anchor(
        self,
        anchor: Optional[float],
        touch_mid: float,
        timestamp: int,
        day_reset: bool,
    ) -> float:
        observed_anchor = touch_mid - self.IPR_DRIFT_PER_TIMESTAMP * timestamp
        if anchor is None or day_reset:
            return observed_anchor

        updated_anchor = float(anchor)
        if timestamp <= self.IPR_ANCHOR_UPDATE_END:
            delta = observed_anchor - updated_anchor
            delta = max(-self.IPR_ANCHOR_RESIDUAL_CLIP, min(self.IPR_ANCHOR_RESIDUAL_CLIP, delta))
            updated_anchor += self.IPR_ANCHOR_UPDATE_ALPHA * delta
        return updated_anchor

    def _adaptive_core_target(self, zscore: float) -> int:
        target = self.IPR_BASE_CORE_TARGET
        if zscore <= self.IPR_CHEAP_ZSCORE:
            target += self.IPR_CORE_TARGET_BAND
        elif zscore >= self.IPR_RICH_ZSCORE:
            target -= self.IPR_CORE_TARGET_BAND

        low = self.IPR_BASE_CORE_TARGET - self.IPR_CORE_TARGET_BAND
        high = self.IPR_BASE_CORE_TARGET + self.IPR_CORE_TARGET_BAND
        return max(low, min(high, target))

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
                ipr_anchor = self._update_ipr_anchor(
                    ipr_anchor,
                    touch_mid,
                    state.timestamp,
                    day_reset,
                )
                residual = touch_mid - (
                    float(ipr_anchor) + self.IPR_DRIFT_PER_TIMESTAMP * state.timestamp
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
                False,
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
            anchor = touch_mid - self.IPR_DRIFT_PER_TIMESTAMP * timestamp

        benchmark_path = float(anchor) + self.IPR_DRIFT_PER_TIMESTAMP * timestamp
        sigma = max(1.0, math.sqrt(max(0.0, float(ipr_var))))
        residual = touch_mid - benchmark_path
        zscore = residual / sigma
        core_target = self._adaptive_core_target(zscore)

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

        excess_inventory = max(0, working_position - core_target)
        if excess_inventory > 0 and best_bid >= benchmark_path + self.IPR_BAND_SELL_EDGE:
            qty = min(excess_inventory, self.IPR_BAND_QTY, abs(int(buy_orders[best_bid])))
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                working_position -= qty
                sold_this_tick = True

        if working_position < limit and best_ask <= benchmark_path + self.IPR_BAND_RELOAD_EDGE:
            reload_qty_cap = self.IPR_BAND_QTY
            if working_position >= core_target and zscore >= self.IPR_RICH_ZSCORE:
                reload_qty_cap = self.IPR_RICH_RELOAD_QTY
            qty = min(limit - working_position, reload_qty_cap, abs(int(sell_orders[best_ask])))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                working_position += qty

        if (not sold_this_tick) and working_position < limit and spread > 2:
            bid_price = min(best_bid + 1, best_ask - 1)
            bid_qty = min(self.IPR_PASSIVE_BID_SIZE, limit - working_position)
            shortfall_to_core = max(0, core_target - working_position)
            if shortfall_to_core <= 0 and zscore >= self.IPR_RICH_ZSCORE:
                bid_qty = min(bid_qty, self.IPR_RICH_PASSIVE_BID_SIZE)
            elif shortfall_to_core > 0:
                bid_qty = min(bid_qty, max(4, shortfall_to_core))
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
            dip_qty_cap = self.IPR_BOTTOM_EXTRA_QTY
            if working_after_orders < core_target:
                dip_qty_cap += min(2, core_target - working_after_orders)
            qty = min(
                dip_qty_cap,
                limit - working_after_orders,
                abs(int(sell_orders[best_ask])),
            )
            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        return orders, anchor
