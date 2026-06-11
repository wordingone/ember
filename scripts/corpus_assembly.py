"""corpus_assembly.py — eng #130 final assembly receipt over all 5 sources.

Fail-closed verification BEFORE any receipt write (no partial artifacts):
  1. exactly ONE manifest mirror per source in corpus-manifests/
     (the canonical run; superseded receipts are ignored by ts-match);
  2. the per-source receipt eng36-<source>-<ts>.json exists and its
     manifest_sha256 matches a fresh hash of the repo mirror
     (byte-identical mirror claim re-verified);
  3. every shard listed in every manifest exists on disk with the
     recorded size AND full sha256 (re-hashed here, ~25GB);
  4. per-source docs_kept == sum of shard doc counts;
  5. totals under the <100GB HARD bar.

Token numbers stay HEURISTIC ONLY (tokenizer not frozen — fp-22):
quoted as raw bytes/chars + bytes-per-token heuristic estimates.

Run:  python scripts/corpus_assembly.py
      (after all 5 ENG36_ACQUIRE_DONE receipts exist)
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import corpus_acquire as ca  # noqa: E402  (SOURCES registry + file_sha256)
from receipt_write import checked_write  # noqa: E402

HARD_BAR_BYTES = 100_000_000_000  # fp-22 <100GB HARD
RAW_TARGET_BYTES = 30_000_000_000  # fp-22 ~30GB raw target (soft, report)


def verify_source(source, out_root):
    """Verify one source end-to-end; returns its assembly row.
    Raises (fail-closed) on any mismatch — nothing is written then."""
    mirrors = sorted(glob.glob(
        os.path.join(REPO, "corpus-manifests", f"{source}-manifest-*.json")))
    if len(mirrors) != 1:
        raise SystemExit(f"assembly: {source}: expected exactly 1 manifest "
                         f"mirror, found {len(mirrors)}: {mirrors}")
    mirror_path = mirrors[0]
    manifest = json.load(open(mirror_path, encoding="utf-8"))
    ts = manifest["ts"]

    receipt_path = os.path.join(REPO, "receipts", f"eng36-{source}-{ts}.json")
    if not os.path.exists(receipt_path):
        raise SystemExit(f"assembly: {source}: receipt missing for the "
                         f"canonical run ts={ts}: {receipt_path}")
    receipt = json.load(open(receipt_path, encoding="utf-8"))

    mirror_sha = ca.file_sha256(mirror_path)
    if receipt["manifest_sha256"] != mirror_sha:
        raise SystemExit(f"assembly: {source}: manifest mirror sha mismatch "
                         f"(receipt {receipt['manifest_sha256'][:12]} != "
                         f"mirror {mirror_sha[:12]})")

    out_dir = os.path.join(out_root, source)
    disk_bytes = 0
    shard_docs = 0
    for s in manifest["shards"]:
        p = os.path.join(out_dir, s["file"])
        if not os.path.exists(p):
            raise SystemExit(f"assembly: {source}: shard missing: {p}")
        size = os.path.getsize(p)
        if size != s["bytes_on_disk"]:
            raise SystemExit(f"assembly: {source}: {s['file']} size {size} "
                             f"!= recorded {s['bytes_on_disk']}")
        got = ca.file_sha256(p)
        if got != s["sha256"]:
            raise SystemExit(f"assembly: {source}: {s['file']} sha mismatch "
                             f"({got[:12]} != {s['sha256'][:12]})")
        disk_bytes += size
        shard_docs += s["docs"]

    counts = manifest["counts"]
    if counts["docs_kept"] != shard_docs:
        raise SystemExit(f"assembly: {source}: docs_kept "
                         f"{counts['docs_kept']} != shard sum {shard_docs}")

    print(f"[assembly] {source}: {len(manifest['shards'])} shards OK, "
          f"docs={counts['docs_kept']} text_bytes="
          f"{counts['text_bytes_kept']} disk={disk_bytes}", flush=True)
    return {
        "source": source,
        "ts": ts,
        "fp22_row": ca.SOURCES[source]["fp22_row"],
        "license_class": ca.SOURCES[source]["license_class"],
        "docs_kept": counts["docs_kept"],
        "text_bytes_kept": counts["text_bytes_kept"],
        "text_chars_kept": counts["text_chars_kept"],
        "bytes_on_disk": disk_bytes,
        "n_shards": len(manifest["shards"]),
        "manifest_mirror": os.path.relpath(mirror_path, REPO),
        "manifest_sha256": mirror_sha,
        "receipt": os.path.relpath(receipt_path, REPO),
        "url_pin": manifest["url_pin"],
    }


def main():
    ap_out_root = ca.OUT_ROOT_DEFAULT
    rows = [verify_source(s, ap_out_root) for s in ca.SOURCES]

    fp22_rows = sorted(r["fp22_row"] for r in rows)
    if fp22_rows != [1, 2, 3, 4, 5]:
        raise SystemExit(f"assembly: fp-22 §1 coverage broken: {fp22_rows}")

    total_text = sum(r["text_bytes_kept"] for r in rows)
    total_disk = sum(r["bytes_on_disk"] for r in rows)
    total_docs = sum(r["docs_kept"] for r in rows)
    if total_disk >= HARD_BAR_BYTES or total_text >= HARD_BAR_BYTES:
        raise SystemExit(f"assembly: <100GB HARD bar violated: "
                         f"text={total_text} disk={total_disk}")

    # HEURISTIC ONLY (fp-22): tokenizer not frozen; chars-per-token
    # heuristics prose ~3.7 / code ~3.2 — never an AC number.
    code_rows = {1, 5}
    code_bytes = sum(r["text_bytes_kept"] for r in rows
                     if r["fp22_row"] in code_rows)
    prose_bytes = total_text - code_bytes
    est_code_tokens = int(code_bytes / 3.2)
    est_prose_tokens = int(prose_bytes / 3.7)
    est_total = est_code_tokens + est_prose_tokens

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "ENG36-CORPUS-ASSEMBLY",
        "ts": ts,
        "issue": "wordingone/ember#130",
        "sources": rows,
        "totals": {
            "docs_kept": total_docs,
            "text_bytes_kept": total_text,
            "bytes_on_disk": total_disk,
            "n_sources": len(rows),
        },
        "bars": {
            "hard_bar_bytes": HARD_BAR_BYTES,
            "hard_bar_pass": True,  # fail-closed above; True iff we got here
            "raw_target_bytes": RAW_TARGET_BYTES,
            "raw_target_note": (f"total text {total_text} vs ~30GB soft "
                                f"target — report-only"),
        },
        "tokens_pending_tokenizer_freeze": True,
        "est_tokens_heuristic": {
            "code": est_code_tokens,
            "prose": est_prose_tokens,
            "total": est_total,
            "code_fraction": round(est_code_tokens / est_total, 4),
        },
        "est_tokens_note": ("HEURISTIC ONLY — chars/token prose ~3.7, code "
                            "~3.2; binding token counts wait for the frozen "
                            "train-on-sample tokenizer (fp-22)"),
        "verification": ("all shards re-hashed sha256 against manifests; "
                         "manifest mirrors re-hashed against per-source "
                         "receipts; docs_kept == shard sums; fail-closed "
                         "BEFORE this write"),
        "sha_convention": ca.SHA_CONVENTION,
        "no_gpu": True,
    }
    out = os.path.join(REPO, "receipts", f"eng36-assembly-{ts}.json")
    checked_write(out, receipt)
    print(json.dumps({"totals": receipt["totals"],
                      "est_tokens_heuristic": receipt["est_tokens_heuristic"]},
                     indent=2))
    print(f"[assembly] receipt: {out}")
    print("ENG36_ASSEMBLY_DONE")


if __name__ == "__main__":
    main()
