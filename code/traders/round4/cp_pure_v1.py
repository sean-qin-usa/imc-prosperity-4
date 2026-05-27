"""
Round 4 — counterparty-pure strategy.

Built ONLY from the per-Mark behavioral table (no reference to other R4/R3
strategies). Three orthogonal alpha modes:

  1. Fair-value SHIFT accumulator: each observed market trade contributes
     side*coef*qty*scale to a per-symbol drift signal. EMA-decayed and capped.
       Mark 14 +5.64  (informed maker, follow)
       Mark 01 +1.35
       Mark 67 +1.03  (informed aggressor, follow direction)
       Mark 22 -0.51  (noise)
       Mark 49 -1.12  (mistimed passive, fade)
       Mark 55 -2.19  (noise)
       Mark 38 -8.41  (dominant noise, fade hard)

  2. Mark 49 direct override: if 49 was net-buying recently, post extra-tight
     ask; net-selling -> extra-tight bid. (Their passive direction = wrong.)

  3. Mark 38 size boost: if Mark 38 has been active recently, double quote
     size to soak up their flow.

Plus standard MM mechanics: take when ask <= fair-1 / bid >= fair+1, post
inside-spread quotes around fair, taper near position limits.
"""

from datamodel import TradingState, Order
from typing import Dict, List
import math

POSITION_LIMITS = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300, "VEV_5100": 300,
    "VEV_5200": 300, "VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300,
    "VEV_6000": 300, "VEV_6500": 300,
}

# fair-shift coef per unit of qty, signed in direction of Mark's trade
CP_COEF = {
    "Mark 14": +5.64, "Mark 01": +1.35, "Mark 67": +1.03,
    "Mark 22": -0.51, "Mark 49": -1.12, "Mark 55": -2.19, "Mark 38": -8.41,
}

# raw coef * qty is the 2000-tick cumulative drift forecast; scale down so the
# instantaneous fair shift reflects expected near-term move only.
# v2: 0.30 -> 0.08. Realised drift per print is much smaller than the sample
# average suggests because counterparty trades co-occur and double-attribute.
SHIFT_SCALE = 0.08
EMA_HL_TS = 1500.0  # decay half-life in timestamp units

# per-symbol cap on accumulated shift (in mid-ticks). Keeps a single big print
# from blowing fair past the touch.
SHIFT_CAP = {
    "HYDROGEL_PACK": 6, "VELVETFRUIT_EXTRACT": 5,
    "VEV_4000": 8, "VEV_4500": 6, "VEV_5000": 5, "VEV_5100": 4,
    "VEV_5200": 4, "VEV_5300": 3, "VEV_5400": 3, "VEV_5500": 3,
    "VEV_6000": 2, "VEV_6500": 2,
}

NOISE_WIN_TS = 2000
NOISE_QTY_TRIGGER = 30   # Mark 38 qty in window to boost size
MIST_WIN_TS = 2000

BASE_SIZE = 20
TAKE_EDGE = 2            # require ask <= fair-2 / bid >= fair+2 to cross
MIN_PRICE = 5            # skip deep-OTM voucher rows where mid < 5
SKEW_DIVISOR = 3.0       # post-size skew = round(shift / SKEW_DIVISOR)
MIN_SPREAD_TO_POST = 8   # only post passive when ask-bid >= this; tight-spread products
                         # can't earn enough per fill to pay for adverse selection


class Trader:
    def __init__(self):
        self.shift: Dict[str, float] = {}
        self.last_ts: Dict[str, int] = {}
        self.recent_38: Dict[str, list] = {}     # sym -> [(ts, qty)]
        self.recent_49: Dict[str, list] = {}     # sym -> [(ts, signed_qty)]

    def _decay(self, sym: str, ts: int) -> None:
        last = self.last_ts.get(sym)
        if last is None:
            self.last_ts[sym] = ts
            return
        dt = ts - last
        if dt > 0:
            decay = math.exp(-dt * math.log(2.0) / EMA_HL_TS)
            self.shift[sym] = self.shift.get(sym, 0.0) * decay
        self.last_ts[sym] = ts

    def _ingest(self, sym: str, trades, ts: int) -> None:
        for t in trades:
            qty = int(getattr(t, "quantity", 0) or 0)
            if qty <= 0:
                continue
            price = float(getattr(t, "price", 0) or 0)
            if price <= 0:
                continue
            buyer = getattr(t, "buyer", "") or ""
            seller = getattr(t, "seller", "") or ""
            t_ts = int(getattr(t, "timestamp", ts) or ts)

            # both sides may be Marks; SUBMISSION (us) won't be in CP_COEF
            for mark, side in ((buyer, +1), (seller, -1)):
                coef = CP_COEF.get(mark)
                if coef is None:
                    continue
                self.shift[sym] = self.shift.get(sym, 0.0) + side * coef * qty * SHIFT_SCALE
                if mark == "Mark 38":
                    self.recent_38.setdefault(sym, []).append((t_ts, qty))
                elif mark == "Mark 49":
                    self.recent_49.setdefault(sym, []).append((t_ts, side * qty))

        cap = SHIFT_CAP.get(sym, 5)
        s = self.shift.get(sym, 0.0)
        if s > cap:
            self.shift[sym] = float(cap)
        elif s < -cap:
            self.shift[sym] = float(-cap)

        cutoff_n = ts - NOISE_WIN_TS
        cutoff_m = ts - MIST_WIN_TS
        if sym in self.recent_38:
            self.recent_38[sym] = [(tt, q) for (tt, q) in self.recent_38[sym] if tt >= cutoff_n]
        if sym in self.recent_49:
            self.recent_49[sym] = [(tt, q) for (tt, q) in self.recent_49[sym] if tt >= cutoff_m]

    def run(self, state: TradingState):
        ts = int(getattr(state, "timestamp", 0) or 0)
        result: Dict[str, List[Order]] = {}

        for sym, depth in state.order_depths.items():
            limit = POSITION_LIMITS.get(sym, 0)
            if limit <= 0:
                result[sym] = []
                continue

            self._decay(sym, ts)
            self._ingest(sym, state.market_trades.get(sym, []) or [], ts)

            buys = depth.buy_orders or {}
            sells = depth.sell_orders or {}
            if not buys or not sells:
                result[sym] = []
                continue

            best_bid = max(buys)
            best_ask = min(sells)
            if best_ask <= best_bid:
                result[sym] = []
                continue

            mid = (best_bid + best_ask) / 2.0
            if mid < MIN_PRICE:
                result[sym] = []
                continue

            shift = self.shift.get(sym, 0.0)
            fair = mid + shift

            pos = int(state.position.get(sym, 0))
            buy_cap = limit - pos
            sell_cap = limit + pos

            orders: List[Order] = []
            taken_buy = 0
            taken_sell = 0

            # --- take side: cross spread when fair clearly exceeds touch ---
            # only take when product spread is wide enough that the take edge is real
            spread_for_gate = best_ask - best_bid
            can_take = spread_for_gate >= MIN_SPREAD_TO_POST
            if can_take and best_ask <= fair - TAKE_EDGE and buy_cap > 0:
                ask_qty = -int(sells[best_ask])  # sells stored as negative
                qty = min(buy_cap, max(0, ask_qty))
                if qty > 0:
                    orders.append(Order(sym, int(best_ask), qty))
                    taken_buy += qty
            if can_take and best_bid >= fair + TAKE_EDGE and sell_cap > 0:
                bid_qty = int(buys[best_bid])
                qty = min(sell_cap, max(0, bid_qty))
                if qty > 0:
                    orders.append(Order(sym, int(best_bid), -qty))
                    taken_sell += qty

            # --- passive posts inside the spread (one tick max, no jumps) ---
            spread = best_ask - best_bid
            # only post when spread is wide enough that 1-tick-inside captures edge
            post_passive = spread >= MIN_SPREAD_TO_POST
            post_bid = best_bid + 1 if post_passive else None
            post_ask = best_ask - 1 if post_passive else None

            # shift / Mark-49 bias goes into SIZE skew, not post PRICE
            r49 = sum(q for (_, q) in self.recent_49.get(sym, []))
            r38 = sum(q for (_, q) in self.recent_38.get(sym, []))

            # Mark 38 noise size boost (more flow to absorb)
            size_mult = 2 if r38 >= NOISE_QTY_TRIGGER else 1

            base = BASE_SIZE * size_mult
            # base size skew from accumulated counterparty shift
            skew = max(-4, min(4, int(round(shift / SKEW_DIVISOR))))
            # Mark 49 fade: if they were net-buying, we want to be net-short, so
            # reduce bid / increase ask
            if r49 > 0:
                skew -= 1
            elif r49 < 0:
                skew += 1

            bid_base = max(2, base + skew)
            ask_base = max(2, base - skew)

            # taper when we're loaded on a side
            soft = 0.7 * limit
            extra = max(0, abs(pos) - soft)
            taper = max(0.2, 1.0 - extra / max(1.0, 0.3 * limit))
            bid_size = max(1, int(bid_base * (taper if pos >= 0 else 1.0)))
            ask_size = max(1, int(ask_base * (taper if pos <= 0 else 1.0)))

            bid_room = max(0, buy_cap - taken_buy)
            ask_room = max(0, sell_cap - taken_sell)
            bid_qty = min(bid_size, bid_room)
            ask_qty = min(ask_size, ask_room)

            if post_passive and post_ask <= post_bid:
                # collapsed: skew based on shift sign
                if shift >= 0:
                    post_ask = post_bid + 1
                else:
                    post_bid = post_ask - 1

            if post_bid is not None and bid_qty > 0 and post_bid >= 1:
                orders.append(Order(sym, int(post_bid), bid_qty))
            if post_ask is not None and ask_qty > 0 and (post_bid is None or post_ask >= post_bid + 1):
                orders.append(Order(sym, int(post_ask), -ask_qty))

            result[sym] = orders

        return result, 0, ""
