"""Round 1 path-anchor trader.

Canonical Round 1 implementation for the current best historical strategy.
Older reference files are kept alongside it for provenance and comparison.
"""

from datamodel import Order, OrderDepth, TradingState
from typing import Any, Dict, List, Optional, Tuple
import json
import math


class Trader:
    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    # ------------------------------------------------------------------
    # ASH_COATED_OSMIUM: keep the stronger fixed-fair mean reversion leg.
    # ------------------------------------------------------------------
    ACO_FAIR_VALUE = 10000
    ACO_TAKE_EDGE = 0.0
    ACO_REDUCE_EDGE = 1.0
    ACO_PENNY_EDGE = 1.5
    ACO_INVENTORY_SKEW_PER_UNIT = 0.06
    ACO_MAX_POST_SIZE = 19
    ACO_PASSIVE_OFFSET = 3.5

    # ------------------------------------------------------------------
    # INTARIAN_PEPPER_ROOT: normalized path-anchor model.
    #
    # Base idea:
    # - replace the Kalman fair value with a deterministic intraday path anchor
    # - keep the stronger execution, inventory control, and flow-signal logic
    # - let current book/trade signals perturb the path anchor rather than define it
    # ------------------------------------------------------------------
    IPR_DRIFT_PER_TIMESTAMP = 0.001
    IPR_FORWARD_DRIFT = 1.15
    IPR_ANCHOR_UPDATE_ALPHA = 0.03
    IPR_WALL_NORM_ALPHA = 0.15
    IPR_PATH_SIGNAL_WEIGHT = 0.95
    IPR_IMBALANCE_WEIGHT = 0.10

    IPR_TAKE_EDGE = 1.6
    IPR_REDUCE_EDGE = 0.6
    IPR_PENNY_EDGE = 0.9
    IPR_INVENTORY_SKEW_PER_UNIT = 0.03
    IPR_PASSIVE_OFFSET = 3.0
    IPR_MAX_POST_SIZE = 10

    IPR_TRADE_SIGNAL_DECAY = 0.92
    IPR_TRADE_SIGNAL_UNIT = 5.0
    IPR_TRADE_SIGNAL_MAX = 3.0
    IPR_TRADE_FAIR_SHIFT = 0.28

    IPR_CANCEL_SIGNAL_DECAY = 0.84
    IPR_CANCEL_SIGNAL_MAX = 2.5
    IPR_CANCEL_FAIR_SHIFT = 0.09
    IPR_CANCEL_EDGE_SKEW = 0.08
    IPR_CANCEL_PASSIVE_SKEW = 0.10

    def run(self, state: TradingState):
        saved_state = self._load_state(state.traderData)
        last_ts = saved_state.get("last_ts")
        day_reset = last_ts is not None and state.timestamp < last_ts

        ipr_depth = state.order_depths.get("INTARIAN_PEPPER_ROOT", OrderDepth())
        ipr_trades = state.market_trades.get("INTARIAN_PEPPER_ROOT", [])

        ipr_trade_signal = self._update_trade_signal(
            ipr_depth,
            ipr_trades,
            float(saved_state.get("ipr_trade_signal", 0.0)),
            self.IPR_TRADE_SIGNAL_DECAY,
            self.IPR_TRADE_SIGNAL_UNIT,
            self.IPR_TRADE_SIGNAL_MAX,
        )
        ipr_cancel_signal, ipr_snapshot = self._update_cancel_signal(
            ipr_depth,
            ipr_trades,
            float(saved_state.get("ipr_cancel_signal", 0.0)),
            saved_state.get("ipr_snapshot", {}),
            self.IPR_CANCEL_SIGNAL_DECAY,
            self.IPR_CANCEL_SIGNAL_MAX,
        )

        result: Dict[str, List[Order]] = {}

        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self.trade_aco_mean_reversion(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
            )

        ipr_anchor = saved_state.get("ipr_anchor")
        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            ipr_orders, ipr_anchor = self.trade_ipr_normalized(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                ipr_anchor,
                state.timestamp,
                day_reset,
                ipr_trade_signal,
                ipr_cancel_signal,
            )
            result["INTARIAN_PEPPER_ROOT"] = ipr_orders

        trader_data = json.dumps(
            {
                "ipr_trade_signal": ipr_trade_signal,
                "ipr_cancel_signal": ipr_cancel_signal,
                "ipr_snapshot": ipr_snapshot,
                "ipr_anchor": ipr_anchor,
                "last_ts": state.timestamp,
            },
            separators=(",", ":"),
        )
        return result, 0, trader_data

    def _load_state(self, trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return {
                "ipr_trade_signal": 0.0,
                "ipr_cancel_signal": 0.0,
                "ipr_snapshot": {},
                "ipr_anchor": None,
                "last_ts": None,
            }

        try:
            payload = json.loads(trader_data)
        except Exception:
            return {
                "ipr_trade_signal": 0.0,
                "ipr_cancel_signal": 0.0,
                "ipr_snapshot": {},
                "ipr_anchor": None,
                "last_ts": None,
            }

        return {
            "ipr_trade_signal": float(payload.get("ipr_trade_signal", 0.0)),
            "ipr_cancel_signal": float(payload.get("ipr_cancel_signal", 0.0)),
            "ipr_snapshot": payload.get("ipr_snapshot", {}),
            "ipr_anchor": payload.get("ipr_anchor"),
            "last_ts": payload.get("last_ts"),
        }

    def _clip(self, value: float, max_abs: float) -> float:
        return max(-max_abs, min(max_abs, value))

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

    def _infer_trade_side(self, price: float, best_bid: int, best_ask: int) -> int:
        if price >= best_ask:
            return 1
        if price <= best_bid:
            return -1

        mid = 0.5 * (best_bid + best_ask)
        if price > mid:
            return 1
        if price < mid:
            return -1
        return 0

    def _update_trade_signal(
        self,
        order_depth: OrderDepth,
        market_trades: List[Any],
        previous_signal: float,
        decay: float,
        signal_unit: float,
        max_signal: float,
    ) -> float:
        signal = decay * previous_signal
        state = self._book_state(order_depth)
        if state is None or not market_trades:
            return self._clip(signal, max_signal)

        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        touch_mid = 0.5 * (best_bid + best_ask)
        half_spread = max(1.0, 0.5 * (best_ask - best_bid))

        total_qty = 0
        signed_qty = 0.0
        vwap_numerator = 0.0

        for trade in market_trades:
            qty = abs(int(getattr(trade, "quantity", 0)))
            if qty <= 0:
                continue

            price = float(getattr(trade, "price", touch_mid))
            side = self._infer_trade_side(price, best_bid, best_ask)

            total_qty += qty
            signed_qty += side * qty
            vwap_numerator += price * qty

        if total_qty <= 0:
            return self._clip(signal, max_signal)

        imbalance = signed_qty / float(total_qty)
        vwap = vwap_numerator / float(total_qty)
        price_bias = self._clip((vwap - touch_mid) / half_spread, 1.5)
        volume_scale = min(1.5, total_qty / signal_unit)
        instant_signal = volume_scale * (0.7 * imbalance + 0.3 * price_bias)

        signal += instant_signal
        return self._clip(signal, max_signal)

    def _snapshot(self, order_depth: OrderDepth) -> Dict[str, int]:
        state = self._book_state(order_depth)
        if state is None:
            return {}

        buy_orders = state["buy_orders"]
        sell_orders = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        bid_wall = int(state["bid_wall"])
        ask_wall = int(state["ask_wall"])

        return {
            "best_bid": best_bid,
            "best_bid_size": int(buy_orders[best_bid]),
            "best_ask": best_ask,
            "best_ask_size": int(sell_orders[best_ask]),
            "bid_wall": bid_wall,
            "bid_wall_size": int(buy_orders[bid_wall]),
            "ask_wall": ask_wall,
            "ask_wall_size": int(sell_orders[ask_wall]),
            "spread": int(state["spread"]),
        }

    def _update_cancel_signal(
        self,
        order_depth: OrderDepth,
        market_trades: List[Any],
        previous_signal: float,
        previous_snapshot: Dict[str, int],
        decay: float,
        max_signal: float,
    ) -> Tuple[float, Dict[str, int]]:
        signal = decay * previous_signal
        state = self._book_state(order_depth)
        current_snapshot = self._snapshot(order_depth)

        if state is None or not previous_snapshot:
            return self._clip(signal, max_signal), current_snapshot

        buy_orders = state["buy_orders"]
        sell_orders = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        touch_mid = 0.5 * (best_bid + best_ask)

        bid_trade_best = 0
        bid_trade_wall = 0
        ask_trade_best = 0
        ask_trade_wall = 0
        total_trade_qty = 0

        prev_best_bid = int(previous_snapshot.get("best_bid", 0))
        prev_best_ask = int(previous_snapshot.get("best_ask", 0))
        prev_bid_wall = int(previous_snapshot.get("bid_wall", 0))
        prev_ask_wall = int(previous_snapshot.get("ask_wall", 0))

        for trade in market_trades:
            qty = abs(int(getattr(trade, "quantity", 0)))
            if qty <= 0:
                continue

            price = float(getattr(trade, "price", touch_mid))
            side = self._infer_trade_side(price, best_bid, best_ask)
            total_trade_qty += qty

            if side < 0:
                if prev_best_bid and price <= prev_best_bid:
                    bid_trade_best += qty
                if prev_bid_wall and price <= prev_bid_wall:
                    bid_trade_wall += qty
            elif side > 0:
                if prev_best_ask and price >= prev_best_ask:
                    ask_trade_best += qty
                if prev_ask_wall and price >= prev_ask_wall:
                    ask_trade_wall += qty

        prev_best_bid_size = int(previous_snapshot.get("best_bid_size", 0))
        prev_best_ask_size = int(previous_snapshot.get("best_ask_size", 0))
        prev_bid_wall_size = int(previous_snapshot.get("bid_wall_size", 0))
        prev_ask_wall_size = int(previous_snapshot.get("ask_wall_size", 0))

        curr_best_bid_size = int(buy_orders.get(prev_best_bid, 0)) if prev_best_bid else 0
        curr_best_ask_size = int(sell_orders.get(prev_best_ask, 0)) if prev_best_ask else 0
        curr_bid_wall_size = int(buy_orders.get(prev_bid_wall, 0)) if prev_bid_wall else 0
        curr_ask_wall_size = int(sell_orders.get(prev_ask_wall, 0)) if prev_ask_wall else 0

        bid_best_delta = curr_best_bid_size - max(prev_best_bid_size - bid_trade_best, 0)
        bid_wall_delta = curr_bid_wall_size - max(prev_bid_wall_size - bid_trade_wall, 0)
        ask_best_delta = curr_best_ask_size - max(prev_best_ask_size - ask_trade_best, 0)
        ask_wall_delta = curr_ask_wall_size - max(prev_ask_wall_size - ask_trade_wall, 0)

        weighted_delta = (
            0.7 * bid_best_delta
            + 1.0 * bid_wall_delta
            - 0.7 * ask_best_delta
            - 1.0 * ask_wall_delta
        )
        reference_size = max(
            10.0,
            float(
                prev_best_bid_size
                + prev_best_ask_size
                + prev_bid_wall_size
                + prev_ask_wall_size
            ),
        )
        no_trade_conviction = max(0.25, 1.0 - min(1.0, total_trade_qty / reference_size))
        signal += 3.0 * no_trade_conviction * (weighted_delta / reference_size)
        return self._clip(signal, max_signal), current_snapshot

    def trade_aco_mean_reversion(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        product = "ASH_COATED_OSMIUM"
        limit = self.LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders

        buy_orders: Dict[int, int] = state["buy_orders"]
        sell_orders: Dict[int, int] = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        spread = int(state["spread"])

        fair_value = float(self.ACO_FAIR_VALUE)
        working_position = position

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

        return orders

    def trade_ipr_normalized(
        self,
        order_depth: OrderDepth,
        position: int,
        anchor: Optional[float],
        timestamp: int,
        day_reset: bool,
        trade_signal: float,
        cancel_signal: float,
    ) -> Tuple[List[Order], Optional[float]]:
        orders: List[Order] = []
        product = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders, anchor

        buy_orders: Dict[int, int] = state["buy_orders"]
        sell_orders: Dict[int, int] = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        bid_wall = int(state["bid_wall"])
        ask_wall = int(state["ask_wall"])
        spread = int(state["spread"])

        touch_mid = 0.5 * (best_bid + best_ask)
        wall_mid = 0.5 * (bid_wall + ask_wall)

        observed_anchor = touch_mid - self.IPR_DRIFT_PER_TIMESTAMP * timestamp
        if anchor is None or day_reset:
            anchor = observed_anchor
        else:
            anchor = (
                (1.0 - self.IPR_ANCHOR_UPDATE_ALPHA) * float(anchor)
                + self.IPR_ANCHOR_UPDATE_ALPHA * observed_anchor
            )

        path_fair = anchor + self.IPR_DRIFT_PER_TIMESTAMP * timestamp
        norm_center = (
            (1.0 - self.IPR_WALL_NORM_ALPHA) * touch_mid
            + self.IPR_WALL_NORM_ALPHA * wall_mid
        )

        bid_size = abs(int(order_depth.buy_orders[best_bid]))
        ask_size = abs(int(order_depth.sell_orders[best_ask]))
        imbalance = 0.0
        if bid_size + ask_size > 0:
            imbalance = (bid_size - ask_size) / float(bid_size + ask_size)

        path_signal = path_fair - norm_center
        fair_exec = (
            norm_center
            + self.IPR_FORWARD_DRIFT
            + self.IPR_PATH_SIGNAL_WEIGHT * path_signal
            + self.IPR_IMBALANCE_WEIGHT * imbalance
            + self.IPR_TRADE_FAIR_SHIFT * trade_signal
            + self.IPR_CANCEL_FAIR_SHIFT * cancel_signal
        )

        if spread >= 13:
            take_edge = self.IPR_TAKE_EDGE
            reduce_edge = self.IPR_REDUCE_EDGE
            penny_edge = self.IPR_PENNY_EDGE
            passive_offset = self.IPR_PASSIVE_OFFSET
        elif spread >= 8:
            take_edge = self.IPR_TAKE_EDGE + 0.4
            reduce_edge = self.IPR_REDUCE_EDGE + 0.2
            penny_edge = self.IPR_PENNY_EDGE + 0.3
            passive_offset = self.IPR_PASSIVE_OFFSET + 0.8
        else:
            take_edge = self.IPR_TAKE_EDGE + 0.8
            reduce_edge = self.IPR_REDUCE_EDGE + 0.4
            penny_edge = self.IPR_PENNY_EDGE + 0.6
            passive_offset = self.IPR_PASSIVE_OFFSET + 1.5

        trend_bias = self._clip((fair_exec - touch_mid) / 2.0, 2.0)
        buy_take_edge = max(
            0.6,
            take_edge - 0.25 * trend_bias - self.IPR_CANCEL_EDGE_SKEW * cancel_signal,
        )
        sell_take_edge = max(
            0.6,
            take_edge + 0.25 * trend_bias + self.IPR_CANCEL_EDGE_SKEW * cancel_signal,
        )
        buy_passive_offset = max(
            1.0,
            passive_offset - 0.20 * trend_bias - self.IPR_CANCEL_PASSIVE_SKEW * cancel_signal,
        )
        sell_passive_offset = max(
            1.0,
            passive_offset + 0.20 * trend_bias + self.IPR_CANCEL_PASSIVE_SKEW * cancel_signal,
        )

        working_position = position

        for ask_price, ask_volume in sell_orders.items():
            buy_capacity = limit - working_position
            if buy_capacity <= 0:
                break

            fair_skewed = fair_exec - self.IPR_INVENTORY_SKEW_PER_UNIT * working_position

            if ask_price <= fair_skewed - buy_take_edge:
                qty = min(ask_volume, buy_capacity)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty
            elif working_position < 0 and ask_price <= fair_skewed - reduce_edge:
                qty = min(ask_volume, buy_capacity, abs(working_position))
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty

        for bid_price, bid_volume in buy_orders.items():
            sell_capacity = limit + working_position
            if sell_capacity <= 0:
                break

            fair_skewed = fair_exec - self.IPR_INVENTORY_SKEW_PER_UNIT * working_position

            if bid_price >= fair_skewed + sell_take_edge:
                qty = min(bid_volume, sell_capacity)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    working_position -= qty
            elif working_position > 0 and bid_price >= fair_skewed + reduce_edge:
                qty = min(bid_volume, sell_capacity, working_position)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    working_position -= qty

        fair_skewed = fair_exec - self.IPR_INVENTORY_SKEW_PER_UNIT * working_position
        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)

        bid_size_post = self._cap_post_size(self.IPR_MAX_POST_SIZE, working_position, "buy", buy_capacity)
        ask_size_post = self._cap_post_size(self.IPR_MAX_POST_SIZE, working_position, "sell", sell_capacity)

        spread_now = best_ask - best_bid
        penny_bid = best_bid + 1 if spread_now > 1 else best_bid
        penny_ask = best_ask - 1 if spread_now > 1 else best_ask

        edge_buy = fair_skewed - penny_bid
        edge_sell = penny_ask - fair_skewed

        if edge_buy >= penny_edge:
            bid_price = penny_bid
        else:
            bid_price = math.floor(fair_skewed - buy_passive_offset)

        if edge_sell >= penny_edge:
            ask_price = penny_ask
        else:
            ask_price = math.ceil(fair_skewed + sell_passive_offset)

        bid_price = min(int(bid_price), best_ask - 1)
        ask_price = max(int(ask_price), best_bid + 1)

        if bid_price >= ask_price:
            bid_price = best_bid
            ask_price = best_ask

        if bid_size_post > 0:
            orders.append(Order(product, int(bid_price), bid_size_post))
        if ask_size_post > 0:
            orders.append(Order(product, int(ask_price), -ask_size_post))

        return orders, anchor
