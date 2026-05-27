"""
Round 3 smile-quadratic hedged v1 (2026-04-24).

Built on baseline_v5 (ship, +168k 3-day jmerle). Adds two new sleeves that
were flagged as untried in the v5→v16 dead-end catalogue:

(A) ATM smile MM on VEV_5000..VEV_5500
    - Each tick, invert BS for market IV at each voucher mid.
    - Update a per-strike EMA `iv_ema[K]`, persisted via traderData so
      day N+1 starts with day N's final smile.
    - Fit quadratic `iv_fair(k) = a + b*k + c*k²` across per-strike
      EMAs (k = log(K/S)). 3x3 least-squares via Cramer's rule.
    - Compute curve-implied BS fair per strike and post passive two-
      sided quotes `fair ± MIN_EDGE - SKEW*pos/SKEW_DENOM`, capped
      strictly inside touch.

(B) Aggregate net-delta hedge via VELVETFRUIT_EXTRACT
    - Sum spot_pos + Σ pos_K·delta_K using curve IV for ATM strikes
      and delta=1 for deep-ITM V_4000/V_4500.
    - When |net_delta| > HEDGE_DELTA_THRESHOLD, sweep VFE toward
      −voucher_delta using visible bid/ask, one-shot at touch.

HYDROGEL + V_4000/V_4500 sleeves inherited unchanged from v5 so the
+168k ship floor is intact; any PnL delta is purely from the smile
sleeve and the hedge.
"""
from typing import Dict, List, Optional, Tuple
from statistics import NormalDist
import json
import math

from datamodel import Order, OrderDepth, TradingState


_N = NormalDist()
DAYS_PER_YEAR = 365
TTE_DAYS_LIVE = 5.0


def _phi(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bs_call(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K)
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sq
    d2 = d1 - sq
    return S * _N.cdf(d1) - K * _N.cdf(d2)


def _bs_delta(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 1.0 if S > K else 0.0
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sq
    return _N.cdf(d1)


def _bs_vega(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sq
    return S * _phi(d1) * math.sqrt(T)


def _implied_vol(price: float, S: float, K: float, T: float,
                  seed: float = 0.23) -> Optional[float]:
    intrinsic = max(0.0, S - K)
    if price <= intrinsic + 1e-6 or T <= 0:
        return None
    sigma = max(0.02, min(2.0, seed))
    for _ in range(25):
        theo = _bs_call(S, K, T, sigma)
        diff = theo - price
        if abs(diff) < 1e-4:
            return sigma
        vega = _bs_vega(S, K, T, sigma)
        if vega < 1e-8:
            break
        sigma -= diff / vega
        if sigma < 0.02 or sigma > 2.0:
            break
    lo, hi = 0.02, 2.0
    flo = _bs_call(S, K, T, lo) - price
    fhi = _bs_call(S, K, T, hi) - price
    if flo * fhi > 0:
        return None
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        fmid = _bs_call(S, K, T, mid) - price
        if abs(fmid) < 1e-4:
            return mid
        if flo * fmid <= 0:
            hi = mid; fhi = fmid
        else:
            lo = mid; flo = fmid
    return 0.5 * (lo + hi)


def _quadratic_fit(ks: List[float], ys: List[float]) -> Optional[Tuple[float, float, float]]:
    n = len(ks)
    if n < 3:
        return None
    s0 = float(n)
    s1 = sum(ks); s2 = sum(k * k for k in ks)
    s3 = sum(k * k * k for k in ks); s4 = sum(k ** 4 for k in ks)
    t0 = sum(ys); t1 = sum(k * y for k, y in zip(ks, ys))
    t2 = sum(k * k * y for k, y in zip(ks, ys))
    # Solve M [a,b,c]^T = [t0,t1,t2]^T
    #   [s0 s1 s2] [a]   [t0]
    #   [s1 s2 s3] [b] = [t1]
    #   [s2 s3 s4] [c]   [t2]
    det = (
        s0 * (s2 * s4 - s3 * s3)
        - s1 * (s1 * s4 - s3 * s2)
        + s2 * (s1 * s3 - s2 * s2)
    )
    if abs(det) < 1e-12:
        return None
    da = (
        t0 * (s2 * s4 - s3 * s3)
        - s1 * (t1 * s4 - s3 * t2)
        + s2 * (t1 * s3 - s2 * t2)
    )
    db = (
        s0 * (t1 * s4 - s3 * t2)
        - t0 * (s1 * s4 - s3 * s2)
        + s2 * (s1 * t2 - t1 * s2)
    )
    dc = (
        s0 * (s2 * t2 - t1 * s3)
        - s1 * (s1 * t2 - t1 * s2)
        + t0 * (s1 * s3 - s2 * s2)
    )
    return da / det, db / det, dc / det


class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
        "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
        "VEV_6500": 300,
    }

    # v5-inherited deep-ITM strikes (pure intrinsic)
    DEEP_ITM_STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500}
    # Smile-fit universe — liquid ATM/OTM strikes where BS fair is
    # load-bearing (time value > 1 tick).
    ATM_STRIKES = {
        "VEV_5000": 5000, "VEV_5100": 5100, "VEV_5200": 5200,
        "VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500,
    }

    # HYDROGEL_PACK peak (v5)
    H_ANCHOR = 9990.0
    H_CLIP = 30.0
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 1.0
    H_PENNY_EDGE = 1.5
    H_INV_SKEW = 0.015
    H_MAX_POST_SIZE = 20
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8

    # Deep-ITM voucher sleeve (v5)
    SIGMA_DEEP = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.005
    VS_MAX_POST_SIZE = 40
    VS_WIDE_SPREAD = 3

    # Smile sleeve
    IV_EMA_ALPHA = 1.0 / 200.0       # half-life ~140 ticks
    IV_SEED = 0.23                    # cold-start seed
    IV_MIN = 0.05
    IV_MAX = 1.0
    # Quadratic fit guard: reject near-singular fits and revert to EMA
    SMILE_MIN_POINTS = 3
    ATM_MIN_EDGE = 1.0                # MIN_EDGE ticks above/below fair
    ATM_INV_SKEW = 0.02               # soft-cap coefficient
    ATM_SKEW_DENOM = 50.0             # scales skew so at pos=SKEW_DENOM we shift 1 edge
    ATM_MAX_POST_SIZE = 15
    ATM_MIN_SPREAD_TO_MM = 2          # need spread >= 2 to place two-sided inside
    ATM_PER_STRIKE_CAP = 250          # soft per-strike cap (< limit 300)

    # Aggregate delta hedge via VFE
    ENABLE_HEDGE = True
    HEDGE_DELTA_THRESHOLD = 25.0
    HEDGE_MAX_PER_TICK = 40

    # ------------------------------------------------------------------
    def _book(self, od: OrderDepth) -> Optional[dict]:
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
    def _tte_years(ts: int) -> float:
        tte_days = TTE_DAYS_LIVE - ts / 1e6
        if tte_days <= 0:
            return 0.0
        return tte_days / DAYS_PER_YEAR

    # ------------------------------------------------------------------
    # v5-inherited sleeves
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
        return orders

    def _trade_deep_voucher(self, name: str, K: int, od: OrderDepth,
                             pos: int, S: float, T: float) -> List[Order]:
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        fair = _bs_call(S, K, T, self.SIGMA_DEEP)
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

    # ------------------------------------------------------------------
    # Smile sleeve
    def _update_iv_emas(
        self, iv_ema: Dict[str, float], S: float, T: float,
        books: Dict[str, dict],
    ) -> None:
        if T <= 0:
            return
        alpha = self.IV_EMA_ALPHA
        for name, K in self.ATM_STRIKES.items():
            book = books.get(name)
            if book is None:
                continue
            mid = book["touch_mid"]
            seed = iv_ema.get(name, self.IV_SEED)
            iv = _implied_vol(mid, S, float(K), T, seed=seed)
            if iv is None or iv < self.IV_MIN or iv > self.IV_MAX:
                continue
            prev = iv_ema.get(name)
            if prev is None:
                iv_ema[name] = iv
            else:
                iv_ema[name] = (1.0 - alpha) * prev + alpha * iv

    def _fit_smile(
        self, iv_ema: Dict[str, float], S: float,
    ) -> Optional[Tuple[float, float, float]]:
        ks: List[float] = []
        ys: List[float] = []
        for name, K in self.ATM_STRIKES.items():
            if name in iv_ema:
                ks.append(math.log(float(K) / S))
                ys.append(iv_ema[name])
        if len(ks) < self.SMILE_MIN_POINTS:
            return None
        return _quadratic_fit(ks, ys)

    def _smile_iv(
        self, coefs: Optional[Tuple[float, float, float]],
        iv_ema: Dict[str, float], name: str, S: float, K: int,
    ) -> Optional[float]:
        if coefs is not None:
            k = math.log(float(K) / S)
            a, b, c = coefs
            iv = a + b * k + c * k * k
            if self.IV_MIN <= iv <= self.IV_MAX:
                return iv
        # Fallback: per-strike EMA
        return iv_ema.get(name)

    def _trade_smile_voucher(
        self, name: str, K: int, od: OrderDepth, pos: int,
        S: float, T: float, iv: float,
    ) -> List[Order]:
        limit = min(self.LIMITS[name], self.ATM_PER_STRIKE_CAP)
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        fair = _bs_call(S, float(K), T, iv)
        skew_shift = self.ATM_INV_SKEW * (pos / self.ATM_SKEW_DENOM)
        orders: List[Order] = []

        if spread < self.ATM_MIN_SPREAD_TO_MM:
            return orders

        # "fair - MIN_EDGE - inv_skew" / "fair + MIN_EDGE - inv_skew"
        raw_bid = fair - self.ATM_MIN_EDGE - skew_shift
        raw_ask = fair + self.ATM_MIN_EDGE - skew_shift

        bid_price = int(math.floor(raw_bid))
        ask_price = int(math.ceil(raw_ask))

        # Strictly inside touch
        bid_price = min(bid_price, ba - 1)
        ask_price = max(ask_price, bb + 1)

        if bid_price >= ask_price:
            return orders

        buy_cap = max(0, limit - pos)
        sell_cap = max(0, limit + pos)
        bid_size = self._cap_size(self.ATM_MAX_POST_SIZE, pos, "buy", buy_cap, limit)
        ask_size = self._cap_size(self.ATM_MAX_POST_SIZE, pos, "sell", sell_cap, limit)

        if bid_price > bb and bid_size > 0:
            orders.append(Order(name, bid_price, bid_size))
        if ask_price < ba and ask_size > 0:
            orders.append(Order(name, ask_price, -ask_size))
        return orders

    # ------------------------------------------------------------------
    def _hedge_orders(
        self, state: TradingState, spot_book: dict, T: float,
        coefs: Optional[Tuple[float, float, float]],
        iv_ema: Dict[str, float], existing_vfe_orders: List[Order],
    ) -> List[Order]:
        if not self.ENABLE_HEDGE:
            return []
        spot_pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
        # Account for any pending self-orders on VFE that will touch pos.
        pending_delta = sum(o.quantity for o in existing_vfe_orders)
        effective_spot = spot_pos + pending_delta
        S = spot_book["touch_mid"]

        net_delta = float(effective_spot)
        for name, K in self.DEEP_ITM_STRIKES.items():
            p = state.position.get(name, 0)
            # Deep-ITM: delta ≈ 1
            net_delta += p * 1.0
        for name, K in self.ATM_STRIKES.items():
            p = state.position.get(name, 0)
            if p == 0:
                continue
            iv = self._smile_iv(coefs, iv_ema, name, S, K)
            if iv is None:
                iv = self.IV_SEED
            net_delta += p * _bs_delta(S, float(K), T, iv)

        if abs(net_delta) < self.HEDGE_DELTA_THRESHOLD:
            return []

        name = "VELVETFRUIT_EXTRACT"
        limit = self.LIMITS[name]
        orders: List[Order] = []
        # Sweep toward fully offsetting voucher delta.
        target_change = -net_delta
        qty_cap = self.HEDGE_MAX_PER_TICK
        if target_change > 0:
            # Buy VFE
            want = min(int(round(target_change)), limit - effective_spot, qty_cap,
                       spot_book["av"])
            if want > 0:
                orders.append(Order(name, spot_book["ba"], want))
        else:
            want = min(int(round(-target_change)), limit + effective_spot, qty_cap,
                       spot_book["bv"])
            if want > 0:
                orders.append(Order(name, spot_book["bb"], -want))
        return orders

    # ------------------------------------------------------------------
    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}
        iv_ema: Dict[str, float] = dict(saved.get("iv_ema", {}))
        result: Dict[str, List[Order]] = {}
        pos = state.position

        if "HYDROGEL_PACK" in state.order_depths:
            result["HYDROGEL_PACK"] = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0),
            )

        # Collect voucher books + spot book
        books: Dict[str, dict] = {}
        for name in ["VELVETFRUIT_EXTRACT"] + list(self.DEEP_ITM_STRIKES) + list(self.ATM_STRIKES):
            od = state.order_depths.get(name)
            if od is not None:
                book = self._book(od)
                if book is not None:
                    books[name] = book

        spot_book = books.get("VELVETFRUIT_EXTRACT")
        if spot_book is not None:
            S = spot_book["touch_mid"]
            T = self._tte_years(state.timestamp)

            # Update IV EMAs, then fit smile.
            self._update_iv_emas(iv_ema, S, T, books)
            coefs = self._fit_smile(iv_ema, S)

            # Deep-ITM sleeve (v5-unchanged) — flat sigma is fine here.
            for name, K in self.DEEP_ITM_STRIKES.items():
                od = state.order_depths.get(name)
                if od is not None:
                    result[name] = self._trade_deep_voucher(
                        name, K, od, pos.get(name, 0), S, T,
                    )

            # ATM smile sleeve.
            if T > 0:
                for name, K in self.ATM_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is None:
                        continue
                    iv = self._smile_iv(coefs, iv_ema, name, S, K)
                    if iv is None:
                        continue
                    result[name] = self._trade_smile_voucher(
                        name, K, od, pos.get(name, 0), S, T, iv,
                    )

            # Net-delta hedge into VFE. Hedge orders OVERWRITE any
            # prior VFE entry (we do not otherwise trade spot).
            hedge = self._hedge_orders(state, spot_book, T, coefs, iv_ema, [])
            if hedge:
                result["VELVETFRUIT_EXTRACT"] = hedge

        saved["iv_ema"] = iv_ema
        return result, 0, json.dumps(saved)
