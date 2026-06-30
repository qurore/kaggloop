---
name: kaggloop-submit
description: Stage 4 of the kaggloop win-loop — finalize the round by ensembling the kept models, passing the strict data-leakage gate (enforced before any submission), submitting to Kaggle via the API, recording the public leaderboard score, then comparing the actual score to the target and deciding whether to loop again to close the gap. Use after experiment. Output a submission, a leaderboard.jsonl + progress.jsonl entry, and a loop/stop decision.
---

# Stage 4 — Submit (gate → ensemble → submit → study the gap → decide)

Convert this round's kept models into the strongest valid submission, **pass the leakage
gate** (the submission guard will block you otherwise), push to Kaggle, record what the
leaderboard says, then **compare to the target and study the gap** to decide the next move.

## Preconditions
- `kept` hypotheses with OOF + test predictions under `experiments/results/`.
  `python -m kloop.project set --stage submit --status running`. A submission-format
  reference from the dossier.

## Procedure

1. **Assemble OOF/test predictions** from the kept models (ingest any pending Colab results
   first: `python -m kloop.colab ingest`).

2. **Build the ensemble**, validated on the **same dossier CV** — the blend must beat the
   best single model on local CV, or ship the single model:
   ```bash
   python -m kloop.score blend results/<a>/artifacts/oof.npy results/<b>/artifacts/oof.npy \
       --weights 0.6 0.4 --out experiments/blend_oof.npy --metric <metric> --y-true code/y_true.npy
   ```
   For >2 models prefer `kloop.score.greedy_blend` (Caruana-style). Apply the chosen weights
   to the **test** predictions to make the submission CSV. Sanity-check it against
   `sample_submission` (columns, row count, id order, ranges, no NaNs). Journal it:
   ```bash
   python -m kloop.journal log --kind ensemble --decision "blend h0003*0.6 + h0007*0.4" \
       --rationale "blend CV 0.849 > best single 0.846; decorrelated" --evidence "experiments/blend_oof.npy"
   ```

3. **Pass the leakage gate (mandatory — the guard enforces it).** Run the automated checks
   on the *final* ensemble, affirm the checklist, and verify:
   ```bash
   python -m kloop.gate check --task <...> --train-ids code/train_ids.npy --test-ids code/test_ids.npy \
       --oof experiments/blend_oof.npy --y-true code/y_true.npy --x code/X.npy \
       --groups code/groups.npy --folds code/folds.npy
   python -m kloop.gate affirm --confirm fit_on_train_only,oof_target_encoding,no_future_info,no_banned_external,cv_matches_split,no_test_in_train
   python -m kloop.gate verify          # writes gate.json passed:true; without it, submit is BLOCKED
   python -m kloop.journal log --kind gate --decision "leakage gate passed" --rationale "no fails; checklist affirmed"
   ```

4. **Respect submission budget.** Check remaining count with
   `python -m kloop.kaggle submissions <comp>`. Submit only your best candidate(s); keep two
   final-selection slots in mind for the competition's end.

5. **Submit and log it:**
   ```bash
   python -m kloop.kaggle submit <comp> -f submissions/<name>.csv -m "iter<N>: blend cv=<cv>"
   python -m kloop.kaggle submissions <comp>      # read back the public score
   python -m kloop.project set --best-lb <public_score> --best-submission submissions/<name>.csv \
       --note "iter<N> LB=<public_score> (cv=<cv>)"
   python -m kloop.journal log --kind submission --decision "submitted <name>.csv" \
       --rationale "cv=<cv>, expected ~target" --evidence "submissions/leaderboard.jsonl"
   ```
   (Append `{file, cv, lb, message, ts}` to `submissions/leaderboard.jsonl`.)

6. **Study the gap (the core of the loop).** Compare actual to target and analyze *why*:
   ```bash
   python -m kloop.project gap --log     # appends target vs actual to progress.jsonl
   ```
   Did LB move with CV? Is the gap from underfitting, a CV↔LB mismatch (shake-up / leakage
   / distribution shift), or a metric/post-processing miss? **Never overfit to the public
   LB** — trust CV. Journal the analysis (required to close the stage):
   ```bash
   python -m kloop.journal log --kind gap_analysis \
       --decision "gap <g> remains; likely <cause>" --rationale "<the evidence>"
   ```

7. **Loop decision** (journaled as `loop_decision`):
   - **Target met** (`python -m kloop.project gap` shows `target_met: true`): finalize.
     ```bash
     python -m kloop.project set --stage submit --status done \
        --decision "target met, finalize" --decision-kind loop_decision
     python -m kloop.project set --complete --decision "final: cv=<>, lb=<>, sub=<file>" --decision-kind loop_decision
     ```
   - **Gap remains and budget left** (`iteration+1 < KLOOP_MAX_ITERATIONS`): loop, focused on
     the gap.
     ```bash
     python -m kloop.project set --stage submit --status done --iteration <N+1> \
        --decision "loop: close gap via <plan>" --decision-kind loop_decision
     ```
     then `/kaggloop-hypothesize` (carry forward kept models + the gap analysis).
   - **Budget spent, target unmet:** finalize honestly with the best submission and the gap
     recorded.

## Output to the user
A scoreboard: this round's submission(s), CV vs public LB, the new `best_lb`, **target vs
actual and the gap**, the CV↔LB read, and the decision (loop with the plan, or finalize). If
the competition is still open, remind the user to set their **final submission selection**
before the deadline.

## Notes
- `guard_submission` blocks Kaggle submits until `kloop.gate verify` passes — never bypass it.
- Submitting acts on the user's real Kaggle account; submit only the intended candidate,
  within the daily limit and the rules. Every LB number must come from a real submission in
  `leaderboard.jsonl` — never invent one.
