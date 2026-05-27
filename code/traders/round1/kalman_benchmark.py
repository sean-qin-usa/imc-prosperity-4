from datamodel import Order, OrderDepth, TradingState
from typing import Any, Dict, List, Optional
import json
import math


class KalmanFilter:
    """
    Lightweight 1-D Kalman filter for the steadily drifting IPR fair value.
    """

    def __init__(self, process_var: float = 2.0, obs_var: float = 8.0):
        self.Q = process_var
        self.R = obs_var
        self.x: Optional[float] = None
        self.P: float = 1.0

    def update(self, z: float) -> float:
        if self.x is None:
            self.x = z
            return z
        p_pred = self.P + self.Q
        k = p_pred / (p_pred + self.R)
        self.x = self.x + k * (z - self.x)
        self.P = (1 - k) * p_pred
        return self.x

    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "P": self.P}

    @classmethod
    def from_dict(
        cls,
        payload: Dict[str, float],
        process_var: float = 2.0,
        obs_var: float = 8.0,
    ) -> "KalmanFilter":
        kf = cls(process_var=process_var, obs_var=obs_var)
        kf.x = payload.get("x")
        kf.P = payload.get("P", 1.0)
        return kf


class Trader:
    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    # ASH_COATED_OSMIUM: use the stronger fair-reversion/MM leg from the
    # tut_try_trades family. Backtests showed this leg consistently beats tut.
    ACO_FAIR_VALUE = 10000
    ACO_TAKE_EDGE = 0.0
    ACO_REDUCE_EDGE = 1.0
    ACO_PENNY_EDGE = 2.0
    ACO_INVENTORY_SKEW_PER_UNIT = 0.05
    ACO_MAX_POST_SIZE = 20
    ACO_PASSIVE_OFFSET = 4.0

    # INTARIAN_PEPPER_ROOT: use the stronger trend-following/Kalman leg from tut.
    IPR_TAKE_THRESHOLD = 2.0
    IPR_POST_OFFSET = 4

    def run(self, state: TradingState):
        saved_state = self._load_state(state.traderData)
        ipr_kf = KalmanFilter.from_dict(saved_state.get("ipr_kf", {}))

        result: Dict[str, List[Order]] = {}

        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self.trade_aco_mean_reversion(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
            )

        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            result["INTARIAN_PEPPER_ROOT"] = self.trade_ipr_kalman(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                ipr_kf,
            )

        trader_data = json.dumps(
            {
                "ipr_kf": ipr_kf.to_dict(),
            },
            separators=(",", ":"),
        )
        return result, 0, trader_data

    def _load_state(self, trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return {"ipr_kf": {}}
        try:
            payload = json.loads(trader_data)
        except Exception:
            return {"ipr_kf": {}}
        return {
            "ipr_kf": payload.get("ipr_kf", {}),
        }

    def _sorted_buy_orders(self, order_depth: OrderDepth) -> Dict[int, int]:
        return {
            int(price): abs(int(volume))
            for price, volume in sorted(order_depth.buy_orders.items(), key=lambda item: item[0], reverse=True)
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
        return {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": best_ask - best_bid,
        }

    def _cap_post_size(self, base_size: int, working_position: int, side: str, capacity: int) -> int:
        size = base_size
        if side == "buy" and working_position > 0:
            size = max(2, size - working_position // 10)
        elif side == "sell" and working_position < 0:
            size = max(2, size - abs(working_position) // 10)
        return max(0, min(capacity, size))

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

    def trade_ipr_kalman(
        self,
        order_depth: OrderDepth,
        position: int,
        kf: KalmanFilter,
    ) -> List[Order]:
        orders: List[Order] = []
        product = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[product]

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid = 0.5 * (best_bid + best_ask)
        fair = kf.update(mid)

        buy_capacity = limit - position
        sell_capacity = limit + position

        if best_ask < fair - self.IPR_TAKE_THRESHOLD and buy_capacity > 0:
            qty = min(-order_depth.sell_orders[best_ask], buy_capacity)
            orders.append(Order(product, best_ask, qty))
            buy_capacity -= qty

        if best_bid > fair + self.IPR_TAKE_THRESHOLD and sell_capacity > 0:
            qty = min(order_depth.buy_orders[best_bid], sell_capacity)
            orders.append(Order(product, best_bid, -qty))
            sell_capacity -= qty

        if buy_capacity > 0:
            orders.append(Order(product, round(fair) - self.IPR_POST_OFFSET, buy_capacity))
        if sell_capacity > 0:
            orders.append(Order(product, round(fair) + self.IPR_POST_OFFSET, -sell_capacity))

        return orders
