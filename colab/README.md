# Colab compute bridge

kaggloop orchestrates locally (macOS, no GPU) and trains on **Google Colab** (GPU). The
two sides talk through a **shared folder** — by default a Google Drive folder that *Google
Drive for Desktop* syncs to your laptop and that the Colab notebook mounts at
`/content/drive`. The transport is just a filesystem, so Dropbox or any synced share works
too.

```
  laptop (Claude Code)                     shared Drive folder                 Colab (GPU)
  ──────────────────────                   ───────────────────                 ───────────
  kloop.colab submit   ──writes job──▶     MyDrive/kaggloop/queue/<job_id>/  ──▶ worker.py
                                                                                  runs on GPU
  kloop.colab ingest   ◀──reads result──   MyDrive/kaggloop/results/<job_id>/ ◀── writes back
```

## One-time setup

1. **Subscribe to / open Colab** and install **Google Drive for Desktop** on your laptop so
   `~/My Drive` (or `~/Google Drive/My Drive`) syncs locally.
2. Create the shared folders in Drive: `MyDrive/kaggloop/queue` and
   `MyDrive/kaggloop/results`.
3. On the laptop, point kaggloop at the synced paths (e.g. in `.env`, then `source .env`,
   or in `.claude/settings.json` → `env`):
   ```bash
   export KLOOP_COLAB_QUEUE="$HOME/Library/CloudStorage/GoogleDrive-<you>/My Drive/kaggloop/queue"
   export KLOOP_COLAB_RESULTS="$HOME/Library/CloudStorage/GoogleDrive-<you>/My Drive/kaggloop/results"
   ```
   (Path varies by OS / Drive version — use the real synced location.)
4. Put your Kaggle token where the worker can read it: copy `~/.kaggle/kaggle.json` to
   `MyDrive/kaggloop/kaggle.json` (the notebook also offers an upload prompt).
5. Open `colab_kaggloop.ipynb` in Colab, set **Runtime → GPU**, and run all cells. The
   last cell starts the polling worker; leave the tab open while a campaign runs.

## How a job flows

- **Submit (laptop):** `python -m kloop.colab submit --script train_h0003.py --timeout 5400`
  snapshots `runs/<id>/experiments/code/` into `queue/<job_id>/code/` and writes
  `queue/<job_id>/job.json`.
- **Run (Colab):** the worker claims the job, downloads+caches the competition data via the
  Kaggle API, runs `python <entrypoint>` with `KLOOP_DATA_DIR` / `KLOOP_OUT_DIR` set,
  captures logs, and writes `results/<job_id>/{result.json, run.log, artifacts/*}`.
- **Ingest (laptop):** `python -m kloop.colab ingest --job <job_id>` copies the artifacts
  into `runs/<id>/experiments/results/<job_id>/` for scoring and ensembling.

## The entrypoint contract

Each training script under `experiments/code/` must:

- read inputs from `$KLOOP_DATA_DIR` (the unzipped competition data) and write outputs to
  `$KLOOP_OUT_DIR`;
- run the campaign's cross-validation with fixed seeds and the competition metric;
- write `metric.json` (a JSON object with a `"metric"` key — the CV score the bridge
  captures — plus per-fold detail), `oof.npy` (out-of-fold preds aligned to train ids), and
  `test.npy` or `submission.csv`; and print one `{"metric": <cv>}` line to stdout as a
  fallback;
- list extra packages in a `requirements.txt` inside `code/` if needed.

## Notes

- **Limits & cost:** Colab GPUs have session time / usage limits even on paid tiers. Keep
  jobs checkpointable and sized to finish in a session; the worker enforces each job's
  `--timeout`.
- **Security:** the worker runs model-written code on the GPU box. Treat the Colab runtime
  as untrusted compute — don't store long-lived secrets there beyond the Kaggle token it
  needs, and never commit `kaggle.json`.
- **Alternative transport:** set `KLOOP_COLAB_QUEUE`/`KLOOP_COLAB_RESULTS` to any synced
  directory (Dropbox, rclone mount) and point the worker's `--queue`/`--results` at the
  same place.
