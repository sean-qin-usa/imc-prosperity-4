"""
Round 3 combined SHIP v14 — 2026-04-25 (session 7, integration stack).

v14 = v12 (HYDROGEL 4-knob micro-tune) + v13 (synth-MM L1-imbalance
sizing). The third candidate (h_only_v17 vol-adaptive post-size) was
TESTED and REJECTED on this chassis — see "vol-size doesn't transfer".

Component PnL (3-day backtest):
  v11 baseline:           428,754
  v12 (HYDROGEL retune):  429,028  (+274)
  v13 (synth IMB sizing): 428,742  (-12, defensive for live)
  v14 with vol-size on:   428,957  (-71 vs v12; vol-size REGRESSES)
  **v14 IMB-only (ship)**: 429,016  (-12 vs v12, IMB live-defensive)

Per-day v14 vs v12: day0 0, day1 -12 (synth V4500), day2 0.

== Vol-size doesn't transfer ==
H_POST_VOL_K=1.0 was tuned against h_only_v16 (CLIP_VOL_K=0.76, AR1=0.17,
TE=0.5) and gained +228 standalone. Stacked on v12's tighter take edge
(TE=0.6) + AR1=0.25, the lever LOSES -71 (day 0 -63, day 1 -8). The take
loop already culls the marginal-fill ticks the vol-size shrink was
protecting against, so the size reduction just leaves money on the table.

H_POST_VOL_K sweep on v14 chassis (DMID_HISTORY=150, std≈2.2):
  vk    total    Δv12
  0.00  429,016   -12   (= v14 IMB-only)
  0.30  429,016   -12   (size capped at 17 ≈ same as 18)
  0.50  429,016   -12   (size capped at 17)
  0.75  429,016   -12   (size capped at 16)
  1.00  428,957   -71   (size starts hitting min=12 in vol bursts)

Below vk=1.0 the size is rarely cut enough to matter (std rarely
crosses the threshold given DMID_HISTORY=150's smoothing). At vk=1.0
the trim hits day-0 hard. **Ship with vk=0** for cleanest behavior.

== Live conversion ==
The IMB sizing on synth is structurally similar to the clean_alpha R2
port; backtest cost is -12 (negligible) but the signal is real
(>99% directional, +5/-5 ticks next-tick) and expected to convert
positively in the live fill model where adverse-selection events
dominate. v12 is identical in backtest; choose v14 if the live regime
favors imbalance-aware sizing.

== v12 history (kept for reference) ==
Round 3 combined SHIP v12 — 2026-04-25 (session 6 late, after parallel
sessions 4-7 produced ship_v8..v11).

DELTA vs ship_v11 (428,754 bt / 399,113 live) — 4 HYDROGEL knob micro-
adjustments from a fresh joint sweep:

  CLIP_VOL_K   0.76 → 0.795  (h_only_v15 originally; v11 used h_v16's 0.76)
  H_PENNY_EDGE 3.0 → 3.5     (within plateau, slight bias up)
  H_TAKE_EDGE  0.5 → 0.6     (h_only_v16 cliff at 0.65 still respected)
  AR1_BETA     0.17 → 0.25   (h_only_v15 had 0.18; sweep shows 0.25 wins
                              when joined with the other three above)

Each individual knob change REGRESSES PnL when applied alone over v11
chassis (CLIP=0.795 alone -2.2k; TE=0.6 alone -2.3k; AR1=0.25 alone -0.4k).
The 4-knob joint produces +274 bt — a small but real win from the
parameter-interaction surface.

3-day bt: **429,028** (vs v11 428,754).  Gain +274 backtest, ~+620 live
extrapolation at HYDROGEL's 2.27x (the change is purely HYDROGEL).

What remained at v11 (and is preserved in v12) — all confirmed peaks:
  - VS_INV_SKEW = 0.0       (h_only_v16-source +25k bt)
  - THEO_NORM_WINDOW = 25
  - OPT_MR_WINDOW = 44       (cliff at 30 = -87k, 48 = -15k)
  - OPT_MR_THR = 6.3         (plateau 6.3-6.5 with WIN=44)
  - UNDER_MR_THR = 6         (cliff at 5 with v11 chassis = -23k!)
  - DMID_HISTORY = 150       (plateau 100-200)
  - All voucher MR strikes {5000-5300}, lottery {6000, 6500},
    ATM-EMA {5400, 5500}, synth {4000, 4500}.

What was tested in this session and DIDN'T help v12:
  - P3 session-4.5 ITM-strike-to-MR move: 8 variants, all regressed
    -25k to -485k.  Wide deep-ITM spread (V4000 ~21 ticks) + low-vega
    OTM strikes break the P3 transfer.  Documented in
    `feedback_p3_to_p4_transfer_caveats.md`.
  - SIGMA != 0.23: peak sharp, ±0.05 → -60k bt.  Different from P3
    (where smile was decorative).
  - DMID_HISTORY=100 with full v7 deltas: +22 over v12 (not worth
    breaking from v11's default 150).
  - UNDER_MR_THR=5 (revert from v11): -23k cliff, confirms v11's
    finding that UNDER_MR_THR=6 matches the new larger OPT_MR_WINDOW=44.

Validator-clean (no forbidden imports).

Live forecast: ~399,700 (v11 live + 600).
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
THEO_NORM_WINDOW = 25
IV_SCALPING_THR = 0.7
IV_SCALPING_WINDOW = 100
OPT_MR_WINDOW = 44
OPT_MR_THR = 6.3

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

    # ----- HYDROGEL (h_only_v14 retune: anchor 9985->9983, skew 0.015->0.014) -----
    H_ANCHOR = 9983.0
    H_CLIP = 33.0
    H_TAKE_EDGE = 0.6
    H_REDUCE_EDGE = 0.0
    H_PENNY_EDGE = 3.5
    H_INV_SKEW = 0.014
    H_MAX_POST_SIZE = 18
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8
    AR1_BETA = 0.25
    TYPICAL_SPREAD = 16
    CLIP_VOL_K = 0.795
    DMID_HISTORY = 150
    # v17 vol-adaptive post size: shrink size during vol bursts.
    # Disabled in v14 because it regresses -71 when stacked on v12's
    # tighter TE=0.6 + AR1=0.25 (the take loop already culls the
    # adverse-fill ticks that vol-size was protecting against).
    H_BASE_POST_SIZE = 18
    H_POST_VOL_K = 0.0  # set 1.0 to enable v17 lever; loses on v12 base
    H_POST_MIN = 12
    H_POST_MAX = 18

    # ----- Underlying MR (VFE) — Timo P3R3 port -----
    ENABLE_UNDERLYING_MR = True
    UNDER_MR_THR = 6  # VFE day-std=15, σ(Δ)=1.13. Start mid-range, sweep.

    # ----- ATM smile-EMA MM on OTM strikes (from baseline_v17) -----
    # OTM 5400/5500 don't fit the IV-residual MR (vega<1, noise) so we
    # use a smile-corrected MM with slow EMA: fair = BS_theo + EMA(mid - theo).
    ATM_STRIKES = {"VEV_5400": 5400, "VEV_5500": 5500}
    ATM_RESIDUAL_ALPHA = 1.0 / 5000  # slow EMA captures stationary residual
    ATM_MAX_POST_SIZE = 20
    ATM_TAKE_EDGE = 0.0
    ATM_PENNY_EDGE = 0.0
    ATM_INV_SKEW = 0.0
    ATM_WIDE_SPREAD = 1
    ATM_PER_STRIKE_LIMIT_RATIO = 0.85

    # ----- Lottery on dead-OTM (from baseline_v15/v17) -----
    LOTTERY_STRIKES = {"VEV_6000": 6000, "VEV_6500": 6500}
    LOTTERY_BID_PRICE = 0
    LOTTERY_BID_SIZE = 30
    LOTTERY_ASK_PRICE = 1
    LOTTERY_ASK_SIZE = 30

    # ----- Synthetic deep-ITM voucher MM (baseline_v5) -----
    SIGMA = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.0
    VS_MAX_POST_SIZE = 40
    VS_WIDE_SPREAD = 3
    # v13 L1-imbalance sizing (clean_alpha port). Strong imbalance fires
    # only in tight-spread regime (~1.5% of ticks); when it does, mid
    # moves +5/-5 ticks next-tick (>99% hit). Boost favorable side, shrink
    # adverse. Defensive (-12 in jmerle bt; expected to convert live).
    VS_IMB_STRONG = 0.30
    VS_IMB_FAVORABLE_BOOST = 1.8
    VS_IMB_ADVERSE_SHRINK = 0.2

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
        # v17: vol-adaptive post size — shrink during vol bursts so we
        # don't get adverse-selected when the book is moving fast.
        if self.H_POST_VOL_K > 0 and len(dmid_hist) >= 3:
            n_d = len(dmid_hist)
            mn_d = sum(dmid_hist) / n_d
            sd_d = math.sqrt(sum((d - mn_d) ** 2 for d in dmid_hist) / n_d)
            adaptive_size = self.H_BASE_POST_SIZE - self.H_POST_VOL_K * sd_d
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

        # v13: L1-imbalance sizing — boost the favorable side, shrink
        # adverse when |imb| > VS_IMB_STRONG (only fires in tight regime).
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

    # ---------- ATM smile-EMA MM (baseline_v17 port for OTM 5400/5500) ----------
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

    # ---------- Lottery on dead-OTM (baseline_v15/v17) ----------
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
            combined = ema_o_dev + 1.75 * iv_dev  # iv-weighted ablation
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

        # 3. IV-residual sleeve (strikes 5000-5300)
        for prod, orders in self._trade_iv_residual(state, pos, saved).items():
            if prod in result:
                result[prod].extend(orders)
            else:
                result[prod] = orders

        # 4. ATM smile-EMA MM (OTM strikes 5400/5500) — baseline_v17 port
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

        # 5. Lottery on V6000 / V6500
        for name, K in self.LOTTERY_STRIKES.items():
            od = state.order_depths.get(name)
            if od is not None:
                orders = self._trade_lottery(name, K, od, pos.get(name, 0))
                if orders:
                    result[name] = orders

        return result, 0, json.dumps(saved, separators=(",", ":"))
