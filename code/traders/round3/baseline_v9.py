"""
Round 3 baseline v9 — 2026-04-24.

v5/v6 pathology seen in calibrated-hybrid backtest:
  * HYDROGEL day 2: 23 buy fills (300 qty) vs 9 sell fills (100 qty).
    Strategy loads to +200 long, realized PnL = 3.6k but unrealized
    PnL = 19.3k (50-tick mark-to-market on 200 long) — most "profit"
    is paper, evaporates when market drops.
  * Max drawdown −28k to −38k per day.
  * ALL fills are take_visible; zero passive fills (round1 calibration
    doesn't know HYDROGEL_PACK passive-fill behavior).

v9 fix (HYDROGEL only, minimal risk changes):
  1. Inventory soft cap at H_SOFT_POS (= 100, not limit=200). Prevents
     runaway loading on trend days.
  2. Aggressive flatten when |pos| > H_FLATTEN_AT: skew fair toward
     the reducing side so we actually close inventory.
  3. Shrink H_CLIP from 30 → 20 to reduce the "fair-crosses-market"
     aggressive-take during trend moves.
  4. Keep v6 shock detector.

Unchanged:
  * VEV_4000, VEV_4500: working as-is (+7k/day jmerle).
  * No other products (ATM tested −EV, VELVET tested −EV).
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

    # HYDROGEL — v9 tightened
    H_ANCHOR = 9990.0
    H_CLIP = 20.0               # was 30 — narrower fair range
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 1.0
    H_PENNY_EDGE = 1.5
    H_INV_SKEW = 0.015
    H_MAX_POST_SIZE = 20
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8
    H_SHOCK_MOVE = 15.0
    H_SOFT_POS = 100            # don't let |pos| exceed this
    H_FLATTEN_AT = 60           # above this, bias fair toward flatten
    H_FLATTEN_SKEW = 0.05       # extra skew per unit once flatten kicks in

    # Deep-ITM voucher
    SIGMA = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.005
    VS_MAX_POST_SIZE = 40
    VS_WIDE_SPREAD = 3

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

    # ---- HYDROGEL ----
    def _trade_hydrogel(self, od: OrderDepth, pos: int,
                        prev_mid: Optional[float]) -> Tuple[List[Order], float]:
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        soft_cap = self.H_SOFT_POS
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

        # Extra flatten-skew once |pos| > H_FLATTEN_AT so we actually close.
        eff_skew = self.H_INV_SKEW
        if abs(pos) > self.H_FLATTEN_AT:
            eff_skew += self.H_FLATTEN_SKEW

        working = pos
        orders: List[Order] = []

        for ap, av in book["sells"].items():
            cap = soft_cap - working
            if cap <= 0: break
            skew = fair - eff_skew * working
            if ap <= skew - self.H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q

        for bp, bv in book["buys"].items():
            cap = soft_cap + working
            if cap <= 0: break
            skew = fair - eff_skew * working
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

        skew = fair - eff_skew * working
        buy_cap = max(0, soft_cap - working)
        sell_cap = max(0, soft_cap + working)
        bid_size = self._cap_size(self.H_MAX_POST_SIZE, working, "buy", buy_cap, soft_cap)
        ask_size = self._cap_size(self.H_MAX_POST_SIZE, working, "sell", sell_cap, soft_cap)

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

    # ---- Deep-ITM voucher ----
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

        u_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if u_od is not None:
            u_book = self._book(u_od)
            if u_book is not None:
                S = u_book["touch_mid"]
                T = self._tte_years(state.timestamp)
                for name, K in self.VOUCHER_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is not None:
                        result[name] = self._trade_deep_itm(
                            name, K, od, pos.get(name, 0), S, T,
                        )
        return result, 0, json.dumps(saved)
