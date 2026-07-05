---
name: kaggloop-publish
description: Upgrade the public Kaggle notebook to a user-specified bundle with a matching Public-Score badge. Use whenever the user says to publish / upgrade / "notebook-ify" a bundle or a new best score, or asks to put a specific score on the public notebook. Handles slug resolution, content-match, badge, and vote preservation automatically.
---

# kaggloop-publish — one-shot notebook version-up + matching Public-Score badge

Publish/upgrade the public forkable notebook so its **Public Score badge == the notebook's content == the exact bundle the user specified**, on the **same voted kernel** (votes preserved). This exists because doing it by hand kept failing in four ways; the script encodes the fixes.

## When to invoke
The user points at a bundle/score and says publish it — e.g. "これをノートブック化 / 同じ要領 / アップグレード / このスコアをPublic Scoreに載せて". They **specify which bundle** (safe primary vs challenge). Never guess the bundle.

## The one command
```bash
python .claude/skills/kaggloop-publish/publish.py \
  --bundle projects/<proj>/submissions/<iterN>_<kind>/submission.zip \
  --score auto            # or the bundle's already-known LB, e.g. 7221.08
```
- `--score auto` submits the bundle first, waits for the LB, and uses that number (guarantees content==badge).
- If you already submitted the bundle and know its LB, pass `--score 7221.08` to skip the extra submission.
- `--dry` builds + content-checks the notebook without pushing (use it to sanity-check first).
- The script prints each step and ends with a `[verify]` line (votes preserved + badge==content) and the live URL. If `[verify]` fails it exits non-zero — do not report success.

## Which bundle (the user chooses — do not assume)
- **Safe primary** (`submissions/<iterN>_primary/submission.zip`) — champions only, no divergence. The default "one-step-back safe" public bundle.
- **Challenge** (`submissions/<iterN>_challenge/submission.zip`) — primary + a *validated* divergence swap that HELD on the LB. Publish this only when the user asks for the higher/challenge score AND it has held on the hidden suite.
Confirm the bundle path scores what the user expects before publishing.

## The four failure modes it prevents (why each step exists)
1. **Stale slug → 0-vote duplicate.** The kernel re-slugs every time the score in its title changes (H1/title drives the slug). A hardcoded slug from last time is dead, so a push there creates a NEW 0-vote kernel. → The script resolves the CURRENT slug from the live `kernels list`, matching the stable branding marker (`github.com/qurore/kaggloop`) and taking the most-voted match.
2. **Wrong bundle (safe vs challenge).** → The caller passes `--bundle` explicitly; nothing is inferred.
3. **Content ≠ badge (stale header).** → `--score` is the bundle's ACTUAL LB, the COSTS table is recomputed from the EMBEDDED bundle (every onnx scored via the project harness), and a post-build self-check asserts the only score string left in the markdown is the new one.
4. **Vote loss.** → It pushes with `metadata id = current slug`, so Kaggle UPDATES the voted kernel (a title score-bump re-slugs it but keeps votes on the same kernel id). The `[verify]` step re-reads the vote count and fails loudly if it dropped.

## Notes / gotchas (learned the hard way)
- A title with the score (e.g. "NeuroGolf 7221.08") **re-slugs** the kernel to `neurogolf-7221-08-…` and **404s the old URL** — votes are preserved but shared links change. That is the accepted "same manner" behavior. (To stop the churn permanently, publish with a score-free title and keep the score only in the body+badge — offer this if the user tires of URL changes.)
- The badge is a **code submission**: `-k <current-slug> -v <version> -f submission.zip` where `-f` is the kernel's OUTPUT filename (`submission.zip`), NOT a local path. Passing a local path → 400.
- The CLI cannot delete kernels. A stray duplicate must be deleted by the user on the website (or re-pushed private).
- Never badge via the raw API or MCP — keep it on the `kaggle` CLI so the submission is visible/governed.
- After publishing, verify the **visible** result (the `[verify]` line): API success ≠ the badge being live. The notebook's score-sort position and the badge number are the real confirmation.

## Relation to the loop
Publishing is a periodic side-quest off the main gap-closing loop, not a loop stage. The public bundle is normally the **safe** one-step-back; only publish a challenge/divergence bundle when the user asks and it has held on the LB. Run this whenever a new best is worth surfacing; then return to the loop.
