"""
Local research variant built on `fundamental_v1.py`.

Idea:
- Measure the residual surface state from `VEV_5000..VEV_5500`.
- Do not trade those strikes directly.
- Do not shift deep-ITM fair.
- Only gate deep-ITM aggression:
  - if the surface is rich, make buying `VEV_4000/4500` harder and
    smaller
  - if the surface is cheap, make selling `VEV_4000/4500` harder and
    smaller

This is the conservative follow-up to `fundamental_surface_level_v1.py`.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Dict, List
import json
import math

_BASE_PATH = Path(__file__).with_name("fundamental_v1.py")
_SPEC = spec_from_file_location("_fundamental_v1_base_surface_gate", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load base strategy from {_BASE_PATH}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BaseTrader = _MODULE.Trader
Order = _MODULE.Order


class Trader(BaseTrader):
    SURF_STRIKES = {
        "VEV_5000": 5000,
        "VEV_5100": 5100,
        "VEV_5200": 5200,
        "VEV_5300": 5300,
        "VEV_5400": 5400,
        "VEV_5500": 5500,
    }

    SURF_MEAN_ALPHA = 0.02
    SURF_SCALE_ALPHA = 0.03
    SURF_MIN_SCALE = 0.75
    SURF_Z_CAP = 3.0

    SURF_EDGE_PER_Z = 0.25
    SURF_SIZE_PER_Z = 0.18
    SURF_MIN_SIDE_MULT = 0.40

    def _update_surface_level(
        self,
        saved: Dict,
        order_depths,
        spot_mid: float,
        T: float,
    ) -> float:
        z_values: List[float] = []

        for name, strike in self.SURF_STRIKES.items():
            od = order_depths.get(name)
            if od is None:
                continue
            book = self._book(od)
            if not book:
                continue

            resid = book["touch_mid"] - self._opt_theo(spot_mid, strike, T, self.V_SIGMA)
            mean_key = f"surf_gate_mean_{name}"
            scale_key = f"surf_gate_scale_{name}"

            mean = float(saved.get(mean_key, resid))
            scale = float(saved.get(scale_key, self.SURF_MIN_SCALE))

            mean = (1.0 - self.SURF_MEAN_ALPHA) * mean + self.SURF_MEAN_ALPHA * resid
            dev = abs(resid - mean)
            scale = (1.0 - self.SURF_SCALE_ALPHA) * scale + self.SURF_SCALE_ALPHA * dev
            scale = max(self.SURF_MIN_SCALE, scale)

            saved[mean_key] = mean
            saved[scale_key] = scale

            z = self._clip((resid - mean) / scale, -self.SURF_Z_CAP, self.SURF_Z_CAP)
            z_values.append(z)

        if not z_values:
            return 0.0
        return float(sum(z_values) / len(z_values))

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
        confidence_bad = abs(disagreement) > self.V_CONFIRM_THRESHOLD
        base_extra_edge = self.V_CONFIRM_WIDEN if confidence_bad else 0.0
        base_size_mult = self.V_CONFIRM_SIZE_MULT if confidence_bad else 1.0

        surface_level = float(getattr(self, "_ctx_surface_level", 0.0))
        surface_level = self._clip(surface_level, -self.SURF_Z_CAP, self.SURF_Z_CAP)
        rich = max(surface_level, 0.0)
        cheap = max(-surface_level, 0.0)

        buy_extra = base_extra_edge + self.SURF_EDGE_PER_Z * rich
        sell_extra = base_extra_edge + self.SURF_EDGE_PER_Z * cheap

        buy_size_mult = base_size_mult * max(
            self.SURF_MIN_SIDE_MULT, 1.0 - self.SURF_SIZE_PER_Z * rich
        )
        sell_size_mult = base_size_mult * max(
            self.SURF_MIN_SIDE_MULT, 1.0 - self.SURF_SIZE_PER_Z * cheap
        )

        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        fair = self._opt_theo(spot_for_fair, K, T, self.V_SIGMA)
        working = pos
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
            if ap <= skew - (self.V_TAKE_EDGE + buy_extra):
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
            if bp >= skew + (self.V_TAKE_EDGE + sell_extra):
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
            self.V_MAX_POST_SIZE, working, "buy", buy_cap, limit, buy_size_mult
        )
        ask_size = self._cap_size(
            self.V_MAX_POST_SIZE, working, "sell", sell_cap, limit, sell_size_mult
        )

        if spread >= self.V_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - self.V_PENNY_EDGE - buy_extra))
            ask_price = max(ba - 1, math.ceil(skew + self.V_PENNY_EDGE + sell_extra))
            bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
            ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)
            if bid_price < ask_price:
                if bid_size > 0:
                    orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0:
                    orders.append(Order(name, ask_price, -ask_size))
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
            self._ctx_surface_level = self._update_surface_level(
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
