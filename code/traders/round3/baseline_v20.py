"""
Round 3 baseline v20 — continue from bundle 395880.

Base family:
- HYDROGEL from the `395880.py` / h_only_v14 line
- Deep-ITM synth MM on VEV_4000 / VEV_4500
- Timo-style IV-residual MR on VEV_5000..5300
- ATM residual-EMA MM on VEV_5400 / VEV_5500
- Lottery bids on VEV_6000 / VEV_6500

Only the HYDROGEL sleeve is changed vs 395880:
- keep the stronger h_only_v14 tuning (anchor 9983, skew 0.014)
- add drift gating / cap flattener from the v13/v17 safety line
- add the VFE crash-state overlay from v18

This keeps the aggressive voucher family from 395880 while improving
the one sleeve that still lacked the hidden-day robustness work.
"""
from typing import Dict, List, Optional, Tuple
from statistics import NormalDist
import json
import math

from datamodel import Order, OrderDepth, TradingState


_N = NormalDist()
DAYS_PER_YEAR = 365
TTE_DAYS_LIVE = 5.0

THR_OPEN = 0.5
THR_CLOSE = 0.0
LOW_VEGA_THR_ADJ = 0.5
THEO_NORM_WINDOW = 20
IV_SCALPING_THR = 0.7
IV_SCALPING_WINDOW = 100
OPT_MR_WINDOW = 30
OPT_MR_THR = 5

SCALP_STRIKES: Dict[str, int] = {}
MR_STRIKES = {
    "VEV_5000": 5000,
    "VEV_5100": 5100,
    "VEV_5200": 5200,
    "VEV_5300": 5300,
}


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

    SYNTH_STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500}
    ATM_STRIKES = {"VEV_5400": 5400, "VEV_5500": 5500}
    LOTTERY_STRIKES = {"VEV_6000": 6000, "VEV_6500": 6500}

    # HYDROGEL base from h_only_v14 / 395880.
    H_ANCHOR = 9983.0
    H_CLIP = 33.0
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 0.0
    H_PENNY_EDGE = 2.0
    H_INV_SKEW = 0.014
    H_MAX_POST_SIZE = 18
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8
    AR1_BETA = 0.18
    TYPICAL_SPREAD = 16
    CLIP_VOL_K = 0.3
    DMID_HISTORY = 20

    # HYDROGEL safety overlays from v13/v17/v18.
    H_SHOCK_MOVE = 15.0
    H_INV_SKEW_DRIFT = 0.042
    H_DRIFT_BLEND = 0.6
    H_DRIFT_THRESHOLD = 50.0
    H_DRIFT_RISK = 2000.0
    H_CAP_NEAR = 1.0
    H_CAP_DRIFT = 35.0
    H_CAP_FLATTEN_QTY = 30
    H_CRASH_TRIGGER = 18.0
    H_CRASH_MIN_SPREAD = 14
    H_VFE_MOM_LOOKBACK = 20
    H_VFE_DOWN_THRESH = -3.5
    H_VFE_UP_THRESH = 1.0
    H_VFE_GOOD_FAIR_SHIFT = 0.75
    H_VFE_BAD_FAIR_SHIFT = -1.25
    H_VFE_GOOD_BID_MULT = 2.0
    H_VFE_GOOD_ASK_MULT = 0.25
    H_VFE_BAD_BID_MULT = 0.25
    H_VFE_BAD_ASK_MULT = 1.25

    # Underlying MR from 395880.
    ENABLE_UNDERLYING_MR = True
    UNDER_MR_THR = 5

    # ATM smile-EMA MM from 395880.
    ATM_RESIDUAL_ALPHA = 1.0 / 5000
    ATM_MAX_POST_SIZE = 20
    ATM_TAKE_EDGE = 0.0
    ATM_PENNY_EDGE = 0.0
    ATM_INV_SKEW = 0.0
    ATM_WIDE_SPREAD = 1
    ATM_PER_STRIKE_LIMIT_RATIO = 0.85

    # Lottery.
    LOTTERY_BID_PRICE = 0
    LOTTERY_BID_SIZE = 30
    LOTTERY_ASK_PRICE = 1
    LOTTERY_ASK_SIZE = 30

    # Deep-ITM synth sleeve from 395880.
    SIGMA = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.005
    VS_MAX_POST_SIZE = 40
    VS_WIDE_SPREAD = 3

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

    def _walls(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None, None, None
        bid_wall = min(od.buy_orders.keys())
        ask_wall = max(od.sell_orders.keys())
        return bid_wall, 0.5 * (bid_wall + ask_wall), ask_wall

    def _cap_size(self, max_size: int, pos: int, side: str, cap: int, limit: int) -> int:
        if cap <= 0:
            return 0
        ratio = 1.0 - min(0.7, abs(pos) / limit)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    @staticmethod
    def _opt_bs(S: float, K: float, T: float, sigma: float):
        if T <= 0 or sigma <= 0:
            return max(0.0, S - K), 1.0 if S > K else 0.0, 0.0
        sq = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sq
        d2 = d1 - sq
        call = S * _N.cdf(d1) - K * _N.cdf(d2)
        delta = _N.cdf(d1)
        vega = S * _N.pdf(d1) * math.sqrt(T)
        return call, delta, vega

    @staticmethod
    def _tte_years(ts: int) -> float:
        return max(0.0, TTE_DAYS_LIVE - ts / 1e6) / DAYS_PER_YEAR

    @staticmethod
    def _ema(saved: Dict, key: str, window: int, value: float) -> float:
        old = saved.get(key, 0.0)
        alpha = 2.0 / (window + 1)
        new = alpha * value + (1 - alpha) * old
        saved[key] = new
        return new

    def _fair_input_h(self, book) -> float:
        if book["spread"] < self.TYPICAL_SPREAD:
            total = book["bv"] + book["av"]
            if total > 0:
                return (book["ba"] * book["bv"] + book["bb"] * book["av"]) / total
        return book["touch_mid"]

    def _hydro_clip(self, dmid_hist: List[float]) -> float:
        if self.CLIP_VOL_K > 0 and len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mean_d = sum(dmid_hist) / n
            std_d = math.sqrt(sum((d - mean_d) ** 2 for d in dmid_hist) / n)
            return self.H_CLIP + self.CLIP_VOL_K * std_d
        return self.H_CLIP

    def _trade_hydrogel(
        self,
        od: OrderDepth,
        pos: int,
        prev_mid: Optional[float],
        last_dmid: Optional[float],
        dmid_hist: List[float],
        vfe_mom20: Optional[float],
    ) -> Tuple[List[Order], Optional[float]]:
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], prev_mid

        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        touch_mid = book["touch_mid"]
        fair_input = self._fair_input_h(book)
        clip = self._hydro_clip(dmid_hist)

        shock = prev_mid is not None and abs(touch_mid - prev_mid) > self.H_SHOCK_MOVE
        drift_raw = touch_mid - self.H_ANCHOR
        risk_aligned = pos * (-drift_raw)
        drift_regime = (
            not shock
            and abs(drift_raw) > self.H_DRIFT_THRESHOLD
            and risk_aligned > self.H_DRIFT_RISK
        )

        if shock:
            fair = fair_input
            inv_skew = self.H_INV_SKEW
        elif drift_regime:
            clipped = max(-clip, min(clip, drift_raw))
            fair = self.H_ANCHOR + clipped + self.H_DRIFT_BLEND * (drift_raw - clipped)
            inv_skew = self.H_INV_SKEW_DRIFT
        else:
            fair_adj = max(-clip, min(clip, fair_input - self.H_ANCHOR))
            fair = self.H_ANCHOR + fair_adj
            inv_skew = self.H_INV_SKEW

        if last_dmid is not None:
            fair -= self.AR1_BETA * last_dmid

        bid_size_mult = 1.0
        ask_size_mult = 1.0
        in_crash = (
            not shock
            and touch_mid <= self.H_ANCHOR - self.H_CRASH_TRIGGER
            and spread >= self.H_CRASH_MIN_SPREAD
        )
        if in_crash and vfe_mom20 is not None:
            if vfe_mom20 <= self.H_VFE_DOWN_THRESH:
                fair += self.H_VFE_GOOD_FAIR_SHIFT
                bid_size_mult = self.H_VFE_GOOD_BID_MULT
                ask_size_mult = self.H_VFE_GOOD_ASK_MULT
            elif vfe_mom20 >= self.H_VFE_UP_THRESH:
                fair += self.H_VFE_BAD_FAIR_SHIFT
                bid_size_mult = self.H_VFE_BAD_BID_MULT
                ask_size_mult = self.H_VFE_BAD_ASK_MULT

        working = pos
        orders: List[Order] = []

        drift_dir = 0
        if drift_regime:
            drift_dir = 1 if drift_raw > 0 else -1

        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - inv_skew * working
            block_aggressive_buy = drift_dir == -1
            if (not block_aggressive_buy) and ap <= skew - self.H_TAKE_EDGE:
                qty = min(av, cap)
                if qty > 0:
                    orders.append(Order(prod, ap, qty))
                    working += qty
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                qty = min(av, cap, abs(working))
                if qty > 0:
                    orders.append(Order(prod, ap, qty))
                    working += qty

        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair - inv_skew * working
            block_aggressive_sell = drift_dir == 1
            if (not block_aggressive_sell) and bp >= skew + self.H_TAKE_EDGE:
                qty = min(bv, cap)
                if qty > 0:
                    orders.append(Order(prod, bp, -qty))
                    working -= qty
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                qty = min(bv, cap, working)
                if qty > 0:
                    orders.append(Order(prod, bp, -qty))
                    working -= qty

        cap_long_bad = working >= self.H_CAP_NEAR * limit and drift_raw <= -self.H_CAP_DRIFT
        cap_short_bad = working <= -self.H_CAP_NEAR * limit and drift_raw >= self.H_CAP_DRIFT
        if cap_long_bad and not shock:
            qty_left = self.H_CAP_FLATTEN_QTY
            for bp, bv in book["buys"].items():
                if qty_left <= 0 or working <= 0:
                    break
                qty = min(bv, qty_left, working)
                if qty > 0:
                    orders.append(Order(prod, bp, -qty))
                    working -= qty
                    qty_left -= qty
        elif cap_short_bad and not shock:
            qty_left = self.H_CAP_FLATTEN_QTY
            for ap, av in book["sells"].items():
                if qty_left <= 0 or working >= 0:
                    break
                qty = min(av, qty_left, abs(working))
                if qty > 0:
                    orders.append(Order(prod, ap, qty))
                    working += qty
                    qty_left -= qty

        if shock:
            return orders, touch_mid

        skew = fair - inv_skew * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.H_MAX_POST_SIZE, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(self.H_MAX_POST_SIZE, working, "sell", sell_cap, limit)
        bid_size = min(buy_cap, int(round(bid_size * bid_size_mult)))
        ask_size = min(sell_cap, int(round(ask_size * ask_size_mult)))

        if drift_dir == -1:
            bid_size = 0
        elif drift_dir == 1:
            ask_size = 0

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

    def _trade_synth_voucher(
        self,
        name: str,
        K: int,
        od: OrderDepth,
        pos: int,
        S: float,
        T: float,
    ) -> List[Order]:
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        fair, _, _ = self._opt_bs(S, K, T, self.SIGMA)
        working = pos
        orders: List[Order] = []

        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - self.VS_INV_SKEW * working
            if ap <= skew - self.VS_TAKE_EDGE:
                qty = min(av, cap)
                if qty > 0:
                    orders.append(Order(name, ap, qty))
                    working += qty
            elif working < 0 and ap <= skew:
                qty = min(av, cap, abs(working))
                if qty > 0:
                    orders.append(Order(name, ap, qty))
                    working += qty

        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair - self.VS_INV_SKEW * working
            if bp >= skew + self.VS_TAKE_EDGE:
                qty = min(bv, cap)
                if qty > 0:
                    orders.append(Order(name, bp, -qty))
                    working -= qty
            elif working > 0 and bp >= skew:
                qty = min(bv, cap, working)
                if qty > 0:
                    orders.append(Order(name, bp, -qty))
                    working -= qty

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

    def _trade_atm(
        self,
        name: str,
        K: int,
        od: OrderDepth,
        pos: int,
        S: float,
        T: float,
        residual: Optional[float],
    ) -> Tuple[List[Order], float]:
        limit = self.LIMITS[name]
        per_strike_limit = int(limit * self.ATM_PER_STRIKE_LIMIT_RATIO)
        book = self._book(od)
        if not book:
            return [], residual if residual is not None else 0.0
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        touch_mid = book["touch_mid"]

        bs_theo, _, _ = self._opt_bs(S, K, T, self.SIGMA)
        instant_residual = touch_mid - bs_theo
        if residual is None:
            new_residual = instant_residual
        else:
            alpha = self.ATM_RESIDUAL_ALPHA
            new_residual = (1 - alpha) * residual + alpha * instant_residual
        fair = bs_theo + new_residual
        working = pos
        orders: List[Order] = []

        for ap, av in book["sells"].items():
            cap = per_strike_limit - working
            if cap <= 0:
                break
            skew = fair - self.ATM_INV_SKEW * working
            if ap <= skew - self.ATM_TAKE_EDGE:
                qty = min(av, cap)
                if qty > 0:
                    orders.append(Order(name, ap, qty))
                    working += qty
            elif working < 0 and ap <= skew:
                qty = min(av, cap, abs(working))
                if qty > 0:
                    orders.append(Order(name, ap, qty))
                    working += qty

        for bp, bv in book["buys"].items():
            cap = per_strike_limit + working
            if cap <= 0:
                break
            skew = fair - self.ATM_INV_SKEW * working
            if bp >= skew + self.ATM_TAKE_EDGE:
                qty = min(bv, cap)
                if qty > 0:
                    orders.append(Order(name, bp, -qty))
                    working -= qty
            elif working > 0 and bp >= skew:
                qty = min(bv, cap, working)
                if qty > 0:
                    orders.append(Order(name, bp, -qty))
                    working -= qty

        if spread >= self.ATM_WIDE_SPREAD:
            skew = fair - self.ATM_INV_SKEW * working
            buy_cap = max(0, per_strike_limit - working)
            sell_cap = max(0, per_strike_limit + working)
            bid_size = self._cap_size(self.ATM_MAX_POST_SIZE, working, "buy", buy_cap, limit)
            ask_size = self._cap_size(self.ATM_MAX_POST_SIZE, working, "sell", sell_cap, limit)
            bid_price = min(bb, math.floor(skew - self.ATM_PENNY_EDGE))
            ask_price = max(ba, math.ceil(skew + self.ATM_PENNY_EDGE))
            bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
            ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)
            if bid_price < ask_price:
                if bid_size > 0:
                    orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0:
                    orders.append(Order(name, ask_price, -ask_size))

        return orders, new_residual

    def _trade_lottery(self, name: str, od: OrderDepth, pos: int) -> List[Order]:
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return []
        orders: List[Order] = []
        room_buy = limit - pos
        if room_buy > 0:
            orders.append(Order(name, self.LOTTERY_BID_PRICE, min(self.LOTTERY_BID_SIZE, room_buy)))
        if pos > 0:
            orders.append(Order(name, self.LOTTERY_ASK_PRICE, -min(self.LOTTERY_ASK_SIZE, pos)))
        return orders

    def _trade_iv_residual(self, state: TradingState, pos: Dict[str, int], saved: Dict):
        out: Dict[str, List[Order]] = {}
        ods = state.order_depths

        u_od = ods.get("VELVETFRUIT_EXTRACT")
        if u_od is None:
            return out
        u_bw, u_wm, u_aw = self._walls(u_od)
        if u_wm is None:
            return out
        S = u_wm
        T = self._tte_years(state.timestamp)
        if T <= 0:
            return out

        ema_o_val = self._ema(saved, "_opt_ema_o", OPT_MR_WINDOW, u_wm)
        ema_o_dev = u_wm - ema_o_val

        all_strikes = {**SCALP_STRIKES, **MR_STRIKES}
        cur_diff: Dict[str, float] = {}
        mean_diff: Dict[str, float] = {}
        switch_mean: Dict[str, float] = {}
        vegas: Dict[str, float] = {}
        walls: Dict[str, tuple] = {}

        for name, K in all_strikes.items():
            od = ods.get(name)
            if od is None:
                continue
            bw, wm, aw = self._walls(od)
            if wm is None:
                if aw is not None:
                    wm = aw - 0.5
                    bw = aw - 1
                elif bw is not None:
                    wm = bw + 0.5
                    aw = bw + 1
                else:
                    continue
            walls[name] = (bw, wm, aw)
            theo, _, vega_v = self._opt_bs(S, K, T, self.SIGMA)
            diff = wm - theo
            cur_diff[name] = diff
            vegas[name] = vega_v
            mean_diff[name] = self._ema(saved, f"_opt_diff_{name}", THEO_NORM_WINDOW, diff)
            switch_mean[name] = self._ema(
                saved,
                f"_opt_sw_{name}",
                IV_SCALPING_WINDOW,
                abs(diff - mean_diff[name]),
            )

        if state.timestamp // 100 < max(IV_SCALPING_WINDOW, OPT_MR_WINDOW):
            return out

        for name, K in SCALP_STRIKES.items():
            if name not in cur_diff:
                continue
            bw, wm, aw = walls[name]
            sm = switch_mean[name]
            p = pos.get(name, 0)
            limit = self.LIMITS[name]
            max_sell = limit + p
            max_buy = limit - p
            orders = out.setdefault(name, [])
            if sm < IV_SCALPING_THR:
                if p > 0:
                    orders.append(Order(name, int(bw), -p))
                elif p < 0:
                    orders.append(Order(name, int(aw), -p))
                continue
            cur = cur_diff[name]
            mean = mean_diff[name]
            low_vega_adj = LOW_VEGA_THR_ADJ if vegas.get(name, 0.0) <= 1 else 0.0
            sell_score = cur - wm + bw - mean
            buy_score = cur - wm + aw - mean
            if sell_score >= (THR_OPEN + low_vega_adj) and max_sell > 0:
                orders.append(Order(name, int(bw), -max_sell))
            if sell_score >= THR_CLOSE and p > 0:
                orders.append(Order(name, int(bw), -p))
            elif buy_score <= -(THR_OPEN + low_vega_adj) and max_buy > 0:
                orders.append(Order(name, int(aw), max_buy))
            if buy_score <= -THR_CLOSE and p < 0:
                orders.append(Order(name, int(aw), -p))

        for name, K in MR_STRIKES.items():
            if name not in cur_diff:
                continue
            bw, wm, aw = walls[name]
            iv_dev = cur_diff[name] - mean_diff[name]
            combined = ema_o_dev + 2.25 * iv_dev
            p = pos.get(name, 0)
            limit = self.LIMITS[name]
            max_sell = limit + p
            max_buy = limit - p
            orders = out.setdefault(name, [])
            if combined > OPT_MR_THR and max_sell > 0:
                orders.append(Order(name, int(bw), -max_sell))
            elif combined < -OPT_MR_THR and max_buy > 0:
                orders.append(Order(name, int(aw), max_buy))

        if self.ENABLE_UNDERLYING_MR:
            u_pos = pos.get("VELVETFRUIT_EXTRACT", 0)
            u_limit = self.LIMITS["VELVETFRUIT_EXTRACT"]
            u_max_sell = u_limit + u_pos
            u_max_buy = u_limit - u_pos
            u_orders = out.setdefault("VELVETFRUIT_EXTRACT", [])
            if ema_o_dev > self.UNDER_MR_THR and u_max_sell > 0:
                u_orders.append(Order("VELVETFRUIT_EXTRACT", int(u_bw + 1), -u_max_sell))
            elif ema_o_dev < -self.UNDER_MR_THR and u_max_buy > 0:
                u_orders.append(Order("VELVETFRUIT_EXTRACT", int(u_aw - 1), u_max_buy))

        return {k: v for k, v in out.items() if v}

    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        pos = state.position

        vfe_mom20: Optional[float] = None
        u_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if u_od is not None:
            u_book = self._book(u_od)
            if u_book is not None:
                vfe_hist = list(saved.get("vfe_hist") or [])
                vfe_hist.append(u_book["touch_mid"])
                if len(vfe_hist) > self.H_VFE_MOM_LOOKBACK + 1:
                    vfe_hist = vfe_hist[-(self.H_VFE_MOM_LOOKBACK + 1):]
                if len(vfe_hist) >= self.H_VFE_MOM_LOOKBACK + 1:
                    vfe_mom20 = vfe_hist[-1] - vfe_hist[0]
                saved["vfe_hist"] = vfe_hist

        last_mid = saved.get("last_mid_H")
        last_dmid = saved.get("last_dmid_H", 0.0)
        dmid_hist = list(saved.get("dmid_hist_H") or [])

        if "HYDROGEL_PACK" in state.order_depths:
            h_orders, new_mid = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0),
                last_mid,
                last_dmid,
                dmid_hist,
                vfe_mom20,
            )
            if h_orders:
                result["HYDROGEL_PACK"] = h_orders
            if new_mid is not None:
                if last_mid is not None:
                    dmid = new_mid - last_mid
                    saved["last_dmid_H"] = dmid
                    dmid_hist.append(dmid)
                    if len(dmid_hist) > self.DMID_HISTORY:
                        dmid_hist = dmid_hist[-self.DMID_HISTORY:]
                else:
                    saved["last_dmid_H"] = 0.0
                saved["last_mid_H"] = new_mid
                saved["dmid_hist_H"] = dmid_hist

        if u_od is not None:
            u_book = self._book(u_od)
            if u_book is not None:
                S = u_book["touch_mid"]
                T = self._tte_years(state.timestamp)

                for name, K in self.SYNTH_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is not None:
                        orders = self._trade_synth_voucher(name, K, od, pos.get(name, 0), S, T)
                        if orders:
                            result[name] = orders

                atm_residuals = dict(saved.get("atm_residuals") or {})
                for name, K in self.ATM_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is not None:
                        orders, new_residual = self._trade_atm(
                            name,
                            K,
                            od,
                            pos.get(name, 0),
                            S,
                            T,
                            atm_residuals.get(name),
                        )
                        if orders:
                            result[name] = orders
                        atm_residuals[name] = new_residual
                saved["atm_residuals"] = atm_residuals

        for prod, orders in self._trade_iv_residual(state, pos, saved).items():
            if prod in result:
                result[prod].extend(orders)
            else:
                result[prod] = orders

        for name in self.LOTTERY_STRIKES:
            od = state.order_depths.get(name)
            if od is not None:
                orders = self._trade_lottery(name, od, pos.get(name, 0))
                if orders:
                    result[name] = orders

        return result, 0, json.dumps(saved)
