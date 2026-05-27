"""Round 2 standalone trader tuned for the matured quote regime.

Key changes from the promoted round 1 baseline:
- smaller PEPPER opening/core inventory so missed quotes do not pin us at +80
- early anchor recentering for PEPPER when the new day opens off the old path
- passive PEPPER asks when overweight, since official inside-spread fills were
  much better than touch-taking sells
- late-session reload stop and explicit PEPPER unwind
- more selective ACO touch-taking and slightly tighter passive quoting

The blind Market Access Fee bid stays conservative by default. Local/public
replays ignore it anyway, so treat `MAF_BID` as a deployment constant.
"""

import json
import math
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState


class Trader:
    MAF_BID = 0

    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    # ASH_COATED_OSMIUM: keep the same fixed-fair shape, but reduce adverse
    # touch-taking and lean slightly more on passive fills.
    ACO_FAIR_VALUE = 10000
    ACO_FAIR_ADJUST_CLIP = 2.0
    ACO_TAKE_EDGE = 0.0
    ACO_REDUCE_EDGE = 1.0
    ACO_PENNY_EDGE = 1.5
    ACO_INVENTORY_SKEW_PER_UNIT = 0.06
    ACO_MAX_POST_SIZE = 19
    ACO_PASSIVE_OFFSET = 3.5
    ACO_LATE_UNWIND_START = 99_500
    ACO_LATE_UNWIND_TARGET = 12
    ACO_LATE_UNWIND_MAX_QTY = 12
    ACO_LATE_UNWIND_EDGE = 1.0

    # INTARIAN_PEPPER_ROOT: smaller carry, adaptive anchor, and explicit
    # overweight liquidation for the round 2 tape.
    IPR_DRIFT_PER_TIMESTAMP = 0.001
    IPR_EARLY_TAKE_TARGET = 60
    IPR_EARLY_TAKE_CLIP = 10
    IPR_BASE_CORE_TARGET = 67
    IPR_CORE_TARGET_BAND = 1
    IPR_CHEAP_ZSCORE = -0.45
    IPR_RICH_ZSCORE = 0.80
    IPR_BAND_SELL_EDGE = 2.0
    IPR_OVERWEIGHT_SELL_EDGE = 1.0
    IPR_BAND_RELOAD_EDGE = 1.0
    IPR_OVERWEIGHT_RELOAD_EDGE = 0.5
    IPR_BAND_QTY = 6
    IPR_PASSIVE_BID_SIZE = 10
    IPR_PASSIVE_ASK_SIZE = 4
    IPR_PASSIVE_ASK_PATH_EDGE = 2.0
    IPR_RELOAD_BUFFER = 8
    IPR_DIP_BUFFER = 10
    IPR_EARLY_TAKE_WINDOW = 500
    IPR_VAR_ALPHA = 0.06
    IPR_BOTTOM_ZSCORE_THRESHOLD = -1.15
    IPR_BOTTOM_EXTRA_QTY = 4
    IPR_BOTTOM_PATH_CAP = 1.5
    IPR_COMPLETION_BID_DISTANCE = 2
    IPR_COMPLETION_BID_SIZE = 2
    IPR_COMPLETION_WINDOW_START = 500
    IPR_COMPLETION_WINDOW_END = 33_333
    IPR_ANCHOR_UPDATE_END = 12_000
    IPR_ANCHOR_UPDATE_ALPHA = 0.02
    IPR_ANCHOR_RESIDUAL_CLIP = 3.0
    IPR_RICH_RELOAD_QTY = 2
    IPR_RICH_PASSIVE_BID_SIZE = 4
    IPR_NO_RELOAD_START = 93_000
    IPR_LATE_UNWIND_START = 98_000
    IPR_LATE_UNWIND_TARGET = 56
    IPR_LATE_UNWIND_MAX_QTY = 18
    IPR_FINAL_UNWIND_START = 99_500
    IPR_FINAL_UNWIND_TARGET = 0
    IPR_FINAL_UNWIND_MAX_QTY = 80

    def bid(self):
        return self.MAF_BID

    def run(self, state: TradingState):
        saved_state = self._load_state(state.traderData)
        last_ts = saved_state.get("last_ts")
        day_reset = last_ts is not None and state.timestamp < last_ts

        result: Dict[str, List[Order]] = {}

        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self.trade_aco_matured(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
                state.timestamp,
            )

        ipr_anchor = saved_state.get("ipr_anchor")
        ipr_var = float(saved_state.get("ipr_var", 9.0))
        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            ipr_state = self._book_state(state.order_depths["INTARIAN_PEPPER_ROOT"])
            if ipr_state is not None:
                touch_mid = 0.5 * (ipr_state["best_bid"] + ipr_state["best_ask"])
                ipr_anchor = self._update_ipr_anchor(
                    ipr_anchor,
                    touch_mid,
                    state.timestamp,
                    day_reset,
                )
                residual = touch_mid - (
                    float(ipr_anchor) + self.IPR_DRIFT_PER_TIMESTAMP * state.timestamp
                )
                ipr_var = (
                    (1.0 - self.IPR_VAR_ALPHA) * ipr_var
                    + self.IPR_VAR_ALPHA * (residual * residual)
                )

            ipr_orders, ipr_anchor = self.trade_ipr_matured(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                ipr_anchor,
                state.timestamp,
                day_reset,
                ipr_var,
            )
            result["INTARIAN_PEPPER_ROOT"] = ipr_orders

        trader_data = json.dumps(
            {
                "ipr_anchor": ipr_anchor,
                "ipr_var": ipr_var,
                "last_ts": state.timestamp,
            },
            separators=(",", ":"),
        )
        return result, 0, trader_data

    def _load_state(self, trader_data: str) -> Dict[str, Any]:
        if not trader_data:
            return {"ipr_anchor": None, "ipr_var": 9.0, "last_ts": None}
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
            int(price): abs(int(volume))
            for price, volume in sorted(
                order_depth.buy_orders.items(),
                key=lambda item: item[0],
                reverse=True,
            )
        }

    def _sorted_sell_orders(self, order_depth: OrderDepth) -> Dict[int, int]:
        return {
            int(price): abs(int(volume))
            for price, volume in sorted(order_depth.sell_orders.items(), key=lambda item: item[0])
        }

    def _book_state(self, order_depth: OrderDepth) -> Optional[Dict[str, Any]]:
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None

        buy_orders = self._sorted_buy_orders(order_depth)
        sell_orders = self._sorted_sell_orders(order_depth)
        if not buy_orders or not sell_orders:
            return None

        best_bid = max(buy_orders.keys())
        best_ask = min(sell_orders.keys())

        return {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": best_ask - best_bid,
        }

    def _cap_post_size(self, base_size: int, working_position: int, side: str, capacity: int) -> int:
        size = base_size
        if side == "buy" and working_position > 0:
            size = max(2, size - working_position // 10)
        elif side == "sell" and working_position < 0:
            size = max(2, size - abs(working_position) // 10)
        return max(0, min(capacity, size))

    def _update_ipr_anchor(
        self,
        anchor: Optional[float],
        touch_mid: float,
        timestamp: int,
        day_reset: bool,
    ) -> float:
        observed_anchor = touch_mid - self.IPR_DRIFT_PER_TIMESTAMP * timestamp
        if anchor is None or day_reset:
            return observed_anchor

        updated_anchor = float(anchor)
        if timestamp <= self.IPR_ANCHOR_UPDATE_END:
            delta = observed_anchor - updated_anchor
            delta = max(-self.IPR_ANCHOR_RESIDUAL_CLIP, min(self.IPR_ANCHOR_RESIDUAL_CLIP, delta))
            updated_anchor += self.IPR_ANCHOR_UPDATE_ALPHA * delta
        return updated_anchor

    def _adaptive_core_target(self, zscore: float) -> int:
        target = self.IPR_BASE_CORE_TARGET
        if zscore <= self.IPR_CHEAP_ZSCORE:
            target += self.IPR_CORE_TARGET_BAND
        elif zscore >= self.IPR_RICH_ZSCORE:
            target -= self.IPR_CORE_TARGET_BAND

        low = self.IPR_BASE_CORE_TARGET - self.IPR_CORE_TARGET_BAND
        high = self.IPR_BASE_CORE_TARGET + self.IPR_CORE_TARGET_BAND
        return max(low, min(high, target))

    def _completion_bid_qty(
        self,
        timestamp: int,
        working_position: int,
        primary_bid_qty: int,
        core_target: int,
        spread: int,
    ) -> int:
        if self.IPR_COMPLETION_BID_SIZE <= 0:
            return 0
        if not (self.IPR_COMPLETION_WINDOW_START <= timestamp < self.IPR_COMPLETION_WINDOW_END):
            return 0
        if spread <= self.IPR_COMPLETION_BID_DISTANCE:
            return 0

        shortfall_to_core = core_target - working_position - primary_bid_qty
        if shortfall_to_core <= 0:
            return 0

        return max(
            0,
            min(
                self.IPR_COMPLETION_BID_SIZE,
                shortfall_to_core,
            ),
        )

    def _sell_into_bids(
        self,
        product: str,
        buy_orders: Dict[int, int],
        working_position: int,
        target_position: int,
        max_qty: int,
    ) -> Tuple[List[Order], int]:
        orders: List[Order] = []
        qty_remaining = min(max_qty, max(0, working_position - target_position))

        for bid_price, bid_volume in buy_orders.items():
            if qty_remaining <= 0:
                break
            qty = min(qty_remaining, abs(int(bid_volume)))
            if qty <= 0:
                continue
            orders.append(Order(product, bid_price, -qty))
            working_position -= qty
            qty_remaining -= qty

        return orders, working_position

    def trade_aco_matured(
        self,
        order_depth: OrderDepth,
        position: int,
        timestamp: int,
    ) -> List[Order]:
        orders: List[Order] = []
        product = "ASH_COATED_OSMIUM"
        limit = self.LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders

        buy_orders: Dict[int, int] = state["buy_orders"]
        sell_orders: Dict[int, int] = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        spread = int(state["spread"])
        touch_mid = 0.5 * (best_bid + best_ask)

        fair_adjustment = max(
            -self.ACO_FAIR_ADJUST_CLIP,
            min(self.ACO_FAIR_ADJUST_CLIP, touch_mid - self.ACO_FAIR_VALUE),
        )
        fair_value = float(self.ACO_FAIR_VALUE) + fair_adjustment
        working_position = position

        for ask_price, ask_volume in sell_orders.items():
            buy_capacity = limit - working_position
            if buy_capacity <= 0:
                break

            fair_skewed = fair_value - self.ACO_INVENTORY_SKEW_PER_UNIT * working_position
            if ask_price <= fair_skewed - self.ACO_TAKE_EDGE:
                qty = min(ask_volume, buy_capacity)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty
            elif working_position < 0 and ask_price <= fair_skewed + self.ACO_REDUCE_EDGE:
                qty = min(ask_volume, buy_capacity, abs(working_position))
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty

        for bid_price, bid_volume in buy_orders.items():
            sell_capacity = limit + working_position
            if sell_capacity <= 0:
                break

            fair_skewed = fair_value - self.ACO_INVENTORY_SKEW_PER_UNIT * working_position
            if bid_price >= fair_skewed + self.ACO_TAKE_EDGE:
                qty = min(bid_volume, sell_capacity)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    working_position -= qty
            elif working_position > 0 and bid_price >= fair_skewed - self.ACO_REDUCE_EDGE:
                qty = min(bid_volume, sell_capacity, working_position)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    working_position -= qty

        if timestamp >= self.ACO_LATE_UNWIND_START:
            if (
                working_position > self.ACO_LATE_UNWIND_TARGET
                and best_bid >= math.floor(fair_value - self.ACO_LATE_UNWIND_EDGE)
            ):
                qty = min(
                    self.ACO_LATE_UNWIND_MAX_QTY,
                    working_position - self.ACO_LATE_UNWIND_TARGET,
                    abs(int(buy_orders[best_bid])),
                )
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))
                    working_position -= qty
            elif (
                working_position < -self.ACO_LATE_UNWIND_TARGET
                and best_ask <= math.ceil(fair_value + self.ACO_LATE_UNWIND_EDGE)
            ):
                qty = min(
                    self.ACO_LATE_UNWIND_MAX_QTY,
                    abs(working_position) - self.ACO_LATE_UNWIND_TARGET,
                    abs(int(sell_orders[best_ask])),
                )
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
                    working_position += qty

        fair_skewed = fair_value - self.ACO_INVENTORY_SKEW_PER_UNIT * working_position
        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)

        bid_size = self._cap_post_size(self.ACO_MAX_POST_SIZE, working_position, "buy", buy_capacity)
        ask_size = self._cap_post_size(self.ACO_MAX_POST_SIZE, working_position, "sell", sell_capacity)

        if spread >= 8:
            bid_price = min(best_bid + 1, math.floor(fair_skewed - self.ACO_PENNY_EDGE))
            ask_price = max(best_ask - 1, math.ceil(fair_skewed + self.ACO_PENNY_EDGE))
        else:
            bid_price = math.floor(fair_skewed - self.ACO_PASSIVE_OFFSET)
            ask_price = math.ceil(fair_skewed + self.ACO_PASSIVE_OFFSET)

        bid_price = min(int(bid_price), best_ask - 1, math.floor(fair_value) - 1)
        ask_price = max(int(ask_price), best_bid + 1, math.ceil(fair_value) + 1)

        if bid_price < ask_price:
            if bid_size > 0:
                orders.append(Order(product, bid_price, bid_size))
            if ask_size > 0:
                orders.append(Order(product, ask_price, -ask_size))

        return orders

    def trade_ipr_matured(
        self,
        order_depth: OrderDepth,
        position: int,
        anchor: Optional[float],
        timestamp: int,
        day_reset: bool,
        ipr_var: float,
    ) -> Tuple[List[Order], Optional[float]]:
        orders: List[Order] = []
        product = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[product]

        state = self._book_state(order_depth)
        if state is None:
            return orders, anchor

        buy_orders = state["buy_orders"]
        sell_orders = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        spread = int(state["spread"])

        touch_mid = 0.5 * (best_bid + best_ask)
        if anchor is None or day_reset:
            anchor = touch_mid - self.IPR_DRIFT_PER_TIMESTAMP * timestamp

        benchmark_path = float(anchor) + self.IPR_DRIFT_PER_TIMESTAMP * timestamp
        sigma = max(1.0, math.sqrt(max(0.0, float(ipr_var))))
        residual = touch_mid - benchmark_path
        zscore = residual / sigma
        core_target = self._adaptive_core_target(zscore)

        working_position = position
        sold_this_tick = False
        allow_reloads = timestamp < self.IPR_NO_RELOAD_START
        opening_target = min(core_target, self.IPR_EARLY_TAKE_TARGET)

        if timestamp <= self.IPR_EARLY_TAKE_WINDOW:
            for ask_price, ask_volume in sell_orders.items():
                if working_position >= opening_target:
                    break
                buy_capacity = opening_target - working_position
                if buy_capacity <= 0:
                    break
                qty = min(
                    ask_volume,
                    buy_capacity,
                    self.IPR_EARLY_TAKE_CLIP,
                )
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty

        excess_inventory = max(0, working_position - core_target)
        sell_edge = (
            self.IPR_OVERWEIGHT_SELL_EDGE
            if working_position > core_target + self.IPR_CORE_TARGET_BAND
            else self.IPR_BAND_SELL_EDGE
        )
        if excess_inventory > 0 and best_bid >= benchmark_path + sell_edge:
            qty = min(
                excess_inventory,
                self.IPR_BAND_QTY + (2 if zscore >= self.IPR_RICH_ZSCORE else 0),
                abs(int(buy_orders[best_bid])),
            )
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                working_position -= qty
                sold_this_tick = True

        passive_ask_capacity = max(0, working_position - core_target)
        if passive_ask_capacity > 0 and spread > 2:
            ask_price = max(
                best_bid + 1,
                min(best_ask - 1, math.ceil(benchmark_path + self.IPR_PASSIVE_ASK_PATH_EDGE)),
            )
            ask_qty = min(self.IPR_PASSIVE_ASK_SIZE, passive_ask_capacity)
            if ask_qty > 0 and ask_price < best_ask:
                orders.append(Order(product, ask_price, -ask_qty))
                working_position -= ask_qty
                sold_this_tick = True

        unwind_target: Optional[int] = None
        unwind_max_qty = 0
        if timestamp >= self.IPR_FINAL_UNWIND_START:
            unwind_target = self.IPR_FINAL_UNWIND_TARGET
            unwind_max_qty = self.IPR_FINAL_UNWIND_MAX_QTY
        elif timestamp >= self.IPR_LATE_UNWIND_START:
            unwind_target = self.IPR_LATE_UNWIND_TARGET
            unwind_max_qty = self.IPR_LATE_UNWIND_MAX_QTY

        if unwind_target is not None and working_position > unwind_target:
            unwind_orders, working_position = self._sell_into_bids(
                product,
                buy_orders,
                working_position,
                unwind_target,
                unwind_max_qty,
            )
            if unwind_orders:
                orders.extend(unwind_orders)
                sold_this_tick = True

        target_buy_cap = min(limit, core_target + self.IPR_RELOAD_BUFFER)
        reload_edge = (
            self.IPR_OVERWEIGHT_RELOAD_EDGE
            if working_position >= core_target
            else self.IPR_BAND_RELOAD_EDGE
        )
        reload_qty_cap = self.IPR_BAND_QTY
        if zscore >= self.IPR_RICH_ZSCORE and working_position >= core_target:
            reload_qty_cap = self.IPR_RICH_RELOAD_QTY

        buy_capacity = max(0, target_buy_cap - working_position)
        if allow_reloads and buy_capacity > 0 and best_ask <= benchmark_path + reload_edge:
            qty = min(
                buy_capacity,
                reload_qty_cap,
                abs(int(sell_orders[best_ask])),
            )
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                working_position += qty

        passive_buy_capacity = max(0, target_buy_cap - working_position)
        if allow_reloads and (not sold_this_tick) and passive_buy_capacity > 0 and spread > 2:
            bid_price = min(best_bid + 1, best_ask - 1)
            bid_qty = min(self.IPR_PASSIVE_BID_SIZE, passive_buy_capacity)
            shortfall_to_core = max(0, core_target - working_position)
            if zscore >= self.IPR_RICH_ZSCORE and shortfall_to_core <= 0:
                bid_qty = min(bid_qty, self.IPR_RICH_PASSIVE_BID_SIZE)
            elif shortfall_to_core > 0:
                bid_qty = min(bid_qty, max(2, shortfall_to_core))
            if bid_qty > 0 and bid_price < best_ask:
                orders.append(Order(product, bid_price, bid_qty))

                completion_bid_price = min(best_bid + self.IPR_COMPLETION_BID_DISTANCE, best_ask - 1)
                completion_bid_qty = 0
                if completion_bid_price > bid_price and completion_bid_price < best_ask:
                    completion_bid_qty = self._completion_bid_qty(
                        timestamp,
                        working_position,
                        bid_qty,
                        core_target,
                        spread,
                    )
                if completion_bid_qty > 0:
                    orders.append(Order(product, completion_bid_price, completion_bid_qty))

        current_buy = sum(max(0, int(order.quantity)) for order in orders)
        current_sell = sum(max(0, -int(order.quantity)) for order in orders)
        working_after_orders = position + current_buy - current_sell
        dip_cap = min(limit, core_target + self.IPR_DIP_BUFFER)
        if (
            allow_reloads
            and timestamp > self.IPR_EARLY_TAKE_WINDOW
            and working_after_orders < dip_cap
            and zscore <= self.IPR_BOTTOM_ZSCORE_THRESHOLD
            and best_ask <= benchmark_path + self.IPR_BOTTOM_PATH_CAP
        ):
            qty = min(
                self.IPR_BOTTOM_EXTRA_QTY,
                dip_cap - working_after_orders,
                abs(int(sell_orders[best_ask])),
            )
            if qty > 0:
                orders.append(Order(product, best_ask, qty))

        return orders, anchor
