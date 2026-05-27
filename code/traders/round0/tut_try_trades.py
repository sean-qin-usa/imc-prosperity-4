from datamodel import OrderDepth, TradingState, Order
from typing import Any, Dict, List, Optional
import json
import math


class Trader:
    POSITION_LIMITS = {
        "EMERALDS": 80,
        "TOMATOES": 80,
    }

    EMERALDS_FAIR_VALUE = 10000
    EMERALDS_TAKE_EDGE = 0.0
    EMERALDS_REDUCE_EDGE = 1.0
    EMERALDS_PENNY_EDGE = 2.0
    EMERALDS_INVENTORY_SKEW_PER_UNIT = 0.05
    EMERALDS_MAX_POST_SIZE = 20
    EMERALDS_PASSIVE_OFFSET = 4.0

    # ------------------------------------------------------------------
    # TOMATOES wall-mid execution model
    # ------------------------------------------------------------------
    # Normalization center for plotting / stationarity:
    #     norm_center = alpha * wall_mid + (1 - alpha) * touch_mid
    #
    # Execution fair for pennying:
    #     fair_exec = wall_mid + delta_lookup[round(touch_mid - wall_mid, 1)]
    #
    # These constants were fitted on the uploaded TOMATOES market data and
    # improved 1-step-ahead touch-mid prediction vs plain wall_mid.
    TOMATO_NORM_ALPHA = 0.5125
    TOMATO_GLOBAL_DELTA = -0.020926046302315114
    TOMATO_RESIDUAL_DELTA = {
        -4.5: -0.38458460085166424,
        -4.0: 0.06757198971059665,
        -3.5: -0.18553554366907535,
        -3.0: -0.10886575578778938,
        -2.5: 0.2506789922829475,
        -0.5: -0.36919707599509194,
         0.0: -0.01762383342744373,
         0.5: 0.341873455513352,
         2.0: -0.3340203300487605,
         2.5: -0.02554058338755088,
         3.0: 0.13425319958808396,
         3.5: -0.12829798793310448,
         4.0: 0.2852662706128007,
    }

    # Trading controls for TOMATOES.
    TOMATO_TAKE_EDGE = 1.5
    TOMATO_REDUCE_EDGE = 0.5
    TOMATO_PENNY_EDGE = 0.4
    TOMATO_INVENTORY_SKEW_PER_UNIT = 0.04
    TOMATO_PASSIVE_OFFSET = 2.0
    TOMATO_MAX_POST_SIZE = 6

    # Persistent trade-flow signal built from state.market_trades.
    TOMATO_TRADE_SIGNAL_DECAY = 0.92
    TOMATO_TRADE_SIGNAL_UNIT = 5.0
    TOMATO_TRADE_SIGNAL_MAX = 3.0
    # Tuned down from 0.9 after cross-checking round0_csv and 77832:
    # 0.7 kept the trade-flow signal useful without letting it over-steer fair value.
    TOMATO_TRADE_FAIR_SHIFT = 0.7

    # Tick-to-tick book-delta / cancellation signal.
    # Positive means support added on bids and/or asks pulled. Negative means
    # bids vanished and/or asks were added without enough execution to explain it.
    TOMATO_CANCEL_SIGNAL_DECAY = 0.84
    TOMATO_CANCEL_SIGNAL_MAX = 2.5
    TOMATO_CANCEL_FAIR_SHIFT = 0.18
    TOMATO_CANCEL_EDGE_SKEW = 0.10
    TOMATO_CANCEL_PASSIVE_SKEW = 0.18

    def run(self, state: TradingState):
        saved_state = self._load_trader_state(state.traderData)
        tomato_trade_signal = self._update_tomato_trade_signal(
            state.order_depths.get("TOMATOES", OrderDepth()),
            state.market_trades.get("TOMATOES", []),
            saved_state.get("tomato_trade_signal", 0.0),
        )
        tomato_cancel_signal, tomato_snapshot = self._update_tomato_cancel_signal(
            state.order_depths.get("TOMATOES", OrderDepth()),
            state.market_trades.get("TOMATOES", []),
            saved_state.get("tomato_cancel_signal", 0.0),
            saved_state.get("tomato_snapshot", {}),
        )

        result: Dict[str, List[Order]] = {}

        for product in self.POSITION_LIMITS:
            order_depth = state.order_depths.get(product, OrderDepth())
            position = state.position.get(product, 0)

            if product == "EMERALDS":
                result[product] = self.trade_emeralds_fair_reversion(order_depth, position)
            elif product == "TOMATOES":
                result[product] = self.trade_tomatoes_wallmid_model(
                    order_depth,
                    position,
                    tomato_trade_signal,
                    tomato_cancel_signal,
                )
            else:
                result[product] = []

        conversions = 0
        traderData = self._encode_trader_state(
            tomato_trade_signal,
            tomato_cancel_signal,
            tomato_snapshot,
        )
        return result, conversions, traderData

    def _load_trader_state(self, trader_data: str) -> Dict[str, float]:
        if not trader_data:
            return {
                "tomato_trade_signal": 0.0,
                "tomato_cancel_signal": 0.0,
                "tomato_snapshot": {},
            }

        try:
            payload = json.loads(trader_data)
        except Exception:
            return {
                "tomato_trade_signal": 0.0,
                "tomato_cancel_signal": 0.0,
                "tomato_snapshot": {},
            }

        return {
            "tomato_trade_signal": float(payload.get("tomato_trade_signal", 0.0)),
            "tomato_cancel_signal": float(payload.get("tomato_cancel_signal", 0.0)),
            "tomato_snapshot": payload.get("tomato_snapshot", {}),
        }

    def _encode_trader_state(
        self,
        tomato_trade_signal: float,
        tomato_cancel_signal: float,
        tomato_snapshot: Dict[str, int],
    ) -> str:
        return json.dumps(
            {
                "tomato_trade_signal": tomato_trade_signal,
                "tomato_cancel_signal": tomato_cancel_signal,
                "tomato_snapshot": tomato_snapshot,
            },
            separators=(",", ":"),
        )

    def _clip(self, value: float, max_abs: float) -> float:
        return max(-max_abs, min(max_abs, value))

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

    def _update_tomato_trade_signal(
        self,
        order_depth: OrderDepth,
        market_trades: List[Any],
        previous_signal: float,
    ) -> float:
        signal = self.TOMATO_TRADE_SIGNAL_DECAY * previous_signal
        state = self._book_state(order_depth)
        if state is None or not market_trades:
            return self._clip(signal, self.TOMATO_TRADE_SIGNAL_MAX)

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
            return self._clip(signal, self.TOMATO_TRADE_SIGNAL_MAX)

        imbalance = signed_qty / float(total_qty)
        vwap = vwap_numerator / float(total_qty)
        price_bias = self._clip((vwap - touch_mid) / half_spread, 1.5)
        volume_scale = min(1.5, total_qty / self.TOMATO_TRADE_SIGNAL_UNIT)

        instant_signal = volume_scale * (0.7 * imbalance + 0.3 * price_bias)
        signal += instant_signal
        return self._clip(signal, self.TOMATO_TRADE_SIGNAL_MAX)

    def _tomato_snapshot(self, order_depth: OrderDepth) -> Dict[str, int]:
        state = self._book_state(order_depth)
        if state is None:
            return {}

        buy_orders = state["buy_orders"]
        sell_orders = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        bid_wall = min(buy_orders.keys())
        ask_wall = max(sell_orders.keys())

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

    def _update_tomato_cancel_signal(
        self,
        order_depth: OrderDepth,
        market_trades: List[Any],
        previous_signal: float,
        previous_snapshot: Dict[str, int],
    ) -> tuple[float, Dict[str, int]]:
        signal = self.TOMATO_CANCEL_SIGNAL_DECAY * previous_signal
        state = self._book_state(order_depth)
        current_snapshot = self._tomato_snapshot(order_depth)

        if state is None or not previous_snapshot:
            return self._clip(signal, self.TOMATO_CANCEL_SIGNAL_MAX), current_snapshot

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
        return self._clip(signal, self.TOMATO_CANCEL_SIGNAL_MAX), current_snapshot

    def _sorted_buy_orders(self, order_depth: OrderDepth) -> Dict[int, int]:
        return {
            int(price): abs(int(volume))
            for price, volume in sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)
        }

    def _sorted_sell_orders(self, order_depth: OrderDepth) -> Dict[int, int]:
        return {
            int(price): abs(int(volume))
            for price, volume in sorted(order_depth.sell_orders.items(), key=lambda x: x[0])
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
        return {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": best_ask - best_bid,
        }

    def _cap_post_size(self, base_size: int, working_position: int, side: str, capacity: int) -> int:
        """
        Shrink passive size on the side that worsens current inventory.
        """
        size = base_size
        if side == "buy" and working_position > 0:
            size = max(2, size - working_position // 10)
        elif side == "sell" and working_position < 0:
            size = max(2, size - abs(working_position) // 10)
        return max(0, min(capacity, size))

    def trade_emeralds_fair_reversion(self, order_depth: OrderDepth, position: int) -> List[Order]:
        """
        EMERALDS behaves like a static-fair market:
        - fair value is anchored at 10000
        - dominant resting liquidity lives around 9992 / 10008
        - impact is low and replenishment is strong

        Strategy:
        - take anything at or through fair value
        - reduce inventory on slightly favorable prices
        - otherwise quote around a skewed fair, with moderate size only
        """
        orders: List[Order] = []
        product = "EMERALDS"
        limit = self.POSITION_LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders

        buy_orders: Dict[int, int] = state["buy_orders"]
        sell_orders: Dict[int, int] = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        spread = int(state["spread"])

        fair_value = float(self.EMERALDS_FAIR_VALUE)
        working_position = position

        for ask_price, ask_volume in sell_orders.items():
            buy_capacity = limit - working_position
            if buy_capacity <= 0:
                break

            fair_skewed = fair_value - self.EMERALDS_INVENTORY_SKEW_PER_UNIT * working_position

            if ask_price <= fair_skewed - self.EMERALDS_TAKE_EDGE:
                qty = min(ask_volume, buy_capacity)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty
            elif working_position < 0 and ask_price <= fair_skewed + self.EMERALDS_REDUCE_EDGE:
                qty = min(ask_volume, buy_capacity, abs(working_position))
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty

        for bid_price, bid_volume in buy_orders.items():
            sell_capacity = limit + working_position
            if sell_capacity <= 0:
                break

            fair_skewed = fair_value - self.EMERALDS_INVENTORY_SKEW_PER_UNIT * working_position

            if bid_price >= fair_skewed + self.EMERALDS_TAKE_EDGE:
                qty = min(bid_volume, sell_capacity)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    working_position -= qty
            elif working_position > 0 and bid_price >= fair_skewed - self.EMERALDS_REDUCE_EDGE:
                qty = min(bid_volume, sell_capacity, working_position)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    working_position -= qty

        fair_skewed = fair_value - self.EMERALDS_INVENTORY_SKEW_PER_UNIT * working_position
        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)

        bid_size = self._cap_post_size(self.EMERALDS_MAX_POST_SIZE, working_position, "buy", buy_capacity)
        ask_size = self._cap_post_size(self.EMERALDS_MAX_POST_SIZE, working_position, "sell", sell_capacity)

        if spread >= 8:
            bid_price = min(best_bid + 1, math.floor(fair_skewed - self.EMERALDS_PENNY_EDGE))
            ask_price = max(best_ask - 1, math.ceil(fair_skewed + self.EMERALDS_PENNY_EDGE))
        else:
            bid_price = math.floor(fair_skewed - self.EMERALDS_PASSIVE_OFFSET)
            ask_price = math.ceil(fair_skewed + self.EMERALDS_PASSIVE_OFFSET)

        bid_price = min(int(bid_price), best_ask - 1, self.EMERALDS_FAIR_VALUE - 1)
        ask_price = max(int(ask_price), best_bid + 1, self.EMERALDS_FAIR_VALUE + 1)

        if bid_price < ask_price:
            if bid_size > 0:
                orders.append(Order(product, bid_price, bid_size))
            if ask_size > 0:
                orders.append(Order(product, ask_price, -ask_size))

        return orders

    def _tomato_model_state(self, order_depth: OrderDepth) -> Optional[Dict[str, Any]]:
        """
        Build the two-layer TOMATOES state:

        1) norm_center: for plotting / normalization
        2) fair_exec:   for execution / pennying
        """
        state = self._book_state(order_depth)
        if state is None:
            return None

        buy_orders = state["buy_orders"]
        sell_orders = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        bid_wall = min(buy_orders.keys())
        ask_wall = max(sell_orders.keys())

        touch_mid = 0.5 * (best_bid + best_ask)
        wall_mid = 0.5 * (bid_wall + ask_wall)
        residual = round(touch_mid - wall_mid, 1)

        fair_exec = wall_mid + self.TOMATO_RESIDUAL_DELTA.get(residual, self.TOMATO_GLOBAL_DELTA)
        norm_center = self.TOMATO_NORM_ALPHA * wall_mid + (1.0 - self.TOMATO_NORM_ALPHA) * touch_mid

        return {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_wall": bid_wall,
            "ask_wall": ask_wall,
            "touch_mid": touch_mid,
            "wall_mid": wall_mid,
            "norm_center": norm_center,
            "fair_exec": fair_exec,
            "residual": residual,
            "spread": int(state["spread"]),
        }

    def _tomato_post_size(self, working_position: int, side: str, capacity: int) -> int:
        return self._cap_post_size(self.TOMATO_MAX_POST_SIZE, working_position, side, capacity)

    def trade_tomatoes_wallmid_model(
        self,
        order_depth: OrderDepth,
        position: int,
        trade_signal: float = 0.0,
        cancel_signal: float = 0.0,
    ) -> List[Order]:
        """
        TOMATOES wall-mid + residual-state model, with a decayed market-trade flow signal.

        Differences vs the original simple wall-mid trader:
        - keeps wall_mid as the deep-book anchor
        - uses touch_mid - wall_mid as a discrete local state
        - trades on fair_exec = wall_mid + residual_delta[state]
        - nudges fair_exec with recent same-product market trades
        - uses norm_center only as the de-noised normalization anchor
        - pennies only when fair edge is real
        """
        orders: List[Order] = []
        product = "TOMATOES"
        limit = self.POSITION_LIMITS[product]

        state = self._tomato_model_state(order_depth)
        if state is None:
            return orders

        buy_orders: Dict[int, int] = state["buy_orders"]
        sell_orders: Dict[int, int] = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        fair_exec = (
            float(state["fair_exec"])
            + self.TOMATO_TRADE_FAIR_SHIFT * trade_signal
            + self.TOMATO_CANCEL_FAIR_SHIFT * cancel_signal
        )
        spread = int(state["spread"])

        # working_position assumes aggressive taking fills immediately.
        working_position = position

        if spread >= 13:
            take_edge = self.TOMATO_TAKE_EDGE
            reduce_edge = self.TOMATO_REDUCE_EDGE
            penny_edge = self.TOMATO_PENNY_EDGE
            passive_offset = self.TOMATO_PASSIVE_OFFSET
        elif spread >= 8:
            take_edge = self.TOMATO_TAKE_EDGE + 0.5
            reduce_edge = self.TOMATO_REDUCE_EDGE + 0.25
            penny_edge = self.TOMATO_PENNY_EDGE + 0.4
            passive_offset = self.TOMATO_PASSIVE_OFFSET + 1.0
        else:
            take_edge = self.TOMATO_TAKE_EDGE + 1.0
            reduce_edge = self.TOMATO_REDUCE_EDGE + 0.5
            penny_edge = self.TOMATO_PENNY_EDGE + 0.75
            passive_offset = self.TOMATO_PASSIVE_OFFSET + 2.0

        buy_take_edge = max(0.5, take_edge - self.TOMATO_CANCEL_EDGE_SKEW * cancel_signal)
        sell_take_edge = max(0.5, take_edge + self.TOMATO_CANCEL_EDGE_SKEW * cancel_signal)
        buy_passive_offset = max(1.0, passive_offset - self.TOMATO_CANCEL_PASSIVE_SKEW * cancel_signal)
        sell_passive_offset = max(1.0, passive_offset + self.TOMATO_CANCEL_PASSIVE_SKEW * cancel_signal)

        # --------------------------------------------------------------
        # 1) TAKE obvious gifts versus the execution fair.
        # --------------------------------------------------------------
        for ask_price, ask_volume in sell_orders.items():
            buy_capacity = limit - working_position
            if buy_capacity <= 0:
                break

            fair_skewed = fair_exec - self.TOMATO_INVENTORY_SKEW_PER_UNIT * working_position

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

            fair_skewed = fair_exec - self.TOMATO_INVENTORY_SKEW_PER_UNIT * working_position

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

        # --------------------------------------------------------------
        # 2) MAKE around the skewed fair.
        # --------------------------------------------------------------
        fair_skewed = fair_exec - self.TOMATO_INVENTORY_SKEW_PER_UNIT * working_position

        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)

        bid_size = self._tomato_post_size(working_position, "buy", buy_capacity)
        ask_size = self._tomato_post_size(working_position, "sell", sell_capacity)

        spread = best_ask - best_bid
        penny_bid = best_bid + 1 if spread > 1 else best_bid
        penny_ask = best_ask - 1 if spread > 1 else best_ask

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

        # Never post crossed or marketable passive quotes.
        bid_price = min(bid_price, best_ask - 1)
        ask_price = max(ask_price, best_bid + 1)

        # If the spread is too tight, fall back to the touch.
        if bid_price >= ask_price:
            bid_price = best_bid
            ask_price = best_ask

        if bid_size > 0:
            orders.append(Order(product, int(bid_price), bid_size))

        if ask_size > 0:
            orders.append(Order(product, int(ask_price), -ask_size))

        return orders
