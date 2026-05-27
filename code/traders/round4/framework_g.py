"""
Framework G - Timo-style minimal R4 chassis.

KEPT: HYDROGEL Timo MM + Mark 22 fade, VFE Citadel z-score MR, VEV_4000/4500 synth MM.
ADDED: Timo IV scalp on V5000-5300 (THR=0.03 from R4 retune).
DROPPED (poor live conversion per memory): ATM smile V5400/V5500, lottery V6000/V6500,
  VEV carry/drift target, L1 imbalance sizing, IV-residual MR (replaced by scalp).
"""
from typing import Dict, List
from statistics import NormalDist
import math
import json

from datamodel import Order, OrderDepth, TradingState

_N = NormalDist()
DAYS_PER_YEAR = 365
TTE_DAYS_LIVE = 4.0

H_ANCHOR = 9983.0
H_CLIP = 33.0
H_TAKE_EDGE = 0.3
H_PENNY_EDGE = 3.5
H_INV_SKEW = 0.014
H_INV_SKEW_LONG = -0.015
H_INV_SKEW_SHORT = 0.014
H_PASSIVE_OFFSET = 8.0
H_WIDE_SPREAD = 8
AR1_BETA = 0.20
TYPICAL_SPREAD = 16
DMID_HISTORY = 150
H_VK_UP = 0.50
H_VK_DN = 0.87
H_VK_DN_LOW = 2.7
H_VK_DN_SHORT = 0.85
H_VK_DN_HIGH = 12.0
H_POS_THR = 120
H_VK_DN_XTREME = 16.0
H_POS_THR_2 = 165
H_BASE_POST_SIZE = 18
H_POST_VK_HIGH = 2.0
H_POST_VK_LOW = 0.3
H_POST_ABS_POS_THR = 150
H_POST_MIN = 12
H_POST_MAX = 18
H_M22_DECAY = 0.92
H_M22_SHIFT_PER_QTY = 0.40

VFE_EMA_ALPHA = 0.0005
VFE_SIGMA_ALPHA = 0.0005
VFE_SIGMA_FLOOR = 1.0
VFE_WARMUP_TICKS = 65
VFE_Z_ENTER = 2.0
VFE_MAX_TAKE_PER_TICK = 8

SIGMA = 0.23
VS_TAKE_EDGE = 0.0
VS_PENNY_EDGE = 1.0
VS_INV_SKEW = 0.0
VS_MAX_POST_SIZE = 40
VS_WIDE_SPREAD = 3

SCALP_STRIKES = {"VEV_5000": 5000, "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300}
THEO_NORM_WINDOW = 20
SCALP_THR_OPEN = 0.03
SCALP_THR_CLOSE = 0.0
LOW_VEGA_THR_ADJ = 0.5
SCALP_PER_TICK_MAX = 30


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

    @staticmethod
    def _book(od):
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys); ba = min(sells)
        return {"buys": dict(sorted(buys.items(), reverse=True)),
                "sells": dict(sorted(sells.items())),
                "bb": bb, "ba": ba, "bv": buys[bb], "av": sells[ba],
                "spread": ba - bb, "touch_mid": 0.5 * (bb + ba)}

    @staticmethod
    def _cap_size(max_size, pos, side, cap, limit):
        if cap <= 0:
            return 0
        ratio = 1.0 - min(0.7, abs(pos) / limit)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    @staticmethod
    def _opt_bs(S, K, T, sigma):
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
    def _tte_years(ts):
        days = TTE_DAYS_LIVE - ts / 1e6
        return max(0.0, days) / DAYS_PER_YEAR

    @staticmethod
    def _ema(saved, key, window, value):
        old = saved.get(key, None)
        if old is None:
            saved[key] = value
            return value
        alpha = 2.0 / (window + 1)
        new = alpha * value + (1 - alpha) * old
        saved[key] = new
        return new

    def _fair_input_h(self, book):
        if book["spread"] < TYPICAL_SPREAD:
            tot = book["bv"] + book["av"]
            if tot > 0:
                return (book["ba"] * book["bv"] + book["bb"] * book["av"]) / tot
        return book["touch_mid"]

    def _hydrogel_m22_fair_shift(self, h_market_trades, saved):
        shift = float(saved.get("h_m22_shift", 0.0)) * H_M22_DECAY
        for tr in (h_market_trades or []):
            if getattr(tr, "seller", None) == "Mark 22":
                qty = abs(int(getattr(tr, "quantity", 0)))
                shift += H_M22_SHIFT_PER_QTY * qty
        saved["h_m22_shift"] = shift
        return shift

    def _trade_hydrogel(self, od, pos, last_dmid, dmid_hist, m22_shift):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]; tm = book["touch_mid"]

        if len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mean_d = sum(dmid_hist) / n
            std_d = math.sqrt(sum((d - mean_d) ** 2 for d in dmid_hist) / n)
            clip_up = H_CLIP + H_VK_UP * std_d
            if pos > H_POS_THR_2:
                vk_dn_eff = H_VK_DN_XTREME
            elif pos > H_POS_THR:
                vk_dn_eff = H_VK_DN_HIGH
            elif pos > 0:
                vk_dn_eff = H_VK_DN_LOW
            elif pos < 0:
                vk_dn_eff = H_VK_DN_SHORT
            else:
                vk_dn_eff = H_VK_DN
            clip_dn = H_CLIP + vk_dn_eff * std_d
        else:
            clip_up = H_CLIP
            clip_dn = H_CLIP

        fair_input = self._fair_input_h(book)
        fair_adj = max(-clip_dn, min(clip_up, fair_input - H_ANCHOR))
        fair = H_ANCHOR + fair_adj
        if last_dmid is not None:
            fair -= AR1_BETA * last_dmid
        fair += m22_shift

        working = pos
        orders: List[Order] = []
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            inv = H_INV_SKEW_LONG if working > 0 else (H_INV_SKEW_SHORT if working < 0 else H_INV_SKEW)
            skew = fair - inv * working
            if ap <= skew - H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            inv = H_INV_SKEW_LONG if working > 0 else (H_INV_SKEW_SHORT if working < 0 else H_INV_SKEW)
            skew = fair - inv * working
            if bp >= skew + H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q

        inv = H_INV_SKEW_LONG if working > 0 else (H_INV_SKEW_SHORT if working < 0 else H_INV_SKEW)
        skew = fair - inv * working
        buy_cap = max(0, limit - working); sell_cap = max(0, limit + working)
        if len(dmid_hist) >= 3:
            n_d = len(dmid_hist)
            mn_d = sum(dmid_hist) / n_d
            sd_d = math.sqrt(sum((d - mn_d) ** 2 for d in dmid_hist) / n_d)
            effective_pvk = H_POST_VK_HIGH if abs(working) > H_POST_ABS_POS_THR else H_POST_VK_LOW
            adaptive_size = H_BASE_POST_SIZE - effective_pvk * sd_d
            adaptive_size = max(H_POST_MIN, min(H_POST_MAX, int(round(adaptive_size))))
        else:
            adaptive_size = H_BASE_POST_SIZE
        bid_size = self._cap_size(adaptive_size, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(adaptive_size, working, "sell", sell_cap, limit)
        if spread >= H_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - H_PENNY_EDGE))
            ask_price = max(ba - 1, math.ceil(skew + H_PENNY_EDGE))
        else:
            bid_price = math.floor(skew - H_PASSIVE_OFFSET)
            ask_price = math.ceil(skew + H_PASSIVE_OFFSET)
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
        fair, _, _ = self._opt_bs(S, K, T, SIGMA)
        working = pos
        orders: List[Order] = []
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - VS_INV_SKEW * working
            if ap <= skew - VS_TAKE_EDGE:
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
            skew = fair - VS_INV_SKEW * working
            if bp >= skew + VS_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q
            elif working > 0 and bp >= skew:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q
        skew = fair - VS_INV_SKEW * working
        buy_cap = max(0, limit - working); sell_cap = max(0, limit + working)
        bid_size = self._cap_size(VS_MAX_POST_SIZE, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(VS_MAX_POST_SIZE, working, "sell", sell_cap, limit)
        if spread >= VS_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - VS_PENNY_EDGE))
            ask_price = max(ba - 1, math.ceil(skew + VS_PENNY_EDGE))
            bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
            ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)
            if bid_price < ask_price:
                if bid_size > 0:
                    orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0:
                    orders.append(Order(name, ask_price, -ask_size))
        return orders

    def _trade_iv_scalp(self, name, K, od, pos, S, T, saved):
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        theo, _, vega = self._opt_bs(S, K, T, SIGMA)
        diff = book["touch_mid"] - theo
        mdiff = self._ema(saved, f"_iv_diff_{name}", THEO_NORM_WINDOW, diff)
        sell_score = bb - theo - mdiff
        buy_score = ba - theo - mdiff
        low_vega_adj = LOW_VEGA_THR_ADJ if vega <= 1.0 else 0.0
        limit = self.LIMITS[name]
        max_sell = limit + pos
        max_buy = limit - pos
        orders: List[Order] = []
        if sell_score >= SCALP_THR_OPEN + low_vega_adj and max_sell > 0:
            q = min(book["bv"], max_sell, SCALP_PER_TICK_MAX)
            if q > 0:
                orders.append(Order(name, int(bb), -q))
        elif sell_score >= SCALP_THR_CLOSE and pos > 0:
            q = min(book["bv"], pos, SCALP_PER_TICK_MAX)
            if q > 0:
                orders.append(Order(name, int(bb), -q))
        if buy_score <= -(SCALP_THR_OPEN + low_vega_adj) and max_buy > 0:
            q = min(book["av"], max_buy, SCALP_PER_TICK_MAX)
            if q > 0:
                orders.append(Order(name, int(ba), q))
        elif buy_score <= -SCALP_THR_CLOSE and pos < 0:
            q = min(book["av"], -pos, SCALP_PER_TICK_MAX)
            if q > 0:
                orders.append(Order(name, int(ba), q))
        return orders

    def _trade_citadel_vfe_mr(self, od, cur_pos, saved):
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        if bb >= ba:
            return []
        mid = 0.5 * (bb + ba)
        ema = saved.get("vfe_ema_long")
        sigma_var = float(saved.get("vfe_sigma_var", 0.0))
        ticks = int(saved.get("vfe_ticks", 0))
        side = int(saved.get("vfe_side", 0))
        if ema is None:
            ema = mid
        else:
            ema = (1.0 - VFE_EMA_ALPHA) * ema + VFE_EMA_ALPHA * mid
        dev = mid - ema
        sigma_var = (1.0 - VFE_SIGMA_ALPHA) * sigma_var + VFE_SIGMA_ALPHA * (dev * dev)
        sigma = max(math.sqrt(sigma_var), VFE_SIGMA_FLOOR)
        ticks += 1
        if ticks >= VFE_WARMUP_TICKS:
            z = dev / sigma
            if z >= VFE_Z_ENTER:
                side = -1
            elif z <= -VFE_Z_ENTER:
                side = 1
        saved["vfe_ema_long"] = ema
        saved["vfe_sigma_var"] = sigma_var
        saved["vfe_ticks"] = ticks
        saved["vfe_side"] = side
        target = side * self.LIMITS["VELVETFRUIT_EXTRACT"]
        diff = target - cur_pos
        if diff == 0:
            return []
        cap = min(abs(diff), VFE_MAX_TAKE_PER_TICK)
        orders: List[Order] = []
        if diff > 0:
            cap = min(cap, self.LIMITS["VELVETFRUIT_EXTRACT"] - cur_pos)
            if cap <= 0:
                return []
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
                return []
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                if cap <= 0:
                    break
                avail = int(od.buy_orders[bp])
                if avail <= 0:
                    continue
                q = min(avail, cap)
                orders.append(Order("VELVETFRUIT_EXTRACT", int(bp), -q))
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

        result: Dict[str, List[Order]] = {}
        pos = state.position
        ods = state.order_depths
        market_trades = getattr(state, "market_trades", {}) or {}

        new_mid = None
        if "HYDROGEL_PACK" in ods:
            m22_shift = self._hydrogel_m22_fair_shift(market_trades.get("HYDROGEL_PACK", []), saved)
            orders, tm = self._trade_hydrogel(
                ods["HYDROGEL_PACK"], pos.get("HYDROGEL_PACK", 0),
                last_dmid, dmid_hist, m22_shift,
            )
            if orders:
                result["HYDROGEL_PACK"] = orders
            new_mid = tm
        if new_mid is not None:
            if last_mid is not None:
                d = new_mid - last_mid
                saved["last_dmid_H"] = d
                dmid_hist.append(d)
                if len(dmid_hist) > DMID_HISTORY:
                    dmid_hist = dmid_hist[-DMID_HISTORY:]
            else:
                saved["last_dmid_H"] = 0.0
            saved["last_mid_H"] = new_mid
            saved["dmid_hist_H"] = dmid_hist

        u_od = ods.get("VELVETFRUIT_EXTRACT")
        if u_od is not None:
            u_book = self._book(u_od)
            if u_book is not None:
                S = u_book["touch_mid"]
                T = self._tte_years(state.timestamp)
                vfe_orders = self._trade_citadel_vfe_mr(u_od, pos.get("VELVETFRUIT_EXTRACT", 0), saved)
                if vfe_orders:
                    result["VELVETFRUIT_EXTRACT"] = vfe_orders
                for name, K in self.SYNTH_STRIKES.items():
                    od = ods.get(name)
                    if od is not None:
                        os_ = self._trade_synth_voucher(name, K, od, pos.get(name, 0), S, T)
                        if os_:
                            result[name] = os_
                for name, K in SCALP_STRIKES.items():
                    od = ods.get(name)
                    if od is None:
                        continue
                    os_ = self._trade_iv_scalp(name, K, od, pos.get(name, 0), S, T, saved)
                    if os_:
                        result[name] = os_

        return result, 0, json.dumps(saved, separators=(",", ":"))
