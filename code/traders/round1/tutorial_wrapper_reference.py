from datamodel import TradingState, Order, Trade, Listing
from typing import Dict, List
import importlib.util
from pathlib import Path

_BASE_PATH = Path(__file__).resolve().parents[1] / "round0" / "tut_try_trades.py"
_BASE_SPEC = importlib.util.spec_from_file_location("round0_tut_try_trades", _BASE_PATH)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load base trader from {_BASE_PATH}")
_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)
BaseTrader = _BASE_MODULE.Trader

_MAP = {
    "ASH_COATED_OSMIUM": "EMERALDS",
    "INTARIAN_PEPPER_ROOT": "TOMATOES",
}
_INV_MAP = {value: key for key, value in _MAP.items()}


def _map_symbol(symbol: str) -> str:
    return _MAP.get(symbol, symbol)


def _unmap_symbol(symbol: str) -> str:
    return _INV_MAP.get(symbol, symbol)


def _map_listings(listings: Dict[str, Listing]) -> Dict[str, Listing]:
    mapped: Dict[str, Listing] = {}
    for symbol, listing in listings.items():
        new_symbol = _map_symbol(symbol)
        mapped[new_symbol] = Listing(
            symbol=new_symbol,
            product=new_symbol,
            denomination=listing.denomination,
        )
    return mapped


def _map_trades(trades_by_symbol: Dict[str, List[Trade]]) -> Dict[str, List[Trade]]:
    mapped: Dict[str, List[Trade]] = {}
    for symbol, trades in trades_by_symbol.items():
        new_symbol = _map_symbol(symbol)
        mapped[new_symbol] = [
            Trade(
                symbol=new_symbol,
                price=int(trade.price),
                quantity=int(trade.quantity),
                buyer=getattr(trade, "buyer", ""),
                seller=getattr(trade, "seller", ""),
                timestamp=int(getattr(trade, "timestamp", 0)),
            )
            for trade in trades
        ]
    return mapped


def _map_state(state: TradingState) -> TradingState:
    return TradingState(
        traderData=state.traderData,
        timestamp=state.timestamp,
        listings=_map_listings(state.listings),
        order_depths={_map_symbol(symbol): depth for symbol, depth in state.order_depths.items()},
        own_trades=_map_trades(state.own_trades),
        market_trades=_map_trades(state.market_trades),
        position={_map_symbol(symbol): position for symbol, position in state.position.items()},
        observations=state.observations,
    )


def _unmap_orders(orders_by_symbol: Dict[str, List[Order]]) -> Dict[str, List[Order]]:
    mapped: Dict[str, List[Order]] = {}
    for symbol, orders in orders_by_symbol.items():
        new_symbol = _unmap_symbol(symbol)
        mapped[new_symbol] = [
            Order(new_symbol, int(order.price), int(order.quantity))
            for order in orders
        ]
    return mapped


class Trader(BaseTrader):
    def run(self, state: TradingState):
        mapped_state = _map_state(state)
        orders, conversions, trader_data = super().run(mapped_state)
        return _unmap_orders(orders), conversions, trader_data
