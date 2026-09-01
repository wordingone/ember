#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_e2b_surpass_run.py — C-E2B surpass harness, PRE-BUILT to fire the
moment C14 clears (issue #23 follow-on build).

RELATIONSHIP TO THE EXISTING RUNNER: src/ember/governance/scripts/ember_c_e2b_paired_run.py already
ran --live against the PRE-TRAINING cbase-v0 seed checkpoint (models/cbase-
smoke-run/checkpoints/step-00000610) and produced the honest measured_distance
receipt receipts/ember-c-e2b-paired-20260703T081621Z.json. That receipt's own
commit message says it plainly: "the surpass re-run is banked for after a
genuine C14 resident-training clearing". THIS file is that banked re-run. It
adds exactly ONE thing the prior runner does not have: a hard gate on a
VETTED C14 RESIDENT_TRAINING_GATE_PASS receipt, and it loads the OWNED-CORE
CHECKPOINT THAT RECEIPT NAMES (never the frozen pretrain seed) before running
the SAME paired two-leg battery test_c_e2b.py judges.

Reused VERBATIM from src/ember/governance/scripts/ember_c_e2b_paired_run.py (never duplicated —
this codebase's convention is to reuse a predicate/battery function, not
re-implement and drift; see _lane14_common.resolve_in_tree for the
precedent this follows): find_local_e2b_model, load_e2b_model,
make_e2b_generate_fn, make_owned_core_generate_fn, score_founder_likeness_
leg_v1, compute_verdict, freeze_protocol_if_needed (the SAME frozen protocol
doc — issue #23 is one paired-legs protocol, not two; calling this again
after that runner just returns the existing freeze file unchanged, per its
own idempotent-first-writer design).

UPDATED (issue #48 supersession, 2026-07-04): paired.py's ember_work leg
scorer moved to citation-only (owned arm is CITED from fire-4's receipt,
never re-run) -- incompatible with THIS file's purpose (re-running the
owned arm live against whatever --c14-receipt resolves, not necessarily
fire-4). This file keeps its own local _score_owned_arm_live_leg1 (the old
score_ember_work_leg body) instead of importing the now citation-only
replacement. score_founder_likeness_leg_v1 (both arms always run live, no
citation shortcut in either version) is unaffected and still reused as-is.

NEW in this file:

  1. --c14-receipt PATH gate. Vetted with ember-goalforge's OWN test_c0.py
     ::_vet_gate_receipts predicate (imported read-only from the contract
     tree — never reimplemented; see vet_c14_receipt() below). A receipt
     that is not a real, undisqualified, unrevoked, unsuperseded
     RESIDENT_TRAINING_GATE_PASS is refused before ANY model load, for
     --live or the refusal-path parts of --selftest.

  2. Checkpoint-lineage resolution FROM the vetted receipt's own
     resident_training_candidate block (see resolve_c14_checkpoint()'s
     docstring for the exact contract: resident_checkpoint_path +
     resident_checkpoint_sha256, on the candidate directly or on the
     candidate's policy_update_trace). NEVER falls back to the frozen
     pretrain seed for a --live invocation — an unresolvable lineage is a
     loud refusal, not a silent re-run of the already-answered pretrain-seed
     comparison ember_c_e2b_paired_run.py already recorded.

  3. ember_c14_owned_core.make_owned_core_factory() is reused completely
     UNCHANGED, TWO ways depending on the resolved checkpoint's shape (see
     resolve_c14_checkpoint()'s docstring): for a DIRECTORY (a future merged
     checkpoint — base + trained delta baked in; no producer exists yet),
     this file temporarily repoints its module-level SEED_CKPT_DEFAULT /
     EXPECTED_MODEL_PT_SHA256 globals at the C14-cleared checkpoint for the
     duration of exactly one factory() call, then restores them in a
     finally block — the same swap-in-finally pattern ember_ceff_closure_
     confirmation.py's run_shatter_compute_fit_selfcheck uses for
     gate_mod.NC. verify_seed_checkpoint()'s hash-verification then runs
     against the RIGHT expected hash for THIS checkpoint, never the
     pretrain one — no drift, no silent weakening of the hash-verify floor.
     For a FILE ending .pt (a bare LoRA adapter_state_dict — only
     "lora.lora_A"/"lora.lora_B" keys, no base weights — the shape
     ember_c14_owned_run.py::_persist_resident_adapter actually writes
     today), the globals are NEVER repointed: the factory loads its normal
     FROZEN pretrain seed (hash-verified as always, unmoved) and attaches a
     fresh zero-effect LoRA; the persisted adapter file is hash-verified
     separately and loaded into that fresh LoRA by
     _load_and_verify_adapter_file() (see load_owned_core_from_c14_
     checkpoint()'s docstring).

  4. api_spend_usd=0 / paid_api_surface_used=False on every receipt this
     file writes (both legs are local-weights CPU inference only; explicit
     on the receipt, never merely implied).

  5. Self-check-before-write, mirroring ember_ceff_closure_confirmation.py's
     write_or_diagnose (assemble -> self-check -> write, never write ->
     hope): the candidate is written to a SCRATCH-isolated receipts dir
     first; the REAL ember-goalforge test_c_e2b.py is run as a subprocess
     against that scratch dir; only a probe outcome the CHK itself
     recognizes as protocol-compliant (a real surpass GREEN, or the
     explicitly-accepted "measured-distance ... protocol-compliant" RED) is
     copied into the live receipts/. Any other outcome (format-invalid RED,
     UNEVALUABLE) is DELETED, never landed — a e2b-surpass-attempt-<ts>.json
     diagnostic is written instead. This is the mechanism that makes the
     harness mechanically incapable of fabricating a surpass verdict: the
     surpass/measured_distance selection is compute_verdict()'s own strict
     numeric comparison, and even THAT receipt only survives if the real,
     unedited probe agrees it is admissible evidence.

THREE MODES (mirrors ember_c_e2b_paired_run.py's three-mode convention):

  --selftest   Pure CPU. NO model load. NO --c14-receipt required.
               (a) THREE synthetic-fixture round trips through the REAL
                   test_c_e2b.py in a sandbox: a surpass-shaped fixture
                   (expect GREEN), an honest-shortfall fixture (expect the
                   named measured-distance RED, and _probe_outcome_
                   acceptable() must accept it), and a deliberately
                   invalid one-leg fixture (expect the format-invalid RED,
                   and _probe_outcome_acceptable() must REJECT it — proving
                   the acceptance filter is not merely "any RED passes").
               (b) vet_c14_receipt() unit tests: a synthetic BLOCKED C14
                   gate-receipt fixture must NOT vet (negative control); a
                   synthetic well-formed PASS fixture must vet (positive
                   control — proves the predicate isn't just always-false).
               (c) TWO subprocess refusal proofs, zero model/torch import in
                   either: --live with EMBER_GATE_AUTHORIZED unset ->
                   LIVE_INTERLOCK_REFUSED (the banked-command / CUDA-
                   authorization interlock proof); --live --c14-receipt
                   <BLOCKED fixture> WITH EMBER_GATE_AUTHORIZED=1 set ->
                   LIVE_REFUSED naming the C14-vet failure (proves the C14
                   gate is enforced even once the env interlock is cleared,
                   and that refusal happens before any checkpoint/model
                   touch).
               (d) write_or_diagnose() defensive test: a receipt carrying a
                   literal INVALID_TOKENS string is aborted pre-write, no
                   file left behind (mirrors ember_ceff_closure_
                   confirmation.py's dirty_candidate coverage).

  --dry-run    Stub scorers (no model load, no torch import). Full receipt
               envelope including a c14_receipt block — vets a REAL receipt
               if --c14-receipt is given (still no model load), or
               synthesizes an in-memory stub c14_receipt block if omitted,
               purely to prove the plumbing runs end-to-end. Written to
               scratch/, never receipts/.

  --live       GATED behind EMBER_GATE_AUTHORIZED=1 (env) AND a
               --c14-receipt that vets PASS under vet_c14_receipt() AND
               v0_pretrain_launch_gate.g_budget() GREEN. IMPLEMENTED, NEVER
               EXECUTED BY THIS FILE'S OWN AUTHOR — banked for the
               authorizing session once a genuine C14 PASS receipt exists.
               Both legs remain pure CPU inference (no CUDA allocation
               anywhere in this file's compute graph, identical to
               ember_c_e2b_paired_run.py) — this specific paired comparison
               never structurally required a GPU; the GPU cost lives
               entirely in the C14 TRAINING run this file depends on (a
               separate, in-progress track), never in this file's own
               inference-only legs.

BANKED COMMAND (fires only once a genuine C14 PASS receipt exists):

  EMBER_GATE_AUTHORIZED=1 python src/ember/governance/scripts/ember_e2b_surpass_run.py --live \
    --c14-receipt receipts/<the-genuine-RESIDENT_TRAINING_GATE_PASS-receipt>.json

No git commits. No downloads. No CUDA allocation from this process ever.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
# ember_phase3_c14/ holds resident_adapter.py (build_toy_adapter,
# build_fp16_adapter) — needed by the adapter-file-loading selftest coverage
# below. Same pattern as ember_c14_owned_core.py / ember_c14_owned_run.py.
_PHASE3_DIR = _SCRIPT_DIR / "ember_phase3_c14"
if str(_PHASE3_DIR) not in sys.path:
    sys.path.insert(0, str(_PHASE3_DIR))

REPO = Path(__file__).resolve().parents[4]
GOALFORGE_ROOT = os.environ.get(
    "EMBER_GOALFORGE_ROOT", os.path.join(os.path.dirname(str(REPO)), "ember-goalforge")
)

TICKET = "E2B-SURPASS-RUN"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
RECEIPT_DIR = REPO / "receipts"
SMOKE_DIR = REPO / "scratch" / "ember-e2b-surpass-dryrun"  # NON-canonical; never receipts/

# Verbatim from ember-goalforge/src/ember/governance/scripts/ember_totality/test_c_e2b.py's own
# INVALID_TOKENS — never emit these as a real verdict-carrying receipt.
INVALID_TOKENS = ["invalid_e2b_unpaired", "invalid_single_leg_surpass"]

import ember_c_e2b_paired_run as paired  # noqa: E402  the runner this file extends


def _ts_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ts_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# C14 gate-receipt vetting — reuses ember-goalforge's OWN predicate, never a
# local reimplementation that could drift from scan()'s real vetting logic.
# ---------------------------------------------------------------------------

def _import_goalforge_c0():
    totality_dir = os.path.join(GOALFORGE_ROOT, "scripts", "ember_totality")
    if totality_dir not in sys.path:
        sys.path.insert(0, totality_dir)
    import test_c0 as c0_mod  # noqa: E402
    return c0_mod


def vet_c14_receipt(path: "str | None"):
    """Run ember-goalforge's test_c0.py::_vet_gate_receipts predicate over
    exactly ONE candidate C14 gate-receipt path. Returns
    (ok: bool, detail: str, data: dict | None). ok is True only if this
    single receipt survives as a real, undisqualified, unrevoked PASS under
    the IDENTICAL predicate scan() itself uses on the live C0 board — never
    a locally reimplemented (and driftable) copy of that logic."""
    if not path:
        return False, "no --c14-receipt given", None
    if not os.path.isfile(path):
        return False, f"C14 receipt path does not exist: {path!r}", None
    try:
        c0_mod = _import_goalforge_c0()
    except Exception as exc:  # noqa: BLE001
        return False, f"UNEVALUABLE: could not import goalforge test_c0.py vetting predicate: {exc}", None
    try:
        _raw, data = c0_mod.load_json(path)
    except Exception as exc:  # noqa: BLE001
        return False, f"C14 receipt unreadable: {exc}", None

    real_passes, revoked, audits, latest_verdict, latest_stamp, latest_blocked_stamp = (
        c0_mod._vet_gate_receipts([path])
    )
    if not real_passes:
        detail = (
            f"C14 receipt does NOT vet as a real PASS under test_c0.py's "
            f"_vet_gate_receipts predicate (verdict={data.get('verdict')!r} "
            f"status={data.get('resident_training_gate_status')!r}); audits={audits}"
        )
        return False, detail, data
    return True, f"vetted PASS (stamp={real_passes[0][0]})", data


def _resolve_relative(rel_or_abs: str, anchor_receipt_path: str) -> str:
    p = Path(rel_or_abs)
    if p.is_absolute():
        return str(p)
    repo_candidate = REPO / rel_or_abs
    if repo_candidate.exists():
        return str(repo_candidate)
    anchor_candidate = Path(anchor_receipt_path).resolve().parent / rel_or_abs
    return str(anchor_candidate)


def resolve_c14_checkpoint(c14_data: dict, c14_receipt_path: str):
    """Resolve the owned-core checkpoint lineage FROM a vetted C14 receipt.

    Contract (documented here because no real C14 PASS receipt exists yet
    to read one from — when the genuine one is authored, its
    resident_training_candidate block must satisfy this, or this harness
    will refuse rather than silently re-run the pretrain-seed comparison
    ember_c_e2b_paired_run.py already answered):

      candidate.resident_checkpoint_path    -- repo-relative or absolute
                                                path to the C14-cleared
                                                checkpoint. TWO shapes are
                                                accepted:
                                                  (1) a DIRECTORY containing
                                                      a merged model.pt
                                                      (base weights with the
                                                      trained delta baked
                                                      in), loadable
                                                      UNCHANGED through
                                                      make_owned_core_
                                                      factory(). No producer
                                                      of this shape exists
                                                      yet — see
                                                      ember_c14_owned_run.py
                                                      ::_persist_resident_
                                                      adapter's docstring
                                                      for why merging is
                                                      not attempted there
                                                      (the tied-embedding
                                                      corruption risk).
                                                  (2) a FILE ending ".pt"
                                                      holding a bare LoRA
                                                      adapter_state_dict()
                                                      (only "lora.lora_A"/
                                                      "lora.lora_B" keys,
                                                      no base weights) --
                                                      the shape
                                                      _persist_resident_
                                                      adapter actually
                                                      writes today.
                                                      load_owned_core_
                                                      from_c14_checkpoint()
                                                      below loads the
                                                      FROZEN pretrain base
                                                      plus this adapter,
                                                      never the untrained
                                                      base alone.
      candidate.resident_checkpoint_sha256  -- sha256 of that checkpoint's
                                                model.pt (shape 1) or of the
                                                adapter FILE's own on-disk
                                                bytes (shape 2). HASH-
                                                VERIFIED here (shape 1: via
                                                the swapped-in
                                                verify_seed_checkpoint call
                                                in load_owned_core_from_
                                                c14_checkpoint; shape 2: via
                                                _load_and_verify_adapter_
                                                file), never trusted bare.

    If the candidate itself defers this pointer to its own
    policy_update_trace_path (the trace JSON the candidate manifest already
    requires to exist per _validate_candidate_manifest), the SAME two keys
    are looked up there as a fallback.

    Returns (ok: bool, detail: str, ckpt_path_abs: str | None, sha256: str | None).
    ckpt_path_abs is a directory path (shape 1) or a file path (shape 2);
    the caller (load_owned_core_from_c14_checkpoint) dispatches on which.
    """
    candidate = (c14_data or {}).get("resident_training_candidate") or {}
    ckpt_rel = candidate.get("resident_checkpoint_path")
    ckpt_sha = candidate.get("resident_checkpoint_sha256")

    if not ckpt_rel:
        trace_ref = candidate.get("policy_update_trace_path")
        if trace_ref:
            trace_abs = _resolve_relative(trace_ref, c14_receipt_path)
            if trace_abs and os.path.isfile(trace_abs):
                try:
                    with open(trace_abs, "r", encoding="utf-8") as fh:
                        trace = json.load(fh)
                    ckpt_rel = trace.get("resident_checkpoint_path")
                    ckpt_sha = ckpt_sha or trace.get("resident_checkpoint_sha256")
                except Exception:  # noqa: BLE001
                    pass

    if not ckpt_rel or not ckpt_sha:
        return (
            False,
            "C14 receipt's resident_training_candidate names no "
            "resident_checkpoint_path/resident_checkpoint_sha256 (checked the "
            "candidate block and its policy_update_trace) -- refusing to fall "
            "back to the frozen pretrain seed for a --live invocation; this "
            "receipt cannot yet resolve a C14-cleared checkpoint lineage",
            None, None,
        )

    ckpt_abs = _resolve_relative(ckpt_rel, c14_receipt_path)
    is_dir = bool(ckpt_abs) and os.path.isdir(ckpt_abs)
    is_adapter_file = bool(ckpt_abs) and os.path.isfile(ckpt_abs) and ckpt_abs.endswith(".pt")
    if not (is_dir or is_adapter_file):
        return (
            False,
            "resolved checkpoint path does not exist on disk as either a "
            f"merged-checkpoint DIRECTORY or a bare adapter .pt FILE: "
            f"{ckpt_rel!r} -> {ckpt_abs!r}",
            None, None,
        )
    shape = "directory: merged checkpoint" if is_dir else "file: bare LoRA adapter"
    return True, f"resolved {ckpt_rel} ({shape}, sha256={ckpt_sha[:16]}..)", ckpt_abs, ckpt_sha


def _load_and_verify_adapter_file(adapter, ckpt_path: str, expected_sha256: str) -> dict:
    """Load a persisted LoRA adapter_state_dict() FILE (only "lora.lora_A"/
    "lora.lora_B" keys — ember_c14_owned_run.py::_persist_resident_adapter's
    actual artifact shape) into `adapter` (any resident_adapter.LoRAAdapter
    instance — the real owned-core adapter in production, a toy adapter in
    this file's --selftest coverage; the mechanism is identical either way).
    Reuses LoRAAdapter's OWN partial-state-dict load convention
    (restore_pre_adapter_state — resident_adapter.py, unedited by this
    function) rather than reimplementing load_state_dict handling.

    Fail-closed in three distinct, named ways — never a silent partial load:

      C14_ADAPTER_SHA256_MISMATCH -- the file's on-disk bytes do not match
        expected_sha256. Checked BEFORE torch.load ever runs; unverified
        bytes are never deserialized.

      C14_ADAPTER_LOAD_NOOP -- adapter_param_hash() is byte-identical
        before and after the load. Proves load_state_dict actually mutated
        the adapter's tensors (catches a silent no-op from e.g. a key or
        shape mismatch that load_state_dict(strict=False) would otherwise
        swallow quietly for missing keys).

      C14_ADAPTER_ZERO_DELTA -- the loaded lora.lora_B tensor is all-zero.
        LoRALayer.forward computes `(x @ lora_A @ lora_B) * scaling`
        (resident_adapter.py), so an all-zero lora_B makes the correction
        EXACTLY zero for every input regardless of lora_A (LoRALayer's own
        docstring: "lora_B starts at zero so the initial correction is
        zero"). A persisted "trained" adapter whose lora_B collapsed back
        to all-zero has, by construction, zero forward effect — silently
        scoring it would be indistinguishable from scoring the untrained
        seed, exactly the failure mode this function exists to refuse.

    Returns a dict of the measured facts on success (never on refusal —
    every failure path above raises RuntimeError instead of returning a
    partial/degraded result)."""
    import torch  # noqa: E402  lazy — matches this file's existing lazy-
                  # import style (see write_or_diagnose); no module-level
                  # torch dependency for callers that never touch this path.
    from ember_c14_owned_run import _sha256_file  # noqa: E402  reuse, never duplicate

    ckpt_p = Path(ckpt_path)
    actual_sha256 = _sha256_file(ckpt_p)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"C14_ADAPTER_SHA256_MISMATCH: {ckpt_path} actual={actual_sha256} "
            f"expected={expected_sha256} — refusing to load unverified adapter bytes."
        )

    pre_load_hash = adapter.adapter_param_hash()
    loaded_sd = torch.load(ckpt_p, map_location="cpu", weights_only=True)
    adapter.restore_pre_adapter_state(loaded_sd)
    post_load_hash = adapter.adapter_param_hash()
    if post_load_hash == pre_load_hash:
        raise RuntimeError(
            "C14_ADAPTER_LOAD_NOOP: loading the persisted adapter file did not "
            "change any adapter parameter bytes — refusing rather than silently "
            "scoring the freshly-initialized zero-effect adapter."
        )

    lora_b = loaded_sd.get("lora.lora_B")
    if lora_b is None or bool(torch.all(lora_b == 0).item()):
        raise RuntimeError(
            "C14_ADAPTER_ZERO_DELTA: the persisted adapter's lora.lora_B is "
            "all-zero — LoRALayer.forward's correction (x @ lora_A @ lora_B * "
            "scaling) is therefore EXACTLY zero for every input regardless of "
            "lora_A, meaning this 'trained' candidate has zero forward effect "
            "and would silently score the untrained seed. Refusing."
        )

    return {
        "adapter_file_sha256": actual_sha256,
        "param_hash_before_load": pre_load_hash,
        "param_hash_after_load": post_load_hash,
        "lora_b_nonzero": True,
    }


def load_owned_core_from_c14_checkpoint(
    ckpt_path: str,
    expected_sha256: str,
    rank: int = 8,
    base_seed_ckpt: Optional[Path] = None,
    base_expected_sha256: Optional[str] = None,
):
    """Load the owned core from a C14-cleared checkpoint. TWO shapes,
    matching resolve_c14_checkpoint()'s contract:

      DIRECTORY (a future merged checkpoint — base weights with the trained
      delta baked in; no producer exists yet): temporarily repoints
      ember_c14_owned_core's module-level SEED_CKPT_DEFAULT /
      EXPECTED_MODEL_PT_SHA256 globals, calling make_owned_core_factory()
      UNCHANGED, then restoring both globals in a finally block. Same
      swap-in-finally pattern as ember_ceff_closure_confirmation.py::
      run_shatter_compute_fit_selfcheck (gate_mod.NC). verify_seed_
      checkpoint's hash-verify then runs against the C14-cleared
      checkpoint's own expected hash — never the pretrain seed's, never
      skipped. UNCHANGED by the FILE branch below.

      FILE ending ".pt" (the shape ember_c14_owned_run.py::
      _persist_resident_adapter actually writes today — a bare LoRA
      adapter_state_dict(), only "lora.lora_A"/"lora.lora_B" keys, no base
      weights): `base_seed_ckpt` and `base_expected_sha256` are REQUIRED for
      this shape (raises C14_FILE_SHAPE_REQUIRES_EXPLICIT_BASE if either is
      missing) and repoint SEED_CKPT_DEFAULT/EXPECTED_MODEL_PT_SHA256 the
      SAME way the DIRECTORY branch above does (same try/finally pattern),
      before make_owned_core_factory() runs. ckpt_path is the ADAPTER file —
      never the base — but which BASE the adapter was actually trained
      against is exactly as load-bearing as the adapter delta itself: an
      adapter is only half an identity (v1.3 clause 1). Prior to this fix,
      the FILE shape silently defaulted to whatever SEED_CKPT_DEFAULT
      happened to be, which is correct only when a run trained against the
      unmodified default seed — and silently WRONG the instant a caller
      trained against an A20-substrate-overridden base instead (issue #23's
      citation-integrity investigation: fire-4's persisted adapter, reloaded
      against the wrong default base, reproduced none of its own in-loop
      recorded rows; reloaded against its ACTUAL training base, it
      reproduced all 8 exactly — scratch/c-e2b-merge/probe-e-base-identity-
      and-real-callback-*.json). The identity dict now carries
      base_checkpoint_path/base_model_pt_sha256 so every downstream receipt
      records which base the adapter was attached to, not just which
      adapter. The persisted adapter FILE is then hash-verified and loaded
      into that attached LoRA by _load_and_verify_adapter_file() (see its
      docstring for the three fail-closed checks).

      This is why adapter-file loading is clean where a directory-based
      merge is not: ember_c14_owned_run.py::_persist_resident_adapter's
      docstring names the merge risk — writing a trained delta into
      head.weight would either be silently dropped on reload (matching the
      existing tied-embedding convention — the merge never takes effect) or
      corrupt the SHARED embedding storage if included. The LoRA correction
      loaded here lives entirely in the separate self.lora submodule
      (lora_A, lora_B), structurally disjoint from every base parameter, so
      loading only those two tensors can never touch head.weight — this
      holds regardless of which layer LoRAAdapter was attached to.

      CORRECTION to an earlier draft of this contract: it claimed LoRA is
      never injected at the tied embed/head layer itself. Measured against
      this repo's actual code, that claim is FALSE at both call sites that
      build a LoRAAdapter: ember_c14_owned_core.make_owned_core_factory()
      hardcodes target_layer_name="head" (tied to the input embedding, per
      that factory's own "tied-embedding alias" comment on head.weight),
      and resident_adapter.build_fp16_adapter()'s "first nn.Linear found in
      named_modules()" search also resolves to the tied lm_head (renamed
      attention_proj_0 by EmberModelShell's naming heuristic — see
      _selftest_adapter_file_load's build_fp16_adapter probe below, which
      measures target_module.weight sharing storage with embed_tokens.
      weight). The TRUE, load-bearing invariant this function actually
      depends on is structural, not positional: lora_A/lora_B live in a
      submodule disjoint from every base parameter, tied or not — never
      which layer the forward hook happens to be attached to.
    """
    ckpt_p = Path(ckpt_path)

    if ckpt_p.is_dir():
        import ember_c14_owned_core as core_mod  # noqa: E402

        old_seed = core_mod.SEED_CKPT_DEFAULT
        old_sha = core_mod.EXPECTED_MODEL_PT_SHA256
        core_mod.SEED_CKPT_DEFAULT = ckpt_p
        core_mod.EXPECTED_MODEL_PT_SHA256 = expected_sha256
        try:
            factory = core_mod.make_owned_core_factory(device="cpu", rank=rank)
            adapter = factory()
        finally:
            core_mod.SEED_CKPT_DEFAULT = old_seed
            core_mod.EXPECTED_MODEL_PT_SHA256 = old_sha
        identity = dict(adapter._owned_core_identity)
        identity["artifact_shape"] = "merged_checkpoint_directory"
        return adapter, identity

    if ckpt_p.is_file() and ckpt_p.suffix == ".pt":
        import ember_c14_owned_core as core_mod  # noqa: E402

        # BASE-IDENTITY ASSERT (v1.3 clause 1, issue #23): the silent
        # SEED_CKPT_DEFAULT fallback that let fire-4's adapter get attached
        # to the wrong base checkpoint is REMOVED for this shape, not
        # defaulted-but-overridable — a caller must name the base explicitly.
        if base_seed_ckpt is None or base_expected_sha256 is None:
            raise RuntimeError(
                "C14_FILE_SHAPE_REQUIRES_EXPLICIT_BASE: the bare-adapter-file "
                "shape has no base weights of its own -- base_seed_ckpt and "
                "base_expected_sha256 must both be supplied (e.g. from the C14 "
                "receipt's own candidate_manifest.seed_checkpoint_path/"
                "seed_checkpoint_sha256) so the adapter is attached to the SAME "
                "base it was actually trained against. Silently defaulting to "
                "SEED_CKPT_DEFAULT is exactly the bug issue #23's citation-"
                "integrity investigation found: an adapter trained against an "
                "A20-substrate-overridden base, reloaded onto the wrong "
                "default base, reproduces none of its own recorded rows."
            )

        base_seed_ckpt = Path(base_seed_ckpt)
        old_seed = core_mod.SEED_CKPT_DEFAULT
        old_sha = core_mod.EXPECTED_MODEL_PT_SHA256
        core_mod.SEED_CKPT_DEFAULT = base_seed_ckpt
        core_mod.EXPECTED_MODEL_PT_SHA256 = base_expected_sha256
        try:
            factory = core_mod.make_owned_core_factory(device="cpu", rank=rank)
            adapter = factory()  # caller-named base + fresh zero-effect LoRA
        finally:
            core_mod.SEED_CKPT_DEFAULT = old_seed
            core_mod.EXPECTED_MODEL_PT_SHA256 = old_sha

        load_facts = _load_and_verify_adapter_file(adapter, str(ckpt_p), expected_sha256)
        identity = dict(adapter._owned_core_identity)
        identity["base_checkpoint_path"] = str(base_seed_ckpt)
        identity["base_model_pt_sha256"] = base_expected_sha256
        identity["resident_adapter_checkpoint_path"] = str(ckpt_p)
        identity["resident_adapter_sha256"] = load_facts["adapter_file_sha256"]
        identity["resident_adapter_param_hash_before_load"] = load_facts["param_hash_before_load"]
        identity["resident_adapter_param_hash_after_load"] = load_facts["param_hash_after_load"]
        identity["artifact_shape"] = "lora_adapter_state_dict_only_file"
        return adapter, identity

    raise RuntimeError(
        f"C14_CHECKPOINT_SHAPE_UNRECOGNIZED: {ckpt_path!r} is neither an "
        "existing directory nor a file ending .pt — resolve_c14_checkpoint() "
        "should have refused before this function was ever called."
    )


# ---------------------------------------------------------------------------
# Self-check leg — the REAL test_c_e2b.py, invoked as a subprocess against
# whatever receipts_dir we just wrote to. Pure Python/JSON, no torch needed.
# ---------------------------------------------------------------------------

def run_test_c_e2b_selfcheck(root_dir: str, timeout: float = 30.0) -> str:
    probe_path = os.path.join(GOALFORGE_ROOT, "scripts", "ember_totality", "test_c_e2b.py")
    if not os.path.isfile(probe_path):
        return f"UNEVALUABLE test_c_e2b.py not found at {probe_path} (set EMBER_GOALFORGE_ROOT)"
    env = dict(os.environ)
    env["EMBER_TOTALITY_ROOT"] = root_dir
    try:
        result = subprocess.run([sys.executable, probe_path], capture_output=True, text=True,
                                 env=env, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return f"UNEVALUABLE test_c_e2b.py subprocess failed: {exc}"
    out = (result.stdout or "").strip()
    lines = [l for l in out.splitlines() if l.strip()]
    return lines[-1] if lines else f"UNEVALUABLE empty stdout (stderr: {(result.stderr or '')[:500]})"


def _probe_outcome_acceptable(probe_line: str) -> bool:
    """True iff test_c_e2b.py's own verdict recognizes this receipt as
    protocol-compliant evidence: either a real surpass GREEN, or the
    explicitly-accepted measured-distance RED (the verbatim substrings
    below are quoted straight from that probe's own emit() calls). A
    format-invalid RED or an UNEVALUABLE is never acceptable — those mean
    the candidate is not admissible evidence at all."""
    if probe_line.upper().startswith("GREEN"):
        return True
    if probe_line.startswith("RED") and "measured-distance receipt" in probe_line \
            and "protocol-compliant" in probe_line:
        return True
    return False


def scan_invalid_tokens(receipt: dict) -> list:
    blob = json.dumps(receipt).lower()
    return [t for t in INVALID_TOKENS if t.lower() in blob]


def write_or_diagnose(receipt: dict, receipts_dir: str):
    """Assemble -> self-check -> write, never write -> hope (mirrors
    ember_ceff_closure_confirmation.py::write_or_diagnose). GREEN or the
    named measured-distance RED -> keep as ember-e2b-surpass-<ts>.json.
    Anything else -> DELETE the candidate (if written) and write an
    e2b-surpass-attempt-<ts>.json diagnostic instead. Returns
    (path, success, probe_line)."""
    from receipt_write import checked_write  # noqa: E402

    ts = receipt["ts"]
    os.makedirs(receipts_dir, exist_ok=True)
    hits = scan_invalid_tokens(receipt)
    if hits:
        diag_path = os.path.join(receipts_dir, f"e2b-surpass-attempt-{_ts_compact()}.json")
        diag = {**receipt, "ticket": "E2B-SURPASS-ATTEMPT",
                "diagnostic_reason": f"invalid-token(s) present pre-write: {hits}"}
        with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(diag, f, indent=2)
        return Path(diag_path), False, f"ABORTED pre-write: invalid-token(s) {hits}"

    candidate_path = os.path.join(receipts_dir, f"ember-e2b-surpass-{_ts_compact()}.json")
    checked_write(candidate_path, receipt)

    probe_root = os.path.dirname(receipts_dir) if os.path.basename(receipts_dir) == "receipts" else receipts_dir
    probe_line = run_test_c_e2b_selfcheck(probe_root)
    if _probe_outcome_acceptable(probe_line):
        return Path(candidate_path), True, probe_line

    try:
        os.unlink(candidate_path)
    except OSError:
        pass
    diag_path = os.path.join(receipts_dir, f"e2b-surpass-attempt-{_ts_compact()}.json")
    diag = {**receipt, "ticket": "E2B-SURPASS-ATTEMPT",
            "diagnostic_reason": f"test_c_e2b.py self-check did not accept: {probe_line}"}
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, indent=2)
    return Path(diag_path), False, probe_line


# ---------------------------------------------------------------------------
# CLI modes
# ---------------------------------------------------------------------------

def cmd_dry_run(args: argparse.Namespace) -> int:
    protocol_ref = paired.freeze_protocol_if_needed()

    if args.c14_receipt:
        ok, detail, _data = vet_c14_receipt(args.c14_receipt)
        c14_block = {"path": args.c14_receipt, "vetted": ok, "vet_detail": detail}
    else:
        ok = True
        c14_block = {
            "path": None, "vetted": True, "stub": True,
            "vet_detail": "STUB-NO-C14-RECEIPT-GIVEN (dry-run plumbing proof only, never evidence)",
        }

    legs = {
        "ember_work": {
            "battery": "c14-increment-mod-8-executing-verifier (STUB)",
            "n_tasks": args.n_tasks, "owned_core_score": 0.5, "e2b_score": 0.25,
            "owned_rows": [], "e2b_rows": [], "stub": True,
        },
        "founder_likeness": {
            "battery": "nck-20-episode-duty-battery (STUB)",
            "n_episodes": args.n_episodes, "owned_core_score": 0.5, "e2b_score": 0.15,
            "owned_rows": [], "e2b_rows": [], "stub": True,
        },
    }
    matched_budget = {"owned_arm": args.max_new_tokens, "e2b_arm": args.max_new_tokens,
                      "unit": "max_new_tokens (identical decode budget both arms both legs)"}
    verdict, gap = paired.compute_verdict(legs)

    receipt = {
        "ticket": TICKET, "ts": _ts_iso(), "mode": "dry-run-plumbing-stub",
        "script": "src/ember/governance/scripts/ember_e2b_surpass_run.py", "sha_convention": SHA_CONVENTION,
        "issue": "#23", "api_spend_usd": 0, "paid_api_surface_used": False,
        "c14_receipt": c14_block,
        "legs": legs, "matched_budget": matched_budget,
        "owned_core_identity": {
            "id": "STUB-NO-LOAD", "checkpoint": "STUB-NO-LOAD",
            "model_pt_sha256": "0" * 64, "no_borrowed_weights": True, "quantized": False,
        },
        "e2b_reference": {"model_id": paired.E2B_MODEL_ID, "local_path": "STUB-NO-LOAD", "stub": True},
        "protocol_frozen_ref": protocol_ref,
        "verdict": verdict,
    }
    if gap:
        receipt["remaining_gap"] = gap
        receipt["receipt_type"] = "e2b_measured_distance"

    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    path = SMOKE_DIR / f"dry-run-{_ts_compact()}.json"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(f"DRY_RUN_PLUMBING_OK verdict={receipt['verdict']} c14_vetted={ok}")
    print(f"receipt={path}")
    return 0


_INT_RE = re.compile(r"-?\d+")


def _score_owned_arm_live_leg1(
    owned_adapter, e2b_generate_fn, n_tasks: int, corpus_seed: int, heldout_size: int,
) -> dict:
    """This file's OWN leg-1 scorer -- distinct from paired.score_ember_work_
    leg_v1 (issue #48: owned arm is CITED from fire-4's receipt, never
    re-run). This file's whole purpose is re-running the owned arm LIVE
    against whatever checkpoint --c14-receipt resolves (not necessarily
    fire-4 -- a future resident-training clearing would name a different
    checkpoint), so the citation shortcut does not apply here by design.
    Body preserved from the pre-#48 ember_c_e2b_paired_run.py::
    score_ember_work_leg (removed there when that file moved to citation-
    only scoring)."""
    from ember_c14_owned_run import (  # noqa: E402
        generate_corpus, _executing_verifier, _eval_one_task, _ActionBandPolicy,
    )

    corpus, corpus_meta = generate_corpus(
        seed=corpus_seed, heldout_size=heldout_size, corpus_v2=True, k_exemplars=3,
    )
    all_tasks = corpus.train + corpus.heldout
    tasks = all_tasks[:n_tasks] if n_tasks < len(all_tasks) else all_tasks

    owned_policy = _ActionBandPolicy(owned_adapter)
    owned_rows = [
        _eval_one_task(owned_policy, task, _executing_verifier, max_depth=0, temperature=0.0)
        for task in tasks
    ]
    owned_pass = sum(1 for r in owned_rows if r["reward"] == 1.0)
    owned_score = owned_pass / len(tasks) if tasks else 0.0

    e2b_rows = []
    for task in tasks:
        prompt = (
            f"You are a state machine. Given an integer state in the range "
            f"0-7, respond with ONLY the single integer that equals "
            f"(state + 1) mod 8. State: {task.state_val}\n"
            "Answer with only the integer, no words, no punctuation."
        )
        completion = e2b_generate_fn(prompt)
        m = _INT_RE.search(completion)
        action = int(m.group(0)) if m else None
        expected = (task.state_val + 1) % 8
        reward = 1.0 if (action is not None and (action % 8) == expected) else 0.0
        e2b_rows.append({
            "id": task.id, "state_val": task.state_val, "raw_completion": completion[:200],
            "parsed_action": action, "expected": expected, "reward": reward,
        })
    e2b_pass = sum(1 for r in e2b_rows if r["reward"] == 1.0)
    e2b_score = e2b_pass / len(tasks) if tasks else 0.0

    return {
        "battery": "c14-increment-mod-8-executing-verifier (owned arm run live, not cited -- "
                   "this file's own use case, see _score_owned_arm_live_leg1 docstring)",
        "corpus_meta": corpus_meta,
        "n_tasks": len(tasks),
        "owned_core_score": owned_score,
        "e2b_score": e2b_score,
        "owned_rows": owned_rows,
        "e2b_rows": e2b_rows,
    }


def cmd_live(args: argparse.Namespace) -> int:
    """The real paired run at matched governed budget, against the
    C14-cleared checkpoint. GATED. Implemented, never executed by this
    file's own author — see module docstring."""
    if not args.c14_receipt:
        print("LIVE_REFUSED: --c14-receipt is required for --live (no fallback to the pretrain seed).")
        return 2

    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
    if not authorized:
        print(
            "LIVE_INTERLOCK_REFUSED: requires EMBER_GATE_AUTHORIZED=1 (env). "
            "Mirrors ember_c_e2b_paired_run.py::cmd_live's fail-closed interlock."
        )
        return 2

    ok, detail, c14_data = vet_c14_receipt(args.c14_receipt)
    if not ok:
        print(f"LIVE_REFUSED: C14 receipt did not vet PASS: {detail}")
        return 2

    ok2, detail2, ckpt_abs, ckpt_sha = resolve_c14_checkpoint(c14_data, args.c14_receipt)
    if not ok2:
        print(f"LIVE_REFUSED: {detail2}")
        return 2

    # BASE-IDENTITY ASSERT (v1.3 clause 1, issue #23): resolve_c14_checkpoint
    # only resolves the ADAPTER lineage (resident_training_candidate); the
    # BASE checkpoint the adapter was actually trained against lives in this
    # SAME receipt's candidate_manifest block (ember_c14_owned_run.py:1787-
    # 1791 builds it from the same seed_ckpt_override/args.seed_checkpoint_
    # sha256 variables the training run's own factory call read, so it is
    # not an independent re-statement). Refused, never defaulted, exactly
    # like the adapter-lineage refusal above.
    candidate_manifest = (c14_data or {}).get("candidate_manifest") or {}
    base_seed_rel = candidate_manifest.get("seed_checkpoint_path")
    base_seed_sha = candidate_manifest.get("seed_checkpoint_sha256")
    if not base_seed_rel or not base_seed_sha:
        print(
            "LIVE_REFUSED: C14 receipt has no candidate_manifest.seed_checkpoint_path/"
            "seed_checkpoint_sha256 -- cannot resolve which base checkpoint the resident "
            "adapter was trained against; refusing rather than defaulting (issue #23 "
            "citation-integrity finding: a silent base default previously reproduced none "
            "of the trained adapter's own recorded rows)."
        )
        return 2
    base_seed_ckpt_dir = _resolve_relative(str(Path(base_seed_rel).parent), args.c14_receipt)

    sys.path.insert(0, str(REPO / "scripts"))
    import v0_pretrain_launch_gate as gate_mod  # noqa: E402
    import datetime as _dt

    steps_c14 = args.n_tasks
    steps_founder = args.n_episodes * args.max_new_tokens  # rough: one fwd/token, no cache
    total_steps = steps_c14 + steps_founder
    requested_run = {
        "source": "ember-e2b-surpass-run--live",
        "total_steps": total_steps,
        "params": gate_mod.V0_REALIZED_PARAMS,
        "batch": 1,
        "seq": 1024,
    }
    st, dt = gate_mod.g_budget(_dt.date.today(), requested_run=requested_run)
    print(f"G-budget: {st} — {dt}")
    if st != "GREEN":
        print(f"LIVE_REFUSED: G-budget not GREEN: {dt}")
        return 2

    protocol_ref = paired.freeze_protocol_if_needed()
    e2b_info = paired.find_local_e2b_model()
    owned_adapter, owned_identity = load_owned_core_from_c14_checkpoint(
        ckpt_abs, ckpt_sha, rank=args.lora_rank,
        base_seed_ckpt=Path(base_seed_ckpt_dir), base_expected_sha256=base_seed_sha,
    )
    e2b_tok, e2b_model = paired.load_e2b_model(e2b_info["local_path"])
    ember_tok = __import__("tokenizers").Tokenizer.from_file(str(paired.EMBER_TOKENIZER_PATH))

    # NOTE (issue #48 supersession): paired.score_ember_work_leg_v1 now scores
    # the owned arm by CITATION from fire-4's own receipt only -- it does not
    # support "evaluate an arbitrary already-loaded adapter live", which is
    # this file's whole reason for existing (--c14-receipt may resolve to any
    # vetted resident-training-gate-pass receipt, not necessarily fire-4's).
    # _score_owned_arm_live_leg1 below is the old direct-eval body (unchanged
    # semantics), kept local here since paired.py's replacement dropped it.
    e2b_generate_c14 = paired.make_e2b_generate_fn(e2b_tok, e2b_model, max_new_tokens=16)
    leg1 = _score_owned_arm_live_leg1(
        owned_adapter, e2b_generate_c14, n_tasks=args.n_tasks,
        corpus_seed=args.corpus_seed, heldout_size=args.heldout_size,
    )
    owned_generate_nck = paired.make_owned_core_generate_fn(owned_adapter, ember_tok, args.max_new_tokens)
    e2b_generate_nck = paired.make_e2b_generate_fn(e2b_tok, e2b_model, max_new_tokens=args.max_new_tokens)
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    leg2 = paired.score_founder_likeness_leg_v1(
        owned_generate_nck, e2b_generate_nck, receipt_dir=str(RECEIPT_DIR),
        window_s=args.continuation_window_s,
    )

    legs = {"ember_work": leg1, "founder_likeness": leg2}
    matched_budget = {"owned_arm": args.max_new_tokens, "e2b_arm": args.max_new_tokens,
                      "unit": "max_new_tokens (identical decode budget both arms both legs)"}
    verdict, gap = paired.compute_verdict(legs)

    c14_path_rel = args.c14_receipt
    try:
        c14_path_rel = os.path.relpath(os.path.abspath(args.c14_receipt), REPO).replace("\\", "/")
    except ValueError:
        pass

    receipt = {
        "ticket": TICKET, "ts": _ts_iso(), "mode": "live",
        "script": "src/ember/governance/scripts/ember_e2b_surpass_run.py", "sha_convention": SHA_CONVENTION,
        "issue": "#23", "api_spend_usd": 0, "paid_api_surface_used": False,
        "c14_receipt": {
            "path": c14_path_rel, "vetted": True, "vet_detail": detail,
            "resident_checkpoint_lineage": detail2,
        },
        "legs": legs, "matched_budget": matched_budget,
        "owned_core_identity": {
            "id": f"c14-cleared:{owned_identity.get('model_pt_sha256', '')[:16]}",
            "checkpoint": owned_identity.get("checkpoint"),
            "model_pt_sha256": owned_identity.get("model_pt_sha256"),
            "no_borrowed_weights": True,
            "quantized": False,
            "artifact_shape": owned_identity.get("artifact_shape"),
            # present only for the adapter-FILE shape (base_* / resident_adapter_*
            # keys load_owned_core_from_c14_checkpoint's FILE branch adds) — never
            # for the DIRECTORY shape, whose identity dict has no such keys.
            **{
                k: owned_identity[k]
                for k in (
                    "base_checkpoint_path",
                    "base_model_pt_sha256",
                    "resident_adapter_checkpoint_path",
                    "resident_adapter_sha256",
                    "resident_adapter_param_hash_before_load",
                    "resident_adapter_param_hash_after_load",
                )
                if k in owned_identity
            },
        },
        "e2b_reference": e2b_info,
        "protocol_frozen_ref": protocol_ref,
        "verdict": verdict,
        "g_budget": {"status": st, "detail": dt},
        "requested_run": requested_run,
    }
    if gap:
        receipt["remaining_gap"] = gap
        receipt["receipt_type"] = "e2b_measured_distance"

    path, ok3, probe_line = write_or_diagnose(receipt, str(RECEIPT_DIR))
    print(f"LIVE_{'DONE' if ok3 else 'DIAGNOSTIC'} verdict={receipt['verdict']} probe={probe_line!r}")
    print(f"receipt={path}")
    return 0 if ok3 else 1


# ---------------------------------------------------------------------------
# Selftest — pure CPU, no model load, no --c14-receipt required.
# ---------------------------------------------------------------------------

def _write_fixture_protocol(root: str, ts_compact: str) -> str:
    docs = os.path.join(root, "docs")
    os.makedirs(docs, exist_ok=True)
    name = f"c-e2b-paired-protocol-freeze-{ts_compact}.md"
    with open(os.path.join(docs, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# selftest fixture protocol freeze ({ts_compact})\n")
    return f"docs/{name}"


def _write_receipt_fixture(root: str, name: str, data: dict) -> str:
    d = os.path.join(root, "receipts")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
    return p


def _base_fixture_fields(protocol_ref: str, ts: str) -> dict:
    return {
        "ticket": "SELFTEST-E2B-SURPASS", "ts": ts, "mode": "selftest-fixture",
        "sha_convention": SHA_CONVENTION, "api_spend_usd": 0, "paid_api_surface_used": False,
        "matched_budget": {"owned_arm": 16, "e2b_arm": 16, "unit": "max_new_tokens"},
        "owned_core_identity": {
            "id": "selftest-fixture", "no_borrowed_weights": True, "quantized": False,
        },
        "protocol_frozen_ref": protocol_ref,
    }


def _fixture_surpass(protocol_ref: str, ts: str) -> dict:
    r = _base_fixture_fields(protocol_ref, ts)
    r["legs"] = {
        "ember_work": {"battery": "fixture", "n_tasks": 2, "owned_core_score": 0.9, "e2b_score": 0.4,
                       "owned_rows": [], "e2b_rows": []},
        "founder_likeness": {"battery": "fixture", "n_episodes": 2, "owned_core_score": 0.8, "e2b_score": 0.3,
                              "owned_rows": [], "e2b_rows": []},
    }
    r["verdict"] = "surpass"
    return r


def _fixture_distance(protocol_ref: str, ts: str) -> dict:
    r = _base_fixture_fields(protocol_ref, ts)
    r["legs"] = {
        "ember_work": {"battery": "fixture", "n_tasks": 2, "owned_core_score": 0.1, "e2b_score": 0.9,
                       "owned_rows": [], "e2b_rows": []},
        "founder_likeness": {"battery": "fixture", "n_episodes": 2, "owned_core_score": 0.8, "e2b_score": 0.3,
                              "owned_rows": [], "e2b_rows": []},
    }
    r["verdict"] = "measured_distance"
    r["remaining_gap"] = "ember_work: owned 0.100 <= e2b 0.900 (gap 0.800)"
    r["receipt_type"] = "e2b_measured_distance"
    return r


def _fixture_invalid_single_leg(protocol_ref: str, ts: str) -> dict:
    r = _base_fixture_fields(protocol_ref, ts)
    r["legs"] = {
        "ember_work": {"battery": "fixture", "n_tasks": 2, "owned_core_score": 0.9, "e2b_score": 0.4,
                       "owned_rows": [], "e2b_rows": []},
        # founder_likeness deliberately absent -- one-leg comparison, invalid by construction
    }
    r["verdict"] = "surpass"
    return r


def _c14_fixture_pass(ts: str) -> dict:
    return {
        "ticket": "SELFTEST-C14-GATE", "ts": ts,
        "verdict": "RESIDENT_TRAINING_GATE_PASS",
        "resident_training_gate_status": "PASS",
        "component_status": {"paper_source_preflight": "PASS", "candidate_resident_training_manifest": "PASS"},
    }


def _c14_fixture_blocked(ts: str) -> dict:
    return {
        "ticket": "SELFTEST-C14-GATE", "ts": ts,
        "verdict": "RESIDENT_TRAINING_GATE_BLOCKED",
        "resident_training_gate_status": "BLOCKED",
        "component_status": {"paper_source_preflight": "PASS", "candidate_resident_training_manifest": "BLOCKED"},
    }


def _selftest_probe_roundtrips(fail: list) -> None:
    # (a1) surpass fixture -> GREEN, acceptable
    with tempfile.TemporaryDirectory(prefix="ember-e2b-surpass-selftest-surpass-") as td:
        proto_ref = _write_fixture_protocol(td, "20260101T000000Z")
        fx = _fixture_surpass(proto_ref, "2026-01-01T00:01:00Z")
        _write_receipt_fixture(td, "selftest-e2b-surpass.json", fx)
        line = run_test_c_e2b_selfcheck(td)
        if not (line.upper().startswith("GREEN") and _probe_outcome_acceptable(line)):
            fail.append(f"surpass-fixture round-trip: expected GREEN+acceptable, got {line!r}")
        else:
            print(f"  [selftest] surpass fixture -> {line[:100]}  PASS")

    # (a2) distance fixture -> RED measured-distance, acceptable
    with tempfile.TemporaryDirectory(prefix="ember-e2b-surpass-selftest-distance-") as td:
        proto_ref = _write_fixture_protocol(td, "20260101T000000Z")
        fx = _fixture_distance(proto_ref, "2026-01-01T00:01:00Z")
        _write_receipt_fixture(td, "selftest-e2b-distance.json", fx)
        line = run_test_c_e2b_selfcheck(td)
        if not (line.startswith("RED") and "measured-distance receipt" in line
                and "protocol-compliant" in line and _probe_outcome_acceptable(line)):
            fail.append(f"distance-fixture round-trip: expected named measured-distance RED+acceptable, got {line!r}")
        else:
            print(f"  [selftest] distance fixture -> {line[:100]}  PASS")

    # (a3) invalid single-leg fixture -> format-invalid RED, NOT acceptable
    with tempfile.TemporaryDirectory(prefix="ember-e2b-surpass-selftest-invalid-") as td:
        proto_ref = _write_fixture_protocol(td, "20260101T000000Z")
        fx = _fixture_invalid_single_leg(proto_ref, "2026-01-01T00:01:00Z")
        _write_receipt_fixture(td, "selftest-e2b-invalid.json", fx)
        line = run_test_c_e2b_selfcheck(td)
        if not (line.startswith("RED") and _probe_outcome_acceptable(line) is False):
            fail.append(f"invalid-fixture round-trip: expected format-invalid RED rejected, got {line!r}")
        else:
            print(f"  [selftest] invalid single-leg fixture -> {line[:100]}  correctly REJECTED  PASS")


def _selftest_c14_vet_unit(fail: list) -> None:
    with tempfile.TemporaryDirectory(prefix="ember-e2b-surpass-selftest-c14-") as td:
        blocked_path = os.path.join(td, "c14-blocked.json")
        with open(blocked_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(_c14_fixture_blocked("20260701T000000Z"), f)
        ok, detail, _data = vet_c14_receipt(blocked_path)
        if ok:
            fail.append(f"vet_c14_receipt negative control: BLOCKED fixture vetted ok=True (should be False): {detail}")
        else:
            print(f"  [selftest] vet_c14_receipt(BLOCKED fixture) -> ok=False ({detail[:80]}...)  PASS")

        pass_path = os.path.join(td, "c14-pass.json")
        with open(pass_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(_c14_fixture_pass("20260701T000000Z"), f)
        ok2, detail2, _data2 = vet_c14_receipt(pass_path)
        if not ok2:
            fail.append(f"vet_c14_receipt positive control: well-formed PASS fixture vetted ok=False: {detail2}")
        else:
            print(f"  [selftest] vet_c14_receipt(PASS fixture) -> ok=True ({detail2})  PASS")


def _selftest_live_refusals(fail: list) -> None:
    env_clean = dict(os.environ)
    env_clean.pop("EMBER_GATE_AUTHORIZED", None)

    # (c1) --live with no EMBER_GATE_AUTHORIZED -> LIVE_INTERLOCK_REFUSED, exit 2
    r1 = subprocess.run(
        [sys.executable, str(_SCRIPT_DIR / "ember_e2b_surpass_run.py"), "--live",
         "--c14-receipt", "nonexistent-path-does-not-matter.json"],
        capture_output=True, text=True, env=env_clean, timeout=30,
    )
    if r1.returncode != 2 or "LIVE_INTERLOCK_REFUSED" not in (r1.stdout or ""):
        fail.append(f"live interlock refusal: expected exit 2 + LIVE_INTERLOCK_REFUSED, "
                    f"got exit={r1.returncode} stdout={r1.stdout!r}")
    else:
        print("  [selftest] --live w/o EMBER_GATE_AUTHORIZED -> LIVE_INTERLOCK_REFUSED, exit 2  PASS "
              "(banked-command / CUDA-authorization interlock proof)")

    # (c2) --live --c14-receipt <BLOCKED fixture> WITH EMBER_GATE_AUTHORIZED=1 ->
    # LIVE_REFUSED naming the C14-vet failure, zero model/checkpoint touch.
    with tempfile.TemporaryDirectory(prefix="ember-e2b-surpass-selftest-c14live-") as td:
        blocked_path = os.path.join(td, "c14-blocked.json")
        with open(blocked_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(_c14_fixture_blocked("20260701T000000Z"), f)
        env_auth = dict(os.environ)
        env_auth["EMBER_GATE_AUTHORIZED"] = "1"
        r2 = subprocess.run(
            [sys.executable, str(_SCRIPT_DIR / "ember_e2b_surpass_run.py"), "--live",
             "--c14-receipt", blocked_path],
            capture_output=True, text=True, env=env_auth, timeout=30,
        )
        out2 = r2.stdout or ""
        if r2.returncode != 2 or "LIVE_REFUSED" not in out2 or "C14 receipt did not vet PASS" not in out2:
            fail.append(f"live C14-gate refusal: expected exit 2 + LIVE_REFUSED naming the C14 vet failure, "
                        f"got exit={r2.returncode} stdout={out2!r}")
        elif "loading" in out2.lower() or "load_owned_core" in out2.lower():
            fail.append(f"live C14-gate refusal: refusal message suggests a model-load line was reached: {out2!r}")
        else:
            print("  [selftest] --live --c14-receipt <BLOCKED> w/ EMBER_GATE_AUTHORIZED=1 -> "
                  "LIVE_REFUSED (C14 gate), zero model touch  PASS")


def _selftest_write_or_diagnose_defensive(fail: list) -> None:
    with tempfile.TemporaryDirectory(prefix="ember-e2b-surpass-selftest-dirty-") as td:
        proto_ref = _write_fixture_protocol(td, "20260101T000000Z")
        dirty = _fixture_surpass(proto_ref, "2026-01-01T00:01:00Z")
        dirty["some_note"] = "this is invalid_single_leg_surpass shaped, never real evidence"
        receipts_dir = os.path.join(td, "receipts")
        path, ok, probe_line = write_or_diagnose(dirty, receipts_dir)
        if ok or "invalid-token" not in probe_line:
            fail.append(f"write_or_diagnose defensive test: expected pre-write abort on invalid token, "
                        f"got ok={ok} probe_line={probe_line!r}")
        elif os.path.basename(str(path)).startswith("ember-e2b-surpass-"):
            fail.append(f"write_or_diagnose defensive test: a RESOLVED-looking file was left behind: {path}")
        else:
            print(f"  [selftest] write_or_diagnose(dirty candidate) -> aborted pre-write, no RESOLVED file left  PASS")


def _selftest_adapter_file_load(fail: list) -> None:
    """New coverage for the checkpoint-contract gap: resolve_c14_checkpoint()
    and load_owned_core_from_c14_checkpoint() now accept a bare adapter .pt
    FILE (ember_c14_owned_run.py::_persist_resident_adapter's actual output
    shape), not only a merged-checkpoint DIRECTORY. Everything here is pure
    CPU and uses only the TINY build_toy_adapter() (TinyPolicyTransformer)
    -- never the real ~466M-param cbase-v0 seed, never receipts/. The
    mechanics under test (_load_and_verify_adapter_file, resolve_c14_
    checkpoint's isdir-or-.pt-file branch) are generic over any
    resident_adapter.LoRAAdapter instance, so the toy adapter exercises the
    identical code path the real owned-core adapter goes through."""
    import torch
    from resident_adapter import build_toy_adapter
    from ember_c14_owned_run import _sha256_file

    def _trained_toy_adapter(rank: int = 4, seed: int = 0):
        torch.manual_seed(seed)
        a = build_toy_adapter(rank=rank)
        # Give lora_B a real nonzero value -- mirrors what a completed iGRPO
        # step leaves behind (resident_adapter.py's own __main__ selftest
        # already proves optimizer.step() moves these same two tensors);
        # this file does not need to re-run iGRPO just to get a
        # deterministic nonzero fixture.
        with torch.no_grad():
            a.lora.lora_B.copy_(torch.randn_like(a.lora.lora_B) * 0.1)
        return a

    # (a) genuine round-trip: save a trained-shaped fixture, load it into a
    # FRESH adapter, assert param-hash change AND forward-output difference
    # on a probe input.
    with tempfile.TemporaryDirectory(prefix="ember-e2b-surpass-selftest-adapterfile-") as td:
        trained = _trained_toy_adapter()
        ckpt_path = os.path.join(td, "resident-adapter-selftest.pt")
        torch.save(trained.adapter_state_dict(), ckpt_path)
        sha = _sha256_file(Path(ckpt_path))

        probe_input = torch.randint(0, 10, (1, 3))
        fresh = build_toy_adapter(rank=4)
        with torch.no_grad():
            pre_load_output = fresh(probe_input).clone()

        facts = _load_and_verify_adapter_file(fresh, ckpt_path, sha)

        with torch.no_grad():
            post_load_output = fresh(probe_input)

        if facts["param_hash_before_load"] == facts["param_hash_after_load"]:
            fail.append("adapter-file round-trip: param hash did not change after load")
        elif torch.allclose(pre_load_output, post_load_output):
            fail.append("adapter-file round-trip: forward output identical before/after adapter load")
        else:
            delta = (post_load_output - pre_load_output).abs().max().item()
            print(f"  [selftest] adapter-file round-trip: param hash changed, "
                  f"forward output differs (max abs delta={delta:.4f})  PASS")

    # (b) sha256-mismatch refusal -- wrong hash given, file's real bytes untouched.
    with tempfile.TemporaryDirectory(prefix="ember-e2b-surpass-selftest-adaptersha-") as td:
        victim = _trained_toy_adapter(seed=1)
        ckpt_path = os.path.join(td, "resident-adapter-selftest.pt")
        torch.save(victim.adapter_state_dict(), ckpt_path)
        target = build_toy_adapter(rank=4)
        try:
            _load_and_verify_adapter_file(target, ckpt_path, "0" * 64)
            fail.append("sha256-mismatch refusal: expected C14_ADAPTER_SHA256_MISMATCH, no exception raised")
        except RuntimeError as exc:
            if "C14_ADAPTER_SHA256_MISMATCH" not in str(exc):
                fail.append(f"sha256-mismatch refusal: wrong exception: {exc}")
            else:
                print("  [selftest] adapter-file sha256 mismatch -> C14_ADAPTER_SHA256_MISMATCH refused  PASS")

    # (c) zero-delta refusal (negative control -- lora_B left at LoRALayer.
    # __init__'s default of all-zero, i.e. a never-trained adapter).
    with tempfile.TemporaryDirectory(prefix="ember-e2b-surpass-selftest-adapterzero-") as td:
        untrained = build_toy_adapter(rank=4)  # lora_B all-zero at init, untouched
        ckpt_path = os.path.join(td, "resident-adapter-selftest.pt")
        torch.save(untrained.adapter_state_dict(), ckpt_path)
        sha = _sha256_file(Path(ckpt_path))
        target = build_toy_adapter(rank=4)
        try:
            _load_and_verify_adapter_file(target, ckpt_path, sha)
            fail.append(
                "zero-delta refusal: expected C14_ADAPTER_ZERO_DELTA or "
                "C14_ADAPTER_LOAD_NOOP, no exception raised"
            )
        except RuntimeError as exc:
            if "C14_ADAPTER_ZERO_DELTA" not in str(exc) and "C14_ADAPTER_LOAD_NOOP" not in str(exc):
                fail.append(f"zero-delta refusal: wrong exception: {exc}")
            else:
                print(f"  [selftest] all-zero lora_B adapter file -> refused ({str(exc)[:70]}...)  PASS")

    # (d) resolve_c14_checkpoint() now accepts a FILE ending .pt, not only a directory.
    with tempfile.TemporaryDirectory(prefix="ember-e2b-surpass-selftest-resolvefile-") as td:
        fixture = _trained_toy_adapter(seed=2)
        ckpt_path = os.path.join(td, "resident-adapter-selftest.pt")
        torch.save(fixture.adapter_state_dict(), ckpt_path)
        sha = _sha256_file(Path(ckpt_path))
        c14_data = {
            "resident_training_candidate": {
                "resident_checkpoint_path": ckpt_path,
                "resident_checkpoint_sha256": sha,
            }
        }
        ok, detail, ckpt_abs, ckpt_sha = resolve_c14_checkpoint(
            c14_data, os.path.join(td, "fake-c14-receipt.json")
        )
        if not ok or ckpt_abs != ckpt_path or ckpt_sha != sha:
            fail.append(
                f"resolve_c14_checkpoint file-shape: expected ok+matching path/sha, "
                f"got ok={ok} detail={detail!r}"
            )
        else:
            print(f"  [selftest] resolve_c14_checkpoint() accepts a bare adapter .pt FILE "
                  f"-> {detail[:80]}  PASS")

        # directory shape must still work UNCHANGED (regression guard).
        ok_dir, detail_dir, ckpt_abs_dir, _ = resolve_c14_checkpoint(
            {"resident_training_candidate": {
                "resident_checkpoint_path": td,  # td itself is a directory
                "resident_checkpoint_sha256": sha,
            }},
            os.path.join(td, "fake-c14-receipt.json"),
        )
        if not ok_dir or ckpt_abs_dir != td:
            fail.append(
                f"resolve_c14_checkpoint directory-shape regression: expected ok+matching "
                f"dir, got ok={ok_dir} detail={detail_dir!r}"
            )
        else:
            print(f"  [selftest] resolve_c14_checkpoint() directory shape unchanged "
                  f"-> {detail_dir[:80]}  PASS")

    # (e) build_fp16_adapter's target-layer premise -- MEASURED, not assumed.
    # An earlier draft of this contract claimed LoRA is never injected at
    # the tied embed/head layer. Empirically that is false (see this
    # function's own probe below and load_owned_core_from_c14_checkpoint's
    # docstring CORRECTION paragraph). This does not threaten adapter-file
    # loading's safety -- lora_A/lora_B are a disjoint submodule regardless
    # of target -- so this check is informational, never a failure either way.
    try:
        from resident_adapter import build_fp16_adapter

        probe_adapter = build_fp16_adapter(live=False)
        shell = probe_adapter.base
        target_mod = dict(shell.named_modules())[probe_adapter._target_layer_name]
        embed_weight = shell._ember_model.embed_tokens.weight
        target_is_tied_head = target_mod.weight.data_ptr() == embed_weight.data_ptr()
        print(
            f"  [selftest] build_fp16_adapter target={probe_adapter._target_layer_name!r} "
            f"is_tied_embed_head={target_is_tied_head} (measured, informational -- "
            "adapter-file loading's safety does not depend on this either way)"
        )
    except Exception as exc:  # noqa: BLE001
        fail.append(f"build_fp16_adapter target-layer probe raised unexpectedly: {exc}")


def selftest() -> int:
    fail: list = []
    print("[selftest] (a) synthetic-fixture round trips through the REAL test_c_e2b.py...")
    _selftest_probe_roundtrips(fail)
    print("[selftest] (b) vet_c14_receipt() unit tests (negative + positive control)...")
    _selftest_c14_vet_unit(fail)
    print("[selftest] (c) --live refusal proofs (subprocess, zero model/torch touch)...")
    _selftest_live_refusals(fail)
    print("[selftest] (d) write_or_diagnose() invalid-token defensive test...")
    _selftest_write_or_diagnose_defensive(fail)
    print("[selftest] (e) adapter-file checkpoint-contract coverage (round-trip, "
          "sha-mismatch refusal, zero-delta refusal, resolve_c14_checkpoint shapes)...")
    _selftest_adapter_file_load(fail)

    if fail:
        for f in fail:
            print(f"SELFTEST FAIL: {f}")
        print(f"E2B_SURPASS_SELFTEST_FAIL ({len(fail)} failure(s))")
        return 1
    print("E2B_SURPASS_SELFTEST_PASS")
    return 0


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--selftest", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")

    ap.add_argument("--c14-receipt", type=str, default=None,
                     help="path to a resident-training-gate receipt to vet as the C14-cleared "
                          "authorization + checkpoint-lineage source")
    ap.add_argument("--n-tasks", type=int, default=8, help="ember_work leg: number of C14 tasks")
    ap.add_argument("--n-episodes", type=int, default=20, help="founder_likeness leg: number of nck episodes")
    ap.add_argument("--max-new-tokens", type=int, default=16,
                     help="founder_likeness leg generation budget (both arms)")
    ap.add_argument("--corpus-seed", type=int, default=20260702)
    ap.add_argument("--heldout-size", type=int, default=3)
    ap.add_argument("--lora-rank", type=int, default=8)
    ap.add_argument("--continuation-window-s", type=float, default=300.0,
                     help="founder_likeness leg 3 unprompted-continuation window "
                          "(frozen protocol value 300; issue #48 v1.1 clause 2)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.dry_run:
        return cmd_dry_run(args)
    if args.live:
        return cmd_live(args)
    ap.error("one of --selftest / --dry-run / --live is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
