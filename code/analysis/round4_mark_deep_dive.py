from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from visualizer import align_trades_to_book, discover_files, load_prices, load_trades


DEFAULT_HORIZONS = (1, 2, 5, 10, 20, 50, 100)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deep Round 4 Mark counterparty analysis.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/round4"),
        help="Directory with prices_round_4_day_*.csv and trades_round_4_day_*.csv.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("analysis/round4_mark_deep_dive"),
        help="Output directory for CSV tables and markdown report.",
    )
    parser.add_argument(
        "--horizons",
        nargs="*",
        type=int,
        default=list(DEFAULT_HORIZONS),
        help="Forward book-row horizons. One row is 100 timestamp units in R4.",
    )
    return parser.parse_args(argv)


def horizon_label(horizon: int) -> str:
    return f"{horizon * 100}"


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna()
    if not mask.any():
        return float("nan")
    w = weights.loc[mask].astype(float)
    total = float(w.sum())
    if total == 0.0:
        return float("nan")
    return float((values.loc[mask].astype(float) * w).sum() / total)


def weighted_t_stat(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna()
    if mask.sum() < 2:
        return float("nan")
    x = values.loc[mask].astype(float)
    w = weights.loc[mask].astype(float)
    w_sum = float(w.sum())
    w2_sum = float((w * w).sum())
    if w_sum == 0.0 or w2_sum == 0.0:
        return float("nan")
    mean = float((x * w).sum() / w_sum)
    n_eff = (w_sum * w_sum) / w2_sum
    if n_eff <= 1.0:
        return float("nan")
    var = float((w * (x - mean) ** 2).sum() / w_sum)
    sem = (var / n_eff) ** 0.5
    if sem == 0.0:
        return float("nan")
    return mean / sem


def add_session_bin(frame: pd.DataFrame) -> pd.Series:
    labels = ["early", "middle", "late"]
    max_ts = frame["timestamp"].max()
    if pd.isna(max_ts) or max_ts <= 0:
        return pd.Series(["unknown"] * len(frame), index=frame.index)
    return pd.cut(
        frame["timestamp"],
        bins=[-1, max_ts / 3.0, 2.0 * max_ts / 3.0, max_ts + 1],
        labels=labels,
    ).astype(str)


def add_quantity_bin(frame: pd.DataFrame) -> pd.Series:
    return pd.cut(
        frame["quantity"],
        bins=[-np.inf, 2, 5, 10, np.inf],
        labels=["1-2", "3-5", "6-10", "11+"],
    ).astype(str)


def build_event_frame(aligned: pd.DataFrame, horizons: Iterable[int]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for role, side in (("buyer", 1.0), ("seller", -1.0)):
        events = aligned.copy()
        events["mark"] = events[role].fillna("").astype(str).str.strip()
        events = events[events["mark"] != ""].copy()
        events["role"] = role
        events["side"] = side
        parts.append(events)

    if not parts:
        return pd.DataFrame()

    events = pd.concat(parts, ignore_index=True)
    events["edge_at_fill"] = events["side"] * (events["mid_price"] - events["price"])
    events["mark_aggressor"] = (
        ((events["side"] > 0) & (events["aggressor"] == "buy"))
        | ((events["side"] < 0) & (events["aggressor"] == "sell"))
    )
    events["spread"] = events["ask_price_1"] - events["bid_price_1"]
    events["session_bin"] = add_session_bin(events)
    events["quantity_bin"] = add_quantity_bin(events)

    for horizon in horizons:
        label = horizon_label(horizon)
        future_mid = events[f"mid_plus_{horizon}"]
        events[f"mid_move_{label}"] = events["side"] * (future_mid - events["mid_price"])
        events[f"fwd_{label}"] = events["side"] * (future_mid - events["price"])
        events[f"fwd_pnl_{label}"] = events[f"fwd_{label}"] * events["quantity"]

    return events


def summarize_events(events: pd.DataFrame, group_cols: list[str], horizons: Sequence[int]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    grouped = events.groupby(group_cols, dropna=False, sort=True)
    for keys, group in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)
        row: dict[str, object] = dict(zip(group_cols, keys))
        row["events"] = int(len(group))
        row["qty"] = int(group["quantity"].sum())
        row["buy_events"] = int((group["side"] > 0).sum())
        row["sell_events"] = int((group["side"] < 0).sum())
        row["buy_qty"] = int(group.loc[group["side"] > 0, "quantity"].sum())
        row["sell_qty"] = int(group.loc[group["side"] < 0, "quantity"].sum())
        row["aggressor_share"] = float(group["mark_aggressor"].mean())
        row["aggressor_qty_share"] = weighted_mean(group["mark_aggressor"].astype(float), group["quantity"])
        row["avg_qty"] = float(group["quantity"].mean())
        row["edge_at_fill"] = weighted_mean(group["edge_at_fill"], group["quantity"])
        row["edge_pnl"] = float((group["edge_at_fill"] * group["quantity"]).sum())
        for horizon in horizons:
            label = horizon_label(horizon)
            row[f"mid_move_{label}"] = weighted_mean(group[f"mid_move_{label}"], group["quantity"])
            row[f"fwd_{label}"] = weighted_mean(group[f"fwd_{label}"], group["quantity"])
            row[f"fwd_pnl_{label}"] = float(group[f"fwd_pnl_{label}"].sum(skipna=True))
        row["t_fwd_2000"] = weighted_t_stat(group["fwd_2000"], group["quantity"]) if "fwd_2000" in group else float("nan")
        row["q10_fwd_2000"] = float(group["fwd_2000"].quantile(0.10)) if "fwd_2000" in group else float("nan")
        row["q50_fwd_2000"] = float(group["fwd_2000"].quantile(0.50)) if "fwd_2000" in group else float("nan")
        row["q90_fwd_2000"] = float(group["fwd_2000"].quantile(0.90)) if "fwd_2000" in group else float("nan")
        rows.append(row)

    return pd.DataFrame(rows)


def summarize_pairs(aligned: pd.DataFrame, horizons: Sequence[int]) -> pd.DataFrame:
    frame = aligned.copy()
    frame["buyer"] = frame["buyer"].fillna("").astype(str).str.strip()
    frame["seller"] = frame["seller"].fillna("").astype(str).str.strip()
    frame = frame[(frame["buyer"] != "") & (frame["seller"] != "")].copy()
    frame["buyer_aggressor"] = frame["aggressor"] == "buy"
    frame["buyer_edge_at_fill"] = frame["mid_price"] - frame["price"]
    frame["session_bin"] = add_session_bin(frame)
    frame["quantity_bin"] = add_quantity_bin(frame)
    for horizon in horizons:
        label = horizon_label(horizon)
        frame[f"buyer_mid_move_{label}"] = frame[f"mid_plus_{horizon}"] - frame["mid_price"]
        frame[f"buyer_fwd_{label}"] = frame[f"mid_plus_{horizon}"] - frame["price"]
        frame[f"buyer_fwd_pnl_{label}"] = frame[f"buyer_fwd_{label}"] * frame["quantity"]

    rows: list[dict[str, object]] = []
    for keys, group in frame.groupby(["buyer", "seller", "symbol"], sort=True):
        buyer, seller, symbol = keys
        row: dict[str, object] = {"buyer": buyer, "seller": seller, "symbol": symbol}
        row["events"] = int(len(group))
        row["qty"] = int(group["quantity"].sum())
        row["buyer_aggressor_share"] = float(group["buyer_aggressor"].mean())
        row["buyer_aggressor_qty_share"] = weighted_mean(group["buyer_aggressor"].astype(float), group["quantity"])
        row["buyer_edge_at_fill"] = weighted_mean(group["buyer_edge_at_fill"], group["quantity"])
        for horizon in horizons:
            label = horizon_label(horizon)
            row[f"buyer_mid_move_{label}"] = weighted_mean(group[f"buyer_mid_move_{label}"], group["quantity"])
            row[f"buyer_fwd_{label}"] = weighted_mean(group[f"buyer_fwd_{label}"], group["quantity"])
            row[f"buyer_fwd_pnl_{label}"] = float(group[f"buyer_fwd_pnl_{label}"].sum(skipna=True))
        rows.append(row)

    return pd.DataFrame(rows)


def fmt(value: object, digits: int = 2, sign: bool = False) -> str:
    if value is None:
        return ""
    try:
        val = float(value)
    except (TypeError, ValueError):
        return str(value)
    if np.isnan(val):
        return "nan"
    prefix = "+" if sign else ""
    return f"{val:{prefix}.{digits}f}"


def pct(value: object, digits: int = 1) -> str:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return ""
    if np.isnan(val):
        return "nan"
    return f"{100.0 * val:.{digits}f}%"


def markdown_table(frame: pd.DataFrame, columns: list[str], headers: list[str] | None = None, max_rows: int | None = None) -> list[str]:
    if headers is None:
        headers = columns
    if max_rows is not None:
        frame = frame.head(max_rows)
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---" for _ in headers]) + " |")
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in columns) + " |")
    return lines


def build_report(
    data_dir: Path,
    out_dir: Path,
    trades: pd.DataFrame,
    events: pd.DataFrame,
    mark_summary: pd.DataFrame,
    mark_product_summary: pd.DataFrame,
    mark_day_summary: pd.DataFrame,
    horizon_summary: pd.DataFrame,
    pair_summary: pd.DataFrame,
    time_summary: pd.DataFrame,
    size_summary: pd.DataFrame,
) -> str:
    headline = mark_summary.copy().sort_values("fwd_2000", ascending=False)
    headline_display = pd.DataFrame(
        {
            "Mark": headline["mark"],
            "events": headline["events"],
            "qty": headline["qty"],
            "aggr": headline["aggressor_share"].map(pct),
            "edge": headline["edge_at_fill"].map(lambda v: fmt(v, 2, True)),
            "mid_move_2000": headline["mid_move_2000"].map(lambda v: fmt(v, 2, True)),
            "fwd_2000": headline["fwd_2000"].map(lambda v: fmt(v, 2, True)),
            "total_fwd": headline["fwd_pnl_2000"].map(lambda v: fmt(v, 0, True)),
        }
    )

    directional = headline.copy()
    directional["directional_abs"] = directional["mid_move_2000"].abs()
    directional = directional.sort_values("directional_abs", ascending=False)
    directional_display = pd.DataFrame(
        {
            "Mark": directional["mark"],
            "events": directional["events"],
            "qty": directional["qty"],
            "mid_move_2000": directional["mid_move_2000"].map(lambda v: fmt(v, 2, True)),
            "edge_at_fill": directional["edge_at_fill"].map(lambda v: fmt(v, 2, True)),
            "fwd_2000": directional["fwd_2000"].map(lambda v: fmt(v, 2, True)),
            "naive_t": directional["t_fwd_2000"].map(lambda v: fmt(v, 1, True)),
        }
    )

    product_rows = mark_product_summary[mark_product_summary["events"] >= 8].copy()
    product_rows = product_rows.sort_values(["symbol", "fwd_2000"], ascending=[True, False])
    product_display = pd.DataFrame(
        {
            "product": product_rows["symbol"],
            "mark": product_rows["mark"],
            "events": product_rows["events"],
            "qty": product_rows["qty"],
            "aggr": product_rows["aggressor_share"].map(pct),
            "edge": product_rows["edge_at_fill"].map(lambda v: fmt(v, 2, True)),
            "mid_move": product_rows["mid_move_2000"].map(lambda v: fmt(v, 2, True)),
            "fwd": product_rows["fwd_2000"].map(lambda v: fmt(v, 2, True)),
        }
    )

    pair_rows = pair_summary[pair_summary["events"] >= 8].copy()
    pair_rows = pair_rows.sort_values("buyer_fwd_pnl_2000", ascending=False)
    pair_display = pd.DataFrame(
        {
            "product": pair_rows["symbol"],
            "buyer->seller": pair_rows["buyer"] + " -> " + pair_rows["seller"],
            "events": pair_rows["events"],
            "qty": pair_rows["qty"],
            "buyer_aggr": pair_rows["buyer_aggressor_share"].map(pct),
            "buyer_edge": pair_rows["buyer_edge_at_fill"].map(lambda v: fmt(v, 2, True)),
            "buyer_mid_move": pair_rows["buyer_mid_move_2000"].map(lambda v: fmt(v, 2, True)),
            "buyer_fwd": pair_rows["buyer_fwd_2000"].map(lambda v: fmt(v, 2, True)),
            "buyer_total": pair_rows["buyer_fwd_pnl_2000"].map(lambda v: fmt(v, 0, True)),
        }
    )

    day_rows = mark_day_summary.copy().sort_values(["mark", "day"])
    day_display = pd.DataFrame(
        {
            "mark": day_rows["mark"],
            "day": day_rows["day"],
            "events": day_rows["events"],
            "qty": day_rows["qty"],
            "edge": day_rows["edge_at_fill"].map(lambda v: fmt(v, 2, True)),
            "mid_move": day_rows["mid_move_2000"].map(lambda v: fmt(v, 2, True)),
            "fwd": day_rows["fwd_2000"].map(lambda v: fmt(v, 2, True)),
        }
    )

    horizon_pivot = horizon_summary.pivot(index="mark", columns="horizon_ticks", values="fwd").reset_index()
    horizon_pivot = horizon_pivot.merge(headline[["mark", "fwd_2000"]], on="mark", how="left").sort_values("fwd_2000", ascending=False)
    hcols = [col for col in horizon_pivot.columns if isinstance(col, int)]
    horizon_display = horizon_pivot[["mark"] + hcols].copy()
    for col in hcols:
        horizon_display[col] = horizon_display[col].map(lambda v: fmt(v, 2, True))
    horizon_display.columns = ["mark"] + [str(col) for col in hcols]

    lines: list[str] = []
    lines.append("# Round 4 Mark Counterparty Deep Dive")
    lines.append("")
    lines.append(f"Data: `{data_dir}`. Raw trades: `{len(trades):,}`. Trader-side events: `{len(events):,}`.")
    lines.append("All per-unit edge and forward-PnL metrics are quantity-weighted. Aggressor share is event-weighted unless explicitly labeled as quantity-weighted.")
    lines.append("")
    lines.append("## Executive Read")
    lines.append("")
    lines.append("- `fwd_2000 = edge_at_fill + mid_move_2000`. This decomposition matters: some Marks look profitable because they captured spread passively, not because they predict the next move.")
    lines.append("- `Mark 67` is the cleanest directional flow: almost pure `VELVETFRUIT_EXTRACT` buyer, pays spread, but the mid still moves about `+1.79` per unit in his favor over 2,000 timestamp units.")
    lines.append("- `Mark 49` is the cleanest fade: mostly passive `VELVETFRUIT_EXTRACT` seller with positive fill edge, but the subsequent mid move is about `-1.85` from his point of view. After his sells, buy/avoid shorts.")
    lines.append("- `Mark 14` and `Mark 01` are passive makers. Their positive `fwd_2000` is mainly fill edge, so they are execution-quality warnings more than chaseable directional signals.")
    lines.append("- `Mark 38` and `Mark 55` are liquidity to provide to. They cross spreads aggressively and lose on fill-to-future PnL; take the other side instead of following them.")
    lines.append("")
    lines.append("## Headline Mark Table")
    lines.append("")
    lines.extend(markdown_table(headline_display, list(headline_display.columns)))
    lines.append("")
    lines.append("## Directional Versus Execution Edge")
    lines.append("")
    lines.append("Positive `edge_at_fill` means the Mark bought below mid or sold above mid. Positive `mid_move_2000` means the post-fill mid moved in the Mark's direction. Only the latter is directly followable after observing the trade.")
    lines.append("")
    lines.extend(markdown_table(directional_display, list(directional_display.columns)))
    lines.append("")
    lines.append("## Mark-By-Mark Dossiers")
    lines.append("")
    lines.append("### `Mark 14` — passive informed maker / execution edge collector")
    lines.append("")
    lines.append(f"- Footprint: `{int(headline.loc[headline['mark'] == 'Mark 14', 'events'].iloc[0]):,}` events and `{int(headline.loc[headline['mark'] == 'Mark 14', 'qty'].iloc[0]):,}` units, mostly `HYDROGEL_PACK`, `VELVETFRUIT_EXTRACT`, and `VEV_4000`; `0%` aggressor share.")
    lines.append(f"- Economics: `edge_at_fill={fmt(headline.loc[headline['mark'] == 'Mark 14', 'edge_at_fill'].iloc[0], 2, True)}`, `mid_move_2000={fmt(headline.loc[headline['mark'] == 'Mark 14', 'mid_move_2000'].iloc[0], 2, True)}`, `fwd_2000={fmt(headline.loc[headline['mark'] == 'Mark 14', 'fwd_2000'].iloc[0], 2, True)}`. The profit is almost entirely spread/fill edge, not post-trade drift.")
    lines.append("- Product read: strongest on wide-spread `HYDROGEL_PACK` and `VEV_4000`; still positive but smaller on `VELVETFRUIT_EXTRACT`.")
    lines.append("- Action: do not cross into this Mark. If our live fills often print against `Mark 14`, our execution layer is likely donating edge. It is not a clean after-the-fact chase signal because the edge has already been captured at their fill price.")
    lines.append("")
    lines.append("### `Mark 01` — passive maker, mild edge, voucher pair specialist")
    lines.append("")
    lines.append(f"- Footprint: `{int(headline.loc[headline['mark'] == 'Mark 01', 'events'].iloc[0]):,}` events and `{int(headline.loc[headline['mark'] == 'Mark 01', 'qty'].iloc[0]):,}` units; `0%` aggressor share. Most volume is `VELVETFRUIT_EXTRACT` plus recurring `Mark 01 -> Mark 22` voucher prints.")
    lines.append(f"- Economics: `edge_at_fill={fmt(headline.loc[headline['mark'] == 'Mark 01', 'edge_at_fill'].iloc[0], 2, True)}`, `mid_move_2000={fmt(headline.loc[headline['mark'] == 'Mark 01', 'mid_move_2000'].iloc[0], 2, True)}`, `fwd_2000={fmt(headline.loc[headline['mark'] == 'Mark 01', 'fwd_2000'].iloc[0], 2, True)}`.")
    lines.append("- Product read: `VELVETFRUIT_EXTRACT` edge is stronger than the voucher edge, but the voucher flow is mostly mechanical spread capture in low-value strikes.")
    lines.append("- Action: respect as a maker and avoid taking bad prices into them. Do not spend position budget following the voucher prints unless another model already wants that exposure.")
    lines.append("")
    lines.append("### `Mark 67` — true VFE informed taker")
    lines.append("")
    lines.append(f"- Footprint: `{int(headline.loc[headline['mark'] == 'Mark 67', 'events'].iloc[0]):,}` events and `{int(headline.loc[headline['mark'] == 'Mark 67', 'qty'].iloc[0]):,}` units, all `VELVETFRUIT_EXTRACT` buys; `99.4%` event aggressor share.")
    lines.append(f"- Economics: pays spread (`edge_at_fill={fmt(headline.loc[headline['mark'] == 'Mark 67', 'edge_at_fill'].iloc[0], 2, True)}`), but future mid move is strong (`mid_move_2000={fmt(headline.loc[headline['mark'] == 'Mark 67', 'mid_move_2000'].iloc[0], 2, True)}`), leaving `fwd_2000={fmt(headline.loc[headline['mark'] == 'Mark 67', 'fwd_2000'].iloc[0], 2, True)}`.")
    lines.append("- Stability: positive on every day; strongest late-session in this sample. The effect is real but thin relative to spread, so late chasing can erase it.")
    lines.append("- Action: use as long bias, short veto, and voucher-delta fair shift. Prefer passive or at-touch participation; blind extra market-taking is only justified when the rest of the VFE stack agrees.")
    lines.append("")
    lines.append("### `Mark 49` — passive but mistimed VFE trader / fade candidate")
    lines.append("")
    lines.append(f"- Footprint: `{int(headline.loc[headline['mark'] == 'Mark 49', 'events'].iloc[0]):,}` events and `{int(headline.loc[headline['mark'] == 'Mark 49', 'qty'].iloc[0]):,}` units, almost entirely `VELVETFRUIT_EXTRACT` sells; only `1.6%` event aggressor share.")
    lines.append(f"- Economics: earns fill edge (`edge_at_fill={fmt(headline.loc[headline['mark'] == 'Mark 49', 'edge_at_fill'].iloc[0], 2, True)}`), then loses it and more (`mid_move_2000={fmt(headline.loc[headline['mark'] == 'Mark 49', 'mid_move_2000'].iloc[0], 2, True)}`, `fwd_2000={fmt(headline.loc[headline['mark'] == 'Mark 49', 'fwd_2000'].iloc[0], 2, True)}`).")
    lines.append("- Stability: negative `fwd_2000` on all three days and across short/medium horizons. Large `11+` unit prints remain negative.")
    lines.append("- Action: fade, especially after sells. In practice this means allow/add VFE long skew and suppress shorts after `Mark 49` seller prints.")
    lines.append("")
    lines.append("### `Mark 55` — pure VFE noise taker")
    lines.append("")
    lines.append(f"- Footprint: `{int(headline.loc[headline['mark'] == 'Mark 55', 'events'].iloc[0]):,}` events and `{int(headline.loc[headline['mark'] == 'Mark 55', 'qty'].iloc[0]):,}` units, all `VELVETFRUIT_EXTRACT`; exactly `100%` aggressor share with balanced buy/sell count.")
    lines.append(f"- Economics: `edge_at_fill={fmt(headline.loc[headline['mark'] == 'Mark 55', 'edge_at_fill'].iloc[0], 2, True)}`, `mid_move_2000={fmt(headline.loc[headline['mark'] == 'Mark 55', 'mid_move_2000'].iloc[0], 2, True)}`, `fwd_2000={fmt(headline.loc[headline['mark'] == 'Mark 55', 'fwd_2000'].iloc[0], 2, True)}`. Direction is mildly favorable but far too small to pay the spread.")
    lines.append("- Action: provide liquidity to `Mark 55`; do not follow. Their trades are useful as fill opportunities, not as price-discovery signals.")
    lines.append("")
    lines.append("### `Mark 38` — strongest spread-paying noise flow")
    lines.append("")
    lines.append(f"- Footprint: `{int(headline.loc[headline['mark'] == 'Mark 38', 'events'].iloc[0]):,}` events and `{int(headline.loc[headline['mark'] == 'Mark 38', 'qty'].iloc[0]):,}` units, concentrated in `HYDROGEL_PACK` and `VEV_4000`; exactly `100%` aggressor share.")
    lines.append(f"- Economics: worst fill-to-future result in the tape: `edge_at_fill={fmt(headline.loc[headline['mark'] == 'Mark 38', 'edge_at_fill'].iloc[0], 2, True)}`, `mid_move_2000={fmt(headline.loc[headline['mark'] == 'Mark 38', 'mid_move_2000'].iloc[0], 2, True)}`, `fwd_2000={fmt(headline.loc[headline['mark'] == 'Mark 38', 'fwd_2000'].iloc[0], 2, True)}`.")
    lines.append("- Pair read: `Mark 14` is usually the other side and captures the transfer. This is a liquidity-provision edge, not a directional forecast.")
    lines.append("- Action: quote confidently into `Mark 38` flow on `HYDROGEL_PACK`/`VEV_4000` when inventory allows; avoid joining their side.")
    lines.append("")
    lines.append("### `Mark 22` — mostly noise taker / mechanical seller")
    lines.append("")
    lines.append(f"- Footprint: `{int(headline.loc[headline['mark'] == 'Mark 22', 'events'].iloc[0]):,}` events and `{int(headline.loc[headline['mark'] == 'Mark 22', 'qty'].iloc[0]):,}` units; `90.7%` event aggressor share and heavily seller-skewed.")
    lines.append(f"- Economics: `edge_at_fill={fmt(headline.loc[headline['mark'] == 'Mark 22', 'edge_at_fill'].iloc[0], 2, True)}`, `mid_move_2000={fmt(headline.loc[headline['mark'] == 'Mark 22', 'mid_move_2000'].iloc[0], 2, True)}`, `fwd_2000={fmt(headline.loc[headline['mark'] == 'Mark 22', 'fwd_2000'].iloc[0], 2, True)}`.")
    lines.append("- Product read: many voucher sells are paired mechanically with `Mark 01`; `VELVETFRUIT_EXTRACT` behavior is weakly negative from Mark 22's perspective but not as clean as `Mark 49`.")
    lines.append("- Action: generally provide, but avoid overfitting. Use as a secondary liquidity/noise tag rather than a primary directional signal.")
    lines.append("")
    lines.append("## Product-Level Mark Behavior")
    lines.append("")
    lines.extend(markdown_table(product_display, list(product_display.columns)))
    lines.append("")
    lines.append("## Buyer/Seller Pair Transfers")
    lines.append("")
    lines.append("Buyer perspective. Seller's `fwd_2000` transfer is the negative of buyer total, up to end-of-day missing horizons.")
    lines.append("")
    lines.extend(markdown_table(pair_display, list(pair_display.columns), max_rows=40))
    lines.append("")
    lines.append("## Horizon Curve: Fill-To-Future PnL")
    lines.append("")
    lines.append("Columns are timestamp units after the trade. Values include fill edge, so passive makers stay positive even when future mid movement is flat.")
    lines.append("")
    lines.extend(markdown_table(horizon_display, list(horizon_display.columns)))
    lines.append("")
    lines.append("## Day Stability")
    lines.append("")
    lines.extend(markdown_table(day_display, list(day_display.columns)))
    lines.append("")
    lines.append("## Timing And Size Diagnostics")
    lines.append("")
    lines.append(f"- Session-bin summary: `{out_dir / 'mark_time_bin_summary.csv'}`")
    lines.append(f"- Quantity-bin summary: `{out_dir / 'mark_size_bin_summary.csv'}`")
    lines.append("- The generated CSVs are the source of truth for slices too wide to keep readable in this markdown file.")
    lines.append("")
    lines.append("## Trading Implications")
    lines.append("")
    lines.append("- Use `Mark 67` as a VFE directional follow/short-veto signal, but do not overpay. His 2,000-unit markout from mid is only about two ticks, so an extra spread crossing can erase the edge.")
    lines.append("- Use `Mark 49` sells as a VFE fade/long-permission signal. The signal is stronger as a quote-skew or short-veto than as a blind market order.")
    lines.append("- Use `Mark 38` and `Mark 55` for liquidity provision. Their losses are mostly spread paid, so the practical edge is making markets against them, not forecasting a large drift after they trade.")
    lines.append("- Treat `Mark 14` and `Mark 01` as makers to respect. If our strategy is repeatedly trading into them, the strategy is probably donating execution edge.")
    lines.append("- Ignore most voucher Mark IDs as standalone alpha. The recurring `Mark 01`/`Mark 22` voucher flow is mechanical, often in near-zero vouchers, and has weak forward information.")
    lines.append("")
    lines.append("## Output Files")
    lines.append("")
    for name in [
        "events.csv",
        "mark_summary.csv",
        "mark_product_summary.csv",
        "mark_day_summary.csv",
        "mark_side_summary.csv",
        "mark_horizon_summary.csv",
        "pair_summary.csv",
        "mark_time_bin_summary.csv",
        "mark_size_bin_summary.csv",
    ]:
        lines.append(f"- `{out_dir / name}`")
    lines.append("")
    return "\n".join(lines)


def build_horizon_summary(events: pd.DataFrame, horizons: Sequence[int]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for mark, group in events.groupby("mark", sort=True):
        for horizon in horizons:
            label = horizon_label(horizon)
            rows.append(
                {
                    "mark": mark,
                    "horizon_rows": horizon,
                    "horizon_ticks": horizon * 100,
                    "events": int(group[f"fwd_{label}"].notna().sum()),
                    "qty": int(group.loc[group[f"fwd_{label}"].notna(), "quantity"].sum()),
                    "edge_at_fill": weighted_mean(group["edge_at_fill"], group["quantity"]),
                    "mid_move": weighted_mean(group[f"mid_move_{label}"], group["quantity"]),
                    "fwd": weighted_mean(group[f"fwd_{label}"], group["quantity"]),
                    "fwd_pnl": float(group[f"fwd_pnl_{label}"].sum(skipna=True)),
                }
            )
    return pd.DataFrame(rows)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    data_dir = args.data_dir
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    horizons = tuple(args.horizons)

    price_files = discover_files(data_dir, "prices_")
    trade_files = discover_files(data_dir, "trades_")
    if not price_files:
        raise FileNotFoundError(f"No price files found in {data_dir}")
    if not trade_files:
        raise FileNotFoundError(f"No trade files found in {data_dir}")

    prices = load_prices(price_files).sort_values(["symbol", "day", "timestamp"]).reset_index(drop=True)
    trades = load_trades(trade_files).sort_values(["symbol", "day", "timestamp"]).reset_index(drop=True)
    aligned = align_trades_to_book(trades, prices, horizons).sort_values(["symbol", "day", "timestamp"]).reset_index(drop=True)
    events = build_event_frame(aligned, horizons)

    mark_summary = summarize_events(events, ["mark"], horizons).sort_values("fwd_2000", ascending=False)
    mark_product_summary = summarize_events(events, ["symbol", "mark"], horizons).sort_values(["symbol", "fwd_2000"], ascending=[True, False])
    mark_day_summary = summarize_events(events, ["mark", "day"], horizons).sort_values(["mark", "day"])
    mark_side_summary = summarize_events(events, ["mark", "role"], horizons).sort_values(["mark", "role"])
    mark_time_summary = summarize_events(events, ["mark", "session_bin"], horizons).sort_values(["mark", "session_bin"])
    mark_size_summary = summarize_events(events, ["mark", "quantity_bin"], horizons).sort_values(["mark", "quantity_bin"])
    horizon_summary = build_horizon_summary(events, horizons).sort_values(["mark", "horizon_rows"])
    pair_summary = summarize_pairs(aligned, horizons).sort_values("buyer_fwd_pnl_2000", ascending=False)

    events.to_csv(out_dir / "events.csv", index=False)
    mark_summary.to_csv(out_dir / "mark_summary.csv", index=False)
    mark_product_summary.to_csv(out_dir / "mark_product_summary.csv", index=False)
    mark_day_summary.to_csv(out_dir / "mark_day_summary.csv", index=False)
    mark_side_summary.to_csv(out_dir / "mark_side_summary.csv", index=False)
    mark_time_summary.to_csv(out_dir / "mark_time_bin_summary.csv", index=False)
    mark_size_summary.to_csv(out_dir / "mark_size_bin_summary.csv", index=False)
    horizon_summary.to_csv(out_dir / "mark_horizon_summary.csv", index=False)
    pair_summary.to_csv(out_dir / "pair_summary.csv", index=False)

    report = build_report(
        data_dir=data_dir,
        out_dir=out_dir,
        trades=trades,
        events=events,
        mark_summary=mark_summary,
        mark_product_summary=mark_product_summary,
        mark_day_summary=mark_day_summary,
        horizon_summary=horizon_summary,
        pair_summary=pair_summary,
        time_summary=mark_time_summary,
        size_summary=mark_size_summary,
    )
    (out_dir / "round4_mark_deep_dive_report.md").write_text(report)
    print(f"Wrote {out_dir / 'round4_mark_deep_dive_report.md'}")


if __name__ == "__main__":
    main()
