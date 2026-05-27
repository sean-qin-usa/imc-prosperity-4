"""
Round 3 research prototype: quadratic IV-surface market making.

This is intentionally isolated from the shipping HYDROGEL sleeve so we
can judge the voucher-chain idea on its own:

1. infer per-strike implied vol from voucher touch mids
2. update slow per-strike IV EMAs in traderData
3. fit a quadratic smile in log-moneyness k = log(K / S)
4. convert fitted IVs back to fair prices via Black-Scholes
5. post passive inside-touch quotes around that fair
6. sweep VELVETFRUIT_EXTRACT only when voucher net delta gets too large

Important local-testing caveat: the jmerle backtester resets traderData
between separate day runs, so cross-day warm starts are implemented here
but not fully verifiable with the stock multi-day CLI.
"""
from typing import Dict, List, Optional, Tuple
from statistics import NormalDist
import json
import math

from datamodel import Order, OrderDepth, TradingState


_N = NormalDist()
DAYS_PER_YEAR = 365.0
TTE_DAYS_LIVE = 5.0


class Trader:
    LIMITS = {
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

    VOUCHER_STRIKES = {
        "VEV_4000": 4000,
        "VEV_4500": 4500,
        "VEV_5000": 5000,
        "VEV_5100": 5100,
        "VEV_5200": 5200,
        "VEV_5300": 5300,
        "VEV_5400": 5400,
        "VEV_5500": 5500,
        "VEV_6000": 6000,
        "VEV_6500": 6500,
    }

    FIT_STRIKES = tuple(VOUCHER_STRIKES.keys())
    QUOTE_STRIKES = tuple(VOUCHER_STRIKES.keys())

    IV_EMA_ALPHA = 0.01
    MIN_SIGMA = 0.05
    MAX_SIGMA = 1.20
    MIN_EDGE = 1.0
    SKEW_DENOM = 140.0
    MIN_SPREAD_TO_QUOTE = 2
    MAX_POST_SIZE = 12

    DELTA_THRESHOLD = 60.0
    DELTA_HEDGE_PRODUCT = "VELVETFRUIT_EXTRACT"

    LOG = False

    def _book(self, od: OrderDepth) -> Optional[dict]:
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

    @staticmethod
    def _clip(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    @staticmethod
    def _tte_years(ts: int) -> float:
        tte_days = TTE_DAYS_LIVE - ts / 1e6
        if tte_days <= 0:
            return 0.0
        return tte_days / DAYS_PER_YEAR

    @staticmethod
    def _bs_call(S: float, K: int, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return max(0.0, S - K)
        sq = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sq
        d2 = d1 - sq
        return S * _N.cdf(d1) - K * _N.cdf(d2)

    @staticmethod
    def _bs_delta(S: float, K: int, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return 1.0 if S > K else 0.0
        sq = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sq
        return _N.cdf(d1)

    @staticmethod
    def _bs_vega(S: float, K: int, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return 0.0
        sqrt_t = math.sqrt(T)
        sq = sigma * sqrt_t
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sq
        return S * _N.pdf(d1) * sqrt_t

    def _implied_vol(
        self,
        price: float,
        S: float,
        K: int,
        T: float,
        prev_guess: Optional[float],
    ) -> Optional[float]:
        if S <= 0 or T <= 0:
            return None
        intrinsic = max(0.0, S - K)
        price = max(price, intrinsic)

        sigma = self._clip(prev_guess if prev_guess is not None else 0.23, self.MIN_SIGMA, self.MAX_SIGMA)
        for _ in range(6):
            theo = self._bs_call(S, K, T, sigma)
            diff = theo - price
            if abs(diff) <= 1e-3:
                return sigma
            vega = self._bs_vega(S, K, T, sigma)
            if vega <= 1e-6:
                break
            sigma = self._clip(sigma - diff / vega, self.MIN_SIGMA, self.MAX_SIGMA)

        lo = self.MIN_SIGMA
        hi = self.MAX_SIGMA
        if self._bs_call(S, K, T, lo) > price:
            return lo
        if self._bs_call(S, K, T, hi) < price:
            return hi
        for _ in range(14):
            mid = 0.5 * (lo + hi)
            theo = self._bs_call(S, K, T, mid)
            if theo > price:
                hi = mid
            else:
                lo = mid
        return 0.5 * (lo + hi)

    def _update_iv_emas(
        self,
        saved: Dict,
        books: Dict[str, dict],
        spot_mid: float,
        T: float,
    ) -> Dict[str, float]:
        iv_ema = dict(saved.get("iv_ema", {}))
        alpha = self.IV_EMA_ALPHA

        for name in self.FIT_STRIKES:
            book = books.get(name)
            if book is None:
                continue
            K = self.VOUCHER_STRIKES[name]
            prev = iv_ema.get(name)
            iv = self._implied_vol(book["touch_mid"], spot_mid, K, T, prev)
            if iv is None or not math.isfinite(iv):
                continue
            if prev is None:
                iv_ema[name] = iv
            else:
                iv_ema[name] = (1.0 - alpha) * float(prev) + alpha * iv

        saved["iv_ema"] = iv_ema
        return iv_ema

    def _solve_3x3(self, rows: List[List[float]]) -> Optional[Tuple[float, float, float]]:
        mat = [row[:] for row in rows]
        for i in range(3):
            pivot = max(range(i, 3), key=lambda r: abs(mat[r][i]))
            if abs(mat[pivot][i]) < 1e-12:
                return None
            if pivot != i:
                mat[i], mat[pivot] = mat[pivot], mat[i]
            scale = mat[i][i]
            for j in range(i, 4):
                mat[i][j] /= scale
            for r in range(3):
                if r == i:
                    continue
                factor = mat[r][i]
                for j in range(i, 4):
                    mat[r][j] -= factor * mat[i][j]
        return mat[0][3], mat[1][3], mat[2][3]

    def _fit_surface(
        self,
        iv_ema: Dict[str, float],
        spot_mid: float,
    ) -> Optional[Tuple[float, float, float]]:
        pts: List[Tuple[float, float]] = []
        for name in self.FIT_STRIKES:
            sigma = iv_ema.get(name)
            if sigma is None:
                continue
            K = self.VOUCHER_STRIKES[name]
            if spot_mid <= 0 or K <= 0:
                continue
            k = math.log(K / spot_mid)
            pts.append((k, float(sigma)))

        if len(pts) < 3:
            return None

        s0 = float(len(pts))
        s1 = sum(k for k, _ in pts)
        s2 = sum(k * k for k, _ in pts)
        s3 = sum(k * k * k for k, _ in pts)
        s4 = sum(k * k * k * k for k, _ in pts)
        t0 = sum(iv for _, iv in pts)
        t1 = sum(k * iv for k, iv in pts)
        t2 = sum(k * k * iv for k, iv in pts)

        return self._solve_3x3(
            [
                [s0, s1, s2, t0],
                [s1, s2, s3, t1],
                [s2, s3, s4, t2],
            ]
        )

    def _curve_sigma(self, coeffs: Tuple[float, float, float], S: float, K: int) -> float:
        a, b, c = coeffs
        k = math.log(K / S)
        sigma = a + b * k + c * k * k
        return self._clip(sigma, self.MIN_SIGMA, self.MAX_SIGMA)

    def _cap_size(self, pos: int, limit: int, side: str) -> int:
        cap = limit - pos if side == "buy" else limit + pos
        if cap <= 0:
            return 0
        ratio = 1.0 - min(0.8, abs(pos) / float(limit))
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.2, ratio - 0.25)
        target = int(round(self.MAX_POST_SIZE * ratio))
        return max(0, min(cap, target))

    def _quote_voucher(
        self,
        name: str,
        K: int,
        book: dict,
        pos: int,
        coeffs: Tuple[float, float, float],
        spot_mid: float,
        T: float,
    ) -> Tuple[List[Order], Optional[float], Optional[float], Optional[float]]:
        if book["spread"] < self.MIN_SPREAD_TO_QUOTE:
            return [], None, None, None

        sigma = self._curve_sigma(coeffs, spot_mid, K)
        fair = self._bs_call(spot_mid, K, T, sigma)
        delta = self._bs_delta(spot_mid, K, T, sigma)

        shift = pos / self.SKEW_DENOM
        center = fair - shift
        desired_bid = int(math.floor(center - self.MIN_EDGE))
        desired_ask = int(math.ceil(center + self.MIN_EDGE))

        inside_lo = book["bb"] + 1
        inside_hi = book["ba"] - 1
        if inside_lo > inside_hi:
            return [], fair, sigma, delta

        bid_price = self._clip(desired_bid, inside_lo, inside_hi)
        ask_price = self._clip(desired_ask, inside_lo, inside_hi)

        bid_size = self._cap_size(pos, self.LIMITS[name], "buy")
        ask_size = self._cap_size(pos, self.LIMITS[name], "sell")

        orders: List[Order] = []
        if bid_price < ask_price:
            if bid_size > 0:
                orders.append(Order(name, int(bid_price), bid_size))
            if ask_size > 0:
                orders.append(Order(name, int(ask_price), -ask_size))
        elif ask_price == bid_price:
            # If the spread is too tight for a proper two-sided inside quote,
            # keep only the inventory-reducing side.
            if pos > 0 and ask_size > 0:
                orders.append(Order(name, int(ask_price), -ask_size))
            elif pos < 0 and bid_size > 0:
                orders.append(Order(name, int(bid_price), bid_size))

        return orders, fair, sigma, delta

    def _hedge_vfe(
        self,
        state: TradingState,
        spot_book: dict,
        desired_spot_pos: int,
    ) -> List[Order]:
        name = self.DELTA_HEDGE_PRODUCT
        current = state.position.get(name, 0)
        target = int(self._clip(desired_spot_pos, -self.LIMITS[name], self.LIMITS[name]))
        remaining = target - current
        if remaining == 0:
            return []

        orders: List[Order] = []
        if remaining > 0:
            for ap, av in spot_book["sells"].items():
                qty = min(remaining, av)
                if qty <= 0:
                    break
                orders.append(Order(name, ap, qty))
                remaining -= qty
                if remaining <= 0:
                    break
        else:
            need = -remaining
            for bp, bv in spot_book["buys"].items():
                qty = min(need, bv)
                if qty <= 0:
                    break
                orders.append(Order(name, bp, -qty))
                need -= qty
                if need <= 0:
                    break
        return orders

    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        books: Dict[str, dict] = {}
        for name in (self.DELTA_HEDGE_PRODUCT,) + tuple(self.VOUCHER_STRIKES.keys()):
            od = state.order_depths.get(name)
            if od is None:
                continue
            book = self._book(od)
            if book is not None:
                books[name] = book

        spot_book = books.get(self.DELTA_HEDGE_PRODUCT)
        if spot_book is None:
            return result, 0, json.dumps(saved)

        T = self._tte_years(state.timestamp)
        if T <= 0:
            return result, 0, json.dumps(saved)

        spot_mid = spot_book["touch_mid"]
        iv_ema = self._update_iv_emas(saved, books, spot_mid, T)
        coeffs = self._fit_surface(iv_ema, spot_mid)
        if coeffs is None:
            return result, 0, json.dumps(saved)

        log_payload = {
            "ts": state.timestamp,
            "spot": round(spot_mid, 2),
            "curve": [round(x, 5) for x in coeffs],
        }

        voucher_delta = 0.0
        for name in self.QUOTE_STRIKES:
            book = books.get(name)
            if book is None:
                continue
            pos = state.position.get(name, 0)
            K = self.VOUCHER_STRIKES[name]
            orders, fair, sigma, delta = self._quote_voucher(
                name=name,
                K=K,
                book=book,
                pos=pos,
                coeffs=coeffs,
                spot_mid=spot_mid,
                T=T,
            )
            if orders:
                result[name] = orders
            if delta is not None:
                voucher_delta += pos * delta
            if fair is not None and sigma is not None:
                log_payload[name] = {
                    "fair": round(fair, 2),
                    "sigma": round(sigma, 4),
                    "pos": pos,
                    "spread": book["spread"],
                }

        spot_pos = state.position.get(self.DELTA_HEDGE_PRODUCT, 0)
        net_delta = spot_pos + voucher_delta
        desired_spot_pos = int(round(-voucher_delta))
        log_payload["net_delta"] = round(net_delta, 2)
        log_payload["target_spot"] = desired_spot_pos

        if abs(net_delta) > self.DELTA_THRESHOLD:
            hedge_orders = self._hedge_vfe(state, spot_book, desired_spot_pos)
            if hedge_orders:
                result[self.DELTA_HEDGE_PRODUCT] = hedge_orders

        if self.LOG:
            print(json.dumps(log_payload))

        return result, 0, json.dumps(saved)
