"""
Local research variant of `fundamental_v1.py`.

Direction:
- Use sibling deep-ITM synthetic spot more aggressively.
- Widen voucher edges more when contracts disagree.
- Enable a light underlying delta hedge.

Use this to answer the question:
"Does stronger cross-contract consensus plus a small hedge make the
 deep-ITM sleeve steadier on noisy days?"

Note: this variant depends on `fundamental_v1.py` being present in the
same directory. If it wins, inline the params back into a standalone
upload-safe file.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_BASE_PATH = Path(__file__).with_name("fundamental_v1.py")
_SPEC = spec_from_file_location("_fundamental_v1_base_consensus", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load base strategy from {_BASE_PATH}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BaseTrader = _MODULE.Trader


class Trader(BaseTrader):
    V_CONFIRM_THRESHOLD = 1.5
    V_CONFIRM_WIDEN = 1.0
    V_CONFIRM_SIZE_MULT = 0.35
    V_SIBLING_BLEND = 0.20
    V_SIBLING_BLEND_CAP = 5.0
    ENABLE_UNDERLYING_HEDGE = True
    HEDGE_DELTA_THRESHOLD = 140.0
    HEDGE_SIZE = 15
    HEDGE_EDGE = 0.5
