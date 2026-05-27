"""
Round 3 — Timo-style clone v1.

Three sleeves:
  1. HYDROGEL_PACK   = exact h_only_v8 (171,890 standalone proven).
  2. VEV_4000/4500   = baseline_v5 synthetic-underlying MM (BS theo, sigma=0.23).
  3. VEV options sleeve = port of Timo's OptionTrader from
     FrankfurtHedgehogs_r3.py. IV scalping on the liquid strikes via
     EMA(theo_diff) residuals, and a separate underlying-MR signal on
     VELVETFRUIT_EXTRACT.

Adaptations vs Timo:
  - Flat smile: sigma = 0.23 (no quadratic fit needed; data is flat).
  - Lower IV-scalp threshold: residual std on this market is 0.3-0.5
    so Timo's THR_OPEN=0.5 with switch_mean=0.7 gate fires never;
    we drop the switch_mean gate and lower THR_OPEN to 0.5 only for
    K=5000-5300 where alpha is established.
  - OTM vouchers (5400+) have POSITIVE 1-lag autocorr (momentum) —
    do NOT trade them via mean-reversion.
  - Underlying MR threshold tuned to VFE std (~2.5 vs P3 VR ~50): THR=3.
"""
from typing import Dict, List
from statistics import NormalDist
import math
import json

from datamodel import Order, OrderDepth, TradingState


_N = NormalDist()
DAYS_PER_YEAR = 365
TTE_DAYS_LIVE = 5.0  # Round 3 starts at TTE = 5 days

# HYDROGEL params (h_only_v8)
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

# VEV_4000/4500 synth-MM (baseline_v5)
SIGMA = 0.23
VS_TAKE_EDGE = 0.0
VS_PENNY_EDGE = 1.0
VS_INV_SKEW = 0.005
VS_MAX_POST_SIZE = 40
VS_WIDE_SPREAD = 3

# IV scalp params (Timo with our threshold tuning)
IV_SCALP_STRIKES = (5000, 5100, 5200, 5300)
THEO_NORM_WINDOW = 20
SCALP_THR_OPEN = 0.5    # Timo's value; gives +0.30/tick alpha on K=5000
SCALP_THR_CLOSE = 0.0
LOW_VEGA_THR_ADJ = 0.5

# Underlying MR (VFE) — Timo-style
UNDER_MR_WINDOW = 30
UNDER_MR_THR = 3.0      # std of ema_o_dev = 2.5; THR=3 gives +0.12/tick alpha


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
    SCALP_VOUCHERS = {f"VEV_{k}": k for k in IV_SCALP_STRIKES}

    # ---------- book helpers ----------
    @staticmethod
    def _book(od: OrderDepth):
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

    @staticmethod
    def _cap_size(max_size, pos, side, cap, limit):
        if cap <= 0: return 0
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

    # ---------- HYDROGEL (h_only_v8) ----------
    def _fair_input_h(self, book):
        if book["spread"] < TYPICAL_SPREAD:
            tot = book["bv"] + book["av"]
            if tot > 0:
                return (book["ba"] * book["bv"] + book["bb"] * book["av"]) / tot
        return book["touch_mid"]

    def _trade_hydrogel(self, od, pos, last_dmid, dmid_hist):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]; tm = book["touch_mid"]

        if CLIP_VOL_K > 0 and len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mean_d = sum(dmid_hist) / n
            std_d = math.sqrt(sum((d - mean_d) ** 2 for d in dmid_hist) / n)
            clip = H_CLIP + CLIP_VOL_K * std_d
        else:
            clip = H_CLIP

        fair_input = self._fair_input_h(book)
        fair_adj = max(-clip, min(clip, fair_input - H_ANCHOR))
        fair = H_ANCHOR + fair_adj
        if last_dmid is not None:
            fair -= AR1_BETA * last_dmid

        working = pos
        orders: List[Order] = []
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0: break
            skew = fair - H_INV_SKEW * working
            if ap <= skew - H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0: orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + H_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0: orders.append(Order(prod, ap, q)); working += q
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0: break
            skew = fair - H_INV_SKEW * working
            if bp >= skew + H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - H_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q

        skew = fair - H_INV_SKEW * working
        buy_cap = max(0, limit - working); sell_cap = max(0, limit + working)
        bid_size = self._cap_size(H_MAX_POST_SIZE, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(H_MAX_POST_SIZE, working, "sell", sell_cap, limit)
        if spread >= H_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - H_PENNY_EDGE))
            ask_price = max(ba - 1, math.ceil(skew + H_PENNY_EDGE))
        else:
            bid_price = math.floor(skew - H_PASSIVE_OFFSET)
            ask_price = math.ceil(skew + H_PASSIVE_OFFSET)
        bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
        ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)
        if bid_price < ask_price:
            if bid_size > 0: orders.append(Order(prod, bid_price, bid_size))
            if ask_size > 0: orders.append(Order(prod, ask_price, -ask_size))
        return orders, tm

    # ---------- VEV_4000/4500 synth MM (baseline_v5) ----------
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
            if cap <= 0: break
            skew = fair - VS_INV_SKEW * working
            if ap <= skew - VS_TAKE_EDGE:
                q = min(av, cap)
                if q > 0: orders.append(Order(name, ap, q)); working += q
            elif working < 0 and ap <= skew:
                q = min(av, cap, abs(working))
                if q > 0: orders.append(Order(name, ap, q)); working += q
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0: break
            skew = fair - VS_INV_SKEW * working
            if bp >= skew + VS_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0: orders.append(Order(name, bp, -q)); working -= q
            elif working > 0 and bp >= skew:
                q = min(bv, cap, working)
                if q > 0: orders.append(Order(name, bp, -q)); working -= q
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
                if bid_size > 0: orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0: orders.append(Order(name, ask_price, -ask_size))
        return orders

    # ---------- IV scalp on K=5000-5300 (Timo-style take-side) ----------
    # Sell at best_bid when (cur_diff - mean_diff) - (touch_mid - best_bid) >= THR
    # Buy at best_ask when (cur_diff - mean_diff) + (best_ask - touch_mid) <= -THR
    def _trade_iv_scalp(self, name, K, od, pos, S, T, saved):
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]; tm = book["touch_mid"]
        theo, _, vega = self._opt_bs(S, K, T, SIGMA)
        diff = tm - theo
        mdiff = self._ema(saved, f"_iv_diff_{name}", THEO_NORM_WINDOW, diff)
        # Score the take side, accounting for cross-spread cost (Timo's exact formula).
        sell_score = diff - tm + bb - mdiff   # = bb - theo - mdiff
        buy_score  = diff - tm + ba - mdiff   # = ba - theo - mdiff
        low_vega_adj = LOW_VEGA_THR_ADJ if vega <= 1.0 else 0.0

        limit = self.LIMITS[name]
        max_sell = limit + pos
        max_buy = limit - pos
        orders: List[Order] = []
        # Open / scale sell side
        if sell_score >= SCALP_THR_OPEN + low_vega_adj and max_sell > 0:
            q = min(book["bv"], max_sell)
            if q > 0: orders.append(Order(name, int(bb), -q))
        # Close (no-edge) sell to flatten longs
        elif sell_score >= SCALP_THR_CLOSE and pos > 0:
            q = min(book["bv"], pos)
            if q > 0: orders.append(Order(name, int(bb), -q))
        # Open / scale buy side
        if buy_score <= -(SCALP_THR_OPEN + low_vega_adj) and max_buy > 0:
            q = min(book["av"], max_buy)
            if q > 0: orders.append(Order(name, int(ba), q))
        elif buy_score <= -SCALP_THR_CLOSE and pos < 0:
            q = min(book["av"], -pos)
            if q > 0: orders.append(Order(name, int(ba), q))
        return orders

    # ---------- VFE underlying MR ----------
    def _trade_vfe_mr(self, od, pos, saved):
        prod = "VELVETFRUIT_EXTRACT"
        book = self._book(od)
        if not book:
            return []
        S = book["touch_mid"]
        ema = self._ema(saved, "_vfe_ema_o", UNDER_MR_WINDOW, S)
        dev = S - ema
        limit = self.LIMITS[prod]
        max_sell = limit + pos
        max_buy = limit - pos
        orders: List[Order] = []
        # Take-side: use best_bid/best_ask. With THR=3 and avg spread=5,
        # we go through a 2.5-tick effective cost on take. Sized to bv/av.
        if dev > UNDER_MR_THR and max_sell > 0:
            q = min(book["bv"], max_sell)
            if q > 0: orders.append(Order(prod, int(book["bb"]), -q))
        elif dev < -UNDER_MR_THR and max_buy > 0:
            q = min(book["av"], max_buy)
            if q > 0: orders.append(Order(prod, int(book["ba"]), q))
        return orders

    # ---------- main ----------
    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try: saved = json.loads(state.traderData)
            except Exception: saved = {}

        last_mid_h = saved.get("last_mid_H")
        last_dmid_h = saved.get("last_dmid_H", 0.0)
        dmid_hist = saved.get("dmid_hist_H", [])

        result: Dict[str, List[Order]] = {}
        pos = state.position
        ods = state.order_depths

        # 1) HYDROGEL
        new_mid_h = None
        if "HYDROGEL_PACK" in ods:
            orders, new_mid_h = self._trade_hydrogel(
                ods["HYDROGEL_PACK"], pos.get("HYDROGEL_PACK", 0),
                last_dmid_h, dmid_hist,
            )
            if orders: result["HYDROGEL_PACK"] = orders
        if new_mid_h is not None:
            if last_mid_h is not None:
                d = new_mid_h - last_mid_h
                saved["last_dmid_H"] = d
                dmid_hist.append(d)
                if len(dmid_hist) > DMID_HISTORY:
                    dmid_hist = dmid_hist[-DMID_HISTORY:]
            else:
                saved["last_dmid_H"] = 0.0
            saved["last_mid_H"] = new_mid_h
            saved["dmid_hist_H"] = dmid_hist

        # 2) Underlying-dependent sleeves: read VFE mid first
        u_od = ods.get("VELVETFRUIT_EXTRACT")
        if u_od is not None:
            u_book = self._book(u_od)
            if u_book is not None:
                S = u_book["touch_mid"]
                T = self._tte_years(state.timestamp)

                # 2a) VEV_4000/4500 synth MM
                for name, K in self.SYNTH_STRIKES.items():
                    od = ods.get(name)
                    if od is not None:
                        os_ = self._trade_synth_voucher(
                            name, K, od, pos.get(name, 0), S, T,
                        )
                        if os_: result[name] = os_

                # 2b) IV scalp on K=5000-5300
                for name, K in self.SCALP_VOUCHERS.items():
                    od = ods.get(name)
                    if od is None: continue
                    os_ = self._trade_iv_scalp(
                        name, K, od, pos.get(name, 0), S, T, saved,
                    )
                    if os_: result[name] = os_

                # 2c) VFE underlying MR — DISABLED: alpha 0.12/tick is below
                # spread cost 2.5 ticks. Bled -60k/day in v1 test. Need
                # passive-quote approach (see v2) or skip entirely.
                pass

        return result, 0, json.dumps(saved, separators=(",", ":"))
