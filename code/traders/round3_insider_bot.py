import json
from typing import Dict, List
from datamodel import OrderDepth, TradingState, Order, Trade

class Trader:    
    def __init__(self):
        self.max_pos = {
            "HYDROGEL_PACK": 200,
            "VELVETFRUIT_EXTRACT": 200
        }
        
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {product: [] for product in state.order_depths}
        
        # Load state from traderData
        try:
            persisted_state = json.loads(state.traderData)
        except (ValueError, TypeError, json.JSONDecodeError):
            persisted_state = {
                "targets": {
                    "HYDROGEL_PACK": {"pos": 0, "expires": 0},
                    "VELVETFRUIT_EXTRACT": {"pos": 0, "expires": 0}
                }
            }

        targets = persisted_state.get("targets", {})

        # Process market trades to find the Insider
        # Signal variables
        H_PACK = "HYDROGEL_PACK"
        V_EXTRACT = "VELVETFRUIT_EXTRACT"
        
        for symbol, trades in state.market_trades.items():
            if symbol not in [H_PACK, V_EXTRACT]:
                continue
                
            depth = state.order_depths.get(symbol)
            if not depth:
                continue
            
            best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
            best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
            
            # Safe guards if book is empty
            if best_ask is None or best_bid is None:
                continue

            for trade in trades:
                # Insider Fingerprint mapping
                is_insider = False
                if symbol == H_PACK and trade.quantity in [4, 5, 6]:
                    is_insider = True
                elif symbol == V_EXTRACT and trade.quantity in [5, 6, 7, 8, 15]:
                    is_insider = True

                if is_insider:
                    # Direction inference
                    if trade.price >= best_ask:
                        # Insider is overwhelmingly buying at Ask
                        targets[symbol] = {"pos": self.max_pos[symbol], "expires": state.timestamp + 2000}
                    elif trade.price <= best_bid:
                        # Insider is overwhelmingly selling at Bid
                        targets[symbol] = {"pos": -self.max_pos[symbol], "expires": state.timestamp + 2000}

        # Order Execution
        for symbol in [H_PACK, V_EXTRACT]:
            if symbol not in state.order_depths:
                continue
                
            spec = targets.get(symbol, {"pos": 0, "expires": 0})
            target_pos = spec["pos"]
            
            # Expiration
            if state.timestamp > spec["expires"]:
                target_pos = 0
                targets[symbol]["pos"] = 0
                
            current_pos = state.position.get(symbol, 0)
            
            # Simple, aggressive order routing to hit target position
            trade_qty = target_pos - current_pos
            if trade_qty != 0:
                depth = state.order_depths[symbol]
                best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
                best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
                
                # Modify execution to be strictly passive to avoid paying the massive 16-tick spread
                if trade_qty > 0:
                    # Target is higher, we need to buy. Quote on the bid.
                    # We quote at best_bid + 1 to be at the top of the queue, but never cross the ask.
                    price = best_bid + 1 if best_bid else int(1e9)
                    if best_ask and price >= best_ask:
                        price = best_ask - 1
                    result[symbol].append(Order(symbol, price, trade_qty))
                elif trade_qty < 0:
                    # Target is lower, we need to sell. Quote on the ask.
                    # We quote at best_ask - 1 to be at the top of the queue, but never cross the bid.
                    price = best_ask - 1 if best_ask else 0
                    if best_bid and price <= best_bid:
                        price = best_bid + 1
                    result[symbol].append(Order(symbol, price, trade_qty))

        # Re-pack state
        conversions = 0
        persisted_state["targets"] = targets
        trader_data = json.dumps(persisted_state)
        
        return result, conversions, trader_data
