#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""a1_quarantine_enum_v2.py -- ember #631 deliverable 2: SEMANTIC pre-freeze
quarantine enumeration (supersedes scripts/a1_quarantine_enum.py).

Cures A1 machinery defect #2 (refs #123 finding 2): the v1 enum searched only
(i) the suite-(a) batch sha256, (ii) each suite-(b) split sha256, and (iii) the
literal strings "eval-suite-v1" / "eval_suite_v1". It therefore MISSED every
pre-freeze receipt that cites a suite-(b) dataset by its TASK/WORLD identity
rather than by split-hash or suite-name -- concretely
`receipts/w1-humaneval-q3-20260610T234716Z.json` (world=humanevalplus,
split.total=164, verified_samples=543, admission.admitted=true) and
`receipts/fp32-baselines-20260611T142515Z.json` (HumanEval+ scores). So the
v1 receipt's "zero suite-citing receipts left unclassified" was false.

v2 adds SEMANTIC dataset-identity markers derived from the freeze receipt (each
dataset's name, its HuggingFace slug from canonical_url, its on-disk dir name)
plus a curated world-value alias map, matched case-insensitively with word
boundaries. A receipt cites the suite iff its raw text contains ANY marker
(hash OR literal-name OR semantic-identity). Every pre-freeze citing receipt is
quarantined; over-quarantine is the safe direction (the freeze doc's rule:
"NO pre-freeze receipt may be cited by a capability claim").

pre_freeze is determined per-receipt by comparing its parsed `ts` to the A1
declaration freeze_ts (NOT the v1 blanket assumption): a citing receipt whose
ts >= freeze_ts is NOT quarantined (it postdates the freeze -- e.g. the
declaration/amendment themselves, later governed receipts). An unparseable ts
is treated pre_freeze (conservative).

Classification (transparent, non-gating -- all pre_freeze citing receipts are
quarantined regardless of class):
  - eval_score        : carries eval-score / admission fields against a suite
                        dataset (the launder-risk class; w1-humaneval-q3 here);
  - training_consumed : a training/RL/probe receipt that CONSUMED a suite
                        dataset as a world (train_loss/steps/episodes/...) --
                        lineage-relevant (refs #631 deliverable 3);
  - pin_infra         : cites a dataset identity but carries neither.

Excluded from the quarantine (they ARE the freeze machinery, not dev evidence):
the A1 declaration, the exclusion amendment, and any a1-prefreeze-quarantine-*
receipt (v1 or this v2 output).

Usage:
  python scripts/a1_quarantine_enum_v2.py \\
      --heldout-receipt receipts/ember-c-scale/w2-heldout-decontam-20260708T121128Z.json \\
      --freeze-receipt receipts/eval-suite-freeze/eval-suite-freeze-v1.json \\
      --declaration receipts/eval-suite-freeze/a1-freeze-declaration-20260709T233050Z.json \\
      --prior-quarantine receipts/eval-suite-freeze/a1-prefreeze-quarantine-20260709T231802Z.json \\
      --out receipts/eval-suite-freeze/a1-prefreeze-quarantine-v2-<UTCts>.json \\
      [--legacy-markers-only]   # reproduce the v1 miss (fail-then-pass demo)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

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
receipt_write = _ember_66ee9e91637922dc_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"

NAME_MARKERS = ["eval-suite-v1", "eval_suite_v1"]
SCORE_FIELD_MARKERS = ['"eval_loss', '"final_eval_loss"', '"target_eval_loss"', '"score"',
                       '"feed_pct"', '"verified_samples"', '"admission"', '"pass@', '"pass_at']
TRAIN_FIELD_MARKERS = ['"train_loss"', '"steps"', '"episodes"', '"frontier"',
                       '"bits_banked"', '"n_texts_after_repeat"', '"n_examples"']

# curated world-value / task-identity aliases per suite-(b) dataset (the surface
# forms these datasets take in ember training/eval receipts), plus the derived
# markers (name, hf slug, dir name) are added at runtime from the freeze receipt.
WORLD_ALIASES = {
    "MMLU-Pro": [r"mmlu[-_]?pro"],
    "GSM8K": [r"\bgsm8k\b"],
    "MATH-500": [r"math[-_]?500"],
    "ARC-Challenge": [r"arc[-_]challenge", r"ai2_arc", r"\barc-c\b"],
    "HumanEval+": [r"humaneval\s*\+?", r"humanevalplus"],
    "MBPP": [r"\bmbpp\b"],
    "HellaSwag": [r"\bhellaswag\b"],
}
DIR_NAME_MAP = {"MMLU-Pro": "MMLU-Pro", "GSM8K": "GSM8K", "MATH-500": "MATH-500",
                "ARC-Challenge": "ARC-Challenge", "HumanEval+": "HumanEvalplus",
                "MBPP": "MBPP", "HellaSwag": "HellaSwag"}


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def parse_ts(t):
    if not t:
        return None
    try:
        return datetime.strptime(t, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def git_tracked_receipts(repo: str) -> list[str]:
    out = subprocess.run(["git", "-C", repo, "ls-files", "receipts/"],
                         capture_output=True, text=True, check=True)
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def build_semantic_patterns(freeze: dict):
    """Per-dataset compiled regexes: derived (name, hf slug, dir name) + curated
    world aliases. Returns {dataset_name: [compiled...]}."""
    pats = {}
    for ds in freeze["datasets"]:
        name = ds["name"]
        if ds.get("test_split_sha256") in (None, "PIN-PENDING"):
            continue
        toks = set()
        toks.add(re.escape(name))                                   # "MMLU-Pro"
        slug = ds.get("canonical_url", "").rstrip("/").split("/")[-1]
        if slug:
            toks.add(re.escape(slug))                               # "humanevalplus"
        toks.add(re.escape(DIR_NAME_MAP[name]))                     # "HumanEvalplus"
        raws = list(WORLD_ALIASES.get(name, []))                    # curated aliases (already regex)
        compiled = [re.compile(r"\b" + t + r"\b", re.I) for t in toks]
        compiled += [re.compile(r, re.I) for r in raws]
        pats[name] = compiled
    return pats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--heldout-receipt", required=True)
    ap.add_argument("--freeze-receipt", required=True)
    ap.add_argument("--declaration", required=True)
    ap.add_argument("--prior-quarantine", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--legacy-markers-only", action="store_true",
                     help="reproduce the v1 miss: use ONLY hash + literal-name markers")
    args = ap.parse_args()

    heldout = json.load(open(os.path.join(REPO, args.heldout_receipt), encoding="utf-8"))
    freeze = json.load(open(os.path.join(REPO, args.freeze_receipt), encoding="utf-8"))
    declaration = json.load(open(os.path.join(REPO, args.declaration), encoding="utf-8"))
    freeze_ts_raw = declaration["freeze_ts"]
    freeze_ts = parse_ts(freeze_ts_raw)

    suite_a_sha = heldout["batch_sha256"]
    suite_b_shas = {ds["name"]: ds["test_split_sha256"] for ds in freeze["datasets"]
                    if ds.get("test_split_sha256") not in (None, "PIN-PENDING")}
    hash_markers = {"suite_a_batch_sha256": suite_a_sha}
    for name, sha in suite_b_shas.items():
        hash_markers[f"suite_b:{name}"] = sha

    semantic = {} if args.legacy_markers_only else build_semantic_patterns(freeze)

    tracked = git_tracked_receipts(REPO)
    self_rel = os.path.relpath(os.path.join(REPO, args.out), REPO).replace(os.sep, "/")
    # machinery artifacts never quarantined (they ARE the freeze, not dev evidence)
    machinery = {self_rel,
                 os.path.relpath(os.path.join(REPO, args.declaration), REPO).replace(os.sep, "/"),
                 os.path.relpath(os.path.join(REPO, args.prior_quarantine), REPO).replace(os.sep, "/")}
    # also exclude the exclusion amendment + any a1-prefreeze-quarantine-* (v1/v2)
    def is_machinery(rel):
        base = os.path.basename(rel)
        return (rel in machinery
                or base.startswith("a1-prefreeze-quarantine")
                or base.startswith("a1-freeze-declaration")
                or base.startswith("a1-freeze-exclusion-amendment"))

    rows = []
    n_unreadable = 0
    n_post_freeze_citing = 0
    for rel in tracked:
        if is_machinery(rel):
            continue
        p = os.path.join(REPO, rel)
        try:
            text = open(p, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            n_unreadable += 1
            continue

        found = [label for label, sha in hash_markers.items() if sha in text]
        found += [f"name:{m}" for m in NAME_MARKERS if m in text]
        sem_hits = [name for name, ps in semantic.items() if any(p_.search(text) for p_ in ps)]
        found += [f"semantic:{n}" for n in sem_hits]
        if not found:
            continue

        try:
            ts = json.loads(text).get("ts")
        except (json.JSONDecodeError, AttributeError):
            ts = None
        tsp = parse_ts(ts)
        pre_freeze = (tsp is None) or (freeze_ts is None) or (tsp < freeze_ts)
        if not pre_freeze:
            n_post_freeze_citing += 1
            continue

        cites_scores = any(m in text for m in SCORE_FIELD_MARKERS)
        has_train = any(m in text for m in TRAIN_FIELD_MARKERS)
        cls = ("eval_score" if cites_scores
               else ("training_consumed" if has_train else "pin_infra"))
        rows.append({
            "id": rel.replace(os.sep, "/"),
            "ts": ts,
            "pre_freeze": True,
            "cites_scores": cites_scores,
            "class": cls,
            "markers_found": found,
            "why_quarantined": {
                "eval_score": "carries eval-score/admission fields against a frozen suite "
                              "dataset and predates the A1 freeze declaration: development-only, "
                              "may never be cited by a capability claim",
                "training_consumed": "a pre-freeze training/RL/probe receipt that CONSUMED a "
                                     "frozen suite dataset as a world (lineage-relevant, refs "
                                     "#631 deliverable 3): development-only, may never back a claim",
                "pin_infra": "references a frozen suite dataset identity pre-declaration "
                             "(pin/infrastructure/design): development-only, quarantined",
            }[cls],
        })

    rows.sort(key=lambda r: (r["class"], r["id"]))
    prior = json.load(open(os.path.join(REPO, args.prior_quarantine), encoding="utf-8"))
    prior_ids = {r["id"] for r in prior.get("rows", [])}
    new_ids = {r["id"] for r in rows}

    receipt = {
        "ticket": "A1-PREFREEZE-QUARANTINE-V2",
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema": "a1-prefreeze-quarantine/v2",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue_refs": ["#631", "#123", "#593", "#591"],
        "supersedes": {
            "receipt": args.prior_quarantine.replace(os.sep, "/"),
            "receipt_sha256": file_sha256(os.path.join(REPO, args.prior_quarantine)),
            "note": "append-only cure (refs #482 shape): the v1 receipt is NEVER edited; this "
                    "v2 receipt re-enumerates with semantic markers and cites it by sha256",
            "n_v1_rows": len(prior_ids),
            "n_v1_rows_missing_from_v2": len(prior_ids - new_ids),
            "v1_rows_missing_from_v2": sorted(prior_ids - new_ids),
            "n_new_rows_added_by_semantic_pass": len(new_ids - prior_ids),
        },
        "freeze_ts_ref": freeze_ts_raw,
        "enumeration_source": {
            "file_set": "git ls-files receipts/ (every tracked receipt at this branch base)",
            "n_files_enumerated": len(tracked),
            "n_files_unreadable": n_unreadable,
            "hash_markers": hash_markers,
            "name_markers": NAME_MARKERS,
            "semantic_markers": {
                "derived_from": "freeze receipt: each dataset name + HuggingFace canonical_url "
                                "slug + on-disk dir name (word-boundary, case-insensitive)",
                "world_aliases": WORLD_ALIASES,
                "note": "curative addition over v1; v1 used only hash + literal-name markers",
            },
            "score_field_markers": SCORE_FIELD_MARKERS,
            "train_field_markers": TRAIN_FIELD_MARKERS,
            "pre_freeze_rule": "ts < declaration.freeze_ts; unparseable ts treated pre_freeze "
                               "(conservative); ts >= freeze_ts NOT quarantined",
            "machinery_excluded": "A1 declaration, exclusion amendment, and all "
                                  "a1-prefreeze-quarantine-* receipts",
        },
        "n_post_freeze_citing_not_quarantined": n_post_freeze_citing,
        "n_quarantined": len(rows),
        "n_eval_score": sum(1 for r in rows if r["class"] == "eval_score"),
        "n_training_consumed": sum(1 for r in rows if r["class"] == "training_consumed"),
        "n_pin_infra": sum(1 for r in rows if r["class"] == "pin_infra"),
        "rows": rows,
    }

    out_abs = os.path.join(REPO, args.out)
    d = os.path.dirname(out_abs)
    if d:
        os.makedirs(d, exist_ok=True)
    receipt_write.checked_write(out_abs, receipt)
    print(f"A1_QUARANTINE_V2{'[LEGACY]' if args.legacy_markers_only else ''}: "
          f"{len(rows)} quarantined (eval_score={receipt['n_eval_score']}, "
          f"training_consumed={receipt['n_training_consumed']}, pin_infra={receipt['n_pin_infra']}) "
          f"from {len(tracked)} enumerated; +{len(new_ids - prior_ids)} new vs v1, "
          f"{len(prior_ids - new_ids)} v1-rows-dropped -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
