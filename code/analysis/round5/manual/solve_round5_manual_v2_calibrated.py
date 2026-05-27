"""
R5 manual — CALIBRATED VIEWS using last-year (Prosperity 3) archetype anchors.

Key lesson from R4 manual disaster:
  R4 lost money because we sized into positions whose model fairs were
  derived from optimistic assumptions (200k MC paths) but scored against
  high-variance reality (100 paths). The R5 analog is FORECAST ERROR in
  move estimates — not sampling noise. The defense is the same: don't
  size into positions whose magnitude prior is unverified.

Last-year (P3) realized magnitudes per archetype (chrispy notebook):
  Quantum Coffee (banned drug, sales plummet):       -0.82
  Cacti Needle   (defective product, fatal crash):   -0.33
  Solar Panels   (tax-hike on consumer good):        -0.28
  VR Monocle     (quarterly blowout 4x growth):      +0.31
  Sculptures     (supply shock from disaster):       +0.20
  Earrings       (acquisition + relaunch):           +0.12
  Refrigerators  (silly minor news):                 +0.02
  Lamps/Striped  (influencer hype, unverified):      ~0
  Chocolate/Moon (silly "to the moon" hype):         ~0

The original solve_round5_manual.py had several priors that don't match
last-year archetypes:
  Magma ink +0.50  vs RanchSauce analog +0.12  (over by 4x)
  Sulfur    +0.38  vs no analog, index flow    (over — typically <0.15)
  Scoria    +0.30  vs Moonshine analog ~0      (TRAP)
  Volcanic  +0.26  vs StripedShirts analog ~0  (TRAP)
  Obsidian  -0.12  vs CactiNeedle analog -0.33 (under)
  Ashes     -0.18  vs no analog, but "sales plummeted" is strong (under)

Cross-eval (see /tmp/r5_cross_eval.py):
                      under USER priors    under CALIB priors
  USER plan                 270,000             100,300
  CALIBRATED plan           187,500             188,000

Calibrated plan is dominant on a risk-adjusted basis: same PnL in either
scenario, vs user plan which is bimodal 270k/100k.
"""
from dataclasses import dataclass

BUDGET = 1_000_000


@dataclass(frozen=True)
class View:
    product: str
    action: str
    expected_move: float
    note: str


VIEWS = [
    View("Lava cake", "SELL", 0.55,
         "QuantumCoffee analog (-0.82) but less severe (no outright ban)"),
    View("Ashes of the Phoenix", "SELL", 0.40,
         "PR-disaster + 'sales plummeted' — between Cacti and QuantumCoffee"),
    View("Obsidian cutlery", "SELL", 0.30,
         "CactiNeedle analog (-0.33): defective core product halts production"),
    View("Thermalite core", "BUY", 0.30,
         "VR Monocle analog (+0.31): quarterly forecast surge, ~4x sales"),
    View("Pyroflex cells", "SELL", 0.28,
         "SolarPanels analog (-0.28): subsidy repeal = effective tax hike. "
         "VERIFY DIRECTION — if article actually says cut is being IMPLEMENTED, flip to BUY."),
    View("Magma ink", "BUY", 0.15,
         "RanchSauce analog (+0.12): partnered launch / limited edition"),
    View("Sulfur reactor", "BUY", 0.22,
         "UPGRADED 04/29 12:00 CEST: Ashflow Alpha correction adds the "
         "Sulfur Reactor *product itself* to Elemental Index 118 (previous "
         "wording added Sulfur Ltd parent company with Reactor as flagship). "
         "Direct index inclusion = mechanical tracking-fund buying on the "
         "tradable good. Stronger than indirect company-level signal."),
    View("Scoria paste", "BUY", 0.0,
         "Moonshine analog (~0): influencer 'market medium' = trap, skip"),
    View("Volcanic incense", "BUY", 0.0,
         "StripedShirts analog (~0): influencer pump = trap, skip"),
]


def fee(percent: int) -> int:
    invest = round(percent / 100 * BUDGET)
    return round(invest * invest / BUDGET)


def score(view: View, percent: int) -> float:
    w = percent / 100
    return BUDGET * (view.expected_move * w - w * w)


def optimize_integer():
    dp = [(-10**18, []) for _ in range(101)]
    dp[0] = (0.0, [])
    for view in VIEWS:
        ndp = [(value, picks[:]) for value, picks in dp]
        for used, (value, picks) in enumerate(dp):
            if value < -1e17:
                continue
            for percent in range(1, 101 - used):
                candidate = value + score(view, percent)
                if candidate > ndp[used + percent][0]:
                    ndp[used + percent] = (candidate, picks + [(view, percent)])
        dp = ndp
    return max(dp, key=lambda item: item[0])


def main():
    ev, picks = optimize_integer()
    print(f"Expected PnL under CALIBRATED priors: {ev:,.0f}")
    print(f"Total allocation: {sum(percent for _, percent in picks)}%")
    print()
    for view, percent in picks:
        invest = round(percent / 100 * BUDGET)
        gross = round(BUDGET * view.expected_move * percent / 100)
        print(
            f"{view.product:22s} {view.action:4s} {percent:3d}% "
            f"invest={invest:>7,} fee={fee(percent):>6,} "
            f"gross_ev={gross:>7,} net_ev={score(view, percent):>7,.0f}"
        )
    print()
    print("Submission orders:")
    for view, percent in picks:
        print(f'  {view.product:22s} {view.action:4s} {percent:>3d}%')


if __name__ == "__main__":
    main()
