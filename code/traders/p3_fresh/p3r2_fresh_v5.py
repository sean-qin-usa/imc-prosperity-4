"""
P3 R2 v4 — per-product head-to-head vs Timo.  2026-04-23.

Each handler is designed to MATCH OR BEAT Timo's FrankfurtHedgehogs_polished
approach on that product.  Data is same round-2 data; backtester is the
same `prosperity3bt`.

Per-product design notes:

  RESIN — StaticTrader logic:
      - Fair = wall_mid = (min_visible_bid + max_visible_ask) / 2  (wall
        midpoint of FULL visible depth, not top-of-book).  For Resin this
        almost always equals 10 000 but it's defended if the book skews.
      - TAKE: any ask ≤ wall_mid − 1 (buy); any bid ≥ wall_mid + 1 (sell).
      - FLATTEN: if short, buy any ask ≤ wall_mid; if long, sell any bid ≥ wall_mid.
      - MAKE: overbid best bid (unless vol=1) up to wall_mid − 1,
              underbid best ask (unless vol=1) down to wall_mid + 1.
              Post at FULL remaining capacity.
      - Net: this is what Timo's StaticTrader does.  It was 55 % better
        than our v1 ACO-scaled handler (117 k vs 75 k).

  KELP — DynamicTrader logic + Olivia:
      - Base: bid at bid_wall+1, ask at ask_wall-1, full size.
      - Olivia LONG (bought in last 500 ticks): bid at ask_wall (aggressive)
        up to position 40.
      - Olivia SHORT: ask at bid_wall aggressive, target -40.
      - Olivia NEUTRAL but direction flagged: pull bid down to bid_wall
        or push ask up to ask_wall on the disfavored side.

  SQUID — InkTrader logic (pure Olivia follower):
      - target = +50 on Olivia LONG, -50 on SHORT, 0 otherwise.
      - Lift asks / hit bids to reach target in one tick.

  CROISSANTS — Olivia on Croissants is the informed signal per Timo's
      ETF logic.  In R2 the Croissants standalone trade was ~20k.
      Implement an Olivia-follower on Croissants analogous to Squid.

  BASKETS — keep v1's fixed-threshold trade (+126 k / 3-day).  Timo's
      polished basket code has a bug (`list.sort()` returns None in
      calculate_spread) that disables basket trading — we preserve our
      working alpha.  Add his "close at zero" logic: when spread is
      on the near side of threshold and we already have a position,
      close into touch to free capacity.

  JAMS / DJEMBES — skip.  Timo doesn't trade them standalone and
      they're covered via basket position.
"""
from typing import Dict, List, Optional
import json
import math

from datamodel import Order, OrderDepth, TradingState


INFORMED = "Olivia"
LONG, NEUTRAL, SHORT = 1, 0, -1


class Trader:
    B1_W = {"CROISSANTS": 6, "JAMS": 3, "DJEMBES": 1}
    B2_W = {"CROISSANTS": 4, "JAMS": 2}

    LIMITS = {
        "RAINFOREST_RESIN": 50, "KELP": 50, "SQUID_INK": 50,
        "CROISSANTS": 250, "JAMS": 350, "DJEMBES": 60,
        "PICNIC_BASKET1": 60, "PICNIC_BASKET2": 100,
    }

    # Basket thresholds (unchanged — sensitivity-validated v1)
    B1_UPPER = 80.0
    B1_LOWER = -40.0
    B2_UPPER = 80.0
    B2_LOWER = -40.0
    BASKET_TRADE_SIZE = 15

    # Olivia memory window (ticks)
    OLIVIA_WINDOW = 500

    # ---------- book helpers ----------
    def _walls(self, od: OrderDepth):
        """Returns (bid_wall, wall_mid, ask_wall) from FULL visible depth."""
        if not od.buy_orders or not od.sell_orders: return None, None, None
        bid_wall = min(od.buy_orders.keys())   # deepest visible bid
        ask_wall = max(od.sell_orders.keys())  # deepest visible ask
        return bid_wall, (bid_wall + ask_wall) / 2, ask_wall

    def _top(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders: return None, None
        return max(od.buy_orders.keys()), min(od.sell_orders.keys())

    # ---------- Olivia detection ----------
    def _olivia_ts(self, state: TradingState, product: str, saved_store: Dict):
        prev = saved_store.get(f"{product}_OL", [None, None])
        bought_ts, sold_ts = prev
        trades = (state.market_trades.get(product, []) + state.own_trades.get(product, []))
        for t in trades:
            if getattr(t, "buyer", "") == INFORMED:
                bought_ts = t.timestamp
            if getattr(t, "seller", "") == INFORMED:
                sold_ts = t.timestamp
        saved_store[f"{product}_OL"] = [bought_ts, sold_ts]
        if bought_ts is None and sold_ts is None: direction = NEUTRAL
        elif sold_ts is None: direction = LONG
        elif bought_ts is None: direction = SHORT
        elif sold_ts > bought_ts: direction = SHORT
        elif sold_ts < bought_ts: direction = LONG
        else: direction = NEUTRAL
        return direction, bought_ts, sold_ts

    # ---------- RESIN (Timo StaticTrader, exact) ----------
    def _trade_resin(self, od: OrderDepth, pos: int) -> List[Order]:
        prod = "RAINFOREST_RESIN"
        limit = self.LIMITS[prod]
        bid_wall, wall_mid, ask_wall = self._walls(od)
        if wall_mid is None: return []
        mkt_sells = dict(sorted(od.sell_orders.items(), key=lambda x: x[0]))
        mkt_buys = dict(sorted(od.buy_orders.items(), key=lambda x: x[0], reverse=True))
        orders: List[Order] = []
        buy_cap = limit - pos
        sell_cap = limit + pos
        # TAKE
        for sp, sv in mkt_sells.items():
            sv = abs(sv)
            if buy_cap <= 0: break
            if sp <= wall_mid - 1:
                q = min(sv, buy_cap); orders.append(Order(prod, sp, q)); buy_cap -= q
            elif sp <= wall_mid and pos < 0:
                q = min(sv, abs(pos), buy_cap); orders.append(Order(prod, sp, q)); buy_cap -= q
        for bp, bv in mkt_buys.items():
            bv = abs(bv)
            if sell_cap <= 0: break
            if bp >= wall_mid + 1:
                q = min(bv, sell_cap); orders.append(Order(prod, bp, -q)); sell_cap -= q
            elif bp >= wall_mid and pos > 0:
                q = min(bv, pos, sell_cap); orders.append(Order(prod, bp, -q)); sell_cap -= q
        # MAKE
        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)
        for bp, bv in mkt_buys.items():
            overbid = bp + 1
            if bv > 1 and overbid < wall_mid: bid_price = max(bid_price, overbid); break
            elif bp < wall_mid: bid_price = max(bid_price, bp); break
        for sp, sv in mkt_sells.items():
            underbid = sp - 1
            if abs(sv) > 1 and underbid > wall_mid: ask_price = min(ask_price, underbid); break
            elif sp > wall_mid: ask_price = min(ask_price, sp); break
        # Timo posts full remaining capacity at the overbid.
        if buy_cap > 0: orders.append(Order(prod, bid_price, buy_cap))
        if sell_cap > 0: orders.append(Order(prod, ask_price, -sell_cap))
        return orders

    # ---------- KELP (Timo DynamicTrader + Olivia + TAKE layer) ----------
    def _trade_kelp(self, od: OrderDepth, pos: int, ts: int, olivia_dir, olivia_bought_ts, olivia_sold_ts) -> List[Order]:
        prod = "KELP"
        limit = self.LIMITS[prod]
        bid_wall, wall_mid, ask_wall = self._walls(od)
        if wall_mid is None: return []
        mkt_sells = dict(sorted(od.sell_orders.items(), key=lambda x: x[0]))
        mkt_buys = dict(sorted(od.buy_orders.items(), key=lambda x: x[0], reverse=True))
        orders: List[Order] = []
        buy_cap = limit - pos
        sell_cap = limit + pos

        # TAKE LAYER (new vs Timo's Kelp, which is pure MM)
        # Any ask strictly below wall_mid = free edge.  Lift it.
        for sp, sv in mkt_sells.items():
            sv = abs(sv)
            if buy_cap <= 0: break
            if sp <= wall_mid - 1:
                q = min(sv, buy_cap); orders.append(Order(prod, sp, q)); buy_cap -= q
            else: break  # sorted ascending; stop once no longer favorable
        for bp, bv in mkt_buys.items():
            bv = abs(bv)
            if sell_cap <= 0: break
            if bp >= wall_mid + 1:
                q = min(bv, sell_cap); orders.append(Order(prod, bp, -q)); sell_cap -= q
            else: break

        # MAKE LAYER (Timo's logic unchanged)
        bid_price = bid_wall + 1
        bid_vol = buy_cap
        if olivia_bought_ts is not None and olivia_bought_ts + self.OLIVIA_WINDOW >= ts:
            if pos < 40:
                bid_price = ask_wall
                bid_vol = min(40 - pos, buy_cap)
        else:
            if wall_mid - bid_price < 1 and olivia_dir == SHORT and pos > -40:
                bid_price = bid_wall
        if bid_vol > 0: orders.append(Order(prod, int(bid_price), bid_vol))

        ask_price = ask_wall - 1
        ask_vol = sell_cap
        if olivia_sold_ts is not None and olivia_sold_ts + self.OLIVIA_WINDOW >= ts:
            if pos > -40:
                ask_price = bid_wall
                ask_vol = min(40 + pos, sell_cap)
        if ask_price - wall_mid < 1 and olivia_dir == LONG and pos < 40:
            ask_price = ask_wall
        if ask_vol > 0: orders.append(Order(prod, int(ask_price), -ask_vol))
        return orders

    # ---------- SQUID (Olivia follower) ----------
    def _trade_squid(self, od: OrderDepth, pos: int, olivia_dir) -> List[Order]:
        prod = "SQUID_INK"
        limit = self.LIMITS[prod]
        bid_wall, _, ask_wall = self._walls(od)
        if bid_wall is None: return []
        if olivia_dir == LONG: target = limit
        elif olivia_dir == SHORT: target = -limit
        else: target = 0
        remaining = target - pos
        if remaining > 0:
            return [Order(prod, int(ask_wall), remaining)]
        elif remaining < 0:
            return [Order(prod, int(bid_wall), remaining)]
        return []

    # ---------- CROISSANTS (Olivia follower, uses aggressive wall lift/hit) ----------
    def _trade_croissants(self, od: OrderDepth, pos: int, olivia_dir) -> List[Order]:
        prod = "CROISSANTS"
        limit = self.LIMITS[prod]
        bid_wall, _, ask_wall = self._walls(od)
        if bid_wall is None: return []
        if olivia_dir == LONG: target = limit
        elif olivia_dir == SHORT: target = -limit
        else: target = 0
        remaining = target - pos
        if remaining > 0:
            return [Order(prod, int(ask_wall), remaining)]
        elif remaining < 0:
            return [Order(prod, int(bid_wall), remaining)]
        return []

    # ---------- BASKETS (v1 fixed-threshold, unchanged) ----------
    def _basket_orders(self, name, od_basket, od_legs, weights,
                       pos_basket, limit, upper, lower):
        if not od_basket.buy_orders or not od_basket.sell_orders: return []
        bb = max(od_basket.buy_orders.keys()); ba = min(od_basket.sell_orders.keys())
        basket_mid = (bb + ba) / 2
        synth_mid = 0.0
        for leg, w in weights.items():
            if leg not in od_legs: return []
            od_ = od_legs[leg]
            if not od_.buy_orders or not od_.sell_orders: return []
            synth_mid += w * (max(od_.buy_orders) + min(od_.sell_orders)) / 2
        spread = basket_mid - synth_mid
        orders: List[Order] = []
        if spread > upper and pos_basket > -limit:
            q = min(self.BASKET_TRADE_SIZE, limit + pos_basket, abs(od_basket.buy_orders[bb]))
            if q > 0: orders.append(Order(name, bb, -q))
        elif spread < lower and pos_basket < limit:
            q = min(self.BASKET_TRADE_SIZE, limit - pos_basket, abs(od_basket.sell_orders[ba]))
            if q > 0: orders.append(Order(name, ba, q))
        # close-at-zero: if on the near side of threshold AND already have position, close into touch
        elif spread > 0 and pos_basket > 0:
            q = min(pos_basket, abs(od_basket.buy_orders[bb]))
            if q > 0: orders.append(Order(name, bb, -q))
        elif spread < 0 and pos_basket < 0:
            q = min(abs(pos_basket), abs(od_basket.sell_orders[ba]))
            if q > 0: orders.append(Order(name, ba, q))
        return orders

    # ---------- main ----------
    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try: saved = json.loads(state.traderData)
            except Exception: saved = {}

        result: Dict[str, List[Order]] = {}
        od = state.order_depths
        pos = state.position

        # Olivia direction per relevant product
        kelp_dir, kelp_b_ts, kelp_s_ts = self._olivia_ts(state, "KELP", saved)
        squid_dir, _, _ = self._olivia_ts(state, "SQUID_INK", saved)
        cro_dir, _, _ = self._olivia_ts(state, "CROISSANTS", saved)

        if "RAINFOREST_RESIN" in od:
            result["RAINFOREST_RESIN"] = self._trade_resin(od["RAINFOREST_RESIN"], pos.get("RAINFOREST_RESIN", 0))
        if "KELP" in od:
            result["KELP"] = self._trade_kelp(od["KELP"], pos.get("KELP", 0), state.timestamp, kelp_dir, kelp_b_ts, kelp_s_ts)
        if "SQUID_INK" in od:
            result["SQUID_INK"] = self._trade_squid(od["SQUID_INK"], pos.get("SQUID_INK", 0), squid_dir)
        if "CROISSANTS" in od:
            result["CROISSANTS"] = self._trade_croissants(od["CROISSANTS"], pos.get("CROISSANTS", 0), cro_dir)
        if "PICNIC_BASKET1" in od:
            legs = {k: od[k] for k in self.B1_W if k in od}
            if len(legs) == len(self.B1_W):
                result["PICNIC_BASKET1"] = self._basket_orders(
                    "PICNIC_BASKET1", od["PICNIC_BASKET1"], legs, self.B1_W,
                    pos.get("PICNIC_BASKET1", 0), self.LIMITS["PICNIC_BASKET1"],
                    self.B1_UPPER, self.B1_LOWER)
        if "PICNIC_BASKET2" in od:
            legs = {k: od[k] for k in self.B2_W if k in od}
            if len(legs) == len(self.B2_W):
                result["PICNIC_BASKET2"] = self._basket_orders(
                    "PICNIC_BASKET2", od["PICNIC_BASKET2"], legs, self.B2_W,
                    pos.get("PICNIC_BASKET2", 0), self.LIMITS["PICNIC_BASKET2"],
                    self.B2_UPPER, self.B2_LOWER)

        return result, 0, json.dumps(saved, separators=(",", ":"))
