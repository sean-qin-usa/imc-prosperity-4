from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from visualizer import (
    VisualizerConfig,
    add_global_time,
    align_trades_to_book,
    filter_symbols,
    filter_trades_by_size,
    load_config,
    load_indicator_entries,
    load_log_entries,
    load_prices,
    load_trades,
    prepare_prices,
    prepare_trades,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path(__file__).with_name("visualizer_report") / "report_interactive.html"
DEFAULT_GEN_ROOT = REPO_ROOT / "gen"
ALT_GEN_ROOT = REPO_ROOT.parent / "gen"

FIXED_FAIR_PRODUCTS: Dict[str, float] = {
    "EMERALDS": 10000.0,
    "RAINFOREST_RESIN": 10000.0,
    "ASH_COATED_OSMIUM": 10000.0,
}

PATH_ANCHOR_PRODUCTS = {
    "INTARIAN_PEPPER_ROOT",
}

BASKET_COMPOSITIONS: Dict[str, Dict[str, float]] = {
    "PICNIC_BASKET1": {"CROISSANTS": 6.0, "JAMS": 3.0, "DJEMBES": 1.0},
    "PICNIC_BASKET2": {"CROISSANTS": 4.0, "JAMS": 2.0},
}

EXTREMA_SCAN_PRODUCTS = {
    "SQUID_INK",
    "CROISSANTS",
}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the unified interactive IMC Prosperity visualizer.")
    parser.add_argument("--config", type=Path, default=None, help="Path to a JSON config.")
    parser.add_argument("--data-dir", type=Path, default=None, help="Directory or official log path.")
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
    parser.add_argument(
        "--group-output",
        action="store_true",
        help="Write outputs under a subdirectory named after the data dir (e.g. output/round1).",
    )
    parser.add_argument("--output", type=Path, default=None, help="Output HTML path.")
    return parser.parse_args(argv)


def load_market_data_from_path(data_path: Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    data_path = data_path.expanduser().resolve()

    if data_path.is_file() and data_path.suffix.lower() in {".json", ".log"}:
        import sys

        tools_dir = REPO_ROOT / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.append(str(tools_dir))
        from backtester import load_run_log

        dataset = load_run_log(data_path)
        prices = prepare_prices(dataset.prices.copy())
        trades = prepare_trades(dataset.trades.copy())
        return prices, trades

    if data_path.is_dir():
        price_files = sorted(data_path.glob("prices*.csv"))
        trade_files = sorted(data_path.glob("trades*.csv"))
        prices = load_prices(price_files)
        trades = load_trades(trade_files) if trade_files else pd.DataFrame()
        return prices, trades

    raise FileNotFoundError(f"Unsupported data path: {data_path}")


def infer_round_name(value: str) -> str:
    match = re.search(r"(round\d+)", value)
    return match.group(1) if match else "unknown"


def infer_round_name_from_path(path: Path) -> str:
    for part in path.parts[::-1]:
        round_name = infer_round_name(part)
        if round_name != "unknown":
            return round_name
    return "unknown"


def market_source_id_from_path(path: Path) -> str:
    path = path.expanduser().resolve()
    if path.is_dir() and path.name.startswith("round"):
        return f"{path.name}_csv"
    if path.is_file():
        if (
            path.parent.name.startswith("benchmark_data_day_")
            or path.parent.name.startswith("benchmark_day_")
            or path.stem.isdigit()
        ):
            return path.stem
        round_name = infer_round_name_from_path(path)
        return f"{round_name}__{path.stem}"
    return path.stem or path.name


def market_source_label_from_path(path: Path) -> str:
    path = path.expanduser().resolve()
    round_name = infer_round_name_from_path(path)
    if path.is_dir() and path.name.startswith("round"):
        return f"{path.name} csv"
    if path.is_file() and (
        path.parent.name.startswith("benchmark_data_day_")
        or path.parent.name.startswith("benchmark_day_")
        or path.stem.isdigit()
    ):
        return f"Official benchmark data {path.stem}"
    if round_name != "unknown":
        return f"{round_name} {path.stem}"
    return path.stem or path.name


def discover_market_source_paths(data_path: Path) -> List[Tuple[Path, bool]]:
    data_path = data_path.expanduser().resolve()
    discovered: List[Tuple[Path, bool]] = []

    if data_path.is_dir() and data_path.name.startswith("round"):
        data_root = data_path.parent
        for round_dir in sorted(data_root.glob("round*")):
            if not round_dir.is_dir():
                continue
            if list(round_dir.glob("prices*.csv")):
                discovered.append((round_dir, round_dir.resolve() == data_path))
            benchmark_candidates: Dict[str, Path] = {}
            for pattern in ("benchmark_data_day_*/*.log", "benchmark_day_*/*.log"):
                for log_path in sorted(round_dir.glob(pattern)):
                    benchmark_candidates[log_path.stem] = log_path
            for pattern in ("benchmark_data_day_*/*.json", "benchmark_day_*/*.json"):
                for json_path in sorted(round_dir.glob(pattern)):
                    benchmark_candidates.setdefault(json_path.stem, json_path)
            for benchmark_path in sorted(benchmark_candidates.values(), key=lambda item: (item.parent.name, item.stem)):
                discovered.append((benchmark_path, benchmark_path.resolve() == data_path))
        if discovered:
            return discovered

    return [(data_path, True)]


def build_market_source_catalog(config: VisualizerConfig) -> Tuple[Dict[str, dict], Optional[str]]:
    catalog: Dict[str, dict] = {}
    preferred_id: Optional[str] = None

    for source_path, preferred in discover_market_source_paths(config.data_dir):
        prices, trades = load_market_data_from_path(source_path)
        prices = filter_symbols(prices, config.symbols)
        trades = filter_symbols(trades, config.symbols)
        if prices.empty:
            continue

        prices = add_global_time(prices)
        trades = add_global_time(trades) if not trades.empty else trades
        trades = filter_trades_by_size(trades, config.min_trade_qty, config.max_trade_qty)
        aligned_trades = align_trades_to_book(trades, prices, config.impact_horizons) if not trades.empty else trades
        if not aligned_trades.empty:
            aligned_trades = add_global_time(aligned_trades)
            aligned_trades = assign_trade_groups(aligned_trades, config)

        source_id = market_source_id_from_path(source_path)
        round_name = infer_round_name_from_path(source_path)
        catalog[source_id] = {
            "id": source_id,
            "label": market_source_label_from_path(source_path),
            "round": round_name,
            "kind": "benchmark" if source_path.is_file() else "csv",
            "path": str(source_path),
            "prices": prices,
            "trades": aligned_trades,
            "symbols": sorted(prices["symbol"].dropna().unique().tolist()),
            "days": sorted(prices["day"].dropna().unique().tolist()),
            "levels": discover_levels(prices),
            "maxTimestamp": int(prices["timestamp"].max()) if prices["timestamp"].notna().any() else None,
        }
        if preferred:
            preferred_id = source_id

    if preferred_id is None and catalog:
        preferred_id = next(iter(sorted(catalog.keys())))
    return catalog, preferred_id


def load_backtest_recursive(backtest_path: Optional[Path]) -> List[Path]:
    if not backtest_path or not backtest_path.exists():
        return []
    if backtest_path.is_dir() and (backtest_path / "equity_curve.csv").exists():
        return [backtest_path]
    if backtest_path.is_dir():
        runs = sorted({p.parent for p in backtest_path.rglob("equity_curve.csv")})
        return runs
    return []


def discover_strategy_catalog(traders_root: Path) -> Dict[str, List[str]]:
    catalog: Dict[str, List[str]] = {}
    if not traders_root.exists():
        return catalog
    for round_dir in sorted(traders_root.glob("round*")):
        if not round_dir.is_dir():
            continue
        round_name = round_dir.name
        strategies = []
        for file in round_dir.glob("*.py"):
            if file.name.startswith("__"):
                continue
            strategies.append(file.stem)
        catalog[round_name] = sorted(set(strategies))
    return catalog


def parse_run_dir_name(
    run_name: str,
    dataset_name: str,
    strategy_catalog: Dict[str, List[str]],
) -> Tuple[str, str]:
    parts = run_name.split("__")
    strategy = parts[1] if len(parts) > 1 else run_name
    round_name = "unknown"
    for token in (run_name, dataset_name):
        match = re.search(r"(round\d+)", token)
        if match:
            round_name = match.group(1)
            break
    if round_name == "unknown":
        matches = [round_key for round_key, items in strategy_catalog.items() if strategy in items]
        if len(matches) == 1:
            round_name = matches[0]
    return round_name, strategy


def infer_market_source_id_from_dataset_source(dataset_dir: Path) -> str:
    run_root = dataset_dir.parent
    manifest_path = run_root / "run_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            manifest = {}
        for dataset in manifest.get("datasets", []):
            if dataset.get("name") == dataset_dir.name and dataset.get("source"):
                return market_source_id_from_path(Path(dataset["source"]))
    if dataset_dir.name.startswith("round"):
        return dataset_dir.name
    if dataset_dir.name.isdigit():
        return dataset_dir.name
    return infer_round_name_from_path(dataset_dir)


def build_backtest_index(
    dataset_dirs: List[Path],
    root: Optional[Path],
    strategy_catalog: Dict[str, List[str]],
    preferred_dataset_dir: Optional[Path] = None,
) -> Tuple[List[dict], Dict[Path, str]]:
    index: List[dict] = []
    id_map: Dict[Path, str] = {}
    used = set()
    for dataset_dir in dataset_dirs:
        if root and dataset_dir.is_relative_to(root):
            rel = dataset_dir.relative_to(root)
            rel_parts = rel.parts
        else:
            rel_parts = (dataset_dir.name,)
        dataset_id = "__".join(rel_parts)
        base_id = dataset_id
        counter = 1
        while dataset_id in used:
            dataset_id = f"{base_id}__{counter}"
            counter += 1
        used.add(dataset_id)
        run_root = dataset_dir
        dataset_name = dataset_dir.name
        parent = dataset_dir.parent
        if parent != dataset_dir and (
            (parent / "run_manifest.json").exists()
            or (parent / "run_summary.csv").exists()
            or "__" in parent.name
        ):
            run_root = parent
        round_name, strategy_name = parse_run_dir_name(run_root.name, dataset_name, strategy_catalog)
        if len(rel_parts) >= 2 and rel_parts[0].startswith("round"):
            round_name = rel_parts[0]
            if rel_parts[1]:
                strategy_name = rel_parts[1]
        label = "/".join(rel_parts)
        if label == dataset_dir.name and round_name != "unknown":
            run_stamp = run_root.name.split("__")[0]
            label = f"{round_name}/{strategy_name}/{run_stamp}/{dataset_name}"
        index.append(
            {
                "id": dataset_id,
                "label": label,
                "round": round_name,
                "strategy": strategy_name,
                "marketSource": infer_market_source_id_from_dataset_source(dataset_dir),
                "preferred": preferred_dataset_dir is not None and dataset_dir.resolve() == preferred_dataset_dir.resolve(),
            }
        )
        id_map[dataset_dir] = dataset_id
    index.sort(key=lambda entry: (0 if entry.get("preferred") else 1, entry["round"], entry["strategy"], entry["label"]))
    return index, id_map


def resolve_backtest_root(explicit: Optional[Path]) -> Tuple[Optional[Path], List[Path], Optional[Path]]:
    if explicit:
        explicit = explicit.expanduser().resolve()
        if explicit.is_dir() and (explicit / "equity_curve.csv").exists():
            dataset_dir = explicit
            run_root = dataset_dir.parent
            scan_root = run_root.parent
            runs = load_backtest_recursive(scan_root)
            return scan_root, runs, dataset_dir
        if explicit.is_dir():
            child_datasets = sorted(
                child for child in explicit.iterdir()
                if child.is_dir() and (child / "equity_curve.csv").exists()
            )
            if child_datasets:
                preferred = child_datasets[0]
                scan_root = explicit.parent
                runs = load_backtest_recursive(scan_root)
                return scan_root, runs, preferred
        if explicit.is_dir() and ((explicit / "run_manifest.json").exists() or (explicit / "run_summary.csv").exists()):
            dataset_dirs = load_backtest_recursive(explicit)
            preferred = dataset_dirs[0] if dataset_dirs else None
            scan_root = explicit.parent
            runs = load_backtest_recursive(scan_root)
            return scan_root, runs, preferred
        return explicit, load_backtest_recursive(explicit), None
    candidates: List[Path] = []
    for base in [DEFAULT_GEN_ROOT, ALT_GEN_ROOT]:
        if base.exists():
            if (base / "backtests").exists():
                candidates.append(base / "backtests")
            candidates.append(base)
    seen = set()
    ordered = []
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        ordered.append(cand)
    for cand in ordered:
        runs = load_backtest_recursive(cand)
        if runs:
            return cand, runs, None
    return (ordered[0] if ordered else None), [], None


def clean_list(values: Sequence) -> List[Optional[float]]:
    cleaned: List[Optional[float]] = []
    for value in values:
        if pd.isna(value):
            cleaned.append(None)
        elif isinstance(value, (np.integer, int)):
            cleaned.append(int(value))
        else:
            cleaned.append(float(value))
    return cleaned


def clean_str_list(values: Sequence) -> List[Optional[str]]:
    cleaned: List[Optional[str]] = []
    for value in values:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            cleaned.append(None)
        else:
            cleaned.append(str(value))
    return cleaned


def discover_levels(book: pd.DataFrame) -> List[int]:
    levels = set()
    for col in book.columns:
        if col.startswith("bid_price_") or col.startswith("ask_price_"):
            try:
                levels.add(int(col.split("_")[-1]))
            except ValueError:
                continue
    return sorted(levels)


def build_book_payload(book: pd.DataFrame, symbols: List[str], levels: Sequence[int]) -> Dict[str, dict]:
    payload: Dict[str, dict] = {}
    for symbol in symbols:
        subset = book[book["symbol"] == symbol].sort_values("global_time")
        payload[symbol] = {
            "global_time": clean_list(subset["global_time"].to_numpy()),
            "timestamp": clean_list(subset["timestamp"].to_numpy()),
            "day": clean_list(subset["day"].to_numpy()),
            "mid_price": clean_list(subset["mid_price"].to_numpy()),
            "wall_mid": clean_list(subset["wall_mid"].to_numpy()),
            "wall_mid_outer": clean_list(subset.get("wall_mid_outer", pd.Series([np.nan] * len(subset))).to_numpy()),
            "spread": clean_list(subset["spread"].to_numpy()),
            "book_imbalance": clean_list(subset["book_imbalance"].to_numpy()),
            "top3_bid_volume": clean_list(subset["top3_bid_volume"].to_numpy()),
            "top3_ask_volume": clean_list(subset["top3_ask_volume"].to_numpy()),
        }
        for level in levels:
            payload[symbol][f"bid_price_{level}"] = clean_list(subset[f"bid_price_{level}"].to_numpy())
            payload[symbol][f"ask_price_{level}"] = clean_list(subset[f"ask_price_{level}"].to_numpy())
            payload[symbol][f"bid_volume_{level}"] = clean_list(subset[f"bid_volume_{level}"].to_numpy())
            payload[symbol][f"ask_volume_{level}"] = clean_list(subset[f"ask_volume_{level}"].to_numpy())
    return payload


def build_trade_payload(trades: pd.DataFrame, symbols: List[str]) -> Dict[str, dict]:
    payload: Dict[str, dict] = {}
    if trades.empty:
        for symbol in symbols:
            payload[symbol] = {}
        return payload

    for symbol in symbols:
        subset = trades[trades["symbol"] == symbol].sort_values("global_time")
        payload[symbol] = {
            "global_time": clean_list(subset["global_time"].to_numpy()),
            "timestamp": clean_list(subset["timestamp"].to_numpy()),
            "day": clean_list(subset["day"].to_numpy()),
            "price": clean_list(subset["price"].to_numpy()),
            "quantity": clean_list(subset["quantity"].to_numpy()),
            "aggressor": clean_str_list(subset.get("aggressor", pd.Series(["unknown"] * len(subset))).to_numpy()),
            "trade_role": clean_str_list(subset.get("trade_role", pd.Series(["unknown"] * len(subset))).to_numpy()),
            "group": clean_str_list(subset.get("group", pd.Series(["M"] * len(subset))).to_numpy()),
            "group_tier": clean_str_list(subset.get("group_tier", pd.Series(["M1"] * len(subset))).to_numpy()),
            "abs_qty": clean_list(subset.get("abs_qty", subset["quantity"].abs()).to_numpy()),
            "buyer": clean_str_list(subset.get("buyer", pd.Series([None] * len(subset))).to_numpy()),
            "seller": clean_str_list(subset.get("seller", pd.Series([None] * len(subset))).to_numpy()),
            "mid_price": clean_list(subset.get("mid_price", pd.Series([np.nan] * len(subset))).to_numpy()),
            "wall_mid": clean_list(subset.get("wall_mid", pd.Series([np.nan] * len(subset))).to_numpy()),
            "wall_mid_outer": clean_list(subset.get("wall_mid_outer", pd.Series([np.nan] * len(subset))).to_numpy()),
            "bid_at_trade": clean_list(subset.get("bid_at_trade", pd.Series([np.nan] * len(subset))).to_numpy()),
            "ask_at_trade": clean_list(subset.get("ask_at_trade", pd.Series([np.nan] * len(subset))).to_numpy()),
        }
    return payload


def assign_trade_groups(trades: pd.DataFrame, config: VisualizerConfig) -> pd.DataFrame:
    if trades.empty:
        return trades
    trades = trades.copy()
    qty = trades["quantity"].abs().fillna(0)

    aggressor = trades.get("aggressor", pd.Series(["unknown"] * len(trades)))
    trade_role = np.where(aggressor.isin(["buy", "sell"]), "taker", "maker")
    trades["trade_role"] = trade_role

    buyer = trades.get("buyer", pd.Series([""] * len(trades))).fillna("").astype(str)
    seller = trades.get("seller", pd.Series([""] * len(trades))).fillna("").astype(str)

    own_tags = [tag.upper() for tag in config.own_trade_tags]
    is_own = buyer.str.upper().apply(lambda x: any(tag in x for tag in own_tags)) | seller.str.upper().apply(
        lambda x: any(tag in x for tag in own_tags)
    )

    informed = {t.upper() for t in config.informed_traders}
    is_informed = buyer.str.upper().isin(informed) | seller.str.upper().isin(informed)

    small_thr = config.small_trade_qty
    big_thr = config.big_trade_qty

    group = []
    for idx, role in enumerate(trade_role):
        if is_own.iloc[idx]:
            group.append("F")
            continue
        if is_informed.iloc[idx]:
            group.append("I")
            continue
        if role == "maker":
            group.append("M")
            continue
        size = qty.iloc[idx]
        if big_thr is not None and size >= big_thr:
            group.append("B")
        elif small_thr is not None and size <= small_thr:
            group.append("S")
        else:
            group.append("S")
    trades["group"] = group
    trades["abs_qty"] = qty
    trades["group_tier"] = ""

    tier_map = {"M": 3, "S": 4, "B": 2, "I": 2, "F": 1}
    for base_group, tier_count in tier_map.items():
        mask = trades["group"] == base_group
        if not mask.any():
            continue
        if tier_count <= 1:
            trades.loc[mask, "group_tier"] = f"{base_group}1"
            continue
        sizes = trades.loc[mask, "abs_qty"].astype(float)
        if sizes.nunique() <= 1:
            trades.loc[mask, "group_tier"] = f"{base_group}1"
            continue
        quantiles = np.linspace(0, 1, tier_count + 1)[1:-1]
        thresholds = [sizes.quantile(q) for q in quantiles]
        thresholds = sorted({float(t) for t in thresholds if not pd.isna(t)})

        def assign_tier(value: float) -> str:
            idx = int(np.searchsorted(thresholds, value, side="right")) + 1
            idx = max(1, min(tier_count, idx))
            return f"{base_group}{idx}"

        trades.loc[mask, "group_tier"] = sizes.apply(assign_tier)
    return trades


def align_indicators_to_book(
    book: pd.DataFrame,
    indicators: pd.DataFrame,
    columns: Sequence[str],
) -> Dict[str, Dict[str, List[Optional[float]]]]:
    if indicators.empty or not columns:
        return {}

    payload: Dict[str, Dict[str, List[Optional[float]]]] = {}
    has_symbol = "symbol" in indicators.columns
    has_day = "day" in indicators.columns

    for symbol in sorted(book["symbol"].unique()):
        book_sym = book[book["symbol"] == symbol].sort_values(["day", "timestamp"]).copy()
        if book_sym.empty:
            continue
        sym_ind = indicators
        if has_symbol:
            sym_ind = indicators[indicators["symbol"] == symbol].copy()
        if sym_ind.empty:
            continue

        aligned_parts = []
        for day, book_day in book_sym.groupby("day", sort=False):
            ind_day = sym_ind
            if has_day:
                ind_day = sym_ind[sym_ind["day"] == day]
            if ind_day.empty:
                aligned = pd.DataFrame({col: [np.nan] * len(book_day) for col in columns})
            else:
                ind_day = ind_day.sort_values("timestamp")
                aligned = pd.merge_asof(
                    book_day[["timestamp"]].reset_index(drop=True),
                    ind_day[["timestamp"] + list(columns)],
                    on="timestamp",
                    direction="backward",
                )
                aligned = aligned.drop(columns=["timestamp"])
            aligned_parts.append(aligned)

        aligned_full = pd.concat(aligned_parts, ignore_index=True)
        payload[symbol] = {col: clean_list(aligned_full[col].to_numpy()) for col in columns}

    return payload


def align_indicators_to_trades(
    trades: pd.DataFrame,
    indicators: pd.DataFrame,
    columns: Sequence[str],
) -> Dict[str, Dict[str, List[Optional[float]]]]:
    if trades.empty or indicators.empty or not columns:
        return {}

    payload: Dict[str, Dict[str, List[Optional[float]]]] = {}
    has_symbol = "symbol" in indicators.columns
    has_day = "day" in indicators.columns

    for symbol in sorted(trades["symbol"].unique()):
        trades_sym = trades[trades["symbol"] == symbol].sort_values(["day", "timestamp"]).copy()
        if trades_sym.empty:
            continue
        sym_ind = indicators
        if has_symbol:
            sym_ind = indicators[indicators["symbol"] == symbol].copy()
        if sym_ind.empty:
            continue

        aligned_parts = []
        for day, trades_day in trades_sym.groupby("day", sort=False):
            ind_day = sym_ind
            if has_day:
                ind_day = sym_ind[sym_ind["day"] == day]
            if ind_day.empty:
                aligned = pd.DataFrame({col: [np.nan] * len(trades_day) for col in columns})
            else:
                ind_day = ind_day.sort_values("timestamp")
                aligned = pd.merge_asof(
                    trades_day[["timestamp"]].reset_index(drop=True),
                    ind_day[["timestamp"] + list(columns)],
                    on="timestamp",
                    direction="backward",
                )
                aligned = aligned.drop(columns=["timestamp"])
            aligned_parts.append(aligned)

        aligned_full = pd.concat(aligned_parts, ignore_index=True)
        payload[symbol] = {col: clean_list(aligned_full[col].to_numpy()) for col in columns}

    return payload


def compute_path_anchor_series(subset: pd.DataFrame) -> pd.Series:
    if subset.empty or subset["mid_price"].notna().sum() < 10:
        return pd.Series(np.nan, index=subset.index)

    ordered = subset.sort_values(["day", "timestamp"]).copy()
    day_center = ordered.groupby("day")["mid_price"].transform("median")
    normalized = ordered["mid_price"] - day_center
    template = normalized.groupby(ordered["timestamp"]).median()
    fair = ordered["timestamp"].map(template) + day_center
    return fair.reindex(subset.index)


def _profile_template(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "family": "generic",
        "fairIndicator": None,
        "residualIndicator": None,
        "supportsExtrema": symbol in EXTREMA_SCAN_PRODUCTS,
        "description": "",
    }


def build_derived_indicator_entries(prices: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, dict], List[dict]]:
    if prices.empty:
        return pd.DataFrame(), {}, [{"id": "manual", "label": "Manual", "description": "Manual controls only."}]

    symbol_frames: Dict[str, pd.DataFrame] = {}
    profiles: Dict[str, dict] = {}

    for symbol in sorted(prices["symbol"].unique()):
        subset = prices[prices["symbol"] == symbol].sort_values(["day", "timestamp"]).copy()
        frame = subset[["symbol", "day", "timestamp"]].reset_index(drop=True)
        mid = subset["mid_price"].reset_index(drop=True)
        profile = _profile_template(symbol)

        if symbol in FIXED_FAIR_PRODUCTS:
            fair = float(FIXED_FAIR_PRODUCTS[symbol])
            frame["static_fair"] = fair
            frame["static_fair_residual"] = mid - fair
            frame["fair_value"] = fair
            frame["fair_residual"] = mid - fair
            profile["family"] = "fixed_fair"
            profile["fairIndicator"] = "fair_value"
            profile["residualIndicator"] = "fair_residual"
            profile["description"] = f"{symbol} is treated as a fixed-fair product around {fair:.0f}."

        if symbol in PATH_ANCHOR_PRODUCTS:
            path_anchor = compute_path_anchor_series(subset).reset_index(drop=True)
            frame["path_anchor_fair"] = path_anchor
            frame["path_anchor_residual"] = mid - path_anchor
            frame["fair_value"] = path_anchor
            frame["fair_residual"] = mid - path_anchor
            profile["family"] = "path_anchor"
            profile["fairIndicator"] = "fair_value"
            profile["residualIndicator"] = "fair_residual"
            profile["description"] = f"{symbol} uses a repeated intraday path anchor as the fair-value model."

        symbol_frames[symbol] = frame
        profiles[symbol] = profile

    pivot = prices.pivot_table(index=["day", "timestamp"], columns="symbol", values="mid_price", aggfunc="last")

    for basket, components in BASKET_COMPOSITIONS.items():
        if basket not in symbol_frames:
            continue
        if not set(components).issubset(set(pivot.columns)):
            continue

        synthetic = pd.Series(0.0, index=pivot.index)
        for component, weight in components.items():
            synthetic = synthetic + float(weight) * pivot[component]

        basket_subset = prices[prices["symbol"] == basket].sort_values(["day", "timestamp"]).copy()
        key_index = pd.MultiIndex.from_frame(basket_subset[["day", "timestamp"]])
        synthetic_aligned = synthetic.reindex(key_index).to_numpy()
        mid = basket_subset["mid_price"].to_numpy()

        frame = symbol_frames[basket]
        frame["synthetic_fair"] = synthetic_aligned
        frame["basket_premium"] = mid - synthetic_aligned
        frame["fair_value"] = synthetic_aligned
        frame["fair_residual"] = frame["basket_premium"]

        profiles[basket]["family"] = "basket"
        profiles[basket]["fairIndicator"] = "fair_value"
        profiles[basket]["residualIndicator"] = "basket_premium"
        profiles[basket]["description"] = f"{basket} fair value is the synthetic sum of its constituents."

    if {"PICNIC_BASKET1", "PICNIC_BASKET2", "DJEMBES"}.issubset(set(pivot.columns)):
        cross_spread = pivot["PICNIC_BASKET1"] - 1.5 * pivot["PICNIC_BASKET2"] - pivot["DJEMBES"]
        for symbol in ["PICNIC_BASKET1", "PICNIC_BASKET2", "DJEMBES"]:
            if symbol not in symbol_frames:
                continue
            subset = prices[prices["symbol"] == symbol].sort_values(["day", "timestamp"]).copy()
            key_index = pd.MultiIndex.from_frame(subset[["day", "timestamp"]])
            symbol_frames[symbol]["cross_basket_spread"] = cross_spread.reindex(key_index).to_numpy()

    derived = pd.concat(symbol_frames.values(), ignore_index=True, sort=False)
    indicator_columns = [
        col
        for col in derived.columns
        if col not in {"symbol", "day", "timestamp"}
        and pd.api.types.is_numeric_dtype(derived[col])
    ]

    presets: List[dict] = [
        {"id": "manual", "label": "Manual", "description": "Manual controls only."},
    ]

    for symbol in sorted(prices["symbol"].unique()):
        profile = profiles[symbol]
        family = profile["family"]
        if family == "fixed_fair":
            presets.append(
                {
                    "id": f"{symbol.lower()}_fair",
                    "label": f"{symbol} Fair",
                    "description": profile["description"],
                    "symbol": symbol,
                    "normalizeBy": "indicator:fair_value",
                    "normalizedBy": "indicator:fair_value",
                    "indicatorNames": ["fair_value", "fair_residual"],
                    "showNormalized": True,
                }
            )
        elif family == "path_anchor":
            presets.append(
                {
                    "id": f"{symbol.lower()}_path",
                    "label": f"{symbol} Path",
                    "description": profile["description"],
                    "symbol": symbol,
                    "normalizeBy": "indicator:fair_value",
                    "normalizedBy": "indicator:fair_value",
                    "indicatorNames": ["fair_value", "path_anchor_residual"],
                    "showNormalized": True,
                }
            )
        elif family == "basket":
            basket_indicators = ["fair_value", "basket_premium"]
            if "cross_basket_spread" in indicator_columns:
                basket_indicators.append("cross_basket_spread")
            presets.append(
                {
                    "id": f"{symbol.lower()}_basket",
                    "label": f"{symbol} Basket",
                    "description": profile["description"],
                    "symbol": symbol,
                    "normalizeBy": "indicator:fair_value",
                    "normalizedBy": "indicator:fair_value",
                    "indicatorNames": basket_indicators,
                    "showNormalized": True,
                }
            )

    extrema_symbol = next((sym for sym in ["SQUID_INK", "CROISSANTS"] if sym in prices["symbol"].unique()), None)
    if extrema_symbol:
        presets.append(
            {
                "id": "extrema_scan",
                "label": "Extrema Scan",
                "description": "Highlights trades near running daily lows and highs, useful for Olivia-style bot detection.",
                "symbol": extrema_symbol,
                "normalizeBy": "none",
                "normalizedBy": "wall_mid",
                "indicatorNames": [],
                "showNormalized": False,
                "extremaQty": 15,
            }
        )

    return derived, profiles, presets


def merge_indicator_payloads(
    base_payload: Dict[str, Dict[str, List[Optional[float]]]],
    extra_payload: Dict[str, Dict[str, List[Optional[float]]]],
) -> Dict[str, Dict[str, List[Optional[float]]]]:
    merged: Dict[str, Dict[str, List[Optional[float]]]] = {}
    for symbol in set(base_payload) | set(extra_payload):
        merged[symbol] = {}
        if symbol in base_payload:
            merged[symbol].update(base_payload[symbol])
        if symbol in extra_payload:
            merged[symbol].update(extra_payload[symbol])
    return merged


def build_backtest_payload(dataset_dirs: List[Path], id_map: Dict[Path, str]) -> Dict[str, dict]:
    if not dataset_dirs:
        return {}
    payload: Dict[str, dict] = {}
    for dataset_dir in dataset_dirs:
        equity_path = dataset_dir / "equity_curve.csv"
        if not equity_path.exists():
            continue
        equity = pd.read_csv(equity_path)
        entry: Dict[str, dict] = {
            "day": clean_list(equity.get("day", pd.Series([np.nan] * len(equity))).to_numpy()),
            "timestamp": clean_list(equity.get("timestamp", pd.Series([np.nan] * len(equity))).to_numpy()),
            "step": clean_list(equity["step"].to_numpy()),
            "total_pnl": clean_list(equity.get("total_pnl", pd.Series([np.nan] * len(equity))).to_numpy()),
            "realized_pnl": clean_list(equity.get("realized_pnl", pd.Series([np.nan] * len(equity))).to_numpy()),
            "unrealized_pnl": clean_list(equity.get("unrealized_pnl", pd.Series([np.nan] * len(equity))).to_numpy()),
        }
        for col in equity.columns:
            if col.startswith("position_"):
                entry[col] = clean_list(equity[col].to_numpy())
            if col.startswith("pnl_"):
                entry[col] = clean_list(equity[col].to_numpy())
        dataset_id = id_map.get(dataset_dir, dataset_dir.name)
        payload[dataset_id] = entry
    return payload


def build_log_payload(config: VisualizerConfig) -> List[dict]:
    if not config.log_file:
        return []
    logs = load_log_entries(config.log_file)
    if logs.empty:
        return []
    logs = logs.tail(config.log_max_rows)
    rows: List[dict] = []
    for row in logs.to_dict(orient="records"):
        cleaned = {}
        for key, value in row.items():
            if pd.isna(value):
                cleaned[key] = None
            elif isinstance(value, (np.integer, int)):
                cleaned[key] = int(value)
            elif isinstance(value, float):
                cleaned[key] = float(value)
            else:
                cleaned[key] = str(value)
        rows.append(cleaned)
    return rows


def compute_global_time_reference(prices: pd.DataFrame) -> Tuple[Dict[int, int], int]:
    days = sorted(prices["day"].dropna().unique().tolist())
    day_index = {day: idx for idx, day in enumerate(days)}
    max_ts = prices["timestamp"].max()
    span = int(max_ts + 1) if not pd.isna(max_ts) else 1
    return day_index, span


def build_fills_payload(
    dataset_dirs: List[Path],
    id_map: Dict[Path, str],
    prices_by_source: Dict[str, pd.DataFrame],
    backtest_index: List[dict],
) -> Dict[str, Dict[str, dict]]:
    if not dataset_dirs:
        return {}

    payload: Dict[str, Dict[str, dict]] = {}
    index_by_id = {entry["id"]: entry for entry in backtest_index}

    for dataset_dir in dataset_dirs:
        dataset_id = id_map.get(dataset_dir, dataset_dir.name)
        market_source = index_by_id.get(dataset_id, {}).get("marketSource")
        prices = prices_by_source.get(market_source, pd.DataFrame())
        if prices.empty:
            continue
        day_index, span = compute_global_time_reference(prices)
        fills_path = dataset_dir / "fills.csv"
        if not fills_path.exists():
            continue
        try:
            fills = pd.read_csv(fills_path)
        except pd.errors.EmptyDataError:
            continue
        if fills.empty:
            continue
        for col in ["day", "timestamp", "price", "quantity"]:
            if col in fills.columns:
                fills[col] = pd.to_numeric(fills[col], errors="coerce")
        fills = fills.dropna(subset=["day", "timestamp", "price"])
        fills = fills[fills["day"].isin(day_index.keys())].copy()
        if fills.empty:
            continue
        fills["symbol"] = fills["symbol"].astype(str)
        fills["global_time"] = fills["day"].map(day_index).astype(float) * span + fills["timestamp"].astype(float)
        fills = fills.sort_values("global_time")

        dataset_payload: Dict[str, dict] = {}
        for symbol, group in fills.groupby("symbol"):
            dataset_payload[symbol] = {
                "global_time": clean_list(group["global_time"].to_numpy()),
                "day": clean_list(group["day"].to_numpy()),
                "timestamp": clean_list(group["timestamp"].to_numpy()),
                "price": clean_list(group["price"].to_numpy()),
                "quantity": clean_list(group["quantity"].to_numpy()),
                "side": clean_str_list(group.get("side", pd.Series(["unknown"] * len(group))).to_numpy()),
            }
        payload[dataset_id] = dataset_payload

    return payload


def build_orders_payload(
    dataset_dirs: List[Path],
    id_map: Dict[Path, str],
    prices_by_source: Dict[str, pd.DataFrame],
    backtest_index: List[dict],
) -> Dict[str, Dict[str, dict]]:
    if not dataset_dirs:
        return {}

    payload: Dict[str, Dict[str, dict]] = {}
    index_by_id = {entry["id"]: entry for entry in backtest_index}

    for dataset_dir in dataset_dirs:
        dataset_id = id_map.get(dataset_dir, dataset_dir.name)
        market_source = index_by_id.get(dataset_id, {}).get("marketSource")
        prices = prices_by_source.get(market_source, pd.DataFrame())
        if prices.empty:
            continue
        day_index, span = compute_global_time_reference(prices)
        orders_path = dataset_dir / "orders.csv"
        if not orders_path.exists():
            continue
        try:
            orders = pd.read_csv(orders_path)
        except pd.errors.EmptyDataError:
            continue
        if orders.empty:
            continue
        for col in [
            "day",
            "timestamp",
            "price",
            "requested_qty",
            "executed_qty",
            "remaining_qty",
            "immediate_qty",
            "passive_qty",
        ]:
            if col in orders.columns:
                orders[col] = pd.to_numeric(orders[col], errors="coerce")
        orders = orders.dropna(subset=["day", "timestamp", "price"])
        orders = orders[orders["day"].isin(day_index.keys())].copy()
        if orders.empty:
            continue
        orders["symbol"] = orders["symbol"].astype(str)
        orders["global_time"] = orders["day"].map(day_index).astype(float) * span + orders["timestamp"].astype(float)
        orders = orders.sort_values("global_time")

        dataset_payload: Dict[str, dict] = {}
        for symbol, group in orders.groupby("symbol"):
            dataset_payload[symbol] = {
                "global_time": clean_list(group["global_time"].to_numpy()),
                "day": clean_list(group["day"].to_numpy()),
                "timestamp": clean_list(group["timestamp"].to_numpy()),
                "price": clean_list(group["price"].to_numpy()),
                "side": clean_str_list(group.get("side", pd.Series(["unknown"] * len(group))).to_numpy()),
                "requested_qty": clean_list(group.get("requested_qty", pd.Series([np.nan] * len(group))).to_numpy()),
                "executed_qty": clean_list(group.get("executed_qty", pd.Series([np.nan] * len(group))).to_numpy()),
                "remaining_qty": clean_list(group.get("remaining_qty", pd.Series([np.nan] * len(group))).to_numpy()),
                "immediate_qty": clean_list(group.get("immediate_qty", pd.Series([np.nan] * len(group))).to_numpy()),
                "passive_qty": clean_list(group.get("passive_qty", pd.Series([np.nan] * len(group))).to_numpy()),
            }
        payload[dataset_id] = dataset_payload

    return payload


def write_html(
    output_path: Path,
    data_payload: dict,
    config: VisualizerConfig,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>chud life</title>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
  <link href=\"https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap\" rel=\"stylesheet\">
  <script src=\"https://cdn.plot.ly/plotly-2.27.0.min.js\"></script>
  <style>
    :root {{
      --bg: #f4f5f7;
      --panel: #ffffff;
      --text: #0b0b0b;
      --muted: #475569;
      --accent: #111111;
      --border: #111111;
      --border-soft: #d1d5db;
      --grid: #e5e7eb;
      --shadow: 0 6px 16px rgba(15, 23, 42, 0.08);
      --radius: 6px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: 'Space Grotesk', 'IBM Plex Sans', sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      padding: 10px 16px;
      border-bottom: 2px solid var(--border);
      background: #ffffff;
    }}
    header h1 {{ margin: 0; font-size: 18px; font-weight: 700; letter-spacing: 0.02em; }}
    header .meta {{ color: var(--muted); font-size: 13px; }}
    .layout {{ display: grid; grid-template-columns: 1fr 340px; gap: 14px; padding: 16px; align-items: start; }}
    .grid {{ grid-column: 1; grid-row: 1; }}
    .panel {{ grid-column: 2; grid-row: 1; }}
    .panel {{
      background: var(--panel);
      border: 1.5px solid var(--border);
      border-radius: var(--radius);
      padding: 12px;
      box-shadow: var(--shadow);
    }}
    .panel h2 {{
      margin: 0 0 8px 0;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    label {{ display: block; margin-top: 8px; font-size: 11px; color: var(--muted); }}
    select, input[type=number], input[type=text] {{
      width: 100%;
      padding: 6px 8px;
      border-radius: 6px;
      border: 1px solid var(--border-soft);
      font-size: 12px;
      background: #fff;
    }}
    select:focus, input[type=number]:focus, input[type=text]:focus {{
      outline: 2px solid rgba(59, 130, 246, 0.25);
      border-color: #93c5fd;
    }}
    button {{
      padding: 6px 10px;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: #ffffff;
      cursor: pointer;
      font-size: 12px;
      transition: background 0.15s ease;
    }}
    button:hover {{ background: #f1f5f9; }}
    input[type=range] {{ width: 100%; accent-color: var(--accent); }}
    input[type=checkbox] {{ accent-color: var(--accent); }}
    .checklist {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px; margin-top: 4px; }}
    .checklist label {{
      margin: 0;
      font-size: 11px;
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 2px 2px;
      border-radius: 0;
      background: transparent;
    }}
    .chart {{
      background: var(--panel);
      border: 1.5px solid var(--border);
      border-radius: var(--radius);
      padding: 8px;
      box-shadow: var(--shadow);
    }}
    .chart + .chart {{ margin-top: 16px; }}
    .chart-title {{ font-weight: 600; margin-bottom: 4px; color: var(--text); font-size: 12px; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 8px; }}
    .subgrid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 8px; }}
    .orderbook-table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
    .orderbook-table th, .orderbook-table td {{ border-bottom: 1px solid var(--border); padding: 4px; text-align: right; }}
    .orderbook-table th {{ text-align: center; background: #f8f8f8; color: var(--muted); }}
    .stats-table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
    .stats-table td {{ border-bottom: 1px solid #e5e5e5; padding: 4px; text-align: right; }}
    .stats-table td:first-child {{ text-align: left; color: var(--muted); }}
    .log-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    .log-table th, .log-table td {{ border-bottom: 1px solid var(--border); padding: 6px; text-align: left; }}
    .log-table th {{ color: var(--muted); font-weight: 600; }}
    .hover-meta {{ font-size: 12px; color: var(--muted); margin-top: 6px; }}
    .key-table {{ font-size: 11px; }}
    .key-row {{ display: flex; align-items: center; gap: 6px; margin: 3px 0; }}
    .key-swatch {{ width: 10px; height: 10px; border: 1px solid #111; display: inline-block; }}
    .key-line {{ width: 18px; height: 2px; display: inline-block; }}
    @media (max-width: 960px) {{
      .layout {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>chud life</h1>
    <div class=\"meta\">Generated {generated_at}</div>
  </header>
  <main class=\"layout\">
    <section class=\"panel\">
      <h2>Controls</h2>
      <label for=\"symbolSelect\">Symbol</label>
      <select id=\"symbolSelect\"></select>

      <label for=\"daySelect\">Day</label>
      <select id=\"daySelect\"></select>

      <label for=\"timeAxisSelect\">Time axis</label>
      <select id=\"timeAxisSelect\">
        <option value=\"timestamp\">Timestamp (per day)</option>
        <option value=\"global\">Global time (all days)</option>
      </select>

      <label for=\"roundSelect\">Round</label>
      <select id=\"roundSelect\"></select>

      <label for=\"strategySelect\">Strategy</label>
      <select id=\"strategySelect\"></select>

      <label for=\"datasetSelect\">Run</label>
      <select id=\"datasetSelect\"></select>

      <label for=\"backtestDaySelect\">Backtest day</label>
      <select id=\"backtestDaySelect\"></select>

      <label for=\"presetSelect\">Preset</label>
      <select id=\"presetSelect\"></select>
      <div class=\"hover-meta\" id=\"presetMeta\">Manual controls only.</div>

      <label for=\"normalizeSelect\">Normalize by</label>
      <select id=\"normalizeSelect\">
        <option value=\"none\">None</option>
        <option value=\"wall_mid\">Wall mid</option>
        <option value=\"wall_mid_outer\">Wall mid (outer)</option>
        <option value=\"mid_price\">Mid price</option>
        <option value=\"bid_price_1\">Bid L1</option>
        <option value=\"ask_price_1\">Ask L1</option>
      </select>

      <label>Indicator overlays</label>
      <div class=\"checklist\" id=\"indicatorChecks\"></div>

      <label>Trade quantity filter</label>
      <div class=\"subgrid\">
        <input id=\"minQty\" type=\"number\" placeholder=\"Min qty\">
        <input id=\"maxQty\" type=\"number\" placeholder=\"Max qty\">
      </div>

      <label for=\"extremaQty\">Extrema qty</label>
      <input id=\"extremaQty\" type=\"number\" placeholder=\"Exact qty for extrema scan\">

      <label for=\"downsample\">Downsample</label>
      <input id=\"downsample\" type=\"range\" min=\"1\" max=\"50\" value=\"1\">
      <div class=\"hover-meta\">Every <span id=\"downsampleValue\">1</span> points</div>

      <label>Order book levels</label>
      <div class=\"checklist\" id=\"levelChecks\"></div>

      <label>Trade groups</label>
      <div class=\"checklist\" id=\"groupChecks\"></div>

      <label>Specific traders</label>
      <div class=\"checklist\" id=\"traderChecks\"></div>

      <label>Trade side</label>
      <div class=\"checklist\" id=\"sideChecks\"></div>

      <label>Own fills</label>
      <div class=\"checklist\" id=\"fillChecks\"></div>

      <label>Our quotes</label>
      <div class=\"checklist\">
        <label><input id=\"showOrders\" type=\"checkbox\"> Show our quotes</label>
        <label><input id=\"ordersPassiveOnly\" type=\"checkbox\" checked> Passive only</label>
      </div>

      <label>Cursor</label>
      <div class=\"subgrid\">
        <input id=\"timestampInput\" type=\"number\" placeholder=\"Timestamp\">
        <input id=\"stepSize\" type=\"number\" value=\"100\" min=\"1\" placeholder=\"Step\">
      </div>
      <div class=\"subgrid\">
        <button id=\"btnLeft\" type=\"button\">&larr;</button>
        <button id=\"btnRight\" type=\"button\">&rarr;</button>
      </div>
      <div class=\"hover-meta\" id=\"cursorMeta\">No cursor set</div>

      <label>Compare runs</label>
      <select id=\"compareDatasetA\"></select>
      <select id=\"compareDatasetB\"></select>
      <select id=\"compareMetric\"></select>
      <select id=\"compareSymbol\"></select>

      <label for=\"logSearch\">Log search</label>
      <input id=\"logSearch\" type=\"text\" placeholder=\"Filter log entries\">
      <div class=\"hover-meta\" id=\"hoverInfo\">Hover a point to sync logs.</div>

      <label>Log viewer</label>
      <div id=\"logs\" style=\"max-height: 220px; overflow: auto;\"></div>

      <label>Order book snapshot</label>
      <div id=\"orderbookTable\"></div>

      <label>Stats</label>
      <div id=\"statsTable\"></div>

      <label>Key</label>
      <div class=\"key-table\">
        <div class=\"key-row\"><span class=\"key-line\" style=\"background:#0b51ff\"></span> Bid L1 (line)</div>
        <div class=\"key-row\"><span class=\"key-line\" style=\"background:#ff1e1e\"></span> Ask L1 (line)</div>
        <div class=\"key-row\"><span class=\"key-line\" style=\"background:#222\"></span> Mid (line)</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#f59e0b\"></span> M1 square</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#f97316\"></span> M2 square</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#ef4444\"></span> M3 square</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#22c55e\"></span> S1 triangle</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#16a34a\"></span> S2 triangle</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#84cc16\"></span> S3 triangle</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#a3e635\"></span> S4 triangle</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#2563eb\"></span> B1 triangle</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#1d4ed8\"></span> B2 triangle</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#8b5cf6\"></span> I1 cross</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#7c3aed\"></span> I2 cross</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#111\"></span> F1 star (ours)</div>
        <div class=\"key-row\"><span class=\"key-swatch\" style=\"background:#f59e0b\"></span> Our fills (cross)</div>
      </div>

      <label>Extras</label>
      <div class=\"checklist\">
        <label><input id=\"showExtras\" type=\"checkbox\"> Show extra charts</label>
        <label><input id=\"showNormalized\" type=\"checkbox\"> Normalized panel</label>
      </div>

      <label for=\"normalizedSelect\">Normalized base</label>
      <select id=\"normalizedSelect\">
        <option value=\"wall_mid\">Wall mid</option>
        <option value=\"wall_mid_outer\">Wall mid (outer)</option>
        <option value=\"mid_price\">Mid price</option>
        <option value=\"bid_price_1\">Bid L1</option>
        <option value=\"ask_price_1\">Ask L1</option>
      </select>

      <label>Plot lab</label>
      <select id=\"plotSource\"></select>
      <select id=\"plotX\"></select>
      <select id=\"plotY\"></select>
      <select id=\"plotType\">
        <option value=\"line\">Line</option>
        <option value=\"scatter\">Scatter</option>
        <option value=\"hist\">Histogram</option>
      </select>
      <select id=\"plotFit\">
        <option value=\"none\">Fit: none</option>
        <option value=\"linear\">Fit: linear</option>
        <option value=\"quadratic\">Fit: quadratic</option>
      </select>
    </section>

    <section class=\"grid\">
      <div class=\"chart\">
        <div class=\"chart-title\">Order book + trades</div>
        <div id=\"orderbook\" style=\"height: 520px;\"></div>
      </div>

      <div class=\"subgrid\">
        <div class=\"chart\">
          <div class=\"chart-title\">PnL</div>
          <div id=\"pnl\" style=\"height: 300px;\"></div>
        </div>
        <div class=\"chart\">
          <div class=\"chart-title\">Position</div>
          <div id=\"position\" style=\"height: 300px;\"></div>
        </div>
      </div>

      <div id=\"extras\" style=\"display: none;\">
        <div class=\"subgrid\">
          <div class=\"chart\">
            <div class=\"chart-title\">Depth & imbalance</div>
            <div id=\"depth\" style=\"height: 280px;\"></div>
          </div>
          <div class=\"chart\">
            <div class=\"chart-title\">Compare</div>
            <div id=\"compare\" style=\"height: 280px;\"></div>
          </div>
        </div>
        <div class=\"subgrid\" style=\"margin-top: 12px;\">
          <div class=\"chart\">
            <div class=\"chart-title\">Spread & mid</div>
            <div id=\"spreadChart\" style=\"height: 240px;\"></div>
          </div>
          <div class=\"chart\">
            <div class=\"chart-title\">Order flow</div>
            <div id=\"flowChart\" style=\"height: 240px;\"></div>
          </div>
        </div>
        <div class=\"subgrid\" style=\"margin-top: 12px;\">
          <div class=\"chart\">
            <div class=\"chart-title\">Trade sizes</div>
            <div id=\"sizeChart\" style=\"height: 240px;\"></div>
          </div>
          <div class=\"chart\">
            <div class=\"chart-title\">Interarrival</div>
            <div id=\"interarrivalChart\" style=\"height: 240px;\"></div>
          </div>
        </div>
        <div class=\"subgrid\" style=\"margin-top: 12px;\">
          <div class=\"chart\" id=\"normalizedPanelWrap\" style=\"display: none;\">
            <div class=\"chart-title\">Order book (normalized)</div>
            <div id=\"orderbookNormalized\" style=\"height: 220px;\"></div>
          </div>
          <div class=\"chart\">
            <div class=\"chart-title\">Plot lab</div>
            <div id=\"plotLab\" style=\"height: 320px;\"></div>
          </div>
        </div>
        <div class=\"subgrid\" style=\"margin-top: 12px;\">
          <div class=\"chart\">
            <div class=\"chart-title\">Fair value overlay</div>
            <div id=\"fairValueChart\" style=\"height: 260px;\"></div>
          </div>
          <div class=\"chart\">
            <div class=\"chart-title\">Relative value</div>
            <div id=\"structureChart\" style=\"height: 260px;\"></div>
          </div>
        </div>
        <div class=\"chart\" style=\"margin-top: 12px;\">
          <div class=\"chart-title\">Extrema detector</div>
          <div id=\"extremaChart\" style=\"height: 280px;\"></div>
        </div>
        <div class=\"subgrid\" style=\"margin-top: 12px;\">
          <div class=\"chart\">
            <div class=\"chart-title\">Intraday path profile</div>
            <div id=\"pathProfileChart\" style=\"height: 260px;\"></div>
          </div>
          <div class=\"chart\">
            <div class=\"chart-title\">Return autocorr</div>
            <div id=\"autocorrChart\" style=\"height: 260px;\"></div>
          </div>
        </div>
        <div class=\"chart\" style=\"margin-top: 12px;\">
          <div class=\"chart-title\">Imbalance response</div>
          <div id=\"imbalanceResponseChart\" style=\"height: 280px;\"></div>
        </div>
      </div>
    </section>
  </main>

  <script>
    const DATA = {json.dumps(data_payload)};
    const DEFAULTS = DATA.defaults || {{}};
    const DEFAULT_NORMALIZE = DEFAULTS.normalizeBy ?? 'none';
    const DEFAULT_NORMALIZED = (DEFAULT_NORMALIZE && DEFAULT_NORMALIZE !== 'none') ? DEFAULT_NORMALIZE : 'wall_mid';

    const state = {{
      marketSource: DEFAULTS.marketSource || null,
      symbol: null,
      dataset: DEFAULTS.dataset || DATA.backtestDatasets[0] || null,
      presetId: DEFAULTS.presetId || 'manual',
      normalizeBy: DEFAULT_NORMALIZE,
      minQty: DEFAULTS.minQty ?? null,
      maxQty: DEFAULTS.maxQty ?? null,
      extremaQty: DEFAULTS.extremaQty ?? null,
      downsample: 1,
      levels: {{}},
      indicators: {{}},
      groups: {{}},
      traders: {{}},
      sides: {{buy: true, sell: true, unknown: true}},
      showFills: true,
      showOrders: DATA.orders && Object.keys(DATA.orders).length > 0,
      ordersPassiveOnly: true,
      showNormalized: true,
      showExtras: true,
      normalizedBy: DEFAULT_NORMALIZED,
      plotSource: 'book',
      plotX: null,
      plotY: null,
      plotType: 'line',
      plotFit: 'none',
      dayFilter: 'all',
      timeAxis: 'timestamp',
      backtestDayFilter: 'all',
      backtestDayManual: false,
      roundFilter: DEFAULTS.roundFilter || 'all',
      strategyFilter: 'all',
      cursorIndex: 0,
      currentIndices: [],
    }};

    const symbolSelect = document.getElementById('symbolSelect');
    const daySelect = document.getElementById('daySelect');
    const timeAxisSelect = document.getElementById('timeAxisSelect');
    const roundSelect = document.getElementById('roundSelect');
    const strategySelect = document.getElementById('strategySelect');
    const datasetSelect = document.getElementById('datasetSelect');
    const backtestDaySelect = document.getElementById('backtestDaySelect');
    const presetSelect = document.getElementById('presetSelect');
    const presetMeta = document.getElementById('presetMeta');
    const normalizeSelect = document.getElementById('normalizeSelect');
    const minQtyInput = document.getElementById('minQty');
    const maxQtyInput = document.getElementById('maxQty');
    const extremaQtyInput = document.getElementById('extremaQty');
    const downsampleInput = document.getElementById('downsample');
    const downsampleValue = document.getElementById('downsampleValue');
    const levelChecks = document.getElementById('levelChecks');
    const indicatorChecks = document.getElementById('indicatorChecks');
    const groupChecks = document.getElementById('groupChecks');
    const traderChecks = document.getElementById('traderChecks');
    const sideChecks = document.getElementById('sideChecks');
    const fillChecks = document.getElementById('fillChecks');
    const showOrdersInput = document.getElementById('showOrders');
    const ordersPassiveOnlyInput = document.getElementById('ordersPassiveOnly');
    const timestampInput = document.getElementById('timestampInput');
    const stepSizeInput = document.getElementById('stepSize');
    const btnLeft = document.getElementById('btnLeft');
    const btnRight = document.getElementById('btnRight');
    const cursorMeta = document.getElementById('cursorMeta');
    const orderbookTable = document.getElementById('orderbookTable');
    const statsTable = document.getElementById('statsTable');
    const compareDatasetA = document.getElementById('compareDatasetA');
    const compareDatasetB = document.getElementById('compareDatasetB');
    const compareMetric = document.getElementById('compareMetric');
    const compareSymbol = document.getElementById('compareSymbol');
    const showExtras = document.getElementById('showExtras');
    const showNormalized = document.getElementById('showNormalized');
    const normalizedSelect = document.getElementById('normalizedSelect');
    const extras = document.getElementById('extras');
    const normalizedPanelWrap = document.getElementById('normalizedPanelWrap');
    const plotSource = document.getElementById('plotSource');
    const plotX = document.getElementById('plotX');
    const plotY = document.getElementById('plotY');
    const plotType = document.getElementById('plotType');
    const plotFit = document.getElementById('plotFit');
    const logSearch = document.getElementById('logSearch');
    const hoverInfo = document.getElementById('hoverInfo');

    const BACKTEST_INDEX = DATA.backtestIndex || [];
    const DATASET_LABELS = BACKTEST_INDEX.reduce((acc, entry) => {{
      acc[entry.id] = entry.label || entry.id;
      return acc;
    }}, {{}});
    const ROUND_OPTIONS = DATA.roundOptions || [];
    const STRATEGY_CATALOG = DATA.strategyCatalog || {{}};
    const MARKET_SOURCES = DATA.marketSources || [];
    const MARKET_SOURCE_INDEX = MARKET_SOURCES.reduce((acc, entry) => {{
      acc[entry.id] = entry;
      return acc;
    }}, {{}});
    const PRESETS = DATA.presets || [{{ id: 'manual', label: 'Manual', description: 'Manual controls only.' }}];
    const PRESET_INDEX = PRESETS.reduce((acc, preset) => {{
      acc[preset.id] = preset;
      return acc;
    }}, {{}});

    function getCurrentMarketMeta() {{
      return MARKET_SOURCE_INDEX[state.marketSource] || null;
    }}

    function getBookForSource(sourceId, symbol) {{
      return DATA.book?.[sourceId]?.[symbol] || null;
    }}

    function getTradesForSource(sourceId, symbol) {{
      return DATA.trades?.[sourceId]?.[symbol] || null;
    }}

    function getIndicatorsForSource(sourceId, symbol) {{
      return DATA.indicators?.[sourceId]?.[symbol] || {{}};
    }}

    function getTradeIndicatorsForSource(sourceId, symbol) {{
      return DATA.tradeIndicators?.[sourceId]?.[symbol] || {{}};
    }}

    function getCurrentBook() {{
      return getBookForSource(state.marketSource, state.symbol);
    }}

    function getCurrentTrades() {{
      return getTradesForSource(state.marketSource, state.symbol) || {{}};
    }}

    function getCurrentIndicatorData() {{
      return getIndicatorsForSource(state.marketSource, state.symbol);
    }}

    function getCurrentTradeIndicatorData() {{
      return getTradeIndicatorsForSource(state.marketSource, state.symbol);
    }}

    function hasCurrentMarketData() {{
      const book = getCurrentBook();
      return Boolean(book && book.timestamp && book.timestamp.length);
    }}

    function getMarketSourcesForRound(roundValue) {{
      const sources = MARKET_SOURCES.filter(entry => roundValue === 'all' || entry.round === roundValue);
      return sources.sort((a, b) => {{
        const kindRank = (a.kind === 'csv' ? 0 : 1) - (b.kind === 'csv' ? 0 : 1);
        if (kindRank !== 0) return kindRank;
        return String(a.label || a.id).localeCompare(String(b.label || b.id));
      }});
    }}

    function getAvailableSymbolsForSource(sourceId) {{
      const meta = MARKET_SOURCE_INDEX[sourceId];
      return meta?.symbols || [];
    }}

    function getDefaultMarketSourceForRound(roundValue, preferredSource = null) {{
      const sources = getMarketSourcesForRound(roundValue);
      if (!sources.length) return null;
      if (preferredSource && sources.some(entry => entry.id === preferredSource)) {{
        return preferredSource;
      }}
      const csvSource = sources.find(entry => entry.kind === 'csv');
      return (csvSource || sources[0]).id;
    }}

    function syncMarketSourceForRound(preferredSource = null) {{
      const nextSource = getDefaultMarketSourceForRound(state.roundFilter, preferredSource || state.marketSource);
      state.marketSource = nextSource;
      return nextSource;
    }}

    function syncSymbolOptions(preferredSymbol = null) {{
      const symbols = getAvailableSymbolsForSource(state.marketSource);
      symbolSelect.innerHTML = '';
      if (!symbols.length) {{
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'None';
        symbolSelect.appendChild(opt);
        symbolSelect.disabled = true;
        state.symbol = null;
        return symbols;
      }}
      symbolSelect.disabled = false;
      symbols.forEach(sym => {{
        const opt = document.createElement('option');
        opt.value = sym;
        opt.textContent = sym;
        symbolSelect.appendChild(opt);
      }});
      const nextSymbol = (preferredSymbol && symbols.includes(preferredSymbol))
        ? preferredSymbol
        : (symbols.includes(state.symbol) ? state.symbol : (symbols[0] || null));
      state.symbol = nextSymbol;
      if (state.symbol) {{
        symbolSelect.value = state.symbol;
      }}
      return symbols;
    }}

    function getFilteredBacktestEntries() {{
      return BACKTEST_INDEX.filter(entry => {{
        if (state.roundFilter !== 'all' && entry.round !== state.roundFilter) return false;
        if (state.strategyFilter !== 'all' && entry.strategy !== state.strategyFilter) return false;
        return true;
      }});
    }}

    function syncDatasetSelection(preferredDataset = null) {{
      if (state.roundFilter !== 'all' && getMarketSourcesForRound(state.roundFilter).length === 0) {{
        state.dataset = '';
        return [];
      }}
      const filtered = getFilteredBacktestEntries();
      if (!filtered.length) {{
        state.dataset = '';
        return filtered;
      }}
      const preferred = preferredDataset && filtered.find(entry => entry.id === preferredDataset)
        ? preferredDataset
        : null;
      const current = state.dataset && filtered.find(entry => entry.id === state.dataset)
        ? state.dataset
        : null;
      const marketMatch = filtered.find(entry => entry.marketSource === state.marketSource)?.id || null;
      state.dataset = preferred || current || marketMatch || filtered[0].id;
      return filtered;
    }}

    function getDatasetMeta(datasetId = null) {{
      if (!datasetId) return null;
      return BACKTEST_INDEX.find(entry => entry.id === datasetId) || null;
    }}

    function syncContextForMarketSource(options = {{}}) {{
      const {{
        preferredSource,
        preferredSymbol,
        preferredDataset,
        resetCursor = true,
      }} = options;

      const datasetMeta = getDatasetMeta(preferredDataset !== undefined ? preferredDataset : state.dataset);
      const datasetSource = datasetMeta?.marketSource || null;
      if (preferredSource !== undefined) {{
        state.marketSource = preferredSource;
      }} else if (datasetSource) {{
        state.marketSource = datasetSource;
      }}
      if (!state.marketSource || !MARKET_SOURCE_INDEX[state.marketSource]) {{
        state.marketSource = syncMarketSourceForRound(state.marketSource);
      }}

      syncSymbolOptions(preferredSymbol);
      syncDatasetSelection(preferredDataset);
      initDayOptions();
      initBacktestDayOptions();
      refreshTraderChecks();
      refreshCompareSymbolOptions();

      const book = getCurrentBook();
      if (book && book.timestamp && book.timestamp.length) {{
        const targetIdx = resetCursor
          ? Math.min(book.timestamp.length - 1, Math.floor(book.timestamp.length * 0.5))
          : Math.min(state.cursorIndex, book.timestamp.length - 1);
        state.cursorIndex = targetIdx;
        timestampInput.value = book.timestamp[targetIdx];
        cursorMeta.textContent = `Day ${{book.day[targetIdx]}} @ ${{book.timestamp[targetIdx]}}`;
      }} else {{
        state.cursorIndex = 0;
        timestampInput.value = '';
        cursorMeta.textContent = 'No book data';
      }}

      const bookForDownsample = getCurrentBook();
      if (bookForDownsample && bookForDownsample.global_time) {{
        const maxPoints = DEFAULTS.maxPoints || bookForDownsample.global_time.length;
        const suggested = Math.max(1, Math.floor(bookForDownsample.global_time.length / Math.max(1, maxPoints)));
        state.downsample = suggested;
        downsampleInput.value = suggested;
        downsampleValue.textContent = suggested;
      }} else {{
        state.downsample = 1;
        downsampleInput.value = 1;
        downsampleValue.textContent = '1';
      }}

      refreshPlotFields();
    }}

    function refreshCompareSymbolOptions() {{
      compareSymbol.innerHTML = '';
      const symbols = getAvailableSymbolsForSource(state.marketSource);
      if (!symbols.length) {{
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'None';
        compareSymbol.appendChild(opt);
        compareSymbol.disabled = true;
        return;
      }}
      compareSymbol.disabled = false;
      symbols.forEach(sym => {{
        const opt = document.createElement('option');
        opt.value = sym;
        opt.textContent = sym;
        compareSymbol.appendChild(opt);
      }});
      if (state.symbol && symbols.includes(state.symbol)) {{
        compareSymbol.value = state.symbol;
      }} else if (symbols.length) {{
        compareSymbol.value = symbols[0];
      }}
    }}

    function createCheckbox(container, id, label, checked, onChange) {{
      const wrapper = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = checked;
      input.id = id;
      input.addEventListener('change', onChange);
      wrapper.appendChild(input);
      wrapper.appendChild(document.createTextNode(label));
      container.appendChild(wrapper);
    }}

    function initRoundOptions() {{
      const rounds = ROUND_OPTIONS.length ? ROUND_OPTIONS : ['round0'];
      roundSelect.innerHTML = '';
      const allOpt = document.createElement('option');
      allOpt.value = 'all';
      allOpt.textContent = 'All';
      roundSelect.appendChild(allOpt);
      rounds.forEach(round => {{
        const opt = document.createElement('option');
        opt.value = round;
        opt.textContent = round;
        roundSelect.appendChild(opt);
      }});
      if (state.roundFilter !== 'all' && !rounds.includes(state.roundFilter)) {{
        state.roundFilter = rounds[0] || 'all';
      }}
      roundSelect.value = state.roundFilter;
    }}

    function getStrategiesForRound(roundValue) {{
      const strategies = new Set();
      if (roundValue === 'all') {{
        Object.values(STRATEGY_CATALOG).forEach(list => list.forEach(item => strategies.add(item)));
        BACKTEST_INDEX.forEach(entry => {{
          if (entry.strategy) strategies.add(entry.strategy);
        }});
      }} else {{
        (STRATEGY_CATALOG[roundValue] || []).forEach(item => strategies.add(item));
        BACKTEST_INDEX.filter(entry => entry.round === roundValue).forEach(entry => {{
          if (entry.strategy) strategies.add(entry.strategy);
        }});
      }}
      return Array.from(strategies).sort();
    }}

    function initStrategyOptions() {{
      const strategies = getStrategiesForRound(state.roundFilter);
      strategySelect.innerHTML = '';
      const allOpt = document.createElement('option');
      allOpt.value = 'all';
      allOpt.textContent = 'All';
      strategySelect.appendChild(allOpt);
      strategies.forEach(strategy => {{
        const opt = document.createElement('option');
        opt.value = strategy;
        opt.textContent = strategy;
        strategySelect.appendChild(opt);
      }});
      if (!strategies.includes(state.strategyFilter)) {{
        state.strategyFilter = 'all';
      }}
      strategySelect.value = state.strategyFilter;
    }}

    function initRunOptions() {{
      datasetSelect.innerHTML = '';
      const filtered = syncDatasetSelection();
      if (filtered.length === 0) {{
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'None';
        datasetSelect.appendChild(opt);
        datasetSelect.disabled = true;
        state.dataset = '';
      }} else {{
        filtered.forEach(entry => {{
          const opt = document.createElement('option');
          opt.value = entry.id;
          opt.textContent = entry.label || entry.id;
          datasetSelect.appendChild(opt);
        }});
        datasetSelect.disabled = false;
        datasetSelect.value = state.dataset;
      }}
    }}

    function collectBacktestDays(datasetName) {{
      const days = new Set();
      const backtestDataset = DATA.backtest?.[datasetName] || null;
      (backtestDataset?.day || []).forEach(d => {{
        if (d != null) days.add(d);
      }});
      const fillsDataset = DATA.fills?.[datasetName] || {{}};
      Object.values(fillsDataset).forEach(entry => {{
        (entry.day || []).forEach(d => {{
          if (d != null) days.add(d);
        }});
      }});
      const ordersDataset = DATA.orders?.[datasetName] || {{}};
      Object.values(ordersDataset).forEach(entry => {{
        (entry.day || []).forEach(d => {{
          if (d != null) days.add(d);
        }});
      }});
      return Array.from(days).sort((a, b) => a - b);
    }}

    function getPreferredBacktestDay(days) {{
      if (!days || !days.length) return 'all';
      if (state.dayFilter !== 'all') {{
        const target = Number(state.dayFilter);
        if (days.includes(target)) return String(target);
      }}
      return 'all';
    }}

    function initBacktestDayOptions() {{
      backtestDaySelect.innerHTML = '';
      if (!state.dataset || !DATA.backtest?.[state.dataset]) {{
        const opt = document.createElement('option');
        opt.value = 'all';
        opt.textContent = 'All';
        backtestDaySelect.appendChild(opt);
        backtestDaySelect.disabled = true;
        state.backtestDayFilter = 'all';
        state.backtestDayManual = false;
        return;
      }}
      const days = collectBacktestDays(state.dataset);
      const allOpt = document.createElement('option');
      allOpt.value = 'all';
      allOpt.textContent = 'All';
      backtestDaySelect.appendChild(allOpt);
      days.forEach(day => {{
        const opt = document.createElement('option');
        opt.value = String(day);
        opt.textContent = String(day);
        backtestDaySelect.appendChild(opt);
      }});
      const preferredDay = getPreferredBacktestDay(days);
      if (!state.backtestDayManual) {{
        state.backtestDayFilter = preferredDay;
      }} else if (state.backtestDayFilter !== 'all' && !days.includes(Number(state.backtestDayFilter))) {{
        state.backtestDayFilter = preferredDay;
      }}
      backtestDaySelect.value = state.backtestDayFilter;
      backtestDaySelect.disabled = false;
    }}

    function initDayOptions() {{
      daySelect.innerHTML = '';
      const currentMeta = getCurrentMarketMeta();
      const roundSources = getMarketSourcesForRound(state.roundFilter);
      const primarySource = getDefaultMarketSourceForRound(state.roundFilter, currentMeta?.kind === 'csv' ? state.marketSource : null);
      const primaryMeta = MARKET_SOURCE_INDEX[primarySource] || currentMeta;
      const book = getBookForSource(primaryMeta?.id, state.symbol);
      if (!book || !book.day) {{
        const opt = document.createElement('option');
        opt.value = 'all';
        opt.textContent = 'None';
        daySelect.appendChild(opt);
        daySelect.disabled = true;
        state.dayFilter = 'all';
        return;
      }}
      daySelect.disabled = false;
      const days = Array.from(new Set(book.day.filter(v => v != null))).sort((a, b) => a - b);
      const allOpt = document.createElement('option');
      allOpt.value = 'all';
      allOpt.textContent = 'All';
      daySelect.appendChild(allOpt);
      days.forEach(day => {{
        const opt = document.createElement('option');
        opt.value = String(day);
        opt.textContent = String(day);
        daySelect.appendChild(opt);
      }});
      roundSources
        .filter(source => source.id !== primaryMeta?.id)
        .forEach(source => {{
          const opt = document.createElement('option');
          opt.value = `source:${{source.id}}`;
          opt.textContent = source.kind === 'benchmark'
            ? `Benchmark: ${{source.label}}`
            : source.label;
          daySelect.appendChild(opt);
        }});
      const defaultDay = days.length ? String(days[days.length - 1]) : 'all';
      if (state.dayFilter !== 'all' && !days.includes(Number(state.dayFilter))) {{
        state.dayFilter = defaultDay;
      }}
      const dayValue = state.marketSource && state.marketSource !== primaryMeta?.id
        ? `source:${{state.marketSource}}`
        : state.dayFilter;
      daySelect.value = dayValue;
      if (state.dayFilter === 'all') {{
        state.timeAxis = 'global';
      }}
    }}

    function setIndicatorSelection(names) {{
      const wanted = new Set(names || []);
      Object.keys(state.indicators).forEach(name => {{
        state.indicators[name] = wanted.has(name);
        const input = document.getElementById(`ind-${{name}}`);
        if (input) input.checked = state.indicators[name];
      }});
    }}

    function syncPresetControls() {{
      presetSelect.value = state.presetId;
      const preset = PRESET_INDEX[state.presetId] || PRESET_INDEX.manual;
      presetMeta.textContent = (preset && preset.description) ? preset.description : 'Manual controls only.';
    }}

    function markPresetManual() {{
      if (state.presetId !== 'manual') {{
        state.presetId = 'manual';
        syncPresetControls();
      }}
    }}

    function applyPreset(presetId, update = true) {{
      const preset = PRESET_INDEX[presetId] || PRESET_INDEX.manual;
      state.presetId = preset.id || 'manual';

      if (preset.symbol) {{
        const sourceWithSymbol = getMarketSourcesForRound(state.roundFilter).find(source => getAvailableSymbolsForSource(source.id).includes(preset.symbol));
        if (sourceWithSymbol) {{
          state.marketSource = sourceWithSymbol.id;
          state.symbol = preset.symbol;
          syncContextForMarketSource({{ preferredSource: sourceWithSymbol.id, preferredSymbol: preset.symbol }});
        }}
      }}

      if (preset.normalizeBy) {{
        state.normalizeBy = preset.normalizeBy;
      }}
      normalizeSelect.value = state.normalizeBy;
      if (!normalizeSelect.value) {{
        state.normalizeBy = 'none';
        normalizeSelect.value = 'none';
      }}

      if (preset.normalizedBy) {{
        state.normalizedBy = preset.normalizedBy;
      }}
      normalizedSelect.value = state.normalizedBy;

      if (Object.prototype.hasOwnProperty.call(preset, 'extremaQty')) {{
        state.extremaQty = preset.extremaQty;
      }}
      extremaQtyInput.value = state.extremaQty == null ? '' : state.extremaQty;

      if (preset.indicatorNames) {{
        setIndicatorSelection(preset.indicatorNames);
      }} else if (preset.id === 'manual') {{
        setIndicatorSelection([]);
      }}

      if (Object.prototype.hasOwnProperty.call(preset, 'showNormalized')) {{
        state.showNormalized = Boolean(preset.showNormalized);
        showNormalized.checked = state.showNormalized;
        normalizedPanelWrap.style.display = state.showNormalized ? 'block' : 'none';
        normalizedSelect.disabled = !state.showNormalized;
      }}

      state.showExtras = true;
      showExtras.checked = true;
      extras.style.display = 'block';
      syncPresetControls();
      refreshPlotFields();
      if (update) updateAll();
    }}

    function initControls() {{
      initRoundOptions();
      syncMarketSourceForRound(DEFAULTS.marketSource || state.marketSource);
      syncSymbolOptions(DEFAULTS.symbol || state.symbol);
      timeAxisSelect.value = state.timeAxis;

      if (DATA.indicatorOptions && DATA.indicatorOptions.length) {{
        DATA.indicatorOptions.forEach(name => {{
          const opt = document.createElement('option');
          opt.value = `indicator:${{name}}`;
          opt.textContent = name;
          normalizeSelect.appendChild(opt);
          const optNorm = document.createElement('option');
          optNorm.value = `indicator:${{name}}`;
          optNorm.textContent = name;
          normalizedSelect.appendChild(optNorm);
        }});
      }}

      if (state.normalizeBy && !state.normalizeBy.startsWith('indicator:')) {{
        const matches = DATA.indicatorOptions?.find(name => name === state.normalizeBy);
        if (matches) {{
          state.normalizeBy = `indicator:${{matches}}`;
        }}
      }}
      normalizeSelect.value = state.normalizeBy;
      if (!normalizeSelect.value) {{
        state.normalizeBy = 'none';
        normalizeSelect.value = 'none';
      }}

      if (state.normalizedBy && !state.normalizedBy.startsWith('indicator:')) {{
        const matches = DATA.indicatorOptions?.find(name => name === state.normalizedBy);
        if (matches) {{
          state.normalizedBy = `indicator:${{matches}}`;
        }}
      }}
      normalizedSelect.value = state.normalizedBy;
      if (state.minQty !== null) minQtyInput.value = state.minQty;
      if (state.maxQty !== null) maxQtyInput.value = state.maxQty;

      initStrategyOptions();
      initRunOptions();

      presetSelect.innerHTML = '';
      PRESETS.forEach(preset => {{
        const opt = document.createElement('option');
        opt.value = preset.id;
        opt.textContent = preset.label;
        presetSelect.appendChild(opt);
      }});
      if (!PRESET_INDEX[state.presetId]) {{
        state.presetId = 'manual';
      }}
      syncPresetControls();

      if (DATA.backtestDatasets.length === 0) {{
        compareDatasetA.disabled = true;
        compareDatasetB.disabled = true;
        compareMetric.disabled = true;
        compareSymbol.disabled = true;
      }} else {{
        compareDatasetA.innerHTML = '';
        compareDatasetB.innerHTML = '';
        DATA.backtestDatasets.forEach(name => {{
          const optA = document.createElement('option');
          optA.value = name;
          optA.textContent = DATASET_LABELS[name] || name;
          compareDatasetA.appendChild(optA);
          const optB = document.createElement('option');
          optB.value = name;
          optB.textContent = DATASET_LABELS[name] || name;
          compareDatasetB.appendChild(optB);
        }});
        compareDatasetA.value = DATA.backtestDatasets[0];
        compareDatasetB.value = DATA.backtestDatasets[1] || DATA.backtestDatasets[0];

        compareMetric.innerHTML = '';
        ['total_pnl','realized_pnl','unrealized_pnl','position','pnl_symbol'].forEach(metric => {{
          const opt = document.createElement('option');
          opt.value = metric;
          opt.textContent = metric.replace('_', ' ');
          compareMetric.appendChild(opt);
        }});
        compareMetric.value = 'total_pnl';

        refreshCompareSymbolOptions();
      }}

      syncContextForMarketSource({{ preferredSource: state.marketSource, preferredSymbol: state.symbol, preferredDataset: state.dataset }});

      indicatorChecks.innerHTML = '';
      (DATA.indicatorOptions || []).forEach(name => {{
        state.indicators[name] = false;
        createCheckbox(indicatorChecks, `ind-${{name}}`, name, false, () => {{
          state.indicators[name] = document.getElementById(`ind-${{name}}`).checked;
          markPresetManual();
          updateAll();
        }});
      }});

      levelChecks.innerHTML = '';
      (DATA.levels || [1,2,3]).forEach(level => {{
        state.levels[level] = true;
        createCheckbox(levelChecks, `level-${{level}}`, `L${{level}}`, true, () => {{
          state.levels[level] = document.getElementById(`level-${{level}}`).checked;
          updateAll();
        }});
      }});

      groupChecks.innerHTML = '';
      const groupLabels = (DATA.groupOptions && DATA.groupOptions.length)
        ? DATA.groupOptions
        : ['M1','M2','M3','S1','S2','S3','S4','B1','B2','I1','I2','F1'];
      groupLabels.forEach(group => {{
        state.groups[group] = true;
        createCheckbox(groupChecks, `group-${{group}}`, group, true, () => {{
          state.groups[group] = document.getElementById(`group-${{group}}`).checked;
          updateAll();
        }});
      }});
      refreshTraderChecks();

      sideChecks.innerHTML = '';
      ['buy','sell','unknown'].forEach(name => {{
        createCheckbox(sideChecks, `side-${{name}}`, name, true, () => {{
          state.sides[name] = document.getElementById(`side-${{name}}`).checked;
          updateAll();
        }});
      }});

      fillChecks.innerHTML = '';
      createCheckbox(fillChecks, 'show-fills', 'Show fills', true, () => {{
        state.showFills = document.getElementById('show-fills').checked;
        updateAll();
      }});

      showOrdersInput.checked = state.showOrders;
      ordersPassiveOnlyInput.checked = state.ordersPassiveOnly;
      if (!DATA.orders || Object.keys(DATA.orders).length === 0) {{
        showOrdersInput.disabled = true;
        ordersPassiveOnlyInput.disabled = true;
      }}

      showExtras.checked = true;
      state.showExtras = true;
      extras.style.display = 'block';

      showNormalized.checked = state.showNormalized;
      normalizedSelect.value = state.normalizedBy;
      normalizedPanelWrap.style.display = state.showNormalized ? 'block' : 'none';
      normalizedSelect.disabled = !state.showNormalized;
      if (state.extremaQty !== null) extremaQtyInput.value = state.extremaQty;

      initPlotLab();

      symbolSelect.addEventListener('change', (e) => {{
        markPresetManual();
        state.symbol = e.target.value;
        syncContextForMarketSource({{ preferredSource: state.marketSource, preferredSymbol: state.symbol }});
        updateAll();
      }});
      roundSelect.addEventListener('change', () => {{
        markPresetManual();
        state.roundFilter = roundSelect.value;
        initStrategyOptions();
        initRunOptions();
        state.backtestDayManual = false;
        syncContextForMarketSource({{ preferredSource: getDefaultMarketSourceForRound(state.roundFilter) }});
        updateAll();
      }});
      strategySelect.addEventListener('change', () => {{
        markPresetManual();
        state.strategyFilter = strategySelect.value;
        initRunOptions();
        state.backtestDayManual = false;
        syncContextForMarketSource({{ preferredSource: state.marketSource, preferredDataset: state.dataset, resetCursor: false }});
        updateAll();
      }});
      daySelect.addEventListener('change', () => {{
        markPresetManual();
        const selected = daySelect.value;
        if (selected.startsWith('source:')) {{
          state.marketSource = selected.replace('source:', '');
          state.dayFilter = 'all';
          state.timeAxis = 'timestamp';
          timeAxisSelect.value = 'timestamp';
          syncContextForMarketSource({{ preferredSource: state.marketSource }});
          updateAll();
          return;
        }}
        state.dayFilter = selected;
        if (state.dayFilter === 'all') {{
          state.timeAxis = 'global';
          timeAxisSelect.value = 'global';
        }} else {{
          state.timeAxis = 'timestamp';
          timeAxisSelect.value = 'timestamp';
        }}
        refreshTraderChecks();
        const book = getCurrentBook();
        if (book && book.timestamp && book.timestamp.length) {{
          const idx = findFirstIndexForDay(book.day, state.dayFilter);
          if (idx !== null) {{
            setCursorIndex(idx);
          }}
        }}
        refreshPlotFields();
        if (!state.backtestDayManual) {{
          initBacktestDayOptions();
        }}
        updateAll();
      }});
      timeAxisSelect.addEventListener('change', () => {{
        markPresetManual();
        state.timeAxis = timeAxisSelect.value;
        updateAll();
      }});
      datasetSelect.addEventListener('change', (e) => {{
        markPresetManual();
        state.dataset = e.target.value;
        state.backtestDayManual = false;
        const datasetMeta = BACKTEST_INDEX.find(entry => entry.id === state.dataset) || null;
        if (datasetMeta) {{
          state.roundFilter = datasetMeta.round || state.roundFilter;
          roundSelect.value = state.roundFilter;
          initStrategyOptions();
          if (datasetMeta.strategy && strategySelect.querySelector(`option[value="${{datasetMeta.strategy}}"]`)) {{
            state.strategyFilter = datasetMeta.strategy;
            strategySelect.value = state.strategyFilter;
          }}
          syncContextForMarketSource({{
            preferredSource: datasetMeta.marketSource || state.marketSource,
            preferredDataset: datasetMeta.id,
            resetCursor: false,
          }});
        }} else {{
          syncContextForMarketSource({{ preferredDataset: state.dataset, resetCursor: false }});
        }}
        updateAll();
      }});
      presetSelect.addEventListener('change', () => {{
        applyPreset(presetSelect.value);
      }});
      backtestDaySelect.addEventListener('change', () => {{
        markPresetManual();
        state.backtestDayFilter = backtestDaySelect.value;
        state.backtestDayManual = true;
        updateAll();
      }});
      normalizeSelect.addEventListener('change', (e) => {{
        markPresetManual();
        state.normalizeBy = e.target.value;
        updateAll();
      }});
      minQtyInput.addEventListener('input', () => {{
        markPresetManual();
        state.minQty = minQtyInput.value === '' ? null : parseFloat(minQtyInput.value);
        updateAll();
      }});
      maxQtyInput.addEventListener('input', () => {{
        markPresetManual();
        state.maxQty = maxQtyInput.value === '' ? null : parseFloat(maxQtyInput.value);
        updateAll();
      }});
      extremaQtyInput.addEventListener('input', () => {{
        state.extremaQty = extremaQtyInput.value === '' ? null : parseFloat(extremaQtyInput.value);
        if (state.presetId !== 'manual') {{
          state.presetId = 'manual';
          syncPresetControls();
        }}
        updateAll();
      }});
      downsampleInput.addEventListener('input', () => {{
        markPresetManual();
        state.downsample = parseInt(downsampleInput.value, 10);
        downsampleValue.textContent = state.downsample;
        updateAll();
      }});
      showOrdersInput.addEventListener('change', () => {{
        markPresetManual();
        state.showOrders = showOrdersInput.checked;
        updateAll();
      }});
      ordersPassiveOnlyInput.addEventListener('change', () => {{
        markPresetManual();
        state.ordersPassiveOnly = ordersPassiveOnlyInput.checked;
        updateAll();
      }});
      logSearch.addEventListener('input', updateLogs);
      showExtras.addEventListener('change', () => {{
        extras.style.display = showExtras.checked ? 'block' : 'none';
        updateAll();
      }});
      showNormalized.addEventListener('change', () => {{
        markPresetManual();
        state.showNormalized = showNormalized.checked;
        normalizedPanelWrap.style.display = state.showNormalized ? 'block' : 'none';
        normalizedSelect.disabled = !state.showNormalized;
        updateAll();
      }});
      normalizedSelect.addEventListener('change', () => {{
        markPresetManual();
        state.normalizedBy = normalizedSelect.value;
        updateAll();
      }});

      plotSource.addEventListener('change', () => {{
        state.plotSource = plotSource.value;
        refreshPlotFields();
        updatePlotLab();
      }});
      plotX.addEventListener('change', () => {{
        state.plotX = plotX.value;
        updatePlotLab();
      }});
      plotY.addEventListener('change', () => {{
        state.plotY = plotY.value;
        updatePlotLab();
      }});
      plotType.addEventListener('change', () => {{
        state.plotType = plotType.value;
        updatePlotLab();
      }});
      plotFit.addEventListener('change', () => {{
        state.plotFit = plotFit.value;
        updatePlotLab();
      }});

      timestampInput.addEventListener('change', () => {{
        const book = getCurrentBook();
        if (!book || !book.timestamp) return;
        const target = parseFloat(timestampInput.value);
        if (Number.isNaN(target)) return;
        const idx = findClosestIndexByTimestamp(book.timestamp, target);
        setCursorIndex(idx);
      }});
      btnLeft.addEventListener('click', () => {{
        const step = parseInt(stepSizeInput.value || '1', 10);
        setCursorIndex(state.cursorIndex - step);
      }});
      btnRight.addEventListener('click', () => {{
        const step = parseInt(stepSizeInput.value || '1', 10);
        setCursorIndex(state.cursorIndex + step);
      }});

      compareDatasetA.addEventListener('change', updateCompare);
      compareDatasetB.addEventListener('change', updateCompare);
      compareMetric.addEventListener('change', updateCompare);
      compareSymbol.addEventListener('change', updateCompare);
      applyPreset(state.presetId, false);
    }}

    function downsampleIndices(length, step) {{
      const indices = [];
      for (let i = 0; i < length; i += step) {{
        indices.push(i);
      }}
      return indices;
    }}

    function sliceByIndex(arr, indices) {{
      return indices.map(i => arr[i]);
    }}

    function findClosestIndexByTimestamp(timestamps, target) {{
      if (!timestamps || timestamps.length === 0) return 0;
      let lo = 0;
      let hi = timestamps.length - 1;
      while (lo < hi) {{
        const mid = Math.floor((lo + hi) / 2);
        if (timestamps[mid] < target) {{
          lo = mid + 1;
        }} else {{
          hi = mid;
        }}
      }}
      if (lo === 0) return 0;
      const prev = lo - 1;
      return Math.abs(timestamps[lo] - target) < Math.abs(timestamps[prev] - target) ? lo : prev;
    }}

    function findFirstIndexForDay(days, dayFilter) {{
      if (!days || days.length === 0) return null;
      if (dayFilter === 'all') return Math.floor(days.length / 2);
      const target = Number(dayFilter);
      for (let i = 0; i < days.length; i++) {{
        if (days[i] === target) return i;
      }}
      return null;
    }}

    function isBacktestDayAllowed(dayValue) {{
      if (state.backtestDayFilter === 'all') return true;
      return Number(state.backtestDayFilter) === dayValue;
    }}

    function getFilteredIndices(book) {{
      const step = Math.max(1, state.downsample);
      const indices = downsampleIndices(book.global_time.length, step);
      if (state.dayFilter === 'all') return indices;
      const target = Number(state.dayFilter);
      return indices.filter(i => book.day[i] === target);
    }}

    function getTimeArray(book, indices) {{
      if (state.timeAxis === 'global') {{
        return sliceByIndex(book.global_time, indices);
      }}
      return sliceByIndex(book.timestamp, indices);
    }}

    function setCursorIndex(idx) {{
      const book = getCurrentBook();
      if (!book || !book.timestamp) return;
      const maxIdx = book.timestamp.length - 1;
      const clamped = Math.max(0, Math.min(maxIdx, idx));
      state.cursorIndex = clamped;
      timestampInput.value = book.timestamp[clamped];
      cursorMeta.textContent = `Day ${{book.day[clamped]}} @ ${{book.timestamp[clamped]}}`;
      updateAll();
    }}

    function getCursorStep() {{
      if (!state.dataset || !DATA.backtest[state.dataset]) return null;
      const data = DATA.backtest[state.dataset];
      if (!data.step || data.step.length === 0) return null;
      const book = getCurrentBook();
      if (
        book && book.day && book.timestamp
        && data.day && data.timestamp
        && state.cursorIndex < book.day.length
        && state.cursorIndex < book.timestamp.length
      ) {{
        const cursorDay = book.day[state.cursorIndex];
        const cursorTs = book.timestamp[state.cursorIndex];
        if (cursorDay != null && cursorTs != null) {{
          if (!isBacktestDayAllowed(cursorDay)) return null;
          const len = Math.min(data.step.length, data.day.length, data.timestamp.length);
          for (let i = 0; i < len; i++) {{
            if (data.day[i] === cursorDay && data.timestamp[i] === cursorTs) {{
              return data.step[i];
            }}
          }}
        }}
      }}
      const idx = Math.min(state.cursorIndex, data.step.length - 1);
      if (data.day && data.day[idx] != null && !isBacktestDayAllowed(data.day[idx])) return null;
      return data.step[idx];
    }}

    function getFilteredBacktestIndices(data) {{
      if (!data || !data.step || data.step.length === 0) return [];
      return data.step.map((_, idx) => idx).filter(idx => {{
        if (!data.day || data.day[idx] == null) return true;
        return isBacktestDayAllowed(data.day[idx]);
      }});
    }}

    function alignBaseline(times, baseSeries, baseTimes) {{
      if (!baseSeries || !baseTimes || baseSeries.length === 0) return times.map(() => null);
      const aligned = [];
      let j = 0;
      for (let i = 0; i < times.length; i++) {{
        const t = times[i];
        while (j < baseTimes.length - 1 && baseTimes[j + 1] <= t) {{
          j++;
        }}
        aligned.push(baseSeries[j]);
      }}
      return aligned;
    }}

    function normalizeSeries(values, base) {{
      if (!base) return values;
      return values.map((v, i) => {{
        const b = base[i];
        if (v == null || b == null) return null;
        return v - b;
      }});
    }}

    function mean(values) {{
      const filtered = values.filter(v => v != null && !Number.isNaN(v));
      if (!filtered.length) return null;
      return filtered.reduce((a, b) => a + b, 0) / filtered.length;
    }}

    function quantile(values, q) {{
      const filtered = values.filter(v => v != null && !Number.isNaN(v)).sort((a, b) => a - b);
      if (!filtered.length) return null;
      if (filtered.length === 1) return filtered[0];
      const pos = (filtered.length - 1) * q;
      const base = Math.floor(pos);
      const rest = pos - base;
      const next = filtered[Math.min(base + 1, filtered.length - 1)];
      return filtered[base] + rest * (next - filtered[base]);
    }}

    function median(values) {{
      return quantile(values, 0.5);
    }}

    function std(values) {{
      const filtered = values.filter(v => v != null && !Number.isNaN(v));
      if (filtered.length < 2) return null;
      const avg = mean(filtered);
      const variance = filtered.reduce((acc, v) => acc + Math.pow(v - avg, 2), 0) / (filtered.length - 1);
      return Math.sqrt(variance);
    }}

    function correlation(x, y) {{
      const len = Math.min(x.length, y.length);
      const xs = [];
      const ys = [];
      for (let i = 0; i < len; i++) {{
        const xi = x[i];
        const yi = y[i];
        if (xi == null || yi == null || Number.isNaN(xi) || Number.isNaN(yi)) continue;
        xs.push(xi);
        ys.push(yi);
      }}
      if (xs.length < 2) return null;
      const meanX = mean(xs);
      const meanY = mean(ys);
      let cov = 0;
      let varX = 0;
      let varY = 0;
      for (let i = 0; i < xs.length; i++) {{
        const dx = xs[i] - meanX;
        const dy = ys[i] - meanY;
        cov += dx * dy;
        varX += dx * dx;
        varY += dy * dy;
      }}
      if (varX <= 0 || varY <= 0) return null;
      return cov / Math.sqrt(varX * varY);
    }}

    function normalizeTraderLabel(value) {{
      const text = value == null ? '' : String(value).trim();
      return text ? text : 'ANONYMOUS';
    }}

    function safeSlug(value) {{
      const text = String(value ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      return text || 'value';
    }}

    function labelForNormalizeChoice(choice) {{
      if (!choice || choice === 'none') return 'raw';
      if (choice.startsWith('indicator:')) return choice.replace('indicator:', '');
      return choice;
    }}

    function resolveBookBaseSeries(book, indicatorData, normalizeBy, indices = null) {{
      if (!normalizeBy || normalizeBy === 'none') return null;
      let series = null;
      if (normalizeBy.startsWith('indicator:')) {{
        const key = normalizeBy.replace('indicator:', '');
        series = indicatorData[key] || null;
      }} else {{
        series = book[normalizeBy] || null;
      }}
      if (!series) return null;
      return indices ? sliceByIndex(series, indices) : series;
    }}

    function getResearchNormalizeChoice(book) {{
      if (state.normalizeBy && state.normalizeBy !== 'none') return state.normalizeBy;
      const indicatorData = getCurrentIndicatorData();
      if (indicatorData.fair_value) return 'indicator:fair_value';
      if (book.wall_mid && book.wall_mid.some(v => v != null && !Number.isNaN(v))) return 'wall_mid';
      return 'none';
    }}

    function getAvailableTraders() {{
      const trades = getCurrentTrades();
      const buyer = trades.buyer || [];
      const seller = trades.seller || [];
      const day = trades.day || [];
      const available = new Set();
      const len = Math.max(buyer.length, seller.length);
      for (let i = 0; i < len; i++) {{
        if (state.dayFilter !== 'all' && Number(state.dayFilter) !== day[i]) continue;
        available.add(normalizeTraderLabel(buyer[i]));
        available.add(normalizeTraderLabel(seller[i]));
      }}
      return Array.from(available).sort();
    }}

    function getTraderSelectionState() {{
      const available = getAvailableTraders();
      const selected = new Set(available.filter(name => state.traders[name] !== false));
      return {{
        available,
        selected,
        allSelected: available.length === 0 || selected.size === available.length,
      }};
    }}

    function refreshTraderChecks() {{
      traderChecks.innerHTML = '';
      const traders = getAvailableTraders();
      if (!traders.length) {{
        traderChecks.innerHTML = '<div class="hover-meta">No trader IDs in current slice.</div>';
        return;
      }}

      const ids = [];
      const syncMaster = () => {{
        const master = document.getElementById('trader-all');
        if (!master) return;
        master.checked = traders.every(name => state.traders[name] !== false);
      }};

      createCheckbox(traderChecks, 'trader-all', 'All', true, () => {{
        const checked = document.getElementById('trader-all').checked;
        traders.forEach((name, idx) => {{
          state.traders[name] = checked;
          const input = document.getElementById(ids[idx]);
          if (input) input.checked = checked;
        }});
        updateAll();
      }});

      traders.forEach((name, idx) => {{
        if (!(name in state.traders)) {{
          state.traders[name] = true;
        }}
        const id = `trader-${{safeSlug(name)}}-${{idx}}`;
        ids.push(id);
        createCheckbox(traderChecks, id, name, state.traders[name] !== false, () => {{
          state.traders[name] = document.getElementById(id).checked;
          syncMaster();
          updateAll();
        }});
      }});

      syncMaster();
    }}

    function getFilteredTradeIndices(trades) {{
      if (!trades || !trades.global_time || trades.global_time.length === 0) return [];
      const tradeQty = trades.abs_qty || trades.quantity || [];
      const tradeAgg = trades.aggressor || [];
      const tradeGroup = trades.group_tier || trades.group || [];
      const tradeBuyer = trades.buyer || [];
      const tradeSeller = trades.seller || [];
      const tradeDay = trades.day || [];
      const traderState = getTraderSelectionState();

      return trades.global_time.map((_, idx) => idx).filter(idx => {{
        const qty = tradeQty[idx] || 0;
        const absQty = Math.abs(qty);
        if (state.minQty !== null && absQty < state.minQty) return false;
        if (state.maxQty !== null && absQty > state.maxQty) return false;
        const agg = (tradeAgg[idx] || 'unknown').toLowerCase();
        const group = tradeGroup[idx] || 'M1';
        if (state.dayFilter !== 'all' && Number(state.dayFilter) !== tradeDay[idx]) return false;
        if (state.sides[agg] === false) return false;
        if (state.groups[group] === false) return false;
        if (!traderState.allSelected) {{
          const buyer = normalizeTraderLabel(tradeBuyer[idx]);
          const seller = normalizeTraderLabel(tradeSeller[idx]);
          if (!traderState.selected.has(buyer) && !traderState.selected.has(seller)) return false;
        }}
        return true;
      }});
    }}

    function updateStats() {{
      const book = getCurrentBook();
      const trades = getCurrentTrades();
      if (!book || !book.mid_price) {{
        statsTable.innerHTML = '<div class=\"hover-meta\">No stats available.</div>';
        return;
      }}
      const spread = (book.spread || []).filter((_, idx) => {{
        if (state.dayFilter !== 'all' && Number(state.dayFilter) !== book.day[idx]) return false;
        return true;
      }});
      const mid = (book.mid_price || []).filter((_, idx) => {{
        if (state.dayFilter !== 'all' && Number(state.dayFilter) !== book.day[idx]) return false;
        return true;
      }});
      const midDiff = [];
      for (let i = 1; i < mid.length; i++) {{
        if (mid[i] != null && mid[i - 1] != null) {{
          midDiff.push(mid[i] - mid[i - 1]);
        }}
      }}
      const tradeQty = trades.abs_qty || trades.quantity || [];
      const tradeAgg = trades.aggressor || [];
      let buyVol = 0;
      let sellVol = 0;
      const filteredTradeIdx = getFilteredTradeIndices(trades);
      filteredTradeIdx.forEach(i => {{
        const qty = Math.abs(tradeQty[i] || 0);
        const side = (tradeAgg[i] || '').toLowerCase();
        if (side === 'buy') buyVol += qty;
        if (side === 'sell') sellVol += qty;
      }});
      const avgTradeSize = filteredTradeIdx.length
        ? mean(filteredTradeIdx.map(i => Math.abs(tradeQty[i] || 0)))
        : null;
      const statsRows = [
        ['Avg spread', mean(spread)],
        ['Median spread', median(spread)],
        ['Mid vol (stdev)', std(midDiff)],
        ['Trades', filteredTradeIdx.length || 0],
        ['Avg trade size', avgTradeSize],
        ['Buy volume', buyVol],
        ['Sell volume', sellVol],
        ['Net volume', buyVol - sellVol],
      ];
      let html = '<table class=\"stats-table\"><tbody>';
      statsRows.forEach(([label, value]) => {{
        const formatted = value == null ? '—' : (Math.abs(value) >= 1000 ? value.toFixed(0) : value.toFixed(3));
        html += `<tr><td>${{label}}</td><td>${{formatted}}</td></tr>`;
      }});
      html += '</tbody></table>';
      statsTable.innerHTML = html;
    }}

    function listNumericFields(data) {{
      if (!data) return [];
      return Object.keys(data).filter(key => {{
        const arr = data[key];
        if (!Array.isArray(arr)) return false;
        return arr.some(v => typeof v === 'number' && !Number.isNaN(v));
      }});
    }}

    function getPlotSourceOptions() {{
      const options = [{{ value: 'book', label: 'Book' }}];
      const trades = getCurrentTrades();
      const indicators = getCurrentIndicatorData();
      if (trades.global_time?.length) {{
        options.push({{ value: 'trades', label: 'Trades' }});
      }}
      if (Object.keys(indicators).length) {{
        options.push({{ value: 'indicators', label: 'Indicators' }});
      }}
      if (DATA.fills && Object.keys(DATA.fills).length) {{
        options.push({{ value: 'fills', label: 'Fills' }});
      }}
      if (DATA.orders && Object.keys(DATA.orders).length) {{
        options.push({{ value: 'orders', label: 'Orders' }});
      }}
      if (DATA.backtestDatasets && DATA.backtestDatasets.length) {{
        options.push({{ value: 'backtest', label: 'Backtest' }});
      }}
      return options;
    }}

    function getSourceData(source) {{
      if (source === 'book') return getCurrentBook();
      if (source === 'trades') return getCurrentTrades();
      if (source === 'indicators') {{
        const indicator = getCurrentIndicatorData();
        const book = getCurrentBook() || {{}};
        return {{
          ...indicator,
          global_time: book.global_time || [],
          timestamp: book.timestamp || [],
          day: book.day || [],
        }};
      }}
      if (source === 'fills') {{
        const dataset = state.dataset || DATA.backtestDatasets[0];
        return DATA.fills?.[dataset]?.[state.symbol];
      }}
      if (source === 'orders') {{
        const dataset = state.dataset || DATA.backtestDatasets[0];
        return DATA.orders?.[dataset]?.[state.symbol];
      }}
      if (source === 'backtest') {{
        const dataset = state.dataset || DATA.backtestDatasets[0];
        return DATA.backtest?.[dataset];
      }}
      return null;
    }}

    function populateSelect(select, options, selected) {{
      select.innerHTML = '';
      options.forEach(opt => {{
        const option = document.createElement('option');
        option.value = opt;
        option.textContent = opt;
        select.appendChild(option);
      }});
      if (options.includes(selected)) {{
        select.value = selected;
      }} else if (options.length) {{
        select.value = options[0];
      }}
    }}

    function initPlotLab() {{
      const sources = getPlotSourceOptions();
      plotSource.innerHTML = '';
      sources.forEach(opt => {{
        const option = document.createElement('option');
        option.value = opt.value;
        option.textContent = opt.label;
        plotSource.appendChild(option);
      }});
      if (!sources.find(opt => opt.value === state.plotSource)) {{
        state.plotSource = sources[0]?.value || 'book';
      }}
      plotSource.value = state.plotSource;
      plotType.value = state.plotType;
      plotFit.value = state.plotFit;
      refreshPlotFields();
    }}

    function refreshPlotFields() {{
      let data = getSourceData(state.plotSource);
      if (!data) {{
        state.plotSource = 'book';
        plotSource.value = 'book';
        data = getSourceData('book');
      }}
      const fields = listNumericFields(data);
      if (!fields.length) {{
        plotX.innerHTML = '';
        plotY.innerHTML = '';
        state.plotX = null;
        state.plotY = null;
        return;
      }}
      const preferredX = fields.includes('global_time')
        ? 'global_time'
        : fields.includes('timestamp')
          ? 'timestamp'
          : fields.includes('step')
            ? 'step'
            : fields[0];
      if (!fields.includes(state.plotX)) {{
        state.plotX = preferredX;
      }}
      if (!fields.includes(state.plotY) || state.plotY === state.plotX) {{
        state.plotY = fields.find(f => f !== state.plotX) || fields[0];
      }}
      populateSelect(plotX, fields, state.plotX);
      populateSelect(plotY, fields, state.plotY);
    }}

    function solveLinearSystem(matrix, vector) {{
      const n = vector.length;
      const a = matrix.map((row, i) => row.map(v => v));
      const b = vector.map(v => v);
      for (let i = 0; i < n; i++) {{
        let maxRow = i;
        for (let k = i + 1; k < n; k++) {{
          if (Math.abs(a[k][i]) > Math.abs(a[maxRow][i])) maxRow = k;
        }}
        [a[i], a[maxRow]] = [a[maxRow], a[i]];
        [b[i], b[maxRow]] = [b[maxRow], b[i]];
        const pivot = a[i][i];
        if (Math.abs(pivot) < 1e-12) return null;
        for (let j = i; j < n; j++) a[i][j] /= pivot;
        b[i] /= pivot;
        for (let k = 0; k < n; k++) {{
          if (k === i) continue;
          const factor = a[k][i];
          for (let j = i; j < n; j++) a[k][j] -= factor * a[i][j];
          b[k] -= factor * b[i];
        }}
      }}
      return b;
    }}

    function polyfit(x, y, degree) {{
      const n = degree + 1;
      const matrix = Array.from({{ length: n }}, () => Array(n).fill(0));
      const vector = Array(n).fill(0);
      for (let idx = 0; idx < x.length; idx++) {{
        const xi = x[idx];
        const yi = y[idx];
        if (xi == null || yi == null) continue;
        let pow = 1;
        const powers = Array(2 * degree + 1).fill(0);
        for (let p = 0; p < powers.length; p++) {{
          powers[p] = pow;
          pow *= xi;
        }}
        for (let i = 0; i < n; i++) {{
          for (let j = 0; j < n; j++) {{
            matrix[i][j] += powers[i + j];
          }}
          vector[i] += yi * powers[i];
        }}
      }}
      return solveLinearSystem(matrix, vector);
    }}

    function buildPlotLabTraces() {{
      if (!hasCurrentMarketData()) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No market data for the selected round.'),
        }};
      }}
      const data = getSourceData(state.plotSource);
      if (!data || !state.plotX || !state.plotY) {{
        return {{ traces: [], layout: {{}} }};
      }}
      const rawX = data[state.plotX] || [];
      const rawY = data[state.plotY] || [];
      const rawDay = data.day || null;
      const pairs = [];
      const len = Math.min(rawX.length, rawY.length);
      for (let i = 0; i < len; i++) {{
        if (rawDay) {{
          const allow = (state.plotSource === 'backtest' || state.plotSource === 'fills' || state.plotSource === 'orders')
            ? isBacktestDayAllowed(rawDay[i])
            : (state.dayFilter === 'all' || Number(state.dayFilter) === rawDay[i]);
          if (!allow) continue;
        }}
        const xi = rawX[i];
        const yi = rawY[i];
        if (xi == null || yi == null || Number.isNaN(xi) || Number.isNaN(yi)) continue;
        pairs.push([xi, yi]);
      }}

      const traces = [];
      if (state.plotType === 'hist') {{
        const values = pairs.map(p => p[1]);
        traces.push({{
          x: values,
          type: 'histogram',
          marker: {{ color: '#111111' }},
        }});
      }} else {{
        const x = pairs.map(p => p[0]);
        const y = pairs.map(p => p[1]);
        traces.push({{
          x,
          y,
          mode: state.plotType === 'line' ? 'lines' : 'markers',
          type: 'scattergl',
          marker: {{ color: '#111111', size: 5 }},
          line: {{ color: '#111111', width: 1 }},
          name: `${{state.plotY}} vs ${{state.plotX}}`,
        }});

        if (state.plotFit !== 'none' && pairs.length >= 5) {{
          const degree = state.plotFit === 'linear' ? 1 : 2;
          const coeff = polyfit(x, y, degree);
          if (coeff) {{
            const sortedX = [...x].sort((a, b) => a - b);
            const step = Math.max(1, Math.floor(sortedX.length / 200));
            const xFit = sortedX.filter((_, idx) => idx % step === 0);
            const yFit = xFit.map(val => {{
              return coeff.reduce((acc, c, idx) => acc + c * Math.pow(val, idx), 0);
            }});
            traces.push({{
              x: xFit,
              y: yFit,
              mode: 'lines',
              type: 'scatter',
              line: {{ color: '#ef4444', width: 2 }},
              name: `fit-${{state.plotFit}}`,
            }});
          }}
        }}
      }}

      const layout = {{
        margin: {{ l: 50, r: 20, t: 20, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: state.plotType === 'hist' ? state.plotY : state.plotX,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: state.plotType === 'hist' ? 'Count' : state.plotY,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildOrderbookTraces(normalizeOverride) {{
      const book = getCurrentBook();
      if (!book) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No market data for the selected round.', state.timeAxis === 'global' ? 'Global time' : 'Timestamp', 'Price'),
        }};
      }}

      const normalizeBy = normalizeOverride ?? state.normalizeBy;
      const indices = getFilteredIndices(book);
      state.currentIndices = indices;

      const time = getTimeArray(book, indices);
      const indicatorData = getCurrentIndicatorData();

      const base = resolveBookBaseSeries(book, indicatorData, normalizeBy, indices);

      const traces = [];

      const mid = normalizeSeries(sliceByIndex(book.mid_price, indices), base);
      traces.push({{
        x: time,
        y: mid,
        mode: 'lines',
        name: 'Mid',
        line: {{ color: '#222222', width: 1, shape: 'hv' }},
      }});

      (DATA.levels || [1,2,3]).forEach(level => {{
        if (!state.levels[level]) return;
        const bid = normalizeSeries(sliceByIndex(book[`bid_price_${{level}}`], indices), base);
        const ask = normalizeSeries(sliceByIndex(book[`ask_price_${{level}}`], indices), base);
        traces.push({{
          x: time,
          y: bid,
          mode: 'lines',
          name: `Bid L${{level}}`,
          line: {{ color: '#0b51ff', width: level === 1 ? 2 : 1, shape: 'hv' }},
          type: 'scattergl',
        }});
        traces.push({{
          x: time,
          y: ask,
          mode: 'lines',
          name: `Ask L${{level}}`,
          line: {{ color: '#ff1e1e', width: level === 1 ? 2 : 1, shape: 'hv' }},
          type: 'scattergl',
        }});
      }});

      Object.keys(state.indicators).forEach(name => {{
        if (!state.indicators[name]) return;
        if (!indicatorData[name]) return;
        const series = normalizeSeries(sliceByIndex(indicatorData[name], indices), base);
        traces.push({{
          x: time,
          y: series,
          mode: 'lines',
          name: name,
          line: {{ dash: 'dot', width: 1.5, color: '#0f766e' }},
        }});
      }});

      const trades = getCurrentTrades();
      if (trades.global_time && trades.global_time.length) {{
        const tradeIndicatorData = getCurrentTradeIndicatorData();
        const tradeBase = (() => {{
          if (normalizeBy === 'none') return null;
          if (normalizeBy.startsWith('indicator:')) {{
            const key = normalizeBy.replace('indicator:', '');
            return tradeIndicatorData[key] || null;
          }}
          if (normalizeBy === 'bid_price_1') return trades.bid_at_trade;
          if (normalizeBy === 'ask_price_1') return trades.ask_at_trade;
          return trades[normalizeBy];
        }})();
        const tradeTime = trades.global_time;
        const tradeTimeDisplay = state.timeAxis === 'global' ? tradeTime : trades.timestamp || tradeTime;
        const tradePrice = normalizeSeries(trades.price, tradeBase);
        const tradeQty = trades.abs_qty || trades.quantity || [];
        const tradeAgg = trades.aggressor || [];
        const tradeGroup = trades.group_tier || trades.group || [];
        const tradeBuyer = trades.buyer || [];
        const tradeSeller = trades.seller || [];
        const tradeDay = trades.day || [];
        const tradeTs = trades.timestamp || [];

        const filtered = getFilteredTradeIndices(trades);

        const groupPalette = {{
          M: ['#f59e0b', '#f97316', '#ea580c'],
          S: ['#22c55e', '#16a34a', '#15803d', '#166534'],
          B: ['#ef4444', '#b91c1c'],
          I: ['#8b5cf6', '#6d28d9'],
          F: ['#111111'],
        }};
        const groupSymbols = {{
          M: 'square',
          S: 'triangle-up',
          B: 'triangle-up',
          I: 'cross',
          F: 'star',
        }};
        const groupBoost = {{ M: 0.9, S: 1.0, B: 1.6, I: 1.2, F: 1.4 }};

        const parseGroup = (label) => {{
          if (!label) return {{ base: 'M', tier: 1 }};
          const match = String(label).match(/^([A-Z])(?:([0-9]+))?/);
          if (!match) return {{ base: 'M', tier: 1 }};
          return {{
            base: match[1],
            tier: match[2] ? parseInt(match[2], 10) : 1,
          }};
        }};

        const grouped = {{}};
        filtered.forEach(idx => {{
          const group = tradeGroup[idx] || 'M1';
          const agg = tradeAgg[idx] || 'unknown';
          const key = `${{group}}_${{agg}}`;
          if (!grouped[key]) grouped[key] = [];
          grouped[key].push(idx);
        }});

        Object.entries(grouped).forEach(([key, indices]) => {{
          if (indices.length === 0) return;
          const [group, agg] = key.split('_');
          const parsed = parseGroup(group);
          const symbol = groupSymbols[parsed.base] || (agg === 'sell' ? 'triangle-down' : 'triangle-up');
          const palette = groupPalette[parsed.base] || ['#7f7f7f'];
          const color = palette[Math.min(parsed.tier - 1, palette.length - 1)] || '#7f7f7f';
          traces.push({{
            x: indices.map(i => tradeTimeDisplay[i]),
            y: indices.map(i => tradePrice[i]),
            mode: 'markers',
            name: group,
            marker: {{
              size: indices.map(i => Math.min(60, Math.max(7, Math.abs(tradeQty[i]) * 2.6 * (groupBoost[parsed.base] || 1)))),
              symbol: symbol === 'triangle-up' && agg === 'sell' ? 'triangle-down' : symbol,
              color: color,
              line: {{ color: '#111', width: 0.6 }},
              opacity: 0.9,
            }},
            customdata: indices.map(i => [tradeDay[i], tradeTs[i], tradePrice[i], tradeQty[i], tradeBuyer[i], tradeSeller[i], tradeGroup[i]]),
            hovertemplate: 'day=%{{customdata[0]}}<br>ts=%{{customdata[1]}}<br>price=%{{customdata[2]}}<br>qty=%{{customdata[3]}}<br>buyer=%{{customdata[4]}}<br>seller=%{{customdata[5]}}<br>group=%{{customdata[6]}}<extra></extra>',
            type: 'scattergl',
          }});
        }});
      }}

      if (state.showOrders && DATA.orders && state.dataset !== '__benchmark__') {{
        const datasetName = state.dataset || DATA.backtestDatasets[0];
        const datasetOrders = DATA.orders[datasetName];
        if (datasetOrders && datasetOrders[state.symbol]) {{
          const orders = datasetOrders[state.symbol];
          const orderTime = orders.global_time || [];
          const orderTimeDisplay = state.timeAxis === 'global' ? orderTime : orders.timestamp || orderTime;
          const orderPrice = orders.price || [];
          const orderPassive = orders.passive_qty || [];
          const orderQty = orderPassive.length ? orderPassive : (orders.requested_qty || []);
          const orderSide = orders.side || [];
          const orderDay = orders.day || [];
          const orderTs = orders.timestamp || [];

          let orderBase = null;
          if (normalizeBy !== 'none') {{
            const baseSeries = normalizeBy.startsWith('indicator:')
              ? (indicatorData[normalizeBy.replace('indicator:', '')] || null)
              : book[normalizeBy];
            orderBase = alignBaseline(orderTime, baseSeries, book.global_time);
          }}
          const orderPriceNorm = normalizeSeries(orderPrice, orderBase);

          const indices = orderTime.map((_, idx) => idx).filter(idx => {{
            const qty = orderQty[idx] ?? 0;
            const passive = orderPassive[idx] ?? qty;
            if (state.ordersPassiveOnly && passive <= 0) return false;
            const absQty = Math.abs(qty);
            if (state.minQty !== null && absQty < state.minQty) return false;
            if (state.maxQty !== null && absQty > state.maxQty) return false;
            if (!isBacktestDayAllowed(orderDay[idx])) return false;
            return true;
          }});

          if (indices.length) {{
            traces.push({{
              x: indices.map(i => orderTimeDisplay[i]),
              y: indices.map(i => orderPriceNorm[i]),
              mode: 'markers',
              name: 'Our quotes',
              marker: {{
                size: indices.map(i => Math.min(28, Math.max(6, Math.abs(orderQty[i] || 1) * 1.8))),
                symbol: 'star',
                color: '#111111',
                line: {{ color: '#111111', width: 0.6 }},
                opacity: 0.95,
              }},
              customdata: indices.map(i => [orderDay[i], orderTs[i], orderPrice[i], orderQty[i], orderSide[i]]),
              hovertemplate: 'day=%{{customdata[0]}}<br>ts=%{{customdata[1]}}<br>price=%{{customdata[2]}}<br>qty=%{{customdata[3]}}<br>side=%{{customdata[4]}}<extra></extra>',
              type: 'scattergl',
            }});
          }}
        }}
      }}

      if (state.showFills && DATA.fills && state.dataset !== '__benchmark__') {{
        const datasetName = state.dataset || DATA.backtestDatasets[0];
        const datasetFills = DATA.fills[datasetName];
        if (datasetFills && datasetFills[state.symbol]) {{
          const fills = datasetFills[state.symbol];
          const fillTime = fills.global_time || [];
          const fillTimeDisplay = state.timeAxis === 'global' ? fillTime : fills.timestamp || fillTime;
          const fillPrice = fills.price || [];
          const fillQty = fills.quantity || [];
          const fillSide = fills.side || [];
          const fillDay = fills.day || [];
          const fillTs = fills.timestamp || [];

          let fillBase = null;
          if (normalizeBy !== 'none') {{
            const baseSeries = normalizeBy.startsWith('indicator:')
              ? (indicatorData[normalizeBy.replace('indicator:', '')] || null)
              : book[normalizeBy];
            fillBase = alignBaseline(fillTime, baseSeries, book.global_time);
          }}
          const fillPriceNorm = normalizeSeries(fillPrice, fillBase);

          const sideBuckets = {{ buy: [], sell: [], unknown: [] }};
          fillTime.forEach((_, idx) => {{
            if (!isBacktestDayAllowed(fillDay[idx])) return;
            const side = (fillSide[idx] || 'unknown').toLowerCase();
            if (!sideBuckets[side]) sideBuckets[side] = [];
            sideBuckets[side].push(idx);
          }});

          Object.entries(sideBuckets).forEach(([side, indices]) => {{
            if (indices.length === 0) return;
            const color = '#f59e0b';
            traces.push({{
              x: indices.map(i => fillTimeDisplay[i]),
              y: indices.map(i => fillPriceNorm[i]),
              mode: 'markers',
              name: 'Our fills',
              marker: {{
                size: indices.map(i => Math.min(60, Math.max(8, Math.abs(fillQty[i]) * 4))),
                symbol: 'cross',
                color: color,
                line: {{ color: '#111', width: 0.6 }},
                opacity: 0.9,
              }},
              customdata: indices.map(i => [fillDay[i], fillTs[i], fillPrice[i], fillQty[i], fillSide[i]]),
              hovertemplate: 'day=%{{customdata[0]}}<br>ts=%{{customdata[1]}}<br>price=%{{customdata[2]}}<br>qty=%{{customdata[3]}}<br>side=%{{customdata[4]}}<extra></extra>',
              type: 'scattergl',
            }});
          }});
        }}
      }}

      const layout = {{
        margin: {{ l: 50, r: 20, t: 10, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: state.timeAxis === 'global' ? 'Global time' : 'Timestamp',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
          mirror: true,
        }},
        yaxis: {{
          title: normalizeBy === 'none' ? 'Price' : 'Normalized price',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
          mirror: true,
        }},
        hovermode: 'closest',
      }};

      const cursorTime = state.timeAxis === 'global'
        ? book.global_time[state.cursorIndex]
        : book.timestamp[state.cursorIndex];
      if (cursorTime !== undefined && cursorTime !== null) {{
        layout.shapes = [
          {{
            type: 'line',
            x0: cursorTime,
            x1: cursorTime,
            y0: 0,
            y1: 1,
            xref: 'x',
            yref: 'paper',
            line: {{ color: '#333', width: 1 }},
          }},
        ];
      }}

      return {{ traces, layout }};
    }}

    function buildDepthTraces() {{
      const book = getCurrentBook();
      if (!book) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No market data for the selected round.', state.timeAxis === 'global' ? 'Global time' : 'Timestamp', 'Volume'),
        }};
      }}
      const indices = getFilteredIndices(book);
      const time = getTimeArray(book, indices);
      const bidVol = sliceByIndex(book.top3_bid_volume, indices);
      const askVol = sliceByIndex(book.top3_ask_volume, indices);
      const imbalance = sliceByIndex(book.book_imbalance, indices);
      const traces = [
        {{ x: time, y: bidVol, mode: 'lines', name: 'Top3 bid', line: {{ color: '#1f77b4' }} }},
        {{ x: time, y: askVol, mode: 'lines', name: 'Top3 ask', line: {{ color: '#d62728' }} }},
        {{ x: time, y: imbalance, mode: 'lines', name: 'Imbalance', yaxis: 'y2', line: {{ color: '#9467bd' }} }},
      ];
      const layout = {{
        margin: {{ l: 50, r: 40, t: 20, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: state.timeAxis === 'global' ? 'Global time' : 'Timestamp',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
          mirror: true,
        }},
        yaxis: {{
          title: 'Volume',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis2: {{
          title: 'Imbalance',
          overlaying: 'y',
          side: 'right',
          range: [-1, 1],
          showgrid: false,
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildSpreadTraces() {{
      const book = getCurrentBook();
      if (!book) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No market data for the selected round.', state.timeAxis === 'global' ? 'Global time' : 'Timestamp', 'Price'),
        }};
      }}
      const indices = getFilteredIndices(book);
      const time = getTimeArray(book, indices);
      const mid = sliceByIndex(book.mid_price, indices);
      const spread = sliceByIndex(book.spread, indices);
      const traces = [
        {{ x: time, y: mid, mode: 'lines', name: 'Mid', line: {{ color: '#111111', width: 1 }} }},
        {{ x: time, y: spread, mode: 'lines', name: 'Spread', yaxis: 'y2', line: {{ color: '#ef4444', width: 1 }} }},
      ];
      const layout = {{
        margin: {{ l: 50, r: 40, t: 20, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: state.timeAxis === 'global' ? 'Global time' : 'Timestamp',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: 'Mid',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis2: {{
          title: 'Spread',
          overlaying: 'y',
          side: 'right',
          showgrid: false,
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildFlowTraces() {{
      const trades = getCurrentTrades();
      if (!trades.global_time || trades.global_time.length === 0) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No trade data for the selected round.', state.timeAxis === 'global' ? 'Global time' : 'Timestamp', 'Cumulative net vol'),
        }};
      }}
      const timeRaw = trades.global_time;
      const time = state.timeAxis === 'global' ? timeRaw : (trades.timestamp || timeRaw);
      const qty = trades.abs_qty || trades.quantity || [];
      const agg = trades.aggressor || [];
      const flow = [];
      const filteredTime = [];
      let cum = 0;
      const filteredIdx = getFilteredTradeIndices(trades);
      filteredIdx.forEach(i => {{
        const side = (agg[i] || '').toLowerCase();
        const sign = side === 'buy' ? 1 : side === 'sell' ? -1 : 0;
        cum += sign * Math.abs(qty[i] || 0);
        flow.push(cum);
        filteredTime.push(time[i]);
      }});
      const traces = [
        {{ x: filteredTime, y: flow, mode: 'lines', name: 'Net flow', line: {{ color: '#111111', width: 1.5 }} }},
      ];
      const layout = {{
        margin: {{ l: 50, r: 20, t: 20, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: state.timeAxis === 'global' ? 'Global time' : 'Timestamp',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: 'Cumulative net vol',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildTradeSizeTraces() {{
      const trades = getCurrentTrades();
      if (!trades.abs_qty || trades.abs_qty.length === 0) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No trade data for the selected round.', 'Trade size', 'Count'),
        }};
      }}
      const sizes = getFilteredTradeIndices(trades)
        .map(idx => trades.abs_qty[idx])
        .filter(v => v != null && !Number.isNaN(v));
      const traces = [
        {{ x: sizes, type: 'histogram', marker: {{ color: '#111111' }} }},
      ];
      const layout = {{
        margin: {{ l: 50, r: 20, t: 20, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: 'Trade size',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: 'Count',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildInterarrivalTraces() {{
      const trades = getCurrentTrades();
      if (!trades.global_time || trades.global_time.length < 2) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No trade data for the selected round.', 'Interarrival (time)', 'Count'),
        }};
      }}
      const timeSource = state.timeAxis === 'global' ? trades.global_time : (trades.timestamp || trades.global_time);
      const times = getFilteredTradeIndices(trades).map(idx => timeSource[idx]);
      const deltas = [];
      for (let i = 1; i < times.length; i++) {{
        if (times[i] != null && times[i - 1] != null) {{
          deltas.push(times[i] - times[i - 1]);
        }}
      }}
      const traces = [
        {{ x: deltas, type: 'histogram', marker: {{ color: '#111111' }} }},
      ];
      const layout = {{
        margin: {{ l: 50, r: 20, t: 20, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: 'Interarrival (time)',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: 'Count',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildNoDataLayout(message, xTitle = null, yTitle = null) {{
      return {{
        margin: {{ l: 50, r: 20, t: 20, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: xTitle,
          showgrid: false,
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: yTitle,
          showgrid: false,
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        annotations: [
          {{
            text: message,
            x: 0.5,
            y: 0.5,
            xref: 'paper',
            yref: 'paper',
            showarrow: false,
            font: {{ size: 13, color: '#475569' }},
          }},
        ],
      }};
    }}

    function buildFairValueTraces() {{
      const book = getCurrentBook();
      if (!book) return {{ traces: [], layout: buildNoDataLayout('No order book data.') }};
      const indicatorData = getCurrentIndicatorData();
      const fair = indicatorData.fair_value || null;
      if (!fair) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No fair-value model available for this product.', state.timeAxis === 'global' ? 'Global time' : 'Timestamp', 'Price'),
        }};
      }}

      const indices = getFilteredIndices(book);
      const time = getTimeArray(book, indices);
      const mid = sliceByIndex(book.mid_price, indices);
      const fairSlice = sliceByIndex(fair, indices);
      const residual = indicatorData.fair_residual ? sliceByIndex(indicatorData.fair_residual, indices) : mid.map((v, idx) => {{
        const fv = fairSlice[idx];
        if (v == null || fv == null) return null;
        return v - fv;
      }});

      const traces = [
        {{ x: time, y: mid, mode: 'lines', name: 'Mid', line: {{ color: '#111111', width: 1.5 }} }},
        {{ x: time, y: fairSlice, mode: 'lines', name: 'Fair value', line: {{ color: '#f59e0b', width: 2 }} }},
        {{ x: time, y: residual, mode: 'lines', name: 'Residual', yaxis: 'y2', line: {{ color: '#0f766e', width: 1.25, dash: 'dot' }} }},
      ];

      const layout = {{
        margin: {{ l: 50, r: 45, t: 20, b: 40 }},
        legend: {{ orientation: 'h' }},
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: state.timeAxis === 'global' ? 'Global time' : 'Timestamp',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: 'Price',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis2: {{
          title: 'Residual',
          overlaying: 'y',
          side: 'right',
          showgrid: false,
          zeroline: true,
          zerolinecolor: '#d0d0d0',
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildStructureTraces() {{
      const book = getCurrentBook();
      if (!book) return {{ traces: [], layout: buildNoDataLayout('No order book data.') }};
      const indicatorData = getCurrentIndicatorData();
      const indices = getFilteredIndices(book);
      const time = getTimeArray(book, indices);
      const traces = [];

      if (indicatorData.basket_premium) {{
        traces.push({{
          x: time,
          y: sliceByIndex(indicatorData.basket_premium, indices),
          mode: 'lines',
          name: 'Basket premium',
          line: {{ color: '#ef4444', width: 1.5 }},
        }});
      }}
      if (indicatorData.cross_basket_spread) {{
        traces.push({{
          x: time,
          y: sliceByIndex(indicatorData.cross_basket_spread, indices),
          mode: 'lines',
          name: 'Cross spread',
          line: {{ color: '#2563eb', width: 1.5 }},
        }});
      }}
      if (indicatorData.path_anchor_residual) {{
        traces.push({{
          x: time,
          y: sliceByIndex(indicatorData.path_anchor_residual, indices),
          mode: 'lines',
          name: 'Path residual',
          line: {{ color: '#16a34a', width: 1.5 }},
        }});
      }}
      if (indicatorData.fair_residual) {{
        traces.push({{
          x: time,
          y: sliceByIndex(indicatorData.fair_residual, indices),
          mode: 'lines',
          name: 'Fair residual',
          line: {{ color: '#111111', width: 1.25, dash: 'dot' }},
        }});
      }}

      if (!traces.length) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No relative-value series for this product.', state.timeAxis === 'global' ? 'Global time' : 'Timestamp', 'Residual'),
        }};
      }}

      const layout = {{
        margin: {{ l: 50, r: 20, t: 20, b: 40 }},
        legend: {{ orientation: 'h' }},
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: state.timeAxis === 'global' ? 'Global time' : 'Timestamp',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: 'Residual / premium',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: true,
          zerolinecolor: '#d0d0d0',
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildExtremaDetectorTraces() {{
      const book = getCurrentBook();
      const trades = getCurrentTrades();
      if (!book || !book.timestamp || !trades.global_time || trades.global_time.length === 0) {{
        return {{ traces: [], layout: buildNoDataLayout('No trade/book data for extrema scan.') }};
      }}

      const indicatorData = getCurrentIndicatorData();
      const tradeIndicatorData = getCurrentTradeIndicatorData();
      const normalizeChoice = indicatorData.fair_value ? 'indicator:fair_value' : getResearchNormalizeChoice(book);
      const base = resolveBookBaseSeries(book, indicatorData, normalizeChoice);
      const normalizedMid = normalizeSeries(book.mid_price || [], base);

      const tradeBase = (() => {{
        if (normalizeChoice === 'none') return null;
        if (normalizeChoice.startsWith('indicator:')) {{
          return tradeIndicatorData[normalizeChoice.replace('indicator:', '')] || null;
        }}
        if (normalizeChoice === 'bid_price_1') return trades.bid_at_trade;
        if (normalizeChoice === 'ask_price_1') return trades.ask_at_trade;
        return trades[normalizeChoice];
      }})();
      const tradeNormalizedPrice = normalizeSeries(trades.price || [], tradeBase);
      const filteredTradeIdx = getFilteredTradeIndices(trades).filter(idx => {{
        if (state.extremaQty === null) return true;
        return Math.abs((trades.abs_qty || trades.quantity || [])[idx] || 0) === state.extremaQty;
      }});

      const time = getTimeArray(book, getFilteredIndices(book));
      const midSlice = sliceByIndex(normalizedMid, getFilteredIndices(book));

      const runningMin = Array(normalizedMid.length).fill(null);
      const runningMax = Array(normalizedMid.length).fill(null);
      const byDay = new Map();
      for (let i = 0; i < book.day.length; i++) {{
        const day = book.day[i];
        if (day == null) continue;
        if (!byDay.has(day)) byDay.set(day, []);
        byDay.get(day).push(i);
      }}
      byDay.forEach(indices => {{
        let minVal = null;
        let maxVal = null;
        indices.forEach(idx => {{
          const value = normalizedMid[idx];
          if (value == null || Number.isNaN(value)) return;
          minVal = minVal == null ? value : Math.min(minVal, value);
          maxVal = maxVal == null ? value : Math.max(maxVal, value);
          runningMin[idx] = minVal;
          runningMax[idx] = maxVal;
        }});
      }});

      const tradeAgg = trades.aggressor || [];
      const tradeTs = trades.timestamp || [];
      const tradeDays = trades.day || [];
      const tradeTime = state.timeAxis === 'global' ? (trades.global_time || []) : (trades.timestamp || trades.global_time || []);
      const candidateX = [];
      const candidateY = [];
      const buyX = [];
      const buyY = [];
      const sellX = [];
      const sellY = [];
      const tolerance = 0.5;

      byDay.forEach((bookIndices, day) => {{
        const bookTs = bookIndices.map(idx => book.timestamp[idx]);
        const dayTradeIdx = filteredTradeIdx.filter(idx => tradeDays[idx] === day).sort((a, b) => tradeTs[a] - tradeTs[b]);
        let ptr = 0;
        let currentMin = null;
        let currentMax = null;
        dayTradeIdx.forEach(idx => {{
          while (ptr < bookIndices.length && bookTs[ptr] <= tradeTs[idx]) {{
            const bookIdx = bookIndices[ptr];
            const value = normalizedMid[bookIdx];
            if (value != null && !Number.isNaN(value)) {{
              currentMin = currentMin == null ? value : Math.min(currentMin, value);
              currentMax = currentMax == null ? value : Math.max(currentMax, value);
            }}
            ptr += 1;
          }}
          const price = tradeNormalizedPrice[idx];
          if (price == null || Number.isNaN(price)) return;
          candidateX.push(tradeTime[idx]);
          candidateY.push(price);
          const agg = (tradeAgg[idx] || 'unknown').toLowerCase();
          if (agg === 'buy' && currentMin != null && Math.abs(price - currentMin) <= tolerance) {{
            buyX.push(tradeTime[idx]);
            buyY.push(price);
          }}
          if (agg === 'sell' && currentMax != null && Math.abs(price - currentMax) <= tolerance) {{
            sellX.push(tradeTime[idx]);
            sellY.push(price);
          }}
        }});
      }});

      const bookIndices = getFilteredIndices(book);
      const traces = [
        {{
          x: time,
          y: midSlice,
          mode: 'lines',
          name: 'Mid',
          line: {{ color: '#111111', width: 1.5 }},
        }},
        {{
          x: getTimeArray(book, bookIndices),
          y: sliceByIndex(runningMin, bookIndices),
          mode: 'lines',
          name: 'Running low',
          line: {{ color: '#16a34a', width: 1, dash: 'dot' }},
        }},
        {{
          x: getTimeArray(book, bookIndices),
          y: sliceByIndex(runningMax, bookIndices),
          mode: 'lines',
          name: 'Running high',
          line: {{ color: '#dc2626', width: 1, dash: 'dot' }},
        }},
      ];

      if (candidateX.length) {{
        traces.push({{
          x: candidateX,
          y: candidateY,
          mode: 'markers',
          name: state.extremaQty == null ? 'Filtered trades' : `Qty=${{state.extremaQty}} trades`,
          marker: {{ color: '#94a3b8', size: 7, symbol: 'circle' }},
          type: 'scattergl',
        }});
      }}
      if (buyX.length) {{
        traces.push({{
          x: buyX,
          y: buyY,
          mode: 'markers',
          name: 'Extreme buys',
          marker: {{ color: '#16a34a', size: 10, symbol: 'triangle-up' }},
          type: 'scattergl',
        }});
      }}
      if (sellX.length) {{
        traces.push({{
          x: sellX,
          y: sellY,
          mode: 'markers',
          name: 'Extreme sells',
          marker: {{ color: '#dc2626', size: 10, symbol: 'triangle-down' }},
          type: 'scattergl',
        }});
      }}

      const layout = {{
        margin: {{ l: 55, r: 20, t: 20, b: 40 }},
        legend: {{ orientation: 'h' }},
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: state.timeAxis === 'global' ? 'Global time' : 'Timestamp',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: normalizeChoice === 'none' ? 'Price' : `Price - ${{labelForNormalizeChoice(normalizeChoice)}}`,
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: true,
          zerolinecolor: '#d0d0d0',
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildPathProfileTraces() {{
      const book = getCurrentBook();
      if (!book || !book.timestamp || book.timestamp.length === 0) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No market data for the selected round.', 'Timestamp', 'Mid price'),
        }};
      }}

      const indicatorData = getCurrentIndicatorData();
      const normalizeChoice = getResearchNormalizeChoice(book);
      const base = resolveBookBaseSeries(book, indicatorData, normalizeChoice);
      const normalizedMid = normalizeSeries(book.mid_price || [], base);
      const buckets = new Map();
      const selectedDay = state.dayFilter === 'all' ? null : Number(state.dayFilter);
      const selectedX = [];
      const selectedY = [];

      for (let i = 0; i < book.timestamp.length; i++) {{
        const timestamp = book.timestamp[i];
        const value = normalizedMid[i];
        if (timestamp == null || value == null || Number.isNaN(timestamp) || Number.isNaN(value)) continue;
        if (!buckets.has(timestamp)) buckets.set(timestamp, []);
        buckets.get(timestamp).push(value);
        if (selectedDay !== null && book.day[i] === selectedDay) {{
          selectedX.push(timestamp);
          selectedY.push(value);
        }}
      }}

      const timestamps = Array.from(buckets.keys()).sort((a, b) => a - b);
      const medianSeries = timestamps.map(ts => median(buckets.get(ts)));
      const meanSeries = timestamps.map(ts => mean(buckets.get(ts)));
      const lowerSeries = timestamps.map(ts => quantile(buckets.get(ts), 0.25));
      const upperSeries = timestamps.map(ts => quantile(buckets.get(ts), 0.75));

      const traces = [
        {{
          x: timestamps,
          y: lowerSeries,
          mode: 'lines',
          line: {{ color: 'rgba(14, 116, 144, 0)' }},
          hoverinfo: 'skip',
          showlegend: false,
        }},
        {{
          x: timestamps,
          y: upperSeries,
          mode: 'lines',
          fill: 'tonexty',
          fillcolor: 'rgba(14, 116, 144, 0.15)',
          line: {{ color: 'rgba(14, 116, 144, 0)' }},
          name: 'IQR',
          hoverinfo: 'skip',
        }},
        {{
          x: timestamps,
          y: medianSeries,
          mode: 'lines',
          name: 'Median',
          line: {{ color: '#0f766e', width: 2 }},
        }},
        {{
          x: timestamps,
          y: meanSeries,
          mode: 'lines',
          name: 'Mean',
          line: {{ color: '#111111', width: 1, dash: 'dot' }},
        }},
      ];

      if (selectedDay !== null && selectedX.length) {{
        traces.push({{
          x: selectedX,
          y: selectedY,
          mode: 'lines',
          name: `Day ${{selectedDay}}`,
          line: {{ color: '#ef4444', width: 1.5 }},
        }});
      }}

      const layout = {{
        margin: {{ l: 55, r: 20, t: 20, b: 40 }},
        legend: {{ orientation: 'h' }},
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: 'Timestamp',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: normalizeChoice === 'none' ? 'Mid price' : `Mid - ${{labelForNormalizeChoice(normalizeChoice)}}`,
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: true,
          zerolinecolor: '#d0d0d0',
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildAutocorrTraces() {{
      const book = getCurrentBook();
      if (!book || !book.timestamp || book.timestamp.length < 3) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No market data for the selected round.', 'Lag', 'Autocorr'),
        }};
      }}

      const indicatorData = getCurrentIndicatorData();
      const normalizeChoice = getResearchNormalizeChoice(book);
      const base = resolveBookBaseSeries(book, indicatorData, normalizeChoice);
      const normalizedMid = normalizeSeries(book.mid_price || [], base);
      const perDay = new Map();

      for (let i = 0; i < normalizedMid.length; i++) {{
        const day = book.day[i];
        const value = normalizedMid[i];
        if (day == null || value == null || Number.isNaN(value)) continue;
        if (state.dayFilter !== 'all' && Number(state.dayFilter) !== day) continue;
        if (!perDay.has(day)) perDay.set(day, []);
        perDay.get(day).push(value);
      }}

      const maxLag = 25;
      const lags = [];
      const values = [];
      for (let lag = 1; lag <= maxLag; lag++) {{
        const left = [];
        const right = [];
        perDay.forEach(series => {{
          if (!series || series.length <= lag + 1) return;
          const returns = [];
          for (let i = 1; i < series.length; i++) {{
            const prev = series[i - 1];
            const curr = series[i];
            if (prev == null || curr == null) continue;
            returns.push(curr - prev);
          }}
          for (let i = lag; i < returns.length; i++) {{
            left.push(returns[i - lag]);
            right.push(returns[i]);
          }}
        }});
        lags.push(lag);
        values.push(correlation(left, right));
      }}

      const traces = [
        {{
          x: lags,
          y: values,
          type: 'bar',
          marker: {{
            color: values.map(v => (v != null && v < 0 ? '#ef4444' : '#2563eb')),
          }},
        }},
      ];
      const layout = {{
        margin: {{ l: 50, r: 20, t: 20, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: 'Lag',
          showgrid: false,
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: 'Autocorr',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: true,
          zerolinecolor: '#d0d0d0',
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildImbalanceResponseTraces() {{
      const book = getCurrentBook();
      if (!book || !book.book_imbalance || !book.mid_price) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No market data for the selected round.', 'Forward horizon', 'Imbalance bucket'),
        }};
      }}

      const horizons = [1, 5, 10];
      const rows = [];
      const imbalances = [];
      const byDay = new Map();

      for (let i = 0; i < book.day.length; i++) {{
        const day = book.day[i];
        if (day == null) continue;
        if (state.dayFilter !== 'all' && Number(state.dayFilter) !== day) continue;
        if (!byDay.has(day)) byDay.set(day, []);
        byDay.get(day).push(i);
      }}

      byDay.forEach(indices => {{
        for (let pos = 0; pos < indices.length; pos++) {{
          const idx = indices[pos];
          const imbalance = book.book_imbalance[idx];
          const mid = book.mid_price[idx];
          if (imbalance == null || mid == null || Number.isNaN(imbalance) || Number.isNaN(mid)) continue;
          const response = {{}};
          let hasResponse = false;
          horizons.forEach(horizon => {{
            const futurePos = pos + horizon;
            if (futurePos >= indices.length) {{
              response[horizon] = null;
              return;
            }}
            const futureIdx = indices[futurePos];
            const futureMid = book.mid_price[futureIdx];
            if (futureMid == null || Number.isNaN(futureMid)) {{
              response[horizon] = null;
              return;
            }}
            response[horizon] = futureMid - mid;
            hasResponse = true;
          }});
          if (!hasResponse) continue;
          imbalances.push(imbalance);
          rows.push({{ imbalance, response }});
        }}
      }});

      if (!rows.length) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No market data for the selected round.', 'Forward horizon', 'Imbalance bucket'),
        }};
      }}

      const cuts = [
        quantile(imbalances, 0.2),
        quantile(imbalances, 0.4),
        quantile(imbalances, 0.6),
        quantile(imbalances, 0.8),
      ];
      const bucketCount = 5;
      const bucketValues = Array.from({{ length: bucketCount }}, () => Array.from({{ length: horizons.length }}, () => []));

      const resolveBucket = (value) => {{
        if (value <= cuts[0]) return 0;
        if (value <= cuts[1]) return 1;
        if (value <= cuts[2]) return 2;
        if (value <= cuts[3]) return 3;
        return 4;
      }};

      rows.forEach(row => {{
        const bucket = resolveBucket(row.imbalance);
        horizons.forEach((horizon, horizonIdx) => {{
          const value = row.response[horizon];
          if (value == null || Number.isNaN(value)) return;
          bucketValues[bucket][horizonIdx].push(value);
        }});
      }});

      const z = bucketValues.map(row => row.map(cell => mean(cell)));
      const traces = [
        {{
          x: horizons.map(h => `+${{h}}`),
          y: ['Q1 low', 'Q2', 'Q3', 'Q4', 'Q5 high'],
          z,
          type: 'heatmap',
          colorscale: 'RdBu',
          reversescale: true,
          zmid: 0,
          hovertemplate: 'imbalance bucket=%{{y}}<br>horizon=%{{x}}<br>avg dMid=%{{z:.4f}}<extra></extra>',
        }},
      ];
      const layout = {{
        margin: {{ l: 70, r: 20, t: 20, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: 'Forward horizon',
          showgrid: false,
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: 'Imbalance bucket',
          showgrid: false,
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
      }};
      return {{ traces, layout }};
    }}

    function buildPnLTraces() {{
      if (!hasCurrentMarketData()) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No market data for the selected round.', 'Step', 'PnL'),
        }};
      }}
      if (!state.dataset || !DATA.backtest[state.dataset]) {{
        return {{ traces: [], layout: {{}} }};
      }}
      const data = DATA.backtest[state.dataset];
      const indices = getFilteredBacktestIndices(data);
      if (!indices.length) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No backtest data for the selected backtest day.', 'Step', 'PnL'),
        }};
      }}
      const x = sliceByIndex(data.step, indices);
      const traces = [
        {{ x, y: sliceByIndex(data.total_pnl || [], indices), mode: 'lines', name: 'Total PnL', line: {{ color: '#111111', width: 2 }} }},
      ];
      if (data.realized_pnl) {{
        traces.push({{ x, y: sliceByIndex(data.realized_pnl, indices), mode: 'lines', name: 'Realized', line: {{ color: '#666666', dash: 'dot' }} }});
      }}
      if (data.unrealized_pnl) {{
        traces.push({{ x, y: sliceByIndex(data.unrealized_pnl, indices), mode: 'lines', name: 'Unrealized', line: {{ color: '#999999', dash: 'dash' }} }});
      }}

      const layout = {{
        margin: {{ l: 50, r: 20, t: 20, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: 'Step',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: 'PnL',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
      }};
      const cursorStep = getCursorStep();
      if (cursorStep !== null) {{
        layout.shapes = [
          {{
            type: 'line',
            x0: cursorStep,
            x1: cursorStep,
            y0: 0,
            y1: 1,
            xref: 'x',
            yref: 'paper',
            line: {{ color: '#333', width: 1 }},
          }},
        ];
      }}
      return {{ traces, layout }};
    }}

    function buildPositionTraces() {{
      if (!hasCurrentMarketData()) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No market data for the selected round.', 'Step', 'Position'),
        }};
      }}
      if (!state.dataset || !DATA.backtest[state.dataset]) {{
        return {{ traces: [], layout: {{}} }};
      }}
      const data = DATA.backtest[state.dataset];
      const key = `position_${{state.symbol}}`;
      if (!data[key]) {{
        return {{ traces: [], layout: {{}} }};
      }}
      const indices = getFilteredBacktestIndices(data);
      if (!indices.length) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No backtest data for the selected backtest day.', 'Step', 'Position'),
        }};
      }}
      const x = sliceByIndex(data.step, indices);
      const traces = [
        {{ x, y: sliceByIndex(data[key], indices), mode: 'lines', name: `Pos ${{state.symbol}}`, line: {{ color: '#111111', width: 2 }} }},
      ];
      const layout = {{
        margin: {{ l: 50, r: 20, t: 20, b: 40 }},
        showlegend: false,
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: 'Step',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: 'Position',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
      }};
      const cursorStep = getCursorStep();
      if (cursorStep !== null) {{
        layout.shapes = [
          {{
            type: 'line',
            x0: cursorStep,
            x1: cursorStep,
            y0: 0,
            y1: 1,
            xref: 'x',
            yref: 'paper',
            line: {{ color: '#333', width: 1 }},
          }},
        ];
      }}
      return {{ traces, layout }};
    }}

    function buildCompareTraces() {{
      if (!hasCurrentMarketData()) {{
        return {{
          traces: [],
          layout: buildNoDataLayout('No market data for the selected round.', 'Step', 'Comparison'),
        }};
      }}
      if (!DATA.backtestDatasets || DATA.backtestDatasets.length === 0) {{
        return {{ traces: [], layout: {{}} }};
      }}
      const metric = compareMetric.value;
      const symbol = compareSymbol.value;
      const datasetA = compareDatasetA.value;
      const datasetB = compareDatasetB.value;
      const dataA = DATA.backtest[datasetA];
      const dataB = DATA.backtest[datasetB];
      if (!dataA || !dataB) {{
        return {{ traces: [], layout: {{}} }};
      }}
      const resolveSeries = (data) => {{
        const indices = getFilteredBacktestIndices(data);
        const x = sliceByIndex(data.step || [], indices);
        if (metric === 'total_pnl') return {{ x, y: sliceByIndex(data.total_pnl || [], indices) }};
        if (metric === 'realized_pnl') return {{ x, y: sliceByIndex(data.realized_pnl || [], indices) }};
        if (metric === 'unrealized_pnl') return {{ x, y: sliceByIndex(data.unrealized_pnl || [], indices) }};
        if (metric === 'position') return {{ x, y: sliceByIndex(data[`position_${{symbol}}`] || [], indices) }};
        if (metric === 'pnl_symbol') return {{ x, y: sliceByIndex(data[`pnl_${{symbol}}`] || [], indices) }};
        return {{ x: [], y: [] }};
      }};
      const seriesA = resolveSeries(dataA);
      const seriesB = resolveSeries(dataB);
      const traces = [
        {{ x: seriesA.x, y: seriesA.y, mode: 'lines', name: datasetA, line: {{ color: '#1f77b4' }} }},
        {{ x: seriesB.x, y: seriesB.y, mode: 'lines', name: datasetB, line: {{ color: '#e76f51' }} }},
      ];
      const layout = {{
        margin: {{ l: 50, r: 20, t: 20, b: 40 }},
        legend: {{ orientation: 'h' }},
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff',
        xaxis: {{
          title: 'Step',
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
        yaxis: {{
          title: metric.replace('_', ' '),
          showgrid: true,
          gridcolor: '#e6e6e6',
          zeroline: false,
          showline: true,
          linecolor: '#111111',
        }},
      }};
      const cursorStep = getCursorStep();
      if (cursorStep !== null) {{
        layout.shapes = [
          {{
            type: 'line',
            x0: cursorStep,
            x1: cursorStep,
            y0: 0,
            y1: 1,
            xref: 'x',
            yref: 'paper',
            line: {{ color: '#333', width: 1 }},
          }},
        ];
      }}
      return {{ traces, layout }};
    }}

    function renderChart(targetId, builder, errorTitle) {{
      try {{
        const {{ traces, layout }} = builder();
        Plotly.react(targetId, traces, layout, {{ displayModeBar: false }});
      }} catch (error) {{
        console.error(`Failed to render ${{targetId}}`, error);
        const message = error && error.message
          ? `${{errorTitle || 'Chart error'}}: ${{error.message}}`
          : (errorTitle || 'Chart error');
        Plotly.react(targetId, [], buildNoDataLayout(message), {{ displayModeBar: false }});
      }}
    }}

    function updateOrderbook() {{
      renderChart('orderbook', buildOrderbookTraces, 'Order book render error');
    }}

    function updateOrderbookNormalized() {{
      renderChart('orderbookNormalized', () => buildOrderbookTraces(state.normalizedBy || 'wall_mid'), 'Normalized order book render error');
    }}

    function updateDepth() {{
      renderChart('depth', buildDepthTraces, 'Depth render error');
    }}

    function updateSpread() {{
      renderChart('spreadChart', buildSpreadTraces, 'Spread render error');
    }}

    function updateFlow() {{
      renderChart('flowChart', buildFlowTraces, 'Flow render error');
    }}

    function updateTradeSize() {{
      renderChart('sizeChart', buildTradeSizeTraces, 'Trade-size render error');
    }}

    function updateInterarrival() {{
      renderChart('interarrivalChart', buildInterarrivalTraces, 'Interarrival render error');
    }}

    function updatePnL() {{
      renderChart('pnl', buildPnLTraces, 'PnL render error');
    }}

    function updatePosition() {{
      renderChart('position', buildPositionTraces, 'Position render error');
    }}

    function updateCompare() {{
      renderChart('compare', buildCompareTraces, 'Compare render error');
    }}

    function updatePlotLab() {{
      renderChart('plotLab', buildPlotLabTraces, 'Plot-lab render error');
    }}

    function updateFairValue() {{
      renderChart('fairValueChart', buildFairValueTraces, 'Fair-value render error');
    }}

    function updateStructure() {{
      renderChart('structureChart', buildStructureTraces, 'Relative-value render error');
    }}

    function updateExtremaDetector() {{
      renderChart('extremaChart', buildExtremaDetectorTraces, 'Extrema render error');
    }}

    function updatePathProfile() {{
      renderChart('pathProfileChart', buildPathProfileTraces, 'Path-profile render error');
    }}

    function updateAutocorr() {{
      renderChart('autocorrChart', buildAutocorrTraces, 'Autocorr render error');
    }}

    function updateImbalanceResponse() {{
      renderChart('imbalanceResponseChart', buildImbalanceResponseTraces, 'Imbalance-response render error');
    }}

    function renderLogs(rows) {{
      if (!rows || rows.length === 0) {{
        document.getElementById('logs').innerHTML = '<div class="hover-meta">No logs available.</div>';
        return;
      }}
      const keys = Object.keys(rows[0]);
      let html = '<table class="log-table"><thead><tr>';
      keys.forEach(key => {{ html += `<th>${{key}}</th>`; }});
      html += '</tr></thead><tbody>';
      rows.forEach(row => {{
        html += '<tr>';
        keys.forEach(key => {{ html += `<td>${{row[key] ?? ''}}</td>`; }});
        html += '</tr>';
      }});
      html += '</tbody></table>';
      document.getElementById('logs').innerHTML = html;
    }}

    function updateLogs() {{
      const query = (logSearch.value || '').toLowerCase();
      let rows = DATA.logs || [];
      if (query) {{
        rows = rows.filter(row => JSON.stringify(row).toLowerCase().includes(query));
        renderLogs(rows);
        return;
      }}
      const book = getCurrentBook();
      if (book && rows.length > 0 && book.timestamp) {{
        const ts = book.timestamp[state.cursorIndex];
        if (ts != null) {{
          const nearest = rows.reduce((best, row) => {{
            if (row.timestamp == null) return best;
            const diff = Math.abs(row.timestamp - ts);
            if (!best || diff < best.diff) return {{ diff, row }};
            return best;
          }}, null);
          if (nearest && nearest.row) {{
            renderLogs([nearest.row]);
            return;
          }}
        }}
      }}
      renderLogs(rows);
    }}

    function updateOrderbookTable() {{
      const book = getCurrentBook();
      if (!book || !book.timestamp || book.timestamp.length === 0) {{
        orderbookTable.innerHTML = '<div class=\"hover-meta\">No order book data.</div>';
        return;
      }}
      const idx = Math.max(0, Math.min(book.timestamp.length - 1, state.cursorIndex));
      const levels = DATA.levels || [1,2,3];
      let html = '<table class=\"orderbook-table\">';
      html += '<thead><tr><th>Bid Vol</th><th>Bid Px</th><th>Ask Px</th><th>Ask Vol</th></tr></thead><tbody>';
      levels.forEach(level => {{
        const bidPx = book[`bid_price_${{level}}`]?.[idx];
        const bidVol = book[`bid_volume_${{level}}`]?.[idx];
        const askPx = book[`ask_price_${{level}}`]?.[idx];
        const askVol = book[`ask_volume_${{level}}`]?.[idx];
        html += `<tr><td>${{bidVol ?? ''}}</td><td>${{bidPx ?? ''}}</td><td>${{askPx ?? ''}}</td><td>${{askVol ?? ''}}</td></tr>`;
      }});
      html += '</tbody></table>';
      const mid = book.mid_price?.[idx];
      const spread = book.spread?.[idx];
      const wall = book.wall_mid?.[idx];
      const imbalance = book.book_imbalance?.[idx];
      html += `<div class=\"hover-meta\">mid=${{mid ?? ''}} | spread=${{spread ?? ''}} | wall=${{wall ?? ''}} | imbalance=${{imbalance ?? ''}}</div>`;
      orderbookTable.innerHTML = html;
    }}

    function updateAll() {{
      updateOrderbook();
      updatePnL();
      updatePosition();
      if (showExtras.checked) {{
        updateDepth();
        updateCompare();
        updateSpread();
        updateFlow();
        updateTradeSize();
        updateInterarrival();
        updateFairValue();
        updateStructure();
        updateExtremaDetector();
        updatePlotLab();
        updatePathProfile();
        updateAutocorr();
        updateImbalanceResponse();
        if (state.showNormalized) {{
          updateOrderbookNormalized();
        }}
      }}
      updateLogs();
      updateOrderbookTable();
      updateStats();
    }}

    initControls();
    updateAll();

    const orderbookDiv = document.getElementById('orderbook');
    orderbookDiv.on('plotly_hover', function(event) {{
      if (!event || !event.points || event.points.length === 0) return;
      const point = event.points[0];
      const book = getCurrentBook();
      if (!book) return;
      let day = null;
      let ts = null;
      if (point.customdata && point.customdata.length >= 2) {{
        day = point.customdata[0];
        ts = point.customdata[1];
      }} else {{
        const idx = state.currentIndices[point.pointIndex];
        day = book.day[idx];
        ts = book.timestamp[idx];
      }}
      hoverInfo.textContent = `Hovered day ${{day}} @ ${{ts}}`;
    }});

    orderbookDiv.on('plotly_click', function(event) {{
      if (!event || !event.points || event.points.length === 0) return;
      const point = event.points[0];
      const idx = state.currentIndices[point.pointIndex];
      if (idx !== undefined) {{
        setCursorIndex(idx);
      }}
    }});
  </script>
</body>
</html>"""

    output_path.write_text(html)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    config_args = argparse.Namespace(**vars(args))
    config_args.output = None
    config = load_config(config_args)
    output_path = args.output if args.output else DEFAULT_OUTPUT

    market_source_catalog, preferred_market_source = build_market_source_catalog(config)
    if not market_source_catalog:
        raise FileNotFoundError(f"No market data discovered from {config.data_dir}")

    raw_indicators = load_indicator_entries(config.indicator_file) if config.indicator_file else pd.DataFrame()

    all_symbols = sorted({symbol for entry in market_source_catalog.values() for symbol in entry["symbols"]})
    levels = sorted({level for entry in market_source_catalog.values() for level in entry["levels"]})
    indicator_options: List[str] = []
    group_values = set()
    product_profiles: Dict[str, dict] = {}
    visualizer_presets: List[dict] = [{"id": "manual", "label": "Manual", "description": "Manual controls only."}]
    seen_presets = {"manual"}

    book_payload: Dict[str, Dict[str, dict]] = {}
    trade_payload: Dict[str, Dict[str, dict]] = {}
    indicator_payload: Dict[str, Dict[str, Dict[str, List[Optional[float]]]]] = {}
    trade_indicator_payload: Dict[str, Dict[str, Dict[str, List[Optional[float]]]]] = {}
    prices_by_source: Dict[str, pd.DataFrame] = {}
    market_sources_meta: List[dict] = []

    for source_id, source_entry in sorted(market_source_catalog.items()):
        prices = source_entry["prices"]
        aligned_trades = source_entry["trades"]
        symbols = source_entry["symbols"]
        prices_by_source[source_id] = prices

        source_indicator_payload: Dict[str, Dict[str, List[Optional[float]]]] = {}
        source_trade_indicator_payload: Dict[str, Dict[str, List[Optional[float]]]] = {}
        source_indicator_options: List[str] = []

        if not raw_indicators.empty:
            if config.indicator_columns:
                source_indicator_options = list(config.indicator_columns)
            else:
                source_indicator_options = [
                    col
                    for col in raw_indicators.columns
                    if col not in {"timestamp", "day", "symbol"}
                    and pd.api.types.is_numeric_dtype(raw_indicators[col])
                ]
            source_indicator_payload = align_indicators_to_book(prices, raw_indicators, source_indicator_options)
            source_trade_indicator_payload = (
                align_indicators_to_trades(aligned_trades, raw_indicators, source_indicator_options)
                if not aligned_trades.empty
                else {}
            )

        derived_indicators, source_profiles, source_presets = build_derived_indicator_entries(prices)
        derived_options = [
            col
            for col in derived_indicators.columns
            if col not in {"timestamp", "day", "symbol"}
            and pd.api.types.is_numeric_dtype(derived_indicators[col])
        ] if not derived_indicators.empty else []
        derived_payload = align_indicators_to_book(prices, derived_indicators, derived_options) if derived_options else {}
        derived_trade_payload = (
            align_indicators_to_trades(aligned_trades, derived_indicators, derived_options)
            if derived_options and not aligned_trades.empty
            else {}
        )
        source_indicator_payload = merge_indicator_payloads(source_indicator_payload, derived_payload)
        source_trade_indicator_payload = merge_indicator_payloads(source_trade_indicator_payload, derived_trade_payload)

        indicator_options = list(dict.fromkeys([*indicator_options, *source_indicator_options, *derived_options]))
        product_profiles.update(source_profiles)
        for preset in source_presets:
            if preset["id"] in seen_presets:
                continue
            visualizer_presets.append(preset)
            seen_presets.add(preset["id"])

        book_payload[source_id] = build_book_payload(prices, symbols, levels)
        trade_payload[source_id] = build_trade_payload(aligned_trades, symbols)
        indicator_payload[source_id] = source_indicator_payload
        trade_indicator_payload[source_id] = source_trade_indicator_payload

        if not aligned_trades.empty and "group_tier" in aligned_trades.columns:
            group_values.update(aligned_trades["group_tier"].dropna().unique().tolist())

        market_sources_meta.append(
            {
                "id": source_id,
                "label": source_entry["label"],
                "round": source_entry["round"],
                "kind": source_entry["kind"],
                "symbols": symbols,
                "days": source_entry["days"],
                "maxTimestamp": source_entry["maxTimestamp"],
            }
        )

    strategy_catalog = discover_strategy_catalog(REPO_ROOT / "traders")
    backtest_root, dataset_dirs, preferred_dataset_dir = resolve_backtest_root(config.backtest_path)
    backtest_index, id_map = build_backtest_index(dataset_dirs, backtest_root, strategy_catalog, preferred_dataset_dir)
    backtest_payload = build_backtest_payload(dataset_dirs, id_map)
    fills_payload = build_fills_payload(dataset_dirs, id_map, prices_by_source, backtest_index)
    orders_payload = build_orders_payload(dataset_dirs, id_map, prices_by_source, backtest_index)
    backtest_datasets = [entry["id"] for entry in backtest_index if entry["id"] in backtest_payload]
    default_dataset = next((entry["id"] for entry in backtest_index if entry.get("preferred") and entry["id"] in backtest_payload), None)
    round_options = sorted(
        {
            *strategy_catalog.keys(),
            *[entry["round"] for entry in market_sources_meta],
            *[entry["round"] for entry in backtest_index],
        }
    )
    group_options: List[str] = []
    if group_values:
        group_order = [
            "M1",
            "M2",
            "M3",
            "S1",
            "S2",
            "S3",
            "S4",
            "B1",
            "B2",
            "I1",
            "I2",
            "F1",
        ]

        def group_key(value: str) -> Tuple[int, int, str]:
            if value in group_order:
                return (0, group_order.index(value), value)
            return (1, 999, value)

        group_options = sorted(group_values, key=group_key)

    payload = {
        "symbols": all_symbols,
        "levels": levels,
        "book": book_payload,
        "trades": trade_payload,
        "indicators": indicator_payload,
        "indicatorOptions": indicator_options,
        "groupOptions": group_options,
        "fills": fills_payload,
        "orders": orders_payload,
        "tradeIndicators": trade_indicator_payload,
        "backtest": backtest_payload,
        "backtestDatasets": backtest_datasets,
        "backtestIndex": backtest_index,
        "roundOptions": round_options,
        "strategyCatalog": strategy_catalog,
        "marketSources": market_sources_meta,
        "productProfiles": product_profiles,
        "presets": visualizer_presets,
        "logs": build_log_payload(config),
        "defaults": {
            "minQty": config.min_trade_qty,
            "maxQty": config.max_trade_qty,
            "normalizeBy": config.normalize_by or "none",
            "maxPoints": config.max_points,
            "smallQty": config.small_trade_qty,
            "bigQty": config.big_trade_qty,
            "presetId": "manual",
            "extremaQty": None,
            "marketSource": preferred_market_source,
            "dataset": default_dataset,
            "roundFilter": market_source_catalog.get(preferred_market_source, {}).get("round", "all"),
        },
    }

    write_html(output_path, payload, config)
    print(f"Interactive visualizer written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
