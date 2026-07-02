---
name: kaggloop-experiment
description: Stage 3 of the kaggloop win-loop — implement and verify the top-ranked hypotheses by writing pipeline code (starting from the synced best-Public-Score public notebook as the baseline — the iron rule; never scratch-written code below the public floor), running it on Google Colab (GPU) via the kloop.colab bridge, scoring with the dossier CV, and running the data-leakage gate on each result before keeping it. Keeps what improves CV (leak-free) and prunes the rest, updating the ledger and saving OOF predictions for ensembling. Also verifies the round's challenge-track bet as a thin layer on top of the standard pipeline, producing the gate-clean artifacts for the mandatory second (challenge) submission. Use after hypothesize. Output Colab results, CV scores, OOF/test predictions.
---

# Stage 3 — Experiment (verify hypotheses on Colab, gate every result)

Turn the top-ranked hypotheses into code, run them on **Colab** with the dossier CV, and
let the evidence decide what to keep — but **only after the leakage gate clears each
result**. Rigorous local CV is the judge; the public LB is a noisy sanity check; a leaky CV
is worse than no CV.

## Start from the best public notebook — never from scratch (the iron rule's other half)

The campaign's first experiment (iteration 0) is **not self-written code**: it is the **top
synced public notebook** (rank #1 by Public Score under `projects/<name>/notebooks/`, from the
survey/hypothesize sync) **adapted to the pipeline contract below** — same features/models/tricks,
re-plumbed onto the dossier CV with gate artifacts and fixed seeds. Reproduce it, confirm its CV
tracks its public LB, gate it, and set it as the campaign baseline (`--best-cv`). Every later bet
is a measured delta **on top of** this baseline: first absorb everything the winners published,
then renovate for the breakthrough. And whenever a loop's sync surfaces a public notebook that
beats our current best, adapting it (or cherry-picking its edge into our pipeline) is the
top-priority experiment — losing to copy-paste is never acceptable.

## Preconditions
- A ranked ledger with `proposed`/`testing` hypotheses and a CV scheme.
  `python -m kloop.project set --stage experiment --status running`.
- A **Colab worker** running (`colab/README.md`) with `KLOOP_COLAB_QUEUE`/`_RESULTS` set.
  Verify with `python -m kloop.colab status`. No worker ⇒ tell the user; only tiny local
  smoke tests are possible without the GPU.

## The pipeline contract (reproducible + ensemble-ready + gate-able)
Write code under `projects/<name>/code/`. Each training entrypoint must:
- read inputs from `$KLOOP_DATA_DIR`, write outputs to `$KLOOP_OUT_DIR`;
- run the **exact dossier CV**, fixed seeds, the competition metric;
- write `metric.json` (a JSON object with `"metric"` = the CV score + per-fold scores),
  `oof.npy` (out-of-fold preds aligned to train ids), `test.npy` or `submission.csv`, and
  also emit the artifacts the leakage gate needs: `y_true.npy`, `folds.npy`, and (when
  relevant) `groups.npy` / `time.npy` and a small feature sample `X.npy`;
- print one `{"metric": <cv>}` line to stdout as a fallback;
- list extra packages in a `requirements.txt` in `code/` if needed.

Keep each entrypoint focused on **one hypothesis vs. the current best** so the CV delta is
attributable. Reuse shared code (data loading, CV, metric) across entrypoints.

## Procedure (per hypothesis, highest priority first)
1. **Implement** the smallest code that tests the bet against the current best baseline
   (iteration 0: the adapted top public notebook — see above; reuse its code from
   `notebooks/`, don't re-derive it).
2. **Smoke-test locally** on a tiny slice (1 fold, few rows) to catch bugs before spending
   Colab time.
3. **Submit to Colab** and tag the hypothesis:
   ```bash
   python -m kloop.colab submit --script train_h0003.py --timeout 5400
   python -m kloop.ledger update --id h0003 --status testing --job-id <job_id>
   ```
4. **Poll, then ingest:**
   ```bash
   python -m kloop.colab status --job <job_id>
   python -m kloop.colab ingest --job <job_id>     # -> projects/<name>/experiments/results/<job_id>/
   ```
5. **Run the leakage gate on the result — before trusting the CV.**
   ```bash
   python -m kloop.gate check --task <classification|regression> \
     --train-ids code/train_ids.npy --test-ids code/test_ids.npy \
     --oof experiments/results/<job_id>/artifacts/oof.npy --y-true code/y_true.npy \
     --x code/X.npy --groups code/groups.npy --folds code/folds.npy   # provide what's relevant
   ```
   A `fail` (train/test overlap, implausibly perfect OOF, single-feature leak, group/time
   contamination) means the CV is not real — **do not keep it**; fix the leak and re-run.
6. **Judge by (leak-free) CV** and update the ledger + journal honestly:
   ```bash
   python -m kloop.ledger update --id h0003 --status kept --cv-after 0.8461 \
       --notes "+0.004 CV vs baseline 0.8421, fold-stable, gate clean"
   python -m kloop.journal log --kind hypothesis_kept --decision "keep h0003 (group TE)" \
       --rationale "+0.004 CV, leakage gate clean" --evidence "results/<job_id>/metric.json"
   # or: ledger update --status rejected  +  journal kind=hypothesis_rejected with the reason
   ```
7. **Update the campaign best** when CV improves (keep OOF/test preds for ensembling):
   ```bash
   python -m kloop.project set --best-cv 0.8461 --note "h0003 kept"
   ```
8. Next hypothesis. Stop when the queue is exhausted, returns diminish, or the Colab/time
   budget is spent.

## Tree-search mindset (AI-Scientist-v2 BFTS, lightweight)
Branch from the current best pipeline, keep (gate-clean) improvements, prune dead ends, let
a strong bet spawn follow-ups. The ledger + `best_cv` are the frontier. Keep a few
**decorrelated** strong models alive for ensembling.

## The challenge track — thin verification for the second submission (every round)

One of this round's bets is the **challenge-track** hypothesis (`track=challenge` in the
ledger, marked `CH` in `kloop.ledger list` — the interdisciplinary breakthrough registered in
hypothesize). Verify it as a **thin layer on top of this round's best standard pipeline**:
reuse the data/CV/feature/metric code, run *after* the standard queue is safe, budget ≤1 extra
Colab job — and gate it like any other result. Its bar is different from the standard bets':
it feeds the round's mandatory **second (challenge) submission** in `/kaggloop-submit`, so
what it must be is **valid** — leakage-gate-clean, format-correct test predictions saved under
`experiments/results/` — not necessarily better than the standard best on CV. Upside variance
is the point; the leaderboard gives the real answer. So **keep its test/submission artifacts
even when its CV trails the standard ensemble**, and update the ledger with the honest CV.
Only a *structurally broken or leaky* challenge result is dropped — record that in the ledger
(`--status rejected --notes "<why>"`) so `/kaggloop-submit` can journal `challenge_deferred`
with the hard blocker. In judged comps, the challenge experiment is the **bold variant of the
deliverable**, judged blind with the same rubric.

## Close the stage
A `hypothesis_kept`/`hypothesis_rejected` decision must be journaled (observability gate);
then:
```bash
python -m kloop.project set --stage experiment --status done --note "round <iter>: kept <k>, rejected <r>"
```
Output to the user: kept/rejected with CV deltas + gate status, the new `best_cv`, and which
OOF sets are ready to ensemble. Offer `/kaggloop-submit`.

## Judged competitions (no CV — the deliverable is scored by the judge rubric)

If the comp is **judged / has no automated leaderboard** (survey set `scoring_mode` =
`judged`/`hybrid` and built `judge_rubric.json`), an "experiment" is not a Colab training run —
it is **producing or upgrading the deliverable** (the writeup draft + the agent / artifacts /
figures it documents) and then **scoring it with the LLM-as-Judge rubric**. Per bet:
1. **Implement the change** to the deliverable that targets the chosen weak sub-criteria.
2. **Judge it — a separate, blind, adversarial pass.** Score the current draft against the fixed
   `judge_rubric.json` anchors: quote the draft as evidence per sub-criterion, actively steelman
   its weaknesses, and (where useful) score it *relative to* a calibrated exemplar. Write the
   result to `projects/<name>/judge/iter_<NNN>.json` (per-sub-criterion raw scores + weighted
   total + concrete gap items). Judge in a **fresh pass, not in the same breath as authoring**, so
   it isn't self-flattering.
3. **Keep only if the judged total rises** (re-judge before/after; the delta must be attributable
   to this change), then update the campaign best:
   ```bash
   python -m kloop.project set --best-lb <judged_total> --note "iter<N>: <change> -> judged <total>/100"
   python -m kloop.journal log --kind hypothesis_kept --decision "keep <change>" \
       --rationale "+<Δ> judged (crit <c>: anchor↑)" --evidence "judge/iter_<NNN>.json"
   ```
   (`--best-lb` carries the judged total on the 0–100 scale in judged mode.) The data-leakage
   gate is **replaced by the judge-rubric gate**; any code/agent still gets normal correctness
   checks. For **hybrid** comps, refresh the real automated sub-score (e.g. the agent's ladder
   rating) and feed it into the rubric's performance criterion before computing the total.

## Code / simulation competitions (submission is code, not a CSV)
If the comp ships an **SDK / evaluation harness** and you submit code (an attack/agent/policy):
- **Reproduce the eval harness locally first** with a fast/deterministic backend (the SDK's
  local evaluate or `run_local_gateway`, `MODEL_NAMES=deterministic` / a tiny budget). Your
  "CV" is (a) offline unit-tests of the exact scoring/predicate code and (b) that the harness
  produces a **valid output file without raising**. A live LLM backend may be unavailable
  locally, so treat local runs as *structural* checks; the real score needs the hidden rerun.
- The hidden rerun replays your output against the **real (slow) models under a per-phase time
  budget** — a blind/static output size **times out → "Submission Format Error"**. Design for
  it here: **budget-aware verify-and-keep** (run each candidate live, track the slowest, stop
  before the deadline) so the workload self-limits; minimise per-item tool-hops. See
  `/kaggloop-submit` → "Code / simulation competitions" for the full submission mechanics.

## Notes
- The PreToolUse guard blocks dangerous shell and protects the append-only journal; keep all
  I/O under `projects/<name>/` and never touch `kaggle.json`.
- A rejected hypothesis with a clear reason is a real result — record it; it prevents wasted
  re-tries next iteration.
