from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List

class Trader:
    POSITION_LIMITS = {
        "EMERALDS": 80,
        "TOMATOES": 80,
    }

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        for product in state.order_depths:
            if product not in self.POSITION_LIMITS:
                continue

            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            if not order_depth.buy_orders or not order_depth.sell_orders:
                result[product] = orders
                continue

            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())

            # Only quote if there is a spread to improve
            if best_ask - best_bid >= 2:
                buy_price = best_bid + 1
                sell_price = best_ask - 1
            else:
                result[product] = orders
                continue

            position = state.position.get(product, 0)
            limit = self.POSITION_LIMITS[product]

            buy_qty = limit - position
            sell_qty = limit + position

            if buy_qty > 0:
                orders.append(Order(product, buy_price, buy_qty))

            if sell_qty > 0:
                orders.append(Order(product, sell_price, -sell_qty))

            result[product] = orders

        conversions = 0
        traderData = ""
        return result, conversions, traderData