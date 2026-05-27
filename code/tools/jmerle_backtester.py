from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import sys
import types
import webbrowser
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import partial, reduce
from http.server import HTTPServer, SimpleHTTPRequestHandler
from json import JSONEncoder
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - optional dependency
    tqdm = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / "data"
DEFAULT_OUTPUT_ROOT = REPO_ROOT.parent / "gen" / "jmerle_backtests"

Time = int
Symbol = str
Product = str
Position = int
UserId = str
ObservationValue = int


class Listing:
    def __init__(self, symbol: Symbol, product: Product, denomination: int):
        self.symbol = symbol
        self.product = product
        self.denomination = denomination


class ConversionObservation:
    def __init__(
        self,
        bidPrice: float,
        askPrice: float,
        transportFees: float,
        exportTariff: float,
        importTariff: float,
        sugarPrice: float,
        sunlightIndex: float,
    ):
        self.bidPrice = bidPrice
        self.askPrice = askPrice
        self.transportFees = transportFees
        self.exportTariff = exportTariff
        self.importTariff = importTariff
        self.sugarPrice = sugarPrice
        self.sunlightIndex = sunlightIndex


class Observation:
    def __init__(
        self,
        plainValueObservations: Dict[Product, ObservationValue],
        conversionObservations: Dict[Product, ConversionObservation],
    ) -> None:
        self.plainValueObservations = plainValueObservations
        self.conversionObservations = conversionObservations

    def __str__(self) -> str:
        return json.dumps(
            {
                "plainValueObservations": self.plainValueObservations,
                "conversionObservations": self.conversionObservations,
            },
            default=lambda value: value.__dict__,
            separators=(",", ":"),
        )


class Order:
    def __init__(self, symbol: Symbol, price: int, quantity: int) -> None:
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

    def __str__(self) -> str:
        return f"({self.symbol}, {self.price}, {self.quantity})"

    def __repr__(self) -> str:
        return str(self)


class OrderDepth:
    def __init__(self):
        self.buy_orders: Dict[int, int] = {}
        self.sell_orders: Dict[int, int] = {}


class Trade:
    def __init__(
        self,
        symbol: Symbol,
        price: int,
        quantity: int,
        buyer: UserId = "",
        seller: UserId = "",
        timestamp: int = 0,
    ) -> None:
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
        self.buyer = buyer
        self.seller = seller
        self.timestamp = timestamp

    def __str__(self) -> str:
        return (
            "("
            + self.symbol
            + ", "
            + str(self.buyer)
            + " << "
            + str(self.seller)
            + ", "
            + str(self.price)
            + ", "
            + str(self.quantity)
            + ", "
            + str(self.timestamp)
            + ")"
        )

    def __repr__(self) -> str:
        return str(self)


class TradingState:
    def __init__(
        self,
        traderData: str,
        timestamp: Time,
        listings: Dict[Symbol, Listing],
        order_depths: Dict[Symbol, OrderDepth],
        own_trades: Dict[Symbol, List[Trade]],
        market_trades: Dict[Symbol, List[Trade]],
        position: Dict[Product, Position],
        observations: Observation,
    ):
        self.traderData = traderData
        self.timestamp = timestamp
        self.listings = listings
        self.order_depths = order_depths
        self.own_trades = own_trades
        self.market_trades = market_trades
        self.position = position
        self.observations = observations

    def toJSON(self) -> str:
        return json.dumps(self, default=lambda value: value.__dict__, sort_keys=True)


class ProsperityEncoder(JSONEncoder):
    def default(self, value: Any) -> Any:
        return value.__dict__


def install_datamodel_shim() -> None:
    if "datamodel" in sys.modules:
        return

    module = types.ModuleType("datamodel")
    exports = {
        "Time": Time,
        "Symbol": Symbol,
        "Product": Product,
        "Position": Position,
        "UserId": UserId,
        "ObservationValue": ObservationValue,
        "Listing": Listing,
        "ConversionObservation": ConversionObservation,
        "Observation": Observation,
        "Order": Order,
        "OrderDepth": OrderDepth,
        "Trade": Trade,
        "TradingState": TradingState,
        "ProsperityEncoder": ProsperityEncoder,
    }
    for name, value in exports.items():
        setattr(module, name, value)
    module.__all__ = list(exports.keys())
    sys.modules["datamodel"] = module


@dataclass
class PriceRow:
    day: int
    timestamp: int
    product: Symbol
    bid_prices: List[int]
    bid_volumes: List[int]
    ask_prices: List[int]
    ask_volumes: List[int]
    mid_price: float


@dataclass
class ObservationRow:
    timestamp: int
    bidPrice: float
    askPrice: float
    transportFees: float
    exportTariff: float
    importTariff: float
    sugarPrice: float
    sunlightIndex: float


@dataclass
class BacktestData:
    round_num: int
    day_num: int
    prices: Dict[int, Dict[Symbol, PriceRow]]
    trades: Dict[int, Dict[Symbol, List[Trade]]]
    observations: Dict[int, ObservationRow]
    products: List[Symbol]


@dataclass
class SandboxLogRow:
    timestamp: int
    sandbox_log: str
    lambda_log: str

    def with_offset(self, timestamp_offset: int) -> "SandboxLogRow":
        original = f"[[{self.timestamp},"
        shifted = f"[[{self.timestamp + timestamp_offset},"
        return SandboxLogRow(
            timestamp=self.timestamp + timestamp_offset,
            sandbox_log=self.sandbox_log,
            lambda_log=self.lambda_log.replace(original, shifted),
        )

    def __str__(self) -> str:
        return json.dumps(
            {
                "sandboxLog": self.sandbox_log,
                "lambdaLog": self.lambda_log,
                "timestamp": self.timestamp,
            },
            indent=2,
        ) + "\n"


@dataclass
class ActivityLogRow:
    columns: List[Any]

    @property
    def timestamp(self) -> int:
        return int(self.columns[1])

    def with_offset(self, timestamp_offset: int, profit_loss_offset: float) -> "ActivityLogRow":
        new_columns = self.columns[:]
        new_columns[1] = int(new_columns[1]) + timestamp_offset
        new_columns[-1] = float(new_columns[-1]) + profit_loss_offset
        return ActivityLogRow(new_columns)

    def __str__(self) -> str:
        return ";".join("" if value is None else str(value) for value in self.columns)


@dataclass
class TradeRow:
    trade: Trade

    @property
    def timestamp(self) -> int:
        return int(self.trade.timestamp)

    def with_offset(self, timestamp_offset: int) -> "TradeRow":
        return TradeRow(
            Trade(
                symbol=self.trade.symbol,
                price=int(self.trade.price),
                quantity=int(self.trade.quantity),
                buyer=self.trade.buyer,
                seller=self.trade.seller,
                timestamp=int(self.trade.timestamp) + timestamp_offset,
            )
        )

    def __str__(self) -> str:
        return (
            "  "
            + f"""
  {{
    "timestamp": {self.trade.timestamp},
    "buyer": "{self.trade.buyer}",
    "seller": "{self.trade.seller}",
    "symbol": "{self.trade.symbol}",
    "currency": "XIRECS",
    "price": {self.trade.price},
    "quantity": {self.trade.quantity},
  }}
        """.strip()
        )


@dataclass
class BacktestResult:
    round_num: int
    day_num: int
    sandbox_logs: List[SandboxLogRow]
    activity_logs: List[ActivityLogRow]
    trades: List[TradeRow]


@dataclass
class MarketTrade:
    trade: Trade
    buy_quantity: int
    sell_quantity: int


class TradeMatchingMode(str, Enum):
    all = "all"
    worse = "worse"
    none = "none"


class TeeBuffer(io.StringIO):
    def __init__(self, downstream: io.TextIOBase):
        super().__init__()
        self._downstream = downstream

    def write(self, text: str) -> int:
        self._downstream.write(text)
        self._downstream.flush()
        return super().write(text)


class HTTPRequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:  # pragma: no cover - local browser integration
        self.server.shutdown_flag = True  # type: ignore[attr-defined]
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return


class CustomHTTPServer(HTTPServer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.shutdown_flag = False


def open_visualizer(output_file: Path) -> None:  # pragma: no cover - local browser integration
    http_handler = partial(HTTPRequestHandler, directory=str(output_file.parent))
    http_server = CustomHTTPServer(("localhost", 0), http_handler)
    webbrowser.open(
        f"https://jmerle.github.io/imc-prosperity-3-visualizer/?open=http://localhost:{http_server.server_port}/{output_file.name}"
    )
    while not http_server.shutdown_flag:
        http_server.handle_request()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Jmerle-style same-tick backtester for local Prosperity datasets."
    )
    parser.add_argument("strategy", help="Path to a Python file that exposes Trader")
    parser.add_argument(
        "days",
        nargs="+",
        help="Backtest targets: <round> for all days in a round, or <round>-<day> for a single day",
    )
    parser.add_argument(
        "--merge-pnl",
        action="store_true",
        help="Carry profit and loss forward when merging multiple requested days into one output log",
    )
    parser.add_argument(
        "--vis",
        action="store_true",
        help="Open the merged output in the Prosperity 3 visualizer after the run completes",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Custom output log path. Defaults to gen/jmerle_backtests/<timestamp>.log",
    )
    parser.add_argument(
        "--no-out",
        action="store_true",
        help="Skip writing the merged output log to disk",
    )
    parser.add_argument(
        "--data",
        default=str(DEFAULT_DATA_ROOT),
        help="Path to the local Prosperity data root. Defaults to IMCP2026/data",
    )
    parser.add_argument(
        "--print",
        dest="print_output",
        action="store_true",
        help="Stream Trader.print output to stdout while the backtest is running",
    )
    parser.add_argument(
        "--match-trades",
        choices=[mode.value for mode in TradeMatchingMode],
        default=TradeMatchingMode.all.value,
        help="How to match against current-timestamp market trades after visible book volume is consumed",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bars",
    )
    parser.add_argument(
        "--original-timestamps",
        action="store_true",
        help="Preserve original timestamps when merging multiple days into one output log",
    )
    return parser.parse_args(argv)


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
    raise TypeError(f"Unsupported Trader.run response type: {type(response)!r}")


def load_trader_class(strategy_path: Path):
    install_datamodel_shim()
    strategy_parent = str(strategy_path.parent)
    if strategy_parent not in sys.path:
        sys.path.insert(0, strategy_parent)

    module_name = (
        "jmerle_style_strategy_"
        + hashlib.sha1(f"{strategy_path}:{datetime.now().timestamp()}".encode("utf-8")).hexdigest()[:12]
    )
    spec = importlib.util.spec_from_file_location(module_name, strategy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not import strategy from {strategy_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "Trader"):
        raise AttributeError(f"{strategy_path} does not define Trader")
    return module.Trader


def infer_position_limits(trader_class: Any, products: Iterable[str]) -> Dict[str, int]:
    for attr in ("POSITION_LIMITS", "LIMITS"):
        raw = getattr(trader_class, attr, None)
        if isinstance(raw, dict):
            return {str(key): int(value) for key, value in raw.items()}
    return {product: 10**9 for product in products}


def create_backtest_data(
    round_num: int,
    day_num: int,
    prices: Sequence[PriceRow],
    trades: Sequence[Trade],
    observations: Sequence[ObservationRow],
) -> BacktestData:
    prices_by_timestamp: Dict[int, Dict[Symbol, PriceRow]] = {}
    for row in prices:
        prices_by_timestamp.setdefault(int(row.timestamp), {})[row.product] = row

    trades_by_timestamp: Dict[int, Dict[Symbol, List[Trade]]] = {}
    for trade in trades:
        product_trades = trades_by_timestamp.setdefault(int(trade.timestamp), {})
        product_trades.setdefault(trade.symbol, []).append(trade)

    observations_by_timestamp = {int(row.timestamp): row for row in observations}
    products = sorted({row.product for row in prices})

    return BacktestData(
        round_num=int(round_num),
        day_num=int(day_num),
        prices=prices_by_timestamp,
        trades=trades_by_timestamp,
        observations=observations_by_timestamp,
        products=products,
    )


def has_day_data(data_root: Path, round_num: int, day_num: int) -> bool:
    return (data_root / f"round{round_num}" / f"prices_round_{round_num}_day_{day_num}.csv").exists()


def list_round_days(data_root: Path, round_num: int) -> List[int]:
    round_dir = data_root / f"round{round_num}"
    if not round_dir.exists():
        return []

    days: List[int] = []
    prefix = f"prices_round_{round_num}_day_"
    for path in round_dir.glob(f"{prefix}*.csv"):
        suffix = path.stem[len(prefix) :]
        try:
            days.append(int(suffix))
        except ValueError:
            continue
    return sorted(set(days))


def parse_days(data_root: Path, day_specs: Sequence[str]) -> List[Tuple[int, int]]:
    parsed_days: List[Tuple[int, int]] = []

    for spec in day_specs:
        if "-" in spec:
            round_str, day_str = spec.split("-", 1)
            round_num = int(round_str)
            day_num = int(day_str)
            if not has_day_data(data_root, round_num, day_num):
                print(f"Warning: no data found for round {round_num} day {day_num}")
                continue
            parsed_days.append((round_num, day_num))
            continue

        round_num = int(spec)
        round_days = list_round_days(data_root, round_num)
        if not round_days:
            print(f"Warning: no data found for round {round_num}")
            continue
        parsed_days.extend((round_num, day_num) for day_num in round_days)

    if not parsed_days:
        raise ValueError("Did not find data for any requested round/day")
    return parsed_days


def parse_output_path(out: Optional[str], no_out: bool) -> Optional[Path]:
    if out:
        return Path(out).expanduser().resolve()
    if no_out:
        return None
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return (DEFAULT_OUTPUT_ROOT / f"{timestamp}.log").resolve()


def format_path(path: Path) -> str:
    cwd = Path.cwd().resolve()
    try:
        return str(path.resolve().relative_to(cwd))
    except ValueError:
        return str(path.resolve())


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return int(float(text))


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return float(text)


def _field(row: Dict[str, str], *names: str, default: str = "") -> str:
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        if name in row and row[name] != "":
            return row[name]
        lowered_name = name.lower()
        if lowered_name in lowered and lowered[lowered_name] != "":
            return lowered[lowered_name]
    return default


def _get_level_values(row: Dict[str, str], price_keys: Sequence[str], volume_keys: Sequence[str]) -> Tuple[List[int], List[int]]:
    prices: List[int] = []
    volumes: List[int] = []
    for price_key, volume_key in zip(price_keys, volume_keys):
        price = _optional_int(row.get(price_key))
        volume = _optional_int(row.get(volume_key))
        if price is None or volume is None:
            continue
        prices.append(price)
        volumes.append(abs(volume))
    return prices, volumes


def _compute_mid_price(bid_prices: Sequence[int], ask_prices: Sequence[int]) -> float:
    if bid_prices and ask_prices:
        return (bid_prices[0] + ask_prices[0]) / 2.0
    if bid_prices:
        return float(bid_prices[0])
    if ask_prices:
        return float(ask_prices[0])
    return 0.0


def read_day_data(data_root: Path, round_num: int, day_num: int) -> BacktestData:
    round_dir = data_root / f"round{round_num}"
    prices_path = round_dir / f"prices_round_{round_num}_day_{day_num}.csv"
    trades_path = round_dir / f"trades_round_{round_num}_day_{day_num}.csv"
    observations_path = round_dir / f"observations_round_{round_num}_day_{day_num}.csv"

    if not prices_path.exists():
        raise FileNotFoundError(f"Missing prices CSV: {prices_path}")

    prices: List[PriceRow] = []
    with prices_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            bid_prices, bid_volumes = _get_level_values(
                row,
                ["bid_price_1", "bid_price_2", "bid_price_3"],
                ["bid_volume_1", "bid_volume_2", "bid_volume_3"],
            )
            ask_prices, ask_volumes = _get_level_values(
                row,
                ["ask_price_1", "ask_price_2", "ask_price_3"],
                ["ask_volume_1", "ask_volume_2", "ask_volume_3"],
            )
            mid_price = _optional_float(row.get("mid_price"))
            if mid_price is None:
                mid_price = _compute_mid_price(bid_prices, ask_prices)
            prices.append(
                PriceRow(
                    day=int(float(_field(row, "day"))),
                    timestamp=int(float(_field(row, "timestamp"))),
                    product=_field(row, "product"),
                    bid_prices=bid_prices,
                    bid_volumes=bid_volumes,
                    ask_prices=ask_prices,
                    ask_volumes=ask_volumes,
                    mid_price=mid_price,
                )
            )

    trades: List[Trade] = []
    if trades_path.exists():
        with trades_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for row in reader:
                trades.append(
                    Trade(
                        symbol=_field(row, "symbol"),
                        price=int(float(_field(row, "price"))),
                        quantity=int(float(_field(row, "quantity"))),
                        buyer=_field(row, "buyer"),
                        seller=_field(row, "seller"),
                        timestamp=int(float(_field(row, "timestamp"))),
                    )
                )

    observations: List[ObservationRow] = []
    if observations_path.exists():
        with observations_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                observations.append(
                    ObservationRow(
                        timestamp=int(float(_field(row, "timestamp"))),
                        bidPrice=float(_field(row, "bidPrice", "bid_price", default="0")),
                        askPrice=float(_field(row, "askPrice", "ask_price", default="0")),
                        transportFees=float(_field(row, "transportFees", "transport_fees", default="0")),
                        exportTariff=float(_field(row, "exportTariff", "export_tariff", default="0")),
                        importTariff=float(_field(row, "importTariff", "import_tariff", default="0")),
                        sugarPrice=float(_field(row, "sugarPrice", "sugar_price", default="0")),
                        sunlightIndex=float(_field(row, "sunlightIndex", "sunlight_index", default="0")),
                    )
                )

    return create_backtest_data(
        round_num=round_num,
        day_num=day_num,
        prices=prices,
        trades=trades,
        observations=observations,
    )


def market_dataset_to_backtest_data(
    dataset: Any,
    round_num: int,
    day_num: Optional[int] = None,
    exclude_submission_trades: bool = False,
) -> BacktestData:
    prices_frame = dataset.prices.sort_values(["day", "timestamp", "product"]).reset_index(drop=True)
    trades_frame = dataset.trades.sort_values(["day", "timestamp", "symbol"]).reset_index(drop=True)

    price_records = prices_frame.to_dict(orient="records")
    if day_num is None:
        if price_records:
            day_num = int(_optional_int(price_records[0].get("day")) or 0)
        else:
            day_num = 0

    prices: List[PriceRow] = []
    observations: Dict[int, ObservationRow] = {}
    for record in price_records:
        bid_prices, bid_volumes = _get_level_values(
            record,
            ["bid_price_1", "bid_price_2", "bid_price_3"],
            ["bid_volume_1", "bid_volume_2", "bid_volume_3"],
        )
        ask_prices, ask_volumes = _get_level_values(
            record,
            ["ask_price_1", "ask_price_2", "ask_price_3"],
            ["ask_volume_1", "ask_volume_2", "ask_volume_3"],
        )
        mid_price = _optional_float(record.get("mid_price"))
        if mid_price is None:
            mid_price = _compute_mid_price(bid_prices, ask_prices)

        timestamp = int(_optional_int(record.get("timestamp")) or 0)
        prices.append(
            PriceRow(
                day=int(_optional_int(record.get("day")) or day_num),
                timestamp=timestamp,
                product=str(record.get("product") or ""),
                bid_prices=bid_prices,
                bid_volumes=bid_volumes,
                ask_prices=ask_prices,
                ask_volumes=ask_volumes,
                mid_price=mid_price,
            )
        )

        raw_obs = record.get("observations")
        if timestamp in observations or not isinstance(raw_obs, dict):
            continue
        conversion_obs = raw_obs.get("conversionObservations", {})
        macarons = conversion_obs.get("MAGNIFICENT_MACARONS")
        if not isinstance(macarons, dict):
            continue
        observations[timestamp] = ObservationRow(
            timestamp=timestamp,
            bidPrice=float(macarons.get("bidPrice", 0.0)),
            askPrice=float(macarons.get("askPrice", 0.0)),
            transportFees=float(macarons.get("transportFees", 0.0)),
            exportTariff=float(macarons.get("exportTariff", 0.0)),
            importTariff=float(macarons.get("importTariff", 0.0)),
            sugarPrice=float(macarons.get("sugarPrice", 0.0)),
            sunlightIndex=float(macarons.get("sunlightIndex", 0.0)),
        )

    trades: List[Trade] = []
    for record in trades_frame.to_dict(orient="records"):
        buyer = str(record.get("buyer") or "")
        seller = str(record.get("seller") or "")
        if exclude_submission_trades and (buyer == "SUBMISSION" or seller == "SUBMISSION"):
            continue
        trades.append(
            Trade(
                symbol=str(record.get("symbol") or ""),
                price=int(_optional_int(record.get("price")) or 0),
                quantity=int(_optional_int(record.get("quantity")) or 0),
                buyer=buyer,
                seller=seller,
                timestamp=int(_optional_int(record.get("timestamp")) or 0),
            )
        )

    return create_backtest_data(
        round_num=round_num,
        day_num=day_num,
        prices=prices,
        trades=trades,
        observations=list(observations.values()),
    )


def build_observation(row: Optional[ObservationRow]) -> Observation:
    if row is None:
        return Observation({}, {})
    conversion_observation = ConversionObservation(
        bidPrice=row.bidPrice,
        askPrice=row.askPrice,
        transportFees=row.transportFees,
        exportTariff=row.exportTariff,
        importTariff=row.importTariff,
        sugarPrice=row.sugarPrice,
        sunlightIndex=row.sunlightIndex,
    )
    return Observation({}, {"MAGNIFICENT_MACARONS": conversion_observation})


def build_state(
    data: BacktestData,
    timestamp: int,
    trader_data: str,
    positions: Dict[str, int],
    own_trades: Dict[str, List[Trade]],
) -> TradingState:
    listings: Dict[str, Listing] = {}
    order_depths: Dict[str, OrderDepth] = {}
    for product, row in data.prices[timestamp].items():
        depth = OrderDepth()
        for price, volume in zip(row.bid_prices, row.bid_volumes):
            depth.buy_orders[int(price)] = int(volume)
        for price, volume in zip(row.ask_prices, row.ask_volumes):
            depth.sell_orders[int(price)] = -int(volume)
        listings[product] = Listing(product, product, 1)
        order_depths[product] = depth

    market_trades: Dict[str, List[Trade]] = {}
    for product, trades in data.trades.get(timestamp, {}).items():
        market_trades[product] = [
            Trade(
                symbol=trade.symbol,
                price=int(trade.price),
                quantity=int(trade.quantity),
                buyer=trade.buyer,
                seller=trade.seller,
                timestamp=int(trade.timestamp),
            )
            for trade in trades
        ]

    return TradingState(
        traderData=trader_data,
        timestamp=timestamp,
        listings=listings,
        order_depths=order_depths,
        own_trades={symbol: trades[:] for symbol, trades in own_trades.items()},
        market_trades=market_trades,
        position=dict(positions),
        observations=build_observation(data.observations.get(timestamp)),
    )


def coerce_orders(raw_orders: Dict[str, Any]) -> Dict[str, List[Order]]:
    orders: Dict[str, List[Order]] = {}
    if raw_orders is None:
        return orders
    if not isinstance(raw_orders, dict):
        raise TypeError(f"Orders must be a dict, got {type(raw_orders)!r}")

    for key, value in raw_orders.items():
        if not isinstance(key, str):
            raise ValueError(f"Order book key {key!r} is of type {type(key)!r}, expected str")
        if value is None:
            continue

        coerced: List[Order] = []
        for raw_order in value:
            if not hasattr(raw_order, "symbol") or not hasattr(raw_order, "price") or not hasattr(raw_order, "quantity"):
                raise TypeError(f"Order {raw_order!r} does not expose symbol/price/quantity")
            coerced.append(
                Order(
                    symbol=str(raw_order.symbol),
                    price=int(raw_order.price),
                    quantity=int(raw_order.quantity),
                )
            )
        orders[key] = coerced
    return orders


def create_activity_logs(
    positions: Dict[str, int],
    cash: Dict[str, float],
    data: BacktestData,
    timestamp: int,
    result: BacktestResult,
) -> None:
    for product in data.products:
        row = data.prices[timestamp].get(product)
        if row is None:
            continue
        position = int(positions.get(product, 0))
        product_profit_loss = float(cash.get(product, 0.0))
        if position != 0:
            product_profit_loss += position * row.mid_price

        bid_prices = row.bid_prices
        bid_volumes = row.bid_volumes
        ask_prices = row.ask_prices
        ask_volumes = row.ask_volumes

        columns = [
            data.day_num,
            timestamp,
            product,
            bid_prices[0] if len(bid_prices) > 0 else "",
            bid_volumes[0] if len(bid_volumes) > 0 else "",
            bid_prices[1] if len(bid_prices) > 1 else "",
            bid_volumes[1] if len(bid_volumes) > 1 else "",
            bid_prices[2] if len(bid_prices) > 2 else "",
            bid_volumes[2] if len(bid_volumes) > 2 else "",
            ask_prices[0] if len(ask_prices) > 0 else "",
            ask_volumes[0] if len(ask_volumes) > 0 else "",
            ask_prices[1] if len(ask_prices) > 1 else "",
            ask_volumes[1] if len(ask_volumes) > 1 else "",
            ask_prices[2] if len(ask_prices) > 2 else "",
            ask_volumes[2] if len(ask_volumes) > 2 else "",
            row.mid_price,
            product_profit_loss,
        ]
        result.activity_logs.append(ActivityLogRow(columns))


def enforce_limits(
    positions: Dict[str, int],
    limits: Dict[str, int],
    products: Sequence[str],
    orders: Dict[str, List[Order]],
    sandbox_row: SandboxLogRow,
) -> None:
    messages: List[str] = []
    for product in products:
        product_orders = orders.get(product, [])
        if not product_orders:
            continue

        position = int(positions.get(product, 0))
        limit = int(limits.get(product, 10**9))
        total_long = sum(int(order.quantity) for order in product_orders if int(order.quantity) > 0)
        total_short = sum(abs(int(order.quantity)) for order in product_orders if int(order.quantity) < 0)

        if position + total_long > limit or position - total_short < -limit:
            messages.append(f"Orders for product {product} exceeded limit of {limit} set")
            orders.pop(product, None)

    if messages:
        sandbox_row.sandbox_log += "\n" + "\n".join(messages)


def match_buy_order(
    state: TradingState,
    positions: Dict[str, int],
    cash: Dict[str, float],
    order: Order,
    market_trades: List[MarketTrade],
    trade_matching_mode: TradeMatchingMode,
) -> List[Trade]:
    trades: List[Trade] = []

    order_depth = state.order_depths.get(order.symbol)
    if order_depth is None:
        return trades

    price_matches = sorted(price for price in order_depth.sell_orders if price <= int(order.price))
    for price in price_matches:
        available = abs(int(order_depth.sell_orders[price]))
        volume = min(int(order.quantity), available)
        if volume <= 0:
            continue

        trades.append(Trade(order.symbol, int(price), volume, "SUBMISSION", "", int(state.timestamp)))
        positions[order.symbol] = int(positions.get(order.symbol, 0)) + volume
        cash[order.symbol] = float(cash.get(order.symbol, 0.0)) - price * volume

        order_depth.sell_orders[price] += volume
        if order_depth.sell_orders[price] == 0:
            order_depth.sell_orders.pop(price)

        order.quantity -= volume
        if order.quantity == 0:
            return trades

    if trade_matching_mode == TradeMatchingMode.none:
        return trades

    for market_trade in market_trades:
        trade_price = int(market_trade.trade.price)
        if (
            market_trade.sell_quantity == 0
            or trade_price > int(order.price)
            or (trade_price == int(order.price) and trade_matching_mode == TradeMatchingMode.worse)
        ):
            continue

        volume = min(int(order.quantity), int(market_trade.sell_quantity))
        if volume <= 0:
            continue

        trades.append(
            Trade(
                order.symbol,
                int(order.price),
                volume,
                "SUBMISSION",
                market_trade.trade.seller,
                int(state.timestamp),
            )
        )
        positions[order.symbol] = int(positions.get(order.symbol, 0)) + volume
        cash[order.symbol] = float(cash.get(order.symbol, 0.0)) - int(order.price) * volume

        market_trade.sell_quantity -= volume
        order.quantity -= volume
        if order.quantity == 0:
            return trades

    return trades


def match_sell_order(
    state: TradingState,
    positions: Dict[str, int],
    cash: Dict[str, float],
    order: Order,
    market_trades: List[MarketTrade],
    trade_matching_mode: TradeMatchingMode,
) -> List[Trade]:
    trades: List[Trade] = []

    order_depth = state.order_depths.get(order.symbol)
    if order_depth is None:
        return trades

    price_matches = sorted(
        (price for price in order_depth.buy_orders if price >= int(order.price)),
        reverse=True,
    )
    for price in price_matches:
        available = int(order_depth.buy_orders[price])
        volume = min(abs(int(order.quantity)), available)
        if volume <= 0:
            continue

        trades.append(Trade(order.symbol, int(price), volume, "", "SUBMISSION", int(state.timestamp)))
        positions[order.symbol] = int(positions.get(order.symbol, 0)) - volume
        cash[order.symbol] = float(cash.get(order.symbol, 0.0)) + price * volume

        order_depth.buy_orders[price] -= volume
        if order_depth.buy_orders[price] == 0:
            order_depth.buy_orders.pop(price)

        order.quantity += volume
        if order.quantity == 0:
            return trades

    if trade_matching_mode == TradeMatchingMode.none:
        return trades

    for market_trade in market_trades:
        trade_price = int(market_trade.trade.price)
        if (
            market_trade.buy_quantity == 0
            or trade_price < int(order.price)
            or (trade_price == int(order.price) and trade_matching_mode == TradeMatchingMode.worse)
        ):
            continue

        volume = min(abs(int(order.quantity)), int(market_trade.buy_quantity))
        if volume <= 0:
            continue

        trades.append(
            Trade(
                order.symbol,
                int(order.price),
                volume,
                market_trade.trade.buyer,
                "SUBMISSION",
                int(state.timestamp),
            )
        )
        positions[order.symbol] = int(positions.get(order.symbol, 0)) - volume
        cash[order.symbol] = float(cash.get(order.symbol, 0.0)) + int(order.price) * volume

        market_trade.buy_quantity -= volume
        order.quantity += volume
        if order.quantity == 0:
            return trades

    return trades


def match_order(
    state: TradingState,
    positions: Dict[str, int],
    cash: Dict[str, float],
    order: Order,
    market_trades: List[MarketTrade],
    trade_matching_mode: TradeMatchingMode,
) -> List[Trade]:
    if int(order.quantity) > 0:
        return match_buy_order(state, positions, cash, order, market_trades, trade_matching_mode)
    if int(order.quantity) < 0:
        return match_sell_order(state, positions, cash, order, market_trades, trade_matching_mode)
    return []


def match_orders(
    state: TradingState,
    positions: Dict[str, int],
    cash: Dict[str, float],
    data: BacktestData,
    orders: Dict[str, List[Order]],
    result: BacktestResult,
    trade_matching_mode: TradeMatchingMode,
) -> Dict[str, List[Trade]]:
    remaining_market_trades: Dict[str, List[MarketTrade]] = {}
    for product, trades in data.trades.get(state.timestamp, {}).items():
        remaining_market_trades[product] = [
            MarketTrade(
                trade=Trade(
                    symbol=trade.symbol,
                    price=int(trade.price),
                    quantity=int(trade.quantity),
                    buyer=trade.buyer,
                    seller=trade.seller,
                    timestamp=int(trade.timestamp),
                ),
                buy_quantity=int(trade.quantity),
                sell_quantity=int(trade.quantity),
            )
            for trade in trades
        ]

    own_trades: Dict[str, List[Trade]] = {}
    for product in data.products:
        new_trades: List[Trade] = []
        for order in orders.get(product, []):
            new_trades.extend(
                match_order(
                    state,
                    positions,
                    cash,
                    order,
                    remaining_market_trades.get(product, []),
                    trade_matching_mode,
                )
            )

        if new_trades:
            own_trades[product] = new_trades
            result.trades.extend(TradeRow(trade) for trade in new_trades)

    for product in data.products:
        for trade in remaining_market_trades.get(product, []):
            trade.trade.quantity = min(int(trade.buy_quantity), int(trade.sell_quantity))
            if trade.trade.quantity > 0:
                result.trades.append(TradeRow(trade.trade))

    return own_trades


def run_backtest_data(
    strategy_path: Path,
    data: BacktestData,
    print_output: bool,
    trade_matching_mode: TradeMatchingMode,
    show_progress_bar: bool,
) -> BacktestResult:
    TraderClass = load_trader_class(strategy_path)
    trader = TraderClass()
    limits = infer_position_limits(TraderClass, data.products)

    positions: Dict[str, int] = {product: 0 for product in data.products}
    cash: Dict[str, float] = {product: 0.0 for product in data.products}
    own_trades: Dict[str, List[Trade]] = {}
    trader_data = ""

    # Match the reference tool's day context environment variables for trader-side debugging.
    os.environ["PROSPERITY3BT_ROUND"] = str(data.round_num)
    os.environ["PROSPERITY3BT_DAY"] = str(data.day_num)

    result = BacktestResult(
        round_num=data.round_num,
        day_num=data.day_num,
        sandbox_logs=[],
        activity_logs=[],
        trades=[],
    )

    timestamps = sorted(data.prices.keys())
    iterator: Iterable[int]
    if show_progress_bar and tqdm is not None:
        iterator = tqdm(timestamps, ascii=True)
    else:
        iterator = timestamps

    for timestamp in iterator:
        state = build_state(
            data=data,
            timestamp=int(timestamp),
            trader_data=trader_data,
            positions=positions,
            own_trades=own_trades,
        )

        stdout_buffer: io.StringIO
        if print_output:
            stdout_buffer = TeeBuffer(sys.stdout)
        else:
            stdout_buffer = io.StringIO()

        with redirect_stdout(stdout_buffer):
            response = trader.run(state)

        raw_orders, _conversions, trader_data = normalize_strategy_response(response)
        orders = coerce_orders(raw_orders)

        sandbox_row = SandboxLogRow(
            timestamp=int(timestamp),
            sandbox_log="",
            lambda_log=stdout_buffer.getvalue().rstrip(),
        )
        result.sandbox_logs.append(sandbox_row)

        create_activity_logs(
            positions=positions,
            cash=cash,
            data=data,
            timestamp=int(timestamp),
            result=result,
        )
        enforce_limits(
            positions=positions,
            limits=limits,
            products=data.products,
            orders=orders,
            sandbox_row=sandbox_row,
        )
        own_trades = match_orders(
            state=state,
            positions=positions,
            cash=cash,
            data=data,
            orders=orders,
            result=result,
            trade_matching_mode=trade_matching_mode,
        )

    return result


def run_backtest(
    strategy_path: Path,
    data_root: Path,
    round_num: int,
    day_num: int,
    print_output: bool,
    trade_matching_mode: TradeMatchingMode,
    show_progress_bar: bool,
) -> BacktestResult:
    data = read_day_data(data_root, round_num, day_num)
    return run_backtest_data(
        strategy_path=strategy_path,
        data=data,
        print_output=print_output,
        trade_matching_mode=trade_matching_mode,
        show_progress_bar=show_progress_bar,
    )


def print_day_summary(result: BacktestResult) -> None:
    if not result.activity_logs:
        print("No activity logs produced")
        return

    last_timestamp = result.activity_logs[-1].timestamp
    product_lines: List[str] = []
    total_profit = 0.0

    for row in reversed(result.activity_logs):
        if row.timestamp != last_timestamp:
            break
        product = str(row.columns[2])
        profit = float(row.columns[-1])
        product_lines.append(f"{product}: {profit:,.0f}")
        total_profit += profit

    print(*reversed(product_lines), sep="\n")
    print(f"Total profit: {total_profit:,.0f}")


def print_overall_summary(results: Sequence[BacktestResult]) -> None:
    print("Profit summary:")
    total_profit = 0.0
    for result in results:
        if not result.activity_logs:
            print(f"Round {result.round_num} day {result.day_num}: 0")
            continue
        last_timestamp = result.activity_logs[-1].timestamp
        profit = 0.0
        for row in reversed(result.activity_logs):
            if row.timestamp != last_timestamp:
                break
            profit += float(row.columns[-1])
        print(f"Round {result.round_num} day {result.day_num}: {profit:,.0f}")
        total_profit += profit
    print(f"Total profit: {total_profit:,.0f}")


def print_intraday_drawdown_report(
    results: Sequence[BacktestResult], threshold: float = 30_000.0
) -> None:
    """Surface mid-day correlated drawdowns that EOD totals hide.

    R3 day-3 reveal lost -74,894 in one 100k-ts bucket as VFE swung and every
    delta-1 voucher marked against position simultaneously. Training days
    0/1/2 EOD totals showed nothing wrong because each closed positive.

    See tools/intraday_drawdown_report.py for the standalone CLI.
    """
    try:
        from intraday_drawdown_report import (  # type: ignore
            Row,
            compute_drawdown_report,
            format_report,
        )
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from intraday_drawdown_report import (  # type: ignore
            Row,
            compute_drawdown_report,
            format_report,
        )

    rows: List["Row"] = []
    for result in results:
        for log_row in result.activity_logs:
            cols = log_row.columns
            try:
                rows.append(
                    Row(
                        day=int(cols[0]),
                        timestamp=int(cols[1]),
                        product=str(cols[2]),
                        pnl=float(cols[-1]) if cols[-1] not in (None, "") else 0.0,
                    )
                )
            except (ValueError, IndexError):
                continue

    if not rows:
        return

    buckets = compute_drawdown_report(rows)
    print()
    print(format_report(buckets, threshold=threshold))


def merge_results(
    left: BacktestResult,
    right: BacktestResult,
    merge_profit_loss: bool,
    merge_timestamps: bool,
) -> BacktestResult:
    sandbox_logs = left.sandbox_logs[:]
    activity_logs = left.activity_logs[:]
    trades = left.trades[:]

    if not left.activity_logs:
        left_last_timestamp = 0
    else:
        left_last_timestamp = left.activity_logs[-1].timestamp

    timestamp_offset = left_last_timestamp + 100 if merge_timestamps else 0

    sandbox_logs.extend(row.with_offset(timestamp_offset) for row in right.sandbox_logs)
    trades.extend(row.with_offset(timestamp_offset) for row in right.trades)

    profit_offsets: Dict[str, float] = {}
    if merge_profit_loss and left.activity_logs:
        for row in reversed(left.activity_logs):
            if row.timestamp != left_last_timestamp:
                break
            profit_offsets[str(row.columns[2])] = float(row.columns[-1])

    for row in right.activity_logs:
        product = str(row.columns[2])
        activity_logs.append(
            row.with_offset(timestamp_offset, profit_offsets.get(product, 0.0))
        )

    return BacktestResult(
        round_num=left.round_num,
        day_num=left.day_num,
        sandbox_logs=sandbox_logs,
        activity_logs=activity_logs,
        trades=trades,
    )


def write_output(output_file: Path, merged_results: BacktestResult) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as handle:
        handle.write("Sandbox logs:\n")
        for row in merged_results.sandbox_logs:
            handle.write(str(row))

        handle.write("\n\n\nActivities log:\n")
        handle.write(
            "day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;mid_price;profit_and_loss\n"
        )
        handle.write("\n".join(str(row) for row in merged_results.activity_logs))

        handle.write("\n\n\n\n\nTrade History:\n")
        handle.write("[\n")
        handle.write(",\n".join(str(row) for row in merged_results.trades))
        handle.write("]")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    strategy_path = Path(args.strategy).expanduser().resolve()
    data_root = Path(args.data).expanduser().resolve()

    if args.out and args.no_out:
        raise ValueError("--out and --no-out are mutually exclusive")
    if not strategy_path.exists():
        raise FileNotFoundError(f"Strategy file not found: {strategy_path}")
    if not data_root.exists():
        raise FileNotFoundError(f"Data root not found: {data_root}")

    parsed_days = parse_days(data_root, args.days)
    output_file = parse_output_path(args.out, args.no_out)
    show_progress_bars = not bool(args.no_progress) and not bool(args.print_output)
    trade_matching_mode = TradeMatchingMode(str(args.match_trades))

    results: List[BacktestResult] = []
    for round_num, day_num in parsed_days:
        print(f"Backtesting {strategy_path} on round {round_num} day {day_num}")
        result = run_backtest(
            strategy_path=strategy_path,
            data_root=data_root,
            round_num=round_num,
            day_num=day_num,
            print_output=bool(args.print_output),
            trade_matching_mode=trade_matching_mode,
            show_progress_bar=show_progress_bars,
        )
        print_day_summary(result)
        if len(parsed_days) > 1:
            print()
        results.append(result)

    if len(parsed_days) > 1:
        print_overall_summary(results)

    if results:
        print_intraday_drawdown_report(results)

    if output_file is not None and results:
        merged_result = reduce(
            lambda left, right: merge_results(
                left,
                right,
                bool(args.merge_pnl),
                not bool(args.original_timestamps),
            ),
            results,
        )
        write_output(output_file, merged_result)
        print(f"\nSuccessfully saved backtest results to {format_path(output_file)}")

    if bool(args.vis) and output_file is not None:
        open_visualizer(output_file)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
