"""
Round 3 baseline v7 — 2026-04-24.

Builds on v6. v6 fixed a one-tick shock event but did not add new
alpha — it still leaves strikes 5000-5500 (the thick-liquidity ATM
band) entirely untraded.

Memory [flat_sigma_options_trap.md]: a flat-sigma BS fair loses money
on ATM strikes even when the smile is flat. Fix = EMA of (mid - BS_theo)
as a learned residual. This is exactly the approach in
p3_combined_v1.py lines 385-441.

v7 additions on top of v6 (v6 is preserved byte-for-byte otherwise):
  1. ATM strikes {5000,5100,5200,5300,5400,5500} traded via
     fair = BS(S,K,TTE,sigma=0.23) + EMA(mid - BS_theo, window=RES_WIN).
     MM around that fair with take/make edges.
  2. Volatility gate: skip strike if EMA(|diff - mean_diff|, window)
     is outside [ATM_SWITCH_MIN, ATM_SWITCH_MAX]. Too calm = no edge.
     Too wild = regime break, residual EMA stale.
  3. Warmup: require RES_WIN ticks of EMA history before trading.
  4. Soft inventory cap (ATM_MAX_POS < limit=300) so a single adverse
     day can't blow out the whole position budget.
  5. Residual-EMA state persisted in traderData across ticks.

Unchanged:
  - HYDROGEL_PACK: v6 shock detector + v5 anchor logic.
  - VEV_4000, VEV_4500: v5 intrinsic MM (was working).
  - VELVETFRUIT_EXTRACT: still skipped (-EV confirmed).
  - VEV_6000, VEV_6500: skipped (OTM, mid ~= 0).
"""
from typing import Dict, List, Tuple, Optional
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

    DEEP_ITM_STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500}
    ATM_STRIKES = {
        "VEV_5000": 5000, "VEV_5100": 5100, "VEV_5200": 5200,
        "VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500,
    }

    # ---- HYDROGEL_PACK (v5 peak + v6 shock) ----
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

    # ---- Deep-ITM voucher (v5 peak) ----
    SIGMA = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.005
    VS_MAX_POST_SIZE = 40
    VS_WIDE_SPREAD = 3

    # ---- ATM voucher IV-residual MM ----
    # v7 iter 1: params too loose; tight-spread ATM got adversely picked.
    # Tighten: require genuine residual volatility, wider edges, smaller pos.
    ATM_RES_WIN = 300
    ATM_SWITCH_WIN = 100
    ATM_SWITCH_MIN = 0.5       # was 0.15 — skip calm regimes (no real edge)
    ATM_SWITCH_MAX = 2.0       # was 3.0 — skip regime breaks
    ATM_WARMUP_TICKS = 150
    ATM_TAKE_EDGE = 2.0        # was 0.5 — only take on big dislocations
    ATM_MAKE_EDGE = 2.0        # was 1.0 — wider MM quote
    ATM_MAX_POST_SIZE = 10     # was 20 — smaller posts, less adverse exposure
    ATM_INV_SKEW = 0.02        # was 0.01 — flatten faster
    ATM_MAX_POS = 80           # was 150 — tight inventory cap

    # Strikes where edge is reliably positive (v7-iter1 day-by-day evidence).
    # 5000/5100/5200 were net −EV; 5300/5400/5500 were net +EV.
    # Start conservative: trade only the 3 outer strikes. Expand later.
    ATM_ENABLED_STRIKES = {"VEV_5300", "VEV_5400", "VEV_5500"}

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

    def _ema(self, saved: Dict, key: str, window: int, x: float) -> float:
        prev = saved.get(key)
        if prev is None:
            saved[key] = float(x)
            return float(x)
        alpha = 2.0 / (window + 1)
        new = prev + alpha * (x - prev)
        saved[key] = new
        return new

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

    # ---- HYDROGEL (identical to v6) ----
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

    # ---- Deep-ITM voucher (identical to v5/v6) ----
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

    # ---- ATM voucher (NEW: IV-residual) ----
    def _trade_atm(self, name: str, K: int, od: OrderDepth,
                   pos: int, S: float, T: float,
                   saved: Dict, tick_no: int) -> List[Order]:
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]; touch_mid = book["touch_mid"]

        theo = self._opt_theo(S, K, T, self.SIGMA)
        diff = touch_mid - theo

        # Always update EMAs so warmup can progress.
        mean_diff = self._ema(saved, f"_atm_m_{name}", self.ATM_RES_WIN, diff)
        sw = self._ema(saved, f"_atm_s_{name}", self.ATM_SWITCH_WIN, abs(diff - mean_diff))

        if tick_no < self.ATM_WARMUP_TICKS:
            return []

        # Regime gates: too calm -> no edge; too wild -> EMA stale.
        if sw < self.ATM_SWITCH_MIN or sw > self.ATM_SWITCH_MAX:
            # Gentle flatten if we carry stale inventory.
            out: List[Order] = []
            if pos > 0 and bb > 0:
                out.append(Order(name, bb, -min(pos, book["bv"])))
            elif pos < 0 and ba > 0:
                out.append(Order(name, ba, min(-pos, book["av"])))
            return out

        fair = theo + mean_diff
        soft_cap = min(limit, self.ATM_MAX_POS)
        working = pos
        orders: List[Order] = []

        # TAKE
        for ap, av in book["sells"].items():
            cap = soft_cap - working
            if cap <= 0: break
            skew = fair - self.ATM_INV_SKEW * working
            if ap <= skew - self.ATM_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(name, ap, q)); working += q
            else:
                break

        for bp, bv in book["buys"].items():
            cap = soft_cap + working
            if cap <= 0: break
            skew = fair - self.ATM_INV_SKEW * working
            if bp >= skew + self.ATM_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q
            else:
                break

        # MAKE (only when spread >= 2 to avoid immediate self-cross)
        if spread >= 2:
            skew = fair - self.ATM_INV_SKEW * working
            buy_cap = max(0, soft_cap - working)
            sell_cap = max(0, soft_cap + working)
            bid_size = self._cap_size(self.ATM_MAX_POST_SIZE, working, "buy", buy_cap, soft_cap)
            ask_size = self._cap_size(self.ATM_MAX_POST_SIZE, working, "sell", sell_cap, soft_cap)

            bid_price = min(bb + 1, int(math.floor(skew - self.ATM_MAKE_EDGE)))
            ask_price = max(ba - 1, int(math.ceil(skew + self.ATM_MAKE_EDGE)))
            bid_price = min(bid_price, ba - 1)
            ask_price = max(ask_price, bb + 1)

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
        tick_no = state.timestamp // 100

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

                for name, K in self.DEEP_ITM_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is not None:
                        result[name] = self._trade_deep_itm(
                            name, K, od, pos.get(name, 0), S, T,
                        )

                for name, K in self.ATM_STRIKES.items():
                    if name not in self.ATM_ENABLED_STRIKES:
                        continue
                    od = state.order_depths.get(name)
                    if od is not None:
                        result[name] = self._trade_atm(
                            name, K, od, pos.get(name, 0), S, T,
                            saved, tick_no,
                        )

        return result, 0, json.dumps(saved)
