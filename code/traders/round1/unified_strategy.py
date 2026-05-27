"""Unified entrypoint for the promoted Round 1 production trader.

This keeps the historical `unified_strategy.py` filename available while
aligning it with the strongest validated live branch:
- the stronger fixed-fair ACO leg
- the benchmark-push PEPPER carry framework
- the `core70` PEPPER target
- the small early-session completion quote that survived both local fill models

The older inline `+2` passive PEPPER implementation is still preserved in
`pepper_benchmark_push_plus2_passive.py` for archived comparisons.
"""

import importlib.util
from pathlib import Path


_BASE_PATH = Path(__file__).with_name("pepper_benchmark_push_core70_completion_early.py")
_BASE_SPEC = importlib.util.spec_from_file_location("pepper_benchmark_push_core70_completion_early", _BASE_PATH)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load unified trader from {_BASE_PATH}")

_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)
Trader = _BASE_MODULE.Trader
