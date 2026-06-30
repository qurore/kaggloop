"""kloop — thin helpers the kaggloop Claude Code skills shell out to.

These modules are deliberately *thin*: the intelligence lives in the skills
(i.e. in you, the Claude Code agent). They do the mechanical bookkeeping that
makes a competition campaign reproducible and resumable — campaign state, the
hypothesis ledger, kaggle CLI wrappers, the Colab compute bridge, and local
ensembling.

Run them as modules from the repo root, e.g.::

    python -m kloop.project new --slug titanic --competition titanic --metric accuracy
    python -m kloop.kaggle list --category getting-started
    python -m kloop.ledger add --title "pseudo-labeling" --expected-gain 0.004 --confidence 0.6
    python -m kloop.colab  submit --script train.py --timeout 5400
    python -m kloop.score  blend oof_a.npy oof_b.npy --out blend.npy --metric auc --y-true y.npy

Console output is Japanese (user-facing); all code, comments, and docstrings are
English.
"""

__all__ = ["state", "project", "ledger", "kaggle", "colab", "score", "gate", "journal"]
