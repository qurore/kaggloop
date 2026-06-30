---
name: kaggloop
description: Orchestrate an end-to-end Kaggle competition campaign — scout competitions (human picks one) → survey the competition + literature → form critical-to-win hypotheses → run experiments on Colab → ensemble & submit, looping to improve the score. Use when the user wants to "run kaggloop", autonomously enter/win a Kaggle competition, or go from a shortlist of competitions to automated submissions. Delegates to the kaggloop-scout / -survey / -hypothesize / -experiment / -submit stage skills.
---

# kaggloop — Loop Engineering for Kaggle (Claude Code-native orchestrator)

You are driving an autonomous Kaggle competition pipeline built **entirely inside the
Claude Code ecosystem** — the stages are **Skills**, the automation + safety + human
gates are **Hooks**. **You — the Claude Code agent — are the competitor.** You read the
competition, mine the top notebooks and discussions, search the academic literature
through the science MCP servers, form *critical-to-win* hypotheses, write and run the
training code on Colab, ensemble, and submit. No external LLM API keys are involved.

What makes this different from a one-shot "write me a Kaggle notebook" bot:

1. **Exploratory, hypothesis-driven (AI-Scientist-v2 style).** Each iteration we write
   down explicit, ranked, testable bets about what will move the score, verify them with
   real cross-validation, and keep/prune based on evidence — a search over ideas, not a
   single guess. See `kaggloop-hypothesize`.
2. **Science-backed.** We use the `arxiv` and `semantic-scholar` MCP servers to find the
   latest methods relevant to the task and ground hypotheses in real papers — alongside
   the competition's own top notebooks and discussions.
3. **Claude Code ecosystem only.** Skills + Hooks. No bespoke daemon, no external agent
   framework.
4. **Human-in-the-loop theme selection.** The `scout` stage produces human-readable TLDR
   cards; **a human picks the competition**. Everything after that is automated.

## The win-loop

| Stage | Skill | Output | Human? |
|------:|-------|--------|:------:|
| 0. Scout      | `kaggloop-scout`       | `competitions/shortlist/*.md` TLDR cards | **picks** |
| 1. Survey     | `kaggloop-survey`      | `runs/<id>/dossier.md` (+ data, metric)  | auto |
| 2. Hypothesize| `kaggloop-hypothesize` | `runs/<id>/hypotheses.jsonl` (ranked)    | auto |
| 3. Experiment | `kaggloop-experiment`  | Colab job results, CV scores, OOF preds  | auto |
| 4. Submit     | `kaggloop-submit`      | ensemble → Kaggle submission → LB score  | auto |

The inner loop **2 → 3 → 4 → 2** repeats (bounded by `KLOOP_MAX_ITERATIONS`) to keep
raising the score with what each round learned. Invoke a stage with its slash command
(e.g. `/kaggloop-survey`) or follow its SKILL.md. This umbrella skill coordinates them.

## Campaign layout

Every campaign (one competition) lives in one directory:
`runs/<YYYY-MM-DD_HH-MM-SS>_<slug>/`

```
runs/<id>/
  state.json          # {stage,status,competition,metric,metric_direction,
                      #  iteration,best_cv,best_lb,best_submission} — source of truth
  competition.json    # raw competition metadata (kaggle API + scout notes)
  dossier.md          # survey output: data, metric, top notebooks, discussions, papers
  hypotheses.jsonl    # the ranked hypothesis ledger (one bet per line)
  experiments/
    code/             # pipeline code you write (snapshotted into each Colab job)
    jobs/             # local copies of submitted job specs
    results/          # results ingested back from Colab (metric.json, oof.npy, logs)
    plots/            # figures
  submissions/
    *.csv             # submission files
    leaderboard.jsonl # submission file -> public LB score log
  campaign.md         # human-readable running lab notebook
```

`state.json` is authoritative. The Stop hook reads it for optional autopilot; always
keep it current as you advance (`python -m kloop.run set ...`).

## How to start a campaign

1. **Check the environment.** `bash scripts/doctor.sh` (the SessionStart hook also prints
   a status banner). If deps are missing, point the user to `scripts/setup.sh`. The
   campaign needs: the `kaggle` CLI + an API token (`~/.kaggle/kaggle.json`), the science
   MCP servers (`/mcp`), and a Colab worker for compute (see `colab/README.md`).
2. **Scout** unless the user already named a competition: run `/kaggloop-scout` to build
   TLDR cards for candidate competitions. **Stop and let the human choose** — this is the
   one mandatory human gate (the autopilot hook enforces it).
3. Once a competition is chosen, create/seed the campaign:
   ```bash
   python -m kloop.run new --slug "<comp-slug>" --competition "<comp-slug>" --metric "<metric>"
   ```
   (prints the run id; also records it as the current run).
4. Run `/kaggloop-survey` → `/kaggloop-hypothesize` → `/kaggloop-experiment` →
   `/kaggloop-submit`, updating `state.json` after each. Pause and summarize for the user
   between stages unless they asked for **autopilot**.

## Autopilot (optional, opt-in)

Set `KLOOP_AUTOPILOT=1` to let the Stop hook auto-advance stages and loop the inner
cycle hands-off, bounded by `KLOOP_AUTOPILOT_MAX` (per-session step cap) and
`KLOOP_MAX_ITERATIONS` (full loops). It **never** auto-advances out of `scout` — a human
always picks the competition. Default is **off**; tell the user the toggle exists, don't
enable it silently.

## Compute model (Colab)

This machine (macOS) has **no GPU**. Training runs on **Google Colab** through the
filesystem bridge in `kloop.colab` + `colab/worker.py`: you snapshot the campaign's
`experiments/code/`, enqueue a job, the Colab worker runs it on GPU and writes results
back, and you ingest them. Keep the local side cheap (orchestration, small CV merges,
ensembling); push heavy training to Colab. See `colab/README.md`. Be honest with the
user about wall-clock time and Colab usage limits for big jobs.

## Operating principles

- **Be a rigorous competitor.** Trust a robust local CV that matches the metric and the
  competition's split; treat the public LB as a small, noisy validation set — never
  overfit to it. State each hypothesis, test it, report honest CV/LB deltas (including
  the bets that *didn't* work — those are kept in the ledger as `rejected`).
- **Never fabricate** scores, leaderboard positions, or citations. Every CV number must
  trace to a file under `experiments/results/`; every LB number to a real submission in
  `submissions/leaderboard.jsonl`; every paper to a real, findable reference.
- **Play by the rules.** Read the competition rules during survey: external-data
  policy, allowed frameworks, team/submission limits, code-competition constraints. Do
  not use banned data or leaks. Respect the daily submission cap.
- **Keep `campaign.md` updated** like a lab notebook, and checkpoint `state.json` after
  every stage so a crash/resume continues cleanly.

## Safety (enforced by hooks, but stay alert)

The `guard-experiment-exec` PreToolUse hook blocks obviously dangerous shell (network
installs piped to a shell, `rm -rf` outside the run dir, credential/`kaggle.json`
exfiltration, guard tampering). If it blocks a command, **fix the step** so it doesn't
need the dangerous action — never route around the guard.
