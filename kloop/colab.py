"""Local side of the kaggloop <-> Google Colab compute bridge.

Heavy training runs on Colab (GPU); Claude Code orchestrates locally (macOS, no
GPU). The two sides talk through a **shared directory** — by default a folder
inside your Google Drive that Google Drive for Desktop syncs locally and that the
Colab worker mounts at ``/content/drive``. The transport is just a filesystem,
so it also works with Dropbox, a synced network share, or a git-backed dir.

Protocol (one folder per job, self-contained so the worker needs nothing else):

    $KLOOP_COLAB_QUEUE/<job_id>/
        job.json          # {job_id, run_id, competition, entrypoint, args,
                          #  requirements, timeout, gpu, created}
        code/             # snapshot of projects/<name>/code at submit time
    $KLOOP_COLAB_RESULTS/<job_id>/
        result.json       # {ok, returncode, metric, duration_s, artifacts, ...}
        run.log           # captured stdout+stderr
        artifacts/        # oof.npy, submission.csv, model files, plots, ...

This module is the local half: ``submit`` enqueues a job, ``status`` inspects the
queue/results, and ``ingest`` pulls a finished job's artifacts back into the
project's ``experiments/results/``. The worker half is ``colab/worker.py``.

All console output, code, and comments are English.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import state


def _queue_dir() -> Path:
    return Path(os.environ.get("KLOOP_COLAB_QUEUE",
                               str(state.REPO / ".kloop-colab" / "queue"))).expanduser()


def _results_dir() -> Path:
    return Path(os.environ.get("KLOOP_COLAB_RESULTS",
                               str(state.REPO / ".kloop-colab" / "results"))).expanduser()


def _resolve(run_id):
    rid = run_id or state.current_project()
    if not rid:
        print("No active project (pass --name).", file=sys.stderr)
        raise SystemExit(2)
    return rid


def submit(run_id: str, entrypoint: str, args: list[str], requirements: str,
           timeout: int, gpu: bool) -> str:
    """Enqueue a Colab job. ``entrypoint`` is relative to the project's code/ dir."""
    rid = _resolve(run_id)
    st = state.load_state(rid)
    code_dir = state.project_dir(rid) / "code"
    src = (code_dir / entrypoint)
    if not src.exists():
        print(f"entrypoint not found: {src}", file=sys.stderr)
        raise SystemExit(2)

    job_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{rid[:19]}_{Path(entrypoint).stem}"
    qdir = _queue_dir() / job_id
    (qdir / "code").mkdir(parents=True, exist_ok=True)
    # Snapshot the whole code dir so the job is self-contained.
    for f in code_dir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(code_dir)
            dest = qdir / "code" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)

    job = {
        "job_id": job_id,
        "run_id": rid,
        "competition": st.get("competition", ""),
        "entrypoint": entrypoint,
        "args": args,
        "requirements": requirements,   # path (in code/) to a requirements.txt, or ""
        "timeout": timeout,
        "gpu": gpu,
        "status": "queued",
        "created": time.strftime("%Y-%m-%d_%H-%M-%S"),
    }
    (qdir / "job.json").write_text(json.dumps(job, indent=2, ensure_ascii=False))
    print(f"job submitted: {job_id}")
    print(f"  queue: {qdir}")
    print("  It runs automatically if a Colab worker is up. "
          "If not, open colab/colab_kaggloop.ipynb.")
    return job_id


def _job_result(job_id: str) -> dict | None:
    rp = _results_dir() / job_id / "result.json"
    if rp.exists():
        try:
            return json.loads(rp.read_text())
        except json.JSONDecodeError:
            return None
    return None


def status(job_id: str | None) -> int:
    qd, rd = _queue_dir(), _results_dir()
    print(f"queue:   {qd}")
    print(f"results: {rd}")
    if job_id:
        res = _job_result(job_id)
        if res is None:
            qjob = qd / job_id / "job.json"
            stt = "queued/running" if qjob.exists() else "unknown (not submitted)"
            print(f"job {job_id}: {stt} (awaiting result)")
        else:
            print(f"job {job_id}: done ok={res.get('ok')} "
                  f"metric={res.get('metric')} rc={res.get('returncode')} "
                  f"dur={res.get('duration_s')}s")
        return 0
    # Summarize all.
    queued = sorted(p.name for p in qd.glob("*") if (p / "job.json").exists()) if qd.exists() else []
    done = sorted(p.name for p in rd.glob("*") if (p / "result.json").exists()) if rd.exists() else []
    pending = [j for j in queued if j not in done]
    print(f"submitted: {len(queued)}  / done: {len(done)}  / pending: {len(pending)}")
    for j in pending:
        print(f"  ⏳ {j}")
    for j in done[-10:]:
        res = _job_result(j) or {}
        print(f"  ✓ {j}  metric={res.get('metric')} ok={res.get('ok')}")
    return 0


def ingest(run_id: str, job_id: str | None) -> int:
    """Copy finished job artifacts into the project's results dir."""
    rid = _resolve(run_id)
    rd = _results_dir()
    dest_root = state.project_dir(rid) / "experiments" / "results"
    targets = [job_id] if job_id else [
        p.name for p in rd.glob("*") if (p / "result.json").exists()
    ]
    if not targets:
        print("No completed jobs to ingest.")
        return 0
    n = 0
    for j in targets:
        src = rd / j
        if not (src / "result.json").exists():
            print(f"  ! {j}: no result.json (not finished)")
            continue
        dest = dest_root / j
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.rglob("*"):
            if f.is_file():
                rel = f.relative_to(src)
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)
        res = _job_result(j) or {}
        print(f"  ingested: {j}  metric={res.get('metric')} -> {dest}")
        n += 1
    print(f"done: ingested {n} job result(s).")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kloop.colab")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("submit", help="enqueue a Colab job")
    ps.add_argument("--name", default=None)
    ps.add_argument("--script", required=True, help="entrypoint relative to the project code/ dir")
    ps.add_argument("--args", nargs="*", default=[], help="args passed to the script")
    ps.add_argument("--requirements", default="", help="requirements.txt path inside code/")
    ps.add_argument("--timeout", type=int, default=3600)
    ps.add_argument("--no-gpu", dest="gpu", action="store_false")
    ps.set_defaults(gpu=True,
                    func=lambda a: print(submit(a.name, a.script, a.args,
                                                a.requirements, a.timeout, a.gpu)) or 0)

    pst = sub.add_parser("status", help="show queue/results status")
    pst.add_argument("--job", default=None)
    pst.set_defaults(func=lambda a: status(a.job))

    pi = sub.add_parser("ingest", help="pull finished results into the project")
    pi.add_argument("--name", default=None)
    pi.add_argument("--job", default=None)
    pi.set_defaults(func=lambda a: ingest(a.name, a.job))

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
