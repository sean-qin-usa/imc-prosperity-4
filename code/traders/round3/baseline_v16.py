"""
Round 3 baseline v16 — fix v15 day-2 trap with cap-flattener.

v15 live result: +8,540 day-2 (peaked +14k at ts=70k, gave back 5.5k).
Failure mode: HYDROGEL touch_mid descended 10027 → 9915. ts 49k–51k:
pos flipped -103 → +200 while drift was -38 to -49. v13c/v15 drift
gate (|drift|>50 AND risk>2000) never tripped (drift bottomed -50),
so fair stayed pinned at 9960 and asks at 9952 looked "below fair" →
algo bought into the descent. Once pinned at +200, inv_skew*pos
gave only 3 ticks of skew so REDUCE couldn't sell to falling bids.

Sweep finding: any drift-gate loosening that catches the live trap
also fires on stationary-day noise (mean-reversion alpha and trap
defense are on the same signal axis). Persistence-based gates have
the same problem — touch_mid sustains 100+ tick one-sided runs in
stationary data.

v16 fix: orthogonal cap-flattener. Fires ONLY when pos is at limit
AND drift is materially adverse (|drift|>=35 against pos). Stationary
days rarely sit AT cap (= 200) with sustained adverse drift, so the
gate is silent in-sample. On the live day-2 trap, pos=+200 with
drift in [-49,-75] from ts 51,400 onward — fires every cycle, dumps
H_CAP_FLATTEN_QTY at the bid, allowing pos to drain.

Backtest: v15 = 187k 3-day, v5 = 168k 3-day, v16 = 162k 3-day.
v16 trades ~7k in-sample for the cap-flattener safety + drops 2 dead
sleeves (LOTTERY zero fills live, ATM smile-EMA +66 PnL live).

Kept unchanged from v15: H_CLIP=30, H_DRIFT_THRESHOLD=50, BLEND=0.6,
INV_SKEW_DRIFT=0.045, all VEV_4000/4500 params.
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

    # HYDROGEL — v16: looser drift gate + harder unwind
    H_ANCHOR = 9990.0
    H_CLIP = 30.0
    H_TAKE_EDGE = 0.0
    H_REDUCE_EDGE = 1.0
    H_PENNY_EDGE = 1.5
    H_INV_SKEW = 0.015
    H_INV_SKEW_DRIFT = 0.045         # v15 value
    H_DRIFT_BLEND = 0.6              # v15 value
    H_DRIFT_THRESHOLD = 50.0         # v15 value
    H_DRIFT_RISK = 2000.0            # v15 value
    # v16: cap-flattener supplement. When pos is pinned near limit AND mid has
    # moved materially against pos, force-flatten via touch trades. This is
    # structurally orthogonal to mean-reversion (only fires at position cap),
    # so it doesn't false-trigger on stationary-day noise.
    H_CAP_NEAR = 1.0                 # at-limit only
    H_CAP_DRIFT = 35.0               # |drift| against pos required to flatten
    H_CAP_FLATTEN_QTY = 30           # max qty per tick to flatten
    H_MAX_POST_SIZE = 20
    H_PASSIVE_OFFSET = 12.0
    H_WIDE_SPREAD = 8
    H_SHOCK_MOVE = 15.0

    SIGMA = 0.23
    VS_TAKE_EDGE = 0.0
    VS_PENNY_EDGE = 1.0
    VS_INV_SKEW = 0.005
    VS_MAX_POST_SIZE = 100
    VS_WIDE_SPREAD = 3
    VS_POST_AT_TOUCH = True

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
                        prev_mid: Optional[float],
                        ) -> Tuple[List[Order], float, Dict]:
        prod = "HYDROGEL_PACK"
        limit = self.LIMITS[prod]
        book = self._book(od)
        if not book:
            return [], (prev_mid if prev_mid is not None else 0.0), {}
        bb, ba = book["bb"], book["ba"]
        spread = book["spread"]; touch_mid = book["touch_mid"]

        shock = (prev_mid is not None
                 and abs(touch_mid - prev_mid) > self.H_SHOCK_MOVE)
        drift_raw = touch_mid - self.H_ANCHOR
        risk_aligned = pos * (-drift_raw)
        drift_regime = (not shock) and abs(drift_raw) > self.H_DRIFT_THRESHOLD \
                                   and risk_aligned > self.H_DRIFT_RISK

        if shock:
            fair = touch_mid
            inv_skew = self.H_INV_SKEW
            regime = "shock"
        elif drift_regime:
            clipped = max(-self.H_CLIP, min(self.H_CLIP, drift_raw))
            fair = self.H_ANCHOR + clipped + self.H_DRIFT_BLEND * (drift_raw - clipped)
            inv_skew = self.H_INV_SKEW_DRIFT
            regime = "drift"
        else:
            clipped = max(-self.H_CLIP, min(self.H_CLIP, drift_raw))
            fair = self.H_ANCHOR + clipped
            inv_skew = self.H_INV_SKEW
            regime = "normal"

        working = pos
        orders: List[Order] = []

        drift_dir = 0
        if drift_regime:
            drift_dir = 1 if drift_raw > 0 else -1

        for ap, av in book["sells"].items():
            cap = limit - working
            if cap <= 0:
                break
            skew = fair - inv_skew * working
            block_aggressive_buy = (drift_dir == -1)
            if (not block_aggressive_buy) and ap <= skew - self.H_TAKE_EDGE:
                q = min(av, cap)
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q
            elif working < 0 and ap <= skew + self.H_REDUCE_EDGE:
                q = min(av, cap, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q)); working += q

        for bp, bv in book["buys"].items():
            cap = limit + working
            if cap <= 0:
                break
            skew = fair - inv_skew * working
            block_aggressive_sell = (drift_dir == 1)
            if (not block_aggressive_sell) and bp >= skew + self.H_TAKE_EDGE:
                q = min(bv, cap)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q
            elif working > 0 and bp >= skew - self.H_REDUCE_EDGE:
                q = min(bv, cap, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q)); working -= q

        # v16: cap-flattener — fires only at extreme pos with adverse drift.
        # Defends against the live day-2 trap where pos pinned at +200 long
        # while market kept dropping. Stationary days rarely sit at cap.
        cap_long_bad = (working >= self.H_CAP_NEAR * limit) and (drift_raw <= -self.H_CAP_DRIFT)
        cap_short_bad = (working <= -self.H_CAP_NEAR * limit) and (drift_raw >= self.H_CAP_DRIFT)
        if cap_long_bad and not shock:
            qty_left = self.H_CAP_FLATTEN_QTY
            for bp, bv in book["buys"].items():
                if qty_left <= 0 or working <= 0:
                    break
                q = min(bv, qty_left, working)
                if q > 0:
                    orders.append(Order(prod, bp, -q))
                    working -= q
                    qty_left -= q
            regime = "cap_flat_long"
        elif cap_short_bad and not shock:
            qty_left = self.H_CAP_FLATTEN_QTY
            for ap, av in book["sells"].items():
                if qty_left <= 0 or working >= 0:
                    break
                q = min(av, qty_left, abs(working))
                if q > 0:
                    orders.append(Order(prod, ap, q))
                    working += q
                    qty_left -= q
            regime = "cap_flat_short"

        log_state = {
            "fair": round(fair, 1),
            "drift": round(drift_raw, 1),
            "regime": regime,
            "pos_in": pos,
            "pos_after_take": working,
        }

        if shock:
            return orders, touch_mid, log_state

        skew = fair - inv_skew * working
        buy_cap = max(0, limit - working)
        sell_cap = max(0, limit + working)
        bid_size = self._cap_size(self.H_MAX_POST_SIZE, working, "buy",
                                  buy_cap, limit)
        ask_size = self._cap_size(self.H_MAX_POST_SIZE, working, "sell",
                                  sell_cap, limit)

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
