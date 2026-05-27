"""
Round 3 baseline v18 = v17 + VFE-momentum HYDROGEL regime overlay.

Sourced from parallel research (HYDROGEL_CROSS_REGIME_FINDINGS_2026_04_24.md):
on the live hidden day, HYDROGEL crash-state mean-reversion was conditional
on VELVETFRUIT_EXTRACT 20-tick momentum. VFE_mom20 <= -3.5 → fwd20 ≈ +5.58
hit 84.6% (good buy); VFE_mom20 >= 0 → fwd20 ≈ -2.5 hit 24-38% (don't buy).

In v18, when HYDROGEL is in crash state (touch_mid <= anchor - 18 AND
spread >= 14):
  - VFE_mom20 <= -3.5 (lean LONG): fair shifted +0.75; bid posts 2x, ask 0.25x.
  - VFE_mom20 >= +1.0 (suppress LONG): fair shifted -1.25; bid 0.25x, ask 1.25x.
  - Otherwise: no change.

Outside crash state, v18 is identical to v17.

----

Round 3 baseline v17 = v15 + cap-flattener + ATM tweaks.

EVAL MODEL: bundle-calibrated official replay
  python3 IMCP2026/tools/score_round3_candidates.py \\
    --bundle-dir /Users/sean_tsu_/Downloads/389872 \\
    IMCP2026/traders/round3/baseline_v17.py
  This is ~99% accurate to the live submission engine. `--match-trades all`
  inflates by ~3x; `--match-trades none` over-corrects.

Bundle 389872 calibrated scores (ranking same direction as live):
  baseline_v5  =  8,805
  baseline_v15 =  8,631
  baseline_v17 = 11,175  (+2,544 vs v15)

v17 = v15 with three changes:

  1. Cap-flattener (HYDROGEL): fires only when pos == ±limit AND
     |drift| >= H_CAP_DRIFT against pos. Dumps H_CAP_FLATTEN_QTY at touch
     bid/ask. Dormant on bundle 389872 (no trap day), zero in-sample cost.
     Defends against live-day-2-style trajectories where pos pins at +200
     while market drops sustained.

  2. ATM_RESIDUAL_ALPHA: 1/200 → 1/5000. Slower EMA holds the smile
     residual closer to a static mispricing estimate. Sweep peak at this
     value under bundle calibration.

  3. ATM_TAKE_EDGE: 0.5 → 0.0. Take whenever ask <= fair (no buffer);
     residual EMA already encodes the smile so the buffer was lost edge.

Sweep at peak (alpha=1/5000, edge=0.0): calibrated 11,175.
Sweep at v15 default (alpha=1/200, edge=0.5): calibrated 8,631.
Sweep at edge=0.5 across alphas: 9-10k — edge=0.0 is the dominant lever.

----

Round 3 baseline v15 — chase ATM-residual + lottery alpha.

Built on v13c. Adds two new sleeves:

(a) SMILE-CORRECTED MM on VEV_5200, 5300, 5400, 5500.
    Track per-strike residual EMA r_K = touch_mid - BS_theo. Use
    fair = BS_theo + r_K as the smile-corrected fair. The persistent-
    residual problem (lag-1 autocorr 0.71-0.99) becomes a self-
    calibrating advantage. Initialize r_K with first observation.

(b) LOTTERY BIDS on VEV_6000, VEV_6500.
    Mid stuck at 0.5, ~98 trades/day at price 0. Posting bid at 0
    captures aggressive sellers; cost basis 0, MTM follows mid.

HYDROGEL + V4000/V4500 sleeves unchanged from v13c.

----

Round 3 baseline v13 — 2026-04-24 (post-live diagnosis session).

v13 = v12 + drift-regime handler for HYDROGEL + position-trend skew
       + per-tick logger.

Live day-2 failure mode (submission 1a9a8223):
  HYDROGEL touch_mid drifted from ~10020 (t=70k) down to ~9920 (t=88k)
  back to ~9960 (t=100k). v12's CLIP=30 froze fair at 9960 once mid
  fell below it; algo kept seeing asks at 9921 as "below fair" take
  signals and accumulated long inventory while mid kept dropping.
  Realized PnL collapsed from +14k (peak) to -750 before bouncing.

Fix family: drift-regime is now an explicit branch.
  When abs(touch_mid - H_ANCHOR) > H_CLIP:
    - blend fair toward touch_mid (DRIFT_BLEND fraction); fair stops
      being stuck at the wall
    - boost inv_skew to H_INV_SKEW_DRIFT (~3x) to refuse adding
      inventory in the drift direction
    - block aggressive TAKE on the drift-adding side; REDUCE-EDGE
      paths (flatten existing inventory) still fire normally
    - suppress MAKE on the drift-adding side (no bid in falling
      market, no ask in rising market)

Position-trend skew (additive nudge): if signed inventory aligns
with the drift direction (e.g. long while market is falling), we
add a small extra skew penalty proportional to recent drift.

Logger: every tick, the trader prints a one-line JSON to lambdaLog
with HYDROGEL fair/drift/regime/pos and voucher fair/pos. This is
visible in submission logs for post-mortem.

Hypothesis: keeps in-sample PnL within ±1k of v12 (drift threshold
hit zero times in the 3 backtest days) AND defends against the
live drift seen on day 2. Toggle LOG=False before final shipping if
log volume is a concern.
"""
from typing import Dict, List, Optional, Tuple
from statistics import NormalDist
import json
import math

from datamodel import Order, OrderDepth, TradingState


_N = NormalDist()
DAYS_PER_YEAR = 365
TTE_DAYS_LIVE = 5.0


class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
        "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
        "VEV_6500": 300,
    }

    VOUCHER_STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500}

    # v15: smile-corrected ATM strikes
    # Pruned to dense-flow strikes only. V5200/V5300 had fewer trades and
    # wider spread; their EMA noise + adverse selection dragged net PnL.
    # V5200 has wider spread + thin flow; smile-EMA noise dragged it
    # negative even with zero skew. Pruned to dense-flow strikes.
    ATM_STRIKES = {"VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500}
    ATM_RESIDUAL_ALPHA = 1.0 / 5000    # v17 sweep: slow EMA captures stationary residual
    ATM_MAX_POST_SIZE = 20
    ATM_TAKE_EDGE = 0.0                # v17 sweep: take whenever ask <= fair
    ATM_PENNY_EDGE = 0.0
    ATM_INV_SKEW = 0.0
    ATM_WIDE_SPREAD = 1                # MM at any spread >= 1
    ATM_PER_STRIKE_LIMIT_RATIO = 0.85

    # v15: lottery on dead-OTM
    LOTTERY_STRIKES = {"VEV_6000": 6000, "VEV_6500": 6500}
    LOTTERY_BID_PRICE = 0
    LOTTERY_BID_SIZE = 30
    LOTTERY_ASK_PRICE = 1
    LOTTERY_ASK_SIZE = 30              # exit at any 1+ price

    # HYDROGEL — v13c: drift handler with risk-gated trigger
    H_ANCHOR = 9990.0
    H_CLIP = 30.0
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 1.0
    H_PENNY_EDGE = 1.5
    H_INV_SKEW = 0.015          # normal regime
    H_INV_SKEW_DRIFT = 0.045    # drift regime: 3x harder flatten
    H_DRIFT_BLEND = 0.6         # fair = clipped + DRIFT_BLEND * (raw - clipped)
    H_DRIFT_THRESHOLD = 50.0    # |drift| must exceed this for drift mode
    H_DRIFT_RISK = 2000.0       # |pos * drift| must also exceed this
    H_MAX_POST_SIZE = 20
    H_PASSIVE_OFFSET = 12.0
    H_WIDE_SPREAD = 8
    H_SHOCK_MOVE = 15.0
    # v17: cap-flattener supplement. Fires only at-limit with adverse drift.
    H_CAP_NEAR = 1.0
    H_CAP_DRIFT = 35.0
    H_CAP_FLATTEN_QTY = 30
    # v18: VFE-momentum regime overlay (only modifies HYDROGEL crash state)
    H_CRASH_TRIGGER = 18.0       # touch_mid <= anchor - 18 = 9972 to be "crash"
    H_CRASH_MIN_SPREAD = 14
    H_VFE_MOM_LOOKBACK = 20
    H_VFE_DOWN_THRESH = -3.5     # VFE has sold off → lean Hydro long
    H_VFE_UP_THRESH = 1.0        # VFE has rallied → suppress Hydro long
    H_VFE_GOOD_FAIR_SHIFT = 0.75
    H_VFE_BAD_FAIR_SHIFT = -1.25
    H_VFE_GOOD_BID_MULT = 2.0
    H_VFE_GOOD_ASK_MULT = 0.25
    H_VFE_BAD_BID_MULT = 0.25
    H_VFE_BAD_ASK_MULT = 1.25

    # Voucher (v12 unchanged)
    SIGMA = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.005
    VS_MAX_POST_SIZE = 100
    VS_WIDE_SPREAD = 3
    VS_POST_AT_TOUCH = True

    # Logger toggle. False keeps lambdaLog volume zero for shipping.
    LOG = True

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

    def _cap_size(self, max_size: int, pos: int, side: str, cap: int, limit: int) -> int:
        if cap <= 0:
            return 0
        ratio = 1.0 - min(0.7, abs(pos) / limit)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    @staticmethod
    def _opt_theo(S: float, K: int, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return max(0.0, S - K)
        sq = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sq
        d2 = d1 - sq
        return S * _N.cdf(d1) - K * _N.cdf(d2)

    @staticmethod
    def _tte_years(ts: int) -> float:
        tte_days = TTE_DAYS_LIVE - ts / 1e6
        if tte_days <= 0:
            return 0.0
        return tte_days / DAYS_PER_YEAR

    def _trade_hydrogel(self, od: OrderDepth, pos: int,
                        prev_mid: Optional[float],
                        vfe_mom20: Optional[float],
                        ) -> Tuple[List[Order], float, Dict]:
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], prev_mid if prev_mid is not None else 0.0, {}
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]; touch_mid = book["touch_mid"]

        shock = (prev_mid is not None
                 and abs(touch_mid - prev_mid) > self.H_SHOCK_MOVE)
        drift_raw = touch_mid - self.H_ANCHOR
        # v13c: BOTH (a) drift large AND (b) we're materially exposed
        # in the wrong direction. risk = pos * (-drift) > 0 when aligned-bad
        risk_aligned = pos * (-drift_raw)  # >0 when long-falling or short-rising
        drift_regime = (not shock) and abs(drift_raw) > self.H_DRIFT_THRESHOLD \
                                   and risk_aligned > self.H_DRIFT_RISK

        # Compute fair + skew per regime
        if shock:
            fair = touch_mid
            inv_skew = self.H_INV_SKEW
            regime = "shock"
        elif drift_regime:
            clipped = max(-self.H_CLIP, min(self.H_CLIP, drift_raw))
            fair = self.H_ANCHOR + clipped + self.H_DRIFT_BLEND * (drift_raw - clipped)
            inv_skew = self.H_INV_SKEW_DRIFT
            regime = "drift"
        else:
            # Normal regime: clip just like v12 (preserves in-sample alpha)
            clipped = max(-self.H_CLIP, min(self.H_CLIP, drift_raw))
            fair = self.H_ANCHOR + clipped
            inv_skew = self.H_INV_SKEW
            regime = "normal"

        # v18: VFE-momentum overlay in HYDROGEL crash state
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
                regime = "vfe_good"
            elif vfe_mom20 >= self.H_VFE_UP_THRESH:
                fair += self.H_VFE_BAD_FAIR_SHIFT
                bid_size_mult = self.H_VFE_BAD_BID_MULT
                ask_size_mult = self.H_VFE_BAD_ASK_MULT
                regime = "vfe_bad"

        trend_adj = 0.0  # disabled in v13c

        working = pos
        orders: List[Order] = []

        drift_dir = 0
        if drift_regime:
            drift_dir = 1 if drift_raw > 0 else -1

        # TAKE asks
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair + trend_adj - inv_skew * working
            block_aggressive_buy = (drift_dir == -1)  # falling market: don't buy
            if (not block_aggressive_buy) and ap <= skew - self.H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                # REDUCE: always allowed (closing existing short)
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q

        # TAKE bids
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair + trend_adj - inv_skew * working
            block_aggressive_sell = (drift_dir == 1)  # rising market: don't sell short
            if (not block_aggressive_sell) and bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                # REDUCE: always allowed (closing existing long)
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q

        # v17: cap-flattener — fires at-limit with sustained adverse drift.
        # Defends day-2-style trap where pos pinned at +200 while market drops.
        cap_long_bad = (working >= self.H_CAP_NEAR * limit) and (drift_raw <= -self.H_CAP_DRIFT)
        cap_short_bad = (working <= -self.H_CAP_NEAR * limit) and (drift_raw >= self.H_CAP_DRIFT)
        if cap_long_bad and not shock:
            qty_left = self.H_CAP_FLATTEN_QTY
            for bp, bv in book["buys"].items():
                if qty_left <= 0 or working <= 0:
                    break
                q = min(bv, qty_left, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q))
                    working -= q
                    qty_left -= q
            regime = "cap_flat_long"
        elif cap_short_bad and not shock:
            qty_left = self.H_CAP_FLATTEN_QTY
            for ap, av in book["sells"].items():
                if qty_left <= 0 or working >= 0:
                    break
                q = min(av, qty_left, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q))
                    working += q
                    qty_left -= q
            regime = "cap_flat_short"

        log_state = {
            "fair": round(fair, 1),
            "drift": round(drift_raw, 1),
            "regime": regime,
            "pos_in": pos,
            "pos_after_take": working,
        }

        if shock:
            return orders, touch_mid, log_state

        skew = fair + trend_adj - inv_skew * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.H_MAX_POST_SIZE, working, "buy",
                                  buy_cap, limit)
        ask_size = self._cap_size(self.H_MAX_POST_SIZE, working, "sell",
                                  sell_cap, limit)
        # v18: VFE-regime size multipliers (cap by buy/sell_cap)
        bid_size = min(buy_cap, int(round(bid_size * bid_size_mult)))
        ask_size = min(sell_cap, int(round(ask_size * ask_size_mult)))

        # Suppress make on drift-adding side
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
        return orders, touch_mid, log_state

    def _trade_deep_itm(self, name: str, K: int, od: OrderDepth,
                        pos: int, S: float, T: float
                        ) -> Tuple[List[Order], Dict]:
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return [], {}
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        fair = self._opt_theo(S, K, T, self.SIGMA)
        working = pos
        orders: List[Order] = []

        # TAKE asks
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

        # TAKE bids
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

        # MAKE
        skew = fair - self.VS_INV_SKEW * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.VS_MAX_POST_SIZE, working, "buy",
                                  buy_cap, limit)
        ask_size = self._cap_size(self.VS_MAX_POST_SIZE, working, "sell",
                                  sell_cap, limit)

        if spread >= self.VS_WIDE_SPREAD:
            if self.VS_POST_AT_TOUCH:
                bid_price = min(bb, math.floor(skew - self.VS_PENNY_EDGE))
                ask_price = max(ba, math.ceil(skew + self.VS_PENNY_EDGE))
            else:
                bid_price = min(bb + 1, math.floor(skew - self.VS_PENNY_EDGE))
                ask_price = max(ba - 1, math.ceil(skew + self.VS_PENNY_EDGE))
            bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
            ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)
            if bid_price < ask_price:
                if bid_size > 0:
                    orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0:
                    orders.append(Order(name, ask_price, -ask_size))
        return orders, {"fair": round(fair, 1), "pos_in": pos, "pos_after": working}

    def _trade_atm(self, name: str, K: int, od: OrderDepth, pos: int,
                   S: float, T: float, residual: Optional[float]
                   ) -> Tuple[List[Order], float, Dict]:
        """Smile-corrected MM on ATM/near-OTM strikes."""
        limit = self.LIMITS[name]
        per_strike_limit = int(limit * self.ATM_PER_STRIKE_LIMIT_RATIO)
        book = self._book(od)
        if not book:
            return [], residual if residual is not None else 0.0, {}
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        touch_mid = book["touch_mid"]

        bs_theo = self._opt_theo(S, K, T, self.SIGMA)
        instant_residual = touch_mid - bs_theo
        if residual is None:
            new_residual = instant_residual  # warmup-free init
        else:
            a = self.ATM_RESIDUAL_ALPHA
            new_residual = (1 - a) * residual + a * instant_residual

        fair = bs_theo + new_residual
        working = pos
        orders: List[Order] = []

        # TAKE asks
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

        # TAKE bids
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

        # MAKE
        if spread >= self.ATM_WIDE_SPREAD:
            skew = fair - self.ATM_INV_SKEW * working
            buy_cap = max(0, per_strike_limit - working)
            sell_cap = max(0, per_strike_limit + working)
            bid_size = self._cap_size(self.ATM_MAX_POST_SIZE, working,
                                      "buy", buy_cap, limit)
            ask_size = self._cap_size(self.ATM_MAX_POST_SIZE, working,
                                      "sell", sell_cap, limit)
            bid_price = min(bb, math.floor(skew - self.ATM_PENNY_EDGE))
            ask_price = max(ba, math.ceil(skew + self.ATM_PENNY_EDGE))
            bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
            ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)
            if bid_price < ask_price:
                if bid_size > 0:
                    orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0:
                    orders.append(Order(name, ask_price, -ask_size))

        return orders, new_residual, {
            "theo": round(bs_theo, 1),
            "resid": round(new_residual, 2),
            "fair": round(fair, 1),
            "pos_after": working,
        }

    def _trade_lottery(self, name: str, K: int, od: OrderDepth,
                       pos: int) -> Tuple[List[Order], Dict]:
        """Lottery-bid the dead-OTM strikes. Buy at 0; ask out at 1+."""
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return [], {}
        orders: List[Order] = []
        # Bid at 0 if room
        room_buy = limit - pos
        if room_buy > 0:
            orders.append(Order(name, self.LOTTERY_BID_PRICE,
                                min(self.LOTTERY_BID_SIZE, room_buy)))
        # Ask at 1+ if we have any inventory to dump
        if pos > 0:
            orders.append(Order(name, self.LOTTERY_ASK_PRICE,
                                -min(self.LOTTERY_ASK_SIZE, pos)))
        return orders, {"pos": pos, "bb": book["bb"], "ba": book["ba"]}

    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        pos = state.position
        log_payload = {"ts": state.timestamp}

        # v18: track VFE rolling history for momentum overlay
        vfe_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        vfe_book = self._book(vfe_od) if vfe_od is not None else None
        vfe_hist = saved.get("vfe_hist") or []
        vfe_mom20: Optional[float] = None
        if vfe_book is not None:
            vfe_hist = list(vfe_hist) + [vfe_book["touch_mid"]]
            if len(vfe_hist) > self.H_VFE_MOM_LOOKBACK + 1:
                vfe_hist = vfe_hist[-(self.H_VFE_MOM_LOOKBACK + 1):]
            if len(vfe_hist) >= self.H_VFE_MOM_LOOKBACK + 1:
                vfe_mom20 = vfe_hist[-1] - vfe_hist[0]
        saved["vfe_hist"] = vfe_hist

        if "HYDROGEL_PACK" in state.order_depths:
            prev_mid = saved.get("h_prev_mid")
            h_orders, new_mid, h_state = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0),
                prev_mid,
                vfe_mom20,
            )
            result["HYDROGEL_PACK"] = h_orders
            saved["h_prev_mid"] = new_mid
            log_payload["h"] = h_state

        if vfe_book is not None:
            u_book = vfe_book
            if u_book is not None:
                S = u_book["touch_mid"]
                T = self._tte_years(state.timestamp)
                log_payload["S"] = round(S, 1)
                for name, K in self.VOUCHER_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is not None:
                        orders, v_state = self._trade_deep_itm(
                            name, K, od, pos.get(name, 0), S, T,
                        )
                        result[name] = orders
                        log_payload[name] = v_state

                # ATM smile-corrected MM
                atm_residuals = saved.get("atm_residuals", {})
                for name, K in self.ATM_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is not None:
                        orders, new_r, atm_state = self._trade_atm(
                            name, K, od, pos.get(name, 0), S, T,
                            atm_residuals.get(name),
                        )
                        result[name] = orders
                        atm_residuals[name] = new_r
                        log_payload[name] = atm_state
                saved["atm_residuals"] = atm_residuals

        # Lottery on dead-OTM (independent of underlying book)
        for name, K in self.LOTTERY_STRIKES.items():
            od = state.order_depths.get(name)
            if od is not None:
                orders, lot_state = self._trade_lottery(
                    name, K, od, pos.get(name, 0),
                )
                result[name] = orders
                log_payload[name] = lot_state

        if self.LOG:
            print(json.dumps(log_payload))

        return result, 0, json.dumps(saved)
