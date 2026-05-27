from __future__ import annotations

from dataclasses import dataclass


BUDGET = 1_000_000


@dataclass(frozen=True)
class Product:
    name: str
    action: str
    aggressive_move: float
    calibrated_move: float
    note: str


# Two scenario sets are intentional:
#
# 1. aggressive_move: direct read of Ashflow Alpha article strength.
# 2. calibrated_move: Claude's Prosperity-3-archetype calibration, which
#    penalizes hype/influencer articles and avoids another optimistic-manual
#    sizing error.
#
# The final allocation maximizes the worse expected PnL across both scenarios.
PRODUCTS = [
    Product("Lava cake", "SELL", 0.55, 0.55, "confirmed lava traces, health review, sales halt"),
    Product("Ashes of the Phoenix", "SELL", 0.18, 0.40, "public sourcing backlash; calibrated view treats this as a serious PR shock"),
    Product("Obsidian cutlery", "SELL", 0.12, 0.30, "production halt / contamination; sign is mixed but calibrated analog is bearish"),
    Product("Thermalite core", "BUY", 0.36, 0.30, "quarterly forecast surge in smart-home devices"),
    Product("Pyroflex cells", "SELL", 0.42, 0.28, "tax cut is abolished; effective levy doubles"),
    Product("Magma ink", "BUY", 0.50, 0.15, "limited-edition launch; calibrated view caps launch hype"),
    Product("Sulfur reactor", "BUY", 0.38, 0.10, "index inclusion flow"),
    Product("Scoria paste", "BUY", 0.30, 0.00, "stockpiling headline; calibrated view treats influencer-like hype as a trap"),
    Product("Volcanic incense", "BUY", 0.26, 0.00, "rally headline; calibrated view treats concentrated influencer buying as a trap"),
]


def fee(percent: int) -> int:
    invest = round(percent / 100 * BUDGET)
    return round(invest * invest / BUDGET)


def score(move: float, percent: int) -> float:
    w = percent / 100
    return BUDGET * (move * w - w * w)


def plan_score(plan: dict[str, int], scenario: str) -> float:
    attr = "aggressive_move" if scenario == "aggressive" else "calibrated_move"
    by_name = {p.name: p for p in PRODUCTS}
    return sum(score(getattr(by_name[name], attr), pct) for name, pct in plan.items())


def optimize_maximin() -> tuple[float, float, float, dict[str, int]]:
    # Each state stores (aggressive_ev, calibrated_ev, plan). We keep only the
    # Pareto frontier for each total percentage.
    states: list[list[tuple[float, float, dict[str, int]]]] = [[(0.0, 0.0, {})] for _ in range(101)]
    for product in PRODUCTS:
        new_states = [bucket[:] for bucket in states]
        for used, bucket in enumerate(states):
            for aggressive_ev, calibrated_ev, plan in bucket:
                for pct in range(1, 101 - used):
                    candidate = dict(plan)
                    candidate[product.name] = pct
                    new_states[used + pct].append(
                        (
                            aggressive_ev + score(product.aggressive_move, pct),
                            calibrated_ev + score(product.calibrated_move, pct),
                            candidate,
                        )
                    )

        pruned: list[list[tuple[float, float, dict[str, int]]]] = []
        for bucket in new_states:
            # Sort by aggressive EV and keep states that improve calibrated EV.
            frontier = []
            best_calibrated = -10**18
            for state in sorted(bucket, key=lambda s: (-s[0], -s[1])):
                if state[1] > best_calibrated:
                    frontier.append(state)
                    best_calibrated = state[1]
            pruned.append(frontier)
        states = pruned

    best_min = -10**18
    best_state: tuple[float, float, dict[str, int]] | None = None
    for bucket in states:
        for state in bucket:
            worst = min(state[0], state[1])
            if worst > best_min:
                best_min = worst
                best_state = state
    assert best_state is not None
    aggressive_ev, calibrated_ev, plan = best_state
    return best_min, aggressive_ev, calibrated_ev, plan


def main() -> None:
    worst_ev, aggressive_ev, calibrated_ev, plan = optimize_maximin()
    by_name = {p.name: p for p in PRODUCTS}
    print(f"Worst-scenario expected PnL: {worst_ev:,.0f}")
    print(f"Aggressive-scenario expected PnL: {aggressive_ev:,.0f}")
    print(f"Calibrated-scenario expected PnL: {calibrated_ev:,.0f}")
    print(f"Total allocation: {sum(plan.values())}%")
    print()
    for name, pct in sorted(plan.items(), key=lambda item: -item[1]):
        product = by_name[name]
        print(
            f"{name:22s} {product.action:4s} {pct:3d}% "
            f"fee={fee(pct):>6,} "
            f"aggr_ev={score(product.aggressive_move, pct):>8,.0f} "
            f"cal_ev={score(product.calibrated_move, pct):>8,.0f}"
        )
    print()
    print("Submission orders:")
    for name, pct in sorted(plan.items(), key=lambda item: -item[1]):
        print(f'  {{"product": "{name}", "action": "{by_name[name].action}", "volume": {pct}}},')


if __name__ == "__main__":
    main()
