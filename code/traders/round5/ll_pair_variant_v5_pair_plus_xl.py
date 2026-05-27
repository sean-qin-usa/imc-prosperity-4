"""
Round 5 — Universal basket market-maker, v5_safe (recommended for submission).

v5 + Pebbles kill-switch. Same PnL as v5 in backtest (kill-switch never triggers
on days 2/3/4). The kill-switch is pure tail-risk insurance: if the empirical
PEBBLES invariant `Σmid = 50000` breaks live, we pull all Pebbles quotes to
prevent runaway adverse selection on the basket-MM strategy.

Trigger condition: |Σmid_pebbles − 50000| > 50 for ≥5 consecutive ticks.
Reset:             first tick with deviation ≤ 50 — quotes resume immediately.

Empirical basis: across 30k aligned ticks in days 2/3/4, the basket sum stays in
[49981.5, 50016.5] — max abs deviation 18.5. A move past 50 for 5 consecutive
ticks would be unprecedented and indicates either the round changed the basket
construction or there's a market-data anomaly. Either way, pulling out is safer
than continuing to MM around a stale anchor.

Layered MM with 4 signals, narrowing the per-leg z-overlay from "snack-pack legs only"
(v4) to a curated robust set of 13 mean-reverting products.

  v1: pure 1-tick BBO improvement on every leg.       Backtest $401k / 134k per day.
  v2: + per-leg L1 imbalance skew (universal).        Backtest $433k / 144k per day.
  v3: + category-basket-z overlay on Robots/UV/Trans  Backtest $510k / 170k per day.
  v4: + per-leg-mid-z on 5 snack pack legs.           Backtest $556k / 185k per day.
  v5: per-leg-mid-z on 13 robust mean-reverters.      Backtest $693k / 231k per day (+72.6% vs v1).

Selection of the 13 robust mean-reverting legs:
  Method: turn on per-leg z-overlay one product at a time on top of v3, measure per-day
  uplift on each of days 2/3/4. Pick products with positive contribution on ALL 3 days,
  then add 2 marginal snack-pack legs (PISTACHIO, RASPBERRY) to keep snack-pack family
  intact (they have positive total uplift across days even though one day's slightly
  negative).

  Robust set (delta vs v3, per-day):
    PEBBLES_M                  +4929  +3837 +20542  → +29,308
    MICROCHIP_TRIANGLE        +11706 +11317  +1576  → +24,600
    MICROCHIP_RECTANGLE        +6350   +647 +15155  → +22,152
    SNACKPACK_VANILLA          +4174 +13030  +1883  → +19,087
    ROBOT_DISHES               +6776  +5056  +6401  → +18,233
    PANEL_1X2                  +6748  +6016  +5182  → +17,946
    ROBOT_VACUUMING            +3390  +7910   +150  → +11,450
    SNACKPACK_STRAWBERRY       +7574  +1705  +2022  → +11,301
    SLEEP_POD_NYLON             +151  +7548   +184  →  +7,883
    TRANSLATOR_GRAPHITE_MIST   +1229  +2416  +1519  →  +5,164
    SNACKPACK_CHOCOLATE        +2065   +734   +359  →  +3,158
    SNACKPACK_PISTACHIO        +2547   -57  +3953   →  +6,443  (small day-3 negative)
    SNACKPACK_RASPBERRY        +3261  +3958  -950   →  +6,268  (small day-4 negative)

  Total uplift: +$182,993 vs v3 across 3 days.

Why these and not others:
  - Each has a stable within-day mean (mid_std 130-560 across days, mean drift modest)
  - AR(1) half-life 600-2500 ticks → reverts within a day
  - Per-product test shows the rolling z-overlay catches the within-day reversion
  - Products outside this set either have too much drift (basket-arb categories like
    GALAXY_SOUNDS that lack within-day stability), too narrow a range to overcome the
    spread cost (low resid_std vs spread), or one-day-noisy contributions that don't
    reproduce.

Risks:
  - Selection used all 3 days; with only 3 days we can't do strict walk-forward. The
    "positive on every day" filter is the strongest robustness signal we have.
  - On a 4th unseen day, products with marginal qualifications (PISTACHIO, RASPBERRY)
    may contribute negatively. But their total magnitude is small (~$6k each).
"""

from typing import Dict, List, Set
import json

from datamodel import Order, OrderDepth, TradingState


POS_LIMIT = 10
IMPROVEMENT = 1
IMB_THR = 0.3
CAT_Z_WINDOW = 500
CAT_Z_THR = 1.0
LEG_Z_WINDOW = 2000
LEG_Z_THR = 1.0
REL_Z_WINDOW = 1000
REL_Z_THR = 1.0
LL_LAG = 200
LL_RET_WINDOW = 1000
LL_Z_THR = 1.0

# Pebbles kill-switch
PEBBLES_TARGET = 50000
PEBBLES_KILL_THR = 50      # |Σmid − target| above this counts as a violation
PEBBLES_KILL_TICKS = 5     # consecutive violations before pulling Pebbles quotes

CATEGORIES: Dict[str, List[str]] = {
    'GALAXY_SOUNDS': [
        'GALAXY_SOUNDS_DARK_MATTER', 'GALAXY_SOUNDS_BLACK_HOLES',
        'GALAXY_SOUNDS_PLANETARY_RINGS', 'GALAXY_SOUNDS_SOLAR_WINDS',
        'GALAXY_SOUNDS_SOLAR_FLAMES',
    ],
    'SLEEP_POD': [
        'SLEEP_POD_SUEDE', 'SLEEP_POD_LAMB_WOOL', 'SLEEP_POD_POLYESTER',
        'SLEEP_POD_NYLON', 'SLEEP_POD_COTTON',
    ],
    'MICROCHIP': [
        'MICROCHIP_CIRCLE', 'MICROCHIP_OVAL', 'MICROCHIP_SQUARE',
        'MICROCHIP_RECTANGLE', 'MICROCHIP_TRIANGLE',
    ],
    'PEBBLES': [
        'PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL',
    ],
    'ROBOT': [
        'ROBOT_VACUUMING', 'ROBOT_MOPPING', 'ROBOT_DISHES',
        'ROBOT_LAUNDRY', 'ROBOT_IRONING',
    ],
    'UV_VISOR': [
        'UV_VISOR_YELLOW', 'UV_VISOR_AMBER', 'UV_VISOR_ORANGE',
        'UV_VISOR_RED', 'UV_VISOR_MAGENTA',
    ],
    'TRANSLATOR': [
        'TRANSLATOR_SPACE_GRAY', 'TRANSLATOR_ASTRO_BLACK',
        'TRANSLATOR_ECLIPSE_CHARCOAL', 'TRANSLATOR_GRAPHITE_MIST',
        'TRANSLATOR_VOID_BLUE',
    ],
    'PANEL': [
        'PANEL_1X2', 'PANEL_2X2', 'PANEL_1X4', 'PANEL_2X4', 'PANEL_4X4',
    ],
    'OXYGEN_SHAKE': [
        'OXYGEN_SHAKE_MORNING_BREATH', 'OXYGEN_SHAKE_EVENING_BREATH',
        'OXYGEN_SHAKE_MINT', 'OXYGEN_SHAKE_CHOCOLATE', 'OXYGEN_SHAKE_GARLIC',
    ],
    'SNACKPACK': [
        'SNACKPACK_CHOCOLATE', 'SNACKPACK_VANILLA', 'SNACKPACK_PISTACHIO',
        'SNACKPACK_STRAWBERRY', 'SNACKPACK_RASPBERRY',
    ],
}

# Category-basket-sum z-overlay applied here (v3 selection).
CAT_Z_CATEGORIES: Set[str] = {'ROBOT', 'UV_VISOR', 'TRANSLATOR'}

# Per-leg-mid z-overlay applied here (v5 selection — 13 robust mean-reverting legs).
LEG_Z_PRODUCTS: Set[str] = {
    'MICROCHIP_RECTANGLE', 'MICROCHIP_TRIANGLE',
    'PANEL_1X2',
    'PEBBLES_M',
    'ROBOT_DISHES', 'ROBOT_VACUUMING',
    'SLEEP_POD_NYLON',
    'SNACKPACK_CHOCOLATE', 'SNACKPACK_VANILLA', 'SNACKPACK_PISTACHIO',
    'SNACKPACK_STRAWBERRY', 'SNACKPACK_RASPBERRY',
    'TRANSLATOR_GRAPHITE_MIST',
}

# Pair/cluster-relative z-overlay: product rich/cheap versus the other four
# products in its family. This is unhedged by request; it only suppresses the
# quote side that would add exposure in the wrong direction.
REL_Z_PRODUCTS: Set[str] = {
    'PEBBLES_S',
    'MICROCHIP_TRIANGLE',
    'TRANSLATOR_GRAPHITE_MIST',
}

# Lead-lag overlay: if the other four legs in the family have made an unusually
# large move over the last LL_LAG ticks, assume this leg may continue in that
# direction. This is also unhedged; it only suppresses the quote side that would
# fight the predicted move.
LL_PRODUCTS: Set[str] = {
    'PEBBLES_XL',
}

PRODUCT_TO_CAT: Dict[str, str] = {
    sym: cat for cat, syms in CATEGORIES.items() for sym in syms
}
PRODUCTS: List[str] = list(PRODUCT_TO_CAT.keys())


def _z_update(stats: Dict, x: float, window: int):
    """Incremental rolling mean/std using sum and sum-of-squares.

    Returns z-score using state BEFORE adding x, then mutates stats to include x.
    """
    buf = stats.get('buf', [])
    s = stats.get('s', 0.0)
    ss = stats.get('ss', 0.0)
    n = len(buf)
    if n >= 2:
        m = s / n
        var = (ss - s * s / n) / (n - 1)
        sd = var ** 0.5 if var > 0 else 0.0
        z = (x - m) / sd if sd > 0 else 0.0
    else:
        z = 0.0
    buf.append(x); s += x; ss += x * x
    if len(buf) > window:
        old = buf.pop(0); s -= old; ss -= old * old
    stats['buf'] = buf; stats['s'] = s; stats['ss'] = ss
    return z


class Trader:
    POS_LIMIT = POS_LIMIT
    IMPROVEMENT = IMPROVEMENT
    IMB_THR = IMB_THR
    CAT_Z_WINDOW = CAT_Z_WINDOW
    CAT_Z_THR = CAT_Z_THR
    LEG_Z_WINDOW = LEG_Z_WINDOW
    LEG_Z_THR = LEG_Z_THR
    REL_Z_WINDOW = REL_Z_WINDOW
    REL_Z_THR = REL_Z_THR
    LL_LAG = LL_LAG
    LL_RET_WINDOW = LL_RET_WINDOW
    LL_Z_THR = LL_Z_THR
    PEBBLES_TARGET = PEBBLES_TARGET
    PEBBLES_KILL_THR = PEBBLES_KILL_THR
    PEBBLES_KILL_TICKS = PEBBLES_KILL_TICKS

    def run(self, state: TradingState):
        try:
            saved = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            saved = {}
        cat_stats: Dict[str, Dict] = saved.get('cat_stats', {})
        leg_stats: Dict[str, Dict] = saved.get('leg_stats', {})
        rel_stats: Dict[str, Dict] = saved.get('rel_stats', {})
        ll_stats: Dict[str, Dict] = saved.get('ll_stats', {})
        ll_hist: Dict[str, List[float]] = saved.get('ll_hist', {})

        # Pebbles kill-switch: track consecutive ticks where |Σmid − target| > threshold.
        # Once the streak hits PEBBLES_KILL_TICKS, pull all Pebbles quotes until a tick
        # with deviation back inside the threshold (then resume).
        pebbles_sum = 0.0
        pebbles_ok = True
        for sym in CATEGORIES['PEBBLES']:
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                pebbles_ok = False
                break
            pebbles_sum += 0.5 * (max(od.buy_orders.keys()) + min(od.sell_orders.keys()))
        consec = int(saved.get('pebbles_consec', 0))
        if pebbles_ok:
            if abs(pebbles_sum - self.PEBBLES_TARGET) > self.PEBBLES_KILL_THR:
                consec += 1
            else:
                consec = 0
        # If pebbles_ok=False (book missing), don't update streak — just preserve.
        saved['pebbles_consec'] = consec
        pebbles_killed = consec >= self.PEBBLES_KILL_TICKS

        # Category-basket z-scores (only for active categories).
        cat_z: Dict[str, float] = {}
        for cat in CAT_Z_CATEGORIES:
            s = 0.0
            ok = True
            for sym in CATEGORIES[cat]:
                od = state.order_depths.get(sym)
                if od is None or not od.buy_orders or not od.sell_orders:
                    ok = False
                    break
                s += 0.5 * (max(od.buy_orders.keys()) + min(od.sell_orders.keys()))
            if not ok:
                cat_z[cat] = 0.0
                continue
            stats = cat_stats.setdefault(cat, {})
            cat_z[cat] = _z_update(stats, s, self.CAT_Z_WINDOW)

        # Per-leg mid z-scores for products in LEG_Z_PRODUCTS.
        leg_z: Dict[str, float] = {}
        for sym in LEG_Z_PRODUCTS:
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                leg_z[sym] = 0.0
                continue
            mid = 0.5 * (max(od.buy_orders.keys()) + min(od.sell_orders.keys()))
            stats = leg_stats.setdefault(sym, {})
            leg_z[sym] = _z_update(stats, mid, self.LEG_Z_WINDOW)

        # Pair/cluster-relative z-scores: mid minus equal-weight mean of the
        # other legs in the same category.
        rel_z: Dict[str, float] = {}
        for sym in REL_Z_PRODUCTS:
            cat = PRODUCT_TO_CAT[sym]
            mids: Dict[str, float] = {}
            ok = True
            for leg in CATEGORIES[cat]:
                od = state.order_depths.get(leg)
                if od is None or not od.buy_orders or not od.sell_orders:
                    ok = False
                    break
                mids[leg] = 0.5 * (max(od.buy_orders.keys()) + min(od.sell_orders.keys()))
            if not ok:
                rel_z[sym] = 0.0
                continue
            others = [leg for leg in CATEGORIES[cat] if leg != sym]
            rel = mids[sym] - sum(mids[leg] for leg in others) / len(others)
            stats = rel_stats.setdefault(sym, {})
            rel_z[sym] = _z_update(stats, rel, self.REL_Z_WINDOW)

        # Lead-lag z-scores on the excluding-self family mean return.
        ll_z: Dict[str, float] = {}
        for sym in LL_PRODUCTS:
            cat = PRODUCT_TO_CAT[sym]
            vals: List[float] = []
            ok = True
            for leg in CATEGORIES[cat]:
                if leg == sym:
                    continue
                od = state.order_depths.get(leg)
                if od is None or not od.buy_orders or not od.sell_orders:
                    ok = False
                    break
                vals.append(0.5 * (max(od.buy_orders.keys()) + min(od.sell_orders.keys())))
            if not ok or not vals:
                ll_z[sym] = 0.0
                continue
            leader = sum(vals) / len(vals)
            hist = ll_hist.setdefault(sym, [])
            if len(hist) >= self.LL_LAG:
                ret = leader - hist[-self.LL_LAG]
                stats = ll_stats.setdefault(sym, {})
                ll_z[sym] = _z_update(stats, ret, self.LL_RET_WINDOW)
            else:
                ll_z[sym] = 0.0
            hist.append(leader)
            if len(hist) > self.LL_LAG + 1:
                hist.pop(0)

        # Build orders.
        result: Dict[str, List[Order]] = {}
        positions = state.position or {}

        for sym in PRODUCTS:
            od: OrderDepth = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue

            # Pebbles kill-switch: skip all Pebbles legs when triggered.
            if pebbles_killed and PRODUCT_TO_CAT[sym] == 'PEBBLES':
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            our_bid = best_bid + self.IMPROVEMENT
            our_ask = best_ask - self.IMPROVEMENT
            if our_bid >= our_ask:
                continue

            pos = int(positions.get(sym, 0))
            buy_cap = max(0, self.POS_LIMIT - pos)
            sell_cap = max(0, self.POS_LIMIT + pos)
            quote_bid = buy_cap > 0
            quote_ask = sell_cap > 0

            # v2: per-leg L1 imbalance skew.
            bid_vol = od.buy_orders.get(best_bid, 0)
            ask_vol = abs(od.sell_orders.get(best_ask, 0))
            tot = bid_vol + ask_vol
            if tot > 0:
                imb = (bid_vol - ask_vol) / tot
                if imb >  self.IMB_THR:
                    quote_ask = False
                elif imb < -self.IMB_THR:
                    quote_bid = False

            # v3: category-basket z mean-reversion overlay.
            cat = PRODUCT_TO_CAT[sym]
            if cat in CAT_Z_CATEGORIES:
                cz = cat_z.get(cat, 0.0)
                if cz >  self.CAT_Z_THR:
                    quote_bid = False
                elif cz < -self.CAT_Z_THR:
                    quote_ask = False

            # v5: per-leg-mid z mean-reversion overlay (extended set).
            if sym in LEG_Z_PRODUCTS:
                lz = leg_z.get(sym, 0.0)
                if lz >  self.LEG_Z_THR:
                    quote_bid = False
                elif lz < -self.LEG_Z_THR:
                    quote_ask = False

            # Pair/relative-value overlay: rich versus family -> avoid buying;
            # cheap versus family -> avoid selling.
            if sym in REL_Z_PRODUCTS:
                rz = rel_z.get(sym, 0.0)
                if rz >  self.REL_Z_THR:
                    quote_bid = False
                elif rz < -self.REL_Z_THR:
                    quote_ask = False

            # Lead-lag overlay: family already moved up -> avoid selling;
            # family already moved down -> avoid buying.
            if sym in LL_PRODUCTS:
                lz = ll_z.get(sym, 0.0)
                if lz >  self.LL_Z_THR:
                    quote_ask = False
                elif lz < -self.LL_Z_THR:
                    quote_bid = False

            orders: List[Order] = []
            if quote_bid:
                orders.append(Order(sym, int(our_bid), int(buy_cap)))
            if quote_ask:
                orders.append(Order(sym, int(our_ask), -int(sell_cap)))
            if orders:
                result[sym] = orders

        saved['cat_stats'] = cat_stats
        saved['leg_stats'] = leg_stats
        saved['rel_stats'] = rel_stats
        saved['ll_stats'] = ll_stats
        saved['ll_hist'] = ll_hist
        return result, 0, json.dumps(saved, separators=(',', ':'))
