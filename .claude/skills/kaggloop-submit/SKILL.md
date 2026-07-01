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

6b. **Write the iteration learning journal (MANDATORY — the meta-learning loop).** Every
   iteration must leave an explicit, human-readable retrospective MD at
   `projects/<name>/iterations/iter_<NNN>_<slug>.md` (zero-padded, one per submit-cycle). The
   **next** iteration's `/kaggloop-hypothesize` reads the last ≤5 of these first, so write it to
   be *useful to your future self*: honest, specific, and grounded. Required sections (in order):
   ```markdown
   # iter <N> — <slug>   ·   <date>   ·   version/sub: <…>   ·   LB: <actual or "format-error/pending">
   ## What was done            # the approach + exact config/knobs changed vs last iter (be concrete)
   ## Predicted score          # the number you expected BEFORE submitting + how you derived it
   ## Actual score             # the real LB (traceable to leaderboard.jsonl / Kaggle); "blank COMPLETE"⇒verify it's not a failure
   ## Gap                      # predicted−actual AND target−actual; was the prediction right?
   ## Gap investigation        # WHY the gap — verified against real resources: public notebooks
                               #   (kernel-pull), discussions, the science MCP (arxiv/semantic-scholar),
                               #   the SDK source, a local harness repro. Cite each. No hand-waving.
   ## Next iteration — plan & resolve   # the concrete方針 for what to try/investigate next, and why
   ```
   Fill every section from real evidence (a predicted-vs-actual number with no derivation, or a
   cause with no cited source, is a failed journal). This file — not memory — is how the loop
   compounds learning across iterations.

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

## Code / simulation competitions (submission = a notebook, not a CSV) — READ FIRST

If the competition ships an **SDK / evaluation harness** in its data and you submit *code*
(an `attack.py`, an agent, a policy) rather than a `submission.csv`, the tabular flow above
does **not** map 1:1. Hard-won rules — follow them to avoid wasting the daily submission cap:

1. **Copy a currently-working, recently-scored public notebook's submission mechanics BEFORE
   writing your own.** Pull the top *non-stale* notebook (`kernel-pull`), read the `serve()` /
   output cells, and match them exactly. Reinventing the harness plumbing from the SDK alone
   is how you burn submissions on avoidable errors. (Verify scoring facts against the SDK, but
   copy the *plumbing* from a notebook that actually scored.)
2. **The version must OUTPUT the required file.** Kaggle re-runs your notebook privately with
   the hidden test set and extracts your output file (e.g. `submission.csv`). On a normal
   commit your code must still write that file or the version is **not submittable**
   ("does not output this file"). Standard pattern: write a valid placeholder, then run the
   eval server only under the rerun flag:
   ```python
   open("/kaggle/working/submission.csv","w").write("Id,Score\n...expected rows...,0.0\n")
   import ...inference_server as server
   if os.getenv("KAGGLE_IS_COMPETITION_RERUN"):
       server.<InferenceServer>().serve()   # blocks; the gateway writes the real file
   ```
   Notebook config: attach the competition dataset (`competition_sources`), GPU if the hidden
   models need it (T4), `enable_internet:false`. The notebook `id`'s slug must match the title.
3. **Reproduce the eval gateway LOCALLY with a fast/deterministic backend before every
   submission** (`run_local_gateway` / the SDK's local evaluate, `MODEL_NAMES=deterministic`
   or a small budget). Confirm it produces a **valid output file without raising** — this
   catches structural/format bugs for free instead of on a ~1–3 h hidden rerun.
4. **Beat the evaluation TIME BUDGET — the #1 cause of "Submission Format Error" here.** The
   hidden rerun replays your output against the *real* (slow) models under a per-phase wall-clock
   budget; if it exceeds it the gateway raises and writes **no valid file** → format error (a
   *blank* score, not `0.000`). Do **not** hard-code a blind output size. Use **budget-aware
   verify-and-keep**: run each candidate live during generation, track the slowest one, and stop
   before the deadline with margin — the kept count then self-adjusts to the model speed, so
   replay (same items, same speed) can never time out. Minimise per-item tool-hops (terse
   "do X once, then stop" prompts).
5. **Submit the notebook** (not a CSV): `kaggle competitions submit -c <comp> -k <user/kernel>
   -v <version> -f <outputfile>`, or the UI **⋮ → Submit to Competition → pick the version**.
   The `guard_submission` gate still applies. A **`403 CreateCodeSubmission`** that persists
   after the gate usually means the account needs **identity verification** (Persona,
   phone/webcam) — a human-only KYC step: surface it to the user and do not attempt it.
6. **A `COMPLETE` submission with a *blank* public score is usually a failure, not a zero** —
   check the Submissions page (score vs "Submission Format Error") and the leaderboard before
   recording anything. Never journal a fabricated score.

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
