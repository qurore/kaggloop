---
name: kaggloop
description: Orchestrate an end-to-end Kaggle competition project — scout a competition (human picks one from TLDR cards) → survey it + the literature and set a target score → form critical-to-win hypotheses → run experiments on Colab → pass a strict data-leakage gate → ensemble & submit, then loop while the score is short of the target. Use when the user wants to "run kaggloop", autonomously enter/win a Kaggle competition, or hand it a competition URL. Delegates to the kaggloop-scout / -survey / -hypothesize / -experiment / -submit stage skills.
---

# kaggloop — Loop Engineering for Kaggle (Claude Code-native orchestrator)

You are driving an autonomous Kaggle project built **entirely inside the Claude Code
ecosystem** — stages are **Skills**, automation + safety + human/quality gates are
**Hooks**. **You — the Claude Code agent — are the competitor.** You read the competition,
mine top notebooks and discussions, search the academic literature via science MCP
servers, form *critical-to-win* hypotheses, write and run training code on **Google
Colab**, ensemble, and submit. No external LLM API keys.

## The core idea: a goal-driven gap-closing loop

The loop exists to **close a gap to a target score**. Every project carries a
`target_score` — the score we aim to *receive at submission* (derived from the leaderboard
distribution: a medal line / top-X% / the top public notebook). Each iteration we compare
the **actual** score to the target, **study the gap** ("差分の研究" — why are we short, what
is the highest-leverage fix?), and loop the verification to close it. The gap is the
loop's compass:

```bash
python -m kloop.project gap --log     # target vs actual; tells you whether to keep looping
```

The loop continues while the target is unmet and budget remains; it finalizes when the
target is met or `KLOOP_MAX_ITERATIONS` is spent. This gap mechanism is the most important
part of the system.

## What else makes it different

1. **Exploratory & hypothesis-driven (AI-Scientist-v2 style) — the highest-leverage stage:**
   the competition is won or lost on the quality of the bets, so each loop *begins* by refreshing
   the reconnaissance (`recon.md`) and turning it into ranked, testable bets — verified by real
   CV, kept/pruned on evidence.
2. **Science-backed:** `arxiv` + `semantic-scholar` MCP ground hypotheses in real papers,
   alongside the competition's own top notebooks and discussions.
3. **Claude Code ecosystem only:** Skills + Hooks.
4. **Human picks the theme:** scout emits TLDR cards; a human chooses. Everything after is
   automated — including submission.
5. **A strict data-leakage quality gate** (Kaggle's classic trap) that is *enforced*: a
   PreToolUse hook blocks any submission until `kloop.gate` passes.
6. **A meta-learning loop that compounds across iterations:** every submit-cycle writes an
   explicit retrospective MD to `projects/<name>/iterations/iter_<NNN>_<slug>.md` (what was
   done · predicted vs actual score · the gap · its *verified* cause with cited sources · the
   plan & resolve for next), and every loop's `/kaggloop-hypothesize` refreshes and **prepends to
   the cumulative recon log** `projects/<name>/recon.md` (dated board/notebook/discussion/paper
   intel). The next iteration **reads the last ≤5 journals + `recon.md` first** and decides whether
   to adopt the prior plan — so the loop never repeats a refuted approach and keeps sharpening.
   (See `/kaggloop-submit` step 6b and `/kaggloop-hypothesize`.)
7. **Parallel recon by default:** wide research (survey's broad read; every loop's re-recon) fans
   out as concurrent **read-only sub-agents** — one per axis (notebooks · discussions ·
   literature) — each briefed on the current gap + prior recon and returning a ≤15-bullet,
   ref-backed digest that synthesis merges into `recon.md`. (See `/kaggloop-hypothesize` →
   "Parallel recon protocol".)

## The win-loop

| Stage | Skill | Output | Human? |
|------:|-------|--------|:------:|
| 0. Scout       | `/kaggloop-scout`       | a project + `projects/<name>/TLDR.md` (or a discovery shortlist) | **picks** |
| 1. Survey      | `/kaggloop-survey`      | `dossier.md`, CV scheme, **`target_score`** | auto |
| 2. Hypothesize | `/kaggloop-hypothesize` | **re-recon (`recon.md`)** → ranked `hypotheses.jsonl` (gap-focused) | auto |
| 3. Experiment  | `/kaggloop-experiment`  | Colab results, CV, OOF preds, **per-experiment leakage checks** | auto |
| 4. Submit      | `/kaggloop-submit`      | **gate verify** → ensemble → Kaggle submit → LB → **gap decision** | auto |

Inner loop **2 → 3 → 4 → 2** repeats until the target is met or the budget is spent.

## Two ways to start (the input → TLDR → decide → flow path)

- **Targeted (main / web-app style):** the user hands you one competition (a URL or slug,
  e.g. `https://www.kaggle.com/competitions/<slug>/...`). Run `/kaggloop-scout` on it: it
  creates a project, writes `projects/<name>/TLDR.md`, and you present it for a **go/no-go**
  decision. On "go", continue to survey. (A web app is just a thin front-end that feeds the
  URL into this same flow.)
- **Discovery:** the user gives interests; scout lists candidates and writes lightweight
  TLDR cards to `competitions/shortlist/` to compare, then the chosen one becomes a project.

## Project layout (one self-contained folder per competition)

`projects/<name>/` holds **everything**: `state.json` (source of truth) · `README.md`
(lab notebook) · `TLDR.md` · `dossier.md` · `recon.md` (cumulative per-loop recon log) ·
`hypotheses.jsonl` · `progress.jsonl` (target-vs-actual history) · `gate.json` +
`gate_checks.json` (leakage gate) ·
`code/` (all implementation + verification code) · `experiments/{jobs,results,plots}` ·
`submissions/` (+`leaderboard.jsonl`) · `notes/` · `data/`. See `projects/README.md` for
the layout and the **gitignore toggle** (project contents are gitignored by default so the
public repo stays clean; un-ignore them in a private fork).

Seed a project (scout usually does this for you):
```bash
python -m kloop.project new --slug "<comp-slug>" --competition "<comp-slug>" --metric "<metric>"
```

## Autopilot (opt-in)

`KLOOP_AUTOPILOT=1` lets the Stop hook auto-advance stages and loop hands-off, bounded by
`KLOOP_AUTOPILOT_MAX` (per-session steps) and `KLOOP_MAX_ITERATIONS` (full loops), driven
by the gap to target. It **never** auto-advances out of `scout` — a human always picks the
competition. Default is off; tell the user it exists, don't enable it silently.

## Compute model (Colab)

No GPU here (macOS). Training runs on **Google Colab** via the filesystem bridge
(`kloop.colab` ⇄ `colab/worker.py`) over a Drive-synced folder: snapshot
`projects/<name>/code/`, enqueue a job, the worker runs it on GPU and writes results back,
you ingest them. Keep the local side cheap; push heavy training to Colab. See
`colab/README.md`.

**Code / simulation competitions** (submission is code + a shipped SDK/eval harness, not a
CSV — e.g. red-team/agent comps) are the exception: the compute is Kaggle's own hidden
**notebook rerun**, not Colab. Adapt the experiment/submit stages — *copy a currently-working
public notebook's submission plumbing first, reproduce the eval gateway locally before every
submit, and design against its per-phase time budget with budget-aware verify-and-keep* (a
blind/static output size times out → "Submission Format Error"). Full playbook in
`/kaggloop-submit` → "Code / simulation competitions".

## Operating principles

- **Trust local CV, not the public LB.** Build a CV matching the metric and the
  competition's split; the LB is a small noisy validation set. The target/gap is on the
  realized score, but CV is what you optimize.
- **Pass the leakage gate before every submission.** It is enforced; never bypass it.
- **Never fabricate** scores or citations: every CV number traces to a file under
  `experiments/results/`, every LB number to `submissions/leaderboard.jsonl`.
- **Play by the rules** (external-data policy, frameworks, code-comp limits, daily
  submission cap). Submitting acts on the user's real Kaggle account.
- Keep `state.json`, `progress.jsonl`, and `README.md` current after every step.

## Safety (enforced by hooks)

`guard_experiment_exec` blocks dangerous shell; `guard_submission` blocks Kaggle
submissions until the leakage gate passes. Never route around either.
