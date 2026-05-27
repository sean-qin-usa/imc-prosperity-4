"""
Local research wrapper: baseline_v5 vouchers only.

Purpose:
- isolate the first-principles deep-ITM voucher sleeve
- remove HYDROGEL entirely so total PnL reflects vouchers only
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_BASE_PATH = Path(__file__).with_name("baseline_v5.py")
_SPEC = spec_from_file_location("_baseline_v5_voucher_only", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load base strategy from {_BASE_PATH}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BaseTrader = _MODULE.Trader


class Trader(BaseTrader):
    def _trade_hydrogel(self, od, pos):
        return []
