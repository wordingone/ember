# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Schema/runtime agreement for the checked-in task-015 packet."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT))

# issue2015 exact-local-import:src/ember/governance/scripts/oldest_issue_disposition.py
import importlib.util as _ember_366a9bf8189d4fa2_importlib
import sys as _ember_366a9bf8189d4fa2_sys
from pathlib import Path as _ember_366a9bf8189d4fa2_Path
_ember_366a9bf8189d4fa2_path = _ember_366a9bf8189d4fa2_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'oldest_issue_disposition.py')
if not _ember_366a9bf8189d4fa2_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/oldest_issue_disposition.py')
_ember_366a9bf8189d4fa2_aliases = ('_ember_issue2015_366a9bf8189d4fa2', 'oldest_issue_disposition', 'scripts.oldest_issue_disposition', 'src.ember.governance.scripts.oldest_issue_disposition')
_ember_366a9bf8189d4fa2_existing = []
for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
    _ember_366a9bf8189d4fa2_candidate = _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias)
    if _ember_366a9bf8189d4fa2_candidate is not None and all(_ember_366a9bf8189d4fa2_candidate is not item for item in _ember_366a9bf8189d4fa2_existing):
        _ember_366a9bf8189d4fa2_existing.append(_ember_366a9bf8189d4fa2_candidate)
if len(_ember_366a9bf8189d4fa2_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/oldest_issue_disposition.py')
if _ember_366a9bf8189d4fa2_existing:
    _ember_366a9bf8189d4fa2_module = _ember_366a9bf8189d4fa2_existing[0]
    _ember_366a9bf8189d4fa2_observed = getattr(_ember_366a9bf8189d4fa2_module, '__file__', None)
    if _ember_366a9bf8189d4fa2_observed is None or _ember_366a9bf8189d4fa2_Path(_ember_366a9bf8189d4fa2_observed).resolve() != _ember_366a9bf8189d4fa2_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/oldest_issue_disposition.py')
else:
    _ember_366a9bf8189d4fa2_spec = _ember_366a9bf8189d4fa2_importlib.spec_from_file_location('_ember_issue2015_366a9bf8189d4fa2', _ember_366a9bf8189d4fa2_path)
    if _ember_366a9bf8189d4fa2_spec is None or _ember_366a9bf8189d4fa2_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/oldest_issue_disposition.py')
    _ember_366a9bf8189d4fa2_module = _ember_366a9bf8189d4fa2_importlib.module_from_spec(_ember_366a9bf8189d4fa2_spec)
    for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
        _ember_366a9bf8189d4fa2_prior = _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias)
        if _ember_366a9bf8189d4fa2_prior is not None and _ember_366a9bf8189d4fa2_prior is not _ember_366a9bf8189d4fa2_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/oldest_issue_disposition.py')
        _ember_366a9bf8189d4fa2_sys.modules[_ember_366a9bf8189d4fa2_alias] = _ember_366a9bf8189d4fa2_module
    try:
        _ember_366a9bf8189d4fa2_spec.loader.exec_module(_ember_366a9bf8189d4fa2_module)
    except BaseException:
        for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
            if _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias) is _ember_366a9bf8189d4fa2_module:
                _ember_366a9bf8189d4fa2_sys.modules.pop(_ember_366a9bf8189d4fa2_alias, None)
        raise
for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
    _ember_366a9bf8189d4fa2_prior = _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias)
    if _ember_366a9bf8189d4fa2_prior is not None and _ember_366a9bf8189d4fa2_prior is not _ember_366a9bf8189d4fa2_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/oldest_issue_disposition.py')
    _ember_366a9bf8189d4fa2_sys.modules[_ember_366a9bf8189d4fa2_alias] = _ember_366a9bf8189d4fa2_module
validate_packet = getattr(_ember_366a9bf8189d4fa2_module, 'validate_packet')
# issue2015 exact-local-import-end:src/ember/governance/scripts/oldest_issue_disposition.py
# issue2015 exact-local-import:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py
import importlib.util as _ember_e1908f060d71f822_importlib
import sys as _ember_e1908f060d71f822_sys
from pathlib import Path as _ember_e1908f060d71f822_Path
_ember_e1908f060d71f822_path = _ember_e1908f060d71f822_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'verify_oldest_issue_disposition_packet.py')
if not _ember_e1908f060d71f822_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
_ember_e1908f060d71f822_aliases = ('_ember_issue2015_e1908f060d71f822', 'scripts.verify_oldest_issue_disposition_packet', 'src.ember.governance.scripts.verify_oldest_issue_disposition_packet', 'verify_oldest_issue_disposition_packet')
_ember_e1908f060d71f822_existing = []
for _ember_e1908f060d71f822_alias in _ember_e1908f060d71f822_aliases:
    _ember_e1908f060d71f822_candidate = _ember_e1908f060d71f822_sys.modules.get(_ember_e1908f060d71f822_alias)
    if _ember_e1908f060d71f822_candidate is not None and all(_ember_e1908f060d71f822_candidate is not item for item in _ember_e1908f060d71f822_existing):
        _ember_e1908f060d71f822_existing.append(_ember_e1908f060d71f822_candidate)
if len(_ember_e1908f060d71f822_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
if _ember_e1908f060d71f822_existing:
    _ember_e1908f060d71f822_module = _ember_e1908f060d71f822_existing[0]
    _ember_e1908f060d71f822_observed = getattr(_ember_e1908f060d71f822_module, '__file__', None)
    if _ember_e1908f060d71f822_observed is None or _ember_e1908f060d71f822_Path(_ember_e1908f060d71f822_observed).resolve() != _ember_e1908f060d71f822_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
else:
    _ember_e1908f060d71f822_spec = _ember_e1908f060d71f822_importlib.spec_from_file_location('_ember_issue2015_e1908f060d71f822', _ember_e1908f060d71f822_path)
    if _ember_e1908f060d71f822_spec is None or _ember_e1908f060d71f822_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
    _ember_e1908f060d71f822_module = _ember_e1908f060d71f822_importlib.module_from_spec(_ember_e1908f060d71f822_spec)
    for _ember_e1908f060d71f822_alias in _ember_e1908f060d71f822_aliases:
        _ember_e1908f060d71f822_prior = _ember_e1908f060d71f822_sys.modules.get(_ember_e1908f060d71f822_alias)
        if _ember_e1908f060d71f822_prior is not None and _ember_e1908f060d71f822_prior is not _ember_e1908f060d71f822_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
        _ember_e1908f060d71f822_sys.modules[_ember_e1908f060d71f822_alias] = _ember_e1908f060d71f822_module
    try:
        _ember_e1908f060d71f822_spec.loader.exec_module(_ember_e1908f060d71f822_module)
    except BaseException:
        for _ember_e1908f060d71f822_alias in _ember_e1908f060d71f822_aliases:
            if _ember_e1908f060d71f822_sys.modules.get(_ember_e1908f060d71f822_alias) is _ember_e1908f060d71f822_module:
                _ember_e1908f060d71f822_sys.modules.pop(_ember_e1908f060d71f822_alias, None)
        raise
for _ember_e1908f060d71f822_alias in _ember_e1908f060d71f822_aliases:
    _ember_e1908f060d71f822_prior = _ember_e1908f060d71f822_sys.modules.get(_ember_e1908f060d71f822_alias)
    if _ember_e1908f060d71f822_prior is not None and _ember_e1908f060d71f822_prior is not _ember_e1908f060d71f822_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
    _ember_e1908f060d71f822_sys.modules[_ember_e1908f060d71f822_alias] = _ember_e1908f060d71f822_module
verify_replay = getattr(_ember_e1908f060d71f822_module, 'verify_replay')
# issue2015 exact-local-import-end:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py

CAPTURED_MASTER = "e8a89a39cee293d793543e025a0d03fee0181e6d"

SCHEMA = ROOT / "manifests" / "oldest-issue-disposition" / "schema-v1.json"
PACKET = (
    ROOT
    / "receipts"
    / "oldest-issue-disposition"
    / "ember-oldest-issue-disposition-015-packet-v1.json"
)
CLASSIFICATIONS = (
    ROOT / "manifests" / "oldest-issue-disposition" / "classifications-v1.json"
)
RAW_BUNDLE = (
    ROOT
    / "receipts"
    / "oldest-issue-disposition"
    / "ember-oldest-issue-disposition-015-raw-sources-v1.json"
)


def test_checked_in_packet_passes_schema_and_runtime_validator() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8", errors="strict"))
    packet = json.loads(PACKET.read_text(encoding="utf-8", errors="strict"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(
        packet,
        schema,
        cls=jsonschema.Draft202012Validator,
    )
    validate_packet(packet, expected_master=CAPTURED_MASTER)
    classifications = json.loads(
        CLASSIFICATIONS.read_text(encoding="utf-8", errors="strict")
    )
    verify_replay(
        packet,
        raw_bundle=RAW_BUNDLE,
        classifications_value=classifications,
        expected_master=CAPTURED_MASTER,
    )


def test_runtime_validator_requires_an_independent_master_pin() -> None:
    packet = json.loads(PACKET.read_text(encoding="utf-8", errors="strict"))
    try:
        validate_packet(packet)  # type: ignore[call-arg]
    except TypeError:
        return
    raise AssertionError("validate_packet accepted an omitted master pin")


def test_authority_review_schema_accepts_honest_provenance_pairs_only() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8", errors="strict"))
    schema["$defs"]["authorityReview"]
    independent = {
        "reviewer": "delegated-authority",
        "review_provenance": "INDEPENDENT_DELEGATED",
        "verdict": "PASS",
        "citation": "mailbox:999",
        "reviewed_commit_sha": "a" * 40,
    }
    solo = {
        "reviewer": "self-review-authority",
        "review_provenance": "SELF_ONLY",
        "verdict": "PASS",
        "citation": "https://github.com/wordingone/ember/pull/1200",
        "reviewed_commit_sha": "b" * 40,
    }

    # Validate through the full schema so local SHA references resolve normally.
    wrapper = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": schema["$defs"],
        "$ref": "#/$defs/authorityReview",
    }
    jsonschema.validate(independent, wrapper, cls=jsonschema.Draft202012Validator)
    jsonschema.validate(solo, wrapper, cls=jsonschema.Draft202012Validator)
    mismatched = dict(solo, review_provenance="INDEPENDENT_DELEGATED")
    try:
        jsonschema.validate(
            mismatched,
            wrapper,
            cls=jsonschema.Draft202012Validator,
        )
    except jsonschema.ValidationError:
        return
    raise AssertionError("authority review schema accepted mismatched provenance")
