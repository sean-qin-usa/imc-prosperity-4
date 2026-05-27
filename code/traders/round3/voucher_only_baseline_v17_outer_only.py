"""
Local research wrapper: baseline_v17 vouchers only, outer smile wing only.

Keeps:
- VEV_5400 / VEV_5500 smile-corrected sleeves

Drops:
- HYDROGEL
- deep-ITM VEV_4000 / VEV_4500
- VEV_5300
- lottery
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_BASE_PATH = Path(__file__).with_name("baseline_v17.py")
_SPEC = spec_from_file_location("_baseline_v17_voucher_outer_only", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load base strategy from {_BASE_PATH}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BaseTrader = _MODULE.Trader


class Trader(BaseTrader):
    LOG = False
    VOUCHER_STRIKES = {}
    ATM_STRIKES = {"VEV_5400": 5400, "VEV_5500": 5500}
    LOTTERY_STRIKES = {}

    def _trade_hydrogel(self, od, pos, prev_mid):
        return [], prev_mid if prev_mid is not None else 0.0, {"disabled": True}
