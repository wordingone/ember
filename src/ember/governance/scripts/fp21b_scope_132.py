# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fp21b_scope_132.py — pin the precise trigger-scope of #132 (fp-21b
prong-A) under the FROZEN fp-26 (b) decision, and demonstrate the world
gate's branches.

fp-21b prong-A asks: does the BORROWED-WORLD band predict downstream
transfer? Its bars/band-legs are Qwen/w1-mbpp artifacts (fp21b_prereg
WORLD_PIN). The fp-26 freeze (fp26-prereg-20260611T081213Z) chose round-3
shape (b) = owned-core in-dist accumulation (ember-v0 in the fp-22
verify-floor world). Consequences, made precise here:

- The PRIMARY (b) round-3 sampling comes from ember-v0 — a different
  model+world. fp-21b's world gate REFUSES it (NOT-APPLICABLE-WORLD-
  CHANGED). The transfer-PREDICTION question does not apply at all: (b)'s
  world is in-dist by construction (eval == train), so cross-task transfer
  is not the axis. The band-transfer bars are borrowed-world artifacts and
  do NOT carry.
- fp-21b prong-A therefore fires ONLY on a FALLBACK-(a) round-3 sampling
  receipt: borrowed-core (Qwen/w1-mbpp) round-3, which exists only if the
  owned core kills the verify floor and (a) is taken.

#132 stays OPEN — trigger-gated, conditional on fallback-(a). This is NOT a
scope reduction: the re-execution still happens when its trigger lands; only
the exact firing world is pinned, tied to the fp-26 decision sha so the
scope cannot silently drift from the freeze.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
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
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py              # noqa: E402
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
validate_receipt = getattr(_ember_2ad73f5df12b45ee_module, 'validate_receipt')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_check.py            # noqa: E402
from fp21b_prereg import check_sampling_world, WORLD_PIN  # noqa: E402

# pin the frozen fp-26 decision so this scope can't drift from the freeze
FP26_DECISION = "docs/domains/governance/research/fp26-round3-shape-decision.md"
FP26_DECISION_SHA = ("5ef7cc20f22168878f139af00e6ac9a75d43c758"
                     "ffd2b3eb181372c50081c939")
OWNED_CORE_MODEL = "ember-v0-0.37b"   # the (b) round-3 sampler (world-changed)
SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _demo_branch(model_or_none):
    """Build a temp sibling receipt with the given args.model (None = no
    sibling) and return the world-gate verdict for it."""
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, "r3-samples.jsonl")
        open(sp, "w", encoding="utf-8").write("{}\n")
        if model_or_none is not None:
            rp = os.path.join(td, "r3.json")
            json.dump({"args": {"model": model_or_none}},
                      open(rp, "w", encoding="utf-8"))
        verdict, detail = check_sampling_world(sp)
        return verdict, detail


def demonstrate():
    """Return the three gate outcomes that pin #132's firing condition."""
    owned, owned_d = _demo_branch(OWNED_CORE_MODEL)          # (b) primary
    borrowed, borrowed_d = _demo_branch(WORLD_PIN["model"])  # (a) fallback
    nosib, nosib_d = _demo_branch(None)                      # protocol flag
    return {
        "primary_b_owned_core": {
            "sampler_model": OWNED_CORE_MODEL,
            "world_gate": owned,
            "detail": owned_d,
            "reading": ("(b) round-3 is owned-core in-dist (eval==train); "
                        "fp-21b's borrowed-world transfer-prediction question "
                        "does not apply and the bars do not carry"),
        },
        "fallback_a_borrowed_world": {
            "sampler_model": WORLD_PIN["model"],
            "world_gate": borrowed if borrowed is not None else "APPLICABLE",
            "detail": borrowed_d,
            "reading": ("fp-21b prong-A FIRES here — this is the only world in "
                        "which #132 re-executes (taken iff the owned core "
                        "kills the verify floor)"),
        },
        "missing_sibling": {
            "world_gate": nosib,
            "detail": nosib_d,
            "reading": "no sibling receipt -> refuse to apply borrowed bars",
        },
    }


def build_receipt(ts, branches):
    return {
        "ticket": "FP21B-SCOPE-132",
        "ts": ts,
        "issue": 132,
        "status": "OPEN — trigger-gated, conditional on fallback-(a)",
        "scope": ("fp-21b prong-A (band predicts transfer) is a "
                  "BORROWED-WORLD question; under the frozen fp-26 (b) "
                  "decision it fires ONLY on a fallback-(a) borrowed-world "
                  "(Qwen/w1-mbpp) round-3 sampling receipt"),
        "world_pin": WORLD_PIN,
        "fp26_decision": {"path": FP26_DECISION, "sha256": FP26_DECISION_SHA},
        "gate_branches": branches,
        "not_a_scope_reduction": ("the prong-A re-execution still happens when "
                                  "its trigger lands; only the firing world is "
                                  "pinned. #132 is NOT closed."),
        "result": {"verdict": "SCOPE-PINNED",
                   "fires_in_world": WORLD_PIN["world"],
                   "owned_core_b_refuses": True},
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


def _selftest():
    # the fp-26 decision sha must still match (scope tied to the freeze)
    dp = f"{NC}/{FP26_DECISION}"
    assert os.path.exists(dp), dp
    assert _sha(dp) == FP26_DECISION_SHA, ("fp-26 decision drifted from the "
                                           "pinned freeze sha")
    b = demonstrate()
    # the load-bearing assertions: (b) owned-core refuses, (a) borrowed fires
    assert b["primary_b_owned_core"]["world_gate"] == \
        "NOT-APPLICABLE-WORLD-CHANGED", b["primary_b_owned_core"]
    assert b["fallback_a_borrowed_world"]["world_gate"] == "APPLICABLE", \
        b["fallback_a_borrowed_world"]
    assert b["missing_sibling"]["world_gate"] == "PROTOCOL-FLAG", \
        b["missing_sibling"]
    r = build_receipt("20260101T000000Z", b)
    assert validate_receipt(r) == [], validate_receipt(r)
    print("FP21B_SCOPE_132_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    # fail-closed: refuse to emit if the freeze drifted
    if _sha(f"{NC}/{FP26_DECISION}") != FP26_DECISION_SHA:
        raise SystemExit("fp-26 decision sha drift — refusing to pin scope "
                         "against a changed freeze")
    branches = demonstrate()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = build_receipt(ts, branches)
    out = f"{NC}/receipts/fp21b-scope-132-{ts}.json"
    checked_write(out, receipt)
    reloaded = json.load(open(out, encoding="utf-8"))
    f = validate_receipt(reloaded)
    if f:
        raise SystemExit(f"emitted scope receipt FAILS receipt_check: {f}")
    print(json.dumps(receipt["result"], indent=2))
    print(f"FP21B_SCOPE_132_PINNED {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
