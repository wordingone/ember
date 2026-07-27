#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build Ember's desired GitHub roadmap projection and issue reconciliation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


MILESTONES = [
    ("EMBER-00", "Authority and totality lock"),
    ("EMBER-01", "Custody, identity, and experiment spine"),
    ("EMBER-02", "Three-billion-parameter foundation birth"),
    ("EMBER-03", "Body, tools, and operator relationship"),
    ("EMBER-04", "Grounded memory, world model, and dreaming"),
    ("EMBER-05", "Three-billion-parameter Verified Expert Accretion rung"),
    ("EMBER-06", "Autonomous AI-research bootstrap"),
    ("EMBER-07", "Seven-billion-parameter hard rung"),
    ("EMBER-08", "Fifteen-billion-parameter hard rung"),
    ("EMBER-09", "Owned model above twenty-seven billion parameters"),
    ("EMBER-10", "General sovereign local AI laboratory"),
    ("EMBER-11", "Independent local ownership and scientific release"),
]
MILESTONE_IDS = {row[0] for row in MILESTONES}
DEPENDENCIES = {
    milestone_id: ([MILESTONES[index - 1][0]] if index else [])
    for index, (milestone_id, _) in enumerate(MILESTONES)
}
MIXED_HISTORICAL = {
    3: ["EMBER-02", "EMBER-05"],
    7: ["EMBER-05"],
    8: ["EMBER-05"],
    12: ["EMBER-05"],
    14: ["EMBER-00", "EMBER-01", "EMBER-06"],
    20: ["EMBER-05"],
    29: ["EMBER-02", "EMBER-05", "EMBER-07", "EMBER-08", "EMBER-09"],
    35: ["EMBER-00", "EMBER-01"],
}
MANUAL_ASSIGNMENTS = {
    37: ["EMBER-05"],
    107: ["EMBER-05"],
    126: ["EMBER-05"],
    222: ["EMBER-05"],
    279: ["EMBER-03"],
    290: ["EMBER-02"],
    320: ["EMBER-02"],
    335: ["EMBER-02"],
    339: ["EMBER-05"],
    354: ["EMBER-03"],
    372: ["EMBER-05"],
    427: ["EMBER-01"],
    483: ["EMBER-04", "EMBER-06"],
    558: ["EMBER-05"],
    582: ["EMBER-05"],
    585: ["EMBER-05"],
    612: ["EMBER-01"],
    627: ["EMBER-02"],
    630: ["EMBER-01", "EMBER-05"],
    667: ["EMBER-05"],
    675: ["EMBER-05"],
    679: ["EMBER-02"],
    688: ["EMBER-02"],
    700: ["EMBER-00", "EMBER-01"],
    702: ["EMBER-02"],
    703: ["EMBER-05"],
    705: ["EMBER-05"],
    711: ["EMBER-05"],
    718: ["EMBER-02", "EMBER-05"],
    722: ["EMBER-02", "EMBER-05"],
    757: ["EMBER-02"],
    763: ["EMBER-02"],
    768: ["EMBER-02"],
    782: ["EMBER-05"],
    793: ["EMBER-02"],
    798: ["EMBER-05"],
    805: ["EMBER-01"],
    869: ["EMBER-02"],
    917: ["EMBER-03"],
}
KEYWORDS = {
    "EMBER-00": re.compile(
        r"\bconstitution\b|\binvariant\b|\btotality\b|\bauthority\b|goal\.md",
        re.I,
    ),
    "EMBER-01": re.compile(
        r"\bcustody\b|\brepo(?:sitory)?\b|\bbranch\b|\bredaction\b|"
        r"\bboard\b|\bmanifest\b|\blineage\b|\bidentity\b|"
        r"\bintegrity\b|\baudit\b|\bdisposition\b|\bfreshness\b|"
        r"\brepo-guard\b",
        re.I,
    ),
    "EMBER-02": re.compile(
        r"\b3b\b|\bpretrain|\bcheckpoint\b|\btokenizer\b|\bcorpus\b|"
        r"\boptimizer\b|\bgpu\b|\bvram\b|\btraining\b|\btrainer\b|"
        r"\bshard\b|\bbitnet\b|\beval(?:uation)?\b|\bcompute\b|"
        r"\brung-3\b|\bmodel\b",
        re.I,
    ),
    "EMBER-03": re.compile(
        r"ember-cli|\bcockpit\b|\btui\b|\bwatchdog\b|\btelemetry\b|"
        r"\bwindow\b|\brender|\boperator protocol\b|\bautomation\b|"
        r"\bbrain-server\b|\bliveness\b|\bserving\b|\bserve\b",
        re.I,
    ),
    "EMBER-04": re.compile(
        r"\bworld[- ]model\b|\bdream(?:ing)?\b|\bepisodic memory\b|"
        r"\bmemory hierarchy\b",
        re.I,
    ),
    "EMBER-05": re.compile(
        r"\bgrow(?:th)?\b|\baccretion\b|\bexpert\b|\bc14\b|"
        r"\benergy(?:-law| envelope)?\b|\bbootstrap_pass\b|\bc-grow\b|"
        r"\bc-scale\b|\bflywheel\b|\bdeletion\b|\bfactor-1\b|"
        r"\btrajectory-gated\b|\brung-2\b",
        re.I,
    ),
    "EMBER-06": re.compile(
        r"\bautonom|\bresearch-core\b|\bgoal organ\b|\bself-improv|"
        r"\brelinquishment\b",
        re.I,
    ),
    "EMBER-07": re.compile(r"\b7b\b", re.I),
    "EMBER-08": re.compile(r"\b15b\b", re.I),
    "EMBER-09": re.compile(r"\b27b\b|\b30b\b|\b35b\b|over-27b", re.I),
    "EMBER-10": re.compile(
        r"\bai[- ]lab\b|\blaboratory\b|\bmaterially different\b", re.I
    ),
    "EMBER-11": re.compile(
        r"\brelease\b|\bmodel card\b|\bpaper\b|\bindependent local\b|"
        r"\bpublic reproducibility\b",
        re.I,
    ),
}


class ReconciliationError(ValueError):
    pass


def _canonical_milestone_id(title: str) -> str | None:
    match = re.match(r"^(EMBER-\d{2})(?::|\s+—|$)", title)
    if match and match.group(1) in MILESTONE_IDS:
        return match.group(1)
    return None


def _explicit_title_id(title: str) -> str | None:
    match = re.search(r"\[(EMBER-\d{2})(?:[A-Z])?\]", title)
    if match and match.group(1) in MILESTONE_IDS:
        return match.group(1)
    return None


def _keyword_ids(title: str) -> list[str]:
    matches = {mid for mid, pattern in KEYWORDS.items() if pattern.search(title)}
    if any(mid in matches for mid in ("EMBER-07", "EMBER-08", "EMBER-09")):
        matches.discard("EMBER-02")
        matches.discard("EMBER-05")
    elif "EMBER-05" in matches:
        matches.discard("EMBER-02")
    elif "EMBER-03" in matches:
        matches.discard("EMBER-02")
    return sorted(matches)


def _classify(issue: dict[str, Any]) -> dict[str, Any]:
    number = int(issue["number"])
    title = str(issue["title"])
    if number in MIXED_HISTORICAL:
        affected = MIXED_HISTORICAL[number]
        return {
            "disposition": "mixed_historical",
            "affected_milestones": affected,
            "desired_parent_subissue": None,
            "rationale": (
                "This historical roadmap-shaped contract spans or predates the "
                "current canonical decomposition. Preserve the original issue "
                "and map its remaining clauses without rewriting its history."
            ),
            "classification_basis": "manual_lossless_historical_crosswalk",
        }
    if number in MANUAL_ASSIGNMENTS:
        affected = MANUAL_ASSIGNMENTS[number]
        disposition = (
            "single_milestone" if len(affected) == 1 else "cross_cutting"
        )
        return {
            "disposition": disposition,
            "affected_milestones": affected,
            "desired_parent_subissue": (
                f"roadmap-parent:{affected[0]}"
                if disposition == "single_milestone"
                else None
            ),
            "rationale": (
                "Manual clause-subject review of this otherwise ambiguous title "
                "binds the remaining public contract to "
                + ", ".join(affected)
                + "."
            ),
            "classification_basis": "manual_clause_subject_review",
        }

    explicit = _explicit_title_id(title)
    existing = None
    if issue.get("milestone"):
        existing = _canonical_milestone_id(str(issue["milestone"]["title"]))
    strong = explicit or existing
    if strong:
        return {
            "disposition": "single_milestone",
            "affected_milestones": [strong],
            "desired_parent_subissue": f"roadmap-parent:{strong}",
            "rationale": (
                "The issue title or existing canonical milestone explicitly "
                f"binds the remaining contract to {strong}."
            ),
            "classification_basis": (
                "explicit_title_milestone" if explicit else "existing_milestone"
            ),
        }

    affected = _keyword_ids(title)
    if len(affected) == 1:
        milestone_id = affected[0]
        return {
            "disposition": "single_milestone",
            "affected_milestones": affected,
            "desired_parent_subissue": f"roadmap-parent:{milestone_id}",
            "rationale": (
                "The public issue title has one unambiguous milestone subject "
                f"under the closed classification vocabulary: {milestone_id}."
            ),
            "classification_basis": "deterministic_title_vocabulary",
        }
    if len(affected) > 1:
        return {
            "disposition": "cross_cutting",
            "affected_milestones": affected,
            "desired_parent_subissue": None,
            "rationale": (
                "The issue names obligations belonging to multiple canonical "
                "milestones and therefore remains standalone."
            ),
            "classification_basis": "deterministic_title_vocabulary",
        }
    return {
        "disposition": "evidence_pending",
        "affected_milestones": [],
        "desired_parent_subissue": None,
        "rationale": (
            "The public title does not prove a narrower milestone mapping. "
            "Preserve the issue standalone until clause-level evidence review."
        ),
        "classification_basis": "fail_closed_no_narrow_title_binding",
    }


def _desired_labels(row: dict[str, Any]) -> list[str]:
    labels = ["roadmap:tracked"]
    labels.extend(
        f"affects:{milestone_id}" for milestone_id in row["affected_milestones"]
    )
    labels.append(
        {
            "single_milestone": "roadmap:subissue",
            "cross_cutting": "roadmap:cross-cutting",
            "mixed_historical": "roadmap:historical",
            "evidence_pending": "roadmap:evidence-pending",
        }[row["disposition"]]
    )
    return sorted(labels)


def _label_definitions() -> list[dict[str, str]]:
    labels = [
        {
            "name": "roadmap:tracked",
            "color": "1f6feb",
            "description": "Accounted for by the version-controlled Ember roadmap",
        },
        {
            "name": "roadmap:parent",
            "color": "8250df",
            "description": "Canonical tracking issue for one Ember milestone",
        },
        {
            "name": "roadmap:subissue",
            "color": "2da44e",
            "description": "Entire remaining contract belongs to one milestone",
        },
        {
            "name": "roadmap:cross-cutting",
            "color": "bf8700",
            "description": "Remaining contract affects multiple milestones",
        },
        {
            "name": "roadmap:historical",
            "color": "9a6700",
            "description": "Historical contract preserved during lossless reconciliation",
        },
        {
            "name": "roadmap:evidence-pending",
            "color": "cf222e",
            "description": "Narrower disposition awaits clause-level evidence",
        },
    ]
    labels.extend(
        {
            "name": f"affects:{mid}",
            "color": "d4c5f9",
            "description": f"Work affects canonical milestone {mid}",
        }
        for mid, _ in MILESTONES
    )
    return labels


def build(census: dict[str, Any]) -> dict[str, Any]:
    if census.get("schema_version") != "ember-roadmap-public-state-v1":
        raise ReconciliationError("unsupported census schema")
    issues = census.get("issues")
    if not isinstance(issues, list):
        raise ReconciliationError("census issues must be an array")
    if census.get("counts", {}).get("open_issues") != len(issues):
        raise ReconciliationError("census issue count does not match rows")

    existing_by_id: dict[str, int] = {}
    for row in census.get("milestones", []):
        milestone_id = _canonical_milestone_id(str(row["title"]))
        if milestone_id:
            if milestone_id in existing_by_id:
                raise ReconciliationError(
                    f"duplicate canonical milestone projection: {milestone_id}"
                )
            existing_by_id[milestone_id] = int(row["number"])

    parent_by_id: dict[str, int] = {}
    for issue in issues:
        match = re.match(
            r"^\[ROADMAP\]\[(EMBER-\d{2})\]\s+", str(issue["title"])
        )
        if match:
            milestone_id = match.group(1)
            if milestone_id in parent_by_id:
                raise ReconciliationError(
                    f"duplicate roadmap parent issue: {milestone_id}"
                )
            parent_by_id[milestone_id] = int(issue["number"])

    reconciliation_rows: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    for issue in sorted(issues, key=lambda row: int(row["number"])):
        number = int(issue["number"])
        if number in seen_numbers:
            raise ReconciliationError(f"duplicate issue number: {number}")
        seen_numbers.add(number)
        classification = _classify(issue)
        row = {
            "number": number,
            "title": str(issue["title"]),
            "url": str(issue["url"]),
            "body_sha256": str(issue["body_sha256"]),
            "snapshot_updated_at": str(issue["updated_at"]),
            "intended_state": "open",
            **classification,
        }
        row["desired_labels"] = _desired_labels(row)
        reconciliation_rows.append(row)

    milestone_rows = []
    parent_rows = []
    for milestone_id, title in MILESTONES:
        contract_url = (
            "https://github.com/wordingone/ember/blob/master/"
            f"docs/roadmap/milestones/{milestone_id}.md"
        )
        milestone_rows.append(
            {
                "milestone_id": milestone_id,
                "title": f"{milestone_id} — {title}",
                "description": (
                    f"Canonical contract: {contract_url}\n\n"
                    "Progress is navigational. Completion requires the "
                    "version-controlled certificate."
                ),
                "state": "open",
                "due_on": None,
                "existing_number": existing_by_id.get(milestone_id),
            }
        )
        marker = f"<!-- ember-roadmap-parent: {milestone_id} -->"
        parent_rows.append(
            {
                "tracking_key": f"roadmap-parent:{milestone_id}",
                "milestone_id": milestone_id,
                "title": f"[ROADMAP][{milestone_id}] {title}",
                "body": (
                    f"{marker}\n\n"
                    f"Canonical contract: {contract_url}\n\n"
                    "This issue tracks concrete work and evidence. Its progress "
                    "does not complete or redefine the version-controlled "
                    "milestone contract.\n\n"
                    "No child issue may be closed without current-master "
                    "evidence for its own acceptance clauses."
                ),
                "labels": ["roadmap:parent", f"affects:{milestone_id}"],
                "depends_on": [
                    f"roadmap-parent:{dep}"
                    for dep in DEPENDENCIES[milestone_id]
                ],
                "existing_number": parent_by_id.get(milestone_id),
            }
        )

    projection = {
        "schema_version": "ember-roadmap-github-projection-v1",
        "repository": census["repository"],
        "source_master_sha": census["public_master_sha"],
        "source_issue_count": len(reconciliation_rows),
        "milestones": milestone_rows,
        "labels": _label_definitions(),
        "parent_issues": parent_rows,
        "issue_mutations": [
            {
                "number": row["number"],
                "expected_body_sha256": row["body_sha256"],
                "expected_updated_at": row["snapshot_updated_at"],
                "expected_labels": next(item["labels"] for item in issues if int(item["number"]) == row["number"]),
                "expected_milestone_id": next(((_canonical_milestone_id(str(item["milestone"]["title"])) if item.get("milestone") else None) for item in issues if int(item["number"]) == row["number"]), None),
                "add_labels": row["desired_labels"],
                "set_milestone": (
                    row["affected_milestones"][0]
                    if row["disposition"] == "single_milestone"
                    else None
                ),
                "add_as_subissue_of": row["desired_parent_subissue"],
                "close": False,
            }
            for row in reconciliation_rows
        ],
        "issue_closures": [],
    }
    reconciliation = {
        "schema_version": "ember-roadmap-issue-reconciliation-v1",
        "repository": census["repository"],
        "source_master_sha": census["public_master_sha"],
        "source_issue_count": len(reconciliation_rows),
        "issues": reconciliation_rows,
    }
    return {"projection": projection, "reconciliation": reconciliation}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    args = parser.parse_args()
    try:
        census = json.loads(args.census.read_text(encoding="utf-8"))
        payload = build(census)
        _write(args.projection, payload["projection"])
        _write(args.reconciliation, payload["reconciliation"])
    except (OSError, json.JSONDecodeError, ReconciliationError) as exc:
        print(f"ROADMAP_RECONCILIATION_REFUSED: {exc}", file=sys.stderr)
        return 2
    counts: dict[str, int] = {}
    for row in payload["reconciliation"]["issues"]:
        counts[row["disposition"]] = counts.get(row["disposition"], 0) + 1
    print(
        json.dumps(
            {
                "issue_count": len(payload["reconciliation"]["issues"]),
                "dispositions": counts,
                "status": "ROADMAP_RECONCILIATION_BUILT",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
