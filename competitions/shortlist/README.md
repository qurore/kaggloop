# Shortlist — pick a competition

The `kaggloop-scout` stage writes one TLDR card per candidate competition into this
folder (`<comp-slug>.md`) and maintains the ranked table below. **A human chooses** which
competition to enter from these cards — that is the one mandatory human-in-the-loop gate.
Everything after selection is automated.

<!-- scout maintains the table below -->

| Rank | Competition | Metric | Deadline | Effort | Fit (1–5) | Recommendation |
|-----:|-------------|--------|----------|:------:|:---------:|----------------|
| _(run `/kaggloop-scout` to populate)_ | | | | | | |

Once you've chosen, tell the agent, then it seeds the campaign:

```bash
python -m kloop.run new --slug "<comp-slug>" --competition "<comp-slug>" --metric "<metric>"
```

and proceeds with `/kaggloop-survey`.
