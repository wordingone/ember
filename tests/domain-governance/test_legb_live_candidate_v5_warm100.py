# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import copy
import sys
import types
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCORER = next(
    candidate
    for candidate in (
        ROOT / "src" / "ember" / "governance" / "scripts" / "legb_live_candidate_v5_scorer.py",
        ROOT / "scripts" / "legb_live_candidate_v5_scorer.py",
    )
    if candidate.is_file()
)


def _load():
    # These tests exercise the scorer's byte-authority seam only. Keep the
    # fixture independent of a 3.84B model runtime and lm_eval installation.
    stubs = {
        "torch": types.ModuleType("torch"),
        "legb_inprocess_scorer": types.ModuleType("legb_inprocess_scorer"),
        "receipt_write": types.ModuleType("receipt_write"),
        "receipt_check": types.ModuleType("receipt_check"),
    }
    stubs["torch"].Tensor = object
    stubs["legb_inprocess_scorer"].LegBLM = object
    stubs["legb_inprocess_scorer"].load_verified_tokenizer = object
    stubs["legb_inprocess_scorer"].device_lease = object
    stubs["legb_inprocess_scorer"].TOKENIZER_EXPECTED_SHA256 = "f" * 64
    stubs["legb_inprocess_scorer"].SHA_CONVENTION = "fixture"
    stubs["receipt_write"].checked_write = object
    stubs["receipt_check"].INVARIANT_SHA256 = "e" * 64
    missing = object()
    prior = {name: sys.modules.get(name, missing) for name in stubs}
    try:
        sys.modules.update(stubs)
        spec = importlib.util.spec_from_file_location("legb_live_candidate_v5_scorer", SCORER)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in prior.items():
            if previous is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _checkpoint(
    module, root: Path, *, step: int = 100, tag: bytes = b"a",
    publisher_accounting: bool = False, owner_optimizer: bool = False,
) -> tuple[Path, dict]:
    root.mkdir()
    records = []
    shard_sha = {}
    optimizer_name = "optimizer-state-shared.pt" if owner_optimizer else "optimizer-state.pt"
    for index, name in enumerate((*module.MODEL_SHARDS, optimizer_name, "replay-state.pt")):
        path = root / name
        path.write_bytes(tag + bytes([index]))
        digest = _sha(path)
        shard_sha[name] = digest
        records.append({
            "path": name,
            "sha256": digest,
            "bytes": path.stat().st_size,
            "incremental_bytes": path.stat().st_size,
        })
    cursor = {
        "shard": "semantic-fixture",
        "record_index": step,
        "receipt_sha256": "c" * 64,
        "tokenizer_sha256": "d" * 64,
        "shard_index": 0,
        "token_offset": step * 1024,
        "global_step": step,
        "tokens_seen": step * 1024,
        "governor": {"schema_version": "ember-runtime-governor-v1"},
    }
    manifest = {
        "schema_version": module.SUPPORTED_CHECKPOINT_SCHEMA,
        "shards": records,
        "shared_model_shard_sha256": shard_sha["shared-model.pt"],
        "expert_checkpoint_sha256": {
            name: shard_sha[f"expert-{name}.pt"] for name in module.EXPERTS
        },
        "model_config_sha256": _sha(ROOT / module.MODEL_CONFIG_REL),
        "data_cursor": cursor,
        "active_expert_ids": ["tool"],
        "architecture_revision": "ember-sparse-3b-v2",
        "contract_version": 5,
        "launch_seed": 830013,
    }
    if owner_optimizer:
        manifest["optimizer_state_owner_ids"] = ["shared"]
        manifest["optimizer_state_owner_shard_sha256"] = {
            "shared": shard_sha[optimizer_name]
        }
    else:
        manifest["optimizer_state_shard_sha256"] = shard_sha[optimizer_name]
    _write_json(root / "checkpoint-manifest.json", manifest)
    published = {
        **manifest,
        "checkpoint_manifest_sha256": _sha(root / "checkpoint-manifest.json"),
        "checkpoint": {"byte_sha256": _sha(root / "checkpoint-manifest.json")},
    }
    if publisher_accounting:
        counter_path = root / "parameter-counter-receipt.json"
        counter_path.write_bytes(b'{"status":"PASS"}\n')
        metadata = {
            counter_path.name: {
                "bytes": counter_path.stat().st_size,
                "sha256": _sha(counter_path),
            }
        }
        manifest_bytes = (root / "checkpoint-manifest.json").stat().st_size
        metadata_bytes = counter_path.stat().st_size
        serialized_bytes = (
            sum(record["bytes"] for record in records)
            + manifest_bytes
            + metadata_bytes
        )
        incremental_bytes = (
            sum(record["incremental_bytes"] for record in records)
            + manifest_bytes
            + metadata_bytes
        )
        published.update({
            "metadata": metadata,
            "serialized_bytes": serialized_bytes,
            "incremental_publication_bytes": incremental_bytes,
            "retention_accounting": {
                "schema_version": "ember-checkpoint-retention-accounting-v1",
                "live_budget_bytes": 2 * serialized_bytes,
                "live_charged_bytes": serialized_bytes,
                "quarantine_budget_bytes": 2 * serialized_bytes,
                "quarantine_charged_bytes": 0,
            },
        })
    return root, published


def _run_receipt(path: Path, published: dict) -> str:
    cursor = published["data_cursor"]
    segment_cursor = {
        key: value for key, value in cursor.items()
        if key not in {"governor", "resume_authority"}
    }
    step = cursor["global_step"]
    _write_json(
        path,
        {
            "post_step_checkpoint": published,
            "resume_authority": None,
            "segment": {
                "steps": step,
                "global_step": step,
                "tokens_seen": cursor["tokens_seen"],
                "data_cursor": segment_cursor,
                "losses": [1.0] * step,
            },
        },
    )
    return _sha(path)


def test_exact_warm100_receipt_reopened_and_boundary_derived(tmp_path: Path) -> None:
    module = _load()
    checkpoint, published = _checkpoint(module, tmp_path / "warm100")
    receipt = tmp_path / "certified-child-result.json"
    receipt_sha = _run_receipt(receipt, published)

    verified = module.load_verified_warm100_checkpoint(
        str(checkpoint), str(receipt), receipt_sha
    )

    assert verified["run_receipt_sha256"] == receipt_sha
    assert verified["global_step"] == 100
    assert verified["tokens_seen"] == 102400
    assert "global_step=100" in module.claim_boundary(verified)
    assert "tokens_seen=102400" in module.claim_boundary(verified)
    assert "HellaSwag split-alignment" not in module.claim_boundary(verified)
    assert "PENDING_FINAL_CORPUS_CONTAMINATION_SCAN" in module.claim_boundary(verified)


def test_v5_owner_optimizer_checkpoint_reopens(tmp_path: Path) -> None:
    module = _load()
    checkpoint, published = _checkpoint(
        module, tmp_path / "warm100", owner_optimizer=True
    )
    receipt = tmp_path / "certified-child-result.json"
    receipt_sha = _run_receipt(receipt, published)

    verified = module.load_verified_warm100_checkpoint(
        str(checkpoint), str(receipt), receipt_sha
    )

    assert verified["global_step"] == 100


@pytest.mark.parametrize(
    "mutate",
    [
        lambda doc: doc.pop("optimizer_state_owner_shard_sha256"),
        lambda doc: doc.__setitem__("optimizer_state_shard_sha256", "a" * 64),
        lambda doc: doc.__setitem__("optimizer_state_owner_shard_sha256", {}),
        lambda doc: doc.__setitem__("optimizer_state_owner_shard_sha256", []),
        lambda doc: doc.__setitem__("optimizer_state_owner_ids", ["vision"]),
        lambda doc: doc["optimizer_state_owner_shard_sha256"].__setitem__("shared", "A" * 64),
        lambda doc: doc["shards"][-2].__setitem__("sha256", "0" * 64),
    ],
    ids=["neither", "both", "empty", "not-object", "key-mismatch", "non-digest", "digest-mismatch"],
)
def test_closed_optimizer_union_refuses_every_invalid_shape(
    tmp_path: Path, mutate
) -> None:
    module = _load()
    checkpoint, _published = _checkpoint(
        module, tmp_path / "warm100", owner_optimizer=True
    )
    manifest_path = checkpoint / "checkpoint-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(manifest)
    _write_json(manifest_path, manifest)

    with pytest.raises(module.LiveCandidateRefusal, match="OPTIMIZER_STATE_SCHEMA_INVALID"):
        module.load_verified_v5_checkpoint(str(checkpoint))


def test_current_publisher_accounting_receipt_reopened(tmp_path: Path) -> None:
    module = _load()
    checkpoint, published = _checkpoint(
        module, tmp_path / "warm100", publisher_accounting=True
    )
    receipt = tmp_path / "certified-child-result.json"
    receipt_sha = _run_receipt(receipt, published)

    verified = module.load_verified_warm100_checkpoint(
        str(checkpoint), str(receipt), receipt_sha
    )

    assert verified["global_step"] == 100
    assert verified["tokens_seen"] == 102400


def test_checkpoint_writer_three_key_accounting_receipt_reopened(tmp_path: Path) -> None:
    module = _load()
    checkpoint, published = _checkpoint(
        module, tmp_path / "warm100", publisher_accounting=True
    )
    del published["retention_accounting"]
    receipt = tmp_path / "certified-child-result.json"
    receipt_sha = _run_receipt(receipt, published)

    verified = module.load_verified_warm100_checkpoint(
        str(checkpoint), str(receipt), receipt_sha
    )

    assert verified["global_step"] == 100


def test_current_publisher_receipt_refuses_fifth_outer_key(tmp_path: Path) -> None:
    module = _load()
    checkpoint, published = _checkpoint(
        module, tmp_path / "warm100", publisher_accounting=True
    )
    published["unexpected_accounting"] = 1
    receipt = tmp_path / "certified-child-result.json"
    receipt_sha = _run_receipt(receipt, published)

    with pytest.raises(module.LiveCandidateRefusal, match="RUN_RECEIPT_CHECKPOINT_MISMATCH"):
        module.load_verified_warm100_checkpoint(
            str(checkpoint), str(receipt), receipt_sha
        )


def test_current_publisher_receipt_refuses_missing_manifest_field(tmp_path: Path) -> None:
    module = _load()
    checkpoint, published = _checkpoint(
        module, tmp_path / "warm100", publisher_accounting=True
    )
    del published["launch_seed"]
    receipt = tmp_path / "certified-child-result.json"
    receipt_sha = _run_receipt(receipt, published)

    with pytest.raises(module.LiveCandidateRefusal, match="RUN_RECEIPT_CHECKPOINT_MISMATCH"):
        module.load_verified_warm100_checkpoint(
            str(checkpoint), str(receipt), receipt_sha
        )


def test_current_publisher_receipt_refuses_partial_accounting_shape(tmp_path: Path) -> None:
    module = _load()
    checkpoint, published = _checkpoint(
        module, tmp_path / "warm100", publisher_accounting=True
    )
    del published["serialized_bytes"]
    receipt = tmp_path / "certified-child-result.json"
    receipt_sha = _run_receipt(receipt, published)

    with pytest.raises(module.LiveCandidateRefusal, match="RUN_RECEIPT_CHECKPOINT_MISMATCH"):
        module.load_verified_warm100_checkpoint(
            str(checkpoint), str(receipt), receipt_sha
        )


@pytest.mark.parametrize(
    "field,mutate",
    [
        ("metadata", lambda value: value["metadata"]["parameter-counter-receipt.json"].update(bytes=999)),
        ("serialized_bytes", lambda value: value.update(serialized_bytes=value["serialized_bytes"] + 1)),
        ("incremental_publication_bytes", lambda value: value.update(incremental_publication_bytes=value["incremental_publication_bytes"] + 1)),
        ("retention_accounting", lambda value: value["retention_accounting"].update(live_charged_bytes=-1)),
    ],
)
def test_current_publisher_receipt_refuses_accounting_value_forgery(
    tmp_path: Path, field: str, mutate
) -> None:
    module = _load()
    checkpoint, published = _checkpoint(
        module, tmp_path / "warm100", publisher_accounting=True
    )
    forged = copy.deepcopy(published)
    mutate(forged)
    receipt = tmp_path / f"forged-{field}.json"
    receipt_sha = _run_receipt(receipt, forged)

    with pytest.raises(module.LiveCandidateRefusal, match="RUN_RECEIPT_CHECKPOINT_MISMATCH"):
        module.load_verified_warm100_checkpoint(
            str(checkpoint), str(receipt), receipt_sha
        )


@pytest.mark.parametrize("failure", ["subscale", "stale", "swap"])
def test_warm100_receipt_refuses_subscale_stale_and_swap(
    tmp_path: Path, failure: str
) -> None:
    module = _load()
    step = 99 if failure == "subscale" else 100
    checkpoint, published = _checkpoint(module, tmp_path / "subject", step=step)
    receipt_checkpoint = checkpoint
    if failure == "swap":
        receipt_checkpoint, published = _checkpoint(
            module, tmp_path / "other", tag=b"b"
        )
        assert receipt_checkpoint != checkpoint
    if failure == "stale":
        published["checkpoint_manifest_sha256"] = "0" * 64
        published["checkpoint"] = {"byte_sha256": "0" * 64}
    receipt = tmp_path / "certified-child-result.json"
    receipt_sha = _run_receipt(receipt, published)

    expected = {
        "subscale": "WARM100_BOUNDARY_REQUIRED",
        "stale": "RUN_RECEIPT_CHECKPOINT_MISMATCH",
        "swap": "RUN_RECEIPT_CHECKPOINT_MISMATCH",
    }[failure]
    with pytest.raises(module.LiveCandidateRefusal, match=expected):
        module.load_verified_warm100_checkpoint(
            str(checkpoint), str(receipt), receipt_sha
        )


def test_score_binding_requires_predictions_and_hashes_canonical_scores() -> None:
    module = _load()
    evaluation = {
        "raw_predictions": {
            "path": "predictions.jsonl",
            "rows": 2,
            "sha256": "a" * 64,
            "format": "jsonl; one row per scored eval item",
        },
        "results": {"arc_challenge": {"acc,none": 0.5}},
    }
    bound = module.bind_evaluation_artifacts(evaluation)
    assert bound["raw_predictions_sha256"] == "a" * 64
    assert bound["scores_sha256"] == hashlib.sha256(
        json.dumps(
            evaluation["results"], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert bound["prediction_score_binding_sha256"] == hashlib.sha256(
        json.dumps(
            {
                "raw_predictions_sha256": bound["raw_predictions_sha256"],
                "scores_sha256": bound["scores_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    evaluation["raw_predictions"] = None
    with pytest.raises(module.LiveCandidateRefusal, match="RAW_PREDICTIONS_REQUIRED"):
        module.bind_evaluation_artifacts(evaluation)


def test_score_binding_refuses_missing_scores() -> None:
    module = _load()
    with pytest.raises(module.LiveCandidateRefusal, match="SCORES_REQUIRED"):
        module.bind_evaluation_artifacts({
            "raw_predictions": {
                "path": "predictions.jsonl",
                "rows": 1,
                "sha256": "a" * 64,
                "format": "jsonl; one row per scored eval item",
            },
            "results": {},
        })


def test_evaluator_task_specs_pin_registered_hellaswag_and_refuse_unknown() -> None:
    module = _load()

    assert module.build_bound_task_specs(["arc_challenge", "hellaswag"]) == {
        "group": "ember_issue1433_bound_eval",
        "task": [
            "arc_challenge",
            {
                "task": "hellaswag",
                "dataset_kwargs": {
                    "revision": module.HELLASWAG_DATASET_REVISION,
                },
            },
        ],
    }
    binding = module.FROZEN_SPLIT_BINDING["hellaswag"]
    assert binding["frozen_pin_matches_scored_split"] is True
    assert binding["frozen_pinned_split"] == "validation"
    assert binding["frozen_pinned_rows"] == module.HELLASWAG_VALIDATION_ROWS
    assert binding["dataset_revision"] == module.HELLASWAG_DATASET_REVISION
    assert (
        binding["frozen_test_split_sha256"]
        == module.HELLASWAG_VALIDATION_PARQUET_SHA256
    )
    with pytest.raises(module.LiveCandidateRefusal, match="UNBOUND_EVALUATOR_TASK"):
        module.build_bound_task_specs(["mmlu_pro"])


def test_real_task_manager_loads_registered_hellaswag_yaml_with_revision_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    datasets = pytest.importorskip("datasets")
    task_module = pytest.importorskip("lm_eval.tasks")
    calls = []
    row = {
        "ctx_a": "A person starts",
        "ctx_b": "the task",
        "activity_label": "Example",
        "endings": ["one", "two", "three", "four"],
        "label": "0",
    }

    def fake_load_dataset(path=None, name=None, **kwargs):
        calls.append({"path": path, "name": name, "kwargs": kwargs})
        dataset = datasets.Dataset.from_list([row])
        return datasets.DatasetDict({"train": dataset, "validation": dataset})

    monkeypatch.setattr(datasets, "load_dataset", fake_load_dataset)
    ordered, by_name = module.load_bound_evaluator_tasks(
        ["hellaswag"], task_module.TaskManager()
    )

    assert list(by_name) == ["hellaswag"]
    assert ordered == [by_name["hellaswag"]]
    assert calls == [{
        "path": "Rowan/hellaswag",
        "name": None,
        "kwargs": {"revision": module.HELLASWAG_DATASET_REVISION},
    }]
    task = by_name["hellaswag"]
    assert task.config.validation_split == "validation"
    assert task.config.test_split is None
    assert task.config.dataset_kwargs == {
        "revision": module.HELLASWAG_DATASET_REVISION,
    }
    assert task.validation_docs()[0]["query"].startswith("Example:")


def test_bound_tasks_are_loaded_once_and_returned_in_requested_order() -> None:
    module = _load()
    arc = object()
    hella = object()

    class Manager:
        def __init__(self) -> None:
            self.received = None

        def load(self, specs):
            self.received = specs
            return {
                "tasks": {"hellaswag": hella, "arc_challenge": arc},
                "groups": {},
                "group_map": {},
            }

    manager = Manager()
    ordered, by_name = module.load_bound_evaluator_tasks(
        ["arc_challenge", "hellaswag"], manager
    )
    assert ordered == [arc, hella]
    assert by_name == {"arc_challenge": arc, "hellaswag": hella}


def test_prediction_row_requires_and_preserves_lm_eval_identity_hashes() -> None:
    module = _load()
    sample = {
        "doc_id": 7,
        "target": "2",
        "arguments": [["prompt", "continuation"]],
        "resps": [[-1.0]],
        "filtered_resps": [-1.0],
        "acc": 1,
        "acc_norm": 1,
        "doc_hash": "a" * 64,
        "prompt_hash": "b" * 64,
        "target_hash": "c" * 64,
    }

    row = module._prediction_row(sample)
    assert row["doc_hash"] == "a" * 64
    assert row["prompt_hash"] == "b" * 64
    assert row["target_hash"] == "c" * 64

    sample.pop("doc_hash")
    with pytest.raises(module.LiveCandidateRefusal, match="SAMPLE_IDENTITY_HASH_REQUIRED"):
        module._prediction_row(sample)


def test_hellaswag_runtime_binding_hashes_consumed_revision_parquet(
    tmp_path: Path,
) -> None:
    module = _load()
    snapshot = tmp_path / "snapshot"
    parquet = snapshot / module.HELLASWAG_VALIDATION_PARQUET_PATH
    parquet.parent.mkdir(parents=True)
    parquet.write_bytes(b"validation parquet")
    expected_sha = _sha(parquet)
    task = SimpleNamespace(
        config=SimpleNamespace(
            dataset_kwargs={"revision": module.HELLASWAG_DATASET_REVISION}
        ),
        dataset={"validation": list(range(module.HELLASWAG_VALIDATION_ROWS))},
    )

    binding = module.verify_frozen_task_runtime(
        "hellaswag",
        task,
        limit=None,
        observed_rows=module.HELLASWAG_VALIDATION_ROWS,
        expected_parquet_sha256=expected_sha,
        snapshot_locator=lambda **_kwargs: snapshot,
    )
    assert binding["revision_pin_verified"] is True
    assert binding["parquet_runtime_verification"] == "VERIFIED"
    assert binding["parquet_sha256"] == expected_sha
    assert binding["full_count_verified"] is True

    with pytest.raises(module.LiveCandidateRefusal, match="HELLASWAG_FULL_COUNT_REQUIRED"):
        module.verify_frozen_task_runtime(
            "hellaswag",
            task,
            limit=None,
            observed_rows=module.HELLASWAG_VALIDATION_ROWS - 1,
            expected_parquet_sha256=expected_sha,
            snapshot_locator=lambda **_kwargs: snapshot,
        )


def test_bounded_hellaswag_runtime_records_nonterminal_cache_boundary(
    tmp_path: Path,
) -> None:
    module = _load()
    task = SimpleNamespace(
        config=SimpleNamespace(
            dataset_kwargs={"revision": module.HELLASWAG_DATASET_REVISION}
        ),
        dataset={"validation": list(range(module.HELLASWAG_VALIDATION_ROWS))},
    )

    binding = module.verify_frozen_task_runtime(
        "hellaswag",
        task,
        limit=4,
        observed_rows=4,
        snapshot_locator=lambda **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    assert binding["parquet_runtime_verification"] == "UNVERIFIABLE_FROM_RUNTIME_CACHE"
    assert binding["full_count_verified"] is False
    assert binding["terminal_split_binding"] is False


def test_hellaswag_runtime_refuses_revision_and_parquet_drift(
    tmp_path: Path,
) -> None:
    module = _load()
    snapshot = tmp_path / "snapshot"
    parquet = snapshot / module.HELLASWAG_VALIDATION_PARQUET_PATH
    parquet.parent.mkdir(parents=True)
    parquet.write_bytes(b"wrong parquet bytes")
    task = SimpleNamespace(
        config=SimpleNamespace(dataset_kwargs={"revision": "0" * 40}),
        dataset={"validation": list(range(module.HELLASWAG_VALIDATION_ROWS))},
    )

    with pytest.raises(module.LiveCandidateRefusal, match="HELLASWAG_REVISION_PIN_REQUIRED"):
        module.verify_frozen_task_runtime(
            "hellaswag",
            task,
            limit=None,
            observed_rows=module.HELLASWAG_VALIDATION_ROWS,
            snapshot_locator=lambda **_kwargs: snapshot,
        )

    task.config.dataset_kwargs["revision"] = module.HELLASWAG_DATASET_REVISION
    with pytest.raises(module.LiveCandidateRefusal, match="HELLASWAG_PARQUET_HASH_CHANGED"):
        module.verify_frozen_task_runtime(
            "hellaswag",
            task,
            limit=None,
            observed_rows=module.HELLASWAG_VALIDATION_ROWS,
            snapshot_locator=lambda **_kwargs: snapshot,
        )


def test_run_evaluator_uses_loaded_revision_bound_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    parquet_root = tmp_path / "snapshot"
    parquet = parquet_root / module.HELLASWAG_VALIDATION_PARQUET_PATH
    parquet.parent.mkdir(parents=True)
    parquet.write_bytes(b"validation parquet")
    monkeypatch.setattr(
        module,
        "load_verified_warm100_checkpoint",
        lambda *_args: {
            "manifest_sha256": "d" * 64,
            "run_receipt_path": "warm100.json",
            "run_receipt_sha256": "e" * 64,
        },
    )
    monkeypatch.setattr(module, "device_lease", lambda _device: nullcontext())
    scorer = object()
    monkeypatch.setattr(
        module,
        "build_live_candidate_scorer",
        lambda **_kwargs: (
            scorer,
            {"checkpoint": {"manifest_sha256": "d" * 64}},
        ),
    )

    arc = SimpleNamespace(config=SimpleNamespace(dataset_kwargs=None), dataset={})
    hella = SimpleNamespace(
        config=SimpleNamespace(
            dataset_kwargs={"revision": module.HELLASWAG_DATASET_REVISION}
        ),
        dataset={"validation": list(range(module.HELLASWAG_VALIDATION_ROWS))},
    )

    class TaskManager:
        last = None

        def __init__(self):
            self.received = None
            TaskManager.last = self

        def load(self, specs):
            self.received = specs
            return {
                "tasks": {"arc_challenge": arc, "hellaswag": hella},
                "groups": {},
                "group_map": {},
            }

    sample = {
        "doc_id": 0,
        "target": "0",
        "arguments": [["p", "c"]],
        "resps": [[-1.0]],
        "filtered_resps": [-1.0],
        "acc": 1,
        "acc_norm": 1,
        "doc_hash": "a" * 64,
        "prompt_hash": "b" * 64,
        "target_hash": "c" * 64,
    }

    def simple_evaluate(**kwargs):
        assert kwargs["model"] is scorer
        assert kwargs["tasks"] == [arc, hella]
        assert kwargs["task_manager"] is TaskManager.last
        return {
            "results": {
                "arc_challenge": {"acc,none": 1.0},
                "hellaswag": {"acc,none": 1.0},
            },
            "samples": {
                "arc_challenge": [sample],
                "hellaswag": [sample],
            },
            "versions": {"arc_challenge": 1, "hellaswag": 1},
            "n-samples": {
                "arc_challenge": {"original": 1172, "effective": 1},
                "hellaswag": {"original": 10042, "effective": 1},
            },
        }

    lm_eval = types.ModuleType("lm_eval")
    evaluator = types.ModuleType("lm_eval.evaluator")
    tasks = types.ModuleType("lm_eval.tasks")
    evaluator.simple_evaluate = simple_evaluate
    tasks.TaskManager = TaskManager
    monkeypatch.setitem(sys.modules, "lm_eval", lm_eval)
    monkeypatch.setitem(sys.modules, "lm_eval.evaluator", evaluator)
    monkeypatch.setitem(sys.modules, "lm_eval.tasks", tasks)
    runtime_calls = []

    def verify_runtime(name, loaded_task, **kwargs):
        runtime_calls.append((name, loaded_task, kwargs))
        return {"revision_pin_verified": name == "hellaswag"}

    monkeypatch.setattr(module, "verify_frozen_task_runtime", verify_runtime)

    evaluation = module.run_evaluator(
        checkpoint_dir="checkpoint",
        warm100_receipt_path="warm100.json",
        warm100_receipt_sha256="e" * 64,
        route="tool",
        tasks=["arc_challenge", "hellaswag"],
        limit=1,
        device="cpu",
        max_position_embeddings=1024,
        predictions_path=str(tmp_path / "predictions.jsonl"),
    )
    assert [call[0] for call in runtime_calls] == ["arc_challenge", "hellaswag"]
    assert runtime_calls[1][1] is hella
    assert runtime_calls[1][2]["observed_rows"] == 1
    assert (
        evaluation["frozen_suite"]["runtime_binding"]["hellaswag"]
        ["revision_pin_verified"]
        is True
    )
    assert evaluation["frozen_suite"]["ready_for_compute"] is False
    assert (
        evaluation["frozen_suite"]["contamination_authority"]["status"]
        == "PENDING_FINAL_CORPUS_CONTAMINATION_SCAN"
    )
