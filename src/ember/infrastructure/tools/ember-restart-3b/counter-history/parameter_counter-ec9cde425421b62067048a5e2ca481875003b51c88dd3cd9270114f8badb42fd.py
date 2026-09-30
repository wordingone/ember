# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-addressed and isolated sparse checkpoint-realization counter."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import pickle
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

# ``python -I src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py`` intentionally
# ignores ambient import configuration.  The counter's declared stream
# consumer is a sibling module, so resolve that sibling from this executable's
# own directory rather than relying on PYTHONPATH or site packages.
_COUNTER_MODULE_DIRECTORY = Path(__file__).resolve().parent
if str(_COUNTER_MODULE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_COUNTER_MODULE_DIRECTORY))

_P2B_STREAM_CORPUS_ROOT_SHA256 = "c2edce94125d9b7d88676ebbfa5aca3c447aa2d264ac6b74d7dfae5cf94e7178"
EXPERT_NAMES = ("vision", "audio", "reasoning", "tool")
ARCHITECTURE_REVISION = "ember-sparse-3b-v2"
_EXPERT_GENESIS_AUTHORITY_SCHEMA = "ember-expert-genesis-authority-v1"
_EXPERT_GENESIS_AUTHORITY_FIELDS = frozenset(
    {
        "schema_version",
        "architecture_revision",
        "model_config_sha256",
        "contract_sha256",
        "checkpoint_manifest_sha256",
        "expert_genesis_sha256",
    }
)
_PACKED_FRESH_GENESIS_LINEAGE_SCHEMA = (
    "ember-issue1413-packed-fresh-genesis-specialist-lineage-v1"
)
_PACKED_FRESH_GENESIS_MODE = "FRESH_GENESIS_NO_EXTERNAL_PREDECESSOR"
_PACKED_CURSOR_FIELDS = {
    "selected_ordinal", "global_step", "tokens_seen",
    "processed_tokens_seen", "pack_ordinal",
}
_PACKED_FRESH_GENESIS_LINEAGE_FIELDS = {
    "schema_version", "lineage_mode", "source_commit",
    "model_config_sha256", "seed", "active_expert", "trained_expert_ids",
    "genesis_lineage_sha256", "selection_receipt_sha256",
    "execution_record_order_sha256", "execution_tokens_sha256",
    "pack_sequence_sha256", "initial_cursor", "checkpoint_cursor",
    "lineage_sha256",
}


def _optimizer_owner_for_name(name: str) -> str:
    for expert_name in EXPERT_NAMES:
        if f".experts.{expert_name}." in name:
            return expert_name
    return "shared"
# `active_parameters` / `episode_trainable_parameters` semantics (issue #1329
# finding 3, decided not redefined): see the `_counts` docstring.
REALIZATION_RECEIPT_FIELDS = frozenset(
    {
        "schema_version", "verification_boundary", "result", "model_config_sha256",
        "subject_checkpoint_sha256", "architecture_revision", "counter_sha256",
        "allocated_parameters", "unique_parameters", "trainable_parameters",
        "served_parameters", "active_parameters", "episode_trainable_parameters",
        "active_expert_ids", "expert_genesis_sha256", "expert_parameter_sha256",
        "runtime_authority",
    }
)

_RUNTIME_AUTHORITY_NONE = {
    "schema_version": "ember-counter-runtime-authority-v1",
    "kind": "NONE",
}


def _runtime_authority_from_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Project a path-free, closed runtime witness into a measured receipt."""
    files = bundle.get("files")
    distribution = bundle.get("distribution")
    if not isinstance(files, list) or not files or not isinstance(distribution, Mapping):
        raise ValueError("tokenizer runtime authority is invalid")
    total_bytes = 0
    for item in files:
        if not isinstance(item, Mapping) or type(item.get("bytes")) is not int or item["bytes"] < 0:
            raise ValueError("tokenizer runtime authority is invalid")
        total_bytes += item["bytes"]
    return {
        "schema_version": "ember-counter-runtime-authority-v1",
        "kind": "P2B_TOKENIZERS_RECORD_V1",
        "runtime_schema_version": bundle.get("schema_version"),
        "distribution": {"name": distribution.get("name"), "version": distribution.get("version")},
        "record_sha256": bundle.get("record_sha256"),
        "compatibility": bundle.get("compatibility"),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "root_sha256": bundle.get("root_sha256"),
        "runtime_manifest_sha256": bundle.get("manifest_sha256"),
    }


def _validate_runtime_authority(value: Any) -> dict[str, Any]:
    if value == _RUNTIME_AUTHORITY_NONE:
        return dict(_RUNTIME_AUTHORITY_NONE)
    fields = {
        "schema_version", "kind", "runtime_schema_version", "distribution",
        "record_sha256", "compatibility", "file_count", "total_bytes",
        "root_sha256", "runtime_manifest_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("realization receipt runtime authority is invalid")
    if value.get("schema_version") != "ember-counter-runtime-authority-v1" or value.get("kind") != "P2B_TOKENIZERS_RECORD_V1":
        raise ValueError("realization receipt runtime authority is invalid")
    if value.get("runtime_schema_version") != "ember-p2b-tokenizer-runtime-bundle-v1":
        raise ValueError("realization receipt runtime authority is invalid")
    distribution = value.get("distribution")
    if not isinstance(distribution, Mapping) or set(distribution) != {"name", "version"} or distribution.get("name") != "tokenizers" or not isinstance(distribution.get("version"), str) or not distribution["version"]:
        raise ValueError("realization receipt runtime authority is invalid")
    compatibility = value.get("compatibility")
    if not isinstance(compatibility, Mapping) or set(compatibility) != {"python_version", "cache_tag", "abi_tag", "platform_tag"} or not all(isinstance(item, str) for item in compatibility.values()):
        raise ValueError("realization receipt runtime authority is invalid")
    for field in ("record_sha256", "root_sha256", "runtime_manifest_sha256"):
        candidate = value.get(field)
        if not isinstance(candidate, str) or len(candidate) != 64 or any(character not in "0123456789abcdef" for character in candidate):
            raise ValueError("realization receipt runtime authority is invalid")
    if type(value.get("file_count")) is not int or value["file_count"] < 1 or type(value.get("total_bytes")) is not int or value["total_bytes"] < 0:
        raise ValueError("realization receipt runtime authority is invalid")
    return dict(value)
SPECIALIST_VERIFICATION_FIELDS = frozenset(
    {
        "schema_version",
        "result",
        "capability",
        "data_manifest_sha256",
        "tokenizer_sha256",
        "verifier_sha256",
        "data_class",
        "record_count",
        "token_count",
        "source_manifest_sha256",
        "records_artifact_sha256",
        "semantic_checks",
        "generator_replay_verified",
        "admission",
        "semantic_model_contract_sha256",
        "runtime_semantic_model_contract_sha256",
    }
)

# Deliberately uninitialized until the P2B branch is selected.  Keeping this
# named seam allows in-process authority tests to substitute only the stream
# opener without forcing an optional stream dependency into the legacy CLI.
open_specialist_stream: Any | None = None


def _specialist_stream_api() -> tuple[Any, str, str, Any]:
    """Load the P2B-only stream consumer after legacy admission is selected."""
    # issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/specialist_stream.py
    import importlib.util as _ember_6373b0ee51e42f72_importlib
    import sys as _ember_6373b0ee51e42f72_sys
    from pathlib import Path as _ember_6373b0ee51e42f72_Path
    _ember_6373b0ee51e42f72_path = _ember_6373b0ee51e42f72_Path(__file__).resolve().parent.joinpath('specialist_stream.py')
    if not _ember_6373b0ee51e42f72_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/specialist_stream.py')
    _ember_6373b0ee51e42f72_aliases = ('_ember_issue2015_6373b0ee51e42f72', 'specialist_stream', 'src.ember.infrastructure.tools.ember-restart-3b.specialist_stream')
    _ember_6373b0ee51e42f72_existing = []
    for _ember_6373b0ee51e42f72_alias in _ember_6373b0ee51e42f72_aliases:
        _ember_6373b0ee51e42f72_candidate = _ember_6373b0ee51e42f72_sys.modules.get(_ember_6373b0ee51e42f72_alias)
        if _ember_6373b0ee51e42f72_candidate is not None and all(_ember_6373b0ee51e42f72_candidate is not item for item in _ember_6373b0ee51e42f72_existing):
            _ember_6373b0ee51e42f72_existing.append(_ember_6373b0ee51e42f72_candidate)
    if len(_ember_6373b0ee51e42f72_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/specialist_stream.py')
    if _ember_6373b0ee51e42f72_existing:
        _ember_6373b0ee51e42f72_module = _ember_6373b0ee51e42f72_existing[0]
        _ember_6373b0ee51e42f72_observed = getattr(_ember_6373b0ee51e42f72_module, '__file__', None)
        if _ember_6373b0ee51e42f72_observed is None or _ember_6373b0ee51e42f72_Path(_ember_6373b0ee51e42f72_observed).resolve() != _ember_6373b0ee51e42f72_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/specialist_stream.py')
    else:
        _ember_6373b0ee51e42f72_spec = _ember_6373b0ee51e42f72_importlib.spec_from_file_location('_ember_issue2015_6373b0ee51e42f72', _ember_6373b0ee51e42f72_path)
        if _ember_6373b0ee51e42f72_spec is None or _ember_6373b0ee51e42f72_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/specialist_stream.py')
        _ember_6373b0ee51e42f72_module = _ember_6373b0ee51e42f72_importlib.module_from_spec(_ember_6373b0ee51e42f72_spec)
        for _ember_6373b0ee51e42f72_alias in _ember_6373b0ee51e42f72_aliases:
            _ember_6373b0ee51e42f72_prior = _ember_6373b0ee51e42f72_sys.modules.get(_ember_6373b0ee51e42f72_alias)
            if _ember_6373b0ee51e42f72_prior is not None and _ember_6373b0ee51e42f72_prior is not _ember_6373b0ee51e42f72_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/specialist_stream.py')
            _ember_6373b0ee51e42f72_sys.modules[_ember_6373b0ee51e42f72_alias] = _ember_6373b0ee51e42f72_module
        try:
            _ember_6373b0ee51e42f72_spec.loader.exec_module(_ember_6373b0ee51e42f72_module)
        except BaseException:
            for _ember_6373b0ee51e42f72_alias in _ember_6373b0ee51e42f72_aliases:
                if _ember_6373b0ee51e42f72_sys.modules.get(_ember_6373b0ee51e42f72_alias) is _ember_6373b0ee51e42f72_module:
                    _ember_6373b0ee51e42f72_sys.modules.pop(_ember_6373b0ee51e42f72_alias, None)
            raise
    for _ember_6373b0ee51e42f72_alias in _ember_6373b0ee51e42f72_aliases:
        _ember_6373b0ee51e42f72_prior = _ember_6373b0ee51e42f72_sys.modules.get(_ember_6373b0ee51e42f72_alias)
        if _ember_6373b0ee51e42f72_prior is not None and _ember_6373b0ee51e42f72_prior is not _ember_6373b0ee51e42f72_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/specialist_stream.py')
        _ember_6373b0ee51e42f72_sys.modules[_ember_6373b0ee51e42f72_alias] = _ember_6373b0ee51e42f72_module
    SELECTION_CURSOR_SCHEMA_VERSION = getattr(_ember_6373b0ee51e42f72_module, 'SELECTION_CURSOR_SCHEMA_VERSION')
    TRAINING_CURSOR_SCHEMA_VERSION = getattr(_ember_6373b0ee51e42f72_module, 'TRAINING_CURSOR_SCHEMA_VERSION')
    canonical_record_bytes = getattr(_ember_6373b0ee51e42f72_module, 'canonical_record_bytes')
    open_specialist_stream = getattr(_ember_6373b0ee51e42f72_module, 'open_specialist_stream')
    # issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/specialist_stream.py

    return (
        canonical_record_bytes,
        SELECTION_CURSOR_SCHEMA_VERSION,
        TRAINING_CURSOR_SCHEMA_VERSION,
        globals().get("open_specialist_stream") or open_specialist_stream,
    )


@contextmanager
def _lease_p2b_tokenizer_runtime(*, bundle_root: Path, manifest_path: Path) -> Iterator[dict[str, Any]]:
    """Keep bound tokenizer bytes immutable through real P2B stream validation."""
    # issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/tokenizer_runtime_bundle.py
    import importlib.util as _ember_4b0514041c2271ff_importlib
    import sys as _ember_4b0514041c2271ff_sys
    from pathlib import Path as _ember_4b0514041c2271ff_Path
    _ember_4b0514041c2271ff_path = _ember_4b0514041c2271ff_Path(__file__).resolve().parent.joinpath('tokenizer_runtime_bundle.py')
    if not _ember_4b0514041c2271ff_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/tokenizer_runtime_bundle.py')
    _ember_4b0514041c2271ff_aliases = ('_ember_issue2015_4b0514041c2271ff', 'tokenizer_runtime_bundle', 'src.ember.infrastructure.tools.ember-restart-3b.tokenizer_runtime_bundle')
    _ember_4b0514041c2271ff_existing = []
    for _ember_4b0514041c2271ff_alias in _ember_4b0514041c2271ff_aliases:
        _ember_4b0514041c2271ff_candidate = _ember_4b0514041c2271ff_sys.modules.get(_ember_4b0514041c2271ff_alias)
        if _ember_4b0514041c2271ff_candidate is not None and all(_ember_4b0514041c2271ff_candidate is not item for item in _ember_4b0514041c2271ff_existing):
            _ember_4b0514041c2271ff_existing.append(_ember_4b0514041c2271ff_candidate)
    if len(_ember_4b0514041c2271ff_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/tokenizer_runtime_bundle.py')
    if _ember_4b0514041c2271ff_existing:
        _ember_4b0514041c2271ff_module = _ember_4b0514041c2271ff_existing[0]
        _ember_4b0514041c2271ff_observed = getattr(_ember_4b0514041c2271ff_module, '__file__', None)
        if _ember_4b0514041c2271ff_observed is None or _ember_4b0514041c2271ff_Path(_ember_4b0514041c2271ff_observed).resolve() != _ember_4b0514041c2271ff_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/tokenizer_runtime_bundle.py')
    else:
        _ember_4b0514041c2271ff_spec = _ember_4b0514041c2271ff_importlib.spec_from_file_location('_ember_issue2015_4b0514041c2271ff', _ember_4b0514041c2271ff_path)
        if _ember_4b0514041c2271ff_spec is None or _ember_4b0514041c2271ff_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/tokenizer_runtime_bundle.py')
        _ember_4b0514041c2271ff_module = _ember_4b0514041c2271ff_importlib.module_from_spec(_ember_4b0514041c2271ff_spec)
        for _ember_4b0514041c2271ff_alias in _ember_4b0514041c2271ff_aliases:
            _ember_4b0514041c2271ff_prior = _ember_4b0514041c2271ff_sys.modules.get(_ember_4b0514041c2271ff_alias)
            if _ember_4b0514041c2271ff_prior is not None and _ember_4b0514041c2271ff_prior is not _ember_4b0514041c2271ff_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/tokenizer_runtime_bundle.py')
            _ember_4b0514041c2271ff_sys.modules[_ember_4b0514041c2271ff_alias] = _ember_4b0514041c2271ff_module
        try:
            _ember_4b0514041c2271ff_spec.loader.exec_module(_ember_4b0514041c2271ff_module)
        except BaseException:
            for _ember_4b0514041c2271ff_alias in _ember_4b0514041c2271ff_aliases:
                if _ember_4b0514041c2271ff_sys.modules.get(_ember_4b0514041c2271ff_alias) is _ember_4b0514041c2271ff_module:
                    _ember_4b0514041c2271ff_sys.modules.pop(_ember_4b0514041c2271ff_alias, None)
            raise
    for _ember_4b0514041c2271ff_alias in _ember_4b0514041c2271ff_aliases:
        _ember_4b0514041c2271ff_prior = _ember_4b0514041c2271ff_sys.modules.get(_ember_4b0514041c2271ff_alias)
        if _ember_4b0514041c2271ff_prior is not None and _ember_4b0514041c2271ff_prior is not _ember_4b0514041c2271ff_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/tokenizer_runtime_bundle.py')
        _ember_4b0514041c2271ff_sys.modules[_ember_4b0514041c2271ff_alias] = _ember_4b0514041c2271ff_module
    lease_tokenizer_runtime_bundle = getattr(_ember_4b0514041c2271ff_module, 'lease_tokenizer_runtime_bundle')
    # issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/tokenizer_runtime_bundle.py

    with lease_tokenizer_runtime_bundle(bundle_root=bundle_root, manifest_path=manifest_path) as authority:
        yield authority


def validate_realization_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the one closed receipt schema emitted by the counter."""
    cia = isinstance(receipt,Mapping) and receipt.get('schema_version') == 'ember-cia-realization-receipt-v1'
    fields = REALIZATION_RECEIPT_FIELDS | ({'qualification'} if cia else set())
    if not isinstance(receipt, Mapping) or set(receipt) != fields:
        raise ValueError("realization receipt has an invalid closed schema")
    if not cia and receipt["schema_version"] != "ember-sparse-realization-receipt-v1":
        raise ValueError("realization receipt has an unsupported schema")
    if receipt["verification_boundary"] != "VERIFIED_MEASURED" or receipt["result"] != "MEASURED":
        raise ValueError("realization receipt is not measured evidence")
    if receipt['architecture_revision'] != ('CIA3-R1-N61' if cia else ARCHITECTURE_REVISION):
        raise ValueError("realization receipt architecture revision drifted")
    if cia and receipt['qualification'] != {'clean_genesis':False,'trained':False,'served':False}:
        raise ValueError('CIA object capacity receipt cannot grant model qualification')
    _validate_runtime_authority(receipt["runtime_authority"])
    for field in ("model_config_sha256", "subject_checkpoint_sha256", "counter_sha256"):
        value = receipt[field]
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError(f"realization receipt has an invalid {field}")
    for field in ("allocated_parameters", "unique_parameters", "trainable_parameters", "served_parameters", "active_parameters", "episode_trainable_parameters"):
        value = receipt[field]
        if type(value) is not int or value < 0:
            raise ValueError(f"realization receipt has an invalid {field}")
    active = receipt["active_expert_ids"]
    if (not isinstance(active,list) or (active != [str(i) for i in range(25) if str(i) in active] if cia else (len(active) != 1 or active[0] not in {'shared', *EXPERT_NAMES}))):
        raise ValueError("realization receipt has an invalid active expert route")
    for field in ("expert_genesis_sha256", "expert_parameter_sha256"):
        mapping = receipt[field]
        if not isinstance(mapping, Mapping) or set(mapping) != ({str(i) for i in range(25)} if cia else set(EXPERT_NAMES)):
            raise ValueError(f"realization receipt has an invalid {field} map")
        for expert, digest in mapping.items():
            if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError(f"realization receipt has an invalid {field} for {expert}")
    return dict(receipt)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_value(value: object, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _packed_cursor(value: object, *, label: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != _PACKED_CURSOR_FIELDS:
        raise ValueError(f"{label} must use the closed packed cursor projection")
    cursor = dict(value)
    if any(type(cursor[field]) is not int or cursor[field] < 0 for field in _PACKED_CURSOR_FIELDS):
        raise ValueError(f"{label} counters must be nonnegative integers")
    return cursor


def _validate_packed_fresh_genesis_specialist_lineage(
    manifest: Mapping[str, Any], *, active_expert: str,
) -> dict[str, Any] | None:
    lineage = manifest.get("lineage")
    if not isinstance(lineage, Mapping) or lineage.get("schema_version") != _PACKED_FRESH_GENESIS_LINEAGE_SCHEMA:
        return None
    if set(lineage) != _PACKED_FRESH_GENESIS_LINEAGE_FIELDS:
        raise ValueError("packed fresh-genesis lineage has an invalid closed shape")
    if (
        lineage.get("lineage_mode") != _PACKED_FRESH_GENESIS_MODE
        or lineage.get("active_expert") != active_expert
        or lineage.get("trained_expert_ids") != [active_expert]
    ):
        raise ValueError("packed fresh-genesis lineage route identity drifted")
    source_commit = lineage.get("source_commit")
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
    ):
        raise ValueError("packed fresh-genesis source commit must be lowercase 40hex")
    for field in (
        "model_config_sha256", "genesis_lineage_sha256",
        "selection_receipt_sha256", "execution_record_order_sha256",
        "execution_tokens_sha256", "pack_sequence_sha256", "lineage_sha256",
    ):
        _sha256_value(lineage.get(field), label=f"packed fresh-genesis {field}")
    seed = lineage.get("seed")
    if type(seed) is not int or seed < 0:
        raise ValueError("packed fresh-genesis seed must be a nonnegative integer")
    initial = _packed_cursor(lineage.get("initial_cursor"), label="packed fresh-genesis initial cursor")
    checkpoint = _packed_cursor(lineage.get("checkpoint_cursor"), label="packed fresh-genesis checkpoint cursor")
    if (
        checkpoint["selected_ordinal"] <= initial["selected_ordinal"]
        or checkpoint["global_step"] <= initial["global_step"]
        or checkpoint["tokens_seen"] <= initial["tokens_seen"]
        or checkpoint["processed_tokens_seen"] < checkpoint["tokens_seen"]
        or checkpoint["pack_ordinal"] <= initial["pack_ordinal"]
    ):
        raise ValueError("packed fresh-genesis checkpoint cursor made no valid progress")
    expected_genesis = _canonical_sha256({
        "schema_version": "ember-issue1413-packed-fresh-genesis-v1",
        "lineage_mode": _PACKED_FRESH_GENESIS_MODE,
        "source_commit": source_commit,
        "model_config_sha256": lineage["model_config_sha256"],
        "seed": seed,
    })
    if lineage["genesis_lineage_sha256"] != expected_genesis:
        raise ValueError("packed fresh-genesis lineage hash drifted")
    unsigned = {key: value for key, value in lineage.items() if key != "lineage_sha256"}
    if lineage["lineage_sha256"] != _canonical_sha256(unsigned):
        raise ValueError("packed fresh-genesis lineage self hash drifted")
    return dict(lineage)


def validate_p2b_stream_episode(episode: Mapping[str, Any], *, active_expert: str) -> dict[str, Any]:
    from repository_layout import allowed_authority_pin_tuples

    """Validate the closed stream-selection episode; legacy execution-slice episodes remain disjoint."""

    canonical_record_bytes, selection_cursor_schema_version, _training_cursor_schema_version, _open_specialist_stream = _specialist_stream_api()

    fields = {
        "schema_version", "active_expert", "selection_receipt", "selection_receipt_sha256",
        "start_selection_cursor", "end_selection_cursor", "completed_updates", "training_token_delta",
        "stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256", "family_root_sha256",
    }
    if not isinstance(episode, Mapping) or set(episode) != fields:
        raise ValueError("P2B stream episode has an invalid closed schema")
    if episode.get("schema_version") != "ember-specialist-stream-episode-v1" or episode.get("active_expert") != active_expert:
        raise ValueError("P2B stream episode active expert does not match")
    capability_for_expert = {"vision": "image", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}
    receipt_fields = {
        "schema_version", "stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256",
        "family_root_sha256", "capability", "selection_rule_id", "selected_record_count", "selected_token_count",
        "selected_records_sha256", "selection_commitment_sha256",
    }
    receipt = episode["selection_receipt"]
    if not isinstance(receipt, Mapping) or set(receipt) != receipt_fields or receipt.get("schema_version") != "ember-owned-specialist-stream-selection-receipt-v1":
        raise ValueError("P2B stream episode selection receipt is invalid")
    expected_rule = "image_scene_split_train_v1" if active_expert == "vision" else "all_records_semantic_pretraining_v1"
    if receipt.get("capability") != capability_for_expert.get(active_expert) or receipt.get("selection_rule_id") != expected_rule:
        raise ValueError("P2B stream episode capability or rule does not match active expert")
    for field in ("stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256", "family_root_sha256", "selected_records_sha256", "selection_commitment_sha256"):
        _sha256_value(receipt.get(field), label=f"P2B selection {field}")
    if any(type(receipt.get(field)) is not int or receipt[field] < 1 for field in ("selected_record_count", "selected_token_count")):
        raise ValueError("P2B stream episode selection counts are invalid")
    canonical = hashlib.sha256(canonical_record_bytes(dict(receipt))).hexdigest()
    if episode.get("selection_receipt_sha256") != canonical:
        raise ValueError("P2B stream episode selection receipt hash does not match")
    cursor_fields = {"schema_version", "selection_receipt_sha256", "selection_rule_id", "selected_ordinal", "next_source_index"}
    cursors: list[dict[str, Any]] = []
    for label in ("start_selection_cursor", "end_selection_cursor"):
        cursor = episode[label]
        if not isinstance(cursor, Mapping) or set(cursor) != cursor_fields or cursor.get("schema_version") != selection_cursor_schema_version:
            raise ValueError("P2B stream episode selection cursor is invalid")
        if cursor.get("selection_receipt_sha256") != canonical or cursor.get("selection_rule_id") != expected_rule:
            raise ValueError("P2B stream episode selection cursor identity does not match")
        if any(type(cursor.get(field)) is not int or cursor[field] < 0 for field in ("selected_ordinal", "next_source_index")):
            raise ValueError("P2B stream episode selection cursor progress is invalid")
        cursors.append(dict(cursor))
    start, end = cursors
    if not (0 <= start["selected_ordinal"] < end["selected_ordinal"] <= receipt["selected_record_count"]):
        raise ValueError("P2B stream episode selected ordinal is outside the selected range")
    if (end["selected_ordinal"] - start["selected_ordinal"] != episode.get("completed_updates")
            or end["next_source_index"] <= start["next_source_index"]):
        raise ValueError("P2B stream episode cursor does not advance by completed updates")
    if type(episode.get("completed_updates")) is not int or episode["completed_updates"] < 1 or type(episode.get("training_token_delta")) is not int or episode["training_token_delta"] < 1:
        raise ValueError("P2B stream episode counters are invalid")
    for field in ("stream_manifest_sha256", "stream_build_receipt_sha256", "corpus_root_sha256", "family_root_sha256"):
        if episode.get(field) != receipt.get(field):
            raise ValueError("P2B stream episode authority does not match selection receipt")
    allowed_pin_tuples = allowed_authority_pin_tuples(
        ("specialist_stream_manifest", "specialist_stream_build_receipt")
    )
    episode_pins = (receipt["stream_manifest_sha256"], receipt["stream_build_receipt_sha256"])
    if (episode_pins not in allowed_pin_tuples
            or receipt["corpus_root_sha256"] != _P2B_STREAM_CORPUS_ROOT_SHA256):
        raise ValueError("P2B stream episode does not bind the canonical stream authorities")
    return dict(episode)


def validate_p2b_counter_stream_authority(
    episode: Mapping[str, Any], *, active_expert: str, repo_root: Path,
    stream_manifest_path: Path, stream_build_receipt_path: Path,
    stream_manifest_bytes: bytes, stream_build_receipt_bytes: bytes,
) -> dict[str, Any]:
    """Require caller-bound stream artifacts before counter admission of a P2B episode."""
    from repository_layout import resolve_repository_authority

    _canonical_record_bytes, _selection_cursor_schema_version, _training_cursor_schema_version, open_specialist_stream = _specialist_stream_api()
    normalized = validate_p2b_stream_episode(episode, active_expert=active_expert)
    if not isinstance(stream_manifest_bytes, bytes) or not isinstance(stream_build_receipt_bytes, bytes):
        raise ValueError("P2B stream authority bytes are required")
    root = Path(repo_root).resolve()
    manifest_path = Path(stream_manifest_path).resolve()
    build_path = Path(stream_build_receipt_path).resolve()
    manifest_authority = resolve_repository_authority(root, "specialist_stream_manifest")
    build_authority = resolve_repository_authority(root, "specialist_stream_build_receipt")
    if (manifest_path != manifest_authority.path.resolve()
            or build_path != build_authority.path.resolve()):
        raise ValueError("P2B stream authority paths do not match the selected repository authorities")
    if (normalized["stream_manifest_sha256"] != manifest_authority.expected_sha256
            or normalized["stream_build_receipt_sha256"] != build_authority.expected_sha256):
        raise ValueError("P2B stream authority hashes do not match the selected repository authorities")
    if hashlib.sha256(stream_manifest_bytes).hexdigest() != normalized["stream_manifest_sha256"]:
        raise ValueError("P2B stream manifest authority mismatch")
    if hashlib.sha256(stream_build_receipt_bytes).hexdigest() != normalized["stream_build_receipt_sha256"]:
        raise ValueError("P2B stream build receipt authority mismatch")
    stream = open_specialist_stream(
        repo_root=root, manifest_path=manifest_path,
        expected_manifest_sha256=normalized["stream_manifest_sha256"],
        expected_corpus_root_sha256=normalized["corpus_root_sha256"],
        manifest_bytes=stream_manifest_bytes,
    )
    receipt = normalized["selection_receipt"]
    family = stream.families.get(str(receipt["capability"]))
    if not isinstance(family, Mapping) or family.get("corpus_root_sha256") != normalized["family_root_sha256"]:
        raise ValueError("P2B stream family authority mismatch")
    stream.open_execution_selection(
        receipt=receipt,
        cursor=normalized["end_selection_cursor"],
        build_receipt_path=build_path,
        expected_build_receipt_sha256=normalized["stream_build_receipt_sha256"],
        expected_selection_receipt_sha256=normalized["selection_receipt_sha256"],
        build_receipt_bytes=stream_build_receipt_bytes,
    )
    return normalized


def validate_p2b_counter_checkpoint_progress(
    episode: Mapping[str, Any], candidate_data_cursor: Mapping[str, Any], parent_data_cursor: Mapping[str, Any],
) -> dict[str, Any]:
    """Revalidate stream-episode progress against candidate and parent checkpoint cursors."""
    _canonical_record_bytes, _selection_cursor_schema_version, training_cursor_schema_version, _open_specialist_stream = _specialist_stream_api()
    required = {"schema_version", "selection_cursor", "global_step", "tokens_seen"}
    if not isinstance(candidate_data_cursor, Mapping) or set(candidate_data_cursor) != required:
        raise ValueError("P2B counter candidate training cursor is invalid")
    if candidate_data_cursor.get("schema_version") != training_cursor_schema_version:
        raise ValueError("P2B counter candidate training cursor schema is invalid")
    if not isinstance(episode, Mapping) or not isinstance(parent_data_cursor, Mapping):
        raise ValueError("P2B counter progress bindings are invalid")
    end = episode.get("end_selection_cursor")
    if candidate_data_cursor.get("selection_cursor") != end:
        raise ValueError("P2B counter candidate cursor does not match episode end")
    for label, value in (("parent global step", parent_data_cursor.get("global_step")), ("parent tokens", parent_data_cursor.get("tokens_seen")), ("candidate global step", candidate_data_cursor.get("global_step")), ("candidate tokens", candidate_data_cursor.get("tokens_seen")), ("completed updates", episode.get("completed_updates")), ("training token delta", episode.get("training_token_delta"))):
        if type(value) is not int or value < 0:
            raise ValueError(f"P2B counter {label} is invalid")
    if episode["completed_updates"] <= 0 or episode["training_token_delta"] <= 0:
        raise ValueError("P2B counter episode progress is invalid")
    if candidate_data_cursor["global_step"] - parent_data_cursor["global_step"] != episode["completed_updates"]:
        raise ValueError("P2B counter global-step delta does not match episode")
    if candidate_data_cursor["tokens_seen"] - parent_data_cursor["tokens_seen"] != episode["training_token_delta"]:
        raise ValueError("P2B counter token delta does not match episode")
    return dict(candidate_data_cursor)


def _validate_specialist_counter_episode(
    lineage: Mapping[str, Any], *, active_expert: str, repo_root: Path,
    stream_manifest_path: Path, stream_build_receipt_path: Path,
    stream_manifest_bytes: bytes, stream_build_receipt_bytes: bytes,
) -> dict[str, Any] | None:
    """Dispatch only the closed P2B episode shape to canonical stream reopening."""
    episode = lineage.get("episode")
    if not isinstance(episode, Mapping) or episode.get("schema_version") != "ember-specialist-stream-episode-v1":
        return None
    return validate_p2b_counter_stream_authority(
        episode,
        active_expert=active_expert,
        repo_root=repo_root,
        stream_manifest_path=stream_manifest_path,
        stream_build_receipt_path=stream_build_receipt_path,
        stream_manifest_bytes=stream_manifest_bytes,
        stream_build_receipt_bytes=stream_build_receipt_bytes,
    )


def _validate_legacy_specialist_counter_episode(episode: object, *, active_expert: str) -> None:
    """Preserve the established v4 data-verification/execution-slice episode contract."""
    capability_experts = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}
    episode_fields = {"active_expert", "data_verification_receipt", "data_verification_receipt_sha256", "execution_slice", "execution_slice_sha256"}
    if active_expert == "vision":
        episode_fields |= {"scene_split_selection", "scene_split_selection_sha256"}
    if (not isinstance(episode, Mapping) or set(episode) != episode_fields
            or episode.get("active_expert") != active_expert or not isinstance(episode.get("data_verification_receipt"), Mapping)):
        raise ValueError("specialist v4 lineage lacks a closed active episode")
    verification = episode["data_verification_receipt"]
    if (set(verification) != SPECIALIST_VERIFICATION_FIELDS or verification.get("schema_version") != "ember-training-data-verification-v1"
            or verification.get("result") != "VERIFIED" or verification.get("data_class") != "SEMANTIC_PRETRAINING"
            or verification.get("generator_replay_verified") is not True
            or verification.get("admission") != "ADMISSIBLE_SEMANTIC_CONTRACT"
            or verification.get("semantic_model_contract_sha256") != verification.get("runtime_semantic_model_contract_sha256")
            or capability_experts.get(verification.get("capability")) != active_expert):
        raise ValueError("specialist v4 lineage has an invalid data verification receipt")
    for field in ("semantic_model_contract_sha256", "runtime_semantic_model_contract_sha256"):
        _sha256_value(verification.get(field), label=f"specialist verification {field}")
    canonical = hashlib.sha256(json.dumps(dict(verification), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if episode.get("data_verification_receipt_sha256") != canonical:
        raise ValueError("specialist v4 lineage data verification receipt hash does not match")
    execution_slice = episode.get("execution_slice")
    slice_fields = {"schema_version", "start_record", "record_count", "token_count", "records_sha256", "tokens_sha256"}
    if active_expert == "vision":
        slice_fields |= {"scene_split_record_count"}
    if (not isinstance(execution_slice, Mapping) or set(execution_slice) != slice_fields
            or execution_slice.get("schema_version") != "ember-specialist-execution-slice-v1"
            or type(execution_slice.get("start_record")) is not int or execution_slice["start_record"] < 0
            or type(execution_slice.get("record_count")) is not int or execution_slice["record_count"] <= 0
            or type(execution_slice.get("token_count")) is not int or execution_slice["token_count"] <= 0
            or execution_slice["start_record"] + execution_slice["record_count"] > verification["record_count"]):
        raise ValueError("specialist v4 lineage has an invalid execution slice")
    for field in ("records_sha256", "tokens_sha256"):
        _sha256_value(execution_slice.get(field), label=f"specialist execution slice {field}")
    slice_canonical = hashlib.sha256(json.dumps(dict(execution_slice), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if episode.get("execution_slice_sha256") != slice_canonical:
        raise ValueError("specialist v4 lineage execution slice hash does not match")
    if active_expert == "vision":
        selection = episode.get("scene_split_selection")
        selection_fields = {"schema_version", "capability", "scene_split", "full_records_artifact_sha256", "selected_record_count", "selected_token_count", "selected_records_sha256", "selected_tokens_sha256"}
        if (not isinstance(selection, Mapping) or set(selection) != selection_fields
                or selection.get("schema_version") != "ember-specialist-scene-split-selection-v1"
                or selection.get("capability") != "image" or selection.get("scene_split") != "train"
                or selection.get("full_records_artifact_sha256") != verification.get("records_artifact_sha256")
                or selection.get("selected_record_count") != execution_slice.get("scene_split_record_count")
                or execution_slice["start_record"] + execution_slice["record_count"] > selection.get("selected_record_count", 0)
                or execution_slice["token_count"] > selection.get("selected_token_count", 0)):
            raise ValueError("specialist v4 lineage has an invalid train scene split selection")
        for field in ("full_records_artifact_sha256", "selected_records_sha256", "selected_tokens_sha256"):
            _sha256_value(selection.get(field), label=f"scene split {field}")
        if any(type(selection.get(field)) is not int or selection[field] <= 0 for field in ("selected_record_count", "selected_token_count")):
            raise ValueError("specialist v4 lineage has invalid scene split counts")
        selection_canonical = hashlib.sha256(json.dumps(dict(selection), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if episode.get("scene_split_selection_sha256") != selection_canonical:
            raise ValueError("specialist v4 lineage scene split selection hash does not match")


def _read_bytes_snapshot(path: Path, *, label: str) -> tuple[bytes, str]:
    try:
        with path.open("rb") as handle:
            payload = handle.read()
    except OSError as error:
        raise ValueError(f"{label} cannot be read") from error
    return payload, hashlib.sha256(payload).hexdigest()


def _read_json_snapshot(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    payload, digest = _read_bytes_snapshot(path, label=label)
    try:
        parsed = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must contain a JSON object") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return parsed, digest
def _model_shape(config: Mapping[str, Any]) -> dict[str, int]:
    model = config.get("model")
    if not isinstance(model, dict):
        raise ValueError("model config lacks model shape")
    routing = model.get("expert_routing")
    image = model.get("image_projection")
    audio = model.get("audio_projection")
    if not isinstance(routing, dict) or not isinstance(image, dict) or not isinstance(audio, dict):
        raise ValueError("model config lacks sparse modality/routing declarations")
    if tuple(routing.get("expert_names", ())) != EXPERT_NAMES:
        raise ValueError("model config must declare the four authorized experts")
    if tuple(image.get("input_shape", ())) != (48, 48, 3) or int(image.get("output_size", -1)) != int(model.get("hidden_size", -2)):
        raise ValueError("model config must declare raw 48x48x3 projection")
    if int(audio.get("frame_samples", -1)) != 640 or int(audio.get("output_size", -1)) != int(model.get("hidden_size", -2)):
        raise ValueError("model config must declare raw 640-sample projection")
    shape = {
        "hidden_size": int(model["hidden_size"]),
        "layers": int(model["layers"]),
        "attention_heads": int(model["attention_heads"]),
        "vocab_size": int(model["vocab_size"]),
    }
    if any(value <= 0 for value in shape.values()) or shape["hidden_size"] % shape["attention_heads"]:
        raise ValueError("model config has an invalid decoder shape")
    if model.get("tied_embeddings") is not True:
        raise ValueError("model config must require tied embeddings")
    return shape


def _expected_shared(shape: Mapping[str, int]) -> dict[str, tuple[int, ...]]:
    hidden, layers, vocab = shape["hidden_size"], shape["layers"], shape["vocab_size"]
    head_dim = hidden // shape["attention_heads"]
    expected = {
        "token_embedding.weight": (vocab, hidden),
        "lm_head.weight": (vocab, hidden),
        "image_projector.linear.weight": (hidden, 48 * 48 * 3),
        "audio_projector.linear.weight": (hidden, 640),
        "final_norm.weight": (hidden,),
    }
    for layer in range(layers):
        prefix = f"layers.{layer}."
        expected.update({
            prefix + "pre_attention_norm.weight": (hidden,),
            prefix + "attention.qkv.weight": (3 * hidden, hidden),
            prefix + "attention.q_norm.weight": (head_dim,),
            prefix + "attention.k_norm.weight": (head_dim,),
            prefix + "attention.output.weight": (hidden, hidden),
            prefix + "pre_ffn_norm.weight": (hidden,),
            prefix + "shared_ffn.up_gate.weight": (8 * hidden, hidden),
            prefix + "shared_ffn.down.weight": (hidden, 4 * hidden),
        })
    return expected


def _expected_expert(shape: Mapping[str, int], name: str) -> dict[str, tuple[int, ...]]:
    hidden, layers = shape["hidden_size"], shape["layers"]
    return {
        f"layers.{layer}.experts.{name}.up_gate.weight": (8 * hidden, hidden)
        for layer in range(layers)
    } | {
        f"layers.{layer}.experts.{name}.down.weight": (hidden, 4 * hidden)
        for layer in range(layers)
    }


class _StorageRef:
    def __init__(self, size: int, key: str = "", storage_type: str = "") -> None:
        self.size = int(size)
        self.key = key
        self.storage_type = storage_type


class _TensorMetadata:
    def __init__(self, storage: _StorageRef, offset: object, shape: object, stride: object) -> None:
        self.storage = storage
        self.offset = int(offset)
        self.shape = tuple(int(value) for value in shape)
        self.stride = tuple(int(value) for value in stride)


def _rebuild_tensor(storage: _StorageRef, offset: object, shape: object, stride: object, *unused: object) -> _TensorMetadata:
    if not isinstance(storage, _StorageRef):
        raise ValueError("checkpoint tensor lacks an authorized storage reference")
    return _TensorMetadata(storage, offset, shape, stride)


def _rebuild_parameter(value: _TensorMetadata, *unused: object) -> _TensorMetadata:
    return value


class _TensorTypeSentinel:
    """Non-executable placeholder for the exact torch.Tensor pickle global."""


def _rebuild_tensor_from_type(func: object, new_type: object, args: object, state: object) -> _TensorMetadata:
    """Extract only shape metadata from PyTorch's tensor-subtype pickle wrapper."""

    if func is not _rebuild_tensor or new_type is not _TensorTypeSentinel or not isinstance(args, tuple):
        raise ValueError("checkpoint tensor subtype wrapper is not an authorized metadata form")
    value = _rebuild_tensor(*args)
    if not isinstance(value, _TensorMetadata):
        raise ValueError("checkpoint tensor subtype wrapper did not produce tensor metadata")
    return value


class _CheckpointMetadataUnpickler(pickle.Unpickler):
    """Read only tensor metadata from a Torch zip checkpoint."""

    def persistent_load(self, persistent_id: object) -> _StorageRef:
        if not isinstance(persistent_id, tuple) or len(persistent_id) != 5 or persistent_id[0] != "storage":
            raise ValueError("checkpoint contains an unsupported persistent reference")
        storage_type = persistent_id[1]
        return _StorageRef(int(persistent_id[4]), str(persistent_id[2]), getattr(storage_type, "__name__", ""))

    def find_class(self, module: str, name: str) -> object:
        if module == "collections" and name == "OrderedDict":
            from collections import OrderedDict
            return OrderedDict
        if module == "torch._utils" and name.startswith("_rebuild_tensor"):
            return _rebuild_tensor
        if module == "torch._utils" and name == "_rebuild_parameter":
            return _rebuild_parameter
        if module == "torch._tensor" and name == "_rebuild_from_type_v2":
            return _rebuild_tensor_from_type
        if module == "torch" and name == "Tensor":
            return _TensorTypeSentinel
        if module == "torch" and name.endswith("Storage"):
            return type(name, (), {})
        raise ValueError(f"checkpoint references disallowed global {module}.{name}")


def _digest_open_handle(handle: Any) -> str:
    digest = hashlib.sha256(); handle.seek(0)
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
    handle.seek(0)
    return digest.hexdigest()


def _load_checkpoint_metadata(archive: zipfile.ZipFile) -> Any:
    try:
        candidates = [name for name in archive.namelist() if name.endswith("data.pkl")]
        if len(candidates) != 1:
            raise ValueError("checkpoint zip lacks exactly one data.pkl")
        return _CheckpointMetadataUnpickler(io.BytesIO(archive.read(candidates[0]))).load()
    except (pickle.PickleError, zipfile.BadZipFile, ValueError) as error:
        raise ValueError(f"checkpoint realization cannot be safely inspected: {error}") from error


def _validate_state(state: Any, expected: Mapping[str, tuple[int, ...]], *, label: str) -> None:
    if not isinstance(state, dict) or set(state) != set(expected):
        raise ValueError(f"{label} state keys do not realize the authorized architecture")
    for key, tensor in state.items():
        if not isinstance(tensor, _TensorMetadata) or tensor.shape != expected[key]:
            raise ValueError(f"{label} tensor shape mismatch: {key}")


def _contiguous_stride(shape: tuple[int, ...]) -> tuple[int, ...]:
    stride: list[int] = []; next_stride = 1
    for dimension in reversed(shape):
        stride.append(next_stride); next_stride *= dimension
    return tuple(reversed(stride))


def _storage_element_bytes(storage_type: str) -> int:
    widths = {"BFloat16Storage": 2, "FloatStorage": 4, "DoubleStorage": 8, "HalfStorage": 2, "LongStorage": 8, "IntStorage": 4, "ShortStorage": 2, "CharStorage": 1, "ByteStorage": 1, "BoolStorage": 1}
    if storage_type not in widths:
        raise ValueError("shared expert genesis uses an unsupported storage type")
    return widths[storage_type]


def _tensor_raw_bytes(archive: zipfile.ZipFile, tensor: _TensorMetadata) -> bytes:
    if tensor.offset != 0 or tensor.stride != _contiguous_stride(tensor.shape):
        raise ValueError("shared expert genesis tensor is not a contiguous base storage")
    width = _storage_element_bytes(tensor.storage.storage_type)
    candidates = [name for name in archive.namelist() if name.endswith(f"data/{tensor.storage.key}")]
    if len(candidates) != 1:
        raise ValueError("shared expert genesis storage entry is ambiguous")
    raw = archive.read(candidates[0]); expected = tensor.storage.size * width
    if len(raw) != expected:
        raise ValueError("shared expert genesis storage byte size mismatch")
    required = width
    for dimension in tensor.shape: required *= dimension
    if required != len(raw):
        raise ValueError("shared expert genesis tensor does not own its full storage")
    return raw


def _expert_raw_digest(archive: zipfile.ZipFile, payload: Any, *, name: str, shape: Mapping[str, int]) -> str:
    """Hash one expert bank's raw storage bytes straight off the archive."""
    state = payload.get("model") if isinstance(payload, dict) else None
    expected = _expected_expert(shape, name)
    if not isinstance(state, dict) or set(state) != set(expected):
        raise ValueError(f"expert genesis payload state mismatch: {name}")
    digest = hashlib.sha256()
    for layer in range(shape["layers"]):
        for suffix in ("up_gate.weight", "down.weight"):
            tensor = state.get(f"layers.{layer}.experts.{name}.{suffix}")
            if not isinstance(tensor, _TensorMetadata):
                raise ValueError(f"expert genesis payload tensor mismatch: {name}")
            digest.update(_tensor_raw_bytes(archive, tensor))
    return digest.hexdigest()


def derive_expert_genesis_sha256(
    *, model_config_path: Path, checkpoint_root: Path,
) -> dict[str, str]:
    """Derive expert tensor hashes through the counter's restricted reader."""

    config, _config_sha256 = _read_json_snapshot(
        Path(model_config_path), label="model config"
    )
    shape = _model_shape(config)
    root = Path(checkpoint_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("genesis checkpoint root must be a directory")
    hashes: dict[str, str] = {}
    for name in EXPERT_NAMES:
        path = (root / f"expert-{name}.pt").resolve(strict=True)
        if path.parent != root or not path.is_file():
            raise ValueError(f"genesis expert shard escapes its checkpoint root: {name}")
        try:
            with path.open("rb") as handle, zipfile.ZipFile(handle) as archive:
                payload = _load_checkpoint_metadata(archive)
                if not isinstance(payload, dict) or payload.get("expert") != name:
                    raise ValueError(f"expert realization identifies the wrong bank: {name}")
                _validate_state(
                    payload.get("model"), _expected_expert(shape, name), label=f"expert {name}"
                )
                hashes[name] = _expert_raw_digest(
                    archive, payload, name=name, shape=shape
                )
        except (OSError, zipfile.BadZipFile, ValueError) as error:
            if isinstance(error, ValueError):
                raise
            raise ValueError(
                f"genesis expert shard cannot be safely inspected: {name}"
            ) from error
    return hashes


def _verify_shared_expert_genesis(archive: zipfile.ZipFile, payload: Any, *, name: str, genesis: Mapping[str, str], shape: Mapping[str, int]) -> None:
    if _expert_raw_digest(archive, payload, name=name, shape=shape) != genesis[name]:
        raise ValueError(f"shared expert genesis hash mismatch: {name}")


def _verify_expert_trained_from_genesis(archive: zipfile.ZipFile, payload: Any, *, name: str, genesis: Mapping[str, str], shape: Mapping[str, int]) -> None:
    """Inverted genesis check: full-coverage root claims every bank trained.

    Unlike ``_verify_shared_expert_genesis`` (which requires an exact genesis
    match for the untouched pure-genesis checkpoint), a full-coverage root
    realization asserts all four banks were trained in this one episode. Byte
    evidence for that claim requires each bank's recomputed raw hash to
    DIFFER from its recorded genesis hash -- a bank still at genesis bytes
    means the manifest's claim is unearned.
    """
    if _expert_raw_digest(archive, payload, name=name, shape=shape) == genesis[name]:
        raise ValueError(f"full-coverage root expert genesis byte-verification failed (untrained): {name}")


_STORAGE_PROJECTION_SCHEMA = "ember-checkpoint-storage-projection-v1"


def _full_coverage_root_projection(manifest: Mapping[str, Any], *, active_expert: str) -> bool:
    """True when the manifest is a signed full-coverage root.

    A governed-vertical genesis run trains every expert in one episode: the
    checkpoint is specialist-active (one routed expert) yet has no lineage,
    because there is no parent — all four banks were realized from genesis in
    this same run. The discriminator is the manifest's own digest-bound storage
    projection attesting that every optimizer route was active. Any tampering
    (forged digest, partial route list, mismatched active expert, missing
    projection, or an id list widened over route bytes that are not actually
    positive for all four routes) makes this return False and the lineage
    refusal stands. The route-bytes cross-check mirrors
    ``_validate_checkpoint_storage_projection`` (checkpoint_artifacts.py) so a
    re-signed manifest that widens only the id list over a genuinely-partial
    optimizer state is refused here too, not just at governed publication.
    """
    if active_expert == "shared":
        return False
    if manifest.get("schema_version") != "ember-sparse-checkpoint-v5":
        return False
    if manifest.get("lineage") is not None:
        return False
    projection = manifest.get("storage_projection")
    if not isinstance(projection, Mapping):
        return False
    if projection.get("schema_version") != _STORAGE_PROJECTION_SCHEMA:
        return False
    declared = projection.get("projection_sha256")
    if not isinstance(declared, str):
        return False
    unsigned = {key: value for key, value in projection.items() if key != "projection_sha256"}
    digest = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if digest != declared:
        return False
    if projection.get("active_expert") != active_expert:
        return False
    if projection.get("optimizer_state_active_expert_ids") != list(EXPERT_NAMES):
        return False
    route_bytes = projection.get("optimizer_state_tensor_storage_by_route_bytes")
    if not isinstance(route_bytes, Mapping) or set(route_bytes) != {"shared", *EXPERT_NAMES}:
        return False
    if any(type(value) is not int or value < 0 for value in route_bytes.values()):
        return False
    if route_bytes[active_expert] <= 0:
        return False
    if [name for name in EXPERT_NAMES if route_bytes[name] > 0] != list(EXPERT_NAMES):
        return False
    return True


def _validate_external_genesis_authority(
    authority: Mapping[str, Any],
    *,
    config_sha256: str,
    subject_checkpoint_sha256: str,
    manifest: Mapping[str, Any],
) -> dict[str, str]:
    """Validate the independent, content-addressed genesis binding."""

    if set(authority) != _EXPERT_GENESIS_AUTHORITY_FIELDS:
        raise ValueError("external genesis authority has an invalid closed schema")
    if authority.get("schema_version") != _EXPERT_GENESIS_AUTHORITY_SCHEMA:
        raise ValueError("external genesis authority has an unsupported schema")
    if authority.get("architecture_revision") != ARCHITECTURE_REVISION:
        raise ValueError("external genesis authority architecture revision drifted")
    if authority.get("model_config_sha256") != config_sha256:
        raise ValueError("external genesis authority model-config hash mismatch")
    if authority.get("checkpoint_manifest_sha256") != subject_checkpoint_sha256:
        raise ValueError("external genesis authority checkpoint hash mismatch")
    contract_sha256 = _sha256_value(authority.get("contract_sha256"), label="external genesis contract hash")
    manifest_contract_sha256 = _sha256_value(manifest.get("contract_sha256"), label="checkpoint contract hash")
    if contract_sha256 != manifest_contract_sha256:
        raise ValueError("external genesis authority contract hash mismatch")
    genesis = authority.get("expert_genesis_sha256")
    if not isinstance(genesis, Mapping) or set(genesis) != set(EXPERT_NAMES):
        raise ValueError("external genesis authority lacks the four expert hashes")
    validated_genesis: dict[str, str] = {}
    for expert in EXPERT_NAMES:
        validated_genesis[expert] = _sha256_value(
            genesis.get(expert), label=f"external {expert} genesis hash"
        )
    manifest_genesis = manifest.get("expert_genesis_sha256")
    if not isinstance(manifest_genesis, Mapping) or set(manifest_genesis) != set(EXPERT_NAMES):
        raise ValueError("checkpoint lacks the four expert genesis hashes")
    if dict(manifest_genesis) != validated_genesis:
        raise ValueError("checkpoint genesis map disagrees with external authority")
    return validated_genesis


def _inspect_realization(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    *,
    active_expert: str,
    shape: Mapping[str, int],
    full_coverage_root: bool = False,
    packed_fresh_genesis_specialist: bool = False,
    genesis_override: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    records = manifest.get("shards")
    if not isinstance(records, list): raise ValueError("checkpoint manifest lacks shard records")
    schema_version = manifest.get("schema_version")
    optimizer_state_layout = manifest.get("optimizer_state_layout", "legacy-v1")
    if schema_version == "ember-sparse-checkpoint-v5":
        if optimizer_state_layout == "owner-sharded-v1":
            owner_ids = manifest.get("optimizer_state_owner_ids")
            if (
                not isinstance(owner_ids, list)
                or owner_ids != [owner for owner in ("shared", *EXPERT_NAMES) if owner in owner_ids]
                or not owner_ids
            ):
                raise ValueError("checkpoint owner-sharded optimizer layout is not closed")
            required = {
                "shared-model.pt",
                "replay-state.pt",
                *(f"optimizer-state-{owner}.pt" for owner in owner_ids),
                *(f"expert-{name}.pt" for name in EXPERT_NAMES),
            }
        elif optimizer_state_layout == "legacy-v1":
            required = {
                "shared-model.pt",
                "optimizer-state.pt",
                "replay-state.pt",
                *(f"expert-{name}.pt" for name in EXPERT_NAMES),
            }
        else:
            raise ValueError("checkpoint optimizer state layout is unsupported")
    elif schema_version in {"ember-sparse-checkpoint-v3", "ember-sparse-checkpoint-v4"}:
        required = {"shared.pt", "replay-state.pt", *(f"expert-{name}.pt" for name in EXPERT_NAMES)}
    else:
        raise ValueError("checkpoint realization schema is unsupported")
    by_path: dict[str, dict[str, Any]] = {}
    for record in records:
        relative = record.get("path") if isinstance(record, dict) else None
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts or relative in by_path:
            raise ValueError("checkpoint shard path is not bundle-relative")
        by_path[relative] = record
    if set(by_path) != required: raise ValueError("checkpoint realization shard set is not closed for its schema")
    if schema_version == "ember-sparse-checkpoint-v5":
        if manifest.get("shared_model_shard_sha256") != by_path["shared-model.pt"].get("sha256"):
            raise ValueError("checkpoint v5 split shard identity does not match its closed records")
        if optimizer_state_layout == "owner-sharded-v1":
            owner_ids = manifest["optimizer_state_owner_ids"]
            owner_hashes = manifest.get("optimizer_state_owner_shard_sha256")
            owner_by_parameter = manifest.get("optimizer_state_owner_by_parameter")
            if (
                not isinstance(owner_hashes, Mapping)
                or set(owner_hashes) != set(owner_ids)
                or not isinstance(owner_by_parameter, Mapping)
                or not owner_by_parameter
                or set(owner_by_parameter.values()) - set(owner_ids)
            ):
                raise ValueError("checkpoint owner-sharded optimizer identity is not closed")
            for owner in owner_ids:
                if owner_hashes[owner] != by_path[f"optimizer-state-{owner}.pt"].get("sha256"):
                    raise ValueError("checkpoint owner-sharded optimizer identity does not match its closed records")
        elif manifest.get("optimizer_state_shard_sha256") != by_path["optimizer-state.pt"].get("sha256"):
            raise ValueError("checkpoint v5 split shard identity does not match its closed records")
    elif manifest.get("shared_optimizer_shard_sha256") != by_path["shared.pt"].get("sha256"):
        raise ValueError("legacy shared optimizer shard identity does not match its closed record")
    if manifest.get("active_expert_ids") != [active_expert]: raise ValueError("checkpoint active expert does not match executed counter argument")
    if active_expert != "shared" and (
        schema_version not in {"ember-sparse-checkpoint-v4", "ember-sparse-checkpoint-v5"}
        or not isinstance(manifest.get("lineage"), Mapping)
    ) and not _full_coverage_root_projection(
        manifest, active_expert=active_expert,
    ) and not packed_fresh_genesis_specialist:
        raise ValueError("specialist-active realization requires a lineage manifest")
    genesis = genesis_override if genesis_override is not None else manifest.get("expert_genesis_sha256")
    expert_hashes = manifest.get("expert_checkpoint_sha256")
    if not isinstance(genesis, dict) or set(genesis) != set(EXPERT_NAMES) or not isinstance(expert_hashes, dict) or set(expert_hashes) != set(EXPERT_NAMES): raise ValueError("checkpoint lacks the four expert genesis/checkpoint hashes")
    for name, digest in genesis.items(): _sha256_value(digest, label=f"{name} genesis hash")
    authorized_parameter_names = set(_expected_shared(shape))
    for expert_name in EXPERT_NAMES:
        authorized_parameter_names.update(_expected_expert(shape, expert_name))
    owner_state_names: set[str] = set()
    for relative, record in by_path.items():
        shard = manifest_path.parent / relative
        if not shard.is_file() or shard.stat().st_size != record.get("bytes"): raise ValueError(f"checkpoint shard byte-size mismatch: {relative}")
        try:
            with shard.open("rb") as handle:
                if _digest_open_handle(handle) != record.get("sha256"): raise ValueError(f"checkpoint shard hash mismatch: {relative}")
                if relative == "replay-state.pt": continue
                with zipfile.ZipFile(handle) as archive:
                    payload = _load_checkpoint_metadata(archive)
                    if relative in {"shared.pt", "shared-model.pt"}:
                        if relative == "shared.pt" and (not isinstance(payload, dict) or "optimizer" not in payload):
                            raise ValueError("legacy shared checkpoint lacks optimizer realization")
                        _validate_state(payload.get("model") if isinstance(payload, dict) else None, _expected_shared(shape), label="shared")
                    elif relative == "optimizer-state.pt":
                        if not isinstance(payload, dict) or "optimizer" not in payload: raise ValueError("shared checkpoint lacks optimizer realization")
                    elif relative.startswith("optimizer-state-") and optimizer_state_layout == "owner-sharded-v1":
                        owner = relative[len("optimizer-state-"):-len(".pt")]
                        if (
                            not isinstance(payload, dict)
                            or set(payload) != {"schema_version", "owner", "state", "param_groups", "optimizer_contract", "optimizer_realization"}
                            or payload.get("schema_version") != "ember-optimizer-owner-shard-v1"
                            or payload.get("owner") != owner
                            or payload.get("optimizer_contract") != manifest.get("optimizer_contract")
                            or payload.get("optimizer_realization") != manifest.get("optimizer_realization")
                            or not isinstance(payload.get("state"), Mapping)
                            or not payload["state"]
                            or not isinstance(payload.get("param_groups"), list)
                        ):
                            raise ValueError(f"checkpoint owner optimizer payload is malformed: {owner}")
                        for name in payload["state"]:
                            if (
                                not isinstance(name, str)
                                or name not in authorized_parameter_names
                                or name not in manifest["optimizer_state_owner_by_parameter"]
                                or manifest["optimizer_state_owner_by_parameter"][name] != owner
                                or _optimizer_owner_for_name(name) != owner
                                or name in owner_state_names
                            ):
                                raise ValueError("checkpoint owner optimizer payload violates parameter ownership")
                            owner_state_names.add(name)
                    else:
                        name = relative[len("expert-"):-len(".pt")]
                        if expert_hashes[name] != record["sha256"]: raise ValueError(f"checkpoint expert hash is not bound: {name}")
                        if not isinstance(payload, dict) or payload.get("expert") != name: raise ValueError(f"expert realization identifies the wrong bank: {name}")
                        _validate_state(payload.get("model"), _expected_expert(shape, name), label=f"expert {name}")
                        if active_expert == "shared": _verify_shared_expert_genesis(archive, payload, name=name, genesis=genesis, shape=shape)
                        elif full_coverage_root:
                            _verify_expert_trained_from_genesis(
                                archive, payload, name=name, genesis=genesis, shape=shape,
                            )
                        elif packed_fresh_genesis_specialist:
                            verifier = (
                                _verify_expert_trained_from_genesis
                                if name == active_expert
                                else _verify_shared_expert_genesis
                            )
                            verifier(archive, payload, name=name, genesis=genesis, shape=shape)
        except (OSError, zipfile.BadZipFile, ValueError) as error:
            if isinstance(error, ValueError): raise
            raise ValueError(f"checkpoint realization cannot be safely inspected: {error}") from error
    if schema_version == "ember-sparse-checkpoint-v5" and optimizer_state_layout == "owner-sharded-v1":
        if owner_state_names != set(manifest["optimizer_state_owner_by_parameter"]):
            raise ValueError("checkpoint owner optimizer projection does not match shard payloads")
    return dict(manifest)
def _counts(shape: Mapping[str, int], *, active_expert: str) -> dict[str, int]:
    """Measure the receipt's parameter-count fields.

    Decided episode-scope semantics (issue #1329 finding 3): ``active_parameters``
    and ``episode_trainable_parameters`` are always the per-step ROUTED-ACTIVE
    scope -- shared plus at most the one bank named by ``active_expert`` -- for
    every admission path, including a full-coverage root realization where the
    manifest's own storage projection attests all four banks were trained in
    the one governed-vertical episode. They never report the wider per-episode
    TRAINED set (shared plus all four banks); that would be a silent
    redefinition rippling into the byte-bound arithmetic of #1320 and into
    ``checkpoint_artifacts._validate_counter_receipt``'s architecture
    cross-check, which is explicitly not wanted. A caller who needs the wider
    trained-set figure for a full-coverage root receipt derives it itself as
    ``allocated_parameters`` (== ``total`` below), since a full-coverage root's
    trained scope is by definition the whole model.
    """
    hidden, layers, vocab = shape["hidden_size"], shape["layers"], shape["vocab_size"]
    head_dim = hidden // shape["attention_heads"]
    shared = (
        vocab * hidden
        + layers * (4 * hidden * hidden + 12 * hidden * hidden + 2 * hidden + 2 * head_dim)
        + hidden
        + (48 * 48 * 3) * hidden
        + 640 * hidden
    )
    expert = layers * 12 * hidden * hidden
    total = shared + len(EXPERT_NAMES) * expert
    active = shared if active_expert == "shared" else shared + expert
    return {
        "allocated_parameters": total,
        "unique_parameters": total,
        "trainable_parameters": total,
        "served_parameters": total,
        "active_parameters": active,
        "episode_trainable_parameters": active,
    }


def execute_counter(
    *, model_config: Path, checkpoint_manifest: Path, active_expert: str,
    parent_manifest: Path | None = None, root_manifest: Path | None = None,
    p2b_repo_root: Path | None = None, p2b_stream_manifest: Path | None = None,
    p2b_stream_build_receipt: Path | None = None, p2b_tokenizer_runtime_root: Path | None = None,
    p2b_tokenizer_runtime_manifest: Path | None = None,
    expert_genesis_authority: Path | None = None,
    expert_genesis_authority_sha256: str | None = None,
) -> dict[str, Any]:
    """Measure a checkpoint using an independent genesis authority when supplied.

    The authority is a closed JSON snapshot whose expected SHA-256 is supplied
    separately; its expert map is checked against the checkpoint manifest before
    any shard payload is inspected.  Legacy in-process callers may omit this
    optional binding for compatibility, while governed external-genesis callers
    must provide both the path and expected content hash.
    """

    cia_manifest, cia_digest = _read_json_snapshot(checkpoint_manifest, label='checkpoint manifest')
    if cia_manifest.get('schema_version') == 'ember-cia-checkpoint-v1':
        if active_expert != 'all' or any(value is not None for value in (
                parent_manifest,root_manifest,p2b_repo_root,p2b_stream_manifest,p2b_stream_build_receipt,
                p2b_tokenizer_runtime_root,p2b_tokenizer_runtime_manifest,expert_genesis_authority,expert_genesis_authority_sha256)):
            raise ValueError('CIA counter requires full-population scope without v2 lineage')
        config, config_digest = _read_json_snapshot(model_config,label='model config')
        if config != cia_manifest['architecture_config']:
            raise ValueError('CIA counter architecture config differs from checkpoint')
        return _cia_realization_receipt(checkpoint_manifest.parent,
            dict(cia_manifest,checkpoint_manifest_sha256=cia_digest),model_config_sha256=config_digest)
    if active_expert not in {*EXPERT_NAMES, "shared"}:
        raise ValueError("active expert must be shared or one of the four authorized banks")
    if (expert_genesis_authority is None) != (expert_genesis_authority_sha256 is None):
        raise ValueError("external genesis authority path and SHA-256 are required together")
    config, config_sha256 = _read_json_snapshot(model_config, label="model config")
    if config.get("architecture_revision") != ARCHITECTURE_REVISION:
        raise ValueError("model config revision is not ember-sparse-3b-v2")
    shape = _model_shape(config)
    manifest_snapshot, subject_checkpoint_sha256 = cia_manifest, cia_digest
    # Determined from the raw snapshot (not the post-inspection manifest) so the
    # discriminator can be threaded into `_inspect_realization` for the inverted
    # genesis byte-verification (Finding 2, issue #1329) in the same shard pass.
    full_coverage_root = _full_coverage_root_projection(manifest_snapshot, active_expert=active_expert)
    packed_fresh_genesis_lineage = _validate_packed_fresh_genesis_specialist_lineage(
        manifest_snapshot, active_expert=active_expert,
    )
    external_genesis: dict[str, str] | None = None
    if expert_genesis_authority is not None:
        expected_authority_sha256 = _sha256_value(
            expert_genesis_authority_sha256,
            label="external genesis authority SHA-256",
        )
        authority_snapshot, authority_sha256 = _read_json_snapshot(
            Path(expert_genesis_authority), label="external genesis authority"
        )
        if authority_sha256 != expected_authority_sha256:
            raise ValueError("external genesis authority content hash mismatch")
        external_genesis = _validate_external_genesis_authority(
            authority_snapshot,
            config_sha256=config_sha256,
            subject_checkpoint_sha256=subject_checkpoint_sha256,
            manifest=manifest_snapshot,
        )
    manifest = _inspect_realization(
        checkpoint_manifest,
        manifest_snapshot,
        active_expert=active_expert,
        shape=shape,
        full_coverage_root=full_coverage_root,
        packed_fresh_genesis_specialist=packed_fresh_genesis_lineage is not None,
        genesis_override=external_genesis,
    )
    p2b_inputs = (p2b_repo_root, p2b_stream_manifest, p2b_stream_build_receipt, p2b_tokenizer_runtime_root, p2b_tokenizer_runtime_manifest)
    runtime_authority: dict[str, Any] = dict(_RUNTIME_AUTHORITY_NONE)
    if active_expert == "shared" and any(value is not None for value in p2b_inputs):
        raise ValueError("legacy counter call must not include P2B stream authority")
    if full_coverage_root:
        if any(value is not None for value in p2b_inputs):
            raise ValueError("full-coverage root counter call must not include P2B stream authority")
        if parent_manifest is not None or root_manifest is not None:
            raise ValueError("full-coverage root realization must not carry external lineage manifests")
        root_parameters = manifest.get("expert_parameter_sha256")
        if not isinstance(root_parameters, dict) or set(root_parameters) != set(EXPERT_NAMES):
            raise ValueError("full-coverage root manifest lacks closed expert parameter hashes")
        for name in EXPERT_NAMES:
            _sha256_value(root_parameters[name], label=f"root {name} parameter hash")
    if packed_fresh_genesis_lineage is not None:
        if any(value is not None for value in p2b_inputs):
            raise ValueError("packed fresh-genesis counter call must not include P2B stream authority")
        if parent_manifest is not None or root_manifest is not None:
            raise ValueError("packed fresh-genesis realization must not carry external lineage manifests")
        if packed_fresh_genesis_lineage["model_config_sha256"] != config_sha256:
            raise ValueError("packed fresh-genesis lineage model-config hash mismatch")
        if packed_fresh_genesis_lineage["seed"] != manifest.get("launch_seed"):
            raise ValueError("packed fresh-genesis lineage launch seed mismatch")
        cursor = manifest.get("data_cursor")
        selection_cursor = cursor.get("packed_selection_cursor") if isinstance(cursor, Mapping) else None
        if not isinstance(selection_cursor, Mapping):
            raise ValueError("packed fresh-genesis checkpoint lacks its selection cursor")
        realized_cursor = _packed_cursor({
            "selected_ordinal": selection_cursor.get("selected_ordinal"),
            "global_step": cursor.get("global_step"),
            "tokens_seen": cursor.get("tokens_seen"),
            "processed_tokens_seen": cursor.get("processed_tokens_seen"),
            "pack_ordinal": cursor.get("pack_ordinal"),
        }, label="packed fresh-genesis realized cursor")
        if realized_cursor != packed_fresh_genesis_lineage["checkpoint_cursor"]:
            raise ValueError("packed fresh-genesis checkpoint cursor does not match lineage")
        candidate_parameters = manifest.get("expert_parameter_sha256")
        genesis_parameters = manifest.get("expert_genesis_sha256")
        if (
            not isinstance(candidate_parameters, Mapping)
            or set(candidate_parameters) != set(EXPERT_NAMES)
            or not isinstance(genesis_parameters, Mapping)
            or set(genesis_parameters) != set(EXPERT_NAMES)
        ):
            raise ValueError("packed fresh-genesis checkpoint lacks closed expert hashes")
        if candidate_parameters[active_expert] == genesis_parameters[active_expert]:
            raise ValueError("packed fresh-genesis active expert did not change from genesis")
        for name in EXPERT_NAMES:
            if name != active_expert and candidate_parameters[name] != genesis_parameters[name]:
                raise ValueError(f"packed fresh-genesis inactive expert changed from genesis: {name}")
    if (
        active_expert != "shared"
        and not full_coverage_root
        and packed_fresh_genesis_lineage is None
        and (parent_manifest is None or root_manifest is None)
    ):
        raise ValueError("specialist-active realization requires external parent and root manifests")
    if active_expert != "shared" and not full_coverage_root and packed_fresh_genesis_lineage is None:
        lineage = manifest.get("lineage")
        if not isinstance(lineage, Mapping):
            raise ValueError("specialist-active realization lacks v4 lineage")
        parent_manifest = Path(parent_manifest).resolve()
        root_manifest = Path(root_manifest).resolve()
        snapshot_cache: dict[Path, tuple[dict[str, Any], str]] = {}
        def external_snapshot(path: Path, label: str) -> tuple[dict[str, Any], str]:
            if path not in snapshot_cache:
                snapshot_cache[path] = _read_json_snapshot(path, label=f"external {label} manifest")
            return snapshot_cache[path]
        parent_snapshot, parent_sha256 = external_snapshot(parent_manifest, "parent")
        root_snapshot, root_sha256 = external_snapshot(root_manifest, "root")
        if lineage.get("parent_checkpoint_sha256") != parent_sha256:
            raise ValueError("specialist lineage parent checkpoint hash does not match external manifest")
        if lineage.get("root_genesis_checkpoint_sha256") != root_sha256:
            raise ValueError("specialist lineage root checkpoint hash does not match external manifest")
        external_manifests: dict[str, dict[str, Any]] = {}
        for external_manifest, label, external, external_sha256 in ((parent_manifest, "parent", parent_snapshot, parent_sha256), (root_manifest, "root", root_snapshot, root_sha256)):
            external_active = external.get("active_expert_ids")
            if not isinstance(external_active, list) or len(external_active) != 1:
                raise ValueError(f"external {label} manifest lacks one active expert")
            external_manifests[label] = _inspect_realization(external_manifest, external, active_expert=external_active[0], shape=shape)
        parent_external, root_external = external_manifests["parent"], external_manifests["root"]
        parent_lineage = parent_external.get("lineage")
        if not isinstance(parent_lineage, Mapping):
            if parent_sha256 != root_sha256:
                raise ValueError("first specialist successor requires matching external parent and root")
            parent_history: list[str] = []
        else:
            if not isinstance(parent_lineage, Mapping) or parent_lineage.get("root_genesis_checkpoint_sha256") != root_sha256:
                raise ValueError("external parent does not bind the supplied immutable root")
            parent_history = parent_lineage.get("trained_expert_ids")
            if not isinstance(parent_history, list):
                raise ValueError("external parent has invalid trained expert history")
        if any(name not in EXPERT_NAMES for name in parent_history) or len(set(parent_history)) != len(parent_history):
            raise ValueError("external parent has invalid trained expert history")
        expected_history = [*parent_history, *([] if active_expert in parent_history else [active_expert])]
        episode = lineage.get("episode")
        if isinstance(episode, Mapping) and episode.get("schema_version") == "ember-specialist-stream-episode-v1":
            if any(value is None for value in p2b_inputs):
                raise ValueError("P2B counter requires explicit stream authority inputs")
            assert p2b_repo_root is not None and p2b_stream_manifest is not None and p2b_stream_build_receipt is not None and p2b_tokenizer_runtime_root is not None and p2b_tokenizer_runtime_manifest is not None
            stream_manifest_bytes, _ = _read_bytes_snapshot(Path(p2b_stream_manifest), label="P2B stream manifest")
            stream_build_receipt_bytes, _ = _read_bytes_snapshot(Path(p2b_stream_build_receipt), label="P2B stream build receipt")
            with _lease_p2b_tokenizer_runtime(
                bundle_root=Path(p2b_tokenizer_runtime_root),
                manifest_path=Path(p2b_tokenizer_runtime_manifest),
            ) as p2b_tokenizer_runtime:
                runtime_authority = _runtime_authority_from_bundle(p2b_tokenizer_runtime)
                p2b_episode = _validate_specialist_counter_episode(
                    lineage,
                    active_expert=active_expert,
                    repo_root=Path(p2b_repo_root),
                    stream_manifest_path=Path(p2b_stream_manifest),
                    stream_build_receipt_path=Path(p2b_stream_build_receipt),
                    stream_manifest_bytes=stream_manifest_bytes,
                    stream_build_receipt_bytes=stream_build_receipt_bytes,
                )
            validate_p2b_counter_checkpoint_progress(
                p2b_episode,
                manifest.get("data_cursor"),
                parent_external.get("data_cursor"),
            )
        else:
            if any(value is not None for value in p2b_inputs):
                raise ValueError("legacy counter call must not include P2B stream authority")
            _validate_legacy_specialist_counter_episode(lineage.get("episode"), active_expert=active_expert)
        candidate_parameters = manifest.get("expert_parameter_sha256")
        parent_parameters = parent_external.get("expert_parameter_sha256", parent_external.get("expert_genesis_sha256"))
        root_parameters = root_external.get("expert_parameter_sha256", root_external.get("expert_genesis_sha256"))
        candidate_files = manifest.get("expert_checkpoint_sha256")
        parent_files = parent_external.get("expert_checkpoint_sha256")
        history = lineage.get("trained_expert_ids")
        if (not isinstance(candidate_parameters, dict) or set(candidate_parameters) != set(EXPERT_NAMES)
                or not isinstance(parent_parameters, dict) or set(parent_parameters) != set(EXPERT_NAMES)
                or not isinstance(root_parameters, dict) or set(root_parameters) != set(EXPERT_NAMES)
                or not isinstance(candidate_files, dict) or not isinstance(parent_files, dict)
                or history != expected_history):
            raise ValueError("specialist v4 lineage lacks closed expert accretion fields")
        for name in EXPERT_NAMES:
            _sha256_value(candidate_parameters[name], label=f"candidate {name} parameter hash")
        if candidate_parameters[active_expert] == parent_parameters[active_expert]:
            raise ValueError("active expert parameter content does not differ from parent")
        for name in EXPERT_NAMES:
            if name == active_expert:
                continue
            if candidate_files.get(name) != parent_files.get(name):
                raise ValueError(f"inactive expert file does not match parent: {name}")
            if candidate_parameters[name] != parent_parameters[name]:
                raise ValueError(f"inactive expert parameter content does not match parent: {name}")
            if name not in history and candidate_parameters[name] != root_parameters[name]:
                raise ValueError(f"untrained expert parameter content does not match root: {name}")
    _counter_bytes, counter_sha256 = _read_bytes_snapshot(Path(__file__), label="counter source")
    if manifest.get("model_config_sha256") != config_sha256:
        raise ValueError("checkpoint model-config hash mismatch")
    return validate_realization_receipt({
        "schema_version": "ember-sparse-realization-receipt-v1",
        "verification_boundary": "VERIFIED_MEASURED",
        "result": "MEASURED",
        "model_config_sha256": config_sha256,
        "subject_checkpoint_sha256": subject_checkpoint_sha256,
        "architecture_revision": ARCHITECTURE_REVISION,
        "counter_sha256": counter_sha256,
        **_counts(shape, active_expert=active_expert),
        "active_expert_ids": [active_expert],
        "expert_genesis_sha256": dict(manifest["expert_genesis_sha256"]),
        "expert_parameter_sha256": dict(manifest.get("expert_parameter_sha256", manifest["expert_genesis_sha256"])),
        "runtime_authority": runtime_authority,
    })


def measure_parameter_counts(model: Any) -> dict[str, Any]:
    """Measure total allocated capacity and one active episode path in-process."""

    from ember.model.ember_v0_decoder import CIADecoder
    if type(model) is CIADecoder:
        parameters = model.parameter_inventory()
        total = sum(value.numel() for value in parameters.values())
        active = sum(value.numel() for value in parameters.values() if value.requires_grad)
        return dict(allocated_parameters=total,unique_parameters=total,trainable_parameters=total,
            served_parameters=total,active_parameters=active,episode_trainable_parameters=active,
            active_expert_ids=[str(i) for i in range(25) if any(name.startswith(f'experts.{i}.') and value.requires_grad for name,value in parameters.items())])
    total = model.count_unique_trainable_parameters(include_frozen=True)
    active = model.count_unique_trainable_parameters()
    return {
        "allocated_parameters": total,
        "unique_parameters": total,
        "trainable_parameters": total,
        "served_parameters": total,
        "active_parameters": active,
        "episode_trainable_parameters": active,
        "active_expert_ids": [model.active_expert],
    }


def measure_dense_a1_parameter_counts(model: Any) -> dict[str, Any]:
    """Measure the distinct dense carrier without sparse-route semantics."""

    # issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/a1_dense.py
    import importlib.util as _ember_55fe345b239cef3d_importlib
    import sys as _ember_55fe345b239cef3d_sys
    from pathlib import Path as _ember_55fe345b239cef3d_Path
    _ember_55fe345b239cef3d_path = _ember_55fe345b239cef3d_Path(__file__).resolve().parent.joinpath('a1_dense.py')
    if not _ember_55fe345b239cef3d_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/a1_dense.py')
    _ember_55fe345b239cef3d_aliases = ('_ember_issue2015_55fe345b239cef3d', 'a1_dense', 'src.ember.infrastructure.tools.ember-restart-3b.a1_dense')
    _ember_55fe345b239cef3d_existing = []
    for _ember_55fe345b239cef3d_alias in _ember_55fe345b239cef3d_aliases:
        _ember_55fe345b239cef3d_candidate = _ember_55fe345b239cef3d_sys.modules.get(_ember_55fe345b239cef3d_alias)
        if _ember_55fe345b239cef3d_candidate is not None and all(_ember_55fe345b239cef3d_candidate is not item for item in _ember_55fe345b239cef3d_existing):
            _ember_55fe345b239cef3d_existing.append(_ember_55fe345b239cef3d_candidate)
    if len(_ember_55fe345b239cef3d_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/a1_dense.py')
    if _ember_55fe345b239cef3d_existing:
        _ember_55fe345b239cef3d_module = _ember_55fe345b239cef3d_existing[0]
        _ember_55fe345b239cef3d_observed = getattr(_ember_55fe345b239cef3d_module, '__file__', None)
        if _ember_55fe345b239cef3d_observed is None or _ember_55fe345b239cef3d_Path(_ember_55fe345b239cef3d_observed).resolve() != _ember_55fe345b239cef3d_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/a1_dense.py')
    else:
        _ember_55fe345b239cef3d_spec = _ember_55fe345b239cef3d_importlib.spec_from_file_location('_ember_issue2015_55fe345b239cef3d', _ember_55fe345b239cef3d_path)
        if _ember_55fe345b239cef3d_spec is None or _ember_55fe345b239cef3d_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/a1_dense.py')
        _ember_55fe345b239cef3d_module = _ember_55fe345b239cef3d_importlib.module_from_spec(_ember_55fe345b239cef3d_spec)
        for _ember_55fe345b239cef3d_alias in _ember_55fe345b239cef3d_aliases:
            _ember_55fe345b239cef3d_prior = _ember_55fe345b239cef3d_sys.modules.get(_ember_55fe345b239cef3d_alias)
            if _ember_55fe345b239cef3d_prior is not None and _ember_55fe345b239cef3d_prior is not _ember_55fe345b239cef3d_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/a1_dense.py')
            _ember_55fe345b239cef3d_sys.modules[_ember_55fe345b239cef3d_alias] = _ember_55fe345b239cef3d_module
        try:
            _ember_55fe345b239cef3d_spec.loader.exec_module(_ember_55fe345b239cef3d_module)
        except BaseException:
            for _ember_55fe345b239cef3d_alias in _ember_55fe345b239cef3d_aliases:
                if _ember_55fe345b239cef3d_sys.modules.get(_ember_55fe345b239cef3d_alias) is _ember_55fe345b239cef3d_module:
                    _ember_55fe345b239cef3d_sys.modules.pop(_ember_55fe345b239cef3d_alias, None)
            raise
    for _ember_55fe345b239cef3d_alias in _ember_55fe345b239cef3d_aliases:
        _ember_55fe345b239cef3d_prior = _ember_55fe345b239cef3d_sys.modules.get(_ember_55fe345b239cef3d_alias)
        if _ember_55fe345b239cef3d_prior is not None and _ember_55fe345b239cef3d_prior is not _ember_55fe345b239cef3d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/a1_dense.py')
        _ember_55fe345b239cef3d_sys.modules[_ember_55fe345b239cef3d_alias] = _ember_55fe345b239cef3d_module
    DenseA1Decoder = getattr(_ember_55fe345b239cef3d_module, 'DenseA1Decoder')
    # issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/a1_dense.py

    if not isinstance(model, DenseA1Decoder):
        raise ValueError("dense A1 counter requires DenseA1Decoder")
    named = list(model.named_parameters())
    if len({id(parameter) for _, parameter in named}) != len(named):
        raise ValueError("dense A1 live parameter inventory contains aliases")
    unique = sum(parameter.numel() for _, parameter in named)
    structural = model.config.structural_parameter_count()
    if unique != structural:
        raise ValueError("dense A1 live parameter inventory differs from structure")
    return {
        "schema_version": "ember-a1-dense-parameter-inventory-v1",
        "architecture_revision": "ember-dense-a1-3b-v1",
        "unique_parameters": unique,
        "trainable_parameters": sum(
            parameter.numel() for _, parameter in named if parameter.requires_grad
        ),
        "active_parameters": unique,
        "contains_router_or_experts": False,
        "parameter_tensors": len(named),
    }


def write_parameter_receipt(
    model: Any,
    config_path: Path,
    checkpoint_manifest_path: Path,
    expert_genesis_sha256: dict[str, str],
) -> dict[str, Any]:
    """Emit an in-process receipt; production must also execute this file under -I."""

    counts = measure_parameter_counts(model)
    return {
        "schema_version": "ember-sparse-parameter-receipt-v1",
        "result": "MEASURED",
        "model_config_sha256": _sha256(config_path),
        "counter_sha256": _read_bytes_snapshot(Path(__file__), label="counter source")[1],
        "subject_checkpoint_sha256": _sha256(checkpoint_manifest_path),
        "architecture_revision": ARCHITECTURE_REVISION,
        **counts,
        "expert_genesis_sha256": dict(expert_genesis_sha256),
    }


def _cia_counter_path(root, relative):
    path = root / relative
    current = path
    while True:
        metadata = current.lstat()
        if current.is_symlink() or getattr(metadata,'st_file_attributes',0) & 0x400:
            raise ValueError('CIA checkpoint path is a symlink or reparse point')
        if current == root: break
        current = current.parent
    return path


@contextmanager
def _cia_counter_component(root, relative, record):
    """Inspect the exact bounded object snapshot through the existing ZIP reader."""
    path = _cia_counter_path(root,relative)
    if type(record.get('bytes')) is not int or record['bytes'] < 1:
        raise ValueError('CIA checkpoint component byte bound mismatch')
    with path.open('rb') as handle:
        raw = handle.read(record['bytes'] + 1)
    if len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError('CIA checkpoint component digest mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if (len({entry.filename for entry in entries}) != len(entries)
                or any(entry.compress_type != zipfile.ZIP_STORED for entry in entries)
                or sum(entry.file_size for entry in entries) > len(raw)):
            raise ValueError('CIA checkpoint ZIP storage exceeds its bound')
        yield archive, _load_checkpoint_metadata(archive)


def _cia_counter_tensor(archive, tensor, shape, storage_type):
    if (not isinstance(tensor,_TensorMetadata) or tensor.shape != shape
            or tensor.storage.storage_type != storage_type):
        raise ValueError('CIA tensor inventory mismatch')
    return _tensor_raw_bytes(archive,tensor)


def _cia_parent_snapshot(parent_checkpoint, *, max_restore_payload_bytes, expected_digest=None):
    """Reopen an admitted zero-step CIA parent using the existing byte counter."""
    parent_root = Path(parent_checkpoint)
    if not parent_root.is_absolute() or parent_root.resolve(strict=True) != parent_root:
        raise ValueError('CIA parent checkpoint requires its canonical absolute path')
    path = _cia_counter_path(parent_root, 'checkpoint-manifest.json')
    with path.open('rb') as handle: raw = handle.read(1048577)
    if len(raw) > 1048576: raise ValueError('CIA parent manifest exceeds its byte bound')
    parent = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        raise ValueError('CIA parent manifest digest differs from its bound identity')
    if (parent.get('schema_version') != 'ember-cia-checkpoint-v1' or 'lineage' in parent
            or parent.get('genesis_provenance') != {'kind':'ZERO_STEP_OBJECT_BINDING','independently_qualified':False}
            or parent.get('data_cursor',{}).get('global_step') != 0
            or parent.get('data_cursor',{}).get('tokens_seen') != 0):
        raise ValueError('CIA first descendant requires an admitted zero-step parent')
    cap = parent.get('max_restore_payload_bytes')
    if type(cap) is not int or cap < 1 or type(max_restore_payload_bytes) is not int or cap > max_restore_payload_bytes:
        raise ValueError('CIA parent exceeds the explicit caller restore byte bound')
    persisted_path = parent_root / 'parameter-counter-receipt.json'
    if not persisted_path.is_file(): raise ValueError('CIA first descendant requires an admitted parent counter receipt')
    _cia_counter_path(parent_root, 'parameter-counter-receipt.json')
    with persisted_path.open('rb') as handle: persisted_raw = handle.read(1048577)
    if len(persisted_raw) > 1048576: raise ValueError('CIA parent counter receipt exceeds its byte bound')
    persisted = validate_realization_receipt(json.loads(persisted_raw))
    parent = dict(parent, checkpoint_manifest_sha256=digest)
    facts = {}
    measured = _cia_realization_receipt(parent_root, parent,
        model_config_sha256=parent['model_config_sha256'], _facts=facts, _allow_descendant=False)
    if measured != persisted:
        raise ValueError('CIA admitted parent counter receipt differs from reopened bytes')
    parent['_parent_counter_receipt_sha256'] = hashlib.sha256(persisted_raw).hexdigest()
    return parent, facts


def _cia_derive_first_lineage(parent_root, parent, parent_facts, child, child_facts, *, owner_update_counts=None):
    """Derive one mechanical transition from reopened parent state and child bytes."""
    for name in ('architecture_config','model_config_sha256','contract_sha256','launch_seed','optimizer_identity','placement'):
        if child.get(name) != parent.get(name): raise ValueError('CIA parent and child '+name+' differ')
    old, new = parent['data_cursor'], child['data_cursor']
    if any(type(cursor.get(name)) is not int or cursor[name] < 0
           for cursor in (old,new) for name in ('global_step','tokens_seen')):
        raise ValueError('CIA parent and child cursor counters must be nonnegative integers')
    step_delta, token_delta = new['global_step']-old['global_step'], new['tokens_seen']-old['tokens_seen']
    if step_delta <= 0 or token_delta < 0: raise ValueError('CIA descendant cursor must advance step without decreasing tokens')
    if child['expert_genesis_sha256'] != parent['expert_genesis_sha256']:
        raise ValueError('CIA descendant genesis differs from the reopened parent')
    if set(child_facts['parameters']) != set(parent_facts['parameters']):
        raise ValueError('CIA descendant parameter inventory differs from parent')
    recorded_counts = owner_update_counts
    if recorded_counts is None:
        recorded_counts = child.get('lineage', {}).get('owner_update_counts')
    updated, changed, owner_update_counts = [], [], {}
    for name in sorted(parent_facts['parameters']):
        before = parent_facts['optimizer'].get(name,{})
        after = child_facts['optimizer'].get(name,{})
        before_step, after_step = before.get('step',0), after.get('step',0)
        if (type(before_step) not in (int, float) or type(after_step) not in (int, float)
                or not 0 <= before_step <= 2**24 or not 0 <= after_step <= 2**24
                or before_step != int(before_step) or after_step != int(after_step)):
            raise ValueError('CIA descendant requires exact bounded optimizer clocks')
        owner_delta = int(after_step - before_step)
        if owner_delta < 0 or owner_delta > step_delta:
            raise ValueError('CIA descendant owner clock exceeds the observed step interval')
        if owner_delta > 0:
            if not child['placement'][name]['requires_grad']:
                raise ValueError('CIA frozen parameter has optimizer update support')
            updated.append(name)
            owner_update_counts[name] = owner_delta
        elif after != before:
            raise ValueError('CIA descendant optimizer clock or inactive state differs from parent')
        if child_facts['parameters'][name] != parent_facts['parameters'][name]:
            if name not in updated: raise ValueError('CIA inactive parameter bytes differ from parent')
            changed.append(name)
    if not updated or not changed: raise ValueError('CIA descendant requires actual optimizer and parameter update support')
    sparse = any(count != step_delta for count in owner_update_counts.values())
    if sparse or recorded_counts is not None:
        if (type(recorded_counts) is not dict or any(type(value) is not int for value in recorded_counts.values())
                or recorded_counts != owner_update_counts):
            raise ValueError('recorded per-owner update counts differ from reopened optimizer clocks')
    return {**({'owner_update_counts': owner_update_counts} if sparse else {}),
        'schema_version':'ember-cia-first-descendant-v2' if sparse else 'ember-cia-first-descendant-v1','parent_checkpoint':str(parent_root),
        'parent_manifest_sha256':parent['checkpoint_manifest_sha256'],
        'parent_counter_receipt_sha256':parent['_parent_counter_receipt_sha256'],
        'step_delta':step_delta,'token_delta':token_delta,'updated_parameters':updated,
        'updated_parameter_elements':sum(child_facts['elements'][name] for name in updated),
        'changed_parameters':changed,'changed_parameter_elements':sum(child_facts['elements'][name] for name in changed)}


def _cia_realization_receipt(root, receipt, *, model_config_sha256, _facts=None, _allow_descendant=True):
    """Measure CIA objects with the existing isolated, standard-library counter.

    No torch import, model allocation, or qualification is needed to inspect
    full-population serialized tensor metadata and its exact storage bytes.
    """
    from math import prod
    source_root = Path(__file__).resolve().parents[4]
    if str(source_root) not in sys.path: sys.path.insert(0,str(source_root))
    from ember.model.ember_v0_contract import validate_cia_architecture, cia_architecture_sha256
    from ember.model.ember_v0_inventory import equation_inventory
    root = Path(root)
    path = _cia_counter_path(root,'checkpoint-manifest.json')
    with path.open('rb') as handle: raw = handle.read(1048577)
    if len(raw) > 1048576 or hashlib.sha256(raw).hexdigest() != receipt['checkpoint_manifest_sha256']:
        raise ValueError('CIA counter manifest snapshot mismatch')
    manifest = json.loads(raw)
    if any(receipt.get(key) != value for key,value in manifest.items()):
        raise ValueError('CIA counter manifest differs from its snapshot')
    descendant = 'lineage' in manifest
    if descendant and not _allow_descendant: raise ValueError('CIA first descendant requires a zero-step parent')
    fields = {'schema_version','architecture_revision','architecture_config','architecture','launch_seed',
        'rng_state_sha256','data_cursor','model_config_sha256','contract_sha256','expert_genesis_sha256',
        'expert_parameter_sha256','active_expert_ids','core','expert_index','optimizer','replay',
        'optimizer_identity','placement','max_restore_payload_bytes','genesis_provenance','qualification'} | ({'lineage'} if descendant else set())
    if set(manifest) != fields or manifest['schema_version'] != 'ember-cia-checkpoint-v1' or manifest['architecture_revision'] != 'CIA3-R1-N61':
        raise ValueError('CIA counter manifest schema mismatch')
    validate_cia_architecture(manifest['architecture_config'])
    architecture_digest = cia_architecture_sha256(manifest['architecture_config'])
    if manifest['model_config_sha256'] != model_config_sha256:
        raise ValueError('CIA counter config digest differs from checkpoint')
    if manifest['genesis_provenance'] != {'kind':'VERIFIED_ZERO_STEP_PARENT' if descendant else 'ZERO_STEP_OBJECT_BINDING','independently_qualified':False}:
        raise ValueError('CIA counter requires unqualified object provenance')
    if manifest['qualification'] != {'clean_genesis':False,'trained':False,'served':False}:
        raise ValueError('CIA checkpoint bytes cannot grant model qualification')
    if not descendant and (manifest['data_cursor'].get('global_step') != 0 or manifest['data_cursor'].get('tokens_seen') != 0):
        raise ValueError('CIA counter descendants require verified parent lineage')
    index = manifest['expert_index']
    if set(index) != {'path','sha256','bytes','expert_object_bytes'} or index['path'] != 'expert-index-'+_sha256_value(index['sha256'],label='CIA index')+'.json':
        raise ValueError('CIA counter expert index record mismatch')
    with _cia_counter_path(root,index['path']).open('rb') as handle: index_raw=handle.read(65537)
    if len(index_raw)>65536 or len(index_raw)!=index['bytes'] or hashlib.sha256(index_raw).hexdigest()!=index['sha256']:
        raise ValueError('CIA counter expert index digest mismatch')
    population=json.loads(index_raw)
    if (set(population)!={'schema_version','candidate_revision','experts'}
            or population['schema_version']!='ember-cia-expert-index-v1' or population['candidate_revision']!='CIA3-R1-N61'
            or type(population['experts']) is not list or len(population['experts'])!=25):
        raise ValueError('CIA counter requires all 25 expert objects')
    records=population['experts']
    for expert_id,record in enumerate(records):
        if (set(record)!={'expert_id','sha256','bytes'} or type(record['expert_id']) is not int or record['expert_id']!=expert_id
                or type(record['bytes']) is not int or not 1<=record['bytes']<=113246208*2+4194304):
            raise ValueError('CIA counter expert object record mismatch')
        _sha256_value(record['sha256'],label='CIA expert object')
    if len({record['sha256'] for record in records})!=25 or sum(record['bytes'] for record in records)!=index['expert_object_bytes']:
        raise ValueError('CIA counter expert index identity or byte arithmetic mismatch')
    core=manifest['core']
    if (set(core)!={'sha256','bytes','architecture_sha256'} or core['architecture_sha256']!=architecture_digest
            or type(core['bytes']) is not int or not 1<=core['bytes']<=251383808*2+4194304):
        raise ValueError('CIA counter core object record mismatch')
    _sha256_value(core['sha256'],label='CIA core object')
    for kind,name in (('optimizer','optimizer-state.pt'),('replay','replay-state.pt')):
        record=manifest[kind]
        if set(record)!={'path','sha256','bytes'} or record['path']!=name or type(record['bytes']) is not int or record['bytes']<1:
            raise ValueError('CIA counter state object record mismatch')
        _sha256_value(record['sha256'],label='CIA state object')
    if (type(manifest['max_restore_payload_bytes']) is not int or sum(record['bytes'] for record in [core,*records,manifest['optimizer'],manifest['replay']])>manifest['max_restore_payload_bytes']):
        raise ValueError('CIA counter checkpoint restore byte arithmetic mismatch')
    expected={'checkpoint-manifest.json',index['path'],'optimizer-state.pt','replay-state.pt',
        *('objects/'+record['sha256']+'.pt' for record in [core,*records])}
    actual=set()
    for item in root.rglob('*'):
        relative=item.relative_to(root).as_posix()
        _cia_counter_path(root,relative)
        if item.is_dir():
            if relative!='objects': raise ValueError('CIA counter directory closure mismatch')
        else: actual.add(relative)
    if actual-{'parameter-counter-receipt.json'}!=expected:
        raise ValueError('CIA counter requires exact complete object closure')
    specs=equation_inventory()
    inventory={spec.name:spec.shape for spec in specs}
    facts={'parameters':{},'elements':{name:prod(shape) for name,shape in inventory.items()},'optimizer':{}}
    for expert_id,record in [(None,core),*enumerate(records)]:
        with _cia_counter_component(root,'objects/'+record['sha256']+'.pt',record) as (archive,payload):
            if expert_id is None:
                if set(payload)!={'schema_version','architecture_sha256','model'} or payload['schema_version']!='ember-cia-core-object-v1' or payload['architecture_sha256']!=architecture_digest:
                    raise ValueError('CIA counter core payload mismatch')
            elif (set(payload)!={'schema_version','candidate_revision','expert_id','model'} or payload['schema_version']!='ember-cia-expert-object-v1'
                    or payload['candidate_revision']!='CIA3-R1-N61' or payload['expert_id']!=expert_id):
                raise ValueError('CIA counter expert payload mismatch')
            shapes={spec.name:spec.shape for spec in specs if spec.expert==expert_id}
            state=payload['model']
            if set(state)!=set(shapes): raise ValueError('CIA tensor inventory mismatch')
            storage=set()
            for name,tensor in state.items():
                raw = _cia_counter_tensor(archive,tensor,shapes[name],'BFloat16Storage')
                facts['parameters'][name] = hashlib.sha256(raw).hexdigest()
                if tensor.storage.key in storage: raise ValueError('CIA counter parameter storage alias')
                storage.add(tensor.storage.key)
    placement=manifest['placement']
    if set(placement)!=set(inventory): raise ValueError('CIA counter placement inventory mismatch')
    for entry in placement.values():
        if set(entry)!={'device','requires_grad'} or type(entry['requires_grad']) is not bool:
            raise ValueError('CIA counter placement record mismatch')
    identity=manifest['optimizer_identity']
    groups={}
    for group in identity['param_groups']:
        for name in group['params']:
            if name in groups: raise ValueError('CIA counter duplicate optimizer membership')
            groups[name]=group['hyperparameters']
    if set(groups)!=set(inventory): raise ValueError('CIA counter optimizer full membership mismatch')
    with _cia_counter_component(root,'optimizer-state.pt',manifest['optimizer']) as (archive,payload):
        if (set(payload)!={'schema_version','identity','placement','master_weights','state'} or payload['schema_version']!='ember-cia-placed-optimizer-state-v2'
                or payload['identity']!=identity or payload['placement']!=placement or payload['master_weights'] is not None):
            raise ValueError('CIA counter native optimizer identity mismatch')
        for name,state in payload['state'].items():
            if name not in inventory or type(state) is not dict: raise ValueError('CIA counter optimizer state membership mismatch')
            if not state: continue
            observed={}
            required={'step','exp_avg','exp_avg_sq'} | ({'max_exp_avg_sq'} if groups[name]['amsgrad'] else set())
            if set(state)!=required: raise ValueError('CIA counter native optimizer fields mismatch')
            for key,tensor in state.items():
                raw = _cia_counter_tensor(archive,tensor,() if key=='step' else inventory[name], 'FloatStorage' if key=='step' else 'BFloat16Storage')
                if key == 'step':
                    import math, struct
                    step = struct.unpack('<f',raw)[0]
                    if not math.isfinite(step) or step < 0 or not step.is_integer(): raise ValueError('CIA native optimizer clock mismatch')
                    observed[key] = int(step)
                else: observed[key] = hashlib.sha256(raw).hexdigest()
            facts['optimizer'][name]=observed
    with _cia_counter_component(root,'replay-state.pt',manifest['replay']) as (archive,payload):
        if set(payload)!={'rng_state','data_cursor'} or payload['data_cursor']!=manifest['data_cursor'] or set(payload['rng_state'])!={'cpu','cuda'}:
            raise ValueError('CIA counter replay binding mismatch')
        for name,tensor in payload['rng_state'].items():
            if not isinstance(tensor,_TensorMetadata) or len(tensor.shape)!=1: raise ValueError('CIA counter RNG tensor mismatch')
            raw=_cia_counter_tensor(archive,tensor,tensor.shape,'ByteStorage')
            if hashlib.sha256(raw).hexdigest()!=manifest['rng_state_sha256'][name]: raise ValueError('CIA counter RNG digest mismatch')
    objects={str(i):record['sha256'] for i,record in enumerate(records)}
    if manifest['expert_parameter_sha256']!=objects or (not descendant and manifest['expert_genesis_sha256']!=objects):
        raise ValueError('CIA counter expert object identity mismatch')
    if descendant:
        lineage=manifest['lineage']
        if type(lineage) is not dict: raise ValueError('CIA descendant lineage schema mismatch')
        parent_root=Path(lineage.get('parent_checkpoint',''))
        parent,parent_facts=_cia_parent_snapshot(parent_root,max_restore_payload_bytes=manifest['max_restore_payload_bytes'],
            expected_digest=lineage.get('parent_manifest_sha256'))
        if lineage != _cia_derive_first_lineage(parent_root,parent,parent_facts,manifest,facts):
            raise ValueError('CIA descendant lineage differs from reopened parent and child bytes')
    total=sum(prod(shape) for shape in inventory.values())
    active=sum(prod(shape) for name,shape in inventory.items() if placement[name]['requires_grad'])
    counts=dict(allocated_parameters=total,unique_parameters=total,trainable_parameters=total,
        served_parameters=total,active_parameters=active,episode_trainable_parameters=active)
    routes=[str(i) for i in range(25) if any(spec.expert==i and placement[spec.name]['requires_grad'] for spec in specs)]
    if counts!=manifest['architecture'] or routes!=manifest['active_expert_ids']:
        raise ValueError('CIA counter measured capacity or update support mismatch')
    if _facts is not None: _facts.update(facts)
    return validate_realization_receipt(dict(schema_version='ember-cia-realization-receipt-v1',
        verification_boundary='VERIFIED_MEASURED',result='MEASURED',architecture_revision='CIA3-R1-N61',
        model_config_sha256=model_config_sha256,subject_checkpoint_sha256=receipt['checkpoint_manifest_sha256'],
        counter_sha256=_sha256(Path(__file__)),**counts,active_expert_ids=routes,
        expert_genesis_sha256=dict(manifest['expert_genesis_sha256']),expert_parameter_sha256=objects,
        runtime_authority=dict(_RUNTIME_AUTHORITY_NONE),qualification=dict(manifest['qualification'])))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect a sparse checkpoint realization and emit its measured capacity.")
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--checkpoint-manifest", type=Path, required=True)
    parser.add_argument("--active-expert", required=True)
    parser.add_argument("--parent-manifest", type=Path)
    parser.add_argument("--root-manifest", type=Path)
    parser.add_argument("--p2b-repo-root", type=Path)
    parser.add_argument("--p2b-stream-manifest", type=Path)
    parser.add_argument("--p2b-stream-build-receipt", type=Path)
    parser.add_argument("--p2b-tokenizer-runtime-root", type=Path)
    parser.add_argument("--p2b-tokenizer-runtime-manifest", type=Path)
    parser.add_argument("--expert-genesis-authority", type=Path)
    parser.add_argument("--expert-genesis-authority-sha256")
    args = parser.parse_args(argv)
    try:
        counter_kwargs = {
            "model_config": args.model_config,
            "checkpoint_manifest": args.checkpoint_manifest,
            "active_expert": args.active_expert,
            "parent_manifest": args.parent_manifest,
            "root_manifest": args.root_manifest,
            "p2b_repo_root": args.p2b_repo_root,
            "p2b_stream_manifest": args.p2b_stream_manifest,
            "p2b_stream_build_receipt": args.p2b_stream_build_receipt,
            "p2b_tokenizer_runtime_root": args.p2b_tokenizer_runtime_root,
            "p2b_tokenizer_runtime_manifest": args.p2b_tokenizer_runtime_manifest,
        }
        if args.expert_genesis_authority is not None or args.expert_genesis_authority_sha256 is not None:
            counter_kwargs.update(
                expert_genesis_authority=args.expert_genesis_authority,
                expert_genesis_authority_sha256=args.expert_genesis_authority_sha256,
            )
        print(json.dumps(execute_counter(**counter_kwargs), sort_keys=True))
    except Exception as error:
        print(f"parameter realization failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
