"""Round 1 hybrid with a tuned Kalman pepper leg.

This is a deliberately narrow iteration from the stable Kalman benchmark:
- keep the overall Kalman pepper structure
- add day-reset handling
- add modest inventory skew
- make same-side taking harder than opposite-side reduction
"""

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List

from datamodel import Order, OrderDepth, TradingState


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE_DIR = Path(__file__).resolve().parent
_KALMAN = _load_module("kalman_benchmark", _BASE_DIR / "kalman_benchmark.py")


class Trader(_KALMAN.Trader):
    IPR_TAKE_THRESHOLD = 2.6
    IPR_REDUCE_THRESHOLD = 1.0
    IPR_POST_OFFSET = 4
    IPR_INVENTORY_SKEW_PER_UNIT = 0.05
    IPR_POST_SCALE = 0.85

    def _load_state(self, trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return {"ipr_kf": {}, "last_ts": None}
        try:
            payload = json.loads(trader_data)
        except Exception:
            return {"ipr_kf": {}, "last_ts": None}
        return {
            "ipr_kf": payload.get("ipr_kf", {}),
            "last_ts": payload.get("last_ts"),
        }

    def run(self, state: TradingState):
        saved_state = self._load_state(state.traderData)
        last_ts = saved_state.get("last_ts")
        day_reset = last_ts is not None and state.timestamp < last_ts

        ipr_kf = _KALMAN.KalmanFilter.from_dict(saved_state.get("ipr_kf", {}))
        if day_reset:
            ipr_kf = _KALMAN.KalmanFilter()

        result: Dict[str, List[Order]] = {}

        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self.trade_aco_mean_reversion(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
            )

        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            result["INTARIAN_PEPPER_ROOT"] = self.trade_ipr_kalman_tuned(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                ipr_kf,
            )

        trader_data = json.dumps(
            {
                "ipr_kf": ipr_kf.to_dict(),
                "last_ts": state.timestamp,
            },
            separators=(",", ":"),
        )
        return result, 0, trader_data

    def trade_ipr_kalman_tuned(
        self,
        order_depth: OrderDepth,
        position: int,
        kf: "_KALMAN.KalmanFilter",
    ) -> List[Order]:
        orders: List[Order] = []
        product = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders

        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        spread = int(state["spread"])
        mid = 0.5 * (best_bid + best_ask)
        fair = kf.update(mid)

        working_position = position
        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)

        fair_skewed = fair - self.IPR_INVENTORY_SKEW_PER_UNIT * working_position
        buy_take_threshold = self.IPR_TAKE_THRESHOLD + max(0.0, working_position) / 25.0
        sell_take_threshold = self.IPR_TAKE_THRESHOLD + max(0.0, -working_position) / 25.0

        if best_ask < fair_skewed - buy_take_threshold and buy_capacity > 0:
            qty = min(abs(int(order_depth.sell_orders[best_ask])), buy_capacity, 12)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                working_position += qty

        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)
        fair_skewed = fair - self.IPR_INVENTORY_SKEW_PER_UNIT * working_position

        if best_bid > fair_skewed + sell_take_threshold and sell_capacity > 0:
            qty = min(abs(int(order_depth.buy_orders[best_bid])), sell_capacity, 12)
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                working_position -= qty

        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)
        fair_skewed = fair - self.IPR_INVENTORY_SKEW_PER_UNIT * working_position

        if working_position < 0 and best_ask < fair_skewed - self.IPR_REDUCE_THRESHOLD and buy_capacity > 0:
            qty = min(abs(int(order_depth.sell_orders[best_ask])), buy_capacity, abs(working_position))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                working_position += qty

        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)
        fair_skewed = fair - self.IPR_INVENTORY_SKEW_PER_UNIT * working_position

        if working_position > 0 and best_bid > fair_skewed + self.IPR_REDUCE_THRESHOLD and sell_capacity > 0:
            qty = min(abs(int(order_depth.buy_orders[best_bid])), sell_capacity, working_position)
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                working_position -= qty

        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)
        fair_skewed = fair - self.IPR_INVENTORY_SKEW_PER_UNIT * working_position

        spread_adjust = 1 if spread >= 14 else 0
        bid_price = round(fair_skewed) - self.IPR_POST_OFFSET + spread_adjust
        ask_price = round(fair_skewed) + self.IPR_POST_OFFSET - spread_adjust

        bid_price = min(int(bid_price), best_ask - 1)
        ask_price = max(int(ask_price), best_bid + 1)
        if bid_price >= ask_price:
            bid_price = round(fair_skewed) - self.IPR_POST_OFFSET
            ask_price = round(fair_skewed) + self.IPR_POST_OFFSET
            bid_price = min(int(bid_price), best_ask - 1)
            ask_price = max(int(ask_price), best_bid + 1)

        bid_scale = max(0.0, 1.0 - max(0.0, working_position) / float(limit))
        ask_scale = max(0.0, 1.0 - max(0.0, -working_position) / float(limit))

        bid_size = min(buy_capacity, max(0, int(round(limit * self.IPR_POST_SCALE * bid_scale))))
        ask_size = min(sell_capacity, max(0, int(round(limit * self.IPR_POST_SCALE * ask_scale))))

        if bid_size > 0:
            orders.append(Order(product, bid_price, bid_size))
        if ask_size > 0:
            orders.append(Order(product, ask_price, -ask_size))

        return orders
