"""kaggloop-publish — upgrade a public Kaggle notebook to a SPECIFIED bundle with a
Public-Score badge that matches the notebook's content. Automates the flow that used to need
manual instruction+correction every time.

It encodes the four failure modes seen in practice (each step notes the lesson):
  1. STALE SLUG -> a 0-vote duplicate kernel. Fix: resolve the CURRENT slug dynamically from
     the live kernel list (never hardcode).
  2. WRONG BUNDLE (safe vs challenge). Fix: the caller passes the exact --bundle; nothing is guessed.
  3. CONTENT != BADGE (stale header). Fix: score = the bundle's ACTUAL LB, and the COSTS table is
     computed from the EMBEDDED bundle, not a separate champions.json.
  4. VOTE LOSS. Fix: push with metadata id = the current slug so it UPDATES the voted kernel
     (an H1/title score change re-slugs it but preserves votes); verify the count afterward.

Usage:
  python publish.py --bundle <submission.zip> --score auto|<X> [--project neurogolf_2026]
                    [--branding "github.com/qurore/kaggloop"] [--name-prefix "NeuroGolf"] [--dry]

  --score auto  submits the bundle first (plain file), waits for the LB, and uses that number.
  --score <X>   uses X as the displayed score (X MUST be the bundle's real LB, else content!=badge).
  --dry         builds + verifies the notebook locally but does not push/badge.
"""
import argparse, base64, io, json, pathlib, re, subprocess, sys, time, zipfile

REPO = pathlib.Path(__file__).resolve().parents[3]
KAGGLE = str(REPO / ".venv" / "bin" / "kaggle")
PY = str(REPO / ".venv" / "bin" / "python")
COMP = "neurogolf-2026"
USER = "ryosukeshiroshita"


def sh(cmd, timeout=900):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def resolve_kernel(branding):
    """LESSON 1: find the CURRENT slug of the voted notebook by matching a stable branding marker
    in its title (never trust a hardcoded slug — it re-slugs on every score bump)."""
    out = sh([KAGGLE, "kernels", "list", "--user", USER, "--search", "neurogolf",
              "--page-size", "30"]).stdout
    best = None
    for line in out.splitlines()[2:]:
        if branding.split("/")[0] not in line:  # 'github.com' marker present
            continue
        parts = line.split()
        if not parts or "/" not in parts[0]:
            continue
        ref = parts[0].split("/", 1)[1]
        try:
            votes = int(parts[-1])
        except ValueError:
            continue
        if best is None or votes > best[1]:
            best = (ref, votes)
    return best  # (slug, votes) or None


def submit_bundle(bundle, msg):
    r = sh([KAGGLE, "competitions", "submit", "-c", COMP, "-f", str(bundle), "-m", msg])
    if "Successfully submitted" not in (r.stdout + r.stderr):
        sys.exit(f"submit failed: {r.stdout}\n{r.stderr}")
    return poll_latest_score()


def poll_latest_score(tries=60, delay=15):
    for _ in range(tries):
        r = sh([KAGGLE, "competitions", "submissions", "-c", COMP, "--csv"])
        import csv
        rows = list(csv.DictReader(io.StringIO(r.stdout)))
        if rows and "COMPLETE" in rows[0]["status"] and rows[0]["publicScore"]:
            return float(rows[0]["publicScore"]), rows[0]["ref"]
        time.sleep(delay)
    sys.exit("timed out waiting for submission score")


def costs_from_bundle(bundle, code_dir):
    """LESSON 3: COSTS table must reflect the EMBEDDED bundle exactly (score every onnx here),
    so the notebook's per-task table never disagrees with what forkers actually get."""
    sys.path.insert(0, str(code_dir))
    import onnx
    from harness import score_model  # project harness (authoritative cost)
    z = zipfile.ZipFile(bundle)
    costs = {}
    for nm in z.namelist():
        m = re.search(r"task0*(\d+)\.onnx", nm)
        if not m:
            continue
        tn = int(m.group(1))
        r = score_model(onnx.load(io.BytesIO(z.read(nm))), tn)
        costs[str(tn)] = int(r["memory"] + r["params"])
    return {k: costs[k] for k in sorted(costs, key=int)}


def pull_template(slug, dest):
    dest.mkdir(parents=True, exist_ok=True)
    sh([KAGGLE, "kernels", "pull", f"{USER}/{slug}", "-p", str(dest), "-m"])
    ipynb = sorted(dest.glob("*.ipynb"))
    if not ipynb:
        sys.exit(f"could not pull template notebook for {slug}")
    return ipynb[0]


def build_notebook(template, bundle, costs, score, slug, branding, prefix, outdir):
    """Swap the bundle B64 + COSTS + all score strings; target metadata id = CURRENT slug so the
    push UPDATES the voted kernel (LESSON 4)."""
    outdir.mkdir(parents=True, exist_ok=True)
    b64 = base64.b64encode(pathlib.Path(bundle).read_bytes()).decode()
    costs_json = json.dumps(costs, separators=(",", ":"))
    nb = json.loads(pathlib.Path(template).read_text())
    swapped_b64 = swapped_costs = False
    md_updates = 0
    old_scores = set()
    for c in nb["cells"]:
        s = "".join(c["source"])
        if c["cell_type"] == "markdown":
            for m in re.finditer(r"\d{4}\.\d\d", s):
                old_scores.add(m.group(0))
    old_scores.discard(score)
    for c in nb["cells"]:
        s = "".join(c["source"])
        if c["cell_type"] == "markdown":
            new = s
            for old in old_scores:
                new = new.replace(old, score)
            if new != s:
                c["source"] = [new]
                md_updates += 1
        elif 'B64 = "' in s:
            pre, rest = s.split('B64 = "', 1)
            _, post = rest.split('"', 1)
            c["source"] = [pre + 'B64 = "' + b64 + '"' + post]
            c["outputs"] = []; c["execution_count"] = None; swapped_b64 = True
        elif "COSTS = json.loads('" in s:
            pre, rest = s.split("COSTS = json.loads('", 1)
            _, post = rest.split("')", 1)
            c["source"] = [pre + "COSTS = json.loads('" + costs_json + "')" + post]
            c["outputs"] = []; c["execution_count"] = None; swapped_costs = True
    # md_updates may be 0 when the template already shows the target score (idempotent re-publish);
    # correctness is guaranteed by the final content-match self-check below, not by a swap happening.
    if not (swapped_b64 and swapped_costs):
        sys.exit(f"template swap incomplete: b64={swapped_b64} costs={swapped_costs}")
    out_nb = outdir / pathlib.Path(template).name
    out_nb.write_text(json.dumps(nb))
    kmeta = {
        "id": f"{USER}/{slug}", "title": f"{prefix} {score} | {branding}",
        "code_file": out_nb.name, "language": "python", "kernel_type": "notebook",
        "is_private": "false", "enable_gpu": "false", "enable_internet": "true",
        "dataset_sources": [], "competition_sources": [COMP], "kernel_sources": [],
    }
    (outdir / "kernel-metadata.json").write_text(json.dumps(kmeta, indent=1))
    # content-match self-check: after the swap, the only score string left must be `score`
    left = set()
    for c in nb["cells"]:
        if c["cell_type"] == "markdown":
            left |= set(re.findall(r"\d{4}\.\d\d", "".join(c["source"])))
    if left - {score}:
        sys.exit(f"CONTENT MISMATCH: stale score strings remain {left - {score}}")
    return out_nb


def push(outdir):
    r = sh([KAGGLE, "kernels", "push", "-p", str(outdir)])
    txt = r.stdout + r.stderr
    m = re.search(r"version (\d+) successfully pushed", txt)
    slug_m = re.search(r"kaggle\.com/\S+?/([\w-]+)\s*$", txt.strip())
    if not m:
        sys.exit(f"push failed: {txt}")
    return int(m.group(1)), (slug_m.group(1) if slug_m else None)


def wait_complete(slug, tries=60, delay=15):
    for _ in range(tries):
        st = sh([KAGGLE, "kernels", "status", f"{USER}/{slug}"]).stdout.lower()
        if "complete" in st:
            return True
        if "error" in st or "fail" in st:
            sys.exit(f"kernel {slug} errored: {st}")
        time.sleep(delay)
    sys.exit(f"kernel {slug} did not complete")


def badge(slug, version, score):
    r = sh([KAGGLE, "competitions", "submit", "-c", COMP, "-k", f"{USER}/{slug}",
            "-v", str(version), "-f", "submission.zip",
            "-m", f"kernel-linked badge {score}"])
    if "Successfully submitted" not in (r.stdout + r.stderr):
        sys.exit(f"badge submit failed: {r.stdout}\n{r.stderr}")
    return poll_latest_score()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--score", required=True, help="'auto' or the bundle's real LB e.g. 7221.08")
    ap.add_argument("--project", default="neurogolf_2026")
    ap.add_argument("--branding", default="github.com/qurore/kaggloop")
    ap.add_argument("--name-prefix", default="NeuroGolf", dest="prefix")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    bundle = pathlib.Path(a.bundle).resolve()
    code_dir = REPO / "projects" / a.project / "code"
    work = REPO / "projects" / a.project / "publish" / "_publish_work"

    kern = resolve_kernel(a.branding)
    if not kern:
        sys.exit("could not resolve current kernel slug (LESSON 1) — check kernels list")
    slug, votes = kern
    print(f"[resolve] current kernel: {slug}  votes={votes}")

    if a.score == "auto":
        print("[score] --score auto: submitting bundle to learn the LB ...")
        score, ref = submit_bundle(bundle, f"auto-score for notebook publish ({bundle.name})")
        score = f"{score:.2f}"
        print(f"[score] bundle LB = {score} (ref {ref})")
    else:
        score = a.score

    print("[costs] computing COSTS from the embedded bundle ...")
    costs = costs_from_bundle(bundle, code_dir)
    print(f"[costs] {len(costs)} tasks (task285={costs.get('285')})")

    template = pull_template(slug, work / "template")
    out_nb = build_notebook(template, bundle, costs, score, slug, a.branding, a.prefix, work / "out")
    print(f"[build] notebook built, content-match OK (only score string = {score})")

    if a.dry:
        print(f"[dry] would push to {slug} + badge {score}; skipping (--dry)")
        return

    version, new_slug = push(work / "out")
    new_slug = new_slug or slug
    print(f"[push] version {version} pushed; slug now {new_slug}")
    wait_complete(new_slug)
    print("[wait] kernel COMPLETE")
    bscore, bref = badge(new_slug, version, score)
    print(f"[badge] scored {bscore} (ref {bref})")

    # LESSON 4 + verify-visible-outcome: votes preserved and badge == content
    kern2 = resolve_kernel(a.branding)
    ok_votes = kern2 and kern2[1] >= votes
    ok_score = abs(bscore - float(score)) < 0.005
    print(f"[verify] votes {votes}->{kern2[1] if kern2 else '?'} ({'OK' if ok_votes else 'LOST!'}); "
          f"badge {bscore} vs content {score} ({'MATCH' if ok_score else 'MISMATCH!'})")
    if not (ok_votes and ok_score):
        sys.exit("VERIFY FAILED — inspect the kernel before trusting the publish")
    print(f"[done] https://www.kaggle.com/code/{USER}/{kern2[0]}  score={score}  votes={kern2[1]}")


if __name__ == "__main__":
    main()
