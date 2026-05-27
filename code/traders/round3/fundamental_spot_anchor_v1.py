"""
Local research variant of `fundamental_v1.py`.

Direction:
- Pure spot-anchor pricing for deep-ITM vouchers.
- No sibling-contract confirmation gate.
- No sibling blend into spot.
- No underlying hedge.

Use this to answer the question:
"Is the only thing we need the tighter underlying as fair, with zero
 cross-contract moderation?"

Note: this variant depends on `fundamental_v1.py` being present in the
same directory. If it wins, inline the params back into a standalone
upload-safe file.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_BASE_PATH = Path(__file__).with_name("fundamental_v1.py")
_SPEC = spec_from_file_location("_fundamental_v1_base_spot_anchor", _BASE_PATH)
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
