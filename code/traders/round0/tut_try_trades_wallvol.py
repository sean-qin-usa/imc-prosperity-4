from datamodel import OrderDepth
from typing import Any, Dict, Optional
import importlib.util
from pathlib import Path

_BASE_PATH = Path(__file__).resolve().parent / "tut_try_trades.py"
_BASE_SPEC = importlib.util.spec_from_file_location("round0_tut_try_trades", _BASE_PATH)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load base trader from {_BASE_PATH}")
_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)
BaseTrader = _BASE_MODULE.Trader


class Trader(BaseTrader):
    """
    Variant of tut_try_trades that computes wall_mid using the max-volume
    level among the top book levels (closer to the visualizer's wall_mid).
    """

    def _tomato_model_state(self, order_depth: OrderDepth) -> Optional[Dict[str, Any]]:
        state = self._book_state(order_depth)
        if state is None:
            return None

        buy_orders = state["buy_orders"]
        sell_orders = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])

        # Wall = price at the largest visible volume (ties break toward touch).
        bid_wall = max(buy_orders.items(), key=lambda item: item[1])[0]
        ask_wall = max(sell_orders.items(), key=lambda item: item[1])[0]

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
            "spread": int(state["spread"]),
        }
