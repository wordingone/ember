#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""gen_readme_status.py -- regenerate README.md's board-status block from the
canonical, adjudicated current board receipt (R3, fspec-R3-1436-20260722T213546Z).

Selection used to be "newest lexicographic filename in one glob'd directory"
(the pre-R3 newest_receipt_path) -- location-blind, index-blind, and
freshness-blind, which is exactly how two 2026-07-11 twin board receipts (18
minutes apart, different counts, different locations) produced a README
citing the wrong one. Selection now derives from
scripts/ember_totality/board_index.py's canonical, adjudicated
BOARD-INDEX.jsonl: board_index.current_board() fails closed (raises) on any
duplicate-epoch RED or a missing/empty index -- this script never falls back
to the old newest-glob rule. The rendered block also carries a mechanical
Binding (receipt sha256 + governing commit) and Freshness (FRESH|STALE +
which basis field moved) verdict, so a stale README is visible in the
rendered text itself, not just discoverable by re-running the script.

Board-run playbook:
  - A board-run lane with a live data tree runs this against that tree BEFORE
    committing anything:
    python scripts/gen_readme_status.py --data-root /path/to/live/receipts-totality --check
    to see whether README would change, then without --check to render it,
    then reviews the diff. The lane tree must carry its own BOARD-INDEX.jsonl
    (the runner now writes one wherever it runs, and
    board_index.py backfill --root <lane root> creates one for a tree that
    predates R3) -- an absent index is a SystemExit, not a silent skip.
  - Run this script as the last step of every totality board run against the
    tree that will actually be committed, so README never drifts from what
    ships in the same commit.
  - If README changes as a result, land it as its own docs PR through the
    normal stop-at-open review flow -- this script never commits or pushes
    on its own.

CLI:
  python scripts/gen_readme_status.py            # regenerate README.md from the in-repo tree
  python scripts/gen_readme_status.py --check     # exit 1 if README.md would change (CI use)
  python scripts/gen_readme_status.py --data-root /path/to/receipts-totality
                                                  # point at a different (e.g. live/uncommitted)
                                                  # receipts-totality directory instead

Stdlib only. No network. PYTHONIOENCODING=utf-8 required (cp1252 console).
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA_ROOT = os.path.join(ROOT, "scripts", "ember_totality", "receipts-totality")
README_PATH = os.path.join(ROOT, "README.md")
CONTINUITY_PATH = os.path.join(ROOT, "CONTINUITY.md")
CURRENT_SUBJECT_PATH = os.path.join(ROOT, "manifests", "ember-current-subject-v1.json")
BEGIN_MARKER = "<!-- BOARD-STATUS-BEGIN -->"
END_MARKER = "<!-- BOARD-STATUS-END -->"
SUBJECT_BEGIN_MARKER = "<!-- CURRENT-SUBJECT-BEGIN -->"
SUBJECT_END_MARKER = "<!-- CURRENT-SUBJECT-END -->"
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

sys.path.insert(0, ROOT)
from scripts.ember_totality import board_index


def _repo_root_for_data_root(data_root):
    """data_root is normally <repo>/scripts/ember_totality/receipts-totality --
    a lane tree mirrors the same layout, so its repo root is three levels up."""
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(data_root)))
    )


def _resolve_current(data_root):
    """Derive the current board row from <data_root>/BOARD-INDEX.jsonl.
    Fail-closed: any board_index.current_board failure (missing index,
    duplicate-epoch RED) raises SystemExit with the finding text -- this
    never falls back to the old newest-glob selection rule."""
    index_path = os.path.join(data_root, "BOARD-INDEX.jsonl")
    if not os.path.isfile(index_path):
        raise SystemExit(
            "gen_readme_status: no BOARD-INDEX.jsonl under " + data_root +
            " -- run board_index.py backfill --root <lane root> first "
            "(every board-run tree now carries its own index)."
        )
    rows, skipped = board_index.load_index(index_path)
    for s in skipped:
        print("gen_readme_status: SKIPPED (malformed index line): " + s, file=sys.stderr)
    # Defect 1 fix (2026-07-23): skipped != [] is TERMINAL -- a dropped or
    # truncated index line must never let selection proceed as if the
    # index were clean (matches board_index._cmd_verify/_cmd_freshness).
    if skipped:
        raise SystemExit(
            "gen_readme_status: " + str(len(skipped)) +
            " malformed index line(s), first: " + skipped[0]
        )
    try:
        receipt_rel_path, row = board_index.current_board(rows)
    except board_index.BoardIndexError as exc:
        raise SystemExit("gen_readme_status: " + str(exc))
    repo_root = _repo_root_for_data_root(data_root)
    # Defect 2 fix (2026-07-23): validate the selected row BEFORE render --
    # closed schema, repo-root path confinement, and an exact on-disk
    # sha256 match to row['sha256'] (a row pinned to the wrong hash, or
    # mutated on-disk bytes, must never reach render_block).
    try:
        receipt_path = board_index.validate_selected_row(row, repo_root)
    except board_index.BoardIndexError as exc:
        raise SystemExit("gen_readme_status: " + str(exc))
    return row, receipt_path, repo_root


def render_block(receipt_path, row, freshness_result):
    with open(receipt_path, "r", encoding="utf-8") as f:
        receipt = json.load(f)
    with open(receipt_path, "rb") as f:
        receipt_sha256 = hashlib.sha256(f.read()).hexdigest()
    receipt_id = os.path.splitext(os.path.basename(receipt_path))[0]
    ts = receipt.get("ts", "unknown")
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

    basis = row.get("basis") or {}
    governing_commit = basis.get("governing_commit") or "UNKNOWN"
    if governing_commit == "UNKNOWN":
        governing_commit_text = "UNKNOWN (pre-index receipt)"
    else:
        governing_commit_text = governing_commit

    changed = freshness_result.get("changed") or []
    changed_text = ", ".join(changed) if changed else "current at index basis"

    lines = [
        BEGIN_MARKER,
        "<!-- GENERATED by scripts/gen_readme_status.py -- do not hand-edit between the markers -->",
        f"**Board receipt:** `{receipt_id}` (ts `{ts}`).",
        "",
        f"**Counts:** {green}-GREEN / {red}-RED / {unevaluable}-UNEVALUABLE / "
        f"{audit_ok}-AUDIT-OK / {audit_incident}-AUDIT-INCIDENT / "
        f"{audit_pending_epoch}-AUDIT-PENDING-EPOCH (total {total} rows, "
        f"{pct_green}% of state-conditions GREEN).",
        "",
        f"**Binding:** receipt sha256 {receipt_sha256[:16]}, governing commit "
        f"{governing_commit_text}.",
        "",
        f"**Freshness:** {freshness_result['verdict']} -- {changed_text}.",
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


def validate_current_subject_evidence(payload, root):
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


def render_current_subject_block(payload):
    subject = payload["subject"]
    cursor = subject["token_cursor"]
    parameters = subject["parameters"]
    predecessor = subject["predecessor"]
    return "\n".join(
        [
            SUBJECT_BEGIN_MARKER,
            "<!-- GENERATED by scripts/gen_readme_status.py from manifests/ember-current-subject-v1.json -->",
            f"**Current checkpoint subject:** `{subject['checkpoint_manifest_sha256']}`.",
            "",
            f"- Disposition: `{subject['disposition']}`; capability credit: `{subject['capability_credit']}`; sufficient pretraining proven: `{str(subject['sufficient_pretraining_proven']).lower()}`.",
            f"- Config: `{subject['model_config_sha256']}`; tokenizer: `{subject['tokenizer_sha256']}`; optimizer state (custody-only, public bytes absent): `{subject['optimizer_state_sha256']}`.",
            f"- Cursor: step `{cursor['global_step']}`, record `{cursor['record_index']}`, token offset `{cursor['token_offset']}`, tokens seen `{cursor['tokens_seen']}`; active route: `{subject['active_route']}`.",
            f"- Parameters: `{parameters['unique']}` unique, `{parameters['trainable']}` trainable, `{parameters['served']}` served, `{parameters['active']}` active, `{parameters['episode_trainable']}` episode-trainable.",
            f"- Historical predecessor: `{predecessor['checkpoint_manifest_sha256']}` at `{predecessor['tokens_seen']}` tokens (`{predecessor['relationship']}`).",
            SUBJECT_END_MARKER,
        ]
    )


def _replace_marked(text, begin, end, block, surface):
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise ValueError(f"{surface} must contain exactly one {begin} ... {end} block")
    return pattern.sub(lambda _: block, text, count=1)


def subject_surfaces_current(payload, readme_path, continuity_path):
    block = render_current_subject_block(payload)
    try:
        with open(readme_path, "r", encoding="utf-8") as stream:
            readme = stream.read()
        with open(continuity_path, "r", encoding="utf-8") as stream:
            continuity = stream.read()
        return (
            _replace_marked(
                readme,
                SUBJECT_BEGIN_MARKER,
                SUBJECT_END_MARKER,
                block,
                "README.md",
            )
            == readme
            and _replace_marked(
                continuity,
                SUBJECT_BEGIN_MARKER,
                SUBJECT_END_MARKER,
                block,
                "CONTINUITY.md",
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
        help="exit 1 if README.md's board-status block is not already current (no write)",
    )
    parser.add_argument(
        "--data-root",
        default=DEFAULT_DATA_ROOT,
        help=(
            "directory to scan for the canonical board index and receipts (default: "
            "this repo's scripts/ember_totality/receipts-totality/). Point this at a "
            "board-run lane's live data tree to render against a receipt not yet "
            "committed here; that tree must carry its own BOARD-INDEX.jsonl."
        ),
    )
    parser.add_argument("--readme", default=README_PATH)
    parser.add_argument("--continuity", default=CONTINUITY_PATH)
    parser.add_argument("--subject-manifest", default=CURRENT_SUBJECT_PATH)
    args = parser.parse_args()

    row, receipt_path, repo_root = _resolve_current(args.data_root)
    fresh = board_index.freshness(row, repo_root)
    block = render_block(receipt_path, row, fresh)

    with open(args.readme, "r", encoding="utf-8") as f:
        readme = f.read()

    pattern = re.compile(re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)
    if not pattern.search(readme):
        raise SystemExit(
            f"gen_readme_status: README.md is missing the {BEGIN_MARKER} ... {END_MARKER} markers"
        )
    new_readme = pattern.sub(lambda _: block, readme, count=1)

    subject = load_current_subject(args.subject_manifest)
    validate_current_subject_evidence(subject, ROOT)
    subject_block = render_current_subject_block(subject)
    new_readme = _replace_marked(
        new_readme,
        SUBJECT_BEGIN_MARKER,
        SUBJECT_END_MARKER,
        subject_block,
        "README.md",
    )
    with open(args.continuity, "r", encoding="utf-8") as stream:
        continuity = stream.read()
    new_continuity = _replace_marked(
        continuity,
        SUBJECT_BEGIN_MARKER,
        SUBJECT_END_MARKER,
        subject_block,
        "CONTINUITY.md",
    )

    if new_readme == readme and new_continuity == continuity:
        print(
            "README.md board-status and current-subject surfaces already current "
            f"({os.path.basename(receipt_path)})."
        )
        return 0

    if args.check:
        print("README.md or CONTINUITY.md generated status is STALE.")
        return 1

    with open(args.readme, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_readme)
    with open(args.continuity, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(new_continuity)
    print(
        "README.md and CONTINUITY.md status surfaces regenerated from "
        f"{os.path.basename(receipt_path)} and {os.path.basename(args.subject_manifest)}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
