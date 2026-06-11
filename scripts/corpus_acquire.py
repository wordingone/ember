"""corpus_acquire.py — eng-36 (#130): v0 corpus acquisition (fp-22 §1 eng half).

License-clean ~7.4B-token mix for the 0.37B bounded local pretrain run.
Per-source AC: URL-pin (HF dataset revision sha) + per-shard sha256 +
license stamp (class + basis) in the manifest + doc-level exact dedup
(before/after counts) + byte/char counts. Token counts are NOT quoted
yet: the v0 tokenizer trains on a stratified sample of THIS corpus and
freezes before step 0 (fp-22 §1, mail 14523) — every manifest carries
tokens_pending_tokenizer_freeze=true plus a bytes/4 HEURISTIC estimate
clearly labeled non-AC.

Sources (registry below): fineweb_edu / wikipedia_en / gutenberg_pg19 /
ledger_mit are fp-22 §1 rows 2-5 exactly. The code majority (row 1):
the-stack-v2 is references-only (SWH blob IDs; bulk content needs a
separate agreement + S3 — no local pull), and the issue's named fallback
(the-stack-march sample) carries NO per-file license metadata (verified
via the HF API 2026-06-11) — both fail the per-file license-stamp AC.
The registry therefore points the code row at codeparrot/github-code-clean
(ungated, per-row `license` field) with a STRICT permissive allow-list
re-verified per file at ingest, fail-closed (missing/unknown license =
reject). That is a source substitution vs the issue text, so the runner
REFUSES to pull it without --ack-code-source — set only after the
gate-holder acks the substitution (practice rule: spec changes are
flagged before running).

Disk: <100GB HARD (fp-22 escalation bar); ~25GB planned across budgets.
Raw data lives OUTSIDE the repo (corpus root below); manifests +
receipts are committed. No GPU anywhere; plain HTTPS streaming on
Windows Python (governed path: local bash, no train-daemon involvement).

Usage:
  python corpus_acquire.py --source list
  python corpus_acquire.py --source fineweb_edu [--byte-budget N] \
      [--out-root DIR] [--shard-bytes N]
  python corpus_acquire.py --source code_github_clean --ack-code-source

Selftest: corpus_acquire_selftest.py (pure logic, no network).
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from receipt_write import checked_write  # noqa: E402

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
if os.name == "nt":
    NC = "B:/M/avir/leo/state/nc-ladder"

OUT_ROOT_DEFAULT = "B:/M/avir/eli/state/ember-eng/corpus-v0"
OUT_ROOT_WSL = "/mnt/b/M/avir/eli/state/ember-eng/corpus-v0"

SHA_CONVENTION = ("sha256 over on-disk raw bytes "
                  "(binary read, no line-ending normalization)")

# Strict permissive allow-list for per-file code licenses. Fail-closed:
# anything not EXACTLY in this list (incl. missing/None/UNKNOWN/copyleft)
# is rejected at ingest. Mirrors the parse_allow discipline (eng #70):
# UNKNOWN is never allowable.
PERMISSIVE_CODE = ("mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause",
                   "isc", "cc0-1.0", "unlicense")

# Byte budgets derive from fp-22 §1 token targets at the documented
# chars-per-token heuristics (prose ~3.7, code ~3.2); total ~25GB, well
# under the ~30GB raw target and the <100GB HARD bar.
SOURCES = {
    "fineweb_edu": {
        "kind": "hf",
        "dataset": "HuggingFaceFW/fineweb-edu",
        "config": "sample-10BT",
        "split": "train",
        "text_field": "text",
        "byte_budget": 7_400_000_000,
        "license_class": "odc-by-1.0",
        "license_basis": ("dataset-level ODC-By 1.0 (FineWeb-Edu card); "
                          "EXTERNAL-CITED per fp-22 §1 row 2"),
        "fp22_row": 2,
    },
    "wikipedia_en": {
        "kind": "hf",
        "dataset": "wikimedia/wikipedia",
        "config": "20231101.en",
        "split": "train",
        "text_field": "text",
        "byte_budget": 3_000_000_000,
        "license_class": "cc-by-sa-4.0",
        "license_basis": ("dataset-level CC-BY-SA (wikimedia/wikipedia "
                          "card); share-alike note carried per fp-22 §1 "
                          "row 3 (weights-not-derivative = HYPOTHESIS "
                          "there; the note rides the manifest either way)"),
        "fp22_row": 3,
    },
    "gutenberg_en": {
        "kind": "hf",
        "dataset": "manu/project_gutenberg",
        "config": None,
        "split": "en",
        "text_field": "text",
        "byte_budget": 1_900_000_000,
        "license_class": "public-domain",
        "license_basis": ("Project Gutenberg books, English split "
                          "(public-domain basis per the PG corpus; "
                          "dataset card manu/project_gutenberg); fp-22 "
                          "§1 row 4. Packaging note: first choice "
                          "deepmind/pg19 is a script-based HF dataset, "
                          "unloadable under datasets 4.x ('Dataset "
                          "scripts are no longer supported') — this "
                          "parquet-native packaging is the eng-36 "
                          "survey's named alternate, same PD basis"),
        "fp22_row": 4,
    },
    "ledger_mit": {
        "kind": "ledger",
        "text_field": "src",
        "byte_budget": 100_000_000,  # tiny by construction (~3K rows)
        "license_class": "arc-dsl-mit",
        "license_basis": ("RECEIPTED — fp-6/eng-70 per-record stamps via "
                          "ledger_license.effective_class; qwen-research "
                          "class EXCLUDED (fp-6 boundary); fp-22 §1 row 5"),
        "fp22_row": 5,
    },
    "code_github_clean": {
        "kind": "hf",
        "dataset": "codeparrot/github-code-clean",
        "config": None,
        "split": "train",
        "text_field": "code",
        "license_field": "license",
        "license_allow": PERMISSIVE_CODE,
        "byte_budget": 13_000_000_000,
        "license_class": "permissive-per-file",
        "license_basis": ("per-file `license` field re-verified at ingest "
                          "against the strict permissive allow-list, "
                          "fail-closed (missing/unknown/copyleft = "
                          "reject); SUBSTITUTION for fp-22 §1 row 1 — "
                          "the-stack-v2 is references-only and the "
                          "issue's march-sample fallback has no per-file "
                          "license metadata (both fail the stamp AC); "
                          "EXTERNAL-CITED upstream detection + our "
                          "per-row stamp"),
        "fp22_row": 1,
        "requires_ack": True,
        # audit-§6 deviation record (gate-holder ack, mail 14530) — copied
        # verbatim into the manifest + receipt by acquire().
        "deviation": ("fp-22 §1 row-1 DEVIATION: source = "
                      "codeparrot/github-code-clean. Basis: the-stack-v2 "
                      "references-only (no local pull) + the-stack "
                      "march-sample lacks per-file license metadata -> "
                      "both fail the per-file license-stamp AC; codeparrot "
                      "satisfies it with a per-row license field "
                      "re-verified fail-closed. Acked by the gate-holder "
                      "(mail 14530) before any pull; --ack-code-source is "
                      "the mechanical gate."),
    },
}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ShardWriter:
    """Rotating zstd-compressed JSONL shard writer.

    Rotation is by UNCOMPRESSED bytes written. close() finalizes the
    current shard; shards() returns [{file, sha256, bytes_uncompressed,
    docs}] with sha256 over the on-disk compressed bytes (SHA_CONVENTION).
    """

    def __init__(self, out_dir, prefix, shard_bytes=1_000_000_000):
        import zstandard
        self._zstd = zstandard
        self.out_dir = out_dir
        self.prefix = prefix
        self.shard_bytes = shard_bytes
        self._idx = -1
        self._fh = None
        self._writer = None
        self._written = 0
        self._docs = 0
        self._done = []
        os.makedirs(out_dir, exist_ok=True)

    def _open_next(self):
        self._close_current()
        self._idx += 1
        path = os.path.join(self.out_dir,
                            f"{self.prefix}-{self._idx:05d}.jsonl.zst")
        self._fh = open(path, "wb")
        cctx = self._zstd.ZstdCompressor(level=6)
        self._writer = cctx.stream_writer(self._fh)
        self._written = 0
        self._docs = 0
        self._path = path

    def _close_current(self):
        if self._writer is not None:
            self._writer.close()
            self._fh.close()
            self._done.append({
                "file": os.path.basename(self._path),
                "sha256": file_sha256(self._path),
                "bytes_uncompressed": self._written,
                "bytes_on_disk": os.path.getsize(self._path),
                "docs": self._docs,
            })
            self._writer = None
            self._fh = None

    def write_doc(self, obj):
        if self._writer is None or self._written >= self.shard_bytes:
            self._open_next()
        b = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        self._writer.write(b)
        self._written += len(b)
        self._docs += 1

    def close(self):
        self._close_current()
        return self._done


def ingest_stream(records, *, text_field, byte_budget, writer,
                  license_field=None, license_allow=None,
                  extra_fields=(), progress_every=200_000):
    """Stream records through license filter + exact doc-dedup into the
    shard writer, stopping at byte_budget (raw text utf-8 bytes kept).

    Fail-closed license discipline: when license_field is set, a record
    whose license value is not EXACTLY in license_allow is rejected —
    missing/None/unknown values reject, never pass. Dedup: sha256 over
    the doc text (utf-8), exact match, source-local.

    Returns the counts dict (all ints) for the manifest/receipt.
    """
    if license_field is not None and not license_allow:
        raise SystemExit("ingest_stream: license_field without an "
                         "allow-list is fail-open; refusing")
    seen = set()
    counts = {
        "docs_in": 0, "docs_kept": 0, "dups_dropped": 0,
        "license_rejected": 0, "empty_skipped": 0,
        "text_bytes_kept": 0, "text_chars_kept": 0,
    }
    for rec in records:
        counts["docs_in"] += 1
        if counts["docs_in"] % progress_every == 0:
            print(f"[ingest] in={counts['docs_in']} "
                  f"kept={counts['docs_kept']} "
                  f"bytes={counts['text_bytes_kept']}", flush=True)
        text = rec.get(text_field)
        if not text or not isinstance(text, str):
            counts["empty_skipped"] += 1
            continue
        if license_field is not None:
            lic = rec.get(license_field)
            if not isinstance(lic, str) or lic not in license_allow:
                counts["license_rejected"] += 1
                continue
        digest = hashlib.sha256(text.encode("utf-8")).digest()[:16]
        if digest in seen:
            counts["dups_dropped"] += 1
            continue
        seen.add(digest)
        out = {"text": text}
        if license_field is not None:
            out["license"] = rec[license_field]
        for k in extra_fields:
            if k in rec:
                out[k] = rec[k]
        writer.write_doc(out)
        counts["docs_kept"] += 1
        counts["text_bytes_kept"] += len(text.encode("utf-8"))
        counts["text_chars_kept"] += len(text)
        if counts["text_bytes_kept"] >= byte_budget:
            print(f"[ingest] byte budget reached: "
                  f"{counts['text_bytes_kept']} >= {byte_budget}",
                  flush=True)
            break
    return counts


def hf_records(spec, revision):
    from datasets import load_dataset
    kwargs = {"split": spec["split"], "streaming": True,
              "revision": revision}
    if spec["config"]:
        return load_dataset(spec["dataset"], spec["config"], **kwargs)
    return load_dataset(spec["dataset"], **kwargs)


def ledger_records():
    """fp-22 §1 row 5: the arc-dsl-mit slice of OUR ledger, classified
    mechanically by ledger_license.effective_class (fp-6 single source).
    qwen-research rows are excluded BY the class check — fail-closed,
    not by enumeration. Ledger is read-only here."""
    from ledger_license import effective_class
    path = f"{NC}/ledger/episodes.jsonl"
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if effective_class(rec) == "arc-dsl-mit":
                yield rec


def acquire(source, out_root, byte_budget=None, shard_bytes=1_000_000_000):
    spec = SOURCES[source]
    budget = byte_budget if byte_budget is not None else spec["byte_budget"]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = os.path.join(out_root, source)

    url_pin = None
    if spec["kind"] == "hf":
        from huggingface_hub import HfApi
        info = HfApi().dataset_info(spec["dataset"])
        revision = info.sha
        url_pin = {
            "dataset": spec["dataset"],
            "config": spec["config"],
            "split": spec["split"],
            "revision_sha": revision,
            "url": (f"https://huggingface.co/datasets/{spec['dataset']}"
                    f"/tree/{revision}"),
        }
        records = hf_records(spec, revision)
    elif spec["kind"] == "ledger":
        ledger_path = f"{NC}/ledger/episodes.jsonl"
        url_pin = {
            "dataset": "local nc-ladder ledger (read-only)",
            "path": ledger_path,
            "ledger_sha256": file_sha256(ledger_path),
        }
        records = ledger_records()
    else:
        raise SystemExit(f"unknown source kind: {spec['kind']}")

    writer = ShardWriter(out_dir, source, shard_bytes=shard_bytes)
    counts = ingest_stream(
        records,
        text_field=spec["text_field"],
        byte_budget=budget,
        writer=writer,
        license_field=spec.get("license_field"),
        license_allow=spec.get("license_allow"),
        extra_fields=("task",) if spec["kind"] == "ledger" else (),
    )
    shards = writer.close()

    manifest = {
        "source": source,
        "ts": ts,
        "fp22_row": spec["fp22_row"],
        "url_pin": url_pin,
        "license_stamp": {
            "class": spec["license_class"],
            "basis": spec["license_basis"],
        },
        **({"deviation": spec["deviation"]} if "deviation" in spec else {}),
        "byte_budget": budget,
        "counts": counts,
        "dedup": {
            "method": "doc-level exact sha256 over utf-8 text, "
                      "source-local",
            "docs_before": counts["docs_in"] - counts["empty_skipped"]
                           - counts["license_rejected"],
            "docs_after": counts["docs_kept"],
        },
        "shards": shards,
        "sha_convention": SHA_CONVENTION,
        "tokens_pending_tokenizer_freeze": True,
        "est_tokens_heuristic": counts["text_bytes_kept"] // 4,
        "est_tokens_note": ("bytes/4 HEURISTIC ONLY, not the AC token "
                            "count — v0-tokenizer counts land after the "
                            "tokenizer trains on the stratified corpus "
                            "sample and freezes (fp-22 §1, mail 14523)"),
        "out_dir_windows": out_dir,
        "out_dir_wsl": out_dir.replace("B:/", "/mnt/b/").replace("\\", "/"),
    }
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    # AC: manifests are COMMITTED (big files are not) — mirror the
    # manifest into the repo, byte-identical to the corpus-dir copy.
    mirror_dir = os.path.join(REPO, "corpus-manifests")
    os.makedirs(mirror_dir, exist_ok=True)
    mirror_path = os.path.join(mirror_dir, f"{source}-manifest-{ts}.json")
    with open(manifest_path, "rb") as f:
        manifest_bytes = f.read()
    with open(mirror_path, "wb") as f:
        f.write(manifest_bytes)

    receipt = {
        "ticket": f"ENG36-CORPUS-{source.upper()}",
        "ts": ts,
        "issue": "wordingone/ember#130",
        "source": source,
        "url_pin": url_pin,
        "license_stamp": manifest["license_stamp"],
        **({"deviation": spec["deviation"]} if "deviation" in spec else {}),
        "counts": counts,
        "dedup": manifest["dedup"],
        "n_shards": len(shards),
        "bytes_on_disk_total": sum(s["bytes_on_disk"] for s in shards),
        "manifest_path": manifest_path,
        "manifest_mirror_in_repo": os.path.relpath(mirror_path, REPO),
        "manifest_sha256": file_sha256(manifest_path),
        "sha_convention": SHA_CONVENTION,
        "tokens_pending_tokenizer_freeze": True,
        "est_tokens_heuristic": manifest["est_tokens_heuristic"],
        "est_tokens_note": manifest["est_tokens_note"],
        "no_gpu": True,
    }
    receipt_path = os.path.join(REPO, "receipts",
                                f"eng36-{source}-{ts}.json")
    checked_write(receipt_path, receipt)
    print(f"[acquire] manifest: {manifest_path}", flush=True)
    print(f"[acquire] receipt:  {receipt_path}", flush=True)
    print(f"ENG36_ACQUIRE_DONE {source} kept={counts['docs_kept']} "
          f"bytes={counts['text_bytes_kept']}", flush=True)
    return receipt


def main():
    ap = argparse.ArgumentParser(description="eng-36 corpus acquisition")
    ap.add_argument("--source", required=True,
                    help="source name from the registry, or 'list'")
    ap.add_argument("--out-root", default=OUT_ROOT_DEFAULT)
    ap.add_argument("--byte-budget", type=int, default=None,
                    help="override the registry budget (Tier-2 slices)")
    ap.add_argument("--shard-bytes", type=int, default=1_000_000_000)
    ap.add_argument("--ack-code-source", action="store_true",
                    help="required for sources marked requires_ack "
                         "(spec-substitution ack from the gate-holder)")
    args = ap.parse_args()

    if args.source == "list":
        for name, spec in SOURCES.items():
            print(f"{name}: kind={spec['kind']} "
                  f"budget={spec['byte_budget']} "
                  f"class={spec['license_class']} "
                  f"ack={spec.get('requires_ack', False)}")
        return

    if args.source not in SOURCES:
        raise SystemExit(f"unknown source: {args.source}")
    spec = SOURCES[args.source]
    if spec.get("requires_ack") and not args.ack_code_source:
        raise SystemExit(
            f"{args.source} is a source SUBSTITUTION vs the issue text "
            "(see module docstring) and needs the gate-holder's ack: "
            "re-run with --ack-code-source once acked. Refusing.")

    acquire(args.source, args.out_root,
            byte_budget=args.byte_budget, shard_bytes=args.shard_bytes)


if __name__ == "__main__":
    main()
