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

    # ------------------------------------------------------------------
    # TOMATOES sparse linear next-mid model
    # ------------------------------------------------------------------
    # The wall-mid residual model remains the anchor because it was stronger
    # out of sample than a pure linear replacement. The linear model below
    # is blended in conservatively and uses one decayed trade-price feature
    # plus three book features:
    # - residual: touch_mid - wall_mid
    # - micro_dev: top-of-book microprice displacement
    # - depth_imbalance: visible-book imbalance across displayed levels
    # - trade_vwap_ewm: decayed same-tick market-trade VWAP pressure
    TOMATO_TRADE_VWAP_EWM_ALPHA = 0.08
    TOMATO_LINEAR_INTERCEPT = -0.01064667752648726
    TOMATO_LINEAR_COEF_RESIDUAL = -0.4860116047036429
    TOMATO_LINEAR_COEF_MICRO_DEV = 0.4246718349656325
    TOMATO_LINEAR_COEF_DEPTH_IMBALANCE = -13.196431448474742
    TOMATO_LINEAR_COEF_TRADE_VWAP_EWM = 0.24176453342844217
    TOMATO_LINEAR_DELTA_CLIP = 4.0
    TOMATO_LINEAR_BLEND = 0.25

    def run(self, state: TradingState):
        saved_state = self._load_trader_state(state.traderData)
        tomato_trade_vwap_ewm = self._update_tomato_trade_vwap_ewm(
            state.order_depths.get("TOMATOES", OrderDepth()),
            state.market_trades.get("TOMATOES", []),
            saved_state.get("tomato_trade_vwap_ewm", 0.0),
        )

        result: Dict[str, List[Order]] = {}

        for product in self.POSITION_LIMITS:
            order_depth = state.order_depths.get(product, OrderDepth())
            position = state.position.get(product, 0)

            if product == "EMERALDS":
                result[product] = self.trade_emeralds_fair_reversion(order_depth, position)
            elif product == "TOMATOES":
                result[product] = self.trade_tomatoes_linear_model(
                    order_depth,
                    position,
                    tomato_trade_vwap_ewm,
                )
            else:
                result[product] = []

        conversions = 0
        traderData = self._encode_trader_state(tomato_trade_vwap_ewm)
        return result, conversions, traderData

    def _load_trader_state(self, trader_data: str) -> Dict[str, float]:
        if not trader_data:
            return {"tomato_trade_vwap_ewm": 0.0}

        try:
            payload = json.loads(trader_data)
        except Exception:
            return {"tomato_trade_vwap_ewm": 0.0}

        return {
            "tomato_trade_vwap_ewm": float(payload.get("tomato_trade_vwap_ewm", 0.0)),
        }

    def _encode_trader_state(self, tomato_trade_vwap_ewm: float) -> str:
        return json.dumps(
            {"tomato_trade_vwap_ewm": tomato_trade_vwap_ewm},
            separators=(",", ":"),
        )

    def _clip(self, value: float, max_abs: float) -> float:
        return max(-max_abs, min(max_abs, value))

    def _update_tomato_trade_vwap_ewm(
        self,
        order_depth: OrderDepth,
        market_trades: List[Any],
        previous_ewm: float,
    ) -> float:
        state = self._book_state(order_depth)
        current_trade_vwap_dev = 0.0
        if state is not None and market_trades:
            best_bid = int(state["best_bid"])
            best_ask = int(state["best_ask"])
            touch_mid = 0.5 * (best_bid + best_ask)
            half_spread = max(1.0, 0.5 * (best_ask - best_bid))

            total_qty = 0
            vwap_numerator = 0.0

            for trade in market_trades:
                qty = abs(int(getattr(trade, "quantity", 0)))
                if qty <= 0:
                    continue

                price = float(getattr(trade, "price", touch_mid))
                total_qty += qty
                vwap_numerator += price * qty

            if total_qty > 0:
                trade_vwap = vwap_numerator / float(total_qty)
                current_trade_vwap_dev = (trade_vwap - touch_mid) / half_spread

        return (
            (1.0 - self.TOMATO_TRADE_VWAP_EWM_ALPHA) * previous_ewm
            + self.TOMATO_TRADE_VWAP_EWM_ALPHA * current_trade_vwap_dev
        )

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
        best_bid_size = int(buy_orders[best_bid])
        best_ask_size = int(sell_orders[best_ask])

        touch_mid = 0.5 * (best_bid + best_ask)
        wall_mid = 0.5 * (bid_wall + ask_wall)
        residual = touch_mid - wall_mid
        residual_key = round(residual, 1)
        base_fair_exec = wall_mid + self.TOMATO_RESIDUAL_DELTA.get(residual_key, self.TOMATO_GLOBAL_DELTA)
        norm_center = self.TOMATO_NORM_ALPHA * wall_mid + (1.0 - self.TOMATO_NORM_ALPHA) * touch_mid
        microprice = (
            (best_bid * best_ask_size + best_ask * best_bid_size)
            / float(best_bid_size + best_ask_size)
        )
        micro_dev = microprice - touch_mid
        bid_depth = float(sum(buy_orders.values()))
        ask_depth = float(sum(sell_orders.values()))
        depth_imbalance = 0.0
        if bid_depth + ask_depth > 0:
            depth_imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)

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
            "base_fair_exec": base_fair_exec,
            "residual": residual,
            "micro_dev": micro_dev,
            "depth_imbalance": depth_imbalance,
            "spread": int(state["spread"]),
        }

    def _tomato_post_size(self, working_position: int, side: str, capacity: int) -> int:
        return self._cap_post_size(self.TOMATO_MAX_POST_SIZE, working_position, side, capacity)

    def _tomato_linear_fair(
        self,
        touch_mid: float,
        residual: float,
        micro_dev: float,
        depth_imbalance: float,
        trade_vwap_ewm: float,
    ) -> float:
        predicted_delta = self.TOMATO_LINEAR_INTERCEPT
        predicted_delta += self.TOMATO_LINEAR_COEF_RESIDUAL * residual
        predicted_delta += self.TOMATO_LINEAR_COEF_MICRO_DEV * micro_dev
        predicted_delta += self.TOMATO_LINEAR_COEF_DEPTH_IMBALANCE * depth_imbalance
        predicted_delta += self.TOMATO_LINEAR_COEF_TRADE_VWAP_EWM * trade_vwap_ewm
        predicted_delta = self._clip(predicted_delta, self.TOMATO_LINEAR_DELTA_CLIP)
        return touch_mid + predicted_delta

    def trade_tomatoes_linear_model(
        self,
        order_depth: OrderDepth,
        position: int,
        trade_vwap_ewm: float = 0.0,
    ) -> List[Order]:
        """
        TOMATOES hybrid fair model:
        - keep the original wall-mid residual model as the anchor
        - add a conservative linear component from book state + trade VWAP EWM
        - blend only 25% toward the linear fair to avoid overfitting
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
        touch_mid = float(state["touch_mid"])
        base_fair_exec = float(state["base_fair_exec"])
        linear_fair = self._tomato_linear_fair(
            touch_mid=touch_mid,
            residual=float(state["residual"]),
            micro_dev=float(state["micro_dev"]),
            depth_imbalance=float(state["depth_imbalance"]),
            trade_vwap_ewm=trade_vwap_ewm,
        )
        fair_exec = (
            (1.0 - self.TOMATO_LINEAR_BLEND) * base_fair_exec
            + self.TOMATO_LINEAR_BLEND * linear_fair
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

        # --------------------------------------------------------------
        # 1) TAKE obvious gifts versus the execution fair.
        # --------------------------------------------------------------
        for ask_price, ask_volume in sell_orders.items():
            buy_capacity = limit - working_position
            if buy_capacity <= 0:
                break

            fair_skewed = fair_exec - self.TOMATO_INVENTORY_SKEW_PER_UNIT * working_position

            if ask_price <= fair_skewed - take_edge:
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

            if bid_price >= fair_skewed + take_edge:
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
            bid_price = math.floor(fair_skewed - passive_offset)

        if edge_sell >= penny_edge:
            ask_price = penny_ask
        else:
            ask_price = math.ceil(fair_skewed + passive_offset)

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
