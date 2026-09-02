#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""manifest_sha.py — stable sha256 manifest of the tokenized pretraining corpus
(data/cbase_pretrain/*.bin), shared by every ADM-pinning receipt
(docs/spec/energy-law-theory-v1.md §1) and by scripts/proofs/contamination_verbatim_check.py
(docs/spec/evaluation-v1.md §8a).

vbits.py-style pure-function core + thin CLI:

  compute_manifest(bin_dir) -> {
      "bin_dir": <path used>,
      "files": [{"name", "sha256", "size_bytes", "n_tokens"} ...]  (sorted by name),
      "combined_sha256": sha256 over the sorted "<name>\\t<sha256>\\t<size_bytes>\\n" lines,
      "dtype": "<u2",
  }

Root resolution (fail-closed, never silently emptied): pass --bin-dir to pin an exact
directory, or let resolve_bin_dir() try, in order:
  1. <this repo>/data/cbase_pretrain           (the goalforge tree itself)
  2. <this repo's parent>/ember/data/cbase_pretrain   (a sibling ember checkout,
     READ-ONLY — never written to by this script or by any Ember tooling)
The first candidate that exists AND contains at least one *.bin file wins; which root
was used is always recorded in the receipt (bin_dir_root: "repo" | "ember-readonly" |
"explicit"). Neither candidate existing/non-empty is a fail-closed error, never a
silent empty manifest.

CLI:
  python manifest_sha.py                 # writes receipts/corpus-manifest-<ts>.json,
                                          # prints the combined digest
  python manifest_sha.py --bin-dir PATH  # pin an exact corpus dir (still checked
                                          # fail-closed: must exist, must contain >=1 .bin)
  python manifest_sha.py --print-only    # compute + print, write no receipt
  python manifest_sha.py --selftest      # hermetic; writes no production receipt

Stdlib only (hashlib for sha256). No network. No git commands.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
RECEIPTS_DIR = REPO_ROOT / "receipts"

sys.path.insert(0, str(HERE))
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
receipt_write = _ember_66ee9e91637922dc_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

DTYPE = "<u2"                      # little-endian uint16, PACK_DTYPE (timeshare_pretrain.py)
BYTES_PER_TOKEN = 2
CORPUS_REL = Path("data") / "cbase_pretrain"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fail_closed_bin_dir_guard(explicit):
    """FAIL-CLOSED (2026-07-02, R14/forensics root-cause fix): the conventional
    data/cbase_pretrain fallback certified a 64K-token stub as 'the corpus'
    (see receipts/corpus-materiality-adjudication-20260702T162033Z.json).
    Production runs MUST pass --bin-dir explicitly; the fallback chain below
    is retained for exploratory CLI use only and now aborts unless
    EMBER_ALLOW_BIN_FALLBACK=1 is set, so a stub can never again be certified
    by omission."""
    import os as _os, sys as _sys
    if explicit is None and _os.environ.get("EMBER_ALLOW_BIN_FALLBACK") != "1":
        _sys.exit("FAIL-CLOSED: no --bin-dir given. Pass the corpus dir explicitly "
                  "(C-DATA leg-1 resolution rule, data-engineering-v1 sec1.1); "
                  "set EMBER_ALLOW_BIN_FALLBACK=1 only for exploratory use.")


def resolve_bin_dir(explicit=None, repo_root=REPO_ROOT):
    """Return (path_or_None, root_label, error_or_None). Never raises.

    root_label is "explicit" | "repo" | "ember-readonly" | None (on failure).
    A candidate "exists" only if it is a directory containing >=1 *.bin file —
    an empty or missing dir is not a usable corpus root and falls through."""
    _fail_closed_bin_dir_guard(explicit)
    if explicit is not None:
        p = Path(explicit)
        if not p.is_dir():
            return None, None, f"--bin-dir {p} is not a directory"
        if not any(p.glob("*.bin")):
            return None, None, f"--bin-dir {p} contains no *.bin files"
        return p, "explicit", None

    repo_candidate = repo_root / CORPUS_REL
    if repo_candidate.is_dir() and any(repo_candidate.glob("*.bin")):
        return repo_candidate, "repo", None

    ember_candidate = repo_root.parent / "ember" / CORPUS_REL
    if ember_candidate.is_dir() and any(ember_candidate.glob("*.bin")):
        return ember_candidate, "ember-readonly", None

    return None, None, (
        f"no usable corpus bin dir: {repo_candidate} "
        f"{'exists but has no *.bin files' if repo_candidate.is_dir() else 'does not exist'}; "
        f"{ember_candidate} "
        f"{'exists but has no *.bin files' if ember_candidate.is_dir() else 'does not exist'}"
    )


def compute_manifest(bin_dir):
    """Pure function: bin_dir (Path, must exist and contain >=1 *.bin) -> manifest dict.
    Raises FileNotFoundError if bin_dir has no *.bin files (fail-closed; callers should
    prefer resolve_bin_dir()'s pre-check, this is the belt-and-suspenders floor)."""
    bin_dir = Path(bin_dir)
    bin_paths = sorted(bin_dir.glob("*.bin"), key=lambda p: p.name)
    if not bin_paths:
        raise FileNotFoundError(f"compute_manifest: no *.bin files under {bin_dir}")

    files = []
    lines = []
    for p in bin_paths:
        size_bytes = p.stat().st_size
        sha = _sha256_file(p)
        odd = size_bytes % BYTES_PER_TOKEN
        n_tokens = size_bytes // BYTES_PER_TOKEN
        files.append({
            "name": p.name,
            "sha256": sha,
            "size_bytes": size_bytes,
            "n_tokens": n_tokens,
            "odd_trailing_bytes": odd,   # 0 expected for a clean uint16 stream
        })
        lines.append(f"{p.name}\t{sha}\t{size_bytes}\n")

    combined = hashlib.sha256("".join(sorted(lines)).encode("utf-8")).hexdigest()
    return {
        "bin_dir": str(bin_dir),
        "dtype": DTYPE,
        "files": files,
        "n_files": len(files),
        "total_size_bytes": sum(f["size_bytes"] for f in files),
        "total_tokens": sum(f["n_tokens"] for f in files),
        "combined_sha256": combined,
    }


def _utc_ts():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_receipt(manifest, bin_dir_root, generator_path):
    ts = _utc_ts()
    generator_sha256 = hashlib.sha256(generator_path.read_bytes()).hexdigest()
    return {
        "ticket": "CORPUS-MANIFEST-SHA",
        "ts": ts,
        "kind": "manifest",
        "spec_ref": "docs/spec/energy-law-theory-v1.md sec1 (ADM-pinning corpus_manifest_sha); "
                    "docs/spec/evaluation-v1.md sec8a (contamination-check corpus manifest)",
        "bin_dir": manifest["bin_dir"],
        "bin_dir_root": bin_dir_root,
        "dtype": manifest["dtype"],
        "files": manifest["files"],
        "n_files": manifest["n_files"],
        "total_size_bytes": manifest["total_size_bytes"],
        "total_tokens": manifest["total_tokens"],
        "combined_sha256": manifest["combined_sha256"],
        "generator": {"path": "src/ember/governance/scripts/manifest_sha.py", "sha256": generator_sha256},
        "sha_convention": SHA_CONVENTION,
    }


def run(bin_dir_arg, print_only):
    bin_dir, root_label, err = resolve_bin_dir(explicit=bin_dir_arg)
    if err is not None:
        print(f"manifest_sha: UNEVALUABLE — {err}")
        return 1

    try:
        manifest = compute_manifest(bin_dir)
    except FileNotFoundError as e:
        print(f"manifest_sha: UNEVALUABLE — {e}")
        return 1

    receipt = build_receipt(manifest, root_label, Path(__file__).resolve())
    print(f"manifest_sha: {manifest['n_files']} file(s), "
          f"{manifest['total_tokens']:,} tokens, root={root_label} ({bin_dir})")
    for f in manifest["files"]:
        print(f"  {f['name']}: {f['n_tokens']:,} tokens, sha256={f['sha256'][:16]}...")
    print(f"combined_sha256={manifest['combined_sha256']}")

    if print_only:
        return 0

    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RECEIPTS_DIR / f"corpus-manifest-{receipt['ts']}.json"
    receipt_write.checked_write(str(out_path), receipt)
    print(f"receipt: {out_path.relative_to(REPO_ROOT).as_posix()}")
    return 0


# ---------------------------------------------------------------------------
# Selftest — hermetic; writes no production receipt, touches no real corpus.
# ---------------------------------------------------------------------------

def _selftest():
    import struct
    import tempfile

    failures = []

    def check(name, cond):
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {name}")
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # --- resolve_bin_dir: nothing anywhere -> fail-closed with a reason ---
        p, label, err = resolve_bin_dir(explicit=None, repo_root=root)
        check("resolve_bin_dir: no repo/ or ember-sibling corpus -> (None, None, reason)",
              p is None and label is None and err is not None)

        # --- resolve_bin_dir: repo-tree corpus present -> used, labeled "repo" ---
        repo_bins = root / CORPUS_REL
        repo_bins.mkdir(parents=True)
        (repo_bins / "a-00000.bin").write_bytes(
            b"".join(struct.pack("<H", x) for x in [10, 11, 12]))
        p2, label2, err2 = resolve_bin_dir(explicit=None, repo_root=root)
        check("resolve_bin_dir: prefers the repo tree when it has >=1 .bin",
              p2 == repo_bins and label2 == "repo" and err2 is None)

        # --- resolve_bin_dir: repo tree EMPTY dir (no .bin) falls through to
        #     the ember-sibling root, not silently accepted as-is ---
        empty_case_root = root / "case2"
        (empty_case_root / CORPUS_REL).mkdir(parents=True)   # exists but empty
        ember_sibling = empty_case_root.parent / "ember" / CORPUS_REL
        ember_sibling.mkdir(parents=True)
        (ember_sibling / "b-00000.bin").write_bytes(
            b"".join(struct.pack("<H", x) for x in [20, 21]))
        p3, label3, err3 = resolve_bin_dir(explicit=None, repo_root=empty_case_root)
        check("resolve_bin_dir: empty repo-tree corpus dir falls through to "
              "ember-sibling read-only root",
              p3 == ember_sibling and label3 == "ember-readonly" and err3 is None)

        # --- resolve_bin_dir: explicit --bin-dir wins and is validated ---
        p4, label4, err4 = resolve_bin_dir(explicit=str(repo_bins))
        check("resolve_bin_dir: explicit dir with .bin files resolves as 'explicit'",
              p4 == repo_bins and label4 == "explicit" and err4 is None)
        p5, label5, err5 = resolve_bin_dir(explicit=str(root / "does-not-exist"))
        check("resolve_bin_dir: explicit dir that doesn't exist fails closed",
              p5 is None and err5 is not None)

        # --- compute_manifest: per-file sha/size/n_tokens + combined digest,
        #     and the combined digest is a pure function of (name, sha, size) sorted ---
        m = compute_manifest(repo_bins)
        check("compute_manifest: one file, 3 tokens, 6 bytes",
              m["n_files"] == 1 and m["total_tokens"] == 3 and m["total_size_bytes"] == 6)
        check("compute_manifest: files[0].sha256 matches direct sha256 of the bytes",
              m["files"][0]["sha256"] == hashlib.sha256(
                  (repo_bins / "a-00000.bin").read_bytes()).hexdigest())

        # add a second file -> combined_sha256 changes, and re-running is deterministic
        (repo_bins / "z-00001.bin").write_bytes(
            b"".join(struct.pack("<H", x) for x in [30]))
        m2 = compute_manifest(repo_bins)
        m2b = compute_manifest(repo_bins)
        check("compute_manifest: adding a file changes combined_sha256",
              m2["combined_sha256"] != m["combined_sha256"])
        check("compute_manifest: deterministic on repeated calls (same inputs)",
              m2["combined_sha256"] == m2b["combined_sha256"])
        check("compute_manifest: files sorted by name regardless of glob order",
              [f["name"] for f in m2["files"]] == ["a-00000.bin", "z-00001.bin"])

        # --- compute_manifest: odd-length file flagged but not crashed on ---
        (repo_bins / "odd-00002.bin").write_bytes(b"\x01\x02\x03")   # 3 bytes, not /2
        m3 = compute_manifest(repo_bins)
        odd_entry = next(f for f in m3["files"] if f["name"] == "odd-00002.bin")
        check("compute_manifest: odd-byte-length file reports odd_trailing_bytes=1, "
              "floor-divided n_tokens, never raises",
              odd_entry["odd_trailing_bytes"] == 1 and odd_entry["n_tokens"] == 1)

        # --- compute_manifest: empty dir raises (fail-closed floor beneath resolve) ---
        empty_dir = root / "truly-empty"
        empty_dir.mkdir()
        raised = False
        try:
            compute_manifest(empty_dir)
        except FileNotFoundError:
            raised = True
        check("compute_manifest: empty dir raises FileNotFoundError (fail-closed floor)",
              raised)

        # --- build_receipt + checked_write: schema-floor compliant, run() end-to-end ---
        receipt = build_receipt(m2, "repo", Path(__file__).resolve())
        check("build_receipt: carries ticket/ts/sha_convention (schema floor)",
              receipt.get("ticket") == "CORPUS-MANIFEST-SHA" and receipt.get("ts")
              and receipt.get("sha_convention"))
        # issue2015 exact-local-import:src/ember/governance/scripts/receipt_check.py
        import importlib.util as _ember_2ad73f5df12b45ee_importlib
        import sys as _ember_2ad73f5df12b45ee_sys
        from pathlib import Path as _ember_2ad73f5df12b45ee_Path
        _ember_2ad73f5df12b45ee_path = _ember_2ad73f5df12b45ee_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_check.py')
        if not _ember_2ad73f5df12b45ee_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_check.py')
        _ember_2ad73f5df12b45ee_aliases = ('_ember_issue2015_2ad73f5df12b45ee', 'receipt_check', 'scripts.receipt_check')
        _ember_2ad73f5df12b45ee_existing = []
        for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
            _ember_2ad73f5df12b45ee_candidate = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
            if _ember_2ad73f5df12b45ee_candidate is not None and all(_ember_2ad73f5df12b45ee_candidate is not item for item in _ember_2ad73f5df12b45ee_existing):
                _ember_2ad73f5df12b45ee_existing.append(_ember_2ad73f5df12b45ee_candidate)
        if len(_ember_2ad73f5df12b45ee_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_check.py')
        if _ember_2ad73f5df12b45ee_existing:
            _ember_2ad73f5df12b45ee_module = _ember_2ad73f5df12b45ee_existing[0]
            _ember_2ad73f5df12b45ee_observed = getattr(_ember_2ad73f5df12b45ee_module, '__file__', None)
            if _ember_2ad73f5df12b45ee_observed is None or _ember_2ad73f5df12b45ee_Path(_ember_2ad73f5df12b45ee_observed).resolve() != _ember_2ad73f5df12b45ee_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_check.py')
        else:
            _ember_2ad73f5df12b45ee_spec = _ember_2ad73f5df12b45ee_importlib.spec_from_file_location('_ember_issue2015_2ad73f5df12b45ee', _ember_2ad73f5df12b45ee_path)
            if _ember_2ad73f5df12b45ee_spec is None or _ember_2ad73f5df12b45ee_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_check.py')
            _ember_2ad73f5df12b45ee_module = _ember_2ad73f5df12b45ee_importlib.module_from_spec(_ember_2ad73f5df12b45ee_spec)
            for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
                _ember_2ad73f5df12b45ee_prior = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
                if _ember_2ad73f5df12b45ee_prior is not None and _ember_2ad73f5df12b45ee_prior is not _ember_2ad73f5df12b45ee_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_check.py')
                _ember_2ad73f5df12b45ee_sys.modules[_ember_2ad73f5df12b45ee_alias] = _ember_2ad73f5df12b45ee_module
            try:
                _ember_2ad73f5df12b45ee_spec.loader.exec_module(_ember_2ad73f5df12b45ee_module)
            except BaseException:
                for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
                    if _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias) is _ember_2ad73f5df12b45ee_module:
                        _ember_2ad73f5df12b45ee_sys.modules.pop(_ember_2ad73f5df12b45ee_alias, None)
                raise
        for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
            _ember_2ad73f5df12b45ee_prior = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
            if _ember_2ad73f5df12b45ee_prior is not None and _ember_2ad73f5df12b45ee_prior is not _ember_2ad73f5df12b45ee_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_check.py')
            _ember_2ad73f5df12b45ee_sys.modules[_ember_2ad73f5df12b45ee_alias] = _ember_2ad73f5df12b45ee_module
        receipt_check = _ember_2ad73f5df12b45ee_module
        # issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_check.py
        check("build_receipt: passes receipt_check.validate_receipt with zero findings",
              receipt_check.validate_receipt(receipt) == [])

    print(f"\nselftest: {'ALL PASS' if not failures else f'{len(failures)} FAILED'}")
    for f in failures:
        print(f"  FAILED: {f}")
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(
        description="manifest_sha.py — stable sha256 manifest of data/cbase_pretrain/*.bin")
    ap.add_argument("--bin-dir", default=None,
                     help="pin an exact corpus bin directory (must exist, must contain "
                          ">=1 *.bin); default resolves repo-tree then ember-sibling read-only")
    ap.add_argument("--print-only", action="store_true",
                     help="compute and print the manifest; write no receipt")
    ap.add_argument("--selftest", action="store_true",
                     help="hermetic selftest; writes no production receipt")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(_selftest())
    sys.exit(run(args.bin_dir, args.print_only))


if __name__ == "__main__":
    main()
