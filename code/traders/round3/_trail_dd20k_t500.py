"""
Round 3 combined SHIP v30 — 2026-04-25 (session 10).

DELTA vs v28_warmup65 live ship (442,623 live, 519,679 bt): port the
4-tier vk_dn LONG side from h_only_v25 (the v25 NEW lever).  Adds a
super-extreme brake (vk_dn = 16.0) when pos > 165, on top of v28's
existing 2-tier (HIGH=12.0 at pos>120, LOW=2.7 otherwise).  Purely
additive — only fires at very-extreme long inventory where v28's
braking was insufficient.

3-day jmerle bt:                 +520,318 (154,592 / 179,498 / 186,229)
Bundle-cal (bundle 427141):      45,275.5 (IDENTICAL to v28 baseline)
cal_minus_official:              +2,626.9 (same as v28)

Day 2 captures the +520 gain — the day where extreme-long inventory
builds up most during persistent down-trends.  Days 0/1 unchanged
because the XTREME tier doesn't fire there.

Per-day vs v28_warmup65:
  Day 0:   154,592   154,592      0   (XTREME never triggers day 0)
  Day 1:   179,378   179,498   +120
  Day 2:   185,709   186,229   +520
  Total:   519,679   520,318   +639

Why this is upside-only:
- bundle-cal is IDENTICAL to v28 (45,275 / +2,626) → snapshot-level
  live conversion unchanged.  XTREME tier rare in 1k-tick window.
- bt gain is concentrated at pos > 165 episodes (rare in any single
  day; 0-1 events per hidden day).  Zero downside if not triggered.
- Lever is a BRAKE (slows accumulation), not a new position.  Worst
  case: it doesn't fire and live = v28_warmup65 = 442,623.

Variants TESTED and REJECTED (do NOT redo):
- THR=130 (h_only v25 lever):     -257 bt (v28 chassis prefers 120)
- LC=0.5 (softer linear cap):     -124 bt vs v30 base (+515 vs v28)
- post_vk port (HIGH=1.0 LOW=0.0 THR=160):
                                  +2,394 bt BUT -7,066 bundle-cal
                                  → forecast ~-70k live regression.
                                  Confirms feedback_h17_volsize_doesnt_stack.
- post_vk + LC=0.5 + XTREME ("full port"):
                                  +3,074 bt over v30 BUT -527 cal
                                  → live regression risk.

Source levers preserved from v28:
  H_POS_THR=120 (chassis sweep peak), H_VK_DN_HIGH=12.0,
  H_POST_VK_HIGH=2.0 / H_POST_VK_LOW=0.3 / H_POST_ABS_POS_THR=150
  (chassis-specific tuning; do NOT port h_only values).
  VFE_WARMUP_TICKS=65 (live-verified +15k over v27).

NEW levers from h_only_v25 (additive):
  H_VK_DN_XTREME = 16.0 (super-brake at pos > H_POS_THR_2)
  H_POS_THR_2 = 165

Live forecast: 442,623 (lower bound = v28 confirmed live)
              to ~443,500 (upper bound if XTREME fires twice in
              hidden day, ~5× snapshot multiplier).

Validator-clean (no forbidden imports).

----- v28_warmup65 history below -----

DELTA vs shipped v27 (516,679 bt, bundle 427141): single-knob change
VFE_WARMUP_TICKS 500 → 65.  Sharp peak at 65 (519,679 bt, +3,000),
plateau 50-75.  Below 50, sigma estimate too noisy and Citadel takes
spurious sides; above 100, Citadel misses the early-day reversal alpha.

LIVE-VERIFIED: 442,623 cumul / 44,356 snapshot (cal predicted 45,275).

----- v27 history below -----

DELTA vs v26 (511,088 bt) — port HYDROGEL chassis from h_only_v24_test:
magnitude-thresholded vk_dn LONG (HIGH=12.0 when pos>120, LOW=2.7 when
0<pos<=120) with asymmetric vol-adaptive CLIP (separate UP/DOWN scaling),
wider asym INV_SKEW LONG=-0.015 (was -0.004), and tighter take edge
TE=0.3 / wider penny PE=4.0 / softer AR1=0.20 / vol-adaptive post size
H_POST_VOL_K=1.0 with magnitude conditioning.

Drops the v15_hdrift price-driven drift-gate: re-stacking it (v28) lost
-18,458 bt because the position-driven vk_dn already does the
vol-burst-protection job; double-stacking over-brakes day 0.

Per-asset vs v26 (cap=8 hybrid kept):
  HYDROGEL_PACK         v27 188,720   v26 188,202   diff   +518
  VFE                   v27 110,162   v26 105,366   diff +4,796
  VEV strikes (4000-5500)  +275 (noise)
  Total                 v27 516,679   v26 511,088   diff +5,591

Sweeps on v27 chassis:
  cap (VFE_MAX_TAKE_PER_TICK):    5→510k, 7→515k, **8→516k**, 10→516k,
                                  12→515k, 15→514k.  Plateau 7-10.
  H_VK_DN_HIGH:                   10→515k, 11→516k, **12→516k**, 13→511k,
                                  14→511k.  Sharp peak at 12.
  H_POS_THR:                      110→502k!, **120→516k**, 130→515k, 140→515k.
                                  Sharp cliff below 120.
  H_TAKE_EDGE:                    0.2→481k!, **0.3→516k**, 0.4→515k,
                                  0.5→509k.  Sharp cliff at 0.2.

3-day backtest match-trades all:  +516,679 (154,804 / 177,874 / 184,001)
3-day backtest match-trades none: +370,768 (alpha floor, +15,870 vs v26)

The +15,870 alpha-floor jump confirms the new HYDROGEL chassis adds
real take-side / passive-make alpha that bots fill, not just
matching-engine wallpaper.  Stacks cleanly with the +71,744 alpha-floor
gain Citadel already delivered (v23 280k → v27 371k = +90,932 floor over v23).

Live precedent: v25 (497,324 bt) hit 525,560 live = **1.057x bt-to-live
conversion**.  At the same ratio: v27 expected live ≈ **546,000**
(+20.4k vs v25's actual live).

Cumulative session-8 stack:
  v15            (baseline ship):                    443,484 / live 417,605
  v15_hdrift     (drift-regime CLIP gate):           +1,964 → 445,448
  v22            (+VEV carry V5000-5300):            +1,594 → 447,042
  v23            (+asym INV_SKEW LONG/SHORT):        +4,289 → 451,331 / 280,836 floor
  v24            (Citadel VFE MR hybrid w/ Timo):   +57,439 → 508,770 / 352,580 floor
  v25            (Citadel-only, cap=15)              497,324 → **live 525,560**
  v26            (v24 + cap=8):                      +2,318 → 511,088 / 354,898 floor
  v27            (v26 + h_only_v24_test HYDROGEL):   +5,591 → 516,679 / 370,768 floor
  Total v15→v27: +73,195 bt; +89,932 alpha-floor over v23.

Same chassis from v26:
  - Asymmetric H_INV_SKEW (LONG=-0.015, SHORT=+0.014)
  - VEV drift carry V5000-5300 target=300 (+1,594)
  - V4000/V4500 synth MM + IMB sizing
  - ATM smile-EMA on V5400/V5500 + lottery V6000/V6500
  - Voucher MR retune (THEO_NORM=25, OPT_MR_WINDOW=44, OPT_MR_THR=6.3)
  - Citadel z-score VFE MR (+ Timo UNDER_MR fallback before warmup)
  - VFE_MAX_TAKE_PER_TICK = 8

NEW in v27 (HYDROGEL chassis):
  - Asymmetric vol-adaptive CLIP (H_VK_UP=0.78 / H_VK_DN_*)
  - Magnitude-thresholded LONG-side vk_dn (HIGH=12.0, LOW=2.7, THR=120)
  - H_POST_VK_HIGH=2.0 / H_POST_VK_LOW=0.3 / H_POST_ABS_POS_THR=150
  - Tighter TE=0.3, wider PE=4.0, softer AR1=0.20

REMOVED in v27 (didn't survive on new chassis):
  - v15_hdrift drift-regime CLIP gate (v28 test: -18,458 bt regression)

Validator-clean (no forbidden imports).
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

    # ----- HYDROGEL (port from h_only_v24_test: magnitude-thresholded vk_dn LONG) -----
    H_ANCHOR = 9983.0
    H_CLIP = 33.0
    H_TAKE_EDGE = 0.3       # h_only_v24_test (was 0.6 in v23/v26)
    H_REDUCE_EDGE = 0.0
    H_PENNY_EDGE = 4.0      # h_only_v24_test (was 3.5 in v23/v26)
    H_INV_SKEW = 0.014      # used only when working == 0
    H_INV_SKEW_LONG = -0.015   # h_only_v24_test (was -0.004 in v23/v26)
    H_INV_SKEW_SHORT = 0.014
    H_MAX_POST_SIZE = 18
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8
    AR1_BETA = 0.20         # h_only_v24_test (was 0.25 in v23/v26)
    TYPICAL_SPREAD = 16
    CLIP_VOL_K = 0.78       # legacy ref; v21+ splits into VK_UP / VK_DN
    DMID_HISTORY = 150

    # v21: ASYMMETRIC vol-adaptive CLIP — vk_up scales upper, vk_dn scales lower
    H_VK_UP = 0.78
    H_VK_DN = 0.87          # legacy: used when pos == 0
    H_VK_DN_LONG = 2.7      # legacy: v23 splits LONG side by magnitude
    H_VK_DN_SHORT = 0.85
    # v23: magnitude-thresholded LONG-side vk_dn — extreme brake at high pos
    # v25 4-tier port (h_only_v25): super-extreme XTREME tier at pos > THR_2.
    H_VK_DN_HIGH = 12.0     # when H_POS_THR < pos <= H_POS_THR_2
    H_VK_DN_LOW = 2.7       # when 0 < pos <= H_POS_THR
    H_POS_THR = 120         # v28 chassis sweep: 120 > 130 > 110-cliff
    H_VK_DN_XTREME = 16.0   # v25 NEW: when pos > H_POS_THR_2 (super-brake)
    H_POS_THR_2 = 165

    # v17 vol-adaptive post size — magnitude-conditioned via H_POST_VK_*
    H_BASE_POST_SIZE = 18
    H_POST_VOL_K = 1.0      # h_only_v24_test (was 0.0 in v23/v26)
    H_POST_VK_HIGH = 2.0    # when |pos| > H_POST_ABS_POS_THR
    H_POST_VK_LOW = 0.3     # when |pos| <= H_POST_ABS_POS_THR
    H_POST_ABS_POS_THR = 150
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
    VFE_WARMUP_TICKS = 65
    VFE_Z_ENTER = 2.0
    VFE_MAX_TAKE_PER_TICK = 8


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

        # v23 chassis: ASYMMETRIC vol-adaptive CLIP — separate UP/DOWN scaling.
        # CLIP_DOWN > CLIP_UP lets fair drift further below anchor in vol bursts,
        # which keeps the strategy from over-buying during persistent down-moves.
        # Magnitude-thresholded vk_dn LONG: extreme brake (12.0) when pos > 120,
        # mild (2.7) at moderate longs, regular (0.85) when short.
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
        # v17 + magnitude-conditioned: vol-adaptive post size shrinks more
        # aggressively at extreme positions (|pos| > H_POST_ABS_POS_THR).
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
    # Trailing-stop reset: track peak mark-to-mid PnL since position open;
    # if current PnL falls VFE_TRAIL_DRAWDOWN below peak AND position has been
    # open at least VFE_TRAIL_MIN_TICKS, force-flat + reset Citadel state.
    # Winning positions ride; only round-trip losses trip the gate.
    VFE_TRAIL_DRAWDOWN = 20000.0
    VFE_TRAIL_MIN_TICKS = 500
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
        entry_mid = saved.get("vfe_entry_mid")
        entry_tick = int(saved.get("vfe_entry_tick", 0))
        peak_pnl = float(saved.get("vfe_peak_pnl", 0.0))
        total_ticks = int(saved.get("vfe_total_ticks", 0)) + 1

        # Maintain entry anchor + peak PnL: clear when flat, set on first non-flat
        if cur_pos == 0:
            entry_mid = None
            peak_pnl = 0.0
        elif entry_mid is None:
            entry_mid = mid
            entry_tick = total_ticks
            peak_pnl = 0.0
        else:
            cur_pnl = cur_pos * (mid - entry_mid)
            if cur_pnl > peak_pnl:
                peak_pnl = cur_pnl

        # Trailing-stop reset: only fires when peak PnL drawdown exceeds threshold
        gated_reset_now = False
        if (
            entry_mid is not None
            and (total_ticks - entry_tick) >= self.VFE_TRAIL_MIN_TICKS
        ):
            cur_pnl = cur_pos * (mid - entry_mid)
            if peak_pnl - cur_pnl >= self.VFE_TRAIL_DRAWDOWN:
                gated_reset_now = True
                entry_mid = None
                peak_pnl = 0.0
                ema = None
                sigma_var = 0.0
                ticks = 0
                side = 0

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
        saved["vfe_entry_mid"] = entry_mid
        saved["vfe_entry_tick"] = entry_tick
        saved["vfe_peak_pnl"] = peak_pnl
        saved["vfe_total_ticks"] = total_ticks

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