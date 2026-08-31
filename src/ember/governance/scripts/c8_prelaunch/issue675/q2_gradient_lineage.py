# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate the persisted post-grow gradient consumed by issue #675.

The historical B3 producer wrote ``grad_post_gate`` but did not bind its
bytes in the B3 receipt.  That receipt is therefore refused.  A governed
successor must bind the exact gradient bytes, pinned batch, target identity,
dtype, and shape before the actual-event adapter may select the tensor.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import torch


class GradientLineageRefusal(ValueError):
    """Named pre-capture refusal for an unbound post-grow gradient."""


def _refuse(code: str) -> None:
    raise GradientLineageRefusal(code)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        _refuse("GRADIENT_ARTIFACT_UNAVAILABLE")


def _require_sha(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        _refuse(code)
    return value


def _resolved_under(root: Path, logical: object) -> Path:
    if not isinstance(logical, str) or not logical or "\\" in logical:
        _refuse("GRADIENT_PATH_INVALID")
    relative = Path(logical)
    if relative.is_absolute() or ".." in relative.parts:
        _refuse("GRADIENT_PATH_INVALID")
    root = root.resolve(strict=True)
    candidate = (root / relative).resolve(strict=False)
    if not candidate.is_relative_to(root):
        _refuse("GRADIENT_PATH_INVALID")
    return candidate


def validate_gradient_lineage(
    *,
    b3_receipt_path: Path,
    persisted_gradient_path: Path,
    data_root: Path,
    target_name: str,
    expected_run_id: str,
    expected_batch_sha256: str,
) -> torch.Tensor:
    """Return the exact receipt-bound float32 gradient or refuse."""

    expected_batch_sha256 = _require_sha(
        expected_batch_sha256, "GRADIENT_BATCH_BINDING_INVALID"
    )
    try:
        receipt = json.loads(Path(b3_receipt_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _refuse("GRADIENT_RECEIPT_INVALID")
    if not isinstance(receipt, dict):
        _refuse("GRADIENT_RECEIPT_INVALID")
    if (
        receipt.get("ticket") != "CBASE-GROW-RUNG2-EVENT-B3"
        or receipt.get("run_id") != expected_run_id
        or receipt.get("verdict") != "B3_CAPTURED"
    ):
        _refuse("GRADIENT_RECEIPT_IDENTITY_MISMATCH")

    batch = receipt.get("batch_pin_check")
    if not isinstance(batch, dict) or set(batch) != {
        "b1m_sha256",
        "b3_recomputed_sha256",
        "match",
    }:
        _refuse("GRADIENT_BATCH_BINDING_MISMATCH")
    try:
        b1m_sha = _require_sha(batch["b1m_sha256"], "GRADIENT_BATCH_BINDING_MISMATCH")
        b3_sha = _require_sha(
            batch["b3_recomputed_sha256"], "GRADIENT_BATCH_BINDING_MISMATCH"
        )
    except KeyError:
        _refuse("GRADIENT_BATCH_BINDING_MISMATCH")
    if batch["match"] is not True or b1m_sha != b3_sha or b3_sha != expected_batch_sha256:
        _refuse("GRADIENT_BATCH_BINDING_MISMATCH")

    paths = receipt.get("cache_paths")
    if not isinstance(paths, dict) or set(paths) != {"grad_post_gate"}:
        _refuse("GRADIENT_PATH_INVALID")
    receipt_gradient = _resolved_under(data_root, paths["grad_post_gate"])
    try:
        supplied_gradient = Path(persisted_gradient_path).resolve(strict=True)
    except OSError:
        _refuse("GRADIENT_ARTIFACT_UNAVAILABLE")
    if receipt_gradient != supplied_gradient:
        _refuse("GRADIENT_PATH_MISMATCH")

    cache_sha = receipt.get("cache_sha256")
    if not isinstance(cache_sha, dict) or set(cache_sha) != {"grad_post_gate"}:
        _refuse("GRADIENT_HASH_MISSING")
    expected_gradient_sha = _require_sha(
        cache_sha["grad_post_gate"], "GRADIENT_HASH_INVALID"
    )
    if _sha256(supplied_gradient) != expected_gradient_sha:
        _refuse("GRADIENT_HASH_MISMATCH")

    lineage = receipt.get("gradient_lineage")
    if not isinstance(lineage, dict) or set(lineage) != {
        "target_name",
        "dtype",
        "shape",
        "source",
        "batch_sha256",
    }:
        _refuse("GRADIENT_LINEAGE_MISMATCH")
    shape = lineage.get("shape")
    if (
        lineage.get("target_name") != target_name
        or lineage.get("dtype") != "float32"
        or lineage.get("source") != "pinned-batch-backward"
        or lineage.get("batch_sha256") != expected_batch_sha256
        or not isinstance(shape, list)
        or len(shape) != 2
        or any(not isinstance(dim, int) or isinstance(dim, bool) or dim <= 0 for dim in shape)
    ):
        _refuse("GRADIENT_LINEAGE_MISMATCH")

    try:
        gradient = torch.load(supplied_gradient, map_location="cpu", weights_only=True)
    except Exception:
        _refuse("GRADIENT_TENSOR_INVALID")
    if (
        not isinstance(gradient, torch.Tensor)
        or gradient.dtype != torch.float32
        or list(gradient.shape) != shape
        or not gradient.is_contiguous()
        or not all(math.isfinite(float(value)) for value in gradient.flatten())
    ):
        _refuse("GRADIENT_TENSOR_INVALID")
    return gradient.detach().clone()
