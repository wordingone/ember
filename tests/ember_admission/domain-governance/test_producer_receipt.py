# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Path-free, content-addressed producer receipt coverage."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
PRODUCER_ROOT = REPO_ROOT / "scripts" / "ember_admission"
sys.path.insert(0, str(PRODUCER_ROOT))

# issue2015 exact-local-import:src/ember/governance/scripts/ember_admission/consumers.py
import importlib.util as _ember_348d9831f4671543_importlib
import sys as _ember_348d9831f4671543_sys
from pathlib import Path as _ember_348d9831f4671543_Path
_ember_348d9831f4671543_path = _ember_348d9831f4671543_Path(__file__).resolve().parents[3].joinpath('src', 'ember', 'governance', 'scripts', 'ember_admission', 'consumers.py')
if not _ember_348d9831f4671543_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_admission/consumers.py')
_ember_348d9831f4671543_aliases = ('_ember_issue2015_348d9831f4671543', 'consumers', 'scripts.ember_admission.consumers', 'src.ember.governance.scripts.ember_admission.consumers')
_ember_348d9831f4671543_existing = []
for _ember_348d9831f4671543_alias in _ember_348d9831f4671543_aliases:
    _ember_348d9831f4671543_candidate = _ember_348d9831f4671543_sys.modules.get(_ember_348d9831f4671543_alias)
    if _ember_348d9831f4671543_candidate is not None and all(_ember_348d9831f4671543_candidate is not item for item in _ember_348d9831f4671543_existing):
        _ember_348d9831f4671543_existing.append(_ember_348d9831f4671543_candidate)
if len(_ember_348d9831f4671543_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_admission/consumers.py')
if _ember_348d9831f4671543_existing:
    _ember_348d9831f4671543_module = _ember_348d9831f4671543_existing[0]
    _ember_348d9831f4671543_observed = getattr(_ember_348d9831f4671543_module, '__file__', None)
    if _ember_348d9831f4671543_observed is None or _ember_348d9831f4671543_Path(_ember_348d9831f4671543_observed).resolve() != _ember_348d9831f4671543_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_admission/consumers.py')
else:
    _ember_348d9831f4671543_spec = _ember_348d9831f4671543_importlib.spec_from_file_location('_ember_issue2015_348d9831f4671543', _ember_348d9831f4671543_path)
    if _ember_348d9831f4671543_spec is None or _ember_348d9831f4671543_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_admission/consumers.py')
    _ember_348d9831f4671543_module = _ember_348d9831f4671543_importlib.module_from_spec(_ember_348d9831f4671543_spec)
    for _ember_348d9831f4671543_alias in _ember_348d9831f4671543_aliases:
        _ember_348d9831f4671543_prior = _ember_348d9831f4671543_sys.modules.get(_ember_348d9831f4671543_alias)
        if _ember_348d9831f4671543_prior is not None and _ember_348d9831f4671543_prior is not _ember_348d9831f4671543_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_admission/consumers.py')
        _ember_348d9831f4671543_sys.modules[_ember_348d9831f4671543_alias] = _ember_348d9831f4671543_module
    try:
        _ember_348d9831f4671543_spec.loader.exec_module(_ember_348d9831f4671543_module)
    except BaseException:
        for _ember_348d9831f4671543_alias in _ember_348d9831f4671543_aliases:
            if _ember_348d9831f4671543_sys.modules.get(_ember_348d9831f4671543_alias) is _ember_348d9831f4671543_module:
                _ember_348d9831f4671543_sys.modules.pop(_ember_348d9831f4671543_alias, None)
        raise
for _ember_348d9831f4671543_alias in _ember_348d9831f4671543_aliases:
    _ember_348d9831f4671543_prior = _ember_348d9831f4671543_sys.modules.get(_ember_348d9831f4671543_alias)
    if _ember_348d9831f4671543_prior is not None and _ember_348d9831f4671543_prior is not _ember_348d9831f4671543_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_admission/consumers.py')
    _ember_348d9831f4671543_sys.modules[_ember_348d9831f4671543_alias] = _ember_348d9831f4671543_module
CONSUMER_COMMAND_CONTRACTS = getattr(_ember_348d9831f4671543_module, 'CONSUMER_COMMAND_CONTRACTS')
CONSUMER_ENTRYPOINTS = getattr(_ember_348d9831f4671543_module, 'CONSUMER_ENTRYPOINTS')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_admission/consumers.py
# issue2015 exact-local-import:src/ember/governance/scripts/ember_admission/receipt.py
import importlib.util as _ember_a9df580263ecd856_importlib
import sys as _ember_a9df580263ecd856_sys
from pathlib import Path as _ember_a9df580263ecd856_Path
_ember_a9df580263ecd856_path = _ember_a9df580263ecd856_Path(__file__).resolve().parents[3].joinpath('src', 'ember', 'governance', 'scripts', 'ember_admission', 'receipt.py')
if not _ember_a9df580263ecd856_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_admission/receipt.py')
_ember_a9df580263ecd856_aliases = ('_ember_issue2015_a9df580263ecd856', 'receipt', 'scripts.ember_admission.receipt', 'src.ember.governance.scripts.ember_admission.receipt')
_ember_a9df580263ecd856_existing = []
for _ember_a9df580263ecd856_alias in _ember_a9df580263ecd856_aliases:
    _ember_a9df580263ecd856_candidate = _ember_a9df580263ecd856_sys.modules.get(_ember_a9df580263ecd856_alias)
    if _ember_a9df580263ecd856_candidate is not None and all(_ember_a9df580263ecd856_candidate is not item for item in _ember_a9df580263ecd856_existing):
        _ember_a9df580263ecd856_existing.append(_ember_a9df580263ecd856_candidate)
if len(_ember_a9df580263ecd856_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_admission/receipt.py')
if _ember_a9df580263ecd856_existing:
    _ember_a9df580263ecd856_module = _ember_a9df580263ecd856_existing[0]
    _ember_a9df580263ecd856_observed = getattr(_ember_a9df580263ecd856_module, '__file__', None)
    if _ember_a9df580263ecd856_observed is None or _ember_a9df580263ecd856_Path(_ember_a9df580263ecd856_observed).resolve() != _ember_a9df580263ecd856_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_admission/receipt.py')
else:
    _ember_a9df580263ecd856_spec = _ember_a9df580263ecd856_importlib.spec_from_file_location('_ember_issue2015_a9df580263ecd856', _ember_a9df580263ecd856_path)
    if _ember_a9df580263ecd856_spec is None or _ember_a9df580263ecd856_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_admission/receipt.py')
    _ember_a9df580263ecd856_module = _ember_a9df580263ecd856_importlib.module_from_spec(_ember_a9df580263ecd856_spec)
    for _ember_a9df580263ecd856_alias in _ember_a9df580263ecd856_aliases:
        _ember_a9df580263ecd856_prior = _ember_a9df580263ecd856_sys.modules.get(_ember_a9df580263ecd856_alias)
        if _ember_a9df580263ecd856_prior is not None and _ember_a9df580263ecd856_prior is not _ember_a9df580263ecd856_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_admission/receipt.py')
        _ember_a9df580263ecd856_sys.modules[_ember_a9df580263ecd856_alias] = _ember_a9df580263ecd856_module
    try:
        _ember_a9df580263ecd856_spec.loader.exec_module(_ember_a9df580263ecd856_module)
    except BaseException:
        for _ember_a9df580263ecd856_alias in _ember_a9df580263ecd856_aliases:
            if _ember_a9df580263ecd856_sys.modules.get(_ember_a9df580263ecd856_alias) is _ember_a9df580263ecd856_module:
                _ember_a9df580263ecd856_sys.modules.pop(_ember_a9df580263ecd856_alias, None)
        raise
for _ember_a9df580263ecd856_alias in _ember_a9df580263ecd856_aliases:
    _ember_a9df580263ecd856_prior = _ember_a9df580263ecd856_sys.modules.get(_ember_a9df580263ecd856_alias)
    if _ember_a9df580263ecd856_prior is not None and _ember_a9df580263ecd856_prior is not _ember_a9df580263ecd856_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_admission/receipt.py')
    _ember_a9df580263ecd856_sys.modules[_ember_a9df580263ecd856_alias] = _ember_a9df580263ecd856_module
verify_producer_receipt = getattr(_ember_a9df580263ecd856_module, 'verify_producer_receipt')
write_producer_receipt = getattr(_ember_a9df580263ecd856_module, 'write_producer_receipt')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_admission/receipt.py
from source_snapshot import SourceSnapshot  # noqa: E402

def _validator_closure(name: str, digest: str) -> dict[str, dict[str, object]]:
    relative = CONSUMER_ENTRYPOINTS[name]
    return {
        relative: {"relative_path": relative, "sha256": digest, "bytes": 1}
    }



def _descriptor_snapshot() -> SourceSnapshot:
    content = b'{"schema_version":"ember-owned-admission-input-v1"}\n'
    return SourceSnapshot(
        role="input_descriptor",
        relative_path="admission.json",
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


def _materialize_outputs(
    candidate: Path,
    snapshots: dict[str, SourceSnapshot],
) -> None:
    for snapshot in snapshots.values():
        path = candidate / snapshot.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(snapshot.content)


def test_receipt_is_content_addressed_and_discloses_no_host_path(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    snapshots = {
        "checkpoint": SourceSnapshot(
            role="checkpoint",
            relative_path="checkpoint.bin",
            sha256=hashlib.sha256(b"checkpoint").hexdigest(),
            content=b"checkpoint",
        ),
        "restart_model_config": SourceSnapshot(
            role="restart_model_config",
            relative_path="config.json",
            sha256=hashlib.sha256(b"{}").hexdigest(),
            content=b"{}",
        ),
    }
    descriptor_snapshot = _descriptor_snapshot()
    _materialize_outputs(candidate, snapshots)

    result = write_producer_receipt(
        candidate,
        "candidate-one",
        descriptor_snapshot,
        snapshots,
        {
            "identity": {
                "accepted": True,
                "command": list(CONSUMER_COMMAND_CONTRACTS["identity"]),
                "returncode": 0,
                "stdout_sha256": "3" * 64,
                "validator_sha256": "1" * 64,
                "validator_closure": _validator_closure("identity", "1" * 64),
            },
            "restart": {
                "accepted": True,
                "command": list(CONSUMER_COMMAND_CONTRACTS["restart"]),
                "returncode": 0,
                "stdout_sha256": "4" * 64,
                "validator_sha256": "2" * 64,
                "validator_closure": _validator_closure("restart", "2" * 64),
            },
        },
    )

    receipt_path = candidate / "producer-receipts" / f"{result.receipt_sha256}.json"
    receipt_bytes = receipt_path.read_bytes()
    payload = json.loads(receipt_bytes)
    assert hashlib.sha256(receipt_bytes).hexdigest() == result.receipt_sha256
    assert payload["selected"] is False
    assert payload["loaded"] is False
    assert payload["training_started"] is False
    assert payload["claim_boundary"] == [
        "candidate_produced",
        "identity_consumer_accepted",
        "restart_consumer_accepted",
    ]
    assert payload["consumers"]["identity"]["command"] == list(
        CONSUMER_COMMAND_CONTRACTS["identity"]
    )
    assert str(tmp_path) not in receipt_bytes.decode("utf-8")
    assert payload["source_identities"]["descriptor"] == {
        "relative_path": "admission.json",
        "sha256": descriptor_snapshot.sha256,
        "bytes": len(descriptor_snapshot.content),
    }
    assert payload["output_identities"]["checkpoint"]["relative_path"] == "checkpoint.bin"
    assert result.candidate_sha256 == hashlib.sha256(
        json.dumps(
            {
                "producer_receipt_sha256": result.receipt_sha256,
                "descriptor_identity": payload["source_identities"]["descriptor"],
                "output_identities": payload["output_identities"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def test_receipt_refuses_nonzero_or_malformed_consumer_authority(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    snapshots = {
        "checkpoint": SourceSnapshot(
            role="checkpoint",
            relative_path="checkpoint.bin",
            sha256=hashlib.sha256(b"checkpoint").hexdigest(),
            content=b"checkpoint",
        )
    }
    _materialize_outputs(candidate, snapshots)
    try:
        write_producer_receipt(
            candidate,
            "candidate-one",
            _descriptor_snapshot(),
            snapshots,
            {
                "identity": {
                    "accepted": True,
                    "returncode": 0,
                    "command": list(CONSUMER_COMMAND_CONTRACTS["identity"]),
                    "stdout_sha256": "3" * 64,
                    "validator_sha256": "1" * 64,
                    "validator_closure": _validator_closure("identity", "1" * 64),
                },
                "restart": {
                    "accepted": True,
                    "returncode": 1,
                    "validator_sha256": "2" * 64,
                    "validator_closure": _validator_closure("restart", "2" * 64),
                    "command": list(CONSUMER_COMMAND_CONTRACTS["restart"]),
                    "stdout_sha256": "4" * 64,
                },
            },
        )
    except ValueError as exc:
        assert str(exc) == "receipt.consumers"
    else:
        raise AssertionError("nonzero consumer result was accepted")


def test_written_receipt_drift_is_detected(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    snapshots = {
        "checkpoint": SourceSnapshot(
            role="checkpoint",
            relative_path="checkpoint.bin",
            sha256=hashlib.sha256(b"checkpoint").hexdigest(),
            content=b"checkpoint",
        )
    }
    _materialize_outputs(candidate, snapshots)
    result = write_producer_receipt(
        candidate,
        "candidate-one",
        _descriptor_snapshot(),
        snapshots,
        {
            "identity": {
                "accepted": True,
                "returncode": 0,
                "validator_sha256": "1" * 64,
                "validator_closure": _validator_closure("identity", "1" * 64),
                "command": list(CONSUMER_COMMAND_CONTRACTS["identity"]),
                "stdout_sha256": "3" * 64,
            },
            "restart": {
                "accepted": True,
                "returncode": 0,
                "validator_sha256": "2" * 64,
                "validator_closure": _validator_closure("restart", "2" * 64),
                "command": list(CONSUMER_COMMAND_CONTRACTS["restart"]),
                "stdout_sha256": "4" * 64,
            },
        },
    )
    assert verify_producer_receipt(candidate, result)
    receipt = candidate / "producer-receipts" / f"{result.receipt_sha256}.json"
    receipt.write_bytes(receipt.read_bytes() + b" ")
    assert not verify_producer_receipt(candidate, result)

    receipt.write_bytes(receipt.read_bytes()[:-1])
    (candidate / "unbound-extra.json").write_text("{}\n", encoding="utf-8")
    assert not verify_producer_receipt(candidate, result)
