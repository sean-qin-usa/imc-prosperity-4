from datamodel import OrderDepth, TradingState, Order
from typing import Any, Dict, List
import importlib.util
import json
import math
from pathlib import Path


_BASE_PATH = Path(__file__).with_name("tut_try_trades.py")
_BASE_SPEC = importlib.util.spec_from_file_location("tut_try_trades_base", _BASE_PATH)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load baseline trader from {_BASE_PATH}")
_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)
BaseTrader = _BASE_MODULE.Trader


class Trader(BaseTrader):
    # Keep the baseline signal, but gate it by recent trade activity so
    # sparse benchmark prints do less and active historical regimes still
    # get the benefit of trade information.
    TOMATO_TRADE_ACTIVITY_DECAY = 0.82
    TOMATO_TRADE_ACTIVITY_UNIT = 12.0
    TOMATO_TRADE_ACTIVITY_MAX = 1.0

    # Minimal extension over the baseline:
    # - activity-gate the existing trade signal
    # - add a tiny microprice shading term
    # - only soften reduce thresholds when inventory needs relief
    # - suppress the passive quote that fights strong, active trade momentum
    TOMATO_TRADE_FAIR_SHIFT = 0.7
    TOMATO_MICROPRICE_SHIFT = 0.18
    TOMATO_SIGNAL_REDUCE_SKEW = 0.22
    TOMATO_MARGINAL_TAKE_CAP = 6
    TOMATO_MODERATE_TAKE_CAP = 12
    TOMATO_SUPPRESS_SIGNAL = 1.35
    TOMATO_SUPPRESS_ACTIVITY = 0.8

    def run(self, state: TradingState):
        saved_state = self._load_trader_state(state.traderData)
        tomato_trade_signal, tomato_trade_activity = self._update_tomato_trade_state(
            state.order_depths.get("TOMATOES", OrderDepth()),
            state.market_trades.get("TOMATOES", []),
            saved_state.get("tomato_trade_signal", 0.0),
            saved_state.get("tomato_trade_activity", 0.0),
        )

        result: Dict[str, List[Order]] = {}

        for product in self.POSITION_LIMITS:
            order_depth = state.order_depths.get(product, OrderDepth())
            position = state.position.get(product, 0)

            if product == "EMERALDS":
                result[product] = self.trade_emeralds_fair_reversion(order_depth, position)
            elif product == "TOMATOES":
                result[product] = self.trade_tomatoes_adaptive_model(
                    order_depth,
                    position,
                    tomato_trade_signal,
                    tomato_trade_activity,
                )
            else:
                result[product] = []

        conversions = 0
        traderData = self._encode_trader_state(tomato_trade_signal, tomato_trade_activity)
        return result, conversions, traderData

    def _load_trader_state(self, trader_data: str) -> Dict[str, float]:
        if not trader_data:
            return {
                "tomato_trade_signal": 0.0,
                "tomato_trade_activity": 0.0,
            }

        try:
            payload = json.loads(trader_data)
        except Exception:
            return {
                "tomato_trade_signal": 0.0,
                "tomato_trade_activity": 0.0,
            }

        return {
            "tomato_trade_signal": float(payload.get("tomato_trade_signal", 0.0)),
            "tomato_trade_activity": float(payload.get("tomato_trade_activity", 0.0)),
        }

    def _encode_trader_state(self, tomato_trade_signal: float, tomato_trade_activity: float) -> str:
        return json.dumps(
            {
                "tomato_trade_signal": tomato_trade_signal,
                "tomato_trade_activity": tomato_trade_activity,
            },
            separators=(",", ":"),
        )

    def _update_tomato_trade_state(
        self,
        order_depth: OrderDepth,
        market_trades: List[Any],
        previous_signal: float,
        previous_activity: float,
    ) -> tuple[float, float]:
        signal = self.TOMATO_TRADE_SIGNAL_DECAY * previous_signal
        activity = self.TOMATO_TRADE_ACTIVITY_DECAY * previous_activity

        state = self._book_state(order_depth)
        if state is None or not market_trades:
            return (
                self._clip(signal, self.TOMATO_TRADE_SIGNAL_MAX),
                max(0.0, min(self.TOMATO_TRADE_ACTIVITY_MAX, activity)),
            )

        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        touch_mid = 0.5 * (best_bid + best_ask)
        half_spread = max(1.0, 0.5 * (best_ask - best_bid))

        total_qty = 0
        signed_qty = 0.0
        vwap_numerator = 0.0

        for trade in market_trades:
            qty = abs(int(getattr(trade, "quantity", 0)))
            if qty <= 0:
                continue

            price = float(getattr(trade, "price", touch_mid))
            side = self._infer_trade_side(price, best_bid, best_ask)

            total_qty += qty
            signed_qty += side * qty
            vwap_numerator += price * qty

        if total_qty <= 0:
            return (
                self._clip(signal, self.TOMATO_TRADE_SIGNAL_MAX),
                max(0.0, min(self.TOMATO_TRADE_ACTIVITY_MAX, activity)),
            )

        imbalance = signed_qty / float(total_qty)
        vwap = vwap_numerator / float(total_qty)
        price_bias = self._clip((vwap - touch_mid) / half_spread, 1.5)
        volume_scale = min(1.5, total_qty / self.TOMATO_TRADE_SIGNAL_UNIT)

        signal += volume_scale * (0.7 * imbalance + 0.3 * price_bias)
        activity += total_qty / self.TOMATO_TRADE_ACTIVITY_UNIT

        return (
            self._clip(signal, self.TOMATO_TRADE_SIGNAL_MAX),
            max(0.0, min(self.TOMATO_TRADE_ACTIVITY_MAX, activity)),
        )

    def trade_tomatoes_adaptive_model(
        self,
        order_depth: OrderDepth,
        position: int,
        trade_signal: float = 0.0,
        trade_activity: float = 0.0,
    ) -> List[Order]:
        orders: List[Order] = []
        product = "TOMATOES"
        limit = self.POSITION_LIMITS[product]

        state = self._tomato_model_state(order_depth)
        if state is None:
            return orders

        buy_orders: Dict[int, int] = state["buy_orders"]
        sell_orders: Dict[int, int] = state["sell_orders"]
        best_bid = int(state["best_bid"])
        best_ask = int(state["best_ask"])
        touch_mid = float(state["touch_mid"])
        residual = float(state["residual"])
        spread = int(state["spread"])

        conviction = max(0.0, min(1.0, trade_activity))
        signal = trade_signal * conviction
        best_bid_size = float(buy_orders[best_bid])
        best_ask_size = float(sell_orders[best_ask])
        microprice = (
            (best_bid * best_ask_size + best_ask * best_bid_size)
            / max(1.0, best_bid_size + best_ask_size)
        )
        micro_dev = self._clip(microprice - touch_mid, 2.0)

        fair_exec = (
            float(state["fair_exec"])
            + self.TOMATO_TRADE_FAIR_SHIFT * signal
            + self.TOMATO_MICROPRICE_SHIFT * micro_dev
        )
        working_position = position

        if spread >= 13:
            take_edge = self.TOMATO_TAKE_EDGE
            reduce_edge = self.TOMATO_REDUCE_EDGE
            penny_edge = self.TOMATO_PENNY_EDGE
            passive_offset = self.TOMATO_PASSIVE_OFFSET
        elif spread >= 8:
            take_edge = self.TOMATO_TAKE_EDGE + 0.5
            reduce_edge = self.TOMATO_REDUCE_EDGE + 0.25
            penny_edge = self.TOMATO_PENNY_EDGE + 0.4
            passive_offset = self.TOMATO_PASSIVE_OFFSET + 1.0
        else:
            take_edge = self.TOMATO_TAKE_EDGE + 1.0
            reduce_edge = self.TOMATO_REDUCE_EDGE + 0.5
            penny_edge = self.TOMATO_PENNY_EDGE + 0.75
            passive_offset = self.TOMATO_PASSIVE_OFFSET + 2.0

        # Residual extremes often mean the book is stretched away from the
        # deep anchor. We become slightly more conservative about passive
        # posting, but a bit more willing to take obvious reversions.
        if abs(residual) >= 3.0:
            take_edge = max(0.75, take_edge - 0.15)
            passive_offset += 0.25

        buy_reduce_edge = reduce_edge
        sell_reduce_edge = reduce_edge
        if working_position < 0 and signal > 0:
            buy_reduce_edge = max(0.25, reduce_edge - self.TOMATO_SIGNAL_REDUCE_SKEW * min(signal, 2.0))
        if working_position > 0 and signal < 0:
            sell_reduce_edge = max(0.25, reduce_edge - self.TOMATO_SIGNAL_REDUCE_SKEW * min(-signal, 2.0))

        for ask_price, ask_volume in sell_orders.items():
            buy_capacity = limit - working_position
            if buy_capacity <= 0:
                break

            fair_skewed = fair_exec - self.TOMATO_INVENTORY_SKEW_PER_UNIT * working_position
            edge = fair_skewed - ask_price

            if ask_price <= fair_skewed - take_edge:
                qty_cap = buy_capacity
                if edge < take_edge + 0.75:
                    qty_cap = min(qty_cap, self.TOMATO_MARGINAL_TAKE_CAP)
                elif edge < take_edge + 1.5:
                    qty_cap = min(qty_cap, self.TOMATO_MODERATE_TAKE_CAP)

                qty = min(ask_volume, qty_cap)
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty
            elif working_position < 0 and ask_price <= fair_skewed - buy_reduce_edge:
                qty = min(ask_volume, buy_capacity, abs(working_position))
                if qty > 0:
                    orders.append(Order(product, ask_price, qty))
                    working_position += qty

        for bid_price, bid_volume in buy_orders.items():
            sell_capacity = limit + working_position
            if sell_capacity <= 0:
                break

            fair_skewed = fair_exec - self.TOMATO_INVENTORY_SKEW_PER_UNIT * working_position
            edge = bid_price - fair_skewed

            if bid_price >= fair_skewed + take_edge:
                qty_cap = sell_capacity
                if edge < take_edge + 0.75:
                    qty_cap = min(qty_cap, self.TOMATO_MARGINAL_TAKE_CAP)
                elif edge < take_edge + 1.5:
                    qty_cap = min(qty_cap, self.TOMATO_MODERATE_TAKE_CAP)

                qty = min(bid_volume, qty_cap)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    working_position -= qty
            elif working_position > 0 and bid_price >= fair_skewed + sell_reduce_edge:
                qty = min(bid_volume, sell_capacity, working_position)
                if qty > 0:
                    orders.append(Order(product, bid_price, -qty))
                    working_position -= qty

        fair_skewed = fair_exec - self.TOMATO_INVENTORY_SKEW_PER_UNIT * working_position
        buy_capacity = max(0, limit - working_position)
        sell_capacity = max(0, limit + working_position)

        bid_size = self._tomato_post_size(working_position, "buy", buy_capacity)
        ask_size = self._tomato_post_size(working_position, "sell", sell_capacity)

        # Avoid passively leaning against strong, active tape.
        if conviction >= self.TOMATO_SUPPRESS_ACTIVITY:
            if signal >= self.TOMATO_SUPPRESS_SIGNAL:
                ask_size = 0
                bid_size = min(buy_capacity, bid_size + 1)
            elif signal <= -self.TOMATO_SUPPRESS_SIGNAL:
                bid_size = 0
                ask_size = min(sell_capacity, ask_size + 1)

        spread = best_ask - best_bid
        penny_bid = best_bid + 1 if spread > 1 else best_bid
        penny_ask = best_ask - 1 if spread > 1 else best_ask

        edge_buy = fair_skewed - penny_bid
        edge_sell = penny_ask - fair_skewed

        if edge_buy >= penny_edge:
            bid_price = penny_bid
        else:
            bid_price = math.floor(fair_skewed - passive_offset)

        if edge_sell >= penny_edge:
            ask_price = penny_ask
        else:
            ask_price = math.ceil(fair_skewed + passive_offset)

        bid_price = min(bid_price, best_ask - 1)
        ask_price = max(ask_price, best_bid + 1)

        if bid_price >= ask_price:
            bid_price = best_bid
            ask_price = best_ask

        if bid_size > 0:
            orders.append(Order(product, int(bid_price), bid_size))

        if ask_size > 0:
            orders.append(Order(product, int(ask_price), -ask_size))

        return orders
