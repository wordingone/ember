# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Real bounded pretraining segments over independently verified routed records."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from batch import DOMAIN_MODALITIES, decode_owned_batch
from model import EXPERT_NAMES, RestartDecoderConfig, UnifiedDecoder
from specialist_stream import TRAINING_CURSOR_SCHEMA_VERSION
from semantic_stream import ManifestBoundTokenStream
from training_acceleration import (
    CudaGraphTrainingStepPool,
    ScaledMmKernel,
    Stage2ActivationAuthority,
    install_fp8_down_projections,
    iter_fp8_down_projections,
    refresh_fp8_after_optimizer_step,
    training_step_signature,
)

CheckpointCallback = Callable[[int, dict[str, Any]], None]
ProgressCallback = Callable[[dict[str, object]], None]
SignatureObserver = Callable[[dict[str, object]], None]
VERIFIER_PATH = Path(__file__).with_name("verify_capability_record.py")
VERIFIER_PUBLIC_PATH = "tools/ember-restart-3b/verify_capability_record.py"


def _eager_forward_loss_backward(
    model: UnifiedDecoder,
    batch: Mapping[str, object],
    config: RestartDecoderConfig,
) -> torch.Tensor:
    logits = model(
        batch["input_ids"],
        image_patches=batch["image_patches"],
        audio_frames=batch["audio_frames"],
        image_coordinates=batch["image_coordinates"],
        spans=batch["spans"],
        active_expert=batch["active_expert"],
    )
    loss = F.cross_entropy(
        logits.float().reshape(-1, config.vocab_size),
        batch["target_ids"].reshape(-1),
    )
    if not torch.isfinite(loss):
        raise RuntimeError("pretraining preparation produced a non-finite loss")
    loss.backward()
    return loss


def _measurement_trainable_parameters(
    model: UnifiedDecoder,
    records: Sequence[Mapping[str, object]],
) -> tuple[torch.Tensor, ...]:
    """Return the unique parameter union trainable across the bound records."""
    activate_expert = getattr(model, "_activate_expert", None)
    original_active_expert = getattr(model, "active_expert", None)
    if not callable(activate_expert) or not isinstance(original_active_expert, str):
        raise RuntimeError("measurement model lacks dynamic expert routing state")
    active_experts: set[str] = set()
    for record in records:
        active_expert = record.get("active_expert")
        if active_expert != "shared" and active_expert not in EXPERT_NAMES:
            raise ValueError("measurement record declares an invalid active expert")
        active_experts.add(str(active_expert))
    selected: dict[int, torch.Tensor] = {}
    try:
        for active_expert in sorted(active_experts):
            activate_expert(active_expert)
            for parameter in model.parameters():
                if parameter.requires_grad:
                    selected.setdefault(id(parameter), parameter)
    finally:
        activate_expert(original_active_expert)
    return tuple(selected.values())


def _preinitialize_optimizer_state(
    optimizer: object,
    *,
    trainable_parameters: Sequence[torch.Tensor] | None = None,
) -> int:
    """Materialize a lazy optimizer's state without taking an optimizer step."""
    init_state = getattr(optimizer, "init_state", None)
    if not callable(init_state):
        return 0
    param_groups = getattr(optimizer, "param_groups", None)
    state = getattr(optimizer, "state", None)
    if not isinstance(param_groups, list) or not isinstance(state, dict):
        raise RuntimeError("lazy optimizer state surface is malformed")
    selected_ids = (
        None if trainable_parameters is None
        else {id(parameter) for parameter in trainable_parameters}
    )
    covered_ids: set[int] = set()
    for group_index, group in enumerate(param_groups):
        if not isinstance(group, Mapping) or not isinstance(group.get("params"), list):
            raise RuntimeError("lazy optimizer parameter group is malformed")
        for parameter_index, parameter in enumerate(group["params"]):
            if not isinstance(parameter, torch.Tensor):
                continue
            parameter_id = id(parameter)
            selected = (
                parameter.requires_grad if selected_ids is None
                else parameter_id in selected_ids
            )
            if not selected or parameter_id in covered_ids:
                continue
            if not state.get(parameter):
                init_state(group, parameter, group_index, parameter_index)
            if not state.get(parameter):
                raise RuntimeError("lazy optimizer state initialization retained no state")
            covered_ids.add(parameter_id)
    if selected_ids is not None and covered_ids != selected_ids:
        raise RuntimeError("measurement trainable parameter is absent from optimizer groups")
    return len(covered_ids)


def _require_preinitialized_gradient_state(optimizer: object) -> None:
    """Refuse before a lazy optimizer step if any gradient lacks state."""
    init_state = getattr(optimizer, "init_state", None)
    if not callable(init_state):
        return
    param_groups = getattr(optimizer, "param_groups", None)
    state = getattr(optimizer, "state", None)
    if not isinstance(param_groups, list) or not isinstance(state, dict):
        raise RuntimeError("lazy optimizer state surface is malformed")
    for group_index, group in enumerate(param_groups):
        if not isinstance(group, Mapping) or not isinstance(group.get("params"), list):
            raise RuntimeError("lazy optimizer parameter group is malformed")
        for parameter_index, parameter in enumerate(group["params"]):
            if isinstance(parameter, torch.Tensor) and parameter.grad is not None and not state.get(parameter):
                raise RuntimeError(
                    "optimizer state preinitialization missed gradient-bearing parameter "
                    f"group={group_index} parameter={parameter_index}"
                )


class CensusBoundStage2Executor:
    """Execute only forward/loss/backward through a census-bound graph pool."""

    def __init__(
        self,
        *,
        model: UnifiedDecoder,
        optimizer: torch.optim.Optimizer,
        config: RestartDecoderConfig,
        authority: Stage2ActivationAuthority,
        graph_backend: object | None = None,
        fp8_kernel: ScaledMmKernel | None = None,
        allow_test_device: bool = False,
    ) -> None:
        self.model = model
        self.optimizer = optimizer
        self.config = config
        self.authority = authority
        self.installation_receipt = install_fp8_down_projections(
            model, kernel=fp8_kernel, allow_test_device=allow_test_device,
        )
        self.graph_pool = CudaGraphTrainingStepPool(
            registry=authority.registry, backend=graph_backend,
        )
        preparation_regions = getattr(
            self.graph_pool.backend, "preparation_regions_per_signature", None,
        )
        if type(preparation_regions) is not int or preparation_regions < 1:
            raise ValueError(
                "Stage-2 graph backend must declare preparation_regions_per_signature"
            )
        self.preparation_regions_per_signature = preparation_regions
        self._static_batches: dict[str, dict[str, object]] = {}
        self._loss_outputs: dict[str, torch.Tensor] = {}
        self._shared_gradient_parameters: tuple[torch.Tensor, ...] = ()
        self._expert_parameters: tuple[torch.Tensor, ...] = ()
        self._conditional_gradient_parameters: tuple[torch.Tensor, ...] = ()
        self._gradient_workspace: tuple[torch.Tensor, ...] | None = None
        self._gradient_parameters_by_signature: dict[str, tuple[torch.Tensor, ...]] = {}
        self._conditional_gradients_by_signature: dict[
            str, tuple[tuple[torch.Tensor, torch.Tensor], ...]
        ] = {}
        self._gradient_workspace_reuses = 0
        self._inactive_grad_none_assertions = 0
        self._preparation_memory_allocated_bytes_by_signature: dict[str, int] = {}
        self._active_gradient_signature: str | None = None
        self._optimizer_steps = 0
        self._refreshes = 0
        self._captures_during_preparation = 0
        self._captures_during_measured_window = 0
        self._measurement_prepared = False

    @staticmethod
    def _static_batch(batch: Mapping[str, object]) -> dict[str, object]:
        return {
            key: value.clone() if isinstance(value, torch.Tensor) else value
            for key, value in batch.items()
        }

    @staticmethod
    def _copy_tensors(
        target: Mapping[str, object], source: Mapping[str, object],
    ) -> None:
        for key, value in target.items():
            if isinstance(value, torch.Tensor):
                incoming = source.get(key)
                if not isinstance(incoming, torch.Tensor):
                    raise RuntimeError("Stage-2 static tensor source disappeared")
                value.copy_(incoming)

    def _optimizer_identity(self) -> str:
        return hashlib.sha256(
            f"stage2-optimizer-steps:{self._optimizer_steps}".encode("ascii")
        ).hexdigest()

    @staticmethod
    def _parameter_bytes(parameters: Sequence[torch.Tensor]) -> int:
        return sum(parameter.numel() * parameter.element_size() for parameter in parameters)

    def _prepare_gradient_partition(
        self, unique: Mapping[str, Mapping[str, object]],
    ) -> None:
        """Partition persistent trunk grads from one reusable expert workspace."""
        named_parameters = tuple(self.model.named_parameters())
        expert_parameters = tuple(
            parameter for name, parameter in named_parameters
            if ".experts." in f".{name}"
        )
        conditional_parameters = tuple(
            parameter
            for name, parameter in named_parameters
            if name.startswith(("image_projector.", "audio_projector."))
        )
        expert_ids = {id(parameter) for parameter in expert_parameters}
        conditional_ids = {id(parameter) for parameter in conditional_parameters}
        shared_parameters = tuple(
            parameter for _name, parameter in named_parameters
            if id(parameter) not in expert_ids | conditional_ids
        )
        original_active_expert = self.model.active_expert
        original_requires_grad = tuple(
            parameter.requires_grad for _name, parameter in named_parameters
        )
        selected_by_signature: dict[str, tuple[torch.Tensor, ...]] = {}
        try:
            for signature, batch in sorted(unique.items()):
                active_expert = batch.get("active_expert")
                if active_expert not in EXPERT_NAMES:
                    raise RuntimeError("Stage-2 gradient workspace requires an expert signature")
                self.model._activate_expert(str(active_expert))
                selected_by_signature[signature] = tuple(
                    parameter for parameter in expert_parameters if parameter.requires_grad
                )
        finally:
            self.model._activate_expert(original_active_expert)
        if tuple(parameter.requires_grad for _name, parameter in named_parameters) != original_requires_grad:
            raise RuntimeError("Stage-2 gradient partition did not restore requires_grad state")
        if not selected_by_signature or any(not parameters for parameters in selected_by_signature.values()):
            raise RuntimeError("Stage-2 gradient workspace found an empty expert bank")
        first_signature = next(iter(sorted(selected_by_signature)))
        reference = selected_by_signature[first_signature]
        reference_layout = tuple(
            (tuple(parameter.shape), parameter.dtype, parameter.device)
            for parameter in reference
        )
        for signature, parameters in selected_by_signature.items():
            layout = tuple(
                (tuple(parameter.shape), parameter.dtype, parameter.device)
                for parameter in parameters
            )
            if layout != reference_layout:
                raise RuntimeError(
                    "Stage-2 expert gradient workspace layout mismatch for signature "
                    f"{signature}"
                )
        for _name, parameter in named_parameters:
            parameter.grad = None
        for parameter in shared_parameters:
            parameter.grad = torch.zeros_like(parameter, memory_format=torch.preserve_format)
        self._shared_gradient_parameters = shared_parameters
        self._expert_parameters = expert_parameters
        self._conditional_gradient_parameters = conditional_parameters
        self._gradient_parameters_by_signature = selected_by_signature
        self._gradient_workspace = tuple(
            torch.zeros_like(parameter, memory_format=torch.preserve_format)
            for parameter in reference
        )

    def _bind_gradient_workspace(self, *, signature: str, active_expert: str) -> None:
        workspace = self._gradient_workspace
        selected = self._gradient_parameters_by_signature.get(signature)
        if workspace is None or selected is None or len(workspace) != len(selected):
            raise RuntimeError("Stage-2 expert gradient workspace is not prepared")
        self.model._activate_expert(active_expert)
        for parameter in self._expert_parameters:
            parameter.grad = None
        for parameter in self._conditional_gradient_parameters:
            parameter.grad = None
        for parameter, gradient in zip(selected, workspace, strict=True):
            if parameter.shape != gradient.shape or parameter.dtype != gradient.dtype:
                raise RuntimeError("Stage-2 expert gradient workspace binding drifted")
            parameter.grad = gradient
        conditional = self._conditional_gradients_by_signature.get(signature, ())
        for parameter, gradient in conditional:
            parameter.grad = gradient
        if self._active_gradient_signature is not None:
            self._gradient_workspace_reuses += 1
        self._active_gradient_signature = signature

    def assert_optimizer_membership(self) -> int:
        signature = self._active_gradient_signature
        if signature is None:
            raise RuntimeError("Stage-2 optimizer membership lacks an active signature")
        selected_ids = {
            id(parameter) for parameter in self._gradient_parameters_by_signature[signature]
        }
        conditional_ids = {
            id(parameter)
            for parameter, _gradient in self._conditional_gradients_by_signature.get(signature, ())
        }
        assertions = 0
        for parameter in self._expert_parameters:
            should_have_gradient = id(parameter) in selected_ids
            if (parameter.grad is not None) != should_have_gradient:
                raise RuntimeError("Stage-2 inactive expert gradient isolation failed")
            if not should_have_gradient:
                assertions += 1
        for parameter in self._conditional_gradient_parameters:
            should_have_gradient = id(parameter) in conditional_ids
            if (parameter.grad is not None) != should_have_gradient:
                raise RuntimeError("Stage-2 conditional gradient isolation failed")
            if not should_have_gradient:
                assertions += 1
        self._inactive_grad_none_assertions += assertions
        return assertions

    def _capture(
        self,
        batch: Mapping[str, object],
        *,
        signature: str,
        cursor_identity: str,
    ) -> None:
        static = self._static_batch(batch)
        loss_holder: list[torch.Tensor] = []
        self._bind_gradient_workspace(
            signature=signature, active_expert=str(static["active_expert"]),
        )

        def marker_indices(*, marker_id: int, raw_key: str) -> torch.Tensor:
            if static[raw_key] is None:
                return torch.empty(
                    0, dtype=torch.int64, device=static["input_ids"].device,
                )
            return static["input_ids"].eq(marker_id).reshape(-1).nonzero(
                as_tuple=False,
            ).flatten()

        image_marker_indices = marker_indices(
            marker_id=self.config.image_token_id, raw_key="image_patches",
        )
        audio_marker_indices = marker_indices(
            marker_id=self.config.audio_token_id, raw_key="audio_frames",
        )

        def region() -> None:
            logits = self.model(
                static["input_ids"],
                image_patches=static["image_patches"],
                audio_frames=static["audio_frames"],
                image_coordinates=static["image_coordinates"],
                static_image_marker_indices=image_marker_indices,
                static_audio_marker_indices=audio_marker_indices,
                spans=static["spans"],
                active_expert=static["active_expert"],
            )
            loss = F.cross_entropy(
                logits.float().reshape(-1, self.config.vocab_size),
                static["target_ids"].reshape(-1),
            )
            loss.backward()
            if loss_holder:
                loss_holder[0] = loss
            else:
                loss_holder.append(loss)

        warmup = getattr(self.graph_pool.backend, "warmup", None)
        if not callable(warmup):
            raise RuntimeError("Stage-2 graph backend must expose warmup")
        warmup(region, lambda: self.optimizer.zero_grad(set_to_none=False))
        if not loss_holder:
            raise RuntimeError("Stage-2 graph warmup did not retain its loss tensor")
        loss_holder.clear()
        self.graph_pool.capture(
            signature_sha256=signature,
            region=region,
            optimizer_identity=self._optimizer_identity,
            cursor_identity=lambda: cursor_identity,
        )
        if not loss_holder:
            raise RuntimeError("Stage-2 graph capture did not retain its loss tensor")
        loss_output = loss_holder[0].detach()
        loss_holder.clear()
        self._static_batches[signature] = static
        self._loss_outputs[signature] = loss_output
        self._conditional_gradients_by_signature[signature] = tuple(
            (parameter, parameter.grad)
            for parameter in self._conditional_gradient_parameters
            if parameter.grad is not None
        )
        self._captures_during_preparation += 1
        self.optimizer.zero_grad(set_to_none=False)

    def prepare_for_measurement(
        self,
        batches: Sequence[Mapping[str, object]],
        *,
        cursor_identity: str,
        regions_per_signature: int,
    ) -> dict[str, object]:
        if self._measurement_prepared:
            raise RuntimeError("Stage-2 measurement preparation is single-use")
        if regions_per_signature != self.preparation_regions_per_signature:
            raise ValueError("Stage-2 preparation region count differs from its backend")
        unique: dict[str, Mapping[str, object]] = {}
        for batch in batches:
            signature = self.authority.resolve(
                batch,
                gradient_checkpointing=bool(self.config.gradient_checkpointing),
            )
            unique.setdefault(signature, batch)
        if set(unique) != set(self.authority.registry.approved_signatures):
            raise RuntimeError("Stage-2 preparation does not cover the full admitted census")
        self._prepare_gradient_partition(unique)
        for signature in sorted(unique):
            status = "COMPLETED"
            try:
                self._capture(
                    unique[signature],
                    signature=signature,
                    cursor_identity=cursor_identity,
                )
            except BaseException:
                status = "FAILED"
                raise
            finally:
                allocated_bytes = (
                    int(torch.cuda.memory_allocated()) if torch.cuda.is_available() else 0
                )
                self._preparation_memory_allocated_bytes_by_signature[signature] = allocated_bytes
                print(json.dumps({
                    "event": "stage2_signature_preparation_memory",
                    "status": status,
                    "signature_sha256": signature,
                    "memory_allocated_bytes": allocated_bytes,
                }, sort_keys=True, separators=(",", ":")), flush=True)
        self._measurement_prepared = True
        return {
            "regions_per_signature": regions_per_signature,
            "signature_count": len(unique),
            "region_count": regions_per_signature * len(unique),
            "no_capture_in_measured_window": True,
        }

    def forward_loss_backward(
        self, batch: Mapping[str, object], *, cursor_identity: str,
    ) -> torch.Tensor:
        del cursor_identity
        if not self._measurement_prepared:
            raise RuntimeError("Stage-2 signatures must be prepared before measurement")
        signature = self.authority.resolve(
            batch, gradient_checkpointing=bool(self.config.gradient_checkpointing),
        )
        if not self.graph_pool.contains(signature):
            self._captures_during_measured_window += 1
            raise RuntimeError("Stage-2 measured window cannot capture a graph")
        self._copy_tensors(self._static_batches[signature], batch)
        self._bind_gradient_workspace(
            signature=signature, active_expert=str(batch["active_expert"]),
        )
        self.optimizer.zero_grad(set_to_none=False)
        self.graph_pool.replay(signature)
        return self._loss_outputs[signature]

    def after_optimizer_step(self) -> int:
        self._optimizer_steps += 1
        refreshed = refresh_fp8_after_optimizer_step(self.model)
        self._refreshes += refreshed
        return refreshed

    def receipt(self) -> dict[str, object]:
        graph = self.graph_pool.receipt()
        kernels = [site.kernel_receipt() for site in iter_fp8_down_projections(self.model)]
        return {
            "schema_version": "ember-stage2-runtime-receipt-v1",
            "census_raw_sha256": self.authority.census_raw_sha256,
            "census_self_sha256": self.authority.census_self_sha256,
            "installed_sites": self.installation_receipt["installed_sites"],
            "optimizer_steps": self._optimizer_steps,
            "fp8_weight_refreshes": self._refreshes,
            "fp8_dispatches": sum(int(item["dispatches"]) for item in kernels),
            "fp8_fallbacks": sum(int(item["fallbacks"]) for item in kernels),
            "cuda_graph_captures": graph["captures"],
            "captures_during_preparation": self._captures_during_preparation,
            "captures_during_measured_window": self._captures_during_measured_window,
            "cuda_graph_replays": graph["replays"],
            "cuda_graph_fallbacks": graph["fallbacks"],
            "shared_trunk_gradient_parameters": len(self._shared_gradient_parameters),
            "shared_trunk_gradient_bytes": self._parameter_bytes(self._shared_gradient_parameters),
            "expert_bank_gradient_workspace_parameters": len(self._gradient_workspace or ()),
            "gradient_workspace_bytes": self._parameter_bytes(self._gradient_workspace or ()),
            "gradient_workspace_rebinds": self._gradient_workspace_reuses,
            "inactive_grad_none_assertions": self._inactive_grad_none_assertions,
            "capture_gradient_zeroing": "eager_default_stream_outside_capture",
            "preparation_memory_allocated_bytes_by_signature": dict(
                self._preparation_memory_allocated_bytes_by_signature
            ),
            "kernel_receipts": kernels,
            "graph_receipt": graph,
        }


def _verified_capabilities(record: Mapping[str, object], *, active_expert: str) -> set[str]:
    """Execute the exact local verifier before semantic capability credit is counted."""

    if active_expert not in DOMAIN_MODALITIES:
        raise ValueError("record must select a declared routed expert")
    capabilities = {"text", *DOMAIN_MODALITIES[active_expert]}
    if active_expert in {"vision", "audio", "shared"}:
        return capabilities
    receipt = record.get("capability_receipt")
    if not isinstance(receipt, Mapping):
        raise ValueError(f"{active_expert} episode requires a content-addressed local verifier receipt")
    verifier_hash = hashlib.sha256(VERIFIER_PATH.read_bytes()).hexdigest()
    if receipt.get("verifier_path") != VERIFIER_PUBLIC_PATH or receipt.get("verifier_sha256") != verifier_hash:
        raise ValueError("capability receipt is not bound to the exact local verifier bytes")
    encoded = base64.b64encode(json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")).decode("ascii")
    completed = subprocess.run(
        # -B: -I also drops PYTHONDONTWRITEBYTECODE, and VERIFIER_PATH is in-tree.
        [sys.executable, "-I", "-B", str(VERIFIER_PATH), "--record-json-base64", encoded],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"local {active_expert} verifier did not pass: {completed.stderr.strip() or completed.stdout.strip()}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("local capability verifier emitted invalid JSON") from error
    if not isinstance(result, dict) or result.get("result") != "PASSED" or result.get("receipt") != dict(receipt):
        raise ValueError("local verifier result does not reproduce the content-addressed receipt")
    capabilities.add(active_expert)
    return capabilities


def _expert_routing_entropy(counts: Mapping[str, int]) -> tuple[float, dict[str, float]]:
    """Derive router/expert entropy and per-expert utilization from cumulative routing counts.

    p_i = count_i / total; H = -sum(p_i * log(p_i)) in nats (natural log), applying the
    0 * log(0) = 0 convention for experts not yet selected. Before any routed expert has
    been selected (total == 0) entropy and every utilization fraction are 0.0.

    COUNTING WINDOW: `counts` is the caller's counter, cumulative since the start of the
    current run_pretraining_segment / run_selection_pretraining_segment call -- NOT since
    training began. That counter is reinitialized to all-zero at the top of every such
    call (see expert_examples there), so this entropy resets to 0.0 (fully concentrated)
    at the first routed step after every resume. A telemetry consumer watching a real
    multi-segment run will see it ramp from zero at every resume; that is a counting-
    window artifact of the call boundary, not evidence of router collapse-and-recovery.
    """
    total = sum(counts.values())
    if total <= 0:
        return 0.0, {name: 0.0 for name in counts}
    utilization = {name: count / total for name, count in counts.items()}
    entropy = -sum(fraction * math.log(fraction) for fraction in utilization.values() if fraction > 0.0)
    # A single 1.0 * log(1.0) term negated is -0.0 in IEEE 754 (all traffic on one
    # expert). json.dumps(-0.0) serializes the literal "-0.0" into the receipted
    # telemetry JSONL, which is a spurious sign on a value that is definitionally
    # nonnegative -- normalize it away rather than let a persisted receipt carry it.
    if entropy == 0.0:
        entropy = 0.0
    return entropy, utilization


def run_pretraining_segment(
    *,
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    records: Sequence[dict[str, object]],
    config: RestartDecoderConfig,
    device: torch.device,
    checkpoint_every: int,
    checkpoint_callback: CheckpointCallback,
    progress_callback: ProgressCallback | None = None,
    signature_observer: SignatureObserver | None = None,
    stage2_executor: CensusBoundStage2Executor | None = None,
    measurement_preparation_regions_per_signature: int = 0,
    initial_global_step: int = 0,
    initial_tokens_seen: int = 0,
    initial_data_cursor: int = 0,
    data_shard_id: str = "owned-pretraining",
    require_complete_coverage: bool = True,
    max_records: int | None = None,
) -> dict[str, Any]:
    """Execute verified routed updates and bind counters needed for exact resume."""

    if not records:
        raise ValueError("pretraining segment requires at least one owned record")
    if checkpoint_every <= 0:
        raise ValueError("checkpoint_every must be positive")
    if min(initial_global_step, initial_tokens_seen, initial_data_cursor) < 0:
        raise ValueError("resume counters must be nonnegative")
    if initial_data_cursor > len(records):
        raise ValueError("resume data cursor exceeds the bound record sequence")
    if max_records is not None and (type(max_records) is not int or max_records < 1 or max_records > 200):
        raise ValueError("pretraining max_records must be an integer from 1 through 200")
    if not isinstance(data_shard_id, str) or not data_shard_id:
        raise ValueError("data_shard_id must be a nonempty owned shard identifier")
    if signature_observer is not None and stage2_executor is not None:
        raise ValueError("an activating run cannot mint its own signature census")
    if (
        type(measurement_preparation_regions_per_signature) is not int
        or measurement_preparation_regions_per_signature < 0
    ):
        raise ValueError("measurement preparation regions must be a nonnegative integer")
    if stage2_executor is not None and measurement_preparation_regions_per_signature < 1:
        raise ValueError("Stage-2 measurement requires out-of-window preparation")
    model.train()
    losses: list[float] = []
    modality_examples = {"text": 0, "image": 0, "audio": 0, "reasoning": 0, "tool": 0}
    expert_examples = {expert: 0 for expert in EXPERT_NAMES}
    tokens_seen = initial_tokens_seen
    data_cursor = initial_data_cursor
    remaining_records = records[initial_data_cursor:] if max_records is None else records[initial_data_cursor:initial_data_cursor + max_records]
    final_global_step = initial_global_step + len(remaining_records)
    measurement_preparation = {
        "regions_per_signature": 0,
        "signature_count": 0,
        "region_count": 0,
        "optimizer_state_preinitialized_parameters": 0,
        "no_capture_in_measured_window": True,
    }
    optimizer_state_parameters = 0
    if measurement_preparation_regions_per_signature:
        measurement_trainable_parameters = _measurement_trainable_parameters(
            model, remaining_records,
        )
        optimizer_state_parameters = _preinitialize_optimizer_state(
            optimizer,
            trainable_parameters=measurement_trainable_parameters,
        )
        prepared_batches = [
            decode_owned_batch(record, config, device=device)
            for record in remaining_records
        ]
        initial_cursor_identity = hashlib.sha256(
            json.dumps(
                {
                    "record_index": initial_data_cursor,
                    "global_step": initial_global_step,
                    "tokens_seen": initial_tokens_seen,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if stage2_executor is not None:
            measurement_preparation = stage2_executor.prepare_for_measurement(
                prepared_batches,
                cursor_identity=initial_cursor_identity,
                regions_per_signature=measurement_preparation_regions_per_signature,
            )
            measurement_preparation = {
                **measurement_preparation,
                "optimizer_state_preinitialized_parameters": optimizer_state_parameters,
            }
        else:
            unique_batches: dict[str, Mapping[str, object]] = {}
            for batch in prepared_batches:
                signature = str(training_step_signature(
                    batch,
                    gradient_checkpointing=bool(config.gradient_checkpointing),
                )["signature_sha256"])
                unique_batches.setdefault(signature, batch)
            for signature in sorted(unique_batches):
                batch = unique_batches[signature]
                for _ in range(measurement_preparation_regions_per_signature):
                    optimizer.zero_grad(set_to_none=True)
                    _eager_forward_loss_backward(model, batch, config)
            optimizer.zero_grad(set_to_none=True)
            measurement_preparation = {
                "regions_per_signature": measurement_preparation_regions_per_signature,
                "signature_count": len(unique_batches),
                "region_count": (
                    measurement_preparation_regions_per_signature * len(unique_batches)
                ),
                "optimizer_state_preinitialized_parameters": optimizer_state_parameters,
                "no_capture_in_measured_window": True,
            }
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        del prepared_batches
    elapsed_step_seconds = 0.0
    step_timings_seconds: list[float] = []
    for local_step, record in enumerate(remaining_records, start=1):
        step_started = time.perf_counter()
        batch = decode_owned_batch(record, config, device=device)
        active_expert = batch["active_expert"]
        capabilities = _verified_capabilities(record, active_expert=active_expert)
        if signature_observer is not None:
            signature_observer(
                training_step_signature(
                    batch,
                    gradient_checkpointing=bool(config.gradient_checkpointing),
                )
            )
        if stage2_executor is None:
            optimizer.zero_grad(set_to_none=True)
            try:
                loss = _eager_forward_loss_backward(model, batch, config)
            except RuntimeError as error:
                if "non-finite loss" not in str(error):
                    raise
                raise RuntimeError(
                    f"pretraining segment stopped on non-finite loss at step "
                    f"{initial_global_step + local_step}"
                ) from error
        else:
            cursor_identity = hashlib.sha256(
                json.dumps(
                    {"record_index": data_cursor, "global_step": initial_global_step + local_step - 1,
                     "tokens_seen": tokens_seen},
                    sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            loss = stage2_executor.forward_loss_backward(
                batch, cursor_identity=cursor_identity,
            )
        if not torch.isfinite(loss):
            raise RuntimeError(f"pretraining segment stopped on non-finite loss at step {initial_global_step + local_step}")
        grad_norm_tensor = torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        if stage2_executor is not None:
            stage2_executor.assert_optimizer_membership()
        if optimizer_state_parameters:
            _require_preinitialized_gradient_state(optimizer)
        optimizer.step()
        if stage2_executor is not None:
            stage2_executor.after_optimizer_step()
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        losses.append(float(loss.detach().cpu()))
        step_elapsed = time.perf_counter() - step_started
        step_timings_seconds.append(step_elapsed)
        elapsed_step_seconds += step_elapsed
        step_tokens = int(batch["input_ids"].numel())
        tokens_seen += step_tokens
        data_cursor += 1
        if active_expert in EXPERT_NAMES:
            expert_examples[active_expert] += 1
        for capability in capabilities:
            modality_examples[capability] += 1
        global_step = initial_global_step + local_step
        cursor = {"shard": data_shard_id, "record_index": data_cursor, "global_step": global_step, "tokens_seen": tokens_seen}
        result = {
            "step": global_step, "global_step": global_step, "losses": list(losses), "tokens_seen": tokens_seen,
            "data_cursor": cursor, "modality_examples": dict(modality_examples),
            "expert_examples": dict(expert_examples), "active_expert": active_expert,
        }
        if progress_callback is not None:
            # clip_grad_norm_ (torch 2.10: torch/nn/utils/clip_grad.py) computes the
            # total norm via a sync-free foreach reduction and returns it BEFORE the
            # in-place clip scaling is applied to .grad -- this is the pre-clip
            # gradient norm. The float() conversion below piggybacks on the device
            # sync the loss capture above already forced, so it adds no new
            # synchronization barrier and no measurable step-time regression.
            #
            # router_entropy_nats / expert_utilization: see _expert_routing_entropy's
            # docstring -- counted since THIS call started (expert_examples above is
            # reinitialized to all-zero on every call), not since training began, so
            # it resets to 0.0 at the first routed step after every resume.
            expert_entropy, expert_utilization = _expert_routing_entropy(expert_examples)
            progress_callback({
                "step": global_step,
                "total_steps": final_global_step,
                "loss": losses[-1],
                "step_ms": float((time.perf_counter() - step_started) * 1000.0),
                "tokens_consumed": step_tokens,
                "grad_norm": float(grad_norm_tensor),
                "router_entropy_nats": expert_entropy,
                "expert_utilization": expert_utilization,
            })
        if global_step % checkpoint_every == 0 or local_step == len(remaining_records):
            checkpoint_callback(global_step, result)
    if require_complete_coverage:
        missing_capabilities = [name for name, value in modality_examples.items() if value <= 0]
        missing_experts = [name for name, value in expert_examples.items() if value <= 0]
        if missing_capabilities or missing_experts:
            raise RuntimeError(
                "pretraining segment stopped because required exposure is missing: "
                f"capabilities={missing_capabilities}, experts={missing_experts}"
            )
    return {
        "steps": len(remaining_records), "global_step": initial_global_step + len(remaining_records), "losses": losses,
        "tokens_seen": tokens_seen,
        "data_cursor": {"shard": data_shard_id, "record_index": data_cursor, "global_step": initial_global_step + len(remaining_records), "tokens_seen": tokens_seen},
        "modality_examples": modality_examples, "expert_examples": expert_examples,
        "measurement_preparation": measurement_preparation,
        "step_timings_seconds": step_timings_seconds,
        "step_elapsed_seconds": elapsed_step_seconds,
        "tokens_per_second": (
            (tokens_seen - initial_tokens_seen) / elapsed_step_seconds
            if elapsed_step_seconds > 0.0 else 0.0
        ),
        "stage2_runtime": stage2_executor.receipt() if stage2_executor is not None else None,
    }


def run_selection_pretraining_segment(
    *,
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    selection: object,
    config: RestartDecoderConfig,
    device: torch.device,
    checkpoint_every: int,
    checkpoint_callback: CheckpointCallback,
    progress_callback: ProgressCallback | None = None,
    initial_selection_cursor: Mapping[str, object] | None = None,
    initial_global_step: int = 0,
    initial_tokens_seen: int = 0,
    max_records: int | None = None,
    require_complete_coverage: bool = True,
) -> dict[str, Any]:
    """Train a bounded specialist selection through its sequential cursor interface only."""

    if checkpoint_every <= 0:
        raise ValueError("checkpoint_every must be positive")
    if min(initial_global_step, initial_tokens_seen) < 0:
        raise ValueError("resume counters must be nonnegative")
    if max_records is not None and (type(max_records) is not int or max_records <= 0):
        raise ValueError("max_records must be a positive integer when supplied")
    if not isinstance(getattr(selection, "receipt", None), Mapping):
        raise ValueError("selection consumer requires a bound selection receipt")
    iter_from = getattr(selection, "iter_from", None)
    if not callable(iter_from):
        raise ValueError("selection consumer requires sequential iter_from")

    model.train()
    losses: list[float] = []
    modality_examples = {"text": 0, "image": 0, "audio": 0, "reasoning": 0, "tool": 0}
    expert_examples = {expert: 0 for expert in EXPERT_NAMES}
    tokens_seen = initial_tokens_seen
    completed = 0
    last_cursor: dict[str, object] | None = None
    last_result: dict[str, Any] | None = None
    last_checkpoint_step: int | None = None
    for item in iter_from(initial_selection_cursor):
        if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], Mapping) or not isinstance(item[1], Mapping):
            raise ValueError("selection iterator must yield a record and exact next cursor")
        record = dict(item[0])
        next_selection_cursor = dict(item[1])
        step_started = time.perf_counter()
        batch = decode_owned_batch(record, config, device=device)
        active_expert = batch["active_expert"]
        capabilities = _verified_capabilities(record, active_expert=active_expert)
        optimizer.zero_grad(set_to_none=True)
        logits = model(
            batch["input_ids"], image_patches=batch["image_patches"], audio_frames=batch["audio_frames"],
            image_coordinates=batch["image_coordinates"], spans=batch["spans"], active_expert=active_expert,
        )
        loss = F.cross_entropy(logits.float().reshape(-1, config.vocab_size), batch["target_ids"].reshape(-1))
        if not torch.isfinite(loss):
            raise RuntimeError(f"pretraining selection stopped on non-finite loss at step {initial_global_step + completed + 1}")
        loss.backward()
        grad_norm_tensor = torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        completed += 1
        step_tokens = int(batch["input_ids"].numel())
        tokens_seen += step_tokens
        losses.append(float(loss.detach().cpu()))
        if active_expert in EXPERT_NAMES:
            expert_examples[active_expert] += 1
        for capability in capabilities:
            modality_examples[capability] += 1
        global_step = initial_global_step + completed
        last_cursor = next_selection_cursor
        training_cursor = {
            "schema_version": TRAINING_CURSOR_SCHEMA_VERSION,
            "selection_cursor": dict(last_cursor),
            "global_step": global_step,
            "tokens_seen": tokens_seen,
        }
        last_result = {
            "step": global_step, "global_step": global_step, "losses": list(losses), "tokens_seen": tokens_seen,
            "data_cursor": training_cursor, "modality_examples": dict(modality_examples),
            "expert_examples": dict(expert_examples), "active_expert": active_expert,
        }
        if progress_callback is not None:
            # See run_pretraining_segment: piggybacks on the loss sync above, and
            # grad_norm_tensor is the pre-clip norm clip_grad_norm_ already returns.
            # router_entropy_nats / expert_utilization: see _expert_routing_entropy's
            # docstring -- counted since THIS call started (expert_examples above is
            # reinitialized to all-zero on every call), not since training began.
            expert_entropy, expert_utilization = _expert_routing_entropy(expert_examples)
            progress_callback({
                "step": global_step, "total_steps": None, "loss": losses[-1],
                "step_ms": float((time.perf_counter() - step_started) * 1000.0),
                "tokens_consumed": step_tokens,
                "grad_norm": float(grad_norm_tensor),
                "router_entropy_nats": expert_entropy,
                "expert_utilization": expert_utilization,
            })
        if global_step % checkpoint_every == 0:
            checkpoint_callback(global_step, last_result)
            last_checkpoint_step = global_step
        if max_records is not None and completed >= max_records:
            break
    if last_result is None or last_cursor is None:
        raise ValueError("selection consumer requires at least one selected record")
    if last_checkpoint_step != last_result["global_step"]:
        checkpoint_callback(int(last_result["global_step"]), last_result)
    if require_complete_coverage:
        missing_capabilities = [name for name, value in modality_examples.items() if value <= 0]
        missing_experts = [name for name, value in expert_examples.items() if value <= 0]
        if missing_capabilities or missing_experts:
            raise RuntimeError(
                "pretraining selection stopped because required exposure is missing: "
                f"capabilities={missing_capabilities}, experts={missing_experts}"
            )
    return {
        "steps": completed, "global_step": int(last_result["global_step"]), "losses": losses,
        "tokens_seen": tokens_seen, "data_cursor": dict(last_result["data_cursor"]),
        "modality_examples": modality_examples, "expert_examples": expert_examples,
    }
def run_manifest_bound_semantic_segment(
    *,
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    stream: ManifestBoundTokenStream,
    config: RestartDecoderConfig,
    device: torch.device,
    sequence_length: int,
    steps: int,
    checkpoint_every: int,
    checkpoint_callback: CheckpointCallback,
    progress_callback: ProgressCallback | None = None,
    initial_data_cursor: Mapping[str, object] | None = None,
    initial_global_step: int = 0,
    initial_tokens_seen: int = 0,
) -> dict[str, Any]:
    """Train bounded shared-text episodes while preserving receipt-bound shard resume state."""

    if not isinstance(sequence_length, int) or sequence_length < 1:
        raise ValueError("semantic stream sequence_length must be positive")
    if not isinstance(steps, int) or steps < 1:
        raise ValueError("semantic stream steps must be positive")
    if type(initial_global_step) is not int or type(initial_tokens_seen) is not int or min(initial_global_step, initial_tokens_seen) < 0:
        raise ValueError("semantic stream resume counters must be nonnegative integers")
    expected_shard = "TOKEN-SHARDS-V0:" + stream.receipt_sha256[:12]
    if initial_data_cursor is None:
        shard_index, token_offset = 0, 0
    else:
        if not isinstance(initial_data_cursor, Mapping):
            raise ValueError("semantic stream resume cursor is malformed")
        if (
            initial_data_cursor.get("receipt_sha256") != stream.receipt_sha256
            or initial_data_cursor.get("tokenizer_sha256") != stream.tokenizer_sha256
        ):
            raise ValueError("semantic stream resume cursor does not bind this receipt and tokenizer")
        if (
            initial_data_cursor.get("shard") != expected_shard
            or type(initial_data_cursor.get("record_index")) is not int
            or initial_data_cursor["record_index"] != initial_global_step
            or type(initial_data_cursor.get("global_step")) is not int
            or initial_data_cursor["global_step"] != initial_global_step
            or type(initial_data_cursor.get("tokens_seen")) is not int
            or initial_data_cursor["tokens_seen"] != initial_tokens_seen
        ):
            raise ValueError("semantic stream resume cursor identity is inconsistent")
        shard_index = initial_data_cursor.get("shard_index")
        token_offset = initial_data_cursor.get("token_offset")
        if type(shard_index) is not int or type(token_offset) is not int or shard_index < 0 or token_offset < 0:
            raise ValueError("semantic stream resume cursor is malformed")

    records: list[dict[str, object]] = []
    cursors: list[dict[str, int]] = []
    for _ in range(steps):
        episode, next_cursor = stream.next_episode(
            shard_index=shard_index,
            token_offset=token_offset,
            sequence_length=sequence_length,
        )
        records.append(episode)
        cursors.append(next_cursor)
        shard_index, token_offset = next_cursor["shard_index"], next_cursor["token_offset"]

    def bound_cursor(cursor: Mapping[str, int], global_step: int, tokens_seen: int) -> dict[str, object]:
        return {
            "shard": "TOKEN-SHARDS-V0:" + stream.receipt_sha256[:12],
            "record_index": global_step,
            "receipt_sha256": stream.receipt_sha256,
            "tokenizer_sha256": stream.tokenizer_sha256,
            "shard_index": cursor["shard_index"],
            "token_offset": cursor["token_offset"],
            "global_step": global_step,
            "tokens_seen": tokens_seen,
        }

    def stream_checkpoint(global_step: int, state: dict[str, Any]) -> None:
        local_index = global_step - initial_global_step - 1
        checkpoint_state = dict(state)
        checkpoint_state["data_cursor"] = bound_cursor(
            cursors[local_index],
            global_step,
            int(state["tokens_seen"]),
        )
        checkpoint_callback(global_step, checkpoint_state)

    result = run_pretraining_segment(
        model=model,
        optimizer=optimizer,
        records=records,
        config=config,
        device=device,
        checkpoint_every=checkpoint_every,
        checkpoint_callback=stream_checkpoint,
        progress_callback=progress_callback,
        initial_global_step=initial_global_step,
        initial_tokens_seen=initial_tokens_seen,
        data_shard_id="TOKEN-SHARDS-V0:" + stream.receipt_sha256[:12],
        require_complete_coverage=False,
    )
    result["data_cursor"] = bound_cursor(
        cursors[-1],
        int(result["global_step"]),
        int(result["tokens_seen"]),
    )
    return result
