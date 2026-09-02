# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import copy
import hashlib
import json
import re
from pathlib import Path


EXECUTION_RECEIPT = Path(__file__).parents[1] / "receipts" / "lifecycle-census" / "ember-inherited-drawdown-002-execution-v1.json"
MANIFEST = Path(__file__).parents[1] / "receipts" / "lifecycle-census" / "ember-inherited-drawdown-002-keep-manifest-v2.json"


def _load() -> dict:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    canonical = dict(payload)
    recorded = canonical.pop("manifest_sha256")
    assert recorded == hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return payload


def _rehashed(payload: dict) -> dict:
    canonical = dict(payload)
    canonical.pop("manifest_sha256", None)
    payload["manifest_sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return payload


def _valid_delete_row(payload: dict) -> dict:
    row = copy.deepcopy(payload["candidates"][0])
    row["verdict"] = "DELETE_VERIFIED"
    row["protection"] = False
    row["open_head_prs"] = []
    row["path_diff_blob_equivalence"] = {
        "status": "PROVEN_EXACT",
        "paths": ["receipts/example.json"],
        "terminal_blobs": {"receipts/example.json": "a" * 40},
    }
    return row


def test_manifest_has_no_delete_rows_and_preserves_divergent_edge_case() -> None:
    payload = _load()
    assert payload["deletion_authority"] == "NOT_GRANTED"
    assert payload["mutation_performed"] is False
    assert payload["candidate_count"] == len(payload["candidates"]) == 15
    assert all(row["verdict"].startswith("KEEP_") for row in payload["candidates"])
    edge = payload["independent_custody_edge_case"]
    assert edge["pr_state"] == "MERGED"
    assert edge["open_head_prs"] == []
    assert edge["protection"] is False
    assert edge["path_diff_blob_equivalence"] == "NOT_PROVEN"
    assert edge["verdict"] == "KEEP_UNCERTAIN_BRANCH_UNIQUE_OR_DIVERGED"
    assert edge["master_compare"]["status"] == "diverged"


def test_manifest_registered_worktrees_are_path_free_and_typed() -> None:
    registered = _load()["registered_worktrees"]
    assert registered["count"] == len(registered["entries"]) == 2
    assert registered["deletion_authority"] == "NOT_GRANTED"
    assert re.fullmatch(r"[0-9a-f]{64}", registered["porcelain_sha256"])
    for entry in registered["entries"]:
        assert re.fullmatch(r"[0-9a-f]{40}", entry["head_sha"])
        assert re.fullmatch(r"[0-9a-f]{64}", entry["path_sha256"])
        assert re.fullmatch(r"[0-9a-f]{64}", entry["common_repo_path_sha256"])
        assert entry["dirty"] is False
        assert entry["verdict"] == "KEEP_ACTIVE_OR_BASE"


def test_manifest_verifier_selects_no_uncertain_delete_rows() -> None:
    # issue2015 exact-local-import:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py
    import importlib.util as _ember_69579b8a05a17b07_importlib
    import sys as _ember_69579b8a05a17b07_sys
    from pathlib import Path as _ember_69579b8a05a17b07_Path
    _ember_69579b8a05a17b07_path = _ember_69579b8a05a17b07_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'verify_lifecycle_drawdown_manifest.py')
    if not _ember_69579b8a05a17b07_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    _ember_69579b8a05a17b07_aliases = ('_ember_issue2015_69579b8a05a17b07', 'scripts.verify_lifecycle_drawdown_manifest', 'src.ember.governance.scripts.verify_lifecycle_drawdown_manifest', 'verify_lifecycle_drawdown_manifest')
    _ember_69579b8a05a17b07_existing = []
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_candidate = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_candidate is not None and all(_ember_69579b8a05a17b07_candidate is not item for item in _ember_69579b8a05a17b07_existing):
            _ember_69579b8a05a17b07_existing.append(_ember_69579b8a05a17b07_candidate)
    if len(_ember_69579b8a05a17b07_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    if _ember_69579b8a05a17b07_existing:
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_existing[0]
        _ember_69579b8a05a17b07_observed = getattr(_ember_69579b8a05a17b07_module, '__file__', None)
        if _ember_69579b8a05a17b07_observed is None or _ember_69579b8a05a17b07_Path(_ember_69579b8a05a17b07_observed).resolve() != _ember_69579b8a05a17b07_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    else:
        _ember_69579b8a05a17b07_spec = _ember_69579b8a05a17b07_importlib.spec_from_file_location('_ember_issue2015_69579b8a05a17b07', _ember_69579b8a05a17b07_path)
        if _ember_69579b8a05a17b07_spec is None or _ember_69579b8a05a17b07_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_importlib.module_from_spec(_ember_69579b8a05a17b07_spec)
        for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
            _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
            if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
            _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
        try:
            _ember_69579b8a05a17b07_spec.loader.exec_module(_ember_69579b8a05a17b07_module)
        except BaseException:
            for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
                if _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias) is _ember_69579b8a05a17b07_module:
                    _ember_69579b8a05a17b07_sys.modules.pop(_ember_69579b8a05a17b07_alias, None)
            raise
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
    verified_delete_rows = getattr(_ember_69579b8a05a17b07_module, 'verified_delete_rows')
    verify_manifest = getattr(_ember_69579b8a05a17b07_module, 'verify_manifest')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py

    payload = _load()
    verify_manifest(payload)
    assert verified_delete_rows(payload) == []


def test_manifest_verifier_rejects_uncertain_row_marked_for_deletion() -> None:
    # issue2015 exact-local-import:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py
    import importlib.util as _ember_69579b8a05a17b07_importlib
    import sys as _ember_69579b8a05a17b07_sys
    from pathlib import Path as _ember_69579b8a05a17b07_Path
    _ember_69579b8a05a17b07_path = _ember_69579b8a05a17b07_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'verify_lifecycle_drawdown_manifest.py')
    if not _ember_69579b8a05a17b07_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    _ember_69579b8a05a17b07_aliases = ('_ember_issue2015_69579b8a05a17b07', 'scripts.verify_lifecycle_drawdown_manifest', 'src.ember.governance.scripts.verify_lifecycle_drawdown_manifest', 'verify_lifecycle_drawdown_manifest')
    _ember_69579b8a05a17b07_existing = []
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_candidate = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_candidate is not None and all(_ember_69579b8a05a17b07_candidate is not item for item in _ember_69579b8a05a17b07_existing):
            _ember_69579b8a05a17b07_existing.append(_ember_69579b8a05a17b07_candidate)
    if len(_ember_69579b8a05a17b07_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    if _ember_69579b8a05a17b07_existing:
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_existing[0]
        _ember_69579b8a05a17b07_observed = getattr(_ember_69579b8a05a17b07_module, '__file__', None)
        if _ember_69579b8a05a17b07_observed is None or _ember_69579b8a05a17b07_Path(_ember_69579b8a05a17b07_observed).resolve() != _ember_69579b8a05a17b07_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    else:
        _ember_69579b8a05a17b07_spec = _ember_69579b8a05a17b07_importlib.spec_from_file_location('_ember_issue2015_69579b8a05a17b07', _ember_69579b8a05a17b07_path)
        if _ember_69579b8a05a17b07_spec is None or _ember_69579b8a05a17b07_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_importlib.module_from_spec(_ember_69579b8a05a17b07_spec)
        for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
            _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
            if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
            _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
        try:
            _ember_69579b8a05a17b07_spec.loader.exec_module(_ember_69579b8a05a17b07_module)
        except BaseException:
            for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
                if _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias) is _ember_69579b8a05a17b07_module:
                    _ember_69579b8a05a17b07_sys.modules.pop(_ember_69579b8a05a17b07_alias, None)
            raise
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
    ManifestError = getattr(_ember_69579b8a05a17b07_module, 'ManifestError')
    verified_delete_rows = getattr(_ember_69579b8a05a17b07_module, 'verified_delete_rows')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py

    payload = _load()
    tampered = copy.deepcopy(payload)
    tampered["candidates"][0]["verdict"] = "DELETE_VERIFIED"
    canonical = dict(tampered)
    canonical.pop("manifest_sha256")
    tampered["manifest_sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    with __import__("pytest").raises(ManifestError, match="DELETE_VERIFIED"):
        verified_delete_rows(tampered)


def test_manifest_verifier_rejects_delete_row_under_not_granted_authority() -> None:
    # issue2015 exact-local-import:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py
    import importlib.util as _ember_69579b8a05a17b07_importlib
    import sys as _ember_69579b8a05a17b07_sys
    from pathlib import Path as _ember_69579b8a05a17b07_Path
    _ember_69579b8a05a17b07_path = _ember_69579b8a05a17b07_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'verify_lifecycle_drawdown_manifest.py')
    if not _ember_69579b8a05a17b07_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    _ember_69579b8a05a17b07_aliases = ('_ember_issue2015_69579b8a05a17b07', 'scripts.verify_lifecycle_drawdown_manifest', 'src.ember.governance.scripts.verify_lifecycle_drawdown_manifest', 'verify_lifecycle_drawdown_manifest')
    _ember_69579b8a05a17b07_existing = []
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_candidate = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_candidate is not None and all(_ember_69579b8a05a17b07_candidate is not item for item in _ember_69579b8a05a17b07_existing):
            _ember_69579b8a05a17b07_existing.append(_ember_69579b8a05a17b07_candidate)
    if len(_ember_69579b8a05a17b07_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    if _ember_69579b8a05a17b07_existing:
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_existing[0]
        _ember_69579b8a05a17b07_observed = getattr(_ember_69579b8a05a17b07_module, '__file__', None)
        if _ember_69579b8a05a17b07_observed is None or _ember_69579b8a05a17b07_Path(_ember_69579b8a05a17b07_observed).resolve() != _ember_69579b8a05a17b07_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    else:
        _ember_69579b8a05a17b07_spec = _ember_69579b8a05a17b07_importlib.spec_from_file_location('_ember_issue2015_69579b8a05a17b07', _ember_69579b8a05a17b07_path)
        if _ember_69579b8a05a17b07_spec is None or _ember_69579b8a05a17b07_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_importlib.module_from_spec(_ember_69579b8a05a17b07_spec)
        for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
            _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
            if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
            _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
        try:
            _ember_69579b8a05a17b07_spec.loader.exec_module(_ember_69579b8a05a17b07_module)
        except BaseException:
            for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
                if _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias) is _ember_69579b8a05a17b07_module:
                    _ember_69579b8a05a17b07_sys.modules.pop(_ember_69579b8a05a17b07_alias, None)
            raise
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
    ManifestError = getattr(_ember_69579b8a05a17b07_module, 'ManifestError')
    verified_delete_rows = getattr(_ember_69579b8a05a17b07_module, 'verified_delete_rows')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py

    tampered = copy.deepcopy(_load())
    tampered["candidates"][0] = _valid_delete_row(tampered)
    tampered = _rehashed(tampered)
    with __import__("pytest").raises(ManifestError, match="DELETE_VERIFIED"):
        verified_delete_rows(tampered)


def test_manifest_verifier_rejects_granted_authority_in_structural_verifier() -> None:
    # issue2015 exact-local-import:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py
    import importlib.util as _ember_69579b8a05a17b07_importlib
    import sys as _ember_69579b8a05a17b07_sys
    from pathlib import Path as _ember_69579b8a05a17b07_Path
    _ember_69579b8a05a17b07_path = _ember_69579b8a05a17b07_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'verify_lifecycle_drawdown_manifest.py')
    if not _ember_69579b8a05a17b07_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    _ember_69579b8a05a17b07_aliases = ('_ember_issue2015_69579b8a05a17b07', 'scripts.verify_lifecycle_drawdown_manifest', 'src.ember.governance.scripts.verify_lifecycle_drawdown_manifest', 'verify_lifecycle_drawdown_manifest')
    _ember_69579b8a05a17b07_existing = []
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_candidate = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_candidate is not None and all(_ember_69579b8a05a17b07_candidate is not item for item in _ember_69579b8a05a17b07_existing):
            _ember_69579b8a05a17b07_existing.append(_ember_69579b8a05a17b07_candidate)
    if len(_ember_69579b8a05a17b07_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    if _ember_69579b8a05a17b07_existing:
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_existing[0]
        _ember_69579b8a05a17b07_observed = getattr(_ember_69579b8a05a17b07_module, '__file__', None)
        if _ember_69579b8a05a17b07_observed is None or _ember_69579b8a05a17b07_Path(_ember_69579b8a05a17b07_observed).resolve() != _ember_69579b8a05a17b07_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    else:
        _ember_69579b8a05a17b07_spec = _ember_69579b8a05a17b07_importlib.spec_from_file_location('_ember_issue2015_69579b8a05a17b07', _ember_69579b8a05a17b07_path)
        if _ember_69579b8a05a17b07_spec is None or _ember_69579b8a05a17b07_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_importlib.module_from_spec(_ember_69579b8a05a17b07_spec)
        for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
            _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
            if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
            _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
        try:
            _ember_69579b8a05a17b07_spec.loader.exec_module(_ember_69579b8a05a17b07_module)
        except BaseException:
            for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
                if _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias) is _ember_69579b8a05a17b07_module:
                    _ember_69579b8a05a17b07_sys.modules.pop(_ember_69579b8a05a17b07_alias, None)
            raise
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
    ManifestError = getattr(_ember_69579b8a05a17b07_module, 'ManifestError')
    verified_delete_rows = getattr(_ember_69579b8a05a17b07_module, 'verified_delete_rows')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py

    tampered = copy.deepcopy(_load())
    tampered["deletion_authority"] = "GRANTED_EXACT_ROWS"
    tampered = _rehashed(tampered)
    with __import__("pytest").raises(ManifestError, match="NOT_GRANTED"):
        verified_delete_rows(tampered)


def test_manifest_verifier_rejects_duplicate_candidate_refs() -> None:
    # issue2015 exact-local-import:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py
    import importlib.util as _ember_69579b8a05a17b07_importlib
    import sys as _ember_69579b8a05a17b07_sys
    from pathlib import Path as _ember_69579b8a05a17b07_Path
    _ember_69579b8a05a17b07_path = _ember_69579b8a05a17b07_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'verify_lifecycle_drawdown_manifest.py')
    if not _ember_69579b8a05a17b07_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    _ember_69579b8a05a17b07_aliases = ('_ember_issue2015_69579b8a05a17b07', 'scripts.verify_lifecycle_drawdown_manifest', 'src.ember.governance.scripts.verify_lifecycle_drawdown_manifest', 'verify_lifecycle_drawdown_manifest')
    _ember_69579b8a05a17b07_existing = []
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_candidate = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_candidate is not None and all(_ember_69579b8a05a17b07_candidate is not item for item in _ember_69579b8a05a17b07_existing):
            _ember_69579b8a05a17b07_existing.append(_ember_69579b8a05a17b07_candidate)
    if len(_ember_69579b8a05a17b07_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    if _ember_69579b8a05a17b07_existing:
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_existing[0]
        _ember_69579b8a05a17b07_observed = getattr(_ember_69579b8a05a17b07_module, '__file__', None)
        if _ember_69579b8a05a17b07_observed is None or _ember_69579b8a05a17b07_Path(_ember_69579b8a05a17b07_observed).resolve() != _ember_69579b8a05a17b07_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    else:
        _ember_69579b8a05a17b07_spec = _ember_69579b8a05a17b07_importlib.spec_from_file_location('_ember_issue2015_69579b8a05a17b07', _ember_69579b8a05a17b07_path)
        if _ember_69579b8a05a17b07_spec is None or _ember_69579b8a05a17b07_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_importlib.module_from_spec(_ember_69579b8a05a17b07_spec)
        for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
            _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
            if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
            _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
        try:
            _ember_69579b8a05a17b07_spec.loader.exec_module(_ember_69579b8a05a17b07_module)
        except BaseException:
            for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
                if _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias) is _ember_69579b8a05a17b07_module:
                    _ember_69579b8a05a17b07_sys.modules.pop(_ember_69579b8a05a17b07_alias, None)
            raise
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
    ManifestError = getattr(_ember_69579b8a05a17b07_module, 'ManifestError')
    verify_manifest = getattr(_ember_69579b8a05a17b07_module, 'verify_manifest')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py

    for duplicate in ("KEEP_KEEP", "KEEP_DELETE"):
        tampered = copy.deepcopy(_load())
        duplicate_row = copy.deepcopy(tampered["candidates"][0])
        if duplicate == "KEEP_DELETE":
            duplicate_row = _valid_delete_row(tampered)
        tampered["candidates"].append(duplicate_row)
        tampered["candidate_count"] = len(tampered["candidates"])
        tampered = _rehashed(tampered)
        with __import__("pytest").raises(ManifestError, match="duplicate candidate ref"):
            verify_manifest(tampered)


def test_manifest_verifier_rejects_more_than_25_candidates() -> None:
    # issue2015 exact-local-import:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py
    import importlib.util as _ember_69579b8a05a17b07_importlib
    import sys as _ember_69579b8a05a17b07_sys
    from pathlib import Path as _ember_69579b8a05a17b07_Path
    _ember_69579b8a05a17b07_path = _ember_69579b8a05a17b07_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'verify_lifecycle_drawdown_manifest.py')
    if not _ember_69579b8a05a17b07_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    _ember_69579b8a05a17b07_aliases = ('_ember_issue2015_69579b8a05a17b07', 'scripts.verify_lifecycle_drawdown_manifest', 'src.ember.governance.scripts.verify_lifecycle_drawdown_manifest', 'verify_lifecycle_drawdown_manifest')
    _ember_69579b8a05a17b07_existing = []
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_candidate = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_candidate is not None and all(_ember_69579b8a05a17b07_candidate is not item for item in _ember_69579b8a05a17b07_existing):
            _ember_69579b8a05a17b07_existing.append(_ember_69579b8a05a17b07_candidate)
    if len(_ember_69579b8a05a17b07_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    if _ember_69579b8a05a17b07_existing:
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_existing[0]
        _ember_69579b8a05a17b07_observed = getattr(_ember_69579b8a05a17b07_module, '__file__', None)
        if _ember_69579b8a05a17b07_observed is None or _ember_69579b8a05a17b07_Path(_ember_69579b8a05a17b07_observed).resolve() != _ember_69579b8a05a17b07_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    else:
        _ember_69579b8a05a17b07_spec = _ember_69579b8a05a17b07_importlib.spec_from_file_location('_ember_issue2015_69579b8a05a17b07', _ember_69579b8a05a17b07_path)
        if _ember_69579b8a05a17b07_spec is None or _ember_69579b8a05a17b07_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_importlib.module_from_spec(_ember_69579b8a05a17b07_spec)
        for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
            _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
            if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
            _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
        try:
            _ember_69579b8a05a17b07_spec.loader.exec_module(_ember_69579b8a05a17b07_module)
        except BaseException:
            for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
                if _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias) is _ember_69579b8a05a17b07_module:
                    _ember_69579b8a05a17b07_sys.modules.pop(_ember_69579b8a05a17b07_alias, None)
            raise
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
    ManifestError = getattr(_ember_69579b8a05a17b07_module, 'ManifestError')
    verify_manifest = getattr(_ember_69579b8a05a17b07_module, 'verify_manifest')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py

    tampered = copy.deepcopy(_load())
    for index in range(11):
        row = copy.deepcopy(tampered["candidates"][0])
        row["ref"] = f"refs/heads/synthetic-wave003-{index}"
        tampered["candidates"].append(row)
    tampered["candidate_count"] = len(tampered["candidates"])
    tampered = _rehashed(tampered)
    with __import__("pytest").raises(ManifestError, match="at most 25"):
        verify_manifest(tampered)


def test_execution_receipt_is_canonical_noop_and_binds_manifest() -> None:
    receipt = json.loads(EXECUTION_RECEIPT.read_text(encoding="utf-8"))
    canonical = dict(receipt)
    recorded = canonical.pop("receipt_sha256")
    assert recorded == hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert receipt["decision"] == {
        "candidate_count": 15,
        "deletion_authority": "NOT_GRANTED",
        "mutation_performed": False,
        "verified_delete_count": 0,
    }
    assert receipt["manifest"]["manifest_sha256"] == _load()["manifest_sha256"]
    assert receipt["before"]["remote_branch_count"] == 77
    assert receipt["after"]["remote_branch_count"] == 78
    assert "not attributed" in receipt["interpretation"]


def test_manifest_verifier_rejects_path_traversal_ref() -> None:
    # issue2015 exact-local-import:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py
    import importlib.util as _ember_69579b8a05a17b07_importlib
    import sys as _ember_69579b8a05a17b07_sys
    from pathlib import Path as _ember_69579b8a05a17b07_Path
    _ember_69579b8a05a17b07_path = _ember_69579b8a05a17b07_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'verify_lifecycle_drawdown_manifest.py')
    if not _ember_69579b8a05a17b07_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    _ember_69579b8a05a17b07_aliases = ('_ember_issue2015_69579b8a05a17b07', 'scripts.verify_lifecycle_drawdown_manifest', 'src.ember.governance.scripts.verify_lifecycle_drawdown_manifest', 'verify_lifecycle_drawdown_manifest')
    _ember_69579b8a05a17b07_existing = []
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_candidate = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_candidate is not None and all(_ember_69579b8a05a17b07_candidate is not item for item in _ember_69579b8a05a17b07_existing):
            _ember_69579b8a05a17b07_existing.append(_ember_69579b8a05a17b07_candidate)
    if len(_ember_69579b8a05a17b07_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    if _ember_69579b8a05a17b07_existing:
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_existing[0]
        _ember_69579b8a05a17b07_observed = getattr(_ember_69579b8a05a17b07_module, '__file__', None)
        if _ember_69579b8a05a17b07_observed is None or _ember_69579b8a05a17b07_Path(_ember_69579b8a05a17b07_observed).resolve() != _ember_69579b8a05a17b07_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
    else:
        _ember_69579b8a05a17b07_spec = _ember_69579b8a05a17b07_importlib.spec_from_file_location('_ember_issue2015_69579b8a05a17b07', _ember_69579b8a05a17b07_path)
        if _ember_69579b8a05a17b07_spec is None or _ember_69579b8a05a17b07_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_module = _ember_69579b8a05a17b07_importlib.module_from_spec(_ember_69579b8a05a17b07_spec)
        for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
            _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
            if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
            _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
        try:
            _ember_69579b8a05a17b07_spec.loader.exec_module(_ember_69579b8a05a17b07_module)
        except BaseException:
            for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
                if _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias) is _ember_69579b8a05a17b07_module:
                    _ember_69579b8a05a17b07_sys.modules.pop(_ember_69579b8a05a17b07_alias, None)
            raise
    for _ember_69579b8a05a17b07_alias in _ember_69579b8a05a17b07_aliases:
        _ember_69579b8a05a17b07_prior = _ember_69579b8a05a17b07_sys.modules.get(_ember_69579b8a05a17b07_alias)
        if _ember_69579b8a05a17b07_prior is not None and _ember_69579b8a05a17b07_prior is not _ember_69579b8a05a17b07_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py')
        _ember_69579b8a05a17b07_sys.modules[_ember_69579b8a05a17b07_alias] = _ember_69579b8a05a17b07_module
    ManifestError = getattr(_ember_69579b8a05a17b07_module, 'ManifestError')
    verify_manifest = getattr(_ember_69579b8a05a17b07_module, 'verify_manifest')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/verify_lifecycle_drawdown_manifest.py

    tampered = copy.deepcopy(_load())
    tampered["candidates"][0]["ref"] = "refs/heads/../unsafe"
    canonical = dict(tampered)
    canonical.pop("manifest_sha256")
    tampered["manifest_sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    with __import__("pytest").raises(ManifestError, match="safe full head ref"):
        verify_manifest(tampered)
