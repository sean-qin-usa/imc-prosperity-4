import json
from typing import Dict, List, Optional

from datamodel import OrderDepth, TradingState, Order


class KalmanFilter:
    """
    Light smoother, not a predictive model.
    """
    def __init__(self, process_var: float = 1.5, obs_var: float = 6.0):
        self.Q = process_var
        self.R = obs_var
        self.x: Optional[float] = None
        self.P: float = 1.0

    def update(self, z: float) -> float:
        if self.x is None:
            self.x = z
            return z
        p_pred = self.P + self.Q
        k = p_pred / (p_pred + self.R)
        self.x = self.x + k * (z - self.x)
        self.P = (1 - k) * p_pred
        return self.x

    def to_dict(self) -> dict:
        return {"x": self.x, "P": self.P}

    @classmethod
    def from_dict(cls, d: dict, process_var: float = 1.5, obs_var: float = 6.0) -> "KalmanFilter":
        kf = cls(process_var, obs_var)
        kf.x = d.get("x")
        kf.P = d.get("P", 1.0)
        return kf


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

        tomato_kf = KalmanFilter.from_dict(saved.get("tomato_kf", {}))

        result: Dict[str, List[Order]] = {}

        if "EMERALDS" in state.order_depths:
            result["EMERALDS"] = self.trade_emeralds(state)

        if "TOMATOES" in state.order_depths:
            result["TOMATOES"] = self.trade_tomatoes(state, tomato_kf)

        trader_data = json.dumps({
            "tomato_kf": tomato_kf.to_dict(),
        })

        return result, 0, trader_data

    # -----------------------------
    # Helpers
    # -----------------------------

    def best_bid_ask(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None, None
        return max(od.buy_orders.keys()), min(od.sell_orders.keys())

    def current_position(self, state: TradingState, product: str) -> int:
        return state.position.get(product, 0)

    def reservation_skew(self, pos: int, limit: int, max_skew: int) -> int:
        """
        Integer quote skew from inventory.
        Positive skew means shift fair DOWN (want to sell more).
        Negative skew means shift fair UP (want to buy more).
        """
        frac = pos / limit
        if frac > 0.75:
            return max_skew
        if frac > 0.40:
            return 1
        if frac < -0.75:
            return -max_skew
        if frac < -0.40:
            return -1
        return 0

    def book_fair(self, od: OrderDepth) -> Optional[float]:
        """
        Robust current-price estimate.
        Prefer size-weighted top-of-book; can be extended to wall-mid logic.
        """
        best_bid, best_ask = self.best_bid_ask(od)
        if best_bid is None or best_ask is None:
            return None

        bid_sz = od.buy_orders[best_bid]
        ask_sz = -od.sell_orders[best_ask]

        if bid_sz + ask_sz == 0:
            return (best_bid + best_ask) / 2.0

        # Microprice leaning toward the thinner side being easier to move through
        micro = (best_bid * ask_sz + best_ask * bid_sz) / (bid_sz + ask_sz)
        return micro

    # -----------------------------
    # EMERALDS
    # -----------------------------

    def trade_emeralds(self, state: TradingState) -> List[Order]:
        product = "EMERALDS"
        od = state.order_depths[product]
        pos = self.current_position(state, product)
        limit = self.LIMITS[product]
        fair = self.EMERALD_FAIR

        orders: List[Order] = []

        buy_cap = limit - pos
        sell_cap = limit + pos

        # 1) Take gifts first
        if od.sell_orders and buy_cap > 0:
            for ask in sorted(od.sell_orders):
                if ask >= fair:
                    break
                qty = min(-od.sell_orders[ask], buy_cap)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    buy_cap -= qty

        if od.buy_orders and sell_cap > 0:
            for bid in sorted(od.buy_orders, reverse=True):
                if bid <= fair:
                    break
                qty = min(od.buy_orders[bid], sell_cap)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    sell_cap -= qty

        # 2) Inventory-aware reservation price
        skew = self.reservation_skew(pos, limit, max_skew=2)
        reservation = fair - skew

        # 3) Flatten at zero edge if inventory is large
        if pos > 55 and od.buy_orders and sell_cap > 0:
            best_bid = max(od.buy_orders)
            if best_bid >= fair:
                qty = min(od.buy_orders[best_bid], sell_cap, pos)
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))
                    sell_cap -= qty

        if pos < -55 and od.sell_orders and buy_cap > 0:
            best_ask = min(od.sell_orders)
            if best_ask <= fair:
                qty = min(-od.sell_orders[best_ask], buy_cap, -pos)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
                    buy_cap -= qty

        # 4) Passive quoting
        # Keep some room for future taking instead of always posting full cap
        post_buy = max(0, min(25, buy_cap))
        post_sell = max(0, min(25, sell_cap))

        bid_px = reservation - 1   # usually 9999
        ask_px = reservation + 1   # usually 10001

        if post_buy > 0:
            orders.append(Order(product, bid_px, post_buy))
        if post_sell > 0:
            orders.append(Order(product, ask_px, -post_sell))

        return orders

    # -----------------------------
    # TOMATOES
    # -----------------------------

    def trade_tomatoes(self, state: TradingState, kf: KalmanFilter) -> List[Order]:
        product = "TOMATOES"
        od = state.order_depths[product]
        pos = self.current_position(state, product)
        limit = self.LIMITS[product]

        orders: List[Order] = []

        best_bid, best_ask = self.best_bid_ask(od)
        if best_bid is None or best_ask is None:
            return orders

        instant_fair = self.book_fair(od)
        if instant_fair is None:
            return orders

        # Light smoothing only
        fair = kf.update(instant_fair)

        buy_cap = limit - pos
        sell_cap = limit + pos

        spread = best_ask - best_bid
        skew = self.reservation_skew(pos, limit, max_skew=3)
        reservation = fair - skew

        # Dynamic thresholds
        # Wider than EMERALDS because TOMATOES fluctuates more
        take_threshold = max(2.0, 0.35 * spread)
        post_offset = max(2, int(round(0.35 * spread)))

        # 1) Take gifts first
        if best_ask < reservation - take_threshold and buy_cap > 0:
            qty = min(-od.sell_orders[best_ask], buy_cap, 20)
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                buy_cap -= qty

        if best_bid > reservation + take_threshold and sell_cap > 0:
            qty = min(od.buy_orders[best_bid], sell_cap, 20)
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                sell_cap -= qty

        # 2) Inventory emergency flattening near fair
        if pos > 50 and sell_cap > 0:
            qty = min(sell_cap, min(20, pos))
            px = max(best_bid, int(round(fair)))
            orders.append(Order(product, px, -qty))
            sell_cap -= qty

        if pos < -50 and buy_cap > 0:
            qty = min(buy_cap, min(20, -pos))
            px = min(best_ask, int(round(fair)))
            orders.append(Order(product, px, qty))
            buy_cap -= qty

        # 3) Passive backup quotes
        # Smaller and more selective than EMERALDS
        post_buy = max(0, min(12, buy_cap))
        post_sell = max(0, min(12, sell_cap))

        bid_px = int(round(reservation)) - post_offset
        ask_px = int(round(reservation)) + post_offset

        # Avoid crossing ourselves into a bad aggressive fill
        bid_px = min(bid_px, best_ask - 1)
        ask_px = max(ask_px, best_bid + 1)

        if post_buy > 0:
            orders.append(Order(product, bid_px, post_buy))
        if post_sell > 0:
            orders.append(Order(product, ask_px, -post_sell))

        return orders