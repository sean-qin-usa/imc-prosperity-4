from __future__ import annotations

from typing import Optional, Sequence

from visualizer_interactive import main as interactive_main


def main(argv: Optional[Sequence[str]] = None) -> int:
    return interactive_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
