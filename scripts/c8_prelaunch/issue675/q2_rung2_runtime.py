# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Import-safe rung-2 model/loss primitives for the issue #675 event.

This module cannot train, checkpoint, resume, or dispatch a model.  It exposes
only current-source model reconstruction, frozen-batch gradient derivation,
and target-only paired-loss replay required by the signed #675 contract.
"""

from __future__ import annotations

import math
from contextlib import nullcontext
from typing import Mapping, Sequence

import torch


class Rung2RuntimeRefusal(ValueError):
    """Named refusal before an actual-event capture can be selected."""


def _refuse(code: str) -> None:
    raise Rung2RuntimeRefusal(code)


def build_rung2_model(
    config: Mapping[str, object], *, intermediate_size: int, device: str
):
    """Build the exact historical cbase architecture without its trainer."""

    try:
        from transformers import LlamaConfig, LlamaModel  # type: ignore

        model_cfg = config["model"]
        objective = config["objective"]
        mtp = objective["mtp_aux_heads"]
        if not isinstance(model_cfg, Mapping) or not isinstance(mtp, Mapping):
            raise TypeError
        if not isinstance(intermediate_size, int) or isinstance(intermediate_size, bool) or intermediate_size <= 0:
            raise TypeError
        vocab = int(model_cfg["vocab"])
        hidden = int(model_cfg["hidden"])
        layers = int(model_cfg["layers"])
        heads = int(model_cfg["heads"])
        seq = int(model_cfg["seq"])
        n_mtp = int(mtp["n_heads"])
        tied = model_cfg["tied_embeddings"]
        grad_checkpointing = model_cfg.get("grad_checkpointing", False)
    except (ImportError, KeyError, TypeError, ValueError):
        _refuse("RUNTIME_MODEL_CONFIG_INVALID")
    if (
        any(value <= 0 for value in (vocab, hidden, layers, heads, seq))
        or n_mtp < 0
        or tied not in (True, False)
        or grad_checkpointing not in (True, False)
    ):
        _refuse("RUNTIME_MODEL_CONFIG_INVALID")

    class _Rung2Model(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            llama = LlamaConfig(
                vocab_size=vocab,
                hidden_size=hidden,
                intermediate_size=intermediate_size,
                num_hidden_layers=layers,
                num_attention_heads=heads,
                num_key_value_heads=heads,
                max_position_embeddings=seq,
                tie_word_embeddings=False,
            )
            self.backbone_model = LlamaModel(llama)
            self.head = torch.nn.Linear(hidden, vocab, bias=False)
            if tied:
                self.head.weight = self.backbone_model.embed_tokens.weight
            self.mtp_heads = torch.nn.ModuleList(
                [torch.nn.Linear(hidden, vocab, bias=False) for _ in range(n_mtp)]
            )

        def backbone(self, ids: torch.Tensor) -> torch.Tensor:
            return self.backbone_model(input_ids=ids).last_hidden_state

    model = _Rung2Model().to(device).to(torch.bfloat16)
    if grad_checkpointing:
        model.backbone_model.gradient_checkpointing_enable()
    return model, vocab, hidden, n_mtp


def chunked_cross_entropy(
    hidden: torch.Tensor,
    weight: torch.Tensor,
    targets: torch.Tensor,
    *,
    chunk_tokens: int = 256,
    ignore_index: int = -100,
) -> tuple[torch.Tensor, int]:
    if not isinstance(chunk_tokens, int) or isinstance(chunk_tokens, bool) or chunk_tokens <= 0:
        _refuse("RUNTIME_CE_CHUNK_INVALID")
    total_nll = hidden.new_zeros(())
    n_valid = 0
    for start in range(0, hidden.shape[0], chunk_tokens):
        end = min(start + chunk_tokens, hidden.shape[0])
        logits = hidden[start:end] @ weight.T
        logp = torch.log_softmax(logits, dim=-1)
        selected = targets[start:end]
        mask = selected != ignore_index
        safe = selected.clamp(min=0).unsqueeze(-1)
        nll = -logp.gather(-1, safe).squeeze(-1)
        total_nll = total_nll + (nll * mask).sum()
        n_valid += int(mask.sum())
    if n_valid == 0:
        _refuse("RUNTIME_BATCH_HAS_NO_VALID_TARGETS")
    return total_nll / n_valid, n_valid


def _cpu_contiguous_clone(value: torch.Tensor) -> torch.Tensor:
    return value.detach().to(device="cpu").contiguous().clone()


def _cpu_state_snapshot(model: torch.nn.Module) -> dict[str, torch.Tensor]:
    return {key: _cpu_contiguous_clone(value) for key, value in model.state_dict().items()}


def _state_matches_cpu_snapshot(
    state: Mapping[str, torch.Tensor], baseline: Mapping[str, torch.Tensor]
) -> bool:
    return set(state) == set(baseline) and all(
        state[key].dtype == baseline[key].dtype
        and state[key].shape == baseline[key].shape
        and torch.equal(state[key].detach().to(device="cpu").contiguous(), baseline[key])
        for key in baseline
    )


def _apply_fake_quant(model: torch.nn.Module) -> list[tuple[torch.nn.Module, torch.Tensor]]:
    saved = []
    try:
        for module in model.modules():
            if isinstance(module, torch.nn.Linear):
                weight = module.weight.data
                saved.append((module, _cpu_contiguous_clone(weight)))
                scale = weight.abs().amax(dim=1, keepdim=True).clamp(min=1e-8) / 127.0
                quantized = (weight / scale).round().clamp(-127, 127) * scale
                with torch.no_grad():
                    module.weight.copy_(quantized)
    except BaseException:
        _restore_weights(saved)
        raise
    return saved


def _restore_weights(saved: Sequence[tuple[torch.nn.Module, torch.Tensor]]) -> None:
    for module, weight in saved:
        with torch.no_grad():
            module.weight.copy_(weight)


def _runtime_config(config: Mapping[str, object]) -> tuple[bool, bool, float, int]:
    try:
        qat = config["precision"]["qat"]["enabled"]
        mtp = config["objective"]["mtp_aux_heads"]
        enabled = mtp["enabled"]
        weight = float(mtp["weight"])
        n_heads = int(mtp["n_heads"])
    except (KeyError, TypeError, ValueError):
        _refuse("RUNTIME_CONFIG_INVALID")
    if (
        qat not in (True, False)
        or enabled not in (True, False)
        or not math.isfinite(weight)
        or weight < 0
        or n_heads < 0
        or (enabled and n_heads == 0)
    ):
        _refuse("RUNTIME_CONFIG_INVALID")
    return bool(qat), bool(enabled), weight, n_heads


def _validated_microsteps(
    microsteps: Sequence[Mapping[str, object]], *, n_mtp: int
) -> list[tuple[torch.Tensor, torch.Tensor, list[torch.Tensor]]]:
    if not isinstance(microsteps, Sequence) or isinstance(microsteps, (str, bytes)) or not microsteps:
        _refuse("RUNTIME_BATCH_SCHEMA_INVALID")
    rows = []
    for row in microsteps:
        if not isinstance(row, Mapping) or set(row) != {"x", "y0", "y_mtp"}:
            _refuse("RUNTIME_BATCH_SCHEMA_INVALID")
        x, y0, y_mtp = row["x"], row["y0"], row["y_mtp"]
        if (
            not isinstance(x, torch.Tensor)
            or not isinstance(y0, torch.Tensor)
            or x.dtype != torch.int64
            or y0.dtype != torch.int64
            or x.shape != y0.shape
            or x.ndim != 2
            or not isinstance(y_mtp, list)
            or len(y_mtp) != n_mtp
            or any(
                not isinstance(value, torch.Tensor)
                or value.dtype != torch.int64
                or value.shape != x.shape
                for value in y_mtp
            )
        ):
            _refuse("RUNTIME_BATCH_SCHEMA_INVALID")
        rows.append((x, y0, list(y_mtp)))
    return rows


def _losses(
    *,
    model: torch.nn.Module,
    microsteps: Sequence[Mapping[str, object]],
    config: Mapping[str, object],
    device: str,
    backward: bool,
) -> tuple[torch.Tensor, str]:
    qat, mtp_enabled, mtp_weight, n_mtp = _runtime_config(config)
    rows = _validated_microsteps(microsteps, n_mtp=n_mtp)
    if any(isinstance(module, torch.nn.Dropout) and module.p != 0 for module in model.modules()):
        _refuse("RUNTIME_NONDETERMINISTIC_DROPOUT")
    losses = []
    for x, y0, y_mtp in rows:
        saved = _apply_fake_quant(model) if qat else []
        try:
            hidden = model.backbone(x.to(device))
            flat = hidden.reshape(-1, hidden.shape[-1])
            primary, _ = chunked_cross_entropy(
                flat, model.head.weight, y0.to(device).reshape(-1)
            )
            mtp_losses = []
            if mtp_enabled:
                if len(model.mtp_heads) != n_mtp:
                    _refuse("RUNTIME_MTP_HEAD_MISMATCH")
                for index, head in enumerate(model.mtp_heads):
                    value, _ = chunked_cross_entropy(
                        flat, head.weight, y_mtp[index].to(device).reshape(-1)
                    )
                    mtp_losses.append(value)
            loss = primary
            if mtp_losses:
                loss = primary + mtp_weight * torch.stack(mtp_losses).mean()
            if not torch.isfinite(loss):
                _refuse("RUNTIME_LOSS_NONFINITE")
            losses.append(loss)
            if backward:
                (loss / len(rows)).backward()
        finally:
            _restore_weights(saved)
    return torch.stack(losses).mean(), "cut_ce_chunked"


def _saved_tensor_context(device: str):
    """Offload autograd-saved CUDA tensors without changing forward math."""

    return (
        torch.autograd.graph.save_on_cpu(pin_memory=False)
        if torch.device(device).type == "cuda"
        else nullcontext()
    )


def _target_only_gradient(
    *,
    model: torch.nn.Module,
    microsteps: Sequence[Mapping[str, object]],
    config: Mapping[str, object],
    target: torch.Tensor,
    device: str,
) -> tuple[torch.Tensor, torch.Tensor, str]:
    """Differentiate one target while keeping saved activations off CUDA."""

    qat, mtp_enabled, mtp_weight, n_mtp = _runtime_config(config)
    rows = _validated_microsteps(microsteps, n_mtp=n_mtp)
    if any(isinstance(module, torch.nn.Dropout) and module.p != 0 for module in model.modules()):
        _refuse("RUNTIME_NONDETERMINISTIC_DROPOUT")
    gradient = torch.zeros_like(target, device="cpu", dtype=torch.float32)
    losses = []
    for x, y0, y_mtp in rows:
        saved = _apply_fake_quant(model) if qat else []
        try:
            with _saved_tensor_context(device):
                hidden = model.backbone(x.to(device))
                flat = hidden.reshape(-1, hidden.shape[-1])
                primary, _ = chunked_cross_entropy(
                    flat, model.head.weight, y0.to(device).reshape(-1)
                )
                mtp_losses = []
                if mtp_enabled:
                    if len(model.mtp_heads) != n_mtp:
                        _refuse("RUNTIME_MTP_HEAD_MISMATCH")
                    for index, head in enumerate(model.mtp_heads):
                        value, _ = chunked_cross_entropy(
                            flat, head.weight, y_mtp[index].to(device).reshape(-1)
                        )
                        mtp_losses.append(value)
                loss = primary
                if mtp_losses:
                    loss = primary + mtp_weight * torch.stack(mtp_losses).mean()
                if not torch.isfinite(loss):
                    _refuse("RUNTIME_LOSS_NONFINITE")
                (row_gradient,) = torch.autograd.grad(
                    loss / len(rows), target, allow_unused=False
                )
            gradient.add_(
                row_gradient.detach().to(device="cpu", dtype=torch.float32)
            )
            losses.append(loss.detach().to(device="cpu"))
        finally:
            _restore_weights(saved)
    return gradient, torch.stack(losses).mean(), "cut_ce_chunked"


def compute_frozen_batch_gradient(
    *,
    model: torch.nn.Module,
    microsteps: Sequence[Mapping[str, object]],
    config: Mapping[str, object],
    target_name: str,
    device: str,
) -> tuple[torch.Tensor, float, str]:
    """Derive G from the exact frozen batch without mutating model bytes."""

    try:
        target = model.get_parameter(target_name)
    except (AttributeError, KeyError):
        _refuse("RUNTIME_TARGET_NOT_FOUND")
    if target.ndim != 2:
        _refuse("RUNTIME_TARGET_INVALID")
    baseline = _cpu_state_snapshot(model)
    training = model.training
    model.eval()
    model.zero_grad(set_to_none=True)
    try:
        gradient, loss, implementation = _target_only_gradient(
            model=model,
            microsteps=microsteps,
            config=config,
            target=target,
            device=device,
        )
        gradient = gradient.contiguous().clone()
        if not torch.isfinite(gradient).all() or gradient.shape != target.shape:
            _refuse("RUNTIME_TARGET_GRADIENT_INVALID")
        return gradient, float(loss.detach().to(device="cpu")), implementation
    finally:
        model.zero_grad(set_to_none=True)
        model.train(training)
        after = model.state_dict()
        if not _state_matches_cpu_snapshot(after, baseline):
            _refuse("RUNTIME_GRADIENT_MUTATED_MODEL")


def replay_target_only_loss(
    *,
    model: torch.nn.Module,
    microsteps: Sequence[Mapping[str, object]],
    config: Mapping[str, object],
    target_name: str,
    target: torch.Tensor,
    expected_non_target_state: Mapping[str, torch.Tensor],
    device: str,
) -> float:
    """Evaluate L_B(W+v) and restore the exact pre-state before returning."""

    baseline = _cpu_state_snapshot(model)
    if target_name not in baseline:
        _refuse("RUNTIME_TARGET_NOT_FOUND")
    actual_non_target = {key: value for key, value in baseline.items() if key != target_name}
    if set(actual_non_target) != set(expected_non_target_state) or any(
        actual_non_target[key].dtype != expected_non_target_state[key].dtype
        or actual_non_target[key].shape != expected_non_target_state[key].shape
        or not torch.equal(actual_non_target[key].cpu(), expected_non_target_state[key].cpu())
        for key in actual_non_target
    ):
        _refuse("RUNTIME_NON_TARGET_STATE_MISMATCH")
    if (
        not isinstance(target, torch.Tensor)
        or target.shape != baseline[target_name].shape
        or not torch.isfinite(target).all()
    ):
        _refuse("RUNTIME_TARGET_INVALID")
    try:
        parameter = model.get_parameter(target_name)
    except (AttributeError, KeyError):
        _refuse("RUNTIME_TARGET_NOT_FOUND")
    training = model.training
    model.eval()
    try:
        with torch.no_grad():
            parameter.copy_(target.to(device=parameter.device, dtype=parameter.dtype))
            loss, _implementation = _losses(
                model=model,
                microsteps=microsteps,
                config=config,
                device=device,
                backward=False,
            )
        value = float(loss.detach().to(device="cpu"))
        if not math.isfinite(value):
            _refuse("RUNTIME_LOSS_NONFINITE")
        return value
    finally:
        with torch.no_grad():
            parameter.copy_(baseline[target_name].to(parameter.device))
        model.train(training)
        after = model.state_dict()
        if not _state_matches_cpu_snapshot(after, baseline):
            _refuse("RUNTIME_REPLAY_RESTORE_FAILED")
