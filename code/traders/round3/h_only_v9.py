"""
HYDROGEL-only v9 — adds L3 deep-book imbalance signal (2026-04-24).

Discovery (3-day stable): at narrow spread (spread<15, ~3.5% of ticks)
the L3 imbalance (deepest book layer) predicts next-tick Δmid with
R²=0.79–0.84 and slope ≈ -4 (positive L3 bid stack → mid drops).
L1 / L2 are co-linear with L3 once L3 is in the model; L3 alone
captures the entire variance. Persists ~10 ticks.

So at narrow spread we replace the L1 micro-price (slope=spread/2≈3
on imb_L1) with fair = touch_mid + L3_BETA * imb_L3 (L3_BETA ≈ -4).
At typical/wide spread the book is symmetric (imb_L3=0) so the
signal is silent and we still fall back to touch_mid.

----- v8 history below -----

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

    # L3 imbalance lean (sign INVERTED vs L1: deep-book bid stack → mid drops)
    # 3-day OLS slope at narrow spread is -4.0 ± 0.1.
    L3_BETA = -4.0

    def _book(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys); ba = min(sells)
        # Sorted books for level access
        buys_sorted = sorted(buys.items(), reverse=True)
        sells_sorted = sorted(sells.items())
        # L3 (deepest of available) volumes — 0 if missing
        l3_bv = buys_sorted[2][1] if len(buys_sorted) >= 3 else 0
        l3_av = sells_sorted[2][1] if len(sells_sorted) >= 3 else 0
        return {
            "buys": dict(buys_sorted),
            "sells": dict(sells_sorted),
            "bb": bb, "ba": ba, "bv": buys[bb], "av": sells[ba],
            "l3_bv": l3_bv, "l3_av": l3_av,
            "spread": ba - bb, "touch_mid": 0.5 * (bb + ba),
        }

    def _fair_input(self, book):
        # At narrow spread (<16) the deep L3 imbalance carries the
        # signal: positive L3 bid stack → mid drops next tick (slope -4,
        # R²≈0.8 across all 3 days). L1/L2 add no incremental info once
        # L3 is in the model.
        if book["spread"] < self.TYPICAL_SPREAD:
            l3_tot = book["l3_bv"] + book["l3_av"]
            if l3_tot > 0:
                imb_l3 = (book["l3_bv"] - book["l3_av"]) / l3_tot
                return book["touch_mid"] + self.L3_BETA * imb_l3
            # No L3 layer available: fall back to L1 micro-price.
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
