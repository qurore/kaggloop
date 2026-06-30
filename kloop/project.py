"""CLI for managing kaggloop projects (one project = one competition campaign).

    python -m kloop.project new   --slug titanic --competition titanic --metric accuracy
    python -m kloop.project show  [--name <name>]
    python -m kloop.project set   --stage experiment --status done [--name <name>]
    python -m kloop.project set   --target-score 0.87 --target-rationale "gold line ~0.87 from LB"
    python -m kloop.project set   --best-cv 0.842 --best-lb 0.811 --note "blend v2"
    python -m kloop.project gap    [--use auto|cv|lb]   # target vs actual, the loop's compass
    python -m kloop.project list

The ``gap`` command is the core of the loop: it compares the actual score to the
target and tells you whether to keep looping. Console output is Japanese
(user-facing); code/comments stay English.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import state


def _resolve(name: str | None) -> str:
    n = name or state.current_project()
    if not n:
        print("アクティブなプロジェクトがありません（--name を指定するか new で作成してください）",
              file=sys.stderr)
        raise SystemExit(2)
    return n


def cmd_new(args) -> int:
    name = state.new_project(args.slug, args.competition or "", args.metric or "")
    print(name)
    return 0


def cmd_show(args) -> int:
    name = _resolve(args.name)
    print(json.dumps(state.load_state(name), indent=2, ensure_ascii=False))
    return 0


def cmd_set(args) -> int:
    name = _resolve(args.name)
    st = state.load_state(name)
    fields = {
        "stage": args.stage, "status": args.status, "competition": args.competition,
        "metric": args.metric, "metric_direction": args.metric_direction,
        "target_score": args.target_score, "target_rationale": args.target_rationale,
        "iteration": args.iteration, "best_cv": args.best_cv, "best_lb": args.best_lb,
        "best_submission": args.best_submission,
    }
    for k, v in fields.items():
        if v is not None:
            st[k] = v
    if args.gate_passed is not None:
        st["gate_passed"] = args.gate_passed
    if args.complete:
        st["status"] = "complete"

    # Observability enforcement: you cannot mark a stage done/complete without a
    # journaled decision for that stage+iteration. Log one inline with --decision,
    # or run `kloop.journal log ...` first. This keeps the audit trail honest.
    if st.get("status") in ("done", "complete"):
        if args.decision:
            state.append_decision(name, {
                "stage": st["stage"], "iteration": st["iteration"],
                "kind": args.decision_kind or "decision",
                "decision": args.decision, "rationale": args.rationale or "",
                "refs": [], "evidence": "",
            })
        if not state.decisions_for(name, st["stage"], st["iteration"]):
            print(
                f"✗ stage '{st['stage']}' (iter {st['iteration']}) を done にできません: "
                f"意思決定ログが未記録です。`python -m kloop.journal log --kind ... "
                f"--decision ... --rationale ...` で記録するか、この set に "
                f"--decision/--rationale を付けてください（observability 強制）。",
                file=sys.stderr,
            )
            return 2

    state.save_state(name, st)
    if args.note:
        state.append_project_log(name, args.note)
    print(json.dumps(st, indent=2, ensure_ascii=False))
    return 0


def cmd_gap(args) -> int:
    name = _resolve(args.name)
    st = state.load_state(name)
    direction = st.get("metric_direction") or "maximize"
    target = st.get("target_score")
    cv, lb = st.get("best_cv"), st.get("best_lb")

    if args.use == "cv":
        actual, src = cv, "cv"
    elif args.use == "lb":
        actual, src = lb, "lb"
    else:  # auto: prefer the realized LB score, fall back to the CV estimate
        actual, src = (lb, "lb") if lb is not None else (cv, "cv")

    g = state.gap(target, actual, direction)
    met = state.target_met(target, actual, direction)
    out = {
        "project": name, "metric": st.get("metric"), "direction": direction,
        "target": target, "actual": actual, "actual_source": src,
        "gap": g, "target_met": met, "iteration": st.get("iteration"),
    }
    if args.log:
        state.append_progress(name, {k: out[k] for k in
                                     ("iteration", "target", "actual", "actual_source", "gap", "target_met")})
    print(json.dumps(out, indent=2, ensure_ascii=False))
    # Human-facing one-liner.
    if target is None:
        print("→ 目標スコア未設定。survey/hypothesize で target_score を設定してください。", file=sys.stderr)
    elif met:
        print(f"→ 目標達成（{src}={actual} が target={target} に到達）。finalize 可能。", file=sys.stderr)
    elif g is not None:
        print(f"→ 残りギャップ {g:+.6g}（{src}={actual} vs target={target}）。差分を研究して次ループへ。",
              file=sys.stderr)
    return 0


def cmd_list(args) -> int:
    if not state.PROJECTS.exists():
        return 0
    cur = state.current_project()
    for d in sorted(state.PROJECTS.iterdir()):
        sp = d / "state.json"
        if not sp.exists():
            continue
        st = json.loads(sp.read_text())
        mark = " *" if st.get("name") == cur else "  "
        direction = st.get("metric_direction") or "maximize"
        g = state.gap(st.get("target_score"),
                      st.get("best_lb") if st.get("best_lb") is not None else st.get("best_cv"),
                      direction)
        print(
            f"{mark} {str(st.get('name')):28s} "
            f"comp={str(st.get('competition') or '-'):28s} "
            f"stage={st.get('stage'):11s} it={st.get('iteration')} "
            f"cv={st.get('best_cv')} lb={st.get('best_lb')} "
            f"target={st.get('target_score')} gap={('%.4g' % g) if g is not None else '-'}"
        )
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kloop.project")
    sub = p.add_subparsers(dest="cmd", required=True)

    pn = sub.add_parser("new", help="create a new project")
    pn.add_argument("--slug", required=True)
    pn.add_argument("--competition", default="")
    pn.add_argument("--metric", default="")
    pn.set_defaults(func=cmd_new)

    ps = sub.add_parser("show", help="print a project's state.json")
    ps.add_argument("--name", default=None)
    ps.set_defaults(func=cmd_show)

    pset = sub.add_parser("set", help="update project state")
    pset.add_argument("--name", default=None)
    pset.add_argument("--stage", choices=state.STAGES, default=None)
    pset.add_argument("--status", default=None)
    pset.add_argument("--competition", default=None)
    pset.add_argument("--metric", default=None)
    pset.add_argument("--metric-direction", dest="metric_direction",
                      choices=["maximize", "minimize"], default=None)
    pset.add_argument("--target-score", dest="target_score", type=float, default=None)
    pset.add_argument("--target-rationale", dest="target_rationale", default=None)
    pset.add_argument("--iteration", type=int, default=None)
    pset.add_argument("--best-cv", dest="best_cv", type=float, default=None)
    pset.add_argument("--best-lb", dest="best_lb", type=float, default=None)
    pset.add_argument("--best-submission", dest="best_submission", default=None)
    gate = pset.add_mutually_exclusive_group()
    gate.add_argument("--gate-passed", dest="gate_passed", action="store_const", const=True)
    gate.add_argument("--gate-failed", dest="gate_passed", action="store_const", const=False)
    pset.add_argument("--complete", action="store_true")
    pset.add_argument("--note", default=None)
    pset.add_argument("--decision", default=None,
                      help="journal this decision when marking a stage done/complete")
    pset.add_argument("--rationale", default=None, help="why (paired with --decision)")
    pset.add_argument("--decision-kind", dest="decision_kind", default=None,
                      help="journal kind for --decision (e.g. cv_design, ensemble, loop_decision)")
    pset.set_defaults(func=cmd_set, gate_passed=None)

    pg = sub.add_parser("gap", help="compare actual score to target (the loop compass)")
    pg.add_argument("--name", default=None)
    pg.add_argument("--use", choices=["auto", "cv", "lb"], default="auto")
    pg.add_argument("--log", action="store_true", help="append to progress.jsonl")
    pg.set_defaults(func=cmd_gap)

    pl = sub.add_parser("list", help="list all projects")
    pl.set_defaults(func=cmd_list)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
