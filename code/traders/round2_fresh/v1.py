"""
Fresh round-2 strategy, written from a blank slate for a Claude-vs-GPT bakeoff.
Uses only the Trader/TradingState/Order interface the backtester expects.

Market observations (raw CSV inspection only, no prior code reused):

- ASH_COATED_OSMIUM  : mid stays in a tight band ~9979-10023 around 10000.
  Treat as mean-reverting; anchor fair at a constant 10000 and market-make.
- INTARIAN_PEPPER_ROOT: mid drifts strongly across the day (e.g. 11998 ->
  ~12900 on day 0). Treat as trending; anchor fair on a short EMA of the
  micro-price and make markets around it with position skew.

Position limit is 80 on each product. Strategy is a standard
skewed market-maker with take-the-mispriced-levels logic, plus a MAF bid
for round 2's auction.
"""

from __future__ import annotations

import json
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


ASH = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"

POSITION_LIMIT = {ASH: 80, PEPPER: 80}

# Anchor fair for the stationary product.
ASH_ANCHOR = 10000.0

# EMA half-life in timesteps (each tick = 100 in this exchange).
PEPPER_EMA_ALPHA = 0.05  # ~ lookback of ~20 ticks

# Quote half-spread we aim to post around fair.
BASE_HALF_SPREAD = {ASH: 2.0, PEPPER: 3.0}

# How much to skew quotes per unit of inventory (fraction of position limit).
SKEW_PER_LIMIT = {ASH: 3.0, PEPPER: 4.0}

# Take threshold: how far below/above fair we demand before crossing.
TAKE_EDGE = {ASH: 1.0, PEPPER: 2.0}

# Passive quote size per side.
QUOTE_SIZE = {ASH: 20, PEPPER: 15}


def _best_bid(depth) -> Tuple[int, int] | None:
    if not depth.buy_orders:
        return None
    p = max(depth.buy_orders)
    return p, depth.buy_orders[p]


def _best_ask(depth) -> Tuple[int, int] | None:
    if not depth.sell_orders:
        return None
    p = min(depth.sell_orders)
    # sell_orders quantities are negative in the prosperity format
    return p, -depth.sell_orders[p]


def _micro_price(depth) -> float | None:
    bb = _best_bid(depth)
    ba = _best_ask(depth)
    if bb is None or ba is None:
        if bb is not None:
            return float(bb[0])
        if ba is not None:
            return float(ba[0])
        return None
    bp, bq = bb
    ap, aq = ba
    total = bq + aq
    if total <= 0:
        return (bp + ap) / 2.0
    return (bp * aq + ap * bq) / total  # weighted toward thin side


def _mid(depth) -> float | None:
    bb = _best_bid(depth)
    ba = _best_ask(depth)
    if bb is None and ba is None:
        return None
    if bb is None:
        return float(ba[0])
    if ba is None:
        return float(bb[0])
    return (bb[0] + ba[0]) / 2.0


def _take_orders(
    symbol: str,
    depth,
    fair: float,
    position: int,
    take_edge: float,
    limit: int,
) -> Tuple[List[Order], int, int]:
    """Cross the book for any level strictly better than fair ± take_edge.
    Returns orders plus the delta to long-buy and short-sell capacity used."""
    orders: List[Order] = []
    bought = 0
    sold = 0

    # Buy side: hit asks priced <= fair - take_edge.
    asks = sorted(depth.sell_orders.items())
    for price, qty in asks:
        qty = -qty  # convert to positive available size
        if price <= fair - take_edge:
            remaining = limit - (position + bought)
            if remaining <= 0:
                break
            take = min(qty, remaining)
            if take > 0:
                orders.append(Order(symbol, price, take))
                bought += take
        else:
            break

    # Sell side: hit bids priced >= fair + take_edge.
    bids = sorted(depth.buy_orders.items(), reverse=True)
    for price, qty in bids:
        if price >= fair + take_edge:
            remaining = limit + (position - sold)  # how much more we can go short
            if remaining <= 0:
                break
            take = min(qty, remaining)
            if take > 0:
                orders.append(Order(symbol, price, -take))
                sold += take
        else:
            break

    return orders, bought, sold


def _make_orders(
    symbol: str,
    depth,
    fair: float,
    position_after_takes: int,
    half_spread: float,
    skew_per_limit: float,
    size: int,
    limit: int,
) -> List[Order]:
    """Post passive quotes around fair, skewed by inventory."""
    orders: List[Order] = []

    skew = skew_per_limit * (position_after_takes / limit)
    desired_bid = fair - half_spread - skew
    desired_ask = fair + half_spread - skew

    # Don't cross the current book with our quotes.
    bb = _best_bid(depth)
    ba = _best_ask(depth)
    bid_price = int(round(desired_bid))
    ask_price = int(round(desired_ask))

    if ba is not None:
        bid_price = min(bid_price, ba[0] - 1)
    if bb is not None:
        ask_price = max(ask_price, bb[0] + 1)
    if bid_price >= ask_price:
        ask_price = bid_price + 1

    # Respect position limit with the posted quantity.
    buy_capacity = limit - position_after_takes
    sell_capacity = limit + position_after_takes

    bid_size = max(0, min(size, buy_capacity))
    ask_size = max(0, min(size, sell_capacity))

    if bid_size > 0:
        orders.append(Order(symbol, bid_price, bid_size))
    if ask_size > 0:
        orders.append(Order(symbol, ask_price, -ask_size))
    return orders


class Trader:
    def bid(self) -> int:
        # MAF bid for round 2. We don't know opponents' bids; pay a small
        # fraction of an average day's expected trading PnL to claim the
        # top-50% access. 500 is modest relative to per-day PnL in this
        # market scale and ignored by local backtests regardless.
        return 500

    def run(self, state: TradingState):
        # Load prior state (EMA of pepper micro-price).
        mem: dict
        try:
            mem = json.loads(state.traderData) if state.traderData else {}
            if not isinstance(mem, dict):
                mem = {}
        except Exception:
            mem = {}

        pepper_ema = mem.get("pepper_ema")

        result: Dict[str, List[Order]] = {sym: [] for sym in state.order_depths}

        # --- ASH: mean-reverting around anchor ---------------------------------
        if ASH in state.order_depths:
            depth = state.order_depths[ASH]
            pos = int(state.position.get(ASH, 0))
            limit = POSITION_LIMIT[ASH]
            fair = ASH_ANCHOR

            takes, bought, sold = _take_orders(
                ASH, depth, fair, pos, TAKE_EDGE[ASH], limit
            )
            new_pos = pos + bought - sold
            makes = _make_orders(
                ASH, depth, fair, new_pos,
                BASE_HALF_SPREAD[ASH], SKEW_PER_LIMIT[ASH],
                QUOTE_SIZE[ASH], limit,
            )
            result[ASH] = takes + makes

        # --- PEPPER: trending, fair = EMA of micro-price -----------------------
        if PEPPER in state.order_depths:
            depth = state.order_depths[PEPPER]
            pos = int(state.position.get(PEPPER, 0))
            limit = POSITION_LIMIT[PEPPER]

            mp = _micro_price(depth)
            if mp is None:
                mp = _mid(depth)

            if mp is not None:
                if pepper_ema is None:
                    pepper_ema = mp
                else:
                    pepper_ema = (
                        PEPPER_EMA_ALPHA * mp + (1.0 - PEPPER_EMA_ALPHA) * pepper_ema
                    )

                fair = pepper_ema
                takes, bought, sold = _take_orders(
                    PEPPER, depth, fair, pos, TAKE_EDGE[PEPPER], limit
                )
                new_pos = pos + bought - sold
                makes = _make_orders(
                    PEPPER, depth, fair, new_pos,
                    BASE_HALF_SPREAD[PEPPER], SKEW_PER_LIMIT[PEPPER],
                    QUOTE_SIZE[PEPPER], limit,
                )
                result[PEPPER] = takes + makes

        mem["pepper_ema"] = pepper_ema
        trader_data = json.dumps(mem, separators=(",", ":"))
        conversions = 0
        return result, conversions, trader_data
