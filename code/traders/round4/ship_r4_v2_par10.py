"""
Round 4 SHIP v2_burst — Jakob-P hypothesis test.

Hypothesis from a competitor PnL chart (Jakob P, ~70k on 1/10 of one day,
extrapolates to ~700k/day). Chart shape (early -10k drawdown, climb to peak,
sideways grind) is signature of an inventory-building directional MR
that runs at MUCH larger size than v1's cap=8.

Three changes vs ship_r4_v1.py (baseline 452,050 R4 bt):

1. VFE_MAX_TAKE_PER_TICK 8 -> 50
   v1's per-tick take cap throttles Citadel to ~8 lots/tick. If Jakob is
   running uncapped or near-uncapped, he can reach full position limit
   ~6× faster, which front-loads the directional MR PnL.

2. Parallel-z on deep-ITM vouchers V4000, V4500, V5000.
   These are delta~0.99/0.96/~0.7 wrt VFE. Same Citadel signal that
   drives VFE side now ALSO steers these toward side*limit. Stacking
   ~3 product limits = effectively 3× notional VFE exposure without
   using any single product's position cap.

3. noflat = disable VS_INV_SKEW (already 0) and disable AR1_BETA on
   HYDROGEL when working position is in the "winning direction".
   v1 has AR1_BETA=0.20 which mean-reverts the fair toward anchor on
   recent dmid; that's a soft flatten that bleeds carry on trends.

Risk: parallel-z amplifies BOTH gains AND drawdowns. Day-3 ts 400k-499k
bucket already loses -76k on v1 chassis; with 3× exposure that becomes
-200k+ if the signal is wrong.

Source: ship_r4_v1.py at 452,050 R4 bt (PYTHONHASHSEED=0).
"""
from typing import Dict, List
from statistics import NormalDist
import math
import json

from datamodel import Order, OrderDepth, TradingState


_N = NormalDist()
DAYS_PER_YEAR = 365
TTE_DAYS_LIVE = 4.0

THR_OPEN, THR_CLOSE = 0.5, 0.0
LOW_VEGA_THR_ADJ = 0.5
THEO_NORM_WINDOW = 25
IV_SCALPING_THR = 0.7
IV_SCALPING_WINDOW = 100
OPT_MR_WINDOW = 44
OPT_MR_THR = 6.3

SCALP_STRIKES: Dict[str, int] = {}
MR_STRIKES = {
    "VEV_5000": 5000, "VEV_5100": 5100,
    "VEV_5200": 5200, "VEV_5300": 5300,
}


class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
        "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
        "VEV_6500": 300,
    }

    SYNTH_STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500}

    # ----- HYDROGEL -----
    H_ANCHOR = 9983.0
    H_CLIP = 33.0
    H_TAKE_EDGE = 0.3
    H_REDUCE_EDGE = 0.0
    H_PENNY_EDGE = 3.5
    H_INV_SKEW = 0.014
    H_INV_SKEW_LONG = -0.015
    H_INV_SKEW_SHORT = 0.014
    H_MAX_POST_SIZE = 18
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8
    AR1_BETA = 0.20
    TYPICAL_SPREAD = 16
    CLIP_VOL_K = 0.78
    DMID_HISTORY = 150

    H_VK_UP = 0.50
    H_VK_DN = 0.87
    H_VK_DN_LONG = 2.7
    H_VK_DN_SHORT = 0.85
    H_VK_DN_HIGH = 12.0
    H_VK_DN_LOW = 2.7
    H_POS_THR = 120
    H_VK_DN_XTREME = 16.0
    H_POS_THR_2 = 165

    H_BASE_POST_SIZE = 18
    H_POST_VOL_K = 1.0
    H_POST_VK_HIGH = 2.0
    H_POST_VK_LOW = 0.3
    H_POST_ABS_POS_THR = 150
    H_POST_MIN = 12
    H_POST_MAX = 18

    MID_RANGE_HISTORY = 200
    DRIFT_GATE_RANGE = 53
    DRIFT_CLIP_BOOST = 1.5

    # ----- Underlying MR -----
    ENABLE_UNDERLYING_MR = True
    UNDER_MR_THR = 6

    # ----- Citadel bipolar VFE — BURST CAP -----
    ENABLE_CITADEL_VFE_MR = True
    VFE_EMA_ALPHA = 0.0005
    VFE_SIGMA_ALPHA = 0.0005
    VFE_SIGMA_FLOOR = 1.0
    VFE_WARMUP_TICKS = 90
    VFE_Z_ENTER = 2.0
    VFE_MAX_TAKE_PER_TICK = 8  # v1=8; burst-mode 6.25x

    # ----- v2_burst: parallel-z on deep-ITM vouchers -----
    # Same Citadel side drives V4000, V4500, V5000 toward side*limit.
    # Delta ~0.99/0.96/0.7 means each unit is ~equivalent VFE exposure.
    ENABLE_PARALLEL_Z = True
    PARALLEL_Z_PRODUCTS = ("VEV_4000", "VEV_4500", "VEV_5000")
    PARALLEL_MAX_TAKE_PER_TICK = 10

    UNDER_DRIFT_TARGET = 200
    VEV_CARRY_TARGET = 300
    VEV_CARRY_SIZE = 30
    UNDER_CARRY_BID_SIZE = 30

    ATM_STRIKES = {"VEV_5400": 5400, "VEV_5500": 5500}
    ATM_RESIDUAL_ALPHA = 1.0 / 5000
    ATM_MAX_POST_SIZE = 20
    ATM_TAKE_EDGE = 0.0
    ATM_PENNY_EDGE = 0.0
    ATM_INV_SKEW = 0.0
    ATM_WIDE_SPREAD = 1
    ATM_PER_STRIKE_LIMIT_RATIO = 0.85

    LOTTERY_STRIKES = {"VEV_6000": 6000, "VEV_6500": 6500}
    LOTTERY_BID_PRICE = 0
    LOTTERY_BID_SIZE = 30
    LOTTERY_ASK_PRICE = 1
    LOTTERY_ASK_SIZE = 30

    SIGMA = 0.252
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.0
    VS_MAX_POST_SIZE = 40
    VS_WIDE_SPREAD = 3
    VS_IMB_STRONG = 0.30
    VS_IMB_FAVORABLE_BOOST = 1.8
    VS_IMB_ADVERSE_SHRINK = 0.2

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

    def _walls(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None, None, None
        bid_wall = min(od.buy_orders.keys())
        ask_wall = max(od.sell_orders.keys())
        return bid_wall, 0.5 * (bid_wall + ask_wall), ask_wall

    def _cap_size(self, max_size, pos, side, cap, limit):
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
        tte_days = TTE_DAYS_LIVE - ts / 1e6
        return max(0.0, tte_days) / DAYS_PER_YEAR

    @staticmethod
    def _ema(saved: Dict, key: str, window: int, value: float) -> float:
        old = saved.get(key, 0.0)
        alpha = 2.0 / (window + 1)
        new = alpha * value + (1 - alpha) * old
        saved[key] = new
        return new

    def _fair_input_h(self, book):
        if book["spread"] < self.TYPICAL_SPREAD:
            tot = book["bv"] + book["av"]
            if tot > 0:
                return (book["ba"] * book["bv"] + book["bb"] * book["av"]) / tot
        return book["touch_mid"]

    def _trade_hydrogel(self, od, pos, last_dmid, dmid_hist, mid_hist):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]; tm = book["touch_mid"]

        if self.CLIP_VOL_K > 0 and len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mean_d = sum(dmid_hist) / n
            std_d = math.sqrt(sum((d - mean_d) ** 2 for d in dmid_hist) / n)
            clip_up = self.H_CLIP + self.H_VK_UP * std_d
            if pos > self.H_POS_THR_2:
                vk_dn_eff = self.H_VK_DN_XTREME
            elif pos > self.H_POS_THR:
                vk_dn_eff = self.H_VK_DN_HIGH
            elif pos > 0:
                vk_dn_eff = self.H_VK_DN_LOW
            elif pos < 0:
                vk_dn_eff = self.H_VK_DN_SHORT
            else:
                vk_dn_eff = self.H_VK_DN
            clip_dn = self.H_CLIP + vk_dn_eff * std_d
        else:
            clip_up = self.H_CLIP
            clip_dn = self.H_CLIP

        fair_input = self._fair_input_h(book)
        fair_adj = max(-clip_dn, min(clip_up, fair_input - self.H_ANCHOR))
        fair = self.H_ANCHOR + fair_adj
        if last_dmid is not None:
            fair -= self.AR1_BETA * last_dmid

        working = pos
        orders: List[Order] = []
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            inv_skew_eff = self.H_INV_SKEW_LONG if working > 0 else (self.H_INV_SKEW_SHORT if working < 0 else self.H_INV_SKEW)
            skew = fair - inv_skew_eff * working
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
            inv_skew_eff = self.H_INV_SKEW_LONG if working > 0 else (self.H_INV_SKEW_SHORT if working < 0 else self.H_INV_SKEW)
            skew = fair - inv_skew_eff * working
            if bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q

        inv_skew_eff = self.H_INV_SKEW_LONG if working > 0 else (self.H_INV_SKEW_SHORT if working < 0 else self.H_INV_SKEW)
        skew = fair - inv_skew_eff * working
        buy_cap = max(0, limit - working); sell_cap = max(0, limit + working)
        if self.H_POST_VOL_K != 0 and len(dmid_hist) >= 3:
            n_d = len(dmid_hist)
            mn_d = sum(dmid_hist) / n_d
            sd_d = math.sqrt(sum((d - mn_d) ** 2 for d in dmid_hist) / n_d)
            effective_pvk = self.H_POST_VK_HIGH if abs(working) > self.H_POST_ABS_POS_THR else self.H_POST_VK_LOW
            adaptive_size = self.H_BASE_POST_SIZE - effective_pvk * sd_d
            adaptive_size = max(self.H_POST_MIN,
                                min(self.H_POST_MAX, int(round(adaptive_size))))
        else:
            adaptive_size = self.H_BASE_POST_SIZE
        bid_size = self._cap_size(adaptive_size, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(adaptive_size, working, "sell", sell_cap, limit)
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
        return orders, tm

    def _trade_synth_voucher(self, name, K, od, pos, S, T):
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]
        fair, _, _ = self._opt_bs(S, K, T, self.SIGMA)
        working = pos
        orders: List[Order] = []
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
        skew = fair - self.VS_INV_SKEW * working
        buy_cap = max(0, limit - working); sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.VS_MAX_POST_SIZE, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(self.VS_MAX_POST_SIZE, working, "sell", sell_cap, limit)

        bv_l1 = book["bv"]; av_l1 = book["av"]
        tot_l1 = bv_l1 + av_l1
        imb = (bv_l1 - av_l1) / tot_l1 if tot_l1 > 0 else 0.0
        if imb > self.VS_IMB_STRONG:
            ask_size = max(0, int(round(ask_size * self.VS_IMB_ADVERSE_SHRINK)))
            bid_size = min(buy_cap, int(round(bid_size * self.VS_IMB_FAVORABLE_BOOST)))
        elif imb < -self.VS_IMB_STRONG:
            bid_size = max(0, int(round(bid_size * self.VS_IMB_ADVERSE_SHRINK)))
            ask_size = min(sell_cap, int(round(ask_size * self.VS_IMB_FAVORABLE_BOOST)))

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

    def _trade_atm(self, name, K, od, pos, S, T, residual):
        limit = self.LIMITS[name]
        per_strike_limit = int(limit * self.ATM_PER_STRIKE_LIMIT_RATIO)
        book = self._book(od)
        if not book:
            return [], residual if residual is not None else 0.0
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]; tm = book["touch_mid"]

        bs_theo, _, _ = self._opt_bs(S, K, T, self.SIGMA)
        instant_residual = tm - bs_theo
        if residual is None:
            new_residual = instant_residual
        else:
            a = self.ATM_RESIDUAL_ALPHA
            new_residual = (1 - a) * residual + a * instant_residual
        fair = bs_theo + new_residual
        working = pos
        orders: List[Order] = []

        for ap, av in book["sells"].items():
            cap = per_strike_limit - working
            if cap <= 0:
                break
            skew = fair - self.ATM_INV_SKEW * working
            if ap <= skew - self.ATM_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(name, ap, q)); working += q
            elif working < 0 and ap <= skew:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(name, ap, q)); working += q
        for bp, bv in book["buys"].items():
            cap = per_strike_limit + working
            if cap <= 0:
                break
            skew = fair - self.ATM_INV_SKEW * working
            if bp >= skew + self.ATM_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q
            elif working > 0 and bp >= skew:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q

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

    def _trade_lottery(self, name, K, od, pos):
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return []
        orders: List[Order] = []
        room_buy = limit - pos
        if room_buy > 0:
            orders.append(Order(name, self.LOTTERY_BID_PRICE,
                                min(self.LOTTERY_BID_SIZE, room_buy)))
        if pos > 0:
            orders.append(Order(name, self.LOTTERY_ASK_PRICE,
                                -min(self.LOTTERY_ASK_SIZE, pos)))
        return orders

    def _trade_iv_residual(self, state: TradingState, pos, saved):
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
                    wm = aw - 0.5; bw = aw - 1
                elif bw is not None:
                    wm = bw + 0.5; aw = bw + 1
                else:
                    continue
            walls[name] = (bw, wm, aw)
            theo, _, vega_v = self._opt_bs(S, K, T, self.SIGMA)
            d = wm - theo
            cur_diff[name] = d
            vegas[name] = vega_v
            md = self._ema(saved, f"_opt_diff_{name}", THEO_NORM_WINDOW, d)
            mean_diff[name] = md
            sm = self._ema(saved, f"_opt_sw_{name}", IV_SCALPING_WINDOW, abs(d - md))
            switch_mean[name] = sm

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
            orders: List[Order] = out.setdefault(name, [])
            if sm < IV_SCALPING_THR:
                if p > 0:
                    orders.append(Order(name, int(bw), -p))
                elif p < 0:
                    orders.append(Order(name, int(aw), -p))
                continue
            cur = cur_diff[name]; mean = mean_diff[name]
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
            combined = ema_o_dev + 1.75 * iv_dev
            p = pos.get(name, 0)
            limit = self.LIMITS[name]
            max_sell = limit + p
            max_buy = limit - p
            orders: List[Order] = out.setdefault(name, [])
            if combined > OPT_MR_THR and max_sell > 0:
                orders.append(Order(name, int(bw), -max_sell))
            elif combined < -OPT_MR_THR and max_buy > 0:
                orders.append(Order(name, int(aw), max_buy))
            else:
                od = ods.get(name)
                if od is not None and od.buy_orders and od.sell_orders:
                    bb_lvl = max(od.buy_orders.keys())
                    if p < self.VEV_CARRY_TARGET:
                        cap = min(max_buy, self.VEV_CARRY_TARGET - p)
                        if cap > 0:
                            for offset, sz in [(0, 30), (-1, 20)]:
                                if cap <= 0: break
                                actual_sz = min(cap, sz)
                                px = bb_lvl + offset
                                if actual_sz > 0 and px > 0:
                                    orders.append(Order(name, px, actual_sz))
                                    cap -= actual_sz

        if self.ENABLE_CITADEL_VFE_MR and u_od is not None:
            vfe_orders, side = self._trade_citadel_vfe_mr(
                u_od, pos.get("VELVETFRUIT_EXTRACT", 0), saved,
            )
            if vfe_orders:
                out["VELVETFRUIT_EXTRACT"] = vfe_orders

            # v2_burst: parallel-z on V4000/V4500/V5000.
            # When Citadel side is set, push these toward side*limit using
            # the same per-tick cap. Override IV-residual orders for V5000.
            if self.ENABLE_PARALLEL_Z and side != 0:
                for prod_name in self.PARALLEL_Z_PRODUCTS:
                    pod = ods.get(prod_name)
                    if pod is None:
                        continue
                    p_orders = self._trade_parallel_z(
                        prod_name, pod, pos.get(prod_name, 0), side,
                    )
                    if p_orders:
                        out[prod_name] = p_orders

        return {k: v for k, v in out.items() if v}

    def _trade_citadel_vfe_mr(self, od, cur_pos, saved):
        if od is None or not od.buy_orders or not od.sell_orders:
            return [], 0
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        if bb >= ba:
            return [], 0
        mid = 0.5 * (bb + ba)

        ema = saved.get("vfe_ema_long")
        sigma_var = float(saved.get("vfe_sigma_var", 0.0))
        ticks = int(saved.get("vfe_ticks", 0))
        side = int(saved.get("vfe_side", 0))

        if ema is None:
            ema = mid
        else:
            a = self.VFE_EMA_ALPHA
            ema = (1.0 - a) * ema + a * mid
        dev = mid - ema
        sa = self.VFE_SIGMA_ALPHA
        sigma_var = (1.0 - sa) * sigma_var + sa * (dev * dev)
        sigma = max(math.sqrt(sigma_var), self.VFE_SIGMA_FLOOR)
        ticks += 1

        if ticks >= self.VFE_WARMUP_TICKS:
            z = dev / sigma
            if z >= self.VFE_Z_ENTER:
                side = -1
            elif z <= -self.VFE_Z_ENTER:
                side = 1

        saved["vfe_ema_long"] = ema
        saved["vfe_sigma_var"] = sigma_var
        saved["vfe_ticks"] = ticks
        saved["vfe_side"] = side

        target = side * self.LIMITS["VELVETFRUIT_EXTRACT"]
        diff = target - cur_pos
        if diff == 0:
            return [], side
        cap = min(abs(diff), self.VFE_MAX_TAKE_PER_TICK)
        orders: List[Order] = []
        if diff > 0:
            cap = min(cap, self.LIMITS["VELVETFRUIT_EXTRACT"] - cur_pos)
            if cap <= 0:
                return [], side
            for ap in sorted(od.sell_orders.keys()):
                if cap <= 0:
                    break
                avail = abs(int(od.sell_orders[ap]))
                if avail <= 0:
                    continue
                q = min(avail, cap)
                orders.append(Order("VELVETFRUIT_EXTRACT", int(ap), q))
                cap -= q
        else:
            cap = min(cap, self.LIMITS["VELVETFRUIT_EXTRACT"] + cur_pos)
            if cap <= 0:
                return [], side
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                if cap <= 0:
                    break
                avail = int(od.buy_orders[bp])
                if avail <= 0:
                    continue
                q = min(avail, cap)
                orders.append(Order("VELVETFRUIT_EXTRACT", int(bp), -q))
                cap -= q
        return orders, side

    def _trade_parallel_z(self, prod_name, od, cur_pos, side):
        """v2_burst: drive deep-ITM voucher toward side*limit on Citadel signal."""
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        limit = self.LIMITS[prod_name]
        target = side * limit
        diff = target - cur_pos
        if diff == 0:
            return []
        cap = min(abs(diff), self.PARALLEL_MAX_TAKE_PER_TICK)
        orders: List[Order] = []
        if diff > 0:
            cap = min(cap, limit - cur_pos)
            if cap <= 0:
                return []
            for ap in sorted(od.sell_orders.keys()):
                if cap <= 0:
                    break
                avail = abs(int(od.sell_orders[ap]))
                if avail <= 0:
                    continue
                q = min(avail, cap)
                orders.append(Order(prod_name, int(ap), q))
                cap -= q
        else:
            cap = min(cap, limit + cur_pos)
            if cap <= 0:
                return []
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                if cap <= 0:
                    break
                avail = int(od.buy_orders[bp])
                if avail <= 0:
                    continue
                q = min(avail, cap)
                orders.append(Order(prod_name, int(bp), -q))
                cap -= q
        return orders

    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}
        last_mid = saved.get("last_mid_H")
        last_dmid = saved.get("last_dmid_H", 0.0)
        dmid_hist = saved.get("dmid_hist_H", [])
        mid_hist = saved.get("mid_hist_H", [])

        result: Dict[str, List[Order]] = {}
        pos = state.position

        new_mid = None
        if "HYDROGEL_PACK" in state.order_depths:
            orders, tm = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0),
                last_dmid, dmid_hist, mid_hist,
            )
            result["HYDROGEL_PACK"] = orders
            new_mid = tm
        if new_mid is not None:
            if last_mid is not None:
                d = new_mid - last_mid
                saved["last_dmid_H"] = d
                dmid_hist.append(d)
                if len(dmid_hist) > self.DMID_HISTORY:
                    dmid_hist = dmid_hist[-self.DMID_HISTORY:]
            else:
                saved["last_dmid_H"] = 0.0
            mid_hist.append(new_mid)
            if len(mid_hist) > self.MID_RANGE_HISTORY:
                mid_hist = mid_hist[-self.MID_RANGE_HISTORY:]
            saved["last_mid_H"] = new_mid
            saved["dmid_hist_H"] = dmid_hist
            saved["mid_hist_H"] = mid_hist

        u_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if u_od is not None:
            u_book = self._book(u_od)
            if u_book is not None:
                S_synth = u_book["touch_mid"]
                T_synth = self._tte_years(state.timestamp)
                for name, K in self.SYNTH_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is not None:
                        result[name] = self._trade_synth_voucher(
                            name, K, od, pos.get(name, 0), S_synth, T_synth,
                        )

        for prod, orders in self._trade_iv_residual(state, pos, saved).items():
            if prod in result:
                result[prod] = orders  # parallel-z OVERRIDES synth-MM
            else:
                result[prod] = orders

        if u_od is not None:
            u_book = self._book(u_od)
            if u_book is not None:
                S_atm = u_book["touch_mid"]
                T_atm = self._tte_years(state.timestamp)
                atm_residuals = saved.get("atm_residuals", {})
                for name, K in self.ATM_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is not None:
                        orders, new_r = self._trade_atm(
                            name, K, od, pos.get(name, 0), S_atm, T_atm,
                            atm_residuals.get(name),
                        )
                        atm_residuals[name] = new_r
                        if orders:
                            if name in result:
                                result[name].extend(orders)
                            else:
                                result[name] = orders
                saved["atm_residuals"] = atm_residuals

        for name, K in self.LOTTERY_STRIKES.items():
            od = state.order_depths.get(name)
            if od is not None:
                orders = self._trade_lottery(name, K, od, pos.get(name, 0))
                if orders:
                    result[name] = orders

        return result, 0, json.dumps(saved, separators=(",", ":"))
