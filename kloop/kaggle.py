"""Thin wrappers around the official ``kaggle`` CLI.

These are mechanics only — they shell out to ``kaggle`` and surface its output so
the skills (i.e. you, the agent) can read competition data, top kernels,
discussions metadata, leaderboards, and push submissions. The intelligence
(which competition, which notebook to learn from, what to submit) lives in the
skills, not here.

Requirements (handled by ``scripts/setup.sh`` / documented in the README):
  * ``pip install kaggle`` (we install it into ``.venv``)
  * Kaggle API token at ``~/.kaggle/kaggle.json`` (chmod 600), or the
    ``KAGGLE_USERNAME`` / ``KAGGLE_KEY`` environment variables.
  * You must *accept each competition's rules on the website* before the API will
    let you download data or submit — the CLI cannot click that button for you.

All console output, code, and comments are English.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from . import state


def _kaggle_bin() -> str | None:
    # Prefer the repo .venv's kaggle, fall back to PATH.
    venv = state.REPO / ".venv" / "bin" / "kaggle"
    if venv.exists():
        return str(venv)
    return shutil.which("kaggle")


def _run(args: list[str], capture: bool = False) -> int:
    kbin = _kaggle_bin()
    if not kbin:
        print("kaggle CLI not found. Run `bash scripts/setup.sh` or "
              "`pip install kaggle`, and place ~/.kaggle/kaggle.json.",
              file=sys.stderr)
        return 127
    cmd = [kbin, *args]
    print(f"$ kaggle {' '.join(args)}")
    try:
        proc = subprocess.run(cmd, text=True,
                              capture_output=capture)
    except FileNotFoundError:
        print("kaggle CLI failed to run.", file=sys.stderr)
        return 127
    if capture:
        sys.stdout.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
    rc = proc.returncode
    if rc != 0:
        print(f"kaggle command failed (rc={rc}). "
              f"Check that you accepted the competition rules and your credentials are valid.",
              file=sys.stderr)
    return rc


# --------------------------------------------------------------------------- ops

def competitions_list(search: str = "", category: str = "", sort_by: str = "") -> int:
    args = ["competitions", "list"]
    if search:
        args += ["-s", search]
    if category:
        args += ["--category", category]
    if sort_by:
        args += ["--sort-by", sort_by]
    args += ["-v"]  # CSV, easier for the agent to parse
    return _run(args)


def competition_files(competition: str) -> int:
    return _run(["competitions", "files", competition, "-v"])


def download(competition: str, path: str = "", file: str = "") -> int:
    args = ["competitions", "download", competition]
    if file:
        args += ["-f", file]
    if path:
        args += ["-p", path]
    return _run(args)


def leaderboard(competition: str, download_to: str = "") -> int:
    if download_to:
        return _run(["competitions", "leaderboard", competition, "-d", "-p", download_to])
    return _run(["competitions", "leaderboard", competition, "-s"])  # --show top of LB


def kernels(competition: str, sort_by: str = "scoreDescending", n: int = 20,
            language: str = "", kernel_type: str = "") -> int:
    """List public notebooks attached to a competition (best Public Score first
    by default — use scoreAscending for minimize metrics, voteCount for buzz)."""
    args = ["kernels", "list", "--competition", competition,
            "--sort-by", sort_by, "--page-size", str(n), "-v"]
    if language:
        args += ["--language", language]
    if kernel_type:
        args += ["--kernel-type", kernel_type]
    return _run(args)


def kernel_pull(ref: str, path: str) -> int:
    """Download a public notebook's source + metadata for study."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return _run(["kernels", "pull", ref, "-p", path, "-m"])


def submit(competition: str, file: str, message: str, watch: bool = False,
           poll: int = 30, timeout: int = 3600) -> int:
    rc = _run(["competitions", "submit", competition, "-f", file, "-m", message])
    if rc == 0 and watch:
        # Measure how long Kaggle takes to score it (poll-window accuracy).
        return watch_scoring(competition, ref=None, poll=poll, timeout=timeout)
    return rc


def submissions(competition: str) -> int:
    return _run(["competitions", "submissions", competition, "-v"])


# ------------------------------------------------- python-API helpers (read-only)

def _api():
    """Authenticated Kaggle python API (lazy import; same package as the CLI)."""
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    api.authenticate()
    return api


def limits(competition: str, save: bool = False, name: str | None = None) -> int:
    """Print a competition's submission limits (max daily submissions etc.).

    With --save, also record max_daily_submissions into the project's state.json
    so every project carries its competition's daily submission cap.
    """
    import json as _json
    try:
        resp = _api().competitions_list(search=competition)
    except Exception as e:
        print(f"kaggle API error while fetching competition info: {e}", file=sys.stderr)
        return 2
    comps = getattr(resp, "competitions", None) or []
    hit = next((c for c in comps
                if str(getattr(c, "ref", "")).rstrip("/").split("/")[-1] == competition), None)
    if hit is None:
        print(f"competition {competition!r} not found via the Kaggle API "
              f"(check the slug, or read the cap off the My Submissions page).",
              file=sys.stderr)
        return 2
    out = {
        "competition": competition,
        "max_daily_submissions": getattr(hit, "max_daily_submissions", None),
        "max_team_size": getattr(hit, "max_team_size", None),
        "deadline": str(getattr(hit, "deadline", "") or ""),
    }
    if save:
        pname = name or state.current_project()
        if not pname:
            print("--save: no active project (pass --name).", file=sys.stderr)
            return 2
        st = state.load_state(pname)
        st["max_daily_submissions"] = out["max_daily_submissions"]
        state.save_state(pname, st)
        state.append_project_log(
            pname, f"max daily submissions = {out['max_daily_submissions']} (Kaggle API)")
        out["saved_to"] = pname
    print(_json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def watch_scoring(competition: str, ref: int | None = None,
                  poll: int = 30, timeout: int = 3600) -> int:
    """Poll a submission until Kaggle finishes scoring it and report the elapsed
    seconds (``scoring_seconds``) for the leaderboard.jsonl record.

    Accuracy is one poll interval — deliberately: the number is for budgeting and
    the submission journal, not benchmarking. Base time is the submission's own
    server-side date; watches the newest submission unless --ref is given (pass
    --ref when parallel sessions may also be submitting). If the submission was
    already scored long before the watch started, the duration is unmeasurable
    and reported as null.
    """
    import json as _json
    import time as _time
    from datetime import datetime, timezone

    try:
        api = _api()
    except Exception as e:
        print(f"kaggle API auth failed: {e}", file=sys.stderr)
        return 2

    def fetch():
        subs = api.competition_submissions(competition, page_size=20) or []
        if ref is not None:
            return next((s for s in subs if getattr(s, "ref", None) == ref), None)
        return max(subs, key=lambda s: getattr(s, "date", datetime.min), default=None)

    def status_name(sub) -> str:
        s = getattr(sub, "status", None)
        return getattr(s, "name", str(s)).upper()

    start = _time.time()
    saw_pending = False
    polls = 0
    sub = None
    while True:
        try:
            sub = fetch()
        except Exception as e:
            print(f"poll failed ({e}); retrying...", file=sys.stderr)
            sub = None
        polls += 1
        if sub is None:
            st_name = "NOT_FOUND"
        else:
            st_name = status_name(sub)
            if st_name in ("COMPLETE", "ERROR"):
                break
            saw_pending = True
        elapsed = int(_time.time() - start)
        if _time.time() - start > timeout:
            print(f"watch timed out after {elapsed}s (status={st_name}); "
                  f"re-run later — scoring_seconds stays measurable only while "
                  f"the transition is observed.", file=sys.stderr)
            print(_json.dumps({"competition": competition, "status": f"WATCH_TIMEOUT({st_name})",
                               "scoring_seconds": None, "poll_seconds": poll},
                              ensure_ascii=False))
            return 2
        print(f"poll #{polls}: status={st_name} (elapsed {elapsed}s, next in {poll}s)",
              file=sys.stderr)
        _time.sleep(max(poll, 5))

    sub_date = getattr(sub, "date", None)  # server-side submit time, naive UTC
    t0 = sub_date.replace(tzinfo=timezone.utc).timestamp() if sub_date else start
    now = _time.time()
    # Measurable if we watched the PENDING->terminal transition, or the submission
    # is fresh enough that "now - submit time" is still an honest upper bound.
    fresh_window = max(2 * poll, 120)
    measurable = saw_pending or (now - t0) <= fresh_window
    out = {
        "competition": competition,
        "ref": getattr(sub, "ref", None),
        "file_name": getattr(sub, "file_name", None),
        "description": getattr(sub, "description", None),
        "submitted_at": (sub_date.replace(tzinfo=timezone.utc).isoformat()
                         if sub_date else None),
        "status": status_name(sub),
        "public_score": getattr(sub, "public_score", None),
        "scoring_seconds": int(round(now - t0)) if measurable else None,
        "poll_seconds": poll,
    }
    if not measurable:
        out["note"] = ("already scored before the watch started — duration not "
                       "measurable (record scoring_seconds: null)")
    if out["status"] == "ERROR":
        out["error_description"] = getattr(sub, "error_description", None)
    print(_json.dumps(out, indent=2, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kloop.kaggle",
                                description="thin kaggle CLI wrappers")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="list/search competitions")
    pl.add_argument("--search", default="")
    pl.add_argument("--category", default="",
                    help="e.g. featured, research, getting-started, playground")
    pl.add_argument("--sort-by", dest="sort_by", default="",
                    help="e.g. prize, latestDeadline, numberOfTeams")
    pl.set_defaults(func=lambda a: competitions_list(a.search, a.category, a.sort_by))

    pf = sub.add_parser("files", help="list a competition's data files")
    pf.add_argument("competition")
    pf.set_defaults(func=lambda a: competition_files(a.competition))

    pd = sub.add_parser("download", help="download competition data")
    pd.add_argument("competition")
    pd.add_argument("-p", "--path", default="")
    pd.add_argument("-f", "--file", default="")
    pd.set_defaults(func=lambda a: download(a.competition, a.path, a.file))

    plb = sub.add_parser("leaderboard", help="show or download the leaderboard")
    plb.add_argument("competition")
    plb.add_argument("-d", "--download-to", dest="download_to", default="")
    plb.set_defaults(func=lambda a: leaderboard(a.competition, a.download_to))

    pk = sub.add_parser("kernels", help="list top public notebooks for a competition")
    pk.add_argument("competition")
    pk.add_argument("--sort-by", dest="sort_by", default="scoreDescending",
                    help="scoreDescending (default) / scoreAscending / voteCount / dateRun ...")
    pk.add_argument("-n", type=int, default=20)
    pk.add_argument("--language", default="")
    pk.add_argument("--kernel-type", dest="kernel_type", default="")
    pk.set_defaults(func=lambda a: kernels(a.competition, a.sort_by, a.n,
                                           a.language, a.kernel_type))

    pkp = sub.add_parser("kernel-pull", help="download a notebook's source for study")
    pkp.add_argument("ref", help="e.g. username/kernel-slug")
    pkp.add_argument("-p", "--path", required=True)
    pkp.set_defaults(func=lambda a: kernel_pull(a.ref, a.path))

    psub = sub.add_parser("submit", help="submit a CSV to a competition")
    psub.add_argument("competition")
    psub.add_argument("-f", "--file", required=True)
    psub.add_argument("-m", "--message", required=True)
    psub.add_argument("--watch", action="store_true",
                      help="poll until scored and report scoring_seconds")
    psub.add_argument("--poll", type=int, default=30, help="poll interval seconds")
    psub.add_argument("--timeout", type=int, default=3600, help="max watch seconds")
    psub.set_defaults(func=lambda a: submit(a.competition, a.file, a.message,
                                            a.watch, a.poll, a.timeout))

    pss = sub.add_parser("submissions", help="list your submissions + scores")
    pss.add_argument("competition")
    pss.set_defaults(func=lambda a: submissions(a.competition))

    plim = sub.add_parser("limits", help="show a competition's submission limits "
                                         "(max daily submissions etc.)")
    plim.add_argument("competition")
    plim.add_argument("--save", action="store_true",
                      help="record max_daily_submissions into the project's state.json")
    plim.add_argument("--name", default=None, help="project name (with --save)")
    plim.set_defaults(func=lambda a: limits(a.competition, a.save, a.name))

    pw = sub.add_parser("watch", help="poll the newest (or --ref) submission until "
                                      "scored; report scoring_seconds")
    pw.add_argument("competition")
    pw.add_argument("--ref", type=int, default=None,
                    help="submission ref id (else the newest submission)")
    pw.add_argument("--poll", type=int, default=30, help="poll interval seconds")
    pw.add_argument("--timeout", type=int, default=3600, help="max watch seconds")
    pw.set_defaults(func=lambda a: watch_scoring(a.competition, a.ref, a.poll, a.timeout))

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
