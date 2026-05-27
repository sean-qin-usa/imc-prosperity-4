from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from backtester import (
    DEFAULT_EXCHANGE_CALIBRATION_PATH,
    infer_position_limits,
    load_exchange_calibration,
    load_run_log,
    load_strategy_class,
    run_backtest,
)


SUBMISSION_TAG = "SUBMISSION"


@dataclass
class ResolvedBundle:
    root: Path
    log_path: Path
    json_path: Optional[Path]
    strategy_path: Optional[Path]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze an official Prosperity run bundle and optionally compare it "
            "to a local replay of the submitted strategy."
        )
    )
    parser.add_argument(
        "path",
        help="Official run directory, .log file, or .json file.",
    )
    parser.add_argument(
        "--official-log",
        type=Path,
        default=None,
        help="Override the official log path if auto-discovery is not enough.",
    )
    parser.add_argument(
        "--official-json",
        type=Path,
        default=None,
        help="Optional companion official JSON with headline profit / graph data.",
    )
    parser.add_argument(
        "--strategy",
        type=Path,
        default=None,
        help="Optional strategy file. If provided, the tool will run a local replay unless disabled.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for CSVs, plots, and the markdown summary.",
    )
    parser.add_argument(
        "--no-local-compare",
        action="store_true",
        help="Skip the local backtest replay even if a strategy file is available.",
    )
    parser.add_argument(
        "--fill-model",
        choices=["same-tick", "interval", "book-delta", "official-hybrid"],
        default="same-tick",
        help="Fill model for the optional local replay.",
    )
    parser.add_argument(
        "--match-trades",
        choices=["all", "worse", "none"],
        default="all",
        help="same-tick market-trade matching for the optional local replay.",
    )
    parser.add_argument(
        "--trade-fill-price",
        choices=["order", "trade"],
        default="order",
        help="Fill price rule for market-trade fills in the optional local replay.",
    )
    parser.add_argument(
        "--book-delta-on-disappear",
        choices=["never", "if-through", "always"],
        default="if-through",
        help="Passive fill rule in book-delta mode for the optional local replay.",
    )
    parser.add_argument(
        "--market-trades",
        choices=["all", "external-only", "none"],
        default="all",
        help="Which trades to expose in state.market_trades in the optional local replay.",
    )
    parser.add_argument(
        "--exchange-calibration",
        type=Path,
        default=None,
        help="Optional JSON calibration for official-hybrid passive fills.",
    )
    parser.add_argument(
        "--fill-trades",
        choices=["auto", "all", "external-only", "none"],
        default="auto",
        help="Which trades to use for fill simulation in the optional local replay.",
    )
    parser.add_argument(
        "--queue-alpha",
        type=float,
        default=1.0,
        help="Queue assumption for interval / book-delta local replay.",
    )
    return parser.parse_args(argv)


def _pick_companion(directory: Path, stem_hint: str, suffix: str) -> Optional[Path]:
    preferred = directory / f"{stem_hint}{suffix}"
    if preferred.exists():
        return preferred.resolve()

    matches = sorted(directory.glob(f"*{suffix}"))
    if len(matches) == 1:
        return matches[0].resolve()

    same_stem = [path for path in matches if path.stem == stem_hint]
    if len(same_stem) == 1:
        return same_stem[0].resolve()
    return None


def resolve_bundle(path_arg: str, official_log: Optional[Path], official_json: Optional[Path], strategy: Optional[Path]) -> ResolvedBundle:
    root = Path(path_arg).expanduser().resolve()
    if root.is_dir():
        stem_hint = root.name
        log_path = official_log.expanduser().resolve() if official_log else _pick_companion(root, stem_hint, ".log")
        json_path = official_json.expanduser().resolve() if official_json else _pick_companion(root, stem_hint, ".json")
        strategy_path = strategy.expanduser().resolve() if strategy else _pick_companion(root, stem_hint, ".py")
        if log_path is None:
            raise FileNotFoundError(f"Could not find a .log file under {root}")
        return ResolvedBundle(root=root, log_path=log_path, json_path=json_path, strategy_path=strategy_path)

    if not root.exists():
        raise FileNotFoundError(f"Path not found: {root}")

    directory = root.parent
    stem_hint = root.stem
    if root.suffix == ".log":
        log_path = root
        json_path = official_json.expanduser().resolve() if official_json else _pick_companion(directory, stem_hint, ".json")
        strategy_path = strategy.expanduser().resolve() if strategy else _pick_companion(directory, stem_hint, ".py")
        return ResolvedBundle(root=directory, log_path=log_path, json_path=json_path, strategy_path=strategy_path)

    if root.suffix == ".json":
        log_path = official_log.expanduser().resolve() if official_log else _pick_companion(directory, stem_hint, ".log")
        if log_path is None:
            raise FileNotFoundError(f"Could not find a matching .log for {root}")
        json_path = official_json.expanduser().resolve() if official_json else root
        strategy_path = strategy.expanduser().resolve() if strategy else _pick_companion(directory, stem_hint, ".py")
        return ResolvedBundle(root=directory, log_path=log_path, json_path=json_path, strategy_path=strategy_path)

    raise ValueError(f"Unsupported input path: {root}")


def load_json_payload(path: Optional[Path]) -> Optional[dict]:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text())


def global_timestamp(day: int, timestamp: int) -> int:
    return int(day) * 100_000 + int(timestamp)


def symbol_slug(symbol: str) -> str:
    return symbol.lower()


def classify_fill(side: str, price: float, best_bid: Optional[float], best_ask: Optional[float]) -> str:
    if side == "buy":
        if pd.notna(best_ask) and price >= float(best_ask):
            return "take_touch_or_worse"
        if pd.notna(best_bid) and price <= float(best_bid):
            return "rest_bid_or_better"
        return "inside_spread"

    if pd.notna(best_bid) and price <= float(best_bid):
        return "take_touch_or_worse"
    if pd.notna(best_ask) and price >= float(best_ask):
        return "rest_ask_or_better"
    return "inside_spread"


def build_official_frames(log_path: Path) -> Tuple[object, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dataset = load_run_log(log_path)
    prices = dataset.prices.copy().sort_values(["day", "timestamp", "product"]).reset_index(drop=True)
    trades = dataset.trades.copy().sort_values(["day", "timestamp", "symbol"]).reset_index(drop=True)

    prices["day"] = prices["day"].astype(int)
    prices["timestamp"] = prices["timestamp"].astype(int)
    prices["global_timestamp"] = [
        global_timestamp(day, ts)
        for day, ts in zip(prices["day"], prices["timestamp"])
    ]
    prices["mid_price"] = pd.to_numeric(prices.get("mid_price"), errors="coerce")
    prices["profit_and_loss"] = pd.to_numeric(prices.get("profit_and_loss"), errors="coerce")
    for column in ("bid_price_1", "ask_price_1"):
        prices[column] = pd.to_numeric(prices.get(column), errors="coerce")

    if trades.empty:
        trades = pd.DataFrame(columns=["day", "timestamp", "symbol", "price", "quantity", "buyer", "seller"])

    trades["day"] = trades["day"].astype(int)
    trades["timestamp"] = trades["timestamp"].astype(int)
    trades["global_timestamp"] = [
        global_timestamp(day, ts)
        for day, ts in zip(trades["day"], trades["timestamp"])
    ]
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["quantity"] = pd.to_numeric(trades["quantity"], errors="coerce").fillna(0).astype(int)
    trades["buyer"] = trades["buyer"].fillna("").astype(str)
    trades["seller"] = trades["seller"].fillna("").astype(str)

    own_trades = trades[
        (trades["buyer"] == SUBMISSION_TAG) | (trades["seller"] == SUBMISSION_TAG)
    ].copy()
    if own_trades.empty:
        own_trades = pd.DataFrame(
            columns=[
                "day",
                "timestamp",
                "global_timestamp",
                "symbol",
                "price",
                "quantity",
                "buyer",
                "seller",
                "side",
                "signed_qty",
            ]
        )
        return dataset, prices, trades, own_trades

    own_trades["side"] = own_trades.apply(
        lambda row: "buy" if row["buyer"] == SUBMISSION_TAG else "sell",
        axis=1,
    )
    own_trades["signed_qty"] = own_trades.apply(
        lambda row: int(row["quantity"]) if row["side"] == "buy" else -int(row["quantity"]),
        axis=1,
    )

    market_cols = prices[["day", "timestamp", "product", "bid_price_1", "ask_price_1", "mid_price"]].copy()
    own_trades = own_trades.merge(
        market_cols,
        left_on=["day", "timestamp", "symbol"],
        right_on=["day", "timestamp", "product"],
        how="left",
    )
    own_trades["fill_class"] = own_trades.apply(
        lambda row: classify_fill(
            side=str(row["side"]),
            price=float(row["price"]),
            best_bid=row["bid_price_1"],
            best_ask=row["ask_price_1"],
        ),
        axis=1,
    )
    own_trades["edge_vs_mid"] = own_trades.apply(
        lambda row: (
            float(row["mid_price"]) - float(row["price"])
            if row["side"] == "buy"
            else float(row["price"]) - float(row["mid_price"])
        )
        if pd.notna(row["mid_price"])
        else float("nan"),
        axis=1,
    )
    return dataset, prices, trades, own_trades


def build_total_pnl_frame(prices: pd.DataFrame) -> pd.DataFrame:
    pnl_frame = (
        prices.groupby(["day", "timestamp", "global_timestamp"], as_index=False)["profit_and_loss"]
        .sum()
        .sort_values(["day", "timestamp"])
        .rename(columns={"profit_and_loss": "total_pnl"})
    )
    return pnl_frame


def infer_positions(prices: pd.DataFrame, own_trades: pd.DataFrame) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    for symbol in sorted(prices["product"].unique()):
        symbol_prices = prices[prices["product"] == symbol][["day", "timestamp", "global_timestamp"]].copy()
        symbol_prices = symbol_prices.sort_values(["day", "timestamp"])

        symbol_own = own_trades[own_trades["symbol"] == symbol]
        flow = (
            symbol_own.groupby(["day", "timestamp", "global_timestamp"], as_index=False)["signed_qty"]
            .sum()
            .sort_values(["day", "timestamp"])
            if not symbol_own.empty
            else pd.DataFrame(columns=["day", "timestamp", "global_timestamp", "signed_qty"])
        )
        merged = symbol_prices.merge(flow, on=["day", "timestamp", "global_timestamp"], how="left")
        merged["signed_qty"] = merged["signed_qty"].fillna(0).astype(int)
        merged["position"] = merged["signed_qty"].cumsum()
        merged["symbol"] = symbol
        rows.append(merged[["day", "timestamp", "global_timestamp", "symbol", "position"]])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["day", "timestamp", "global_timestamp", "symbol", "position"])


def summarize_by_symbol(prices: pd.DataFrame, own_trades: pd.DataFrame, positions: pd.DataFrame, limits: Dict[str, int]) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for symbol in sorted(prices["product"].unique()):
        symbol_prices = prices[prices["product"] == symbol].copy()
        symbol_own = own_trades[own_trades["symbol"] == symbol].copy()
        symbol_positions = positions[positions["symbol"] == symbol].copy()

        buy_qty = int(symbol_own.loc[symbol_own["side"] == "buy", "quantity"].sum()) if not symbol_own.empty else 0
        sell_qty = int(symbol_own.loc[symbol_own["side"] == "sell", "quantity"].sum()) if not symbol_own.empty else 0
        final_position = int(symbol_positions["position"].iloc[-1]) if not symbol_positions.empty else 0
        max_abs_position = int(symbol_positions["position"].abs().max()) if not symbol_positions.empty else 0
        avg_abs_position = float(symbol_positions["position"].abs().mean()) if not symbol_positions.empty else 0.0
        final_pnl = float(symbol_prices["profit_and_loss"].iloc[-1]) if not symbol_prices.empty else 0.0
        max_drawdown = float(
            (symbol_prices["profit_and_loss"] - symbol_prices["profit_and_loss"].cummax()).min()
        ) if not symbol_prices.empty else 0.0
        limit = limits.get(symbol)
        rows.append(
            {
                "symbol": symbol,
                "limit": limit,
                "official_final_pnl": round(final_pnl, 6),
                "official_trade_count": int(len(symbol_own)),
                "official_fill_qty": int(symbol_own["quantity"].sum()) if not symbol_own.empty else 0,
                "buy_qty": buy_qty,
                "sell_qty": sell_qty,
                "final_position": final_position,
                "max_abs_position": max_abs_position,
                "avg_abs_position": round(avg_abs_position, 3),
                "limit_utilization_pct": round(100.0 * max_abs_position / limit, 2) if limit else None,
                "max_drawdown": round(max_drawdown, 6),
            }
        )
    return pd.DataFrame(rows)


def summarize_fill_classes(own_trades: pd.DataFrame) -> pd.DataFrame:
    if own_trades.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "class",
                "fill_qty",
                "fill_count",
                "qty_pct",
                "mean_edge_vs_mid",
            ]
        )

    grouped = (
        own_trades.groupby(["symbol", "fill_class"], as_index=False)
        .agg(
            fill_qty=("quantity", "sum"),
            fill_count=("quantity", "size"),
            mean_edge_vs_mid=("edge_vs_mid", "mean"),
        )
        .rename(columns={"fill_class": "class"})
    )
    grouped["qty_pct"] = grouped.groupby("symbol")["fill_qty"].transform(lambda series: 100.0 * series / max(1, float(series.sum())))
    grouped["qty_pct"] = grouped["qty_pct"].round(2)
    grouped["mean_edge_vs_mid"] = grouped["mean_edge_vs_mid"].round(6)
    return grouped.sort_values(["symbol", "fill_qty"], ascending=[True, False]).reset_index(drop=True)


def filter_plot_prices(symbol_prices: pd.DataFrame) -> pd.DataFrame:
    filtered = symbol_prices.copy().sort_values(["day", "timestamp"])
    median_mid = filtered["mid_price"].dropna().median()
    if pd.notna(median_mid) and median_mid > 0:
        filtered = filtered[
            filtered["mid_price"].isna() | (filtered["mid_price"] > 0.8 * float(median_mid))
        ].copy()
    return filtered


def plot_pnl_curves(total_pnl: pd.DataFrame, prices: pd.DataFrame, output_path: Path) -> None:
    by_symbol = (
        prices.pivot_table(
            index="global_timestamp",
            columns="product",
            values="profit_and_loss",
            aggfunc="last",
        )
        .sort_index()
        .ffill()
        .fillna(0.0)
    )
    plt.figure(figsize=(12, 7))
    for symbol in by_symbol.columns:
        plt.plot(by_symbol.index, by_symbol[symbol], linewidth=1.7, label=symbol)
    plt.plot(total_pnl["global_timestamp"], total_pnl["total_pnl"], color="black", linewidth=2.4, label="TOTAL")
    plt.title("Official Run PnL by Product and Total")
    plt.xlabel("Global Timestamp")
    plt.ylabel("PnL")
    plt.legend()
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()


def plot_positions(positions: pd.DataFrame, limits: Dict[str, int], output_path: Path) -> None:
    pivot = (
        positions.pivot_table(index="global_timestamp", columns="symbol", values="position", aggfunc="last")
        .sort_index()
        .ffill()
        .fillna(0.0)
    )
    plt.figure(figsize=(12, 6))
    for symbol in pivot.columns:
        plt.plot(pivot.index, pivot[symbol], linewidth=1.8, label=symbol)
        limit = limits.get(symbol)
        if limit:
            plt.axhline(limit, color="red", linestyle="--", alpha=0.2)
            plt.axhline(-limit, color="red", linestyle="--", alpha=0.2)
    plt.title("Official Run Inferred Position by Product")
    plt.xlabel("Global Timestamp")
    plt.ylabel("Position")
    plt.legend()
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()


def plot_symbol_overlay(symbol: str, prices: pd.DataFrame, own_trades: pd.DataFrame, output_path: Path) -> None:
    symbol_prices = filter_plot_prices(prices[prices["product"] == symbol])
    symbol_own = own_trades[own_trades["symbol"] == symbol].copy().sort_values(["day", "timestamp"])

    plt.figure(figsize=(13, 6))
    if symbol_prices["bid_price_1"].notna().any():
        plt.plot(symbol_prices["global_timestamp"], symbol_prices["bid_price_1"], color="tab:blue", linewidth=1.0, alpha=0.85, label="best bid")
    if symbol_prices["ask_price_1"].notna().any():
        plt.plot(symbol_prices["global_timestamp"], symbol_prices["ask_price_1"], color="tab:orange", linewidth=1.0, alpha=0.85, label="best ask")
    if symbol_prices["mid_price"].notna().any():
        plt.plot(symbol_prices["global_timestamp"], symbol_prices["mid_price"], color="black", linewidth=1.2, alpha=0.9, label="mid")

    buys = symbol_own[symbol_own["side"] == "buy"]
    sells = symbol_own[symbol_own["side"] == "sell"]
    if not buys.empty:
        plt.scatter(
            buys["global_timestamp"],
            buys["price"],
            color="green",
            s=24 + 3 * buys["quantity"],
            alpha=0.75,
            label="buy fills",
        )
    if not sells.empty:
        plt.scatter(
            sells["global_timestamp"],
            sells["price"],
            color="crimson",
            s=24 + 3 * sells["quantity"],
            alpha=0.75,
            label="sell fills",
        )

    plt.title(f"Official Trade Overlay: {symbol}")
    plt.xlabel("Global Timestamp")
    plt.ylabel("Price")
    plt.legend()
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()


def cleanup_outputs(output_dir: Path) -> None:
    known_files = [
        "official_total_pnl.csv",
        "official_pnl_pivot.csv",
        "official_pnl_timeseries.csv",
        "official_positions.csv",
        "official_summary.csv",
        "official_fill_classes.csv",
        "official_own_trades.csv",
        "local_replay_summary.csv",
        "local_replay_equity.csv",
        "local_replay_fills.csv",
        "official_vs_local_summary.csv",
        "official_pnl_curves.png",
        "official_positions.png",
        "official_vs_local_total_pnl.png",
        "official_vs_local_fill_qty.png",
        "summary.md",
    ]
    for name in known_files:
        path = output_dir / name
        if path.exists():
            path.unlink()

    for path in output_dir.glob("official_overlay_*.png"):
        path.unlink()

    local_compare_dir = output_dir / "local_compare"
    if local_compare_dir.exists():
        shutil.rmtree(local_compare_dir)


def normalize_fill_modes(fill_model: str, market_trades_mode: str, fill_trades_mode: str) -> Tuple[str, str]:
    resolved_market_trades_mode = market_trades_mode
    resolved_fill_trades_mode = fill_trades_mode
    if fill_model == "official-hybrid":
        if resolved_market_trades_mode == "all":
            resolved_market_trades_mode = "external-only"
        if resolved_fill_trades_mode == "auto":
            resolved_fill_trades_mode = "external-only"
    return resolved_market_trades_mode, resolved_fill_trades_mode


def run_local_compare(
    bundle: ResolvedBundle,
    dataset: object,
    output_dir: Path,
    args: argparse.Namespace,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    calibration_path = args.exchange_calibration
    if calibration_path is None and str(args.fill_model) == "official-hybrid" and DEFAULT_EXCHANGE_CALIBRATION_PATH.exists():
        calibration_path = DEFAULT_EXCHANGE_CALIBRATION_PATH
    resolved_market_trades_mode, resolved_fill_trades_mode = normalize_fill_modes(
        fill_model=str(args.fill_model),
        market_trades_mode=str(args.market_trades),
        fill_trades_mode=str(args.fill_trades),
    )
    result = run_backtest(
        strategy_path=bundle.strategy_path,
        dataset=dataset,
        output_dir=output_dir,
        reuse_trader_instance=False,
        queue_alpha=float(args.queue_alpha),
        make_plots=False,
        fill_model=str(args.fill_model),
        match_trades=str(args.match_trades),
        trade_fill_price=str(args.trade_fill_price),
        book_delta_on_disappear=str(args.book_delta_on_disappear),
        market_trades_mode=resolved_market_trades_mode,
        fill_trades_mode=resolved_fill_trades_mode,
        exchange_calibration=load_exchange_calibration(calibration_path),
    )
    return result.summary.copy(), result.equity_curve.copy(), result.fills.copy()


def summarize_local_compare(
    symbol_summary: pd.DataFrame,
    local_summary: pd.DataFrame,
    local_fills: pd.DataFrame,
) -> pd.DataFrame:
    local_qty = (
        local_fills.groupby("symbol", as_index=False)["quantity"]
        .sum()
        .rename(columns={"quantity": "local_fill_qty"})
        if not local_fills.empty
        else pd.DataFrame(columns=["symbol", "local_fill_qty"])
    )

    local_liquidity = (
        local_fills.groupby(["symbol", "liquidity"], as_index=False)["quantity"]
        .sum()
        if not local_fills.empty
        else pd.DataFrame(columns=["symbol", "liquidity", "quantity"])
    )
    local_wide = (
        local_liquidity.pivot(index="symbol", columns="liquidity", values="quantity")
        .fillna(0.0)
        .reset_index()
        .rename_axis(None, axis=1)
    )
    renamed = {}
    for column in local_wide.columns:
        if column == "symbol":
            continue
        renamed[column] = f"local_{column}_qty"
    local_wide = local_wide.rename(columns=renamed)

    compare = symbol_summary.merge(local_qty, on="symbol", how="left").merge(local_wide, on="symbol", how="left")
    compare["local_fill_qty"] = compare["local_fill_qty"].fillna(0).astype(int)
    for column in compare.columns:
        if column.startswith("local_") and column.endswith("_qty") and column != "local_fill_qty":
            compare[column] = compare[column].fillna(0).astype(int)
    compare["official_vs_local_fill_qty_ratio"] = compare.apply(
        lambda row: round(float(row["official_fill_qty"]) / float(row["local_fill_qty"]), 6)
        if float(row["local_fill_qty"]) > 0
        else None,
        axis=1,
    )

    if not local_summary.empty and "final_total_pnl" in local_summary.columns:
        compare["local_replay_final_pnl"] = float(local_summary.iloc[0]["final_total_pnl"])
    else:
        compare["local_replay_final_pnl"] = None
    return compare


def plot_official_vs_local_total_pnl(official_total: pd.DataFrame, local_equity: pd.DataFrame, output_path: Path) -> None:
    if local_equity.empty or "total_pnl" not in local_equity.columns:
        return
    local = local_equity.copy()
    local["day"] = local["day"].astype(int)
    local["timestamp"] = local["timestamp"].astype(int)
    local["global_timestamp"] = [global_timestamp(day, ts) for day, ts in zip(local["day"], local["timestamp"])]
    local = local.sort_values(["day", "timestamp"])

    plt.figure(figsize=(12, 6))
    plt.plot(official_total["global_timestamp"], official_total["total_pnl"], linewidth=2.1, color="black", label="official")
    plt.plot(local["global_timestamp"], local["total_pnl"], linewidth=1.8, color="tab:purple", label="local replay")
    plt.title("Official vs Local Replay Total PnL")
    plt.xlabel("Global Timestamp")
    plt.ylabel("Total PnL")
    plt.legend()
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()


def plot_official_vs_local_fill_qty(compare: pd.DataFrame, output_path: Path) -> None:
    if compare.empty or "local_fill_qty" not in compare.columns:
        return

    x = list(range(len(compare)))
    width = 0.36
    plt.figure(figsize=(10, 5))
    plt.bar([idx - width / 2 for idx in x], compare["official_fill_qty"], width=width, label="official")
    plt.bar([idx + width / 2 for idx in x], compare["local_fill_qty"], width=width, label="local replay")
    plt.xticks(x, compare["symbol"])
    plt.ylabel("Filled Quantity")
    plt.title("Official vs Local Replay Filled Quantity")
    plt.legend()
    plt.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    plt.savefig(output_path, dpi=160)
    plt.close()


def build_advice(symbol_summary: pd.DataFrame, fill_classes: pd.DataFrame, compare: Optional[pd.DataFrame]) -> List[str]:
    advice: List[str] = []

    if not symbol_summary.empty and symbol_summary["limit"].notna().any():
        limit_bound = symbol_summary[
            symbol_summary.apply(
                lambda row: row["limit"] is not None and row["max_abs_position"] >= 0.9 * row["limit"],
                axis=1,
            )
        ]
        if limit_bound.empty:
            advice.append(
                "Inventory limits were not the binding constraint in this official run. "
                "Execution realism and fill capture matter more than tighter position controls."
            )
        else:
            symbols = ", ".join(limit_bound["symbol"].tolist())
            advice.append(
                f"Inventory approached the hard limit for {symbols}. If that was uncomfortable, "
                "tighten inventory skew or late-run unwind logic there."
            )

    if compare is not None and not compare.empty and "official_vs_local_fill_qty_ratio" in compare.columns:
        low_fill = compare[
            compare["official_vs_local_fill_qty_ratio"].notna()
            & (compare["official_vs_local_fill_qty_ratio"] < 0.35)
        ]
        if not low_fill.empty:
            joined = ", ".join(
                f"{row.symbol} ({row.official_vs_local_fill_qty_ratio:.2f}x)"
                for row in low_fill.itertuples(index=False)
            )
            advice.append(
                f"Local replay fills are materially more optimistic than official for {joined}. "
                "Use official logs or stricter fill assumptions as the main tuning filter."
            )

    if not fill_classes.empty:
        for symbol, symbol_fill in fill_classes.groupby("symbol"):
            passive_like = symbol_fill[symbol_fill["class"].isin(["inside_spread", "rest_bid_or_better", "rest_ask_or_better"])]
            take_like = symbol_fill[symbol_fill["class"] == "take_touch_or_worse"]
            passive_qty = float(passive_like["fill_qty"].sum())
            take_qty = float(take_like["fill_qty"].sum())
            passive_edge = float(passive_like["mean_edge_vs_mid"].mean()) if not passive_like.empty else float("nan")
            take_edge = float(take_like["mean_edge_vs_mid"].mean()) if not take_like.empty else float("nan")

            if passive_qty > 0 and take_qty > 0 and pd.notna(passive_edge) and pd.notna(take_edge):
                if passive_edge > take_edge + 1.0:
                    advice.append(
                        f"{symbol}: passive / inside-spread fills carried much better official edge than touch-taking. "
                        "Prioritize queue capture and quote competitiveness before loosening take thresholds."
                    )
                elif take_edge < 0 and take_qty >= passive_qty:
                    advice.append(
                        f"{symbol}: aggressive taking gave up edge in the official run. "
                        "A slightly tighter take threshold may improve realized execution quality."
                    )

    for row in symbol_summary.itertuples(index=False):
        if row.limit and abs(row.final_position) >= 0.4 * row.limit:
            advice.append(
                f"{row.symbol}: end-of-run inventory stayed meaningful at {row.final_position:+d} against limit {row.limit}. "
                "If you care about cleaner closes, add stronger late-session unwind logic."
            )

    if not advice:
        advice.append("No strong execution pathology stood out. The current official run looks internally consistent.")
    return advice


def write_markdown_report(
    output_dir: Path,
    bundle: ResolvedBundle,
    headline_profit: Optional[float],
    total_pnl: pd.DataFrame,
    symbol_summary: pd.DataFrame,
    fill_classes: pd.DataFrame,
    compare: Optional[pd.DataFrame],
    advice: Sequence[str],
    args: argparse.Namespace,
) -> Path:
    report_path = output_dir / "summary.md"
    lines: List[str] = []
    lines.append("# Official Run Review")
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    lines.append(f"- Official log: `{bundle.log_path}`")
    if bundle.json_path is not None:
        lines.append(f"- Official json: `{bundle.json_path}`")
    if bundle.strategy_path is not None:
        lines.append(f"- Strategy: `{bundle.strategy_path}`")
    lines.append("")
    lines.append("## Result")
    lines.append("")
    final_total = float(total_pnl["total_pnl"].iloc[-1]) if not total_pnl.empty else 0.0
    lines.append(f"- Final total PnL from activitiesLog: `{final_total:.6f}`")
    if headline_profit is not None:
        lines.append(f"- Headline official profit: `{headline_profit:.6f}`")
    lines.append("")
    lines.append("## Symbol Summary")
    lines.append("")
    lines.append("```text")
    lines.append(symbol_summary.to_string(index=False))
    lines.append("```")
    lines.append("")
    lines.append("## Fill Classes")
    lines.append("")
    lines.append("```text")
    lines.append(fill_classes.to_string(index=False))
    lines.append("```")
    if compare is not None and not compare.empty:
        lines.append("")
        lines.append("## Local Replay Comparison")
        lines.append("")
        lines.append(f"- fill model: `{args.fill_model}`")
        lines.append(f"- match trades: `{args.match_trades}`")
        lines.append("```text")
        lines.append(compare.to_string(index=False))
        lines.append("```")
    lines.append("")
    lines.append("## Advice")
    lines.append("")
    for item in advice:
        lines.append(f"- {item}")
    lines.append("")
    report_path.write_text("\n".join(lines))
    return report_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    bundle = resolve_bundle(
        path_arg=str(args.path),
        official_log=args.official_log,
        official_json=args.official_json,
        strategy=args.strategy,
    )

    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else (bundle.root / "analysis").resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    cleanup_outputs(output_dir)

    dataset, prices, _trades, own_trades = build_official_frames(bundle.log_path)
    headline_payload = load_json_payload(bundle.json_path)
    headline_profit = None
    if headline_payload is not None and headline_payload.get("profit") is not None:
        headline_profit = float(headline_payload["profit"])

    limits: Dict[str, int] = {}
    if bundle.strategy_path is not None and bundle.strategy_path.exists():
        try:
            trader_class = load_strategy_class(bundle.strategy_path)
            limits = infer_position_limits(trader_class, prices["product"].unique())
        except Exception:
            limits = {}

    total_pnl = build_total_pnl_frame(prices)
    positions = infer_positions(prices, own_trades)
    symbol_summary = summarize_by_symbol(prices, own_trades, positions, limits)
    fill_classes = summarize_fill_classes(own_trades)

    total_pnl.to_csv(output_dir / "official_total_pnl.csv", index=False)
    prices.to_csv(output_dir / "official_pnl_timeseries.csv", index=False)
    positions.to_csv(output_dir / "official_positions.csv", index=False)
    symbol_summary.to_csv(output_dir / "official_summary.csv", index=False)
    fill_classes.to_csv(output_dir / "official_fill_classes.csv", index=False)
    own_trades.to_csv(output_dir / "official_own_trades.csv", index=False)

    plot_pnl_curves(total_pnl, prices, output_dir / "official_pnl_curves.png")
    plot_positions(positions, limits, output_dir / "official_positions.png")
    for symbol in sorted(prices["product"].unique()):
        plot_symbol_overlay(symbol, prices, own_trades, output_dir / f"official_overlay_{symbol_slug(symbol)}.png")

    compare: Optional[pd.DataFrame] = None
    if not args.no_local_compare and bundle.strategy_path is not None and bundle.strategy_path.exists():
        local_dir = output_dir / "local_compare"
        local_dir.mkdir(parents=True, exist_ok=True)
        local_summary, local_equity, local_fills = run_local_compare(
            bundle=bundle,
            dataset=dataset,
            output_dir=local_dir,
            args=args,
        )
        local_summary.to_csv(output_dir / "local_replay_summary.csv", index=False)
        local_equity.to_csv(output_dir / "local_replay_equity.csv", index=False)
        local_fills.to_csv(output_dir / "local_replay_fills.csv", index=False)
        compare = summarize_local_compare(symbol_summary, local_summary, local_fills)
        compare.to_csv(output_dir / "official_vs_local_summary.csv", index=False)
        plot_official_vs_local_total_pnl(total_pnl, local_equity, output_dir / "official_vs_local_total_pnl.png")
        plot_official_vs_local_fill_qty(compare, output_dir / "official_vs_local_fill_qty.png")

    advice = build_advice(symbol_summary, fill_classes, compare)
    report_path = write_markdown_report(
        output_dir=output_dir,
        bundle=bundle,
        headline_profit=headline_profit,
        total_pnl=total_pnl,
        symbol_summary=symbol_summary,
        fill_classes=fill_classes,
        compare=compare,
        advice=advice,
        args=args,
    )

    print(f"Official log: {bundle.log_path}")
    if bundle.json_path is not None:
        print(f"Official json: {bundle.json_path}")
    if bundle.strategy_path is not None:
        print(f"Strategy: {bundle.strategy_path}")
    print(f"Analysis dir: {output_dir}")
    print()
    print("Symbol summary:")
    print(symbol_summary.to_string(index=False))
    print()
    print("Advice:")
    for item in advice:
        print(f"- {item}")
    print()
    print(f"Markdown summary: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
