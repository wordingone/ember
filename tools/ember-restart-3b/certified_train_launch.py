# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Any, NamedTuple


# A certificate that carries closure_sha256 binds the TRAINING DEPENDENCY
# CLOSURE (scripts/training_closure.py) instead of the whole repository tip, so
# a merge outside the closure no longer invalidates a pending launch.
# public_master_sha stays the VERIFIED-AT commit either way. Certificates minted
# before this field existed keep whole-tip equality.
#
# CERTIFICATE_KEYS and OPTIONAL_CERTIFICATE_KEYS are the key template the
# out-of-repo mint producer reads (it already exec-loads this module), so
# producer and consumer cannot skew.
CLOSURE_MODULE_RELATIVE_PATH = "scripts/training_closure.py"
# Guard-floor keys (issue #1410): the remote guard's receipt_check requires
# ticket/ts/sha_convention on any receipt carrying sha256 fields, and authority
# leg 4 requires goal_id/next_executed_outcome on committed artifacts. They are
# ACCEPTED as validated optional keys -- each shape-checked below, and any key
# outside this enumeration still hard-fails -- so a minted triple can be born
# guard-compliant instead of riding frozen-receipt exceptions. Presence of any
# guard-floor key marks a post-#1410 certificate, which must carry a RELATIVE
# completion_receipt_path (resolved against the certificate's own directory
# inside the custody root) so no absolute local path is baked into the
# sha-cited payload.
GUARD_FLOOR_CERTIFICATE_KEYS = {
    "ticket",
    "ts",
    "sha_convention",
    "goal_id",
    "next_executed_outcome",
}
OPTIONAL_CERTIFICATE_KEYS = {"closure_sha256"} | GUARD_FLOOR_CERTIFICATE_KEYS
CERTIFICATE_KEYS = {
    "schema_version",
    "event_kind",
    "declared_by_role",
    "declared_at_utc",
    "superseded_by",
    "completion_receipt_path",
    "completion_receipt_sha256",
    "public_master_sha",
    "checkout_sha256",
    "config_sha256",
    "tokenizer_sha256",
    "input_authority_sha256",
    "cli_binary_sha256",
    "launch_packet_sha256",
    "board_receipt_sha256",
    "benchmark_registry_sha256",
    "failure_class_ledger_sha256",
    "subject_manifest_sha256",
    "seat_sha256",
    "root_summary_sha256",
    "declaration_conjuncts",
    "execution_scope",
}
CERTIFICATE_SHA256_KEYS = {
    "completion_receipt_sha256",
    "checkout_sha256",
    "config_sha256",
    "tokenizer_sha256",
    "input_authority_sha256",
    "cli_binary_sha256",
    "launch_packet_sha256",
    "board_receipt_sha256",
    "benchmark_registry_sha256",
    "failure_class_ledger_sha256",
    "subject_manifest_sha256",
    "seat_sha256",
    "root_summary_sha256",
}
DECLARATION_CONJUNCT_KEYS = {
    "record_coherent",
    "nine_leg_completion",
    "birth_failure_classes_disposed",
}
LEDGER_ROW_KEYS = {
    "schema_version",
    "event_kind",
    "declared_by_role",
    "certificate_sha256",
}
RUN_SPEC_KEYS = {
    "schema_version",
    "certificate_sha256",
    "run_id",
    "seed",
    "runner_receipt",
    "requested_scope",
}
# Pin-freshness evidence (issue #1419) rides the RUN SPEC, not the certificate:
# the certificate is a frozen sha-cited payload minted at verification time,
# while this receipt must be newer than it (it proves the closure is still
# intact at the tip being launched from). The run spec is the launch-time
# document -- it already names the runner receipt -- so it is the only place a
# per-launch artifact can be named without re-minting. Optional-key handling
# mirrors OPTIONAL_CERTIFICATE_KEYS: anything outside the enumeration still
# hard-fails.
# Resume plumbing (issue #1425) rides the RUN SPEC for the same reason the
# pin-freshness receipt does: which checkpoint a rung resumes from is a
# launch-time decision, while the certificate is a frozen sha-cited payload.
# The runner already accepts these flags; without them a resumed rung simply
# cannot be expressed through the certified path, which pushes operators onto
# the uncertified one. Evidence keys mirror the runner's mutually exclusive
# group -- exactly one, never zero, never two.
# WHICH checkpoint may be resumed from is a certificate decision, not a run-spec
# one (issue #1426): these keys are validated for COHERENCE here and for
# AUTHORIZATION against the certificate's allowed_resume_roots.
RESUME_EVIDENCE_RUN_SPEC_FLAGS = {
    "resume_counter_receipt": "--resume-counter-receipt",
    "resume_realization_registry": "--resume-realization-registry",
    "resume_optimizer_transition_registry": "--resume-optimizer-transition-registry",
}
RESUME_RUN_SPEC_KEYS = {
    "resume_checkpoint",
    "resume_optimizer_transition_registry_sha256",
} | set(RESUME_EVIDENCE_RUN_SPEC_FLAGS)
# Specialist routing (issue #1430) rides the RUN SPEC for the same reason the
# resume triple does: which admitted training-data manifest and capability a
# rung trains is a launch-time decision, while the certificate is a frozen
# sha-cited payload. The pair is required together -- a manifest with no
# declared capability cannot be scope-checked, and a capability with no
# manifest names no data.
SPECIALIST_RUN_SPEC_KEYS = {"training_data_manifest", "training_capability"}
# The runner's own "specialist" subcommand (run_vertical_slice.py) additionally
# REQUIRES a checkpoint publication cadence, a write budget, a telemetry sink,
# and a model-chat cooldown floor before it will start -- none of which has an
# existing certificate- or run-spec-bound source the way seed/artifact_root/
# max_records/write_budget_bytes already do for governed-vertical. These ride
# the run spec too, required only alongside the pair above. write-budget-gib is
# NOT one of these: it is derived from the already-authorized
# requested_scope.write_budget_bytes (see _validate_specialist_request) rather
# than declared a second time, so a specialist launch cannot claim a larger
# write budget than governed-vertical's own certificate-authorized ceiling.
SPECIALIST_LAUNCH_RUN_SPEC_KEYS = {
    "training_checkpoint_interval",
    "training_telemetry_path",
    "training_model_chat_restore_not_before",
}
TRAINING_DATA_MANIFEST_SCHEMA = "ember-owned-training-data-v1"
TRAINING_CAPABILITIES = {"image", "audio", "reasoning", "tool"}
# Mirrors production_rung.py::TOKENIZER_RELATIVE / launch_packet.py's
# identity-manifest preflight / serve_owned_openai.py's _TRACKED_TOKENIZER_SOURCE
# -- the one frozen tokenizer this tree trains and serves against. Not a
# run-spec key: an operator-declared tokenizer path would let a specialist
# launch train against different token identity than every other consumer of
# this same tree without the certificate ever noticing.
SPECIALIST_TOKENIZER_RELATIVE_PATH = "tokenizer/tokenizer.json"
OPTIONAL_RUN_SPEC_KEYS = (
    {"training_verify_receipt_path"}
    | RESUME_RUN_SPEC_KEYS
    | SPECIALIST_RUN_SPEC_KEYS
    | SPECIALIST_LAUNCH_RUN_SPEC_KEYS
)
CHECKPOINT_MANIFEST_NAME = "checkpoint-manifest.json"
CONFIG_RELATIVE_PATH = "configs/ember-restart-3b.json"
CHECKPOINT_QUARANTINE_COMPONENT = ".checkpoint-quarantine"
AUTHORIZED_SCOPE_KEYS = {
    "purpose",
    "allowed_modes",
    "max_optimizer_steps",
    "max_records",
    "max_active_expert_families",
    "max_gpu_vram_gib",
    "max_transient_checkpoint_gib",
    "max_wall_minutes",
    "max_b_write_gib",
    "max_c_write_gib",
    "max_write_budget_bytes",
    "allowed_artifact_roots",
    "allowed_custody_roots",
    "model_server_allowed",
    "wsl_allowed",
    "persistent_worker_allowed",
}
# Resume-root authorization (issue #1426) and training-capability authorization
# (issue #1430) are both declared one level DOWN from the certificate's
# top-level key template, so the exact-match problem #1410 solved for
# CERTIFICATE_KEYS recurs here: AUTHORIZED_SCOPE_KEYS is compared for equality,
# so a certificate carrying either new key would be refused outright without
# this subtraction. Same closed-enumeration discipline as
# OPTIONAL_CERTIFICATE_KEYS -- a scope key outside these two sets still
# hard-fails, so the mechanism cannot be used to smuggle an unvalidated key in.
# resume_relocation_custody_root (issue #1452) rides the SAME mechanism: which
# checkpoint may be resumed from is already a certificate decision here, and
# the C: custody root the disk-budget runner relocated it under is exactly
# that same kind of decision, for the same reason -- the launcher must never
# derive it locally (from the checkpoint's own parents or any local default).
OPTIONAL_AUTHORIZED_SCOPE_KEYS = {
    "allowed_resume_roots",
    "allowed_training_capabilities",
    "resume_relocation_custody_root",
}
REQUESTED_SCOPE_KEYS = {
    "mode",
    "optimizer_steps",
    "max_records",
    "active_expert_families",
    "gpu_vram_gib",
    "transient_checkpoint_gib",
    "wall_minutes",
    "max_b_write_gib",
    "max_c_write_gib",
    "write_budget_bytes",
    "artifact_root",
    "custody_root",
}
# Mirrors the EXACT emission of scripts/verify_ember01_completion.py (the
# producer is the source of truth): top-level goal_id is the ACTIVE goal
# ("EMBER-02"); the EMBER-01 subject binding is completion_subject_goal_id.
COMPLETION_RECEIPT_KEYS = {
    "schema",
    "ok",
    "verified_at_utc",
    "goal_id",
    "completion_subject_goal_id",
    "workstream_id",
    "next_executed_outcome",
    "certificate_legs",
    "leg_detail",
    "leg_summary",
    "claim_scope",
    "checkout",
    "selection",
    "authority_certificate",
}
# scripts/verify_ember01_completion.py RESOLVED_TRUE -- lowercase-hyphen form.
COMPLETION_LEG_RESOLVED_TRUE = "resolved-true"

# Mirrors the receipt runtime/ember-lab/src/training_verify.rs::run assembles.
TRAINING_VERIFY_RECEIPT_SCHEMA = "ember-lab-training-verify-receipt-v1"
TRAINING_VERIFY_RECEIPT_KEYS = {
    "schema_version",
    "ok",
    "root",
    "started_at_ms",
    "finished_at_ms",
    "duration_ms",
    "closure",
    "input_identity",
    "model_tokenizer",
    "certificate",
    "checks",
    "ember_lab_binary_sha256",
    "ember_lab_source_sha256",
}


class ValidatedLaunch(NamedTuple):
    certificate_sha256: str
    run_spec_sha256: str
    public_master_sha: str
    closure_sha256: str | None
    artifact_root: pathlib.Path
    custody_root: pathlib.Path
    runner_receipt: pathlib.Path
    seed: int
    write_budget_bytes: int
    max_records: int
    max_c_write_gib: float
    max_b_write_gib: float
    # Resume plumbing is absent on a clean-genesis launch, and a launch that
    # carries none of these builds byte-identical argv to a pre-#1425 one.
    resume_checkpoint: pathlib.Path | None = None
    resume_evidence_flag: str | None = None
    resume_evidence_path: pathlib.Path | None = None
    resume_optimizer_transition_registry_sha256: str | None = None
    # Set only when the authorized resume_checkpoint resolves off B: (issue
    # #1452). This is the SINGLE predicate the governed-vertical route's
    # relocation refusal and the specialist tail's flag emission both read --
    # neither re-derives "does this resume need relocation" independently, so
    # the two cannot drift apart. A B: resume leaves this None and
    # build_runner_argv emits no relocation flags, byte-identical to a
    # pre-#1452 launch.
    resume_relocation_custody_root: pathlib.Path | None = None
    # Specialist routing is absent on a governed-vertical launch, and a launch
    # that carries none of these builds byte-identical argv to a pre-#1430 one.
    # specialist_capability is the field build_runner_argv reads to decide
    # which runner subcommand to emit.
    specialist_data_manifest: pathlib.Path | None = None
    specialist_capability: str | None = None
    specialist_tokenizer_path: pathlib.Path | None = None
    specialist_parent_manifest: pathlib.Path | None = None
    specialist_root_manifest: pathlib.Path | None = None
    specialist_checkpoint_interval: int | None = None
    specialist_write_budget_gib: int | None = None
    specialist_telemetry_path: pathlib.Path | None = None
    specialist_telemetry_run_id: str | None = None
    specialist_model_chat_restore_not_before: str | None = None


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: pathlib.Path, label: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError(f"{label} is unreadable") from error


def _require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} schema keys mismatch")


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value.lower() != value
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"{label} must be a lowercase SHA-256") from error
    return value


def _require_git_sha(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or value.lower() != value
    ):
        raise ValueError(f"{label} must be a lowercase 40-hex Git object ID")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(
            f"{label} must be a lowercase 40-hex Git object ID"
        ) from error
    return value


def _load_json(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable or invalid JSON") from error
    return _require_object(value, label)


def _load_ledger(path: pathlib.Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ValueError("declaration ledger is unreadable") from error
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = _require_object(
                json.loads(line), f"declaration ledger row {index}"
            )
        except json.JSONDecodeError as error:
            raise ValueError(
                f"declaration ledger row {index} is invalid JSON"
            ) from error
        _require_keys(row, LEDGER_ROW_KEYS, f"declaration ledger row {index}")
        if row["schema_version"] != "ember-spine-declaration-ledger-row-v1":
            raise ValueError("declaration ledger row schema")
        if row["event_kind"] != "SPINE_CERTIFIED":
            raise ValueError("declaration ledger event")
        if row["declared_by_role"] != "EMBER_CERTIFICATE_AUTHORITY":
            raise ValueError("declaration ledger role")
        _require_sha256(
            row["certificate_sha256"],
            f"declaration ledger row {index} certificate_sha256",
        )
        rows.append(row)
    return rows


def load_closure_module(repo_root: pathlib.Path):
    """Load the single closure implementation out of the tree being launched."""

    module_path = pathlib.Path(repo_root) / CLOSURE_MODULE_RELATIVE_PATH
    specification = importlib.util.spec_from_file_location(
        "ember_training_closure", module_path
    )
    if specification is None or specification.loader is None:
        raise ValueError("training dependency closure module cannot be loaded")
    module = importlib.util.module_from_spec(specification)
    try:
        specification.loader.exec_module(module)
    except OSError as error:
        raise ValueError("training dependency closure module is unreadable") from error
    return module


def read_live_closure_sha256(repo_root: pathlib.Path) -> str:
    """Recompute the training closure from LIVE TREE BYTES, boundary included.

    Not a format check. The declared closure is re-audited against the live
    import/exec graph first -- a stale manifest is the shape that would let
    unverified code train under a green certificate -- and only then are the
    member bytes re-hashed. CI runs this same function; it is the mechanism,
    not a mirror of one.
    """

    repo_root = pathlib.Path(repo_root)
    closure = load_closure_module(repo_root)
    try:
        manifest = closure.load_manifest(repo_root)
        audit = closure.audit_closure(repo_root, manifest)
    except ValueError as error:
        raise ValueError(f"training dependency closure is unusable: {error}") from error
    if not audit.ok:
        raise ValueError(
            "live training dependency closure fails its own boundary guard:\n"
            + audit.failure_report()
        )
    return _require_sha256(
        closure.compute_closure_hash(repo_root, manifest),
        "live training dependency closure hash",
    )


def read_pin_is_ancestor(repo_root: pathlib.Path, pin: str) -> bool:
    """Whether the certificate's verified-at commit is an ancestor of live HEAD.

    Closure equality alone would accept a tree that never contained the
    verified commit; this keeps the launch on the same history.
    """

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "merge-base",
            "--is-ancestor",
            pin,
            "HEAD",
        ],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    return result.returncode == 0


def read_commit_is_ancestor(
    repo_root: pathlib.Path, ancestor: str, descendant: str
) -> bool:
    """Whether `ancestor` is reachable from `descendant` in the local history.

    Fails CLOSED by raising: a `git` that is missing, or that cannot resolve
    either commit, yields no evidence of ancestry, and "no evidence" must never
    read as "related". Distinguished from `read_pin_is_ancestor`, which answers
    the different question (pin vs live HEAD) and tolerates a silent no.
    """

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "merge-base",
                "--is-ancestor",
                ancestor,
                descendant,
            ],
            check=False,
            capture_output=True,
            text=True,
            shell=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except OSError as error:
        raise ValueError(
            "git is unavailable, so completion-head ancestry cannot be proven"
        ) from error
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise ValueError(
        "completion-head ancestry is unprovable in this repository "
        f"({ancestor[:12]} vs {descendant[:12]})"
    )


def read_current_master(repo_root: pathlib.Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        raise ValueError("current public master is unreadable")
    return _require_git_sha(result.stdout.strip(), "current public master")


def _validate_completion_receipt(
    value: dict[str, Any], public_master_sha: str, repo_root: pathlib.Path
) -> bool:
    """Validate the EMBER-01 completion receipt; return whether its head IS the pin.

    EMBER-01 completion is a HISTORICAL fact, established once at the commit the
    census actually ran against. Demanding that commit EQUAL a newly minted
    certificate's `public_master_sha` made every new pin require a fresh
    whole-repo census -- re-importing the exact freeze #1400 removed from the
    launch path (issue #1419). The receipt is therefore validated at its OWN
    recorded head, which must be an ANCESTOR of the pin (equality still passes:
    a commit is an ancestor of itself). Ancestry alone is not freshness, so the
    caller requires a training-verify receipt whenever the head is strictly
    behind the pin.
    """

    _require_keys(value, COMPLETION_RECEIPT_KEYS, "completion receipt")
    if value["schema"] != "ember-01-completion-receipt-v1" or value["ok"] is not True:
        raise ValueError("completion receipt is not a successful EMBER-01 receipt")

    legs = _require_object(value["certificate_legs"], "completion certificate legs")
    expected_legs = {str(index) for index in range(1, 10)}
    if set(legs) != expected_legs or any(
        state != COMPLETION_LEG_RESOLVED_TRUE for state in legs.values()
    ):
        raise ValueError("completion receipt must contain exactly nine resolved-true legs")

    checkout = _require_object(value["checkout"], "completion checkout")
    checkout_head = _require_git_sha(
        checkout.get("head"), "completion checkout head"
    )
    head_is_pin = checkout_head == public_master_sha
    if not head_is_pin and not read_commit_is_ancestor(
        repo_root, checkout_head, public_master_sha
    ):
        raise ValueError(
            "completion checkout head is not an ancestor of declared public master"
        )
    if not (
        checkout.get("clean") is True
        and checkout.get("detached") is True
        and checkout.get("head_unchanged") is True
    ):
        raise ValueError("completion checkout integrity")

    if value["completion_subject_goal_id"] != "EMBER-01":
        raise ValueError("completion subject is not EMBER-01")
    selection = _require_object(value["selection"], "completion selection")
    if selection.get("unchanged_during_verification") is not True:
        raise ValueError("completion selection integrity")
    return head_is_pin


def _validate_training_verify_receipt(
    receipt_path: pathlib.Path,
    repo_root: pathlib.Path,
    certificate_closure_sha256: str,
) -> None:
    """Pin-freshness evidence: the #1400/#1418 training-scoped verify receipt.

    Freshness is proven STRUCTURALLY, never by a clock: the receipt's closure
    hash must equal the certificate's, which the caller has already equated to
    the closure recomputed from live tree bytes. A receipt taken before any
    closure-touching merge therefore cannot pass, and a receipt from a different
    checkout is refused outright by the root binding.
    """

    receipt = _load_json(receipt_path, "training verify receipt")
    _require_keys(
        receipt, TRAINING_VERIFY_RECEIPT_KEYS, "training verify receipt"
    )
    if receipt["schema_version"] != TRAINING_VERIFY_RECEIPT_SCHEMA:
        raise ValueError("training verify receipt schema")
    if receipt["ok"] is not True:
        raise ValueError("training verify receipt is not green")

    receipt_root = receipt["root"]
    if not isinstance(receipt_root, str) or not receipt_root:
        raise ValueError("training verify receipt root must be a non-empty string")
    if pathlib.Path(receipt_root).resolve(strict=False) != repo_root.resolve(
        strict=False
    ):
        raise ValueError(
            "training verify receipt was produced against a different tree"
        )

    closure = _require_object(receipt["closure"], "training verify closure")
    receipt_closure_sha256 = _require_sha256(
        closure.get("closure_sha256"), "training verify closure_sha256"
    )
    if receipt_closure_sha256 != certificate_closure_sha256:
        raise ValueError(
            "training verify receipt does not bind the certificate's training "
            "dependency closure"
        )

    checks = receipt["checks"]
    if not isinstance(checks, list) or not checks:
        raise ValueError("training verify receipt carries no checks")
    for index, check in enumerate(checks, start=1):
        check = _require_object(check, f"training verify check {index}")
        if check.get("ok") is not True:
            raise ValueError(
                "training verify check is red: "
                f"{check.get('name', f'check {index}')}"
            )


class ResumeRequest(NamedTuple):
    checkpoint: pathlib.Path
    evidence_flag: str
    evidence_path: pathlib.Path
    optimizer_transition_registry_sha256: str | None
    relocation_custody_root: pathlib.Path | None


def _reject_quarantined_resume_path(path: pathlib.Path, label: str) -> None:
    """Refuse a quarantined checkpoint lexically AND after resolution.

    Mirrors run_vertical_slice._reject_quarantined_checkpoint_path: quarantine
    is a directory-name convention, so a symlink or junction that resolves INTO
    quarantine must fail even though its lexical form is clean.
    """

    for candidate in (path, path.resolve(strict=False)):
        if any(
            str(part).casefold() == CHECKPOINT_QUARANTINE_COMPONENT
            for part in candidate.parts
        ):
            raise ValueError(
                f"run spec {label} names a quarantined checkpoint, which is "
                "not selectable"
            )


def _require_resume_string(value: object, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"run spec {key} must be a non-empty string")
    return value


def _authorized_resume_roots(
    authorized: dict[str, Any]
) -> list[pathlib.Path] | None:
    """The certificate's declared resume roots, resolved; None when undeclared.

    An ALLOWLIST, deliberately not a containment rule: cross-run resume is the
    point of the feature (an R1->R2 rung resumes from a PRIOR run's custody), so
    "must sit inside this run's custody_root" would refuse the primary use case.
    The producer that authors the run spec also mints the certificate, so it
    names the prior run's root at mint time -- the same producer/consumer split
    allowed_artifact_roots already runs on.

    Absent (None) and empty ([]) both authorize nothing; they are distinguished
    only in the refusal message, because "your certificate predates #1426, re-
    mint it" and "this certificate deliberately authorizes no resume" are
    different operator actions.
    """

    declared = authorized.get("allowed_resume_roots")
    if declared is None:
        return None
    if not isinstance(declared, list) or not all(
        isinstance(item, str) and item for item in declared
    ):
        raise ValueError(
            "certificate allowed_resume_roots must be a list of non-empty "
            "strings"
        )
    return [pathlib.Path(item).resolve(strict=False) for item in declared]


def _authorized_resume_relocation_custody_root(
    authorized: dict[str, Any]
) -> pathlib.Path | None:
    """The certificate's declared C: relocation custody root, resolved.

    Issue #1452: run_vertical_slice.authorize_production_resume_checkpoint
    accepts a resume checkpoint that resolves off B: only when the runner is
    also told c_relocated_under_disk_budget_runner=True with a
    relocation_custody_root -- the disk-budget runner relocates custody
    material off C: under pressure, and the escape hatch exists for exactly
    that case. WHICH root is the certificate's call for the same reason
    allowed_resume_roots is: naming it is authorizing it, so it belongs here
    and never in something the launcher derives from the checkpoint path
    itself (its parents, a default, anything else on local disk).

    None when undeclared; _validate_resume_request is the one that decides
    whether that absence is fatal (only when the authorized checkpoint
    actually resolves off B:). Must be absolute: a relative declaration
    would resolve against THIS PROCESS's own cwd (below), which is exactly
    the "derive it locally" shape the module doctrine above refuses -- a
    conspiring cwd could otherwise make an unauthorized root validate.
    """

    declared = authorized.get("resume_relocation_custody_root")
    if declared is None:
        return None
    if not isinstance(declared, str) or not declared:
        raise ValueError(
            "certificate resume_relocation_custody_root must be a non-empty "
            "string"
        )
    if not pathlib.Path(declared).is_absolute():
        raise ValueError(
            "certificate resume_relocation_custody_root must be an absolute "
            "path (a relative one would resolve against this process's own "
            "cwd, not a certificate-fixed location)"
        )
    return pathlib.Path(declared).resolve(strict=False)


def _require_authorized_resume_path(
    path: pathlib.Path,
    label: str,
    allowed_roots: list[pathlib.Path] | None,
) -> None:
    """Refuse a resume path the certificate never authorized.

    Decided on the RESOLVED form, never the lexical one: the probe that found
    this defect (issue #1426) named `<custody>/../outside-custody`, which reads
    as "inside custody" lexically and resolves outside it -- and the resolved
    form is what the runner will actually open. Roots are resolved on the same
    terms so a linked root still compares.
    """

    if allowed_roots is None:
        raise ValueError(
            f"certificate declares no allowed_resume_roots, so run spec {label} "
            "is unauthorized (re-mint the certificate to launch a resumed rung)"
        )
    resolved = path.resolve(strict=False)
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise ValueError(f"run scope exceeds certificate: {label}")


def _validate_resume_request(
    run_spec: dict[str, Any],
    run_spec_path: pathlib.Path,
    repo_root: pathlib.Path,
    allowed_resume_roots: list[pathlib.Path] | None,
    relocation_custody_root: pathlib.Path | None,
) -> ResumeRequest | None:
    """Validate the optional resume triple, fail-closed, before any argv exists.

    Returns None when the run spec declares no resume at all -- the clean-genesis
    shape, which must stay exactly as it was, and the only shape a certificate
    without allowed_resume_roots can still launch. A partially declared resume is
    never "close enough": a checkpoint without evidence would train from weights
    whose realization was never proven, and evidence without a checkpoint names
    nothing.

    Authorization is settled BEFORE the paths are opened, so an unauthorized
    checkpoint is refused without this process reading a byte of it. Quarantine
    is settled earlier still: it is a property of the path itself, so a
    quarantined checkpoint stays unselectable even under a certificate that
    would have authorized its root.
    """

    present = {
        key for key in RESUME_RUN_SPEC_KEYS if run_spec.get(key) is not None
    }
    if not present:
        return None

    evidence_present = sorted(present & set(RESUME_EVIDENCE_RUN_SPEC_FLAGS))
    if "resume_checkpoint" not in present:
        raise ValueError(
            "run spec resume evidence requires resume_checkpoint"
        )
    if len(evidence_present) != 1:
        raise ValueError(
            "run spec resume_checkpoint requires exactly one resume evidence "
            "key, got " + (", ".join(evidence_present) or "none")
        )
    evidence_key = evidence_present[0]

    registry_sha256 = run_spec.get("resume_optimizer_transition_registry_sha256")
    if registry_sha256 is not None:
        if evidence_key != "resume_optimizer_transition_registry":
            raise ValueError(
                "run spec resume_optimizer_transition_registry_sha256 is only "
                "legal alongside resume_optimizer_transition_registry"
            )
        registry_sha256 = _require_sha256(
            registry_sha256,
            "run spec resume_optimizer_transition_registry_sha256",
        )

    checkpoint = pathlib.Path(
        _require_resume_string(run_spec["resume_checkpoint"], "resume_checkpoint")
    )
    evidence = pathlib.Path(
        _require_resume_string(run_spec[evidence_key], evidence_key)
    )
    _reject_quarantined_resume_path(checkpoint, "resume_checkpoint")
    _reject_quarantined_resume_path(evidence, evidence_key)
    if not checkpoint.is_absolute():
        checkpoint = run_spec_path.parent / checkpoint
    if not evidence.is_absolute():
        evidence = run_spec_path.parent / evidence
    _reject_quarantined_resume_path(checkpoint, "resume_checkpoint")
    _reject_quarantined_resume_path(evidence, evidence_key)

    # The evidence path is authorized on exactly the same basis as the
    # checkpoint. Authorizing only the checkpoint would let a certificate-named
    # checkpoint be admitted on realization evidence fetched from anywhere.
    _require_authorized_resume_path(
        checkpoint, "resume_checkpoint", allowed_resume_roots
    )
    _require_authorized_resume_path(evidence, evidence_key, allowed_resume_roots)

    # Issue #1452: authorize_production_resume_checkpoint (run_vertical_slice)
    # accepts this checkpoint only when it resolves under B:, or when the
    # runner is also told c_relocated_under_disk_budget_runner=True with a
    # relocation_custody_root. Settled here, on the same terms as the
    # authorization check just above (resolved form, before the path is
    # opened), so a certificate that cannot express the relocation is refused
    # before any argv exists -- not after the certificate is minted and the
    # runner subprocess is the one that discovers it.
    checkpoint_relocation_root: pathlib.Path | None = None
    resolved_checkpoint = checkpoint.resolve(strict=False)
    if resolved_checkpoint.drive.upper() != "B:":
        if relocation_custody_root is None:
            raise ValueError(
                "run spec resume_checkpoint resolves off B:, so the "
                "certificate must declare resume_relocation_custody_root "
                "(re-mint the certificate to authorize the C: relocation)"
            )
        if (
            relocation_custody_root.drive.upper() != "C:"
            or resolved_checkpoint.drive.upper() != "C:"
            or not resolved_checkpoint.is_relative_to(relocation_custody_root)
        ):
            raise ValueError(
                "certificate resume_relocation_custody_root does not contain "
                "the authorized resume_checkpoint"
            )
        checkpoint_relocation_root = relocation_custody_root

    if not checkpoint.is_dir():
        raise ValueError(
            "run spec resume_checkpoint must name an existing checkpoint directory"
        )
    manifest_path = checkpoint / CHECKPOINT_MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(
            "run spec resume_checkpoint carries no "
            f"{CHECKPOINT_MANIFEST_NAME}, so it is not a resumable checkpoint"
        )
    if not evidence.is_file():
        raise ValueError(f"run spec {evidence_key} must name an existing file")

    # Architecture agreement is the load-bearing check: resuming v1 weights into
    # a v2 architecture silently trains a model nobody verified.
    manifest = _load_json(manifest_path, "resume checkpoint manifest")
    config = _load_json(
        pathlib.Path(repo_root) / CONFIG_RELATIVE_PATH, "model config"
    )
    manifest_revision = manifest.get("architecture_revision")
    config_revision = config.get("architecture_revision")
    if not isinstance(config_revision, str) or not config_revision:
        raise ValueError("model config carries no architecture_revision")
    if manifest_revision != config_revision:
        raise ValueError(
            "resume checkpoint architecture_revision does not match this "
            f"tree's config ({manifest_revision!r} vs {config_revision!r})"
        )

    return ResumeRequest(
        checkpoint=checkpoint,
        evidence_flag=RESUME_EVIDENCE_RUN_SPEC_FLAGS[evidence_key],
        evidence_path=evidence,
        optimizer_transition_registry_sha256=registry_sha256,
        relocation_custody_root=checkpoint_relocation_root,
    )


class SpecialistRequest(NamedTuple):
    data_manifest: pathlib.Path
    capability: str
    tokenizer_path: pathlib.Path
    parent_manifest: pathlib.Path
    root_manifest: pathlib.Path
    checkpoint_interval: int
    write_budget_gib: int
    telemetry_path: pathlib.Path
    telemetry_run_id: str
    model_chat_restore_not_before: str


def _require_specialist_string(value: object, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"run spec {key} must be a non-empty string")
    return value


def _authorized_training_capabilities(
    authorized: dict[str, Any]
) -> set[str] | None:
    """The certificate's declared specialist capabilities; None when undeclared.

    Same absent-vs-empty split _authorized_resume_roots implements for resume
    (issue #1426), applied to specialist routing: a certificate minted before
    #1430 carries no allowed_training_capabilities at all, so it authorizes no
    specialist route -- an accept-when-absent default would leave every
    previously minted certificate (declared allowed_modes == ["governed-
    vertical"] and nothing else) a standing bypass, since build_runner_argv
    routes on run-spec content alone and never re-reads allowed_modes. A
    certificate that DOES declare the key but lists no capabilities is a
    different, deliberate statement -- still authorizes nothing, but
    distinguished in the refusal message because the two are different
    operator actions to cure.
    """

    declared = authorized.get("allowed_training_capabilities")
    if declared is None:
        return None
    if not isinstance(declared, list) or not all(
        isinstance(item, str) and item for item in declared
    ):
        raise ValueError(
            "certificate allowed_training_capabilities must be a list of "
            "non-empty strings"
        )
    return set(declared)


def _require_authorized_training_capability(
    capability: str, authorized_capabilities: set[str] | None
) -> None:
    if authorized_capabilities is None:
        raise ValueError(
            "certificate declares no allowed_training_capabilities, so run "
            "spec training_capability is unauthorized (re-mint the "
            "certificate to launch a specialist route)"
        )
    if capability not in authorized_capabilities:
        raise ValueError("run scope exceeds certificate: training_capability")


def _validate_specialist_request(
    run_spec: dict[str, Any],
    run_spec_path: pathlib.Path,
    repo_root: pathlib.Path,
    resume: ResumeRequest | None,
    write_budget_bytes: int,
    max_records: int,
    authorized_training_capabilities: set[str] | None,
) -> SpecialistRequest | None:
    """Validate the optional specialist route, fail-closed, before any argv exists.

    Returns None when the run spec declares no specialist route at all -- the
    governed-vertical shape, which must stay exactly as it was. training_data_
    manifest and training_capability are required together (mirrors
    _validate_resume_request: a partially declared route is never "close
    enough" -- a manifest with no declared capability cannot be scope-checked,
    and a capability with no manifest names no data). Once both are present,
    the runner's own "specialist" subcommand requires a checkpoint cadence, a
    telemetry sink, a model-chat cooldown floor, and a positive max_records
    before it will start, so those become required too -- and it requires an
    AUTHORIZED resume checkpoint (unlike governed-vertical, where resume is
    optional).
    """

    pair_present = {
        key for key in SPECIALIST_RUN_SPEC_KEYS if run_spec.get(key) is not None
    }
    companions_present = {
        key
        for key in SPECIALIST_LAUNCH_RUN_SPEC_KEYS
        if run_spec.get(key) is not None
    }
    if not pair_present and not companions_present:
        return None
    if len(pair_present) == 1:
        missing = sorted(SPECIALIST_RUN_SPEC_KEYS - pair_present)[0]
        raise ValueError(
            f"run spec specialist launch requires {missing}, which is absent"
        )
    if not pair_present:
        dangling = sorted(companions_present)[0]
        raise ValueError(
            f"run spec {dangling} requires training_data_manifest and "
            "training_capability"
        )
    missing_companions = sorted(SPECIALIST_LAUNCH_RUN_SPEC_KEYS - companions_present)
    if missing_companions:
        raise ValueError(
            "run spec specialist launch requires "
            f"{missing_companions[0]}, which is absent"
        )

    capability = _require_specialist_string(
        run_spec["training_capability"], "training_capability"
    )
    if capability not in TRAINING_CAPABILITIES:
        raise ValueError(
            "run spec training_capability must be one of "
            + ", ".join(sorted(TRAINING_CAPABILITIES))
        )
    # Authorized before anything named by the run spec is opened: the
    # certificate, not the run spec, decides which capabilities this launch
    # may train -- otherwise a certificate scoped to governed-vertical alone
    # (allowed_modes == ["governed-vertical"]) would still route to the
    # specialist runner on any capability the run spec names (issue #1430
    # review finding: routing read only run-spec content, never the
    # certificate's authorized mode).
    _require_authorized_training_capability(
        capability, authorized_training_capabilities
    )

    data_manifest = pathlib.Path(
        _require_specialist_string(
            run_spec["training_data_manifest"], "training_data_manifest"
        )
    )
    if not data_manifest.is_absolute():
        data_manifest = pathlib.Path(repo_root) / data_manifest
    # Authorize the manifest's LOCATION before this process reads a byte of
    # it -- same discipline _require_authorized_resume_path applies to resume
    # paths. Both the runner (run_vertical_slice.py::
    # load_verified_specialist_records: "root not in manifest.parents") and
    # the bundle producer (build_specialist_bundle.py::emit_bundle: "repo_root
    # not in output_root.parents") refuse any manifest that does not resolve
    # below repo_root, so a relative path resolved against run_spec_path.parent
    # (the custody root, which is by construction OUTSIDE the repo -- see
    # write_valid_bundle in the test fixtures) would build a perfect argv for a
    # launch the runner can never actually start. Resolve against repo_root,
    # matching tokenizer_path below, and refuse anything -- relative or
    # absolute -- that resolves outside it.
    resolved_repo_root = pathlib.Path(repo_root).resolve()
    # Rebind to the RESOLVED form here, once, so every downstream use --
    # _load_json below, SpecialistRequest.data_manifest, and the --data-
    # manifest argv build_runner_argv emits -- carries the authorized path,
    # not a syntactically-different-but-equivalent one (issue #1430 review
    # Defect F3: authorizing resolved_data_manifest while continuing to use
    # the unresolved data_manifest let a "manifests/../manifests/image.json"
    # spelling through unchanged -- benign only because the runner
    # re-resolves independently, the same "authorize A, use B" shape #1426
    # cured for resume paths).
    data_manifest = data_manifest.resolve(strict=False)
    if resolved_repo_root not in data_manifest.parents:
        raise ValueError(
            "run spec training_data_manifest must resolve below repo_root "
            "(the runner refuses to load a specialist manifest from anywhere "
            "else)"
        )
    manifest = _load_json(data_manifest, "training data manifest")
    if manifest.get("schema_version") != TRAINING_DATA_MANIFEST_SCHEMA:
        raise ValueError(
            "run spec training_data_manifest is not an "
            f"{TRAINING_DATA_MANIFEST_SCHEMA} manifest "
            f"(capability={capability!r})"
        )
    manifest_capability = manifest.get("capability")
    if manifest_capability != capability:
        raise ValueError(
            "run spec training_capability does not match the manifest's own "
            f"declared capability (declared={capability!r}, "
            f"manifest={manifest_capability!r})"
        )

    # The runner's specialist CLI makes --resume-checkpoint and its evidence a
    # REQUIRED (not optional) group -- unlike governed-vertical/vertical, a
    # specialist route always trains a resumed expert family, never a clean
    # genesis. Reject before any argv exists, same as every other specialist
    # precondition.
    if resume is None:
        raise ValueError(
            "run spec specialist launch requires an authorized resume "
            "checkpoint (resume_checkpoint plus exactly one resume evidence "
            "key)"
        )

    checkpoint_interval = run_spec["training_checkpoint_interval"]
    if (
        isinstance(checkpoint_interval, bool)
        or not isinstance(checkpoint_interval, int)
        or checkpoint_interval < 1
    ):
        raise ValueError(
            "run spec training_checkpoint_interval must be a positive integer"
        )

    # write-budget-gib is derived, not declared: see SPECIALIST_LAUNCH_RUN_SPEC_KEYS.
    # Refusing a non-exact GiB multiple keeps the derivation lossless -- a
    # floor-divided value would silently authorize LESS than the certificate
    # granted, which is a certificate the launch would then quietly disagree
    # with rather than one that fails closed.
    if write_budget_bytes % (1024**3) != 0:
        raise ValueError(
            "run spec requested_scope.write_budget_bytes must be an exact "
            "GiB multiple for a specialist launch (the runner's "
            "--write-budget-gib takes whole GiB)"
        )
    write_budget_gib = write_budget_bytes // (1024**3)
    if write_budget_gib < 1:
        raise ValueError(
            "run spec requested_scope.write_budget_bytes must authorize at "
            "least 1 GiB for a specialist launch"
        )

    # Issue #1430 delta review Finding A (LOW): _require_scope_subset only
    # floors requested_scope.max_records at >= 0 (it is a shared ceiling
    # check across every mode, governed-vertical included, and 0 is not
    # inherently invalid there). The specialist runner disagrees --
    # bind_specialist_execution_slice refuses a zero or negative slice
    # ("specialist execution slice max records must be positive") -- so a
    # certificate-and-scope-valid run spec with max_records=0 built
    # parse-perfect argv the runner then deterministically refused at
    # subprocess time. Specialist-only, checked here rather than tightened
    # in the shared comparator, so governed-vertical's own (already correct)
    # tolerance for 0 is untouched.
    if max_records < 1:
        raise ValueError(
            "run spec requested_scope.max_records must be at least 1 for a "
            "specialist launch (the runner refuses a zero or negative slice)"
        )

    # run_id doubles as --telemetry-run-id, which the runner bounds to 128
    # characters ("training telemetry run id is invalid"). The top-level
    # scalar-field check has already proved it is a non-empty string; this is
    # the specialist-only length bound the runner additionally enforces.
    run_id = run_spec["run_id"]
    if len(run_id) > 128:
        raise ValueError(
            "run spec run_id must be at most 128 characters for a specialist "
            "launch (the runner's --telemetry-run-id enforces this bound)"
        )

    telemetry_path = pathlib.Path(
        _require_specialist_string(
            run_spec["training_telemetry_path"], "training_telemetry_path"
        )
    )
    if not telemetry_path.is_absolute():
        telemetry_path = run_spec_path.parent / telemetry_path

    # No format check: neither real consumer ever parses this value.
    # run_vertical_slice.py only type-checks it as part of an all-or-none
    # telemetry group (telemetry_path/telemetry_run_id/model_chat_restore_
    # not_before together or not at all) and embeds it verbatim into a
    # telemetry JSON payload at three call sites ("restore_not_before":
    # model_chat_restore_not_before); ember-cli's telemetry-watch.ts only
    # type-checks it as a string, and telemetry-label.ts only string-
    # interpolates it into a display label -- Date.parse/new Date() never
    # touch it either. A format bound invented here would be a bound this
    # launcher does not own, the exact defect class the manifest-path fix
    # above cured (issue #1430 review Defect F1). It could not even be made
    # correct in general: this repo pins Python 3.10.11 (manifests/python-
    # environment-v1.json), whose datetime.fromisoformat predates "Z"-
    # designator support (CPython 3.11+), while "Z" is the house convention
    # at every real timestamp producer in this chain (mint_launch_authority.
    # py's strftime("...Z"), this runner's own telemetry writer's isoformat()
    # .replace("+00:00","Z"), launch_packet.py's strftime("...Z")) -- a naive
    # fromisoformat check refused the chain's own format outright. Non-
    # emptiness is the one bound this process does own, checked above by
    # _require_specialist_string.
    model_chat_restore_not_before = _require_specialist_string(
        run_spec["training_model_chat_restore_not_before"],
        "training_model_chat_restore_not_before",
    )

    tokenizer_path = pathlib.Path(repo_root) / SPECIALIST_TOKENIZER_RELATIVE_PATH
    if not tokenizer_path.is_file():
        raise ValueError(
            "run spec specialist launch requires the tree's canonical "
            f"{SPECIALIST_TOKENIZER_RELATIVE_PATH}"
        )

    # Single-hop scope (no chaining): the checkpoint being resumed is both the
    # immediate parent and the lineage root of this specialist generation.
    # _validate_resume_request has already proven this manifest exists, is
    # readable JSON, and matches this tree's architecture_revision -- reusing
    # it here (rather than accepting a separately declared run-spec path) means
    # a specialist launch's lineage always traces to the exact checkpoint whose
    # architecture was just verified, never to an operator-named substitute.
    parent_manifest = resume.checkpoint / CHECKPOINT_MANIFEST_NAME
    root_manifest = parent_manifest

    return SpecialistRequest(
        data_manifest=data_manifest,
        capability=capability,
        tokenizer_path=tokenizer_path,
        parent_manifest=parent_manifest,
        root_manifest=root_manifest,
        checkpoint_interval=checkpoint_interval,
        write_budget_gib=write_budget_gib,
        telemetry_path=telemetry_path,
        telemetry_run_id=run_id,
        model_chat_restore_not_before=model_chat_restore_not_before,
    )


def _require_scope_subset(
    requested: dict[str, Any], authorized: dict[str, Any]
) -> None:
    _require_keys(requested, REQUESTED_SCOPE_KEYS, "requested scope")
    if set(authorized) - OPTIONAL_AUTHORIZED_SCOPE_KEYS != AUTHORIZED_SCOPE_KEYS:
        raise ValueError("certificate execution scope schema keys mismatch")

    if authorized["purpose"] != "BOUNDED_CANARY":
        raise ValueError("certificate execution scope is not a bounded canary")
    if not (
        authorized["model_server_allowed"] is False
        and authorized["wsl_allowed"] is False
        and authorized["persistent_worker_allowed"] is False
    ):
        raise ValueError("certificate execution scope enables a forbidden runtime")

    allowed_modes = authorized["allowed_modes"]
    if (
        not isinstance(allowed_modes, list)
        or allowed_modes != ["governed-vertical"]
        or requested["mode"] not in allowed_modes
    ):
        raise ValueError("run scope exceeds certificate: mode")

    numeric_pairs = (
        ("optimizer_steps", "max_optimizer_steps"),
        ("max_records", "max_records"),
        ("active_expert_families", "max_active_expert_families"),
        ("gpu_vram_gib", "max_gpu_vram_gib"),
        ("transient_checkpoint_gib", "max_transient_checkpoint_gib"),
        ("wall_minutes", "max_wall_minutes"),
        ("max_b_write_gib", "max_b_write_gib"),
        ("max_c_write_gib", "max_c_write_gib"),
        ("write_budget_bytes", "max_write_budget_bytes"),
    )
    for requested_key, authorized_key in numeric_pairs:
        requested_value = requested[requested_key]
        authorized_value = authorized[authorized_key]
        if (
            isinstance(requested_value, bool)
            or not isinstance(requested_value, (int, float))
            or isinstance(authorized_value, bool)
            or not isinstance(authorized_value, (int, float))
            or requested_value < 0
            or requested_value > authorized_value
        ):
            raise ValueError(
                f"run scope exceeds certificate: {requested_key}"
            )

    root_pairs = (
        ("artifact_root", "allowed_artifact_roots"),
        ("custody_root", "allowed_custody_roots"),
    )
    for requested_key, allowed_key in root_pairs:
        allowed = authorized[allowed_key]
        if (
            not isinstance(allowed, list)
            or not all(isinstance(item, str) for item in allowed)
            or requested[requested_key] not in allowed
        ):
            raise ValueError(
                f"run scope exceeds certificate: {requested_key}"
            )


def validate_certified_request(
    repo_root: pathlib.Path,
    certificate_path: pathlib.Path,
    declaration_ledger_path: pathlib.Path,
    run_spec_path: pathlib.Path,
) -> ValidatedLaunch:
    repo_root = pathlib.Path(repo_root)
    certificate_path = pathlib.Path(certificate_path)
    declaration_ledger_path = pathlib.Path(declaration_ledger_path)
    run_spec_path = pathlib.Path(run_spec_path)

    certificate = _load_json(certificate_path, "certificate")
    if set(certificate) - OPTIONAL_CERTIFICATE_KEYS != CERTIFICATE_KEYS:
        raise ValueError("certificate schema keys mismatch")
    if certificate["schema_version"] != "ember-spine-certified-declaration-v1":
        raise ValueError("certificate schema")
    if certificate["event_kind"] != "SPINE_CERTIFIED":
        raise ValueError("declaration event")
    if certificate["declared_by_role"] != "EMBER_CERTIFICATE_AUTHORITY":
        raise ValueError("declaration role")
    if certificate["superseded_by"] is not None:
        raise ValueError("certificate is superseded")
    for key in CERTIFICATE_SHA256_KEYS:
        _require_sha256(certificate[key], f"certificate {key}")
    _require_git_sha(certificate["public_master_sha"], "certificate public_master_sha")
    guard_floor_present = GUARD_FLOOR_CERTIFICATE_KEYS & set(certificate)
    for key in sorted(guard_floor_present):
        value = certificate[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"certificate {key} must be a non-empty string")

    certificate_sha256 = _canonical_sha256(certificate)
    ledger_rows = _load_ledger(declaration_ledger_path)
    if not any(
        row["certificate_sha256"] == certificate_sha256 for row in ledger_rows
    ):
        raise ValueError("declaration ledger membership is missing")

    completion_receipt_path = certificate["completion_receipt_path"]
    if not isinstance(completion_receipt_path, str) or not completion_receipt_path:
        raise ValueError("certificate completion_receipt_path must be a non-empty string")
    completion_path = pathlib.Path(completion_receipt_path)
    if guard_floor_present:
        # Post-#1410 certificates: the path must be custody-portable. An
        # absolute local path baked into a sha-cited payload is unredactable
        # post-mint; a ".." segment would let the sha-cited payload reference
        # bytes outside the custody root.
        if completion_path.is_absolute():
            raise ValueError(
                "certificate completion_receipt_path must be relative to the "
                "certificate directory, not absolute"
            )
        if ".." in completion_path.parts:
            raise ValueError(
                "certificate completion_receipt_path must not traverse above "
                "the certificate directory"
            )
        # is_absolute() is False on Windows for anchored-but-incomplete paths:
        # "/M/ember/x.json" (drive-root-relative) and "C:x.json" (drive-relative)
        # both carry an anchor with no ".." part, so the two checks above admit
        # them. Neither is custody-portable -- what they name depends on the
        # drive the certificate happens to sit on.
        if completion_path.drive or completion_path.root:
            raise ValueError(
                "certificate completion_receipt_path must not name a drive or "
                "root anchor"
            )
        # Resolved backstop for anything the syntactic checks miss (a symlinked
        # segment, a differing drive letter).
        certificate_directory = certificate_path.parent.resolve()
        resolved = (certificate_path.parent / completion_path).resolve()
        if not resolved.is_relative_to(certificate_directory):
            raise ValueError(
                "certificate completion_receipt_path must resolve under the "
                "certificate directory"
            )
    if not completion_path.is_absolute():
        completion_path = certificate_path.parent / completion_path
    completion = _load_json(completion_path, "completion receipt")
    if _file_sha256(
        completion_path, "completion receipt"
    ) != certificate["completion_receipt_sha256"]:
        raise ValueError("completion receipt hash mismatch")
    completion_head_is_pin = _validate_completion_receipt(
        completion, certificate["public_master_sha"], repo_root
    )

    conjuncts = _require_object(
        certificate["declaration_conjuncts"], "declaration conjuncts"
    )
    _require_keys(conjuncts, DECLARATION_CONJUNCT_KEYS, "declaration conjuncts")
    if any(value is not True for value in conjuncts.values()):
        raise ValueError("B7 declaration conjunct is false")

    # Closure binding when the certificate carries one. public_master_sha stays
    # the VERIFIED-AT commit, and live-HEAD equality is replaced by exactly two
    # checks: the closure recomputed from live bytes equals the certificate's,
    # and the verified-at commit is an ancestor of live HEAD. So a docs-only
    # merge -- which cannot affect a training run -- no longer stalls one, while
    # "you train exactly the verified training code" is untouched: a changed
    # closure file still rejects, even at the pinned tip. Certificates minted
    # before closure_sha256 existed fall back to whole-tip equality.
    current_master = read_current_master(repo_root)
    certificate_closure_sha256 = certificate.get("closure_sha256")
    if certificate_closure_sha256 is None:
        if certificate["public_master_sha"] != current_master:
            raise ValueError("certificate does not bind current public master")
    else:
        _require_sha256(certificate_closure_sha256, "certificate closure_sha256")
        if read_live_closure_sha256(repo_root) != certificate_closure_sha256:
            raise ValueError(
                "certificate does not bind the live training dependency closure"
            )
        if not read_pin_is_ancestor(repo_root, certificate["public_master_sha"]):
            raise ValueError(
                "certificate verified-at commit is not an ancestor of current HEAD"
            )

    run_spec = _load_json(run_spec_path, "run spec")
    if set(run_spec) - OPTIONAL_RUN_SPEC_KEYS != RUN_SPEC_KEYS:
        raise ValueError("run spec schema keys mismatch")
    if run_spec["schema_version"] != "ember-certified-train-run-v1":
        raise ValueError("run spec schema")
    if run_spec["certificate_sha256"] != certificate_sha256:
        raise ValueError("run spec certificate hash mismatch")
    if (
        not isinstance(run_spec["run_id"], str)
        or not run_spec["run_id"]
        or not isinstance(run_spec["seed"], int)
        or isinstance(run_spec["seed"], bool)
        or not isinstance(run_spec["runner_receipt"], str)
        or not run_spec["runner_receipt"]
    ):
        raise ValueError("run spec scalar fields are invalid")

    # Ancestor-head completion receipts carry no evidence about the pin, so the
    # training-scoped verify receipt supplies it. An equal-head launch keeps the
    # pre-#1419 shape exactly: the census already ran at this very commit.
    training_verify_receipt_path = run_spec.get("training_verify_receipt_path")
    if training_verify_receipt_path is not None:
        if (
            not isinstance(training_verify_receipt_path, str)
            or not training_verify_receipt_path
        ):
            raise ValueError(
                "run spec training_verify_receipt_path must be a non-empty string"
            )
        if certificate_closure_sha256 is None:
            raise ValueError(
                "training verify receipt requires a closure-bound certificate"
            )
        training_path = pathlib.Path(training_verify_receipt_path)
        if not training_path.is_absolute():
            training_path = run_spec_path.parent / training_path
        _validate_training_verify_receipt(
            training_path, repo_root, certificate_closure_sha256
        )
    elif not completion_head_is_pin:
        raise ValueError(
            "completion receipt predates the declared public master, so the run "
            "spec must supply training_verify_receipt_path as pin-freshness "
            "evidence"
        )

    requested_scope = _require_object(
        run_spec["requested_scope"], "requested scope"
    )
    authorized_scope = _require_object(
        certificate["execution_scope"], "certificate execution scope"
    )
    # Scope first: the resume paths are authorized AGAINST this scope, so the
    # certificate's authority must be established and shape-checked before
    # anything is measured against it.
    _require_scope_subset(requested_scope, authorized_scope)

    resume = _validate_resume_request(
        run_spec,
        run_spec_path,
        repo_root,
        _authorized_resume_roots(authorized_scope),
        _authorized_resume_relocation_custody_root(authorized_scope),
    )

    # Issue #1430 delta review Finding A: _require_scope_subset above has
    # already proven requested_scope["max_records"] is a non-bool int-or-
    # float within the certificate's ceiling, but a fractional value (e.g.
    # 10.7) would still silently truncate at the int(...) cast below --
    # refused here instead, on both routes, rather than quietly authorizing
    # less than what the run spec actually asked for.
    requested_max_records = requested_scope["max_records"]
    if (
        isinstance(requested_max_records, float)
        and not requested_max_records.is_integer()
    ):
        raise ValueError(
            "run spec requested_scope.max_records must be an exact integer "
            "(a fractional value would be silently truncated)"
        )
    requested_max_records = int(requested_max_records)

    specialist = _validate_specialist_request(
        run_spec,
        run_spec_path,
        repo_root,
        resume,
        int(requested_scope["write_budget_bytes"]),
        requested_max_records,
        _authorized_training_capabilities(authorized_scope),
    )

    # Issue #1452 / #1462: route determination is now settled (specialist is
    # None exactly when this launch will take the governed-vertical tail in
    # build_runner_argv). ONE predicate decides "this resume needs the
    # relocation pair expressed" -- resume.relocation_custody_root is not
    # None -- and it is read here, not re-derived: the SAME value rides onto
    # ValidatedLaunch.resume_relocation_custody_root below and is what
    # build_runner_argv's specialist tail checks to emit the flags, so the
    # refusal below and the emission downstream cannot drift apart.
    # run_vertical_slice.py's governed-vertical subparser declares neither
    # --c-relocated-under-disk-budget-runner nor --relocation-custody-root,
    # and run_governed_vertical's own signature has no parameters to receive
    # them (issue #1462 tracks adding this capability) -- so emitting them
    # on that tail would not silently misbehave, it would build argv the
    # runner's argparse rejects outright. Refused here, before any argv
    # exists, rather than after the certificate is minted and the runner
    # subprocess is the one that discovers it.
    resume_requires_relocation_expression = (
        resume is not None and resume.relocation_custody_root is not None
    )
    if specialist is None and resume_requires_relocation_expression:
        raise ValueError(
            "governed-vertical route cannot express a relocated resume "
            "checkpoint: run_governed_vertical has no relocation parameters "
            "and the governed-vertical subparser declares neither "
            "--c-relocated-under-disk-budget-runner nor "
            "--relocation-custody-root (issue #1462 tracks adding this "
            "capability). Route this launch through the specialist path, or "
            "resume from a B: custody root, until then."
        )

    custody_root = pathlib.Path(requested_scope["custody_root"])
    runner_receipt = pathlib.Path(run_spec["runner_receipt"])
    try:
        runner_receipt.resolve(strict=False).relative_to(
            custody_root.resolve(strict=False)
        )
    except ValueError as error:
        raise ValueError(
            "run scope exceeds certificate: runner_receipt"
        ) from error
    if specialist is not None:
        # The runner's telemetry sink is a write disk_budget_runner must be
        # able to attribute, same reason runner_receipt is checked above: both
        # are paths the wrapped child process writes to, and disk_budget_runner
        # only ever authorizes writes under its declared --write-root roots.
        try:
            specialist.telemetry_path.resolve(strict=False).relative_to(
                custody_root.resolve(strict=False)
            )
        except ValueError as error:
            raise ValueError(
                "run scope exceeds certificate: training_telemetry_path"
            ) from error

    return ValidatedLaunch(
        certificate_sha256=certificate_sha256,
        run_spec_sha256=_file_sha256(run_spec_path, "run spec"),
        public_master_sha=current_master,
        closure_sha256=certificate_closure_sha256,
        artifact_root=pathlib.Path(requested_scope["artifact_root"]),
        custody_root=custody_root,
        runner_receipt=runner_receipt,
        seed=run_spec["seed"],
        write_budget_bytes=int(requested_scope["write_budget_bytes"]),
        max_records=requested_max_records,
        max_c_write_gib=float(requested_scope["max_c_write_gib"]),
        max_b_write_gib=float(requested_scope["max_b_write_gib"]),
        resume_checkpoint=None if resume is None else resume.checkpoint,
        resume_evidence_flag=None if resume is None else resume.evidence_flag,
        resume_evidence_path=None if resume is None else resume.evidence_path,
        resume_optimizer_transition_registry_sha256=(
            None if resume is None else resume.optimizer_transition_registry_sha256
        ),
        resume_relocation_custody_root=(
            None if resume is None else resume.relocation_custody_root
        ),
        specialist_data_manifest=None if specialist is None else specialist.data_manifest,
        specialist_capability=None if specialist is None else specialist.capability,
        specialist_tokenizer_path=None if specialist is None else specialist.tokenizer_path,
        specialist_parent_manifest=None if specialist is None else specialist.parent_manifest,
        specialist_root_manifest=None if specialist is None else specialist.root_manifest,
        specialist_checkpoint_interval=(
            None if specialist is None else specialist.checkpoint_interval
        ),
        specialist_write_budget_gib=(
            None if specialist is None else specialist.write_budget_gib
        ),
        specialist_telemetry_path=None if specialist is None else specialist.telemetry_path,
        specialist_telemetry_run_id=(
            None if specialist is None else specialist.telemetry_run_id
        ),
        specialist_model_chat_restore_not_before=(
            None if specialist is None else specialist.model_chat_restore_not_before
        ),
    )


def build_runner_argv(
    repo_root: pathlib.Path, launch: ValidatedLaunch
) -> list[str]:
    repo_root = pathlib.Path(repo_root)
    argv = [
        sys.executable,
        str(
            repo_root
            / "tools"
            / "ember-restart-3b"
            / "disk_budget_runner.py"
        ),
        "--max-c-write-gib",
        str(launch.max_c_write_gib),
        "--max-b-write-gib",
        str(launch.max_b_write_gib),
        "--receipt",
        str(launch.runner_receipt),
        "--write-root",
        f"custody={launch.custody_root}",
        "--write-root",
        f"artifacts={launch.artifact_root}",
        "--",
        sys.executable,
        str(
            repo_root
            / "tools"
            / "ember-restart-3b"
            / "run_vertical_slice.py"
        ),
    ]
    # A launch that declares no specialist route reaches only the
    # governed-vertical tail below, so its argv is byte-identical to a
    # pre-#1430 one. validate_certified_request has already proven a declared
    # route is complete and coherent -- the training_data_manifest/
    # training_capability pair, its required companions, and an authorized
    # resume checkpoint -- so no partial specialist argv can be emitted.
    if launch.specialist_capability is not None:
        argv += [
            "specialist",
            "--seed",
            str(launch.seed),
            "--artifact-root",
            str(launch.artifact_root),
            "--data-manifest",
            str(launch.specialist_data_manifest),
            "--tokenizer",
            str(launch.specialist_tokenizer_path),
            "--capability",
            launch.specialist_capability,
            "--resume-checkpoint",
            str(launch.resume_checkpoint),
            launch.resume_evidence_flag,
            str(launch.resume_evidence_path),
        ]
        if launch.resume_optimizer_transition_registry_sha256 is not None:
            argv += [
                "--resume-optimizer-transition-registry-sha256",
                launch.resume_optimizer_transition_registry_sha256,
            ]
        argv += [
            "--parent-manifest",
            str(launch.specialist_parent_manifest),
            "--root-manifest",
            str(launch.specialist_root_manifest),
            "--max-records",
            str(launch.max_records),
            "--checkpoint-interval",
            str(launch.specialist_checkpoint_interval),
            "--write-budget-gib",
            str(launch.specialist_write_budget_gib),
            "--telemetry-path",
            str(launch.specialist_telemetry_path),
            "--telemetry-run-id",
            launch.specialist_telemetry_run_id,
            "--model-chat-restore-not-before",
            launch.specialist_model_chat_restore_not_before,
        ]
        # Issue #1452 / #1462: validate_certified_request has already proven
        # (fail-closed, before this argv exists) that a resume_checkpoint off
        # B: carries a certificate-declared relocation_custody_root -- and,
        # since the #1452/#1454 compose, that the governed-vertical route
        # (the only OTHER route a launch could have taken) is refused
        # outright whenever this value is set, because it cannot express
        # relocation (issue #1462). So the specialist tail is the only argv
        # this process ever builds when a resume is relocated. The value
        # emitted here IS the certificate value -- never derived from
        # launch.resume_checkpoint or anything else local -- so a specialist
        # launch resuming from B: stays byte-identical to one with no
        # relocation involved.
        if launch.resume_relocation_custody_root is not None:
            argv += [
                "--c-relocated-under-disk-budget-runner",
                "--relocation-custody-root",
                str(launch.resume_relocation_custody_root),
            ]
        return argv

    argv += [
        "governed-vertical",
        "--seed",
        str(launch.seed),
        "--artifact-root",
        str(launch.artifact_root),
        "--write-budget-bytes",
        str(launch.write_budget_bytes),
        "--max-records",
        str(launch.max_records),
    ]
    # A launch with no resume returns here, so its argv is byte-identical to a
    # pre-#1425 one. validate_certified_request has already proven the triple is
    # complete and coherent, so no partial suffix can be emitted.
    if launch.resume_checkpoint is not None:
        argv += [
            "--resume-checkpoint",
            str(launch.resume_checkpoint),
            launch.resume_evidence_flag,
            str(launch.resume_evidence_path),
        ]
        if launch.resume_optimizer_transition_registry_sha256 is not None:
            argv += [
                "--resume-optimizer-transition-registry-sha256",
                launch.resume_optimizer_transition_registry_sha256,
            ]
    # Issue #1452 / #1462: this tail can never carry the two relocation flags
    # -- validate_certified_request refuses fail-closed, before this function
    # is ever reached, whenever a governed-vertical launch's resume is
    # relocated (run_governed_vertical has neither the CLI flags nor the
    # Python parameters to receive them). Structurally absent here, not just
    # conditionally false, so a future edit to this tail cannot silently
    # re-ship the argparse crash #1452 exists to prevent.
    return argv


def _child_log_path(launch: ValidatedLaunch) -> pathlib.Path:
    """Log file the fixed runner's stdout+stderr are redirected to.

    Lives under custody_root (preserved, not devnulled) so the consumer's own
    stdout stays a single pure JSON line for the cockpit handshake. Named
    alongside the runner receipt so the two are trivially correlated.
    """
    return launch.custody_root / f"{launch.runner_receipt.stem}-child.log"


def _write_execution_receipt(
    launch: ValidatedLaunch,
    argv: list[str],
    exit_code: int,
    child_log_path: pathlib.Path | None = None,
    energy_sidecar: dict[str, Any] | None = None,
) -> pathlib.Path:
    receipt_path = _execution_receipt_path(launch)
    receipt = {
        "schema_version": "ember-certified-train-execution-v1",
        "certificate_sha256": launch.certificate_sha256,
        "run_spec_sha256": launch.run_spec_sha256,
        "public_master_sha": launch.public_master_sha,
        "closure_sha256": launch.closure_sha256,
        "argv": argv,
        "exit_code": exit_code,
        "artifact_root": str(launch.artifact_root),
        "runner_receipt": str(launch.runner_receipt),
        "child_log": str(child_log_path) if child_log_path is not None else None,
        "energy_sidecar": energy_sidecar,
        "claim_scope": {
            "capability_claimed": False,
            "admission_claimed": False,
            "sufficient_pretraining_claimed": False,
            "verified_expert_accretion_claimed": False,
            "competitiveness_claimed": False,
        },
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=receipt_path.parent,
        prefix=f".{receipt_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary_path = pathlib.Path(handle.name)
        handle.write(_canonical_bytes(receipt))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, receipt_path)
    return receipt_path


def _execution_receipt_path(launch: ValidatedLaunch) -> pathlib.Path:
    return launch.runner_receipt.with_name(
        f"{launch.runner_receipt.stem}-certified-launch.json"
    )


ENERGY_SIDECAR_BASELINE_WAIT_S = 120.0
ENERGY_SIDECAR_FINALIZE_WAIT_S = 60.0


def _start_energy_sidecar(
    repo_root: pathlib.Path, launch: ValidatedLaunch, child_env: dict[str, str]
) -> tuple[Any, pathlib.Path, dict[str, Any]]:
    """Spawn the R1-E5 energy sidecar (scripts/energy_proxy_logger.py
    --watch-pidfile) and hold until its idle baseline completes, so the
    baseline is measured with no Ember job resident. Every failure here is
    DISCLOSED and none is fatal: the sidecar exists to produce evidence, and
    an evidence producer must never be able to kill the certified run (the
    #1489 lesson, applied at spawn instead of at write). A run that ends up
    without an energy receipt fails R1-E5 at the battery -- fail-closed
    downstream, never fail-fatal here.

    Returns (process_or_None, pidfile_path, disclosure_dict).
    """
    receipt_path = launch.artifact_root / "energy-proxy-receipt.json"
    pidfile = launch.custody_root / "energy-sidecar.pid"
    sidecar_log = launch.custody_root / "energy-sidecar.log"
    marker = pathlib.Path(str(receipt_path) + ".baseline-done")
    disclosure: dict[str, Any] = {
        "spawned": False,
        "receipt_path": str(receipt_path),
        "pidfile": str(pidfile),
        "log": str(sidecar_log),
        "note": None,
    }
    logger_path = repo_root / "scripts" / "energy_proxy_logger.py"
    if not logger_path.is_file():
        disclosure["note"] = f"sidecar not spawned: {logger_path} missing"
        return None, pidfile, disclosure
    try:
        for stale in (pidfile, marker):
            if stale.exists():
                stale.unlink()
        launch.artifact_root.mkdir(parents=True, exist_ok=True)
        launch.custody_root.mkdir(parents=True, exist_ok=True)
        sidecar_log_handle = open(sidecar_log, "wb")
        process = subprocess.Popen(
            [sys.executable, "-B", str(logger_path),
             "--watch-pidfile", str(pidfile), "--receipt", str(receipt_path)],
            shell=False,
            cwd=repo_root,
            env=child_env,
            stdout=sidecar_log_handle,
            stderr=subprocess.STDOUT,
        )
    except Exception as error:
        disclosure["note"] = f"sidecar spawn failed: {error!r}"
        return None, pidfile, disclosure
    disclosure["spawned"] = True
    import time as _time
    waited = 0.0
    while not marker.exists():
        if process.poll() is not None:
            disclosure["note"] = (
                f"sidecar exited (code {process.returncode}) before its idle "
                "baseline completed; proceeding without energy capture"
            )
            return None, pidfile, disclosure
        if waited >= ENERGY_SIDECAR_BASELINE_WAIT_S:
            disclosure["note"] = (
                f"idle-baseline marker not seen within {ENERGY_SIDECAR_BASELINE_WAIT_S:.0f}s; "
                "child launched anyway -- the sidecar may still capture a late window"
            )
            return process, pidfile, disclosure
        _time.sleep(0.5)
        waited += 0.5
    disclosure["note"] = f"idle baseline completed in {waited:.1f}s"
    return process, pidfile, disclosure


def _finish_energy_sidecar(
    process: Any, pidfile: pathlib.Path, disclosure: dict[str, Any]
) -> None:
    """Close the measured window (delete the pidfile -- a file operation,
    never a signal) and give the sidecar a bounded interval to finalize its
    receipt. A sidecar that overruns is LEFT RUNNING and disclosed: its
    sampling loop has already ended with the window, its own exit is bounded
    by one counter read, and this launcher kills nothing it can avoid
    killing."""
    import time as _time
    try:
        if pidfile.exists():
            pidfile.unlink()
    except OSError as error:
        disclosure["note"] = (disclosure.get("note") or "") + f"; pidfile unlink failed: {error!r}"
    if process is None:
        return
    deadline = _time.monotonic() + ENERGY_SIDECAR_FINALIZE_WAIT_S
    while process.poll() is None and _time.monotonic() < deadline:
        _time.sleep(0.5)
    if process.poll() is None:
        disclosure["exit_code"] = None
        disclosure["note"] = (disclosure.get("note") or "") + (
            f"; sidecar still finalizing after {ENERGY_SIDECAR_FINALIZE_WAIT_S:.0f}s -- left "
            "running (its window is closed; it exits after one counter read)"
        )
    else:
        disclosure["exit_code"] = int(process.returncode)
    receipt = pathlib.Path(disclosure["receipt_path"])
    disclosure["receipt_written"] = receipt.is_file()


def execute_validated_launch(
    repo_root: pathlib.Path,
    launch: ValidatedLaunch,
    run_process=subprocess.run,
) -> int:
    repo_root = pathlib.Path(repo_root)
    argv = build_runner_argv(repo_root, launch)
    # argv is certificate-visible (an execution receipt pins argv[1] to the
    # fixed runner path) so bytecode suppression rides the spawn env instead
    # of an -B argv insertion, which would shift that pinned position.
    child_env = os.environ.copy()
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    # R1-E5 energy sidecar rides only REAL launches: an injected run_process
    # is a test double with no child process to meter, and metering a fake
    # would slow every launcher test by the idle-baseline interval. The
    # execution receipt discloses the skip either way, and the battery's E5
    # check refuses a run root with no energy receipt -- a stripped sidecar
    # cannot fake a frontier point, it can only fail one honestly later.
    sidecar_process = None
    sidecar_pidfile = None
    if run_process is subprocess.run:
        sidecar_process, sidecar_pidfile, sidecar_disclosure = _start_energy_sidecar(
            repo_root, launch, child_env
        )
    else:
        sidecar_disclosure = {
            "spawned": False,
            "note": "sidecar skipped: injected run_process (test double)",
        }
    # The child (disk_budget_runner -> run_vertical_slice) must NEVER inherit
    # this consumer's stdout: this process's own final line is the cockpit's
    # machine-readable handshake (main()'s json.dumps), and any training-log
    # noise interleaved ahead of it breaks JSON.parse on the whole stream
    # (issue #1408). Redirect the child's stdout+stderr to a log file under
    # custody_root instead -- preserved for debugging, never devnulled.
    child_log_path = _child_log_path(launch)
    child_log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if sidecar_pidfile is not None and sidecar_process is not None:
            try:
                # The pidfile's lifetime IS the sidecar's measured window; its
                # content (this launcher's pid) is only the crash backstop.
                sidecar_pidfile.write_text(str(os.getpid()), encoding="utf-8")
            except OSError as error:
                sidecar_disclosure["note"] = (sidecar_disclosure.get("note") or "") + (
                    f"; pidfile write failed: {error!r} -- window never opened"
                )
        with open(child_log_path, "wb") as child_log:
            result = run_process(
                argv,
                shell=False,
                check=False,
                cwd=repo_root,
                env=child_env,
                stdout=child_log,
                stderr=subprocess.STDOUT,
            )
        exit_code = int(result.returncode)
    finally:
        if sidecar_pidfile is not None:
            _finish_energy_sidecar(sidecar_process, sidecar_pidfile, sidecar_disclosure)
    _write_execution_receipt(
        launch, argv, exit_code, child_log_path=child_log_path,
        energy_sidecar=sidecar_disclosure,
    )
    return exit_code


def certify_and_execute(
    repo_root: pathlib.Path,
    certificate_path: pathlib.Path,
    declaration_ledger_path: pathlib.Path,
    run_spec_path: pathlib.Path,
    run_process=subprocess.run,
) -> int:
    launch = validate_certified_request(
        repo_root,
        certificate_path,
        declaration_ledger_path,
        run_spec_path,
    )
    return execute_validated_launch(repo_root, launch, run_process=run_process)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a declared Ember canary certificate and execute its fixed runner."
    )
    parser.add_argument("--root", required=True, type=pathlib.Path)
    parser.add_argument("--certificate", required=True, type=pathlib.Path)
    parser.add_argument(
        "--declaration-ledger", required=True, type=pathlib.Path
    )
    parser.add_argument("--run-spec", required=True, type=pathlib.Path)
    arguments = parser.parse_args(argv)
    try:
        launch = validate_certified_request(
            arguments.root,
            arguments.certificate,
            arguments.declaration_ledger,
            arguments.run_spec,
        )
        exit_code = execute_validated_launch(arguments.root, launch)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "outcome": "COMPLETED" if exit_code == 0 else "FAILED",
                "execution_receipt": str(_execution_receipt_path(launch)),
                "artifact_root": str(launch.artifact_root),
                "exit_code": exit_code,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
