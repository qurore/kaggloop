---
name: kaggloop-hypothesize
description: Stage 2 of the kaggloop win-loop — generate, ground, and rank critical-to-win hypotheses for the chosen competition (AI-Scientist-v2 style), each a concrete, testable bet about what will move the score, grounded in the dossier's top notebooks/discussions and the academic literature. Use after survey, or at the start of each new loop iteration to plan the next round of experiments. Output: a ranked hypotheses.jsonl ledger.
---

# Stage 2 — Hypothesize (critical-to-win bets, ranked)

This is the exploratory engine, modeled on **AI-Scientist-v2's** ideate→reflect loop but
pointed at *winning a competition* instead of writing a paper. You produce a small set of
**explicit, testable hypotheses** — each one a bet that "doing X will improve the
competition score by ~Δ because <evidence>" — ranked by expected value, recorded in the
hypothesis ledger for the experiment stage to verify.

## Preconditions
- `runs/<id>/dossier.md` exists (from survey) and `state.json` has `metric` +
  `metric_direction`. `python -m kloop.run set --stage hypothesize --status running`.
- On loop iterations >0, also read what previous rounds learned: the `kept`/`rejected`
  hypotheses (`python -m kloop.ledger list`), CV/LB deltas, and any LB feedback.

## What makes a good hypothesis here
- **Critical-to-win, not generic.** Tie it to *this* metric, data, and CV. "Add dropout"
  is weak; "group-aware target encoding of `entity_id` (folds from the dossier CV) should
  cut RMSE ~0.01 because top notebook N and arXiv:XXXX show leakage-safe TE helps on
  high-card categoricals" is a bet.
- **Grounded.** Cite the source: a top notebook, a discussion insight, or a paper found
  via the science MCP. Mix three buckets:
  1. **Notebook/discussion-derived** — proven-here ideas to adopt/strengthen.
  2. **Literature-derived** — recent methods (architectures, losses, augmentation,
     pseudo-labeling, calibration, distillation) portable to one Colab GPU.
  3. **Insight/exploit** — your own read of the data/metric (leak, magic feature,
     post-processing that matches the metric, CV-vs-LB gap to exploit).
- **Falsifiable & cheap to test.** State the exact experiment, the control it's compared
  against, and the metric delta that would confirm/refute it. Prefer bets testable in one
  Colab job.
- **Decorrelated.** Favor a portfolio whose members help for *different* reasons (good
  ensembles need diverse, individually-strong models), not five flavors of one idea.

## Procedure
1. **Brainstorm** ~6–12 candidate bets across the three buckets above, reading the dossier
   and (re-)querying the MCP servers for anything metric/data-specific you're missing.
2. **Reflect / sharpen (2–3 passes).** For each: is it really likely to move *this* metric?
   Is it leakage-safe under the dossier's CV? Is it feasible on one Colab GPU in a
   reasonable time? Tighten the experiment description and the expected Δ. Drop weak or
   redundant ones.
3. **Estimate** `expected_gain` (in metric units, honest and usually small), `confidence`
   (0–1), and `effort` (S/M/L compute) for each survivor.
4. **Record** each in the ledger (ranked automatically by `expected_gain·confidence`
   discounted by effort):
   ```bash
   python -m kloop.ledger add \
     --title "group target-encoding of entity_id" \
     --rationale "notebook N +0.4%; arXiv:2401.xxxxx leakage-safe TE on high-card cats" \
     --source notebook --refs "https://kaggle.com/...,arXiv:2401.xxxxx" \
     --expected-gain 0.01 --confidence 0.6 --effort S
   ```
   Use `--source paper|notebook|discussion|insight`. Add the baseline itself as the first
   hypothesis on iteration 0 (the thing every later bet is measured against).
5. **Plan the round.** Pick the top few by priority (`python -m kloop.ledger list
   --proposed`) as the experiment queue. Mark them `testing` when handed off.
   ```bash
   python -m kloop.run set --stage hypothesize --status done --note "<n> hypotheses ranked"
   ```
   Append a summary to `campaign.md`.

## Output to the user
A ranked shortlist: each bet's title, the one-line rationale + source, expected Δ,
confidence, effort, and why the top picks lead. Note which are independent enough to
ensemble later. Offer to proceed to `/kaggloop-experiment`.

## Notes
- Be honest about expected gains — most bets yield little; the loop's value is finding the
  few that compound. Keep refuted bets in the ledger as `rejected` with a note (they stop
  you re-trying them next iteration).
- Never propose anything that violates the competition rules (banned external data, leaks
  the host prohibits, disallowed frameworks). Flag dual-use/leak ideas explicitly.
