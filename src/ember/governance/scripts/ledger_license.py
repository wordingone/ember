# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ledger_license.py — license-class stamping + license-filtered views (eng #70).

fp-6 (#57) found the ledger mixes license classes: 1,909 arc-dsl MIT
human-expert episodes + 956 episodes sampled by the 3B core, which sits under
the Qwen RESEARCH LICENSE (non-commercial-only; its S4.b reaches outputs used
to train distributed models). NC2-own corpus assembly must exclude encumbered
episodes MECHANICALLY. Three pieces:

  stamp(rec)         license_class/license_basis on records AT INGEST
                     (w2_ingest + t2_round call this; the class mapping is
                     imported from fp6_provenance.classify — single source
                     of truth, never duplicated here).
  backfill_view      sidecar VIEWs (receipts/ledger/views/license-class.jsonl +
                     license-class-control.jsonl, eng #80) mapping every
                     EXISTING record key -> class. Ledger AND control pool
                     stay append-only: backfill writes the views, never
                     rewrites the source files (the receipt carries sha256
                     before/after for both as the byte-unchanged proof).
  filter_records     allow-list filter for dataset builds. UNKNOWN is
                     FAIL-CLOSED: parse_allow refuses it in an allow-list,
                     so filtered builds always drop UNKNOWN records.

`python ledger_license.py --selftest` (no ledger needed).
`python ledger_license.py --backfill --ledger ... --control-pool ...
    --view-out ... --receipt-dir ...` -> view + receipt.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

# Single source of truth (#57). fp6_provenance.py lands via PR #72 — this
# module MUST merge after it (hard import, no fallback, by design).
# issue2015 exact-local-import:src/ember/governance/scripts/fp6_provenance.py
import importlib.util as _ember_a9bffa102e04b80d_importlib
import sys as _ember_a9bffa102e04b80d_sys
from pathlib import Path as _ember_a9bffa102e04b80d_Path
_ember_a9bffa102e04b80d_path = _ember_a9bffa102e04b80d_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'fp6_provenance.py')
if not _ember_a9bffa102e04b80d_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/fp6_provenance.py')
_ember_a9bffa102e04b80d_aliases = ('_ember_issue2015_a9bffa102e04b80d', 'fp6_provenance', 'scripts.fp6_provenance')
_ember_a9bffa102e04b80d_existing = []
for _ember_a9bffa102e04b80d_alias in _ember_a9bffa102e04b80d_aliases:
    _ember_a9bffa102e04b80d_candidate = _ember_a9bffa102e04b80d_sys.modules.get(_ember_a9bffa102e04b80d_alias)
    if _ember_a9bffa102e04b80d_candidate is not None and all(_ember_a9bffa102e04b80d_candidate is not item for item in _ember_a9bffa102e04b80d_existing):
        _ember_a9bffa102e04b80d_existing.append(_ember_a9bffa102e04b80d_candidate)
if len(_ember_a9bffa102e04b80d_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/fp6_provenance.py')
if _ember_a9bffa102e04b80d_existing:
    _ember_a9bffa102e04b80d_module = _ember_a9bffa102e04b80d_existing[0]
    _ember_a9bffa102e04b80d_observed = getattr(_ember_a9bffa102e04b80d_module, '__file__', None)
    if _ember_a9bffa102e04b80d_observed is None or _ember_a9bffa102e04b80d_Path(_ember_a9bffa102e04b80d_observed).resolve() != _ember_a9bffa102e04b80d_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/fp6_provenance.py')
else:
    _ember_a9bffa102e04b80d_spec = _ember_a9bffa102e04b80d_importlib.spec_from_file_location('_ember_issue2015_a9bffa102e04b80d', _ember_a9bffa102e04b80d_path)
    if _ember_a9bffa102e04b80d_spec is None or _ember_a9bffa102e04b80d_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/fp6_provenance.py')
    _ember_a9bffa102e04b80d_module = _ember_a9bffa102e04b80d_importlib.module_from_spec(_ember_a9bffa102e04b80d_spec)
    for _ember_a9bffa102e04b80d_alias in _ember_a9bffa102e04b80d_aliases:
        _ember_a9bffa102e04b80d_prior = _ember_a9bffa102e04b80d_sys.modules.get(_ember_a9bffa102e04b80d_alias)
        if _ember_a9bffa102e04b80d_prior is not None and _ember_a9bffa102e04b80d_prior is not _ember_a9bffa102e04b80d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp6_provenance.py')
        _ember_a9bffa102e04b80d_sys.modules[_ember_a9bffa102e04b80d_alias] = _ember_a9bffa102e04b80d_module
    try:
        _ember_a9bffa102e04b80d_spec.loader.exec_module(_ember_a9bffa102e04b80d_module)
    except BaseException:
        for _ember_a9bffa102e04b80d_alias in _ember_a9bffa102e04b80d_aliases:
            if _ember_a9bffa102e04b80d_sys.modules.get(_ember_a9bffa102e04b80d_alias) is _ember_a9bffa102e04b80d_module:
                _ember_a9bffa102e04b80d_sys.modules.pop(_ember_a9bffa102e04b80d_alias, None)
        raise
for _ember_a9bffa102e04b80d_alias in _ember_a9bffa102e04b80d_aliases:
    _ember_a9bffa102e04b80d_prior = _ember_a9bffa102e04b80d_sys.modules.get(_ember_a9bffa102e04b80d_alias)
    if _ember_a9bffa102e04b80d_prior is not None and _ember_a9bffa102e04b80d_prior is not _ember_a9bffa102e04b80d_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp6_provenance.py')
    _ember_a9bffa102e04b80d_sys.modules[_ember_a9bffa102e04b80d_alias] = _ember_a9bffa102e04b80d_module
LICENSE_BY_SAMPLER = getattr(_ember_a9bffa102e04b80d_module, 'LICENSE_BY_SAMPLER')
classify = getattr(_ember_a9bffa102e04b80d_module, 'classify')
# issue2015 exact-local-import-end:src/ember/governance/scripts/fp6_provenance.py
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
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
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py

NC = "<local-path>"

# Repo-standard sha convention (eng #103/#107). The receipt carries
# receipts/ledger/control sha256 before/after as the byte-unchanged proof, so it MUST
# declare this — receipt_check fail-closes on a sha256 field without it.
SHA_CONVENTION = ("sha256 over on-disk raw bytes "
                  "(binary read, no line-ending normalization)")

# Every class classify() can emit except UNKNOWN, which is fail-closed and
# never allowable. arc-dsl-mit comes from classify's origin branch, not the
# sampler map.
KNOWN_CLASSES = sorted(set(LICENSE_BY_SAMPLER.values()) | {"arc-dsl-mit"})


def stamp(rec):
    """Stamp license_class/license_basis on a record at ingest. Idempotent:
    an existing stamp is preserved (precedence: explicit stamp > classify —
    a manual stamp may be MORE specific than classify can derive, e.g. a
    researched class on a record classify can only call UNKNOWN). But a
    pre-existing stamp that CONTRADICTS a non-UNKNOWN classification is
    corrupted provenance, and that fails loud, not silent."""
    lic, basis = classify(rec)
    pre = rec.get("license_class")
    if pre:
        if lic != "UNKNOWN" and pre != lic:
            raise SystemExit(
                f"ledger_license: stamp conflict on {rec.get('key', '?')}: "
                f"record carries license_class={pre!r} but provenance "
                f"classifies {lic!r} ({basis}) — refusing to ingest")
        return rec
    rec["license_class"] = lic
    rec["license_basis"] = basis
    return rec


def effective_class(rec):
    """Stamped field wins; unstamped (pre-#70) records classify on the fly.

    AC2: a STAMPED UNKNOWN whose license_basis starts with 'sampler-unmapped:'
    is a recorded classification FAILURE, not a license fact — re-classify on
    read using the current classify() (which may now resolve the sampler via
    the adapter-mapping AC1 rule).  Stamped non-UNKNOWN classes still win.
    """
    cls = rec.get("license_class")
    if cls and cls != "UNKNOWN":
        return cls
    if cls == "UNKNOWN":
        basis = rec.get("license_basis", "")
        if basis.startswith("sampler-unmapped:"):
            # Recorded classification failure — re-classify now.
            return classify(rec)[0]
        # UNKNOWN for other reasons (no-provenance, etc.) — no re-classify.
        return "UNKNOWN"
    # Unstamped — classify on the fly.
    return classify(rec)[0]


def parse_allow(spec):
    """--license-allow 'a,b' -> set. Fail-closed: UNKNOWN is not allowable,
    and an unrecognized class name is an error rather than a silent
    everything-excluded filter (typo protection)."""
    classes = sorted({c.strip() for c in spec.split(",") if c.strip()})
    if not classes:
        raise SystemExit("ledger_license: empty --license-allow")
    if "UNKNOWN" in classes:
        raise SystemExit("ledger_license: UNKNOWN cannot be allow-listed "
                         "(fail-closed); fix the record's provenance instead")
    bad = [c for c in classes if c not in KNOWN_CLASSES]
    if bad:
        raise SystemExit(f"ledger_license: unknown license class(es) {bad}; "
                         f"known: {KNOWN_CLASSES}")
    return set(classes)


def filter_records(recs, allow):
    """Keep records whose effective class is allow-listed. UNKNOWN can never
    pass: parse_allow refuses it, so it is never a member of `allow`."""
    return [r for r in recs if effective_class(r) in allow]


def census(recs):
    out = {}
    for r in recs:
        lic = effective_class(r)
        out[lic] = out.get(lic, 0) + 1
    return dict(sorted(out.items()))


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backfill_view(ledger_path, view_path):
    """Sidecar view: one row per ledger record, key -> class/basis. The
    ledger is opened read-only and never rewritten. Returns (records,
    conflicts): a stamped record whose stamp contradicts a non-UNKNOWN
    classification is written with a CONFLICT basis and counted — the view
    is the audit surface, so corruption is made visible, not normalized."""
    recs = load_jsonl(ledger_path)
    d = os.path.dirname(view_path)
    if d:
        os.makedirs(d, exist_ok=True)
    conflicts = 0
    with open(view_path, "w", encoding="utf-8", newline="\n") as f:
        for r in recs:
            cls, cls_basis = classify(r)
            if r.get("license_class"):
                lic = r["license_class"]
                basis = r.get("license_basis", "stamped")
                if cls != "UNKNOWN" and lic != cls:
                    basis = f"CONFLICT(stamped={lic},classify={cls})"
                    conflicts += 1
            else:
                lic, basis = cls, cls_basis
            f.write(json.dumps({"key": r["key"], "task": r["task"],
                                "license_class": lic,
                                "license_basis": basis}) + "\n")
    return recs, conflicts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", required=True,
                    help="write the sidecar view + receipt (the only mode)")
    ap.add_argument("--ledger", default=f"{NC}/receipts/ledger/episodes.jsonl")
    ap.add_argument("--control-pool", default=f"{NC}/receipts/ledger/control_pool.jsonl")
    ap.add_argument("--view-out",
                    default=f"{NC}/receipts/ledger/views/license-class.jsonl")
    ap.add_argument("--control-view-out",  # eng #80
                    default=f"{NC}/receipts/ledger/views/license-class-control.jsonl")
    ap.add_argument("--receipt-dir", default=f"{NC}/receipts")
    ap.add_argument("--license-allow", default="arc-dsl-mit,apache-2.0",
                    help="allow-list the receipt's before/after demo uses")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore them

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sha_before = sha256_file(args.ledger)
    ctl_sha_before = sha256_file(args.control_pool)
    recs, conflicts = backfill_view(args.ledger, args.view_out)
    ctl, ctl_conflicts = backfill_view(args.control_pool,
                                       args.control_view_out)  # eng #80
    sha_after = sha256_file(args.ledger)
    ctl_sha_after = sha256_file(args.control_pool)

    allow = parse_allow(args.license_allow)
    kept = filter_records(recs, allow)
    dropped = [r for r in recs if effective_class(r) not in allow]
    ctl_kept = filter_records(ctl, allow)

    receipt = {
        "ticket": "ENG20-LICENSE-VIEW", "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "mapping_source": "fp6_provenance.classify (#57, single source)",
        "known_classes": KNOWN_CLASSES,
        "ledger": args.ledger, "view": args.view_out, "view_rows": len(recs),
        "ledger_sha256_before": sha_before,
        "ledger_sha256_after": sha_after,
        "ledger_byte_unchanged": sha_before == sha_after,
        "stamp_conflicts": conflicts,
        "control_pool": args.control_pool,
        "control_view": args.control_view_out,
        "control_view_rows": len(ctl),
        "control_sha256_before": ctl_sha_before,
        "control_sha256_after": ctl_sha_after,
        "control_byte_unchanged": ctl_sha_before == ctl_sha_after,
        "control_stamp_conflicts": ctl_conflicts,
        "episodes_by_class": census(recs),
        "control_pool_by_class": census(ctl),
        "filter_demo": {
            "allow": sorted(allow),
            "episodes": {"before": len(recs), "after": len(kept),
                         "excluded_by_class": census(dropped)},
            "control_pool": {"before": len(ctl), "after": len(ctl_kept)},
        },
    }
    if not (receipt["ledger_byte_unchanged"]
            and receipt["control_byte_unchanged"]):
        raise SystemExit("ledger_license: receipts/ledger/control sha256 CHANGED "
                         "during backfill — append-only invariant violated, "
                         "abort")
    os.makedirs(args.receipt_dir, exist_ok=True)
    out = f"{args.receipt_dir}/eng20-license-view-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"ENG20_LICENSE_VIEW_DONE {out}")


def _selftest():
    # --- precedence: classify puts sampler-stamp above origin; an explicit
    # stamp beats re-classification; unstamped falls back to classify ---
    r = {"sampler": "Qwen/Qwen2.5-Coder-3B-Instruct", "origin": "seed-dsl-orig"}
    assert classify(r)[0] == "qwen-research"  # sampler beats origin
    stamp(r)
    assert r["license_class"] == "qwen-research"
    assert r["license_basis"].startswith("sampler-stamp")
    stamp(r)  # idempotent: same-class re-stamp is a no-op
    assert r["license_class"] == "qwen-research"
    # manual enrichment survives: explicit stamp on a record classify can
    # only call UNKNOWN is the legitimate use of stamp-wins precedence
    pre = {"license_class": "apache-2.0", "origin": "manually-researched"}
    stamp(pre)
    assert pre["license_class"] == "apache-2.0"
    assert effective_class(pre) == "apache-2.0"
    # CONTRADICTORY stamp fails loud: stamped MIT but provenance says 3B
    try:
        stamp({"key": "k", "license_class": "arc-dsl-mit",
               "sampler": "Qwen/Qwen2.5-Coder-3B-Instruct"})
        raise AssertionError("conflicting stamp should have exited")
    except SystemExit:
        pass
    assert effective_class({"origin": "seed-dsl-orig"}) == "arc-dsl-mit"
    assert effective_class({}) == "UNKNOWN"

    # AC2 selftest — both branches pinned:
    # Branch A: STAMPED UNKNOWN with sampler-unmapped: basis -> re-classify
    # Use WSL-style path (as stored by w2_ingest on Linux/WSL)
    import re as _re_test2
    # issue2015 exact-local-import:src/ember/governance/scripts/fp6_provenance.py
    import importlib.util as _ember_a9bffa102e04b80d_importlib
    import sys as _ember_a9bffa102e04b80d_sys
    from pathlib import Path as _ember_a9bffa102e04b80d_Path
    _ember_a9bffa102e04b80d_path = _ember_a9bffa102e04b80d_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'fp6_provenance.py')
    if not _ember_a9bffa102e04b80d_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/fp6_provenance.py')
    _ember_a9bffa102e04b80d_aliases = ('_ember_issue2015_a9bffa102e04b80d', 'fp6_provenance', 'scripts.fp6_provenance')
    _ember_a9bffa102e04b80d_existing = []
    for _ember_a9bffa102e04b80d_alias in _ember_a9bffa102e04b80d_aliases:
        _ember_a9bffa102e04b80d_candidate = _ember_a9bffa102e04b80d_sys.modules.get(_ember_a9bffa102e04b80d_alias)
        if _ember_a9bffa102e04b80d_candidate is not None and all(_ember_a9bffa102e04b80d_candidate is not item for item in _ember_a9bffa102e04b80d_existing):
            _ember_a9bffa102e04b80d_existing.append(_ember_a9bffa102e04b80d_candidate)
    if len(_ember_a9bffa102e04b80d_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/fp6_provenance.py')
    if _ember_a9bffa102e04b80d_existing:
        _ember_a9bffa102e04b80d_module = _ember_a9bffa102e04b80d_existing[0]
        _ember_a9bffa102e04b80d_observed = getattr(_ember_a9bffa102e04b80d_module, '__file__', None)
        if _ember_a9bffa102e04b80d_observed is None or _ember_a9bffa102e04b80d_Path(_ember_a9bffa102e04b80d_observed).resolve() != _ember_a9bffa102e04b80d_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/fp6_provenance.py')
    else:
        _ember_a9bffa102e04b80d_spec = _ember_a9bffa102e04b80d_importlib.spec_from_file_location('_ember_issue2015_a9bffa102e04b80d', _ember_a9bffa102e04b80d_path)
        if _ember_a9bffa102e04b80d_spec is None or _ember_a9bffa102e04b80d_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/fp6_provenance.py')
        _ember_a9bffa102e04b80d_module = _ember_a9bffa102e04b80d_importlib.module_from_spec(_ember_a9bffa102e04b80d_spec)
        for _ember_a9bffa102e04b80d_alias in _ember_a9bffa102e04b80d_aliases:
            _ember_a9bffa102e04b80d_prior = _ember_a9bffa102e04b80d_sys.modules.get(_ember_a9bffa102e04b80d_alias)
            if _ember_a9bffa102e04b80d_prior is not None and _ember_a9bffa102e04b80d_prior is not _ember_a9bffa102e04b80d_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp6_provenance.py')
            _ember_a9bffa102e04b80d_sys.modules[_ember_a9bffa102e04b80d_alias] = _ember_a9bffa102e04b80d_module
        try:
            _ember_a9bffa102e04b80d_spec.loader.exec_module(_ember_a9bffa102e04b80d_module)
        except BaseException:
            for _ember_a9bffa102e04b80d_alias in _ember_a9bffa102e04b80d_aliases:
                if _ember_a9bffa102e04b80d_sys.modules.get(_ember_a9bffa102e04b80d_alias) is _ember_a9bffa102e04b80d_module:
                    _ember_a9bffa102e04b80d_sys.modules.pop(_ember_a9bffa102e04b80d_alias, None)
            raise
    for _ember_a9bffa102e04b80d_alias in _ember_a9bffa102e04b80d_aliases:
        _ember_a9bffa102e04b80d_prior = _ember_a9bffa102e04b80d_sys.modules.get(_ember_a9bffa102e04b80d_alias)
        if _ember_a9bffa102e04b80d_prior is not None and _ember_a9bffa102e04b80d_prior is not _ember_a9bffa102e04b80d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp6_provenance.py')
        _ember_a9bffa102e04b80d_sys.modules[_ember_a9bffa102e04b80d_alias] = _ember_a9bffa102e04b80d_module
    ADAPTERS_DIR = getattr(_ember_a9bffa102e04b80d_module, 'ADAPTERS_DIR')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/fp6_provenance.py
    wsl_adapters = _re_test2.sub(
        r"^([a-zA-Z]):/",
        lambda m: f"/mnt/{m.group(1).lower()}/",
        ADAPTERS_DIR.replace("\\", "/")
    )
    adapter_wsl = wsl_adapters + "/r1w-q3-mtp"
    rec_stamped_unknown = {
        "sampler": f"Qwen/Qwen2.5-Coder-3B-Instruct+{adapter_wsl}",
        "license_class": "UNKNOWN",
        "license_basis": "sampler-unmapped:Qwen/Qwen2.5-Coder-3B-Instruct+r1w-q3-mtp",
    }
    # After AC1 is live, classify() resolves this to qwen-research;
    # effective_class must follow suit (AC2 re-classify on read).
    assert effective_class(rec_stamped_unknown) == "qwen-research", (
        f"AC2 branch-A: expected qwen-research, got {effective_class(rec_stamped_unknown)!r}"
    )
    # Branch B: STAMPED non-UNKNOWN (e.g. arc-dsl-mit) — must still win.
    rec_stamped_known = {
        "sampler": "Qwen/Qwen2.5-Coder-3B-Instruct",  # would classify qwen-research
        "license_class": "arc-dsl-mit",
        "license_basis": "stamped-manually",
    }
    assert effective_class(rec_stamped_known) == "arc-dsl-mit", (
        f"AC2 branch-B: stamped non-UNKNOWN must win; got {effective_class(rec_stamped_known)!r}"
    )

    # --- fail-closed: UNKNOWN never allow-listable; typos error out ---
    for bad in ("UNKNOWN", "arc-dsl-mit,UNKNOWN", "mit", "", " , "):
        try:
            parse_allow(bad)
            raise AssertionError(f"parse_allow({bad!r}) should have exited")
        except SystemExit:
            pass

    # --- filter math on constructed rows ---
    rows = [{"sampler": "Qwen/Qwen2.5-Coder-3B-Instruct"},    # qwen-research
            {"sampler": "Qwen/Qwen2.5-Coder-1.5B-Instruct"},  # apache-2.0
            {"origin": "seed-dsl-orig"},                      # arc-dsl-mit
            {"origin": "seed-verifier-rearc-v2"},             # arc-dsl-mit
            {"origin": "seed-control-wrongtask"},  # arc-dsl-mit (eng #80)
            {}]                                               # UNKNOWN
    assert census(rows) == {"UNKNOWN": 1, "apache-2.0": 1,
                            "arc-dsl-mit": 3, "qwen-research": 1}
    kept = filter_records(rows, parse_allow("arc-dsl-mit,apache-2.0"))
    assert len(kept) == 4
    assert all(effective_class(k) != "UNKNOWN" for k in kept)
    assert len(filter_records(rows, parse_allow("qwen-research"))) == 1
    assert len(filter_records(rows, parse_allow("apache-2.0"))) == 1

    # --- backfill: view rows 1:1 with ledger, source bytes untouched,
    # contradictory pre-existing stamps surfaced as CONFLICT rows ---
    import tempfile
    rows2 = [dict(r, key=f"k{i}", task=f"t{i}") for i, r in enumerate(rows)]
    rows2.append({"key": "k6", "task": "t6", "license_class": "arc-dsl-mit",
                  "sampler": "Qwen/Qwen2.5-Coder-3B-Instruct"})
    fd, p = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows2:
            f.write(json.dumps(r) + "\n")
    before = sha256_file(p)
    fd, v = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    recs, conflicts = backfill_view(p, v)
    view = load_jsonl(v)
    assert sha256_file(p) == before
    assert {x["key"] for x in view} == {x["key"] for x in rows2}
    assert view[2]["license_class"] == "arc-dsl-mit"
    assert view[4]["license_class"] == "arc-dsl-mit"  # wrongtask (eng #80)
    assert view[5]["license_class"] == "UNKNOWN"
    assert conflicts == 1
    assert view[6]["license_basis"].startswith("CONFLICT(")
    os.unlink(p)
    os.unlink(v)

    # eng #172: the receipt carries sha256 fields, so it MUST declare
    # sha_convention — receipt_check fail-closes otherwise. Pin both that the
    # emitter wires it (source) and that the contract holds (functional).
    # issue2015 exact-local-import:src/ember/governance/scripts/receipt_check.py
    import importlib.util as _ember_2ad73f5df12b45ee_importlib
    import sys as _ember_2ad73f5df12b45ee_sys
    from pathlib import Path as _ember_2ad73f5df12b45ee_Path
    _ember_2ad73f5df12b45ee_path = _ember_2ad73f5df12b45ee_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_check.py')
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
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    assert '"sha_convention": SHA_CONVENTION' in src, \
        "emitter receipt must carry sha_convention"
    shaped = {"ticket": "ENG20-LICENSE-VIEW", "ts": "20260611T000000Z",
              "ledger_sha256_before": "a" * 64, "ledger_sha256_after": "a" * 64,
              "sha_convention": SHA_CONVENTION}
    assert receipt_check.validate_receipt(shaped) == [], \
        receipt_check.validate_receipt(shaped)
    no_conv = {k: v for k, v in shaped.items() if k != "sha_convention"}
    assert any("MISSING_SHA_CONVENTION" in f
               for f in receipt_check.validate_receipt(no_conv)), \
        "without sha_convention the sha-bearing receipt must be flagged"

    print("LEDGER_LICENSE_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
