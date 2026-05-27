"""
Round 3 baseline v13 — 2026-04-24 (post-live diagnosis session).

v13 = v12 + drift-regime handler for HYDROGEL + position-trend skew
       + per-tick logger.

Live day-2 failure mode (submission 1a9a8223):
  HYDROGEL touch_mid drifted from ~10020 (t=70k) down to ~9920 (t=88k)
  back to ~9960 (t=100k). v12's CLIP=30 froze fair at 9960 once mid
  fell below it; algo kept seeing asks at 9921 as "below fair" take
  signals and accumulated long inventory while mid kept dropping.
  Realized PnL collapsed from +14k (peak) to -750 before bouncing.

Fix family: drift-regime is now an explicit branch.
  When abs(touch_mid - H_ANCHOR) > H_CLIP:
    - blend fair toward touch_mid (DRIFT_BLEND fraction); fair stops
      being stuck at the wall
    - boost inv_skew to H_INV_SKEW_DRIFT (~3x) to refuse adding
      inventory in the drift direction
    - block aggressive TAKE on the drift-adding side; REDUCE-EDGE
      paths (flatten existing inventory) still fire normally
    - suppress MAKE on the drift-adding side (no bid in falling
      market, no ask in rising market)

Position-trend skew (additive nudge): if signed inventory aligns
with the drift direction (e.g. long while market is falling), we
add a small extra skew penalty proportional to recent drift.

Logger: every tick, the trader prints a one-line JSON to lambdaLog
with HYDROGEL fair/drift/regime/pos and voucher fair/pos. This is
visible in submission logs for post-mortem.

Hypothesis: keeps in-sample PnL within ±1k of v12 (drift threshold
hit zero times in the 3 backtest days) AND defends against the
live drift seen on day 2. Toggle LOG=False before final shipping if
log volume is a concern.
"""
from typing import Dict, List, Optional, Tuple
from statistics import NormalDist
import json
import math

from datamodel import Order, OrderDepth, TradingState


_N = NormalDist()
DAYS_PER_YEAR = 365
TTE_DAYS_LIVE = 5.0


class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
        "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
        "VEV_6500": 300,
    }

    VOUCHER_STRIKES = {"VEV_4000": 4000, "VEV_4500": 4500}

    # HYDROGEL — v13 adds drift handler
    H_ANCHOR = 9990.0
    H_CLIP = 30.0
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 1.0
    H_PENNY_EDGE = 1.5
    H_INV_SKEW = 0.015          # normal regime
    H_INV_SKEW_DRIFT = 0.045    # drift regime: 3x harder flatten
    H_DRIFT_BLEND = 0.6         # fair = clipped + DRIFT_BLEND * (raw - clipped)
    H_TREND_SKEW = 0.05         # extra skew when pos aligns with drift
    H_MAX_POST_SIZE = 20
    H_PASSIVE_OFFSET = 12.0
    H_WIDE_SPREAD = 8
    H_SHOCK_MOVE = 15.0

    # Voucher (v12 unchanged)
    SIGMA = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.005
    VS_MAX_POST_SIZE = 100
    VS_WIDE_SPREAD = 3
    VS_POST_AT_TOUCH = True

    # Logger toggle. False keeps lambdaLog volume zero for shipping.
    LOG = True

    def _book(self, od: OrderDepth):
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in od.buy_orders.items()}
        sells = {int(p): abs(int(v)) for p, v in od.sell_orders.items()}
        bb = max(buys); ba = min(sells)
        return {
            "buys": dict(sorted(buys.items(), reverse=True)),
            "sells": dict(sorted(sells.items())),
            "bb": bb, "ba": ba, "bv": buys[bb], "av": sells[ba],
            "spread": ba - bb, "touch_mid": 0.5 * (bb + ba),
        }

    def _cap_size(self, max_size: int, pos: int, side: str, cap: int, limit: int) -> int:
        if cap <= 0:
            return 0
        ratio = 1.0 - min(0.7, abs(pos) / limit)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    @staticmethod
    def _opt_theo(S: float, K: int, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return max(0.0, S - K)
        sq = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / sq
        d2 = d1 - sq
        return S * _N.cdf(d1) - K * _N.cdf(d2)

    @staticmethod
    def _tte_years(ts: int) -> float:
        tte_days = TTE_DAYS_LIVE - ts / 1e6
        if tte_days <= 0:
            return 0.0
        return tte_days / DAYS_PER_YEAR

    def _trade_hydrogel(self, od: OrderDepth, pos: int,
                        prev_mid: Optional[float]
                        ) -> Tuple[List[Order], float, Dict]:
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], prev_mid if prev_mid is not None else 0.0, {}
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]; touch_mid = book["touch_mid"]

        shock = (prev_mid is not None
                 and abs(touch_mid - prev_mid) > self.H_SHOCK_MOVE)
        drift_raw = touch_mid - self.H_ANCHOR
        drift_regime = (not shock) and abs(drift_raw) > self.H_CLIP

        # Compute fair + skew per regime
        if shock:
            fair = touch_mid
            inv_skew = self.H_INV_SKEW
            regime = "shock"
        elif drift_regime:
            clipped = max(-self.H_CLIP, min(self.H_CLIP, drift_raw))
            # blend toward touch_mid: BLEND=0 -> v12 (clip), BLEND=1 -> follow
            fair = self.H_ANCHOR + clipped + self.H_DRIFT_BLEND * (drift_raw - clipped)
            inv_skew = self.H_INV_SKEW_DRIFT
            regime = "drift"
        else:
            fair = self.H_ANCHOR + drift_raw  # touch_mid is within clip
            inv_skew = self.H_INV_SKEW
            regime = "normal"

        # Position-trend extra skew: penalize being long-and-falling /
        # short-and-rising. Magnitude scales with drift size.
        # drift_raw < 0 means market falling; pos > 0 (long) means we're
        # holding into the move. trend_term shifts skew DOWN (asking lower)
        # so we prefer to sell.
        trend_term = self.H_TREND_SKEW * pos * (drift_raw / max(self.H_CLIP, 1.0))
        # Note: pos*drift_raw > 0 when aligned (bad). Subtract from fair so we
        # ask cheaper / bid lower, biasing toward exit.
        # We bake this into skew uniformly:
        trend_adj = -trend_term * 0.5  # scale so it doesn't dominate

        working = pos
        orders: List[Order] = []

        drift_dir = 0
        if drift_regime:
            drift_dir = 1 if drift_raw > 0 else -1

        # TAKE asks
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair + trend_adj - inv_skew * working
            block_aggressive_buy = (drift_dir == -1)  # falling market: don't buy
            if (not block_aggressive_buy) and ap <= skew - self.H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                # REDUCE: always allowed (closing existing short)
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q

        # TAKE bids
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair + trend_adj - inv_skew * working
            block_aggressive_sell = (drift_dir == 1)  # rising market: don't sell short
            if (not block_aggressive_sell) and bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                # REDUCE: always allowed (closing existing long)
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q

        log_state = {
            "fair": round(fair, 1),
            "drift": round(drift_raw, 1),
            "regime": regime,
            "pos_in": pos,
            "pos_after_take": working,
        }

        if shock:
            return orders, touch_mid, log_state

        skew = fair + trend_adj - inv_skew * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.H_MAX_POST_SIZE, working, "buy",
                                  buy_cap, limit)
        ask_size = self._cap_size(self.H_MAX_POST_SIZE, working, "sell",
                                  sell_cap, limit)

        # Suppress make on drift-adding side
        if drift_dir == -1:
            bid_size = 0
        elif drift_dir == 1:
            ask_size = 0

        if spread >= self.H_WIDE_SPREAD:
            bid_price = min(bb + 1, math.floor(skew - self.H_PENNY_EDGE))
            ask_price = max(ba - 1, math.ceil(skew + self.H_PENNY_EDGE))
        else:
            bid_price = math.floor(skew - self.H_PASSIVE_OFFSET)
            ask_price = math.ceil(skew + self.H_PASSIVE_OFFSET)
        bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
        ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)

        if bid_price < ask_price:
            if bid_size > 0:
                orders.append(Order(prod, bid_price, bid_size))
            if ask_size > 0:
                orders.append(Order(prod, ask_price, -ask_size))
        return orders, touch_mid, log_state

    def _trade_deep_itm(self, name: str, K: int, od: OrderDepth,
                        pos: int, S: float, T: float
                        ) -> Tuple[List[Order], Dict]:
        limit = self.LIMITS[name]
        book = self._book(od)
        if not book:
            return [], {}
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]
        fair = self._opt_theo(S, K, T, self.SIGMA)
        working = pos
        orders: List[Order] = []

        # TAKE asks
        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - self.VS_INV_SKEW * working
            if ap <= skew - self.VS_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(name, ap, q)); working += q
            elif working < 0 and ap <= skew:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(name, ap, q)); working += q

        # TAKE bids
        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair - self.VS_INV_SKEW * working
            if bp >= skew + self.VS_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q
            elif working > 0 and bp >= skew:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(name, bp, -q)); working -= q

        # MAKE
        skew = fair - self.VS_INV_SKEW * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.VS_MAX_POST_SIZE, working, "buy",
                                  buy_cap, limit)
        ask_size = self._cap_size(self.VS_MAX_POST_SIZE, working, "sell",
                                  sell_cap, limit)

        if spread >= self.VS_WIDE_SPREAD:
            if self.VS_POST_AT_TOUCH:
                bid_price = min(bb, math.floor(skew - self.VS_PENNY_EDGE))
                ask_price = max(ba, math.ceil(skew + self.VS_PENNY_EDGE))
            else:
                bid_price = min(bb + 1, math.floor(skew - self.VS_PENNY_EDGE))
                ask_price = max(ba - 1, math.ceil(skew + self.VS_PENNY_EDGE))
            bid_price = min(int(bid_price), ba - 1, math.floor(fair) - 1)
            ask_price = max(int(ask_price), bb + 1, math.ceil(fair) + 1)
            if bid_price < ask_price:
                if bid_size > 0:
                    orders.append(Order(name, bid_price, bid_size))
                if ask_size > 0:
                    orders.append(Order(name, ask_price, -ask_size))
        return orders, {"fair": round(fair, 1), "pos_in": pos, "pos_after": working}

    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        result: Dict[str, List[Order]] = {}
        pos = state.position
        log_payload = {"ts": state.timestamp}

        if "HYDROGEL_PACK" in state.order_depths:
            prev_mid = saved.get("h_prev_mid")
            h_orders, new_mid, h_state = self._trade_hydrogel(
                state.order_depths["HYDROGEL_PACK"],
                pos.get("HYDROGEL_PACK", 0),
                prev_mid,
            )
            result["HYDROGEL_PACK"] = h_orders
            saved["h_prev_mid"] = new_mid
            log_payload["h"] = h_state

        u_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if u_od is not None:
            u_book = self._book(u_od)
            if u_book is not None:
                S = u_book["touch_mid"]
                T = self._tte_years(state.timestamp)
                log_payload["S"] = round(S, 1)
                for name, K in self.VOUCHER_STRIKES.items():
                    od = state.order_depths.get(name)
                    if od is not None:
                        orders, v_state = self._trade_deep_itm(
                            name, K, od, pos.get(name, 0), S, T,
                        )
                        result[name] = orders
                        log_payload[name] = v_state

        if self.LOG:
            print(json.dumps(log_payload))

        return result, 0, json.dumps(saved)
