"""Standalone hybrid: top_strat PEPPER with 235973 ACO sleeve.

This keeps the promoted `top_strat` PEPPER leg unchanged and swaps the ACO leg
to the EMA-taker-plus-benchmark-market-making variant from 235973.
"""

import json
import math
from typing import Any, Dict, List, Optional

from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    # ASH_COATED_OSMIUM: 235973 benchmark MM plus EMA taker sleeve.
    ACO_FAIR_VALUE = 10000
    ACO_TAKE_EDGE = 0.0
    ACO_REDUCE_EDGE = 0.0
    ACO_PENNY_EDGE = 1.5
    ACO_INVENTORY_SKEW_PER_UNIT = 0.04
    ACO_MAX_POST_SIZE = 20
    ACO_PASSIVE_OFFSET = 3.0

    ACO_TAKER_EMA_WINDOW_TS = 300000
    ACO_TAKER_EMA_INIT = 10000.0
    ACO_TAKER_BLEND_TO_STATIC = 0.5
    ACO_TAKER_ENTRY_EDGE = 1.0
    ACO_TAKER_REDUCE_EDGE = 0.0
    ACO_TAKER_POSITION_LIMIT = 24
    ACO_TAKER_MAX_ORDER_SIZE = 16

    # PEPPER benchmark-carry configuration from top_strat.
    IPR_DRIFT_PER_TIMESTAMP = 0.001
    IPR_EARLY_TAKE_TARGET = 64
    IPR_CORE_TARGET = 70
    IPR_BAND_SELL_EDGE = 3.0
    IPR_BAND_RELOAD_EDGE = 1.0
    IPR_BAND_QTY = 6
    IPR_PASSIVE_BID_SIZE = 10
    IPR_EARLY_TAKE_WINDOW = 500
    IPR_VAR_ALPHA = 0.06
    IPR_BOTTOM_ZSCORE_THRESHOLD = -1.10
    IPR_BOTTOM_EXTRA_QTY = 4
    IPR_BOTTOM_PATH_CAP = 1.5
    IPR_COMPLETION_BID_DISTANCE = 2
    IPR_COMPLETION_BID_SIZE = 3
    IPR_COMPLETION_WINDOW_START = 500
    IPR_COMPLETION_WINDOW_END = 33_333

    def run(self, state: TradingState):
        saved_state = self._load_state(state.traderData)
        last_ts = saved_state.get("last_ts")
        day_reset = last_ts is not None and state.timestamp < last_ts

        result: Dict[str, List[Order]] = {}

        aco_fair_value = (
            self.ACO_TAKER_EMA_INIT
            if day_reset
            else float(saved_state.get("aco_fair_value", self.ACO_TAKER_EMA_INIT))
        )
        aco_last_ts = None if day_reset else saved_state.get("aco_last_ts")

        if "ASH_COATED_OSMIUM" in state.order_depths:
            aco_orders, aco_fair_value, aco_last_ts = self.trade_aco_combined(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
                aco_fair_value,
                aco_last_ts,
                state.timestamp,
            )
            result["ASH_COATED_OSMIUM"] = aco_orders

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
                "aco_fair_value": aco_fair_value,
                "aco_last_ts": aco_last_ts,
                "ipr_anchor": ipr_anchor,
                "ipr_var": ipr_var,
                "last_ts": state.timestamp,
            },
            separators=(",", ":"),
        )
        return result, 0, trader_data

    def _load_state(self, trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return {
                "aco_fair_value": self.ACO_TAKER_EMA_INIT,
                "aco_last_ts": None,
                "ipr_anchor": None,
                "ipr_var": 9.0,
                "last_ts": None,
            }
        try:
            payload = json.loads(trader_data)
        except Exception:
            return {
                "aco_fair_value": self.ACO_TAKER_EMA_INIT,
                "aco_last_ts": None,
                "ipr_anchor": None,
                "ipr_var": 9.0,
                "last_ts": None,
            }
        return {
            "aco_fair_value": float(payload.get("aco_fair_value", self.ACO_TAKER_EMA_INIT)),
            "aco_last_ts": payload.get("aco_last_ts"),
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

    def trade_aco_combined(
        self,
        order_depth: OrderDepth,
        position: int,
        aco_fair_value: float,
        aco_last_ts: Optional[int],
        timestamp: int,
    ):
        orders: List[Order] = []
        product = "ASH_COATED_OSMIUM"
        limit = self.LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders, aco_fair_value, aco_last_ts

        buy_orders: Dict[int, int] = state["buy_orders"]
        sell_orders: Dict[int, int] = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        spread = int(state["spread"])

        mid = 0.5 * (best_bid + best_ask)
        if aco_last_ts is None or timestamp < int(aco_last_ts):
            aco_fair_value = float(aco_fair_value)
        else:
            dt = max(1, timestamp - int(aco_last_ts))
            alpha = 1.0 - math.exp(-float(dt) / float(self.ACO_TAKER_EMA_WINDOW_TS))
            aco_fair_value = float(aco_fair_value) + alpha * (mid - float(aco_fair_value))
        aco_last_ts = timestamp

        working_position = position

        taker_fair_value = (
            self.ACO_TAKER_BLEND_TO_STATIC * float(self.ACO_FAIR_VALUE)
            + (1.0 - self.ACO_TAKER_BLEND_TO_STATIC) * float(aco_fair_value)
        )

        if best_ask < taker_fair_value - self.ACO_TAKER_ENTRY_EDGE:
            buy_capacity = min(
                max(0, limit - working_position),
                max(0, self.ACO_TAKER_POSITION_LIMIT - working_position),
            )
            buy_qty = min(
                self.ACO_TAKER_MAX_ORDER_SIZE,
                buy_capacity,
                abs(int(sell_orders[best_ask])),
            )
            if buy_qty > 0:
                orders.append(Order(product, best_ask, buy_qty))
                working_position += buy_qty
        elif working_position < 0 and best_ask <= taker_fair_value + self.ACO_TAKER_REDUCE_EDGE:
            buy_capacity = min(
                max(0, limit - working_position),
                abs(working_position),
                self.ACO_TAKER_POSITION_LIMIT,
            )
            buy_qty = min(
                self.ACO_TAKER_MAX_ORDER_SIZE,
                buy_capacity,
                abs(int(sell_orders[best_ask])),
            )
            if buy_qty > 0:
                orders.append(Order(product, best_ask, buy_qty))
                working_position += buy_qty

        if best_bid > taker_fair_value + self.ACO_TAKER_ENTRY_EDGE:
            sell_capacity = min(
                max(0, limit + working_position),
                max(0, self.ACO_TAKER_POSITION_LIMIT + working_position),
            )
            sell_qty = min(
                self.ACO_TAKER_MAX_ORDER_SIZE,
                sell_capacity,
                abs(int(buy_orders[best_bid])),
            )
            if sell_qty > 0:
                orders.append(Order(product, best_bid, -sell_qty))
                working_position -= sell_qty
        elif working_position > 0 and best_bid >= taker_fair_value - self.ACO_TAKER_REDUCE_EDGE:
            sell_capacity = min(
                max(0, limit + working_position),
                abs(working_position),
                self.ACO_TAKER_POSITION_LIMIT,
            )
            sell_qty = min(
                self.ACO_TAKER_MAX_ORDER_SIZE,
                sell_capacity,
                abs(int(buy_orders[best_bid])),
            )
            if sell_qty > 0:
                orders.append(Order(product, best_bid, -sell_qty))
                working_position -= sell_qty

        fair_value = float(self.ACO_FAIR_VALUE)

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

        return orders, aco_fair_value, aco_last_ts

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
