"""VFE-only skew-residual trader v1 — test if the s8e signal converts in the
local backtester.

Signal:
  residual_t = (V5500_mid_t - V5000_mid_t) - (a + b * VFE_mid_t)
  Predict ΔVFE_{t+1} ≈ k * residual_t  (k is NEGATIVE).
  Position target = -K_TRADE * residual_t  (short rich smile).

Pooled OLS from days 0-2 of round-3 data:
  a ≈ +4170, b ≈ -0.85  (averaged across days; level shifts daily)
  k_partial_corr ≈ -0.21 (partial-corr after controlling for VFE Δm AR(1))
  Implied prediction coeff ≈ -0.07 ticks/unit-residual (rough)

This trader does NOT trade vouchers (just observes them) and trades VFE
only via aggressive take when |residual| > THR. If this works, we'll
integrate it into the v15 ship as a fair-value shift.

Spread cost concern: VFE typical spread is ~5 ticks, so each take pays
2.5 ticks half-spread. Signal must beat that to be live-tradable.
"""
from typing import Dict, List
import math
import json
from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {"VELVETFRUIT_EXTRACT": 200}

    # Linear fit (smile = a + b * VFE), pooled estimate
    SKEW_A = 4170.0
    SKEW_B = -0.85

    # Trade thresholds
    SKEW_THR = 30.0          # |residual| above which we take (alpha must beat half-spread)
    SKEW_TARGET_SCALE = 30.0 # position target = -clip(residual / SCALE) * LIMIT

    def _book(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys); ba = min(sells)
        return {"bb": bb, "ba": ba, "bv": buys[bb], "av": sells[ba],
                "spread": ba - bb, "touch_mid": 0.5 * (bb + ba),
                "buys": dict(sorted(buys.items(), reverse=True)),
                "sells": dict(sorted(sells.items()))}

    def run(self, state: TradingState):
        out: Dict[str, List[Order]] = {}

        v5000_od = state.order_depths.get("VEV_5000")
        v5500_od = state.order_depths.get("VEV_5500")
        vfe_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if v5000_od is None or v5500_od is None or vfe_od is None:
            return {}, 0, ""

        b5000 = self._book(v5000_od)
        b5500 = self._book(v5500_od)
        bvfe = self._book(vfe_od)
        if b5000 is None or b5500 is None or bvfe is None:
            return {}, 0, ""

        skew = b5500["touch_mid"] - b5000["touch_mid"]
        vfe_mid = bvfe["touch_mid"]
        residual = skew - (self.SKEW_A + self.SKEW_B * vfe_mid)

        # Target position: -clip(residual/scale, -1, 1) * LIMIT
        signal = max(-1.0, min(1.0, residual / self.SKEW_TARGET_SCALE))
        target_pos = int(-signal * self.LIMITS["VELVETFRUIT_EXTRACT"])

        cur_pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
        delta = target_pos - cur_pos

        orders: List[Order] = []
        if abs(residual) >= self.SKEW_THR:
            if delta > 0:
                # Buy: lift the offer
                cap = self.LIMITS["VELVETFRUIT_EXTRACT"] - cur_pos
                qty = min(delta, cap, bvfe["av"])
                if qty > 0:
                    orders.append(Order("VELVETFRUIT_EXTRACT", bvfe["ba"], qty))
            elif delta < 0:
                cap = self.LIMITS["VELVETFRUIT_EXTRACT"] + cur_pos
                qty = min(-delta, cap, bvfe["bv"])
                if qty > 0:
                    orders.append(Order("VELVETFRUIT_EXTRACT", bvfe["bb"], -qty))

        if orders:
            out["VELVETFRUIT_EXTRACT"] = orders
        return out, 0, ""
