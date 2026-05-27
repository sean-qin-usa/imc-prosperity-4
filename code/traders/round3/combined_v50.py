"""
Round 3 combined SHIP v1 — 2026-04-24 (session 2).

3-day backtest match-trades all: +268,008 (72,648 / 102,805 / 92,555).
3-day backtest match-trades none (alpha floor): +124,854.
Baseline h_only_v8 (HYDROGEL alone): 171,890 / 37,656 → +96k / +87k.

Layers four sleeves, each independently verified:
  1. HYDROGEL_PACK: h_only_v8 handler (own-microstructure MM).
       3-day +171,890 alone.
  2. VEV_4000 / VEV_4500: synthetic-underlying MM at flat sigma=0.23.
       Spread on V4000 = 21 ticks (vs underlying 5) gives MM headroom.
       3-day ~+8k combined.
  3. Strikes 5000-5300: Timo-P3R3-style MR on (ema_o_dev + iv_dev).
       3-day ~+71k (5000:+12k, 5100:+27k, 5200:+24k, 5300:+8k).
       Residual EMA centers out flat-sigma bias automatically.
  4. VELVETFRUIT_EXTRACT underlying MR: cross spread on |ema_o_dev| > 5.
       3-day ~+19k.

Tuning: OPT_MR_THR=5 (peak; sweep showed 3:-542k, 4:-66k, 5:+249k,
6:+234k, 7:+247k). UNDER_MR_THR=5 (peak; 3:174k, 4:251k, 5:268k,
6:254k, 7:254k). OPT_MR_WINDOW=30 (peak; 20:222k, 25:242k, 30:268k,
40:117k, 50:-410). All windows/thresholds ported from Timo's P3R3
defaults; only the strike sets and SIGMA were refit for P4R3.

What we ALSO tried that didn't work (port of dead ends):
- IV scalping on OTM 5300/5400/5500: Timo's exact logic, fired 0 times
  on this data. Likely because scalp signal needs cur-mean residual
  > half_spread + 0.5; OTM books here have spread=1, residual rarely
  exceeds 1.5 at the THR.
- MR on 5400/5500: each lost 1-2k (vega < 1, residual is noise).
- Lowering OPT_MR_THR to 3 or 4: blew up (traded noise).
- VFE-hedge of voucher delta: pure tax (already in HYDROGEL_ONLY notes).

Underlying = VELVETFRUIT_EXTRACT (per-tick wall_mid).
"""
from typing import Dict, List
from statistics import NormalDist
import math
import json

from datamodel import Order, OrderDepth, TradingState


_N = NormalDist()
DAYS_PER_YEAR = 365
TTE_DAYS_LIVE = 5.0  # historical day 0 = TTE 8, day 1 = 7, day 2 = 6.

# IV-residual machinery constants (mirrors Timo P3R3)
THR_OPEN, THR_CLOSE = 0.5, 0.0
LOW_VEGA_THR_ADJ = 0.5
THEO_NORM_WINDOW = 15
IV_SCALPING_THR = 0.7
IV_SCALPING_WINDOW = 100
OPT_MR_WINDOW = 30
OPT_MR_THR = 5

# Strike bucketing — v3: MR on 5000/5100/5200/5300 only.  v2 added
# 5400/5500 to MR and each lost 1-2k (OTM, vega < 1, residual noise-dom).
# 5300 is a small win (+1.5-6k).
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

    # ----- HYDROGEL (h_only_v8) -----
    H_ANCHOR = 9985.0
    H_CLIP = 33.0
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 0.0
    H_PENNY_EDGE = 2.0
    H_INV_SKEW = 0.015
    H_MAX_POST_SIZE = 18
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8
    AR1_BETA = 0.18
    TYPICAL_SPREAD = 16
    CLIP_VOL_K = 0.3
    DMID_HISTORY = 20

    # ----- Underlying MR (VFE) — Timo P3R3 port -----
    ENABLE_UNDERLYING_MR = True
    UNDER_MR_THR = 5  # VFE day-std=15, σ(Δ)=1.13. Start mid-range, sweep.

    # ----- Synthetic deep-ITM voucher MM (baseline_v5) -----
    SIGMA = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.005
    VS_MAX_POST_SIZE = 40
    VS_WIDE_SPREAD = 3

    # ---------- helpers ----------
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

    # ---------- HYDROGEL ----------
    def _trade_hydrogel(self, od, pos, last_dmid, dmid_hist):
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
            clip = self.H_CLIP + self.CLIP_VOL_K * std_d
        else:
            clip = self.H_CLIP

        fair_input = self._fair_input_h(book)
        fair_adj = max(-clip, min(clip, fair_input - self.H_ANCHOR))
        fair = self.H_ANCHOR + fair_adj
        if last_dmid is not None:
            fair -= self.AR1_BETA * last_dmid

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
        buy_cap = max(0, limit - working); sell_cap = max(0, limit + working)
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
        return orders, tm

    # ---------- Deep-ITM synthetic voucher MM ----------
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

    # ---------- Timo IV-residual: scalping + MR ----------
    def _trade_iv_residual(self, state: TradingState, pos, saved):
        out: Dict[str, List[Order]] = {}
        ods = state.order_depths

        # Underlying = VELVETFRUIT_EXTRACT
        u_od = ods.get("VELVETFRUIT_EXTRACT")
        if u_od is None:
            return out
        u_bw, u_wm, u_aw = self._walls(u_od)
        if u_wm is None:
            return out
        S = u_wm  # use wall_mid (Timo convention)
        T = self._tte_years(state.timestamp)
        if T <= 0:
            return out

        # Underlying EMA dev (window=30 per Timo)
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

        # warmup
        if state.timestamp // 100 < max(IV_SCALPING_WINDOW, OPT_MR_WINDOW):
            return out

        # ---- IV scalping: OTM strikes 5300/5400/5500 ----
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
                # flatten on calm regime
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

        # ---- MR: near-ATM strikes 5000/5100/5200/5300 ----
        for name, K in MR_STRIKES.items():
            if name not in cur_diff:
                continue
            bw, wm, aw = walls[name]
            iv_dev = cur_diff[name] - mean_diff[name]
            combined = ema_o_dev + 2.0 * iv_dev  # iv-weighted ablation
            p = pos.get(name, 0)
            limit = self.LIMITS[name]
            max_sell = limit + p
            max_buy = limit - p
            orders: List[Order] = out.setdefault(name, [])
            if combined > OPT_MR_THR and max_sell > 0:
                orders.append(Order(name, int(bw), -max_sell))
            elif combined < -OPT_MR_THR and max_buy > 0:
                orders.append(Order(name, int(aw), max_buy))

        # ---- Underlying MR (Timo: cross VFE spread on ema_o_dev) ----
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

    # ---------- main ----------
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

        # 1. HYDROGEL
        new_mid = None
        if "HYDROGEL_PACK" in state.order_depths:
            orders, tm = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0),
                last_dmid, dmid_hist,
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
            saved["last_mid_H"] = new_mid
            saved["dmid_hist_H"] = dmid_hist

        # 2. Deep-ITM synth MM (VEV_4000, VEV_4500)
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

        # 3. IV-residual sleeve (strikes 5000-5500)
        for prod, orders in self._trade_iv_residual(state, pos, saved).items():
            if prod in result:
                result[prod].extend(orders)
            else:
                result[prod] = orders

        return result, 0, json.dumps(saved, separators=(",", ":"))
