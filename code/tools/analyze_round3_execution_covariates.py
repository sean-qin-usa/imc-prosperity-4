from __future__ import annotations

import argparse
import json
import math
from io import StringIO
from pathlib import Path
from statistics import NormalDist

import pandas as pd


_N = NormalDist()
SIGMA = 0.23
DAYS_PER_YEAR = 365.0
REPO_ROOT = Path(__file__).resolve().parents[1]
ROUND3_DATA = REPO_ROOT / "data" / "round3"


def bs_call(spot: float, strike: int, tte_years: float, sigma: float) -> float:
    if spot <= 0 or tte_years <= 0 or sigma <= 0:
        return max(0.0, spot - strike)
    sq = sigma * math.sqrt(tte_years)
    d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * tte_years) / sq
    d2 = d1 - sq
    return spot * _N.cdf(d1) - strike * _N.cdf(d2)


def load_visible_day(day: int) -> pd.DataFrame:
    path = ROUND3_DATA / f"prices_round_3_day_{day}.csv"
    return pd.read_csv(path, sep=";")


def load_official_bundle(bundle_path: Path) -> pd.DataFrame:
    payload = json.loads(bundle_path.read_text())
    return pd.read_csv(StringIO(payload["activitiesLog"]), sep=";")


def build_wide_frame(raw: pd.DataFrame, tte_days: float, sigma: float) -> pd.DataFrame:
    wide = None
    for product, group in raw.groupby("product"):
        block = group.sort_values("timestamp")[
            [
                "timestamp",
                "mid_price",
                "bid_price_1",
                "ask_price_1",
                "bid_volume_1",
                "ask_volume_1",
            ]
        ].copy()
        block.columns = [
            "timestamp",
            f"{product}_mid",
            f"{product}_bb",
            f"{product}_ba",
            f"{product}_bv",
            f"{product}_av",
        ]
        wide = block if wide is None else wide.merge(block, on="timestamp", how="outer")

    assert wide is not None
    wide = wide.sort_values("timestamp").ffill()

    hydro_mid = wide["HYDROGEL_PACK_mid"]
    wide["h_z"] = hydro_mid - 9990.0
    wide["h_spread"] = wide["HYDROGEL_PACK_ba"] - wide["HYDROGEL_PACK_bb"]
    wide["h_fwd10"] = hydro_mid.shift(-10) - hydro_mid
    wide["h_fwd20"] = hydro_mid.shift(-20) - hydro_mid
    wide["h_fwd50"] = hydro_mid.shift(-50) - hydro_mid
    wide["vfe_mom20"] = wide["VELVETFRUIT_EXTRACT_mid"].diff(20)

    wide["basis"] = wide["VELVETFRUIT_EXTRACT_mid"] - 0.5 * (
        (wide["VEV_4000_mid"] + 4000) + (wide["VEV_4500_mid"] + 4500)
    )
    wide["basis_z"] = (
        wide["basis"] - wide["basis"].rolling(400, min_periods=100).mean()
    ) / wide["basis"].rolling(400, min_periods=100).std()

    tte_years = tte_days / DAYS_PER_YEAR
    for strike in (5000, 5100, 5200, 5300, 5400, 5500):
        theo = wide["VELVETFRUIT_EXTRACT_mid"].map(
            lambda s: bs_call(float(s), strike, tte_years, sigma)
        )
        wide[f"resid_{strike}"] = wide[f"VEV_{strike}_mid"] - theo

    wide["otm_rich"] = wide[["resid_5300", "resid_5400", "resid_5500"]].mean(axis=1)
    wide["otm_rich_z"] = (
        wide["otm_rich"] - wide["otm_rich"].rolling(400, min_periods=100).mean()
    ) / wide["otm_rich"].rolling(400, min_periods=100).std()
    return wide


def crash_subset(
    frame: pd.DataFrame,
    crash_threshold: float,
    min_spread: int,
) -> pd.DataFrame:
    return frame[
        (frame["h_z"] <= -crash_threshold) & (frame["h_spread"] >= min_spread)
    ].dropna(subset=["h_fwd20", "h_fwd50", "vfe_mom20", "basis_z", "otm_rich_z"])


def format_quintile_table(frame: pd.DataFrame, feature: str) -> str:
    quintiles = pd.qcut(frame[feature], 5, duplicates="drop")
    grouped = frame.groupby(quintiles, observed=False).agg(
        n=("h_fwd20", "size"),
        f20=("h_fwd20", "mean"),
        f50=("h_fwd50", "mean"),
        hit20=("h_fwd20", lambda s: float((s > 0).mean())),
    )
    return grouped.to_string()


def describe_dataset(
    name: str,
    frame: pd.DataFrame,
    crash_threshold: float,
    min_spread: int,
) -> str:
    sub = crash_subset(frame, crash_threshold, min_spread)
    lines = [f"## {name}", f"crash-state rows: {len(sub)}", ""]
    if len(sub) == 0:
        lines.append("No crash-state rows matched the filter.")
        return "\n".join(lines)

    for feature in ("vfe_mom20", "basis_z", "otm_rich_z"):
        lines.append(f"### {feature}")
        lines.append(format_quintile_table(sub, feature))
        lines.append("")
    return "\n".join(lines).rstrip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze Hydro crash-state covariates for round 3."
    )
    parser.add_argument(
        "--bundle-json",
        type=Path,
        help="Optional official bundle JSON path to analyze alongside visible days.",
    )
    parser.add_argument(
        "--crash-threshold",
        type=float,
        default=25.0,
        help="Hydro distance below 9990 anchor required to enter crash state.",
    )
    parser.add_argument(
        "--min-spread",
        type=int,
        default=14,
        help="Minimum Hydro L1 spread required to enter crash state.",
    )
    parser.add_argument(
        "--sigma",
        type=float,
        default=SIGMA,
        help="Flat-vol assumption for option residual features.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reports: list[str] = []

    for day, tte_days in ((0, 8.0), (1, 7.0), (2, 6.0)):
        raw = load_visible_day(day)
        frame = build_wide_frame(raw, tte_days, args.sigma)
        reports.append(
            describe_dataset(
                f"visible_day_{day}",
                frame,
                args.crash_threshold,
                args.min_spread,
            )
        )

    if args.bundle_json is not None:
        raw = load_official_bundle(args.bundle_json)
        day_label = "official_bundle"
        if "day" in raw.columns and raw["day"].notna().any():
            day_label = f"official_day_{int(raw['day'].dropna().iloc[0])}"
        frame = build_wide_frame(raw, 6.0, args.sigma)
        reports.append(
            describe_dataset(
                day_label,
                frame,
                args.crash_threshold,
                args.min_spread,
            )
        )

    print("\n\n".join(reports))


if __name__ == "__main__":
    main()
