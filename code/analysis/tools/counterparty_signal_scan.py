from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import List, Sequence

import numpy as np
import pandas as pd

from visualizer import align_trades_to_book, discover_files, load_prices, load_trades


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan named-counterparty flow for informed-trader style signals.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Directory containing prices_round_*_day_*.csv and trades_round_*_day_*.csv.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional markdown output path. Defaults to <data-dir>/../counterparty_signal_report.md.",
    )
    parser.add_argument("--horizons", nargs="*", type=int, default=[1, 5, 10], help="Forward book horizons.")
    parser.add_argument("--min-events", type=int, default=8, help="Minimum events before reporting a trader/symbol pair.")
    return parser.parse_args(argv)


def nonempty_counterparty_fraction(series: pd.Series) -> float:
    cleaned = series.fillna("").astype(str).str.strip()
    return float((cleaned != "").mean())


def trader_event_frame(aligned_trades: pd.DataFrame, horizons: Sequence[int]) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []

    buyer = aligned_trades["buyer"].fillna("").astype(str).str.strip()
    seller = aligned_trades["seller"].fillna("").astype(str).str.strip()

    buyer_events = aligned_trades[buyer != ""].copy()
    if not buyer_events.empty:
        buyer_events["trader"] = buyer[buyer != ""].to_numpy()
        buyer_events["direction"] = 1.0
        buyer_events["role"] = "buyer"
        rows.append(buyer_events)

    seller_events = aligned_trades[seller != ""].copy()
    if not seller_events.empty:
        seller_events["trader"] = seller[seller != ""].to_numpy()
        seller_events["direction"] = -1.0
        seller_events["role"] = "seller"
        rows.append(seller_events)

    if not rows:
        return pd.DataFrame()

    events = pd.concat(rows, ignore_index=True)
    for horizon in horizons:
        future_mid = pd.to_numeric(events.get(f"mid_plus_{horizon}"), errors="coerce")
        current_mid = pd.to_numeric(events.get("mid_price"), errors="coerce")
        events[f"ret_{horizon}"] = future_mid - current_mid
        events[f"signed_ret_{horizon}"] = events["direction"] * events[f"ret_{horizon}"]
    return events


def markdown_report(
    prices: pd.DataFrame,
    trades: pd.DataFrame,
    data_dir: Path,
    horizons: Sequence[int],
    min_events: int,
) -> str:
    lines: List[str] = []
    lines.append(f"# Counterparty Signal Report — `{data_dir}`")
    lines.append("")

    if trades.empty:
        lines.append("No trade files found.")
        return "\n".join(lines) + "\n"

    buyer_frac = nonempty_counterparty_fraction(trades.get("buyer", pd.Series(dtype=str)))
    seller_frac = nonempty_counterparty_fraction(trades.get("seller", pd.Series(dtype=str)))
    lines.append(f"- Non-empty buyer fraction: `{buyer_frac:.3f}`")
    lines.append(f"- Non-empty seller fraction: `{seller_frac:.3f}`")
    lines.append("")

    if max(buyer_frac, seller_frac) == 0.0:
        lines.append("No named counterparties are visible in this dataset, so insider/copy-trade scans are not meaningful yet.")
        return "\n".join(lines) + "\n"

    aligned = align_trades_to_book(trades.sort_values(["symbol", "day", "timestamp"]), prices, horizons)
    events = trader_event_frame(aligned, horizons)
    if events.empty:
        lines.append("Trades aligned successfully, but no named counterparties were available after cleaning.")
        return "\n".join(lines) + "\n"

    lines.append(
        "Scores below are event studies: after a named trader buys we treat positive future returns as evidence of informed flow; after a named trader sells we flip the sign."
    )
    lines.append("")

    for symbol in sorted(events["symbol"].unique()):
        subset = events[events["symbol"] == symbol].copy()
        summary = (
            subset.groupby("trader")
            .agg(
                events=("trader", "size"),
                buys=("direction", lambda values: int((values > 0).sum())),
                sells=("direction", lambda values: int((values < 0).sum())),
                avg_qty=("quantity", "mean"),
            )
            .reset_index()
        )
        for horizon in horizons:
            grouped = subset.groupby("trader")[f"signed_ret_{horizon}"]
            summary[f"edge_{horizon}"] = grouped.mean().to_numpy()
            summary[f"hit_{horizon}"] = grouped.apply(lambda values: float((values > 0).mean())).to_numpy()
        summary = summary[summary["events"] >= min_events].sort_values(
            by=[f"edge_{horizons[-1]}", "events"], ascending=[False, False]
        )

        lines.append(f"## `{symbol}`")
        lines.append("")
        if summary.empty:
            lines.append(f"- No traders met the `min_events={min_events}` threshold.")
            lines.append("")
            continue

        lines.append("| Trader | Events | Buys | Sells | Avg Qty | " + " | ".join([f"Edge {h}" for h in horizons]) + " | " + " | ".join([f"Hit {h}" for h in horizons]) + " |")
        lines.append("| --- | ---: | ---: | ---: | ---: | " + " | ".join(["---:" for _ in horizons]) + " | " + " | ".join(["---:" for _ in horizons]) + " |")
        for row in summary.head(12).itertuples(index=False):
            edge_cells = " | ".join([f"`{getattr(row, f'edge_{h}'):+.3f}`" for h in horizons])
            hit_cells = " | ".join([f"`{getattr(row, f'hit_{h}'):.3f}`" for h in horizons])
            lines.append(
                f"| `{row.trader}` | `{row.events}` | `{row.buys}` | `{row.sells}` | `{row.avg_qty:.2f}` | {edge_cells} | {hit_cells} |"
            )
        lines.append("")

        raw_subset = aligned[aligned["symbol"] == symbol].copy()
        raw_subset["buyer"] = raw_subset["buyer"].fillna("").astype(str).str.strip()
        raw_subset["seller"] = raw_subset["seller"].fillna("").astype(str).str.strip()
        raw_subset["_pair_ret"] = (
            pd.to_numeric(raw_subset.get(f"mid_plus_{horizons[-1]}"), errors="coerce")
            - pd.to_numeric(raw_subset.get("mid_price"), errors="coerce")
        )
        pair_summary = (
            raw_subset.groupby(["buyer", "seller"])
            .agg(
                events=("symbol", "size"),
                buyer_edge=("_pair_ret", "mean"),
                buyer_hit=("_pair_ret", lambda values: float((values > 0).mean())),
            )
            .reset_index()
        )
        pair_summary = pair_summary[(pair_summary["buyer"] != "") & (pair_summary["seller"] != "")]
        pair_summary = pair_summary[pair_summary["events"] >= min_events].sort_values(["buyer_edge", "events"], ascending=[False, False])
        if not pair_summary.empty:
            lines.append("### Buyer/Seller Pair Edges")
            lines.append("")
            for row in pair_summary.head(8).itertuples(index=False):
                lines.append(
                    f"- `{row.buyer} -> {row.seller}`: events=`{row.events}`, buyer-edge@{horizons[-1]}=`{row.buyer_edge:+.3f}`, buyer-hit@{horizons[-1]}=`{row.buyer_hit:.3f}`"
                )
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    price_files = discover_files(args.data_dir, "prices_")
    trade_files = discover_files(args.data_dir, "trades_")
    if not price_files:
        raise FileNotFoundError(f"No price files found under {args.data_dir}")

    prices = load_prices(price_files).sort_values(["symbol", "day", "timestamp"]).reset_index(drop=True)
    trades = load_trades(trade_files).sort_values(["symbol", "day", "timestamp"]).reset_index(drop=True)

    output_path = args.output or (args.data_dir.parent / "counterparty_signal_report.md")
    report = markdown_report(prices, trades, args.data_dir, args.horizons, args.min_events)
    output_path.write_text(report)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
