#!/usr/bin/env python3
"""kaggloop Colab worker — the GPU half of the compute bridge.

Runs inside a Google Colab notebook (GPU runtime). It watches a shared
directory (a Google Drive folder that both your laptop and Colab can see),
picks up jobs enqueued locally by ``kloop.colab``, runs each training
entrypoint on the GPU, and writes results back for the laptop to ingest.

One job folder is self-contained::

    $QUEUE/<job_id>/job.json   {job_id, run_id, competition, entrypoint, args,
                               requirements, timeout, gpu, ...}
    $QUEUE/<job_id>/code/      snapshot of the campaign's experiments/code

The worker, per job:
  1. claims it (renames job.json -> job.running so it isn't double-run),
  2. ensures the competition data is downloaded+unzipped to a cached data dir
     (via the kaggle API — Colab has the bandwidth and the GPU),
  3. runs ``python <entrypoint> [args]`` with cwd = the job's code dir and
     env KLOOP_DATA_DIR / KLOOP_OUT_DIR set, capturing stdout+stderr,
  4. collects the metric (a ``{"metric": ...}`` stdout line or out/metric.json),
  5. writes $RESULTS/<job_id>/{result.json, run.log, artifacts/*}.

Console output is Japanese; code/comments are English.

Usage (inside Colab, after mounting Drive and uploading kaggle.json)::

    python worker.py --queue /content/drive/MyDrive/kaggloop/queue \
                     --results /content/drive/MyDrive/kaggloop/results \
                     --data /content/kaggle_data --once   # or --loop
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path


def log(msg: str) -> None:
    print(f"[worker {time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- data

def ensure_competition_data(competition: str, data_root: Path) -> Path:
    """Download + unzip a competition's data once, cached under data_root/<comp>."""
    dest = data_root / competition
    if dest.exists() and any(dest.iterdir()):
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    if not competition:
        log("コンペ未指定のためデータDLをスキップします。")
        return dest
    log(f"コンペデータをダウンロード中: {competition}")
    rc = subprocess.run(
        ["kaggle", "competitions", "download", "-c", competition, "-p", str(dest)],
        text=True,
    ).returncode
    if rc != 0:
        log("✗ データのダウンロードに失敗（ルール同意 / kaggle.json を確認）。")
        return dest
    for z in dest.glob("*.zip"):
        log(f"展開中: {z.name}")
        with zipfile.ZipFile(z) as zf:
            zf.extractall(dest)
    return dest


# --------------------------------------------------------------------------- run

def _find_metric(stdout: str, out_dir: Path):
    # Prefer out/metric.json; fall back to the last {"metric": ...} stdout line.
    mj = out_dir / "metric.json"
    if mj.exists():
        try:
            obj = json.loads(mj.read_text())
            if isinstance(obj, dict) and "metric" in obj:
                return obj
        except json.JSONDecodeError:
            pass
    found = None
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "metric" in obj:
                found = obj
    return found


def run_job(job_dir: Path, results_root: Path, data_root: Path) -> None:
    job = json.loads((job_dir / "job.json").read_text())
    job_id = job["job_id"]
    log(f"ジョブ開始: {job_id}  (entry={job['entrypoint']})")

    # Claim it so a second worker / re-run won't pick it up.
    running = job_dir / "job.running"
    try:
        (job_dir / "job.json").rename(running)
    except OSError:
        log("既に処理中のジョブのようです。スキップします。")
        return

    out_dir = results_root / job_id
    art_dir = out_dir / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    code_dir = job_dir / "code"

    data_dir = ensure_competition_data(job.get("competition", ""), data_root)

    # Optional per-job requirements.
    req = job.get("requirements")
    if req:
        req_path = code_dir / req
        if req_path.exists():
            log(f"pip install -r {req}")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                            "-r", str(req_path)], text=True)

    env = dict(os.environ)
    env["KLOOP_DATA_DIR"] = str(data_dir)
    env["KLOOP_OUT_DIR"] = str(art_dir)

    cmd = [sys.executable, job["entrypoint"], *job.get("args", [])]
    t0 = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd, cwd=str(code_dir), env=env, text=True,
            capture_output=True, timeout=int(job.get("timeout", 3600)),
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        rc = -1
        out = e.stdout or ""
        err = (e.stderr or "") + f"\n[worker] TIMEOUT after {job.get('timeout')}s"
    dur = time.time() - t0

    (out_dir / "run.log").write_text(
        f"$ {' '.join(cmd)}\n# cwd={code_dir}\n# rc={rc} dur={dur:.1f}s\n"
        f"\n----- STDOUT -----\n{out or ''}\n----- STDERR -----\n{err or ''}"
    )

    metric = _find_metric(out or "", art_dir)
    is_buggy = rc != 0 or timed_out or metric is None
    artifacts = sorted(str(p.relative_to(out_dir)) for p in art_dir.rglob("*") if p.is_file())
    result = {
        "job_id": job_id,
        "run_id": job.get("run_id"),
        "ok": not is_buggy,
        "is_buggy": is_buggy,
        "returncode": rc,
        "timed_out": timed_out,
        "duration_s": round(dur, 1),
        "metric": metric,
        "artifacts": artifacts,
        "stderr_tail": (err or "")[-1000:],
        "finished": time.strftime("%Y-%m-%d_%H-%M-%S"),
    }
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    # Mark the queue job done.
    try:
        running.rename(job_dir / "job.done")
    except OSError:
        pass
    status = "✓ 成功" if not is_buggy else "✗ 失敗(buggy)"
    log(f"ジョブ終了: {job_id}  {status}  metric={metric}  ({dur:.0f}s)")


def pending_jobs(queue_root: Path):
    if not queue_root.exists():
        return []
    return sorted(d for d in queue_root.iterdir()
                  if d.is_dir() and (d / "job.json").exists())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kaggloop-worker")
    p.add_argument("--queue", required=True)
    p.add_argument("--results", required=True)
    p.add_argument("--data", default="/content/kaggle_data")
    p.add_argument("--once", action="store_true", help="drain current queue then exit")
    p.add_argument("--loop", action="store_true", help="keep polling for new jobs")
    p.add_argument("--interval", type=int, default=20, help="poll seconds in --loop")
    args = p.parse_args(argv)

    # Resolve to absolute paths: jobs run with cwd = the job's code dir, so any
    # relative queue/results/data path would otherwise resolve against the wrong
    # directory (and KLOOP_OUT_DIR would point somewhere that doesn't exist).
    queue = Path(args.queue).resolve()
    results = Path(args.results).resolve()
    data = Path(args.data).resolve()
    results.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)

    log(f"ワーカー起動  queue={queue}  results={results}")
    if not (args.once or args.loop):
        args.loop = True

    while True:
        jobs = pending_jobs(queue)
        if jobs:
            log(f"{len(jobs)} 件の新規ジョブを検出。")
            for jd in jobs:
                try:
                    run_job(jd, results, data)
                except Exception as e:  # never let one bad job kill the worker
                    log(f"✗ ジョブ実行中に例外: {jd.name}: {e}")
        elif args.once:
            log("キューは空です。--once のため終了します。")
        if args.once:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
