"""
R5 manual — SYNTHESIS plan.

Reconciles two prior sets:
  Codex (original solve_round5_manual.py): trusted user's article reading,
      270k EV but 100k EV under last-year-anchored magnitudes.
  Calibrated (solve_round5_manual_v2_calibrated.py): shrank to last-year
      Prosperity-3 archetypes, 188k EV either way.

Each VIEW.expected_move is the midpoint of Codex and calibrated estimates.
Re-optimized with the same DP. Live frontend fee formula (verified):
  fee = invest^2 / 1,000,000 = 100 * percent^2

Three-way cross-evaluation:
                            Codex priors   Synth priors   Calib priors
  Codex plan                     270,000        162,900        100,300
  SYNTHESIS plan                 233,900        198,700        174,800
  Calibrated plan                187,500        187,300        188,000

Synthesis dominates the midpoint-reality scenario and has 1/3 the
downside range of Codex's plan. Worst case = +174,800 (vs Codex's
+100,300), so well above any R4-class loss.

R4-loss-prevention check: every position has its sign-flip worst case
contained because no single position is sized above 25%. Largest worst
case (Lava cake sign-flip, 25% SELL) = -0.55 * 250k - 62.5k = -200k.
This is the ONE position to verify article reading on; the article is
unambiguous (lava in cakes, production halt, returns).
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
         "Codex 0.55 / calib 0.55 — agreed; QuantumCoffee-class but no outright ban"),
    View("Pyroflex cells", "SELL", 0.35,
         "Codex 0.42 / calib 0.28; SolarPanels analog (-0.28). VERIFY DIRECTION on article."),
    View("Thermalite core", "BUY", 0.33,
         "Codex 0.36 / calib 0.30; VRMonocle-class quarterly blowout"),
    View("Magma ink", "BUY", 0.30,
         "Codex 0.50 / calib 0.15; six-hour lines bullish but RanchSauce was only +0.12"),
    View("Ashes of the Phoenix", "SELL", 0.30,
         "Codex 0.18 / calib 0.40; 'sales plummeted' is strong, between Cacti and QuantumCoffee"),
    View("Obsidian cutlery", "SELL", 0.22,
         "Codex 0.12 / calib 0.30; CactiNeedle production-halt analog (-0.33)"),
    View("Sulfur reactor", "BUY", 0.20,
         "Codex 0.38 / calib 0.10; index inclusion = real but priced-in flow"),
    View("Scoria paste", "BUY", 0.08,
         "Codex 0.30 / calib 0.00; influencer trap, but 'essential utility' framing > pure Moonshine"),
    View("Volcanic incense", "BUY", 0.04,
         "Codex 0.26 / calib 0.00; pure influencer pump, expect tiny weight"),
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
    print(f"Expected PnL under SYNTHESIS priors: {ev:,.0f}")
    print(f"Total allocation: {sum(p for _, p in picks)}%\n")
    for view, percent in picks:
        invest = round(percent / 100 * BUDGET)
        gross = round(BUDGET * view.expected_move * percent / 100)
        print(
            f"{view.product:22s} {view.action:4s} {percent:3d}% "
            f"invest={invest:>7,} fee={fee(percent):>6,} "
            f"gross_ev={gross:>7,} net_ev={score(view, percent):>7,.0f}"
        )
    print("\nSubmission orders:")
    for view, percent in picks:
        print(f'  {view.product:22s} {view.action:4s} {percent:>3d}%')


if __name__ == "__main__":
    main()
