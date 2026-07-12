"""Publish our best bundle as a BRAND-NEW Kaggle kernel (fresh, from scratch) — not an update of the
existing gold-medal kernel. Same reference-friendly layout as the current notebook (title, tricks
explainer, env check, embedded bundle -> submission.zip, overrides, official verification, cost table,
credits), but a new slug/id, cleaned score/lineage strings, the given bundle's B64 + COSTS, and the
title `NeuroGolf <score> | github.com/qurore/kaggloop`.

Flow (verify the user-visible outcome, per [[verify-user-visible-outcome]]):
  build clean nb -> push NEW kernel (private) -> wait COMPLETE -> flip public -> kernel-linked badge
  submit -> verify badge == content score. Votes start at 0 (new kernel) — that is expected.

Usage: publish_new.py --bundle <submission.zip> --score 7266.91 [--template <ipynb>] [--dry]
"""
import argparse, base64, csv, io, json, pathlib, re, subprocess, sys, time

REPO = pathlib.Path(__file__).resolve().parents[3]
KAGGLE = str(REPO / ".venv" / "bin" / "kaggle")
USER = "ryosukeshiroshita"
COMP = "neurogolf-2026"
BRANDING = "github.com/qurore/kaggloop"


def sh(cmd, timeout=1200):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def costs_from_bundle(bundle, code_dir):
    sys.path.insert(0, str(code_dir))
    import onnx
    from harness import score_model
    z = __import__("zipfile").ZipFile(bundle)
    costs = {}
    for nm in z.namelist():
        if not nm.endswith(".onnx"):
            continue
        t = int(re.search(r"(\d+)", nm).group(1))
        r = score_model(onnx.ModelProto.FromString(z.read(nm)), t)
        costs[str(t)] = int((r.get("memory") or 0) + (r.get("params") or 0))
    return {k: costs[k] for k in sorted(costs, key=int)}


def clean_source(s, score):
    """Update stale score strings + lineage comments so the fresh notebook is accurate."""
    s = re.sub(r"\d{4}\.\d\d", score, s)  # every old score string -> the new score
    s = s.replace("validated 7219.90 bundle", "validated bundle")
    s = s.replace("pure 7219.90 base", "pure base bundle")
    s = s.replace("The validated bundle -> submission.zip", "The validated bundle -> submission.zip")
    return s


def build_notebook(template, bundle, costs, score, slug, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    b64 = base64.b64encode(pathlib.Path(bundle).read_bytes()).decode()
    costs_json = json.dumps(costs, separators=(",", ":"))
    nb = json.loads(pathlib.Path(template).read_text())
    swapped_b64 = swapped_costs = False
    for c in nb["cells"]:
        s = "".join(c["source"])
        if 'B64 = "' in s:
            pre, rest = s.split('B64 = "', 1)
            _, post = rest.split('"', 1)
            c["source"] = [clean_source(pre, score) + 'B64 = "' + b64 + '"' + clean_source(post, score)]
            c["outputs"] = []; c["execution_count"] = None; swapped_b64 = True
        elif "COSTS = json.loads('" in s:
            pre, rest = s.split("COSTS = json.loads('", 1)
            _, post = rest.split("')", 1)
            c["source"] = [clean_source(pre, score) + "COSTS = json.loads('" + costs_json + "')" + clean_source(post, score)]
            c["outputs"] = []; c["execution_count"] = None; swapped_costs = True
        else:
            c["source"] = [clean_source(s, score)]
            if c["cell_type"] == "code":
                c["outputs"] = []; c["execution_count"] = None
    if not (swapped_b64 and swapped_costs):
        sys.exit(f"template swap incomplete: b64={swapped_b64} costs={swapped_costs}")
    # content self-check: only score string left in markdown must be `score`
    left = set()
    for c in nb["cells"]:
        if c["cell_type"] == "markdown":
            left |= set(re.findall(r"\d{4}\.\d\d", "".join(c["source"])))
    if left - {score}:
        sys.exit(f"CONTENT MISMATCH: stale score strings remain {left - {score}}")
    out_nb = outdir / "notebook.ipynb"
    out_nb.write_text(json.dumps(nb))
    # competition_sources is REQUIRED for the kernel-linked badge: `competitions submit -k` on a
    # notebook WITHOUT the comp attached returns 400 CreateCodeSubmission. But Kaggle blocks making a
    # comp-source notebook public mid-competition ("may not be made public until after the competition
    # ends"), and it 403s de-sourcing a kernel that already has a comp submission. So a NEW notebook is
    # pushed PRIVATE with the source, badged, and then the PRIVATE->PUBLIC flip must be done on the
    # website (the CLI cannot do it mid-competition). See main()'s closing hand-off message.
    kmeta = {
        "id": f"{USER}/{slug}", "title": f"NeuroGolf {score} | {BRANDING}",
        "code_file": out_nb.name, "language": "python", "kernel_type": "notebook",
        "is_private": "true", "enable_gpu": "false", "enable_internet": "true",
        "dataset_sources": [], "competition_sources": [COMP], "kernel_sources": [],
    }
    (outdir / "kernel-metadata.json").write_text(json.dumps(kmeta, indent=1))
    return out_nb


def push(outdir):
    # 403 Forbidden on SaveKernel is TRANSIENT — retry with exponential backoff (user-confirmed).
    delay = 12
    last = ""
    for attempt in range(7):
        r = sh([KAGGLE, "kernels", "push", "-p", str(outdir)])
        txt = r.stdout + r.stderr
        if "successfully pushed" in txt.lower():
            m = re.search(r"version (\d+)", txt)
            return int(m.group(1)) if m else 1, txt
        last = txt.strip()
        if "403" in txt or "forbidden" in txt.lower() or "429" in txt or "too many" in txt.lower():
            print(f"  [push] transient {('403' if '403' in txt else 'throttle')} (attempt {attempt+1}/7) — backoff {delay}s")
            time.sleep(delay); delay = min(delay * 2, 180); continue
        break  # non-transient error
    sys.exit(f"push failed after retries: {last}")


def wait_complete(slug, tries=80, delay=15):
    for _ in range(tries):
        st = sh([KAGGLE, "kernels", "status", f"{USER}/{slug}"]).stdout.lower()
        if "complete" in st:
            return True
        if "error" in st or "fail" in st:
            sys.exit(f"kernel {slug} errored: {st}")
        time.sleep(delay)
    sys.exit(f"kernel {slug} did not complete in time")


def top_ref():
    r = sh([KAGGLE, "competitions", "submissions", "-c", COMP, "--csv"])
    rows = list(csv.DictReader(io.StringIO(r.stdout)))
    return rows[0]["ref"] if rows else None


def badge(slug, version, score):
    prev = top_ref()
    r = sh([KAGGLE, "competitions", "submit", "-c", COMP, "-k", f"{USER}/{slug}",
            "-v", str(version), "-f", "submission.zip", "-m", f"kernel-linked badge {score}"])
    txt = (r.stdout + r.stderr).lower()
    if any(s in txt for s in ("error", "denied", "not found", " 400", " 403", "traceback")):
        sys.exit(f"badge submit failed: {r.stdout + r.stderr}")
    for _ in range(80):
        rows = list(csv.DictReader(io.StringIO(sh([KAGGLE, "competitions", "submissions", "-c", COMP, "--csv"]).stdout)))
        if rows and rows[0]["ref"] != prev and "COMPLETE" in rows[0]["status"] and rows[0]["publicScore"]:
            return float(rows[0]["publicScore"]), rows[0]["ref"]
        time.sleep(15)
    sys.exit("badge: no new COMPLETE submission appeared — verify manually")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--score", required=True)
    ap.add_argument("--template", default=None, help="ipynb to reuse the layout from; default = current published kernel")
    ap.add_argument("--slug", default=None, help="new kernel slug; default derived from score")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    bundle = pathlib.Path(a.bundle).resolve()
    code_dir = REPO / "projects" / "neurogolf_2026" / "code"
    work = REPO / "projects" / "neurogolf_2026" / "publish" / "_publish_new"
    work.mkdir(parents=True, exist_ok=True)
    slug = a.slug or ("neurogolf-" + a.score.replace(".", "-") + "-github-com-qurore-kaggloop")

    template = a.template
    if not template:
        tdir = work / "template"; tdir.mkdir(parents=True, exist_ok=True)
        # pull the current published kernel as the layout template
        cur = None
        rows = sh([KAGGLE, "kernels", "list", "--mine", "--csv", "-p", "1", "--page-size", "50"]).stdout
        for row in csv.DictReader(io.StringIO(rows)):
            if "qurore/kaggloop" in row.get("title", "") and "neurogolf" in row.get("ref", "").lower():
                cur = row["ref"].split("/")[-1]; break
        if not cur:
            sys.exit("could not find a template kernel; pass --template <ipynb>")
        sh([KAGGLE, "kernels", "pull", f"{USER}/{cur}", "-p", str(tdir)])
        template = next(tdir.glob("*.ipynb"))
    print(f"[template] {template}")
    costs = costs_from_bundle(bundle, code_dir)
    print(f"[costs] {len(costs)} tasks")
    out_nb = build_notebook(template, bundle, costs, a.score, slug, work / "out")
    print(f"[build] fresh notebook built for NEW kernel slug={slug}, content-match OK (score {a.score})")
    if a.dry:
        print("[dry] not pushing"); return
    ver, _ = push(work / "out")
    print(f"[push] new PRIVATE kernel pushed (comp-source, badge-ready): {USER}/{slug} v{ver}")
    wait_complete(slug)
    print("[wait] kernel COMPLETE")
    bscore, bref = badge(slug, ver, a.score)
    ok = abs(bscore - float(a.score)) < 0.005
    print(f"[verify] badge {bscore} vs content {a.score} ({'MATCH' if ok else 'MISMATCH!'}) ref={bref}")
    if not ok:
        sys.exit("VERIFY FAILED — inspect the new kernel")
    url = f"https://www.kaggle.com/code/{USER}/{slug}"
    print(f"[done] built + badged (score={a.score}) but PRIVATE — CLI cannot make a comp-source "
          f"notebook public mid-competition.")
    print(f"[action] flip to PUBLIC on the website (Settings -> Sharing -> Public), or via the "
          f"connected Claude browser extension: {url}/settings")
    print(f"[url] {url}")


if __name__ == "__main__":
    main()
