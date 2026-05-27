"""
Stricter local variant of the quadratic IV-surface prototype.

Use the broader chain to estimate the smile, but only quote the names
that actually showed meaningful trade activity in prior round-3 probes.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_BASE_PATH = Path(__file__).with_name("voucher_iv_surface_all_v1.py")
_SPEC = spec_from_file_location("_voucher_iv_surface_all_v1", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load base strategy from {_BASE_PATH}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BaseTrader = _MODULE.Trader


class Trader(BaseTrader):
    FIT_STRIKES = (
        "VEV_5000",
        "VEV_5100",
        "VEV_5200",
        "VEV_5300",
        "VEV_5400",
        "VEV_5500",
    )

    QUOTE_STRIKES = (
        "VEV_5300",
        "VEV_5400",
        "VEV_5500",
    )

    IV_EMA_ALPHA = 0.008
    MIN_EDGE = 1.0
    SKEW_DENOM = 120.0
    MIN_SPREAD_TO_QUOTE = 2
    MAX_POST_SIZE = 10
    DELTA_THRESHOLD = 40.0
