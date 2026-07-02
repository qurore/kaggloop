"""Top-notebook sync — "learn from the winners first" mechanics (the iron rule).

THE IRON RULE (skills enforce it every loop): sort the competition's Code tab by
best **Public Score**, read the **top 5** notebooks, and keep **byte-deduped
local copies** under ``projects/<name>/notebooks/``. On later loops a pull that
is byte-identical to the previous download costs nothing (``UNCHANGED``); only
genuinely NEW or UPDATED notebooks are stored (the replaced version is archived
under ``_archive/`` so the delta can be diffed). The best public notebook is the
baseline the loop starts from and must beat — never start below it with
scratch-written code.

This module is mechanics only: list -> pull -> byte-compare -> manifest.
Reading the notebooks, extracting their Public Scores/techniques into
``recon.md``, and betting on top of them is the skills' (the agent's) job.
Note: the kaggle CLI/API returns the score-sorted *order* but not the score
*values* — read the values off the notebook page / Code tab and record them in
``recon.md``.

All console output, code, and comments are English.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import state
from .kaggle import _kaggle_bin

MANIFEST = "manifest.json"
TOP_DEFAULT = 5
# kernel-metadata.json is bookkeeping, not the notebook's source; exclude it
# from the update-detection hash so a pure metadata wiggle isn't an "update".
HASH_EXCLUDE = {"kernel-metadata.json"}


def _stamp() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())


def _safe_ref(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", ref.replace("/", "__"))


def _run_kaggle(args: list[str]) -> tuple[int, str]:
    kbin = _kaggle_bin()
    if not kbin:
        print("kaggle CLI not found. Run `bash scripts/setup.sh`.",
              file=sys.stderr)
        return 127, ""
    proc = subprocess.run([kbin, *args], text=True, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or "")
    return proc.returncode, proc.stdout or ""


def list_top(competition: str, sort_by: str, n: int) -> list[dict] | None:
    """Top-n public kernels of a competition, in best-Public-Score order.

    Returns [{ref,title,author,lastRunTime,totalVotes}] or None on failure.
    """
    rc, out = _run_kaggle(["kernels", "list", "--competition", competition,
                           "--sort-by", sort_by, "--page-size", str(n), "-v"])
    if rc != 0:
        return None
    lines = [ln for ln in out.splitlines() if ln.strip()]
    hdr = next((i for i, ln in enumerate(lines) if ln.startswith("ref,")), None)
    if hdr is None:
        return []  # "No kernels found" or similar
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[hdr:]))))
    return rows[:n]


def _source_hash(d: Path) -> tuple[str, list[str]]:
    """sha256 over the pulled *source* files (names + bytes), deterministic order."""
    files = sorted(p for p in d.rglob("*")
                   if p.is_file() and p.name not in HASH_EXCLUDE
                   and "_archive" not in p.relative_to(d).parts)
    h = hashlib.sha256()
    rels = []
    for p in files:
        rel = str(p.relative_to(d))
        rels.append(rel)
        h.update(rel.encode() + b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest(), rels


def _load_manifest(base: Path) -> dict:
    p = base / MANIFEST
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    return {"kernels": {}, "last_sync": None}


def _default_sort(direction: str | None) -> str:
    # "Best Public Score first": descending for maximize metrics, ascending for
    # minimize metrics (lower = better). Override with --sort-by if the listing
    # looks polluted (e.g. unscored kernels leading an ascending sort).
    return "scoreAscending" if direction == "minimize" else "scoreDescending"


def _archive_and_replace(refdir: Path, tmpdir: Path, tag: str) -> None:
    arch = refdir / "_archive" / tag
    arch.mkdir(parents=True, exist_ok=True)
    for f in list(refdir.iterdir()):
        if f.name != "_archive":
            shutil.move(str(f), str(arch / f.name))
    for f in list(tmpdir.iterdir()):
        shutil.move(str(f), str(refdir / f.name))


def sync(name: str | None, competition: str | None, top: int,
         sort_by: str | None, dest: str | None) -> int:
    iteration = None
    st: dict = {}
    if dest:
        base = Path(dest)
    else:
        n = name or state.current_project()
        if not n:
            print("No active project (pass --name or --dest).",
                  file=sys.stderr)
            return 2
        st = state.load_state(n)
        base = state.project_dir(n) / "notebooks"
        competition = competition or st.get("competition")
        iteration = st.get("iteration")
    if not competition:
        print("Competition slug unknown (pass --competition).", file=sys.stderr)
        return 2
    sort_by = sort_by or _default_sort(st.get("metric_direction"))

    listing = list_top(competition, sort_by, top)
    if listing is None:
        print("Failed to list the Code tab (check kaggle CLI / auth / slug).",
              file=sys.stderr)
        return 1
    base.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(base)
    if not listing:
        print(f"({competition}: no public notebooks found — possibly a judged/new competition)")

    now = _stamp()
    counts = {"new": 0, "updated": 0, "unchanged": 0, "failed": 0}
    to_read: list[str] = []
    tmproot = base / ".tmp"
    for rank, k in enumerate(listing, 1):
        ref = k["ref"]
        refdir = base / _safe_ref(ref)
        entry = manifest["kernels"].get(ref, {})
        tmp = tmproot / _safe_ref(ref)
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True, exist_ok=True)
        rc, _ = _run_kaggle(["kernels", "pull", ref, "-p", str(tmp), "-m"])
        if rc != 0:
            status = "pull_failed"
            print(f"  #{rank} FAILED    {ref} (pull failed — possibly made private/deleted)")
        else:
            sha, files = _source_hash(tmp)
            prev_sha = entry.get("sha256")
            if prev_sha is None and refdir.exists():
                prev_sha, _rels = _source_hash(refdir)  # adopt a pre-manifest copy
            if prev_sha is None:
                status = "new"
                refdir.mkdir(parents=True, exist_ok=True)
                for f in list(tmp.iterdir()):
                    shutil.move(str(f), str(refdir / f.name))
                entry.update(first_seen=now, first_seen_iter=iteration,
                             last_updated=now, last_updated_iter=iteration,
                             sha256=sha, files=files)
            elif sha != prev_sha:
                status = "updated"
                _archive_and_replace(refdir, tmp, f"{now}_{prev_sha[:8]}")
                entry.update(last_updated=now, last_updated_iter=iteration,
                             sha256=sha, files=files)
            else:
                status = "unchanged"
                entry.setdefault("sha256", sha)
                entry.setdefault("files", files)
                entry.setdefault("first_seen", now)
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        counts[{"pull_failed": "failed"}.get(status, status)] += 1
        entry.update(ref=ref, title=k.get("title", ""), author=k.get("author", ""),
                     rank=rank, total_votes=k.get("totalVotes", ""),
                     last_run_time=k.get("lastRunTime", ""),
                     last_checked=now, last_checked_iter=iteration,
                     last_status=status)
        manifest["kernels"][ref] = entry
        if status in ("new", "updated"):
            to_read.append(f"{ref} ({status})")
        if status != "pull_failed":
            print(f"  #{rank} {status.upper():9s} {ref} → {refdir.relative_to(base.parent)}")
    if tmproot.exists():
        shutil.rmtree(tmproot, ignore_errors=True)

    manifest["competition"] = competition
    manifest["last_sync"] = {
        "ts": now, "iteration": iteration, "competition": competition,
        "sort_by": sort_by, "top": top, "refs": [k["ref"] for k in listing],
        **counts,
    }
    (base / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    print(f"\nTop-{top} sync ({competition}, {sort_by}): "
          f"new {counts['new']} / updated {counts['updated']} / "
          f"unchanged {counts['unchanged']} / failed {counts['failed']}")
    if to_read:
        print("Deltas to read (read in full; record score + techniques in recon.md): "
              + ", ".join(to_read))
    else:
        print("No new/updated notebooks (byte-identical). No re-read needed; move recon to other axes.")
    print("Note: score values are not in the CLI output — read them off the Code tab / notebook page and record.")
    return 0


def sync_freshness(name: str, st: dict) -> tuple[bool, str]:
    """Is the top-notebook sync fresh enough to close the given stage?

    survey: a sync must exist. hypothesize: the last sync must carry the
    project's *current* iteration (i.e. re-synced this loop). Callers skip the
    check entirely for judged comps (no Public Scores on the Code tab).
    """
    p = state.project_dir(name) / "notebooks" / MANIFEST
    if not p.exists():
        return False, "top-notebook sync has not been run (no notebooks/manifest.json)."
    try:
        last = (json.loads(p.read_text()) or {}).get("last_sync") or {}
    except json.JSONDecodeError:
        return False, "notebooks/manifest.json is corrupt; re-sync."
    if st.get("stage") == "hypothesize" and last.get("iteration") != st.get("iteration"):
        return False, (f"top-notebook sync has not been run this loop (iter {st.get('iteration')}); "
                       f"last sync was iter {last.get('iteration')}.")
    return True, ""


def cmd_list(name: str | None, dest: str | None) -> int:
    if dest:
        base = Path(dest)
    else:
        n = name or state.current_project()
        if not n:
            print("No active project", file=sys.stderr)
            return 2
        base = state.project_dir(n) / "notebooks"
    m = _load_manifest(base)
    last = m.get("last_sync")
    if not last:
        print("No sync history — run `python -m kloop.notebooks sync`.")
        return 0
    print(f"last sync: {last['ts']} (iter {last['iteration']}, {last['sort_by']}, "
          f"top {last['top']}) — new {last['new']} / updated {last['updated']} / "
          f"unchanged {last['unchanged']} / failed {last['failed']}")
    for ref, e in sorted(m["kernels"].items(), key=lambda kv: kv[1].get("rank", 99)):
        print(f"  #{e.get('rank','-')} [{e.get('last_status','?'):9s}] {ref} "
              f"(checked iter {e.get('last_checked_iter')}, "
              f"updated {e.get('last_updated','-')})")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kloop.notebooks",
        description="top-5 Public-Score notebook sync (byte-deduped, the iron rule)")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("sync", help="pull the top-N best-Public-Score notebooks (dedup by bytes)")
    ps.add_argument("--name", default=None, help="project name (default: current project)")
    ps.add_argument("--competition", default=None, help="slug (default: from project state)")
    ps.add_argument("--top", type=int, default=TOP_DEFAULT)
    ps.add_argument("--sort-by", dest="sort_by", default=None,
                    help="default: scoreDescending (scoreAscending for minimize metrics)")
    ps.add_argument("--dest", default=None,
                    help="sync into this directory instead of a project (e.g. scout/shortlist)")
    ps.set_defaults(func=lambda a: sync(a.name, a.competition, a.top, a.sort_by, a.dest))

    pl = sub.add_parser("list", help="show the sync manifest")
    pl.add_argument("--name", default=None)
    pl.add_argument("--dest", default=None)
    pl.set_defaults(func=lambda a: cmd_list(a.name, a.dest))

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
