# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind a terminal Ember Lab capture to the frozen issue #675 evaluator."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

from q2_capture_loader import load_capture


_LOGICAL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class CaptureAdjudicationRefusal(ValueError):
    """Named path-free refusal before a scientific receipt is selectable."""


def _refuse(code: str) -> None:
    raise CaptureAdjudicationRefusal(code)


def _bound_path(root: Path, logical_name: object) -> Path:
    if not isinstance(logical_name, str) or _LOGICAL_RE.fullmatch(logical_name) is None:
        _refuse("ADJUDICATOR_BINDING_NAME_INVALID")
    try:
        path = (root / logical_name).resolve(strict=True)
    except OSError:
        _refuse("ADJUDICATOR_BINDING_UNAVAILABLE")
    if path.parent != root:
        _refuse("ADJUDICATOR_BINDING_NAME_INVALID")
    return path


def _load_module(path: Path, name: str) -> ModuleType:
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            _refuse("ADJUDICATOR_MODULE_INVALID")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except CaptureAdjudicationRefusal:
        raise
    except Exception:
        _refuse("ADJUDICATOR_MODULE_LOAD_FAILED")


def adjudicate_capture(
    *,
    manifest_path: Path,
    dispatch_receipt_path: Path,
    terminal_receipt_path: Path,
) -> dict[str, object]:
    """Reopen bound bytes, recompute losses, and seal terminal custody."""

    manifest_path = Path(manifest_path).resolve(strict=True)
    root = manifest_path.parent
    admitted = load_capture(
        manifest_path, dispatch_receipt_path, terminal_receipt_path
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    binding_files = manifest.get("binding_files")
    if not isinstance(binding_files, dict):
        _refuse("ADJUDICATOR_BINDING_SCHEMA_INVALID")

    verifier = _load_module(
        _bound_path(root, binding_files.get("verifier_sha256")),
        f"q2_bound_verifier_{admitted['bindings']['verifier_sha256'][:12]}",
    )
    replay = _load_module(
        _bound_path(root, binding_files.get("replay_sha256")),
        f"q2_bound_replay_{admitted['bindings']['replay_sha256'][:12]}",
    )
    if not callable(getattr(replay, "loss_from_state", None)):
        _refuse("ADJUDICATOR_REPLAY_ENTRYPOINT_MISSING")
    try:
        threshold = json.loads(
            _bound_path(root, binding_files.get("threshold_sha256")).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("ADJUDICATOR_THRESHOLD_MALFORMED")

    identities = {
        "source_sha256": admitted["bindings"]["source_sha256"],
        "config_sha256": admitted["bindings"]["config_sha256"],
        "batch_sha256": admitted["bindings"]["batch_sha256"],
        "optimizer_sha256": admitted["bindings"]["optimizer_sha256"],
        "momentum_sha256": admitted["bindings"]["momentum_sha256"],
        "replay_sha256": admitted["bindings"]["replay_sha256"],
        "learning_rate": admitted["optimizer"]["learning_rate"],
        "optimizer_scale": admitted["optimizer"]["scale"],
        "optimizer_name": admitted["optimizer"]["name"],
        "capture_receipt_sha256": admitted["capture_manifest_sha256"],
        "event_authority": "FUTURE_CAPTURED_GPU_EVENT",
    }
    try:
        receipt = verifier.evaluate_actual_update(
            pre_state=admitted["pre_state"],
            reset_state=admitted["reset_state"],
            transplant_state=admitted["transplant_state"],
            gradients=admitted["gradients"],
            scope=verifier.TARGET_TENSOR_COUNTERFACTUAL,
            target_tensor=admitted["target"]["name"],
            requested_claim_scope=verifier.TARGET_TENSOR_COUNTERFACTUAL,
            identities=identities,
            loss_fn=replay.loss_from_state,
            threshold_artifact=threshold,
            event_captured_at=admitted["event_captured_at"],
        )
    except Exception:
        _refuse("ADJUDICATOR_VERIFIER_REFUSED")

    captured_losses = admitted["paired_losses"]
    if (
        receipt.get("losses", {}).get("reset") != captured_losses["reset"]
        or receipt.get("losses", {}).get("transplant")
        != captured_losses["transplant"]
    ):
        _refuse("CAPTURE_PAIRED_LOSS_REPLAY_MISMATCH")

    receipt = dict(receipt)
    receipt.pop("receipt_sha256", None)
    receipt["event_custody"] = {
        "authority": admitted["event_authority"],
        "capture_manifest_sha256": admitted["capture_manifest_sha256"],
        "dispatch_manifest_sha256": admitted["dispatch_manifest_sha256"],
        "preflight_receipt_sha256": admitted["preflight_receipt_sha256"],
        "terminal_receipt_sha256": admitted["terminal_receipt_sha256"],
        "ember_lab_identity": admitted["ember_lab_identity"],
    }
    receipt["receipt_sha256"] = verifier.artifact_sha256(receipt)
    return receipt
