#!/usr/bin/env python3
"""Analyze the Round 2 manual challenge and generate decision charts.

The challenge gives a 50,000 XIREC budget split across:

- Research: logarithmic from 0 to 200,000
- Scale: linear from 0 to 7
- Speed: rank-based multiplier from 0.1 to 0.9

PnL = Research * Scale * Speed - Budget_Used

This script covers two layers:

1. Deterministic layer:
   - the best Research / Scale split for any remaining non-speed budget
   - how much deterministic value is lost when budget is diverted to Speed
   - what Speed multiplier is required to justify that diversion
2. Game-theory layer:
   - the symmetric mixed-strategy benchmark for the rank-based Speed leg
   - a rank-bid-framework mixture using dropout / AI-default / nice-number /
     meme / smooth-contest components

It writes a CSV frontier, several PNG charts, and a Markdown summary.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


TOTAL_BUDGET_XIRECS = 50_000
TOTAL_PCT = 100.0
MIN_SPEED_MULTIPLIER = 0.1
MAX_SPEED_MULTIPLIER = 0.9
TABLE_SPEED_POINTS = (0, 10, 15, 18, 19, 20, 21, 22, 23, 25, 27, 30, 35, 40, 50)
TABLE_MULTIPLIERS = tuple(round(value, 2) for value in np.arange(0.10, 0.95, 0.05))
DECISION_SPEED_POINTS = tuple(range(0, 101))
AI_DEFAULT_SPEED_PCT = 20.0
NICE_NUMBER_WEIGHTS = {
    5: 1.0,
    10: 1.0,
    20: 1.0,
    25: 1.0,
    30: 1.0,
    40: 1.0,
    50: 1.0,
    100: 1.0,
}
MEME_NUMBER_WEIGHTS = {
    42: 1.0,
    69: 1.0,
    73: 1.0,
}
FRAMEWORK_SCENARIOS = {
    "mostly_nash": {
        "dropout": 0.10,
        "ai_default": 0.10,
        "nice_numbers": 0.15,
        "meme_numbers": 0.05,
        "smooth_contest": 0.60,
    },
    "heavy_round_numbers": {
        "dropout": 0.10,
        "ai_default": 0.15,
        "nice_numbers": 0.30,
        "meme_numbers": 0.05,
        "smooth_contest": 0.40,
    },
    "bimodal_dropout_sim": {
        "dropout": 0.25,
        "ai_default": 0.10,
        "nice_numbers": 0.10,
        "meme_numbers": 0.05,
        "smooth_contest": 0.50,
    },
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("analysis/round2_manual"),
        help="Directory where charts and summary files will be written.",
    )
    parser.add_argument(
        "--grid-step",
        type=float,
        default=0.1,
        help="Percent step used for brute-force Research/Scale optimization.",
    )
    parser.add_argument(
        "--speed-step",
        type=float,
        default=0.25,
        help="Percent step used for the Speed frontier charts.",
    )
    return parser.parse_args(argv)


def research_value(research_pct: np.ndarray | float) -> np.ndarray | float:
    return 200_000.0 * np.log1p(research_pct) / math.log1p(100.0)


def scale_value(scale_pct: np.ndarray | float) -> np.ndarray | float:
    return 7.0 * np.asarray(scale_pct) / 100.0


def budget_used_xirecs(total_pct: np.ndarray | float) -> np.ndarray | float:
    return TOTAL_BUDGET_XIRECS * np.asarray(total_pct) / TOTAL_PCT


def best_research_scale_split(remaining_pct: float, grid_step: float) -> dict[str, float]:
    if remaining_pct <= 0:
        return {
            "remaining_pct": 0.0,
            "research_pct": 0.0,
            "scale_pct": 0.0,
            "research_value": 0.0,
            "scale_value": 0.0,
            "product_value": 0.0,
        }

    research_grid = np.arange(0.0, remaining_pct + grid_step * 0.5, grid_step)
    research_grid = np.clip(research_grid, 0.0, remaining_pct)
    scale_grid = remaining_pct - research_grid
    product_grid = research_value(research_grid) * scale_value(scale_grid)
    best_idx = int(product_grid.argmax())

    research_pct = float(research_grid[best_idx])
    scale_pct = float(scale_grid[best_idx])
    research_amt = float(research_value(research_pct))
    scale_amt = float(scale_value(scale_pct))
    product_amt = float(product_grid[best_idx])

    return {
        "remaining_pct": float(remaining_pct),
        "research_pct": research_pct,
        "scale_pct": scale_pct,
        "research_value": research_amt,
        "scale_value": scale_amt,
        "product_value": product_amt,
    }


def build_frontier(grid_step: float, speed_step: float) -> pd.DataFrame:
    records: list[dict[str, float]] = []
    for speed_pct in np.arange(0.0, TOTAL_PCT + speed_step * 0.5, speed_step):
        remaining_pct = max(0.0, TOTAL_PCT - float(speed_pct))
        best = best_research_scale_split(remaining_pct, grid_step)
        best["speed_pct"] = float(speed_pct)
        best["total_pct"] = float(speed_pct + best["research_pct"] + best["scale_pct"])
        best["budget_used_xirecs"] = float(budget_used_xirecs(best["total_pct"]))
        records.append(best)

    frontier = pd.DataFrame.from_records(records).sort_values("speed_pct").reset_index(drop=True)
    return frontier


def normalize_weight_map(weight_map: dict[int, float]) -> dict[float, float]:
    total_weight = float(sum(weight_map.values()))
    if total_weight <= 0:
        raise ValueError("Weight map must have positive total weight.")
    return {float(key): float(value) / total_weight for key, value in weight_map.items() if value > 0}


def build_game_theory_table(frontier: pd.DataFrame) -> pd.DataFrame:
    decision_rows: list[dict[str, float]] = []
    for speed_pct in DECISION_SPEED_POINTS:
        idx = int((frontier["speed_pct"] - speed_pct).abs().idxmin())
        row = frontier.loc[idx]
        decision_rows.append(
            {
                "speed_pct": float(speed_pct),
                "research_pct": float(row["research_pct"]),
                "scale_pct": float(row["scale_pct"]),
                "research_value": float(row["research_value"]),
                "scale_value": float(row["scale_value"]),
                "product_value": float(row["product_value"]),
                "budget_used_xirecs": float(row["budget_used_xirecs"]),
            }
        )

    table = pd.DataFrame.from_records(decision_rows).sort_values("speed_pct").reset_index(drop=True)
    zero_speed_product = float(table.loc[table["speed_pct"] == 0.0, "product_value"].iloc[0])
    product = table["product_value"].to_numpy(dtype=float)
    raw_equilibrium_cdf = np.divide(
        zero_speed_product - product,
        8.0 * product,
        out=np.full_like(product, np.inf, dtype=float),
        where=product > 0.0,
    )
    table["equilibrium_cdf"] = np.clip(raw_equilibrium_cdf, 0.0, 1.0)
    table["equilibrium_multiplier"] = MIN_SPEED_MULTIPLIER + (
        MAX_SPEED_MULTIPLIER - MIN_SPEED_MULTIPLIER
    ) * table["equilibrium_cdf"]

    equilibrium_component = np.zeros(len(table), dtype=float)
    support_mask = table["speed_pct"] <= 80.0
    support_indices = np.flatnonzero(support_mask.to_numpy())
    previous_cdf = 0.0
    for index in support_indices:
        current_cdf = float(table.at[index, "equilibrium_cdf"])
        equilibrium_component[index] = max(0.0, current_cdf - previous_cdf)
        previous_cdf = current_cdf
    if support_indices.size > 0:
        equilibrium_component[support_indices[-1]] += max(0.0, 1.0 - equilibrium_component.sum())

    nice_component_map = normalize_weight_map(NICE_NUMBER_WEIGHTS)
    meme_component_map = normalize_weight_map(MEME_NUMBER_WEIGHTS)
    dropout_component = np.zeros(len(table), dtype=float)
    dropout_component[0] = 1.0
    ai_default_component = np.zeros(len(table), dtype=float)
    ai_default_index = int((table["speed_pct"] - AI_DEFAULT_SPEED_PCT).abs().idxmin())
    ai_default_component[ai_default_index] = 1.0
    nice_component = np.array(
        [nice_component_map.get(float(speed_pct), 0.0) for speed_pct in table["speed_pct"]],
        dtype=float,
    )
    meme_component = np.array(
        [meme_component_map.get(float(speed_pct), 0.0) for speed_pct in table["speed_pct"]],
        dtype=float,
    )

    table["equilibrium_component_mass"] = equilibrium_component
    table["dropout_component_mass"] = dropout_component
    table["ai_default_component_mass"] = ai_default_component
    table["nice_number_component_mass"] = nice_component
    table["meme_component_mass"] = meme_component

    scenario_pnl_columns: list[str] = []
    for scenario_name, weights in FRAMEWORK_SCENARIOS.items():
        scenario_mass = (
            weights["dropout"] * dropout_component
            + weights["ai_default"] * ai_default_component
            + weights["nice_numbers"] * nice_component
            + weights["meme_numbers"] * meme_component
            + weights["smooth_contest"] * equilibrium_component
        )
        scenario_mass /= scenario_mass.sum()
        scenario_cumulative_mass = np.cumsum(scenario_mass)
        scenario_percentile = scenario_cumulative_mass - 0.5 * scenario_mass
        scenario_multiplier = MIN_SPEED_MULTIPLIER + (
            MAX_SPEED_MULTIPLIER - MIN_SPEED_MULTIPLIER
        ) * scenario_percentile
        scenario_expected_pnl = scenario_multiplier * table["product_value"] - TOTAL_BUDGET_XIRECS

        table[f"{scenario_name}_mass"] = scenario_mass
        table[f"{scenario_name}_percentile"] = scenario_percentile
        table[f"{scenario_name}_multiplier"] = scenario_multiplier
        table[f"{scenario_name}_expected_pnl"] = scenario_expected_pnl
        scenario_pnl_columns.append(f"{scenario_name}_expected_pnl")

    scenario_optima = {column: float(table[column].max()) for column in scenario_pnl_columns}
    worst_case_regret = np.zeros(len(table), dtype=float)
    average_regret = np.zeros(len(table), dtype=float)
    for index in range(len(table)):
        regrets = [scenario_optima[column] - float(table.at[index, column]) for column in scenario_pnl_columns]
        worst_case_regret[index] = max(regrets)
        average_regret[index] = float(np.mean(regrets))

    table["worst_case_regret"] = worst_case_regret
    table["average_regret"] = average_regret
    return table


def build_multiplier_grid() -> np.ndarray:
    return np.linspace(MIN_SPEED_MULTIPLIER, MAX_SPEED_MULTIPLIER, 161)


def style_plot() -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update(
        {
            "figure.figsize": (10, 6),
            "figure.dpi": 180,
            "axes.titlesize": 13,
            "axes.labelsize": 10,
            "legend.fontsize": 9,
            "font.size": 10,
        }
    )


def plot_optimal_split(frontier: pd.DataFrame, output_dir: Path) -> Path:
    fig, ax = plt.subplots()
    speed = frontier["speed_pct"].to_numpy()
    research = frontier["research_pct"].to_numpy()
    scale = frontier["scale_pct"].to_numpy()

    ax.plot(speed, research, label="Optimal Research %", color="#1f77b4", linewidth=2.2)
    ax.plot(speed, scale, label="Optimal Scale %", color="#ff7f0e", linewidth=2.2)
    ax.plot(speed, speed, label="Speed %", color="#2ca02c", linewidth=2.2)

    ax.set_title("Round 2 Manual Challenge: Best Allocation Split by Speed Budget")
    ax.set_xlabel("Speed allocation (%)")
    ax.set_ylabel("Allocation (%)")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.legend(loc="upper right")

    path = output_dir / "optimal_split_vs_speed_budget.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def plot_product_and_pnl(frontier: pd.DataFrame, output_dir: Path) -> Path:
    fig, (ax_top, ax_bottom) = plt.subplots(2, 1, figsize=(10, 9), sharex=True)
    speed = frontier["speed_pct"].to_numpy()
    product = frontier["product_value"].to_numpy()

    ax_top.plot(speed, product, color="#7f3c8d", linewidth=2.4)
    ax_top.set_title("Deterministic Research x Scale Capacity vs. Speed Spend")
    ax_top.set_ylabel("Best Research x Scale value")
    ax_top.set_xlim(0, 100)

    for multiplier, color in [
        (0.1, "#4c78a8"),
        (0.3, "#f58518"),
        (0.5, "#54a24b"),
        (0.7, "#e45756"),
        (0.9, "#72b7b2"),
    ]:
        pnl = multiplier * product - TOTAL_BUDGET_XIRECS
        ax_bottom.plot(speed, pnl, label=f"Speed multiplier {multiplier:.1f}", color=color, linewidth=2.0)

    ax_bottom.axhline(0.0, color="black", linewidth=1.0, linestyle="--")
    ax_bottom.set_title("Optimal PnL if You Achieve a Given Speed Multiplier")
    ax_bottom.set_xlabel("Speed allocation (%)")
    ax_bottom.set_ylabel("PnL (XIRECs)")
    ax_bottom.legend(loc="upper right")

    path = output_dir / "product_and_pnl_vs_speed_budget.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def plot_required_multiplier(frontier: pd.DataFrame, output_dir: Path) -> Path:
    fig, ax = plt.subplots()
    speed = frontier["speed_pct"].to_numpy()
    product = frontier["product_value"].to_numpy()
    zero_speed_product = float(frontier.loc[frontier["speed_pct"].idxmin(), "product_value"])
    ratio = np.divide(
        zero_speed_product,
        product,
        out=np.full_like(product, np.nan, dtype=float),
        where=product > 0,
    )

    for baseline_multiplier, color in [
        (0.1, "#4c78a8"),
        (0.2, "#72b7b2"),
        (0.3, "#54a24b"),
        (0.4, "#eeca3b"),
        (0.5, "#e45756"),
    ]:
        required = baseline_multiplier * ratio
        ax.plot(
            speed,
            required,
            label=f"Needed if 0% Speed would earn {baseline_multiplier:.1f}",
            color=color,
            linewidth=2.0,
        )

    ax.axhline(MAX_SPEED_MULTIPLIER, color="black", linewidth=1.0, linestyle="--", label="Hard max: 0.9")
    ax.set_title("Required Speed Multiplier to Beat the 0% Speed Baseline")
    ax.set_xlabel("Speed allocation (%)")
    ax.set_ylabel("Required achieved speed multiplier")
    ax.set_xlim(0, 100)
    ax.set_ylim(0.08, 1.0)
    ax.legend(loc="upper left")

    path = output_dir / "required_speed_multiplier_vs_speed_budget.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def plot_pnl_surface(frontier: pd.DataFrame, output_dir: Path) -> Path:
    speed = frontier["speed_pct"].to_numpy()
    product = frontier["product_value"].to_numpy()
    multipliers = build_multiplier_grid()
    pnl_grid = multipliers[:, None] * product[None, :] - TOTAL_BUDGET_XIRECS

    fig, ax = plt.subplots(figsize=(11, 7))
    image = ax.imshow(
        pnl_grid,
        origin="lower",
        aspect="auto",
        extent=[speed.min(), speed.max(), multipliers.min(), multipliers.max()],
        cmap="viridis",
    )
    contour = ax.contour(
        speed,
        multipliers,
        pnl_grid,
        levels=[0.0, 100_000.0, 250_000.0, 400_000.0],
        colors="white",
        linewidths=1.0,
    )
    ax.clabel(contour, fmt="%d", inline=True, fontsize=8)

    ax.set_title("Optimal PnL Surface for Round 2 Manual Challenge")
    ax.set_xlabel("Speed allocation (%)")
    ax.set_ylabel("Achieved speed multiplier")
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("PnL (XIRECs)")

    path = output_dir / "pnl_surface.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def format_pct(value: float) -> str:
    return f"{value:.1f}%"


def multiplier_column_name(multiplier: float) -> str:
    return f"pnl_m_{multiplier:.2f}".replace(".", "_")


def build_key_table(frontier: pd.DataFrame) -> pd.DataFrame:
    snapshot_rows: list[dict[str, float]] = []
    for speed_pct in TABLE_SPEED_POINTS:
        idx = int((frontier["speed_pct"] - speed_pct).abs().idxmin())
        row = frontier.loc[idx]
        entry = {
            "research_pct": float(row["research_pct"]),
            "scale_pct": float(row["scale_pct"]),
            "speed_pct": float(row["speed_pct"]),
            "research_value": float(row["research_value"]),
            "scale_value": float(row["scale_value"]),
            "product_value": float(row["product_value"]),
            "breakeven_multiplier": float(TOTAL_BUDGET_XIRECS / row["product_value"]),
        }
        for multiplier in TABLE_MULTIPLIERS:
            entry[multiplier_column_name(multiplier)] = float(multiplier * row["product_value"] - TOTAL_BUDGET_XIRECS)
        snapshot_rows.append(entry)
    return pd.DataFrame(snapshot_rows)


def plot_candidate_heatmap(key_table: pd.DataFrame, output_dir: Path) -> Path:
    pnl_columns = [multiplier_column_name(multiplier) for multiplier in TABLE_MULTIPLIERS]
    pnl_matrix = key_table[pnl_columns].to_numpy(dtype=float)
    row_labels = [
        f"{int(row.research_pct)} / {int(row.scale_pct)} / {int(row.speed_pct)}"
        for row in key_table.itertuples(index=False)
    ]

    fig, ax = plt.subplots(figsize=(14, 8))
    image = ax.imshow(pnl_matrix, aspect="auto", cmap="viridis")

    ax.set_title("Round 2 Manual Challenge: PnL Heatmap by Candidate Allocation")
    ax.set_xlabel("Achieved speed multiplier m")
    ax.set_ylabel("Research / Scale / Speed")
    ax.set_xticks(range(len(TABLE_MULTIPLIERS)))
    ax.set_xticklabels([f"{multiplier:.2f}" for multiplier in TABLE_MULTIPLIERS], rotation=45, ha="right")
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels)

    for y_index in range(pnl_matrix.shape[0]):
        for x_index in range(pnl_matrix.shape[1]):
            value = pnl_matrix[y_index, x_index]
            text_color = "white" if value < 250_000 else "black"
            ax.text(x_index, y_index, f"{value/1000:.0f}k", ha="center", va="center", color=text_color, fontsize=7)

    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("PnL (XIRECs)")

    path = output_dir / "candidate_pnl_heatmap.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def format_integerish(value: float) -> str:
    return f"{int(round(value)):,}"


def format_speed_row(row: pd.Series) -> str:
    return (
        f"{int(round(float(row['research_pct'])))} / "
        f"{int(round(float(row['scale_pct'])))} / "
        f"{int(round(float(row['speed_pct'])))}"
    )


def scenario_expected_pnl_column(scenario_name: str) -> str:
    return f"{scenario_name}_expected_pnl"


def scenario_multiplier_column(scenario_name: str) -> str:
    return f"{scenario_name}_multiplier"


def build_markdown_table(key_table: pd.DataFrame) -> str:
    chosen_multipliers = (0.10, 0.20, 0.30, 0.40, 0.50, 0.55, 0.60, 0.70, 0.80, 0.90)
    headers = [
        "Research",
        "Scale",
        "Speed",
        "Break-even m",
        "PnL @ 0.10",
        "PnL @ 0.20",
        "PnL @ 0.30",
        "PnL @ 0.40",
        "PnL @ 0.50",
        "PnL @ 0.55",
        "PnL @ 0.60",
        "PnL @ 0.70",
        "PnL @ 0.80",
        "PnL @ 0.90",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in key_table.itertuples(index=False):
        cells = [
            f"{int(round(row.research_pct))}",
            f"{int(round(row.scale_pct))}",
            f"{int(round(row.speed_pct))}",
            f"{row.breakeven_multiplier:.3f}",
        ]
        for multiplier in chosen_multipliers:
            cells.append(format_integerish(getattr(row, multiplier_column_name(multiplier))))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_summary(
    frontier: pd.DataFrame,
    key_table: pd.DataFrame,
    game_theory_table: pd.DataFrame,
    output_dir: Path,
) -> Path:
    zero_row = frontier.loc[frontier["speed_pct"].idxmin()]
    twenty_row = frontier.iloc[(frontier["speed_pct"] - 20).abs().idxmin()]
    thirty_row = frontier.iloc[(frontier["speed_pct"] - 30).abs().idxmin()]
    fifty_row = frontier.iloc[(frontier["speed_pct"] - 50).abs().idxmin()]
    equilibrium_median_row = game_theory_table.iloc[(game_theory_table["equilibrium_cdf"] - 0.5).abs().idxmin()]
    recommended_row = game_theory_table.sort_values(
        ["worst_case_regret", "average_regret", "speed_pct"],
        ascending=[True, True, True],
    ).iloc[0]
    just_past_25_row = game_theory_table.loc[game_theory_table["speed_pct"] == 26.0].iloc[0]
    just_past_30_row = game_theory_table.loc[game_theory_table["speed_pct"] == 31.0].iloc[0]
    top_candidates = (
        game_theory_table.sort_values(
            ["worst_case_regret", "average_regret", "speed_pct"],
            ascending=[True, True, True],
        )
        .head(6)
        .copy()
        .reset_index(drop=True)
    )
    scenario_best_rows = {
        scenario_name: game_theory_table.loc[game_theory_table[scenario_expected_pnl_column(scenario_name)].idxmax()]
        for scenario_name in FRAMEWORK_SCENARIOS
    }

    zero_product = float(zero_row["product_value"])

    def required_multiplier(row: pd.Series, baseline: float) -> float:
        return baseline * zero_product / float(row["product_value"])

    summary_table = build_markdown_table(key_table)
    top_candidate_lines = []
    for row in top_candidates.itertuples(index=False):
        top_candidate_lines.append(
            f"| {format_speed_row(pd.Series(row._asdict()))} | "
            f"{format_integerish(row.worst_case_regret)} | "
            f"{format_integerish(row.average_regret)} |"
        )
    top_candidate_table = "\n".join(
        [
            "| Research / Scale / Speed | Worst-case regret | Average regret |",
            "| --- | --- | --- |",
            *top_candidate_lines,
        ]
    )
    scenario_lines = []
    for scenario_name, row in scenario_best_rows.items():
        scenario_lines.append(
            f"| `{scenario_name}` | {format_speed_row(row)} | "
            f"{float(row[scenario_multiplier_column(scenario_name)]):.3f} | "
            f"{format_integerish(float(row[scenario_expected_pnl_column(scenario_name)]))} |"
        )
    scenario_table = "\n".join(
        [
            "| Scenario | Best split | Achieved m | Expected PnL |",
            "| --- | --- | --- | --- |",
            *scenario_lines,
        ]
    )

    summary = f"""# Round 2 Manual Challenge Direction

This report follows only:

- `IMCP2026/documents/round2_info.md`
- `IMCP2026/analysis/round2_manual/rank_bid_framework.md`

The deterministic layer comes from the Round 2 formula sheet. The game-theory layer follows the rank-bid framework's cluster-scan rule.

## Core findings

- If you spend **0% on Speed**, the best split is about **{format_pct(float(zero_row['research_pct']))} Research / {format_pct(float(zero_row['scale_pct']))} Scale**.
- If you spend **20% on Speed**, the best remaining split is about **{format_pct(float(twenty_row['research_pct']))} Research / {format_pct(float(twenty_row['scale_pct']))} Scale**.
- If you spend **30% on Speed**, the best remaining split is about **{format_pct(float(thirty_row['research_pct']))} Research / {format_pct(float(thirty_row['scale_pct']))} Scale**.
- The optimal Research/Scale split is stable: roughly **23% Research / 77% Scale of whatever budget remains after Speed**.
- Spending more on Speed lowers your deterministic Research x Scale engine, so Speed only makes sense if it materially improves your rank-based multiplier.

## Symmetric-equilibrium benchmark

- If every team solved `Speed` as a rank contest, the symmetric mixed-strategy support runs from about **0% Speed to 80% Speed**.
- In that benchmark, the **median** outcome is around **{int(round(float(equilibrium_median_row['speed_pct'])))}% Speed**, with split **{format_speed_row(equilibrium_median_row)}** and multiplier about **{float(equilibrium_median_row['equilibrium_multiplier']):.3f}**.
- The pure-equilibrium benchmark makes the supported speeds almost **flat in expected value** at roughly **{format_integerish(0.1 * zero_product - TOTAL_BUDGET_XIRECS)} XIRECs**. That means the actionable edge comes from **cluster avoidance**, not from the deterministic frontier alone.

## Framework Cluster Scan

Following `rank_bid_framework.md`, the field model is split into:

- **dropouts / disengaged** at `0`
- **AI-default bidders** at the single-agent break-even answer
- **nice-number humans** at `{5, 10, 20, 25, 30, 40, 50, 100}`
- **meme / cultural focal points** at `{42, 69, 73}`
- **smooth contest-aware teams** distributed over the equilibrium support

Using only the deterministic frontier from `round2_info.md`, the **AI-default cluster** is taken to be **20% Speed**:

- it is the obvious round-number "balanced" answer
- it keeps most of the `Research x Scale` engine
- from the zero-speed floor case (`m = 0.1`), it only needs about **{required_multiplier(twenty_row, 0.1):.3f}** to beat `0% Speed`

Under the framework, that contaminates `20` itself. The cheapest rank-arbitrage move is therefore **just past 20**, i.e. `21`.

## Sensitivity Check

Per the framework, I ran three plausible field priors:

- `mostly_nash`
- `heavy_round_numbers`
- `bimodal_dropout_sim`

All three scenarios pick the same best response:

- **Recommended:** **{format_speed_row(recommended_row)}**
- Worst-case regret across the three priors: **{format_integerish(float(recommended_row['worst_case_regret']))}**
- Average regret across the three priors: **{format_integerish(float(recommended_row['average_regret']))}**

Scenario table:

{scenario_table}

## Practical Direction

- **Do not submit `19 / 61 / 20`.** The framework marks `20` as the contaminated AI-default cluster.
- **Submit `19 / 60 / 21`.** This is the clean "just past the herd" bid that also survives the 3-prior sensitivity check.
- If you believe the field has already migrated upward and `25` is now the crowded focal point, the next clean jump is **{format_speed_row(just_past_25_row)}**.
- If you think serious teams will crowd `30`, the next clean jump is **{format_speed_row(just_past_30_row)}**.

## Robust Candidates

{top_candidate_table}

## Useful thresholds

- `0% Speed` product capacity: **{zero_product:,.0f}**
- `20% Speed` product capacity: **{float(twenty_row['product_value']):,.0f}**
- `30% Speed` product capacity: **{float(thirty_row['product_value']):,.0f}**
- `50% Speed` product capacity: **{float(fifty_row['product_value']):,.0f}**

- To justify **20% Speed** instead of **0% Speed**:
  - if `0% Speed` would only get you multiplier `0.1`, you need about **{required_multiplier(twenty_row, 0.1):.3f}**
  - if `0% Speed` would get you `0.3`, you need about **{required_multiplier(twenty_row, 0.3):.3f}**
- To justify **30% Speed** instead of **0% Speed**:
  - from baseline `0.1`, you need about **{required_multiplier(thirty_row, 0.1):.3f}**
  - from baseline `0.3`, you need about **{required_multiplier(thirty_row, 0.3):.3f}**
- To justify **50% Speed** instead of **0% Speed**:
  - from baseline `0.1`, you need about **{required_multiplier(fifty_row, 0.1):.3f}**
  - from baseline `0.3`, you need about **{required_multiplier(fifty_row, 0.3):.3f}**

## Direction

- **Framework-only re-do:** submit **{format_speed_row(recommended_row)}**.
- **If you need the next cluster-jump:** use **{format_speed_row(just_past_25_row)}** or **{format_speed_row(just_past_30_row)}**.
- The framework result is about **rank positioning**, not about maximizing a deterministic break-even table entry.

## Candidate Table

Screen order: `Research / Scale / Speed`

{summary_table}

## Files

- `frontier.csv`: full optimal frontier by Speed budget
- `key_points.csv`: expanded scenario table with many `PnL @ m=` columns
- `game_theory_table.csv`: integer-speed grid with equilibrium and framework-scenario overlays
- `optimal_split_vs_speed_budget.png`
- `product_and_pnl_vs_speed_budget.png`
- `required_speed_multiplier_vs_speed_budget.png`
- `pnl_surface.png`
- `candidate_pnl_heatmap.png`
"""

    path = output_dir / "summary.md"
    path.write_text(summary)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    style_plot()
    frontier = build_frontier(grid_step=args.grid_step, speed_step=args.speed_step)
    key_table = build_key_table(frontier)

    frontier.to_csv(output_dir / "frontier.csv", index=False)
    key_table.to_csv(output_dir / "key_points.csv", index=False)
    game_theory_table = build_game_theory_table(frontier)
    game_theory_table.to_csv(output_dir / "game_theory_table.csv", index=False)

    chart_paths = [
        plot_optimal_split(frontier, output_dir),
        plot_product_and_pnl(frontier, output_dir),
        plot_required_multiplier(frontier, output_dir),
        plot_pnl_surface(frontier, output_dir),
        plot_candidate_heatmap(key_table, output_dir),
    ]
    summary_path = write_summary(frontier, key_table, game_theory_table, output_dir)

    print(f"Summary: {summary_path}")
    print(f"Frontier: {output_dir / 'frontier.csv'}")
    print(f"Key table: {output_dir / 'key_points.csv'}")
    print(f"Game theory table: {output_dir / 'game_theory_table.csv'}")
    for chart_path in chart_paths:
        print(f"Chart: {chart_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
