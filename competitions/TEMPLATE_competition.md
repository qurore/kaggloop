<!--
TLDR card template for the scout stage. One file per candidate competition under
competitions/shortlist/<comp-slug>.md. Keep it to ~one screen — the point is to let a
HUMAN choose the theme fast. Fill every field; write "?" if unknown rather than guessing.
-->

# <Competition title>  ·  `<comp-slug>`

**TLDR:** <one sentence: what you predict, from what, scored how>

|              |                                   |
|--------------|-----------------------------------|
| Metric       | `<exact metric>` (<maximize/minimize>) |
| Scoring mode | <automated LB / judged writeup / hybrid> |
| Best public  | <best public notebook's Public Score — the de-facto floor the loop starts from and must beat> |
| Deadline     | <date>  ·  <N days left>          |
| Prize / type | <$ or knowledge>  ·  <featured/research/playground/code> |
| Teams        | <count>  ·  Submissions/day: <N>  |
| Data         | <modality>, <train/test size>, fits 1 Colab GPU: <yes/no/tight> |

## Why we might win
- <concrete edge: metric quirk, CV strategy, an arXiv method, under-exploited data, a leak the host allows>

## Risks
- <saturated LB / shake-up risk / leakage bans / huge data / code-competition runtime limits / external-data rules>

## Top public notebooks (signal)
- <ref> — <public score> — <key idea>
- <ref> — <public score> — <key idea>

## Effort & fit
- **Effort:** <S/M/L>  ·  rough wall-clock per experiment on Colab: <~minutes/hours>
- **kaggloop fit (1–5):** <n> — <one line: how well it suits this exploratory, science-backed, Colab-bound loop>

## Recommendation
<one line: pursue / maybe / skip — and why>
