"""
Round 3 baseline v8 — 2026-04-24.

v7 learned: flat-sigma BS + EMA residual on ATM strikes has no real
edge (spreads 2-4 too tight, adverse selection eats MM edge). Gate it
off in v8.

v8 new piece: basis arb on VELVETFRUIT_EXTRACT.

Logic:
  S_synth_4000 = VEV_4000.mid + 4000   (deep-ITM call reprice)
  S_synth_4500 = VEV_4500.mid + 4500
  S_synth      = (S_synth_4000 + S_synth_4500) / 2
  basis        = S_market_mid - S_synth

  Per research: basis std ≈ 0.84 ticks, min/max ±6.
  Threshold: |basis| > B_THR (= 3 ticks, ~3.5σ) → trade.

  basis > +B_THR  → VELVETFRUIT rich vs options   → sell VELVETFRUIT
  basis < -B_THR  → VELVETFRUIT cheap vs options  → buy  VELVETFRUIT

  Research also notes: this is position-limit-bound, not signal-bound.
  So we size up to B_MAX_POS per direction, and exit ALL the way back
  to 0 when basis re-crosses zero (full reversion).

Unchanged from v6:
  HYDROGEL_PACK, VEV_4000, VEV_4500.
  ATM / OTM strikes stay disabled.
  No VELVETFRUIT MM (confirmed −EV).
"""
from typing import Dict, List, Optional, Tuple
from statistics import NormalDist
import json
import math

from datamodel import Order, OrderDepth, TradingState


_N = NormalDist()
DAYS_PER_YEAR = 365
TTE_DAYS_LIVE = 5.0


class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
        "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
        "VEV_6500": 300,
    }

    VOUCHER_STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500}

    # HYDROGEL (v6)
    H_ANCHOR = 9990.0
    H_CLIP = 30.0
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 1.0
    H_PENNY_EDGE = 1.5
    H_INV_SKEW = 0.015
    H_MAX_POST_SIZE = 20
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8
    H_SHOCK_MOVE = 15.0

    # Deep-ITM voucher (v5)
    SIGMA = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.005
    VS_MAX_POST_SIZE = 40
    VS_WIDE_SPREAD = 3

    # Basis arb parameters
    # basis = VELVETFRUIT.mid - mean(VEV_4000+4000, VEV_4500+4500)
    # Research: std 0.84, |max| 6. Trade on 3.5σ.
    B_THR_OPEN = 3.0       # open position when |basis| > this
    B_THR_CLOSE = 0.5      # close back to 0 when |basis| < this
    B_MAX_POS = 150        # inventory cap on VELVETFRUIT (vs limit 200)
    B_POST_SIZE = 50       # quote size when basis signal fires
    B_TAKE_SIZE = 80       # take size when crossing

    # ---- helpers ----
    def _book(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys); ba = min(sells)
        return {
            "buys": dict(sorted(buys.items(), reverse=True)),
            "sells": dict(sorted(sells.items())),
            "bb": bb, "ba": ba, "bv": buys[bb], "av": sells[ba],
            "spread": ba - bb, "touch_mid": 0.5 * (bb + ba),
        }

    def _cap_size(self, max_size: int, pos: int, side: str, cap: int, limit: int) -> int:
        if cap <= 0:
            return 0
        ratio = 1.0 - min(0.7, abs(pos) / limit)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    @staticmethod
    def _opt_theo(S: float, K: int, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return max(0.0, S - K)
        sq = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sq
        d2 = d1 - sq
        return S * _N.cdf(d1) - K * _N.cdf(d2)

    @staticmethod
    def _tte_years(ts: int) -> float:
        tte_days = TTE_DAYS_LIVE - ts / 1e6
        if tte_days <= 0:
            return 0.0
        return tte_days / DAYS_PER_YEAR

    # ---- HYDROGEL (v6) ----
    def _trade_hydrogel(self, od: OrderDepth, pos: int,
                        prev_mid: Optional[float]) -> Tuple[List[Order], float]:
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], prev_mid if prev_mid is not None else 0.0
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]; touch_mid = book["touch_mid"]

        shock = (prev_mid is not None
                 and abs(touch_mid - prev_mid) > self.H_SHOCK_MOVE)
        if shock:
            fair = touch_mid
        else:
            fair_adj = max(-self.H_CLIP, min(self.H_CLIP, touch_mid - self.H_ANCHOR))
            fair = self.H_ANCHOR + fair_adj

        working = pos
        orders: List[Order] = []

        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0: break
            skew = fair - self.H_INV_SKEW * working
            if ap <= skew - self.H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q

        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0: break
            skew = fair - self.H_INV_SKEW * working
            if bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q

        if shock:
            return orders, touch_mid

        skew = fair - self.H_INV_SKEW * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.H_MAX_POST_SIZE, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(self.H_MAX_POST_SIZE, working, "sell", sell_cap, limit)

        if spread >= self.H_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - self.H_PENNY_EDGE))
            ask_price = max(ba - 1, math.ceil(skew + self.H_PENNY_EDGE))
        else:
            bid_price = math.floor(skew - self.H_PASSIVE_OFFSET)
            ask_price = math.ceil(skew + self.H_PASSIVE_OFFSET)
        bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
        ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)

        if bid_price < ask_price:
            if bid_size > 0: orders.append(Order(prod, bid_price, bid_size))
            if ask_size > 0: orders.append(Order(prod, ask_price, -ask_size))
        return orders, touch_mid

    # ---- Deep-ITM voucher (v5) ----
    def _trade_deep_itm(self, name: str, K: int, od: OrderDepth,
                        pos: int, S: float, T: float) -> List[Order]:
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        fair = self._opt_theo(S, K, T, self.SIGMA)
        working = pos
        orders: List[Order] = []

        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0: break
            skew = fair - self.VS_INV_SKEW * working
            if ap <= skew - self.VS_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(name, ap, q)); working += q
            elif working < 0 and ap <= skew:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(name, ap, q)); working += q

        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0: break
            skew = fair - self.VS_INV_SKEW * working
            if bp >= skew + self.VS_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q
            elif working > 0 and bp >= skew:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q

        skew = fair - self.VS_INV_SKEW * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.VS_MAX_POST_SIZE, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(self.VS_MAX_POST_SIZE, working, "sell", sell_cap, limit)

        if spread >= self.VS_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - self.VS_PENNY_EDGE))
            ask_price = max(ba - 1, math.ceil(skew + self.VS_PENNY_EDGE))
            bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
            ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)
            if bid_price < ask_price:
                if bid_size > 0: orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0: orders.append(Order(name, ask_price, -ask_size))
        return orders

    # ---- NEW: basis arb on VELVETFRUIT ----
    def _trade_basis(self, u_od: OrderDepth, u_pos: int,
                     books: Dict[str, dict], S_market: float) -> List[Order]:
        name = "VELVETFRUIT_EXTRACT"
        limit = self.LIMITS[name]
        u_book = self._book(u_od)
        if not u_book:
            return []

        # Need both deep-ITM books to synthesise S.
        b4 = books.get("VEV_4000")
        b45 = books.get("VEV_4500")
        if b4 is None or b45 is None:
            return []

        s4 = b4["touch_mid"] + 4000
        s45 = b45["touch_mid"] + 4500
        s_synth = 0.5 * (s4 + s45)
        basis = S_market - s_synth

        bb = u_book["bb"]; ba = u_book["ba"]
        working = u_pos
        orders: List[Order] = []
        soft_cap = min(limit, self.B_MAX_POS)

        # Open positions when basis breaches threshold.
        if basis > self.B_THR_OPEN:
            # Underlying rich — sell.
            # Take the best bid first.
            cap = soft_cap + working
            if cap > 0:
                qtake = min(u_book["bv"], cap, self.B_TAKE_SIZE)
                if qtake > 0:
                    orders.append(Order(name, bb, -qtake)); working -= qtake
            # Post passive ask one in from touch to catch more.
            cap = max(0, soft_cap + working)
            psize = min(self.B_POST_SIZE, cap)
            if psize > 0:
                orders.append(Order(name, ba - 1, -psize))
        elif basis < -self.B_THR_OPEN:
            # Underlying cheap — buy.
            cap = soft_cap - working
            if cap > 0:
                qtake = min(u_book["av"], cap, self.B_TAKE_SIZE)
                if qtake > 0:
                    orders.append(Order(name, ba, qtake)); working += qtake
            cap = max(0, soft_cap - working)
            psize = min(self.B_POST_SIZE, cap)
            if psize > 0:
                orders.append(Order(name, bb + 1, psize))
        else:
            # Inside the band: flatten toward zero when basis sign
            # flips through zero (full reversion).
            if abs(basis) < self.B_THR_CLOSE:
                if working > 0:
                    orders.append(Order(name, bb, -min(working, u_book["bv"])))
                elif working < 0:
                    orders.append(Order(name, ba, min(-working, u_book["av"])))

        return orders

    def run(self, state: TradingState):
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
            )
            result["HYDROGEL_PACK"] = orders
            saved["h_prev_mid"] = new_mid

        # Pre-compute all relevant books once.
        books: Dict[str, dict] = {}
        for p in ("VELVETFRUIT_EXTRACT", "VEV_4000", "VEV_4500"):
            od = state.order_depths.get(p)
            if od is not None:
                b = self._book(od)
                if b is not None:
                    books[p] = b

        u_book = books.get("VELVETFRUIT_EXTRACT")
        if u_book is not None:
            S = u_book["touch_mid"]
            T = self._tte_years(state.timestamp)

            for name, K in self.VOUCHER_STRIKES.items():
                od = state.order_depths.get(name)
                if od is not None:
                    result[name] = self._trade_deep_itm(
                        name, K, od, pos.get(name, 0), S, T,
                    )

            # Basis arb on the underlying.
            result["VELVETFRUIT_EXTRACT"] = self._trade_basis(
                state.order_depths["VELVETFRUIT_EXTRACT"],
                pos.get("VELVETFRUIT_EXTRACT", 0),
                books, S,
            )

        return result, 0, json.dumps(saved)
