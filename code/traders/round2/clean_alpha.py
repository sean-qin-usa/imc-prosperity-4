"""Round 2 clean-alpha strategy, tuned for single-day PnL.

No fill-matcher exploits: no 1-lot child-order splitting, no size-bucket
calibration, no posting the whole limit at a single price as many tiny
orders. Everything here is honest alpha.

Primary alphas:

  1. IPR drift: price rises +0.001 per timestamp, deterministic.
     Capture by carrying a long inventory target.

  2. ACO / IPR book-imbalance microprice signal: at |imb| > 0.5 the
     next mid moves ~3.6 in the imbalance direction with >95% prob
     (ACO +3.61, IPR +3.99 at the positive tail; symmetric on negative
     side). Capture by (a) anchoring fair on the volume-weighted
     micro-price instead of the mid, and (b) pulling passive size on
     the side imbalance is pushing against.

  3. ACO stationarity around 10_000: provides the long-term anchor,
     clipped so the micro-price doesn't pull us too far.

Per-day alpha breakdown (empirical):

  IPR drift carry @ ~80 units avg          ~80_000
  IPR residual mean-reversion              ~15_000 - 30_000
  ACO MM with micro-price fair             ~40_000 - 70_000
  Imbalance-aware skew on both             ~15_000 - 25_000
                                           ------------------
  Realistic range                          ~150_000 - 200_000

Levers vs. the previous baseline:

  - Fair uses volume-weighted micro-price, not mid (both products)
  - Imbalance-aware size skew: shrink passive quotes on the side the
    imbalance is pushing against (adverse-selection guard)
  - IPR inventory target 70 -> 80          (+10_000 drift / day)
  - IPR early accumulation window 500 -> 2_000 ticks
  - IPR early-take target pushed to full limit when cheap asks exist
  - IPR passive bids at two price levels when spread > 4
  - ACO MM offset 3 -> 2, size 19 -> 22
  - ACO takes deeper ask/bid levels on the same pass
  - End-of-day unwind only in the last 1% of the day
"""

import json
import math
from typing import Any, Dict, List, Optional

from datamodel import Order, OrderDepth, TradingState


class Trader:
    MAF_BID = 15_000

    LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}

    ACO_FAIR = 10_000
    ACO_FAIR_CLIP = 4.0
    ACO_TAKE_EDGE = 0.0
    ACO_REDUCE_EDGE = 1.0
    ACO_INV_SKEW = 0.06
    ACO_MM_SIZE = 75
    ACO_MM_OFFSET = 1
    ACO_PENNY_EDGE = 1.0
    ACO_WIDE_SPREAD = 4
    ACO_LATE_UNWIND_START = 990_000
    ACO_LATE_UNWIND_EDGE = 1.0
    ACO_LATE_UNWIND_MAX = 12
    ACO_TYPICAL_SPREAD = 16
    ACO_WALKED_FAIR_CLIP = 6.0

    IPR_TYPICAL_SPREAD = 14
    IPR_WALKED_FAIR_CLIP = 5.0

    # Imbalance alpha: L1 book imbalance has r=+0.59 with next-tick mid move,
    # and at |imb| > 0.5 the expected move is +-3.6 with >95% direction hit
    # rate. IMB_STRONG gates the size adjustments; IMB_FAVORABLE_BOOST scales
    # up the side the imbalance is pushing into; IMB_ADVERSE_SHRINK reduces
    # the opposite side (adverse-selection guard).
    IMB_STRONG = 0.30
    IMB_FAVORABLE_BOOST = 1.8
    IMB_ADVERSE_SHRINK = 0.2
    # Fill post-mortem 2026-04-23: ACO take-side E[pnl/unit,10t] was only
    # +0.2 (sell) / +1.1 (buy) vs passive +7.4/+7.6.  Imbalance-conditional
    # take relaxation made ACO takes too generous.  Disable globally.
    IMB_TAKE_RELAX = 0.0

    # When spread > typical_spread the walked side rebounds next tick by +1 to
    # +3 pts. Post an extra quote on the rebound side at bid+1 or ask-1 with
    # walked-side size, in addition to the normal passive quote.
    ACO_WALKED_EXTRA_SIZE = 55
    IPR_WALKED_EXTRA_SIZE = 12

    IPR_DRIFT = 0.001
    IPR_TARGET = 80
    IPR_SOFT_TARGET = 72
    IPR_TAKE_EDGE = 0.0
    IPR_EARLY_WINDOW = 2_000
    IPR_EARLY_MAX_QTY = 20
    IPR_REVERT_SIZE = 8
    IPR_RICH_Z = 1.2
    IPR_CHEAP_Z = -1.2
    IPR_PASSIVE_SIZE = 12
    IPR_PASSIVE_SECOND_SIZE = 6
    IPR_VAR_ALPHA = 0.06
    IPR_INIT_VAR = 6.0
    IPR_ANCHOR_ALPHA = 0.02
    IPR_ANCHOR_WARMUP = 12_000
    IPR_ANCHOR_CLIP = 3.0
    IPR_UNWIND_START = 990_000
    IPR_UNWIND_SIZE = 20

    def bid(self) -> int:
        return self.MAF_BID

    def run(self, state: TradingState):
        saved = self._load(state.traderData)
        last_ts = saved["last_ts"]
        day_reset = last_ts is not None and state.timestamp < last_ts

        result: Dict[str, List[Order]] = {}

        if "ASH_COATED_OSMIUM" in state.order_depths:
            result["ASH_COATED_OSMIUM"] = self._trade_aco(
                state.order_depths["ASH_COATED_OSMIUM"],
                state.position.get("ASH_COATED_OSMIUM", 0),
                state.timestamp,
            )

        ipr_anchor = saved["ipr_anchor"]
        ipr_var = saved["ipr_var"]
        if "INTARIAN_PEPPER_ROOT" in state.order_depths:
            book = self._book(state.order_depths["INTARIAN_PEPPER_ROOT"])
            if book is not None:
                # Use micro-price for anchor & residual so the benchmark
                # reflects book pressure, not just the midpoint.
                micro = book["micro"]
                ipr_anchor = self._update_anchor(ipr_anchor, micro, state.timestamp, day_reset)
                residual = micro - (ipr_anchor + self.IPR_DRIFT * state.timestamp)
                ipr_var = (1 - self.IPR_VAR_ALPHA) * ipr_var + self.IPR_VAR_ALPHA * residual * residual
            result["INTARIAN_PEPPER_ROOT"] = self._trade_ipr(
                state.order_depths["INTARIAN_PEPPER_ROOT"],
                state.position.get("INTARIAN_PEPPER_ROOT", 0),
                ipr_anchor,
                ipr_var,
                state.timestamp,
            )

        trader_data = json.dumps(
            {"ipr_anchor": ipr_anchor, "ipr_var": ipr_var, "last_ts": state.timestamp},
            separators=(",", ":"),
        )
        return result, 0, trader_data

    def _load(self, trader_data: str) -> Dict[str, Any]:
        default = {"ipr_anchor": None, "ipr_var": self.IPR_INIT_VAR, "last_ts": None}
        if not trader_data:
            return default
        try:
            p = json.loads(trader_data)
        except Exception:
            return default
        return {
            "ipr_anchor": p.get("ipr_anchor"),
            "ipr_var": float(p.get("ipr_var", self.IPR_INIT_VAR)),
            "last_ts": p.get("last_ts"),
        }

    def _book(self, od: OrderDepth) -> Optional[Dict[str, Any]]:
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(p): abs(int(v)) for p, v in sorted(od.buy_orders.items(), reverse=True)}
        sells = {int(p): abs(int(v)) for p, v in sorted(od.sell_orders.items())}
        if not buys or not sells:
            return None
        best_bid = max(buys)
        best_ask = min(sells)
        bv, av = buys[best_bid], sells[best_ask]
        tot = bv + av
        imbalance = (bv - av) / tot if tot > 0 else 0.0
        spread = best_ask - best_bid
        # Conditional-imbalance finding (2026-04-23): on ACO at spread=16
        # (the 82%-of-data normal state), L1-imbalance correlation with
        # next-Δmid is ≈ 0.  All of the +0.59 aggregate correlation comes
        # from walked states (spread 18-19).  So gate the micro-price
        # effect on the spread being non-normal.
        if spread <= 16:  # ACO normal regime — disable imbalance shift
            micro = 0.5 * (best_bid + best_ask)
        elif tot > 0:
            micro = (best_ask * bv + best_bid * av) / tot
        else:
            micro = 0.5 * (best_bid + best_ask)
        return {
            "buys": buys,
            "sells": sells,
            "bid": best_bid,
            "ask": best_ask,
            "imbalance": imbalance,
            "micro": micro,
        }

    def _walked_fair(
        self,
        best_bid: int,
        best_ask: int,
        micro: float,
        anchor: float,
        typical_spread: int,
        clip: float,
    ) -> float:
        """Spread-walked fair correction.

        When the observed spread exceeds the typical MM spread, one or both
        sides have 'walked'. Empirically the walked side snaps back next
        tick (see research_log). The true fair sits typical_spread/2 away
        from whichever side is closer to the stationary anchor.  When the
        spread is normal, fall back to the micro-price (imbalance alpha).
        """
        spread = best_ask - best_bid
        if spread <= typical_spread:
            return anchor + max(-clip, min(clip, micro - anchor))
        bid_gap = anchor - best_bid
        ask_gap = best_ask - anchor
        half = typical_spread / 2
        if bid_gap > ask_gap + 0.5:
            trusted = best_ask - half
        elif ask_gap > bid_gap + 0.5:
            trusted = best_bid + half
        else:
            trusted = 0.5 * (best_bid + best_ask)
        return anchor + max(-clip, min(clip, trusted - anchor))

    def _update_anchor(
        self, anchor: Optional[float], mid: float, ts: int, day_reset: bool
    ) -> float:
        observed = mid - self.IPR_DRIFT * ts
        if anchor is None or day_reset:
            return observed
        if ts <= self.IPR_ANCHOR_WARMUP:
            delta = max(-self.IPR_ANCHOR_CLIP, min(self.IPR_ANCHOR_CLIP, observed - anchor))
            return anchor + self.IPR_ANCHOR_ALPHA * delta
        return anchor

    def _trade_aco(self, od: OrderDepth, position: int, ts: int) -> List[Order]:
        product = "ASH_COATED_OSMIUM"
        limit = self.LIMITS[product]
        book = self._book(od)
        if book is None:
            return []

        buys, sells = book["buys"], book["sells"]
        best_bid, best_ask = book["bid"], book["ask"]
        micro = book["micro"]
        imb = book["imbalance"]
        spread = best_ask - best_bid

        # Walked-fair: when spread > ACO_TYPICAL_SPREAD, one side has pulled
        # and will snap back by ~1-3 pts next tick. Lean fair toward the
        # unwalked side. Normal spreads fall back to the micro-price.
        fair = self._walked_fair(
            best_bid, best_ask, micro, float(self.ACO_FAIR),
            self.ACO_TYPICAL_SPREAD, self.ACO_WALKED_FAIR_CLIP,
        )

        pos = position
        orders: List[Order] = []

        # Imbalance-conditional take relaxation: when imb strongly favors the
        # buy side, relax the buy edge by IMB_TAKE_RELAX (we can pay up to
        # fair + relax because next mid is ~+1.6 higher). Mirror for sell.
        buy_relax = self.IMB_TAKE_RELAX if imb > self.IMB_STRONG else 0.0
        sell_relax = self.IMB_TAKE_RELAX if imb < -self.IMB_STRONG else 0.0

        # Take all asks at/below skewed-fair in one pass, not just best ask.
        for ap, av in sells.items():
            if limit - pos <= 0:
                break
            skewed = fair - self.ACO_INV_SKEW * pos
            if ap <= skewed - self.ACO_TAKE_EDGE + buy_relax:
                qty = min(av, limit - pos)
                if qty > 0:
                    orders.append(Order(product, ap, qty))
                    pos += qty
            elif pos < 0 and ap <= skewed + self.ACO_REDUCE_EDGE:
                qty = min(av, limit - pos, -pos)
                if qty > 0:
                    orders.append(Order(product, ap, qty))
                    pos += qty

        for bp, bv in buys.items():
            if limit + pos <= 0:
                break
            skewed = fair - self.ACO_INV_SKEW * pos
            if bp >= skewed + self.ACO_TAKE_EDGE - sell_relax:
                qty = min(bv, limit + pos)
                if qty > 0:
                    orders.append(Order(product, bp, -qty))
                    pos -= qty
            elif pos > 0 and bp >= skewed - self.ACO_REDUCE_EDGE:
                qty = min(bv, limit + pos, pos)
                if qty > 0:
                    orders.append(Order(product, bp, -qty))
                    pos -= qty

        # End-of-day unwind into best bid/ask if we still have inventory.
        if ts >= self.ACO_LATE_UNWIND_START:
            if pos > 0 and best_bid >= math.floor(fair - self.ACO_LATE_UNWIND_EDGE):
                qty = min(pos, buys.get(best_bid, 0), self.ACO_LATE_UNWIND_MAX)
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))
                    pos -= qty
            elif pos < 0 and best_ask <= math.ceil(fair + self.ACO_LATE_UNWIND_EDGE):
                qty = min(-pos, sells.get(best_ask, 0), self.ACO_LATE_UNWIND_MAX)
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
                    pos += qty

        # Passive MM: tighter offset, bigger size, penny inside on wide books.
        skewed = fair - self.ACO_INV_SKEW * pos
        if spread >= self.ACO_WIDE_SPREAD:
            bid_px = min(best_bid + 1, math.floor(skewed - self.ACO_PENNY_EDGE))
            ask_px = max(best_ask - 1, math.ceil(skewed + self.ACO_PENNY_EDGE))
        else:
            bid_px = math.floor(skewed - self.ACO_MM_OFFSET)
            ask_px = math.ceil(skewed + self.ACO_MM_OFFSET)
        bid_px = min(int(bid_px), best_ask - 1, math.floor(fair) - 1)
        ask_px = max(int(ask_px), best_bid + 1, math.ceil(fair) + 1)

        buy_cap = max(0, limit - pos)
        sell_cap = max(0, limit + pos)
        bid_sz = min(self.ACO_MM_SIZE, buy_cap)
        ask_sz = min(self.ACO_MM_SIZE, sell_cap)

        # Imbalance-aware passive skew: shrink the side the imbalance is
        # pushing against, and boost the side it is pushing toward.  Bigger
        # bid when imb > +0.3 (next mid rising, want long inventory); bigger
        # ask when imb < -0.3 (next mid falling, want short inventory).
        if imb > self.IMB_STRONG:
            ask_sz = max(0, int(round(ask_sz * self.IMB_ADVERSE_SHRINK)))
            bid_sz = min(buy_cap, int(round(bid_sz * self.IMB_FAVORABLE_BOOST)))
        elif imb < -self.IMB_STRONG:
            bid_sz = max(0, int(round(bid_sz * self.IMB_ADVERSE_SHRINK)))
            ask_sz = min(sell_cap, int(round(ask_sz * self.IMB_FAVORABLE_BOOST)))

        if bid_px < ask_px:
            if bid_sz > 0:
                orders.append(Order(product, bid_px, bid_sz))
            if ask_sz > 0:
                orders.append(Order(product, ask_px, -ask_sz))

        # Walked-rebound block: when spread has walked, post an extra quote on
        # the side that is about to snap back, at bid+1 / ask-1 (inside the
        # spread by 1 tick).  Edge per fill is ~the rebound magnitude.
        if spread > self.ACO_TYPICAL_SPREAD:
            bid_gap = self.ACO_FAIR - best_bid
            ask_gap = best_ask - self.ACO_FAIR
            if bid_gap > ask_gap + 0.5 and pos < limit:
                walked_px = best_bid + 1
                if walked_px < math.floor(fair):
                    walked_sz = min(self.ACO_WALKED_EXTRA_SIZE, limit - pos)
                    if walked_sz > 0 and walked_px != bid_px:
                        orders.append(Order(product, walked_px, walked_sz))
            elif ask_gap > bid_gap + 0.5 and pos > -limit:
                walked_px = best_ask - 1
                if walked_px > math.ceil(fair):
                    walked_sz = min(self.ACO_WALKED_EXTRA_SIZE, limit + pos)
                    if walked_sz > 0 and walked_px != ask_px:
                        orders.append(Order(product, walked_px, -walked_sz))

        return orders

    def _trade_ipr(
        self,
        od: OrderDepth,
        position: int,
        anchor: Optional[float],
        var: float,
        ts: int,
    ) -> List[Order]:
        product = "INTARIAN_PEPPER_ROOT"
        limit = self.LIMITS[product]
        book = self._book(od)
        if book is None:
            return []

        buys, sells = book["buys"], book["sells"]
        best_bid, best_ask = book["bid"], book["ask"]
        micro = book["micro"]
        imb = book["imbalance"]
        spread = best_ask - best_bid

        if anchor is None:
            anchor = micro - self.IPR_DRIFT * ts
        benchmark = anchor + self.IPR_DRIFT * ts
        sigma = max(1.0, math.sqrt(max(0.0, var)))
        zscore = (micro - benchmark) / sigma

        # Walked-fair for IPR using the drift-aware benchmark as anchor.
        fair = self._walked_fair(
            best_bid, best_ask, micro, benchmark,
            self.IPR_TYPICAL_SPREAD, self.IPR_WALKED_FAIR_CLIP,
        )

        pos = position
        orders: List[Order] = []

        # End-of-day unwind: close long inventory into the last 1% of the day.
        if ts >= self.IPR_UNWIND_START:
            if pos > 0 and best_bid >= benchmark - 1:
                qty = min(pos, buys.get(best_bid, 0), self.IPR_UNWIND_SIZE)
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))
            return orders

        # Take threshold: use the higher of benchmark and walked-fair.  When
        # the ask side has walked up, walked-fair < benchmark and we stay
        # disciplined; when the bid walked down and we trust the ask, fair
        # >= benchmark and we can pay slightly more to capture the rebound.
        take_fair = max(benchmark, fair)

        # Early-session aggressive accumulation: take every ask at/below
        # take_fair, up to the position limit, while the book is still cheap.
        if ts <= self.IPR_EARLY_WINDOW and pos < self.IPR_TARGET:
            for ap, av in sells.items():
                if pos >= self.IPR_TARGET:
                    break
                if ap <= take_fair + self.IPR_TAKE_EDGE:
                    qty = min(av, self.IPR_TARGET - pos, limit - pos, self.IPR_EARLY_MAX_QTY)
                    if qty > 0:
                        orders.append(Order(product, ap, qty))
                        pos += qty
                else:
                    break

        # Ongoing take at take_fair or below, up to soft target.
        if pos < self.IPR_SOFT_TARGET:
            for ap, av in sells.items():
                if pos >= self.IPR_SOFT_TARGET:
                    break
                if ap <= take_fair + self.IPR_TAKE_EDGE:
                    qty = min(av, self.IPR_SOFT_TARGET - pos, limit - pos)
                    if qty > 0:
                        orders.append(Order(product, ap, qty))
                        pos += qty
                else:
                    break

        # Mean-revert sell when residual is high enough and we have stock.
        if zscore >= self.IPR_RICH_Z and pos > 0 and best_bid >= benchmark + 1:
            qty = min(self.IPR_REVERT_SIZE, pos, buys.get(best_bid, 0))
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                pos -= qty

        # Mean-revert reload on cheap residuals.
        if zscore <= self.IPR_CHEAP_Z and pos < limit and best_ask <= benchmark + 0.5:
            qty = min(self.IPR_REVERT_SIZE, limit - pos, sells.get(best_ask, 0))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                pos += qty

        # Passive bids inside the spread. Post a primary bid at bid+1 and a
        # secondary at bid+2 when the book is wide, so we occupy two priority
        # slots instead of one. Shrink (or skip) when imbalance says the next
        # mid is about to fall - our bid would otherwise be picked off.
        if pos < limit and spread > 2 and imb > -self.IMB_STRONG:
            primary_px = min(best_bid + 1, best_ask - 1)
            primary_sz = min(self.IPR_PASSIVE_SIZE, limit - pos)
            if imb > self.IMB_STRONG:
                primary_sz = min(limit - pos, int(round(primary_sz * self.IMB_FAVORABLE_BOOST)))
            elif imb < 0:
                primary_sz = max(0, int(round(primary_sz * (1 + imb))))
            if primary_sz > 0 and primary_px < best_ask:
                orders.append(Order(product, primary_px, primary_sz))

                if spread > 4 and pos + primary_sz < limit:
                    secondary_px = min(best_bid + 2, best_ask - 1)
                    if secondary_px > primary_px:
                        secondary_sz = min(
                            self.IPR_PASSIVE_SECOND_SIZE, limit - pos - primary_sz
                        )
                        if secondary_sz > 0:
                            orders.append(Order(product, secondary_px, secondary_sz))

        # Walked-rebound block for IPR: when the spread exceeds the typical
        # IPR width, the walked side snaps back.  Post on the rebound side.
        if spread > self.IPR_TYPICAL_SPREAD:
            bid_gap = benchmark - best_bid
            ask_gap = best_ask - benchmark
            if bid_gap > ask_gap + 0.5 and pos < limit:
                walked_px = best_bid + 1
                if walked_px < fair:
                    walked_sz = min(self.IPR_WALKED_EXTRA_SIZE, limit - pos)
                    if walked_sz > 0:
                        orders.append(Order(product, walked_px, walked_sz))
            elif ask_gap > bid_gap + 0.5 and pos > 0:
                walked_px = best_ask - 1
                if walked_px > fair:
                    walked_sz = min(self.IPR_WALKED_EXTRA_SIZE, pos)
                    if walked_sz > 0:
                        orders.append(Order(product, walked_px, -walked_sz))

        return orders
