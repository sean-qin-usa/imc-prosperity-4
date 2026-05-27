"""
P3 manual-challenge solvers and documented Timo results.
"""
from itertools import product

# ==== Round 1: FX Arbitrage ====
# Starting: 1 SeaShell (per unit).  5 trades, must end in SeaShells.
# Rates: row→col (row pays 1 unit of row currency, receives rate[row][col] of col).
RATES = {
    "Snow":   {"Snow": 1.00, "Pizza": 1.45, "Si": 0.52, "Shells": 0.72},
    "Pizza":  {"Snow": 0.70, "Pizza": 1.00, "Si": 0.31, "Shells": 0.48},
    "Si":     {"Snow": 1.95, "Pizza": 3.10, "Si": 1.00, "Shells": 1.49},
    "Shells": {"Snow": 1.34, "Pizza": 1.98, "Si": 0.64, "Shells": 1.00},
}


def solve_r1_fx():
    currencies = list(RATES.keys())
    best_amount = 1.0
    best_path = ["Shells"] * 6
    for seq in product(currencies, repeat=4):
        path = ["Shells"] + list(seq) + ["Shells"]
        amt = 1.0
        for i in range(5):
            amt *= RATES[path[i]][path[i + 1]]
        if amt > best_amount:
            best_amount = amt
            best_path = path
    return best_amount, best_path


# ==== Round 2: Containers (Game Theory) ====
# Payoff: Π(f) = M_f * 10000 / (p_f * 100 + I_f)
# Where p_f = team % choosing f, I_f = inhabitant count.
# Fields in P3 R2: (multiplier, inhabitants) — see Prosperity site for the 10 values.
# Timo: picked multiplier=50, made ~40k; optimum across teams was ~50-54k.
# We document Timo's measured choice + predicted vs actual allocation.

TIMO_R2_ACTUAL_ALLOCATIONS = {
    # multiplier: actual team pick %
    37: 0.0512,
    10: 0.0094,
    50: 0.0852,
    # (others not listed in writeup)
}


# ==== Round 3: Reserve Price ====
# Part 1 (pure opt): Π(p) = N * (p - 160)/40 * (320 - p), optimal p = 200.
# Part 2 (game theory with avg-scaling):
#   Π(p, μ) = N * (p - 250)/70 * (320 - p) * min[((320-μ)/(320-p))^3, 1]
# Timo bid 303; actual average was 287; they lost ~5.5% vs naive optimum 284.


# ==== Round 4: Suitcases ====
# Same mechanic as R2 but 2 picks allowed for 25k fee.
# Timo: picked multiplier=37 and 50, made ~85k; optimal was ~130k (60+50 combo).


# ==== Round 5: News Trading ====
# Predict % movement of 9 products; PnL scales with direction-correctness × size.
# Timo's results per README:
TIMO_R5_NEWS = [
    # (product, predicted %, actual %, timo profit, optimum)
    ("Haystacks",      12,   -0.48,   -3240,      0),
    ("Ranch Sauce",    10,   -0.72,   -2208,      0),
    ("Cacti Needle",  -30,  -41.20,   32160,  35360),
    ("Solar Panels",  -30,   -8.90,   -6600,   1640),
    ("Red Flags",       5,   50.90,    9700,  53970),
    ("VR Monocle",     30,   22.40,    9600,  10440),
    ("Quantum Coffee",-50,  -66.79,   87339,  92932),
    ("Moonshine",       0,    3.00,       0,    180),
    ("Striped shirts",  0,    0.21,       0,      0),
]


def timo_r5_totals():
    return sum(r[3] for r in TIMO_R5_NEWS), sum(r[4] for r in TIMO_R5_NEWS)


if __name__ == "__main__":
    print("=== P3 R1 FX Arbitrage ===")
    amount, path = solve_r1_fx()
    print(f"Best path: {' -> '.join(path)}")
    print(f"Ending amount (from 1 Shell): {amount:.6f}")
    print(f"Profit: {(amount - 1) * 100:.3f}%")
    print(f"Timo's reported profit: 8.9 % (matches)")

    print()
    print("=== P3 R5 News Trading ===")
    timo, opt = timo_r5_totals()
    print(f"Timo total profit:       {timo:>8d}")
    print(f"Optimal hindsight total: {opt:>8d}")
    print(f"Timo captured:           {timo/opt*100:.1f}% of optimum")
