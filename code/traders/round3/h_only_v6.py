"""
HYDROGEL-only v6 — built on confirmed-from-data signals only.

What we know from covariate hunt + regime analysis:
  - HYDROGEL is INDEPENDENT of every other product (cross R²_oos < 0).
  - Own L1 imbalance huge at spread<=15 (z>20), DEAD at spread=16 (typical).
  - AR(1) Δmid = -0.13 (mild mean reversion in price moves).
  - |ΔH| ~ spread = -0.32 (wider spread → smaller move; safer to size up).

v6 layers on top of v5:
  1. Spread-gated micro-price: use (ask*bv + bid*av)/(bv+av) when spread <= 15;
     fall back to touch_mid at spread >= 16 to avoid tracking noise.
  2. AR(1) lean: fair -= AR1_BETA * last_dmid  (β ≈ 0.10–0.15 from data).
  3. Anchor stays at 9990 (fixed; data-tuned mean).
  4. Wider CLIP scaling tested separately.
  5. Layered passive quoting: post 2 layers (touch+1, touch+3) when spread is wide.
"""
from typing import Dict, List
import math
import json
from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {"HYDROGEL_PACK": 200}

    # --- Anchor / clip
    H_ANCHOR = 9990.0
    H_CLIP = 30.0

    # --- Take / make / inventory
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 1.0
    H_PENNY_EDGE = 1.5
    H_INV_SKEW = 0.015
    H_MAX_POST_SIZE = 20
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8

    # --- v6 new
    AR1_BETA = 0.13           # mean-reverting lean on last Δmid
    TYPICAL_SPREAD = 16       # gate: at spread > or == typical, use touch_mid not micro
    LAYER2_OFFSET = 3         # 2nd passive layer offset from touch
    LAYER2_FRACTION = 0.5     # size of 2nd layer relative to first

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

    def _fair_input(self, book):
        """Spread-gated micro-price."""
        spread = book["spread"]
        if spread < self.TYPICAL_SPREAD:
            tot = book["bv"] + book["av"]
            if tot > 0:
                # micro-price: (ask*bv + bid*av)/(bv+av) — biased toward thinner side
                return (book["ba"] * book["bv"] + book["bb"] * book["av"]) / tot
        return book["touch_mid"]

    def _cap_size(self, max_size, pos, side, cap, limit):
        if cap <= 0: return 0
        ratio = 1.0 - min(0.7, abs(pos) / limit)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    def _trade_hydrogel(self, od, pos, last_dmid):
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], None
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        tm = book["touch_mid"]

        # --- v6 fair: spread-gated micro - AR(1) lean
        fair_input = self._fair_input(book)
        fair_adj = max(-self.H_CLIP, min(self.H_CLIP, fair_input - self.H_ANCHOR))
        fair = self.H_ANCHOR + fair_adj
        if last_dmid is not None:
            fair -= self.AR1_BETA * last_dmid  # mean-revert prior move

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
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
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

            # ---- LAYER 2 (only when spread is wide enough)
            if spread >= self.H_WIDE_SPREAD + self.LAYER2_OFFSET:
                bid2 = bid_price - self.LAYER2_OFFSET
                ask2 = ask_price + self.LAYER2_OFFSET
                bid2_sz = max(0, int(round(bid_size * self.LAYER2_FRACTION)))
                ask2_sz = max(0, int(round(ask_size * self.LAYER2_FRACTION)))
                # cap by remaining limit (after 1st-layer hypothetical fill)
                bid2_sz = min(bid2_sz, max(0, limit - (working + bid_size)))
                ask2_sz = min(ask2_sz, max(0, limit + (working - ask_size)))
                if bid2 < ask2:
                    if bid2_sz > 0: orders.append(Order(prod, bid2, bid2_sz))
                    if ask2_sz > 0: orders.append(Order(prod, ask2, -ask2_sz))

        return orders, tm

    def run(self, state: TradingState):
        saved = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}
        last_mid = saved.get("last_mid_H")
        last_dmid = saved.get("last_dmid_H", 0.0)

        result: Dict[str, List[Order]] = {}
        new_mid = None
        if "HYDROGEL_PACK" in state.order_depths:
            orders, tm = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                state.position.get("HYDROGEL_PACK", 0),
                last_dmid,
            )
            result["HYDROGEL_PACK"] = orders
            new_mid = tm

        if new_mid is not None:
            if last_mid is not None:
                saved["last_dmid_H"] = new_mid - last_mid
            else:
                saved["last_dmid_H"] = 0.0
            saved["last_mid_H"] = new_mid

        return result, 0, json.dumps(saved)
