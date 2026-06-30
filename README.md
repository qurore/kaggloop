# kaggloop

**Loop Engineering for Kaggle, built entirely inside the Claude Code ecosystem.**

kaggloop runs a Kaggle competition campaign as an exploratory, hypothesis-driven loop —
*scout → survey → hypothesize → experiment → submit*, looping to raise the score. The
**Claude Code agent is the competitor**: it reads the competition, mines the top public
notebooks and discussions, searches the academic literature through science MCP servers,
forms explicit *critical-to-win* hypotheses, writes and runs the training code on **Google
Colab**, ensembles, and submits — with **no external LLM API keys**. The stages are Claude
Code **Skills**; the automation, safety, and human gates are **Hooks**.

> **Status: base scaffolding.** The skills (stage procedures), hooks (automation + safety +
> human gate), the `kloop` helper package, the Colab worker, and the docs are in place. Each
> stage skill is a working v1 procedure to iterate on against a real competition. It does not
> magically win Kaggle — it gives you a disciplined, science-backed, automated loop to do so.

## What's different about it

1. **Exploratory & hypothesis-driven (AI-Scientist-v2 style).** Every iteration writes down
   ranked, testable bets about what will move the score, verifies them with real
   cross-validation, and keeps/prunes on evidence — a *search over ideas*, not one guess.
2. **Science-backed.** The `arxiv` and `semantic-scholar` MCP servers surface the latest
   methods relevant to the task, so hypotheses are grounded in real papers — alongside the
   competition's own top notebooks and discussions.
3. **Claude Code ecosystem only.** Skills + Hooks. No external agent framework or bespoke
   daemon.
4. **Human picks the theme.** The `scout` stage produces human-readable **TLDR cards**; a
   human chooses the competition. Everything after selection is automated, including
   submission.

## The win-loop

| Stage | Skill | Output | Human? |
|------:|-------|--------|:------:|
| 0. Scout       | `/kaggloop-scout`       | `competitions/shortlist/*.md` TLDR cards | **picks** |
| 1. Survey      | `/kaggloop-survey`      | `runs/<id>/dossier.md` (data, metric, CV, notebooks, discussions, papers) | auto |
| 2. Hypothesize | `/kaggloop-hypothesize` | ranked `runs/<id>/hypotheses.jsonl` ledger | auto |
| 3. Experiment  | `/kaggloop-experiment`  | Colab job results, CV scores, OOF predictions | auto |
| 4. Submit      | `/kaggloop-submit`      | ensemble → Kaggle submission → leaderboard score | auto |

The inner loop **2 → 3 → 4 → 2** repeats (bounded by `KLOOP_MAX_ITERATIONS`). `/kaggloop`
is the umbrella orchestrator.

## Layout

| Path | What |
|------|------|
| `.claude/skills/` | `kaggloop` orchestrator + `scout` / `survey` / `hypothesize` / `experiment` / `submit` |
| `.claude/hooks/` | `session_start` (banner), `guard_experiment_exec` (safety), `log_tool_use` (provenance), `stop_autopilot` (human-gated autopilot) |
| `.claude/settings.json` | wires hooks; autopilot off by default; minimal permissions |
| `.mcp.json` | project-shared science MCP servers: `arxiv`, `semantic-scholar` |
| `kloop/` | thin Python helpers: `state`, `run`, `ledger`, `kaggle`, `colab`, `score` |
| `colab/` | `worker.py` (GPU half of the compute bridge) + `kaggloop_worker.ipynb` + `README.md` |
| `competitions/` | `TEMPLATE_competition.md` + `shortlist/` (scout writes TLDR cards here) |
| `scripts/` | `setup.sh`, `doctor.sh` |
| `runs/<id>/` | one self-contained campaign directory per competition (gitignored) |

## Quick start

```bash
# 1. Set up the local orchestration env (.venv + kaggle CLI + uv for the MCP servers)
bash scripts/setup.sh
bash scripts/doctor.sh                 # verify

# 2. Credentials & compute
#    - put your Kaggle token at ~/.kaggle/kaggle.json (chmod 600); accept comp rules on the site
#    - set up the Colab worker and KLOOP_COLAB_* paths  (see colab/README.md)

# 3. In Claude Code:
#    /kaggloop-scout            -> read the TLDR cards, pick a competition
#    /kaggloop-survey           -> build the dossier
#    /kaggloop-hypothesize      -> rank critical-to-win bets
#    /kaggloop-experiment       -> verify them on Colab
#    /kaggloop-submit           -> ensemble, submit, track, loop
#    (or set KLOOP_AUTOPILOT=1 to run the loop hands-off after you pick the competition)
```

## Requirements

- **Claude Code** logged in (`claude` CLI) — it runs the skills/hooks and is the competitor.
- **Python 3.11+** locally for the `kloop` helpers (`scripts/setup.sh` builds a `.venv`).
- **Kaggle API** token (`~/.kaggle/kaggle.json`) and acceptance of each competition's rules.
- **Google Colab** (GPU) for training, plus a Drive-synced folder as the compute bridge —
  see [`colab/README.md`](./colab/README.md).
- Science MCP servers launch via `.venv/bin/uvx` (installed by setup); run `/mcp` to confirm.

## Safety & honesty

- A `PreToolUse` hook blocks dangerous shell (downloads piped to a shell, `rm -rf` outside
  the run dir, credential/`kaggle.json` exfiltration, guard tampering). Don't route around it.
- **Trust local CV, not the public LB.** Never overfit to the leaderboard, and never fabricate
  a CV score, an LB score, or a citation — every number traces to a file under `runs/<id>/`.
- **Play by the rules:** no banned external data or host-prohibited leaks; respect framework
  and daily-submission limits. Submitting acts on your real Kaggle account.

## Inspiration & attribution

The exploratory hypothesis loop is inspired by Sakana AI's
[**AI-Scientist-v2**](https://github.com/SakanaAI/AI-Scientist-v2) and its Claude Code port.
Kaggle data, notebook, discussion, and paper text are **untrusted external input** — treated
as data, not instructions. See [`CLAUDE.md`](./CLAUDE.md) for the full operating guide.

MIT licensed — see [`LICENSE`](./LICENSE).
