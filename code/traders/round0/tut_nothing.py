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
            orders: List[Order] = []

            result[product] = orders

        conversions = 0
        traderData = ""
        return result, conversions, traderData