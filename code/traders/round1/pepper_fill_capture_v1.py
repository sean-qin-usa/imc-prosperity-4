"""PEPPER-only capture variant derived from the official follow-up probe.

Changes versus `pepper_fill_probe_followup.py`:
- keep PEPPER isolated
- keep the successful +2/+3 inside-spread entry style
- reject narrow-spread books that do not offer real inside-spread edge
- remove the early 90k soft-reduction
- delay flattening to the final 1k timestamps

This file is standalone so it can be uploaded directly to the official site.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    IPR_PROBE_PHASES: Tuple[Tuple[int, int, int], ...] = (
        (2, 4, 8),
        (2, 5, 12),
        (2, 6, 16),
        (3, 4, 8),
        (3, 5, 12),
        (3, 6, 16),
        (2, 4, 12),
        (3, 4, 12),
    )
    IPR_PHASE_LENGTH = 5_000
    IPR_PROBE_WINDOW_END = 45_000
    IPR_FLATTEN_START = 99_000
    IPR_MIN_SPREAD_TO_QUOTE = 8
    IPR_MAX_NET_LONG = 20

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            result["INTARIAN_PEPPER_ROOT"] = self.trade_ipr_capture(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                state.timestamp,
            )

        trader_data = json.dumps({"last_ts": state.timestamp}, separators=(",", ":"))
        return result, 0, trader_data

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
        return {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": best_ask - best_bid,
        }

    def trade_ipr_capture(self, order_depth: OrderDepth, position: int, timestamp: int) -> List[Order]:
        orders: List[Order] = []
        product = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders

        buy_orders: Dict[int, int] = state["buy_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        spread = int(state["spread"])

        if timestamp >= self.IPR_FLATTEN_START:
            if position > 0:
                qty = min(position, buy_orders[best_bid])
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))
            return orders

        if timestamp >= self.IPR_PROBE_WINDOW_END:
            return orders

        if spread < self.IPR_MIN_SPREAD_TO_QUOTE:
            return orders

        phase_index = min(
            len(self.IPR_PROBE_PHASES) - 1,
            timestamp // self.IPR_PHASE_LENGTH,
        )
        distance, quote_size, target_inventory = self.IPR_PROBE_PHASES[int(phase_index)]
        target_inventory = min(target_inventory, self.IPR_MAX_NET_LONG)

        if position >= target_inventory or spread <= distance:
            return orders

        remaining = min(limit - position, target_inventory - position)
        if remaining <= 0:
            return orders

        price = min(best_bid + distance, best_ask - 1)
        qty = min(quote_size, remaining)
        if qty > 0 and price < best_ask:
            orders.append(Order(product, price, qty))

        return orders
