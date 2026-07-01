---
name: kaggloop-experiment
description: Stage 3 of the kaggloop win-loop — implement and verify the top-ranked hypotheses by writing pipeline code, running it on Google Colab (GPU) via the kloop.colab bridge, scoring with the dossier CV, and running the data-leakage gate on each result before keeping it. Keeps what improves CV (leak-free) and prunes the rest, updating the ledger and saving OOF predictions for ensembling. Use after hypothesize. Output Colab results, CV scores, OOF/test predictions.
---

# Stage 3 — Experiment (verify hypotheses on Colab, gate every result)

Turn the top-ranked hypotheses into code, run them on **Colab** with the dossier CV, and
let the evidence decide what to keep — but **only after the leakage gate clears each
result**. Rigorous local CV is the judge; the public LB is a noisy sanity check; a leaky CV
is worse than no CV.

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
1. **Implement** the smallest code that tests the bet against the current best baseline.
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

## Close the stage
A `hypothesis_kept`/`hypothesis_rejected` decision must be journaled (observability gate);
then:
```bash
python -m kloop.project set --stage experiment --status done --note "round <iter>: kept <k>, rejected <r>"
```
Output to the user: kept/rejected with CV deltas + gate status, the new `best_cv`, and which
OOF sets are ready to ensemble. Offer `/kaggloop-submit`.

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
