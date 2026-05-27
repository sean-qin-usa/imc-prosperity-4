"""
Round 2 — v2, 2026-04-23.  Still first-principles but now incorporates the
non-obvious levers that past work showed were essential.  Target: ≥140k/day
on local_bundles_profile.json (real-calibration proxy for official).

Non-obvious levers (that a blank-state claude would miss):

    1. MM passive size must be HIGH (~75) not small (~20) — saturation is
       at 75, depths below that leave ~50k/day on the table.  Rationale:
       the local passive-fill calibration rewards bucket "5_12" and
       "gt_12" price-point order sizes; size = 75 sits in gt_12 and also
       handles the case where the rebound tick fills our whole quote.

    2. ACO fair = ANCHOR 10000 clipped, NOT pure micro-price.  The L1
       imbalance alpha only lives in walked states (spread > 16); at
       spread = 16 (≈58% of data) imbalance ↔ Δmid is noise.  Using
       pure micro at spread=16 degrades PnL.

    3. Walked-side EXTRA quote of size 55 on ACO (12 on IPR) when spread
       > typical.  Captures the +1.4-2.4 rebound on the walked side.

    4. IPR early-accumulation window of 2000 ticks at up to 20 qty/tick:
       buy anything at or below benchmark to load the +80 drift-carry
       position fast.

    5. IPR 2-level passive bids at bid+1 and bid+2 when spread > 4 — you
       get two priority slots so you don't get queued out.

    6. Inventory skew (ACO): fair -= 0.06 * pos shifts posted bids/asks
       away from adverse inventory.  Cheap and automatic flattening.

Generative-process hypotheses confirmed by per-day §0.2 numbers:

    ACO: stationary around 10_000 + mean-reverting noise sd ≈ 5 around
        the anchor.  Residual sd "387-468" in first-principles scan was
        the sd around the *drift line*; actual sd around the 10_000
        anchor is ≈ 5 (IPR noise sd ≈ 2 around drift).

        Wait — that's only true if you detrend.  For ACO the drift is
        near zero so "drift line" ≈ constant, but residual sd of 387 in
        the first scan is inflated by wide-spread outlier ticks.  The
        clipped anchor at 10_000 avoids that trap.

    IPR: drift +0.001 per ts, residual sd ≈ 2-3 around drift.

Two knobs per product (§8):  ACO_MM_SIZE, ACO_WALKED_EXTRA;
  IPR_SOFT_TARGET, IPR_PASSIVE_SIZE.  Everything else is derived.
"""
from typing import Dict, List, Optional
import json
import math

from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
    MAF_BID = 15_000

    # ACO
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

    # IPR
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

    # Imbalance gates
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
        bb = max(buys)
        ba = min(sells)
        bv, av = buys[bb], sells[ba]
        tot = bv + av
        imb = (bv - av) / tot if tot else 0.0
        spread = ba - bb
        # Spread-gated micro: when spread is at or below the MM's typical
        # spread, L1 imbalance is NOT predictive (see research log
        # 2026-04-23) — fall back to the touch midpoint.
        if spread <= spread_gate_mid:
            micro = 0.5 * (bb + ba)
        else:
            micro = (ba * bv + bb * av) / tot if tot else 0.5 * (bb + ba)
        return {
            "buys": dict(sorted(buys.items(), reverse=True)),
            "sells": dict(sorted(sells.items())),
            "bb": bb,
            "ba": ba,
            "imb": imb,
            "micro": micro,
            "spread": spread,
        }

    def _walked_fair(self, bb: int, ba: int, micro: float, anchor: float,
                     typical: int, clip: float) -> float:
        spread = ba - bb
        if spread <= typical:
            return anchor + max(-clip, min(clip, micro - anchor))
        bid_gap = anchor - bb
        ask_gap = ba - anchor
        half = typical / 2
        if bid_gap > ask_gap + 0.5:
            trusted = ba - half
        elif ask_gap > bid_gap + 0.5:
            trusted = bb + half
        else:
            trusted = 0.5 * (bb + ba)
        return anchor + max(-clip, min(clip, trusted - anchor))

    def _trade_aco(self, od: OrderDepth, pos: int, ts: int) -> List[Order]:
        prod = "ASH_COATED_OSMIUM"
        limit = self.LIMITS[prod]
        book = self._book(od, self.ACO_TYPICAL_SPREAD)
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        micro = book["micro"]
        imb = book["imb"]
        spread = book["spread"]
        fair = self._walked_fair(bb, ba, micro, float(self.ACO_FAIR),
                                 self.ACO_TYPICAL_SPREAD, self.ACO_WALKED_FAIR_CLIP)
        orders: List[Order] = []

        # Takes with inventory skew
        skewed = fair - self.ACO_INV_SKEW * pos
        for ap, av in book["sells"].items():
            if limit - pos <= 0:
                break
            if ap <= skewed:
                qty = min(av, limit - pos)
                if qty > 0:
                    orders.append(Order(prod, ap, qty))
                    pos += qty
        for bp, bv in book["buys"].items():
            if limit + pos <= 0:
                break
            skewed = fair - self.ACO_INV_SKEW * pos
            if bp >= skewed:
                qty = min(bv, limit + pos)
                if qty > 0:
                    orders.append(Order(prod, bp, -qty))
                    pos -= qty

        # Passive MM — penny inside when wide.
        skewed = fair - self.ACO_INV_SKEW * pos
        if spread >= self.ACO_WIDE_SPREAD:
            bid_px = min(bb + 1, math.floor(skewed - self.ACO_PENNY_EDGE))
            ask_px = max(ba - 1, math.ceil(skewed + self.ACO_PENNY_EDGE))
        else:
            bid_px = math.floor(skewed - self.ACO_MM_OFFSET)
            ask_px = math.ceil(skewed + self.ACO_MM_OFFSET)
        bid_px = min(int(bid_px), ba - 1, math.floor(fair) - 1)
        ask_px = max(int(ask_px), bb + 1, math.ceil(fair) + 1)

        buy_cap = max(0, limit - pos)
        sell_cap = max(0, limit + pos)
        bid_sz = min(self.ACO_MM_SIZE, buy_cap)
        ask_sz = min(self.ACO_MM_SIZE, sell_cap)

        if imb > self.IMB_STRONG:
            ask_sz = max(0, int(round(ask_sz * self.IMB_SHRINK)))
            bid_sz = min(buy_cap, int(round(bid_sz * self.IMB_BOOST)))
        elif imb < -self.IMB_STRONG:
            bid_sz = max(0, int(round(bid_sz * self.IMB_SHRINK)))
            ask_sz = min(sell_cap, int(round(ask_sz * self.IMB_BOOST)))

        if bid_px < ask_px:
            if bid_sz > 0:
                orders.append(Order(prod, bid_px, bid_sz))
            if ask_sz > 0:
                orders.append(Order(prod, ask_px, -ask_sz))

        # Walked-rebound extra quote.
        if spread > self.ACO_TYPICAL_SPREAD:
            bid_gap = self.ACO_FAIR - bb
            ask_gap = ba - self.ACO_FAIR
            if bid_gap > ask_gap + 0.5 and pos < limit:
                walked_px = bb + 1
                if walked_px < math.floor(fair):
                    sz = min(self.ACO_WALKED_EXTRA, limit - pos)
                    if sz > 0 and walked_px != bid_px:
                        orders.append(Order(prod, walked_px, sz))
            elif ask_gap > bid_gap + 0.5 and pos > -limit:
                walked_px = ba - 1
                if walked_px > math.ceil(fair):
                    sz = min(self.ACO_WALKED_EXTRA, limit + pos)
                    if sz > 0 and walked_px != ask_px:
                        orders.append(Order(prod, walked_px, -sz))

        return orders

    def _trade_ipr(self, od: OrderDepth, pos: int, ts: int) -> List[Order]:
        prod = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[prod]
        book = self._book(od, self.IPR_TYPICAL_SPREAD - 1)  # use micro even at typical
        if not book:
            return []
        bb, ba = book["bb"], book["ba"]
        micro = book["micro"]
        imb = book["imb"]
        spread = book["spread"]
        # Benchmark = drift-corrected anchor (using the first observed micro
        # would require state — approximate with current mid minus drift to
        # ts; the +0.001 slope gives us a clean level per timestamp).  Pass
        # benchmark=current_micro so walked-fair just uses micro as anchor.
        benchmark = micro
        fair = self._walked_fair(bb, ba, micro, benchmark,
                                 self.IPR_TYPICAL_SPREAD, self.IPR_WALKED_FAIR_CLIP)
        orders: List[Order] = []

        # End-of-day unwind (IPR drift keeps going up — only unwind
        # very last 1% of day and only if bid at/near benchmark).
        if ts >= self.IPR_UNWIND_START:
            if pos > 0 and bb >= benchmark - 1:
                qty = min(pos, book["buys"].get(bb, 0), self.IPR_UNWIND_SIZE)
                if qty > 0:
                    orders.append(Order(prod, bb, -qty))
            return orders

        take_fair = max(benchmark, fair)

        # Early-window aggressive accumulation.
        if ts <= self.IPR_EARLY_WINDOW and pos < self.IPR_TARGET:
            for ap, av in book["sells"].items():
                if pos >= self.IPR_TARGET:
                    break
                if ap <= take_fair:
                    qty = min(av, self.IPR_TARGET - pos, limit - pos, self.IPR_EARLY_MAX_QTY)
                    if qty > 0:
                        orders.append(Order(prod, ap, qty))
                        pos += qty
                else:
                    break

        # Ongoing take up to soft target.
        if pos < self.IPR_SOFT_TARGET:
            for ap, av in book["sells"].items():
                if pos >= self.IPR_SOFT_TARGET:
                    break
                if ap <= take_fair:
                    qty = min(av, self.IPR_SOFT_TARGET - pos, limit - pos)
                    if qty > 0:
                        orders.append(Order(prod, ap, qty))
                        pos += qty
                else:
                    break

        # 2-level passive bid inside the spread (skip if imbalance says
        # the book is about to drop).
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
                    secondary_px = min(bb + 2, ba - 1)
                    if secondary_px > primary_px:
                        sec_sz = min(self.IPR_PASSIVE_SECOND, limit - pos - primary_sz)
                        if sec_sz > 0:
                            orders.append(Order(prod, secondary_px, sec_sz))

        # Walked-rebound extra quote.
        if spread > self.IPR_TYPICAL_SPREAD:
            bid_gap = benchmark - bb
            ask_gap = ba - benchmark
            if bid_gap > ask_gap + 0.5 and pos < limit:
                walked_px = bb + 1
                if walked_px < fair:
                    sz = min(self.IPR_WALKED_EXTRA, limit - pos)
                    if sz > 0:
                        orders.append(Order(prod, walked_px, sz))
            elif ask_gap > bid_gap + 0.5 and pos > 0:
                walked_px = ba - 1
                if walked_px > fair:
                    sz = min(self.IPR_WALKED_EXTRA, pos)
                    if sz > 0:
                        orders.append(Order(prod, walked_px, -sz))

        return orders

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self._trade_aco(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
                state.timestamp,
            )
        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            result["INTARIAN_PEPPER_ROOT"] = self._trade_ipr(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                state.timestamp,
            )
        return result, 0, state.traderData or ""
