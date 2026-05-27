"""
Spot-anchor + medium-strength surface gate.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_BASE_PATH = Path(__file__).with_name("fundamental_surface_gate_v1.py")
_SPEC = spec_from_file_location(
    "_fundamental_surface_gate_base_spot_anchor_mid",
    _BASE_PATH,
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load base strategy from {_BASE_PATH}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BaseTrader = _MODULE.Trader


class Trader(BaseTrader):
    V_CONFIRM_THRESHOLD = 999.0
    V_CONFIRM_WIDEN = 0.0
    V_CONFIRM_SIZE_MULT = 1.0
    V_SIBLING_BLEND = 0.0
    ENABLE_UNDERLYING_HEDGE = False

    SURF_EDGE_PER_Z = 0.20
    SURF_SIZE_PER_Z = 0.08
    SURF_MIN_SIDE_MULT = 0.60
