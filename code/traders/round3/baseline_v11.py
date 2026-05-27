"""
Round 3 baseline v11 — 2026-04-24.

Goal: keep the proven v6 sleeves, but make them slightly less brittle.

Changes vs v6:
  * HYDROGEL_PACK keeps the exact v6 fair logic; only endgame inventory
    reduction is added.
  * Deep-ITM voucher pricing is left spot-based (same as v6); the first
    cross-asset blend regressed too much.
  * Very light endgame flattening only when inventory is already large.

This file stays standalone so it can be uploaded directly.
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
        "VEV_4000": 300,
        "VEV_4500": 300,
        "VEV_5000": 300,
        "VEV_5100": 300,
        "VEV_5200": 300,
        "VEV_5300": 300,
        "VEV_5400": 300,
        "VEV_5500": 300,
        "VEV_6000": 300,
        "VEV_6500": 300,
    }

    VOUCHER_STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500}

    # HYDROGEL_PACK: exact v6 logic plus light endgame flattening.
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
    H_ENDGAME_START = 990000
    H_ENDGAME_POS = 120

    # Deep-ITM vouchers: keep the proven v6 spot-based fair.
    SIGMA = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.005
    VS_MAX_POST_SIZE = 40
    VS_WIDE_SPREAD = 3
    VS_ENDGAME_START = 975000
    VS_ENDGAME_POS = 50

    def _book(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys)
        ba = min(sells)
        return {
            "buys": dict(sorted(buys.items(), reverse=True)),
            "sells": dict(sorted(sells.items())),
            "bb": bb,
            "ba": ba,
            "bv": buys[bb],
            "av": sells[ba],
            "spread": ba - bb,
            "touch_mid": 0.5 * (bb + ba),
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

    @staticmethod
    def _clip(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    def _trade_hydrogel(
        self,
        od: OrderDepth,
        pos: int,
        prev_mid: Optional[float],
        ts: int,
    ) -> Tuple[List[Order], float]:
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], prev_mid if prev_mid is not None else 0.0
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        touch_mid = book["touch_mid"]

        move = 0.0 if prev_mid is None else touch_mid - prev_mid
        shock = prev_mid is not None and abs(move) > self.H_SHOCK_MOVE
        if shock:
            fair = touch_mid
        else:
            fair_adj = self._clip(touch_mid - self.H_ANCHOR, -self.H_CLIP, self.H_CLIP)
            fair = self.H_ANCHOR + fair_adj
        working = pos
        orders: List[Order] = []

        if ts >= self.H_ENDGAME_START and abs(working) >= self.H_ENDGAME_POS:
            if working > 0:
                for bp, bv in book["buys"].items():
                    q = min(bv, working)
                    if q > 0:
                        orders.append(Order(prod, bp, -q))
                        working -= q
                    if working <= 0:
                        break
            elif working < 0:
                for ap, av in book["sells"].items():
                    q = min(av, -working)
                    if q > 0:
                        orders.append(Order(prod, ap, q))
                        working += q
                    if working >= 0:
                        break
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
            if bid_size > 0:
                orders.append(Order(prod, bid_price, bid_size))
            if ask_size > 0:
                orders.append(Order(prod, ask_price, -ask_size))
        return orders, touch_mid

    def _trade_voucher(
        self,
        name: str,
        K: int,
        od: OrderDepth,
        pos: int,
        spot_estimate: float,
        T: float,
        ts: int,
    ) -> List[Order]:
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        fair = self._opt_theo(spot_estimate, K, T, self.SIGMA)
        working = pos
        orders: List[Order] = []

        if ts >= self.VS_ENDGAME_START and abs(working) >= self.VS_ENDGAME_POS:
            if working > 0:
                for bp, bv in book["buys"].items():
                    q = min(bv, working)
                    if q > 0:
                        orders.append(Order(name, bp, -q))
                        working -= q
                    if working <= 0:
                        break
            elif working < 0:
                for ap, av in book["sells"].items():
                    q = min(av, -working)
                    if q > 0:
                        orders.append(Order(name, ap, q))
                        working += q
                    if working >= 0:
                        break
            return orders

        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - self.VS_INV_SKEW * working
            if ap <= skew - self.VS_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(name, ap, q))
                    working += q
            elif working < 0 and ap <= skew:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(name, ap, q))
                    working += q

        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair - self.VS_INV_SKEW * working
            if bp >= skew + self.VS_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(name, bp, -q))
                    working -= q
            elif working > 0 and bp >= skew:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(name, bp, -q))
                    working -= q

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
                if bid_size > 0:
                    orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0:
                    orders.append(Order(name, ask_price, -ask_size))
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
            for name, K in self.VOUCHER_STRIKES.items():
                od = state.order_depths.get(name)
                if od is None:
                    continue
                result[name] = self._trade_voucher(
                    name,
                    K,
                    od,
                    pos.get(name, 0),
                    spot_mid,
                    T,
                    state.timestamp,
                )

        return result, 0, json.dumps(saved)
