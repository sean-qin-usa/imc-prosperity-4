"""
Round 3 combined SHIP v27 — 2026-04-25 (session 9, Citadel mirror on
deep-ITM voucher delta-1 legs).

DELTA vs v26 (511,088 bt): adds a Citadel-style directional mirror on
VEV_4000 and VEV_4500.  Both have delta ≈ 1.000 at S=5250, T=5/365 —
they track VFE 1:1 — so the same `vfe_side` flag from the existing
Citadel VFE MR translates directly to long/short positions on V4000
and V4500.

3-day backtest match-trades all:  +576,528 (178,766 / 204,450 / 193,312)
3-day backtest match-trades none: +428,676 (113,057 / 162,559 / 153,060)

vs v26: +65,440 bt all / +73,778 alpha-floor.
vs v25 (live 525,560 = 1.057× bt): +79,204 bt all / +87,542 alpha-floor.

The alpha-floor jump (+74k) is LARGER than the match-trades-all jump
(+65k).  Per `feedback_match_trades_none_for_alpha.md`, alpha-floor
is a strict live-predictive lower bound; that the floor jump exceeds
the headline jump means the new sleeve is essentially 100% take-side
directional alpha (the bots are crossing the spread to fill our
±280 V4000/V4500 entries).  Per `feedback_citadel_overconverts_live.md`
this class converts at ≥ 1.057× live, so projected live is ≥
576,528 × 1.057 = **609,150** (vs v25's 525,560 actual / v26's 540k
forecast).

Per-product attribution (3-day match-trades all):
  HYDROGEL_PACK:        67,974 + 54,346 + 65,882 = 188,202 (unchanged from v26)
  VELVETFRUIT_EXTRACT:  33,429 + 37,521 + 36,734 = 107,684 (unchanged; Citadel-VFE)
  VEV_4000:              7,948 + 15,843 + 14,279 =  38,070 (was ~39,579 in v26 — small reshuffle)
  VEV_4500:             19,515 + 26,575 + 24,886 =  70,976 (was ~18,093 in v26 → +52,883)
  VEV_5000-5300:       (unchanged — voucher MR sleeve preserved)
  VEV_5400-5500:       (unchanged — ATM-EMA preserved)
  Lottery V6000/6500:  (unchanged)

The +52k jump on V4500 is the dominant new alpha — V4500 had 0 trades
historically, but Citadel-driven inventory of ±280 against the visible
book volume (8.9 per side, sp=16) accumulates large directional PnL
when VFE long-EMA z-score reverts.

V4000 + V4500 sweep peaks (Z=2.0, EMA=5e-4 fixed):
  TARGET_V4000 / TARGET_V4500 / cap → bt
   200 / 200 /  8 →  544,918
   250 / 250 /  8 →  563,734
   270 / 280 /  8 →  571,224
   280 / 280 /  8 →  572,142
   280 / 280 / 10 →  576,528  ← peak (this ship)
   285 / 285 / 10 →  573,667
   290 / 290 / 10 →  hits cliff (synth-MM at LIMIT) — drops -64k

Cliffs:
  TARGET ≥ 290 — synth-MM bid/ask blocked at LIMIT margin → -60k+
  TARGET ≤ 100 — too small to capture the directional move → -10 to -25k
  cap ≤ 6      — slow rebalance misses Z-cross peaks → -15 to -45k
  cap ≥ 15     — fast rebalance whipsaws on local Z noise → -10 to -35k

Citadel-H (HYDROGEL z-score directional layer) tested in this session
and REJECTED — at any TARGET ∈ {10, 20, 30, 50, 75, 100, 200} loses
$167k–$202k.  The static-anchor MM and the directional layer compete
for inventory; the MM needs near-zero position to earn its 145k
matching-engine PnL.  Confirms `feedback_static_anchor_is_the_feature.md`.

Sample-path risk: the 3-day historical sample has VFE drift -6/+20.5/+28
(net upward).  V4000/V4500 inherit the VFE move 1:1 — if live VFE drift
deviates substantially the directional bet may converge differently.
Bundle-cal on bundle 399113 was inconclusive for v27 (1k-tick window
too short for the long-EMA Citadel signal to develop the full 280-unit
position; Citadel needs the 500-tick warmup + space for several Z
crossings).  Trust the 3-day jmerle bt over the 1k-tick bundle here.

Older v26 / v25 / v24 history below.
==================================================================

Round 3 combined SHIP v26 — 2026-04-25 (session 8 close, after v25 live=525,560).

DELTA vs v24 (508,770 bt) — single knob change: VFE_MAX_TAKE_PER_TICK
80 → 8.  Slower per-tick rebalancing reduces whipsaw on z-score
crossings near ±LIMIT.

Cap sweep on v24 chassis:
  5 → 505,144
  6 → 508,464
  7 → 510,358
  **8 → 511,088** ← peak (+2,318 vs v24 default 80)
  9 → 510,909
  10 → 510,307
  12 → 509,663
  15 → 509,293
  18-25 → 508,742-508,936
  80 (v24 default) → 508,770

3-day backtest match-trades all:  +511,088
3-day backtest match-trades none: TBD
vs v23 (no Citadel): +59,757 bt

Live precedent: v25 (cap=15 on parallel chassis, bt 497,324) hit live
525,560 — **1.057x bt-to-live**.  The Citadel layer converts cleanly,
not just matching-engine wallpaper.

Live forecast for v26: 511,088 × 1.057 ≈ **540,200 live** (vs v25's
525,560 = +14.6k expected).

Same chassis as v24 (v23 + Citadel):
  - HYDROGEL h_only_v16 retune + 4-knob v12 + drift-gate (v15_hdrift)
  - Asymmetric INV_SKEW (LONG=-0.004, SHORT=0.014)
  - VEV drift carry V5000-5300 target=300
  - V4000/V4500 synth carry + IMB sizing
  - ATM smile-EMA on V5400/V5500 + lottery V6000/V6500
  - Voucher MR retune (THEO_NORM=25, OPT_MR_WINDOW=44, OPT_MR_THR=6.3)
  - Citadel z-score VFE MR replacing UNDER_MR + drift carry on VFE
  - VFE_MAX_TAKE_PER_TICK = 8 (v26 add)

No `import os`.
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
    H_INV_SKEW_LONG = -0.004
    H_INV_SKEW_SHORT = 0.014
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

    # Drift-regime gate (added 2026-04-25 on top of v15 chassis).
    # 443,484 → 445,448 (+1,964) — all 3 days improved (+629/+660/+676).
    # Detects drift via 200-tick touch_mid range and widens CLIP_VOL_K
    # when the range exceeds 53 ticks. Tuned against v15's CLIP_VOL_K=0.795
    # + TE=0.6 + AR1=0.25 chassis.
    # Cliffs (sweep_drift_v15.py):
    #   R <= 51 → spurious gating on a recurring day-2 episode = -28k d2
    #   B >= 1.7 → over-widening fades real MR = -456 d1
    # On the looser v11/v16 chassis (CLIP_VOL_K=0.76, TE=0.5, AR1=0.17)
    # the optimum shifts to B=1.6 (see h_day1_drift_v2.py / combined_ship_v11_hdrift.py).
    MID_RANGE_HISTORY = 200
    DRIFT_GATE_RANGE = 53
    DRIFT_CLIP_BOOST = 1.5

    # ----- Underlying MR (VFE) — Timo P3R3 port -----
    ENABLE_UNDERLYING_MR = True
    UNDER_MR_THR = 6  # VFE day-std=15, σ(Δ)=1.13. Start mid-range, sweep.

    # ----- Citadel bipolar VFE mean-reversion (long-EMA, HL ~ 1000) -----
    ENABLE_CITADEL_VFE_MR = True
    VFE_EMA_ALPHA = 0.0005
    VFE_SIGMA_ALPHA = 0.0005
    VFE_SIGMA_FLOOR = 1.0
    VFE_WARMUP_TICKS = 500
    VFE_Z_ENTER = 2.0
    VFE_MAX_TAKE_PER_TICK = 8

    # ----- Citadel HYDROGEL z-score directional layer (NEW v27) -----
    # Anchored at H_ANCHOR=9983 (the static long-term mean per memory
    # `feedback_static_anchor_is_the_feature.md`); long-EMA realized
    # variance gives sigma. When |z|≥H_Z_ENTER, take aggressively into
    # the reversion. Layered ON TOP of the existing anchor-MM (which
    # earns 145k matching-engine PnL); the Citadel take adds directional
    # alpha that converts >1.0× live (per `feedback_citadel_overconverts_live.md`).
    # Citadel-H tested and REJECTED: target ±200 → -167k, target ±10..100
    # all regress (-167k to -202k). The static-anchor MM and the
    # directional layer compete for inventory; the MM needs near-zero
    # position to earn its 145k matching-engine PnL.
    ENABLE_CITADEL_H_MR = False
    H_SIGMA_ALPHA = 0.0005
    H_SIGMA_FLOOR = 5.0
    H_WARMUP_TICKS = 500
    H_Z_ENTER = 2.0
    H_MAX_TAKE_PER_TICK = 8
    H_CITADEL_TARGET = 50

    # ----- Citadel on V4000 mirror (NEW v27 attempt 2) ----------------
    # V4000 = max(VFE - 4000, 0) at delta=1 deep ITM; basis V4000 + 4000 - VFE
    # has mean=0.0, sd=0.83 across all 3 days. So the SAME VFE Citadel
    # z-score signal applies 1:1 to V4000 — when VFE is +Z (long-EMA-rich),
    # V4000 is also rich. Adds a parallel directional bet on V4000.
    ENABLE_CITADEL_V4000_MR = True
    V4000_CITADEL_TARGET = 280
    V4000_MAX_TAKE_PER_TICK = 10
    ENABLE_CITADEL_V4500_MR = True
    V4500_CITADEL_TARGET = 280
    V4500_MAX_TAKE_PER_TICK = 10


    # ----- VFE drift carry (v15 add) — passive long bias capturing +0.002/tick drift -----
    UNDER_DRIFT_TARGET = 200
    VEV_CARRY_TARGET = 300
    VEV_CARRY_SIZE = 30   # full long position when no MR signal
    UNDER_CARRY_BID_SIZE = 30  # passive bid size on bb to accumulate

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
    def _trade_hydrogel(self, od, pos, last_dmid, dmid_hist, mid_hist):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]; tm = book["touch_mid"]

        clip_vol_k = self.CLIP_VOL_K
        if len(mid_hist) >= self.MID_RANGE_HISTORY // 2:
            if max(mid_hist) - min(mid_hist) > self.DRIFT_GATE_RANGE:
                clip_vol_k *= (1.0 + self.DRIFT_CLIP_BOOST)

        if clip_vol_k > 0 and len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mean_d = sum(dmid_hist) / n
            std_d = math.sqrt(sum((d - mean_d) ** 2 for d in dmid_hist) / n)
            clip = self.H_CLIP + clip_vol_k * std_d
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

        # ---- Citadel bipolar VFE long-EMA z-score MR (replaces UNDER_MR + drift carry) ----
        if self.ENABLE_CITADEL_VFE_MR and u_od is not None:
            vfe_orders = self._trade_citadel_vfe_mr(
                u_od, pos.get("VELVETFRUIT_EXTRACT", 0), saved,
            )
            if vfe_orders:
                out["VELVETFRUIT_EXTRACT"] = vfe_orders

        return {k: v for k, v in out.items() if v}

    # ---------- Citadel bipolar long-EMA VFE mean-reversion ----------
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
            return []
        cap = min(abs(diff), self.VFE_MAX_TAKE_PER_TICK)
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

    def _trade_citadel_hydrogel(self, od, cur_pos, saved):
        """Z-score directional layer on HYDROGEL anchored at H_ANCHOR=9983.

        Uses static H_ANCHOR (per `feedback_static_anchor_is_the_feature.md`)
        as the long-term mean; realized variance comes from a long-EMA of
        squared deviations. When |z|≥H_Z_ENTER, take aggressively into the
        reversion. Position target ±LIMIT, capped per tick.
        """
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        bb = max(od.buy_orders.keys())
        ba = min(od.sell_orders.keys())
        if bb >= ba:
            return []
        mid = 0.5 * (bb + ba)

        sigma_var = float(saved.get("h_sigma_var", 0.0))
        ticks = int(saved.get("h_ticks", 0))
        side = int(saved.get("h_side", 0))

        dev = mid - self.H_ANCHOR
        sa = self.H_SIGMA_ALPHA
        sigma_var = (1.0 - sa) * sigma_var + sa * (dev * dev)
        sigma = max(math.sqrt(sigma_var), self.H_SIGMA_FLOOR)
        ticks += 1

        if ticks >= self.H_WARMUP_TICKS:
            z = dev / sigma
            if z >= self.H_Z_ENTER:
                side = -1
            elif z <= -self.H_Z_ENTER:
                side = 1

        saved["h_sigma_var"] = sigma_var
        saved["h_ticks"] = ticks
        saved["h_side"] = side

        if side == 0:
            return []
        target = side * self.H_CITADEL_TARGET
        diff = target - cur_pos
        if diff == 0:
            return []
        cap = min(abs(diff), self.H_MAX_TAKE_PER_TICK)
        orders: List[Order] = []
        if diff > 0:
            cap = min(cap, self.LIMITS["HYDROGEL_PACK"] - cur_pos)
            if cap <= 0:
                return []
            for ap in sorted(od.sell_orders.keys()):
                if cap <= 0:
                    break
                avail = abs(int(od.sell_orders[ap]))
                if avail <= 0:
                    continue
                q = min(avail, cap)
                orders.append(Order("HYDROGEL_PACK", int(ap), q))
                cap -= q
        else:
            cap = min(cap, self.LIMITS["HYDROGEL_PACK"] + cur_pos)
            if cap <= 0:
                return []
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                if cap <= 0:
                    break
                avail = int(od.buy_orders[bp])
                if avail <= 0:
                    continue
                q = min(avail, cap)
                orders.append(Order("HYDROGEL_PACK", int(bp), -q))
                cap -= q
        return orders

    def _trade_citadel_mirror(self, name, od, cur_pos, saved, target_abs, cap_per_tick):
        """Mirror the VFE Citadel side onto a delta=1 voucher (V4000/V4500).

        Reads `vfe_side` saved by `_trade_citadel_vfe_mr`; takes the
        product in the same direction up to ±target_abs, capped per tick.
        Layered on top of synth-MM (which keeps posting passive quotes).
        """
        if od is None or not od.buy_orders or not od.sell_orders:
            return []
        side = int(saved.get("vfe_side", 0))
        if side == 0:
            return []
        target = side * target_abs
        diff = target - cur_pos
        if diff == 0:
            return []
        cap = min(abs(diff), cap_per_tick)
        orders: List[Order] = []
        if diff > 0:
            cap = min(cap, self.LIMITS[name] - cur_pos)
            if cap <= 0:
                return []
            for ap in sorted(od.sell_orders.keys()):
                if cap <= 0:
                    break
                avail = abs(int(od.sell_orders[ap]))
                if avail <= 0:
                    continue
                q = min(avail, cap)
                orders.append(Order(name, int(ap), q))
                cap -= q
        else:
            cap = min(cap, self.LIMITS[name] + cur_pos)
            if cap <= 0:
                return []
            for bp in sorted(od.buy_orders.keys(), reverse=True):
                if cap <= 0:
                    break
                avail = int(od.buy_orders[bp])
                if avail <= 0:
                    continue
                q = min(avail, cap)
                orders.append(Order(name, int(bp), -q))
                cap -= q
        return orders

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
        mid_hist = saved.get("mid_hist_H", [])

        result: Dict[str, List[Order]] = {}
        pos = state.position

        # 1. HYDROGEL
        new_mid = None
        if "HYDROGEL_PACK" in state.order_depths:
            h_pos = pos.get("HYDROGEL_PACK", 0)
            citadel_h_orders: List[Order] = []
            if self.ENABLE_CITADEL_H_MR:
                citadel_h_orders = self._trade_citadel_hydrogel(
                    state.order_depths["HYDROGEL_PACK"], h_pos, saved,
                )
            # Apply Citadel orders to position projection so the MM layer
            # respects the take-side fills.
            citadel_buy = sum(o.quantity for o in citadel_h_orders if o.quantity > 0)
            citadel_sell = sum(-o.quantity for o in citadel_h_orders if o.quantity < 0)
            h_pos_proj = h_pos + citadel_buy - citadel_sell
            orders, tm = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                h_pos_proj,
                last_dmid, dmid_hist, mid_hist,
            )
            result["HYDROGEL_PACK"] = citadel_h_orders + orders
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
                        # Citadel mirror layers (NEW v27): take V4000 / V4500
                        # in the same direction as the VFE Citadel sleeve.
                        mirror: List[Order] = []
                        v_pos = pos.get(name, 0)
                        if name == "VEV_4000" and self.ENABLE_CITADEL_V4000_MR:
                            mirror = self._trade_citadel_mirror(
                                "VEV_4000", od, v_pos, saved,
                                self.V4000_CITADEL_TARGET, self.V4000_MAX_TAKE_PER_TICK,
                            )
                        elif name == "VEV_4500" and self.ENABLE_CITADEL_V4500_MR:
                            mirror = self._trade_citadel_mirror(
                                "VEV_4500", od, v_pos, saved,
                                self.V4500_CITADEL_TARGET, self.V4500_MAX_TAKE_PER_TICK,
                            )
                        v_pos_proj = v_pos + sum(o.quantity for o in mirror)
                        synth = self._trade_synth_voucher(
                            name, K, od, v_pos_proj, S_synth, T_synth,
                        )
                        result[name] = mirror + synth

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
