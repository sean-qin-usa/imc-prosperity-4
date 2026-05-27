"""
Round 4 — adaptive standalone pennying strategy.

Versus the historical penny_vwap.py:

  1. Online edge learning. Per-(mark, symbol) rolling stats are accumulated
     from state.market_trades during live trading — no hardcoded EDGE_TABLE.
     Each observed fill updates:
       fills, qty, agg_fills (price-vs-mid based), edge_ema (alpha=0.05).

  2. Behavior-based classification, not identity-based. After WARMUP_FILLS
     observations on a (mark, symbol) pair, we classify it. A mark qualifies
     as an "informed maker" — i.e. a counterparty worth pennying — iff
       aggressor_share <= AGGRESSOR_MAX_SHARE      (mostly passive)
       AND edge_ema      >= EDGE_THR_PASSIVE       (mid sits above their
                                                    buys / below their sells
                                                    when they fill)
     Round-to-round Mark ID reshuffling and behavior shifts are absorbed
     automatically — the strategy never names "Mark 14".

  3. Trades involving "SUBMISSION" (us) are excluded from stat updates.

The pennying mechanic and exit logic match penny_twap.py:
  - Penny the most recent informed-maker level by 1 tick.
  - Pennying entry posts full remaining capacity per side (SIZE=None).
  - HOLD_PERIOD ticks after first entry, passive-TWAP unwind kicks in
    (post at touch ba-1 / bb+1, slice sized to bleed flat over TWAP_PERIOD).
"""

from typing import Dict, List
import json
import math

from datamodel import Order, OrderDepth, TradingState


LIMITS: Dict[str, int] = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300, "VEV_5100": 300,
    "VEV_5200": 300, "VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300,
    "VEV_6000": 300, "VEV_6500": 300,
}


def _new_stat() -> Dict:
    return {
        "fills": 0,
        "qty": 0,
        "agg_fills": 0,
        "edge_ema": 0.0,
        "last_buy_px": None, "last_buy_ts": -1,
        "last_sell_px": None, "last_sell_ts": -1,
    }


class Trader:
    # Online stat learning
    EMA_ALPHA = 0.05
    WARMUP_FILLS = 20            # min fills per (mark, sym) before classifying

    # Classification — informed-maker thresholds
    EDGE_THR_PASSIVE = 2.0       # edge_ema >= this → mid sits favorably vs their fills
    AGGRESSOR_MAX_SHARE = 0.20   # at most this fraction of fills are aggressor side

    # Pennying mechanics
    LEVEL_TTL = 1000             # an observed level decays after this many ts
    PENNY = 1
    SIZE = None                  # None → post full remaining capacity per side

    # Exit logic
    HOLD_PERIOD = 500            # ts before TWAP unwind starts
    TWAP_PERIOD = 500            # ts to spread the unwind across

    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                saved = {}

        # mark_stats[sym][mark] = stat dict (see _new_stat)
        mark_stats: Dict[str, Dict[str, Dict]] = saved.setdefault("mark_stats", {})
        entry_ts: Dict[str, int] = saved.setdefault("entry_ts", {})
        known_pos: Dict[str, int] = saved.setdefault("known_pos", {})

        ts = int(state.timestamp)
        a = self.EMA_ALPHA

        # 1) Update per-Mark stats from market trades.
        for sym, trades in (state.market_trades or {}).items():
            if not trades:
                continue
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            mid = 0.5 * (max(od.buy_orders.keys()) + min(od.sell_orders.keys()))
            sym_stats = mark_stats.setdefault(sym, {})
            for t in trades:
                buyer = getattr(t, "buyer", "") or ""
                seller = getattr(t, "seller", "") or ""
                qty = abs(int(t.quantity))
                price = int(t.price)

                # Buyer side stats
                if buyer and buyer != "SUBMISSION":
                    s = sym_stats.setdefault(buyer, _new_stat())
                    s["fills"] = int(s.get("fills", 0)) + 1
                    s["qty"] = int(s.get("qty", 0)) + qty
                    edge = float(mid) - float(price)  # buyer's perspective
                    s["edge_ema"] = (1.0 - a) * float(s.get("edge_ema", 0.0)) + a * edge
                    if price > mid:  # crossed the ask → aggressor
                        s["agg_fills"] = int(s.get("agg_fills", 0)) + 1
                    s["last_buy_px"] = price
                    s["last_buy_ts"] = ts

                # Seller side stats
                if seller and seller != "SUBMISSION":
                    s = sym_stats.setdefault(seller, _new_stat())
                    s["fills"] = int(s.get("fills", 0)) + 1
                    s["qty"] = int(s.get("qty", 0)) + qty
                    edge = float(price) - float(mid)
                    s["edge_ema"] = (1.0 - a) * float(s.get("edge_ema", 0.0)) + a * edge
                    if price < mid:  # crossed the bid → aggressor
                        s["agg_fills"] = int(s.get("agg_fills", 0)) + 1
                    s["last_sell_px"] = price
                    s["last_sell_ts"] = ts

        # 2) Reconcile own_trades for entry_ts (used to gate exit phase).
        own_all: Dict[str, List] = state.own_trades or {}
        for sym, otrades in own_all.items():
            if not otrades:
                continue
            cur_known = int(known_pos.get(sym, 0))
            for t in otrades:
                buyer = getattr(t, "buyer", "") or ""
                seller = getattr(t, "seller", "") or ""
                qty = abs(int(t.quantity))
                if buyer == "SUBMISSION":
                    my_qty = +qty
                elif seller == "SUBMISSION":
                    my_qty = -qty
                else:
                    continue
                new_known = cur_known + my_qty
                if cur_known == 0:
                    entry_ts[sym] = ts
                elif new_known == 0:
                    entry_ts.pop(sym, None)
                elif (cur_known > 0 > new_known) or (cur_known < 0 < new_known):
                    entry_ts[sym] = ts  # flipped
                cur_known = new_known
            known_pos[sym] = cur_known

        positions = state.position or {}
        for sym, actual in list(positions.items()):
            if int(actual) != int(known_pos.get(sym, 0)):
                known_pos[sym] = int(actual)
                if int(actual) == 0:
                    entry_ts.pop(sym, None)

        # 3) Classify Marks per symbol and build orders.
        result: Dict[str, List[Order]] = {}
        active_syms = set(mark_stats.keys()) | {s for s, p in positions.items() if p != 0}
        for sym in active_syms:
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            bb = max(od.buy_orders.keys())
            ba = min(od.sell_orders.keys())
            pos = int(positions.get(sym, 0))
            limit = LIMITS.get(sym, 200)
            sym_stats = mark_stats.get(sym, {})

            informed_buy_pxs: List[int] = []
            informed_sell_pxs: List[int] = []
            for mark, s in sym_stats.items():
                fills = int(s.get("fills", 0))
                if fills < self.WARMUP_FILLS:
                    continue
                agg_share = int(s.get("agg_fills", 0)) / max(fills, 1)
                edge_ema = float(s.get("edge_ema", 0.0))
                if agg_share > self.AGGRESSOR_MAX_SHARE:
                    continue
                if edge_ema < self.EDGE_THR_PASSIVE:
                    continue
                # Qualifies as an informed maker for this symbol.
                lb_px = s.get("last_buy_px")
                lb_ts = int(s.get("last_buy_ts", -1))
                if lb_px is not None and ts - lb_ts <= self.LEVEL_TTL:
                    informed_buy_pxs.append(int(lb_px))
                ls_px = s.get("last_sell_px")
                ls_ts = int(s.get("last_sell_ts", -1))
                if ls_px is not None and ts - ls_ts <= self.LEVEL_TTL:
                    informed_sell_pxs.append(int(ls_px))

            in_exit = (
                pos != 0
                and sym in entry_ts
                and (ts - int(entry_ts[sym])) >= self.HOLD_PERIOD
            )
            block_long_add = in_exit and pos > 0
            block_short_add = in_exit and pos < 0
            orders: List[Order] = []

            # Pennying entries (full remaining capacity per side when SIZE=None).
            if informed_buy_pxs and not block_long_add:
                ref = max(informed_buy_pxs)
                bid_px = ref + self.PENNY
                if bid_px < ba:
                    cap = max(0, limit - pos)
                    sz = cap if self.SIZE is None else min(self.SIZE, cap)
                    if sz > 0:
                        orders.append(Order(sym, int(bid_px), sz))

            if informed_sell_pxs and not block_short_add:
                ref = min(informed_sell_pxs)
                ask_px = ref - self.PENNY
                if ask_px > bb:
                    cap = max(0, limit + pos)
                    sz = cap if self.SIZE is None else min(self.SIZE, cap)
                    if sz > 0:
                        orders.append(Order(sym, int(ask_px), -sz))

            # Passive TWAP unwind once aged.
            if in_exit and pos != 0:
                exit_start = int(entry_ts[sym]) + self.HOLD_PERIOD
                elapsed = max(0, ts - exit_start)
                remaining_ts = max(self.TWAP_PERIOD - elapsed, 0)
                if remaining_ts <= 0:
                    slice_qty = abs(pos)
                else:
                    slice_qty = max(1, math.ceil(abs(pos) * 100 / remaining_ts))
                slice_qty = min(slice_qty, abs(pos))
                if pos > 0:
                    exit_px = ba - 1
                    if exit_px > bb and slice_qty > 0:
                        orders.append(Order(sym, int(exit_px), -slice_qty))
                else:
                    exit_px = bb + 1
                    if exit_px < ba and slice_qty > 0:
                        orders.append(Order(sym, int(exit_px), slice_qty))

            if orders:
                result[sym] = orders

        saved["mark_stats"] = mark_stats
        saved["entry_ts"] = entry_ts
        saved["known_pos"] = known_pos
        return result, 0, json.dumps(saved, separators=(",", ":"))