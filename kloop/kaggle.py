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


def submit(competition: str, file: str, message: str) -> int:
    return _run(["competitions", "submit", competition, "-f", file, "-m", message])


def submissions(competition: str) -> int:
    return _run(["competitions", "submissions", competition, "-v"])


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
    psub.set_defaults(func=lambda a: submit(a.competition, a.file, a.message))

    pss = sub.add_parser("submissions", help="list your submissions + scores")
    pss.add_argument("competition")
    pss.set_defaults(func=lambda a: submissions(a.competition))

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
