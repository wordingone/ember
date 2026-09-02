# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations


import hashlib
import json

import pytest

# issue2015 exact-local-import:src/ember/governance/scripts/ember_01_identity/merge_adjudications.py
import importlib.util as _ember_85fe50cdb978e4df_importlib
import sys as _ember_85fe50cdb978e4df_sys
from pathlib import Path as _ember_85fe50cdb978e4df_Path
_ember_85fe50cdb978e4df_path = _ember_85fe50cdb978e4df_Path(__file__).resolve().parents[3].joinpath('src', 'ember', 'governance', 'scripts', 'ember_01_identity', 'merge_adjudications.py')
if not _ember_85fe50cdb978e4df_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_01_identity/merge_adjudications.py')
_ember_85fe50cdb978e4df_aliases = ('_ember_issue2015_85fe50cdb978e4df', 'merge_adjudications', 'scripts.ember_01_identity.merge_adjudications', 'src.ember.governance.scripts.ember_01_identity.merge_adjudications')
_ember_85fe50cdb978e4df_existing = []
for _ember_85fe50cdb978e4df_alias in _ember_85fe50cdb978e4df_aliases:
    _ember_85fe50cdb978e4df_candidate = _ember_85fe50cdb978e4df_sys.modules.get(_ember_85fe50cdb978e4df_alias)
    if _ember_85fe50cdb978e4df_candidate is not None and all(_ember_85fe50cdb978e4df_candidate is not item for item in _ember_85fe50cdb978e4df_existing):
        _ember_85fe50cdb978e4df_existing.append(_ember_85fe50cdb978e4df_candidate)
if len(_ember_85fe50cdb978e4df_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_01_identity/merge_adjudications.py')
if _ember_85fe50cdb978e4df_existing:
    _ember_85fe50cdb978e4df_module = _ember_85fe50cdb978e4df_existing[0]
    _ember_85fe50cdb978e4df_observed = getattr(_ember_85fe50cdb978e4df_module, '__file__', None)
    if _ember_85fe50cdb978e4df_observed is None or _ember_85fe50cdb978e4df_Path(_ember_85fe50cdb978e4df_observed).resolve() != _ember_85fe50cdb978e4df_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_01_identity/merge_adjudications.py')
else:
    _ember_85fe50cdb978e4df_spec = _ember_85fe50cdb978e4df_importlib.spec_from_file_location('_ember_issue2015_85fe50cdb978e4df', _ember_85fe50cdb978e4df_path)
    if _ember_85fe50cdb978e4df_spec is None or _ember_85fe50cdb978e4df_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_01_identity/merge_adjudications.py')
    _ember_85fe50cdb978e4df_module = _ember_85fe50cdb978e4df_importlib.module_from_spec(_ember_85fe50cdb978e4df_spec)
    for _ember_85fe50cdb978e4df_alias in _ember_85fe50cdb978e4df_aliases:
        _ember_85fe50cdb978e4df_prior = _ember_85fe50cdb978e4df_sys.modules.get(_ember_85fe50cdb978e4df_alias)
        if _ember_85fe50cdb978e4df_prior is not None and _ember_85fe50cdb978e4df_prior is not _ember_85fe50cdb978e4df_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_01_identity/merge_adjudications.py')
        _ember_85fe50cdb978e4df_sys.modules[_ember_85fe50cdb978e4df_alias] = _ember_85fe50cdb978e4df_module
    try:
        _ember_85fe50cdb978e4df_spec.loader.exec_module(_ember_85fe50cdb978e4df_module)
    except BaseException:
        for _ember_85fe50cdb978e4df_alias in _ember_85fe50cdb978e4df_aliases:
            if _ember_85fe50cdb978e4df_sys.modules.get(_ember_85fe50cdb978e4df_alias) is _ember_85fe50cdb978e4df_module:
                _ember_85fe50cdb978e4df_sys.modules.pop(_ember_85fe50cdb978e4df_alias, None)
        raise
for _ember_85fe50cdb978e4df_alias in _ember_85fe50cdb978e4df_aliases:
    _ember_85fe50cdb978e4df_prior = _ember_85fe50cdb978e4df_sys.modules.get(_ember_85fe50cdb978e4df_alias)
    if _ember_85fe50cdb978e4df_prior is not None and _ember_85fe50cdb978e4df_prior is not _ember_85fe50cdb978e4df_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_01_identity/merge_adjudications.py')
    _ember_85fe50cdb978e4df_sys.modules[_ember_85fe50cdb978e4df_alias] = _ember_85fe50cdb978e4df_module
merge_adjudication_lanes = getattr(_ember_85fe50cdb978e4df_module, 'merge_adjudication_lanes')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_01_identity/merge_adjudications.py


SOURCE_COMMIT = "a" * 40


def _bytes(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True) + "\n").encode()


def _consumer(path: str, digest: str) -> dict:
    return {
        "path": path,
        "category": "checkpoint_save_load",
        "evidence_sha256": digest,
        "current_input": "checkpoint bytes",
        "derived_label": "checkpoint restore",
        "protocol": "torch.load",
        "failure_behavior": "fails closed",
        "claim_effect": "selects restored state",
        "conflict": "path is not identity",
        "integration_requirement": "bind the exact checkpoint manifest",
    }


def test_merge_expands_legacy_collapsed_selectors_into_line_bound_rows() -> None:
    digest = "b" * 64
    content = "c" * 64
    helper_content = "d" * 64
    source = {
        "roots": [{"root_id": "public-master", "source_commit": SOURCE_COMMIT}],
        "evidence": [
            {"path": "runtime.py", "line": 1, "category": "checkpoint_save_load",
             "line_sha256": digest, "content_sha256": content,
             "evidence_scope": "LINE", "source_role": "EXECUTABLE_CANDIDATE"},
            {"path": "runtime.py", "line": 3, "category": "checkpoint_save_load",
             "line_sha256": digest, "content_sha256": content,
             "evidence_scope": "LINE", "source_role": "EXECUTABLE_CANDIDATE"},
            {"path": "helper.py", "line": 0, "category": "unclassified_file",
             "content_sha256": helper_content, "evidence_scope": "FILE_CATEGORY",
             "source_role": "EXECUTABLE_CANDIDATE"},
        ],
    }
    consumer_scope = '{"path_prefix":"runtime"}'
    consumer_lane = {
        "schema": "ember-consumer-adjudication-review-v1",
        "source_commit": SOURCE_COMMIT,
        "scope": {"path_prefix": "runtime"},
        "coverage": {},
        "consumer_rows": [_consumer("runtime.py", digest)],
        "nonconsumer_rows": [],
        "nonconsumer_files": [],
    }
    helper_lane = {
        "schema": "ember-consumer-adjudication-review-v1",
        "source_commit": SOURCE_COMMIT,
        "scope": "helper",
        "coverage": {},
        "consumer_rows": [],
        "nonconsumer_rows": [],
        "nonconsumer_files": [{
            "path": "helper.py", "content_sha256": helper_content,
            "review_basis": "INSPECTED_NO_IDENTITY_OPERATION",
        }],
    }
    merged = merge_adjudication_lanes(
        [(consumer_scope, _bytes(consumer_lane)), ("helper", _bytes(helper_lane))], source
    )
    assert [row["line"] for row in merged["consumer_rows"]] == [1, 3]
    assert merged["coverage"] == {
        "source_executable_rows": 3,
        "reviewed_consumer_rows": 2,
        "reviewed_nonconsumer_rows": 1,
        "unresolved_executable_rows": 0,
        "duplicate_dispositions": 0,
    }
    assert merged["lanes"] == [
        {"scope": "helper", "sha256": hashlib.sha256(_bytes(helper_lane)).hexdigest()},
        {"scope": consumer_scope, "sha256": hashlib.sha256(_bytes(consumer_lane)).hexdigest()},
    ]


def test_merge_rejects_a_line_selector_absent_from_the_source() -> None:
    digest = "b" * 64
    source = {
        "roots": [{"root_id": "public-master", "source_commit": SOURCE_COMMIT}],
        "evidence": [{
            "path": "runtime.py", "line": 1, "category": "checkpoint_save_load",
            "line_sha256": digest, "content_sha256": "c" * 64,
            "evidence_scope": "LINE", "source_role": "EXECUTABLE_CANDIDATE",
        }],
    }
    row = {**_consumer("runtime.py", digest), "line": 2}
    lane = {
        "schema": "ember-consumer-adjudication-review-v1",
        "source_commit": SOURCE_COMMIT,
        "scope": "runtime",
        "coverage": {},
        "consumer_rows": [row], "nonconsumer_rows": [], "nonconsumer_files": [],
    }
    with pytest.raises(ValueError, match="absent from source"):
        merge_adjudication_lanes([("runtime", _bytes(lane))], source)


def test_merge_preserves_verified_consumer_and_drops_lane_nonconsumer_override() -> None:
    digest = "b" * 64
    source = {
        "roots": [{"root_id": "public-master", "source_commit": SOURCE_COMMIT}],
        "evidence": [{
            "path": "runtime.py", "line": 1, "category": "checkpoint_save_load",
            "line_sha256": digest, "content_sha256": "c" * 64,
            "evidence_scope": "LINE", "source_role": "EXECUTABLE_CANDIDATE",
            "record_class": "VERIFIED_CONSUMER",
        }],
    }
    lane = {
        "schema": "ember-consumer-adjudication-review-v1",
        "source_commit": SOURCE_COMMIT,
        "scope": "runtime",
        "coverage": {},
        "consumer_rows": [],
        "nonconsumer_rows": [{
            "path": "runtime.py", "line": 1, "category": "checkpoint_save_load",
            "evidence_sha256": digest, "review_basis": "INCORRECT_LANE_OVERRIDE",
        }],
        "nonconsumer_files": [],
    }
    merged = merge_adjudication_lanes([("runtime", _bytes(lane))], source)
    assert merged["consumer_rows"] == []
    assert merged["nonconsumer_rows"] == []
    assert merged["coverage"]["reviewed_consumer_rows"] == 1
    assert merged["coverage"]["reviewed_nonconsumer_rows"] == 0
