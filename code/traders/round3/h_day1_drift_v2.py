"""HYDROGEL with day-1 drift gate — v2 (locked best config).

3-day backtest 183,461 (+1,786 vs v16's 181,675), all days improved:
  d0: 64,183 (+639)
  d1: 54,533 (+649)
  d2: 64,745 (+498)

Mechanism: a 200-tick rolling touch_mid window is tracked; if its range
(max-min) exceeds DRIFT_GATE_RANGE, multiply CLIP_VOL_K by (1+BOOST). This
widens fair tracking only during sustained-drift regimes (day 1 ticks
6000-9999 + scattered episodes on days 0/2).

Sweep findings:
  - Cliff at R<=51: gate triggers on a recurring day-2 episode → -28k cliff
  - R=52..56 are above the cliff; R=53 produces identical PnL to R=52
    in this sample (no episodes with range ∈ [52, 53))
  - PnL peak at B=1.6, ridge across R=52-55. B>=1.7 cliffs day 1 (-95+)
  - H<150 weakens detection; H>=300 introduces day-1 spurious triggers
  - Picked R=53 (2-unit margin from R=51 cliff), B=1.6, H=200

Did NOT use: H_ANCHOR shift (cross-day -12k cliff), uniform CLIP_VOL_K
boost (cross-day -13k cliff). The regime gate is necessary because any
uniform widening hurts a non-day-1 day.

History above v16 (181,675): see h_only_v16.py header.
"""
from typing import Dict, List
import math
import json
from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {"HYDROGEL_PACK": 200}

    H_ANCHOR = 9983.0
    H_CLIP = 33.0
    H_TAKE_EDGE = 0.5
    H_REDUCE_EDGE = 0.0
    H_PENNY_EDGE = 3.0
    H_INV_SKEW = 0.014
    H_MAX_POST_SIZE = 18
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8

    AR1_BETA = 0.17
    TYPICAL_SPREAD = 16
    CLIP_VOL_K = 0.76
    DMID_HISTORY = 150

    # Drift-regime gate (NEW vs v16)
    MID_RANGE_HISTORY = 200      # ticks of touch_mid history
    DRIFT_GATE_RANGE = 53        # range threshold (ticks). R<=51 cliffs day 2.
    DRIFT_CLIP_BOOST = 1.6       # CLIP_VOL_K *= (1 + BOOST) when tripped.
                                 # B>=1.7 cliffs day 1.

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

    def _trade_hydrogel(self, od, pos, last_dmid, dmid_hist, mid_hist):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None
        bb, ba = book["bb"], book["ba"]; spread = book["spread"]; tm = book["touch_mid"]

        clip_vol_k = self.CLIP_VOL_K
        # Drift-regime gate: touch_mid range over last MID_RANGE_HISTORY ticks.
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

        fair_input = self._fair_input(book)
        fair_adj = max(-clip, min(clip, fair_input - self.H_ANCHOR))
        fair = self.H_ANCHOR + fair_adj
        if last_dmid is not None:
            fair -= self.AR1_BETA * last_dmid

        working = pos
        orders: List[Order] = []

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
        mid_hist = saved.get("mid_hist_H", [])

        result: Dict[str, List[Order]] = {}
        new_mid = None
        if "HYDROGEL_PACK" in state.order_depths:
            orders, tm = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                state.position.get("HYDROGEL_PACK", 0),
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
        return result, 0, json.dumps(saved)
