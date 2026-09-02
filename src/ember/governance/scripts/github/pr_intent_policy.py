#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate a pull request that has not been opened yet against the live PR policy.

`live_pr_policy.validate_live_pull_request` can only run once a PR exists, so a
builder discovers a missing milestone or a second `kind:` label from a red CI run
rather than before `gh pr create`. This module closes that gap without restating
the contract: it maps a declared PR *intent* onto the snapshot that gate already
validates and hands it to that same function. Every rule about titles, label
cardinality, template markers, required sections, authority binding, and body/SHA
agreement continues to live in exactly one place.

Two checks are added on top, and they are the only ones original to this module.
The gate reasons about a snapshot GitHub has already accepted, so it can take for
granted that every label and the milestone exist -- GitHub would have rejected an
unknown one at apply time. Before the PR exists nothing has been accepted yet, so
`area:tooling` looks indistinguishable from `area:tools` to a cardinality count.
The repository's actual vocabulary is therefore required here, and it is required
rather than optional: an unavailable vocabulary is an error, never a silent skip.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# issue2015 exact-local-import:src/ember/governance/scripts/check_pr_authority_binding.py
import importlib.util as _ember_fab48fcd56c3e48d_importlib
import sys as _ember_fab48fcd56c3e48d_sys
from pathlib import Path as _ember_fab48fcd56c3e48d_Path
_ember_fab48fcd56c3e48d_path = _ember_fab48fcd56c3e48d_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'governance', 'scripts', 'check_pr_authority_binding.py')
if not _ember_fab48fcd56c3e48d_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/check_pr_authority_binding.py')
_ember_fab48fcd56c3e48d_aliases = ('_ember_issue2015_fab48fcd56c3e48d', 'check_pr_authority_binding', 'scripts.check_pr_authority_binding', 'src.ember.governance.scripts.check_pr_authority_binding')
_ember_fab48fcd56c3e48d_existing = []
for _ember_fab48fcd56c3e48d_alias in _ember_fab48fcd56c3e48d_aliases:
    _ember_fab48fcd56c3e48d_candidate = _ember_fab48fcd56c3e48d_sys.modules.get(_ember_fab48fcd56c3e48d_alias)
    if _ember_fab48fcd56c3e48d_candidate is not None and all(_ember_fab48fcd56c3e48d_candidate is not item for item in _ember_fab48fcd56c3e48d_existing):
        _ember_fab48fcd56c3e48d_existing.append(_ember_fab48fcd56c3e48d_candidate)
if len(_ember_fab48fcd56c3e48d_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/check_pr_authority_binding.py')
if _ember_fab48fcd56c3e48d_existing:
    _ember_fab48fcd56c3e48d_module = _ember_fab48fcd56c3e48d_existing[0]
    _ember_fab48fcd56c3e48d_observed = getattr(_ember_fab48fcd56c3e48d_module, '__file__', None)
    if _ember_fab48fcd56c3e48d_observed is None or _ember_fab48fcd56c3e48d_Path(_ember_fab48fcd56c3e48d_observed).resolve() != _ember_fab48fcd56c3e48d_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/check_pr_authority_binding.py')
else:
    _ember_fab48fcd56c3e48d_spec = _ember_fab48fcd56c3e48d_importlib.spec_from_file_location('_ember_issue2015_fab48fcd56c3e48d', _ember_fab48fcd56c3e48d_path)
    if _ember_fab48fcd56c3e48d_spec is None or _ember_fab48fcd56c3e48d_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/check_pr_authority_binding.py')
    _ember_fab48fcd56c3e48d_module = _ember_fab48fcd56c3e48d_importlib.module_from_spec(_ember_fab48fcd56c3e48d_spec)
    for _ember_fab48fcd56c3e48d_alias in _ember_fab48fcd56c3e48d_aliases:
        _ember_fab48fcd56c3e48d_prior = _ember_fab48fcd56c3e48d_sys.modules.get(_ember_fab48fcd56c3e48d_alias)
        if _ember_fab48fcd56c3e48d_prior is not None and _ember_fab48fcd56c3e48d_prior is not _ember_fab48fcd56c3e48d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/check_pr_authority_binding.py')
        _ember_fab48fcd56c3e48d_sys.modules[_ember_fab48fcd56c3e48d_alias] = _ember_fab48fcd56c3e48d_module
    try:
        _ember_fab48fcd56c3e48d_spec.loader.exec_module(_ember_fab48fcd56c3e48d_module)
    except BaseException:
        for _ember_fab48fcd56c3e48d_alias in _ember_fab48fcd56c3e48d_aliases:
            if _ember_fab48fcd56c3e48d_sys.modules.get(_ember_fab48fcd56c3e48d_alias) is _ember_fab48fcd56c3e48d_module:
                _ember_fab48fcd56c3e48d_sys.modules.pop(_ember_fab48fcd56c3e48d_alias, None)
        raise
for _ember_fab48fcd56c3e48d_alias in _ember_fab48fcd56c3e48d_aliases:
    _ember_fab48fcd56c3e48d_prior = _ember_fab48fcd56c3e48d_sys.modules.get(_ember_fab48fcd56c3e48d_alias)
    if _ember_fab48fcd56c3e48d_prior is not None and _ember_fab48fcd56c3e48d_prior is not _ember_fab48fcd56c3e48d_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/check_pr_authority_binding.py')
    _ember_fab48fcd56c3e48d_sys.modules[_ember_fab48fcd56c3e48d_alias] = _ember_fab48fcd56c3e48d_module
load_goal_binding = getattr(_ember_fab48fcd56c3e48d_module, 'load_goal_binding')
# issue2015 exact-local-import-end:src/ember/governance/scripts/check_pr_authority_binding.py
from src.ember.governance.scripts.github.live_pr_policy import SNAPSHOT_FIELDS, validate_live_pull_request


# Derived from the gate's own field set rather than restated. A field added to
# SNAPSHOT_FIELDS becomes required of an intent automatically, so this module
# cannot silently drift into validating a narrower object than the gate does.
DERIVED_FIELDS = {"event_base_sha", "event_head_sha"}
INTENT_FIELDS = SNAPSHOT_FIELDS - DERIVED_FIELDS


def _names(payload: Any, key: str) -> list[str]:
    """Normalize a `gh api` listing to plain names.

    Accepts a list of strings, a list of objects carrying `key`, or the
    list-of-pages shape that `gh api --paginate --slurp` produces.
    """
    if not isinstance(payload, list):
        raise ValueError("vocabulary payload must be a list")
    rows: list[Any] = []
    for entry in payload:
        if isinstance(entry, list):
            rows.extend(entry)
        else:
            rows.append(entry)
    names: list[str] = []
    for row in rows:
        if isinstance(row, str):
            names.append(row)
        elif isinstance(row, Mapping) and isinstance(row.get(key), str):
            names.append(row[key])
        else:
            raise ValueError("vocabulary row is malformed")
    return names


def validate_intent_fields(intent: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(intent) - INTENT_FIELDS)
    missing = sorted(INTENT_FIELDS - set(intent))
    if unknown:
        errors.append(f"intent:unknown-fields:{','.join(unknown)}")
    if missing:
        errors.append(f"intent:missing-fields:{','.join(missing)}")
    return errors


def build_intent_snapshot(intent: Mapping[str, Any]) -> dict[str, Any]:
    """Map an intent onto a live-policy snapshot.

    At open time GitHub's event SHAs are by definition the PR's own SHAs, so the
    two derived fields are filled from the intent rather than asked of the caller.
    """
    snapshot = dict(intent)
    snapshot["event_base_sha"] = intent.get("base_sha")
    snapshot["event_head_sha"] = intent.get("head_sha")
    return snapshot


def validate_vocabulary(
    labels: Sequence[str],
    milestone: str | None,
    *,
    known_labels: Iterable[str] | None,
    known_milestones: Iterable[str] | None,
) -> list[str]:
    if known_labels is None or known_milestones is None:
        return ["vocabulary:unavailable"]
    errors: list[str] = []
    for label in sorted(set(labels) - set(known_labels)):
        errors.append(f"vocabulary:label-unknown:{label}")
    if milestone is not None and milestone not in set(known_milestones):
        errors.append(f"vocabulary:milestone-unknown:{milestone}")
    return errors


def validate_pr_intent(
    intent: Mapping[str, Any],
    *,
    authority: tuple[str, str, Sequence[str]],
    known_labels: Iterable[str] | None,
    known_milestones: Iterable[str] | None,
) -> list[str]:
    errors = validate_intent_fields(intent)
    if errors:
        return errors
    snapshot = build_intent_snapshot(intent)
    errors = list(validate_live_pull_request(snapshot, authority=authority))
    labels = intent.get("labels")
    errors.extend(
        validate_vocabulary(
            labels if isinstance(labels, list) else [],
            intent.get("milestone"),
            known_labels=known_labels,
            known_milestones=known_milestones,
        )
    )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--intent-json", type=Path, required=True)
    parser.add_argument("--labels-json", type=Path, required=True)
    parser.add_argument("--milestones-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        intent = json.loads(args.intent_json.read_text(encoding="utf-8", errors="strict"))
        known_labels = _names(
            json.loads(args.labels_json.read_text(encoding="utf-8", errors="strict")),
            "name",
        )
        known_milestones = _names(
            json.loads(args.milestones_json.read_text(encoding="utf-8", errors="strict")),
            "title",
        )
        errors = validate_pr_intent(
            intent,
            authority=load_goal_binding(args.root.resolve()),
            known_labels=known_labels,
            known_milestones=known_milestones,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "errors": [str(exc)]}, sort_keys=True))
        return 1
    print(json.dumps(
        {
            "status": "PASS" if not errors else "FAIL",
            "errors": errors,
            # True for both callers: the pre-open wrapper and Step C of the
            # authbind preflight are predicting a verdict, never rendering one.
            # The public gate remains the only authority.
            "claim_boundary": (
                "pull-request policy prediction only; the public gate is authoritative"
            ),
        },
        sort_keys=True,
    ))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
