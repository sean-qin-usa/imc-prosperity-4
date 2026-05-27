import json
from typing import Dict, List, Optional

from datamodel import Order, OrderDepth, TradingState


class Trader:
    LIMITS = {
        "EMERALDS": 80,
        "TOMATOES": 80,
    }

    EMERALD_FAIR = 10000

    def run(self, state: TradingState):
        saved = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        tomato_state = saved.get("tomatoes", {})

        orders: Dict[str, List[Order]] = {}
        if "EMERALDS" in state.order_depths:
            orders["EMERALDS"] = self.trade_emeralds(state)
        if "TOMATOES" in state.order_depths:
            orders["TOMATOES"], tomato_state = self.trade_tomatoes(state, tomato_state)

        trader_data = json.dumps({
            "tomatoes": tomato_state
        })

        return orders, 0, trader_data

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def get_pos(self, state: TradingState, product: str) -> int:
        return state.position.get(product, 0)

    def best_bid_ask(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None, None
        return max(od.buy_orders.keys()), min(od.sell_orders.keys())

    def second_best_bid(self, od: OrderDepth):
        if len(od.buy_orders) < 2:
            return None
        return sorted(od.buy_orders.keys(), reverse=True)[1]

    def second_best_ask(self, od: OrderDepth):
        if len(od.sell_orders) < 2:
            return None
        return sorted(od.sell_orders.keys())[1]

    def microprice(self, od: OrderDepth) -> Optional[float]:
        best_bid, best_ask = self.best_bid_ask(od)
        if best_bid is None or best_ask is None:
            return None

        bid_sz = od.buy_orders[best_bid]
        ask_sz = -od.sell_orders[best_ask]

        if bid_sz + ask_sz == 0:
            return (best_bid + best_ask) / 2.0

        return (best_bid * ask_sz + best_ask * bid_sz) / (bid_sz + ask_sz)

    def inventory_skew(self, pos: int, limit: int, max_ticks: int) -> int:
        frac = pos / limit
        if frac >= 0.75:
            return max_ticks
        if frac >= 0.40:
            return 1
        if frac <= -0.75:
            return -max_ticks
        if frac <= -0.40:
            return -1
        return 0

    def take_sells_up_to(self, product: str, od: OrderDepth, acceptable_price: float, buy_cap: int):
        orders: List[Order] = []
        if buy_cap <= 0:
            return orders, buy_cap

        for ask in sorted(od.sell_orders.keys()):
            if ask > acceptable_price:
                break
            qty = min(-od.sell_orders[ask], buy_cap)
            if qty > 0:
                orders.append(Order(product, ask, qty))
                buy_cap -= qty
            if buy_cap <= 0:
                break
        return orders, buy_cap

    def take_buys_down_to(self, product: str, od: OrderDepth, acceptable_price: float, sell_cap: int):
        orders: List[Order] = []
        if sell_cap <= 0:
            return orders, sell_cap

        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid < acceptable_price:
                break
            qty = min(od.buy_orders[bid], sell_cap)
            if qty > 0:
                orders.append(Order(product, bid, -qty))
                sell_cap -= qty
            if sell_cap <= 0:
                break
        return orders, sell_cap

    # --------------------------------------------------
    # EMERALDS
    # --------------------------------------------------

    def trade_emeralds(self, state: TradingState) -> List[Order]:
        product = "EMERALDS"
        od = state.order_depths[product]
        pos = self.get_pos(state, product)
        limit = self.LIMITS[product]
        fair = self.EMERALD_FAIR

        orders: List[Order] = []

        buy_cap = limit - pos
        sell_cap = limit + pos

        # 1) Take gifts first
        buy_orders, buy_cap = self.take_sells_up_to(product, od, fair - 1, buy_cap)
        sell_orders, sell_cap = self.take_buys_down_to(product, od, fair + 1, sell_cap)
        orders.extend(buy_orders)
        orders.extend(sell_orders)

        best_bid, best_ask = self.best_bid_ask(od)

        # 2) Earlier zero-edge flattening if inventory is meaningful
        if best_bid is not None and pos > 25 and sell_cap > 0 and best_bid >= fair:
            qty = min(pos, sell_cap, od.buy_orders[best_bid])
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                sell_cap -= qty

        if best_ask is not None and pos < -25 and buy_cap > 0 and best_ask <= fair:
            qty = min(-pos, buy_cap, -od.sell_orders[best_ask])
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                buy_cap -= qty

        # 3) Passive quoting
        skew = self.inventory_skew(pos, limit, max_ticks=3)
        reservation = fair - skew

        buy_price = reservation - 1
        sell_price = reservation + 1

        ext_bid = None
        ext_ask = None

        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid < fair:
                ext_bid = bid
                break

        for ask in sorted(od.sell_orders.keys()):
            if ask > fair:
                ext_ask = ask
                break

        if ext_bid is not None:
            buy_price = max(buy_price, ext_bid + 1)
            buy_price = min(buy_price, fair - 1)

        if ext_ask is not None:
            sell_price = min(sell_price, ext_ask - 1)
            sell_price = max(sell_price, fair + 1)

        if abs(pos) <= 10:
            post_buy = min(35, buy_cap)
            post_sell = min(35, sell_cap)
        elif abs(pos) <= 30:
            post_buy = min(28, buy_cap)
            post_sell = min(28, sell_cap)
        else:
            post_buy = min(18, buy_cap)
            post_sell = min(18, sell_cap)

        if pos > 20:
            post_buy = min(post_buy, 10)
            post_sell = min(post_sell + 8, sell_cap)
        elif pos < -20:
            post_sell = min(post_sell, 10)
            post_buy = min(post_buy + 8, buy_cap)

        if post_buy > 0:
            orders.append(Order(product, int(buy_price), post_buy))
        if post_sell > 0:
            orders.append(Order(product, int(sell_price), -post_sell))

        return orders

    # --------------------------------------------------
    # TOMATOES
    # --------------------------------------------------

    def trade_tomatoes(self, state: TradingState, saved: dict):
        product = "TOMATOES"
        od = state.order_depths[product]
        pos = self.get_pos(state, product)
        limit = self.LIMITS[product]

        orders: List[Order] = []

        best_bid, best_ask = self.best_bid_ask(od)
        if best_bid is None or best_ask is None:
            return orders, saved

        micro = self.microprice(od)
        if micro is None:
            return orders, saved

        prev_ema = saved.get("ema")

        if prev_ema is None:
            ema = micro
        else:
            ema = 0.85 * prev_ema + 0.15 * micro

        fair = ema

        spread = best_ask - best_bid
        buy_cap = limit - pos
        sell_cap = limit + pos

        # Stronger skew than baseline
        skew = self.inventory_skew(pos, limit, max_ticks=4)
        reservation = fair - skew

        # Harder to add more when already leaning
        if abs(pos) <= 10:
            take_threshold = max(2.0, 0.35 * spread)
        elif abs(pos) <= 25:
            take_threshold = max(2.5, 0.40 * spread)
        else:
            take_threshold = max(3.0, 0.45 * spread)

        post_offset = max(2, int(round(0.35 * spread)))

        # Aggressive takes
        if best_ask < reservation - take_threshold and buy_cap > 0:
            qty = min(-od.sell_orders[best_ask], buy_cap, 16)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                buy_cap -= qty

        if best_bid > reservation + take_threshold and sell_cap > 0:
            qty = min(od.buy_orders[best_bid], sell_cap, 16)
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                sell_cap -= qty

        # Moderate earlier flattening
        if pos > 30 and sell_cap > 0:
            qty = min(pos - 20, sell_cap, 12)
            px = max(best_bid, int(round(fair)) - 1)
            if qty > 0:
                orders.append(Order(product, px, -qty))
                sell_cap -= qty

        if pos < -30 and buy_cap > 0:
            qty = min((-pos) - 20, buy_cap, 12)
            px = min(best_ask, int(round(fair)) + 1)
            if qty > 0:
                orders.append(Order(product, px, qty))
                buy_cap -= qty

        # Hard emergency flatten only when truly stretched
        if pos > 50 and sell_cap > 0:
            qty = min(pos, sell_cap, 16)
            px = max(best_bid, int(round(fair)))
            if qty > 0:
                orders.append(Order(product, px, -qty))
                sell_cap -= qty

        if pos < -50 and buy_cap > 0:
            qty = min(-pos, buy_cap, 16)
            px = min(best_ask, int(round(fair)))
            if qty > 0:
                orders.append(Order(product, px, qty))
                buy_cap -= qty

        # Passive quotes
        bid_px = int(round(reservation)) - post_offset
        ask_px = int(round(reservation)) + post_offset

        bid_px = min(bid_px, best_ask - 1)
        ask_px = max(ask_px, best_bid + 1)

        ext_bid = self.second_best_bid(od)
        ext_ask = self.second_best_ask(od)

        if ext_bid is not None and ext_bid + 1 < fair:
            bid_px = max(bid_px, ext_bid + 1)

        if ext_ask is not None and ext_ask - 1 > fair:
            ask_px = min(ask_px, ext_ask - 1)

        # Smaller passive size when inventory is stretched
        if abs(pos) <= 10:
            post_buy = min(12, buy_cap)
            post_sell = min(12, sell_cap)
        elif abs(pos) <= 25:
            post_buy = min(8, buy_cap)
            post_sell = min(8, sell_cap)
        else:
            post_buy = min(5, buy_cap)
            post_sell = min(5, sell_cap)

        if pos > 20:
            post_buy = min(post_buy, 3)
            post_sell = min(post_sell + 4, sell_cap)
        elif pos < -20:
            post_sell = min(post_sell, 3)
            post_buy = min(post_buy + 4, buy_cap)

        if post_buy > 0:
            orders.append(Order(product, int(bid_px), post_buy))
        if post_sell > 0:
            orders.append(Order(product, int(ask_px), -post_sell))

        new_state = {
            "ema": ema,
        }

        return orders, new_state