from datamodel import TradingState, Order
from typing import Dict, List, Any
import json


def _best_price(order_book: Dict[int, int], is_buy: bool):
    if not order_book:
        return None
    price = max(order_book) if is_buy else min(order_book)
    return [int(price), int(order_book[price])]


def _safe_json(obj: Any):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {str(k): _safe_json(v) for k, v in obj.__dict__.items()}
    return str(obj)


def _serialize_trades(trades_by_symbol):
    serialized = {}
    for symbol, trades in trades_by_symbol.items():
        serialized[symbol] = [
            {
                "symbol": getattr(trade, "symbol", symbol),
                "price": int(getattr(trade, "price", 0)),
                "qty": int(getattr(trade, "quantity", 0)),
                "buyer": getattr(trade, "buyer", ""),
                "seller": getattr(trade, "seller", ""),
                "ts": int(getattr(trade, "timestamp", 0)),
            }
            for trade in trades
        ]
    return serialized


def _log_state(state: TradingState) -> None:
    payload = {
        "type": "snapshot",
        "ts": int(getattr(state, "timestamp", 0)),
        "traderData": getattr(state, "traderData", ""),
        "positions": {symbol: int(pos) for symbol, pos in state.position.items()},
        "order_depths": {
            symbol: {
                "buy": {str(p): int(q) for p, q in depth.buy_orders.items()},
                "sell": {str(p): int(q) for p, q in depth.sell_orders.items()},
                "best_bid": _best_price(depth.buy_orders, is_buy=True),
                "best_ask": _best_price(depth.sell_orders, is_buy=False),
            }
            for symbol, depth in state.order_depths.items()
        },
        "own_trades": _serialize_trades(state.own_trades),
        "market_trades": _serialize_trades(state.market_trades),
        "observations": _safe_json(getattr(state, "observations", None)),
    }
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


class Trader:
    """Do-nothing trader: submits no orders for any product."""

    def bid(self) -> int:
        # Safe for Round 2; ignored elsewhere.
        return 0

    def run(self, state: TradingState):
        _log_state(state)
        result: Dict[str, List[Order]] = {product: [] for product in state.order_depths}
        conversions = 0
        trader_data = ""
        return result, conversions, trader_data
