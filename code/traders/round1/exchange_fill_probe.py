"""Official-site fill probe.

Purpose:
- submit low-risk inside-spread quotes on both symbols
- vary quote size and distance-from-touch deterministically over time
- keep inventory close to flat so repeated submissions stay readable

The resulting official bundle can be fed into `tools/calibrate_exchange_model.py`
to build a richer passive-fill calibration.
"""

from datamodel import Order, OrderDepth, TradingState
from typing import List, Sequence, Tuple


class Trader:
    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    ACO_FAIR = 10000

    # Alternate between one-tick and two-tick improvements, and vary size so the
    # official-site bundle gives us size-bucket evidence as well as hit/no-hit data.
    ACO_PROBE_SCHEDULE: Sequence[Tuple[int, int]] = (
        (1, 2),
        (1, 4),
        (1, 8),
        (2, 2),
        (2, 4),
        (2, 8),
    )
    IPR_PROBE_SCHEDULE: Sequence[Tuple[int, int]] = (
        (1, 2),
        (1, 4),
        (1, 8),
        (2, 2),
        (2, 4),
        (2, 8),
    )

    INVENTORY_FLATTEN_THRESHOLD = 12
    INVENTORY_HARD_FLATTEN_THRESHOLD = 20

    def run(self, state: TradingState):
        result = {}

        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self.trade_aco_probe(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
                state.timestamp,
            )

        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            result["INTARIAN_PEPPER_ROOT"] = self.trade_ipr_probe(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                state.timestamp,
            )

        return result, 0, ""

    def _phase(self, timestamp: int, schedule: Sequence[Tuple[int, int]], offset: int = 0) -> Tuple[int, int]:
        index = ((int(timestamp) // 100) + offset) % len(schedule)
        return schedule[index]

    def _flatten_inventory(
        self,
        product: str,
        best_bid: int,
        best_ask: int,
        position: int,
    ) -> List[Order]:
        orders: List[Order] = []
        if position >= self.INVENTORY_HARD_FLATTEN_THRESHOLD:
            orders.append(Order(product, best_bid, -min(position, 8)))
        elif position <= -self.INVENTORY_HARD_FLATTEN_THRESHOLD:
            orders.append(Order(product, best_ask, min(-position, 8)))
        return orders

    def trade_aco_probe(self, order_depth: OrderDepth, position: int, timestamp: int) -> List[Order]:
        orders: List[Order] = []
        product = "ASH_COATED_OSMIUM"
        limit = self.LIMITS[product]

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders)
        best_ask = min(order_depth.sell_orders)
        spread = best_ask - best_bid
        fair = self.ACO_FAIR

        orders.extend(self._flatten_inventory(product, best_bid, best_ask, position))
        if orders:
            return orders

        depth, size = self._phase(timestamp, self.ACO_PROBE_SCHEDULE, offset=0)
        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)

        # When inventory is leaning, only keep the quote that helps flatten.
        allow_buy = position < self.INVENTORY_FLATTEN_THRESHOLD
        allow_sell = position > -self.INVENTORY_FLATTEN_THRESHOLD

        if spread > depth and allow_buy:
            bid_price = min(best_bid + depth, fair - 1)
            if bid_price > best_bid and bid_price < best_ask and buy_capacity > 0:
                orders.append(Order(product, bid_price, min(size, buy_capacity)))

        if spread > depth and allow_sell:
            ask_price = max(best_ask - depth, fair + 1)
            if ask_price < best_ask and ask_price > best_bid and sell_capacity > 0:
                orders.append(Order(product, ask_price, -min(size, sell_capacity)))

        return orders

    def trade_ipr_probe(self, order_depth: OrderDepth, position: int, timestamp: int) -> List[Order]:
        orders: List[Order] = []
        product = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[product]

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders)
        best_ask = min(order_depth.sell_orders)
        spread = best_ask - best_bid
        fair = 0.5 * (best_bid + best_ask)

        orders.extend(self._flatten_inventory(product, best_bid, best_ask, position))
        if orders:
            return orders

        depth, size = self._phase(timestamp, self.IPR_PROBE_SCHEDULE, offset=1)
        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)

        allow_buy = position < self.INVENTORY_FLATTEN_THRESHOLD
        allow_sell = position > -self.INVENTORY_FLATTEN_THRESHOLD

        if spread > depth and allow_buy:
            bid_price = min(best_bid + depth, int(fair))
            if bid_price > best_bid and bid_price < best_ask and buy_capacity > 0:
                orders.append(Order(product, bid_price, min(size, buy_capacity)))

        if spread > depth and allow_sell:
            ask_price = max(best_ask - depth, int(fair + 1))
            if ask_price < best_ask and ask_price > best_bid and sell_capacity > 0:
                orders.append(Order(product, ask_price, -min(size, sell_capacity)))

        return orders
