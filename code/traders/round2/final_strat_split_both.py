"""Round 2 final submission.

Merges the best-validated round 1 core (core70 + clipped ACO fair) with the
round 2 adaptations from current_strategy.py:
  - early anchor re-centering so the path is not pinned to a stale opening
  - ACO late-session unwind to close near flat
  - rich-regime passive throttle on PEPPER
  - adaptive PEPPER core band (disabled at width 0 — keeps the validated 70)

MAF_BID is the one-time Market Access Fee for the blind auction.  A bid of
15 000 is expected to finish in the top 50 % of the field while leaving a
comfortable positive net on the extra 25 % order-book access.
"""

import json
import math
from typing import Any, Dict, List, Optional

from datamodel import Order, OrderDepth, TradingState


class Trader:
    # ── Market Access Fee blind auction ──────────────────────────────────────
    MAF_BID = 15_000

    # ── Position limits ──────────────────────────────────────────────────────
    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    # ── ASH_COATED_OSMIUM ────────────────────────────────────────────────────
    # Structural fair at 10 000 with a small clipped local recenter.
    # Promoted in round 1 log: +4 231 official-hybrid / +4 025 same-tick.
    ACO_FAIR_VALUE = 10_000
    ACO_FAIR_ADJUST_CLIP = 2.0
    ACO_TAKE_EDGE = 0.0
    ACO_REDUCE_EDGE = 1.0
    ACO_PENNY_EDGE = 1.5
    ACO_INVENTORY_SKEW_PER_UNIT = 0.06
    ACO_MAX_POST_SIZE = 19
    ACO_PASSIVE_SPLIT_PRIMARY = 10
    ACO_PASSIVE_SPLIT_SECONDARY = 9
    ACO_PASSIVE_OFFSET = 3.5
    ACO_LATE_UNWIND_START = 98_500
    ACO_LATE_UNWIND_TARGET = 16
    ACO_LATE_UNWIND_MAX_QTY = 8
    ACO_LATE_UNWIND_EDGE = 1.0

    # ── INTARIAN_PEPPER_ROOT ─────────────────────────────────────────────────
    # core70 was the round 1 optimum (314 454 official-hybrid / 292 669 same-tick).
    # Band width 0 keeps the target fixed at exactly 70.
    IPR_DRIFT_PER_TIMESTAMP = 0.001
    IPR_EARLY_TAKE_TARGET = 64
    IPR_BASE_CORE_TARGET = 70
    IPR_CORE_TARGET_BAND = 0
    IPR_CHEAP_ZSCORE = -0.45
    IPR_RICH_ZSCORE = 0.80
    IPR_BAND_SELL_EDGE = 3.0
    IPR_BAND_RELOAD_EDGE = 1.0
    IPR_BAND_QTY = 6
    IPR_PASSIVE_BID_SIZE = 10
    IPR_EARLY_TAKE_WINDOW = 500
    IPR_VAR_ALPHA = 0.06
    IPR_BOTTOM_ZSCORE_THRESHOLD = -1.10
    IPR_BOTTOM_EXTRA_QTY = 4
    IPR_BOTTOM_PATH_CAP = 1.5
    IPR_RICH_RELOAD_QTY = 2
    IPR_RICH_PASSIVE_BID_SIZE = 4
    IPR_PASSIVE_SPLIT_PRIMARY = 5
    IPR_PASSIVE_SPLIT_SECONDARY = 5
    IPR_ANCHOR_UPDATE_END = 12_000
    IPR_ANCHOR_UPDATE_ALPHA = 0.02
    IPR_ANCHOR_RESIDUAL_CLIP = 3.0
    IPR_COMPLETION_BID_DISTANCE = 2
    IPR_COMPLETION_BID_SIZE = 3
    IPR_COMPLETION_WINDOW_START = 500
    IPR_COMPLETION_WINDOW_END = 33_333

    def bid(self) -> int:
        return self.MAF_BID

    def run(self, state: TradingState):
        saved = self._load_state(state.traderData)
        last_ts = saved.get("last_ts")
        day_reset = last_ts is not None and state.timestamp < last_ts

        result: Dict[str, List[Order]] = {}

        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self._trade_aco(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
                state.timestamp,
            )

        ipr_anchor = saved.get("ipr_anchor")
        ipr_var = float(saved.get("ipr_var", 9.0))
        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            book = self._book_state(state.order_depths["INTARIAN_PEPPER_ROOT"])
            if book is not None:
                touch_mid = 0.5 * (book["best_bid"] + book["best_ask"])
                ipr_anchor = self._update_ipr_anchor(
                    ipr_anchor, touch_mid, state.timestamp, day_reset
                )
                residual = touch_mid - (
                    float(ipr_anchor) + self.IPR_DRIFT_PER_TIMESTAMP * state.timestamp
                )
                ipr_var = (
                    (1.0 - self.IPR_VAR_ALPHA) * ipr_var
                    + self.IPR_VAR_ALPHA * residual * residual
                )
            ipr_orders, ipr_anchor = self._trade_ipr(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                ipr_anchor,
                state.timestamp,
                ipr_var,
            )
            result["INTARIAN_PEPPER_ROOT"] = ipr_orders

        trader_data = json.dumps(
            {"ipr_anchor": ipr_anchor, "ipr_var": ipr_var, "last_ts": state.timestamp},
            separators=(",", ":"),
        )
        return result, 0, trader_data

    def _load_state(self, trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return {"ipr_anchor": None, "last_ts": None}
        try:
            payload = json.loads(trader_data)
        except Exception:
            return {"ipr_anchor": None, "ipr_var": 9.0, "last_ts": None}
        return {
            "ipr_anchor": payload.get("ipr_anchor"),
            "ipr_var": float(payload.get("ipr_var", 9.0)),
            "last_ts": payload.get("last_ts"),
        }

    def _sorted_buy_orders(self, order_depth: OrderDepth) -> Dict[int, int]:
        return {
            int(p): abs(int(v))
            for p, v in sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)
        }

    def _sorted_sell_orders(self, order_depth: OrderDepth) -> Dict[int, int]:
        return {
            int(p): abs(int(v))
            for p, v in sorted(order_depth.sell_orders.items(), key=lambda x: x[0])
        }

    def _book_state(self, order_depth: OrderDepth) -> Optional[Dict[str, Any]]:
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None
        buys = self._sorted_buy_orders(order_depth)
        sells = self._sorted_sell_orders(order_depth)
        if not buys or not sells:
            return None
        best_bid = max(buys)
        best_ask = min(sells)
        return {
            "buy_orders": buys,
            "sell_orders": sells,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": best_ask - best_bid,
        }

    def _cap_post_size(self, base: int, pos: int, side: str, cap: int) -> int:
        size = base
        if side == "buy" and pos > 0:
            size = max(2, size - pos // 10)
        elif side == "sell" and pos < 0:
            size = max(2, size - abs(pos) // 10)
        return max(0, min(cap, size))

    def _update_ipr_anchor(
        self,
        anchor: Optional[float],
        touch_mid: float,
        timestamp: int,
        day_reset: bool,
    ) -> float:
        observed = touch_mid - self.IPR_DRIFT_PER_TIMESTAMP * timestamp
        if anchor is None or day_reset:
            return observed
        if timestamp <= self.IPR_ANCHOR_UPDATE_END:
            delta = max(
                -self.IPR_ANCHOR_RESIDUAL_CLIP,
                min(self.IPR_ANCHOR_RESIDUAL_CLIP, observed - float(anchor)),
            )
            return float(anchor) + self.IPR_ANCHOR_UPDATE_ALPHA * delta
        return float(anchor)

    def _trade_aco(
        self, order_depth: OrderDepth, position: int, timestamp: int
    ) -> List[Order]:
        orders: List[Order] = []
        product = "ASH_COATED_OSMIUM"
        limit = self.LIMITS[product]

        book = self._book_state(order_depth)
        if book is None:
            return orders

        buys = book["buy_orders"]
        sells = book["sell_orders"]
        best_bid = int(book["best_bid"])
        best_ask = int(book["best_ask"])
        spread = int(book["spread"])
        touch_mid = 0.5 * (best_bid + best_ask)

        fair_adj = max(
            -self.ACO_FAIR_ADJUST_CLIP,
            min(self.ACO_FAIR_ADJUST_CLIP, touch_mid - self.ACO_FAIR_VALUE),
        )
        fair = float(self.ACO_FAIR_VALUE) + fair_adj
        pos = position

        for ask, vol in sells.items():
            if limit - pos <= 0:
                break
            skewed = fair - self.ACO_INVENTORY_SKEW_PER_UNIT * pos
            if ask <= skewed - self.ACO_TAKE_EDGE:
                qty = min(vol, limit - pos)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    pos += qty
            elif pos < 0 and ask <= skewed + self.ACO_REDUCE_EDGE:
                qty = min(vol, limit - pos, abs(pos))
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    pos += qty

        for bid, vol in buys.items():
            if limit + pos <= 0:
                break
            skewed = fair - self.ACO_INVENTORY_SKEW_PER_UNIT * pos
            if bid >= skewed + self.ACO_TAKE_EDGE:
                qty = min(vol, limit + pos)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    pos -= qty
            elif pos > 0 and bid >= skewed - self.ACO_REDUCE_EDGE:
                qty = min(vol, limit + pos, pos)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    pos -= qty

        if timestamp >= self.ACO_LATE_UNWIND_START:
            if (
                pos > self.ACO_LATE_UNWIND_TARGET
                and best_bid >= math.floor(fair - self.ACO_LATE_UNWIND_EDGE)
            ):
                qty = min(
                    self.ACO_LATE_UNWIND_MAX_QTY,
                    pos - self.ACO_LATE_UNWIND_TARGET,
                    abs(int(buys[best_bid])),
                )
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))
                    pos -= qty
            elif (
                pos < -self.ACO_LATE_UNWIND_TARGET
                and best_ask <= math.ceil(fair + self.ACO_LATE_UNWIND_EDGE)
            ):
                qty = min(
                    self.ACO_LATE_UNWIND_MAX_QTY,
                    abs(pos) - self.ACO_LATE_UNWIND_TARGET,
                    abs(int(sells[best_ask])),
                )
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
                    pos += qty

        skewed = fair - self.ACO_INVENTORY_SKEW_PER_UNIT * pos
        buy_cap = max(0, limit - pos)
        sell_cap = max(0, limit + pos)
        bid_sz = self._cap_post_size(self.ACO_MAX_POST_SIZE, pos, "buy", buy_cap)
        ask_sz = self._cap_post_size(self.ACO_MAX_POST_SIZE, pos, "sell", sell_cap)

        if spread >= 8:
            bid_px = min(best_bid + 1, math.floor(skewed - self.ACO_PENNY_EDGE))
            ask_px = max(best_ask - 1, math.ceil(skewed + self.ACO_PENNY_EDGE))
        else:
            bid_px = math.floor(skewed - self.ACO_PASSIVE_OFFSET)
            ask_px = math.ceil(skewed + self.ACO_PASSIVE_OFFSET)

        bid_px = min(int(bid_px), best_ask - 1, math.floor(fair) - 1)
        ask_px = max(int(ask_px), best_bid + 1, math.ceil(fair) + 1)

        if bid_px < ask_px:
            if bid_sz > 0:
                primary = min(self.ACO_PASSIVE_SPLIT_PRIMARY, bid_sz)
                secondary = min(self.ACO_PASSIVE_SPLIT_SECONDARY, max(0, bid_sz - primary))
                if primary > 0:
                    orders.append(Order(product, bid_px, primary))
                if secondary > 0:
                    orders.append(Order(product, bid_px, secondary))
            if ask_sz > 0:
                primary = min(self.ACO_PASSIVE_SPLIT_PRIMARY, ask_sz)
                secondary = min(self.ACO_PASSIVE_SPLIT_SECONDARY, max(0, ask_sz - primary))
                if primary > 0:
                    orders.append(Order(product, ask_px, -primary))
                if secondary > 0:
                    orders.append(Order(product, ask_px, -secondary))

        return orders

    def _trade_ipr(
        self,
        order_depth: OrderDepth,
        position: int,
        anchor: Optional[float],
        timestamp: int,
        ipr_var: float,
    ):
        orders: List[Order] = []
        product = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[product]

        book = self._book_state(order_depth)
        if book is None:
            return orders, anchor

        buys = book["buy_orders"]
        sells = book["sell_orders"]
        best_bid = int(book["best_bid"])
        best_ask = int(book["best_ask"])
        spread = int(book["spread"])
        touch_mid = 0.5 * (best_bid + best_ask)

        if anchor is None:
            anchor = touch_mid - self.IPR_DRIFT_PER_TIMESTAMP * timestamp

        benchmark = float(anchor) + self.IPR_DRIFT_PER_TIMESTAMP * timestamp
        sigma = max(1.0, math.sqrt(max(0.0, float(ipr_var))))
        zscore = (touch_mid - benchmark) / sigma

        band = self.IPR_CORE_TARGET_BAND
        base = self.IPR_BASE_CORE_TARGET
        if band > 0:
            if zscore <= self.IPR_CHEAP_ZSCORE:
                core_target = base + band
            elif zscore >= self.IPR_RICH_ZSCORE:
                core_target = base - band
            else:
                core_target = base
        else:
            core_target = base

        pos = position
        sold_this_tick = False

        if timestamp <= self.IPR_EARLY_TAKE_WINDOW:
            for ask, vol in sells.items():
                if pos >= self.IPR_EARLY_TAKE_TARGET:
                    break
                cap = limit - pos
                if cap <= 0:
                    break
                qty = min(vol, cap, self.IPR_EARLY_TAKE_TARGET - pos, 12)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    pos += qty

        excess = max(0, pos - core_target)
        if excess > 0 and best_bid >= benchmark + self.IPR_BAND_SELL_EDGE:
            qty = min(excess, self.IPR_BAND_QTY, abs(int(buys[best_bid])))
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                pos -= qty
                sold_this_tick = True

        if pos < limit and best_ask <= benchmark + self.IPR_BAND_RELOAD_EDGE:
            reload_cap = self.IPR_BAND_QTY
            if pos >= core_target and zscore >= self.IPR_RICH_ZSCORE:
                reload_cap = self.IPR_RICH_RELOAD_QTY
            qty = min(limit - pos, reload_cap, abs(int(sells[best_ask])))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                pos += qty

        if (not sold_this_tick) and pos < limit and spread > 2:
            bid_px = min(best_bid + 1, best_ask - 1)
            bid_qty = min(self.IPR_PASSIVE_BID_SIZE, limit - pos)
            shortfall = max(0, core_target - pos)
            if shortfall <= 0 and zscore >= self.IPR_RICH_ZSCORE:
                bid_qty = min(bid_qty, self.IPR_RICH_PASSIVE_BID_SIZE)
            elif shortfall > 0:
                bid_qty = min(bid_qty, max(4, shortfall))
            if bid_qty > 0 and bid_px < best_ask:
                primary = min(self.IPR_PASSIVE_SPLIT_PRIMARY, bid_qty)
                secondary = min(self.IPR_PASSIVE_SPLIT_SECONDARY, max(0, bid_qty - primary))
                if primary > 0:
                    orders.append(Order(product, bid_px, primary))
                if secondary > 0:
                    orders.append(Order(product, bid_px, secondary))

                if (
                    self.IPR_COMPLETION_WINDOW_START <= timestamp < self.IPR_COMPLETION_WINDOW_END
                    and spread > self.IPR_COMPLETION_BID_DISTANCE
                ):
                    comp_px = min(best_bid + self.IPR_COMPLETION_BID_DISTANCE, best_ask - 1)
                    if comp_px > bid_px:
                        comp_shortfall = core_target - pos - bid_qty
                        remaining = limit - pos - bid_qty
                        comp_qty = max(0, min(self.IPR_COMPLETION_BID_SIZE, comp_shortfall, remaining))
                        if comp_qty > 0:
                            orders.append(Order(product, comp_px, comp_qty))

        current_buy = sum(max(0, int(o.quantity)) for o in orders)
        current_sell = sum(max(0, -int(o.quantity)) for o in orders)
        pos_after = position + current_buy - current_sell
        if (
            timestamp > self.IPR_EARLY_TAKE_WINDOW
            and pos_after < limit
            and zscore <= self.IPR_BOTTOM_ZSCORE_THRESHOLD
            and best_ask <= benchmark + self.IPR_BOTTOM_PATH_CAP
        ):
            dip_cap = self.IPR_BOTTOM_EXTRA_QTY
            if pos_after < core_target:
                dip_cap += min(2, core_target - pos_after)
            qty = min(dip_cap, limit - pos_after, abs(int(sells[best_ask])))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        return orders, anchor
