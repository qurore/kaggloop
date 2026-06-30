"""CLI for managing kaggloop campaign runs.

    python -m kloop.run new   --slug titanic --competition titanic --metric accuracy
    python -m kloop.run show  [--run <id>]
    python -m kloop.run set   --stage experiment --status done [--run <id>]
    python -m kloop.run set   --best-cv 0.8421 --best-lb 0.811 --note "blend v2"
    python -m kloop.run list

Console output is Japanese (this is user-facing). Code/comments stay English.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import state


def _resolve(run_id: str | None) -> str:
    rid = run_id or state.current_run()
    if not rid:
        print("実行中のキャンペーンがありません（--run を指定するか new で作成してください）",
              file=sys.stderr)
        raise SystemExit(2)
    return rid


def cmd_new(args) -> int:
    rid = state.new_run(args.slug, args.competition or "", args.metric or "")
    print(rid)
    return 0


def cmd_show(args) -> int:
    rid = _resolve(args.run)
    print(json.dumps(state.load_state(rid), indent=2, ensure_ascii=False))
    return 0


def cmd_set(args) -> int:
    rid = _resolve(args.run)
    st = state.load_state(rid)
    if args.stage:
        st["stage"] = args.stage
    if args.status:
        st["status"] = args.status
    if args.competition:
        st["competition"] = args.competition
    if args.metric:
        st["metric"] = args.metric
    if args.metric_direction:
        st["metric_direction"] = args.metric_direction
    if args.iteration is not None:
        st["iteration"] = args.iteration
    if args.best_cv is not None:
        st["best_cv"] = args.best_cv
    if args.best_lb is not None:
        st["best_lb"] = args.best_lb
    if args.best_submission:
        st["best_submission"] = args.best_submission
    if args.complete:
        st["status"] = "complete"
    state.save_state(rid, st)
    if args.note:
        state.append_campaign_log(rid, args.note)
    print(json.dumps(st, indent=2, ensure_ascii=False))
    return 0


def cmd_list(args) -> int:
    if not state.RUNS.exists():
        return 0
    cur = state.current_run()
    for d in sorted(state.RUNS.iterdir()):
        sp = d / "state.json"
        if not sp.exists():
            continue
        st = json.loads(sp.read_text())
        mark = " *" if st["run_id"] == cur else "  "
        cv = st.get("best_cv")
        lb = st.get("best_lb")
        print(
            f"{mark} {st['run_id']:42s} "
            f"comp={str(st.get('competition') or '-'):24s} "
            f"stage={st['stage']:11s} status={st['status']:9s} "
            f"cv={cv if cv is not None else '-'} lb={lb if lb is not None else '-'}"
        )
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kloop.run")
    sub = p.add_subparsers(dest="cmd", required=True)

    pn = sub.add_parser("new", help="create a new campaign")
    pn.add_argument("--slug", required=True)
    pn.add_argument("--competition", default="")
    pn.add_argument("--metric", default="")
    pn.set_defaults(func=cmd_new)

    ps = sub.add_parser("show", help="print a campaign's state.json")
    ps.add_argument("--run", default=None)
    ps.set_defaults(func=cmd_show)

    pset = sub.add_parser("set", help="update campaign state")
    pset.add_argument("--run", default=None)
    pset.add_argument("--stage", choices=state.STAGES, default=None)
    pset.add_argument("--status", default=None)
    pset.add_argument("--competition", default=None)
    pset.add_argument("--metric", default=None)
    pset.add_argument("--metric-direction", dest="metric_direction",
                      choices=["maximize", "minimize"], default=None)
    pset.add_argument("--iteration", type=int, default=None)
    pset.add_argument("--best-cv", dest="best_cv", type=float, default=None)
    pset.add_argument("--best-lb", dest="best_lb", type=float, default=None)
    pset.add_argument("--best-submission", dest="best_submission", default=None)
    pset.add_argument("--complete", action="store_true")
    pset.add_argument("--note", default=None)
    pset.set_defaults(func=cmd_set)

    pl = sub.add_parser("list", help="list all campaigns")
    pl.set_defaults(func=cmd_list)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
