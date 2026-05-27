"""Round 1 hybrid with the current ACO leg and the benchmark Kalman pepper leg."""

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from datamodel import Order, OrderDepth, TradingState


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE_DIR = Path(__file__).resolve().parent
_PATH_ANCHOR = _load_module("path_anchor_strategy", _BASE_DIR / "path_anchor_strategy.py")


class KalmanFilter:
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
        self.P = (1.0 - k) * p_pred
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


class Trader(_PATH_ANCHOR.Trader):
    IPR_TAKE_THRESHOLD = 2.0
    IPR_POST_OFFSET = 4

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

        ipr_kf = KalmanFilter.from_dict(saved_state.get("ipr_kf", {}))
        if day_reset:
            ipr_kf = KalmanFilter()

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
                "last_ts": state.timestamp,
            },
            separators=(",", ":"),
        )
        return result, 0, trader_data

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
