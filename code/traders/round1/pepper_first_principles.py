"""Round 1 hybrid focused on a more passive pepper leg.

Design goals for INTARIAN_PEPPER_ROOT:
- keep the stronger current ASH leg unchanged
- use a smoother Kalman-style fair for local execution
- favor one-tick-inside passive quotes when the spread is wide
- take far less often than the current path-anchor leg
"""

import importlib.util
import json
import math
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
_PATH_ANCHOR = _load_module("path_anchor_strategy", _BASE_DIR / "path_anchor_strategy.py")


class KalmanFilter:
    def __init__(self, process_var: float = 2.2, obs_var: float = 7.5):
        self.Q = process_var
        self.R = obs_var
        self.x = None
        self.P = 1.0

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
    def from_dict(cls, payload: Dict[str, float]) -> "KalmanFilter":
        kf = cls()
        kf.x = payload.get("x")
        kf.P = payload.get("P", 1.0)
        return kf


class Trader(_PATH_ANCHOR.Trader):
    # Pepper execution is intentionally more passive than the current path anchor,
    # but inventory pressure grows much stronger late in the day.
    IPR_PROCESS_VAR = 2.2
    IPR_OBS_VAR = 7.5
    IPR_TAKE_EDGE_WIDE = 2.8
    IPR_TAKE_EDGE_MID = 3.4
    IPR_TAKE_EDGE_NARROW = 4.8
    IPR_REDUCE_EDGE = 0.9
    IPR_PASSIVE_EDGE = 1.8
    IPR_FALLBACK_OFFSET = 4.0
    IPR_INVENTORY_SKEW_PER_UNIT = 0.08
    IPR_MAX_POST_SIZE = 48
    IPR_MIN_POST_SIZE = 8

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

        kf = KalmanFilter.from_dict(saved_state.get("ipr_kf", {}))
        if day_reset:
            kf = KalmanFilter()

        result: Dict[str, List[Order]] = {}

        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self.trade_aco_mean_reversion(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
            )

        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            result["INTARIAN_PEPPER_ROOT"] = self.trade_ipr_first_principles(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                kf,
                state.timestamp,
            )

        trader_data = json.dumps(
            {
                "ipr_kf": kf.to_dict(),
                "last_ts": state.timestamp,
            },
            separators=(",", ":"),
        )
        return result, 0, trader_data

    def trade_ipr_first_principles(
        self,
        order_depth: OrderDepth,
        position: int,
        kf: KalmanFilter,
        timestamp: int,
    ) -> List[Order]:
        orders: List[Order] = []
        product = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders

        buy_orders = state["buy_orders"]
        sell_orders = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        bid_wall = int(state["bid_wall"])
        ask_wall = int(state["ask_wall"])
        spread = int(state["spread"])

        touch_mid = 0.5 * (best_bid + best_ask)
        wall_mid = 0.5 * (bid_wall + ask_wall)
        fair_kalman = kf.update(touch_mid)

        # Blend touch and wall context to avoid chasing temporary thin prints.
        fair = 0.88 * fair_kalman + 0.12 * wall_mid
        trend_bias = self._clip((fair - touch_mid) / 2.0, 3.0)
        late_phase = max(0.0, min(1.0, (float(timestamp) - 65000.0) / 35000.0))

        working_position = position
        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)

        if spread >= 13:
            take_edge = self.IPR_TAKE_EDGE_WIDE
        elif spread >= 8:
            take_edge = self.IPR_TAKE_EDGE_MID
        else:
            take_edge = self.IPR_TAKE_EDGE_NARROW

        long_pressure = max(0.0, working_position / float(limit))
        short_pressure = max(0.0, -working_position / float(limit))
        buy_take_edge = take_edge + (1.2 + 1.2 * late_phase) * long_pressure
        sell_take_edge = take_edge + (1.2 + 1.2 * late_phase) * short_pressure

        # Narrow-spread taking is allowed only when the fair is clearly through touch.
        if best_ask <= fair - buy_take_edge and buy_capacity > 0:
            take_qty = min(abs(int(sell_orders[best_ask])), buy_capacity, 12)
            if take_qty > 0:
                orders.append(Order(product, best_ask, take_qty))
                working_position += take_qty

        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)
        if best_bid >= fair + sell_take_edge and sell_capacity > 0:
            take_qty = min(abs(int(buy_orders[best_bid])), sell_capacity, 12)
            if take_qty > 0:
                orders.append(Order(product, best_bid, -take_qty))
                working_position -= take_qty

        # Let inventory reduction happen sooner than directional taking.
        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)
        inventory_skew = self.IPR_INVENTORY_SKEW_PER_UNIT * (1.0 + 1.5 * late_phase)
        fair_skewed = fair - inventory_skew * working_position
        if working_position < 0 and best_ask <= fair_skewed - self.IPR_REDUCE_EDGE and buy_capacity > 0:
            qty = min(abs(int(sell_orders[best_ask])), buy_capacity, abs(working_position))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                working_position += qty
        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)
        fair_skewed = fair - inventory_skew * working_position
        if working_position > 0 and best_bid >= fair_skewed + self.IPR_REDUCE_EDGE and sell_capacity > 0:
            qty = min(abs(int(buy_orders[best_bid])), sell_capacity, working_position)
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                working_position -= qty

        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)
        fair_skewed = fair - inventory_skew * working_position
        long_pressure = max(0.0, working_position / float(limit))
        short_pressure = max(0.0, -working_position / float(limit))

        base_post = self.IPR_MAX_POST_SIZE
        if spread <= 6:
            base_post = 24
        elif spread <= 9:
            base_post = 36

        bid_base = base_post + int(round(3.0 * max(0.0, trend_bias)))
        ask_base = base_post + int(round(3.0 * max(0.0, -trend_bias)))

        bid_scale = max(0.0, 1.0 - (1.0 + 1.2 * late_phase) * long_pressure)
        ask_scale = max(0.0, 1.0 - (1.0 + 1.2 * late_phase) * short_pressure)
        bid_scale *= 1.0 + 0.5 * short_pressure
        ask_scale *= 1.0 + 0.5 * long_pressure

        bid_raw = int(round(bid_base * bid_scale))
        ask_raw = int(round(ask_base * ask_scale))

        if late_phase > 0.0 and working_position > 0:
            bid_raw = int(round(bid_raw * (1.0 - 0.8 * late_phase)))
        elif late_phase > 0.0 and working_position < 0:
            ask_raw = int(round(ask_raw * (1.0 - 0.8 * late_phase)))

        if bid_raw <= 0:
            bid_size = 0
        elif bid_raw < self.IPR_MIN_POST_SIZE:
            bid_size = min(buy_capacity, self.IPR_MIN_POST_SIZE) if bid_scale > 0.45 else 0
        else:
            bid_size = min(buy_capacity, bid_raw)

        if ask_raw <= 0:
            ask_size = 0
        elif ask_raw < self.IPR_MIN_POST_SIZE:
            ask_size = min(sell_capacity, self.IPR_MIN_POST_SIZE) if ask_scale > 0.45 else 0
        else:
            ask_size = min(sell_capacity, ask_raw)

        if spread > 2:
            penny_bid = best_bid + 1
            penny_ask = best_ask - 1
            buy_edge = fair_skewed - penny_bid
            sell_edge = penny_ask - fair_skewed
            buy_passive_edge = self.IPR_PASSIVE_EDGE + (1.4 + 1.2 * late_phase) * long_pressure
            sell_passive_edge = self.IPR_PASSIVE_EDGE + (1.4 + 1.2 * late_phase) * short_pressure
            buy_offset = self.IPR_FALLBACK_OFFSET + (2.5 + 1.5 * late_phase) * long_pressure
            sell_offset = self.IPR_FALLBACK_OFFSET + (2.5 + 1.5 * late_phase) * short_pressure

            if buy_edge >= buy_passive_edge:
                bid_price = penny_bid
            else:
                bid_price = math.floor(fair_skewed - buy_offset)

            if sell_edge >= sell_passive_edge:
                ask_price = penny_ask
            else:
                ask_price = math.ceil(fair_skewed + sell_offset)
        else:
            bid_price = math.floor(fair_skewed - self.IPR_FALLBACK_OFFSET)
            ask_price = math.ceil(fair_skewed + self.IPR_FALLBACK_OFFSET)

        bid_price = min(int(bid_price), best_ask - 1)
        ask_price = max(int(ask_price), best_bid + 1)

        if bid_price >= ask_price:
            bid_price = best_bid
            ask_price = best_ask

        if bid_size > 0:
            orders.append(Order(product, int(bid_price), bid_size))
        if ask_size > 0:
            orders.append(Order(product, int(ask_price), -ask_size))

        return orders
