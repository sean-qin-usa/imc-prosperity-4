"""
Local research variant built on `fundamental_v1.py`.

Idea:
- Detect slow VFE trend with a fast/slow EMA spread.
- Use that trend only as a risk controller for the deep-ITM sleeve:
  reduce buying / size when we are long-delta into a downtrend, and vice
  versa for short-delta into an uptrend.
- Optionally hedge a slice of the net long/short delta with spot only
  when trend and position align adversely.

This is a hidden-day robustness branch, not a claim that VFE momentum is
the primary alpha source.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Dict, List
import json
import math

_BASE_PATH = Path(__file__).with_name("fundamental_v1.py")
_SPEC = spec_from_file_location("_fundamental_v1_base_drift_guard", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load base strategy from {_BASE_PATH}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BaseTrader = _MODULE.Trader
Order = _MODULE.Order


class Trader(BaseTrader):
    TREND_FAST_ALPHA = 0.06
    TREND_SLOW_ALPHA = 0.01
    TREND_TRIGGER = 8.0
    TREND_FAIR_BETA = 0.20
    TREND_EDGE_WIDEN = 0.75
    TREND_SIZE_MULT = 0.50

    ENABLE_UNDERLYING_HEDGE = True
    HEDGE_DELTA_THRESHOLD = 150.0
    HEDGE_SIZE = 15
    HEDGE_EDGE = 0.5

    def _update_spot_trend(self, saved: Dict, spot_mid: float) -> float:
        fast = float(saved.get("spot_ema_fast", spot_mid))
        slow = float(saved.get("spot_ema_slow", spot_mid))
        fast = (1.0 - self.TREND_FAST_ALPHA) * fast + self.TREND_FAST_ALPHA * spot_mid
        slow = (1.0 - self.TREND_SLOW_ALPHA) * slow + self.TREND_SLOW_ALPHA * spot_mid
        saved["spot_ema_fast"] = fast
        saved["spot_ema_slow"] = slow
        return fast - slow

    def _trade_deep_itm(
        self,
        name: str,
        K: int,
        od,
        pos: int,
        spot_mid: float,
        books: Dict[str, dict],
        T: float,
        ts: int,
    ) -> List[Order]:
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return []

        spot_for_fair, disagreement = self._voucher_context(name, spot_mid, books)
        trend = getattr(self, "_ctx_spot_trend", 0.0)

        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        working = pos
        fair = self._opt_theo(spot_for_fair, K, T, self.V_SIGMA)

        adverse_long = trend <= -self.TREND_TRIGGER and working >= 0
        adverse_short = trend >= self.TREND_TRIGGER and working <= 0

        confidence_bad = abs(disagreement) > self.V_CONFIRM_THRESHOLD
        extra_edge = self.V_CONFIRM_WIDEN if confidence_bad else 0.0
        size_mult = self.V_CONFIRM_SIZE_MULT if confidence_bad else 1.0

        if adverse_long or adverse_short:
            fair += self.TREND_FAIR_BETA * trend
            extra_edge += self.TREND_EDGE_WIDEN
            size_mult *= self.TREND_SIZE_MULT

        orders: List[Order] = []

        if ts >= self.V_ENDGAME_START and abs(working) >= self.V_ENDGAME_POS:
            flat_orders, _ = self._flatten_visible(
                name, book, working, self.V_ENDGAME_CHUNK
            )
            return flat_orders

        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - self.V_INV_SKEW * working
            if ap <= skew - (self.V_TAKE_EDGE + extra_edge):
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(name, ap, q))
                    working += q
            elif working < 0 and ap <= skew + self.V_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(name, ap, q))
                    working += q

        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair - self.V_INV_SKEW * working
            if bp >= skew + (self.V_TAKE_EDGE + extra_edge):
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(name, bp, -q))
                    working -= q
            elif working > 0 and bp >= skew - self.V_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(name, bp, -q))
                    working -= q

        skew = fair - self.V_INV_SKEW * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(
            self.V_MAX_POST_SIZE, working, "buy", buy_cap, limit, size_mult
        )
        ask_size = self._cap_size(
            self.V_MAX_POST_SIZE, working, "sell", sell_cap, limit, size_mult
        )

        if spread >= self.V_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - self.V_PENNY_EDGE - extra_edge))
            ask_price = max(ba - 1, math.ceil(skew + self.V_PENNY_EDGE + extra_edge))
            bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
            ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)
            if bid_price < ask_price:
                if bid_size > 0:
                    orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0:
                    orders.append(Order(name, ask_price, -ask_size))
        return orders

    def _maybe_hedge_underlying(self, state, spot_book: dict, T: float) -> List[Order]:
        trend = getattr(self, "_ctx_spot_trend", 0.0)
        if abs(trend) < self.TREND_TRIGGER:
            return []

        spot_pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
        net_delta = float(spot_pos)
        spot_mid = spot_book["touch_mid"]

        for name, K in self.VOUCHER_STRIKES.items():
            p = state.position.get(name, 0)
            net_delta += p * self._opt_delta(spot_mid, K, T, self.V_SIGMA)

        orders: List[Order] = []
        name = "VELVETFRUIT_EXTRACT"
        bb, ba = spot_book["bb"], spot_book["ba"]

        if trend < 0 and net_delta > self.HEDGE_DELTA_THRESHOLD:
            q = min(self.HEDGE_SIZE, self.LIMITS[name] + spot_pos, spot_book["bv"])
            if q > 0 and bb >= spot_mid - self.HEDGE_EDGE:
                orders.append(Order(name, bb, -q))
        elif trend > 0 and net_delta < -self.HEDGE_DELTA_THRESHOLD:
            q = min(self.HEDGE_SIZE, self.LIMITS[name] - spot_pos, spot_book["av"])
            if q > 0 and ba <= spot_mid + self.HEDGE_EDGE:
                orders.append(Order(name, ba, q))
        return orders

    def run(self, state):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        pos = state.position

        if "HYDROGEL_PACK" in state.order_depths:
            prev_mid = saved.get("h_prev_mid")
            orders, new_mid = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0),
                prev_mid,
                state.timestamp,
            )
            result["HYDROGEL_PACK"] = orders
            saved["h_prev_mid"] = new_mid

        books: Dict[str, dict] = {}
        for name in ("VELVETFRUIT_EXTRACT", "VEV_4000", "VEV_4500"):
            od = state.order_depths.get(name)
            if od is not None:
                book = self._book(od)
                if book is not None:
                    books[name] = book

        spot_book = books.get("VELVETFRUIT_EXTRACT")
        if spot_book is not None:
            spot_mid = spot_book["touch_mid"]
            self._ctx_spot_trend = self._update_spot_trend(saved, spot_mid)
            T = self._tte_years(state.timestamp)

            for name, K in self.VOUCHER_STRIKES.items():
                od = state.order_depths.get(name)
                if od is None:
                    continue
                result[name] = self._trade_deep_itm(
                    name,
                    K,
                    od,
                    pos.get(name, 0),
                    spot_mid,
                    books,
                    T,
                    state.timestamp,
                )

            hedge_orders = self._maybe_hedge_underlying(state, spot_book, T)
            if hedge_orders:
                result["VELVETFRUIT_EXTRACT"] = hedge_orders

        return result, 0, json.dumps(saved)
