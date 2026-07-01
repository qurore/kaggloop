---
name: kaggloop-hypothesize
description: Stage 2 of the kaggloop win-loop — generate, ground, and rank critical-to-win hypotheses (AI-Scientist-v2 style), each a concrete testable bet about what will move the score toward the target, grounded in the dossier's top notebooks/discussions and the academic literature. On later iterations it is driven by the gap to target. Use after survey, or at the start of each new loop iteration. Output a ranked hypotheses.jsonl ledger.
---

# Stage 2 — Hypothesize (critical-to-win bets, gap-driven)

The exploratory engine, modeled on **AI-Scientist-v2's** ideate→reflect loop but aimed at
**closing the gap to the target score**. Produce a small set of explicit, testable
hypotheses — each a bet that "doing X will move the score by ~Δ because <evidence>" —
ranked by expected value, recorded in the ledger for the experiment stage to verify.

## Preconditions
- `dossier.md` exists; state has `metric`, `metric_direction`, `target_score`.
  `python -m kloop.project set --stage hypothesize --status running`.
- **MANDATORY FIRST STEP — read the last ≤5 iteration learning journals.** Before forming any
  bet, read the most recent iteration retrospectives written by `/kaggloop-submit` (newest
  first) — this is the meta-learning loop that stops us repeating mistakes:
  ```bash
  ls -1 projects/<name>/iterations/iter_*.md | sort | tail -5   # newest ≤5
  ```
  Read each. They carry, per past iteration: what was done, the predicted vs actual score, the
  **gap and its verified cause** (grounded in notebooks/discussions/papers/SDK), and an explicit
  **plan & resolve for the next iteration**. **Explicitly decide** whether to adopt the prior
  iteration's stated plan (and say why / why not) — do not silently ignore it, and never re-try
  an approach a past journal already refuted. Carry the confirmed levers forward.
- **On iterations >0, start from the gap.** Read where the loop stands and *why* it's short:
  ```bash
  python -m kloop.project gap            # how far from target, on cv and lb
  python -m kloop.journal show --kind gap_analysis
  python -m kloop.ledger list            # what was kept / rejected (don't re-try rejected)
  ```
  Let the gap analysis (the realized CV↔LB behavior, the size and likely source of the
  remaining gap) and the iteration journals **focus** this round's bets on the highest-leverage
  way to close the gap.

## What makes a good hypothesis here
- **Critical-to-win, not generic.** Tie it to *this* metric, data, and CV, and to the
  remaining gap. "Add dropout" is weak; "group-aware OOF target encoding of `entity_id`
  should cut RMSE ~0.01 because top notebook N and arXiv:XXXX show leakage-safe TE helps on
  high-card categoricals, and our gap is concentrated on high-card rows" is a bet.
- **Grounded.** Cite the source — a top notebook, a discussion insight, or a paper from the
  science MCP. Mix three buckets: notebook/discussion-derived, literature-derived, and your
  own data/metric **insight/exploit** (leak the host allows, magic feature, metric-aware
  post-processing).
- **Falsifiable & cheap.** State the exact experiment, the control, and the Δ that would
  confirm/refute it. Prefer one-Colab-job tests.
- **Leakage-safe by design.** Every bet must be expressible without leaking test info; if it
  risks leakage (target encoding, scaling, pseudo-labeling), specify the fold-isolation now —
  the experiment stage will run the leakage gate on it.
- **Decorrelated.** Favor a portfolio that helps for *different* reasons (good ensembles
  need diverse, individually-strong models).

## Procedure
1. **Brainstorm** ~6–12 candidates across the three buckets, (re-)querying the MCP servers
   for anything metric/data-specific you're missing.
2. **Reflect / sharpen (2–3 passes):** is it likely to move *this* metric and close the
   *current* gap? leakage-safe under the dossier CV? feasible on one Colab GPU? Tighten the
   experiment and the expected Δ; drop weak/redundant ones.
3. **Estimate** `expected_gain` (metric units, honest, usually small), `confidence` (0–1),
   `effort` (S/M/L) per survivor.
4. **Record** each in the ledger (auto-ranked by `expected_gain·confidence` ÷ effort):
   ```bash
   python -m kloop.ledger add --title "group OOF target-encoding of entity_id" \
     --rationale "notebook N +0.4%; arXiv:2401.xxxxx leakage-safe TE" \
     --source notebook --refs "https://kaggle.com/...,arXiv:2401.xxxxx" \
     --expected-gain 0.01 --confidence 0.6 --effort S
   ```
   On iteration 0 add the **baseline** as the first hypothesis (the control everything is
   measured against).
5. **Plan the round and journal it** (required to close the stage):
   ```bash
   python -m kloop.ledger list --proposed          # this round's test queue, by priority
   python -m kloop.journal log --kind hypothesis_proposed \
     --decision "round <iter>: test h00xx, h00yy (top by priority)" \
     --rationale "<how these target the current gap>"
   python -m kloop.project set --stage hypothesize --status done --note "<n> hypotheses ranked"
   ```

## Output to the user
A ranked shortlist: each bet's title, one-line rationale + source, expected Δ, confidence,
effort, and why the top picks lead — and how they target the remaining gap. Note which are
decorrelated enough to ensemble later. Offer to proceed to `/kaggloop-experiment`.

## Notes
- Be honest about expected gains — most bets yield little; the loop's value is the few that
  compound. Keep refuted bets as `rejected` with a note so you don't re-try them.
- Never propose anything that violates the rules (banned external data, host-prohibited
  leaks, disallowed frameworks). Flag dual-use/leak ideas explicitly.
