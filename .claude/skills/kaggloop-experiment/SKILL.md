---
name: kaggloop-experiment
description: Stage 3 of the kaggloop win-loop — implement and verify the top-ranked hypotheses by writing pipeline code, running it on Google Colab (GPU) through the kloop.colab bridge, and scoring with the dossier's cross-validation. Keeps what improves CV and prunes what doesn't, updating the hypothesis ledger and saving OOF predictions for ensembling. Use after hypothesize. Output: Colab job results, CV scores, OOF/test predictions.
---

# Stage 3 — Experiment (verify hypotheses on Colab)

Turn the top-ranked hypotheses into code, run them on **Colab** with the dossier's CV, and
let the evidence decide which bets to keep. This is the verification half of the loop —
rigorous local CV is the judge; the public LB is only a noisy sanity check.

## Preconditions
- A ranked ledger with `proposed`/`testing` hypotheses (from hypothesize) and a CV scheme
  in the dossier. `python -m kloop.run set --stage experiment --status running`.
- A **Colab worker** is running (see `colab/README.md`) and `KLOOP_COLAB_QUEUE` /
  `KLOOP_COLAB_RESULTS` point at the shared (Drive-synced) folders. Verify with
  `python -m kloop.colab status`. If no worker is available, tell the user — heavy
  training needs the GPU; only do tiny smoke tests locally.

## The pipeline contract (so jobs are reproducible and ensemble-ready)
Write code under `runs/<id>/experiments/code/`. Each training entrypoint must:
- Read input from `$KLOOP_DATA_DIR` (the worker downloads/caches the competition data
  there) and write outputs to `$KLOOP_OUT_DIR`.
- Run the **exact dossier CV**, fixed seeds, and the competition metric.
- Write to `$KLOOP_OUT_DIR`: `metric.json` containing a JSON object with a `"metric"`
  key (the CV score the bridge captures) plus per-fold scores; `oof.npy` (out-of-fold
  predictions aligned to train ids); `test.npy` or `submission.csv` (test predictions);
  and any plots. Print one `{"metric": <cv>}` line to stdout as a fallback.
- A small `requirements.txt` in `code/` if it needs packages beyond the Colab default.

Keep each entrypoint focused on **one hypothesis vs. the baseline** so the CV delta is
attributable. Reuse shared code (data loading, CV, metric) across entrypoints.

## Procedure (per hypothesis, highest priority first)
1. **Implement** the smallest code that tests the bet against the current best baseline.
   Snapshot-friendly: everything the job needs lives in `experiments/code/`.
2. **Smoke test locally** on a tiny slice if feasible (1 fold, few rows) to catch bugs
   before spending Colab time. (No GPU locally — keep it tiny.)
3. **Submit to Colab** and record the job on the hypothesis:
   ```bash
   python -m kloop.colab submit --script train_h0003.py --timeout 5400
   python -m kloop.ledger update --id h0003 --status testing --job-id <job_id>
   ```
4. **Poll, then ingest** when done:
   ```bash
   python -m kloop.colab status --job <job_id>
   python -m kloop.colab ingest --job <job_id>
   ```
   Results land in `runs/<id>/experiments/results/<job_id>/`.
5. **Judge by CV.** Compare the bet's CV to the current best (mind `metric_direction`).
   Update the ledger honestly:
   ```bash
   python -m kloop.ledger update --id h0003 --status kept     --cv-after 0.8461 \
       --notes "+0.004 CV vs baseline 0.8421, fold-stable"
   # or --status rejected with a note on why (no gain / unstable / worse)
   ```
   If a job is `buggy` (nonzero rc / no metric), read its `run.log`, fix, resubmit. If a
   bet needs the GPU but the worker is down, mark it `blocked`.
6. **Update campaign best** when CV improves, and save the OOF/test predictions for the
   ensemble stage:
   ```bash
   python -m kloop.run set --best-cv 0.8461 --note "h0003 kept: group TE"
   ```
7. Repeat for the next hypothesis. Stop the round when the queue is exhausted, returns
   diminish, or the Colab/time budget is spent.

## Tree-search mindset (AI-Scientist-v2 BFTS, lightweight)
Treat experiments as a search: branch from the current best pipeline, keep improvements,
prune dead ends, and let a strong bet spawn follow-ups (e.g. a winning feature → tune its
hyperparameters next). The ledger + `best_cv` are the frontier. Don't chase a single line;
keep a few **decorrelated** strong models alive for ensembling.

## Close the stage
```bash
python -m kloop.run set --stage experiment --status done --note "round <iter>: kept <k>, rejected <r>"
```
Summarize to `campaign.md`. Output to the user: which bets were kept/rejected with CV
deltas, the new `best_cv`, and which OOF sets are ready to ensemble. Offer `/kaggloop-submit`.

## Notes
- The PreToolUse guard blocks dangerous shell; keep all I/O under the run dir and never
  touch `kaggle.json`. Honor competition rules in code (no banned external data/leaks).
- Be honest about failures — a rejected hypothesis with a clear reason is a real result and
  prevents wasted re-tries next iteration.
