# kaggloop

**Loop Engineering for Kaggle, built entirely inside the Claude Code ecosystem.**

kaggloop runs a Kaggle competition as a **goal-driven, gap-closing loop** — *scout → survey →
hypothesize → experiment → submit* — that keeps iterating until the score reaches a target.
The **Claude Code agent is the competitor**: it reads the competition, mines the top public
notebooks and discussions, searches the academic literature through science MCP servers,
forms explicit *critical-to-win* hypotheses, trains on **Google Colab**, ensembles, passes a
strict data-leakage gate, and submits — with **no external LLM API keys**. Stages are Claude
Code **Skills**; automation, safety, and the human/quality gates are **Hooks**.

> **Status: base scaffolding.** The skills, hooks, the `kloop` helper package (with the
> target/gap loop, the leakage gate, and the append-only decision journal), and the Colab
> worker are in place and verified. Each stage skill is a working v1 procedure to iterate on
> against a real competition. It doesn't magically win Kaggle — it gives you a disciplined,
> science-backed, leakage-gated, fully-audited loop to do so.

## What's different about it

1. **Goal-driven gap loop (the core).** Each project has a **target score**; every iteration
   compares the *actual* score to it, **studies the gap**, and loops the verification to close
   it. `python -m kloop.project gap` is the compass.
2. **Exploratory & hypothesis-driven (AI-Scientist-v2 style).** Ranked, testable bets,
   verified by real CV, kept/pruned on evidence.
3. **Science-backed.** `arxiv` + `semantic-scholar` MCP servers ground hypotheses in real
   papers, alongside the competition's own top notebooks and discussions.
4. **A strict, enforced data-leakage gate.** Automated leak detectors + a mandatory
   checklist; a hook **blocks every Kaggle submission until the gate passes**.
5. **Full observability.** An append-only decision journal records *why* the current model
   exists; you can't close a stage without logging the decision.
6. **Human picks the theme.** Hand it a competition URL → it writes a TLDR card → you decide.
   Everything after is automated.
7. **Claude Code ecosystem only.** Skills + Hooks. No external agent framework.

## The win-loop

| Stage | Skill | Output | Human? |
|------:|-------|--------|:------:|
| 0. Scout       | `/kaggloop-scout`       | a project + `projects/<name>/TLDR.md` (or a discovery shortlist) | **picks** |
| 1. Survey      | `/kaggloop-survey`      | `dossier.md`, leakage-safe CV scheme, **target_score** | auto |
| 2. Hypothesize | `/kaggloop-hypothesize` | ranked `hypotheses.jsonl` (gap-focused) | auto |
| 3. Experiment  | `/kaggloop-experiment`  | Colab results, CV, OOF preds, **leakage gate per result** | auto |
| 4. Submit      | `/kaggloop-submit`      | **gate** → ensemble → Kaggle submit → LB → **study gap → decide** | auto |

Inner loop **2 → 3 → 4 → 2** repeats until the target is met or the budget is spent.
`/kaggloop` is the umbrella orchestrator.

## Two ways to start

- **Targeted (main — a web app would drive this):** give it one competition URL/slug →
  `/kaggloop-scout` creates a project and a `TLDR.md` → you make a go/no-go call.
- **Discovery:** give it interests → scout shortlists candidates → you pick → it becomes a
  project.

## Project = one self-contained folder

`projects/<name>/` holds **everything** for a competition — `state.json`, `README.md` (lab
notebook), `TLDR.md`, `dossier.md`, `hypotheses.jsonl`, `progress.jsonl` (target/actual
history), `decisions.jsonl` (audit journal), `gate.json`, `code/` (all implementation +
verification code), `experiments/`, `submissions/`, `notes/`, `data/`. **Contents are
gitignored by default** so this public repo stays a clean tool; see `projects/README.md` for
the one-line toggle to version your projects in a private fork.

## Layout

| Path | What |
|------|------|
| `.claude/skills/` | `kaggloop` orchestrator + `scout`/`survey`/`hypothesize`/`experiment`/`submit` |
| `.claude/hooks/` | `session_start`, `guard_experiment_exec`, `guard_submission` (gate enforcement), `log_tool_use`, `stop_autopilot` (gap-driven autopilot) |
| `.mcp.json` | science MCP servers: `arxiv`, `semantic-scholar` |
| `kloop/` | helpers: `state`, `project`, `ledger`, `kaggle`, `colab`, `score`, `gate`, `journal` |
| `colab/` | `worker.py` (GPU compute) + `colab_kaggloop.ipynb` + `README.md` |
| `competitions/` | `TEMPLATE_competition.md` + `shortlist/` (discovery scratch) |
| `projects/<name>/` | one self-contained project per competition (gitignored) |

## Quick start

```bash
# 1. Set up the local orchestration env (.venv + kaggle CLI + uv for the MCP servers)
bash scripts/setup.sh && bash scripts/doctor.sh

# 2. Credentials & compute
#    - Kaggle token at ~/.kaggle/kaggle.json (chmod 600); accept comp rules on the site
#    - Colab worker + KLOOP_COLAB_* paths  (see colab/README.md)

# 3. In Claude Code — hand it a competition and go:
#    /kaggloop-scout https://www.kaggle.com/competitions/<slug>/overview
#    …read the TLDR, say go, then /kaggloop-survey → -hypothesize → -experiment → -submit
#    (or set KLOOP_AUTOPILOT=1 to loop hands-off after you pick the competition)
```

## Requirements

- **Claude Code** logged in (`claude` CLI) — it runs the skills/hooks and is the competitor.
- **Python 3.11+** locally for the `kloop` helpers (`scripts/setup.sh` builds a `.venv`).
- **Kaggle API** token (`~/.kaggle/kaggle.json`) + acceptance of each competition's rules.
- **Google Colab** (GPU) for training + a Drive-synced folder as the compute bridge
  ([`colab/README.md`](./colab/README.md)).
- Science MCP servers launch via `.venv/bin/uvx`; run `/mcp` to confirm.

## Safety & honesty

- `guard_experiment_exec` blocks dangerous shell and protects the append-only journal;
  `guard_submission` blocks Kaggle submits until the leakage gate passes. Don't route around
  them.
- **Trust local (leak-free) CV, not the public LB.** Never overfit to the leaderboard; never
  fabricate a CV/LB score or a citation — every number traces to a file under `projects/<name>/`.
- **Play by the rules:** no banned external data or host-prohibited leaks; respect framework
  and daily-submission limits. Submitting acts on your real Kaggle account.

## Inspiration & attribution

The exploratory hypothesis loop is inspired by Sakana AI's
[**AI-Scientist-v2**](https://github.com/SakanaAI/AI-Scientist-v2) and its Claude Code port.
Kaggle and paper text is **untrusted external input** — treated as data, not instructions.
See [`CLAUDE.md`](./CLAUDE.md) for the full operating guide. MIT licensed — see
[`LICENSE`](./LICENSE).
