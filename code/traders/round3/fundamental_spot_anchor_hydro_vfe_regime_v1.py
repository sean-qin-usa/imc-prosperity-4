"""
Local research variant of `fundamental_v1.py`.

Direction:
- Keep the pure spot-anchor deep-ITM voucher sleeve unchanged.
- Use `VELVETFRUIT_EXTRACT` momentum only as a Hydro crash-state overlay.
- If Hydro is cheap and VFE has sold off recently, lean harder into the
  Hydro bounce.
- If Hydro is cheap but VFE is flat/up, suppress fresh Hydro long risk.

This is a cross-asset *regime* branch, not a direct pair-trade branch.
If it wins, generate and upload the standalone `*_uploadsafe_*` file.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
import math

from datamodel import Order, OrderDepth, TradingState


_BASE_PATH = Path(__file__).with_name("fundamental_v1.py")
_SPEC = spec_from_file_location("_fundamental_v1_base_hydro_vfe_regime", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load base strategy from {_BASE_PATH}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BaseTrader = _MODULE.Trader


class Trader(BaseTrader):
    V_CONFIRM_THRESHOLD = 999.0
    V_CONFIRM_WIDEN = 0.0
    V_CONFIRM_SIZE_MULT = 1.0
    V_SIBLING_BLEND = 0.0
    ENABLE_UNDERLYING_HEDGE = False

    H_CRASH_SIZEUP_TRIGGER = 18.0
    H_CRASH_MIN_SPREAD = 14
    H_VFE_MOM_LOOKBACK = 20
    H_VFE_DOWN_THRESH = -3.5
    H_VFE_UP_THRESH = 1.0

    H_GOOD_BID_SIZE_MULT = 2.0
    H_GOOD_ASK_SIZE_MULT = 0.25
    H_GOOD_FAIR_SHIFT = 0.75

    H_BAD_BID_SIZE_MULT = 0.25
    H_BAD_ASK_SIZE_MULT = 1.25
    H_BAD_FAIR_SHIFT = -1.25

    @staticmethod
    def _push_hist(
        history: Optional[List[float]],
        value: float,
        max_len: int,
    ) -> List[float]:
        out = list(history or [])
        out.append(float(value))
        if len(out) > max_len:
            out = out[-max_len:]
        return out

    def _trade_hydrogel(
        self,
        od: OrderDepth,
        pos: int,
        prev_mid: Optional[float],
        ts: int,
        vfe_mom20: Optional[float],
    ) -> Tuple[List[Order], float]:
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], prev_mid if prev_mid is not None else 0.0
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        touch_mid = book["touch_mid"]

        shock = prev_mid is not None and abs(touch_mid - prev_mid) > self.H_SHOCK_MOVE
        if shock:
            fair = touch_mid
        else:
            fair_adj = self._clip(touch_mid - self.H_ANCHOR, -self.H_CLIP, self.H_CLIP)
            fair = self.H_ANCHOR + fair_adj

        bid_size_mult = 1.0
        ask_size_mult = 1.0
        in_crash = (
            not shock
            and touch_mid <= self.H_ANCHOR - self.H_CRASH_SIZEUP_TRIGGER
            and spread >= self.H_CRASH_MIN_SPREAD
        )
        if in_crash and vfe_mom20 is not None:
            if vfe_mom20 <= self.H_VFE_DOWN_THRESH:
                fair += self.H_GOOD_FAIR_SHIFT
                bid_size_mult = self.H_GOOD_BID_SIZE_MULT
                ask_size_mult = self.H_GOOD_ASK_SIZE_MULT
            elif vfe_mom20 >= self.H_VFE_UP_THRESH:
                fair += self.H_BAD_FAIR_SHIFT
                bid_size_mult = self.H_BAD_BID_SIZE_MULT
                ask_size_mult = self.H_BAD_ASK_SIZE_MULT

        working = pos
        orders: List[Order] = []

        if ts >= self.H_ENDGAME_START and abs(working) >= self.H_ENDGAME_POS:
            flat_orders, working = self._flatten_visible(
                prod, book, working, self.H_ENDGAME_CHUNK
            )
            orders.extend(flat_orders)
            return orders, touch_mid

        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - self.H_INV_SKEW * working
            if ap <= skew - self.H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(prod, ap, q))
                    working += q
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q))
                    working += q

        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair - self.H_INV_SKEW * working
            if bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(prod, bp, -q))
                    working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q))
                    working -= q

        if shock:
            return orders, touch_mid

        skew = fair - self.H_INV_SKEW * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(
            self.H_MAX_POST_SIZE,
            working,
            "buy",
            buy_cap,
            limit,
            bid_size_mult,
        )
        ask_size = self._cap_size(
            self.H_MAX_POST_SIZE,
            working,
            "sell",
            sell_cap,
            limit,
            ask_size_mult,
        )

        if spread >= self.H_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - self.H_PENNY_EDGE))
            ask_price = max(ba - 1, math.ceil(skew + self.H_PENNY_EDGE))
        else:
            bid_price = math.floor(skew - self.H_PASSIVE_OFFSET)
            ask_price = math.ceil(skew + self.H_PASSIVE_OFFSET)
        bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
        ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)

        if bid_price < ask_price:
            if bid_size > 0:
                orders.append(Order(prod, bid_price, bid_size))
            if ask_size > 0:
                orders.append(Order(prod, ask_price, -ask_size))
        return orders, touch_mid

    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        pos = state.position

        books: Dict[str, dict] = {}
        for name in ("VELVETFRUIT_EXTRACT", "VEV_4000", "VEV_4500"):
            od = state.order_depths.get(name)
            if od is None:
                continue
            book = self._book(od)
            if book is not None:
                books[name] = book

        vfe_book = books.get("VELVETFRUIT_EXTRACT")
        vfe_hist = saved.get("vfe_hist")
        vfe_mom20 = None
        if vfe_book is not None:
            vfe_hist = self._push_hist(
                vfe_hist,
                vfe_book["touch_mid"],
                self.H_VFE_MOM_LOOKBACK + 1,
            )
            if len(vfe_hist) >= self.H_VFE_MOM_LOOKBACK + 1:
                vfe_mom20 = vfe_hist[-1] - vfe_hist[0]
        saved["vfe_hist"] = vfe_hist or []

        if "HYDROGEL_PACK" in state.order_depths:
            prev_mid = saved.get("h_prev_mid")
            orders, new_mid = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0),
                prev_mid,
                state.timestamp,
                vfe_mom20,
            )
            result["HYDROGEL_PACK"] = orders
            saved["h_prev_mid"] = new_mid

        if vfe_book is not None:
            spot_mid = vfe_book["touch_mid"]
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

            hedge_orders = self._maybe_hedge_underlying(state, vfe_book, T)
            if hedge_orders:
                result["VELVETFRUIT_EXTRACT"] = hedge_orders

        return result, 0, json.dumps(saved)
