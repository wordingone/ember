#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind the #757 Leg-B teacher-forced loglikelihood scorer to a live
ember-sparse-checkpoint-v5 candidate (issue #1433).

WHY THIS FILE EXISTS (executed evidence, not assumption):
scripts/legb_inprocess_scorer.py cannot be "re-pointed" at the live R1
candidate by swapping a path and four hashes. It is bound to a DIFFERENT
MODEL. Measured on the live candidate at
checkpoint-vertical-slice-seed-830001:

  * legb_inprocess_scorer.load_verified_checkpoint(<live dir>, ...)
    -> FileNotFoundError: ...\\model.pt
    It demands model.pt / optimizer.pt / rng.pt / manifest.json against four
    hard-pinned STEP50 sha256 values. The live candidate has shared-model.pt,
    four expert-*.pt shards, optimizer-state.pt, replay-state.pt and
    checkpoint-manifest.json. No file name overlaps.
  * The STEP50 artifact is a RealW1Model (LlamaModel backbone, hidden 1024,
    20 layers, keys backbone_model.embed_tokens.* / mlp.gate_proj.*). The
    live candidate is a UnifiedDecoder (ember-sparse-3b-v2, hidden 2048,
    14 layers, keys token_embedding.weight / layers.N.attention.qkv /
    layers.N.shared_ffn.up_gate / layers.N.experts.<name>.* / final_norm /
    lm_head). Zero state-dict key overlap.

What IS reusable, and is reused here VERBATIM rather than reimplemented:
legb_inprocess_scorer's exact-token-ID scoring core and its LegBLM
lm_eval.api.model.LM subclass. Neither takes a tokenizer inside the scoring
core and neither is specific to RealW1Model -- LegBLM calls `self.model(
input_ids)` and needs only an object whose forward returns logits.
UnifiedDecoder.forward(input_ids, ...) -> logits satisfies that exactly.
So this module supplies ONLY the missing half: a fail-closed v5 loader and
the model/route construction. The scoring mathematics are untouched, which
keeps the external-review-CLEAR status of that core intact.

ROUTE IS A REQUIRED ARGUMENT, DELIBERATELY WITH NO DEFAULT.
configs/ember-restart-3b.json declares default_active_expert = "reasoning".
The live candidate's own manifest declares active_expert_ids = ["tool"].
UnifiedDecoder.forward resolves the route as `active_expert or
self.active_expert`, so a load-and-score with no explicit route would
silently score every item through the REASONING expert on a checkpoint whose
declared active route is TOOL -- no error, no warning, just wrong numbers
that look plausible. This module refuses to guess: --route must be supplied,
it is validated, and both the chosen route and the manifest's declared
active_expert_ids are bound into the receipt so a reader can see whether they
agreed.

WARM-100 IDENTITY IS CONSUMED, NEVER INVENTED HERE. The scorer requires the
exact path and SHA-256 of the governed semantic runner's own JSON result. That
result carries `post_step_checkpoint`, minted by
checkpoint_artifacts.published_checkpoint_receipt(), plus its segment and
resume boundary. The scorer reopens those bytes, requires a fresh exact
100-step run, and cross-checks the published checkpoint receipt against the
actual manifest, shards, and cursor before any model load.

GPU: never initialized without EMBER_GATE_AUTHORIZED=1, and any cuda* run is
serialized through legb_inprocess_scorer.device_lease -> gpu_lock_guard
(reused verbatim). As committed, gpu_lock_guard.LOCK_PATH is the literal
placeholder "<local-path>", so an authorized cuda run currently REFUSES with
LEGB_SCORER_GPU_LOCK_GUARD_REFUSED (verified by execution, exit 1 via the
corrupt-lock fail-closed branch). That is a real prerequisite for any
full-suite run, not a defect introduced here.

Usage:
  python scripts/legb_live_candidate_v5_scorer.py --verify-only \\
      --checkpoint-dir <live v5 custody dir> \\
      --warm100-receipt <certified child result> \\
      --warm100-receipt-sha256 <sha256>
  python scripts/legb_live_candidate_v5_scorer.py --evaluator-run \\
      --checkpoint-dir <live v5 custody dir> --route tool --limit 2 \\
      --tasks arc_challenge,hellaswag --device cpu \\
      --warm100-receipt <certified child result> \\
      --warm100-receipt-sha256 <sha256> \\
      --predictions receipts/legb-live-candidate/<name>.jsonl \\
      --out receipts/legb-live-candidate/<name>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
_MODEL_PKG = os.path.join(REPO_ROOT, "tools", "ember-restart-3b")
if _MODEL_PKG not in sys.path:
    sys.path.insert(0, _MODEL_PKG)

import torch  # noqa: E402

from legb_inprocess_scorer import (  # noqa: E402 -- reused, never edited
    LegBLM, load_verified_tokenizer, device_lease,
    TOKENIZER_EXPECTED_SHA256, SHA_CONVENTION,
)
from receipt_write import checked_write  # noqa: E402
from receipt_check import INVARIANT_SHA256  # noqa: E402

ISSUE_REF = "#1433"
RELATED_REF = "#757"
RECEIPT_SCHEMA = "legb-live-candidate-v5/v1"

SUPPORTED_CHECKPOINT_SCHEMA = "ember-sparse-checkpoint-v5"
MODEL_CONFIG_REL = "configs/ember-restart-3b.json"
TOKENIZER_REL = "tokenizer/tokenizer.json"

EXPERTS = ("vision", "audio", "reasoning", "tool")
# "shared" scores through the always-active shared SwiGLU FFN with no expert
# bank contribution; the four named routes additionally activate that bank.
VALID_ROUTES = ("shared",) + EXPERTS

# Model shards only. optimizer-state.pt and replay-state.pt are lineage pins:
# hash-verified below, never loaded into a live optimizer by this scorer.
MODEL_SHARDS = ("shared-model.pt",) + tuple(f"expert-{name}.pt" for name in EXPERTS)

FROZEN_SUITE_SPEC = (
    "docs/spec/eval-suite-freeze-v1.md (freeze v1) + "
    "docs/spec/c8-f3-instrument-list-v1.md (full test_split_sha256 values)")

# Per-task binding between the FROZEN suite pin and the split the INSTALLED
# harness actually scores. These are not always the same split, and pretending
# they are would put a hash in the receipt over bytes that were never scored.
#
# arc_challenge: arc_easy.yaml (included by arc_challenge.yaml) sets
#   test_split: test -- the harness scores the same 1172-row test split the
#   freeze pins. Genuinely bindable.
# hellaswag: hellaswag.yaml sets test_split: null, validation_split: validation
#   -- upstream HellaSwag's test split is UNLABELED, so the harness scores
#   validation (10042 rows). The freeze pins the 10003-row TEST split. The pin
#   therefore cannot be bound to these predictions; it names bytes the harness
#   cannot score. Recorded as a disclosed non-alignment, never silently
#   asserted as a match.
FROZEN_SPLIT_BINDING = {
    "arc_challenge": {
        "dataset": "allenai/ai2_arc",
        "subset": "ARC-Challenge",
        "frozen_pinned_split": "test",
        "frozen_pinned_rows": 1172,
        "frozen_test_split_sha256":
            "c0e7635ee91b9ca47bf388f1f6cd5140fda083a71dccda44de72c364645df3f3",
        "harness_scored_split": "test",
        "frozen_pin_matches_scored_split": True,
    },
    "hellaswag": {
        "dataset": "Rowan/hellaswag",
        "subset": None,
        "frozen_pinned_split": "test",
        "frozen_pinned_rows": 10003,
        "frozen_test_split_sha256":
            "6a78734fc71263f4257d9b52dbfd697830622b2eedb6473094120eed2d142a9f",
        "harness_scored_split": "validation",
        "frozen_pin_matches_scored_split": False,
        "non_alignment_reason": (
            "installed hellaswag.yaml sets test_split: null (upstream test split "
            "is unlabeled) and scores validation; the freeze pins the test split, "
            "so the pinned sha256 is NOT a hash of the scored bytes"),
    },
}

WARM100_GLOBAL_STEP = 100
SEMANTIC_CURSOR_KEYS = {
    "shard", "record_index", "receipt_sha256", "tokenizer_sha256",
    "shard_index", "token_offset", "global_step", "tokens_seen",
}
PUBLISHED_CURSOR_EXTRA_KEYS = {"governor", "resume_authority"}


class LiveCandidateRefusal(Exception):
    """Fail-closed refusal (schema mismatch, hash drift, unknown route) --
    never a silent skip, never a default value, never a trivial pass."""


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def claim_boundary(checkpoint: dict) -> str:
    """Derive the claim boundary from the accepted checkpoint, never literals."""
    return (
        "WARM100_IDENTITY_AND_MEASUREMENT_ONLY; the governed run receipt and "
        f"subject checkpoint agree at data_cursor.tokens_seen={checkpoint['tokens_seen']} "
        f"and global_step={checkpoint['global_step']} -- no capability, parity, "
        "acceleration, HellaSwag split-alignment, modality-marker, or "
        "issue-closure credit"
    )


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _redact_external_path(path: str) -> str:
    """The live candidate lives in external custody; its absolute path is not
    the identity evidence (the shard hashes are) and committing this machine's
    directory layout into a receipt is a real local-path leak. Same convention
    as legb_inprocess_scorer._redact_external_path."""
    return f"<external custody, path redacted -- basename={os.path.basename(path)!r}>"


def _repo_relative(path: str) -> str:
    """Repo-relative path when the target lives under the repo, else the
    redacted basename. os.path.relpath raises across Windows drive letters, and
    an absolute off-repo path in a committed receipt is a local-path leak."""
    absolute = os.path.abspath(path)
    try:
        relative = os.path.relpath(absolute, REPO_ROOT)
    except ValueError:
        return _redact_external_path(absolute)
    if relative.startswith(os.pardir):
        return _redact_external_path(absolute)
    return relative.replace(os.sep, "/")


def load_verified_v5_checkpoint(checkpoint_dir: str) -> dict:
    """Re-hash every shard against the manifest's OWN recorded digests, and
    cross-check those against the manifest's independent top-level digest
    fields. Refuses on any drift. Nothing is loaded before every byte is
    verified."""
    manifest_path = os.path.join(checkpoint_dir, "checkpoint-manifest.json")
    if not os.path.isfile(manifest_path):
        raise LiveCandidateRefusal(
            f"CHECKPOINT_MANIFEST_MISSING: {_redact_external_path(manifest_path)}")
    try:
        with open(manifest_path, "rb") as handle:
            manifest_bytes = handle.read()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LiveCandidateRefusal(f"CHECKPOINT_MANIFEST_UNREADABLE: {exc}") from exc
    if not isinstance(manifest, dict):
        raise LiveCandidateRefusal("CHECKPOINT_MANIFEST_NOT_OBJECT")

    schema = manifest.get("schema_version")
    if schema != SUPPORTED_CHECKPOINT_SCHEMA:
        raise LiveCandidateRefusal(
            f"CHECKPOINT_SCHEMA_UNSUPPORTED: expected "
            f"{SUPPORTED_CHECKPOINT_SCHEMA!r} got {schema!r}")

    shards = manifest.get("shards")
    if not isinstance(shards, list) or not shards:
        raise LiveCandidateRefusal("CHECKPOINT_SHARD_LIST_INVALID")

    measured: dict[str, str] = {}
    for record in shards:
        if not isinstance(record, dict):
            raise LiveCandidateRefusal("CHECKPOINT_SHARD_RECORD_INVALID")
        name, expected, size = record.get("path"), record.get("sha256"), record.get("bytes")
        if not isinstance(name, str) or os.path.basename(name) != name:
            raise LiveCandidateRefusal(f"CHECKPOINT_SHARD_PATH_INVALID: {name!r}")
        shard_path = os.path.join(checkpoint_dir, name)
        if not os.path.isfile(shard_path):
            raise LiveCandidateRefusal(f"CHECKPOINT_SHARD_MISSING: {name}")
        actual_size = os.path.getsize(shard_path)
        if actual_size != size:
            raise LiveCandidateRefusal(
                f"CHECKPOINT_SHARD_SIZE_MISMATCH: {name} expected={size} actual={actual_size}")
        actual = _sha256_file(shard_path)
        if actual != expected:
            raise LiveCandidateRefusal(
                f"CHECKPOINT_SHARD_SHA_MISMATCH: {name} expected={expected} actual={actual}")
        measured[name] = actual

    missing = [name for name in MODEL_SHARDS if name not in measured]
    if missing:
        raise LiveCandidateRefusal(f"CHECKPOINT_MODEL_SHARDS_MISSING: {missing}")

    # Independent cross-check: the manifest states the same digests a second
    # time in dedicated top-level fields. Agreeing with itself in only one
    # place is weaker evidence than agreeing in both.
    cross = {
        "shared-model.pt": manifest.get("shared_model_shard_sha256"),
        "optimizer-state.pt": manifest.get("optimizer_state_shard_sha256"),
    }
    expert_map = manifest.get("expert_checkpoint_sha256")
    if not isinstance(expert_map, dict):
        raise LiveCandidateRefusal("CHECKPOINT_EXPERT_DIGEST_MAP_INVALID")
    for name in EXPERTS:
        cross[f"expert-{name}.pt"] = expert_map.get(name)
    for name, declared in cross.items():
        if name in measured and declared != measured[name]:
            raise LiveCandidateRefusal(
                f"CHECKPOINT_TOP_LEVEL_DIGEST_DISAGREES: {name} "
                f"top_level={declared} shard_list={measured[name]}")

    config_path = os.path.join(REPO_ROOT, MODEL_CONFIG_REL)
    if not os.path.isfile(config_path):
        raise LiveCandidateRefusal(f"MODEL_CONFIG_MISSING: {MODEL_CONFIG_REL}")
    config_sha = _sha256_file(config_path)
    declared_config_sha = manifest.get("model_config_sha256")
    if config_sha != declared_config_sha:
        raise LiveCandidateRefusal(
            f"MODEL_CONFIG_SHA_MISMATCH: {MODEL_CONFIG_REL} actual={config_sha} "
            f"manifest_declared={declared_config_sha} -- the committed architecture "
            "is not the one this checkpoint was written with")

    cursor = manifest.get("data_cursor") or {}
    return {
        "manifest": manifest,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "measured_shard_sha256": measured,
        "model_config_path": MODEL_CONFIG_REL,
        "model_config_sha256": config_sha,
        "declared_active_expert_ids": manifest.get("active_expert_ids"),
        "architecture_revision": manifest.get("architecture_revision"),
        "contract_version": manifest.get("contract_version"),
        "global_step": cursor.get("global_step"),
        "tokens_seen": cursor.get("tokens_seen"),
        "launch_seed": manifest.get("launch_seed"),
    }


def load_verified_warm100_checkpoint(
        checkpoint_dir: str, run_receipt_path: str,
        expected_run_receipt_sha256: str) -> dict:
    """Reopen the governed run result and bind it to the actual WARM-100 bytes.

    This consumes `run_vertical_slice.py`'s existing result shape. It does not
    mint or reinterpret a second run-receipt schema.
    """
    if not _is_sha256(expected_run_receipt_sha256):
        raise LiveCandidateRefusal("RUN_RECEIPT_SHA256_INVALID")
    if not os.path.isfile(run_receipt_path):
        raise LiveCandidateRefusal("RUN_RECEIPT_MISSING")
    actual_receipt_sha256 = _sha256_file(run_receipt_path)
    if actual_receipt_sha256 != expected_run_receipt_sha256:
        raise LiveCandidateRefusal(
            "RUN_RECEIPT_SHA_MISMATCH: "
            f"expected={expected_run_receipt_sha256} actual={actual_receipt_sha256}")
    try:
        with open(run_receipt_path, "r", encoding="utf-8", errors="strict") as handle:
            run_receipt = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LiveCandidateRefusal(f"RUN_RECEIPT_UNREADABLE: {exc}") from exc
    if not isinstance(run_receipt, dict):
        raise LiveCandidateRefusal("RUN_RECEIPT_NOT_OBJECT")

    verified = load_verified_v5_checkpoint(checkpoint_dir)
    published = run_receipt.get("post_step_checkpoint")
    if not isinstance(published, dict):
        raise LiveCandidateRefusal("RUN_RECEIPT_CHECKPOINT_MISSING")
    manifest = verified["manifest"]
    expected_published_keys = set(manifest) | {
        "checkpoint_manifest_sha256", "checkpoint"}
    checkpoint_identity = published.get("checkpoint")
    if (
        set(published) != expected_published_keys
        or {key: published.get(key) for key in manifest} != manifest
        or published.get("checkpoint_manifest_sha256") != verified["manifest_sha256"]
        or not isinstance(checkpoint_identity, dict)
        or checkpoint_identity != {"byte_sha256": verified["manifest_sha256"]}
    ):
        raise LiveCandidateRefusal("RUN_RECEIPT_CHECKPOINT_MISMATCH")

    cursor = manifest.get("data_cursor")
    segment = run_receipt.get("segment")
    if not isinstance(cursor, dict) or not isinstance(segment, dict):
        raise LiveCandidateRefusal("RUN_RECEIPT_CURSOR_MISSING")
    segment_cursor = segment.get("data_cursor")
    cursor_projection_matches = (
        isinstance(segment_cursor, dict)
        and set(segment_cursor) == SEMANTIC_CURSOR_KEYS
        and set(segment_cursor).issubset(cursor)
        and set(cursor) - set(segment_cursor) <= PUBLISHED_CURSOR_EXTRA_KEYS
        and {key: cursor[key] for key in segment_cursor} == segment_cursor
    )
    global_step = cursor.get("global_step")
    tokens_seen = cursor.get("tokens_seen")
    if (
        type(global_step) is not int
        or type(tokens_seen) is not int
        or global_step != WARM100_GLOBAL_STEP
        or tokens_seen < 1
        or run_receipt.get("resume_authority", object()) is not None
        or segment.get("steps") != WARM100_GLOBAL_STEP
        or segment.get("global_step") != global_step
        or segment.get("tokens_seen") != tokens_seen
        or not cursor_projection_matches
        or not isinstance(segment.get("losses"), list)
        or len(segment["losses"]) != WARM100_GLOBAL_STEP
    ):
        raise LiveCandidateRefusal("WARM100_BOUNDARY_REQUIRED")

    return {
        **verified,
        "run_receipt_path": _redact_external_path(run_receipt_path),
        "run_receipt_sha256": actual_receipt_sha256,
    }


def build_live_candidate_scorer(*, checkpoint_dir: str, route: str,
                                 tokenizer_path: str | None = None,
                                 device: str = "cpu",
                                 max_position_embeddings: int) -> tuple:
    """Construct a LegBLM over the verified live v5 candidate.

    Built on the meta device first so the 3.84B-parameter random genesis init
    is never materialized only to be immediately overwritten; real tensors
    arrive via load_state_dict(assign=True) straight from the verified shards.
    """
    if route not in VALID_ROUTES:
        raise LiveCandidateRefusal(
            f"ROUTE_UNKNOWN: {route!r} not in {VALID_ROUTES!r}")

    verified = load_verified_v5_checkpoint(checkpoint_dir)

    from model import RestartDecoderConfig, UnifiedDecoder  # noqa: E402

    config_path = os.path.join(REPO_ROOT, MODEL_CONFIG_REL)
    config = RestartDecoderConfig.from_contract(config_path)
    model = UnifiedDecoder(config, device="meta")

    state: dict[str, torch.Tensor] = {}
    for name in MODEL_SHARDS:
        payload = torch.load(os.path.join(checkpoint_dir, name),
                             map_location="cpu", mmap=True, weights_only=False)
        shard_state = payload.get("model")
        if not isinstance(shard_state, dict):
            raise LiveCandidateRefusal(f"CHECKPOINT_SHARD_PAYLOAD_INVALID: {name}")
        overlap = set(shard_state) & set(state)
        if overlap:
            raise LiveCandidateRefusal(
                f"CHECKPOINT_SHARD_KEY_COLLISION: {name} redefines {sorted(overlap)[:5]}")
        state.update(shard_state)

    expected_keys = set(model.state_dict().keys())
    if set(state) != expected_keys:
        raise LiveCandidateRefusal(
            f"CHECKPOINT_KEY_SET_MISMATCH: missing={sorted(expected_keys - set(state))[:5]} "
            f"unexpected={sorted(set(state) - expected_keys)[:5]}")

    model.load_state_dict(state, strict=True, assign=True)

    # assign=True installs two distinct tensors for the tied pair. The
    # checkpoint stores them sharing one storage (verified: equal values, same
    # data_ptr), and the architecture contract requires tied_embeddings. Re-tie
    # explicitly and prove the values agreed before doing so, rather than
    # letting an untied duplicate ride along silently.
    tied_equal = bool(torch.equal(model.token_embedding.weight, model.lm_head.weight))
    if not tied_equal:
        raise LiveCandidateRefusal(
            "CHECKPOINT_TIED_EMBEDDING_DISAGREEMENT: token_embedding.weight and "
            "lm_head.weight differ, but the architecture contract declares "
            "tied_embeddings=True")
    model.lm_head.weight = model.token_embedding.weight

    model.eval()
    if device != "meta":
        model.to(device)
    model.active_expert = route
    realized_device = str(next(model.parameters()).device)
    realized_dtype = str(next(model.parameters()).dtype)

    tokenizer_path = tokenizer_path or os.path.join(REPO_ROOT, TOKENIZER_REL)
    tokenizer, tokenizer_info = load_verified_tokenizer(
        tokenizer_path, TOKENIZER_EXPECTED_SHA256)

    scorer = LegBLM(model, tokenizer,
                    max_position_embeddings=max_position_embeddings, device=device)

    declared = verified["declared_active_expert_ids"]
    binding = {
        "checkpoint": {
            "dir": _redact_external_path(checkpoint_dir),
            "schema_version": SUPPORTED_CHECKPOINT_SCHEMA,
            "manifest_sha256": verified["manifest_sha256"],
            "measured_shard_sha256": verified["measured_shard_sha256"],
            "architecture_revision": verified["architecture_revision"],
            "contract_version": verified["contract_version"],
            "launch_seed": verified["launch_seed"],
            "global_step": verified["global_step"],
            "tokens_seen": verified["tokens_seen"],
        },
        "model_config": {
            "path": verified["model_config_path"],
            "sha256": verified["model_config_sha256"],
            "hidden_size": config.hidden_size,
            "layers": config.layers,
            "attention_heads": config.attention_heads,
            "vocab_size": config.vocab_size,
        },
        "route": {
            "selected": route,
            "selection_policy": "explicit_required_argument_no_default",
            "config_default_active_expert": config.default_active_expert,
            "manifest_declared_active_expert_ids": declared,
            "selected_matches_manifest_declared": (
                isinstance(declared, list) and declared == [route]),
        },
        "tied_embeddings_reasserted": tied_equal,
        "tokenizer": {**tokenizer_info,
                      "path": _redact_external_path(tokenizer_info["path"])},
        "sha_convention": SHA_CONVENTION,
        "requested_device": device,
        "realized_device": realized_device,
        "realized_dtype": realized_dtype,
        "max_position_embeddings": max_position_embeddings,
        "scoring_core_source": (
            "legb_inprocess_scorer.LegBLM + score_ids_single/score_ids_batch, "
            "imported verbatim (#757 external-review-CLEAR core, unmodified)"),
    }
    return scorer, binding


def run_evaluator(*, checkpoint_dir: str, warm100_receipt_path: str,
                   warm100_receipt_sha256: str, route: str, tasks: list,
                   limit, device: str, max_position_embeddings: int,
                   tokenizer_path: str | None = None,
                   predictions_path: str | None = None) -> dict:
    """Dispatch the verified live-candidate LegBLM through the INSTALLED
    lm_eval.evaluator.simple_evaluate -- the harness is never reimplemented.

    Raw per-sample predictions are requested from the harness (log_samples) and
    written to `predictions_path` as JSONL, whose sha256 is bound into the
    returned payload. #1433 acceptance requires the chain checkpoint sha ->
    suite split sha -> RAW PREDICTIONS -> scores; a metrics-only receipt does
    not satisfy it."""
    if predictions_path is None:
        raise LiveCandidateRefusal("RAW_PREDICTIONS_REQUIRED")
    warm100 = load_verified_warm100_checkpoint(
        checkpoint_dir, warm100_receipt_path, warm100_receipt_sha256)

    from lm_eval.evaluator import simple_evaluate

    with device_lease(device):
        scorer, binding = build_live_candidate_scorer(
            checkpoint_dir=checkpoint_dir, route=route,
            tokenizer_path=tokenizer_path, device=device,
            max_position_embeddings=max_position_embeddings)
        if binding["checkpoint"]["manifest_sha256"] != warm100["manifest_sha256"]:
            raise LiveCandidateRefusal("CHECKPOINT_CHANGED_DURING_MODEL_LOAD")
        binding["checkpoint"]["run_receipt"] = {
            "path": warm100["run_receipt_path"],
            "sha256": warm100["run_receipt_sha256"],
        }
        results = simple_evaluate(
            model=scorer, tasks=tasks, limit=limit, bootstrap_iters=0,
            log_samples=True, verbosity="ERROR")

    per_task = {}
    for task_name, metrics in (results.get("results") or {}).items():
        per_task[task_name] = {
            key: value for key, value in metrics.items()
            if isinstance(value, (int, float, str, bool)) or value is None
        }

    os.makedirs(os.path.dirname(os.path.abspath(predictions_path)) or ".",
                exist_ok=True)
    row_count = 0
    with open(predictions_path, "w", encoding="utf-8", newline="\n") as handle:
        for task_name, samples in sorted((results.get("samples") or {}).items()):
            for sample in samples:
                handle.write(json.dumps(
                    {"task": task_name, **_prediction_row(sample)},
                    sort_keys=True, ensure_ascii=False) + "\n")
                row_count += 1
    if row_count < 1:
        raise LiveCandidateRefusal("RAW_PREDICTIONS_EMPTY")
    _write_authority_sidecar(predictions_path)
    predictions = {
        "path": _repo_relative(predictions_path),
        "rows": row_count,
        "sha256": _sha256_file(predictions_path),
        "format": "jsonl; one row per scored eval item",
    }

    evaluation = {
        "binding": binding,
        "tasks": tasks,
        "limit": limit,
        "bounded": limit is not None,
        "task_versions": results.get("versions"),
        "frozen_suite": {
            "spec": FROZEN_SUITE_SPEC,
            "split_binding": {
                name: FROZEN_SPLIT_BINDING[name]
                for name in tasks if name in FROZEN_SPLIT_BINDING
            },
            "unbound_tasks": [
                name for name in tasks if name not in FROZEN_SPLIT_BINDING
            ],
        },
        "n_samples": {
            name: counts for name, counts in (results.get("n-samples") or {}).items()
        },
        "raw_predictions": predictions,
        "results": per_task,
    }
    evaluation["artifact_binding"] = bind_evaluation_artifacts(evaluation)
    return evaluation


def bind_evaluation_artifacts(evaluation: dict) -> dict:
    """Bind the required raw predictions and canonical score object."""
    predictions = evaluation.get("raw_predictions")
    if (
        not isinstance(predictions, dict)
        or type(predictions.get("rows")) is not int
        or predictions["rows"] < 1
        or not _is_sha256(predictions.get("sha256"))
    ):
        raise LiveCandidateRefusal("RAW_PREDICTIONS_REQUIRED")
    scores = evaluation.get("results")
    if not isinstance(scores, dict) or not scores:
        raise LiveCandidateRefusal("SCORES_REQUIRED")
    scores_sha256 = _canonical_sha256(scores)
    return {
        "raw_predictions_sha256": predictions["sha256"],
        "scores_sha256": scores_sha256,
        "prediction_score_binding_sha256": _canonical_sha256({
            "raw_predictions_sha256": predictions["sha256"],
            "scores_sha256": scores_sha256,
        }),
        "scores_sha256_convention": (
            "sha256 over UTF-8 JSON with sort_keys=True and separators=(',', ':')"),
    }


def _sidecar_name(artifact_path: str) -> str:
    """repo-guard's sidecar resolution: replace the artifact's suffix with
    '.authority.json'. Reproduced here so the collision guard uses the same
    rule the guard itself applies."""
    return os.path.splitext(os.path.abspath(artifact_path))[0] + ".authority.json"


def _write_authority_sidecar(artifact_path: str) -> str | None:
    """Emit the content-addressed authority binding beside a generated artifact.

    repo-guard's authority-conservation leg requires every committed artifact to
    carry a goal binding. A predictions JSONL cannot carry it inline without
    stamping goal_id/workstream_id/next_executed_outcome onto every one of its
    thousands of rows, which is exactly the case the sidecar mechanism exists
    for: `<artifact>.authority.json`, believed only when it names this exact
    path AND records the artifact's current digest, so it cannot outlive an
    edit to the artifact. Emitted by the producer so the artifact is compliant
    by construction rather than patched by hand afterwards."""
    relative = _repo_relative(artifact_path)
    if relative.startswith("<external custody"):
        return None  # off-repo output is never committed; nothing to bind
    with open(artifact_path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    sidecar_path = os.path.splitext(os.path.abspath(artifact_path))[0] + ".authority.json"
    payload = {
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": (
                "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"),
        },
        "schema_version": "ember-content-addressed-authority-binding/v1",
        "artifact_path": relative,
        "artifact_sha256": digest,
        "ticket": "1433",
        "ts": _utc_stamp(),
        "sha_convention": SHA_CONVENTION,
        "invariant_sha256": INVARIANT_SHA256,
        "reason": (
            "generated raw-prediction JSONL with a fixed per-row schema; the "
            "inline .jsonl binding rule would require stamping the authority "
            "triple onto every scored row"),
    }
    with open(sidecar_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return sidecar_path


def _prediction_row(sample: dict) -> dict:
    """Project one lm_eval log_samples entry down to the identity-bearing
    fields: which item, what the model scored, and what it got. Kept explicit
    rather than dumping the whole sample so the JSONL stays reviewable and
    carries no incidental local paths."""
    return {
        "doc_id": sample.get("doc_id"),
        "target": sample.get("target"),
        "arguments_count": len(sample.get("arguments") or ()),
        "resps": sample.get("resps"),
        "filtered_resps": sample.get("filtered_resps"),
        "acc": sample.get("acc"),
        "acc_norm": sample.get("acc_norm"),
    }


def _receipt(ticket: str, payload: dict) -> dict:
    checkpoint = (
        payload.get("checkpoint")
        if payload.get("mode") == "verify-only"
        else (payload.get("binding") or {}).get("checkpoint")
    )
    if not isinstance(checkpoint, dict):
        raise LiveCandidateRefusal("RECEIPT_CHECKPOINT_BINDING_MISSING")
    return {
        "ticket": ticket,
        "ts": _utc_stamp(),
        "schema": RECEIPT_SCHEMA,
        "issue_refs": [ISSUE_REF, RELATED_REF],
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": (
                "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"),
        },
        "claim_boundary": claim_boundary(checkpoint),
        "result_credit": False,
        "capability_credit": False,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
        **payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true",
                        help="Hash-verify the v5 candidate and exit; loads no model.")
    parser.add_argument("--evaluator-run", action="store_true",
                        help="Score the named tasks through the installed lm_eval.")
    parser.add_argument("--checkpoint-dir", required=True,
                        help="Live v5 custody checkpoint dir (external, never committed).")
    parser.add_argument("--warm100-receipt", required=True,
                        help="Governed semantic runner result containing "
                             "post_step_checkpoint (exact custody path).")
    parser.add_argument("--warm100-receipt-sha256", required=True,
                        help="SHA-256 over the exact --warm100-receipt bytes.")
    parser.add_argument("--route", default=None, choices=VALID_ROUTES,
                        help="REQUIRED for --evaluator-run. Expert route to score "
                             "through. Deliberately has no default: the config default "
                             "and the checkpoint's declared active expert disagree.")
    parser.add_argument("--tokenizer-path", default=None,
                        help=f"Defaults to the committed {TOKENIZER_REL}.")
    parser.add_argument("--tasks", default="arc_challenge,hellaswag")
    parser.add_argument("--limit", type=int, default=None,
                        help="Bound samples per task (proof-of-wiring runs).")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-position-embeddings", type=int, default=1024)
    parser.add_argument("--predictions", default=None,
                        help="JSONL path for raw per-item predictions; its sha256 "
                             "is bound into the receipt (#1433 acceptance).")
    parser.add_argument("--out", default=None, help="Receipt path.")
    args = parser.parse_args()

    if args.verify_only == args.evaluator_run:
        print("ERROR: pass exactly one of --verify-only / --evaluator-run",
              file=sys.stderr)
        return 2

    # repo-guard resolves an artifact's authority sidecar by replacing its
    # suffix with ".authority.json". `<name>.json` and `<name>.jsonl` therefore
    # resolve to the SAME sidecar, and the receipt then gets validated against
    # a sidecar describing the predictions file -- a real pre-commit failure,
    # observed, not theorized. Refuse the colliding pair up front instead of
    # producing artifacts that cannot be committed.
    if args.out and args.predictions:
        if _sidecar_name(args.out) == _sidecar_name(args.predictions):
            print(f"ERROR: --out and --predictions resolve to the same authority "
                  f"sidecar ({os.path.basename(_sidecar_name(args.out))}). Give one "
                  f"of them a distinct stem -- naming the receipt "
                  f"'<name>-receipt.json' is preferred, since the receipt records "
                  f"the predictions path and renaming the predictions file after "
                  f"the fact would strand that reference.",
                  file=sys.stderr)
            return 2

    try:
        if args.verify_only:
            verified = load_verified_warm100_checkpoint(
                args.checkpoint_dir, args.warm100_receipt,
                args.warm100_receipt_sha256)
            payload = {
                "mode": "verify-only",
                "checkpoint": {
                    "dir": _redact_external_path(args.checkpoint_dir),
                    "schema_version": SUPPORTED_CHECKPOINT_SCHEMA,
                    "manifest_sha256": verified["manifest_sha256"],
                    "measured_shard_sha256": verified["measured_shard_sha256"],
                    "architecture_revision": verified["architecture_revision"],
                    "contract_version": verified["contract_version"],
                    "launch_seed": verified["launch_seed"],
                    "global_step": verified["global_step"],
                    "tokens_seen": verified["tokens_seen"],
                    "declared_active_expert_ids": verified["declared_active_expert_ids"],
                    "run_receipt": {
                        "path": verified["run_receipt_path"],
                        "sha256": verified["run_receipt_sha256"],
                    },
                },
                "model_config": {
                    "path": verified["model_config_path"],
                    "sha256": verified["model_config_sha256"],
                },
            }
            ticket = "legb-live-candidate-v5-verify"
            print("LEGB_LIVE_CANDIDATE_V5_VERIFY_PASS")
            print(f"  schema={SUPPORTED_CHECKPOINT_SCHEMA} "
                  f"global_step={verified['global_step']} "
                  f"tokens_seen={verified['tokens_seen']}")
            print(f"  declared_active_expert_ids={verified['declared_active_expert_ids']}")
            for name, digest in sorted(verified["measured_shard_sha256"].items()):
                print(f"  {name}: {digest}")
        else:
            if args.route is None:
                print("ERROR: --route is REQUIRED for --evaluator-run. The committed "
                      "config default_active_expert and the checkpoint's declared "
                      "active_expert_ids disagree; this scorer will not guess.",
                      file=sys.stderr)
                return 2
            if args.predictions is None:
                print("ERROR: --predictions is REQUIRED for --evaluator-run; "
                      "a metrics-only receipt cannot bind the scored items.",
                      file=sys.stderr)
                return 2
            tasks = [name.strip() for name in args.tasks.split(",") if name.strip()]
            payload = {"mode": "evaluator-run",
                       **run_evaluator(
                           checkpoint_dir=args.checkpoint_dir,
                           warm100_receipt_path=args.warm100_receipt,
                           warm100_receipt_sha256=args.warm100_receipt_sha256,
                           route=args.route,
                           tasks=tasks, limit=args.limit, device=args.device,
                           max_position_embeddings=args.max_position_embeddings,
                           tokenizer_path=args.tokenizer_path,
                           predictions_path=args.predictions)}
            ticket = "legb-live-candidate-v5-evaluator-run"
            print("LEGB_LIVE_CANDIDATE_V5_EVALUATOR_RUN_COMPLETE")
            print(json.dumps(payload["results"], indent=2, sort_keys=True))
    except LiveCandidateRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    if args.out:
        checked_write(args.out, _receipt(ticket, payload))
        print(f"receipt: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
