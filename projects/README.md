# projects/ — one self-contained folder per project

A **project** is one Kaggle competition you are working. Everything for it lives
in `projects/<name>/` — state, the dossier, the hypothesis ledger, **all
implementation and verification code**, experiment results, submissions, the
target/gap history, the leakage-gate record, and free-form notes. Nothing about a
project leaks outside its folder, so projects are easy to start, archive, or
delete independently.

## Layout of a project

```
projects/<name>/
  state.json          # source of truth (stage, status, metric, target_score, gap, gate_passed, ...)
  README.md           # human overview + running log (lab notebook)
  TLDR.md             # the scout TLDR card for this competition (created at scouting)
  dossier.md          # survey output: data, metric, CV scheme, top notebooks, discussions, papers
  hypotheses.jsonl    # ranked hypothesis ledger (one critical-to-win bet per line)
  progress.jsonl      # target-vs-actual history per iteration (the loop's gap log)
  gate.json           # leakage quality-gate result (must pass before submitting)
  gate_checks.json    # detailed gate check + checklist record
  code/               # ALL implementation + verification code (snapshotted into Colab jobs)
  experiments/
    jobs/  results/  plots/   # submitted job specs, ingested Colab results, figures
  submissions/        # submission CSVs + leaderboard.jsonl
  notes/              # analyses, decisions, scratch MD
  data/               # local data scratch (not committed)
```

Create one with the helper (usually done for you by the `kaggloop-scout` skill):

```bash
python -m kloop.project new --slug "<comp-slug>" --competition "<comp-slug>" --metric "<metric>"
```

## Git behavior — public tool vs. private workspace

By default the **contents of `projects/` are gitignored** (only this README is
tracked), so the public `kaggloop` repo stays a clean tool. The rule lives in the
root `.gitignore`:

```gitignore
/projects/*
!/projects/README.md
```

**If you keep a private fork and want your competition work under version
control**, delete those two lines from `.gitignore`; your project folders will
then be tracked like any other file. (Keep `kaggle.json`, `.env`, and large data
out of git regardless — those stay ignored by their own rules.)
