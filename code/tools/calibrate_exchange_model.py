from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from backtester import (
    Trade,
    build_state,
    load_run_log,
    load_strategy_class,
    normalize_strategy_response,
)


def inside_spread_size_bucket(order_qty: int) -> str:
    qty = max(1, int(order_qty))
    if qty <= 4:
        return "le_4"
    if qty <= 12:
        return "5_12"
    return "gt_12"


def inside_spread_distance_ticks(side: str, order_price: int, best_bid: int, best_ask: int) -> int:
    if side == "buy":
        return max(0, int(order_price) - int(best_bid))
    return max(0, int(best_ask) - int(order_price))


def stats_dict(frame: pd.DataFrame) -> Dict[str, object]:
    if frame.empty:
        return {
            "hit_probability": 0.0,
            "fill_ratio": 0.0,
            "order_count": 0,
            "fill_count": 0,
        }

    fills = frame[frame["filled_qty"] > 0].copy()
    fill_ratio = float((fills["filled_qty"] / fills["order_qty"]).mean()) if not fills.empty else 0.0
    return {
        "hit_probability": float((frame["filled_qty"] > 0).mean()),
        "fill_ratio": fill_ratio,
        "order_count": int(len(frame)),
        "fill_count": int((frame["filled_qty"] > 0).sum()),
    }


def nested_stats(frame: pd.DataFrame) -> Dict[str, object]:
    payload = stats_dict(frame)
    payload["size_buckets"] = {
        str(bucket): stats_dict(bucket_frame)
        for bucket, bucket_frame in sorted(frame.groupby("size_bucket"), key=lambda item: str(item[0]))
    }
    payload["distances"] = {
        str(int(distance)): stats_dict(distance_frame)
        for distance, distance_frame in sorted(frame.groupby("distance_ticks"), key=lambda item: int(item[0]))
    }
    return payload


def build_symbol_calibration(frame: pd.DataFrame) -> Dict[str, object]:
    payload = stats_dict(frame)
    payload["sides"] = {
        str(side): nested_stats(side_frame)
        for side, side_frame in sorted(frame.groupby("side"), key=lambda item: str(item[0]))
    }
    payload["size_buckets"] = {
        str(bucket): stats_dict(bucket_frame)
        for bucket, bucket_frame in sorted(frame.groupby("size_bucket"), key=lambda item: str(item[0]))
    }
    payload["distances"] = {
        str(int(distance)): stats_dict(distance_frame)
        for distance, distance_frame in sorted(frame.groupby("distance_ticks"), key=lambda item: int(item[0]))
    }
    payload["spreads"] = {
        str(int(spread)): {
            **stats_dict(spread_frame),
            "sides": {
                str(side): nested_stats(side_frame)
                for side, side_frame in sorted(spread_frame.groupby("side"), key=lambda item: str(item[0]))
            },
            "size_buckets": {
                str(bucket): stats_dict(bucket_frame)
                for bucket, bucket_frame in sorted(spread_frame.groupby("size_bucket"), key=lambda item: str(item[0]))
            },
            "distances": {
                str(int(distance)): stats_dict(distance_frame)
                for distance, distance_frame in sorted(
                    spread_frame.groupby("distance_ticks"),
                    key=lambda item: int(item[0]),
                )
            },
        }
        for spread, spread_frame in sorted(frame.groupby("spread"), key=lambda item: int(item[0]))
    }
    payload["default_hit_probability"] = float(payload["hit_probability"])
    payload["default_fill_ratio"] = float(payload["fill_ratio"])
    return payload


def calibration_stats(config: Optional[Dict[str, object]]) -> Optional[Tuple[float, float]]:
    if not isinstance(config, dict):
        return None
    if "hit_probability" not in config and "fill_ratio" not in config:
        return None
    return (
        float(config.get("hit_probability", 0.0)),
        float(config.get("fill_ratio", 0.0)),
    )


def default_symbol_stats(config: Optional[Dict[str, object]]) -> Optional[Tuple[float, float]]:
    if not isinstance(config, dict):
        return None
    if "default_hit_probability" not in config and "default_fill_ratio" not in config:
        return None
    return (
        float(config.get("default_hit_probability", 0.0)),
        float(config.get("default_fill_ratio", 0.0)),
    )


def blend_stats(
    prior: Tuple[float, float],
    observed: Tuple[float, float],
    order_count: Optional[int],
    prior_weight: float,
) -> Tuple[float, float]:
    if order_count is None or prior_weight <= 0:
        return observed
    observed_weight = float(order_count) / float(order_count + prior_weight)
    return (
        ((1.0 - observed_weight) * prior[0]) + (observed_weight * observed[0]),
        ((1.0 - observed_weight) * prior[1]) + (observed_weight * observed[1]),
    )


def merge_bucket_node(
    observed_node: Optional[Dict[str, object]],
    prior_node: Optional[Dict[str, object]],
    fallback_prior_stats: Tuple[float, float],
    prior_weight: float,
) -> Dict[str, object]:
    merged: Dict[str, object] = copy.deepcopy(prior_node) if isinstance(prior_node, dict) else {}
    if not isinstance(observed_node, dict):
        return merged

    merged.update(copy.deepcopy(observed_node))

    prior_stats = calibration_stats(prior_node) or fallback_prior_stats
    observed_stats = calibration_stats(observed_node)
    if observed_stats is not None:
        blended_hit, blended_fill = blend_stats(
            prior=prior_stats,
            observed=observed_stats,
            order_count=observed_node.get("order_count") if isinstance(observed_node.get("order_count"), int) else None,
            prior_weight=prior_weight,
        )
        merged["hit_probability"] = blended_hit
        merged["fill_ratio"] = blended_fill

    child_fallback = calibration_stats(merged) or prior_stats
    for key in ("sides", "size_buckets", "distances"):
        observed_children = observed_node.get(key, {}) if isinstance(observed_node.get(key), dict) else {}
        prior_children = prior_node.get(key, {}) if isinstance(prior_node, dict) and isinstance(prior_node.get(key), dict) else {}
        if not observed_children and not prior_children:
            continue

        merged_children: Dict[str, object] = {}
        for child_key in sorted(set(prior_children) | set(observed_children)):
            if child_key in observed_children:
                child_prior_stats = calibration_stats(prior_children.get(child_key)) or child_fallback
                merged_children[str(child_key)] = merge_bucket_node(
                    observed_node=observed_children[child_key],
                    prior_node=prior_children.get(child_key),
                    fallback_prior_stats=child_prior_stats,
                    prior_weight=prior_weight,
                )
            else:
                merged_children[str(child_key)] = copy.deepcopy(prior_children[child_key])
        merged[key] = merged_children

    return merged


def merge_prior_calibration(
    observed_calibration: Dict[str, object],
    prior_calibration: Dict[str, object],
    prior_weight: float,
    prior_path: Optional[Path] = None,
) -> Dict[str, object]:
    observed_inside = observed_calibration.get("inside_spread", {})
    prior_inside = prior_calibration.get("inside_spread", {})

    merged: Dict[str, object] = {
        "inputs": copy.deepcopy(observed_calibration.get("inputs", [])),
        "metadata": {
            "prior_weight": float(prior_weight),
        },
        "inside_spread": {},
    }
    if prior_path is not None:
        merged["metadata"]["prior_calibration"] = str(prior_path.expanduser().resolve())

    for symbol in sorted(set(prior_inside) | set(observed_inside)):
        if symbol not in observed_inside:
            merged["inside_spread"][str(symbol)] = copy.deepcopy(prior_inside[symbol])
            continue
        if symbol not in prior_inside:
            merged["inside_spread"][str(symbol)] = copy.deepcopy(observed_inside[symbol])
            continue

        observed_symbol = copy.deepcopy(observed_inside[symbol])
        prior_symbol = prior_inside[symbol]
        symbol_prior_stats = default_symbol_stats(prior_symbol) or default_symbol_stats(observed_symbol)
        if symbol_prior_stats is None:
            symbol_prior_stats = calibration_stats(prior_symbol) or calibration_stats(observed_symbol) or (0.0, 0.0)

        observed_symbol["default_hit_probability"] = symbol_prior_stats[0]
        observed_symbol["default_fill_ratio"] = symbol_prior_stats[1]

        observed_symbol_stats = calibration_stats(observed_symbol)
        if observed_symbol_stats is not None:
            blended_hit, blended_fill = blend_stats(
                prior=symbol_prior_stats,
                observed=observed_symbol_stats,
                order_count=observed_symbol.get("order_count")
                if isinstance(observed_symbol.get("order_count"), int)
                else None,
                prior_weight=prior_weight,
            )
            observed_symbol["hit_probability"] = blended_hit
            observed_symbol["fill_ratio"] = blended_fill

        for key in ("sides", "size_buckets", "distances"):
            observed_children = observed_symbol.get(key, {}) if isinstance(observed_symbol.get(key), dict) else {}
            prior_children = prior_symbol.get(key, {}) if isinstance(prior_symbol.get(key), dict) else {}
            merged_children: Dict[str, object] = {}
            for child_key in sorted(set(prior_children) | set(observed_children)):
                if child_key in observed_children:
                    child_prior_stats = calibration_stats(prior_children.get(child_key)) or symbol_prior_stats
                    merged_children[str(child_key)] = merge_bucket_node(
                        observed_node=observed_children[child_key],
                        prior_node=prior_children.get(child_key),
                        fallback_prior_stats=child_prior_stats,
                        prior_weight=prior_weight,
                    )
                else:
                    merged_children[str(child_key)] = copy.deepcopy(prior_children[child_key])
            if merged_children:
                observed_symbol[key] = merged_children

        observed_spreads = observed_symbol.get("spreads", {}) if isinstance(observed_symbol.get("spreads"), dict) else {}
        prior_spreads = prior_symbol.get("spreads", {}) if isinstance(prior_symbol.get("spreads"), dict) else {}
        merged_spreads: Dict[str, object] = {}
        for spread_key in sorted(set(prior_spreads) | set(observed_spreads), key=lambda item: int(item)):
            if spread_key in observed_spreads:
                spread_prior_stats = calibration_stats(prior_spreads.get(spread_key)) or symbol_prior_stats
                merged_spreads[str(spread_key)] = merge_bucket_node(
                    observed_node=observed_spreads[spread_key],
                    prior_node=prior_spreads.get(spread_key),
                    fallback_prior_stats=spread_prior_stats,
                    prior_weight=prior_weight,
                )
            else:
                merged_spreads[str(spread_key)] = copy.deepcopy(prior_spreads[spread_key])
        observed_symbol["spreads"] = merged_spreads

        merged["inside_spread"][str(symbol)] = observed_symbol

    return merged


def resolve_bundle_paths(bundle_dir: Path) -> Tuple[Path, Path]:
    bundle_dir = bundle_dir.expanduser().resolve()
    logs = sorted(bundle_dir.glob("*.log"))
    strategies = sorted(bundle_dir.glob("*.py"))
    if len(logs) != 1 or len(strategies) != 1:
        raise FileNotFoundError(
            f"Bundle dir {bundle_dir} must contain exactly one .log and one .py file "
            f"(found {len(logs)} logs, {len(strategies)} strategies)"
        )
    return logs[0], strategies[0]


def resolve_input_pairs(
    bundle_dirs: Sequence[Path],
    official_logs: Sequence[Path],
    strategies: Sequence[Path],
) -> List[Tuple[Path, Path]]:
    pairs: List[Tuple[Path, Path]] = []

    for bundle_dir in bundle_dirs:
        pairs.append(resolve_bundle_paths(bundle_dir))

    if official_logs or strategies:
        if len(official_logs) != len(strategies):
            raise ValueError("--official-log and --strategy must be provided the same number of times.")
        pairs.extend(
            (official_log.expanduser().resolve(), strategy.expanduser().resolve())
            for official_log, strategy in zip(official_logs, strategies)
        )

    if not pairs:
        raise ValueError("Provide at least one --bundle-dir or one matching --official-log/--strategy pair.")
    return pairs


def collect_inside_spread_rows(official_log: Path, strategy_path: Path) -> List[Dict[str, object]]:
    dataset = load_run_log(official_log)
    trader_class = load_strategy_class(strategy_path)
    trader = trader_class()

    prices = dataset.prices.sort_values(["day", "timestamp", "product"]).reset_index(drop=True)
    trades = dataset.trades.sort_values(["day", "timestamp", "symbol"]).reset_index(drop=True)
    symbols = sorted(prices["product"].unique().tolist())

    rows: List[Dict[str, object]] = []

    for day in sorted(prices["day"].unique().tolist()):
        day_prices = prices[prices["day"] == day]
        day_trades = trades[trades["day"] == day]
        timestamps = sorted(day_prices["timestamp"].unique().tolist())

        trader_data = ""
        positions = {symbol: 0 for symbol in symbols}
        own_trades_for_state = {symbol: [] for symbol in symbols}

        for timestamp in timestamps:
            tick_rows = day_prices[day_prices["timestamp"] == timestamp]
            current_market_trades = day_trades[
                (day_trades["timestamp"] == timestamp)
                & (day_trades["buyer"].astype(str) == "")
                & (day_trades["seller"].astype(str) == "")
            ]

            market_trade_dict = {symbol: [] for symbol in symbols}
            for trade_row in current_market_trades.itertuples(index=False):
                market_trade_dict[str(trade_row.symbol)].append(
                    Trade(
                        symbol=str(trade_row.symbol),
                        price=int(trade_row.price),
                        quantity=int(trade_row.quantity),
                        buyer="",
                        seller="",
                        timestamp=int(trade_row.timestamp),
                    )
                )

            state = build_state(
                tick_rows=tick_rows,
                timestamp=int(timestamp),
                trader_data=trader_data,
                positions=positions,
                own_trades=own_trades_for_state,
                market_trades=market_trade_dict,
            )
            response = trader.run(state)
            orders_by_symbol, _conversions, trader_data = normalize_strategy_response(response)

            official_tick = day_trades[
                (day_trades["timestamp"] == timestamp)
                & (
                    (day_trades["buyer"].astype(str) == "SUBMISSION")
                    | (day_trades["seller"].astype(str) == "SUBMISSION")
                )
            ]

            next_own_trades = {symbol: [] for symbol in symbols}
            for trade_row in official_tick.itertuples(index=False):
                signed_qty = int(trade_row.quantity) if trade_row.buyer == "SUBMISSION" else -int(trade_row.quantity)
                positions[str(trade_row.symbol)] += signed_qty
                next_own_trades[str(trade_row.symbol)].append(
                    Trade(
                        symbol=str(trade_row.symbol),
                        price=int(trade_row.price),
                        quantity=int(trade_row.quantity),
                        buyer=str(trade_row.buyer),
                        seller=str(trade_row.seller),
                        timestamp=int(trade_row.timestamp),
                    )
                )
            own_trades_for_state = next_own_trades

            for symbol in symbols:
                symbol_rows = tick_rows[tick_rows["product"] == symbol]
                if symbol_rows.empty:
                    continue
                row = symbol_rows.iloc[0]
                best_bid = row.get("bid_price_1")
                best_ask = row.get("ask_price_1")
                if pd.isna(best_bid) or pd.isna(best_ask):
                    continue

                best_bid = int(best_bid)
                best_ask = int(best_ask)
                spread = int(best_ask - best_bid)

                for order in orders_by_symbol.get(symbol, []) or []:
                    side = "buy" if int(order.quantity) > 0 else "sell"
                    order_price = int(order.price)
                    order_qty = abs(int(order.quantity))
                    if not (best_bid < order_price < best_ask):
                        continue

                    distance_ticks = inside_spread_distance_ticks(side, order_price, best_bid, best_ask)
                    fill_match = official_tick[
                        (official_tick["symbol"] == symbol)
                        & (
                            (
                                (official_tick["buyer"].astype(str) == "SUBMISSION")
                                & (side == "buy")
                            )
                            | (
                                (official_tick["seller"].astype(str) == "SUBMISSION")
                                & (side == "sell")
                            )
                        )
                        & (official_tick["price"].astype(int) == order_price)
                    ]
                    filled_qty = int(fill_match["quantity"].sum()) if not fill_match.empty else 0

                    rows.append(
                        {
                            "official_log": str(official_log),
                            "strategy": str(strategy_path),
                            "symbol": symbol,
                            "side": side,
                            "spread": spread,
                            "distance_ticks": distance_ticks,
                            "order_qty": order_qty,
                            "size_bucket": inside_spread_size_bucket(order_qty),
                            "filled_qty": filled_qty,
                        }
                    )

    return rows


def calibrate_inside_spread(pairs: Iterable[Tuple[Path, Path]]) -> Dict[str, object]:
    pairs = list(pairs)
    all_rows: List[Dict[str, object]] = []
    inputs: List[Dict[str, str]] = []

    for official_log, strategy_path in pairs:
        all_rows.extend(collect_inside_spread_rows(official_log, strategy_path))
        inputs.append(
            {
                "official_log": str(official_log),
                "strategy": str(strategy_path),
            }
        )

    frame = pd.DataFrame(all_rows)
    if frame.empty:
        return {"inputs": inputs, "inside_spread": {}}

    inside_spread: Dict[str, object] = {}
    for symbol, symbol_frame in frame.groupby("symbol"):
        inside_spread[str(symbol)] = build_symbol_calibration(symbol_frame)

    return {
        "inputs": inputs,
        "inside_spread": inside_spread,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calibrate an inside-spread passive fill profile from one or more official bundles."
    )
    parser.add_argument("--bundle-dir", type=Path, action="append", default=[])
    parser.add_argument("--official-log", type=Path, action="append", default=[])
    parser.add_argument("--strategy", type=Path, action="append", default=[])
    parser.add_argument(
        "--prior-calibration",
        type=Path,
        default=None,
        help="Optional baseline calibration JSON to blend against instead of using raw observed rates directly.",
    )
    parser.add_argument(
        "--prior-weight",
        type=float,
        default=0.0,
        help="Pseudo-order weight for --prior-calibration blending. Larger values preserve more of the prior profile.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    calibration = calibrate_inside_spread(
        resolve_input_pairs(
            bundle_dirs=args.bundle_dir,
            official_logs=args.official_log,
            strategies=args.strategy,
        )
    )
    if args.prior_calibration is not None:
        prior_path = args.prior_calibration.expanduser().resolve()
        prior_calibration = json.loads(prior_path.read_text())
        calibration = merge_prior_calibration(
            observed_calibration=calibration,
            prior_calibration=prior_calibration,
            prior_weight=float(args.prior_weight),
            prior_path=prior_path,
        )
    else:
        calibration["metadata"] = {"prior_weight": 0.0}
    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(calibration, indent=2, sort_keys=True) + "\n")
    print(json.dumps(calibration, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
