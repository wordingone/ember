#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regenerate CONTINUITY.md's mutable status from the newest totality receipt.

Reads the newest ember-totality-*.json under a receipts-totality directory (lexicographic sort of
the ts-stamped filename == chronological order) and rewrites everything between the
<!-- BOARD-STATUS-BEGIN --> / <!-- BOARD-STATUS-END --> markers in CONTINUITY.md with: the receipt
id, its ts, counts by status, and a one-line legend. This makes a stale continuity count structurally
impossible for whatever receipt tree the script was pointed at -- the block can only ever say
what the newest receipt in THAT tree says.

**"Newest" is scoped to --data-root, not to the world.** By default this reads
scripts/ember_totality/receipts-totality/ under this repo -- the newest receipt COMMITTED to this
checkout. A board-run lane's live data tree (uncommitted local receipts, or a different working
copy) can genuinely hold a newer receipt than what's tracked here; that receipt is invisible to
this script until it (or a copy of it) lands under --data-root. The generated block's stamped
receipt id is the honest disclosure either way -- it never claims to be "current," only to match
the newest receipt the script could see.

Board-run playbook:
  - A board-run lane with a live data tree runs this against that tree BEFORE committing anything:
    `python src/ember/governance/scripts/gen_readme_status.py --data-root /path/to/live/receipts-totality --check`
    to see whether generated continuity status would change, then renders and reviews the diff.
  - Run this script as the last step of every totality board run against the tree that will
    actually be committed, so continuity never drifts from what ships in the same commit.
  - If continuity changes as a result, land it as its own docs PR through the normal stop-at-open
    review flow -- this script never commits or pushes on its own.

CLI:
  python src/ember/governance/scripts/gen_readme_status.py            # regenerate continuity from the in-repo tree
  python src/ember/governance/scripts/gen_readme_status.py --check     # exit 1 if generated status would change
  python src/ember/governance/scripts/gen_readme_status.py --check --generated-status
                                                  # deterministic merge-gate scope
  python src/ember/governance/scripts/gen_readme_status.py --data-root /path/to/receipts-totality
                                                  # point at a different (e.g. live/uncommitted)
                                                  # receipts-totality directory instead

Stdlib only. No network.
"""
import argparse
import glob
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[4])
GOVERNANCE_SCRIPTS = str(Path(__file__).resolve().parent)
for import_root in (GOVERNANCE_SCRIPTS, ROOT):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)
from selected_subject_architecture import (
    SCHEMA as SELECTED_SUBJECT_SCHEMA, BindingError, bounded_read,
    decode, lint_selected_architecture, load_subject, one,
)
from ember_totality import quarantine_sweep
from ember_totality import tree_provenance
from src.ember.governance.scripts.branch_inventory import (
    InventoryError as BranchInventoryError,
    check_inventory,
)

DEFAULT_DATA_ROOT = os.path.join(
    GOVERNANCE_SCRIPTS, "ember_totality", "receipts-totality"
)
README_PATH = os.path.join(ROOT, "README.md")
CONTINUITY_PATH = os.path.join(ROOT, "docs/domains/governance/authority/CONTINUITY.md")
CURRENT_SUBJECT_PATH = os.path.join(ROOT, "manifests", "ember-current-subject-v2.json")
BRANCH_INVENTORY_PATH = os.path.join(
    ROOT, "receipts", "branch-inventory", "branch-inventory-current.json"
)
BEGIN_MARKER = "<!-- BOARD-STATUS-BEGIN -->"
END_MARKER = "<!-- BOARD-STATUS-END -->"
SUBJECT_BEGIN_MARKER = "<!-- CURRENT-SUBJECT-BEGIN -->"
SUBJECT_END_MARKER = "<!-- CURRENT-SUBJECT-END -->"
ARCHITECTURE_BEGIN_MARKER = "<!-- CURRENT-ARCHITECTURE-BEGIN -->"
ARCHITECTURE_END_MARKER = "<!-- CURRENT-ARCHITECTURE-END -->"
CONTINUITY_STATUS_PATH = os.path.join(ROOT, "manifests", "ember-training-continuity-status-v1.json")
CONTINUITY_BEGIN_MARKER = "<!-- CONTINUITY-STATUS-BEGIN -->"
CONTINUITY_END_MARKER = "<!-- CONTINUITY-STATUS-END -->"
UNKNOWN_STATUS = "UNKNOWN"   # a live source that could not be read says so, with its reason (issue 2119 row 7)
CONTINUITY_SNAPSHOT_SCHEMA = "ember-training-continuity-snapshot-v1"
CONTINUITY_STATUS_SCHEMA = "ember-training-continuity-status-v2"  # training_continuity_status.STATUS_SCHEMA; a test compares the two
CONTINUITY_CANDIDATE_AUDIT_SCHEMA = "ember-lineage-candidate-audit-v1"  # lineage_candidate_audit.SCHEMA; a test compares the two
CONTINUITY_CANDIDATE_AUDIT_STATUSES = {"REFUSED_NOT_RETAINED", "UNRULED_NOT_RETAINED", "RETAINED_IN_CHAIN", "NO_CANDIDATE"}
CURRENT_SUBJECT_FIELDS = {
    "active_route",
    "capability_credit",
    "checkpoint_custody",
    "checkpoint_manifest_sha256",
    "disposition",
    "evidence_paths",
    "model_config_sha256",
    "optimizer_state_sha256",
    "parameters",
    "predecessor",
    "sufficient_pretraining_proven",
    "token_cursor",
    "tokenizer_sha256",
}
RECEIPT_TIMESTAMP_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")
STATE_AS_OF_PATTERN = re.compile(r"<!-- state-as-of: \d{4}-\d{2}-\d{2} -->")
# One glob for both selection and predecessor lookup: the chain check is only
# meaningful if it walks the exact ordering that picked the rendered receipt.
RECEIPT_GLOB = "ember-totality-*.json"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _receipt_datetime(ts):
    if not isinstance(ts, str) or RECEIPT_TIMESTAMP_PATTERN.fullmatch(ts) is None:
        raise ValueError("board receipt ts must be a YYYYMMDDTHHMMSSZ UTC timestamp")
    return datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def validate_receipt_freshness(ts, *, max_age_days, now=None):
    if isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or max_age_days < 0:
        raise ValueError("receipt max age must be a non-negative integer number of days")
    captured_at = _receipt_datetime(ts)
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("freshness clock must be timezone-aware")
    observed_at = observed_at.astimezone(timezone.utc)
    age_seconds = (observed_at - captured_at).total_seconds()
    if age_seconds < 0:
        raise ValueError("board receipt timestamp is in the future")
    age_days = int(age_seconds // 86400)
    if age_seconds > max_age_days * 86400:
        raise ValueError(
            f"board receipt is {age_days} days old; maximum is {max_age_days} days"
        )
    return captured_at


def bind_state_as_of(continuity, receipt_ts):
    captured_at = _receipt_datetime(receipt_ts)
    markers = STATE_AS_OF_PATTERN.findall(continuity)
    if len(markers) != 1:
        raise ValueError("CONTINUITY.md must contain exactly one state-as-of marker")
    marker = f"<!-- state-as-of: {captured_at.date().isoformat()} -->"
    return STATE_AS_OF_PATTERN.sub(marker, continuity, count=1)


def newest_receipt_path(data_root):
    findings = quarantine_sweep.discover_quarantines([("data-root", data_root)])
    if findings:
        paths = ", ".join(str(row["path"]) for row in findings)
        raise SystemExit(
            "gen_readme_status: refusing stale receipt fallback because exact "
            f"{quarantine_sweep.QUARANTINE_SUFFIX} file(s) exist: {paths}"
        )
    receipts_glob = os.path.join(data_root, RECEIPT_GLOB)
    paths = sorted(glob.glob(receipts_glob))
    if not paths:
        raise SystemExit(
            f"gen_readme_status: no ember-totality-*.json receipts found under {data_root}"
        )
    return paths[-1]


def receipt_chain_predecessor(receipt_path):
    """Immediate predecessor of receipt_path in selection order, or None if it is the first.

    Derived from the directory listing rather than from any path string inside the
    receipt, so a receipt cannot point the chain check at a file of its choosing.
    """
    directory = os.path.dirname(os.path.abspath(receipt_path))
    paths = sorted(glob.glob(os.path.join(directory, RECEIPT_GLOB)))
    target = os.path.abspath(receipt_path)
    for index, candidate in enumerate(paths):
        if os.path.abspath(candidate) == target:
            return paths[index - 1] if index else None
    return None


def verify_receipt_chain(receipt_path, receipt, *, allow_unchained=False):
    """Refuse to render unless the declared predecessor sha matches real predecessor bytes.

    The receipt's own chain_verification.chain_ok is deliberately not consulted: it is
    the subject's self-report, and the receipts carry a note conceding it could not be
    computed at write time. The verdict here comes only from bytes hashed on disk.
    """
    predecessor = receipt_chain_predecessor(receipt_path)
    declared = receipt.get("prev_totality_receipt_sha256")
    name = os.path.basename(str(receipt_path))
    if predecessor is None:
        if declared is not None and not allow_unchained:
            raise ValueError(
                f"board receipt {name} declares a predecessor sha but no earlier "
                "receipt exists beside it; pass --allow-unchained-receipt to render "
                "it as an unverifiable fragment"
            )
        return None
    if declared is None:
        if allow_unchained:
            return None
        raise ValueError(
            f"board receipt {name} omits prev_totality_receipt_sha256 while its "
            f"predecessor {os.path.basename(predecessor)} exists on disk; the chain "
            "cannot be verified"
        )
    if not isinstance(declared, str) or SHA256_PATTERN.fullmatch(declared) is None:
        raise ValueError(
            f"board receipt {name} prev_totality_receipt_sha256 must be lowercase SHA-256"
        )
    with open(predecessor, "rb") as stream:
        actual = hashlib.sha256(stream.read()).hexdigest()
    if actual != declared:
        raise ValueError(
            f"board receipt {name} chain is broken: it declares predecessor sha "
            f"{declared}, but the on-disk bytes of its immediate predecessor "
            f"{os.path.basename(predecessor)} hash to {actual}"
        )
    return predecessor


def render_block(
    receipt_path,
    *,
    allow_stale_tree=False,
    allow_unbound_tree=False,
    allow_unchained=False,
    repo_root=None,
    required_commits=(),
    receipt_max_age_days=None,
    now=None,
):
    with open(receipt_path, "r", encoding="utf-8") as f:
        receipt = json.load(f)
    tree_state = tree_provenance.validate_receipt_for_render(
        receipt,
        allow_stale_tree=allow_stale_tree,
        repo_root=repo_root,
        required_commits=required_commits,
    )
    receipt_id = os.path.splitext(os.path.basename(receipt_path))[0]
    ts = receipt.get("ts", "unknown")
    if receipt_max_age_days is not None:
        validate_receipt_freshness(ts, max_age_days=receipt_max_age_days, now=now)
    if tree_state is None and not allow_unbound_tree:
        # A stale/dirty tree already demands --allow-stale-tree. A receipt with no
        # run-tree binding at all is strictly less verifiable, so it cannot be the
        # more permissive case: refuse unless the matching opt-out is passed.
        raise ValueError(
            "README_TREE_REFUSED: board receipt carries no run-tree provenance; "
            "pass --allow-unbound-tree to render it as visibly marked archaeology"
        )
    verify_receipt_chain(receipt_path, receipt, allow_unchained=allow_unchained)
    summary = receipt.get("summary", {})
    green = summary.get("green", 0)
    red = summary.get("red", 0)
    unevaluable = summary.get("unevaluable", 0)
    audit_ok = summary.get("audit_ok", 0)
    audit_incident = summary.get("audit_incident", 0)
    audit_pending_epoch = summary.get("audit_pending_epoch", 0)
    total = summary.get(
        "total",
        green + red + unevaluable + audit_ok + audit_incident + audit_pending_epoch,
    )
    pct_green = summary.get("pct_green", 0.0)
    if tree_state is None:
        tree_line = "**Tree provenance:** `LEGACY_UNBOUND` (no run-tree binding in receipt)."
    else:
        display_status = tree_state.get("provenance_status", "UNKNOWN")
        if display_status == "STALE_DIRTY_OVERRIDE":
            display_status = "ARCHAEOLOGY_ONLY"
        tree_line = (
            f"**Tree provenance:** `{display_status}`; "
            f"run `{tree_state.get('run_tree_sha', 'unknown')}`; "
            f"remote master `{tree_state.get('remote_master_sha', 'unknown')}`; "
            f"tree_is_stale={str(tree_state.get('tree_is_stale') is True).lower()}; "
            f"tracked_dirty={len(tree_state.get('tree_dirty', []))}."
        )
    lines = [
        BEGIN_MARKER,
        "<!-- GENERATED by src/ember/governance/scripts/gen_readme_status.py -- do not hand-edit between the markers -->",
        f"**Board receipt:** `{receipt_id}` (ts `{ts}`).",
        "",
        tree_line,
        "",
        f"**Counts:** {green}-GREEN / {red}-RED / {unevaluable}-UNEVALUABLE / "
        f"{audit_ok}-AUDIT-OK / {audit_incident}-AUDIT-INCIDENT / "
        f"{audit_pending_epoch}-AUDIT-PENDING-EPOCH (total {total} rows, "
        f"{pct_green}% of state-conditions GREEN).",
        "",
        "**Legend:** GREEN = a fresh receipt satisfies the condition's CHK; RED = CHK unmet or a "
        "satisfying artifact is absent; UNEVALUABLE = the probe genuinely cannot look (counts as "
        "RED for completion math); AUDIT-OK/AUDIT-INCIDENT/AUDIT-PENDING-EPOCH = the three "
        "standing process-invariant rows (cadence-audit results, never a completion conjunct).",
        END_MARKER,
    ]
    return "\n".join(lines)


def _closed_hash(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"current subject {field} must be lowercase SHA-256")
    return value


def load_current_subject(path):
    with open(path, "r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "authority",
        "subject",
    }:
        raise ValueError("current subject root fields are not closed")
    if isinstance(payload, dict) and payload.get("schema_version") == SELECTED_SUBJECT_SCHEMA:
        return load_subject(Path(path).read_bytes())
    if payload.get("schema_version") != "ember-current-subject-v1":
        raise ValueError("current subject schema_version must be ember-current-subject-v1")
    authority = payload.get("authority")
    if not isinstance(authority, dict) or set(authority) != {
        "goal_id",
        "workstream_id",
        "next_executed_outcome",
    }:
        raise ValueError("current subject authority binding is not closed")
    if authority != {
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": (
            "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        ),
    }:
        raise ValueError("current subject authority binding is not current")
    subject = payload.get("subject")
    if not isinstance(subject, dict):
        raise ValueError("current subject payload is missing")
    if set(subject) != CURRENT_SUBJECT_FIELDS:
        raise ValueError("current subject fields are not closed")
    for field in (
        "checkpoint_manifest_sha256",
        "model_config_sha256",
        "tokenizer_sha256",
        "optimizer_state_sha256",
    ):
        _closed_hash(subject.get(field), field)
    cursor = subject.get("token_cursor")
    if not isinstance(cursor, dict) or set(cursor) != {
        "global_step",
        "record_index",
        "token_offset",
        "tokens_seen",
    }:
        raise ValueError("current subject token_cursor is not closed")
    if not all(isinstance(value, int) and value >= 0 for value in cursor.values()):
        raise ValueError("current subject token_cursor values must be nonnegative integers")
    parameters = subject.get("parameters")
    if not isinstance(parameters, dict) or set(parameters) != {
        "active",
        "allocated",
        "episode_trainable",
        "served",
        "trainable",
        "unique",
    }:
        raise ValueError("current subject parameter counts are not closed")
    if not all(isinstance(value, int) and value > 0 for value in parameters.values()):
        raise ValueError("current subject parameter counts must be positive integers")
    if not (
        parameters["active"] <= parameters["served"] <= parameters["allocated"]
        and parameters["episode_trainable"]
        <= parameters["trainable"]
        <= parameters["allocated"]
        and parameters["unique"] <= parameters["allocated"]
    ):
        raise ValueError("current subject parameter relationships are invalid")
    if not isinstance(subject.get("active_route"), str) or not subject["active_route"]:
        raise ValueError("current subject active_route must be non-empty")
    if subject.get("disposition") != "CHECKPOINT_CANDIDATE_NOT_ADMITTED":
        raise ValueError("current subject disposition exceeds the public evidence boundary")
    if subject.get("capability_credit") != "none":
        raise ValueError("current subject capability_credit exceeds the public evidence boundary")
    if subject.get("sufficient_pretraining_proven") is not False:
        raise ValueError("current subject cannot claim sufficient pretraining")
    predecessor = subject.get("predecessor")
    if not isinstance(predecessor, dict) or set(predecessor) != {
        "checkpoint_manifest_sha256",
        "relationship",
        "tokens_seen",
    }:
        raise ValueError("current subject predecessor is not closed")
    _closed_hash(
        predecessor.get("checkpoint_manifest_sha256"),
        "predecessor.checkpoint_manifest_sha256",
    )
    if (
        predecessor["checkpoint_manifest_sha256"]
        == subject["checkpoint_manifest_sha256"]
        or predecessor.get("relationship") != "historical_step1_predecessor"
        or not isinstance(predecessor.get("tokens_seen"), int)
        or predecessor["tokens_seen"] < 0
        or predecessor["tokens_seen"] >= cursor["tokens_seen"]
    ):
        raise ValueError("current subject predecessor relationship is invalid")
    custody = subject.get("checkpoint_custody")
    if not isinstance(custody, dict) or set(custody) != {
        "class",
        "locator_id",
        "public_manifest_bytes_present",
    }:
        raise ValueError("current subject checkpoint_custody is not closed")
    if (
        custody.get("class") != "private_checkpoint_bytes"
        or not isinstance(custody.get("locator_id"), str)
        or not custody["locator_id"]
        or custody.get("public_manifest_bytes_present") is not False
    ):
        raise ValueError("current subject checkpoint custody disclosure is invalid")
    evidence = subject.get("evidence_paths")
    if (
        not isinstance(evidence, list)
        or not evidence
        or evidence != sorted(evidence)
        or not all(
            isinstance(item, str)
            and item
            and not os.path.isabs(item)
            and not re.match(r"^[A-Za-z]:", item)
            for item in evidence
        )
    ):
        raise ValueError("current subject evidence_paths must be sorted repo-relative paths")
    return payload


def validate_current_subject_evidence(payload, root, selected_bindings=None):
    if payload["schema_version"] == SELECTED_SUBJECT_SCHEMA:
        bindings = selected_bindings or {}
        return lint_selected_architecture(
            json.dumps(payload, sort_keys=True).encode("utf-8"),
            bounded_read(one(bindings.get("pointer"), "selected_pointer"), "selected_pointer"),
            bounded_read(one(bindings.get("manifest"), "selected_manifest"), "selected_manifest"),
            one(bindings.get("pointer_sha256"), "approved_selected_pointer"),
        )
    root = Path(root).resolve()
    subject = payload["subject"]
    identity = {
        "checkpoint_manifest_sha256": subject["checkpoint_manifest_sha256"],
        "model_config_sha256": subject["model_config_sha256"],
        "tokenizer_sha256": subject["tokenizer_sha256"],
    }
    seen = set()
    for relative in subject["evidence_paths"]:
        candidate = (root / relative).resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError(f"current subject evidence path escapes root: {relative}")
        if not candidate.is_file():
            raise ValueError(f"current subject evidence path is missing: {relative}")
        if candidate.suffix.lower() != ".json":
            continue
        with open(candidate, "r", encoding="utf-8") as stream:
            evidence = json.load(stream)
        schema = evidence.get("schema_version") if isinstance(evidence, dict) else None
        if schema in {
            "ember-anchor-cost-calibration-certificate-v1",
            "ember-first-shared-raw-forward-v1",
            "ember-restart-execution-authorities-v1",
        } and (
            evidence.get("goal_id") != payload["authority"]["goal_id"]
            or evidence.get("next_executed_outcome")
            != payload["authority"]["next_executed_outcome"]
        ):
            raise ValueError(
                f"current subject conflicts with public evidence authority: {schema}"
            )
        if schema == "ember-first-shared-raw-forward-v1":
            stamps = evidence.get("identity_stamps", {})
            truth = evidence.get("truth_boundary", {})
            prompt = evidence.get("prompt", {})
            raw_identity = {
                "checkpoint_sha256": subject["checkpoint_manifest_sha256"],
                "model_config_sha256": subject["model_config_sha256"],
                "tokenizer_sha256": subject["tokenizer_sha256"],
            }
            if (
                any(stamps.get(field) != value for field, value in raw_identity.items())
                or truth.get("training_tokens_seen") != subject["token_cursor"]["tokens_seen"]
                or prompt.get("active_expert") != subject["active_route"]
            ):
                raise ValueError("current subject conflicts with public evidence: raw forward")
            seen.add(schema)
        elif schema == "ember-restart-execution-authorities-v1":
            authorities = evidence.get("authorities")
            if not isinstance(authorities, list) or not any(
                isinstance(row, dict)
                and all(row.get(field) == value for field, value in identity.items())
                for row in authorities
            ):
                raise ValueError(
                    "current subject conflicts with public evidence: execution registry"
                )
            seen.add(schema)
        elif schema == "ember-anchor-cost-calibration-certificate-v1":
            binding = evidence.get("receipt_binding", {})
            if any(binding.get(field) != value for field, value in identity.items()):
                raise ValueError(
                    "current subject conflicts with public evidence: cost certificate"
                )
            seen.add(schema)
    required = {
        "ember-anchor-cost-calibration-certificate-v1",
        "ember-first-shared-raw-forward-v1",
        "ember-restart-execution-authorities-v1",
    }
    if seen != required:
        raise ValueError(
            "current subject public evidence classes are incomplete: "
            + ", ".join(sorted(required - seen))
        )


def render_current_subject_block(payload, selected_result=None):
    if payload["schema_version"] == SELECTED_SUBJECT_SCHEMA:
        if selected_result is None:
            raise BindingError("MISSING_BINDING:selected_architecture_validation")
        subject = payload["subject"]
        return "\n".join([
            ARCHITECTURE_BEGIN_MARKER,
            "<!-- GENERATED by src/ember/governance/scripts/gen_readme_status.py from manifests/ember-current-subject-v2.json -->",
            f"**Canonical selected architecture:** {subject['architecture_revision']}.",
            "",
            f"- Selected checkpoint manifest SHA256: {subject['checkpoint_manifest_sha256']}.",
            f"- Verified selected pointer SHA256: {selected_result['selected_pointer_sha256']}.",
            "- This verifies selection and architecture identity only. Checkpoint qualification and capability credit remain undetermined.",
            ARCHITECTURE_END_MARKER,
        ])
    subject = payload["subject"]
    cursor = subject["token_cursor"]
    parameters = subject["parameters"]
    predecessor = subject["predecessor"]
    return "\n".join(
        [
            SUBJECT_BEGIN_MARKER,
            "<!-- GENERATED by src/ember/governance/scripts/gen_readme_status.py from manifests/ember-current-subject-v1.json -->",
            f"**Historical v2 checkpoint snapshot:** `{subject['checkpoint_manifest_sha256']}`.",
            "",
            f"- Disposition: `{subject['disposition']}`; capability credit: `{subject['capability_credit']}`; sufficient pretraining proven: `{str(subject['sufficient_pretraining_proven']).lower()}`.",
            f"- Config: `{subject['model_config_sha256']}`; tokenizer: `{subject['tokenizer_sha256']}`; optimizer state (custody-only, public bytes absent): `{subject['optimizer_state_sha256']}`.",
            f"- Cursor: step `{cursor['global_step']}`, record `{cursor['record_index']}`, token offset `{cursor['token_offset']}`, tokens seen `{cursor['tokens_seen']}`; active route: `{subject['active_route']}`.",
            f"- Parameters: `{parameters['unique']}` unique, `{parameters['trainable']}` trainable, `{parameters['served']}` served, `{parameters['active']}` active, `{parameters['episode_trainable']}` episode-trainable.",
            f"- Historical predecessor: `{predecessor['checkpoint_manifest_sha256']}` at `{predecessor['tokens_seen']}` tokens (`{predecessor['relationship']}`).",
            SUBJECT_END_MARKER,
        ]
    )


def _closed(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"continuity status {where} keys are not {sorted(keys)}")
    return value


def _nonneg_int(value, where):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"continuity status {where} must be a nonnegative integer")
    return value


def _digest_or_genesis(value, where):
    if value == "GENESIS":
        return value
    return _closed_hash(value, where)


def _text(value, where, *, nullable=False):
    if value is None and nullable:
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"continuity status {where} must be a non-empty string")
    return value


def _reject_nonfinite(token):
    raise ValueError(f"continuity snapshot carries a non-finite number ({token}); JSON NaN and Infinity are refused")


def _parse_finite_float(token):
    """An ordinary JSON literal such as 1e999 parses to infinity without ever reaching parse_constant."""
    value = float(token)
    if not math.isfinite(value):
        raise ValueError(f"continuity snapshot carries a non-finite number ({token}); it overflows to infinity")
    return value


def _private_path_strings(value, found=None):
    """Every string leaf that looks like a local filesystem path (drive letter or backslash)."""
    found = [] if found is None else found
    if isinstance(value, str):
        if "\\" in value or re.match(r"^[A-Za-z]:[/\\]", value):
            found.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            _private_path_strings(key, found)
            _private_path_strings(item, found)
    elif isinstance(value, list):
        for item in value:
            _private_path_strings(item, found)
    return found


def _check_candidate_audit(candidate_audit, head, lineage):
    if not isinstance(candidate_audit, dict) or candidate_audit.get("schema") != CONTINUITY_CANDIDATE_AUDIT_SCHEMA:
        raise ValueError(f"continuity snapshot candidate_audit schema must be {CONTINUITY_CANDIDATE_AUDIT_SCHEMA}")
    audit_status = candidate_audit.get("status")
    if audit_status not in CONTINUITY_CANDIDATE_AUDIT_STATUSES:
        raise ValueError(f"continuity snapshot candidate_audit.status {audit_status!r} is not one of {sorted(CONTINUITY_CANDIDATE_AUDIT_STATUSES)}")
    duplicate = candidate_audit.get("duplicate_credit")
    if not isinstance(duplicate, dict) or duplicate.get("each_hour_counted_once") is not True:
        raise ValueError("continuity snapshot candidate_audit must carry a passing duplicate_credit check")
    # the duplicate-credit tuple must reconcile with the selected lineage it audits: a true flag beside counts that disagree is not a check
    for name in ("distinct_manifests", "hops_checked", "summed_step_delta", "summed_token_delta"):
        value = duplicate.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"continuity snapshot candidate_audit duplicate_credit.{name} must be a non-negative integer")
    expected = {"distinct_manifests": lineage["depth"], "hops_checked": max(lineage["depth"] - 1, 0),
                "summed_step_delta": lineage["retained_global_steps"], "summed_token_delta": lineage["retained_applied_positions"]}
    for name, want in expected.items():
        if duplicate[name] != want:
            raise ValueError(f"continuity snapshot candidate_audit duplicate_credit.{name} {duplicate[name]} disagrees with the selected lineage ({want})")
    if audit_status != "NO_CANDIDATE":
        candidate = candidate_audit.get("candidate")
        retained = candidate_audit.get("retained")
        if not isinstance(candidate, dict) or not isinstance(retained, dict):
            raise ValueError("continuity snapshot candidate_audit needs candidate and retained sections")
        _closed_hash(candidate.get("manifest_sha256"), "candidate manifest_sha256")
        parent_is_head = candidate.get("parent_is_selected_head")
        if not isinstance(parent_is_head, bool) or parent_is_head != (candidate.get("parent_manifest_sha256") == head):
            raise ValueError("continuity snapshot candidate_audit parent_is_selected_head must be a boolean that matches the candidate parent and the selected head")
        in_chain = retained.get("candidate_in_retained_chain")
        credited = retained.get("positions_credited_to_lineage")
        if not isinstance(in_chain, bool):
            raise ValueError("continuity snapshot candidate_audit candidate_in_retained_chain must be a boolean")
        if isinstance(credited, bool) or not isinstance(credited, int) or credited < 0:
            raise ValueError("continuity snapshot candidate_audit positions_credited_to_lineage must be a non-negative integer")
        if (audit_status == "RETAINED_IN_CHAIN") != in_chain:
            raise ValueError("continuity snapshot candidate_audit status disagrees with candidate_in_retained_chain")
        if audit_status != "RETAINED_IN_CHAIN" and credited != 0:
            raise ValueError("continuity snapshot candidate_audit credits positions to a candidate that is not retained")
        if audit_status == "REFUSED_NOT_RETAINED":
            ruling = candidate_audit.get("refusal_ruling")
            if not isinstance(ruling, dict) or ruling.get("verdict") != "REFUTED":
                raise ValueError("continuity snapshot candidate_audit REFUSED_NOT_RETAINED needs a REFUTED ruling")
            _closed_hash(ruling.get("receipt_sha256"), "refusal receipt_sha256")


def load_continuity_status(path):
    """Closed load of the committed continuity snapshot: the training-continuity status dict plus when it was
    captured and the head it describes. Anything outside the closed key sets, a non-hex digest or a negative
    count refuses; the loader never repairs."""
    with open(path, "r", encoding="utf-8") as stream:
        payload = json.load(stream, parse_constant=_reject_nonfinite, parse_float=_parse_finite_float)
    _closed(payload, {"schema_version", "captured_at", "head_manifest_sha256", "status", "candidate_audit"}, "root")
    if payload["schema_version"] != CONTINUITY_SNAPSHOT_SCHEMA:
        raise ValueError(f"continuity snapshot schema_version must be {CONTINUITY_SNAPSHOT_SCHEMA}")
    if not isinstance(payload["captured_at"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["captured_at"]):
        raise ValueError("continuity snapshot captured_at must be YYYY-MM-DDTHH:MM:SSZ (UTC)")
    head = _digest_or_genesis(payload["head_manifest_sha256"], "head_manifest_sha256")
    status = _closed(payload["status"], {
        "schema", "lineage_checkpoint_manifest_sha256", "lineage", "claim_budget_eligible", "gpu_owner", "checkpoint",
        "learning_measurement", "purpose", "diagnostic_allowance", "next_segment"}, "status")
    if status["schema"] != CONTINUITY_STATUS_SCHEMA:
        raise ValueError(f"continuity status schema must be {CONTINUITY_STATUS_SCHEMA}")
    if _digest_or_genesis(status["lineage_checkpoint_manifest_sha256"], "lineage_checkpoint_manifest_sha256") != head:
        raise ValueError("continuity snapshot head differs from the status lineage checkpoint")
    lineage = status["lineage"]
    if isinstance(lineage, dict) and "genesis_manifest_sha256" in lineage:
        _closed(lineage, {"depth", "genesis_manifest_sha256", "retained_applied_positions", "retained_global_steps"}, "lineage")
        _closed_hash(lineage["genesis_manifest_sha256"], "lineage.genesis_manifest_sha256")
    else:
        _closed(lineage, {"depth", "retained_applied_positions", "retained_global_steps"}, "lineage")
    for name in ("depth", "retained_applied_positions", "retained_global_steps"):
        _nonneg_int(lineage[name], f"lineage.{name}")
    claim = status["claim_budget_eligible"]
    if not isinstance(claim, dict) or claim.get("status") not in {"UNDEFINED", "UNDETERMINED", "MEASURED"}:
        raise ValueError("continuity status claim_budget_eligible.status must be UNDEFINED, UNDETERMINED or MEASURED")
    if "accounting" in claim:
        # the status as `claim_budget_eligible_status` returns it under the approved frozen predicate: exact key set, never a free-form dict
        _closed(claim, {"status", "predicate_sha256", "accounting"}, "claim_budget_eligible")
        _closed_hash(claim["predicate_sha256"], "claim_budget_eligible.predicate_sha256")
        accounting = claim["accounting"]
        if not isinstance(accounting, dict) or accounting.get("head_segment_id") != head:
            raise ValueError("continuity status claim_budget_eligible.accounting must be an object for the snapshot head")
        if claim["status"] == "MEASURED":
            _nonneg_int(accounting.get("eligible_unique_total"), "claim_budget_eligible.accounting.eligible_unique_total")
        else:
            if claim["status"] != "UNDETERMINED" or accounting.get("eligible_unique_total") is not None:
                raise ValueError("continuity status claim_budget_eligible with accounting must be MEASURED with a total or UNDETERMINED without one")
            evidence = accounting.get("missing_evidence")
            if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item for item in evidence):
                raise ValueError("continuity status UNDETERMINED claim_budget_eligible must name its missing evidence")
    elif claim["status"] == "MEASURED":
        _closed(claim, {"status", "eligible_unique_total"}, "claim_budget_eligible")
        _nonneg_int(claim["eligible_unique_total"], "claim_budget_eligible.eligible_unique_total")
    else:
        _closed(claim, {"status", "missing"}, "claim_budget_eligible")
        _text(claim["missing"], "claim_budget_eligible.missing")
    gpu = status["gpu_owner"]
    if isinstance(gpu, dict) and gpu.get("status") == "held":
        _closed(gpu, {"status", "owner", "run_id", "training_job_purpose"}, "gpu_owner")
        for name in ("owner", "run_id", "training_job_purpose"):
            _text(gpu[name], f"gpu_owner.{name}", nullable=True)
    elif isinstance(gpu, dict) and gpu.get("status") == UNKNOWN_STATUS:
        _closed(gpu, {"status", "reason"}, "gpu_owner")
        _text(gpu["reason"], "gpu_owner.reason")
    else:
        _closed(gpu, {"status"}, "gpu_owner")
        if gpu["status"] not in {"not_reported", "free"}:
            raise ValueError("continuity status gpu_owner.status must be held, free, UNKNOWN or not_reported")
    checkpoint = _closed(status["checkpoint"], {"child_manifest_sha256", "parent_manifest_sha256", "last_hour_applied_positions"}, "checkpoint")
    if _digest_or_genesis(checkpoint["child_manifest_sha256"], "checkpoint.child_manifest_sha256") != head:
        raise ValueError("continuity snapshot head differs from the status checkpoint child")
    if checkpoint["parent_manifest_sha256"] is not None:
        _closed_hash(checkpoint["parent_manifest_sha256"], "checkpoint.parent_manifest_sha256")
    _nonneg_int(checkpoint["last_hour_applied_positions"], "checkpoint.last_hour_applied_positions")
    measurement = status["learning_measurement"]
    if isinstance(measurement, dict) and measurement.get("status") == "measured":
        _closed(measurement, {"status", "measurement"}, "learning_measurement")
        if not isinstance(measurement["measurement"], dict):
            raise ValueError("continuity status learning_measurement.measurement must be an object")
    elif isinstance(measurement, dict) and measurement.get("status") == UNKNOWN_STATUS:
        _closed(measurement, {"status", "reason"}, "learning_measurement")
        _text(measurement["reason"], "learning_measurement.reason")
    else:
        _closed(measurement, {"status"}, "learning_measurement")
        if measurement["status"] != "pending":
            raise ValueError("continuity status learning_measurement.status must be measured, pending or UNKNOWN")
    purpose = _closed(status["purpose"], {"training_job_purpose", "run_id"}, "purpose")
    for name in ("training_job_purpose", "run_id"):
        _text(purpose[name], f"purpose.{name}", nullable=True)
    allowance_keys = {
        "diagnostic_occupancy_seconds", "max_diagnostic_occupancy_seconds", "postponement_seconds",
        "max_postponement_seconds", "at_occupancy_limit", "at_postponement_limit"}
    if isinstance(status["diagnostic_allowance"], dict) and "postponed" in status["diagnostic_allowance"]:
        allowance_keys = allowance_keys | {"postponed", "postponement_reason"}
    allowance = _closed(status["diagnostic_allowance"], allowance_keys, "diagnostic_allowance")
    if "postponed" in allowance:
        if allowance["postponed"] is not True and allowance["postponed"] != UNKNOWN_STATUS:
            raise ValueError("continuity status diagnostic_allowance.postponed must be true or UNKNOWN")
        _text(allowance["postponement_reason"], "diagnostic_allowance.postponement_reason")
    for name in ("diagnostic_occupancy_seconds", "max_diagnostic_occupancy_seconds", "postponement_seconds", "max_postponement_seconds"):
        if (isinstance(allowance[name], bool) or not isinstance(allowance[name], (int, float))
                or not math.isfinite(allowance[name]) or allowance[name] < 0):
            raise ValueError(f"continuity status diagnostic_allowance.{name} must be a nonnegative number")
    for name in ("at_occupancy_limit", "at_postponement_limit"):
        if not isinstance(allowance[name], bool):
            raise ValueError(f"continuity status diagnostic_allowance.{name} must be a boolean")
    nxt = status["next_segment"]
    if isinstance(nxt, dict) and nxt.get("status") == "blocked":
        _closed(nxt, {"status", "blocker"}, "next_segment")
        _text(nxt["blocker"], "next_segment.blocker")
    else:
        _closed(nxt, {"status", "training_job_purpose", "run_id"}, "next_segment")
        if nxt["status"] != "ready":
            raise ValueError("continuity status next_segment.status must be ready or blocked")
        for name in ("training_job_purpose", "run_id"):
            _text(nxt[name], f"next_segment.{name}", nullable=True)
    _check_candidate_audit(payload["candidate_audit"], head, lineage)
    leaked = _private_path_strings(payload)
    if leaked:
        raise ValueError(f"continuity snapshot carries a local filesystem path: {leaked[0]!r}")
    return payload


def render_continuity_status_block(payload):
    """The page block for a loaded snapshot. Lineage retained positions come from the ancestry walk
    (`status.lineage`); the last hour's count is printed on its own line under its own name and is never presented as the
    lineage total. The block states `captured_at` and the head digest rather than claiming currency."""
    status = payload["status"]
    lineage, checkpoint, claim = status["lineage"], status["checkpoint"], status["claim_budget_eligible"]
    allowance, nxt = status["diagnostic_allowance"], status["next_segment"]
    if claim["status"] == "MEASURED":
        total = claim["accounting"]["eligible_unique_total"] if "accounting" in claim else claim["eligible_unique_total"]   # the loader admits both shapes
        claim_line = f"- Claim-budget-eligible unique targets: `{total}` (frozen predicate evaluated)."
    elif "accounting" in claim:
        evidence = claim["accounting"]["missing_evidence"]
        reasons = sorted({re.sub(r"^(segment )?'?[0-9a-f]{64}'?: ", "", item) for item in evidence})
        claim_line = (f"- Claim-budget-eligible unique targets: **{claim['status']}** under predicate `{claim['predicate_sha256']}`, no number is shown; "
                      f"`{len(evidence)}` missing-evidence items in `{len(reasons)}` kinds: " + "; ".join(reasons) + ".")
    else:
        claim_line = f"- Claim-budget-eligible unique targets: **{claim['status']}**, no number is shown; missing: {claim['missing']}"
    audit = payload["candidate_audit"]
    duplicate = audit["duplicate_credit"]
    if audit["status"] == "NO_CANDIDATE":
        candidate_line = "- Candidate child: none recorded."
    else:
        candidate, ruling = audit["candidate"], audit.get("refusal_ruling")
        ruled = (f"; ruling `{ruling['verdict']}` (row `{ruling['row_sha256']}`, receipt `{ruling['receipt_sha256']}`)"
                 if ruling else "; no ruling recorded")
        candidate_line = (f"- Candidate child `{candidate['manifest_sha256']}` (parent `{candidate['parent_manifest_sha256']}`): "
                          f"`{audit['status']}`{ruled}; positions credited to the lineage `{audit['retained']['positions_credited_to_lineage']}`.")
    duplicate_line = (f"- Duplicate-credit check: `{duplicate['distinct_manifests']}` distinct manifests, `{duplicate['hops_checked']}` hops, "
                      f"each hour counted once: `{str(duplicate['each_hour_counted_once']).lower()}`.")
    measurement = status["learning_measurement"]
    if measurement["status"] == "measured":
        measure_line = (f"- Last learning measurement (bound to `{checkpoint['child_manifest_sha256']}`): "
                        f"`{json.dumps(measurement['measurement'], sort_keys=True, separators=(',', ':'))}`.")
    elif measurement["status"] == UNKNOWN_STATUS:
        measure_line = f"- Last learning measurement: **UNKNOWN** ({measurement['reason']})."
    else:
        measure_line = "- Last learning measurement: pending."
    gpu = status["gpu_owner"]
    if gpu["status"] == "not_reported":
        gpu_line = "- GPU owner: not reported."
    elif gpu["status"] == "free":
        gpu_line = "- GPU owner: free (no window marker and no training process)."
    elif gpu["status"] == UNKNOWN_STATUS:
        gpu_line = f"- GPU owner: **UNKNOWN** ({gpu['reason']})."
    else:
        gpu_line = f"- GPU owner: `{gpu['owner']}`, run `{gpu['run_id']}`, purpose `{gpu['training_job_purpose']}`."
    if "postponed" in allowance:
        hold_line = ("- Training postponed: **UNKNOWN**" if allowance["postponed"] == UNKNOWN_STATUS else "- Training postponed: yes")
        hold_line += f" ({allowance['postponement_reason']})."
    else:
        hold_line = None
    purpose = status["purpose"]
    if nxt["status"] == "blocked":
        next_line = f"- Next segment: blocked: {nxt['blocker']}"
    else:
        next_line = f"- Next segment: ready, purpose `{nxt['training_job_purpose']}`, run `{nxt['run_id']}`."
    return "\n".join([
        CONTINUITY_BEGIN_MARKER,
        "<!-- GENERATED by src/ember/governance/scripts/gen_readme_status.py from manifests/ember-training-continuity-status-v1.json -->",
        f"**Training continuity (snapshot captured `{payload['captured_at']}`, head `{payload['head_manifest_sha256']}`):** "
        "this block matches the committed snapshot and does not claim to be current.",
        "",
        f"- Selected checkpoint: `{checkpoint['child_manifest_sha256']}`; parent: `{checkpoint['parent_manifest_sha256']}`.",
        f"- Retained applied positions over the whole lineage (ancestry walk, depth `{lineage['depth']}`): "
        f"`{lineage['retained_applied_positions']}` positions, `{lineage['retained_global_steps']}` steps.",
        f"- Last hour only: `{checkpoint['last_hour_applied_positions']}` applied positions.",
        candidate_line,
        duplicate_line,
        claim_line,
        measure_line,
        gpu_line,
        f"- Current purpose: `{purpose['training_job_purpose']}`, run `{purpose['run_id']}`.",
        f"- Diagnostic occupancy `{allowance['diagnostic_occupancy_seconds']}` of `{allowance['max_diagnostic_occupancy_seconds']}` s "
        f"(at limit: `{str(allowance['at_occupancy_limit']).lower()}`); postponement `{allowance['postponement_seconds']}` of "
        f"`{allowance['max_postponement_seconds']}` s (at limit: `{str(allowance['at_postponement_limit']).lower()}`).",
        *([hold_line] if hold_line else []),
        next_line,
        CONTINUITY_END_MARKER,
    ])


def _replace_marked(text, begin, end, block, surface):
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise ValueError(f"{surface} must contain exactly one {begin} ... {end} block")
    return pattern.sub(lambda _: block, text, count=1)


def apply_continuity_status(continuity_text, snapshot_path):
    """The page text with its continuity-status block rendered from the committed snapshot. Both halves or neither: a
    snapshot with no page block, a page block with no snapshot, or an invalid snapshot raises ValueError."""
    snapshot_present = os.path.isfile(snapshot_path)
    markers_present = CONTINUITY_BEGIN_MARKER in continuity_text or CONTINUITY_END_MARKER in continuity_text
    if not snapshot_present and not markers_present:
        return continuity_text
    if not snapshot_present:
        raise ValueError("CONTINUITY.md carries a continuity-status block but the committed snapshot is absent")
    if not markers_present:
        raise ValueError("the continuity snapshot exists but CONTINUITY.md has no continuity-status block")
    try:
        snapshot = load_continuity_status(snapshot_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"continuity snapshot is invalid: {exc}") from exc
    return _replace_marked(
        continuity_text,
        CONTINUITY_BEGIN_MARKER,
        CONTINUITY_END_MARKER,
        render_continuity_status_block(snapshot),
        "docs/domains/governance/authority/CONTINUITY.md",
    )


def subject_surfaces_current(payload, continuity_path):
    block = render_current_subject_block(payload)
    try:
        with open(continuity_path, "r", encoding="utf-8") as stream:
            continuity = stream.read()
        return (
            _replace_marked(
                continuity,
                SUBJECT_BEGIN_MARKER,
                SUBJECT_END_MARKER,
                block,
                "docs/domains/governance/authority/CONTINUITY.md",
            )
            == continuity
        )
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if generated continuity status is not current (no write)",
    )
    parser.add_argument(
        "--generated-status",
        action="store_true",
        help=(
            "with --check, verify deterministic generated status only; bypass branch-inventory "
            "distance and receipt wall-age checks"
        ),
    )
    parser.add_argument(
        "--data-root",
        default=DEFAULT_DATA_ROOT,
        help=(
            "directory to scan for ember-totality-*.json (default: this repo's "
            "scripts/ember_totality/receipts-totality/). Point this at a board-run lane's live "
            "data tree to render against a receipt not yet committed here."
        ),
    )
    parser.add_argument("--readme", default=README_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--continuity", default=CONTINUITY_PATH)
    parser.add_argument("--subject-manifest", default=CURRENT_SUBJECT_PATH)
    for flag in ("selected-pointer", "selected-manifest", "selected-pointer-sha256"):
        parser.add_argument("--" + flag, action="append")
    parser.add_argument("--continuity-snapshot", default=CONTINUITY_STATUS_PATH)
    parser.add_argument("--branch-inventory", default=BRANCH_INVENTORY_PATH)
    parser.add_argument("--branch-inventory-max-age-days", type=int, default=7)
    parser.add_argument(
        "--allow-stale-tree",
        action="store_true",
        help=(
            "render a stale/dirty receipt only as visibly marked archaeology; "
            "without this matching opt-out such receipts are refused"
        ),
    )
    parser.add_argument(
        "--allow-unbound-tree",
        action="store_true",
        help=(
            "render a receipt carrying no run-tree provenance at all only as visibly "
            "marked LEGACY_UNBOUND archaeology; without this opt-out it is refused"
        ),
    )
    parser.add_argument(
        "--allow-unchained-receipt",
        action="store_true",
        help=(
            "render a receipt whose predecessor sha cannot be checked against the "
            "on-disk bytes of the receipt before it; without this opt-out it is refused"
        ),
    )
    parser.add_argument(
        "--receipt-max-age-days",
        type=int,
        default=1,
        help="maximum age of the selected board receipt in normal continuity generation",
    )
    parser.add_argument(
        "--require-merge",
        action="append",
        default=[],
        metavar="SHA",
        help=(
            "repeatable exact merge commit that must be an ancestor of the "
            "selected board receipt's run-tree SHA; refuses stale decision evidence"
        ),
    )
    args = parser.parse_args()

    if args.generated_status and not args.check:
        parser.error("--generated-status requires --check")

    if not args.generated_status:
        try:
            check_inventory(
                manifest_path=Path(args.branch_inventory),
                continuity_path=Path(args.continuity),
                repo_path=Path(ROOT),
                max_age_days=args.branch_inventory_max_age_days,
            )
        except BranchInventoryError as exc:
            raise SystemExit(f"gen_readme_status: branch inventory is invalid: {exc}") from exc
    receipt_path = newest_receipt_path(args.data_root)
    block = render_block(
        receipt_path,
        allow_stale_tree=args.allow_stale_tree,
        allow_unbound_tree=args.allow_unbound_tree,
        allow_unchained=args.allow_unchained_receipt,
        repo_root=ROOT,
        required_commits=args.require_merge,
        receipt_max_age_days=(None if args.generated_status else args.receipt_max_age_days),
    )

    with open(args.readme, "r", encoding="utf-8") as f:
        readme = f.read()

    subject = load_current_subject(args.subject_manifest)
    selected_result = validate_current_subject_evidence(subject, ROOT, {
        "pointer": args.selected_pointer, "manifest": args.selected_manifest,
        "pointer_sha256": args.selected_pointer_sha256,
    })
    subject_block = render_current_subject_block(subject, selected_result)
    with open(args.continuity, "r", encoding="utf-8") as stream:
        continuity = stream.read()
    new_continuity = _replace_marked(
        continuity,
        BEGIN_MARKER,
        END_MARKER,
        block,
        "docs/domains/governance/authority/CONTINUITY.md",
    )
    receipt_ts = Path(receipt_path).stem.removeprefix("ember-totality-")
    new_continuity = bind_state_as_of(new_continuity, receipt_ts)
    new_continuity = _replace_marked(
        new_continuity,
        ARCHITECTURE_BEGIN_MARKER if subject["schema_version"] == SELECTED_SUBJECT_SCHEMA else SUBJECT_BEGIN_MARKER,
        ARCHITECTURE_END_MARKER if subject["schema_version"] == SELECTED_SUBJECT_SCHEMA else SUBJECT_END_MARKER,
        subject_block,
        "docs/domains/governance/authority/CONTINUITY.md",
    )
    try:
        new_continuity = apply_continuity_status(new_continuity, args.continuity_snapshot)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"gen_readme_status: {exc}") from exc

    if new_continuity == continuity:
        print(
            "docs/domains/governance/authority/CONTINUITY.md generated status is current "
            f"({os.path.basename(receipt_path)})."
        )
        return 0

    if args.check:
        print("docs/domains/governance/authority/CONTINUITY.md generated status is STALE.")
        return 1

    with open(args.continuity, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(new_continuity)
    print(
        "docs/domains/governance/authority/CONTINUITY.md status regenerated from "
        f"{os.path.basename(receipt_path)} and {os.path.basename(args.subject_manifest)}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
