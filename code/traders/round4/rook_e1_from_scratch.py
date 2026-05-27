"""
Rook-E1 from-scratch R3/R4 strategy.

Design intent:
- Use only local, explainable product models: adaptive fair values, spread
  capture, and bounded inventory.
- Treat Round 4 Mark IDs as an execution/activity layer, not as a full
  replacement for the product model.
- Keep correlated VFE exposure bounded so the day-3 sticky regime cannot
  load every voucher and the underlying to max size at the open.

Mark classification used:
- Mark 67: informed VFE buyer. Long bias, short veto.
- Mark 49: mistimed passive VFE seller. Fade sells with long bias.
- Mark 55: aggressive VFE noise taker. Provide liquidity, do not chase.
- Mark 38: aggressive HYDROGEL/VEV_4000 noise taker. Provide liquidity.
- Mark 14 / Mark 01: passive makers. Respect their fills; do not chase.
"""

from __future__ import annotations

import json
import math
import os
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


N = NormalDist()
DAYS_PER_YEAR = 365.0


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
    POSITION_LIMITS = LIMITS

    STRIKES = {
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

    # Conservative deltas for exposure gating. They do not need to be exact:
    # the goal is to prevent all positive-delta sleeves from maxing together.
    DELTAS = {
        "VEV_4000": 1.00,
        "VEV_4500": 0.98,
        "VEV_5000": 0.90,
        "VEV_5100": 0.84,
        "VEV_5200": 0.70,
        "VEV_5300": 0.50,
        "VEV_5400": 0.24,
        "VEV_5500": 0.10,
        "VEV_6000": 0.01,
        "VEV_6500": 0.00,
    }

    def run(self, state: TradingState):
        saved = self._load_state(state.traderData)
        ts = int(getattr(state, "timestamp", 0) or 0)
        last_ts = int(saved.get("last_ts", ts))
        if ts < last_ts:
            saved = self._empty_state()
        saved["last_ts"] = ts

        books = {sym: self._book(depth) for sym, depth in state.order_depths.items()}
        self._update_mids(saved, books)
        self._decay_activity(saved, max(0, ts - last_ts))
        self._ingest_marks(saved, state)

        result: Dict[str, List[Order]] = {}

        vfe_book = books.get("VELVETFRUIT_EXTRACT")
        vfe_mid = vfe_book["mid"] if vfe_book else None
        vfe_ema = self._get(saved, "ema", "VELVETFRUIT_EXTRACT", vfe_mid or 0.0)
        vfe_shift = self._vfe_mark_shift(saved)

        for sym in state.order_depths:
            result[sym] = []

        if books.get("HYDROGEL_PACK"):
            result["HYDROGEL_PACK"] = self._orders_hydrogel(
                saved, state, books["HYDROGEL_PACK"], ts
            )

        if vfe_book:
            result["VELVETFRUIT_EXTRACT"] = self._orders_vfe(
                saved, state, vfe_book, ts, vfe_shift
            )

        net_delta = self._portfolio_delta(state.position)
        for sym in self.STRIKES:
            book = books.get(sym)
            if not book:
                continue
            if sym in ("VEV_6000", "VEV_6500"):
                result[sym] = self._orders_lottery(state, book, sym, ts, net_delta)
            elif vfe_mid is not None:
                result[sym] = self._orders_voucher(
                    saved,
                    state,
                    book,
                    sym,
                    vfe_mid,
                    vfe_ema,
                    vfe_shift,
                    ts,
                    net_delta,
                )

        return result, 0, json.dumps(saved, separators=(",", ":"))

    # ---------------- state and book helpers ----------------

    @staticmethod
    def _empty_state() -> Dict[str, Any]:
        return {
            "last_ts": 0,
            "ema": {},
            "fast": {},
            "var": {},
            "prev": {},
            "dm": {},
            "basis": {},
            "basis_var": {},
            "sigma": 0.23,
            "open": {},
            "activity": {},
        }

    def _load_state(self, raw: str) -> Dict[str, Any]:
        if not raw:
            return self._empty_state()
        try:
            loaded = json.loads(raw)
        except Exception:
            return self._empty_state()
        base = self._empty_state()
        for key, value in loaded.items():
            if key in base:
                base[key] = value
        return base

    @staticmethod
    def _book(depth: OrderDepth) -> Optional[Dict[str, Any]]:
        if not depth.buy_orders or not depth.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in depth.buy_orders.items() if int(v) != 0}
        sells = {int(p): abs(int(v)) for p, v in depth.sell_orders.items() if int(v) != 0}
        if not buys or not sells:
            return None
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
            "mid": 0.5 * (bb + ba),
        }

    @staticmethod
    def _get(saved: Dict[str, Any], bucket: str, key: str, default: float) -> float:
        return float(saved.get(bucket, {}).get(key, default))

    @staticmethod
    def _set(saved: Dict[str, Any], bucket: str, key: str, value: float) -> None:
        saved.setdefault(bucket, {})[key] = float(value)

    def _ewma(self, saved: Dict[str, Any], bucket: str, key: str, value: float, alpha: float) -> float:
        prior = self._get(saved, bucket, key, value)
        updated = prior + alpha * (value - prior)
        self._set(saved, bucket, key, updated)
        return updated

    def _update_mids(self, saved: Dict[str, Any], books: Dict[str, Optional[Dict[str, Any]]]) -> None:
        for sym, book in books.items():
            if not book:
                continue
            mid = float(book["mid"])
            saved.setdefault("open", {}).setdefault(sym, mid)
            prev = saved.setdefault("prev", {}).get(sym)
            if prev is not None:
                diff = mid - float(prev)
                saved.setdefault("dm", {})[sym] = diff
                old_var = self._get(saved, "var", sym, 4.0)
                self._set(saved, "var", sym, 0.985 * old_var + 0.015 * diff * diff)
            saved["prev"][sym] = mid

            if sym == "HYDROGEL_PACK":
                self._ewma(saved, "ema", sym, mid, 0.0035)
                self._ewma(saved, "fast", sym, mid, 0.025)
            elif sym == "VELVETFRUIT_EXTRACT":
                self._ewma(saved, "ema", sym, mid, 0.0012)
                self._ewma(saved, "fast", sym, mid, 0.015)
            else:
                self._ewma(saved, "ema", sym, mid, 0.002)

    # ---------------- activity / Mark layer ----------------

    def _decay_activity(self, saved: Dict[str, Any], dt: int) -> None:
        if dt <= 0:
            return
        decay = math.exp(-dt / 2500.0)
        activity = saved.setdefault("activity", {})
        for key in list(activity.keys()):
            activity[key] = float(activity[key]) * decay
            if abs(float(activity[key])) < 0.01:
                activity.pop(key, None)

    def _bump_activity(self, saved: Dict[str, Any], key: str, amount: float) -> None:
        activity = saved.setdefault("activity", {})
        activity[key] = max(-80.0, min(80.0, float(activity.get(key, 0.0)) + amount))

    def _ingest_marks(self, saved: Dict[str, Any], state: TradingState) -> None:
        for sym, trades in state.market_trades.items():
            for trade in trades:
                qty = int(getattr(trade, "quantity", 0) or 0)
                if qty <= 0:
                    continue
                buyer = getattr(trade, "buyer", "") or ""
                seller = getattr(trade, "seller", "") or ""

                if sym == "VELVETFRUIT_EXTRACT":
                    if buyer == "Mark 67":
                        self._bump_activity(saved, "vfe_informed", 2.2 * qty)
                    if seller == "Mark 67":
                        self._bump_activity(saved, "vfe_informed", -2.2 * qty)
                    if seller == "Mark 49":
                        self._bump_activity(saved, "vfe_informed", 1.8 * qty)
                    if buyer == "Mark 49":
                        self._bump_activity(saved, "vfe_informed", -1.8 * qty)

                    # Mark 55 pays spread and is best handled as liquidity demand.
                    if buyer == "Mark 55":
                        self._bump_activity(saved, "vfe_noise", -0.8 * qty)
                    if seller == "Mark 55":
                        self._bump_activity(saved, "vfe_noise", 0.8 * qty)
                    if buyer == "Mark 22":
                        self._bump_activity(saved, "vfe_noise", -0.3 * qty)
                    if seller == "Mark 22":
                        self._bump_activity(saved, "vfe_noise", 0.3 * qty)

                if sym in ("HYDROGEL_PACK", "VEV_4000"):
                    if buyer == "Mark 38":
                        self._bump_activity(saved, sym + "_noise", -1.3 * qty)
                    if seller == "Mark 38":
                        self._bump_activity(saved, sym + "_noise", 1.3 * qty)

    def _vfe_mark_shift(self, saved: Dict[str, Any]) -> float:
        activity = saved.get("activity", {})
        informed = float(activity.get("vfe_informed", 0.0))
        noise = float(activity.get("vfe_noise", 0.0))
        return max(-7.0, min(7.0, 0.13 * informed + 0.05 * noise))

    # ---------------- pricing helpers ----------------

    @staticmethod
    def _round_num() -> int:
        try:
            return int(os.environ.get("PROSPERITY3BT_ROUND", "4"))
        except Exception:
            return 4

    def _tte_years(self, ts: int) -> float:
        # R4 live page states VEV_5000 has 4 days left. R3 local replay is
        # older data; 5 days is a practical local default for the same file.
        base_days = 4.0 if self._round_num() >= 4 else 5.0
        return max(0.25, base_days - ts / 1_000_000.0) / DAYS_PER_YEAR

    @staticmethod
    def _bs_call(S: float, K: float, T: float, sigma: float) -> Tuple[float, float, float]:
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            delta = 1.0 if S > K else 0.0
            return max(0.0, S - K), delta, 0.0
        vol = sigma * math.sqrt(T)
        if vol <= 0:
            delta = 1.0 if S > K else 0.0
            return max(0.0, S - K), delta, 0.0
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / vol
        d2 = d1 - vol
        call = S * N.cdf(d1) - K * N.cdf(d2)
        delta = N.cdf(d1)
        vega = S * N.pdf(d1) * math.sqrt(T)
        return call, delta, vega

    def _implied_vol(self, S: float, K: float, T: float, price: float) -> Optional[float]:
        intrinsic = max(0.0, S - K)
        if price <= intrinsic + 0.05 or price <= 0.1:
            return None
        lo, hi = 0.01, 1.50
        for _ in range(24):
            mid = 0.5 * (lo + hi)
            theo, _, _ = self._bs_call(S, K, T, mid)
            if theo < price:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    # ---------------- risk helpers ----------------

    def _portfolio_delta(self, position: Dict[str, int]) -> float:
        total = float(position.get("VELVETFRUIT_EXTRACT", 0))
        for sym, delta in self.DELTAS.items():
            total += float(position.get(sym, 0)) * delta
        return total

    @staticmethod
    def _time_cap(ts: int, early: int, mid: int, late: int) -> int:
        if ts < 100_000:
            return early
        if ts < 600_000:
            return mid
        return late

    def _room(self, state: TradingState, sym: str, cap: int) -> Tuple[int, int]:
        pos = int(state.position.get(sym, 0))
        hard = int(self.LIMITS[sym])
        soft = min(hard, int(cap))
        return max(0, soft - pos), max(0, soft + pos)

    # ---------------- order templates ----------------

    def _quote_mean_reversion(
        self,
        sym: str,
        state: TradingState,
        book: Dict[str, Any],
        fair: float,
        cap: int,
        take_edge: float,
        post_edge: float,
        base_size: int,
        min_spread: int,
        inv_skew: float,
        buy_mult: float = 1.0,
        sell_mult: float = 1.0,
        allow_buy: bool = True,
        allow_sell: bool = True,
    ) -> List[Order]:
        pos = int(state.position.get(sym, 0))
        buy_room, sell_room = self._room(state, sym, cap)
        orders: List[Order] = []
        working = pos

        skewed = fair - inv_skew * working
        if allow_buy and buy_room > 0:
            for ap, av in book["sells"].items():
                if ap > skewed - take_edge:
                    break
                qty = min(av, buy_room, max(1, int(base_size * buy_mult)))
                if qty <= 0:
                    break
                orders.append(Order(sym, int(ap), int(qty)))
                working += qty
                buy_room -= qty
                skewed = fair - inv_skew * working

        if allow_sell and sell_room > 0:
            for bp, bv in book["buys"].items():
                if bp < skewed + take_edge:
                    break
                qty = min(bv, sell_room, max(1, int(base_size * sell_mult)))
                if qty <= 0:
                    break
                orders.append(Order(sym, int(bp), -int(qty)))
                working -= qty
                sell_room -= qty
                skewed = fair - inv_skew * working

        if book["spread"] < min_spread:
            return orders

        buy_room = max(0, min(self.LIMITS[sym], cap) - working)
        sell_room = max(0, min(self.LIMITS[sym], cap) + working)
        skewed = fair - inv_skew * working

        bid_price = min(book["bb"] + 1, math.floor(skewed - post_edge))
        ask_price = max(book["ba"] - 1, math.ceil(skewed + post_edge))
        if bid_price >= ask_price:
            bid_price = min(book["bb"] + 1, math.floor(skewed - 0.5))
            ask_price = max(book["ba"] - 1, bid_price + 1)

        taper_buy = 1.0 - max(0.0, working / max(1.0, float(cap))) * 0.65
        taper_sell = 1.0 + min(0.0, working / max(1.0, float(cap))) * 0.65
        bid_qty = max(1, int(base_size * buy_mult * max(0.25, taper_buy)))
        ask_qty = max(1, int(base_size * sell_mult * max(0.25, taper_sell)))

        if allow_buy and buy_room > 0 and bid_price >= 1 and bid_price < book["ba"]:
            orders.append(Order(sym, int(bid_price), int(min(buy_room, bid_qty))))
        if allow_sell and sell_room > 0 and ask_price > book["bb"]:
            orders.append(Order(sym, int(ask_price), -int(min(sell_room, ask_qty))))
        return orders

    # ---------------- product sleeves ----------------

    def _orders_hydrogel(
        self, saved: Dict[str, Any], state: TradingState, book: Dict[str, Any], ts: int
    ) -> List[Order]:
        sym = "HYDROGEL_PACK"
        var = max(1.5, self._get(saved, "var", sym, 6.0))
        mark_noise = float(saved.get("activity", {}).get(sym + "_noise", 0.0))
        std = math.sqrt(var)
        pos = int(state.position.get(sym, 0))

        # HYDROGEL is stationary enough that a hard bounded anchor dominates
        # the adaptive EMA. The bound prevents chasing a transient high/low
        # print while still letting fair move inside the normal daily range.
        anchor = 9983.0
        clip_up = 33.0 + 0.50 * std
        if pos > 165:
            clip_dn = 33.0 + 16.0 * std
        elif pos > 120:
            clip_dn = 33.0 + 12.0 * std
        elif pos > 0:
            clip_dn = 33.0 + 2.7 * std
        else:
            clip_dn = 33.0 + 0.9 * std

        fair_input = book["mid"]
        if book["spread"] < 16:
            total = book["bv"] + book["av"]
            if total > 0:
                fair_input = (book["ba"] * book["bv"] + book["bb"] * book["av"]) / total
        fair = anchor + max(-clip_dn, min(clip_up, fair_input - anchor))
        fair -= 0.20 * float(saved.get("dm", {}).get(sym, 0.0))
        fair += max(-3.0, min(3.0, 0.05 * mark_noise))

        open_mid = self._get(saved, "open", sym, book["mid"])
        if open_mid > 10005.0:
            cap = self._time_cap(ts, 130, 200, 200)
            size = max(14, min(18, int(20 - 0.5 * std)))
        else:
            cap = self._time_cap(ts, 95, 155, 200)
            size = max(12, min(18, int(19 - 0.7 * std)))
        return self._quote_mean_reversion(
            sym=sym,
            state=state,
            book=book,
            fair=fair,
            cap=cap,
            take_edge=0.3,
            post_edge=3.5,
            base_size=size,
            min_spread=8,
            inv_skew=0.014 if pos <= 0 else -0.015,
            buy_mult=1.0 if mark_noise >= -8 else 0.7,
            sell_mult=1.0 if mark_noise <= 8 else 0.7,
        )

    def _orders_vfe(
        self,
        saved: Dict[str, Any],
        state: TradingState,
        book: Dict[str, Any],
        ts: int,
        mark_shift: float,
    ) -> List[Order]:
        sym = "VELVETFRUIT_EXTRACT"
        ema = self._get(saved, "ema", sym, book["mid"])
        fast = self._get(saved, "fast", sym, book["mid"])
        var = max(0.8, self._get(saved, "var", sym, 2.0))
        drift = fast - ema
        fair = ema + 0.10 * drift + mark_shift

        cap = self._time_cap(ts, 55, 95, 145)
        net_delta = self._portfolio_delta(state.position)
        delta_cap = self._time_cap(ts, 110, 170, 230)

        allow_buy = net_delta < delta_cap
        allow_sell = net_delta > -delta_cap

        if mark_shift > 1.2:
            buy_mult, sell_mult = 1.35, 0.35
        elif mark_shift < -1.2:
            buy_mult, sell_mult = 0.35, 1.35
        else:
            buy_mult, sell_mult = 1.0, 1.0

        # If the book has already loaded us with too much portfolio delta, use
        # VFE as the hedge rather than adding more vouchers.
        orders: List[Order] = []
        pos = int(state.position.get(sym, 0))
        buy_room, sell_room = self._room(state, sym, cap)
        if net_delta > delta_cap + 35 and sell_room > 0:
            qty = min(sell_room, int(min(12, net_delta - delta_cap)))
            if qty > 0:
                orders.append(Order(sym, int(book["bb"]), -qty))
                sell_room -= qty
        elif net_delta < -delta_cap - 35 and buy_room > 0:
            qty = min(buy_room, int(min(12, -delta_cap - net_delta)))
            if qty > 0:
                orders.append(Order(sym, int(book["ba"]), qty))
                buy_room -= qty

        if buy_room <= 0:
            allow_buy = False
        if sell_room <= 0:
            allow_sell = False

        size = max(5, min(12, int(12 - math.sqrt(var))))
        orders.extend(
            self._quote_mean_reversion(
                sym=sym,
                state=state,
                book=book,
                fair=fair,
                cap=cap,
                take_edge=3.2,
                post_edge=1.0,
                base_size=size,
                min_spread=4,
                inv_skew=0.040,
                buy_mult=buy_mult,
                sell_mult=sell_mult,
                allow_buy=allow_buy,
                allow_sell=allow_sell,
            )
        )
        return orders

    def _orders_voucher(
        self,
        saved: Dict[str, Any],
        state: TradingState,
        book: Dict[str, Any],
        sym: str,
        vfe_mid: float,
        vfe_ema: float,
        mark_shift: float,
        ts: int,
        net_delta: float,
    ) -> List[Order]:
        K = float(self.STRIKES[sym])
        if K >= 5000:
            return []
        T = self._tte_years(ts)
        mid = float(book["mid"])

        # Update a global sigma from liquid non-lottery strikes.
        if 5000 <= K <= 5500 and mid > 1.0:
            iv = self._implied_vol(vfe_mid, K, T, mid)
            if iv is not None and 0.05 <= iv <= 1.25:
                old = float(saved.get("sigma", 0.23))
                saved["sigma"] = max(0.08, min(0.70, old + 0.006 * (iv - old)))

        sigma = float(saved.get("sigma", 0.23))
        theo, bs_delta, _vega = self._bs_call(vfe_mid, K, T, sigma)

        if K <= 4500:
            intrinsic = max(0.0, vfe_mid - K)
            raw_basis = mid - intrinsic
            basis = self._ewma(saved, "basis", sym, raw_basis, 0.004)
            old_var = self._get(saved, "basis_var", sym, 9.0)
            self._set(saved, "basis_var", sym, 0.99 * old_var + 0.01 * (raw_basis - basis) ** 2)
            delta = self.DELTAS[sym]
            fair = intrinsic + basis + delta * mark_shift
            take_edge = 2.0
            post_edge = 3.0
            min_spread = 8 if sym == "VEV_4000" else 5
            base_size = 14 if sym == "VEV_4000" else 12
            cap = self._time_cap(ts, 65, 115, 170)
        else:
            raw_resid = mid - theo
            resid = self._ewma(saved, "basis", sym, raw_resid, 0.003)
            old_var = self._get(saved, "basis_var", sym, 4.0)
            self._set(saved, "basis_var", sym, 0.99 * old_var + 0.01 * (raw_resid - resid) ** 2)
            delta = max(0.02, min(0.98, bs_delta))
            fair = theo + resid + delta * mark_shift + delta * 0.05 * (vfe_mid - vfe_ema)
            take_edge = 1.4 if K <= 5300 else 0.9
            post_edge = 1.0 if K <= 5300 else 0.4
            min_spread = 3 if K <= 5300 else 1
            base_size = 10 if K <= 5300 else 8
            cap = self._time_cap(ts, 55, 95, 135)

        delta_cap = self._time_cap(ts, 110, 170, 230)
        allow_buy = net_delta < delta_cap
        allow_sell = net_delta > -delta_cap
        if mark_shift > 1.2:
            buy_mult, sell_mult = 1.25, 0.55
        elif mark_shift < -1.2:
            buy_mult, sell_mult = 0.55, 1.25
        else:
            buy_mult, sell_mult = 1.0, 1.0

        # The vouchers are the source of correlated drawdowns, so their
        # inventory skew is deliberately stronger than single-name products.
        inv_skew = 0.020 + 0.030 * abs(delta)
        return self._quote_mean_reversion(
            sym=sym,
            state=state,
            book=book,
            fair=fair,
            cap=cap,
            take_edge=take_edge,
            post_edge=post_edge,
            base_size=base_size,
            min_spread=min_spread,
            inv_skew=inv_skew,
            buy_mult=buy_mult,
            sell_mult=sell_mult,
            allow_buy=allow_buy,
            allow_sell=allow_sell,
        )

    def _orders_lottery(
        self,
        state: TradingState,
        book: Dict[str, Any],
        sym: str,
        ts: int,
        net_delta: float,
    ) -> List[Order]:
        pos = int(state.position.get(sym, 0))
        cap = self._time_cap(ts, 60, 120, 180)
        buy_room, sell_room = self._room(state, sym, cap)
        orders: List[Order] = []

        # Only buy free optionality at zero. Sell one-tick offers only to trim
        # existing inventory, not to build naked short lottery exposure.
        if buy_room > 0 and 0 in book["sells"] and net_delta < self._time_cap(ts, 110, 170, 230):
            orders.append(Order(sym, 0, min(buy_room, 25, book["sells"][0])))
        if pos > 0 and sell_room > 0 and book["spread"] >= 1:
            orders.append(Order(sym, 1, -min(sell_room, pos, 15)))
        elif buy_room > 0 and book["bb"] <= 0:
            orders.append(Order(sym, 0, min(buy_room, 15)))
        return orders
