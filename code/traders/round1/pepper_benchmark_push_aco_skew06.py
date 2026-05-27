"""Benchmark-push variant with only the stronger ACO inventory skew.

Purpose:
- keep the PEPPER benchmark-push logic unchanged
- isolate whether the current/unified edge mostly comes from the stronger
  ACO inventory skew (`0.06` instead of `0.04`)
"""

import importlib.util
from pathlib import Path


_BASE_PATH = Path(__file__).with_name("pepper_benchmark_push.py")
_BASE_SPEC = importlib.util.spec_from_file_location("pepper_benchmark_push", _BASE_PATH)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load base trader from {_BASE_PATH}")

_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)


class Trader(_BASE_MODULE.Trader):
    ACO_INVENTORY_SKEW_PER_UNIT = 0.06
