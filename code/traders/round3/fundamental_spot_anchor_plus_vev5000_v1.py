"""
Local research variant of `fundamental_v1.py`.

Question:
- Can the proven spot-anchor family pick up hidden-day `VEV_5000` flow
  without reopening the whole weak middle-strike sleeve?

Design:
- keep the pure spot-anchor deep-ITM setup from `fundamental_spot_anchor_v1.py`
- add only `VEV_5000`
- quote `VEV_5000` more conservatively than `VEV_4000/4500`
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import math

from datamodel import Order


_BASE_PATH = Path(__file__).with_name("fundamental_v1.py")
_SPEC = spec_from_file_location("_fundamental_v1_base_spot_anchor_plus_5000", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load base strategy from {_BASE_PATH}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BaseTrader = _MODULE.Trader


class Trader(BaseTrader):
    VOUCHER_STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000}

    V_CONFIRM_THRESHOLD = 999.0
    V_CONFIRM_WIDEN = 0.0
    V_CONFIRM_SIZE_MULT = 1.0
    V_SIBLING_BLEND = 0.0
    ENABLE_UNDERLYING_HEDGE = False

    V5000_EXTRA_EDGE = 1.0
    V5000_SIZE_MULT = 0.5

    def _trade_deep_itm(self, name, K, od, pos, spot_mid, books, T, ts):
        if name != "VEV_5000":
            return super()._trade_deep_itm(name, K, od, pos, spot_mid, books, T, ts)

        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return []

        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        fair = self._opt_theo(spot_mid, K, T, self.V_SIGMA)
        working = pos
        orders = []

        if ts >= self.V_ENDGAME_START and abs(working) >= self.V_ENDGAME_POS:
            flat_orders, _ = self._flatten_visible(name, book, working, self.V_ENDGAME_CHUNK)
            return flat_orders

        take_edge = self.V_TAKE_EDGE + self.V5000_EXTRA_EDGE
        post_edge = self.V_PENNY_EDGE + self.V5000_EXTRA_EDGE

        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - self.V_INV_SKEW * working
            if ap <= skew - take_edge:
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
            if bp >= skew + take_edge:
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
            self.V_MAX_POST_SIZE,
            working,
            "buy",
            buy_cap,
            limit,
            self.V5000_SIZE_MULT,
        )
        ask_size = self._cap_size(
            self.V_MAX_POST_SIZE,
            working,
            "sell",
            sell_cap,
            limit,
            self.V5000_SIZE_MULT,
        )

        if spread >= self.V_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - post_edge))
            ask_price = max(ba - 1, math.ceil(skew + post_edge))
            bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
            ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)
            if bid_price < ask_price:
                if bid_size > 0:
                    orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0:
                    orders.append(Order(name, ask_price, -ask_size))
        return orders
