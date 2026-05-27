from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("visualizer_config.json")


@dataclass
class Theme:
    dpi: int = 160
    font_size: int = 10
    title_size: int = 12
    label_size: int = 9


@dataclass
class VisualizerConfig:
    data_dir: Path
    output_dir: Path
    group_output: bool
    symbols: List[str]
    max_points: int
    min_trade_qty: Optional[float]
    max_trade_qty: Optional[float]
    impact_horizons: List[int]
    rolling_window: int
    normalize_by: Optional[str]
    ema_windows: List[int]
    theme: Theme
    backtest_path: Optional[Path]
    log_file: Optional[Path]
    log_max_rows: int
    indicator_file: Optional[Path]
    indicator_columns: List[str]
    small_trade_qty: Optional[float]
    big_trade_qty: Optional[float]
    own_trade_tags: List[str]
    informed_traders: List[str]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an IMC Prosperity visualizer report.")
    parser.add_argument("--config", type=Path, default=None, help="Path to a JSON config.")
    parser.add_argument("--data-dir", type=Path, default=None, help="Directory with prices_*.csv and trades_*.csv.")
    parser.add_argument("--output", type=Path, default=None, help="Output directory for the report.")
    parser.add_argument(
        "--group-output",
        action="store_true",
        help="Write outputs under a subdirectory named after the data dir (e.g. output/round1).",
    )
    parser.add_argument("--symbols", nargs="*", default=None, help="Limit to specific symbols.")
    parser.add_argument("--max-points", type=int, default=None, help="Max points to plot for dense series.")
    parser.add_argument("--min-trade-qty", type=float, default=None, help="Filter trades below this size.")
    parser.add_argument("--max-trade-qty", type=float, default=None, help="Filter trades above this size.")
    parser.add_argument("--backtest", type=Path, default=None, help="Optional backtest run or dataset dir.")
    parser.add_argument("--log-file", type=Path, default=None, help="Optional log file (csv/jsonl/plain text).")
    parser.add_argument("--log-max-rows", type=int, default=None, help="Max log rows to render in report.")
    parser.add_argument("--indicator-file", type=Path, default=None, help="Optional indicator file (csv/jsonl/plain text).")
    parser.add_argument("--indicator-columns", nargs="*", default=None, help="Indicator columns to overlay.")
    parser.add_argument("--small-trade-qty", type=float, default=None, help="Max qty for 'small' taker.")
    parser.add_argument("--big-trade-qty", type=float, default=None, help="Min qty for 'big' taker.")
    parser.add_argument("--own-trade-tags", nargs="*", default=None, help="Tags indicating our own trades.")
    parser.add_argument("--informed-traders", nargs="*", default=None, help="Trader IDs tagged as informed.")
    return parser.parse_args(argv)


def load_config(args: argparse.Namespace) -> VisualizerConfig:
    config_path = args.config if args.config else DEFAULT_CONFIG
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    raw = json.loads(config_path.read_text())

    def _path(value: Optional[str]) -> Optional[Path]:
        if value is None:
            return None
        return Path(value).expanduser()

    theme_raw = raw.get("theme", {})
    theme = Theme(
        dpi=int(theme_raw.get("dpi", 160)),
        font_size=int(theme_raw.get("font_size", 10)),
        title_size=int(theme_raw.get("title_size", 12)),
        label_size=int(theme_raw.get("label_size", 9)),
    )

    data_dir = _path(raw.get("data_dir")) or REPO_ROOT / "data"
    output_dir = _path(raw.get("output_dir")) or REPO_ROOT / "analysis" / "visualizer_report"
    group_output = bool(raw.get("group_output", False))

    if args.data_dir is not None:
        data_dir = args.data_dir
    if args.output is not None:
        output_dir = args.output
    if args.group_output:
        group_output = True

    symbols = raw.get("symbols", [])
    if args.symbols is not None:
        symbols = args.symbols

    max_points = int(raw.get("max_points", 20000))
    if args.max_points is not None:
        max_points = args.max_points

    min_trade_qty = raw.get("min_trade_qty")
    if args.min_trade_qty is not None:
        min_trade_qty = args.min_trade_qty

    max_trade_qty = raw.get("max_trade_qty")
    if args.max_trade_qty is not None:
        max_trade_qty = args.max_trade_qty

    impact_horizons = [int(x) for x in raw.get("impact_horizons", [1, 5, 10])]
    rolling_window = int(raw.get("rolling_window", 20))
    normalize_by = raw.get("normalize_by", None)
    ema_windows = [int(x) for x in raw.get("ema_windows", [])]

    backtest_path = _path(raw.get("backtest_path"))
    if args.backtest is not None:
        backtest_path = args.backtest

    log_file = _path(raw.get("log_file"))
    if args.log_file is not None:
        log_file = args.log_file

    log_max_rows = int(raw.get("log_max_rows", 200))
    if args.log_max_rows is not None:
        log_max_rows = args.log_max_rows

    indicator_file = _path(raw.get("indicator_file"))
    if args.indicator_file is not None:
        indicator_file = args.indicator_file

    indicator_columns = raw.get("indicator_columns", [])
    if args.indicator_columns is not None:
        indicator_columns = args.indicator_columns

    small_trade_qty = raw.get("small_trade_qty")
    if args.small_trade_qty is not None:
        small_trade_qty = args.small_trade_qty

    big_trade_qty = raw.get("big_trade_qty")
    if args.big_trade_qty is not None:
        big_trade_qty = args.big_trade_qty

    own_trade_tags = raw.get("own_trade_tags", ["SUBMISSION"])
    if args.own_trade_tags is not None:
        own_trade_tags = args.own_trade_tags

    informed_traders = raw.get("informed_traders", [])
    if args.informed_traders is not None:
        informed_traders = args.informed_traders

    return VisualizerConfig(
        data_dir=data_dir,
        output_dir=output_dir,
        group_output=group_output,
        symbols=symbols,
        max_points=max_points,
        min_trade_qty=min_trade_qty,
        max_trade_qty=max_trade_qty,
        impact_horizons=impact_horizons,
        rolling_window=rolling_window,
        normalize_by=normalize_by,
        ema_windows=ema_windows,
        theme=theme,
        backtest_path=backtest_path,
        log_file=log_file,
        log_max_rows=log_max_rows,
        indicator_file=indicator_file,
        indicator_columns=indicator_columns,
        small_trade_qty=small_trade_qty,
        big_trade_qty=big_trade_qty,
        own_trade_tags=own_trade_tags,
        informed_traders=informed_traders,
    )


def apply_theme(theme: Theme) -> None:
    plt.style.use("ggplot")
    plt.rcParams.update(
        {
            "figure.dpi": theme.dpi,
            "font.size": theme.font_size,
            "axes.titlesize": theme.title_size,
            "axes.labelsize": theme.label_size,
            "legend.fontsize": theme.label_size,
            "xtick.labelsize": theme.label_size,
            "ytick.labelsize": theme.label_size,
            "axes.grid": True,
        }
    )


def discover_files(data_dir: Path, prefix: str) -> List[Path]:
    return sorted(data_dir.glob(f"{prefix}*.csv"))


def parse_day_from_name(path: Path) -> Optional[int]:
    name = path.name
    for part in name.split("_"):
        if part == "day":
            continue
    import re

    match = re.search(r"day_(-?\d+)", name)
    if match:
        return int(match.group(1))
    return None


def ensure_columns(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for col in columns:
        if col not in frame.columns:
            frame[col] = np.nan
    return frame


def prepare_prices(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return prices

    needed = [
        "bid_price_1",
        "bid_volume_1",
        "bid_price_2",
        "bid_volume_2",
        "bid_price_3",
        "bid_volume_3",
        "ask_price_1",
        "ask_volume_1",
        "ask_price_2",
        "ask_volume_2",
        "ask_price_3",
        "ask_volume_3",
        "mid_price",
    ]
    prices = ensure_columns(prices, needed)

    numeric_cols = [col for col in prices.columns if col not in {"product", "symbol", "source_file"}]
    for col in numeric_cols:
        prices[col] = pd.to_numeric(prices[col], errors="coerce")

    if "product" in prices.columns and "symbol" not in prices.columns:
        prices = prices.rename(columns={"product": "symbol"})
    prices["symbol"] = prices["symbol"].astype(str)

    # Some datasets encode missing mid_price as 0 while bid/ask are NaN.
    # Treat those as missing to avoid distorted axes.
    if "mid_price" in prices.columns:
        missing_mid = (prices["mid_price"] == 0) & prices["bid_price_1"].isna() & prices["ask_price_1"].isna()
        prices.loc[missing_mid, "mid_price"] = np.nan
        mid_from_touch = prices["mid_price"].isna() & prices["bid_price_1"].notna() & prices["ask_price_1"].notna()
        prices.loc[mid_from_touch, "mid_price"] = (
            prices.loc[mid_from_touch, "bid_price_1"] + prices.loc[mid_from_touch, "ask_price_1"]
        ) / 2.0

    # Outer-wall mid: midpoint of the widest visible prices (min bid, max ask).
    prices["outer_bid"] = prices[["bid_price_1", "bid_price_2", "bid_price_3"]].min(axis=1, skipna=True)
    prices["outer_ask"] = prices[["ask_price_1", "ask_price_2", "ask_price_3"]].max(axis=1, skipna=True)
    prices["wall_mid_outer"] = (prices["outer_bid"] + prices["outer_ask"]) / 2.0

    prices["spread"] = prices["ask_price_1"] - prices["bid_price_1"]
    prices["top3_bid_volume"] = prices[["bid_volume_1", "bid_volume_2", "bid_volume_3"]].sum(axis=1, skipna=True)
    prices["top3_ask_volume"] = prices[["ask_volume_1", "ask_volume_2", "ask_volume_3"]].sum(axis=1, skipna=True)
    denom = prices["top3_bid_volume"] + prices["top3_ask_volume"]
    prices["book_imbalance"] = np.where(denom != 0, (prices["top3_bid_volume"] - prices["top3_ask_volume"]) / denom, np.nan)

    prices["wall_bid"] = select_wall_price(
        prices[["bid_price_1", "bid_price_2", "bid_price_3"]],
        prices[["bid_volume_1", "bid_volume_2", "bid_volume_3"]],
        fallback=prices["bid_price_1"],
    )
    prices["wall_ask"] = select_wall_price(
        prices[["ask_price_1", "ask_price_2", "ask_price_3"]],
        prices[["ask_volume_1", "ask_volume_2", "ask_volume_3"]],
        fallback=prices["ask_price_1"],
    )
    prices["wall_mid"] = (prices["wall_bid"] + prices["wall_ask"]) / 2.0

    return prices


def load_prices(files: Sequence[Path]) -> pd.DataFrame:
    frames = []
    for file in files:
        df = pd.read_csv(file, sep=";")
        if "day" not in df.columns:
            day = parse_day_from_name(file)
            if day is None:
                raise ValueError(f"Missing day in {file}")
            df["day"] = day
        df["source_file"] = file.name
        frames.append(df)
    prices = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return prepare_prices(prices)


def select_wall_price(price_frame: pd.DataFrame, volume_frame: pd.DataFrame, fallback: pd.Series) -> pd.Series:
    volumes = volume_frame.fillna(-1).to_numpy()
    prices = price_frame.to_numpy()
    idx = volumes.argmax(axis=1)
    selected = prices[np.arange(len(prices)), idx]
    selected = pd.Series(selected, index=price_frame.index)
    selected = selected.where(~selected.isna(), fallback)
    return selected


def load_trades(files: Sequence[Path]) -> pd.DataFrame:
    frames = []
    for file in files:
        df = pd.read_csv(file, sep=";")
        if "day" not in df.columns:
            day = parse_day_from_name(file)
            if day is None:
                raise ValueError(f"Missing day in {file}")
            df["day"] = day
        df["source_file"] = file.name
        frames.append(df)
    trades = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return prepare_trades(trades)


def prepare_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades
    trades = trades.rename(columns={"symbol": "symbol"})
    trades["symbol"] = trades["symbol"].astype(str)
    for col in ["timestamp", "price", "quantity", "day"]:
        if col in trades.columns:
            trades[col] = pd.to_numeric(trades[col], errors="coerce")
    trades["notional"] = trades["price"] * trades["quantity"]
    return trades


def add_global_time(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    days = sorted(frame["day"].dropna().unique().tolist())
    day_index = {day: idx for idx, day in enumerate(days)}
    max_ts = frame["timestamp"].max()
    span = int(max_ts + 1) if not math.isnan(max_ts) else 1
    frame = frame.copy()
    frame["global_time"] = frame["day"].map(day_index).astype(float) * span + frame["timestamp"].astype(float)
    return frame


def filter_symbols(frame: pd.DataFrame, symbols: List[str]) -> pd.DataFrame:
    if not symbols:
        return frame
    wanted = {s.upper() for s in symbols}
    return frame[frame["symbol"].str.upper().isin(wanted)].copy()


def filter_trades_by_size(trades: pd.DataFrame, min_qty: Optional[float], max_qty: Optional[float]) -> pd.DataFrame:
    if trades.empty:
        return trades
    filtered = trades
    if min_qty is not None:
        filtered = filtered[filtered["quantity"] >= min_qty]
    if max_qty is not None:
        filtered = filtered[filtered["quantity"] <= max_qty]
    return filtered


def downsample(frame: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if frame.empty or len(frame) <= max_points:
        return frame
    step = max(1, int(len(frame) / max_points))
    return frame.iloc[::step].copy()


def align_trades_to_book(
    trades: pd.DataFrame,
    book: pd.DataFrame,
    horizons: Sequence[int],
) -> pd.DataFrame:
    if trades.empty or book.empty:
        return trades

    aligned_parts: List[pd.DataFrame] = []
    for (symbol, day), trades_part in trades.groupby(["symbol", "day"], sort=False):
        book_part = book[(book["symbol"] == symbol) & (book["day"] == day)].sort_values("timestamp").copy()
        if book_part.empty:
            continue
        book_part = book_part.reset_index(drop=True)
        book_part["book_index"] = np.arange(len(book_part))

        trades_part = trades_part.sort_values("timestamp").copy()
        merged = pd.merge_asof(
            trades_part,
            book_part,
            on="timestamp",
            direction="backward",
            suffixes=("", "_book"),
        )
        merged["book_index"] = merged["book_index"].astype("Int64")

        mid_series = book_part.set_index("book_index")["mid_price"]
        bid_series = book_part.set_index("book_index")["bid_price_1"]
        ask_series = book_part.set_index("book_index")["ask_price_1"]
        top_bid_series = book_part.set_index("book_index")["top3_bid_volume"]
        top_ask_series = book_part.set_index("book_index")["top3_ask_volume"]

        for horizon in horizons:
            future_index = merged["book_index"] + horizon
            merged[f"mid_plus_{horizon}"] = mid_series.reindex(future_index).to_numpy()

        merged["next_top3_bid"] = top_bid_series.reindex(merged["book_index"] + 1).to_numpy()
        merged["next_top3_ask"] = top_ask_series.reindex(merged["book_index"] + 1).to_numpy()
        merged["bid_at_trade"] = bid_series.reindex(merged["book_index"]).to_numpy()
        merged["ask_at_trade"] = ask_series.reindex(merged["book_index"]).to_numpy()

        merged["aggressor"] = merged.apply(classify_aggressor, axis=1)
        aligned_parts.append(merged)

    if not aligned_parts:
        return trades
    aligned = pd.concat(aligned_parts, ignore_index=True)
    return aligned


def classify_aggressor(row: pd.Series) -> str:
    price = row.get("price")
    bid = row.get("bid_at_trade")
    ask = row.get("ask_at_trade")
    mid = row.get("mid_price")
    if pd.notna(ask) and pd.notna(price) and price >= ask:
        return "buy"
    if pd.notna(bid) and pd.notna(price) and price <= bid:
        return "sell"
    if pd.notna(mid) and pd.notna(price):
        if price > mid:
            return "buy"
        if price < mid:
            return "sell"
    return "unknown"


def compute_ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def plot_mid_and_spread(book: pd.DataFrame, symbol: str, output: Path, ema_windows: Sequence[int]) -> None:
    subset = book[book["symbol"] == symbol].sort_values("global_time")
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    axes[0].plot(subset["global_time"], subset["mid_price"], color="#1f77b4", label="Mid")
    for window in ema_windows:
        axes[0].plot(subset["global_time"], compute_ema(subset["mid_price"], window), label=f"EMA {window}")
    axes[0].plot(subset["global_time"], subset["wall_mid"], color="#2ca02c", alpha=0.7, label="Wall mid")
    axes[0].set_title(f"{symbol} mid price")
    axes[0].set_ylabel("Price")
    axes[0].legend(loc="best")

    axes[1].plot(subset["global_time"], subset["spread"], color="#d62728", label="Spread")
    axes[1].set_ylabel("Spread")
    axes[1].set_xlabel("Time")
    axes[1].legend(loc="best")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_normalized_mid(book: pd.DataFrame, symbol: str, output: Path, normalize_by: str) -> None:
    subset = book[book["symbol"] == symbol].sort_values("global_time")
    if normalize_by not in subset.columns:
        return
    base = subset[normalize_by]
    if base.isna().all():
        return
    normalized = subset["mid_price"] - base
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(subset["global_time"], normalized, color="#2ca02c")
    ax.axhline(0, color="#666", linewidth=1)
    ax.set_title(f"{symbol} mid normalized by {normalize_by}")
    ax.set_xlabel("Time")
    ax.set_ylabel("Mid - baseline")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_orderbook_scatter(
    book: pd.DataFrame,
    trades: pd.DataFrame,
    symbol: str,
    output: Path,
    max_points: int,
) -> None:
    subset = book[book["symbol"] == symbol].sort_values("global_time")
    subset = downsample(subset, max_points)
    if subset.empty:
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    for level in [1, 2, 3]:
        bid_price = subset.get(f"bid_price_{level}")
        bid_volume = subset.get(f"bid_volume_{level}")
        ask_price = subset.get(f"ask_price_{level}")
        ask_volume = subset.get(f"ask_volume_{level}")
        if bid_price is not None:
            ax.scatter(
                subset["global_time"],
                bid_price,
                s=np.clip((bid_volume.fillna(0).to_numpy() * 6), 8, 80),
                color="#1f77b4",
                alpha=0.5,
            )
        if ask_price is not None:
            ax.scatter(
                subset["global_time"],
                ask_price,
                s=np.clip((ask_volume.fillna(0).to_numpy() * 6), 8, 80),
                color="#d62728",
                alpha=0.5,
            )

    aligned = trades[trades["symbol"] == symbol] if not trades.empty else pd.DataFrame()
    if not aligned.empty:
        marker_map = {"buy": "^", "sell": "v", "unknown": "o"}
        color_map = {"buy": "#2ca02c", "sell": "#ff7f0e", "unknown": "#7f7f7f"}
        for side, group in aligned.groupby("aggressor"):
            ax.scatter(
                group["global_time"],
                group["price"],
                s=np.clip(group["quantity"].abs().to_numpy() * 10, 12, 120),
                marker=marker_map.get(side, "o"),
                color=color_map.get(side, "#7f7f7f"),
                edgecolor="black",
                linewidth=0.3,
                label=f"Trade {side}",
            )

    ax.set_title(f"{symbol} order book & trades")
    ax.set_xlabel("Time")
    ax.set_ylabel("Price")
    if not aligned.empty:
        ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_book_depth(book: pd.DataFrame, symbol: str, output: Path) -> None:
    subset = book[book["symbol"] == symbol].sort_values("global_time")
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    axes[0].plot(subset["global_time"], subset["top3_bid_volume"], label="Top3 bid")
    axes[0].plot(subset["global_time"], subset["top3_ask_volume"], label="Top3 ask")
    axes[0].set_title(f"{symbol} depth")
    axes[0].set_ylabel("Volume")
    axes[0].legend(loc="best")

    axes[1].plot(subset["global_time"], subset["book_imbalance"], color="#9467bd", label="Imbalance")
    axes[1].axhline(0, color="#666", linewidth=1)
    axes[1].set_ylabel("Imbalance")
    axes[1].set_xlabel("Time")
    axes[1].legend(loc="best")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_top_level_volume(book: pd.DataFrame, symbol: str, output: Path) -> None:
    subset = book[book["symbol"] == symbol].sort_values("global_time")
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(subset["global_time"], subset["bid_volume_1"], label="Bid vol L1")
    ax.plot(subset["global_time"], subset["ask_volume_1"], label="Ask vol L1")
    ax.set_title(f"{symbol} level-1 volumes")
    ax.set_xlabel("Time")
    ax.set_ylabel("Volume")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_trade_size(trades: pd.DataFrame, symbol: str, output: Path) -> None:
    subset = trades[trades["symbol"] == symbol]
    if subset.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(subset["quantity"].abs(), bins=30, color="#4C72B0", alpha=0.8)
    ax.set_title(f"{symbol} trade size distribution")
    ax.set_xlabel("Quantity")
    ax.set_ylabel("Count")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_trade_interarrival(trades: pd.DataFrame, symbol: str, output: Path) -> None:
    subset = trades[trades["symbol"] == symbol].sort_values(["day", "timestamp"])
    if subset.empty:
        return
    subset = subset.copy()
    subset["time_diff"] = subset.groupby("day")["timestamp"].diff()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(subset["time_diff"].dropna(), bins=30, color="#55A868", alpha=0.8)
    ax.set_title(f"{symbol} time between trades")
    ax.set_xlabel("Time diff")
    ax.set_ylabel("Count")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_trade_impact(trades: pd.DataFrame, symbol: str, horizons: Sequence[int], output: Path) -> None:
    subset = trades[trades["symbol"] == symbol]
    if subset.empty:
        return

    rows = []
    for horizon in horizons:
        col = f"mid_plus_{horizon}"
        if col not in subset.columns:
            continue
        impact = subset[col] - subset["mid_price"]
        for side in ["buy", "sell", "unknown"]:
            side_imp = impact[subset["aggressor"] == side]
            rows.append({"horizon": horizon, "side": side, "avg_impact": side_imp.mean()})

    if not rows:
        return
    frame = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(8, 4))
    for side, group in frame.groupby("side"):
        ax.plot(group["horizon"], group["avg_impact"], marker="o", label=side)
    ax.axhline(0, color="#666", linewidth=1)
    ax.set_title(f"{symbol} short-horizon price impact")
    ax.set_xlabel("Horizon (book ticks)")
    ax.set_ylabel("Avg price change")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_replenishment(trades: pd.DataFrame, symbol: str, output: Path) -> None:
    subset = trades[trades["symbol"] == symbol]
    if subset.empty:
        return
    subset = subset.copy()
    subset["bid_replenish"] = subset["next_top3_bid"] / subset["top3_bid_volume"]
    subset["ask_replenish"] = subset["next_top3_ask"] / subset["top3_ask_volume"]
    # Filter non-finite replenishment ratios (e.g., zero volume).
    for col in ("bid_replenish", "ask_replenish"):
        subset[col] = subset[col].replace([np.inf, -np.inf], np.nan)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(subset["bid_replenish"].dropna(), bins=30, alpha=0.6, label="Bid replenish")
    ax.hist(subset["ask_replenish"].dropna(), bins=30, alpha=0.6, label="Ask replenish")
    ax.set_title(f"{symbol} top-of-book replenishment")
    ax.set_xlabel("Next / current volume")
    ax.set_ylabel("Count")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_return_distribution(book: pd.DataFrame, symbol: str, output: Path, window: int) -> None:
    subset = book[book["symbol"] == symbol].sort_values("global_time")
    if subset.empty:
        return
    returns = subset["mid_price"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if returns.empty:
        return
    vol = returns.rolling(window).std() * math.sqrt(window)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].hist(returns, bins=40, color="#8172B2", alpha=0.8)
    axes[0].set_title(f"{symbol} return distribution")
    axes[0].set_xlabel("Return")
    axes[0].set_ylabel("Count")

    axes[1].plot(subset["global_time"].iloc[-len(vol):], vol, color="#C44E52")
    axes[1].set_title(f"{symbol} rolling volatility ({window})")
    axes[1].set_xlabel("Time")
    axes[1].set_ylabel("Volatility")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_correlation_heatmap(book: pd.DataFrame, output: Path) -> None:
    pivot = book.pivot_table(index=["day", "timestamp"], columns="symbol", values="mid_price")
    returns = pivot.pct_change().dropna(how="all")
    if returns.empty:
        return
    corr = returns.corr()
    fig, ax = plt.subplots(figsize=(6 + 0.5 * len(corr), 6))
    im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(corr.columns)))
    ax.set_yticklabels(corr.columns)
    for i in range(len(corr.columns)):
        for j in range(len(corr.columns)):
            ax.text(j, i, f"{corr.iloc[i, j]:.2f}", ha="center", va="center", color="black")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    ax.set_title("Return correlation")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def load_backtest(backtest_path: Path) -> List[Path]:
    if not backtest_path.exists():
        return []
    if backtest_path.is_dir() and (backtest_path / "equity_curve.csv").exists():
        return [backtest_path]
    if backtest_path.is_dir():
        dataset_dirs = [d for d in backtest_path.iterdir() if d.is_dir() and (d / "equity_curve.csv").exists()]
        return sorted(dataset_dirs)
    return []


def plot_equity_curve(equity: pd.DataFrame, output: Path, title: str) -> None:
    if equity.empty:
        return
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    axes[0].plot(equity["step"], equity["total_pnl"], label="Total PnL", color="#1f77b4")
    if "realized_pnl" in equity.columns:
        axes[0].plot(equity["step"], equity["realized_pnl"], label="Realized", color="#2ca02c")
    if "unrealized_pnl" in equity.columns:
        axes[0].plot(equity["step"], equity["unrealized_pnl"], label="Unrealized", color="#ff7f0e")
    axes[0].set_title(title)
    axes[0].set_ylabel("PnL")
    axes[0].legend(loc="best")

    running_max = equity["total_pnl"].cummax()
    drawdown = equity["total_pnl"] - running_max
    axes[1].fill_between(equity["step"], drawdown, 0, color="#d62728", alpha=0.35)
    axes[1].set_xlabel("Step")
    axes[1].set_ylabel("Drawdown")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_positions(equity: pd.DataFrame, output: Path) -> None:
    if equity.empty:
        return
    pos_cols = [col for col in equity.columns if col.startswith("position_")]
    if not pos_cols:
        return
    fig, axes = plt.subplots(len(pos_cols), 1, figsize=(12, 3 * len(pos_cols)), sharex=True)
    if len(pos_cols) == 1:
        axes = [axes]
    for ax, col in zip(axes, pos_cols):
        ax.plot(equity["step"], equity[col], label=col.replace("position_", ""))
        ax.axhline(0, color="#666", linewidth=1)
        ax.set_ylabel("Position")
        ax.legend(loc="best")
    axes[-1].set_xlabel("Step")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_symbol_pnl(equity: pd.DataFrame, output: Path) -> None:
    if equity.empty:
        return
    pnl_cols = [col for col in equity.columns if col.startswith("pnl_")]
    if not pnl_cols:
        return
    fig, axes = plt.subplots(len(pnl_cols), 1, figsize=(12, 3 * len(pnl_cols)), sharex=True)
    if len(pnl_cols) == 1:
        axes = [axes]
    for ax, col in zip(axes, pnl_cols):
        ax.plot(equity["step"], equity[col], label=col.replace("pnl_", ""))
        ax.axhline(0, color="#666", linewidth=1)
        ax.set_ylabel("PnL")
        ax.legend(loc="best")
    axes[-1].set_xlabel("Step")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def plot_fills(fills: pd.DataFrame, equity: pd.DataFrame, output: Path) -> None:
    if fills.empty or equity.empty:
        return
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(equity["step"], equity["total_pnl"], color="#1f77b4", label="Total PnL")
    buys = fills[fills["side"] == "buy"]
    sells = fills[fills["side"] == "sell"]
    ax.scatter(buys["step"], buys["price"], color="#2ca02c", marker="^", label="Buy fills")
    ax.scatter(sells["step"], sells["price"], color="#d62728", marker="v", label="Sell fills")
    ax.set_title("PnL with fills")
    ax.set_xlabel("Step")
    ax.set_ylabel("Price / PnL")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def render_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "<p>No data</p>"
    return df.to_html(index=False, classes="dataframe", border=0)


def load_log_entries(log_path: Path) -> pd.DataFrame:
    if not log_path.exists():
        return pd.DataFrame()
    suffix = log_path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(log_path)
    elif suffix in {".jsonl", ".json"}:
        rows = []
        with log_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        df = pd.DataFrame(rows)
    else:
        rows = []
        with log_path.open() as f:
            for line in f:
                line = line.rstrip()
                if not line:
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) == 2 and parts[0].isdigit():
                    rows.append({"timestamp": int(parts[0]), "message": parts[1]})
                else:
                    rows.append({"message": line})
        df = pd.DataFrame(rows)

    if df.empty:
        return df

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
        df = df.sort_values("timestamp")
    return df


def load_indicator_entries(indicator_path: Path) -> pd.DataFrame:
    if not indicator_path.exists():
        return pd.DataFrame()
    suffix = indicator_path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(indicator_path)
    elif suffix in {".jsonl", ".json"}:
        rows = []
        with indicator_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        df = pd.DataFrame(rows)
    else:
        return pd.DataFrame()

    if df.empty:
        return df

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    if "day" in df.columns:
        df["day"] = pd.to_numeric(df["day"], errors="coerce")
    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].astype(str)
    return df


def write_report(
    output_dir: Path, sections: List[Tuple[str, str]], generated_at: str, title_suffix: Optional[str] = None
) -> None:
    def slugify(value: str) -> str:
        safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
        while "--" in safe:
            safe = safe.replace("--", "-")
        return safe.strip("-") or "section"

    nav = "".join(f'<li><a href="#{slugify(title)}">{title}</a></li>' for title, _ in sections)
    body = "".join(
        f"<section id=\"{slugify(title)}\">\n<h2>{title}</h2>\n{content}\n</section>"
        for title, content in sections
    )
    title = "Prosperity Visualizer Report"
    if title_suffix:
        title = f"{title} - {title_suffix}"
    html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>{title}</title>
  <style>
    body {{ font-family: 'Helvetica Neue', Arial, sans-serif; margin: 24px; background: #fafafa; color: #222; }}
    h1 {{ margin-bottom: 8px; }}
    h2 {{ margin-top: 32px; border-bottom: 2px solid #ddd; padding-bottom: 6px; }}
    .meta {{ color: #666; font-size: 0.9rem; margin-bottom: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }}
    figure {{ margin: 0; background: #fff; border: 1px solid #e0e0e0; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
    img {{ max-width: 100%; height: auto; }}
    table.dataframe {{ border-collapse: collapse; width: 100%; margin-bottom: 16px; }}
    table.dataframe th, table.dataframe td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: right; }}
    table.dataframe th {{ background: #f3f3f3; text-align: center; }}
    nav ul {{ list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 12px; }}
    nav a {{ text-decoration: none; color: #1f77b4; }}
    section {{ background: #fff; padding: 16px; border: 1px solid #e6e6e6; margin-bottom: 24px; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <div class=\"meta\">Generated {generated_at}</div>
  <nav><ul>{nav}</ul></nav>
  {body}
</body>
</html>"""
    (output_dir / "report.html").write_text(html)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    config = load_config(args)
    apply_theme(config.theme)

    data_dir = config.data_dir.expanduser().resolve()
    output_dir = config.output_dir.expanduser().resolve()
    if config.group_output:
        output_dir = output_dir / data_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)

    price_files = discover_files(data_dir, "prices")
    trade_files = discover_files(data_dir, "trades")
    if not price_files:
        raise FileNotFoundError(f"No price files found in {data_dir}")

    prices = load_prices(price_files)
    trades = load_trades(trade_files) if trade_files else pd.DataFrame()

    prices = filter_symbols(prices, config.symbols)
    trades = filter_symbols(trades, config.symbols)

    prices = add_global_time(prices)
    trades = add_global_time(trades) if not trades.empty else trades

    trades = filter_trades_by_size(trades, config.min_trade_qty, config.max_trade_qty)
    aligned_trades = align_trades_to_book(trades, prices, config.impact_horizons) if not trades.empty else trades
    if not aligned_trades.empty:
        aligned_trades = add_global_time(aligned_trades)

    sections: List[Tuple[str, str]] = []

    summary = pd.DataFrame(
        {
            "symbols": [", ".join(sorted(prices["symbol"].unique()))],
            "days": [", ".join(str(d) for d in sorted(prices["day"].unique()))],
            "book_rows": [len(prices)],
            "trade_rows": [len(trades)],
        }
    )
    if not trades.empty and "buyer" in trades.columns and "seller" in trades.columns:
        summary["missing_buyer_pct"] = [float(trades["buyer"].isna().mean())]
        summary["missing_seller_pct"] = [float(trades["seller"].isna().mean())]
    trade_summary = (
        aligned_trades.groupby(["symbol", "aggressor"]).agg(trades=("quantity", "size"), notional=("notional", "sum")).reset_index()
        if not aligned_trades.empty
        else pd.DataFrame()
    )
    spread_summary = (
        prices.groupby("symbol")["spread"].agg(["mean", "median", "min", "max"]).reset_index()
        if not prices.empty
        else pd.DataFrame()
    )

    summary_html = render_table(summary) + render_table(spread_summary) + render_table(trade_summary)
    sections.append(("Overview", summary_html))

    if config.log_file:
        log_entries = load_log_entries(config.log_file)
        if not log_entries.empty:
            trimmed = log_entries.tail(config.log_max_rows)
            sections.append(("Logs", render_table(trimmed)))

    corr_path = output_dir / "correlation_heatmap.png"
    plot_correlation_heatmap(prices, corr_path)
    sections.append(
        (
            "Cross-Asset",
            f"<figure><img src=\"{corr_path.name}\" alt=\"Correlation heatmap\"></figure>",
        )
    )

    symbols = sorted(prices["symbol"].unique())
    for symbol in symbols:
        chart_paths = []
        mid_path = output_dir / f"{symbol.lower()}_mid_spread.png"
        plot_mid_and_spread(prices, symbol, mid_path, config.ema_windows)
        chart_paths.append(mid_path)

        if config.normalize_by:
            norm_path = output_dir / f"{symbol.lower()}_normalized.png"
            plot_normalized_mid(prices, symbol, norm_path, config.normalize_by)
            if norm_path.exists():
                chart_paths.append(norm_path)

        book_path = output_dir / f"{symbol.lower()}_orderbook.png"
        plot_orderbook_scatter(prices, aligned_trades, symbol, book_path, config.max_points)
        chart_paths.append(book_path)

        depth_path = output_dir / f"{symbol.lower()}_depth.png"
        plot_book_depth(prices, symbol, depth_path)
        chart_paths.append(depth_path)

        l1_path = output_dir / f"{symbol.lower()}_level1_volume.png"
        plot_top_level_volume(prices, symbol, l1_path)
        if l1_path.exists():
            chart_paths.append(l1_path)

        size_path = output_dir / f"{symbol.lower()}_trade_size.png"
        plot_trade_size(aligned_trades, symbol, size_path)
        if size_path.exists():
            chart_paths.append(size_path)

        inter_path = output_dir / f"{symbol.lower()}_trade_interarrival.png"
        plot_trade_interarrival(aligned_trades, symbol, inter_path)
        if inter_path.exists():
            chart_paths.append(inter_path)

        impact_path = output_dir / f"{symbol.lower()}_impact.png"
        plot_trade_impact(aligned_trades, symbol, config.impact_horizons, impact_path)
        if impact_path.exists():
            chart_paths.append(impact_path)

        rep_path = output_dir / f"{symbol.lower()}_replenishment.png"
        plot_replenishment(aligned_trades, symbol, rep_path)
        if rep_path.exists():
            chart_paths.append(rep_path)

        ret_path = output_dir / f"{symbol.lower()}_returns.png"
        plot_return_distribution(prices, symbol, ret_path, config.rolling_window)
        if ret_path.exists():
            chart_paths.append(ret_path)

        grid = "".join(
            f'<figure><img src="{path.name}" alt="{path.stem}"><figcaption>{path.stem}</figcaption></figure>'
            for path in chart_paths
        )
        sections.append((f"{symbol}", f"<div class=\"grid\">{grid}</div>"))

    if config.backtest_path:
        backtest_dirs = load_backtest(config.backtest_path)
        if backtest_dirs:
            for dataset_dir in backtest_dirs:
                equity = pd.read_csv(dataset_dir / "equity_curve.csv")
                orders_path = dataset_dir / "orders.csv"
                fills_path = dataset_dir / "fills.csv"
                fills = pd.read_csv(fills_path) if fills_path.exists() else pd.DataFrame()

                eq_path = output_dir / f"{dataset_dir.name}_equity.png"
                plot_equity_curve(equity, eq_path, f"{dataset_dir.name} equity")

                pnl_path = output_dir / f"{dataset_dir.name}_symbol_pnl.png"
                plot_symbol_pnl(equity, pnl_path)

                pos_path = output_dir / f"{dataset_dir.name}_positions.png"
                plot_positions(equity, pos_path)

                fill_path = output_dir / f"{dataset_dir.name}_fills.png"
                plot_fills(fills, equity, fill_path)

                charts = [eq_path, pnl_path, pos_path, fill_path]
                grid = "".join(
                    f'<figure><img src="{path.name}" alt="{path.stem}"><figcaption>{path.stem}</figcaption></figure>'
                    for path in charts
                    if path.exists()
                )
                sections.append((f"Backtest: {dataset_dir.name}", f"<div class=\"grid\">{grid}</div>"))

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_report(output_dir, sections, generated_at, title_suffix=data_dir.name)

    # Persist the resolved config for quick iteration.
    resolved_config = {
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "group_output": config.group_output,
        "symbols": config.symbols,
        "max_points": config.max_points,
        "min_trade_qty": config.min_trade_qty,
        "max_trade_qty": config.max_trade_qty,
        "impact_horizons": config.impact_horizons,
        "rolling_window": config.rolling_window,
        "normalize_by": config.normalize_by,
        "ema_windows": config.ema_windows,
        "theme": {
            "dpi": config.theme.dpi,
            "font_size": config.theme.font_size,
            "title_size": config.theme.title_size,
            "label_size": config.theme.label_size,
        },
        "backtest_path": str(config.backtest_path) if config.backtest_path else None,
        "log_file": str(config.log_file) if config.log_file else None,
        "log_max_rows": config.log_max_rows,
        "indicator_file": str(config.indicator_file) if config.indicator_file else None,
        "indicator_columns": config.indicator_columns,
        "small_trade_qty": config.small_trade_qty,
        "big_trade_qty": config.big_trade_qty,
        "own_trade_tags": config.own_trade_tags,
        "informed_traders": config.informed_traders,
    }
    (output_dir / "resolved_config.json").write_text(json.dumps(resolved_config, indent=2))

    print(f"Report written to {output_dir / 'report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
