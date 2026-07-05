#!/usr/bin/env python3
"""Assemble colab_kaggloop.ipynb — a self-contained kaggloop Colab runner.

Modelled on ai-scientist's colab_runner.ipynb (self-contained cells + RUNNER_ALIVE
heartbeat), but it speaks kaggloop's `kloop.colab` bridge protocol: it embeds
worker.py's exact run_job/pending_jobs logic verbatim (so `kloop.colab ingest` reads
the results unchanged) instead of cloning the repo. Just mount Drive, drop kaggle.json,
Run all, and leave the last cell running.

Regenerate after editing worker.py:  python colab/build_colab_kaggloop.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKER = HERE / "worker.py"
OUT = HERE / "colab_kaggloop.ipynb"

# --- embed worker.py's functions verbatim (everything up to `def main`) ---
worker_src = WORKER.read_text()
cut = worker_src.index("def main(")
worker_funcs = worker_src[:cut].rstrip() + "\n"

INTRO = """# kaggloop — Colab GPU runner (`colab_kaggloop`)

Self-contained GPU worker for the kaggloop compute bridge. It watches a **Google Drive**
folder that your laptop and Colab both see, runs each training job enqueued by
`python -m kloop.colab submit` on the GPU, and writes results back for
`python -m kloop.colab ingest` to pull.

**One-time setup**
1. Runtime → Change runtime type → **GPU** (T4/L4/A100).
2. On the laptop, point kaggloop at the same Drive folder (already wired in
   `.claude/settings.json`):
   `KLOOP_COLAB_QUEUE=.../My Drive/kaggloop/queue`, `KLOOP_COLAB_RESULTS=.../My Drive/kaggloop/results`.
3. Put `kaggle.json` where this notebook can read it — either at
   `My Drive/kaggloop/kaggle.json` or via the upload prompt in the mount cell.

**Run**: Runtime → **Run all**, approve the Drive mount, and leave the last cell polling.
Parallel workers? Give each its own queue folder (`queue-a`, `queue-b`, …) — never point two
runners at one queue (Drive sync is eventual-consistent, so the atomic-rename claim can race).
"""

GPU = '''# 1. GPU sanity check
import subprocess
print(subprocess.run(["nvidia-smi"], capture_output=True, text=True).stdout or "no nvidia-smi")
try:
    import torch
    print("torch", torch.__version__, "cuda", torch.cuda.is_available(),
          torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
except Exception as e:
    print("torch not imported:", e)
'''

MOUNT = '''# 2. Mount Drive + config: point QUEUE/RESULTS at the shared kaggloop folder, set up kaggle.json.
import os, shutil
from pathlib import Path
from google.colab import drive
drive.mount("/content/drive")

# EDIT this if your bridge folder differs (must match KLOOP_COLAB_QUEUE/RESULTS on the laptop).
BRIDGE  = Path("/content/drive/MyDrive/kaggloop")
QUEUE   = BRIDGE / "queue"
RESULTS = BRIDGE / "results"
DATA    = Path("/content/kaggle_data")   # local cache for competition data (not on Drive)
for d in (QUEUE, RESULTS, DATA):
    d.mkdir(parents=True, exist_ok=True)
print("queue   =", QUEUE)
print("results =", RESULTS)

# kaggle.json: prefer one dropped in the Drive bridge; else prompt to upload. Kept in the
# session only (~/.kaggle), never written back to Drive.
kdir = Path.home() / ".kaggle"; kdir.mkdir(exist_ok=True)
src = BRIDGE / "kaggle.json"
if src.exists():
    shutil.copy(src, kdir / "kaggle.json")
    print("kaggle.json <- Drive bridge")
elif not (kdir / "kaggle.json").exists():
    from google.colab import files
    print("Upload kaggle.json:")
    up = files.upload()
    for name, data in up.items():
        (kdir / "kaggle.json").write_bytes(data)
os.chmod(kdir / "kaggle.json", 0o600)
# kaggle CLI is preinstalled on Colab; install if missing.
try:
    import kaggle  # noqa: F401
except Exception:
    subprocess.run(["pip", "install", "-q", "kaggle"], text=True)
print("config ready")
'''

RUN = '''# 4. Run the worker loop with a RUNNER_ALIVE heartbeat. Leave this cell running.
import time, traceback
from pathlib import Path

DATA = Path("/content/kaggle_data")
print("runner up; watching", QUEUE, "— leave this cell running")
while True:
    try:
        (QUEUE.parent / "RUNNER_ALIVE").write_text(str(time.time()))  # heartbeat
        for jd in pending_jobs(QUEUE):
            print("[run]", jd.name)
            try:
                run_job(jd, RESULTS, DATA)
            except Exception:
                traceback.print_exc()
    except Exception:
        traceback.print_exc()
    time.sleep(20)
'''

cells = [
    {"cell_type": "markdown", "metadata": {}, "source": INTRO.splitlines(keepends=True)},
    {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
     "source": GPU.splitlines(keepends=True)},
    {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
     "source": MOUNT.splitlines(keepends=True)},
    {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
     "source": ("# 3. kaggloop worker logic (embedded verbatim from colab/worker.py).\n"
                + worker_funcs).splitlines(keepends=True)},
    {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
     "source": RUN.splitlines(keepends=True)},
]
nb = {"cells": cells, "metadata": {"kernelspec": {"language": "python", "name": "python3",
      "display_name": "Python 3"}, "accelerator": "GPU"},
      "nbformat": 4, "nbformat_minor": 5}
OUT.write_text(json.dumps(nb, indent=1))

# sanity: every code cell compiles
import ast
bad = 0
for c in nb["cells"]:
    if c["cell_type"] != "code":
        continue
    src = "".join(c["source"])
    lines = [l for l in src.splitlines() if not l.lstrip().startswith(("!", "%"))]
    try:
        ast.parse("\n".join(lines))
    except SyntaxError as e:
        bad += 1
        print("SyntaxError:", e)
print(f"wrote {OUT}  ({len(cells)} cells, compile-clean code cells: {sum(1 for c in nb['cells'] if c['cell_type']=='code') - bad})")
