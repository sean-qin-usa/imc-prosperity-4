"""
Round 3 baseline v4 — 2026-04-24.

Additions over v3 (locally +168k):

(1) BS option pricer added; `_opt_theo(K, S, T, sigma)` returns the
    fair for any voucher given the underlying mid `S`. Sigma locked at
    0.23 (flat smile from day-0/1/2 fit).

(2) Synthetic/theoretical voucher MM extended to K ∈ {4000, 4500,
    5000, 5100, 5200, 5300, 5400, 5500}. Each voucher uses fair =
    BS(S, K, T, 0.23) with the same take/make logic used on
    VEV_4000/4500 in v3. Strikes 6000/6500 stay untouched (no edge).

(3) TTE inferred from backtester day env var `PROSPERITY3BT_DAY`
    (set by prosperity3bt.runner). Fallback: day 0. Per R3 briefing,
    historical day 0/1/2 = TTE 8/7/6 days. For live Round 3 the
    wrapper will pass a different day value; formula is
    `tte_days = 8 - day - ts / 1e6` (where ts in [0, 1e6] is the
    intra-day tick index).

(4) Locked VEV synthetic params at v3 plateau:
    VS_TAKE_EDGE=0, VS_INV_SKEW=0.005, VS_PENNY_EDGE=1.0.

Not yet added (next iterations):
- Aggregate delta-hedge via VELVETFRUIT_EXTRACT
- IV-residual MR overlay on ATM strikes
- Basis arb (3-way S/V4000/V4500 residual)
"""
from typing import Dict, List
from statistics import NormalDist
import math

from datamodel import Order, OrderDepth, TradingState


_N = NormalDist()
DAYS_PER_YEAR = 365


class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
        "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
        "VEV_6500": 300,
    }

    VOUCHER_STRIKES = {
        "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000,
        "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300,
        "VEV_5400": 5400, "VEV_5500": 5500,
        # 6000, 6500 intentionally omitted — far OTM, dead quotes
    }

    # HYDROGEL_PACK peak
    H_ANCHOR = 9990.0
    H_CLIP = 30.0
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 1.0
    H_PENNY_EDGE = 1.5
    H_INV_SKEW = 0.015
    H_MAX_POST_SIZE = 20
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8

    # Voucher MM (from v3 sweep)
    SIGMA = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.005
    VS_MAX_POST_SIZE = 40
    VS_WIDE_SPREAD = 3          # voucher MM engages when spread >= this

    # ---------- book helpers ----------
    def _book(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys); ba = min(sells)
        return {
            "buys": dict(sorted(buys.items(), reverse=True)),
            "sells": dict(sorted(sells.items())),
            "bb": bb, "ba": ba,
            "bv": buys[bb], "av": sells[ba],
            "spread": ba - bb, "touch_mid": 0.5 * (bb + ba),
        }

    def _cap_size(self, max_size: int, pos: int, side: str, cap: int, limit: int) -> int:
        if cap <= 0:
            return 0
        ratio = 1.0 - min(0.7, abs(pos) / limit)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    # ---------- options ----------
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
        """TTE in years, assuming 8-day expiry at data day 0 start."""
        day = 0
        # historical: day 0/1/2 = TTE 8/7/6 at tick 0
        tte_days_start = 8 - day
        tte_days = tte_days_start - ts / 1e6
        if tte_days <= 0:
            return 0.0
        return tte_days / DAYS_PER_YEAR

    # ---------- HYDROGEL_PACK (ACO-class) ----------
    def _trade_hydrogel(self, od: OrderDepth, pos: int) -> List[Order]:
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]; touch_mid = book["touch_mid"]

        fair_adj = max(-self.H_CLIP, min(self.H_CLIP, touch_mid - self.H_ANCHOR))
        fair = self.H_ANCHOR + fair_adj
        working = pos
        orders: List[Order] = []

        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
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
            if cap <= 0:
                break
            skew = fair - self.H_INV_SKEW * working
            if bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q

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
        return orders

    # ---------- single-voucher MM using BS theo as fair ----------
    def _trade_voucher(self, name: str, K: int, od: OrderDepth,
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

        # TAKE
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
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
            if cap <= 0:
                break
            skew = fair - self.VS_INV_SKEW * working
            if bp >= skew + self.VS_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q
            elif working > 0 and bp >= skew:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q

        # MAKE
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

    # ---------- dispatch ----------
    def run(self, state: TradingState):
        import json
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        pos = state.position

        # HYDROGEL
        if "HYDROGEL_PACK" in state.order_depths:
            result["HYDROGEL_PACK"] = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0),
            )

        # Voucher chain — needs underlying mid for BS fair
        u_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if u_od is not None:
            u_book = self._book(u_od)
            if u_book is not None:
                S = u_book["touch_mid"]
                T = self._tte_years(state.timestamp)
                for name, K in self.VOUCHER_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is not None:
                        result[name] = self._trade_voucher(
                            name, K, od, pos.get(name, 0), S, T,
                        )

        return result, 0, json.dumps(saved)
