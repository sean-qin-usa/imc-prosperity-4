#!/bin/bash
# P3 R2 parameter sensitivity check — is the strategy overfit?
# Vary one param at a time ±25 pts from baseline (80,-40,80,-40).
# If PnL moves >20% for any single-knob change, the grid is noise-fitted.

set -e
cd /Users/sean_tsu_/Downloads/prosperity
SCRATCH=/Users/sean_tsu_/Downloads/prosperity/IMCP2026/traders/p3_fresh_claude/_sweep
mkdir -p "$SCRATCH"
cp IMCP2026/traders/p3_fresh_claude/datamodel.py "$SCRATCH/datamodel.py"

run_one() {
    local b1u=$1 b1l=$2 b2u=$3 b2l=$4 label=$5
    local f="$SCRATCH/sweep_${label}.py"
    sed -e "s/B1_UPPER = 80.0/B1_UPPER = ${b1u}.0/" \
        -e "s/B1_LOWER = -40.0/B1_LOWER = ${b1l}.0/" \
        -e "s/B2_UPPER = 80.0/B2_UPPER = ${b2u}.0/" \
        -e "s/B2_LOWER = -40.0/B2_LOWER = ${b2l}.0/" \
      IMCP2026/traders/p3_fresh_claude/p3r2_fresh.py > "$f"
    local tot=$(python3 -m prosperity3bt "$f" 2 --merge-pnl 2>&1 | grep "Total profit:" | tail -1 | awk -F': ' '{print $2}')
    echo "  $label  (B1U=$b1u B1L=$b1l B2U=$b2u B2L=$b2l)  -> $tot"
}

echo "=== baseline ==="
run_one 80 -40 80 -40 "baseline"
echo ""
echo "=== single-knob sweep ==="
run_one 60 -40 80 -40 "B1U-25"
run_one 100 -40 80 -40 "B1U+25"
run_one 80 -20 80 -40 "B1L-20hi"
run_one 80 -60 80 -40 "B1L-20lo"
run_one 80 -40 60 -40 "B2U-25"
run_one 80 -40 100 -40 "B2U+25"
run_one 80 -40 80 -20 "B2L-20hi"
run_one 80 -40 80 -60 "B2L-20lo"
echo ""
echo "=== also test on R3 (OOS days include day 2) ==="
run_one_r3() {
    local b1u=$1 b1l=$2 b2u=$3 b2l=$4 label=$5
    local f="$SCRATCH/sweep_${label}.py"
    sed -e "s/B1_UPPER = 80.0/B1_UPPER = ${b1u}.0/" \
        -e "s/B1_LOWER = -40.0/B1_LOWER = ${b1l}.0/" \
        -e "s/B2_UPPER = 80.0/B2_UPPER = ${b2u}.0/" \
        -e "s/B2_LOWER = -40.0/B2_LOWER = ${b2l}.0/" \
      IMCP2026/traders/p3_fresh_claude/p3r2_fresh.py > "$f"
    local tot=$(python3 -m prosperity3bt "$f" 3 --merge-pnl 2>&1 | grep "Total profit:" | tail -1 | awk -F': ' '{print $2}')
    echo "  R3 $label -> $tot"
}
run_one_r3 80 -40 80 -40 "baseline"
run_one_r3 60 -40 80 -40 "B1U-25"
run_one_r3 100 -40 80 -40 "B1U+25"
run_one_r3 80 -40 100 -40 "B2U+25"
run_one_r3 80 -40 80 -60 "B2L-20lo"
