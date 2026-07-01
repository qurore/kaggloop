"""Thin helper: append a leaderboard-standing snapshot after each submission.

Records our score against the live **medal landscape** — the current top score plus the
gold / silver / bronze cutoff scores (computed from Kaggle's team-count medal formula) — to
``projects/<name>/standing.jsonl``, one record per loop iteration, stacked vertically. The
loop uses it to see how far our realized score is from each medal line, round over round.

    python -m kloop.standing snapshot --score 10.08 --iter 0 --note "iter0 v5"

Mechanics only; the intelligence (what to do about the gap) lives in the skills / you.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import zipfile
from pathlib import Path

from . import kaggle as kg
from . import state as st


def medal_cutoff_ranks(n: int) -> dict[str, int]:
    """Kaggle medal cutoff *ranks* for a competition with ``n`` teams (approximate).

    Per Kaggle's progression system:
      1–249 teams  -> gold top 10%, silver top 20%, bronze top 40%
      250–999      -> gold top 20,  silver top 50,  bronze top 100
      1000+        -> gold top (10 + 0.2%·n), silver top 5%, bronze top 10%
    """
    if n <= 0:
        return {"gold": 0, "silver": 0, "bronze": 0}
    if n < 250:
        return {"gold": max(1, round(0.10 * n)),
                "silver": max(1, round(0.20 * n)),
                "bronze": max(1, round(0.40 * n))}
    if n < 1000:
        return {"gold": 20, "silver": 50, "bronze": 100}
    return {"gold": round(10 + 0.002 * n),
            "silver": round(0.05 * n),
            "bronze": round(0.10 * n)}


def _leaderboard_rows(competition: str) -> list[tuple[int, float]]:
    """Download the public LB and return ``[(rank, score)]`` sorted by rank."""
    with tempfile.TemporaryDirectory() as tmp:
        kg.leaderboard(competition, download_to=tmp)
        csvs = list(Path(tmp).glob("*.csv"))
        if not csvs:
            for z in Path(tmp).glob("*.zip"):
                with zipfile.ZipFile(z) as zf:
                    zf.extractall(tmp)
            csvs = list(Path(tmp).glob("*.csv"))
        if not csvs:
            raise RuntimeError("could not fetch a leaderboard CSV for " + competition)
        rows: list[tuple[int, float]] = []
        with csvs[0].open(newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    rows.append((int(r["Rank"]), float(r["Score"])))
                except (KeyError, ValueError, TypeError):
                    continue
    rows.sort(key=lambda t: t[0])
    return rows


def snapshot(name: str, competition: str, our_score: float | None, iteration: int,
             note: str, direction: str, target: float | None) -> dict:
    """Compute the medal landscape vs our score and append it to standing.jsonl."""
    rows = _leaderboard_rows(competition)
    if not rows:
        raise RuntimeError("empty leaderboard")
    n = len(rows)
    scores = [s for _, s in rows]                 # already ranked by Kaggle (direction-aware)
    maximize = direction != "minimize"
    cuts = medal_cutoff_ranks(n)

    def score_at(rank: int) -> float:
        return rows[max(1, min(rank, n)) - 1][1]

    top = rows[0][1]
    gold_min, silver_min, bronze_min = (score_at(cuts["gold"]),
                                        score_at(cuts["silver"]),
                                        score_at(cuts["bronze"]))

    our_rank: int | None = None
    medal, gap = "none", None
    if our_score is not None:
        better = sum(1 for s in scores if (s > our_score if maximize else s < our_score))
        our_rank = better + 1
        if our_rank <= cuts["gold"]:
            medal = "gold"
        elif our_rank <= cuts["silver"]:
            medal = "silver"
        elif our_rank <= cuts["bronze"]:
            medal = "bronze"
        if target is not None:
            gap = round((target - our_score) if maximize else (our_score - target), 6)

    rec = {"iter": iteration, "ts": st._stamp(),
           "score": our_score, "rank": our_rank, "n_teams": n, "medal": medal,
           "top": top, "gold_min": gold_min, "silver_min": silver_min,
           "bronze_min": bronze_min, "target": target, "gap": gap, "note": note}
    (st.project_dir(name) / "standing.jsonl").open("a", encoding="utf-8").write(
        json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def cmd_snapshot(a) -> int:
    name = a.name or st.current_project()
    if not name:
        print("no active project (pass --name)", file=sys.stderr)
        return 2
    s = st.load_state(name)
    rec = snapshot(
        name=name,
        competition=a.competition or s.get("competition"),
        our_score=a.score if a.score is not None else s.get("best_lb"),
        iteration=a.iter if a.iter is not None else int(s.get("iteration", 0)),
        note=a.note,
        direction=s.get("metric_direction", "maximize"),
        target=a.target if a.target is not None else s.get("target_score"),
    )
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    ap = argparse.ArgumentParser("kloop.standing", description="leaderboard-standing tracker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("snapshot", help="append a standing record to standing.jsonl")
    ps.add_argument("--name", default=None, help="project (default: current)")
    ps.add_argument("--competition", default=None)
    ps.add_argument("--score", type=float, default=None, help="our public score (default: state best_lb)")
    ps.add_argument("--target", type=float, default=None)
    ps.add_argument("--iter", type=int, default=None)
    ps.add_argument("--note", default="")
    ps.set_defaults(func=cmd_snapshot)
    args = ap.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
