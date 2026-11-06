# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Derive the next hour's mixture identity, epoch sidecar, shards root and cap from the parent hour's.

The template is the parent hour's mixture identity. Only the fields in WHITELIST may differ from it; every
other leaf must stay byte-equal, or the build refuses. The template's sha and the field diff are recorded in
`resume_derivation`. Changing any other field is a code change with its own review, never an edit at run time.

Proofs, each a refusal:
  - shards root: the new root's digest list starts with the parent root's digest list verbatim (a proven
    superset); every file is a hard link (same file id as its source); every extension shard's sha256 equals
    its ledger row's `sha256`;
  - sidecar: labels for the trained rows are byte-equal to the parent sidecar's rows; every extension row is
    epoch 0, never repeat-declared;
  - cursor: taken from the parent's continuation-hour.json terminal_data_cursor (what the trainer consumed,
    never the planned span); continuation-next-pack.json cursor_before must equal it, and it must lie inside
    the parent's trained rows.
  - image slot: the manifest comes from the parent hour's input_binding.image_text, never from a script default. It
    binds only with a C1/C2 receipt whose verdict is PASS and whose candidate_sha256 is that manifest's sha;
    and the manifest must not be re-read more than MAX_IMAGE_PASSES times per hour at the rate cap;
    otherwise the hour is text-only (image_text None, every document from the text stream), recorded in
    resume_derivation. Unverified rows are never trained to keep the recipe identical.
Stdlib only, CPU only. Never starts a process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

WHITELIST = frozenset({
    "data.cursor.shard_index", "data.cursor.token_offset",
    "data.shard_ledger_path", "data.shard_ledger_sha256", "data.shards_root",
    "stream.hour_start_token", "stream.ledger_rows", "stream.total_stream_tokens",
    "stream.tokens_available_from_cursor",
    "h35_source_binding.consumer_ledger.sha256", "h35_source_binding.consumer_ledger.epoch_label_sidecar_sha256",
    "h35_source_binding.shards_root.path", "h35_source_binding.shards_root.files",
    "h35_source_binding.shards_root.digest_list_sha256", "h35_source_binding.shards_root.receipt_path",
    "h35_source_binding.shards_root.receipt_sha256",
})
DERIVATION_KEY = "resume_derivation"
CAP_RATE = 21.812776  # updates/s: the H22 maximum the parent cap used
CAP_CEILING = 131072
PAIRS_PER_UPDATE = 8  # image-text pairs in the one image document of an update
MAX_IMAGE_PASSES = 4  # bind the image slot only if the manifest is not re-read more than this per hour
DOC = 1024  # positions per document; 4 documents per update, one of them image-text when bound


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def refuse(why: str):
    raise SystemExit(f"REFUSE {why}")


def leaves(o, p=""):
    if isinstance(o, dict):
        for k in sorted(o):
            yield from leaves(o[k], f"{p}.{k}" if p else k)
    else:
        yield p, json.dumps(o, sort_keys=True)


def field_diff(template: dict, out: dict) -> list[str]:
    a = {k: v for k, v in leaves(template) if not k.startswith(DERIVATION_KEY)}
    b = {k: v for k, v in leaves(out) if not k.startswith(DERIVATION_KEY)}
    return sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))


def extend_root(parent_receipt: dict, new_root: Path, ext_rows: list[dict], ext_src: dict[str, Path]) -> dict:
    old_root = Path(parent_receipt["root"])
    old_list = parent_receipt["digest_list"].rstrip("\n")
    old_names = [ln.split("  ", 1)[1] for ln in old_list.splitlines()]
    new_root.mkdir(parents=True, exist_ok=True)
    lines = [old_list]
    for name in old_names:
        _link(old_root / name, new_root / name)
    for r in ext_rows:
        dst = new_root / r["name"]
        _link(ext_src[r["name"]], dst)
        if sha_file(dst) != r["sha256"]:
            refuse(f"extension shard {r['name']} sha does not match its ledger row")
        lines.append(f"{r['sha256']}  {r['name']}")
    digest_list = "\n".join(lines) + "\n"
    if not digest_list.startswith(old_list + "\n"):
        refuse("new digest list does not start with the parent digest list verbatim")
    return {"schema": "ember-resume-root-receipt-v1", "root": str(new_root).replace("\\", "/"),
            "count": len(old_names) + len(ext_rows), "parent_root": str(old_root).replace("\\", "/"),
            "parent_count": len(old_names), "digest_list": digest_list, "digest_list_sha256": sha_bytes(digest_list.encode()),
            "hard_links_only": True}


def _link(src: Path, dst: Path) -> None:
    if dst.exists():
        if os.stat(dst).st_ino != os.stat(src).st_ino or os.stat(dst).st_dev != os.stat(src).st_dev:
            refuse(f"{dst} exists and is not a hard link of {src}")
        return
    os.link(src, dst)


def sidecar(parent: dict, rows: list[dict], n_trained: int, ledger_sha: str) -> dict:
    prev = parent["rows"]
    if len(prev) != n_trained:
        refuse(f"parent sidecar has {len(prev)} rows, the trained ledger {n_trained}")
    out_rows = [dict(r) for r in prev]
    for r in rows[n_trained:]:
        out_rows.append({"cls": "fresh", "epoch": 0, "index": r["index"], "ledger_pass_index": 0,
                         "n_tokens": r["n_tokens"], "name": r["name"], "repeat_declared": False,
                         "row_sha256": r["row_sha256"], "token_start": r["token_start"]})
    for a, b in zip(prev, out_rows):
        if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
            refuse(f"sidecar label for trained row {a.get('index')} changed")
    if any(x["epoch"] != 0 or x["repeat_declared"] for x in out_rows[n_trained:]):
        refuse("an extension row is not epoch 0")
    out = {k: v for k, v in parent.items() if k != "rows"}
    out.update(ledger_sha256=ledger_sha, rows=out_rows)
    return out


def parent_cursor(rows: list[dict], n_trained: int, continuation_hour: Path, next_pack: Path) -> tuple[int, int, int]:
    """(shard_index, token_offset, absolute end) of what the parent trainer consumed: its terminal_data_cursor,
    cross-checked with the next pack's cursor_before, inside the first n_trained rows of `rows`."""
    tc = json.loads(continuation_hour.read_text(encoding="utf-8"))["terminal_data_cursor"]
    nb = json.loads(next_pack.read_text(encoding="utf-8"))["cursor_before"]
    shard_index, token_offset = int(tc["shard"]), int(tc["record_index"])
    if (int(nb["shard_index"]), int(nb["token_offset"])) != (shard_index, token_offset):
        refuse(f"next-pack cursor_before {nb} differs from terminal_data_cursor {tc}")
    if not (0 <= shard_index < n_trained and 0 <= token_offset < rows[shard_index]["n_tokens"]):
        refuse(f"terminal cursor {tc} is not inside the parent's trained rows")
    end = sum(r["n_tokens"] for r in rows[:shard_index]) + token_offset
    if "token_start" in rows[shard_index] and int(rows[shard_index]["token_start"]) + token_offset != end:
        refuse("ledger token_start disagrees with the summed row lengths")
    return shard_index, token_offset, end


def image_slot(parent_hour: dict, receipt_path: Path | None) -> dict:
    parent = parent_hour["input_binding"].get("image_text")
    if parent is None:
        return {"image_text": None, "reason": "parent hour bound no image_text"}
    if receipt_path is None:
        return {"image_text": None, "reason": "no C1/C2 receipt for the parent image manifest", "parent_manifest_sha256": parent["manifest_sha256"]}
    r = json.loads(receipt_path.read_text(encoding="utf-8"))
    if r.get("verdict") != "PASS":
        refuse(f"image manifest receipt verdict is {r.get('verdict')}, not PASS")
    if r.get("inputs", {}).get("candidate_sha256") != parent["manifest_sha256"]:
        refuse("image manifest receipt names a different manifest than the parent hour bound")
    rows = sum(1 for ln in Path(parent["manifest_path"]).read_text(encoding="utf-8").splitlines() if ln.strip())
    passes = PAIRS_PER_UPDATE * math.ceil(CAP_RATE * 3600 * 1.25) / rows
    if passes > MAX_IMAGE_PASSES:
        return {"image_text": None, "reason": f"{rows} rows give {passes:.2f} passes per hour at the rate cap (> {MAX_IMAGE_PASSES})",
                "parent_manifest_sha256": parent["manifest_sha256"], "receipt_sha256": sha_file(receipt_path)}
    return {"image_text": dict(parent), "reason": "C1/C2 PASS", "receipt_sha256": sha_file(receipt_path),
            "rows": rows, "passes_per_hour_at_rate_cap": passes}


def build(a) -> dict:
    template_bytes = a.template.read_bytes()
    template = json.loads(template_bytes)
    composed_bytes = a.composed_ledger.read_bytes()
    rows = [json.loads(x) for x in composed_bytes.decode("utf-8").splitlines() if x.strip()]
    ledger_sha = sha_bytes(composed_bytes)
    n_trained = len(json.loads(a.parent_sidecar.read_text(encoding="utf-8"))["rows"])
    shard_index, token_offset, end = parent_cursor(rows, n_trained, a.parent_continuation_hour, a.parent_next_pack)
    total = sum(r["n_tokens"] for r in rows)
    a.out.mkdir(parents=True, exist_ok=True)
    ext_src = {}
    for d in a.intake:
        for r in (json.loads(x) for x in (d / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()):
            ext_src[r["name"]] = d / "shards" / r["name"]
    root = extend_root(json.loads(a.parent_root_receipt.read_text(encoding="utf-8")), a.shards_root, rows[n_trained:], ext_src)
    root_path = a.out / "root-receipt.json"
    root_path.write_text(json.dumps(root, indent=1, sort_keys=True), encoding="utf-8")
    side = sidecar(json.loads(a.parent_sidecar.read_text(encoding="utf-8")), rows, n_trained, ledger_sha)
    side_path = a.out / "epoch-labels.json"
    side_path.write_text(json.dumps(side, indent=1, sort_keys=True), encoding="utf-8")
    m = json.loads(template_bytes)
    d, s, b = m["data"], m["stream"], m["h35_source_binding"]
    d["cursor"] = {"shard_index": shard_index, "token_offset": token_offset}
    d["shard_ledger_path"] = str(a.composed_ledger).replace("\\", "/")
    d["shard_ledger_sha256"] = ledger_sha
    d["shards_root"] = root["root"]
    s.update(hour_start_token=end, ledger_rows=len(rows), total_stream_tokens=total,
             tokens_available_from_cursor=total - end)
    b["consumer_ledger"]["sha256"] = ledger_sha
    b["consumer_ledger"]["epoch_label_sidecar_sha256"] = sha_file(side_path)
    b["shards_root"].update(path=root["root"], files=root["count"], digest_list_sha256=root["digest_list_sha256"],
                            receipt_path=str(root_path).replace("\\", "/"), receipt_sha256=sha_file(root_path))
    diff = field_diff(template, m)
    outside = [k for k in diff if k not in WHITELIST]
    if outside:
        refuse(f"fields outside the frozen whitelist changed: {outside}")
    img = image_slot(json.loads(a.parent_hour_result.read_text(encoding="utf-8")), a.image_receipt)
    m[DERIVATION_KEY] = {"template_sha256": sha_bytes(template_bytes), "changed_fields": diff,
                         "whitelist": sorted(WHITELIST), "image_slot": img}
    ident_path = a.out / "mixture-identity.json"
    ident_path.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
    avail = total - end
    stream_per_update = DOC * (3 if img["image_text"] is not None else 4)
    data_cap = math.floor((avail - 1) / stream_per_update) - 2
    rate_cap = math.ceil(CAP_RATE * 3600 * 1.25)
    cap = min(rate_cap, data_cap, CAP_CEILING)
    cap_rec = json.loads(a.parent_cap.read_text(encoding="utf-8"))
    cap_rec.update(cap=cap, rate_cap=rate_cap, data_cap=data_cap, data_bound=cap == data_cap, ledger_sha256=ledger_sha,
                   interleaved_available_tokens=avail, interleave_end_abs=total,
                   derivation=f"cap = min(ceil({CAP_RATE} x 3600 x 1.25), floor(({avail} - 1)/{stream_per_update}) - 2 = {data_cap}, {CAP_CEILING}) = {cap}")
    cap_path = a.out / "cap.json"
    cap_path.write_text(json.dumps(cap_rec, indent=1, sort_keys=True), encoding="utf-8")
    return {"mixture_identity_sha256": sha_file(ident_path), "template_sha256": sha_bytes(template_bytes),
            "changed_fields": diff, "cursor": d["cursor"], "cap": cap, "root_count": root["count"],
            "epoch_labels_sha256": sha_file(side_path), "cap_sha256": sha_file(cap_path),
            "image_text": img["image_text"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    for f in ("--template", "--parent-sidecar", "--parent-root-receipt", "--parent-cap", "--parent-continuation-hour", "--parent-next-pack", "--parent-hour-result",
              "--composed-ledger", "--shards-root", "--out"):
        ap.add_argument(f, required=True, type=Path)
    ap.add_argument("--intake", action="append", required=True, type=Path)
    ap.add_argument("--image-receipt", type=Path, default=None)
    print(json.dumps(build(ap.parse_args(argv)), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
