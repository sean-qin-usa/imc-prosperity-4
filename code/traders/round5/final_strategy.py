"""
Round 5 — 50-product sentiment-directional MM (shipped strategy).

50 products across 10 themed families, per-product position limit 10. The trade
is per-product directional bias (buy / sell), derived from the round-5 uplink
transcript and product descriptions, executed as:

  1. After ts >= 10_000 (skip first 1 % of day for the book to settle),
     take aggressively up to a directional target of ±DIRECTIONAL_TARGET at
     the touch.
  2. Outside the taking band, post passive quotes inside the spread, with an
     imbalance gate: suppress the ask if imb > +IMB_THR, suppress the bid if
     imb < -IMB_THR.
  3. Per-product limit is 10, so a DIRECTIONAL_TARGET of 6 leaves 4 units of
     room above the target for passive-make on the same side and meaningful
     capacity to lean into adverse fills.

Sister strategy NOT shipped: ``ll_pair_base_561965.py`` (universal basket-MM,
live PnL $561,965). See ``../../../round_5.md`` for why the directional
version shipped instead.
"""

from datamodel import Order, OrderDepth, TradingState


class Trader:
    # ---------- universe -------------------------------------------------
    PRODUCTS = (
        "GALAXY_SOUNDS_DARK_MATTER",
        "GALAXY_SOUNDS_BLACK_HOLES",
        "GALAXY_SOUNDS_PLANETARY_RINGS",
        "GALAXY_SOUNDS_SOLAR_WINDS",
        "GALAXY_SOUNDS_SOLAR_FLAMES",
        "SLEEP_POD_SUEDE",
        "SLEEP_POD_LAMB_WOOL",
        "SLEEP_POD_POLYESTER",
        "SLEEP_POD_NYLON",
        "SLEEP_POD_COTTON",
        "MICROCHIP_CIRCLE",
        "MICROCHIP_OVAL",
        "MICROCHIP_SQUARE",
        "MICROCHIP_RECTANGLE",
        "MICROCHIP_TRIANGLE",
        "PEBBLES_XS",
        "PEBBLES_S",
        "PEBBLES_M",
        "PEBBLES_L",
        "PEBBLES_XL",
        "ROBOT_VACUUMING",
        "ROBOT_MOPPING",
        "ROBOT_DISHES",
        "ROBOT_LAUNDRY",
        "ROBOT_IRONING",
        "UV_VISOR_YELLOW",
        "UV_VISOR_AMBER",
        "UV_VISOR_ORANGE",
        "UV_VISOR_RED",
        "UV_VISOR_MAGENTA",
        "TRANSLATOR_SPACE_GRAY",
        "TRANSLATOR_ASTRO_BLACK",
        "TRANSLATOR_ECLIPSE_CHARCOAL",
        "TRANSLATOR_GRAPHITE_MIST",
        "TRANSLATOR_VOID_BLUE",
        "PANEL_1X2",
        "PANEL_2X2",
        "PANEL_1X4",
        "PANEL_2X4",
        "PANEL_4X4",
        "OXYGEN_SHAKE_MORNING_BREATH",
        "OXYGEN_SHAKE_EVENING_BREATH",
        "OXYGEN_SHAKE_MINT",
        "OXYGEN_SHAKE_CHOCOLATE",
        "OXYGEN_SHAKE_GARLIC",
        "SNACKPACK_CHOCOLATE",
        "SNACKPACK_VANILLA",
        "SNACKPACK_PISTACHIO",
        "SNACKPACK_STRAWBERRY",
        "SNACKPACK_RASPBERRY",
    )
    LIMITS = {product: 10 for product in PRODUCTS}

    # ---------- side-bias dict ------------------------------------------
    # Per-product directional bias from the round-5 uplink transcript /
    # product descriptions. Manual classification — see ../../../round_5.md
    # for the family-level reasoning.
    SIDE_BIAS = {
        "GALAXY_SOUNDS_BLACK_HOLES": "buy",
        "GALAXY_SOUNDS_DARK_MATTER": "buy",
        "GALAXY_SOUNDS_PLANETARY_RINGS": "sell",
        "GALAXY_SOUNDS_SOLAR_FLAMES": "buy",
        "GALAXY_SOUNDS_SOLAR_WINDS": "buy",
        "MICROCHIP_CIRCLE": "buy",
        "MICROCHIP_OVAL": "sell",
        "MICROCHIP_RECTANGLE": "sell",
        "MICROCHIP_SQUARE": "buy",
        "MICROCHIP_TRIANGLE": "sell",
        "OXYGEN_SHAKE_CHOCOLATE": "buy",
        "OXYGEN_SHAKE_EVENING_BREATH": "sell",
        "OXYGEN_SHAKE_GARLIC": "buy",
        "OXYGEN_SHAKE_MINT": "buy",
        "OXYGEN_SHAKE_MORNING_BREATH": "sell",
        "PANEL_1X2": "sell",
        "PANEL_1X4": "sell",
        "PANEL_2X2": "sell",
        "PANEL_2X4": "buy",
        "PANEL_4X4": "sell",
        "PEBBLES_L": "sell",
        "PEBBLES_M": "buy",
        "PEBBLES_S": "sell",
        "PEBBLES_XL": "buy",
        "PEBBLES_XS": "sell",
        "ROBOT_DISHES": "buy",
        "ROBOT_IRONING": "sell",
        "ROBOT_LAUNDRY": "sell",
        "ROBOT_MOPPING": "buy",
        "ROBOT_VACUUMING": "sell",
        "SLEEP_POD_COTTON": "buy",
        "SLEEP_POD_LAMB_WOOL": "buy",
        "SLEEP_POD_NYLON": "buy",
        "SLEEP_POD_POLYESTER": "buy",
        "SLEEP_POD_SUEDE": "buy",
        "SNACKPACK_CHOCOLATE": "sell",
        "SNACKPACK_PISTACHIO": "sell",
        "SNACKPACK_RASPBERRY": "buy",
        "SNACKPACK_STRAWBERRY": "buy",
        "SNACKPACK_VANILLA": "buy",
        "TRANSLATOR_ASTRO_BLACK": "sell",
        "TRANSLATOR_ECLIPSE_CHARCOAL": "sell",
        "TRANSLATOR_GRAPHITE_MIST": "sell",
        "TRANSLATOR_SPACE_GRAY": "sell",
        "TRANSLATOR_VOID_BLUE": "buy",
        "UV_VISOR_AMBER": "sell",
        "UV_VISOR_MAGENTA": "buy",
        "UV_VISOR_ORANGE": "sell",
        "UV_VISOR_RED": "buy",
        "UV_VISOR_YELLOW": "buy",
    }

    # ---------- tunables -------------------------------------------------
    DIRECTIONAL_TARGET = 6   # target ±position per product
    TAKE_SIZE          = 8   # max units taken per tick
    PASSIVE_SIZE       = 4   # passive quote size inside the spread
    IMPROVEMENT        = 1   # ticks to improve the BBO when quoting passive
    IMB_THR            = 0.3 # |imbalance| above this suppresses the adverse side
    PURE_TAKER         = False  # if True, skip the passive layer entirely

    # ---------- book helpers ---------------------------------------------
    @staticmethod
    def _best(depth):
        """Best bid / ask + volumes, or None if either side is empty."""
        if not depth.buy_orders or not depth.sell_orders:
            return None
        bid = max(depth.buy_orders)
        ask = min(depth.sell_orders)
        return bid, int(depth.buy_orders[bid]), ask, -int(depth.sell_orders[ask])

    def _capacity(self, state, product):
        """(buy_cap, sell_cap, current_pos, limit) for the product."""
        limit = self.LIMITS.get(product, 10)
        pos   = int(state.position.get(product, 0))
        return max(0, limit - pos), max(0, limit + pos), pos, limit

    # ---------- main loop ------------------------------------------------
    def run(self, state: TradingState):
        result = {}
        for sym, od in state.order_depths.items():
            side = self.SIDE_BIAS.get(sym)
            if side is None:
                continue  # not in our bias dict — skip

            best = self._best(od)
            if best is None:
                continue
            bid, bid_vol, ask, ask_vol = best
            buy_cap, sell_cap, pos, _ = self._capacity(state, sym)
            orders = []

            # 1) Directional take: ramp position toward ±DIRECTIONAL_TARGET
            #    after the first 1 % of day.
            if state.timestamp >= 10_000:
                target = self.DIRECTIONAL_TARGET if side == "buy" else -self.DIRECTIONAL_TARGET
                if side == "buy" and pos < target and buy_cap > 0:
                    qty = min(target - pos, buy_cap, ask_vol, self.TAKE_SIZE)
                    if qty > 0:
                        orders.append(Order(sym, ask, qty))
                elif side == "sell" and pos > target and sell_cap > 0:
                    qty = min(pos - target, sell_cap, bid_vol, self.TAKE_SIZE)
                    if qty > 0:
                        orders.append(Order(sym, bid, -qty))

            # 2) Passive layer: inside-spread quotes with an imbalance gate.
            if not orders and not self.PURE_TAKER:
                our_bid = bid + self.IMPROVEMENT
                our_ask = ask - self.IMPROVEMENT
                if our_bid < our_ask:
                    quote_bid = buy_cap > 0
                    quote_ask = sell_cap > 0
                    tot = bid_vol + ask_vol
                    if tot > 0:
                        imb = (bid_vol - ask_vol) / tot
                        if imb > self.IMB_THR:
                            quote_ask = False   # book pressure up → don't sell into it
                        elif imb < -self.IMB_THR:
                            quote_bid = False   # book pressure down → don't buy into it
                    if quote_bid:
                        qty = min(buy_cap, self.PASSIVE_SIZE)
                        if qty > 0:
                            orders.append(Order(sym, our_bid, qty))
                    if quote_ask:
                        qty = min(sell_cap, self.PASSIVE_SIZE)
                        if qty > 0:
                            orders.append(Order(sym, our_ask, -qty))

            if orders:
                result[sym] = orders
        return result, 0, ""
