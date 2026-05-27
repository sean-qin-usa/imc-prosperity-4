from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import shlex
import sys
import types
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

os.environ.setdefault("XDG_CACHE_HOME", "/tmp/prosperity_cache")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/prosperity_mpl")

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

Symbol = str
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_ROOT = REPO_ROOT / "data"
# Store backtests at the prosperity workspace root to avoid bloating IMCP2026.
DEFAULT_OUTPUT_ROOT = REPO_ROOT.parent / "gen" / "backtests"
DEFAULT_EXCHANGE_CALIBRATION_PATH = (
    REPO_ROOT / "tools" / "calibrations" / "combined_official_passive_profile.json"
)
if not DEFAULT_EXCHANGE_CALIBRATION_PATH.exists():
    DEFAULT_EXCHANGE_CALIBRATION_PATH = (
        REPO_ROOT / "tools" / "calibrations" / "round1_official_passive_fills.json"
    )


@dataclass
class Listing:
    symbol: Symbol
    product: str
    denomination: str


@dataclass
class Observation:
    plainValueObservations: Dict[str, float] = field(default_factory=dict)
    conversionObservations: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Order:
    symbol: Symbol
    price: int
    quantity: int


@dataclass
class OrderDepth:
    buy_orders: Dict[int, int] = field(default_factory=dict)
    sell_orders: Dict[int, int] = field(default_factory=dict)


@dataclass
class Trade:
    symbol: Symbol
    price: int
    quantity: int
    buyer: str = ""
    seller: str = ""
    timestamp: int = 0


@dataclass
class TradingState:
    traderData: str
    timestamp: int
    listings: Dict[str, Listing]
    order_depths: Dict[str, OrderDepth]
    own_trades: Dict[str, List[Trade]]
    market_trades: Dict[str, List[Trade]]
    position: Dict[str, int]
    observations: Observation


class ProsperityEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if is_dataclass(obj):
            return asdict(obj)
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return super().default(obj)


def install_datamodel_shim() -> None:
    if "datamodel" in sys.modules:
        return

    module = types.ModuleType("datamodel")
    module.Symbol = Symbol
    module.Listing = Listing
    module.Observation = Observation
    module.Order = Order
    module.OrderDepth = OrderDepth
    module.Trade = Trade
    module.TradingState = TradingState
    module.ProsperityEncoder = ProsperityEncoder
    module.__all__ = [
        "Symbol",
        "Listing",
        "Observation",
        "Order",
        "OrderDepth",
        "Trade",
        "TradingState",
        "ProsperityEncoder",
    ]
    sys.modules["datamodel"] = module


@dataclass
class MarketDataset:
    name: str
    prices: pd.DataFrame
    trades: pd.DataFrame
    source: Path


@dataclass
class FillEvent:
    dataset: str
    day: int
    timestamp: int
    symbol: str
    side: str
    quantity: int
    price: int
    liquidity: str
    order_price: int


@dataclass
class OrderResult:
    requested_qty: int
    executed_qty: int
    remaining_qty: int
    immediate_qty: int
    passive_qty: int
    fill_count: int


@dataclass
class ProductLedger:
    symbol: str
    limit: int
    position: int = 0
    cash: float = 0.0
    realized_pnl: float = 0.0
    avg_cost: float = 0.0
    turnover: float = 0.0
    fills: int = 0

    def apply_fill(self, signed_qty: int, price: int) -> None:
        if signed_qty == 0:
            return

        self.cash -= signed_qty * price
        self.turnover += abs(signed_qty * price)
        self.fills += 1

        pos = self.position
        qty = signed_qty

        if pos == 0 or pos * qty > 0:
            new_abs = abs(pos) + abs(qty)
            if new_abs > 0:
                if pos == 0:
                    self.avg_cost = float(price)
                else:
                    self.avg_cost = (
                        self.avg_cost * abs(pos) + float(price) * abs(qty)
                    ) / new_abs
            self.position = pos + qty
            return

        if pos > 0 and qty < 0:
            closing = min(pos, -qty)
            self.realized_pnl += closing * (price - self.avg_cost)
        elif pos < 0 and qty > 0:
            closing = min(-pos, qty)
            self.realized_pnl += closing * (self.avg_cost - price)

        new_pos = pos + qty
        if new_pos == 0:
            self.position = 0
            self.avg_cost = 0.0
            return

        if pos * new_pos > 0:
            self.position = new_pos
            return

        self.position = new_pos
        self.avg_cost = float(price)


@dataclass
class BacktestResult:
    dataset_name: str
    output_dir: Path
    summary: pd.DataFrame
    equity_curve: pd.DataFrame
    fills: pd.DataFrame
    orders: pd.DataFrame


def parse_day_from_name(path: Path) -> int:
    stem = path.stem
    marker = "day_"
    if marker not in stem:
        raise ValueError(f"Could not parse day from {path.name}")
    return int(stem.split(marker, 1)[1])


def read_prices_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=";")
    frame["day"] = frame["day"].astype(int)
    return frame


def read_trades_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=";")
    frame["day"] = parse_day_from_name(path)
    return frame


def _parse_snapshot_from_lambda_log(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and "order_depths" in payload:
            return payload
    except json.JSONDecodeError:
        payload = None

    candidate = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "order_depths" in payload:
            candidate = payload
    return candidate


def _coerce_book(value: Any) -> Optional[Dict[int, int]]:
    if isinstance(value, dict):
        return {int(price): int(qty) for price, qty in value.items() if int(qty) != 0}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return {int(price): int(qty) for price, qty in parsed.items() if int(qty) != 0}
    return None


def _infer_day_from_activities(raw: Optional[str]) -> int:
    if not raw:
        return 0
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("day;"):
            continue
        try:
            return int(line.split(";", 1)[0])
        except ValueError:
            break
    return 0


def build_prices_from_snapshots(
    snapshots: Sequence[Dict[str, Any]],
    default_day: int,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for snapshot in snapshots:
        ts = int(snapshot.get("ts", snapshot.get("timestamp", 0)))
        observations = snapshot.get("observations", {})
        for symbol, depth in (snapshot.get("order_depths") or {}).items():
            buy = _coerce_book(depth.get("buy")) or {}
            sell = _coerce_book(depth.get("sell")) or {}

            bid_levels = sorted(buy.items(), key=lambda item: item[0], reverse=True)
            ask_levels = sorted(sell.items(), key=lambda item: item[0])

            row: Dict[str, Any] = {
                "day": int(default_day),
                "timestamp": ts,
                "product": str(symbol),
                "book_buy": buy,
                "book_sell": sell,
                "observations": observations,
            }

            for level in range(3):
                if level < len(bid_levels):
                    price, volume = bid_levels[level]
                    row[f"bid_price_{level + 1}"] = int(price)
                    row[f"bid_volume_{level + 1}"] = abs(int(volume))
                else:
                    row[f"bid_price_{level + 1}"] = None
                    row[f"bid_volume_{level + 1}"] = None

                if level < len(ask_levels):
                    price, volume = ask_levels[level]
                    row[f"ask_price_{level + 1}"] = int(price)
                    row[f"ask_volume_{level + 1}"] = abs(int(volume))
                else:
                    row[f"ask_price_{level + 1}"] = None
                    row[f"ask_volume_{level + 1}"] = None

            best_bid = bid_levels[0][0] if bid_levels else None
            best_ask = ask_levels[0][0] if ask_levels else None
            if best_bid is None and best_ask is None:
                mid_price = np.nan
            elif best_bid is None:
                mid_price = float(best_ask)
            elif best_ask is None:
                mid_price = float(best_bid)
            else:
                mid_price = (float(best_bid) + float(best_ask)) / 2.0
            row["mid_price"] = mid_price
            rows.append(row)

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["day"] = frame["day"].astype(int)
    frame["timestamp"] = frame["timestamp"].astype(int)
    frame = frame.sort_values(["day", "timestamp", "product"]).drop_duplicates(
        subset=["day", "timestamp", "product"], keep="last"
    )
    return sanitize_prices_frame(frame)


def sanitize_prices_frame(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return prices

    frame = prices.copy()
    bid_cols = [f"bid_price_{level}" for level in range(1, 4) if f"bid_price_{level}" in frame.columns]
    ask_cols = [f"ask_price_{level}" for level in range(1, 4) if f"ask_price_{level}" in frame.columns]

    has_bid = frame[bid_cols].notna().any(axis=1) if bid_cols else pd.Series(False, index=frame.index)
    has_ask = frame[ask_cols].notna().any(axis=1) if ask_cols else pd.Series(False, index=frame.index)

    best_bid = frame["bid_price_1"] if "bid_price_1" in frame.columns else pd.Series(np.nan, index=frame.index)
    best_ask = frame["ask_price_1"] if "ask_price_1" in frame.columns else pd.Series(np.nan, index=frame.index)

    computed_mid = pd.Series(np.nan, index=frame.index, dtype=float)
    both = has_bid & has_ask
    computed_mid.loc[both] = (best_bid.loc[both].astype(float) + best_ask.loc[both].astype(float)) / 2.0
    computed_mid.loc[has_bid & ~has_ask] = best_bid.loc[has_bid & ~has_ask].astype(float)
    computed_mid.loc[~has_bid & has_ask] = best_ask.loc[~has_bid & has_ask].astype(float)

    if "mid_price" not in frame.columns:
        frame["mid_price"] = computed_mid
    else:
        bad_mid = frame["mid_price"].isna() | (frame["mid_price"].astype(float) <= 0.0)
        frame.loc[bad_mid, "mid_price"] = computed_mid.loc[bad_mid]

    frame["mid_price"] = frame.groupby(["day", "product"])["mid_price"].transform(
        lambda series: series.ffill().bfill()
    )
    return frame


def load_exchange_calibration(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise TypeError(f"Exchange calibration must be a JSON object: {path}")
    return payload


def load_csv_bundle(directory: Path) -> Optional[MarketDataset]:
    price_files = sorted(directory.glob("prices_round_*.csv"))
    trade_files = sorted(directory.glob("trades_round_*.csv"))
    if not price_files:
        return None

    prices = pd.concat([read_prices_csv(path) for path in price_files], ignore_index=True)
    if trade_files:
        trades = pd.concat([read_trades_csv(path) for path in trade_files], ignore_index=True)
    else:
        trades = pd.DataFrame(columns=["timestamp", "buyer", "seller", "symbol", "currency", "price", "quantity", "day"])

    prices = prices.sort_values(["day", "timestamp", "product"]).reset_index(drop=True)
    prices = sanitize_prices_frame(prices)
    trades = trades.sort_values(["day", "timestamp", "symbol"]).reset_index(drop=True)
    return MarketDataset(
        name=f"{directory.name}_csv",
        prices=prices,
        trades=trades,
        source=directory,
    )


def load_run_log(path: Path) -> MarketDataset:
    payload = json.loads(path.read_text())

    snapshots: List[Dict[str, Any]] = []
    if isinstance(payload.get("logs"), list):
        for entry in payload.get("logs", []):
            snapshot = _parse_snapshot_from_lambda_log(entry.get("lambdaLog", ""))
            if snapshot is not None:
                snapshots.append(snapshot)

    prices: pd.DataFrame
    if snapshots:
        default_day = _infer_day_from_activities(payload.get("activitiesLog"))
        prices = build_prices_from_snapshots(snapshots, default_day=default_day)
        if prices.empty and "activitiesLog" in payload:
            prices = pd.read_csv(StringIO(payload["activitiesLog"]), sep=";")
            prices["day"] = prices["day"].astype(int)
    else:
        prices = pd.read_csv(StringIO(payload["activitiesLog"]), sep=";")
        prices["day"] = prices["day"].astype(int)

    raw_trades = payload.get("tradeHistory", [])
    trades = pd.DataFrame(raw_trades)
    if trades.empty:
        trades = pd.DataFrame(columns=["timestamp", "buyer", "seller", "symbol", "currency", "price", "quantity"])

    if "day" not in trades.columns:
        inferred_day = int(prices["day"].mode().iloc[0])
        trades["day"] = inferred_day
    trades["currency"] = trades.get("currency", pd.Series(["XIRECS"] * len(trades)))
    trades["buyer"] = trades.get("buyer", pd.Series([""] * len(trades)))
    trades["seller"] = trades.get("seller", pd.Series([""] * len(trades)))

    trades = trades[["timestamp", "buyer", "seller", "symbol", "currency", "price", "quantity", "day"]]
    prices = prices.sort_values(["day", "timestamp", "product"]).reset_index(drop=True)
    prices = sanitize_prices_frame(prices)
    trades = trades.sort_values(["day", "timestamp", "symbol"]).reset_index(drop=True)
    return MarketDataset(name=path.stem, prices=prices, trades=trades, source=path)


def filter_market_trades(frame: pd.DataFrame, mode: str) -> pd.DataFrame:
    if mode == "all":
        return frame
    if mode == "none":
        return frame.iloc[0:0]
    # external-only: drop trades that involve the submission (buyer or seller tagged)
    if frame.empty:
        return frame
    buyer = frame.get("buyer")
    seller = frame.get("seller")
    if buyer is None or seller is None:
        return frame
    mask = ~buyer.astype(str).str.contains("SUBMISSION", na=False) & ~seller.astype(str).str.contains("SUBMISSION", na=False)
    return frame.loc[mask]


def discover_datasets(input_paths: Sequence[Path]) -> List[MarketDataset]:
    datasets: List[MarketDataset] = []

    for path in input_paths:
        if path.is_file() and path.suffix.lower() in {".json", ".log"}:
            datasets.append(load_run_log(path))
            continue

        if path.is_dir():
            run_candidates: Dict[str, Path] = {}
            candidate_dirs = [path] + [
                child
                for child in sorted(path.rglob("*"))
                if child.is_dir() and child.name != "__pycache__"
            ]

            for directory in candidate_dirs:
                csv_bundle = load_csv_bundle(directory)
                if csv_bundle is not None:
                    datasets.append(csv_bundle)

                for log_path in sorted(directory.glob("*.log")):
                    run_candidates[log_path.stem] = log_path
                for json_path in sorted(directory.glob("*.json")):
                    run_candidates.setdefault(json_path.stem, json_path)

            for run_path in run_candidates.values():
                datasets.append(load_run_log(run_path))
            continue

        raise FileNotFoundError(f"Unsupported input path: {path}")

    unique: Dict[str, MarketDataset] = {}
    for dataset in datasets:
        unique[dataset.name] = dataset
    return list(unique.values())


def select_default_datasets(datasets: Sequence[MarketDataset]) -> List[MarketDataset]:
    benchmark_data_markers = ("benchmark_data_day_", "benchmark_day_")
    benchmark_datasets = [
        dataset
        for dataset in datasets
        if any(marker in str(dataset.source) for marker in benchmark_data_markers)
    ]
    if benchmark_datasets:
        return benchmark_datasets

    preferred_names = {"77832"}
    named_datasets = [dataset for dataset in datasets if dataset.name in preferred_names]
    if named_datasets:
        return named_datasets

    return list(datasets)


def safe_int(value: Any) -> Optional[int]:
    if pd.isna(value):
        return None
    return int(value)


def extract_levels(row: pd.Series, side: str) -> List[Tuple[int, int]]:
    book_key = "book_buy" if side == "bid" else "book_sell"
    book = _coerce_book(row.get(book_key))
    if book:
        levels = [(int(price), abs(int(volume))) for price, volume in book.items()]
        if side == "bid":
            levels.sort(key=lambda item: item[0], reverse=True)
        else:
            levels.sort(key=lambda item: item[0])
        return levels

    levels: List[Tuple[int, int]] = []
    for level in (1, 2, 3):
        price = safe_int(row.get(f"{side}_price_{level}"))
        volume = safe_int(row.get(f"{side}_volume_{level}"))
        if price is None or volume is None:
            continue
        levels.append((price, abs(volume)))

    if side == "bid":
        levels.sort(key=lambda item: item[0], reverse=True)
    else:
        levels.sort(key=lambda item: item[0])
    return levels


def build_order_depth(row: pd.Series) -> OrderDepth:
    book_buy = _coerce_book(row.get("book_buy"))
    book_sell = _coerce_book(row.get("book_sell"))
    if book_buy is not None or book_sell is not None:
        bids = book_buy or {}
        asks = book_sell or {}
        return OrderDepth(buy_orders=bids, sell_orders=asks)

    bids = {price: volume for price, volume in extract_levels(row, "bid")}
    asks = {price: -volume for price, volume in extract_levels(row, "ask")}
    return OrderDepth(buy_orders=bids, sell_orders=asks)


def same_price_volume(levels: Sequence[Tuple[int, int]], price: int) -> int:
    return sum(volume for level_price, volume in levels if level_price == price)


def visible_cross_volume(levels: Sequence[Tuple[int, int]], side: str, limit_price: int) -> int:
    if side == "buy":
        return sum(volume for price, volume in levels if price <= limit_price)
    return sum(volume for price, volume in levels if price >= limit_price)


def order_is_improving(side: str, limit_price: int, best_bid: int, best_ask: int) -> bool:
    if side == "buy":
        return best_bid < limit_price < best_ask
    return best_bid < limit_price < best_ask


def deterministic_uniform(*parts: Any) -> float:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) / float(2**64)


def inside_spread_size_bucket(requested_qty: int) -> str:
    qty = max(1, int(requested_qty))
    if qty <= 4:
        return "le_4"
    if qty <= 12:
        return "5_12"
    return "gt_12"


def inside_spread_distance_ticks(side: str, limit_price: int, best_bid: int, best_ask: int) -> int:
    if side == "buy":
        return max(0, int(limit_price) - int(best_bid))
    return max(0, int(best_ask) - int(limit_price))


def _calibration_stats(config: Optional[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
    if not config:
        return None
    if "hit_probability" not in config and "fill_ratio" not in config:
        return None
    hit_probability = max(0.0, float(config.get("hit_probability", 0.0)))
    fill_ratio = max(0.0, float(config.get("fill_ratio", 0.0)))
    return hit_probability, fill_ratio


def inside_spread_fill_params(
    exchange_calibration: Dict[str, Any],
    symbol: str,
    spread: int,
    side: str,
    requested_qty: int,
    distance_ticks: int,
) -> Tuple[float, float]:
    inside = exchange_calibration.get("inside_spread", {})
    symbol_config = inside.get(symbol, {})
    spread_config = symbol_config.get("spreads", {}).get(str(int(spread)), {})
    size_bucket = inside_spread_size_bucket(requested_qty)
    distance_key = str(max(0, int(distance_ticks)))

    spread_side = spread_config.get("sides", {}).get(side, {})
    symbol_side = symbol_config.get("sides", {}).get(side, {})

    candidates = [
        spread_side.get("distances", {}).get(distance_key),
        spread_side.get("size_buckets", {}).get(size_bucket),
        spread_side,
        spread_config.get("distances", {}).get(distance_key),
        spread_config.get("size_buckets", {}).get(size_bucket),
        spread_config,
        symbol_side.get("distances", {}).get(distance_key),
        symbol_side.get("size_buckets", {}).get(size_bucket),
        symbol_side,
        symbol_config.get("distances", {}).get(distance_key),
        symbol_config.get("size_buckets", {}).get(size_bucket),
        symbol_config,
    ]

    for candidate in candidates:
        stats = _calibration_stats(candidate)
        if stats is not None:
            return stats

    hit_probability = max(0.0, float(symbol_config.get("default_hit_probability", 0.0)))
    fill_ratio = max(0.0, float(symbol_config.get("default_fill_ratio", 0.0)))
    return hit_probability, fill_ratio


def normalize_strategy_response(response: Any) -> Tuple[Dict[str, List[Order]], int, str]:
    if isinstance(response, tuple):
        if len(response) == 3:
            orders, conversions, trader_data = response
            return orders, int(conversions), str(trader_data)
        if len(response) == 2:
            orders, conversions = response
            return orders, int(conversions), ""
        if len(response) == 1:
            return response[0], 0, ""
    if isinstance(response, dict):
        return response, 0, ""
    raise TypeError(f"Unsupported strategy response: {type(response)!r}")


def load_strategy_class(strategy_path: Path):
    install_datamodel_shim()
    module_name = f"strategy_{strategy_path.stem}_{hashlib.sha1(str(strategy_path).encode()).hexdigest()[:8]}"
    spec = importlib.util.spec_from_file_location(module_name, strategy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not import strategy from {strategy_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "Trader"):
        raise AttributeError(f"{strategy_path} does not define Trader")
    return module.Trader


def infer_position_limits(trader_class: Any, symbols: Iterable[str]) -> Dict[str, int]:
    for attr in ("POSITION_LIMITS", "LIMITS"):
        raw = getattr(trader_class, attr, None)
        if isinstance(raw, dict):
            return {str(key): int(value) for key, value in raw.items()}
    return {symbol: 10**9 for symbol in symbols}


def build_state(
    tick_rows: pd.DataFrame,
    timestamp: int,
    trader_data: str,
    positions: Dict[str, int],
    own_trades: Dict[str, List[Trade]],
    market_trades: Dict[str, List[Trade]],
) -> TradingState:
    order_depths: Dict[str, OrderDepth] = {}
    listings: Dict[str, Listing] = {}
    observations = Observation()

    for row in tick_rows.itertuples(index=False):
        row_series = pd.Series(row._asdict())
        symbol = str(row_series["product"])
        order_depths[symbol] = build_order_depth(row_series)
        listings[symbol] = Listing(symbol=symbol, product=symbol, denomination="XIRECS")

        if "observations" in row_series and observations == Observation():
            raw_obs = row_series.get("observations")
            if isinstance(raw_obs, dict):
                observations = Observation(
                    plainValueObservations=dict(raw_obs.get("plainValueObservations", {})),
                    conversionObservations=dict(raw_obs.get("conversionObservations", {})),
                )

    return TradingState(
        traderData=trader_data,
        timestamp=int(timestamp),
        listings=listings,
        order_depths=order_depths,
        own_trades=own_trades,
        market_trades=market_trades,
        position=dict(positions),
        observations=observations,
    )


def capacity_for_fill(position: int, limit: int, side: str) -> int:
    if side == "buy":
        return max(0, limit - position)
    return max(0, limit + position)


def product_orders_within_limits(position: int, limit: int, orders: Sequence[Order]) -> bool:
    buy_qty = sum(max(0, int(order.quantity)) for order in orders)
    sell_qty = sum(max(0, -int(order.quantity)) for order in orders)
    return position + buy_qty <= limit and position - sell_qty >= -limit


def execute_fill(
    ledger: ProductLedger,
    dataset_name: str,
    day: int,
    timestamp: int,
    side: str,
    quantity: int,
    price: int,
    liquidity: str,
    order_price: int,
) -> FillEvent:
    signed_qty = quantity if side == "buy" else -quantity
    ledger.apply_fill(signed_qty, price)
    return FillEvent(
        dataset=dataset_name,
        day=day,
        timestamp=timestamp,
        symbol=ledger.symbol,
        side=side,
        quantity=quantity,
        price=price,
        liquidity=liquidity,
        order_price=order_price,
    )


def trade_matches_quote(side: str, trade_price: int, order_price: int, mode: str) -> bool:
    if mode == "none":
        return False

    if side == "buy":
        if mode == "all":
            return trade_price <= order_price
        return trade_price < order_price

    if mode == "all":
        return trade_price >= order_price
    return trade_price > order_price


def simulate_order_same_tick(
    dataset_name: str,
    day: int,
    current_timestamp: int,
    order: Order,
    current_row: pd.Series,
    current_market_trades: pd.DataFrame,
    ledger: ProductLedger,
    match_trades: str,
    trade_fill_price: str,
) -> Tuple[OrderResult, List[FillEvent]]:
    side = "buy" if int(order.quantity) > 0 else "sell"
    remaining = abs(int(order.quantity))
    order_price = int(order.price)
    fills: List[FillEvent] = []
    visible_qty = 0
    trade_qty = 0

    bid_levels = extract_levels(current_row, "bid")
    ask_levels = extract_levels(current_row, "ask")

    if side == "buy":
        for ask_price, ask_volume in ask_levels:
            if ask_price > order_price or remaining <= 0:
                break
            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, ask_volume, allowed)
            if fill_qty <= 0:
                break
            fills.append(
                execute_fill(
                    ledger,
                    dataset_name,
                    day,
                    current_timestamp,
                    side,
                    fill_qty,
                    ask_price,
                    "take_visible",
                    order_price,
                )
            )
            remaining -= fill_qty
            visible_qty += fill_qty
    else:
        for bid_price, bid_volume in bid_levels:
            if bid_price < order_price or remaining <= 0:
                break
            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, bid_volume, allowed)
            if fill_qty <= 0:
                break
            fills.append(
                execute_fill(
                    ledger,
                    dataset_name,
                    day,
                    current_timestamp,
                    side,
                    fill_qty,
                    bid_price,
                    "take_visible",
                    order_price,
                )
            )
            remaining -= fill_qty
            visible_qty += fill_qty

    if remaining > 0 and match_trades != "none" and not current_market_trades.empty:
        for trade_row in current_market_trades.sort_values("timestamp").itertuples(index=False):
            trade_price = int(trade_row.price)
            trade_size = int(trade_row.quantity)
            if not trade_matches_quote(side, trade_price, order_price, match_trades):
                continue

            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, trade_size, allowed)
            if fill_qty <= 0:
                break

            fill_price = order_price if trade_fill_price == "order" else trade_price
            fills.append(
                execute_fill(
                    ledger,
                    dataset_name,
                    day,
                    current_timestamp,
                    side,
                    fill_qty,
                    fill_price,
                    "market_trade",
                    order_price,
                )
            )
            remaining -= fill_qty
            trade_qty += fill_qty
            if remaining <= 0:
                break

    return (
        OrderResult(
            requested_qty=abs(int(order.quantity)),
            executed_qty=visible_qty + trade_qty,
            remaining_qty=remaining,
            immediate_qty=visible_qty,
            passive_qty=trade_qty,
            fill_count=len(fills),
        ),
        fills,
    )


def simulate_order_official_hybrid(
    dataset_name: str,
    day: int,
    current_timestamp: int,
    next_timestamp: Optional[int],
    order: Order,
    current_row: pd.Series,
    next_row: Optional[pd.Series],
    current_market_trades: pd.DataFrame,
    ledger: ProductLedger,
    queue_alpha: float,
    fill_on_disappear: str,
    exchange_calibration: Dict[str, Any],
) -> Tuple[OrderResult, List[FillEvent]]:
    side = "buy" if int(order.quantity) > 0 else "sell"
    requested_qty = abs(int(order.quantity))
    remaining = requested_qty
    order_price = int(order.price)
    fills: List[FillEvent] = []
    immediate_qty = 0
    passive_qty = 0

    bid_levels = extract_levels(current_row, "bid")
    ask_levels = extract_levels(current_row, "ask")
    best_bid = bid_levels[0][0] if bid_levels else -10**9
    best_ask = ask_levels[0][0] if ask_levels else 10**9

    if side == "buy":
        for ask_price, ask_volume in ask_levels:
            if ask_price > order_price or remaining <= 0:
                break
            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, ask_volume, allowed)
            if fill_qty <= 0:
                break
            fills.append(
                execute_fill(
                    ledger,
                    dataset_name,
                    day,
                    current_timestamp,
                    side,
                    fill_qty,
                    ask_price,
                    "take_visible",
                    order_price,
                )
            )
            remaining -= fill_qty
            immediate_qty += fill_qty
    else:
        for bid_price, bid_volume in bid_levels:
            if bid_price < order_price or remaining <= 0:
                break
            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, bid_volume, allowed)
            if fill_qty <= 0:
                break
            fills.append(
                execute_fill(
                    ledger,
                    dataset_name,
                    day,
                    current_timestamp,
                    side,
                    fill_qty,
                    bid_price,
                    "take_visible",
                    order_price,
                )
            )
            remaining -= fill_qty
            immediate_qty += fill_qty

    if remaining <= 0:
        return (
            OrderResult(
                requested_qty=requested_qty,
                executed_qty=immediate_qty,
                remaining_qty=remaining,
                immediate_qty=immediate_qty,
                passive_qty=0,
                fill_count=len(fills),
            ),
            fills,
        )

    is_inside_spread = order_is_improving(side, order_price, best_bid, best_ask)
    spread = best_ask - best_bid if best_bid > -10**8 and best_ask < 10**8 else 0

    if is_inside_spread:
        distance_ticks = inside_spread_distance_ticks(side, order_price, best_bid, best_ask)
        hit_probability, fill_ratio = inside_spread_fill_params(
            exchange_calibration,
            ledger.symbol,
            spread,
            side,
            requested_qty,
            distance_ticks,
        )
        if hit_probability > 0.0 and fill_ratio > 0.0:
            draw = deterministic_uniform(
                dataset_name,
                day,
                current_timestamp,
                ledger.symbol,
                side,
                order_price,
                requested_qty,
            )
            if draw < hit_probability:
                allowed = capacity_for_fill(ledger.position, ledger.limit, side)
                target_qty = int(round(requested_qty * fill_ratio))
                fill_qty = min(remaining, target_qty, allowed)
                if fill_qty > 0:
                    fills.append(
                        execute_fill(
                            ledger,
                            dataset_name,
                            day,
                            current_timestamp,
                            side,
                            fill_qty,
                            order_price,
                            "passive_calibrated",
                            order_price,
                        )
                    )
                    remaining -= fill_qty
                    passive_qty += fill_qty
    else:
        queue_ahead = -1
        if side == "buy" and order_price == best_bid:
            queue_ahead = int(math.ceil(same_price_volume(bid_levels, order_price) * queue_alpha))
        elif side == "sell" and order_price == best_ask:
            queue_ahead = int(math.ceil(same_price_volume(ask_levels, order_price) * queue_alpha))

        if queue_ahead >= 0 and current_market_trades is not None and not current_market_trades.empty:
            for trade_row in current_market_trades.sort_values("timestamp").itertuples(index=False):
                if remaining <= 0:
                    break
                trade_price = int(trade_row.price)
                trade_qty = int(trade_row.quantity)
                if trade_price != order_price:
                    continue
                if queue_ahead > 0:
                    consumed = min(queue_ahead, trade_qty)
                    queue_ahead -= consumed
                    trade_qty -= consumed
                if trade_qty <= 0:
                    continue
                allowed = capacity_for_fill(ledger.position, ledger.limit, side)
                fill_qty = min(remaining, trade_qty, allowed)
                if fill_qty <= 0:
                    break
                fills.append(
                    execute_fill(
                        ledger,
                        dataset_name,
                        day,
                        current_timestamp,
                        side,
                        fill_qty,
                        order_price,
                        "passive_tape",
                        order_price,
                    )
                )
                remaining -= fill_qty
                passive_qty += fill_qty

    return (
        OrderResult(
            requested_qty=requested_qty,
            executed_qty=immediate_qty + passive_qty,
            remaining_qty=remaining,
            immediate_qty=immediate_qty,
            passive_qty=passive_qty,
            fill_count=len(fills),
        ),
        fills,
    )


def simulate_order(
    dataset_name: str,
    day: int,
    current_timestamp: int,
    next_timestamp: Optional[int],
    symbol: str,
    order: Order,
    current_row: pd.Series,
    next_row: Optional[pd.Series],
    interval_trades: pd.DataFrame,
    ledger: ProductLedger,
    queue_alpha: float,
    trade_fill_price: str,
) -> Tuple[OrderResult, List[FillEvent]]:
    side = "buy" if int(order.quantity) > 0 else "sell"
    remaining = abs(int(order.quantity))
    order_price = int(order.price)
    fills: List[FillEvent] = []
    immediate_qty = 0
    passive_qty = 0

    bid_levels = extract_levels(current_row, "bid")
    ask_levels = extract_levels(current_row, "ask")
    best_bid = bid_levels[0][0] if bid_levels else -10**9
    best_ask = ask_levels[0][0] if ask_levels else 10**9

    if side == "buy":
        for ask_price, ask_volume in ask_levels:
            if ask_price > order_price or remaining <= 0:
                break
            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, ask_volume, allowed)
            if fill_qty <= 0:
                break
            fills.append(
                execute_fill(
                    ledger,
                    dataset_name,
                    day,
                    current_timestamp,
                    side,
                    fill_qty,
                    ask_price,
                    "take_visible",
                    order_price,
                )
            )
            remaining -= fill_qty
            immediate_qty += fill_qty
    else:
        for bid_price, bid_volume in bid_levels:
            if bid_price < order_price or remaining <= 0:
                break
            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, bid_volume, allowed)
            if fill_qty <= 0:
                break
            fills.append(
                execute_fill(
                    ledger,
                    dataset_name,
                    day,
                    current_timestamp,
                    side,
                    fill_qty,
                    bid_price,
                    "take_visible",
                    order_price,
                )
            )
            remaining -= fill_qty
            immediate_qty += fill_qty

    if remaining <= 0:
        return (
            OrderResult(
                requested_qty=abs(int(order.quantity)),
                executed_qty=immediate_qty,
                remaining_qty=0,
                immediate_qty=immediate_qty,
                passive_qty=0,
                fill_count=len(fills),
            ),
            fills,
        )

    if next_timestamp is None:
        return (
            OrderResult(
                requested_qty=abs(int(order.quantity)),
                executed_qty=immediate_qty,
                remaining_qty=remaining,
                immediate_qty=immediate_qty,
                passive_qty=0,
                fill_count=len(fills),
            ),
            fills,
        )

    queue_ahead = 0
    tape_fill_allowed = False

    if side == "buy":
        if order_price == best_bid:
            queue_ahead = int(math.ceil(same_price_volume(bid_levels, order_price) * queue_alpha))
            tape_fill_allowed = True
        elif order_is_improving(side, order_price, best_bid, best_ask):
            tape_fill_allowed = True
    else:
        if order_price == best_ask:
            queue_ahead = int(math.ceil(same_price_volume(ask_levels, order_price) * queue_alpha))
            tape_fill_allowed = True
        elif order_is_improving(side, order_price, best_bid, best_ask):
            tape_fill_allowed = True

    if tape_fill_allowed and not interval_trades.empty:
        for trade_row in interval_trades.sort_values("timestamp").itertuples(index=False):
            trade_price = int(trade_row.price)
            trade_qty = int(trade_row.quantity)
            if side == "buy" and trade_price > order_price:
                continue
            if side == "sell" and trade_price < order_price:
                continue

            if queue_ahead > 0:
                consumed = min(queue_ahead, trade_qty)
                queue_ahead -= consumed
                trade_qty -= consumed

            if trade_qty <= 0 or remaining <= 0:
                continue

            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, trade_qty, allowed)
            if fill_qty <= 0:
                break

            fill_price = order_price if trade_fill_price == "order" else trade_price
            fills.append(
                execute_fill(
                    ledger,
                    dataset_name,
                    day,
                    int(trade_row.timestamp),
                    side,
                    fill_qty,
                    fill_price,
                    "passive_tape",
                    order_price,
                )
            )
            remaining -= fill_qty
            passive_qty += fill_qty
            if remaining <= 0:
                break

    if remaining > 0 and next_row is not None:
        next_bid_levels = extract_levels(next_row, "bid")
        next_ask_levels = extract_levels(next_row, "ask")
        next_best_bid = next_bid_levels[0][0] if next_bid_levels else -10**9
        next_best_ask = next_ask_levels[0][0] if next_ask_levels else 10**9

        if side == "buy" and next_best_ask <= order_price:
            trade_volume = int(interval_trades.loc[interval_trades["price"] <= order_price, "quantity"].sum())
            visible_volume = visible_cross_volume(next_ask_levels, side, order_price)
            estimated = max(trade_volume, visible_volume)
            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, estimated, allowed)
            if fill_qty > 0:
                fills.append(
                    execute_fill(
                        ledger,
                        dataset_name,
                        day,
                        next_timestamp,
                        side,
                        fill_qty,
                        order_price,
                        "passive_cross",
                        order_price,
                    )
                )
                remaining -= fill_qty
                passive_qty += fill_qty

        if side == "sell" and next_best_bid >= order_price:
            trade_volume = int(interval_trades.loc[interval_trades["price"] >= order_price, "quantity"].sum())
            visible_volume = visible_cross_volume(next_bid_levels, side, order_price)
            estimated = max(trade_volume, visible_volume)
            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, estimated, allowed)
            if fill_qty > 0:
                fills.append(
                    execute_fill(
                        ledger,
                        dataset_name,
                        day,
                        next_timestamp,
                        side,
                        fill_qty,
                        order_price,
                        "passive_cross",
                        order_price,
                    )
                )
                remaining -= fill_qty
                passive_qty += fill_qty

    return (
        OrderResult(
            requested_qty=abs(int(order.quantity)),
            executed_qty=immediate_qty + passive_qty,
            remaining_qty=remaining,
            immediate_qty=immediate_qty,
            passive_qty=passive_qty,
            fill_count=len(fills),
        ),
        fills,
    )


def simulate_order_book_delta(
    dataset_name: str,
    day: int,
    current_timestamp: int,
    next_timestamp: Optional[int],
    order: Order,
    current_row: pd.Series,
    next_row: Optional[pd.Series],
    ledger: ProductLedger,
    queue_alpha: float,
    fill_on_disappear: str,
) -> Tuple[OrderResult, List[FillEvent]]:
    side = "buy" if int(order.quantity) > 0 else "sell"
    remaining = abs(int(order.quantity))
    order_price = int(order.price)
    fills: List[FillEvent] = []
    immediate_qty = 0
    passive_qty = 0

    bid_levels = extract_levels(current_row, "bid")
    ask_levels = extract_levels(current_row, "ask")
    best_bid = bid_levels[0][0] if bid_levels else -10**9
    best_ask = ask_levels[0][0] if ask_levels else 10**9

    if side == "buy":
        for ask_price, ask_volume in ask_levels:
            if ask_price > order_price or remaining <= 0:
                break
            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, ask_volume, allowed)
            if fill_qty <= 0:
                break
            fills.append(
                execute_fill(
                    ledger,
                    dataset_name,
                    day,
                    current_timestamp,
                    side,
                    fill_qty,
                    ask_price,
                    "take_visible",
                    order_price,
                )
            )
            remaining -= fill_qty
            immediate_qty += fill_qty
    else:
        for bid_price, bid_volume in bid_levels:
            if bid_price < order_price or remaining <= 0:
                break
            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, bid_volume, allowed)
            if fill_qty <= 0:
                break
            fills.append(
                execute_fill(
                    ledger,
                    dataset_name,
                    day,
                    current_timestamp,
                    side,
                    fill_qty,
                    bid_price,
                    "take_visible",
                    order_price,
                )
            )
            remaining -= fill_qty
            immediate_qty += fill_qty

    if remaining <= 0 or next_timestamp is None or next_row is None:
        return (
            OrderResult(
                requested_qty=abs(int(order.quantity)),
                executed_qty=immediate_qty,
                remaining_qty=remaining,
                immediate_qty=immediate_qty,
                passive_qty=0,
                fill_count=len(fills),
            ),
            fills,
        )

    # Passive fills inferred from book deltas at our price level.
    next_bid_levels = extract_levels(next_row, "bid")
    next_ask_levels = extract_levels(next_row, "ask")
    next_best_bid = next_bid_levels[0][0] if next_bid_levels else -10**9
    next_best_ask = next_ask_levels[0][0] if next_ask_levels else 10**9

    queue_ahead = 0
    eligible = False

    if side == "buy":
        if order_price == best_bid:
            queue_ahead = int(math.ceil(same_price_volume(bid_levels, order_price) * queue_alpha))
            eligible = True
        elif order_is_improving(side, order_price, best_bid, best_ask):
            eligible = True
    else:
        if order_price == best_ask:
            queue_ahead = int(math.ceil(same_price_volume(ask_levels, order_price) * queue_alpha))
            eligible = True
        elif order_is_improving(side, order_price, best_bid, best_ask):
            eligible = True

    if eligible:
        current_vol = (
            same_price_volume(bid_levels, order_price)
            if side == "buy"
            else same_price_volume(ask_levels, order_price)
        )
        next_vol = (
            same_price_volume(next_bid_levels, order_price)
            if side == "buy"
            else same_price_volume(next_ask_levels, order_price)
        )

        if next_vol == 0 and current_vol > 0:
            if fill_on_disappear == "always":
                consumed = current_vol
            elif fill_on_disappear == "if-through":
                if side == "buy" and next_best_bid < order_price:
                    consumed = current_vol
                elif side == "sell" and next_best_ask > order_price:
                    consumed = current_vol
                else:
                    consumed = max(0, current_vol - next_vol)
            else:
                consumed = max(0, current_vol - next_vol)
        else:
            consumed = max(0, current_vol - next_vol)

        if queue_ahead > 0:
            consumed = max(0, consumed - queue_ahead)

        if consumed > 0:
            allowed = capacity_for_fill(ledger.position, ledger.limit, side)
            fill_qty = min(remaining, consumed, allowed)
            if fill_qty > 0:
                fills.append(
                    execute_fill(
                        ledger,
                        dataset_name,
                        day,
                        int(next_timestamp),
                        side,
                        fill_qty,
                        order_price,
                        "passive_book",
                        order_price,
                    )
                )
                remaining -= fill_qty
                passive_qty += fill_qty

    return (
        OrderResult(
            requested_qty=abs(int(order.quantity)),
            executed_qty=immediate_qty + passive_qty,
            remaining_qty=remaining,
            immediate_qty=immediate_qty,
            passive_qty=passive_qty,
            fill_count=len(fills),
        ),
        fills,
    )


def max_drawdown(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    running_max = series.cummax()
    drawdown = series - running_max
    return float(drawdown.min())


def slugify(value: str, max_length: int = 80) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        return "unknown"
    return slug[:max_length].rstrip("-._") or "unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_run_name(
    strategy_path: Path,
    datasets: Sequence[MarketDataset],
    fill_model: str,
    match_trades: str,
    run_name: Optional[str],
) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    strategy_slug = slugify(strategy_path.stem, max_length=40)
    dataset_slug = slugify("+".join(dataset.name for dataset in datasets), max_length=64)
    parts = [
        timestamp,
        strategy_slug,
        slugify(fill_model, max_length=20),
        slugify(match_trades, max_length=20),
        dataset_slug,
    ]
    if run_name:
        parts.append(slugify(run_name, max_length=48))
    return "__".join(parts)


def make_unique_run_dir(base_dir: Path, run_name: str) -> Path:
    candidate = base_dir / run_name
    suffix = 2
    while candidate.exists():
        candidate = base_dir / f"{run_name}__{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def write_latest_pointer(base_dir: Path, run_dir: Path) -> None:
    latest_txt = base_dir / "LATEST.txt"
    latest_txt.write_text(f"{run_dir}\n")

    latest_link = base_dir / "latest"
    if latest_link.exists() or latest_link.is_symlink():
        if latest_link.is_symlink() or latest_link.is_file():
            latest_link.unlink()
        else:
            return

    try:
        latest_link.symlink_to(run_dir.relative_to(base_dir), target_is_directory=True)
    except OSError:
        return


def write_run_status(run_dir: Path, status: str, details: Optional[str] = None) -> None:
    lines = [status]
    if details:
        lines.append(details)
    (run_dir / "STATUS.txt").write_text("\n".join(lines) + "\n")


def build_run_summary_frame(
    results: Sequence[BacktestResult],
    run_name: str,
    run_dir: Path,
    created_at: str,
    strategy_path: Path,
    fill_model: str,
    match_trades: str,
    queue_alpha: float,
    trade_fill_price: str,
    book_delta_on_disappear: str,
    market_trades_mode: str,
    fill_trades_mode: str,
    make_plots: bool,
    reuse_trader_instance: bool,
) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for result in results:
        if result.summary.empty:
            continue
        frame = result.summary.copy()
        frame.insert(0, "run_name", run_name)
        frame.insert(1, "created_at", created_at)
        frame.insert(2, "run_dir", str(run_dir))
        frame.insert(3, "strategy", str(strategy_path))
        frame.insert(4, "fill_model", fill_model)
        frame.insert(5, "match_trades", match_trades)
        frame.insert(6, "queue_alpha", queue_alpha)
        frame.insert(7, "trade_fill_price", trade_fill_price)
        frame.insert(8, "book_delta_on_disappear", book_delta_on_disappear)
        frame.insert(9, "market_trades", market_trades_mode)
        frame.insert(10, "fill_trades", fill_trades_mode)
        frame.insert(11, "plots_enabled", bool(make_plots))
        frame.insert(12, "reuse_trader_instance", bool(reuse_trader_instance))
        frames.append(frame)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def update_runs_index(base_dir: Path, run_summary: pd.DataFrame) -> None:
    if run_summary.empty:
        return

    index_path = base_dir / "index.csv"
    if index_path.exists():
        existing = pd.read_csv(index_path)
        combined = pd.concat([existing, run_summary], ignore_index=True, sort=False)
    else:
        combined = run_summary.copy()

    dedupe_cols = [column for column in ("run_name", "dataset", "day") if column in combined.columns]
    if dedupe_cols:
        combined = combined.drop_duplicates(subset=dedupe_cols, keep="last")
    combined.to_csv(index_path, index=False)


def write_run_manifest(
    run_dir: Path,
    run_name: str,
    created_at: str,
    strategy_path: Path,
    input_paths: Sequence[Path],
    datasets: Sequence[MarketDataset],
    args: argparse.Namespace,
    command: str,
    results: Sequence[BacktestResult],
    status: str,
) -> None:
    manifest = {
        "run_name": run_name,
        "status": status,
        "created_at": created_at,
        "run_dir": str(run_dir),
        "strategy": {
            "path": str(strategy_path),
            "sha256": sha256_file(strategy_path),
        },
        "inputs": [str(path) for path in input_paths],
        "datasets": [
            {
                "name": dataset.name,
                "source": str(dataset.source),
            }
            for dataset in datasets
        ],
        "options": {
            "fill_model": str(args.fill_model),
            "match_trades": str(args.match_trades),
            "queue_alpha": float(args.queue_alpha),
            "trade_fill_price": str(args.trade_fill_price),
            "book_delta_on_disappear": str(args.book_delta_on_disappear),
            "market_trades": str(args.market_trades),
            "fill_trades": str(args.fill_trades),
            "exchange_calibration": str(args.exchange_calibration) if args.exchange_calibration else None,
            "plots_enabled": not bool(args.no_plots),
            "reuse_trader_instance": bool(args.reuse_trader_instance),
            "dataset_filter": list(args.dataset) if args.dataset else None,
            "run_name": args.run_name,
        },
        "command": command,
        "outputs": {
            "run_summary_csv": str(run_dir / "run_summary.csv"),
            "index_csv": str(run_dir.parent / "index.csv"),
            "latest_txt": str(run_dir.parent / "LATEST.txt"),
            "datasets": {
                result.dataset_name: {
                    "directory": str(result.output_dir),
                    "summary_csv": str(result.output_dir / "summary.csv"),
                    "equity_curve_csv": str(result.output_dir / "equity_curve.csv"),
                    "orders_csv": str(result.output_dir / "orders.csv"),
                    "fills_csv": str(result.output_dir / "fills.csv"),
                    "report_html": str(result.output_dir / "report.html"),
                }
                for result in results
            },
        },
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2))


def write_html_report(output_dir: Path, summary: pd.DataFrame, images: Sequence[Path]) -> None:
    rows = summary.to_html(index=False, float_format=lambda value: f"{value:.2f}")
    image_html = "\n".join(
        f'<div><h3>{path.stem}</h3><img src="{path.name}" style="max-width: 100%; border: 1px solid #ccc;"></div>'
        for path in images
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Backtest Report</title>
  <style>
    body {{ font-family: Helvetica, Arial, sans-serif; margin: 24px; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: right; }}
    th {{ background: #f5f5f5; }}
    h1, h2, h3 {{ text-align: left; }}
  </style>
</head>
<body>
  <h1>Backtest Report</h1>
  <h2>Summary</h2>
  {rows}
  <h2>Charts</h2>
  {image_html}
</body>
</html>
"""
    (output_dir / "report.html").write_text(html)


def plot_equity_curve(equity: pd.DataFrame, output_path: Path, title: str) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    axes[0].plot(equity["step"], equity["total_pnl"], label="Total PnL", color="#1f77b4")
    axes[0].plot(equity["step"], equity["realized_pnl"], label="Realized PnL", color="#2ca02c")
    axes[0].plot(equity["step"], equity["unrealized_pnl"], label="Unrealized PnL", color="#ff7f0e")
    axes[0].set_ylabel("PnL")
    axes[0].set_title(title)
    axes[0].legend(loc="best")

    running_max = equity["total_pnl"].cummax()
    drawdown = equity["total_pnl"] - running_max
    axes[1].fill_between(equity["step"], drawdown, 0, color="#d62728", alpha=0.35)
    axes[1].set_xlabel("Simulation Step")
    axes[1].set_ylabel("Drawdown")
    axes[1].set_title("Drawdown")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_positions(equity: pd.DataFrame, output_path: Path, products: Sequence[str]) -> None:
    fig, axes = plt.subplots(len(products), 1, figsize=(12, 4 * max(1, len(products))), sharex=True)
    if len(products) == 1:
        axes = [axes]

    for ax, symbol in zip(axes, products):
        ax.plot(equity["step"], equity[f"position_{symbol}"], label=f"{symbol} position", color="#9467bd")
        ax.axhline(0, color="#666", linewidth=1)
        ax.set_ylabel("Position")
        ax.set_title(symbol)
        ax.legend(loc="best")

    axes[-1].set_xlabel("Simulation Step")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_symbol_market(equity: pd.DataFrame, fills: pd.DataFrame, symbol: str, output_path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    price_col = f"mid_{symbol}"
    pos_col = f"position_{symbol}"
    symbol_fills = fills[fills["symbol"] == symbol]

    axes[0].plot(equity["step"], equity[price_col], label="Mid price", color="#1f77b4")
    buy_fills = symbol_fills[symbol_fills["side"] == "buy"]
    sell_fills = symbol_fills[symbol_fills["side"] == "sell"]
    if not buy_fills.empty:
        axes[0].scatter(buy_fills["step"], buy_fills["price"], color="#2ca02c", s=24, label="Buy fills")
    if not sell_fills.empty:
        axes[0].scatter(sell_fills["step"], sell_fills["price"], color="#d62728", s=24, label="Sell fills")
    axes[0].set_ylabel("Price")
    axes[0].set_title(f"{symbol} market and fills")
    axes[0].legend(loc="best")

    axes[1].plot(equity["step"], equity[pos_col], color="#9467bd", label="Position")
    axes[1].axhline(0, color="#666", linewidth=1)
    axes[1].set_ylabel("Position")
    axes[1].set_xlabel("Simulation Step")
    axes[1].legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_order_activity(orders: pd.DataFrame, output_path: Path, title: str) -> None:
    if orders.empty:
        return

    activity = (
        orders.groupby("step")
        .agg(
            orders_submitted=("symbol", "size"),
            requested_qty=("requested_qty", "sum"),
            executed_qty=("executed_qty", "sum"),
            fill_count=("fill_count", "sum"),
            cancelled=("cancelled_by_limit", "sum"),
        )
        .reset_index()
        .sort_values("step")
    )
    activity["fill_rate"] = (
        activity["executed_qty"] / activity["requested_qty"].replace(0, np.nan)
    ).fillna(0.0)

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

    axes[0].bar(activity["step"], activity["orders_submitted"], color="#4C72B0", alpha=0.7, label="Orders")
    axes[0].plot(activity["step"], activity["fill_count"], color="#55A868", linewidth=1.5, label="Fills")
    axes[0].set_ylabel("Count")
    axes[0].set_title(title)
    axes[0].legend(loc="best")

    axes[1].plot(activity["step"], activity["requested_qty"], color="#C44E52", label="Requested qty")
    axes[1].plot(activity["step"], activity["executed_qty"], color="#8172B2", label="Executed qty")
    axes[1].set_ylabel("Quantity")
    axes[1].legend(loc="best")

    axes[2].plot(activity["step"], activity["fill_rate"], color="#64B5CD", label="Fill rate")
    axes[2].bar(activity["step"], activity["cancelled"], color="#CCB974", alpha=0.4, label="Cancelled by limit")
    axes[2].set_ylabel("Rate / Count")
    axes[2].set_xlabel("Simulation Step")
    axes[2].legend(loc="best")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_fill_activity(fills: pd.DataFrame, output_path: Path, title: str) -> None:
    if fills.empty:
        return

    frame = fills.copy()
    frame["notional"] = frame["quantity"] * frame["price"]
    frame["buy_qty"] = np.where(frame["side"] == "buy", frame["quantity"], 0)
    frame["sell_qty"] = np.where(frame["side"] == "sell", frame["quantity"], 0)

    step_activity = (
        frame.groupby("step")
        .agg(
            fill_count=("symbol", "size"),
            total_qty=("quantity", "sum"),
            buy_qty=("buy_qty", "sum"),
            sell_qty=("sell_qty", "sum"),
            notional=("notional", "sum"),
        )
        .reset_index()
        .sort_values("step")
    )
    step_activity["cum_notional"] = step_activity["notional"].cumsum()

    by_symbol = frame.groupby("symbol")["quantity"].sum().sort_values(ascending=False)
    by_liquidity = frame.groupby("liquidity")["quantity"].sum().sort_values(ascending=False)

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    axes[0, 0].bar(step_activity["step"], step_activity["fill_count"], color="#55A868")
    axes[0, 0].set_title(title)
    axes[0, 0].set_ylabel("Fill count")

    axes[0, 1].plot(step_activity["step"], step_activity["cum_notional"], color="#C44E52")
    axes[0, 1].set_title("Cumulative traded notional")
    axes[0, 1].set_ylabel("Notional")

    axes[1, 0].bar(by_symbol.index, by_symbol.values, color="#8172B2")
    axes[1, 0].set_title("Filled quantity by symbol")
    axes[1, 0].set_ylabel("Quantity")
    axes[1, 0].tick_params(axis="x", rotation=0)

    axes[1, 1].bar(by_liquidity.index, by_liquidity.values, color="#64B5CD")
    axes[1, 1].set_title("Filled quantity by liquidity")
    axes[1, 1].set_ylabel("Quantity")
    axes[1, 1].tick_params(axis="x", rotation=30)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_execution_summary(orders: pd.DataFrame, fills: pd.DataFrame, output_path: Path, title: str) -> None:
    if orders.empty:
        return

    order_summary = (
        orders.groupby("symbol")
        .agg(
            orders=("symbol", "size"),
            requested_qty=("requested_qty", "sum"),
            executed_qty=("executed_qty", "sum"),
            cancelled=("cancelled_by_limit", "sum"),
        )
        .reset_index()
    )
    order_summary["fill_rate"] = (
        order_summary["executed_qty"] / order_summary["requested_qty"].replace(0, np.nan)
    ).fillna(0.0)

    side_summary = (
        orders.groupby(["symbol", "side"])["requested_qty"]
        .sum()
        .unstack(fill_value=0)
        .reindex(columns=["buy", "sell"], fill_value=0)
    )

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    axes[0, 0].bar(order_summary["symbol"], order_summary["orders"], color="#4C72B0")
    axes[0, 0].set_title(title)
    axes[0, 0].set_ylabel("Orders submitted")

    width = 0.35
    x = np.arange(len(order_summary))
    axes[0, 1].bar(x - width / 2, order_summary["requested_qty"], width=width, color="#C44E52", label="Requested")
    axes[0, 1].bar(x + width / 2, order_summary["executed_qty"], width=width, color="#55A868", label="Executed")
    axes[0, 1].set_xticks(x)
    axes[0, 1].set_xticklabels(order_summary["symbol"])
    axes[0, 1].set_title("Requested vs executed quantity")
    axes[0, 1].set_ylabel("Quantity")
    axes[0, 1].legend(loc="best")

    axes[1, 0].bar(order_summary["symbol"], order_summary["fill_rate"], color="#64B5CD")
    axes[1, 0].bar(order_summary["symbol"], order_summary["cancelled"], color="#CCB974", alpha=0.35)
    axes[1, 0].set_title("Fill rate and limit cancellations")
    axes[1, 0].set_ylabel("Rate / Count")

    side_summary.plot(kind="bar", stacked=True, ax=axes[1, 1], color=["#2CA02C", "#D62728"])
    axes[1, 1].set_title("Requested quantity by side")
    axes[1, 1].set_ylabel("Quantity")
    axes[1, 1].tick_params(axis="x", rotation=0)

    if not fills.empty:
        fig.suptitle("Execution Summary", fontsize=14)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def run_backtest(
    strategy_path: Path,
    dataset: MarketDataset,
    output_dir: Path,
    reuse_trader_instance: bool = False,
    queue_alpha: float = 1.0,
    make_plots: bool = True,
    fill_model: str = "same-tick",
    match_trades: str = "all",
    trade_fill_price: str = "order",
    book_delta_on_disappear: str = "if-through",
    market_trades_mode: str = "all",
    fill_trades_mode: str = "auto",
    exchange_calibration: Optional[Dict[str, Any]] = None,
) -> BacktestResult:
    TraderClass = load_strategy_class(strategy_path)
    symbols = sorted(dataset.prices["product"].unique().tolist())
    limits = infer_position_limits(TraderClass, symbols)

    dataset_dir = output_dir / dataset.name
    dataset_dir.mkdir(parents=True, exist_ok=True)

    order_rows: List[Dict[str, Any]] = []
    fill_rows: List[Dict[str, Any]] = []
    equity_rows: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []

    prices = dataset.prices.copy().sort_values(["day", "timestamp", "product"]).reset_index(drop=True)
    trades = dataset.trades.copy().sort_values(["day", "timestamp", "symbol"]).reset_index(drop=True)
    exchange_calibration = exchange_calibration or {}

    global_step = 0

    for day in sorted(prices["day"].unique().tolist()):
        day_prices = prices[prices["day"] == day].copy()
        day_trades = trades[trades["day"] == day].copy()
        timestamps = sorted(day_prices["timestamp"].unique().tolist())

        ledgers = {
            symbol: ProductLedger(symbol=symbol, limit=int(limits.get(symbol, 10**9)))
            for symbol in symbols
        }
        trader_data = ""
        own_trades_for_state: Dict[str, List[Trade]] = {symbol: [] for symbol in symbols}
        trader_instance = TraderClass() if reuse_trader_instance else None

        day_rows = []

        for index, timestamp in enumerate(timestamps):
            tick_rows = day_prices[day_prices["timestamp"] == timestamp]
            next_timestamp = timestamps[index + 1] if index + 1 < len(timestamps) else None
            next_tick_rows = (
                day_prices[day_prices["timestamp"] == next_timestamp]
                if next_timestamp is not None
                else pd.DataFrame(columns=day_prices.columns)
            )

            market_trade_dict: Dict[str, List[Trade]] = {symbol: [] for symbol in symbols}
            current_market_trades = day_trades[day_trades["timestamp"] == timestamp]
            current_market_trades = filter_market_trades(current_market_trades, market_trades_mode)
            for trade_row in current_market_trades.itertuples(index=False):
                market_trade_dict[str(trade_row.symbol)].append(
                    Trade(
                        symbol=str(trade_row.symbol),
                        price=int(trade_row.price),
                        quantity=int(trade_row.quantity),
                        buyer=str(getattr(trade_row, "buyer", "")),
                        seller=str(getattr(trade_row, "seller", "")),
                        timestamp=int(trade_row.timestamp),
                    )
                )

            state = build_state(
                tick_rows=tick_rows,
                timestamp=int(timestamp),
                trader_data=trader_data,
                positions={symbol: ledger.position for symbol, ledger in ledgers.items()},
                own_trades=own_trades_for_state,
                market_trades=market_trade_dict,
            )

            trader = trader_instance if trader_instance is not None else TraderClass()
            response = trader.run(state)
            orders_by_symbol, _conversions, trader_data = normalize_strategy_response(response)

            next_own_trades: Dict[str, List[Trade]] = {symbol: [] for symbol in symbols}

            fill_trades_mode_resolved = (
                market_trades_mode if fill_trades_mode == "auto" else fill_trades_mode
            )

            for symbol in symbols:
                current_row = tick_rows[tick_rows["product"] == symbol]
                if current_row.empty:
                    continue
                current_row = current_row.iloc[0]

                next_row_series: Optional[pd.Series] = None
                if next_timestamp is not None:
                    next_row = next_tick_rows[next_tick_rows["product"] == symbol]
                    if not next_row.empty:
                        next_row_series = next_row.iloc[0]

                current_symbol_trades = day_trades[
                    (day_trades["symbol"] == symbol)
                    & (day_trades["timestamp"] == timestamp)
                ]
                current_symbol_trades = filter_market_trades(
                    current_symbol_trades, fill_trades_mode_resolved
                )
                interval_trades = day_trades[
                    (day_trades["symbol"] == symbol)
                    & (day_trades["timestamp"] > timestamp)
                    & (
                        True
                        if next_timestamp is None
                        else day_trades["timestamp"] <= next_timestamp
                    )
                ]
                interval_trades = filter_market_trades(interval_trades, fill_trades_mode_resolved)

                symbol_orders = orders_by_symbol.get(symbol, []) or []
                symbol_orders = [
                    Order(symbol=str(raw_order.symbol), price=int(raw_order.price), quantity=int(raw_order.quantity))
                    for raw_order in symbol_orders
                ]

                cancelled_by_limit = not product_orders_within_limits(
                    position=ledgers[symbol].position,
                    limit=ledgers[symbol].limit,
                    orders=symbol_orders,
                )
                if cancelled_by_limit:
                    for order in symbol_orders:
                        order_rows.append(
                            {
                                "dataset": dataset.name,
                                "day": int(day),
                                "timestamp": int(timestamp),
                                "step": global_step,
                                "symbol": symbol,
                                "side": "buy" if order.quantity > 0 else "sell",
                                "price": int(order.price),
                                "requested_qty": abs(int(order.quantity)),
                                "executed_qty": 0,
                                "remaining_qty": abs(int(order.quantity)),
                                "immediate_qty": 0,
                                "passive_qty": 0,
                                "fill_count": 0,
                                "cancelled_by_limit": True,
                            }
                        )
                    continue

                for raw_order in symbol_orders:
                    order = raw_order
                    if fill_model == "same-tick":
                        result, fills = simulate_order_same_tick(
                            dataset_name=dataset.name,
                            day=int(day),
                            current_timestamp=int(timestamp),
                            order=order,
                            current_row=current_row,
                            current_market_trades=current_symbol_trades,
                            ledger=ledgers[symbol],
                            match_trades=match_trades,
                            trade_fill_price=trade_fill_price,
                        )
                    elif fill_model == "official-hybrid":
                        result, fills = simulate_order_official_hybrid(
                            dataset_name=dataset.name,
                            day=int(day),
                            current_timestamp=int(timestamp),
                            next_timestamp=int(next_timestamp) if next_timestamp is not None else None,
                            order=order,
                            current_row=current_row,
                            next_row=next_row_series,
                            current_market_trades=current_symbol_trades,
                            ledger=ledgers[symbol],
                            queue_alpha=queue_alpha,
                            fill_on_disappear=book_delta_on_disappear,
                            exchange_calibration=exchange_calibration,
                        )
                    elif fill_model == "book-delta":
                        result, fills = simulate_order_book_delta(
                            dataset_name=dataset.name,
                            day=int(day),
                            current_timestamp=int(timestamp),
                            next_timestamp=int(next_timestamp) if next_timestamp is not None else None,
                            order=order,
                            current_row=current_row,
                            next_row=next_row_series,
                            ledger=ledgers[symbol],
                            queue_alpha=queue_alpha,
                            fill_on_disappear=book_delta_on_disappear,
                        )
                    else:
                        result, fills = simulate_order(
                            dataset_name=dataset.name,
                            day=int(day),
                            current_timestamp=int(timestamp),
                            next_timestamp=int(next_timestamp) if next_timestamp is not None else None,
                            symbol=symbol,
                            order=order,
                            current_row=current_row,
                            next_row=next_row_series,
                            interval_trades=interval_trades,
                            ledger=ledgers[symbol],
                            queue_alpha=queue_alpha,
                            trade_fill_price=trade_fill_price,
                        )

                    order_rows.append(
                        {
                            "dataset": dataset.name,
                            "day": int(day),
                            "timestamp": int(timestamp),
                            "step": global_step,
                            "symbol": symbol,
                            "side": "buy" if order.quantity > 0 else "sell",
                            "price": int(order.price),
                            "requested_qty": result.requested_qty,
                            "executed_qty": result.executed_qty,
                            "remaining_qty": result.remaining_qty,
                            "immediate_qty": result.immediate_qty,
                            "passive_qty": result.passive_qty,
                            "fill_count": result.fill_count,
                            "cancelled_by_limit": False,
                        }
                    )

                    for fill in fills:
                        fill_rows.append(
                            {
                                "dataset": fill.dataset,
                                "day": fill.day,
                                "timestamp": fill.timestamp,
                                "step": global_step,
                                "symbol": fill.symbol,
                                "side": fill.side,
                                "quantity": fill.quantity,
                                "price": fill.price,
                                "liquidity": fill.liquidity,
                                "order_price": fill.order_price,
                            }
                        )
                        next_own_trades[symbol].append(
                            Trade(
                                symbol=fill.symbol,
                                price=int(fill.price),
                                quantity=int(fill.quantity),
                                buyer="BACKTEST_BUYER" if fill.side == "buy" else "",
                                seller="BACKTEST_SELLER" if fill.side == "sell" else "",
                                timestamp=int(fill.timestamp),
                            )
                        )

            mark_rows = (
                tick_rows
                if fill_model in {"same-tick", "official-hybrid"}
                else (next_tick_rows if next_timestamp is not None else tick_rows)
            )
            mids = {
                str(row.product): float(row.mid_price)
                for row in mark_rows.itertuples(index=False)
            }

            realized = sum(ledger.realized_pnl for ledger in ledgers.values())
            total = 0.0
            unrealized = 0.0
            equity_row: Dict[str, Any] = {
                "dataset": dataset.name,
                "day": int(day),
                "timestamp": int(
                    timestamp
                    if fill_model in {"same-tick", "official-hybrid"}
                    else (next_timestamp if next_timestamp is not None else timestamp)
                ),
                "step": global_step,
                "realized_pnl": realized,
            }

            for symbol in symbols:
                ledger = ledgers[symbol]
                mid = float(mids.get(symbol, 0.0))
                symbol_total = ledger.cash + ledger.position * mid
                symbol_unrealized = symbol_total - ledger.realized_pnl
                equity_row[f"position_{symbol}"] = ledger.position
                equity_row[f"mid_{symbol}"] = mid
                equity_row[f"pnl_{symbol}"] = symbol_total
                total += symbol_total
                unrealized += symbol_unrealized

            equity_row["total_pnl"] = total
            equity_row["unrealized_pnl"] = unrealized
            equity_rows.append(equity_row)
            day_rows.append(equity_row)
            own_trades_for_state = next_own_trades
            global_step += 1

        day_equity = pd.DataFrame(day_rows)
        day_orders = [
            row
            for row in order_rows
            if row["dataset"] == dataset.name and row["day"] == int(day)
        ]
        day_fills = [
            row
            for row in fill_rows
            if row["dataset"] == dataset.name and row["day"] == int(day)
        ]
        orders_submitted = len(day_orders)
        buy_orders_submitted = sum(1 for row in day_orders if row["side"] == "buy")
        sell_orders_submitted = orders_submitted - buy_orders_submitted
        requested_qty = int(sum(int(row["requested_qty"]) for row in day_orders))
        requested_buy_qty = int(
            sum(int(row["requested_qty"]) for row in day_orders if row["side"] == "buy")
        )
        requested_sell_qty = requested_qty - requested_buy_qty
        executed_qty = int(sum(int(row["executed_qty"]) for row in day_orders))
        executed_buy_qty = int(
            sum(int(row["executed_qty"]) for row in day_orders if row["side"] == "buy")
        )
        executed_sell_qty = executed_qty - executed_buy_qty
        cancelled_by_limit = int(
            sum(1 for row in day_orders if bool(row["cancelled_by_limit"]))
        )
        fills_count = len(day_fills)
        buy_fills = sum(1 for row in day_fills if row["side"] == "buy")
        sell_fills = fills_count - buy_fills
        fill_qty = int(sum(int(row["quantity"]) for row in day_fills))
        fill_buy_qty = int(
            sum(int(row["quantity"]) for row in day_fills if row["side"] == "buy")
        )
        fill_sell_qty = fill_qty - fill_buy_qty
        summary_rows.append(
            {
                "dataset": dataset.name,
                "day": int(day),
                "final_total_pnl": float(day_equity["total_pnl"].iloc[-1]) if not day_equity.empty else 0.0,
                "final_realized_pnl": float(day_equity["realized_pnl"].iloc[-1]) if not day_equity.empty else 0.0,
                "final_unrealized_pnl": float(day_equity["unrealized_pnl"].iloc[-1]) if not day_equity.empty else 0.0,
                "max_drawdown": max_drawdown(day_equity["total_pnl"]) if not day_equity.empty else 0.0,
                "orders_submitted": int(orders_submitted),
                "buy_orders_submitted": int(buy_orders_submitted),
                "sell_orders_submitted": int(sell_orders_submitted),
                "requested_qty": int(requested_qty),
                "requested_buy_qty": int(requested_buy_qty),
                "requested_sell_qty": int(requested_sell_qty),
                "executed_qty": int(executed_qty),
                "executed_buy_qty": int(executed_buy_qty),
                "executed_sell_qty": int(executed_sell_qty),
                "fill_rate": float(executed_qty / requested_qty) if requested_qty > 0 else 0.0,
                "cancelled_by_limit": int(cancelled_by_limit),
                "fills": int(fills_count),
                "buy_fills": int(buy_fills),
                "sell_fills": int(sell_fills),
                "fill_qty": int(fill_qty),
                "fill_buy_qty": int(fill_buy_qty),
                "fill_sell_qty": int(fill_sell_qty),
                "turnover": float(sum(ledger.turnover for ledger in ledgers.values())),
            }
        )

    summary = pd.DataFrame(summary_rows)
    equity_curve = pd.DataFrame(equity_rows)
    fills = pd.DataFrame(fill_rows)
    orders = pd.DataFrame(order_rows)

    summary.to_csv(dataset_dir / "summary.csv", index=False)
    equity_curve.to_csv(dataset_dir / "equity_curve.csv", index=False)
    fills.to_csv(dataset_dir / "fills.csv", index=False)
    orders.to_csv(dataset_dir / "orders.csv", index=False)

    chart_paths: List[Path] = []
    if make_plots and not equity_curve.empty:
        equity_path = dataset_dir / "equity_curve.png"
        plot_equity_curve(equity_curve, equity_path, f"{dataset.name} equity curve")
        chart_paths.append(equity_path)

        order_activity_path = dataset_dir / "order_activity.png"
        plot_order_activity(orders, order_activity_path, f"{dataset.name} order activity")
        if order_activity_path.exists():
            chart_paths.append(order_activity_path)

        execution_summary_path = dataset_dir / "execution_summary.png"
        plot_execution_summary(orders, fills, execution_summary_path, f"{dataset.name} execution summary")
        if execution_summary_path.exists():
            chart_paths.append(execution_summary_path)

        fill_activity_path = dataset_dir / "fill_activity.png"
        plot_fill_activity(fills, fill_activity_path, f"{dataset.name} fill activity")
        if fill_activity_path.exists():
            chart_paths.append(fill_activity_path)

        positions_path = dataset_dir / "positions.png"
        plot_positions(equity_curve, positions_path, symbols)
        chart_paths.append(positions_path)

        if not fills.empty:
            for symbol in symbols:
                symbol_path = dataset_dir / f"{symbol.lower()}_market.png"
                plot_symbol_market(equity_curve, fills, symbol, symbol_path)
                chart_paths.append(symbol_path)

    if make_plots:
        write_html_report(dataset_dir, summary, chart_paths)

    return BacktestResult(
        dataset_name=dataset.name,
        output_dir=dataset_dir,
        summary=summary,
        equity_curve=equity_curve,
        fills=fills,
        orders=orders,
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest Prosperity tutorial strategy files against local historical data.")
    parser.add_argument("strategy", help="Path to a strategy file that defines Trader")
    parser.add_argument(
        "--input",
        nargs="+",
        default=[str(DEFAULT_INPUT_ROOT)],
        help="One or more data directories or JSON/LOG run files. Directory inputs are scanned recursively.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Base directory where per-run folders, reports, and CSV outputs will be written",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Optional short label appended to the auto-generated run folder name",
    )
    parser.add_argument(
        "--reuse-trader-instance",
        action="store_true",
        help="Reuse one Trader instance across ticks instead of recreating it each tick",
    )
    parser.add_argument(
        "--queue-alpha",
        type=float,
        default=1.0,
        help="Fraction of displayed same-price queue assumed ahead of our passive order in interval fill mode",
    )
    parser.add_argument(
        "--fill-model",
        choices=["same-tick", "interval", "book-delta", "official-hybrid"],
        default="same-tick",
        help="Order matching model. official-hybrid uses visible takes plus calibrated passive fills for inside-spread quotes.",
    )
    parser.add_argument(
        "--match-trades",
        choices=["all", "worse", "none"],
        default="all",
        help="How same-tick market trades should be matched after visible depth is consumed.",
    )
    parser.add_argument(
        "--trade-fill-price",
        choices=["order", "trade"],
        default="order",
        help="Price used when filling against market trades (order price vs trade print price).",
    )
    parser.add_argument(
        "--book-delta-on-disappear",
        choices=["never", "if-through", "always"],
        default="if-through",
        help="Passive fill rule when our price level disappears in book-delta mode.",
    )
    parser.add_argument(
        "--market-trades",
        choices=["all", "external-only", "none"],
        default="all",
        help="Which trades to expose in state.market_trades. Fill simulation uses --fill-trades.",
    )
    parser.add_argument(
        "--fill-trades",
        choices=["auto", "all", "external-only", "none"],
        default="auto",
        help="Which trades to use for fill simulation. auto follows --market-trades.",
    )
    parser.add_argument(
        "--exchange-calibration",
        default=None,
        help="Optional JSON calibration for official-hybrid passive fills. Defaults to the bundled round1 file when available.",
    )
    parser.add_argument(
        "--dataset",
        nargs="*",
        default=None,
        help="Optional dataset names to run after discovery, e.g. round0_csv 77832. If omitted, benchmark-data datasets are preferred by default.",
    )
    parser.add_argument(
        "--all-datasets",
        action="store_true",
        help="Run all discovered datasets instead of the default benchmark-data selection.",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip PNG and HTML report generation for faster iteration",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    args = parse_args(argv_list)
    strategy_path = Path(args.strategy).expanduser().resolve()
    input_paths = [Path(value).expanduser().resolve() for value in args.input]
    output_root = Path(args.output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    exchange_calibration_path: Optional[Path] = None
    if args.exchange_calibration:
        exchange_calibration_path = Path(args.exchange_calibration).expanduser().resolve()
    elif str(args.fill_model) == "official-hybrid" and DEFAULT_EXCHANGE_CALIBRATION_PATH.exists():
        exchange_calibration_path = DEFAULT_EXCHANGE_CALIBRATION_PATH
    exchange_calibration = load_exchange_calibration(exchange_calibration_path)

    resolved_market_trades_mode = str(args.market_trades)
    resolved_fill_trades_mode = str(args.fill_trades)
    if str(args.fill_model) == "official-hybrid":
        if resolved_market_trades_mode == "all":
            resolved_market_trades_mode = "external-only"
        if resolved_fill_trades_mode == "auto":
            resolved_fill_trades_mode = "external-only"

    args.market_trades = resolved_market_trades_mode
    args.fill_trades = resolved_fill_trades_mode
    args.exchange_calibration = str(exchange_calibration_path) if exchange_calibration_path else None

    datasets = discover_datasets(input_paths)
    if not datasets:
        raise FileNotFoundError("No datasets discovered from the provided input paths.")

    if args.dataset:
        wanted = set(args.dataset)
        datasets = [dataset for dataset in datasets if dataset.name in wanted]
        if not datasets:
            raise ValueError(f"No discovered datasets matched: {sorted(wanted)}")
    elif not args.all_datasets:
        datasets = select_default_datasets(datasets)

    run_name = build_run_name(
        strategy_path=strategy_path,
        datasets=datasets,
        fill_model=str(args.fill_model),
        match_trades=str(args.match_trades),
        run_name=args.run_name,
    )
    run_dir = make_unique_run_dir(output_root, run_name)
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    command = "python3 tools/backtester.py " + " ".join(shlex.quote(part) for part in argv_list)
    write_run_status(run_dir, "running", details=command)
    write_latest_pointer(output_root, run_dir)

    print(f"Strategy: {strategy_path}")
    print(f"Run directory: {run_dir}")
    print("Datasets:")
    for dataset in datasets:
        print(f"  - {dataset.name}: {dataset.source}")

    results: List[BacktestResult] = []
    try:
        for dataset in datasets:
            result = run_backtest(
                strategy_path=strategy_path,
                dataset=dataset,
                output_dir=run_dir,
                reuse_trader_instance=bool(args.reuse_trader_instance),
                queue_alpha=float(args.queue_alpha),
                make_plots=not args.no_plots,
                fill_model=str(args.fill_model),
                match_trades=str(args.match_trades),
                trade_fill_price=str(args.trade_fill_price),
                book_delta_on_disappear=str(args.book_delta_on_disappear),
                market_trades_mode=resolved_market_trades_mode,
                fill_trades_mode=resolved_fill_trades_mode,
                exchange_calibration=exchange_calibration,
            )
            results.append(result)
            if result.summary.empty:
                print(f"{dataset.name}: no summary rows produced")
                continue
            print()
            print(f"Dataset {dataset.name}")
            print(result.summary.to_string(index=False))
            if not args.no_plots:
                print(f"Report: {result.output_dir / 'report.html'}")

        run_summary = build_run_summary_frame(
            results=results,
            run_name=run_dir.name,
            run_dir=run_dir,
            created_at=created_at,
            strategy_path=strategy_path,
            fill_model=str(args.fill_model),
            match_trades=str(args.match_trades),
            queue_alpha=float(args.queue_alpha),
            trade_fill_price=str(args.trade_fill_price),
            book_delta_on_disappear=str(args.book_delta_on_disappear),
            market_trades_mode=resolved_market_trades_mode,
            fill_trades_mode=resolved_fill_trades_mode,
            make_plots=not args.no_plots,
            reuse_trader_instance=bool(args.reuse_trader_instance),
        )
        if not run_summary.empty:
            run_summary.to_csv(run_dir / "run_summary.csv", index=False)
            update_runs_index(output_root, run_summary)

        write_run_manifest(
            run_dir=run_dir,
            run_name=run_dir.name,
            created_at=created_at,
            strategy_path=strategy_path,
            input_paths=input_paths,
            datasets=datasets,
            args=args,
            command=command,
            results=results,
            status="completed",
        )
        write_run_status(run_dir, "completed", details=command)
        print()
        print(f"Saved run artifacts under: {run_dir}")
        print(f"Latest pointer: {output_root / 'latest'}")
    except Exception as exc:
        write_run_manifest(
            run_dir=run_dir,
            run_name=run_dir.name,
            created_at=created_at,
            strategy_path=strategy_path,
            input_paths=input_paths,
            datasets=datasets,
            args=args,
            command=command,
            results=results,
            status="failed",
        )
        write_run_status(run_dir, "failed", details=str(exc))
        raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
