---
name: kaggloop-submit
description: Stage 4 of the kaggloop win-loop — finalize the round by ensembling the kept models' out-of-fold predictions, building the best submission, submitting it to Kaggle via the API, recording the public leaderboard score, and deciding whether to loop again. Use after experiment. Output: submission CSV(s), leaderboard.jsonl entry, and a loop/stop decision.
---

# Stage 4 — Submit (ensemble, submit, track, decide)

Convert this round's kept models into the strongest valid submission, push it to Kaggle,
record what the leaderboard says, and decide whether another loop iteration is worth it.

## Preconditions
- The experiment stage left `kept` hypotheses with OOF + test predictions under
  `runs/<id>/experiments/results/`. `python -m kloop.run set --stage submit --status running`.
- A submission-format reference from the dossier (columns, id, sample_submission).

## Procedure

1. **Assemble OOF/test predictions** from the kept models (ingest any pending Colab
   results first: `python -m kloop.colab ingest`). Load each model's `oof.npy` (aligned to
   train ids) and `test.npy`/`submission.csv`.

2. **Build the ensemble** and validate it on the **same dossier CV** as everything else —
   the blend must beat the best single model *on local CV*, or you ship the single model:
   ```bash
   # quick weighted/rank blend of OOF predictions, scored locally:
   python -m kloop.score blend results/<a>/oof.npy results/<b>/oof.npy \
       --weights 0.6 0.4 --out experiments/blend_oof.npy \
       --metric <metric> --y-true experiments/y_true.npy
   ```
   For >2 models, prefer the greedy forward selection in `kloop.score.greedy_blend`
   (Caruana-style: robust, weights toward decorrelated strong models). Apply the chosen
   weights to the **test** predictions to make the submission. Sanity-check the file
   against `sample_submission` (columns, row count, id order, value ranges, no NaNs).

3. **Respect submission budget.** Kaggle has a **daily submission limit**; check
   `python -m kloop.kaggle submissions <comp>` for remaining count. Submit only your best
   candidate(s) — don't waste the budget on near-duplicates. Keep 2 final-selection slots
   in mind for the competition's end (typically a safe CV-best and a higher-variance pick).

4. **Submit** and log it:
   ```bash
   python -m kloop.kaggle submit <comp> -f submissions/<name>.csv \
       -m "iter<N>: blend(h0003,h0007) cv=<cv>"
   ```
   Then read back the public score (`python -m kloop.kaggle submissions <comp>`) and
   append it to the leaderboard log, and update the campaign best:
   ```bash
   python -m kloop.run set --best-lb <public_score> --best-submission submissions/<name>.csv \
       --note "iter<N> LB=<public_score> (cv=<cv>)"
   ```
   (Append `{file, cv, lb, message, ts}` to `runs/<id>/submissions/leaderboard.jsonl`.)

5. **Read the CV↔LB relationship.** Did LB move with CV? A consistent gap or a CV that
   doesn't track LB is itself information for next iteration (revisit the CV scheme,
   suspect shake-up risk, check for leakage or distribution shift). **Never overfit to the
   public LB** — trust CV.

6. **Loop decision.**
   - If the loop budget remains (`iteration+1 < KLOOP_MAX_ITERATIONS`) and there are
     promising untested bets or the LB feedback suggests a new direction:
     bump the iteration and start a new round —
     ```bash
     python -m kloop.run set --stage submit --status done --iteration <N+1> \
        --note "looping: <what to try next>"
     ```
     then `/kaggloop-hypothesize` (carry forward kept models + lessons).
   - If returns have flattened or the budget is spent: finalize.
     ```bash
     python -m kloop.run set --stage submit --status done
     python -m kloop.run set --complete --note "final: best_cv=<>, best_lb=<>, sub=<file>"
     ```

## Output to the user
A scoreboard: this round's submission(s), CV vs public LB, the new `best_lb`, the CV↔LB
read, and the decision (loop again with the plan, or finalize with the chosen final
submission). If the competition is still open, remind the user to set their **final
submission selection** on the website before the deadline.

## Notes
- The PreToolUse guard protects `kaggle.json`; never echo or upload credentials. Submitting
  is an outward-facing action against the user's Kaggle account — only submit the candidate
  you intend, with a clear message, and stay within the daily limit and competition rules.
- Every LB number must come from a real submission recorded in `leaderboard.jsonl`. Never
  invent or estimate a leaderboard score.
