"""
Round-2 strategy v2. Fresh rewrite from v1 diagnosis.

v1 result (round2_csv, same-tick fill model, 3 days):
    day -1: ASH = +7522  PEPPER = -65902  total = -58380
    day  0: ASH = +6352  PEPPER = -54772  total = -48420
    day  1: ASH = +7199  PEPPER = -52818  total = -45619

ASH market-making is profitable. PEPPER drifts ~+1000/day (near-linear
in the data) and a two-sided market-maker gets adversely selected,
ending each day short into the rise.

v2 keeps ASH market-making and replaces PEPPER with a momentum
trend-follower:
- estimate short vs long EMA of micro-price
- target long (+limit) when short > long by a threshold
- target short (-limit) when short < long by a threshold
- flatten when signal is inconclusive
- execute the delta aggressively against the visible book

Still submits a MAF bid() for round 2's auction.
"""

from __future__ import annotations

import json
from typing import Dict, List, Tuple

from datamodel import Order, TradingState


ASH = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"

POSITION_LIMIT = {ASH: 80, PEPPER: 80}

# --- ASH (stationary mean-reverting) ---
ASH_ANCHOR = 10000.0
ASH_HALF_SPREAD = 2.0
ASH_SKEW_PER_LIMIT = 3.0
ASH_TAKE_EDGE = 1.0
ASH_QUOTE_SIZE = 20

# --- PEPPER (trending) ---
PEPPER_EMA_FAST = 0.30   # ~3 ticks effective
PEPPER_EMA_SLOW = 0.02   # ~50 ticks effective
PEPPER_SIGNAL_THRESHOLD = 0.5   # points of EMA separation to trade


def _best_bid(depth) -> Tuple[int, int] | None:
    if not depth.buy_orders:
        return None
    p = max(depth.buy_orders)
    return p, depth.buy_orders[p]


def _best_ask(depth) -> Tuple[int, int] | None:
    if not depth.sell_orders:
        return None
    p = min(depth.sell_orders)
    return p, -depth.sell_orders[p]  # convert to positive size


def _micro_price(depth) -> float | None:
    bb = _best_bid(depth)
    ba = _best_ask(depth)
    if bb is None and ba is None:
        return None
    if bb is None:
        return float(ba[0])
    if ba is None:
        return float(bb[0])
    bp, bq = bb
    ap, aq = ba
    total = bq + aq
    if total <= 0:
        return (bp + ap) / 2.0
    return (bp * aq + ap * bq) / total


def _take_orders(
    symbol: str,
    depth,
    fair: float,
    position: int,
    take_edge: float,
    limit: int,
) -> Tuple[List[Order], int, int]:
    orders: List[Order] = []
    bought = 0
    sold = 0

    for price, qty in sorted(depth.sell_orders.items()):
        qty = -qty
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

    for price, qty in sorted(depth.buy_orders.items(), reverse=True):
        if price >= fair + take_edge:
            remaining = limit + (position - sold)
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
    orders: List[Order] = []

    skew = skew_per_limit * (position_after_takes / limit)
    bid_price = int(round(fair - half_spread - skew))
    ask_price = int(round(fair + half_spread - skew))

    bb = _best_bid(depth)
    ba = _best_ask(depth)
    if ba is not None:
        bid_price = min(bid_price, ba[0] - 1)
    if bb is not None:
        ask_price = max(ask_price, bb[0] + 1)
    if bid_price >= ask_price:
        ask_price = bid_price + 1

    buy_capacity = limit - position_after_takes
    sell_capacity = limit + position_after_takes

    bid_size = max(0, min(size, buy_capacity))
    ask_size = max(0, min(size, sell_capacity))

    if bid_size > 0:
        orders.append(Order(symbol, bid_price, bid_size))
    if ask_size > 0:
        orders.append(Order(symbol, ask_price, -ask_size))
    return orders


def _trend_orders(
    symbol: str,
    depth,
    target_position: int,
    current_position: int,
) -> List[Order]:
    """Drive toward target_position by crossing the book aggressively.

    Only trades as far as visible liquidity allows each tick; the next
    tick will continue to close the gap.
    """
    orders: List[Order] = []
    delta = target_position - current_position
    if delta == 0:
        return orders

    if delta > 0:
        remaining = delta
        for price, qty in sorted(depth.sell_orders.items()):
            qty = -qty
            take = min(qty, remaining)
            if take > 0:
                orders.append(Order(symbol, price, take))
                remaining -= take
            if remaining <= 0:
                break
    else:
        remaining = -delta
        for price, qty in sorted(depth.buy_orders.items(), reverse=True):
            take = min(qty, remaining)
            if take > 0:
                orders.append(Order(symbol, price, -take))
                remaining -= take
            if remaining <= 0:
                break
    return orders


class Trader:
    def bid(self) -> int:
        # Modest MAF bid; ignored in local backtests.
        return 500

    def run(self, state: TradingState):
        try:
            mem = json.loads(state.traderData) if state.traderData else {}
            if not isinstance(mem, dict):
                mem = {}
        except Exception:
            mem = {}

        pepper_fast = mem.get("pepper_fast")
        pepper_slow = mem.get("pepper_slow")

        result: Dict[str, List[Order]] = {sym: [] for sym in state.order_depths}

        # --- ASH ------------------------------------------------------------
        if ASH in state.order_depths:
            depth = state.order_depths[ASH]
            pos = int(state.position.get(ASH, 0))
            limit = POSITION_LIMIT[ASH]
            fair = ASH_ANCHOR
            takes, b, s = _take_orders(ASH, depth, fair, pos, ASH_TAKE_EDGE, limit)
            new_pos = pos + b - s
            makes = _make_orders(
                ASH, depth, fair, new_pos,
                ASH_HALF_SPREAD, ASH_SKEW_PER_LIMIT, ASH_QUOTE_SIZE, limit,
            )
            result[ASH] = takes + makes

        # --- PEPPER (momentum) ---------------------------------------------
        if PEPPER in state.order_depths:
            depth = state.order_depths[PEPPER]
            pos = int(state.position.get(PEPPER, 0))
            limit = POSITION_LIMIT[PEPPER]

            mp = _micro_price(depth)
            if mp is not None:
                pepper_fast = (
                    mp if pepper_fast is None
                    else PEPPER_EMA_FAST * mp + (1 - PEPPER_EMA_FAST) * pepper_fast
                )
                pepper_slow = (
                    mp if pepper_slow is None
                    else PEPPER_EMA_SLOW * mp + (1 - PEPPER_EMA_SLOW) * pepper_slow
                )

                signal = pepper_fast - pepper_slow
                if signal > PEPPER_SIGNAL_THRESHOLD:
                    target = limit
                elif signal < -PEPPER_SIGNAL_THRESHOLD:
                    target = -limit
                else:
                    target = 0

                result[PEPPER] = _trend_orders(PEPPER, depth, target, pos)

        mem["pepper_fast"] = pepper_fast
        mem["pepper_slow"] = pepper_slow
        trader_data = json.dumps(mem, separators=(",", ":"))
        return result, 0, trader_data
