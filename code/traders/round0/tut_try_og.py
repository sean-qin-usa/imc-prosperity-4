from datamodel import OrderDepth, TradingState, Order
from typing import Any, Dict, List, Optional
import math


class Trader:
    POSITION_LIMITS = {
        "EMERALDS": 80,
        "TOMATOES": 80,
    }

    EMERALDS_FAIR_VALUE = 10000

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
    TOMATO_REDUCE_EDGE = 0.25
    TOMATO_PENNY_EDGE = 0.15
    TOMATO_INVENTORY_SKEW_PER_UNIT = 0.03
    TOMATO_PASSIVE_OFFSET = 1.0
    TOMATO_MAX_POST_SIZE = 10

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        for product in self.POSITION_LIMITS:
            order_depth = state.order_depths.get(product, OrderDepth())
            position = state.position.get(product, 0)

            if product == "EMERALDS":
                result[product] = self.trade_emeralds_baseline(order_depth, position)
            elif product == "TOMATOES":
                result[product] = self.trade_tomatoes_wallmid_model(order_depth, position)
            else:
                result[product] = []

        conversions = 0
        traderData = ""
        return result, conversions, traderData

    def trade_emeralds_baseline(self, order_depth: OrderDepth, position: int) -> List[Order]:
        """
        Keep EMERALDS baseline behavior essentially the same as the uploaded file:
        quote one tick inside when spread >= 2, no extra fair-value logic.
        """
        orders: List[Order] = []
        limit = self.POSITION_LIMITS["EMERALDS"]

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        if best_ask - best_bid < 2:
            return orders

        buy_price = best_bid + 1
        sell_price = best_ask - 1

        buy_qty = limit - position
        sell_qty = limit + position

        if buy_qty > 0:
            orders.append(Order("EMERALDS", buy_price, buy_qty))

        if sell_qty > 0:
            orders.append(Order("EMERALDS", sell_price, -sell_qty))

        return orders

    # ------------------------------------------------------------------
    # TOMATOES helpers
    # ------------------------------------------------------------------

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

    def _tomato_model_state(self, order_depth: OrderDepth) -> Optional[Dict[str, Any]]:
        """
        Build the two-layer TOMATOES state:

        1) norm_center: for plotting / normalization
        2) fair_exec:   for execution / pennying
        """
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
            "spread": best_ask - best_bid,
        }

    def _tomato_post_size(self, working_position: int, side: str, capacity: int) -> int:
        """
        Reduce quote size on the side that worsens current inventory.
        """
        base = self.TOMATO_MAX_POST_SIZE
        if side == "buy" and working_position > 0:
            base = max(2, base - working_position // 10)
        elif side == "sell" and working_position < 0:
            base = max(2, base - abs(working_position) // 10)
        return max(0, min(capacity, base))

    def trade_tomatoes_wallmid_model(self, order_depth: OrderDepth, position: int) -> List[Order]:
        """
        TOMATOES wall-mid + residual-state model.

        Differences vs the original simple wall-mid trader:
        - keeps wall_mid as the deep-book anchor
        - uses touch_mid - wall_mid as a discrete local state
        - trades on fair_exec = wall_mid + residual_delta[state]
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
        fair_exec = float(state["fair_exec"])

        # working_position assumes aggressive taking fills immediately.
        working_position = position

        # --------------------------------------------------------------
        # 1) TAKE obvious gifts versus the execution fair.
        # --------------------------------------------------------------
        for ask_price, ask_volume in sell_orders.items():
            buy_capacity = limit - working_position
            if buy_capacity <= 0:
                break

            fair_skewed = fair_exec - self.TOMATO_INVENTORY_SKEW_PER_UNIT * working_position

            if ask_price <= fair_skewed - self.TOMATO_TAKE_EDGE:
                qty = min(ask_volume, buy_capacity)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty

            elif working_position < 0 and ask_price <= fair_skewed - self.TOMATO_REDUCE_EDGE:
                qty = min(ask_volume, buy_capacity, abs(working_position))
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty

        for bid_price, bid_volume in buy_orders.items():
            sell_capacity = limit + working_position
            if sell_capacity <= 0:
                break

            fair_skewed = fair_exec - self.TOMATO_INVENTORY_SKEW_PER_UNIT * working_position

            if bid_price >= fair_skewed + self.TOMATO_TAKE_EDGE:
                qty = min(bid_volume, sell_capacity)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    working_position -= qty

            elif working_position > 0 and bid_price >= fair_skewed + self.TOMATO_REDUCE_EDGE:
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

        if edge_buy >= self.TOMATO_PENNY_EDGE:
            bid_price = penny_bid
        else:
            bid_price = math.floor(fair_skewed - self.TOMATO_PASSIVE_OFFSET)

        if edge_sell >= self.TOMATO_PENNY_EDGE:
            ask_price = penny_ask
        else:
            ask_price = math.ceil(fair_skewed + self.TOMATO_PASSIVE_OFFSET)

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