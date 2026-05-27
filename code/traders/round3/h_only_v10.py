"""
HYDROGEL-only v10 — v8 + risk overlays (2026-04-24).

Motivation: v8 ship hits the local 3-day total of 171,890 but on the
hidden day (submission 391745) the equity curve peaked at +20.1k around
ts=70k, then bled back to +13.5k at the close while position sat pinned
at the +200 long limit and mid fell from 9996 → 9927. We're losing
upside the moment a directional regime persists past the CLIP=33 band.

Borrowed wholesale from baseline_v18 (the only existing strategy that
improved BOTH visible 3-day backtest AND bundle-calibrated hidden-day
replay):

  1) shock detector — if |Δmid since last tick| > H_SHOCK_MOVE, just
     follow touch_mid for one tick (no take/make biasing).
  2) drift regime — when |touch_mid - anchor| > H_DRIFT_THRESHOLD AND
     pos*(-drift) > H_DRIFT_RISK (we're aligned the wrong way), boost
     inv_skew to 3x and partially follow drift past the CLIP band
     (DRIFT_BLEND).
  3) drift_dir veto — when in drift, refuse to add to the wrong side
     (no aggressive buys when drift_dir=-1, no aggressive sells when
     drift_dir=+1) and zero the make-quote on the adding side.
  4) cap-flattener — at-limit (|pos| >= 0.95 limit) AND adverse drift
     (|drift| >= 35) → force-flatten H_CAP_FLATTEN_QTY by hitting the
     opposite side. Defends the "stuck at +200 while mid drops" trap.
  5) VFE crash overlay — when HYDROGEL is in a crash (touch_mid <=
     anchor - 18, spread >= 14), use VELVETFRUIT_EXTRACT 20-tick
     momentum as a hidden-day-validated regime filter:
       VFE_mom20 <= -3.5 → fair +0.75, bid 2x, ask 0.25x (lean LONG)
       VFE_mom20 >=  1.0 → fair -1.25, bid 0.25x, ask 1.25x (suppress)
     The ONLY cross-product touch — HYDROGEL still trades alone, we
     just observe VFE for the regime tag.

v8 own-microstructure pieces preserved exactly:
  AR1_BETA=0.18, CLIP_VOL_K=0.3, TYPICAL_SPREAD=16 micro-price gate,
  H_ANCHOR=9985, H_CLIP=33, H_REDUCE_EDGE=0.0, H_INV_SKEW=0.015,
  H_MAX_POST_SIZE=18.
"""
from typing import Dict, List, Optional, Tuple
import math
import json
from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {"HYDROGEL_PACK": 200}

    # ----- v8 core (unchanged) -----
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

    # ----- v18 risk machinery -----
    H_SHOCK_MOVE = 15.0
    H_INV_SKEW_DRIFT = 0.045        # 3x normal — refuse to add in drift
    H_DRIFT_BLEND = 0.6             # follow part of drift past CLIP
    H_DRIFT_THRESHOLD = 50.0        # |drift| > 50 to enter drift regime
    H_DRIFT_RISK = 2000.0           # AND pos*(-drift) > 2000 (aligned bad)
    H_CAP_NEAR = 0.95               # at-limit threshold
    H_CAP_DRIFT = 35.0
    H_CAP_FLATTEN_QTY = 30

    # ----- v18 VFE crash overlay -----
    H_CRASH_TRIGGER = 18.0          # touch_mid <= anchor-18 = 9967
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
        # v8 spread-gated micro-price.
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

    def _trade_hydrogel(self, od, pos, last_dmid, dmid_hist,
                        prev_mid, vfe_mom20):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]
        touch_mid = book["touch_mid"]

        # Volatility-adaptive CLIP (v8)
        if self.CLIP_VOL_K > 0 and len(dmid_hist) >= 3:
            n = len(dmid_hist)
            mean_d = sum(dmid_hist) / n
            std_d = math.sqrt(sum((d - mean_d) ** 2 for d in dmid_hist) / n)
            clip = self.H_CLIP + self.CLIP_VOL_K * std_d
        else:
            clip = self.H_CLIP

        # ---- regime ----
        shock = (prev_mid is not None
                 and abs(touch_mid - prev_mid) > self.H_SHOCK_MOVE)
        drift_raw = touch_mid - self.H_ANCHOR
        risk_aligned = pos * (-drift_raw)
        drift_regime = (not shock) and abs(drift_raw) > self.H_DRIFT_THRESHOLD \
                                   and risk_aligned > self.H_DRIFT_RISK
        drift_dir = 0
        if drift_regime:
            drift_dir = 1 if drift_raw > 0 else -1

        if shock:
            fair = touch_mid
            inv_skew = self.H_INV_SKEW
        elif drift_regime:
            clipped = max(-clip, min(clip, drift_raw))
            fair = self.H_ANCHOR + clipped + self.H_DRIFT_BLEND * (drift_raw - clipped)
            inv_skew = self.H_INV_SKEW_DRIFT
        else:
            fair_input = self._fair_input(book)
            fair_adj = max(-clip, min(clip, fair_input - self.H_ANCHOR))
            fair = self.H_ANCHOR + fair_adj
            if last_dmid is not None:
                fair -= self.AR1_BETA * last_dmid
            inv_skew = self.H_INV_SKEW

        # VFE crash overlay
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

        # ---- TAKE asks (buy from sellers) ----
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0: break
            skew = fair - inv_skew * working
            block_aggressive_buy = (drift_dir == -1)  # falling: don't buy
            if (not block_aggressive_buy) and ap <= skew - self.H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0: orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0: orders.append(Order(prod, ap, q)); working += q

        # ---- TAKE bids (sell to buyers) ----
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0: break
            skew = fair - inv_skew * working
            block_aggressive_sell = (drift_dir == 1)  # rising: don't short
            if (not block_aggressive_sell) and bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0: orders.append(Order(prod, bp, -q)); working -= q

        # ---- cap-flattener defense ----
        cap_long_bad = (working >= self.H_CAP_NEAR * limit) and (drift_raw <= -self.H_CAP_DRIFT)
        cap_short_bad = (working <= -self.H_CAP_NEAR * limit) and (drift_raw >= self.H_CAP_DRIFT)
        if cap_long_bad and not shock:
            qty_left = self.H_CAP_FLATTEN_QTY
            for bp, bv in book["buys"].items():
                if qty_left <= 0 or working <= 0: break
                q = min(bv, qty_left, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q))
                    working -= q; qty_left -= q
        elif cap_short_bad and not shock:
            qty_left = self.H_CAP_FLATTEN_QTY
            for ap, av in book["sells"].items():
                if qty_left <= 0 or working >= 0: break
                q = min(av, qty_left, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q))
                    working += q; qty_left -= q

        if shock:
            return orders, touch_mid

        # ---- MAKE ----
        skew = fair - inv_skew * working
        buy_cap = max(0, limit - working); sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.H_MAX_POST_SIZE, working, "buy", buy_cap, limit)
        ask_size = self._cap_size(self.H_MAX_POST_SIZE, working, "sell", sell_cap, limit)

        # VFE crash size multipliers
        bid_size = min(buy_cap, int(round(bid_size * bid_size_mult)))
        ask_size = min(sell_cap, int(round(ask_size * ask_size_mult)))

        # Suppress make on the drift-adding side
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
            if bid_size > 0: orders.append(Order(prod, bid_price, bid_size))
            if ask_size > 0: orders.append(Order(prod, ask_price, -ask_size))
        return orders, touch_mid

    def run(self, state: TradingState):
        saved = {}
        if state.traderData:
            try: saved = json.loads(state.traderData)
            except Exception: saved = {}
        last_mid = saved.get("last_mid_H")
        last_dmid = saved.get("last_dmid_H", 0.0)
        dmid_hist = saved.get("dmid_hist_H", [])
        vfe_hist = saved.get("vfe_hist", [])

        # VFE momentum (for crash overlay only)
        vfe_mom20 = None
        if "VELVETFRUIT_EXTRACT" in state.order_depths:
            vb = self._book(state.order_depths["VELVETFRUIT_EXTRACT"])
            if vb is not None:
                vfe_hist.append(vb["touch_mid"])
                if len(vfe_hist) > self.H_VFE_MOM_LOOKBACK + 1:
                    vfe_hist = vfe_hist[-(self.H_VFE_MOM_LOOKBACK + 1):]
                if len(vfe_hist) >= self.H_VFE_MOM_LOOKBACK + 1:
                    vfe_mom20 = vfe_hist[-1] - vfe_hist[0]
        saved["vfe_hist"] = vfe_hist

        result: Dict[str, List[Order]] = {}
        new_mid = None
        if "HYDROGEL_PACK" in state.order_depths:
            orders, tm = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                state.position.get("HYDROGEL_PACK", 0),
                last_dmid, dmid_hist, last_mid, vfe_mom20,
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
