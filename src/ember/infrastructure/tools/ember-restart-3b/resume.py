# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""`ember-lab resume` data leg: compose -> C1/C2 gate -> certificate -> daemon issuance.

Composes the next ledger (resume_compose.py), splits out the extension rows, merges the intakes' source manifests,
runs the C1/C2 gate on the extension, and writes a run certificate binding the composed ledger, the gate receipt,
the parent checkpoint manifest and the trainer tree: --trainer-checkout must be clean, at the trainer_tree pinned in
resume-lineage.json, and that tree must carry its lineage tag. The daemon re-hashes the ledger and
receipt before it records the certificate (`ember-lab issue-certificate`). Refuses at the first failed step.

The trained end is never an input: it is the parent trainer's terminal_data_cursor (continuation-hour.json),
cross-checked with continuation-next-pack.json (resume_identity.parent_cursor). The next hour's mixture identity,
epoch sidecar, shards root receipt, cap and image slot are derived by resume_identity.py into OUT/identity.

  python -I resume.py --trained L --parent-continuation-hour F --parent-next-pack F --parent-hour-result F
         --parent-sidecar F --parent-root-receipt F --parent-cap F --template F [--image-receipt F]
         --intake DIR ... --seed S --add-tokens N --shards-root DIR
         --parent-manifest FILE --out DIR --pipe PIPE --ember-lab EXE --trainer-checkout DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import resume_identity  # noqa: E402
SCHEMA = "ember-lab-run-certificate-v1"


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        step = Path(cmd[2] if cmd[1:2] == ["-I"] else cmd[0]).name
        raise SystemExit(f"REFUSE {step} rc {p.returncode}: {(p.stderr or p.stdout)[-600:]}")
    return p.stdout


LINEAGE = HERE / "resume-lineage.json"


def code_tree_sha(checkout: Path) -> str:
    """The trainer checkout's HEAD, which must be the pinned lineage tree, clean, and tagged."""
    pin = json.loads(LINEAGE.read_text(encoding="utf-8"))
    head = run(["git", "-C", str(checkout), "rev-parse", "HEAD"]).strip()
    if head != pin["trainer_tree"]:
        raise SystemExit(f"REFUSE trainer checkout HEAD {head} is not the pinned trainer_tree {pin['trainer_tree']}")
    tagged = run(["git", "-C", str(checkout), "rev-parse", pin["trainer_tag"] + "^{commit}"]).strip()
    if tagged != head:
        raise SystemExit(f"REFUSE tag {pin['trainer_tag']} names {tagged}, not the pinned trainer_tree")
    if run(["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=all"]).strip():
        raise SystemExit("REFUSE trainer checkout has uncommitted or untracked changes")
    return head


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    for f in ("--trained", "--shards-root", "--parent-manifest", "--out", "--ember-lab", "--trainer-checkout",
              "--parent-continuation-hour", "--parent-next-pack", "--parent-hour-result", "--parent-sidecar",
              "--parent-root-receipt", "--parent-cap", "--template"):
        ap.add_argument(f, required=True, type=Path)
    ap.add_argument("--intake", action="append", required=True, type=Path)
    ap.add_argument("--image-receipt", type=Path, default=None)
    ap.add_argument("--add-tokens", required=True, type=int)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--pipe", required=True)
    a = ap.parse_args(argv)
    tree = code_tree_sha(a.trainer_checkout)
    trained_rows = [json.loads(x) for x in open(a.trained, encoding="utf-8") if x.strip()]
    n_side = len(json.loads(a.parent_sidecar.read_text(encoding="utf-8"))["rows"])
    if n_side != len(trained_rows):
        raise SystemExit(f"REFUSE parent sidecar has {n_side} rows, the trained ledger {len(trained_rows)}")
    *_, a.trained_end = resume_identity.parent_cursor(trained_rows, n_side, a.parent_continuation_hour, a.parent_next_pack)
    a.out.mkdir(parents=True, exist_ok=True)
    py = [sys.executable, "-I"]
    run(py + [str(HERE / "resume_compose.py"), "--trained", str(a.trained), "--trained-end", str(a.trained_end),
              *sum((["--intake", str(d)] for d in a.intake), []), "--seed", a.seed, "--add-tokens", str(a.add_tokens),
              "--shards-root", str(a.shards_root), "--out", str(a.out)])
    n_trained = sum(1 for x in open(a.trained, encoding="utf-8") if x.strip())
    composed = (a.out / "composed-ledger.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
    ext = a.out / "extension-ledger.jsonl"
    ext.write_text("".join(composed[n_trained:]), encoding="utf-8")
    sources = a.out / "sources.jsonl"
    with open(sources, "w", encoding="utf-8") as w:
        for d in a.intake:
            w.write((d / "source-manifest.jsonl").read_text(encoding="utf-8"))
    receipt = a.out / "c1c2-receipt.json"
    run(py + [str(HERE / "c1c2_interim_gate.py"), "--trained", str(a.trained), "--trained-end", str(a.trained_end),
              "--candidate", str(ext), "--sources", str(sources), "--out", str(receipt)])
    ident = [*py, str(HERE / "resume_identity.py"), "--template", a.template, "--parent-sidecar", a.parent_sidecar,
             "--parent-root-receipt", a.parent_root_receipt, "--parent-cap", a.parent_cap,
             "--parent-continuation-hour", a.parent_continuation_hour, "--parent-next-pack", a.parent_next_pack,
             "--parent-hour-result", a.parent_hour_result, "--composed-ledger", a.out / "composed-ledger.jsonl",
             "--shards-root", a.shards_root, "--out", a.out / "identity",
             *sum((["--intake", d] for d in a.intake), [])]
    if a.image_receipt is not None:
        ident += ["--image-receipt", a.image_receipt]
    run([str(x) for x in ident])
    comp = json.loads((a.out / "composition.json").read_text(encoding="utf-8"))
    cert = {"schema_version": SCHEMA, "ledger_path": str(a.out / "composed-ledger.jsonl"),
            "ledger_sha256": sha(a.out / "composed-ledger.jsonl"), "extension_ledger_sha256": sha(ext),
            "c1c2_receipt_path": str(receipt), "c1c2_receipt_sha256": sha(receipt),
            "parent_manifest_path": str(a.parent_manifest), "parent_manifest_sha256": sha(a.parent_manifest),
            "code_tree_sha": tree, "trainer_checkout": str(a.trainer_checkout), "trained_end": a.trained_end, "composition_sha256": sha(a.out / "composition.json"),
            "seed": a.seed, "added_tokens": comp["added_tokens"]}
    cp = a.out / "run-certificate.json"
    cp.write_text(json.dumps(cert, sort_keys=True, indent=1), encoding="utf-8")
    print(run([str(a.ember_lab), "issue-certificate", "--pipe", a.pipe, "--certificate", str(cp)]).strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
