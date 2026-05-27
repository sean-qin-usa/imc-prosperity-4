"""Core-69 PEPPER carry with a small early-session completion quote."""

import importlib.util
from pathlib import Path


_BASE_PATH = Path(__file__).with_name("pepper_benchmark_push_core66_completion_early.py")
_BASE_SPEC = importlib.util.spec_from_file_location("pepper_benchmark_push_core66_completion_early", _BASE_PATH)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise ImportError(f"Could not load base trader from {_BASE_PATH}")

_BASE_MODULE = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(_BASE_MODULE)


class Trader(_BASE_MODULE.Trader):
    IPR_CORE_TARGET = 69
