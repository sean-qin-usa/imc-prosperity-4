# Rank-bid contest framework (Prosperity-style)

**Scope:** any rank-based bid contest in Prosperity-likes — Speed allocation in a manual challenge, Market Access Fee auctions, any future rank-auction mechanic.

## Rule

**Do not submit the answer that comes from break-even math alone.** That answer is what every mainstream LLM returns on first pass, so 5–10% of the field will bid exactly that number. Being tied with them destroys the rank you were paying for.

## Why it fails

Break-even math treats the problem as single-agent optimization: "what Speed multiplier μ do I need to justify spending X on Speed?" That gives you a number that looks reasonable in isolation but ignores that the *whole field is doing the same math*. The resulting bid lands in the densest cluster of the field's bid distribution — you pay for Speed but get rank-tied with everyone else who also paid for Speed.

The real game is positional: rank is a percentile, not a deterministic function of your bid. Your PnL depends on *where your bid sits in the field's distribution*, not on how much the bid cost.

## How to apply

1. **Before math, do the cluster scan.** Map the expected field into five buckets:
   - Dropouts / disengaged → V=0 (large in rounds with no filter, small after elimination)
   - AI-default bidders → the specific number LLMs converge on (compute this explicitly)
   - Nice-number humans → anchors like {5, 10, 20, 25, 30, 40, 50, 100}
   - Meme / cultural focal points → {42, 69, 73} or competition-specific
   - Simulator-driven teams → concentrated at wherever a reasonable Monte Carlo peaks
2. **Compute the AI-default answer, then mark it contaminated.** Before submitting, ask "if ChatGPT, Claude, and Gemini all gave this exact number, would I still be happy with it?" If no, iterate. Subtract 5–10% of the field at that specific value when building the mixture prior. The "just past" bid of that cluster is the cheapest rank arbitrage.
3. **Run Monte Carlo with a mixture model**, not a single Beta distribution. A pure Beta misses the spikes at V=0 and round numbers. Mix:
   - Point mass at 0 (dropouts)
   - Small point masses at nice numbers
   - Optional point mass at the computed AI-default value
   - A smooth Beta (or log-normal, truncated normal) for "did some thinking" bidders
   - Weights calibrated to the round's filter (dropouts shrink after elimination, sophisticates concentrate)
4. **Find the E[PnL](V) plateau, not a point peak.** The optimum in a contest like this is almost always a flat-top plateau spanning 2–4 integer bids. Pick the midpoint or the bid just past the last visible cluster.
5. **"Just past the last herd that isn't you"** is the invariant. Clusters shift with filters, but the heuristic doesn't. Identify every cluster the Monte Carlo surfaces; your optimal bid is one step past whichever cluster is closest to the marginal-rank-gain / marginal-product-loss crossover.

   **CRITICAL — recursive climbing.** Your own "just past the AI-default" bid is itself adopted by every sophisticated team, so it becomes a cluster too. The true optimum is not "just past the first herd you find" — it's the position where marginal rank gain per +1 V no longer covers marginal product loss per +1 V. Expect that position to sit **past every nice-number anchor in your cluster list** (so for a nice-number set `{5, 10, 20, 25, 30, 40, 50}`, expect the optimum past V=40 or near V=50), not at "AI-default + 1."

   Diagnostic: if your candidate bid is less than +10 above the AI-default, you're probably in the first-leapfrog trap. Compute E[PnL] at your candidate AND at every +5 increment above it up to V=60. If any of those beats your candidate, you're under-bidding. The true plateau is whichever integer range is locally flat in E[PnL] — not the first local improvement over the AI-default.
6. **Post-filter rounds (manual R3–R5):** the Prosperity 4 field was cut from ~22,200 teams to ~4,050 survivors after R2 — filtering was on trading PnL, so what remains is teams using AI or doing real work. Recalibrate the cluster weights:
   - V=0 pile drops from ~7% to ~2–3% (disengaged teams are mostly eliminated).
   - **AI-default cluster *grows in share* to ~12–18%** — not skill-uncorrelated as the naive model assumes. Disengaged V=0 teams weren't using AI (they didn't submit anything), so filtering them out concentrates AI use among the survivors. Most of the ~4k survivors used AI at least once during the competition, and a meaningful chunk will paste the raw AI answer into R3's manual. This is now typically the single largest avoidable cluster.
   - Nice-number humans shrink ~2x in share (correlated with weak trading).
   - Simulator / "did the work" cluster **grows to ~25–30%** — these are exactly the teams that survived.
   - Expect the prior round's winning bid to become a cluster itself (survivors remember it). Bid "just past" the new cluster, or consider that the under-crowded zone may now be *below* the old optimum if sophisticates all moved up together.
   - Concretely for any R3+ rank-bid resembling R2's Speed problem: V=42 is now the crowded sophisticate bid, AND the AI-default (whatever current LLMs output for the R3 problem) is likely 12–18% of the field rather than 6–8%. Winning move is past *both* clusters — V=44–46 above if sophisticates and AI users stack there, or the under-crowded V=30–35 zone below if they all piled upward.

## Sensitivity check

Run the Monte Carlo with at least 3 plausible field priors (e.g., "mostly Nash," "heavy round-number anchoring," "bimodal dropouts + simulators"). If all three give the same V* ± 2, you're robust. If the answer swings wildly, your model is fragile — either hedge by widening the plateau range, or take the safer deterministic play (max-product allocation with V=0) and accept the rank floor.
