---
name: kaggloop-submit
description: Stage 4 of the kaggloop win-loop — finalize the round by ensembling the kept models, passing the strict data-leakage gate (enforced before any submission), submitting to Kaggle via the API — the standard ensemble AND the round's challenge-track submission (the dual-submission mandate, enforced at stage close) — recording the public leaderboard scores, comparing the actual score to the target, running the results-driven pipeline self-improvement pass (skills/hooks/CLAUDE.md may be upgraded only when the realized score improved), and deciding whether to loop again to close the gap. Use after experiment. Output two submissions (main + challenge), a leaderboard.jsonl + progress.jsonl entry, a self-improvement log entry, and a loop/stop decision.
---

# Stage 4 — Submit (gate → ensemble → submit → study the gap → decide)

Convert this round's kept models into the strongest valid submission, **pass the leakage
gate** (the submission guard will block you otherwise), push to Kaggle, record what the
leaderboard says, then **compare to the target and study the gap** to decide the next move.

**Both of this round's two submissions must attempt a NEW improvement — never a defensive
resubmission of a past best (the two-way-door principle).** Submission **#1 (primary)** is this
loop's **highest-confidence new improvement** — the kept, gap-closing bets applied on top of the
current best, a genuine measured step forward, *not* a prior iteration's model re-submitted to
guard the score. Submission **#2 (challenge)** is the low-confidence, high-variance home-run swing
(step 5b). Because a submission is a **reversible door** — every earlier iteration's models and
submissions are kept, Kaggle holds two final-selection slots, and a worse LB this round never
erases a better earlier one — a bet that fails just means you **roll back and restart from the
previous iteration**. The downside is bounded and undoable, so **always be aggressive: neither
submission may be a score-protecting rehash.**

## Preconditions
- `kept` hypotheses with OOF + test predictions under `experiments/results/`.
  `python -m kloop.project set --stage submit --status running`. A submission-format
  reference from the dossier.

## Judged competitions (no CSV — the judge-rubric gate, enforced) — READ FIRST

If survey set `scoring_mode` = `judged` / `hybrid` (a human-scored **Writeup**; no leaderboard),
the tabular flow below (ensemble → leakage gate → `kaggle submit` CSV) does **not** apply. Instead:

1. **Assemble the final deliverable** — the ≤word-limit **Kaggle Writeup** + its required
   attachments (media/figures, and for an agent challenge the agent/deck it documents), matching
   the Submission Requirements exactly.
2. **Judge-rubric gate (enforced — replaces the leakage gate).** Run a final **blind, adversarial**
   judging pass over the assembled deliverable against `judge_rubric.json`; write
   `judge/iter_<NNN>.json` (per-sub-criterion scores + quoted evidence + weighted total). Record
   the realized score and study the gap on it:
   ```bash
   python -m kloop.project set --best-lb <judged_total> --best-submission <writeup/draft path> \
       --note "iter<N> judged=<total>/100"
   python -m kloop.project gap --log        # target(rubric) vs judged actual — the compass
   python -m kloop.journal log --kind gate --decision "judge-rubric gate: judged=<total>/100" \
       --rationale "scored vs fixed anchors; weakest crit <c>=<...>; evidence in judge/iter_<NNN>.json"
   ```
   **Do not finalize** without a primary-source `judge_rubric.json` **and** a fresh
   `judge/iter_<NNN>.json` for this iteration — that is the enforced quality gate for judged comps.
2b. **The challenge deliverable (the dual-submission mandate, judged form).** Judged rounds
   ship a challenge too: the challenge-track bet becomes a **bold, interdisciplinary variant or
   extension of the deliverable** (a section/demo/artifact importing a mechanism from a foreign
   field). Judge it blind against the same rubric, write `judge/iter_<NNN>_challenge.json`, and
   journal `--kind challenge_submission` (or `--kind challenge_deferred` with the hard
   blocker) — the stage will not close without one of the two. The better-scoring variant
   becomes the writeup candidate and `--best-lb` carries its total.

3. **The human submits the Writeup on the Kaggle website** (New Writeup → attach assets → pick a
   Track → **Submit**) before the deadline — the one manual gate (like scout). There is no
   `kaggle submit` CSV and `guard_submission` does not fire; **never** fabricate a leaderboard
   number for a judged comp.
4. **Then continue at 6b/6c/7 below** — write the mandatory **iteration journal** (predicted vs
   judged, the per-criterion gap + its cause with cited sources, next plan), run the
   **results-driven self-improvement pass** (the judged rubric total recorded via `--best-lb`
   feeds `kloop.selfimprove check` exactly like a leaderboard score), and make the loop
   decision on the judged gap: loop back to `hypothesize` on the weakest-weighted criteria, or
   finalize when the target rubric score is met or the budget is spent.

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

4. **Respect submission budget.** The daily cap lives in project state
   (`max_daily_submissions` — set during survey via `python -m kloop.kaggle limits <comp>
   --save`); count today's used slots with `python -m kloop.kaggle submissions <comp>`. A round
   ships **two** submissions — the main ensemble (step 5) plus the challenge submission (step
   5b) — so it wants two remaining slots; the **main sub always goes first** when the budget is
   tight. Keep two final-selection slots in mind for the competition's end.

5. **Submit and log it:**
   ```bash
   python -m kloop.kaggle submit <comp> -f submissions/<name>.csv -m "iter<N>: blend cv=<cv>" \
       --watch                                    # polls until scored; prints scoring_seconds
   python -m kloop.project set --best-lb <public_score> --best-submission submissions/<name>.csv \
       --note "iter<N> LB=<public_score> (cv=<cv>)"
   python -m kloop.journal log --kind submission --decision "submitted <name>.csv" \
       --rationale "cv=<cv>, expected ~target" --evidence "submissions/leaderboard.jsonl"
   ```
   (Append `{file, cv, lb, message, track: "standard", scoring_seconds, ts}` to
   `submissions/leaderboard.jsonl`. `scoring_seconds` — how long Kaggle took to score the
   submission — comes from the `--watch` output (or `python -m kloop.kaggle watch <comp>` after
   the fact); poll-interval accuracy is fine, and `null` when the transition wasn't observed —
   e.g. a code-comp rerun scored overnight.)

5b. **The challenge submission (mandatory second submission — enforced at stage close).** Every
   round also ships the **challenge-track** artifact verified in `/kaggloop-experiment` (the
   interdisciplinary breakthrough bet — `kloop.ledger list` marks it `CH`). After the main
   submission is in, re-run the leakage gate on the challenge artifacts (`gate check` on its
   OOF/preds → `affirm` → `verify` — it is a different model; its gate run must be its own),
   then submit and journal it:
   ```bash
   python -m kloop.kaggle submit <comp> -f submissions/<name>_challenge.csv \
       -m "iter<N> CHALLENGE: <the bet> cv=<cv>" --watch    # prints scoring_seconds too
   python -m kloop.journal log --kind challenge_submission \
       --decision "challenge sub <file> LB=<score> (main LB=<score>)" \
       --rationale "<the breakthrough bet + what the LB answered>" \
       --evidence "submissions/leaderboard.jsonl"
   ```
   Append it to `submissions/leaderboard.jsonl` with `track: "challenge"` (+ its
   `scoring_seconds`, as in step 5). `--best-lb` /
   `--best-submission` take **whichever of the two submissions scored better** — when the
   challenge sub wins, the leapfrog worked: promote it to next round's standard baseline.
   Only a **hard blocker** — zero remaining daily submissions, a gate-failing / structurally
   broken challenge artifact (rejected in the ledger with the reason), the deadline — may skip
   it, and that skip must be journaled honestly:
   ```bash
   python -m kloop.journal log --kind challenge_deferred --rationale "<the hard blocker>" \
       --decision "challenge submission deferred"
   ```
   `kloop.project set` **refuses to close this stage without one of the two records**
   (`challenge_submission` or `challenge_deferred`) for this iteration — never game the
   deferral: "CV was worse than the main sub" is NOT a blocker (upside variance is the point).

6. **Study the gap (the core of the loop).** Compare actual to target and analyze *why*:
   ```bash
   python -m kloop.project gap --log     # appends target vs actual to progress.jsonl
   python -m kloop.standing snapshot --note "iter<N>: <sub>"   # append our score vs the live
       # medal landscape (top score + gold/silver/bronze cutoff scores, our rank & medal) to
       # projects/<name>/standing.jsonl — one stacked record per iteration. Pass --name when
       # multiple projects run concurrently (current_project is a shared cache).
   ```
   Read the standing: how far is our realized score from the **bronze/silver/gold lines** and
   from `top`? Did LB move with CV? Is the gap from underfitting, a CV↔LB mismatch (shake-up /
   leakage / distribution shift), or a metric/post-processing miss? **Compare the two tracks:**
   did the challenge submission beat the main one (leapfrog → promote it to next round's
   baseline), land close (the mechanism has signal → sharpen it next round), or crater (retire
   it and pick a fresh challenge axis)? **And check the public
   floor:** is our realized score still below the best public notebook's Public Score (the synced
   top-5 — `python -m kloop.notebooks list` + `recon.md`)? Below the floor, the gap analysis must
   explain *why we underperform code anyone can fork*, and closing to that baseline (adapt it —
   it's local) is next loop's #1 bet before any exotic idea. **Never overfit to the public
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
   ## Gap investigation        # WHY the gap — verified against real resources: the synced top-5
                               #   notebooks (projects/<name>/notebooks/), discussions, the science
                               #   MCP (arxiv/semantic-scholar), the SDK source, a local harness
                               #   repro. Cite each. No hand-waving. Include: above or below the
                               #   best public notebook's score, and why.
   ## Challenge track          # the 2nd (challenge) submission: the bet, its LB vs the main sub,
                               #   verdict (leapfrog → new baseline / signal → sharpen / retire);
                               #   or the journaled challenge_deferred hard blocker
   ## Next iteration — plan & resolve   # the concrete plan for what to try/investigate next, and why
   ```
   Fill every section from real evidence (a predicted-vs-actual number with no derivation, or a
   cause with no cited source, is a failed journal). This file — not memory — is how the loop
   compounds learning across iterations.

6c. **Pipeline self-improvement (results-driven — the CHECK runs every loop, the EDIT only on
   real improvement).** The pipeline upgrades itself, but strictly on results-ism: only a *realized*
   score improvement can trigger edits. After `gap --log` (and the iteration journal), run:
   ```bash
   python -m kloop.selfimprove check      # pass --name when multiple projects run concurrently
   ```
   - **`improved: false` → touch nothing.** Log the skip and move on:
     `python -m kloop.selfimprove log --action no_improvement --analysis "<1 line why>"`.
     If the *previous* loop's entry (`kloop.selfimprove list`) shows pipeline edits and this
     round regressed, treat them as regression suspects: restore the prior content (`git diff` /
     `git checkout -- <file>`, or Edit back) and log `--action reverted`.
   - **`improved: true` (especially `significant: true`) → success retrospective first.** From
     the ledger, `experiments/results/` and the journal, identify *which bet/lever caused the
     delta* (cite the evidence) and add a short "What worked & why" note to this iteration's
     journal (6b). Then ask: **is there a generalizable *process* lesson** — something that would
     help *any* competition, not just this one? Competition-specific tricks stay in `recon.md` /
     the journal, never in the shared pipeline.
   - **If a generalizable lesson exists, edit the pipeline directly** — `.claude/skills/**`,
     `.claude/hooks/**`, `CLAUDE.md` — via the Edit/Write tools (pre-authorized; no approval
     prompt). Read `kloop.selfimprove list` first so you never silently re-apply an idea a past
     loop reverted. Keep diffs small and surgical; preserve each SKILL.md's frontmatter.
     **Invariants you may never weaken:** the scout human gate, `guard_submission`'s
     gate-before-submit enforcement, the leakage / judge-rubric gate requirements, journal
     append-only enforcement, autopilot bounds, "never fabricate scores".
   - **After editing any hook:** `python -m kloop.selfimprove hookcheck` must pass (syntax +
     smoke-run of every hook). A broken hook is worse than no improvement — restore immediately
     if it fails. New hooks need `settings.json` wiring, which is out of self-edit scope:
     propose that to the human via the journal instead.
   - **Log the outcome — mandatory every loop, whatever happened:**
     ```bash
     python -m kloop.selfimprove log --action improved_and_changed \
         --analysis "<what worked + the distilled lesson>" --files "<comma-separated files>" \
         --rationale "<why it generalizes>" --delta <delta> --gap-closed-frac <frac>
     python -m kloop.journal log --kind self_improve --decision "<changed X | no change | skip>" \
         --rationale "<evidence>"
     ```
     (`--action improved_no_change` when the score improved but nothing generalizable emerged.)

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
     then `/kaggloop-hypothesize` (carry forward kept models + the gap analysis; its re-recon
     reviews the small-start board — promote/defer/drop each open candidate from this round's
     probes, enforced).
   - **Budget spent, target unmet:** finalize honestly with the best submission and the gap
     recorded.

## Code / simulation competitions (submission = a notebook, not a CSV) — READ FIRST

If the competition ships an **SDK / evaluation harness** in its data and you submit *code*
(an `attack.py`, an agent, a policy) rather than a `submission.csv`, the tabular flow above
does **not** map 1:1. Hard-won rules — follow them to avoid wasting the daily submission cap:

1. **Copy a currently-working, recently-scored public notebook's submission mechanics BEFORE
   writing your own.** The top-5 by Public Score are already synced locally
   (`projects/<name>/notebooks/` — the iron rule; `python -m kloop.notebooks sync` refreshes,
   byte-deduped): read the best *non-stale* one's `serve()` / output cells and match them
   exactly. Reinventing the harness plumbing from the SDK alone
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
   hidden rerun replays your output against the *real* (slow) models under a **per-phase** wall-clock
   budget; if any phase exceeds it the gateway raises and writes **no valid file** → format error (a
   *blank* score, not `0.000`). Do **not** hard-code a blind output size. Use **budget-aware
   verify-and-keep**: run each candidate live during generation, track the slowest one, stop early,
   and keep only those that fire — the kept count self-sizes to the model's speed.
   **CRITICAL nuance (this bites even a "safe" verify-and-keep):** *filling to the deadline is NOT
   safe.* Generation and each replay are **separate per-phase budgets**, and replay runs **once per
   evaluation slice** (e.g. public AND private guardrail; the private/held-out one can be slower).
   Because replay re-runs the *same* kept list at ~the same speed, if generation consumes ~the full
   budget then replay has no headroom and times out. So **fill only a FRACTION of the phase budget**
   (start ~0.7–0.8) with a generous absolute margin, and use **uniform-timing candidates**
   (single-action; avoid slow multi-message chains that skew the slowest-time estimate). Minimise
   per-item tool-hops (terse "do X once, then stop" prompts). *If the eval AVERAGES multiple
   backends of different speeds, this per-backend self-sizing is exactly what beats a static count
   (the fast backend fills far more).* Bank a proven-safe **static** submission first, then push the
   fill fraction up across iterations.
5. **Submit the notebook** (not a CSV): `kaggle competitions submit -c <comp> -k <user/kernel>
   -v <version> -f <outputfile>`, or the UI **⋮ → Submit to Competition → pick the version**.
   The `guard_submission` gate still applies. A **`403 CreateCodeSubmission`** that persists
   after the gate usually means the account needs **identity verification** (Persona,
   phone/webcam) — a human-only KYC step: surface it to the user and do not attempt it.
   **Exact filename precondition:** some file-based comps enforce a fixed submission filename
   (e.g. `submission.zip`); a differently-named upload → **`400 FAILED_PRECONDITION`
   "Submission files must be named …"** (not a gate/auth error). Copy your artifact to the
   required name and submit that (the required name is in the dossier/`competition.json`
   `submission.format`). Confirmed on neurogolf-2026: `iter003_merge.zip` 400s, `submission.zip` works.
6. **A `COMPLETE` submission with a *blank* public score is usually a failure, not a zero** —
   check the Submissions page (score vs "Submission Format Error") and the leaderboard before
   recording anything. Never journal a fabricated score.
7. **Adapt the leakage gate honestly** (it still gates the submit). The mandatory tabular
   detectors (`train_test_overlap`, `oof_sanity`) need arrays; map them to the comp's *real*
   overfit risk — usually the **public→private / held-out eval split** — and generate small,
   truthful artifacts (disjoint dev-vs-holdout ids; a realistic *partial*-success "oof" that is
   NOT implausibly perfect) so the checks run and pass for real reasons. Affirm the checklist
   only where genuinely true; never game it.
8. **Local harness deps + env:** to reproduce the SDK/gateway locally you'll usually need its
   requirements (`pydantic`, `gymnasium`, `polars`, `pyarrow`, `grpcio`, …) — install them into
   the project venv. Set realistic **expectations from the leaderboard**: check the top teams'
   *submission counts* — a big number (dozens+) means an iteration-heavy comp where no one
   one-shots the target; plan for many tuned submissions, and bank valid scores early.
9. **The dual-submission mandate applies here too.** The challenge-track bet ships as its own
   notebook version (e.g. `iter<N>-challenge`), submitted after the main version when the
   budget allows; journal `challenge_submission` / `challenge_deferred` exactly as in step 5b.

## Output to the user
A scoreboard: this round's **two submissions (main + challenge)** with CV vs public LB each,
which track won, the new `best_lb`, **target vs actual and the gap**, the CV↔LB read, the
**self-improvement outcome** (files changed + lesson, or "no improvement → no change"), and
the decision (loop with the plan, or finalize).
If the competition is still open, remind the user to set their **final submission selection**
before the deadline.

## Notes
- `guard_submission` blocks Kaggle submits until `kloop.gate verify` passes — never bypass it.
- Submitting acts on the user's real Kaggle account; submit only the intended candidate,
  within the daily limit and the rules. Every LB number must come from a real submission in
  `leaderboard.jsonl` — never invent one.
- Self-improvement is results-gated: no realized score improvement ⇒ no pipeline edits, ever.
  Every check/edit/skip/revert is recorded in `.claude/self-improvements.jsonl` (append-only)
  plus a `self_improve` journal entry, so the pipeline's own evolution stays auditable.
