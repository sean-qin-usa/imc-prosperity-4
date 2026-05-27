"""
Round 1 fresh strategy — 2026-04-23, written from ROUND2_RECIPE.md only.

Sanity scan (`analysis/fresh_scan_round1.py`) confirms R1 and R2 share the
same generative structure:

  ACO: anchored at ≈ 10_000, residual sd ≈ 4-5, AR(1) = -0.5,
       mode spread 16, walked states at 18/19.
  IPR: drift +0.001/ts (exact, same as R2), residual sd ≈ 1.1-1.3,
       AR(1) = -0.49, mode spread 12-13.

Position limits 80/80, same as R2.  Imbalance→Δmid aggregate r ≈ +0.59,
spread-gate dead zone at 11-16, walked-regime r ≈ +0.65 at 18/19 —
identical to R2.

Direct application of the recipe (v3 for R2) is therefore correct.
This file is a copy of the v3 logic with the comment header adapted.
"""
from typing import Dict, List, Optional
import math

from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
    MAF_BID = 0  # MAF is round-2-only; round-1 ignores bid().

    ACO_FAIR = 10_000
    ACO_FAIR_CLIP = 4.0
    ACO_TYPICAL_SPREAD = 16
    ACO_WALKED_FAIR_CLIP = 6.0
    ACO_INV_SKEW = 0.06
    ACO_MM_SIZE = 75
    ACO_MM_OFFSET = 1
    ACO_PENNY_EDGE = 1.0
    ACO_WIDE_SPREAD = 4
    ACO_WALKED_EXTRA = 55
    ACO_UNWIND_START = 990_000
    ACO_UNWIND_EDGE = 1.0
    ACO_UNWIND_MAX = 12

    IPR_DRIFT = 0.001
    IPR_TARGET = 80
    IPR_SOFT_TARGET = 72
    IPR_EARLY_WINDOW = 2_000
    IPR_EARLY_MAX_QTY = 20
    IPR_PASSIVE_SIZE = 12
    IPR_PASSIVE_SECOND = 6
    IPR_TYPICAL_SPREAD = 14
    IPR_WALKED_FAIR_CLIP = 5.0
    IPR_WALKED_EXTRA = 12
    IPR_UNWIND_START = 990_000
    IPR_UNWIND_SIZE = 20

    IMB_STRONG = 0.30
    IMB_BOOST = 1.8
    IMB_SHRINK = 0.2

    def bid(self) -> int:
        return self.MAF_BID

    def _book(self, od: OrderDepth, spread_gate_mid: int) -> Optional[Dict]:
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys); ba = min(sells)
        bv, av = buys[bb], sells[ba]
        tot = bv + av
        imb = (bv - av) / tot if tot else 0.0
        spread = ba - bb
        if spread <= spread_gate_mid:
            micro = 0.5 * (bb + ba)
        else:
            micro = (ba * bv + bb * av) / tot if tot else 0.5 * (bb + ba)
        return {
            "buys": dict(sorted(buys.items(), reverse=True)),
            "sells": dict(sorted(sells.items())),
            "bb": bb, "ba": ba, "imb": imb, "micro": micro, "spread": spread,
        }

    def _walked_fair(self, bb, ba, micro, anchor, typical, clip):
        spread = ba - bb
        if spread <= typical:
            return anchor + max(-clip, min(clip, micro - anchor))
        bid_gap = anchor - bb; ask_gap = ba - anchor
        half = typical / 2
        if bid_gap > ask_gap + 0.5: trusted = ba - half
        elif ask_gap > bid_gap + 0.5: trusted = bb + half
        else: trusted = 0.5 * (bb + ba)
        return anchor + max(-clip, min(clip, trusted - anchor))

    def _trade_aco(self, od, pos, ts):
        prod = "ASH_COATED_OSMIUM"
        limit = self.LIMITS[prod]
        book = self._book(od, self.ACO_TYPICAL_SPREAD)
        if not book: return []
        bb, ba = book["bb"], book["ba"]
        micro, imb, spread = book["micro"], book["imb"], book["spread"]
        fair = self._walked_fair(bb, ba, micro, float(self.ACO_FAIR),
                                 self.ACO_TYPICAL_SPREAD, self.ACO_WALKED_FAIR_CLIP)
        orders: List[Order] = []
        skewed = fair - self.ACO_INV_SKEW * pos
        for ap, av in book["sells"].items():
            if limit - pos <= 0: break
            if ap <= skewed:
                qty = min(av, limit - pos)
                if qty > 0:
                    orders.append(Order(prod, ap, qty)); pos += qty
        for bp, bv in book["buys"].items():
            if limit + pos <= 0: break
            skewed = fair - self.ACO_INV_SKEW * pos
            if bp >= skewed:
                qty = min(bv, limit + pos)
                if qty > 0:
                    orders.append(Order(prod, bp, -qty)); pos -= qty
        if ts >= self.ACO_UNWIND_START:
            if pos > 0 and bb >= math.floor(fair - self.ACO_UNWIND_EDGE):
                qty = min(pos, book["buys"].get(bb, 0), self.ACO_UNWIND_MAX)
                if qty > 0:
                    orders.append(Order(prod, bb, -qty)); pos -= qty
            elif pos < 0 and ba <= math.ceil(fair + self.ACO_UNWIND_EDGE):
                qty = min(-pos, book["sells"].get(ba, 0), self.ACO_UNWIND_MAX)
                if qty > 0:
                    orders.append(Order(prod, ba, qty)); pos += qty
        skewed = fair - self.ACO_INV_SKEW * pos
        if spread >= self.ACO_WIDE_SPREAD:
            bid_px = min(bb + 1, math.floor(skewed - self.ACO_PENNY_EDGE))
            ask_px = max(ba - 1, math.ceil(skewed + self.ACO_PENNY_EDGE))
        else:
            bid_px = math.floor(skewed - self.ACO_MM_OFFSET)
            ask_px = math.ceil(skewed + self.ACO_MM_OFFSET)
        bid_px = min(int(bid_px), ba - 1, math.floor(fair) - 1)
        ask_px = max(int(ask_px), bb + 1, math.ceil(fair) + 1)
        buy_cap = max(0, limit - pos); sell_cap = max(0, limit + pos)
        bid_sz = min(self.ACO_MM_SIZE, buy_cap)
        ask_sz = min(self.ACO_MM_SIZE, sell_cap)
        if imb > self.IMB_STRONG:
            ask_sz = max(0, int(round(ask_sz * self.IMB_SHRINK)))
            bid_sz = min(buy_cap, int(round(bid_sz * self.IMB_BOOST)))
        elif imb < -self.IMB_STRONG:
            bid_sz = max(0, int(round(bid_sz * self.IMB_SHRINK)))
            ask_sz = min(sell_cap, int(round(ask_sz * self.IMB_BOOST)))
        if bid_px < ask_px:
            if bid_sz > 0: orders.append(Order(prod, bid_px, bid_sz))
            if ask_sz > 0: orders.append(Order(prod, ask_px, -ask_sz))
        if spread > self.ACO_TYPICAL_SPREAD:
            bid_gap = self.ACO_FAIR - bb; ask_gap = ba - self.ACO_FAIR
            if bid_gap > ask_gap + 0.5 and pos < limit:
                wx = bb + 1
                if wx < math.floor(fair):
                    sz = min(self.ACO_WALKED_EXTRA, limit - pos)
                    if sz > 0 and wx != bid_px: orders.append(Order(prod, wx, sz))
            elif ask_gap > bid_gap + 0.5 and pos > -limit:
                wx = ba - 1
                if wx > math.ceil(fair):
                    sz = min(self.ACO_WALKED_EXTRA, limit + pos)
                    if sz > 0 and wx != ask_px: orders.append(Order(prod, wx, -sz))
        return orders

    def _trade_ipr(self, od, pos, ts):
        prod = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[prod]
        book = self._book(od, self.IPR_TYPICAL_SPREAD - 1)
        if not book: return []
        bb, ba = book["bb"], book["ba"]
        micro, imb, spread = book["micro"], book["imb"], book["spread"]
        benchmark = micro
        fair = self._walked_fair(bb, ba, micro, benchmark,
                                 self.IPR_TYPICAL_SPREAD, self.IPR_WALKED_FAIR_CLIP)
        orders: List[Order] = []
        if ts >= self.IPR_UNWIND_START:
            if pos > 0 and bb >= benchmark - 1:
                qty = min(pos, book["buys"].get(bb, 0), self.IPR_UNWIND_SIZE)
                if qty > 0: orders.append(Order(prod, bb, -qty))
            return orders
        take_fair = max(benchmark, fair)
        if ts <= self.IPR_EARLY_WINDOW and pos < self.IPR_TARGET:
            for ap, av in book["sells"].items():
                if pos >= self.IPR_TARGET: break
                if ap <= take_fair:
                    qty = min(av, self.IPR_TARGET - pos, limit - pos, self.IPR_EARLY_MAX_QTY)
                    if qty > 0: orders.append(Order(prod, ap, qty)); pos += qty
                else: break
        if pos < self.IPR_SOFT_TARGET:
            for ap, av in book["sells"].items():
                if pos >= self.IPR_SOFT_TARGET: break
                if ap <= take_fair:
                    qty = min(av, self.IPR_SOFT_TARGET - pos, limit - pos)
                    if qty > 0: orders.append(Order(prod, ap, qty)); pos += qty
                else: break
        if pos < limit and spread > 2 and imb > -self.IMB_STRONG:
            primary_px = min(bb + 1, ba - 1)
            primary_sz = min(self.IPR_PASSIVE_SIZE, limit - pos)
            if imb > self.IMB_STRONG:
                primary_sz = min(limit - pos, int(round(primary_sz * self.IMB_BOOST)))
            elif imb < 0:
                primary_sz = max(0, int(round(primary_sz * (1 + imb))))
            if primary_sz > 0 and primary_px < ba:
                orders.append(Order(prod, primary_px, primary_sz))
                if spread > 4 and pos + primary_sz < limit:
                    sec_px = min(bb + 2, ba - 1)
                    if sec_px > primary_px:
                        sz = min(self.IPR_PASSIVE_SECOND, limit - pos - primary_sz)
                        if sz > 0: orders.append(Order(prod, sec_px, sz))
        if spread > self.IPR_TYPICAL_SPREAD:
            bid_gap = benchmark - bb; ask_gap = ba - benchmark
            if bid_gap > ask_gap + 0.5 and pos < limit:
                wx = bb + 1
                if wx < fair:
                    sz = min(self.IPR_WALKED_EXTRA, limit - pos)
                    if sz > 0: orders.append(Order(prod, wx, sz))
            elif ask_gap > bid_gap + 0.5 and pos > 0:
                wx = ba - 1
                if wx > fair:
                    sz = min(self.IPR_WALKED_EXTRA, pos)
                    if sz > 0: orders.append(Order(prod, wx, -sz))
        return orders

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self._trade_aco(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
                state.timestamp)
        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            result["INTARIAN_PEPPER_ROOT"] = self._trade_ipr(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                state.timestamp)
        return result, 0, state.traderData or ""
