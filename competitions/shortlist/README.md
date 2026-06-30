# Shortlist — discovery scratch for picking a competition

When the `kaggloop-scout` skill runs in **discovery mode** (you give it interests
rather than one competition), it drops lightweight TLDR cards here so a human can
compare candidates. These are ephemeral, pre-decision artifacts and are
gitignored (only this README is tracked).

The **main flow** is targeted: you give scout a single competition URL or slug
(e.g. from a web-app input), it creates a project and writes
`projects/<name>/TLDR.md`, and you make a go/no-go decision on that one. A chosen
competition becomes a real project under `projects/<name>/`; everything after the
human's "go" is automated.

```bash
# targeted (main): one competition in -> project + TLDR -> human decides
python -m kloop.project new --slug "<comp-slug>" --competition "<comp-slug>" --metric "<metric>"
# then /kaggloop-scout writes projects/<name>/TLDR.md for review, and on "go" -> /kaggloop-survey
```
