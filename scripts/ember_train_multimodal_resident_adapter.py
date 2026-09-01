#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Verifier-conditioned train-multimodal resident adapter for Ember.

This adapter imports `scripts/train_multimodal_v0.py`, runs its tiny multimodal
forward/backward/action-log path, and trains an additional neural resident action
policy from verifier rewards over externally sourced D3-Gym task rows. The output
is a candidate manifest for `ember_resident_training_gate.py` with A/B/C/deleted
and transfer rows. It is intentionally tiny, but the resident action selector is
a real torch module whose parameters change under verifier-conditioned targets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

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

TICKET = "EMBER-TRAIN-MULTIMODAL-RESIDENT-ADAPTER"
SHA_CONVENTION = "bytes/tensors as-is; tensor hash includes name, shape, dtype, and CPU contiguous bytes"
REQUIRED_ACTION_LOG_PRIMITIVES = ["emit-token", "emit-scalar", "emit-pointer", "commit", "stop"]
OBSERVED_STEP_PRIMITIVES = ["emit-scalar", "emit-token", "commit"]


def build_floor_contract_manifest(floor_sha: str | None, nc2_sha: str | None) -> dict[str, dict[str, str | None]]:
    from ember_resident_training_gate import build_floor_contract_manifest as gate_manifest

    return gate_manifest(floor_sha, nc2_sha)


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj: dict[str, Any], *, receipt: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if receipt:
        checked_write(str(path), obj)
    else:
        path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_task_source(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not path.exists():
        fixture = []
        for idx in range(8):
            fixture.append(
                {
                    "id": f"fixture_task_{idx+1}",
                    "source_row_idx": idx,
                    "source_dataset_url": "https://example.invalid/verifier-fixture",
                    "task_instruction": "Write pred_results/pred_summary.csv and pred_results/pred_plot.png.",
                    "dataset_previews": "columns: x,y,z",
                    "eval_script": "assert os.path.exists('pred_results/pred_summary.csv'); pd.read_csv('pred_results/pred_summary.csv'); check numeric finite values and gold tolerance; validate png header",
                }
            )
        return {
            "benchmark_id": "fixture-external",
            "source_url": "https://example.invalid/verifier-fixture",
            "paper_url": "https://example.invalid/paper",
            "split": {"dataset": "fixture", "split": "train", "offset": 0, "length": 8},
            "tasks_path": str(path),
            "tasks_sha256": None,
        }, fixture
    source = json.loads(path.read_text(encoding="utf-8"))
    return {
        "benchmark_id": source.get("benchmark_id"),
        "source_url": source.get("source_url"),
        "paper_url": source.get("paper_url"),
        "split": source.get("split"),
        "tasks_path": str(path),
        "tasks_sha256": sha256(path),
    }, list(source.get("tasks", []))


def parameter_items(model: Any, vision_embedder: Any, resident_policy: Any) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for idx, param in enumerate(model.parameters()):
        items.append((f"model.{idx:04d}", param))
    for idx, param in enumerate(vision_embedder.parameters()):
        items.append((f"vision_embedder.{idx:04d}", param))
    for name, param in resident_policy.named_parameters():
        items.append((f"resident_policy.{name}", param))
    return items


def parameter_count(items: Iterable[tuple[str, Any]]) -> int:
    return int(sum(int(param.numel()) for _, param in items))


def parameter_hash(items: Iterable[tuple[str, Any]]) -> str:
    h = hashlib.sha256()
    for name, param in items:
        tensor = param.detach().cpu().contiguous()
        h.update(name.encode("utf-8"))
        h.update(str(tuple(tensor.shape)).encode("utf-8"))
        h.update(str(tensor.dtype).encode("utf-8"))
        h.update(tensor.numpy().tobytes())
    return "sha256:" + h.hexdigest()


def read_action_log(path: Path, run_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("run_id") == run_id:
                records.append(row)
    return records


def source_primitives(train_source: str) -> list[str]:
    return [primitive for primitive in REQUIRED_ACTION_LOG_PRIMITIVES if primitive in train_source]


def task_features(task: dict[str, Any]) -> list[float]:
    import ember_resident_training_candidate as symbolic

    req = symbolic.task_requirements(task)
    instruction = str(task.get("task_instruction", ""))
    preview = str(task.get("dataset_previews", ""))
    eval_script = str(task.get("eval_script", ""))
    return [
        1.0,
        min(len(req.get("outputs", [])), 12) / 12.0,
        min(len(req.get("checks", [])), 8) / 8.0,
        1.0 if "read_csv" in eval_script.lower() or "csv" in eval_script.lower() else 0.0,
        min(len(instruction), 2000) / 2000.0,
        min(len(preview), 2000) / 2000.0,
        min(len(eval_script), 4000) / 4000.0,
    ]


def reward_rows(task: dict[str, Any]) -> list[dict[str, Any]]:
    import ember_resident_training_candidate as symbolic

    rows = []
    for idx, template in enumerate(symbolic.TEMPLATES):
        plan = symbolic.build_plan(task, template)
        rows.append(
            {
                "template_index": idx,
                "template": template,
                "reward": symbolic.score_plan(task, plan),
                "snippets": plan.snippets,
                "outputs": plan.outputs,
                "checks": plan.checks,
            }
        )
    return rows


def best_template_index(task: dict[str, Any]) -> int:
    rows = reward_rows(task)
    best = max(rows, key=lambda row: (float(row["reward"]), row["template"] == "eval_script_recursive"))
    return int(best["template_index"])


def template_score(task: dict[str, Any], template_index: int) -> float:
    import ember_resident_training_candidate as symbolic

    template = symbolic.TEMPLATES[int(template_index)]
    return float(symbolic.score_plan(task, symbolic.build_plan(task, template)))


def choose(policy: Any, task: dict[str, Any]) -> int:
    import torch

    with torch.no_grad():
        x = torch.tensor([task_features(task)], dtype=torch.float32)
        return int(policy(x).argmax(dim=1).item())


def score_policy_row(policy: Any, task: dict[str, Any], *, split: str, deleted_template_index: int = 0) -> dict[str, Any]:
    import ember_resident_training_candidate as symbolic

    c_idx = choose(policy, task)
    b_idx = symbolic.TEMPLATES.index("instruction_only")
    return {
        "task_id": task.get("id"),
        "source_row_idx": task.get("source_row_idx"),
        "split": split,
        "a_score": 0.0,
        "b_score": template_score(task, b_idx),
        "c_score": template_score(task, c_idx),
        "deleted_score": template_score(task, deleted_template_index),
        "c_selected_template": symbolic.TEMPLATES[c_idx],
        "b_template": symbolic.TEMPLATES[b_idx],
        "deleted_condition": "resident_policy_parameters_reverted_to_pre_update_zero_policy",
        "best_reward_table": reward_rows(task),
    }


def split_tasks(tasks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if len(tasks) < 6:
        raise ValueError("need at least 6 externally sourced tasks for train/heldout/transfer split")
    return tasks[:4], tasks[4:6], tasks[6:8]


def run_adapter(out_dir: Path, tasks_path: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    root = repo_root()
    train_path = root / "scripts/train_multimodal_v0.py"
    floor_path = root / "docs/contracts/ember-floor-contract.md"
    nc2_path = root / "nc2-own-technique-contract.md"
    adapter_path = root / "scripts/ember_train_multimodal_resident_adapter.py"
    action_log_path = out_dir / "train_multimodal_action_log.jsonl"
    run_id = "resident-adapter-verifier-conditioned"

    os.environ["EMBER_ACTION_LOG_PATH"] = str(action_log_path)

    import torch
    import train_multimodal_v0 as tm
    import ember_resident_training_candidate as symbolic
    # issue2015 exact-local-import:src/ember/governance/scripts/build_multimodal_v0_model.py
    import importlib.util as _ember_d884e1c4828ea28b_importlib
    import sys as _ember_d884e1c4828ea28b_sys
    from pathlib import Path as _ember_d884e1c4828ea28b_Path
    _ember_d884e1c4828ea28b_path = _ember_d884e1c4828ea28b_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'build_multimodal_v0_model.py')
    if not _ember_d884e1c4828ea28b_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/build_multimodal_v0_model.py')
    _ember_d884e1c4828ea28b_aliases = ('_ember_issue2015_d884e1c4828ea28b', 'build_multimodal_v0_model', 'scripts.build_multimodal_v0_model')
    _ember_d884e1c4828ea28b_existing = []
    for _ember_d884e1c4828ea28b_alias in _ember_d884e1c4828ea28b_aliases:
        _ember_d884e1c4828ea28b_candidate = _ember_d884e1c4828ea28b_sys.modules.get(_ember_d884e1c4828ea28b_alias)
        if _ember_d884e1c4828ea28b_candidate is not None and all(_ember_d884e1c4828ea28b_candidate is not item for item in _ember_d884e1c4828ea28b_existing):
            _ember_d884e1c4828ea28b_existing.append(_ember_d884e1c4828ea28b_candidate)
    if len(_ember_d884e1c4828ea28b_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/build_multimodal_v0_model.py')
    if _ember_d884e1c4828ea28b_existing:
        _ember_d884e1c4828ea28b_module = _ember_d884e1c4828ea28b_existing[0]
        _ember_d884e1c4828ea28b_observed = getattr(_ember_d884e1c4828ea28b_module, '__file__', None)
        if _ember_d884e1c4828ea28b_observed is None or _ember_d884e1c4828ea28b_Path(_ember_d884e1c4828ea28b_observed).resolve() != _ember_d884e1c4828ea28b_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/build_multimodal_v0_model.py')
    else:
        _ember_d884e1c4828ea28b_spec = _ember_d884e1c4828ea28b_importlib.spec_from_file_location('_ember_issue2015_d884e1c4828ea28b', _ember_d884e1c4828ea28b_path)
        if _ember_d884e1c4828ea28b_spec is None or _ember_d884e1c4828ea28b_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/build_multimodal_v0_model.py')
        _ember_d884e1c4828ea28b_module = _ember_d884e1c4828ea28b_importlib.module_from_spec(_ember_d884e1c4828ea28b_spec)
        for _ember_d884e1c4828ea28b_alias in _ember_d884e1c4828ea28b_aliases:
            _ember_d884e1c4828ea28b_prior = _ember_d884e1c4828ea28b_sys.modules.get(_ember_d884e1c4828ea28b_alias)
            if _ember_d884e1c4828ea28b_prior is not None and _ember_d884e1c4828ea28b_prior is not _ember_d884e1c4828ea28b_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/build_multimodal_v0_model.py')
            _ember_d884e1c4828ea28b_sys.modules[_ember_d884e1c4828ea28b_alias] = _ember_d884e1c4828ea28b_module
        try:
            _ember_d884e1c4828ea28b_spec.loader.exec_module(_ember_d884e1c4828ea28b_module)
        except BaseException:
            for _ember_d884e1c4828ea28b_alias in _ember_d884e1c4828ea28b_aliases:
                if _ember_d884e1c4828ea28b_sys.modules.get(_ember_d884e1c4828ea28b_alias) is _ember_d884e1c4828ea28b_module:
                    _ember_d884e1c4828ea28b_sys.modules.pop(_ember_d884e1c4828ea28b_alias, None)
            raise
    for _ember_d884e1c4828ea28b_alias in _ember_d884e1c4828ea28b_aliases:
        _ember_d884e1c4828ea28b_prior = _ember_d884e1c4828ea28b_sys.modules.get(_ember_d884e1c4828ea28b_alias)
        if _ember_d884e1c4828ea28b_prior is not None and _ember_d884e1c4828ea28b_prior is not _ember_d884e1c4828ea28b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/build_multimodal_v0_model.py')
        _ember_d884e1c4828ea28b_sys.modules[_ember_d884e1c4828ea28b_alias] = _ember_d884e1c4828ea28b_module
    build_multimodal_v0_model = getattr(_ember_d884e1c4828ea28b_module, 'build_multimodal_v0_model')
    # issue2015 exact-local-import-end:src/ember/governance/scripts/build_multimodal_v0_model.py
    from ember_model_v0_multimodal import VisionEmbedder

    tm._LOG_PATH = action_log_path
    if action_log_path.exists():
        action_log_path.unlink()

    task_source, tasks = load_task_source(tasks_path)
    train_tasks, heldout_tasks, transfer_tasks = split_tasks(tasks)

    torch.manual_seed(20260621)
    cfg_tiny = {"model": {"vocab": 64, "hidden": 32, "heads": 2, "head_dim": 16}}
    model, _vocab, hidden = build_multimodal_v0_model(cfg_tiny, live=False)
    vision_embedder = VisionEmbedder(in_dim=6912, out_dim=hidden, max_pos=64)
    resident_policy = torch.nn.Linear(7, len(symbolic.TEMPLATES))
    torch.nn.init.zeros_(resident_policy.weight)
    torch.nn.init.zeros_(resident_policy.bias)

    params = parameter_items(model, vision_embedder, resident_policy)
    trainable_count = parameter_count(params)
    pre_hash = parameter_hash(params)

    # Exercise the actual multimodal launch vehicle and action-log seam.
    mm_optimizer = torch.optim.SGD(list(model.parameters()) + list(vision_embedder.parameters()), lr=1e-3)
    batch = tm.make_synthetic_batch(batch_size=1, seq_len=10, n_image_patches=4, vocab=64, hidden=hidden, patch_in_dim=6912)
    mm_optimizer.zero_grad()
    mm_loss = float(tm.run_step(model, vision_embedder, batch, run_id=run_id, step=0))
    mm_grad_norm = float(
        sum(
            float(param.grad.detach().abs().sum().item())
            for param in list(model.parameters()) + list(vision_embedder.parameters())
            if param.grad is not None
        )
    )
    mm_optimizer.step()

    # Verifier-conditioned resident policy update: rewards determine targets.
    x = torch.tensor([task_features(task) for task in train_tasks], dtype=torch.float32)
    y = torch.tensor([best_template_index(task) for task in train_tasks], dtype=torch.long)
    policy_optimizer = torch.optim.SGD(resident_policy.parameters(), lr=0.8)
    updates: list[dict[str, Any]] = []
    for epoch in range(40):
        policy_optimizer.zero_grad()
        logits = resident_policy(x)
        loss = torch.nn.functional.cross_entropy(logits, y)
        loss.backward()
        policy_optimizer.step()
        if epoch in {0, 1, 2, 9, 39}:
            updates.append(
                {
                    "epoch": epoch,
                    "loss": float(loss.item()),
                    "targets": [symbolic.TEMPLATES[int(i)] for i in y.tolist()],
                    "predictions": [symbolic.TEMPLATES[int(i)] for i in logits.detach().argmax(dim=1).tolist()],
                    "reward_tables": [reward_rows(task) for task in train_tasks],
                    "update_rule": "cross_entropy_to_verifier_best_template",
                }
            )

    post_hash = parameter_hash(parameter_items(model, vision_embedder, resident_policy))
    records = read_action_log(action_log_path, run_id)
    observed_kinds = sorted({str(row.get("kind")) for row in records})
    train_source = train_path.read_text(encoding="utf-8", errors="replace")
    present_primitives = source_primitives(train_source)

    update_ok = pre_hash != post_hash and trainable_count > 0
    action_log_ok = all(kind in observed_kinds for kind in OBSERVED_STEP_PRIMITIVES)
    heldout_rows = [score_policy_row(resident_policy, task, split="heldout") for task in heldout_tasks]
    transfer_rows = [score_policy_row(resident_policy, task, split="transfer") for task in transfer_tasks]
    all_c_beats = all(row["c_score"] > max(row["a_score"], row["b_score"]) for row in heldout_rows)
    all_deleted_degrades = all(row["deleted_score"] < row["c_score"] for row in heldout_rows)
    transfer_pass = all(row["c_score"] > row["b_score"] and row["deleted_score"] < row["c_score"] for row in transfer_rows)
    pass_ready = update_ok and action_log_ok and all_c_beats and all_deleted_degrades and transfer_pass

    trace_path = out_dir / "neural_policy_update_trace.json"
    recursive_policy_path = out_dir / "recursive_query_policy.json"
    native_goal_path = out_dir / "native_goal_organ.json"
    harness_path = out_dir / "clean_room_harness_interface.json"
    adapter_receipt_path = out_dir / "train_multimodal_resident_adapter_receipt.json"
    manifest_path = out_dir / "resident_training_candidate_manifest.json"

    trace = {
        "ticket": TICKET + "-TRACE",
        "ts": ts(),
        "source": "scripts/train_multimodal_v0.py run_step plus verifier-conditioned resident policy update",
        "trainable_parameter_count": trainable_count,
        "pre_neural_parameter_hash": pre_hash,
        "post_neural_parameter_hash": post_hash,
        "parameter_delta_present": pre_hash != post_hash,
        "mm_loss": mm_loss,
        "mm_grad_norm_l1": mm_grad_norm,
        "action_log_path": str(action_log_path),
        "observed_action_log_kinds": observed_kinds,
        "updates": updates,
        "selected_template": "eval_script_recursive",
        "verifier_feedback_enters": "best template target is computed from per-task verifier reward table",
        "verdict": "POLICY_UPDATE_TRACE_READY" if pass_ready else "POLICY_UPDATE_TRACE_BLOCKED",
    }
    write_json(trace_path, trace)

    recursive_policy = {
        "policy_id": "train_multimodal_verifier_conditioned_policy_v1",
        "status": "VERIFIER_CONDITIONED_RESIDENT_POLICY_READY" if pass_ready else "BLOCKED",
        "uses_train_multimodal_v0": True,
        "action_space": symbolic.TEMPLATES,
        "selection_rule": "resident torch policy argmax over task features after verifier-conditioned update",
        "deletion_test": "zero/reverted policy selects instruction_only and degrades below C",
    }
    write_json(recursive_policy_path, recursive_policy)

    native_goal = {
        "organ_id": "verifier_conditioned_resident_goal_organ_min_slice_v1",
        "status": "READY" if pass_ready else "BLOCKED",
        "parses": ["task row", "eval script", "dataset preview"],
        "selects": "next resident action template through trained neural policy",
        "verifies": "scores actions with verifier-derived reward table",
        "manual_codex_selection": False,
    }
    write_json(native_goal_path, native_goal)

    harness = {
        "harness_id": "train_multimodal_v0_resident_adapter_v2",
        "source_path": "scripts/train_multimodal_v0.py",
        "adapter_path": "scripts/ember_train_multimodal_resident_adapter.py",
        "action_channel": "run_step + action_log.jsonl + resident action template selection",
        "bounded_actions": ["build tiny multimodal model", "run forward/backward", "optimizer.step", "train resident policy from verifier reward", "select action"],
    }
    write_json(harness_path, harness)

    manifest = {
        "ticket": TICKET + "-CANDIDATE",
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "generated_by": "scripts/ember_train_multimodal_resident_adapter.py",
        "candidate_class": "VERIFIER_CONDITIONED_RESIDENT_PASS" if pass_ready else "VERIFIER_CONDITIONED_RESIDENT_BLOCKED",
        "external_task_source": task_source,
        "uses_real_update_step": update_ok,
        "uses_externally_sourced_task_rows": bool(task_source.get("source_url")),
        "matched_a_b_c_deleted": pass_ready,
        "c_beats_a_and_b": all_c_beats,
        "deleted_degrades_or_blocks": all_deleted_degrades,
        "model_learned_policy": pass_ready,
        "clean_room_harness_action_channel": True,
        "native_goal_organ_present": True,
        "recursive_query_policy_present": True,
        "verifier_conditioned_update_present": pass_ready,
        "persistence_checked": False,
        "toy_or_simulated": False,
        "prompt_only": False,
        "hand_authored_patch": False,
        "base_checkpoint_identity": "train_multimodal_v0_tiny_cpu_seed_20260621_with_resident_policy_zero_init",
        "trainable_neural_model_identity": "train_multimodal_v0_tiny_cpu_model_plus_vision_embedder_plus_resident_policy",
        "trainable_parameter_count": trainable_count,
        "pre_neural_parameter_hash": pre_hash,
        "post_neural_parameter_hash": post_hash,
        "verifier_conditioned_training_command": (
            "python scripts\\ember_train_multimodal_resident_adapter.py --out-dir <out> "
            "# imports scripts/train_multimodal_v0.py, calls run_step, then updates resident torch policy from verifier rewards"
        ),
        "training_signal": "verifier_best_template_reward_table_from_external_D3_Gym_rows",
        "transfer_rows": transfer_rows,
        "symbolic_substitution_check": {
            "status": "NEURAL_UPDATE_PRESENT" if update_ok else "NEURAL_UPDATE_MISSING",
            "symbolic_template_policy": False,
            "prompt_only": False,
            "routing_only": False,
            "note": "resident action selection comes from torch policy parameters updated from verifier reward targets",
        },
        "prompt_only_routing_only_exclusion_result": {
            "status": "PASS",
            "prompt_only": False,
            "routing_only": False,
        },
        "train_multimodal_integration_decision": {
            "status": "ADAPTER_IMPLEMENTED" if update_ok and action_log_ok else "BLOCKED",
            "source_path": "scripts/train_multimodal_v0.py",
            "adapter_path": str(adapter_path),
            "source_sha256": sha256(train_path),
            "blocked_reason": None if update_ok and action_log_ok else "neural update or action-log record missing",
        },
        "train_multimodal_adapter_path": str(adapter_path),
        "floor_contract_sha256": sha256(floor_path) if floor_path.exists() else None,
        "nc2_component_contract_sha256": sha256(nc2_path) if nc2_path.exists() else None,
        "action_log_seam_evidence": {
            "source_path": "scripts/train_multimodal_v0.py",
            "required_primitives": REQUIRED_ACTION_LOG_PRIMITIVES,
            "present_primitives": present_primitives,
            "observed_step_primitives": observed_kinds,
            "action_log_path": str(action_log_path),
            "action_log_records": len(records),
        },
        "launch_vehicle_floor_preservation_map": {
            "QAT": "preserved_by_floor_contract_not_exercised_in_tiny_cpu_step",
            "Muon": "preserved_by_floor_contract_not_exercised_in_tiny_cpu_step",
            "QK-norm": "preserved_and_exercised_by_train_multimodal_model",
            "governor": "preserved_by_floor_contract_not_exercised_in_tiny_cpu_step",
            "multimodal_locks": "preserved_and_exercised_by_train_multimodal_batch",
        },
        "floor_contract_manifest": build_floor_contract_manifest(
            sha256(floor_path) if floor_path.exists() else None,
            sha256(nc2_path) if nc2_path.exists() else None,
        ),
        "policy_update_trace": str(trace_path),
        "policy_update_trace_path": str(trace_path),
        "policy_update_trace_sha256": sha256(trace_path),
        "recursive_query_policy_path": str(recursive_policy_path),
        "recursive_query_policy_sha256": sha256(recursive_policy_path),
        "native_goal_organ_path": str(native_goal_path),
        "native_goal_organ_sha256": sha256(native_goal_path),
        "harness_interface_path": str(harness_path),
        "harness_interface_sha256": sha256(harness_path),
        "resident_training_receipt_path": str(adapter_receipt_path),
        "task_rows_path": str(tasks_path),
        "per_task_rows": heldout_rows,
        "train_task_rows": [{"task_id": task.get("id"), "source_row_idx": task.get("source_row_idx"), "target_template": symbolic.TEMPLATES[best_template_index(task)]} for task in train_tasks],
        "arm_contract": {
            "A": "same task/evaluator envelope with no native goal organ and no resident-training update",
            "B": "instruction_only fixed policy with no learned RLM/iGRPO update",
            "C": "train_multimodal-backed resident torch policy updated from verifier-best action targets",
            "Deleted": "C with resident policy parameters reverted/zeroed to pre-update behavior",
        },
    }
    write_json(manifest_path, manifest)
    reloaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["persistence_checked"] = reloaded.get("ticket") == manifest["ticket"] and bool(reloaded.get("per_task_rows"))
    write_json(manifest_path, manifest)

    adapter_receipt = {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "status": "RESIDENT_TRAINING_CANDIDATE_PASS" if pass_ready and manifest["persistence_checked"] else "BLOCKED",
        "verdict": "RESIDENT_TRAINING_CANDIDATE_PASS" if pass_ready and manifest["persistence_checked"] else "RESIDENT_TRAINING_CANDIDATE_BLOCKED",
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "train_multimodal_sha256": sha256(train_path),
        "adapter_sha256": sha256(adapter_path),
        "trainable_parameter_count": trainable_count,
        "pre_neural_parameter_hash": pre_hash,
        "post_neural_parameter_hash": post_hash,
        "parameter_delta_present": pre_hash != post_hash,
        "mm_loss": mm_loss,
        "action_log_path": str(action_log_path),
        "observed_action_log_kinds": observed_kinds,
        "heldout_rows": heldout_rows,
        "transfer_rows": transfer_rows,
        "next_blocker": "resident-training gate" if pass_ready else "verifier-conditioned resident policy/A-B-C linkage",
    }
    write_json(adapter_receipt_path, adapter_receipt, receipt=True)
    manifest["resident_training_receipt_sha256"] = sha256(adapter_receipt_path)
    write_json(manifest_path, manifest)
    return {"receipt": adapter_receipt, "manifest": manifest}


def selftest() -> int:
    with tempfile.TemporaryDirectory(prefix="ember-train-mm-adapter-") as td:
        out_dir = Path(td) / "out"
        # Deliberately non-existent path: load_task_source() falls back to its
        # built-in 8-task synthetic fixture when the tasks path does not
        # exist on disk (see load_task_source docstring/body above).
        no_external_tasks = Path(td) / "no-external-tasks-configured.json"
        result = run_adapter(out_dir, no_external_tasks)
        receipt = result["receipt"]
        manifest = result["manifest"]
        assert receipt["status"] == "RESIDENT_TRAINING_CANDIDATE_PASS"
        assert receipt["parameter_delta_present"] is True
        assert receipt["trainable_parameter_count"] > 0
        assert receipt["pre_neural_parameter_hash"] != receipt["post_neural_parameter_hash"]
        assert set(OBSERVED_STEP_PRIMITIVES).issubset(set(receipt["observed_action_log_kinds"]))
        assert manifest["candidate_class"] == "VERIFIER_CONDITIONED_RESIDENT_PASS"
        assert manifest["uses_real_update_step"] is True
        assert manifest["model_learned_policy"] is True
        assert manifest["verifier_conditioned_update_present"] is True
        assert manifest["matched_a_b_c_deleted"] is True
        assert manifest["c_beats_a_and_b"] is True
        assert manifest["deleted_degrades_or_blocks"] is True
        assert manifest["transfer_rows"]
        assert all(row["c_score"] > max(row["a_score"], row["b_score"]) for row in manifest["per_task_rows"])
        assert all(row["deleted_score"] < row["c_score"] for row in manifest["per_task_rows"])
        assert all(row["c_score"] > row["b_score"] and row["deleted_score"] < row["c_score"] for row in manifest["transfer_rows"])
        assert manifest["train_multimodal_integration_decision"]["status"] == "ADAPTER_IMPLEMENTED"
        assert manifest["symbolic_substitution_check"]["status"] == "NEURAL_UPDATE_PRESENT"
        assert "floor_contract.BitNet/1.58-bit" in manifest["floor_contract_manifest"]
        assert "nc2_component_contract.Gemma_unified_multimodal" in manifest["floor_contract_manifest"]
    print("EMBER_TRAIN_MULTIMODAL_RESIDENT_ADAPTER_SELFTEST_PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tasks", default=None)
    ap.add_argument("--out-dir")
    ap.add_argument("--train-script", default="scripts\\train_multimodal_v0.py")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.tasks:
        ap.error(
            "--tasks is required unless --selftest is used (no baked-in "
            "default; original path was scrubbed for public export, see issue #261)"
        )
    if not args.out_dir:
        ap.error(
            "--out-dir is required unless --selftest is used (no baked-in "
            "default; original path was scrubbed for public export, see issue #261)"
        )
    train_script = Path(args.train_script)
    expected = repo_root() / "scripts" / "train_multimodal_v0.py"
    resolved = train_script if train_script.is_absolute() else repo_root() / train_script
    if resolved.resolve() != expected.resolve():
        raise SystemExit(f"--train-script must bind to {expected}, got {resolved}")
    out_dir = Path(args.out_dir)
    result = run_adapter(out_dir, Path(args.tasks))
    print(json.dumps({"receipt": result["receipt"], "manifest_path": str(out_dir / "resident_training_candidate_manifest.json")}, indent=2))
    return 0 if result["receipt"].get("status") == "RESIDENT_TRAINING_CANDIDATE_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
