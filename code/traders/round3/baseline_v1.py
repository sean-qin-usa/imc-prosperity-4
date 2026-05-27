"""
Round 3 baseline v1 — 2026-04-24.

First-principles minimum:

- HYDROGEL_PACK: mild-reversion stationary product, anchor drifts around
  9985-9995 with std ~26 and mode spread 16. Treat as ACO-class with
  dynamic fair = EMA(touch-mid) + inventory skew. Inside-touch MM at
  bb+1 / ba-1 with size ≤ 40 (cap adverse selection, rescaled from P4 R2
  ACO size 75 by limit ratio 200/80 is too big for this std regime; we
  start conservative and grid-search later).
- VELVETFRUIT_EXTRACT: tight-spread (mode 5) underlying. Inside-touch
  MM with small size (≤ 10) to avoid adverse selection. Drift is too
  small to be worth inventory-carry on 2-day rounds.
- Vouchers (VEV_*): NOT TRADED in v1. We want a clean floor number
  from delta-1 alone before layering option logic. Next iterations
  will add (i) VEV_4000 / VEV_4500 synthetic-underlying MM (basis
  std < 1, spreads 16-21), (ii) basis arb vs VELVETFRUIT, (iii) ATM
  voucher BS-residual MR.

Run:
    python3 tools/jmerle_backtester.py traders/round3/baseline_v1.py 3 --merge-pnl
"""
from typing import Dict, List, Optional
import math

from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
        "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
        "VEV_6500": 300,
    }

    # HYDROGEL_PACK params (ACO-class, rescaled for limit 200 and std ~26)
    H_FAIR_ANCHOR = 9990.0          # empirical 3-day mean
    H_FAIR_EMA = 0.02               # slow EMA on touch-mid; stationary trust
    H_INV_SKEW = 0.035              # fair shift per unit position
    H_MM_SIZE = 40                  # inside-touch quote size
    H_MM_OFFSET = 1                 # tick inside touch when spread wide
    H_WIDE_SPREAD = 4               # use inside-touch above this spread
    H_TYPICAL_SPREAD = 16           # modal spread
    H_TAKE_EDGE = 1.0               # take if touch crosses fair by >= this

    # VELVETFRUIT_EXTRACT params (tight spread, small size)
    V_FAIR_EMA = 0.05               # slightly faster (drift not pinned)
    V_INV_SKEW = 0.02
    V_MM_SIZE = 10                  # conservative due to tight spread

    # ---------- book helpers ----------
    def _book(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys); ba = min(sells)
        bv, av = buys[bb], sells[ba]
        tot = bv + av
        imb = (bv - av) / tot if tot else 0.0
        spread = ba - bb
        micro = (ba * bv + bb * av) / tot if tot else 0.5 * (bb + ba)
        return {
            "buys": dict(sorted(buys.items(), reverse=True)),
            "sells": dict(sorted(sells.items())),
            "bb": bb, "ba": ba, "bv": bv, "av": av,
            "imb": imb, "micro": micro,
            "spread": spread, "mid": 0.5 * (bb + ba),
        }

    # ---------- HYDROGEL_PACK ----------
    def _trade_hydrogel(self, od: OrderDepth, pos: int, saved: Dict) -> List[Order]:
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        mid = book["mid"]; spread = book["spread"]

        # Slow EMA on mid; blend toward anchor 9990. Key idea: the series
        # has mean-reversion AR(-0.13), but drifts across days, so a pure
        # fixed anchor misses; a pure EMA chases noise. Blend both.
        prev_ema = saved.get("h_ema", self.H_FAIR_ANCHOR)
        ema = (1 - self.H_FAIR_EMA) * prev_ema + self.H_FAIR_EMA * mid
        saved["h_ema"] = ema
        # Soft pull toward anchor (half-weight)
        fair = 0.5 * ema + 0.5 * self.H_FAIR_ANCHOR
        skewed = fair - self.H_INV_SKEW * pos

        orders: List[Order] = []

        # TAKE — cross the book if it's clearly mispriced
        for ap, av in book["sells"].items():
            if limit - pos <= 0:
                break
            if ap <= skewed - self.H_TAKE_EDGE:
                q = min(av, limit - pos)
                if q > 0:
                    orders.append(Order(prod, ap, q)); pos += q
            else:
                break
        for bp, bv in book["buys"].items():
            if limit + pos <= 0:
                break
            if bp >= skewed + self.H_TAKE_EDGE:
                q = min(bv, limit + pos)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); pos -= q
            else:
                break

        # MAKE — inside-touch quotes
        skewed = fair - self.H_INV_SKEW * pos
        if spread >= self.H_WIDE_SPREAD:
            bid_px = min(bb + self.H_MM_OFFSET, math.floor(skewed) - 1)
            ask_px = max(ba - self.H_MM_OFFSET, math.ceil(skewed) + 1)
        else:
            bid_px = math.floor(skewed) - 1
            ask_px = math.ceil(skewed) + 1
        buy_cap = max(0, limit - pos)
        sell_cap = max(0, limit + pos)
        if bid_px < ask_px and bid_px < ba:
            sz = min(self.H_MM_SIZE, buy_cap)
            if sz > 0:
                orders.append(Order(prod, int(bid_px), sz))
        if ask_px > bid_px and ask_px > bb:
            sz = min(self.H_MM_SIZE, sell_cap)
            if sz > 0:
                orders.append(Order(prod, int(ask_px), -sz))
        return orders

    # ---------- VELVETFRUIT_EXTRACT ----------
    def _trade_velvet(self, od: OrderDepth, pos: int, saved: Dict) -> List[Order]:
        prod = "VELVETFRUIT_EXTRACT"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        mid = book["mid"]; spread = book["spread"]

        prev_ema = saved.get("v_ema", mid)
        ema = (1 - self.V_FAIR_EMA) * prev_ema + self.V_FAIR_EMA * mid
        saved["v_ema"] = ema
        fair = ema
        skewed = fair - self.V_INV_SKEW * pos

        orders: List[Order] = []

        # TAKE — only if asymmetric mispricing
        for ap, av in book["sells"].items():
            if limit - pos <= 0:
                break
            if ap <= skewed - 1.0:
                q = min(av, limit - pos)
                if q > 0:
                    orders.append(Order(prod, ap, q)); pos += q
            else:
                break
        for bp, bv in book["buys"].items():
            if limit + pos <= 0:
                break
            if bp >= skewed + 1.0:
                q = min(bv, limit + pos)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); pos -= q
            else:
                break

        # MAKE — inside-touch quotes when spread >= 3 (most ticks)
        skewed = fair - self.V_INV_SKEW * pos
        if spread >= 3:
            bid_px = bb + 1
            ask_px = ba - 1
            buy_cap = max(0, limit - pos)
            sell_cap = max(0, limit + pos)
            if bid_px < ask_px:
                sz = min(self.V_MM_SIZE, buy_cap)
                if sz > 0:
                    orders.append(Order(prod, bid_px, sz))
                sz = min(self.V_MM_SIZE, sell_cap)
                if sz > 0:
                    orders.append(Order(prod, ask_px, -sz))
        return orders

    # ---------- dispatch ----------
    def run(self, state: TradingState):
        import json
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        pos = state.position

        if "HYDROGEL_PACK" in state.order_depths:
            result["HYDROGEL_PACK"] = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0), saved,
            )
        if "VELVETFRUIT_EXTRACT" in state.order_depths:
            result["VELVETFRUIT_EXTRACT"] = self._trade_velvet(
                state.order_depths["VELVETFRUIT_EXTRACT"],
                pos.get("VELVETFRUIT_EXTRACT", 0), saved,
            )

        return result, 0, json.dumps(saved)
