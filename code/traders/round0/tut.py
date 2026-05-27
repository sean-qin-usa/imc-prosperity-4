"""
Round 1 (Tutorial) Strategy: EMERALDS + TOMATOES
=================================================

EMERALDS — pure market making at fair value 10000
--------------------------------------------------
Finding: Bots permanently post at 9992 (ask) and 10008 (bid).
The fair value is provably 10000 — mid is at 10000 for 96.7% of ticks,
and NEVER leaves [9996, 10004].

Strategy: Post buy at 9999, sell at 10001.
- When a bot sells at 9992 it also fills our buy order at 9999 (profit 1 vs fair)
- When a bot buys at 10008 it also fills our sell at 10001 (profit 1 vs fair)
- Inventory skew: if we drift long, lower both quotes by 1 to encourage rebalancing

TOMATOES — Kalman fair-value + aggressive mean reversion taking
---------------------------------------------------------------
Finding: Tomatoes has a ~5-tick mean reversion half-life but also a multi-day trend.
The spread is ±6.5 pts from mid. Market making INSIDE the spread gives 0 fills —
the 6.5 pt ask premium is never crossed passively. Instead we TAKE aggressively
when price diverges from fair value, and post passively only as backup.

IMPORTANT NOTES on Prosperity 4 environment:
- Trader is re-instantiated every tick. ALL state must be persisted via traderData JSON.
- run() must return a 3-tuple: (orders_dict, conversions, traderData_string)
- Allowed stdlib: json, math, typing, statistics. Also: numpy, pandas, jsonpickle.
- Position limits: EMERALDS=80, TOMATOES=80.
"""

import json
import math
from typing import Dict, List, Optional

from datamodel import OrderDepth, TradingState, Order


# ──────────────────────────────────────────────────────────────────────
# Kalman Filter for Tomatoes fair value tracking
# ──────────────────────────────────────────────────────────────────────

class KalmanFilter:
    """
    1-D Kalman filter for tracking a slowly drifting fair value.
    process_var (Q): how much we expect fair value to move each tick.
    obs_var     (R): how noisy the mid-price is as an observation.
    """
    def __init__(self, process_var: float = 2.0, obs_var: float = 8.0):
        self.Q = process_var
        self.R = obs_var
        self.x: Optional[float] = None   # state estimate (fair value)
        self.P: float = 1.0              # state variance

    def update(self, z: float) -> float:
        if self.x is None:
            self.x = z
            return z
        P_pred = self.P + self.Q
        K = P_pred / (P_pred + self.R)
        self.x = self.x + K * (z - self.x)
        self.P = (1 - K) * P_pred
        return self.x

    def to_dict(self) -> dict:
        return {"x": self.x, "P": self.P}

    @classmethod
    def from_dict(cls, d: dict, process_var: float = 2.0, obs_var: float = 8.0) -> "KalmanFilter":
        kf = cls(process_var, obs_var)
        kf.x = d.get("x")
        kf.P = d.get("P", 1.0)
        return kf


# ──────────────────────────────────────────────────────────────────────
# Trader — exact interface Prosperity expects
# ──────────────────────────────────────────────────────────────────────

class Trader:
    # Position limits set by Prosperity for the tutorial round
    LIMITS = {
        "EMERALDS": 80,
        "TOMATOES": 80,
    }

    # Emeralds fair value — fixed from historical data analysis
    EMERALD_FAIR = 10_000

    def run(self, state: TradingState):
        """
        Called every tick by Prosperity.
        Returns: (orders_dict, conversions, traderData)
          - orders_dict : {symbol: [Order, ...]}
          - conversions : int (0 for tutorial round — no conversion product)
          - traderData  : str (serialised state for next tick)
        """

        # ── Restore per-tick state from traderData JSON ─────────────────
        # NOTE: Prosperity re-instantiates Trader each tick, so we cannot
        # rely on instance variables. Everything persistent must come from
        # state.traderData.
        saved: dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        tom_kf = KalmanFilter.from_dict(saved.get("tom_kf", {}))

        # ── Build orders ─────────────────────────────────────────────────
        orders: Dict[str, List[Order]] = {}

        if "EMERALDS" in state.order_depths:
            orders["EMERALDS"] = self._trade_emeralds(state)

        if "TOMATOES" in state.order_depths:
            orders["TOMATOES"] = self._trade_tomatoes(state, tom_kf)

        # ── Persist state for next tick ──────────────────────────────────
        trader_data = json.dumps({"tom_kf": tom_kf.to_dict()})

        return orders, 0, trader_data

    # ── EMERALDS strategy ─────────────────────────────────────────────

    def _trade_emeralds(self, state: TradingState) -> List[Order]:
        od: OrderDepth = state.order_depths["EMERALDS"]
        pos = state.position.get("EMERALDS", 0)
        limit = self.LIMITS["EMERALDS"]
        fair = self.EMERALD_FAIR
        orders: List[Order] = []

        # Inventory skew: nudge quotes to push position back toward zero
        # when we are more than 50% utilised on either side.
        skew = 0
        if pos > limit * 0.5:
            skew = 1    # shift both quotes DOWN → easier to sell
        elif pos < -limit * 0.5:
            skew = -1   # shift both quotes UP  → easier to buy

        our_bid = fair - 1 - skew   # normally 9999
        our_ask = fair + 1 - skew   # normally 10001

        buy_cap  = limit - pos   # max additional long we can add
        sell_cap = limit + pos   # max additional short we can add

        # ── AGGRESSIVE: hit any ask that is strictly below fair value ──
        # (rare, but captures any mispriced bot quote)
        if od.sell_orders and buy_cap > 0:
            for ask_price in sorted(od.sell_orders.keys()):
                if ask_price >= fair:
                    break
                vol = min(-od.sell_orders[ask_price], buy_cap)
                orders.append(Order("EMERALDS", ask_price, vol))
                buy_cap -= vol
                if buy_cap <= 0:
                    break

        # ── AGGRESSIVE: lift any bid that is strictly above fair value ──
        if od.buy_orders and sell_cap > 0:
            for bid_price in sorted(od.buy_orders.keys(), reverse=True):
                if bid_price <= fair:
                    break
                vol = min(od.buy_orders[bid_price], sell_cap)
                orders.append(Order("EMERALDS", bid_price, -vol))
                sell_cap -= vol
                if sell_cap <= 0:
                    break

        # ── PASSIVE: post tight quotes just inside the bot spread ──────
        if buy_cap > 0:
            orders.append(Order("EMERALDS", our_bid, buy_cap))
        if sell_cap > 0:
            orders.append(Order("EMERALDS", our_ask, -sell_cap))

        return orders

    # ── TOMATOES strategy ─────────────────────────────────────────────

    def _trade_tomatoes(self, state: TradingState, kf: KalmanFilter) -> List[Order]:
        od: OrderDepth = state.order_depths["TOMATOES"]
        pos = state.position.get("TOMATOES", 0)
        limit = self.LIMITS["TOMATOES"]
        orders: List[Order] = []

        if not od.buy_orders or not od.sell_orders:
            return orders

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        mid = (best_bid + best_ask) / 2.0

        # Update Kalman fair value (mutates kf in place; caller persists it)
        fair = kf.update(mid)

        buy_cap  = limit - pos
        sell_cap = limit + pos

        # ── AGGRESSIVE TAKING ──────────────────────────────────────────
        # Enter when the best available price is more than TAKE_THRESHOLD
        # away from our Kalman fair value estimate. This exploits the mean-
        # reverting nature of Tomatoes without relying on passive fills.
        TAKE_THRESHOLD = 2.0

        if best_ask < fair - TAKE_THRESHOLD and buy_cap > 0:
            vol = min(-od.sell_orders[best_ask], buy_cap)
            orders.append(Order("TOMATOES", best_ask, vol))
            buy_cap -= vol

        if best_bid > fair + TAKE_THRESHOLD and sell_cap > 0:
            vol = min(od.buy_orders[best_bid], sell_cap)
            orders.append(Order("TOMATOES", best_bid, -vol))
            sell_cap -= vol

        # ── PASSIVE POSTING ────────────────────────────────────────────
        # Post limit orders further inside the spread as backup liquidity.
        # POST_OFFSET must be large enough that we are not adverse-selected,
        # but inside the natural ~6.5pt half-spread so we occasionally fill.
        POST_OFFSET = 4

        if buy_cap > 0:
            orders.append(Order("TOMATOES", round(fair) - POST_OFFSET, buy_cap))
        if sell_cap > 0:
            orders.append(Order("TOMATOES", round(fair) + POST_OFFSET, -sell_cap))

        return orders