"""
HYDROGEL-only v16 — second round of retunes on top of v15 (2026-04-25).

Four-knob change vs v15:
  H_TAKE_EDGE     0.0   → 0.5   (+1.4k joint)  ← biggest new lever
  DMID_HISTORY    50    → 150   (+0.4k joint)
  AR1_BETA        0.18  → 0.17  (+small)
  CLIP_VOL_K      0.75  → 0.76  (+0.07k, just on the plateau peak)

Local 3-day total: 181,675  (+1,442 vs v15 180,233; +9,785 vs v8 171,890;
+5.7%). Per-day: [63,544 / 53,884 / 64,247]
  day 0: +1,753 vs v8     day 1: +1,419 vs v8     day 2: +6,613 vs v8

Why TAKE_EDGE=0.5 helps:
  v15 took asks at any ap <= skew (TE=0). Marginal trades — where the
  fair barely beat the ask — paid the half-spread for too little edge.
  Requiring a 0.5-tick cushion cuts the marginal noise trades and
  preserves edge for the high-conviction crosses. Plateau is narrow
  (TE=0.5 best, TE=0.6 = -2.3k cliff on day 2). REDUCE_EDGE must stay
  at 0; with TE=0.5 the reduce branch is now live and any RE>0 lets
  the "close-at-loss" path leak (sweep verified).

Why DMID_HISTORY=150 helps:
  Smoother std → CLIP scales more steadily; less reactive to single-
  spike Δmid. Plateau 100-300; below 100 small loss; above 300 no
  marginal gain.

------ v15 history below ------

HYDROGEL-only v15 — multi-knob retune (2026-04-25).

Five-knob change vs v8 (180,233 = +8,343 vs 171,890, +4.85%):
  H_ANCHOR        9985  → 9983   (+2.8k single-knob)
  H_INV_SKEW      0.015 → 0.014  (+1.5k single-knob)
  CLIP_VOL_K      0.3   → 0.75   (+~5k joint)   ← biggest lever
  DMID_HISTORY    20    → 50     (+~0.5k joint, smoother std)
  H_PENNY_EDGE    2.0   → 3.0    (+~0.2k joint, also avoids the
                                   pe=2.0 cliff at large dh)

Per-day: [62,764 / 53,407 / 63,621]
  day 0:  +973 vs v8     day 1:  +942 vs v8     day 2:  +5,987 vs v8

Day 2 is the data the hidden submission was sampled from (the first
100k of 1M ticks), so the day-2 boost should carry over.

Why CLIP_VOL_K=0.75 wins (vs 0.3 in v8):
  CLIP = 33 + 0.75 * std(last 50 Δmid)
  In v8 (vk=0.3, dh=20) the volatility-adaptive CLIP barely opened up
  during fast moves; the strategy got pinned. With vk=0.75 + dh=50,
  CLIP lifts further and the EMA over 50 Δmid samples is much steadier,
  so the fair tracks touch_mid more loosely during volatile bursts and
  we don't get whipsawed.

Cliffs to know about (sweep-verified):
  CLIP_VOL_K ≥ 0.8         → day 2 craters to 35k (-30k)
  H_PENNY_EDGE = 2 with dh ≥ 60 → day 2 craters
  H_PENNY_EDGE ≤ 1         → day 2 craters
  H_MAX_POST_SIZE ≥ 20     → days 0+2 crater
  DMID_HISTORY = 10        → day 2 craters

What we explored and abandoned:
  - L3 imbalance fair adjustment (-19k, signal real but unprofitable)
  - drift-regime risk machinery from baseline_v18 (-69k visible — kills
    mean reversion)
  - cap-flattener defense alone (-74k visible)
  - VFE crash overlay alone (-1.7k vs v8, +1.0k vs v14 net loss)
  - position-cap on adding side (monotonic loss, every tighter cap hurt)

v8 history below.
==========================================================
HYDROGEL-only v8 — final ship strategy (2026-04-24).

Background: comprehensive covariate hunt across days 0/1/2 confirmed
HYDROGEL_PACK is statistically independent of every other product
(VELVETFRUIT_EXTRACT and all VEV vouchers). Cross-product OOS R²
trained on 2 days, tested on the 3rd → NEGATIVE. So we treat
HYDROGEL as a pure-MM target with ONLY own-microstructure signals.

3-day backtest (HYDROGEL only): +171,890.
  day 0 = 61,791    day 1 = 52,465    day 2 = 57,634
  vs v5 HYDROGEL-only baseline +149,355  →  +22,535  (+15.1 %)
  vs v5 full ship (HYDROGEL+VEV)  +168,031  →  +3,859  (HYDROGEL alone beats full v5).

Key changes from v5/v6 baseline params:
  H_ANCHOR     9990 → 9985    (-5; biases strategy to short rich, cover at fair)
  H_CLIP        30 → 33       (wider fair tolerance)
  H_REDUCE_EDGE 1.0 → 0.0     (eagerly reduce inventory at fair)
  AR1_BETA       0 → 0.18     (mean-reversion lean: fair -= 0.18 * last_dmid)
  CLIP_VOL_K     0 → 0.3      (CLIP grows with realized volatility)
  H_MAX_POST_SIZE 20 → 18     (slightly smaller; plateau 16-22)
  TYPICAL_SPREAD ∞ → 16       (use micro-price as fair when spread<16)

Knobs left at zero / off (verified via sweep — no help):
  ANCHOR_EMA_ALPHA, ASYM_REDUCE_LONG, ASYM_REDUCE_SHORT, LAYER2_FRACTION.
"""
from typing import Dict, List
import math
import json
from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {"HYDROGEL_PACK": 200}

    # v16 retune (best joint sweep result, see header):
    H_ANCHOR = 9983.0
    H_CLIP = 33.0
    H_TAKE_EDGE = 0.5      # v16: was 0.0 — require 0.5 cushion before take
    H_REDUCE_EDGE = 0.0    # MUST stay 0 with TE=0.5 (reduce branch now live)
    H_PENNY_EDGE = 3.0
    H_INV_SKEW = 0.014
    H_MAX_POST_SIZE = 18
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8

    AR1_BETA = 0.17        # v16: was 0.18
    TYPICAL_SPREAD = 16
    CLIP_VOL_K = 0.76      # v16: was 0.75
    DMID_HISTORY = 150     # v16: was 50 — smoother std

    # v17: walked-rebound (port from R2 clean_alpha ACO logic).
    # When spread > TYPICAL_SPREAD, the walked side rebounds next tick.
    # HYDROGEL data shows ~100-165 ASK-walks/day (zero bid-walks) with
    # (ba-1) - next_mid mean edge = 7-8 ticks (std 2). Boost rebound-
    # side make size; on HYDROGEL this fires on the ASK only.
    H_WALKED_TRIGGER = 16   # spread strictly > this triggers walked logic
    H_WALKED_GAP_MIN = 0.5  # min gap difference to identify walked side
    H_WALKED_SIZE = 60      # boosted post size on rebound side

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

    def _fair_input(self, book):
        # Spread-gated micro-price: at spread = TYPICAL (16) own-imbalance
        # has zero predictive power (z<1, see imb_regime.py); at spread<16
        # imbalance is highly predictive (z>20). Only use micro then.
        if book["spread"] < self.TYPICAL_SPREAD:
            tot = book["bv"] + book["av"]
            if tot > 0:
                return (book["ba"] * book["bv"] + book["bb"] * book["av"]) / tot
        return book["touch_mid"]

    def _cap_size(self, max_size, pos, side, cap, limit):
        if cap <= 0: return 0
        ratio = 1.0 - min(0.7, abs(pos) / limit)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    def _trade_hydrogel(self, od, pos, last_dmid, dmid_hist):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]; tm = book["touch_mid"]

        # Volatility-adaptive CLIP: CLIP = base + k * recent_std
        if self.CLIP_VOL_K > 0 and len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mean_d = sum(dmid_hist) / n
            std_d = math.sqrt(sum((d - mean_d) ** 2 for d in dmid_hist) / n)
            clip = self.H_CLIP + self.CLIP_VOL_K * std_d
        else:
            clip = self.H_CLIP

        fair_input = self._fair_input(book)
        fair_adj = max(-clip, min(clip, fair_input - self.H_ANCHOR))
        fair = self.H_ANCHOR + fair_adj
        if last_dmid is not None:
            # AR(1) lean: Δmid_H AR(1) = -0.13 in data; lean negatively against last move
            fair -= self.AR1_BETA * last_dmid

        working = pos
        orders: List[Order] = []

        # ---- TAKE ----
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0: break
            skew = fair - self.H_INV_SKEW * working
            if ap <= skew - self.H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0: orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0: orders.append(Order(prod, ap, q)); working += q
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0: break
            skew = fair - self.H_INV_SKEW * working
            if bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q

        # ---- MAKE ----
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

        # ---- WALKED-REBOUND: boost rebound-side size when spread walked ----
        if spread > self.H_WALKED_TRIGGER:
            bid_gap = self.H_ANCHOR - bb
            ask_gap = ba - self.H_ANCHOR
            if ask_gap > bid_gap + self.H_WALKED_GAP_MIN:
                # ASK walked up -> rebound down. Boost ask size at ba-1.
                if ask_price >= ba - 1 and ask_price > math.ceil(fair):
                    ask_size = max(ask_size, min(self.H_WALKED_SIZE, sell_cap))
            elif bid_gap > ask_gap + self.H_WALKED_GAP_MIN:
                # BID walked down -> rebound up. Boost bid size at bb+1.
                if bid_price <= bb + 1 and bid_price < math.floor(fair):
                    bid_size = max(bid_size, min(self.H_WALKED_SIZE, buy_cap))

        if bid_price < ask_price:
            if bid_size > 0: orders.append(Order(prod, bid_price, bid_size))
            if ask_size > 0: orders.append(Order(prod, ask_price, -ask_size))
        return orders, tm

    def run(self, state: TradingState):
        saved = {}
        if state.traderData:
            try: saved = json.loads(state.traderData)
            except Exception: saved = {}
        last_mid = saved.get("last_mid_H")
        last_dmid = saved.get("last_dmid_H", 0.0)
        dmid_hist = saved.get("dmid_hist_H", [])

        result: Dict[str, List[Order]] = {}
        new_mid = None
        if "HYDROGEL_PACK" in state.order_depths:
            orders, tm = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                state.position.get("HYDROGEL_PACK", 0),
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
        return result, 0, json.dumps(saved)
