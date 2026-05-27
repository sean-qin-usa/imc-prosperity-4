import json
from typing import Dict, List
from datamodel import TradingState, Order

class Trader:
    def __init__(self):
        self.ema = None

    def run(self, state: TradingState):
        result = {}
        conversions = 0
        traderData = ""

        if state.traderData:
            try:
                data = json.loads(state.traderData)
                self.ema = data.get("ema", None)
            except:
                pass

        for product in state.order_depths:
            order_depth = state.order_depths[product]
            orders: List[Order] = []
            pos = state.position.get(product, 0)
            limit = 80
            
            buy_cap = limit - pos
            sell_cap = limit + pos

            # ==========================================
            # EMERALDS: High-Volume Squeeze
            # ==========================================
            if product == 'EMERALDS':
                fair = 10000
                
                # 1. Instant Arbitrage
                if order_depth.sell_orders:
                    for ask, vol in sorted(order_depth.sell_orders.items()):
                        if ask < fair and buy_cap > 0:
                            qty = min(-vol, buy_cap)
                            orders.append(Order(product, ask, qty))
                            buy_cap -= qty
                            
                if order_depth.buy_orders:
                    for bid, vol in sorted(order_depth.buy_orders.items(), reverse=True):
                        if bid > fair and sell_cap > 0:
                            qty = min(vol, sell_cap)
                            orders.append(Order(product, bid, -qty))
                            sell_cap -= qty
                            
                # 2. Aggressive 1-Tick Quoting
                # Camp at 9999/10001 unless inventory is heavily skewed
                bid_px = 9999 if pos < 40 else 9998
                ask_px = 10001 if pos > -40 else 10002
                
                if buy_cap > 0:
                    orders.append(Order(product, bid_px, buy_cap))
                if sell_cap > 0:
                    orders.append(Order(product, ask_px, -sell_cap))
                    
                result[product] = orders

            # ==========================================
            # TOMATOES: Hyper-Responsive Stat Arb
            # ==========================================
            elif product == 'TOMATOES':
                bids = order_depth.buy_orders
                asks = order_depth.sell_orders
                
                if not bids or not asks:
                    continue
                    
                best_bid = max(bids.keys())
                best_ask = min(asks.keys())
                mid = (best_bid + best_ask) / 2.0
                
                # Microprice Calculation
                bid_vol = bids[best_bid]
                ask_vol = -asks[best_ask]
                total_vol = bid_vol + ask_vol
                microprice = (best_bid * ask_vol + best_ask * bid_vol) / total_vol if total_vol > 0 else mid
                
                # Highly responsive EMA (50% weight to instantaneous microprice)
                if self.ema is None:
                    self.ema = mid
                else:
                    self.ema = 0.50 * self.ema + 0.50 * microprice 
                    
                # Heavy inventory skew to force reversion (4 ticks max)
                skew = (pos / limit) * 4.0 
                fair = self.ema - skew
                
                # 1. Uncapped Aggressive Taking
                if asks:
                    for ask, vol in sorted(asks.items()):
                        if ask <= fair - 1.5 and buy_cap > 0:
                            qty = min(-vol, buy_cap) # Removed the artificial 25 limit
                            orders.append(Order(product, ask, qty))
                            buy_cap -= qty
                            
                if bids:
                    for bid, vol in sorted(bids.items(), reverse=True):
                        if bid >= fair + 1.5 and sell_cap > 0:
                            qty = min(vol, sell_cap) # Removed the artificial 25 limit
                            orders.append(Order(product, bid, -qty))
                            sell_cap -= qty
                            
                # 2. Smart Passive Quoting (Penny-Jumping)
                bid_px = int(round(fair - 2))
                ask_px = int(round(fair + 2))
                
                # Guarantee we don't cross the spread, but try to front-run
                bid_px = min(bid_px, best_ask - 1)
                ask_px = max(ask_px, best_bid + 1)
                
                if buy_cap > 0:
                    orders.append(Order(product, bid_px, buy_cap))
                if sell_cap > 0:
                    orders.append(Order(product, ask_px, -sell_cap))
                    
                result[product] = orders

        traderData = json.dumps({"ema": self.ema})
        return result, conversions, traderData