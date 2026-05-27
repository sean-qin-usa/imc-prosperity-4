from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from visualizer_fh_clone import main as fh_main

# Canonical entrypoint for the unified interactive dashboard.
DEFAULT_CONFIG = Path(__file__).with_name("visualizer_config.json")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("visualizer_report")
DEFAULT_OUTPUT = DEFAULT_OUTPUT_DIR / "report_interactive.html"


def _parse_output_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--group-output", action="store_true")
    parsed, _ = parser.parse_known_args(argv)
    return parsed


def _resolve_output(parsed: argparse.Namespace) -> Path:
    if parsed.output:
        return parsed.output

    config_path = parsed.config if parsed.config else DEFAULT_CONFIG
    output_dir = DEFAULT_OUTPUT_DIR
    data_dir = parsed.data_dir
    group_output = parsed.group_output

    if config_path.exists():
        raw = json.loads(config_path.read_text())
        if raw.get("output_dir"):
            output_dir = Path(raw["output_dir"]).expanduser()
        if raw.get("data_dir") and data_dir is None:
            data_dir = Path(raw["data_dir"]).expanduser()
        if raw.get("group_output", False):
            group_output = True

    if group_output:
        suffix = data_dir.name if data_dir else "dataset"
        output_dir = output_dir / suffix

    return output_dir / "report_interactive.html"


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    parsed = _parse_output_args(args)
    output_path = _resolve_output(parsed)

    cleaned_args = [arg for arg in args if arg != "--group-output"]
    if "--output" not in cleaned_args:
        cleaned_args += ["--output", str(output_path)]
    return fh_main(cleaned_args)


if __name__ == "__main__":
    raise SystemExit(main())
