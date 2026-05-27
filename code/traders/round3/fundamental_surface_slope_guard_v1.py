"""
Local research variant built on `fundamental_v1.py`.

Idea:
- Extract two standardized residual clusters:
  - near-ATM: `VEV_5000/5100/5200`
  - OTM wing: `VEV_5300/5400/5500`
- Use `slope = otm_factor - atm_factor` as a directional state signal.
  Positive slope means the OTM wing is rich versus ATM, which is
  bearish for `VELVETFRUIT_EXTRACT`; negative slope is the opposite.
- Apply this only as a guard / hedge overlay on the deep-ITM sleeve:
  reduce buying into bearish slope when long-delta, and vice versa.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Dict, List
import json
import math

_BASE_PATH = Path(__file__).with_name("fundamental_v1.py")
_SPEC = spec_from_file_location("_fundamental_v1_base_surface_slope_guard", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load base strategy from {_BASE_PATH}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BaseTrader = _MODULE.Trader
Order = _MODULE.Order


class Trader(BaseTrader):
    ATM_STRIKES = {
        "VEV_5000": 5000,
        "VEV_5100": 5100,
        "VEV_5200": 5200,
    }
    OTM_STRIKES = {
        "VEV_5300": 5300,
        "VEV_5400": 5400,
        "VEV_5500": 5500,
    }

    SURF_MEAN_ALPHA = 0.02
    SURF_SCALE_ALPHA = 0.03
    SURF_MIN_SCALE = 0.75
    SURF_Z_CAP = 3.0

    SLOPE_TRIGGER = 0.75
    SLOPE_EDGE_WIDEN = 0.50
    SLOPE_SIZE_MULT = 0.55

    ENABLE_UNDERLYING_HEDGE = True
    HEDGE_DELTA_THRESHOLD = 150.0
    HEDGE_SIZE = 15
    HEDGE_EDGE = 0.5

    def _update_surface_slope(
        self,
        saved: Dict,
        order_depths,
        spot_mid: float,
        T: float,
    ) -> float:
        factors: Dict[str, List[float]] = {"atm": [], "otm": []}

        for bucket, mapping in (("atm", self.ATM_STRIKES), ("otm", self.OTM_STRIKES)):
            for name, strike in mapping.items():
                od = order_depths.get(name)
                if od is None:
                    continue
                book = self._book(od)
                if not book:
                    continue

                resid = book["touch_mid"] - self._opt_theo(spot_mid, strike, T, self.V_SIGMA)
                mean_key = f"surf_slope_mean_{name}"
                scale_key = f"surf_slope_scale_{name}"

                mean = float(saved.get(mean_key, resid))
                scale = float(saved.get(scale_key, self.SURF_MIN_SCALE))

                mean = (1.0 - self.SURF_MEAN_ALPHA) * mean + self.SURF_MEAN_ALPHA * resid
                dev = abs(resid - mean)
                scale = (1.0 - self.SURF_SCALE_ALPHA) * scale + self.SURF_SCALE_ALPHA * dev
                scale = max(self.SURF_MIN_SCALE, scale)

                saved[mean_key] = mean
                saved[scale_key] = scale

                z = self._clip((resid - mean) / scale, -self.SURF_Z_CAP, self.SURF_Z_CAP)
                factors[bucket].append(z)

        if not factors["atm"] or not factors["otm"]:
            return 0.0

        atm_factor = float(sum(factors["atm"]) / len(factors["atm"]))
        otm_factor = float(sum(factors["otm"]) / len(factors["otm"]))
        return otm_factor - atm_factor

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
        slope = float(getattr(self, "_ctx_surface_slope", 0.0))

        confidence_bad = abs(disagreement) > self.V_CONFIRM_THRESHOLD
        extra_edge = self.V_CONFIRM_WIDEN if confidence_bad else 0.0
        size_mult = self.V_CONFIRM_SIZE_MULT if confidence_bad else 1.0

        working = pos
        bearish = slope >= self.SLOPE_TRIGGER and working >= 0
        bullish = slope <= -self.SLOPE_TRIGGER and working <= 0

        if bearish or bullish:
            extra_edge += self.SLOPE_EDGE_WIDEN
            size_mult *= self.SLOPE_SIZE_MULT

        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        fair = self._opt_theo(spot_for_fair, K, T, self.V_SIGMA)
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
        slope = float(getattr(self, "_ctx_surface_slope", 0.0))
        if abs(slope) < self.SLOPE_TRIGGER:
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

        if slope > 0 and net_delta > self.HEDGE_DELTA_THRESHOLD:
            q = min(self.HEDGE_SIZE, self.LIMITS[name] + spot_pos, spot_book["bv"])
            if q > 0 and bb >= spot_mid - self.HEDGE_EDGE:
                orders.append(Order(name, bb, -q))
        elif slope < 0 and net_delta < -self.HEDGE_DELTA_THRESHOLD:
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
            T = self._tte_years(state.timestamp)
            self._ctx_surface_slope = self._update_surface_slope(
                saved, state.order_depths, spot_mid, T
            )

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
