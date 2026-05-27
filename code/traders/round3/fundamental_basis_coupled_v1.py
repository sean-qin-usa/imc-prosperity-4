"""
Local research variant built on `fundamental_v1.py`.

Idea:
- Couple VFE with both deep-ITM synthetics explicitly via a consensus
  spot estimator.
- Weight spot highest, but allow VEV_4000/4500 implied spot to nudge
  fair values when the contracts agree with each other against spot.
- No explicit hedge. This is the "understand the group first" branch.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_BASE_PATH = Path(__file__).with_name("fundamental_v1.py")
_SPEC = spec_from_file_location("_fundamental_v1_base_basis_coupled", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load base strategy from {_BASE_PATH}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
BaseTrader = _MODULE.Trader


class Trader(BaseTrader):
    C_SPOT_WEIGHT = 1.0
    C_SYNTH_WEIGHT = 8.0
    C_BLEND = 0.25
    C_BLEND_CAP = 5.0

    V_CONFIRM_THRESHOLD = 1.5
    V_CONFIRM_WIDEN = 0.75
    V_CONFIRM_SIZE_MULT = 0.50
    ENABLE_UNDERLYING_HEDGE = False

    def _voucher_context(self, name: str, spot_mid: float, books):
        weighted_sum = self.C_SPOT_WEIGHT * spot_mid
        total_w = self.C_SPOT_WEIGHT
        for other_name, strike in self.VOUCHER_STRIKES.items():
            book = books.get(other_name)
            if book is None:
                continue
            synth = book["touch_mid"] + strike
            weight = self.C_SYNTH_WEIGHT / max(1.0, float(book["spread"]))
            weighted_sum += weight * synth
            total_w += weight

        consensus = weighted_sum / total_w if total_w > 0 else spot_mid
        disagreement = consensus - spot_mid
        blended_spot = spot_mid + self.C_BLEND * self._clip(
            disagreement, -self.C_BLEND_CAP, self.C_BLEND_CAP
        )
        return blended_spot, disagreement
