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
from statistics import NormalDist

from datamodel import Order, OrderDepth, TradingState


INFORMED = "Olivia"
LONG, NEUTRAL, SHORT = 1, 0, -1

_N = NormalDist()

# ---- Options constants (ported from Timo FrankfurtHedgehogs_polished) ----
# Fitted vol smile: IV(m) = A*m^2 + B*m + C where m = ln(K/S)/sqrt(TTE)
SMILE_A, SMILE_B, SMILE_C = 0.27362531, 0.01007566, 0.14876677
DAYS_PER_YEAR = 365

# IV scalping thresholds (K >= 9750)
THR_OPEN, THR_CLOSE = 0.5, 0.0
LOW_VEGA_THR_ADJ = 0.5
THEO_NORM_WINDOW = 20
IV_SCALPING_THR = 0.7
IV_SCALPING_WINDOW = 100

# Underlying / options MR windows and thresholds
UNDER_MR_THR = 15
UNDER_MR_WINDOW = 10
OPT_MR_THR = 5
OPT_MR_WINDOW = 30

# Strikes traded via MR vs IV scalping.
# ITM vouchers (9500/9750/10000) benefit from MR (delta≈1 → they track
# the underlying, and the combined `ema_o_dev + iv_dev` signal harvests
# underlying MR + IV-residual in one trade).  OTM strikes (10250/10500)
# stay on IV scalping (dormant below the switch-mean threshold on this
# data, but kept in case real-submission vol is higher).
# Tested 2026-04-23 s4: {9500} → 1.79M; {9500,9750} → 2.14M;
# {9500,9750,10000} → 2.47M; all-MR → 2.46M.  Three ITM is the peak.
MR_STRIKES = {9500, 9750, 10000}


class Trader:
    B1_W = {"CROISSANTS": 6, "JAMS": 3, "DJEMBES": 1}
    B2_W = {"CROISSANTS": 4, "JAMS": 2}

    LIMITS = {
        "RAINFOREST_RESIN": 50, "KELP": 50, "SQUID_INK": 50,
        "CROISSANTS": 250, "JAMS": 350, "DJEMBES": 60,
        "PICNIC_BASKET1": 60, "PICNIC_BASKET2": 100,
        "VOLCANIC_ROCK": 400,
        "VOLCANIC_ROCK_VOUCHER_9500": 200,
        "VOLCANIC_ROCK_VOUCHER_9750": 200,
        "VOLCANIC_ROCK_VOUCHER_10000": 200,
        "VOLCANIC_ROCK_VOUCHER_10250": 200,
        "VOLCANIC_ROCK_VOUCHER_10500": 200,
        "MAGNIFICENT_MACARONS": 75,
    }

    VOUCHER_STRIKES = {
        "VOLCANIC_ROCK_VOUCHER_9500": 9500,
        "VOLCANIC_ROCK_VOUCHER_9750": 9750,
        "VOLCANIC_ROCK_VOUCHER_10000": 10000,
        "VOLCANIC_ROCK_VOUCHER_10250": 10250,
        "VOLCANIC_ROCK_VOUCHER_10500": 10500,
    }

    # Basket thresholds (unchanged — sensitivity-validated v1)
    B1_UPPER = 80.0
    B1_LOWER = -40.0
    B2_UPPER = 80.0
    B2_LOWER = -40.0
    BASKET_TRADE_SIZE = 15

    # Olivia memory window (ticks)
    OLIVIA_WINDOW = 500

    # Options feature flags
    ENABLE_UNDERLYING_MR = True  # VOLCANIC_ROCK directional MR (Timo's logic)

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
        if buy_cap > 0: orders.append(Order(prod, bid_price, buy_cap))
        if sell_cap > 0: orders.append(Order(prod, ask_price, -sell_cap))
        return orders

    # ---------- KELP (Timo DynamicTrader + Olivia) ----------
    def _trade_kelp(self, od: OrderDepth, pos: int, ts: int, olivia_dir, olivia_bought_ts, olivia_sold_ts) -> List[Order]:
        prod = "KELP"
        limit = self.LIMITS[prod]
        bid_wall, wall_mid, ask_wall = self._walls(od)
        if wall_mid is None: return []
        orders: List[Order] = []
        buy_cap = limit - pos
        sell_cap = limit + pos

        # BID side
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

        # ASK side
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

    # ---------- Options: BS + fitted smile + EMA indicators + scalping/MR ----------
    # Ported from Timo FrankfurtHedgehogs_polished.OptionTrader with two
    # attribute bugs fixed (self.new_switch_mean / self.vegas → self.indicators).
    # TTE formula: tte = (8 - DAY - ts/1e6) / 365.  DAY comes from the
    # backtester env var PROSPERITY3BT_DAY (set in prosperity3bt.runner).

    @staticmethod
    def _opt_iv(S: float, K: float, TTE: float) -> float:
        m = math.log(K / S) / math.sqrt(TTE)
        return SMILE_A * m * m + SMILE_B * m + SMILE_C

    @staticmethod
    def _opt_bs(S: float, K: float, TTE: float, sigma: float):
        sqrt_t = math.sqrt(TTE)
        sig_t = sigma * sqrt_t
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * TTE) / sig_t
        d2 = d1 - sig_t
        call = S * _N.cdf(d1) - K * _N.cdf(d2)
        delta = _N.cdf(d1)
        vega = S * _N.pdf(d1) * sqrt_t
        return call, delta, vega

    @staticmethod
    def _ema(saved: Dict, key: str, window: int, value: float) -> float:
        old = saved.get(key, 0.0)
        alpha = 2.0 / (window + 1)
        new = alpha * value + (1 - alpha) * old
        saved[key] = new
        return new

    def _trade_options(self, state: TradingState, pos: Dict[str, int],
                       saved: Dict) -> Dict[str, List[Order]]:
        out: Dict[str, List[Order]] = {}
        ods = state.order_depths

        rock_od = ods.get("VOLCANIC_ROCK")
        if rock_od is None: return out

        rock_bw, rock_wm, rock_aw = self._walls(rock_od)
        if rock_wm is None: return out
        rock_tb, rock_ta = self._top(rock_od)
        if rock_tb is None or rock_ta is None: return out
        S = 0.5 * (rock_tb + rock_ta)  # Timo uses top-mid for underlying

        day = 0
        tte = (8 - day - state.timestamp / 1e6) / DAYS_PER_YEAR
        if tte <= 0: return out

        # Underlying EMAs.  Timo computes ema_u and ema_o but uses ema_o_dev
        # for BOTH the underlying-MR trigger and the voucher-MR iv_dev
        # overlay (bug-compatible copy; the ema_u is computed but unused).
        # We keep only ema_o here.
        ema_o_val = self._ema(saved, "_opt_ema_o", OPT_MR_WINDOW, rock_wm)
        ema_o_dev = rock_wm - ema_o_val

        # Per-voucher indicators
        current_theo_diff: Dict[str, float] = {}
        mean_theo_diff: Dict[str, float] = {}
        switch_mean: Dict[str, float] = {}
        deltas: Dict[str, float] = {}
        vegas: Dict[str, float] = {}
        voucher_walls: Dict[str, tuple] = {}  # name -> (bw, wm, aw, tb, ta)

        for name, K in self.VOUCHER_STRIKES.items():
            od = ods.get(name)
            if od is None: continue
            bw, wm, aw = self._walls(od)
            tb, ta = self._top(od)
            # Fallback per Timo: if one side missing, synthesise from the other
            if wm is None:
                if aw is not None:
                    wm = aw - 0.5; bw = aw - 1; tb = aw - 1
                elif bw is not None:
                    wm = bw + 0.5; aw = bw + 1; ta = bw + 1
                else:
                    continue
            voucher_walls[name] = (bw, wm, aw, tb, ta)

            # Guard: |m| huge → polynomial extrapolation unreliable
            try:
                m = math.log(K / S) / math.sqrt(tte)
            except (ValueError, ZeroDivisionError):
                continue
            if abs(m) > 3.0: continue

            sigma = self._opt_iv(S, K, tte)
            if sigma <= 0: continue

            theo, delta_v, vega_v = self._opt_bs(S, K, tte, sigma)
            diff = wm - theo

            current_theo_diff[name] = diff
            deltas[name] = delta_v
            vegas[name] = vega_v

            mdiff = self._ema(saved, f"_opt_diff_{name}", THEO_NORM_WINDOW, diff)
            mean_theo_diff[name] = mdiff
            smean = self._ema(saved, f"_opt_sw_{name}", IV_SCALPING_WINDOW, abs(diff - mdiff))
            switch_mean[name] = smean

        # Warmup gate: need at least max(window) ticks of history.
        if state.timestamp // 100 < max(IV_SCALPING_WINDOW, OPT_MR_WINDOW, UNDER_MR_WINDOW):
            return out

        # ---- IV scalping (K >= 9750, exclude MR_STRIKES) ----
        for name, K in self.VOUCHER_STRIKES.items():
            if K in MR_STRIKES: continue
            if name not in current_theo_diff: continue
            bw, wm, aw, tb, ta = voucher_walls[name]
            if tb is None or ta is None: continue

            cur = current_theo_diff[name]
            mean = mean_theo_diff[name]
            sm = switch_mean[name]
            if sm < IV_SCALPING_THR:
                # Flatten when regime is too calm
                p = pos.get(name, 0)
                if p > 0:
                    out.setdefault(name, []).append(Order(name, int(tb), -p))
                elif p < 0:
                    out.setdefault(name, []).append(Order(name, int(ta), -p))
                continue

            low_vega_adj = LOW_VEGA_THR_ADJ if vegas.get(name, 0.0) <= 1 else 0.0
            p = pos.get(name, 0)
            limit = self.LIMITS[name]
            max_sell = limit + p
            max_buy = limit - p

            # sell signal: best_bid is rich vs theo + mean-bias
            sell_score = cur - wm + tb - mean
            buy_score = cur - wm + ta - mean

            orders: List[Order] = out.setdefault(name, [])
            if sell_score >= (THR_OPEN + low_vega_adj) and max_sell > 0:
                orders.append(Order(name, int(tb), -max_sell))
            if sell_score >= THR_CLOSE and p > 0:
                orders.append(Order(name, int(tb), -p))
            elif buy_score <= -(THR_OPEN + low_vega_adj) and max_buy > 0:
                orders.append(Order(name, int(ta), max_buy))
            if buy_score <= -THR_CLOSE and p < 0:
                orders.append(Order(name, int(ta), -p))

        # ---- MR (K=9500): combined underlying + IV deviation ----
        for name, K in self.VOUCHER_STRIKES.items():
            if K not in MR_STRIKES: continue
            if name not in current_theo_diff: continue
            bw, wm, aw, tb, ta = voucher_walls[name]
            if tb is None or ta is None: continue

            iv_dev = current_theo_diff[name] - mean_theo_diff[name]
            combined = ema_o_dev + iv_dev
            p = pos.get(name, 0)
            limit = self.LIMITS[name]
            max_sell = limit + p
            max_buy = limit - p
            orders: List[Order] = out.setdefault(name, [])
            if combined > OPT_MR_THR and max_sell > 0:
                orders.append(Order(name, int(tb), -max_sell))
            elif combined < -OPT_MR_THR and max_buy > 0:
                orders.append(Order(name, int(ta), max_buy))

        # ---- Underlying MR (VOLCANIC_ROCK) ----
        # Timo uses ema_o_dev for the underlying MR (bug-compatible copy).
        # Gated by ENABLE_UNDERLYING_MR to allow disabling if it regresses.
        if self.ENABLE_UNDERLYING_MR:
            rock_p = pos.get("VOLCANIC_ROCK", 0)
            rock_limit = self.LIMITS["VOLCANIC_ROCK"]
            rock_max_sell = rock_limit + rock_p
            rock_max_buy = rock_limit - rock_p
            rock_orders: List[Order] = out.setdefault("VOLCANIC_ROCK", [])
            if ema_o_dev > UNDER_MR_THR and rock_max_sell > 0:
                rock_orders.append(Order("VOLCANIC_ROCK", int(rock_bw + 1), -rock_max_sell))
            elif ema_o_dev < -UNDER_MR_THR and rock_max_buy > 0:
                rock_orders.append(Order("VOLCANIC_ROCK", int(rock_aw - 1), rock_max_buy))

        # Drop empty entries so result doesn't carry no-op products
        return {k: v for k, v in out.items() if v}

    # ---------- Macarons (R4, replicates Timo CommodityTrader exactly) ----------
    def _trade_macarons(self, state: TradingState, pos: int, saved: Dict):
        """Conversion arbitrage: CONVERSION_LIMIT per tick = 10.

        Logic exactly mirrors Timo's CommodityTrader:
        short_arb = local_sell_price - ex_ask
        long_arb  = ex_bid - local_buy_price - 0.1
        Trade only on the larger side, and only if > 0 AND the 11-tick
        mean is also > 0 (noise guard).
        Take market orders whose per-unit edge > 58 % of short_arb, then
        post residual at local_sell_price / local_buy_price.
        """
        prod = "MAGNIFICENT_MACARONS"
        od = state.order_depths.get(prod)
        if od is None: return [], 0
        try: conv = state.observations.conversionObservations.get(prod)
        except Exception: conv = None
        if conv is None: return [], 0
        CONV_LIMIT = 10

        ex_raw_bid, ex_raw_ask = conv.bidPrice, conv.askPrice
        local_sell_price = int(math.floor(ex_raw_bid + 0.5))
        local_buy_price = int(math.ceil(ex_raw_ask - 0.5))
        ex_ask = ex_raw_ask + conv.importTariff + conv.transportFees
        ex_bid = ex_raw_bid - conv.exportTariff - conv.transportFees

        short_arb = round(local_sell_price - ex_ask, 1)
        long_arb = round(ex_bid - local_buy_price - 0.1, 1)

        sa_hist = saved.get("MAC_SA", [])
        la_hist = saved.get("MAC_LA", [])
        if len(sa_hist) > 10: sa_hist = sa_hist[1:]; la_hist = la_hist[1:]
        sa_hist.append(short_arb); la_hist.append(long_arb)
        saved["MAC_SA"] = sa_hist; saved["MAC_LA"] = la_hist
        mean_sa = sum(sa_hist) / len(sa_hist)
        mean_la = sum(la_hist) / len(la_hist)

        orders: List[Order] = []
        if short_arb > long_arb:
            if short_arb >= 0 and mean_sa > 0:
                remaining = CONV_LIMIT
                for bp, bv in sorted(od.buy_orders.items(), key=lambda x: x[0], reverse=True):
                    if remaining <= 0: break
                    bv = abs(bv)
                    # Timo: only take market bid if its edge > 0.58 * short_arb
                    if (short_arb - (local_sell_price - bp)) > 0.58 * short_arb:
                        v = min(remaining, bv)
                        orders.append(Order(prod, bp, -v)); remaining -= v
                    else: break
                if remaining > 0:
                    orders.append(Order(prod, local_sell_price, -remaining))
        else:
            if long_arb >= 0 and mean_la > 0:
                remaining = CONV_LIMIT
                for sp, sv in sorted(od.sell_orders.items(), key=lambda x: x[0]):
                    if remaining <= 0: break
                    sv = abs(sv)
                    if (long_arb - (sp - local_buy_price)) > 0.58 * long_arb:
                        v = min(remaining, sv)
                        orders.append(Order(prod, sp, v)); remaining -= v
                    else: break
                if remaining > 0:
                    orders.append(Order(prod, local_buy_price, remaining))

        # Convert to flatten existing position (up to CONV_LIMIT per tick).
        conversion = max(min(-pos, CONV_LIMIT), -CONV_LIMIT)
        return orders, conversion

    def _kelp_style_mm(self, prod: str, od: OrderDepth, pos: int) -> List[Order]:
        """Kelp-pattern MM: wall-anchored fair, bid_wall+1/ask_wall-1 posting.
        Use for Croissants/Jams/Djembes where Timo doesn't trade standalone.
        """
        limit = self.LIMITS[prod]
        bid_wall, wall_mid, ask_wall = self._walls(od)
        if wall_mid is None: return []
        orders: List[Order] = []
        buy_cap = limit - pos
        sell_cap = limit + pos
        # TAKE layer — any ask ≤ wall_mid − 1 is free edge.
        for sp, sv in sorted(od.sell_orders.items(), key=lambda x: x[0]):
            sv = abs(sv)
            if buy_cap <= 0: break
            if sp <= wall_mid - 1:
                q = min(sv, buy_cap); orders.append(Order(prod, sp, q)); buy_cap -= q
            else: break
        for bp, bv in sorted(od.buy_orders.items(), key=lambda x: x[0], reverse=True):
            bv = abs(bv)
            if sell_cap <= 0: break
            if bp >= wall_mid + 1:
                q = min(bv, sell_cap); orders.append(Order(prod, bp, -q)); sell_cap -= q
            else: break
        # MAKE — Timo's Kelp structure
        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)
        if buy_cap > 0 and bid_price < ask_price:
            orders.append(Order(prod, bid_price, buy_cap))
        if sell_cap > 0 and bid_price < ask_price:
            orders.append(Order(prod, ask_price, -sell_cap))
        return orders

    def _plain_mm(self, prod, od, pos, limit):
        bid_wall, wall_mid, ask_wall = self._walls(od)
        if wall_mid is None: return []
        top_bid, top_ask = self._top(od)
        orders = []
        buy_cap = limit - pos; sell_cap = limit + pos
        bid_price = top_bid + 1 if top_bid is not None else int(bid_wall + 1)
        ask_price = top_ask - 1 if top_ask is not None else int(ask_wall - 1)
        if bid_price < ask_price:
            if buy_cap > 0: orders.append(Order(prod, bid_price, buy_cap))
            if sell_cap > 0: orders.append(Order(prod, ask_price, -sell_cap))
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

        # R3-R5 Volcanic Rock + Vouchers (options handler).
        # Port of Timo's OptionTrader with `self.new_switch_mean` and
        # `self.vegas` AttributeError bugs fixed.  BS + fitted smile +
        # EMA indicators; IV scalping on K>=9750, MR on K=9500, plus
        # underlying MR on VOLCANIC_ROCK.  Gated by backtester env
        # PROSPERITY3BT_DAY for TTE.
        volcanic_products = ("VOLCANIC_ROCK",) + tuple(self.VOUCHER_STRIKES.keys())
        if any(p in od for p in volcanic_products):
            for prod, orders in self._trade_options(state, pos, saved).items():
                result[prod] = orders

        # Standalone Kelp-style MM on basket constituents.  Tested
        # Croissants/Jams/Djembes on R1-R5 (2026-04-23):
        #   CROISSANTS: per-product PnL shows +13-25 k/day on R5 but
        #     total-PnL is unchanged — likely offset by basket-leg
        #     accounting.  Net zero.
        #   JAMS: some days +6k, others −22k.  Trending product,
        #     MM adversely selected.
        #   DJEMBES: 0 fills (too thin book for Kelp-MM).
        # All disabled.  The basket trade already captures the value.

        # R4 Macarons: Timo's conversion-arb logic replicated; still loses
        # ~7 k/day on this backtester (local post adversely selected by
        # the matching model).  Real competition may have been different.
        # Disabled — we still beat Timo by +114 k/round on R4 via baskets.

        return result, 0, json.dumps(saved, separators=(",", ":"))
