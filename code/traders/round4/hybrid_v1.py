"""
Round 4 — hybrid: MM-at-touch on wide-spread products + adaptive pennying on
narrow-spread products.

Per-product alpha mix:
  HYDROGEL_PACK   (spread=16):  MM at touch (offset=0)
  VEV_4000        (spread=21):  MM at touch
  VEV_4500        (spread=16):  MM at touch
  VELVETFRUIT_EXTRACT (spread=5): Penny informed makers (penny_v1 logic)
  Everything else (spread<=7):    Penny only (if classifier qualifies)

The two modes never compete on the same product, so capacity stays clean.
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

MM_SYMS = {"HYDROGEL_PACK", "VEV_4000", "VEV_4500"}
MM_BASE_SIZE = 20
MM_MIN_PRICE = 5


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
    EMA_ALPHA = 0.05
    WARMUP_FILLS = 20
    EDGE_THR_PASSIVE = 2.0
    AGGRESSOR_MAX_SHARE = 0.20
    LEVEL_TTL = 1000
    PENNY = 1
    SIZE = None
    HOLD_PERIOD = 500
    TWAP_PERIOD = 500

    def _mm_orders(self, sym, od, pos, limit) -> List[Order]:
        bb = max(od.buy_orders.keys()); ba = min(od.sell_orders.keys())
        if ba <= bb: return []
        mid = 0.5 * (bb + ba)
        if mid < MM_MIN_PRICE: return []
        spread = ba - bb
        # only post when spread is wide enough that 1-tick-inside captures edge
        if spread < 8: return []
        buy_cap = limit - pos; sell_cap = limit + pos
        soft = 0.7 * limit
        extra = max(0, abs(pos) - soft)
        taper = max(0.2, 1.0 - extra / max(1.0, 0.3 * limit))
        bid_size = max(1, int(MM_BASE_SIZE * (taper if pos >= 0 else 1.0)))
        ask_size = max(1, int(MM_BASE_SIZE * (taper if pos <= 0 else 1.0)))
        orders: List[Order] = []
        bid_qty = min(bid_size, max(0, buy_cap))
        ask_qty = min(ask_size, max(0, sell_cap))
        if bid_qty > 0:
            orders.append(Order(sym, int(bb), bid_qty))
        if ask_qty > 0:
            orders.append(Order(sym, int(ba), -ask_qty))
        return orders

    def run(self, state: TradingState):
        saved: Dict = {}
        if state.traderData:
            try: saved = json.loads(state.traderData)
            except Exception: saved = {}

        mark_stats: Dict[str, Dict[str, Dict]] = saved.setdefault("mark_stats", {})
        entry_ts: Dict[str, int] = saved.setdefault("entry_ts", {})
        known_pos: Dict[str, int] = saved.setdefault("known_pos", {})

        ts = int(state.timestamp)
        a = self.EMA_ALPHA

        # 1) Update per-Mark stats from market trades.
        for sym, trades in (state.market_trades or {}).items():
            if not trades: continue
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders: continue
            mid = 0.5 * (max(od.buy_orders.keys()) + min(od.sell_orders.keys()))
            sym_stats = mark_stats.setdefault(sym, {})
            for t in trades:
                buyer = getattr(t, "buyer", "") or ""
                seller = getattr(t, "seller", "") or ""
                qty = abs(int(t.quantity)); price = int(t.price)
                if buyer and buyer != "SUBMISSION":
                    s = sym_stats.setdefault(buyer, _new_stat())
                    s["fills"] = int(s.get("fills", 0)) + 1
                    s["qty"] = int(s.get("qty", 0)) + qty
                    edge = float(mid) - float(price)
                    s["edge_ema"] = (1.0 - a) * float(s.get("edge_ema", 0.0)) + a * edge
                    if price > mid: s["agg_fills"] = int(s.get("agg_fills", 0)) + 1
                    s["last_buy_px"] = price; s["last_buy_ts"] = ts
                if seller and seller != "SUBMISSION":
                    s = sym_stats.setdefault(seller, _new_stat())
                    s["fills"] = int(s.get("fills", 0)) + 1
                    s["qty"] = int(s.get("qty", 0)) + qty
                    edge = float(price) - float(mid)
                    s["edge_ema"] = (1.0 - a) * float(s.get("edge_ema", 0.0)) + a * edge
                    if price < mid: s["agg_fills"] = int(s.get("agg_fills", 0)) + 1
                    s["last_sell_px"] = price; s["last_sell_ts"] = ts

        # 2) Reconcile own_trades for entry_ts.
        own_all: Dict[str, List] = state.own_trades or {}
        for sym, otrades in own_all.items():
            if not otrades: continue
            cur_known = int(known_pos.get(sym, 0))
            for t in otrades:
                buyer = getattr(t, "buyer", "") or ""
                seller = getattr(t, "seller", "") or ""
                qty = abs(int(t.quantity))
                if buyer == "SUBMISSION": my_qty = +qty
                elif seller == "SUBMISSION": my_qty = -qty
                else: continue
                new_known = cur_known + my_qty
                if cur_known == 0:
                    entry_ts[sym] = ts
                elif new_known == 0:
                    entry_ts.pop(sym, None)
                elif (cur_known > 0 > new_known) or (cur_known < 0 < new_known):
                    entry_ts[sym] = ts
                cur_known = new_known
            known_pos[sym] = cur_known

        positions = state.position or {}
        for sym, actual in list(positions.items()):
            if int(actual) != int(known_pos.get(sym, 0)):
                known_pos[sym] = int(actual)
                if int(actual) == 0:
                    entry_ts.pop(sym, None)

        result: Dict[str, List[Order]] = {}

        # 3a) MM-at-touch on wide-spread products.
        for sym in MM_SYMS:
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders: continue
            limit = LIMITS.get(sym, 200)
            pos = int(positions.get(sym, 0))
            mm = self._mm_orders(sym, od, pos, limit)
            if mm: result[sym] = mm

        # 3b) Penny informed makers on the rest (and override MM if we want
        # to penny on a wide-spread product too — but skip MM_SYMS for clarity).
        active_syms = (set(mark_stats.keys()) | {s for s, p in positions.items() if p != 0}) - MM_SYMS
        for sym in active_syms:
            od = state.order_depths.get(sym)
            if od is None or not od.buy_orders or not od.sell_orders: continue
            bb = max(od.buy_orders.keys()); ba = min(od.sell_orders.keys())
            pos = int(positions.get(sym, 0))
            limit = LIMITS.get(sym, 200)
            sym_stats = mark_stats.get(sym, {})

            informed_buy_pxs: List[int] = []
            informed_sell_pxs: List[int] = []
            for mark, s in sym_stats.items():
                fills = int(s.get("fills", 0))
                if fills < self.WARMUP_FILLS: continue
                agg_share = int(s.get("agg_fills", 0)) / max(fills, 1)
                edge_ema = float(s.get("edge_ema", 0.0))
                if agg_share > self.AGGRESSOR_MAX_SHARE: continue
                if edge_ema < self.EDGE_THR_PASSIVE: continue
                lb_px = s.get("last_buy_px"); lb_ts = int(s.get("last_buy_ts", -1))
                if lb_px is not None and ts - lb_ts <= self.LEVEL_TTL:
                    informed_buy_pxs.append(int(lb_px))
                ls_px = s.get("last_sell_px"); ls_ts = int(s.get("last_sell_ts", -1))
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

            if orders: result[sym] = orders

        saved["mark_stats"] = mark_stats
        saved["entry_ts"] = entry_ts
        saved["known_pos"] = known_pos
        return result, 0, json.dumps(saved, separators=(",", ":"))
