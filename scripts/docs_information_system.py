#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Generate and verify Ember's source-bound public documentation system."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
PUBLIC_INTERPRETER_RECEIPT_PATH = Path("state/receipts/python-environment-install-v1.json")
PUBLIC_PYTHON_LAUNCHER_PATH = Path("scripts/headless-python.ps1")
PUBLIC_PYTHON_LAUNCHER_SHA256 = "f4570528882408c6c0bdc5bcd4fb945b60a6e2770287875e8750824bf1f5d230"

METADATA_PATH = Path("manifests/documentation/current-documents-v1.json")
CLAIM_MAP_PATH = Path("manifests/documentation/claim-source-map-v1.json")
COMMANDS_PATH = Path("manifests/documentation/public-commands-v1.json")
QUESTION_DESTINATIONS_PATH = Path("manifests/documentation/reader-question-destinations-v2.json")
REFERENCE_DISPOSITIONS_PATH = Path("manifests/documentation/reference-dispositions-v1.json")
CURRENT_REFERENCE_RECONCILIATION_PATH = Path(
    "manifests/documentation/current-reference-reconciliation-v1.json"
)
READER_INSTRUMENT_PATH = Path("manifests/documentation/reader-study-instrument-v2.json")
READER_INSTRUMENT_V1_PATH = Path("manifests/documentation/reader-study-instrument-v1.json")
READER_INSTRUMENT_SHA256 = "ccca620e2b8d5759f8aa89c7862baa0a25d7cac89f725ea45639c67ece3ab91e"
PREDECESSOR_READER_ID_SHA256S = {
    "c66bd342cb4e5e1432c2eb601d2f2ce784aff6da5b15f14e10e3c0e0f4facfd7",
    "58e1156648c53a55ce490437ee7a1cec562ad37b8cf3bf343faa2db81ab840d4",
}
READER_INSTRUMENT_FIELDS = {
    "questions",
    "eligibility",
    "sample_rule",
    "rubric",
    "threshold",
    "freeze_rule",
}
DOMAIN_AUTHORITY_PATH = Path("manifests/architecture/domain-authority-v1.json")
INDEX_PATH = Path("docs/INDEX.md")
CONSERVATION_MARKER = "<!-- EMBER_CONSERVATION_V1"
SOURCE_CLASSES = {
    "AUTHORITY_DERIVED",
    "IMPLEMENTATION_DERIVED",
    "EXECUTION_EVIDENCE_DERIVED",
    "EXPLICIT_TARGET",
    "EDITORIAL_OR_NAVIGATION",
}
STATUSES = {"normative", "current", "reference", "superseded", "historical"}
CURRENT_STATUSES = {"normative", "current"}
AUTHORITY_CLASSES = {"GOVERNED_NORMATIVE", "CURRENT_GUIDANCE", "GENERATED_NAVIGATION"}
REFERENCE_DISPOSITIONS = {
    "RESOLVED_AT_CURRENT_HEAD",
    "RETIRED_WITH_CANONICAL_DISPOSITION",
    "CLASSIFIER_ROW_OUTSIDE_CURRENT_NORMATIVE_ENTRY_SCOPE",
}
FILING_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:scripts|tools|src|runtime|configs|manifests|receipts|schemas|docs|tests|"
    r"state|scratch|artifacts|baseline|data|tokenizer)/[A-Za-z0-9_./-]+)"
)
CORRECTED_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"((?:scripts|tools|src|runtime|configs|manifests|receipts|schemas|docs|tests|"
    r"state|scratch|artifacts|baseline|data|tokenizer)/[A-Za-z0-9_./-]+)"
)
REFERENCE_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+")
REFERENCE_ROOT_PREFIXES = tuple(
    f"{root}/"
    for root in (
        "scripts",
        "tools",
        "src",
        "runtime",
        "configs",
        "manifests",
        "receipts",
        "schemas",
        "docs",
        "tests",
        "state",
        "scratch",
        "artifacts",
        "baseline",
        "data",
        "tokenizer",
    )
)
REQUIRED_METADATA_FIELDS = {
    "path",
    "title",
    "summary",
    "domain",
    "document_type",
    "status",
    "authority_class",
    "audience",
    "canonical_id",
    "owner",
    "supersedes",
}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
PROSE_PATH = re.compile(
    r"(?<![A-Za-z0-9_./-])((?:docs|scripts|tools|runtime|configs|manifests|schemas|tests)/[A-Za-z0-9_./-]+)"
)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
INTRO_FORBIDDEN = re.compile(
    r"(?:\b[0-9a-f]{40,64}\b|#\d+|\b20\d{2}-\d{2}-\d{2}\b|\b(?:PASS|FAIL|SKIP|RED)_[A-Z0-9_]+\b)"
)


class DocsInfoError(ValueError):
    """The documentation system is nonterminal for one exact reason."""


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_compact(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DocsInfoError(f"JSON_INVALID:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise DocsInfoError(f"JSON_ROOT_NOT_OBJECT:{path}")
    return value


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError as exc:
        raise DocsInfoError(f"OUTPUT_EXISTS_REFUSED:{path}") from exc


def validate_metadata(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema_version") != "ember-doc-metadata-v1":
        raise DocsInfoError("METADATA_SCHEMA_INVALID")
    rows = manifest.get("documents")
    if not isinstance(rows, list) or not rows:
        raise DocsInfoError("METADATA_DOCUMENTS_EMPTY")
    canonical_ids: set[str] = set()
    paths: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != REQUIRED_METADATA_FIELDS:
            raise DocsInfoError(f"METADATA_ROW_SCHEMA_INVALID:{index}")
        path = row["path"]
        canonical_id = row["canonical_id"]
        if not isinstance(path, str) or path.startswith(("/", "\\")) or ".." in Path(path).parts:
            raise DocsInfoError(f"DOCUMENT_PATH_INVALID:{index}")
        if path in paths:
            raise DocsInfoError(f"DUPLICATE_DOCUMENT_PATH:{path}")
        if canonical_id in canonical_ids:
            raise DocsInfoError(f"DUPLICATE_CANONICAL_ID:{canonical_id}")
        if row["status"] not in STATUSES:
            raise DocsInfoError(f"DOCUMENT_STATUS_INVALID:{path}")
        if row["authority_class"] not in AUTHORITY_CLASSES:
            raise DocsInfoError(f"DOCUMENT_AUTHORITY_CLASS_INVALID:{path}")
        if not isinstance(row["audience"], list) or not row["audience"]:
            raise DocsInfoError(f"DOCUMENT_AUDIENCE_INVALID:{path}")
        if not isinstance(row["supersedes"], list):
            raise DocsInfoError(f"DOCUMENT_SUPERSESSION_INVALID:{path}")
        if not (root / path).is_file():
            raise DocsInfoError(f"DOCUMENT_PATH_MISSING:{path}")
        paths.add(path)
        canonical_ids.add(canonical_id)
        normalized.append(dict(row))
    return normalized


def render_index(manifest: dict[str, Any]) -> str:
    rows = manifest.get("documents")
    if not isinstance(rows, list):
        raise DocsInfoError("METADATA_DOCUMENTS_INVALID")
    lines = [
        "<!-- generated by scripts/docs_information_system.py; do not edit -->",
        "# Canonical documentation index",
        "",
        "This index is generated from `manifests/documentation/current-documents-v1.json`.",
        "",
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("status") in CURRENT_STATUSES:
            grouped.setdefault(str(row["domain"]), []).append(row)
    for domain in sorted(grouped, key=str.casefold):
        lines.extend([f"## {domain}", ""])
        for row in sorted(grouped[domain], key=lambda item: str(item["canonical_id"])):
            path = str(row["path"])
            target = path.removeprefix("docs/") if path.startswith("docs/") else f"../{path}"
            lines.append(
                f"- [`{row['canonical_id']}`]({target}) — {row['summary']} "
                f"({row['status']}; {', '.join(row['audience'])})"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def validate_claim_map(root: Path, claim_map: dict[str, Any]) -> list[dict[str, Any]]:
    if claim_map.get("schema_version") != "ember-doc-claim-source-map-v1":
        raise DocsInfoError("CLAIM_MAP_SCHEMA_INVALID")
    claims = claim_map.get("claims")
    anchors = claim_map.get("anchors")
    if not isinstance(claims, list) or not claims:
        raise DocsInfoError("CLAIM_MAP_EMPTY")
    if not isinstance(anchors, dict):
        raise DocsInfoError("CLAIM_ANCHORS_INVALID")
    claim_ids: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise DocsInfoError(f"CLAIM_ROW_INVALID:{index}")
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or claim_id in claim_ids:
            raise DocsInfoError(f"DUPLICATE_CLAIM_ID:{claim_id}")
        claim_ids.add(claim_id)
        anchor = anchors.get(claim_id)
        if anchor != claim_id:
            raise DocsInfoError(f"CLAIM_ANCHOR_INVALID:{claim_id}")
        if claim.get("source_class") not in SOURCE_CLASSES:
            raise DocsInfoError(f"CLAIM_SOURCE_CLASS_INVALID:{claim_id}")
        if claim.get("status") != "current":
            raise DocsInfoError(f"STALE_CLAIM_STATUS:{claim_id}")
        document = claim.get("document")
        if not isinstance(document, str) or not (root / document).is_file():
            raise DocsInfoError(f"CLAIM_DOCUMENT_MISSING:{claim_id}")
        if f'id="{anchor}"' not in (root / document).read_text(encoding="utf-8"):
            raise DocsInfoError(f"CLAIM_ANCHOR_MISSING:{claim_id}:{document}")
        sources = claim.get("sources")
        if not isinstance(sources, list) or not sources:
            raise DocsInfoError(f"CLAIM_SOURCES_EMPTY:{claim_id}")
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
                raise DocsInfoError(f"CLAIM_SOURCE_SCHEMA_INVALID:{claim_id}")
            path = root / source["path"]
            if not path.is_file():
                raise DocsInfoError(f"CLAIM_SOURCE_MISSING:{claim_id}:{source['path']}")
            if sha256_file(path) != source["sha256"]:
                raise DocsInfoError(f"STALE_CLAIM_SOURCE:{claim_id}:{source['path']}")
    return claims


def validate_readme(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    if CONSERVATION_MARKER not in text:
        raise DocsInfoError("CONSERVATION_BLOCK_MISSING")
    rendered = HTML_COMMENT.sub("", text)
    words = re.findall(r"\b\S+\b", rendered)
    if len(words) > 1500:
        raise DocsInfoError(f"README_WORD_LIMIT_EXCEEDED:{len(words)}")
    introduction = " ".join(words[:400])
    match = INTRO_FORBIDDEN.search(introduction)
    if match:
        raise DocsInfoError(f"README_INTRO_VOLATILE_TOKEN:{match.group(0)}")
    return {"rendered_words": len(words), "intro_words": min(400, len(words))}


def _resolve_reference(document: Path, target: str, root: Path) -> bool:
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target or target.startswith(("http://", "https://", "mailto:")):
        return True
    candidate = (root / target.lstrip("/")) if target.startswith("/") else (document.parent / target)
    return candidate.resolve().exists()


def validate_references(root: Path, rows: list[dict[str, Any]], retired_paths: list[str]) -> dict[str, int]:
    link_count = 0
    prose_count = 0
    for row in rows:
        if row["status"] not in CURRENT_STATUSES:
            continue
        relative = row["path"]
        path = root / relative
        text = path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            link_count += 1
            target = match.group(1).strip().strip("<>")
            if not _resolve_reference(path, target, root):
                raise DocsInfoError(f"BROKEN_MARKDOWN_LINK:{relative}:{target}")
        for match in PROSE_PATH.finditer(text):
            prose_count += 1
            target = match.group(1).rstrip(".,:;)")
            if not (root / target).exists():
                raise DocsInfoError(f"BROKEN_PROSE_PATH:{relative}:{target}")
        for retired in retired_paths:
            if retired in text:
                raise DocsInfoError(f"RETIRED_PATH_ACTIVE:{relative}:{retired}")
    return {"markdown_links": link_count, "prose_paths": prose_count}


def validate_domains(root: Path, rows: list[dict[str, Any]], authority: dict[str, Any]) -> list[str]:
    owners = authority.get("owners")
    if not isinstance(owners, list) or len(owners) != 8:
        raise DocsInfoError("DOMAIN_AUTHORITY_OWNERS_INVALID")
    declared = {row["domain"] for row in rows if row["status"] in CURRENT_STATUSES}
    undeclared = declared - set(owners)
    if undeclared:
        raise DocsInfoError(f"DOCUMENT_DOMAIN_UNADOPTED:{sorted(undeclared)}")
    for owner in owners:
        expected = root / "docs" / "domains" / owner.lower() / "README.md"
        if not expected.is_file():
            raise DocsInfoError(f"DOMAIN_OVERVIEW_MISSING:{owner}:{expected.relative_to(root)}")
    return list(owners)


def validate_commands_manifest(commands: dict[str, Any]) -> list[dict[str, Any]]:
    if commands.get("schema_version") != "ember-public-command-replay-v1":
        raise DocsInfoError("PUBLIC_COMMAND_SCHEMA_INVALID")
    denominator = commands.get("filing_time_census")
    if not isinstance(denominator, dict) or denominator.get("command_rows") != 276:
        raise DocsInfoError("PUBLIC_COMMAND_CENSUS_DENOMINATOR_INVALID")
    scope = commands.get("governed_subset")
    if (
        not isinstance(scope, dict)
        or scope.get("authority_artifact_sha256")
        != "c2eee97ca0ea1f24ef80f5a0a128ac48b88a0632c5a9b774f735648eb8c4fe54"
        or scope.get("authority_artifact_lines") != [242, 249]
        or scope.get("selection") != "FOUR_FINAL_PUBLIC_ENTRY_COMMANDS"
    ):
        raise DocsInfoError("PUBLIC_COMMAND_GOVERNED_SUBSET_INVALID")
    rows = commands.get("commands")
    if not isinstance(rows, list) or len(rows) != 4:
        raise DocsInfoError("PUBLIC_COMMAND_SET_INCOMPLETE")
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "argv", "cwd", "requirements", "expected"}:
            raise DocsInfoError("PUBLIC_COMMAND_ROW_INVALID")
        if row["id"] in ids:
            raise DocsInfoError(f"PUBLIC_COMMAND_ID_DUPLICATE:{row['id']}")
        ids.add(row["id"])
        if not isinstance(row["argv"], list) or not row["argv"]:
            raise DocsInfoError(f"PUBLIC_COMMAND_ARGV_INVALID:{row['id']}")
    expected_argv = {
        "bootstrap-python": [
            "python",
            "tools/ember-restart-3b/python_environment.py",
            "install",
            "--receipt",
            "state\\receipts\\python-environment-install-v1.json",
        ],
        "verify-authority": [
            "python",
            "scripts/verify_authority_conservation.py",
            "--root",
            ".",
        ],
        "receipt-selftest": ["python", "src/ember/governance/scripts/receipt_check.py", "--selftest"],
        "verify-documentation": [
            "python",
            "scripts/docs_information_system.py",
            "check",
            "--root",
            ".",
        ],
    }
    if ids != set(expected_argv):
        raise DocsInfoError("PUBLIC_COMMAND_ID_SET_INVALID")
    bootstrap = next(row for row in rows if row["id"] == "bootstrap-python")
    if "--receipt" not in bootstrap["argv"]:
        raise DocsInfoError("PUBLIC_COMMAND_REQUIRED_RECEIPT_MISSING:bootstrap-python")
    for row in rows:
        if row["argv"] != expected_argv[row["id"]]:
            raise DocsInfoError(f"PUBLIC_COMMAND_ARGV_MISMATCH:{row['id']}")
    return rows


def validate_public_command_docs(root: Path, rows: list[dict[str, Any]]) -> None:
    rendered = {row["id"]: " ".join(row["argv"]) for row in rows}
    verify_text = (root / "docs/guides/VERIFY.md").read_text(encoding="utf-8")
    for command_id, command in rendered.items():
        if command not in verify_text:
            raise DocsInfoError(f"PUBLIC_COMMAND_DOC_DRIFT:docs/guides/VERIFY.md:{command_id}")
    bootstrap = rendered["bootstrap-python"]
    for relative in ("README.md", "docs/domains/governance/guides/START-HERE.md"):
        if bootstrap not in (root / relative).read_text(encoding="utf-8"):
            raise DocsInfoError(f"PUBLIC_COMMAND_DOC_DRIFT:{relative}:bootstrap-python")


def validate_question_destinations(
    root: Path, mapping: dict[str, Any], rows: list[dict[str, Any]], instrument: dict[str, Any]
) -> list[dict[str, Any]]:
    if mapping.get("schema_version") != "ember-reader-question-destinations-v2":
        raise DocsInfoError("QUESTION_DESTINATION_SCHEMA_INVALID")
    if mapping.get("instrument_sha256") != instrument.get("instrument_sha256"):
        raise DocsInfoError("QUESTION_DESTINATION_INSTRUMENT_MISMATCH")
    questions = instrument.get("questions")
    routes = mapping.get("routes")
    if not isinstance(questions, list) or len(questions) != 8:
        raise DocsInfoError("QUESTION_DESTINATION_INSTRUMENT_INVALID")
    if not isinstance(routes, list) or len(routes) != 8:
        raise DocsInfoError("QUESTION_DESTINATION_COUNT_INVALID")
    current_ids = {
        row["canonical_id"]: row for row in rows if row["status"] in CURRENT_STATUSES
    }
    expected = {question.get("question_id"): question.get("question") for question in questions}
    seen: set[str] = set()
    for route in routes:
        if not isinstance(route, dict) or set(route) != {
            "question_id",
            "question",
            "canonical_destination_id",
        }:
            raise DocsInfoError("QUESTION_DESTINATION_ROW_INVALID")
        question_id = route["question_id"]
        if question_id in seen or expected.get(question_id) != route["question"]:
            raise DocsInfoError(f"QUESTION_DESTINATION_QUESTION_INVALID:{question_id}")
        seen.add(question_id)
        destination = route["canonical_destination_id"]
        if destination not in current_ids:
            raise DocsInfoError(f"QUESTION_DESTINATION_UNKNOWN:{question_id}:{destination}")
    if seen != set(expected):
        raise DocsInfoError("QUESTION_DESTINATION_SET_INVALID")
    source_dispositions = mapping.get("source_dispositions")
    if not isinstance(source_dispositions, list):
        raise DocsInfoError("READER_SOURCE_DISPOSITIONS_INVALID")
    disposition_by_source = {
        row.get("source"): row for row in source_dispositions if isinstance(row, dict)
    }
    for question in questions:
        answer_key = question.get("answer_key")
        public_sources = answer_key.get("public_sources") if isinstance(answer_key, dict) else None
        if not isinstance(public_sources, list):
            raise DocsInfoError(f"READER_PUBLIC_SOURCES_INVALID:{question.get('question_id')}")
        for source in public_sources:
            if (root / source).exists():
                continue
            disposition = disposition_by_source.get(source)
            if (
                not isinstance(disposition, dict)
                or disposition.get("disposition") != "RETIRED_WITH_CANONICAL_DISPOSITION"
                or not isinstance(disposition.get("canonical_source"), str)
                or not (root / disposition["canonical_source"]).is_file()
            ):
                raise DocsInfoError(
                    f"READER_PUBLIC_SOURCE_UNRESOLVED:{question.get('question_id')}:{source}"
                )
    return routes


def validate_reader_instrument(root: Path, instrument: dict[str, Any]) -> None:
    if set(instrument) != {
        "authority",
        "claim_boundary",
        "eligibility",
        "freeze_rule",
        "instrument_sha256",
        "questions",
        "result",
        "rubric",
        "sample_rule",
        "schema_version",
        "self_sha256",
        "threshold",
    } or instrument.get("schema_version") != "ember-issue1951-reader-instrument-v2":
        raise DocsInfoError("READER_INSTRUMENT_V2_SCHEMA_INVALID")
    contract = {key: instrument[key] for key in READER_INSTRUMENT_FIELDS}
    if instrument.get("instrument_sha256") != READER_INSTRUMENT_SHA256 or sha256_bytes(
        canonical_compact(contract)
    ) != READER_INSTRUMENT_SHA256:
        raise DocsInfoError("READER_INSTRUMENT_V2_HASH_INVALID")
    unsigned = dict(instrument)
    claimed_self = unsigned.pop("self_sha256", None)
    if claimed_self != sha256_bytes(canonical_compact(unsigned)):
        raise DocsInfoError("READER_INSTRUMENT_V2_SELF_HASH_INVALID")
    predecessor = load_json(root / READER_INSTRUMENT_V1_PATH)
    expected_contract = {key: predecessor[key] for key in READER_INSTRUMENT_FIELDS}
    expected_questions = json.loads(json.dumps(expected_contract["questions"]))
    q3 = next(row for row in expected_questions if row.get("question_id") == "Q3")
    q3["question"] = (
        "State Ember's certified current model/training status, then state the full EMBER-02 "
        "target including approximate parameter range, modalities, reasoning, and structured-tool role."
    )
    expected_contract["questions"] = expected_questions
    if contract != expected_contract:
        raise DocsInfoError("READER_INSTRUMENT_V2_SEMANTIC_DRIFT")
    authority = instrument.get("authority")
    if (
        not isinstance(authority, dict)
        or authority.get("predecessor_instrument_sha256")
        != "f6d851c10dcc7a19dcc6f5c8bdca72344933764aedb244fb92bfc2c48d5d288b"
        or set(authority.get("excluded_predecessor_reader_id_sha256s", []))
        != PREDECESSOR_READER_ID_SHA256S
    ):
        raise DocsInfoError("READER_INSTRUMENT_V2_PREDECESSOR_BINDING_INVALID")


def reference_target_resolves(root: Path, document: Path, target: str) -> bool:
    if "://" in target:
        return False
    try:
        root_candidate = root / target
        if root_candidate.exists():
            return True
        return (document.parent / target).exists()
    except OSError:
        return False


def current_unresolved_reference_rows(
    root: Path, pattern: re.Pattern[str],
) -> list[dict[str, Any]]:
    documents = [root / "README.md", *sorted((root / "docs").rglob("*.md"))]
    rows: dict[tuple[str, int, str], dict[str, Any]] = {}
    for document in documents:
        relative = document.relative_to(root).as_posix()
        for line_number, line in enumerate(
            document.read_text(encoding="utf-8").splitlines(), 1
        ):
            for match in pattern.finditer(line):
                target = match.group(1).rstrip(".,:;)]}")
                if reference_target_resolves(root, document, target):
                    continue
                containing_token = next(
                    (
                        token.group(0).rstrip(".,:;)]}")
                        for token in REFERENCE_TOKEN_RE.finditer(line)
                        if token.start() <= match.start(1) and token.end() >= match.end(1)
                    ),
                    target,
                )
                key = (relative, line_number, target)
                rows[key] = {
                    "document": relative,
                    "line": line_number,
                    "target": target,
                    "containing_token": containing_token,
                    "containing_token_resolves": reference_target_resolves(
                        root, document, containing_token
                    ),
                }
    return [rows[key] for key in sorted(rows)]


def validate_current_reference_reconciliation(
    root: Path,
    value: dict[str, Any],
    frozen_dispositions: dict[str, Any],
) -> list[dict[str, Any]]:
    if (
        not isinstance(value, dict)
        or set(value)
        != {"schema_version", "source", "classifiers", "counts", "rows", "rows_sha256"}
        or value.get("schema_version") != "ember-current-reference-reconciliation-v1"
    ):
        raise DocsInfoError("CURRENT_REFERENCE_RECONCILIATION_SCHEMA_INVALID")
    source = value.get("source")
    if not isinstance(source, dict) or source != {
        "commit": "f78e05de04b375e87a2f385316fbbda385930272",
        "tree": "c09bb86cafc94409ebd775e428daac2d7923cee8",
        "frozen_dispositions_raw_sha256": sha256_file(root / REFERENCE_DISPOSITIONS_PATH),
        "filing_census_raw_sha256": "5a2da304d5f40cc99b6fd23dbdd092866f48eb97a282416ffada52cbf105fce7",
        "filing_census_self_sha256": "ad77a19d985a5f7772e04b782900f30b648ee78720c4446d7fc7d38a4a967b04",
    }:
        raise DocsInfoError("CURRENT_REFERENCE_RECONCILIATION_SOURCE_INVALID")
    classifiers = value.get("classifiers")
    expected_classifiers = {
        "filing_regex": FILING_REFERENCE_RE.pattern,
        "filing_regex_sha256": sha256_bytes(FILING_REFERENCE_RE.pattern.encode("utf-8")),
        "corrected_regex": CORRECTED_REFERENCE_RE.pattern,
        "corrected_regex_sha256": sha256_bytes(
            CORRECTED_REFERENCE_RE.pattern.encode("utf-8")
        ),
    }
    if classifiers != expected_classifiers:
        raise DocsInfoError("CURRENT_REFERENCE_RECONCILIATION_CLASSIFIER_INVALID")
    filing_rows = current_unresolved_reference_rows(root, FILING_REFERENCE_RE)
    corrected_rows = current_unresolved_reference_rows(root, CORRECTED_REFERENCE_RE)
    filing_by_key = {
        (row["document"], row["line"], row["target"]): row for row in filing_rows
    }
    corrected_keys = {
        (row["document"], row["line"], row["target"]) for row in corrected_rows
    }
    frozen_rows = frozen_dispositions.get("rows")
    if not isinstance(frozen_rows, list):
        raise DocsInfoError("CURRENT_REFERENCE_RECONCILIATION_FROZEN_ROWS_INVALID")
    frozen_by_key = {
        (row.get("document"), row.get("line"), row.get("target")): row
        for row in frozen_rows
        if isinstance(row, dict)
    }
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise DocsInfoError("CURRENT_REFERENCE_RECONCILIATION_ROWS_INVALID")
    observed_keys: set[tuple[str, int, str]] = set()
    container_count = 0
    explicit_count = 0
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"document", "line", "target", "resolution"}
        ):
            raise DocsInfoError("CURRENT_REFERENCE_RECONCILIATION_ROW_INVALID")
        key = (row.get("document"), row.get("line"), row.get("target"))
        if key in observed_keys or key not in filing_by_key:
            raise DocsInfoError(f"CURRENT_REFERENCE_RECONCILIATION_ROW_STALE:{key}")
        observed_keys.add(key)
        resolution = row.get("resolution")
        if not isinstance(resolution, dict):
            raise DocsInfoError(
                f"CURRENT_REFERENCE_RECONCILIATION_RESOLUTION_INVALID:{key}"
            )
        if resolution.get("kind") == "CONTAINED_RESOLVED_CANONICAL_TOKEN":
            if set(resolution) != {"kind", "canonical_token"}:
                raise DocsInfoError(
                    f"CURRENT_REFERENCE_RECONCILIATION_CONTAINER_INVALID:{key}"
                )
            canonical_token = resolution.get("canonical_token")
            current = filing_by_key[key]
            document = root / str(row["document"])
            if (
                key in corrected_keys
                or not isinstance(canonical_token, str)
                or str(row["target"]) not in canonical_token
                or canonical_token != current["containing_token"]
                or not reference_target_resolves(root, document, canonical_token)
            ):
                raise DocsInfoError(
                    f"CURRENT_REFERENCE_RECONCILIATION_CONTAINER_INVALID:{key}"
                )
            container_count += 1
        elif resolution.get("kind") == "EXPLICIT_FILING_DISPOSITION":
            if set(resolution) != {
                "kind",
                "source_document",
                "source_line",
                "source_target",
                "disposition",
                "visible_classification",
            }:
                raise DocsInfoError(
                    f"CURRENT_REFERENCE_RECONCILIATION_DISPOSITION_INVALID:{key}"
                )
            source_key = (
                resolution.get("source_document"),
                resolution.get("source_line"),
                resolution.get("source_target"),
            )
            frozen = frozen_by_key.get(source_key)
            if (
                frozen is None
                or resolution.get("source_target") != row.get("target")
                or resolution.get("disposition") != frozen.get("disposition")
                or resolution.get("visible_classification")
                != frozen.get("visible_classification")
            ):
                raise DocsInfoError(
                    f"CURRENT_REFERENCE_RECONCILIATION_DISPOSITION_INVALID:{key}"
                )
            explicit_count += 1
        else:
            raise DocsInfoError(
                f"CURRENT_REFERENCE_RECONCILIATION_RESOLUTION_INVALID:{key}"
            )
    if observed_keys != set(filing_by_key):
        raise DocsInfoError("CURRENT_REFERENCE_RECONCILIATION_CURRENT_ROWS_STALE")
    counts = value.get("counts")
    expected_counts = {
        "documents": 1 + len(list((root / "docs").rglob("*.md"))),
        "filing_classifier_current_unresolved": len(filing_rows),
        "corrected_classifier_current_unresolved": len(corrected_rows),
        "explicit_filing_dispositions": explicit_count,
        "contained_resolved_canonical_tokens": container_count,
    }
    if counts != expected_counts or value.get("rows_sha256") != sha256_bytes(
        canonical_compact(rows)
    ):
        raise DocsInfoError("CURRENT_REFERENCE_RECONCILIATION_COUNTS_OR_HASH_STALE")
    return rows


def build_current_reference_reconciliation(
    root: Path, frozen_dispositions: dict[str, Any], prior: dict[str, Any]
) -> dict[str, Any]:
    prior_source = prior.get("source")
    expected_fixed_source = {
        "commit": "f78e05de04b375e87a2f385316fbbda385930272",
        "tree": "c09bb86cafc94409ebd775e428daac2d7923cee8",
        "filing_census_raw_sha256": "5a2da304d5f40cc99b6fd23dbdd092866f48eb97a282416ffada52cbf105fce7",
        "filing_census_self_sha256": "ad77a19d985a5f7772e04b782900f30b648ee78720c4446d7fc7d38a4a967b04",
    }
    if not isinstance(prior_source, dict) or {
        key: prior_source.get(key) for key in expected_fixed_source
    } != expected_fixed_source:
        raise DocsInfoError("CURRENT_REFERENCE_RECONCILIATION_SOURCE_INVALID")
    frozen_rows = frozen_dispositions.get("rows")
    if not isinstance(frozen_rows, list):
        raise DocsInfoError("CURRENT_REFERENCE_RECONCILIATION_FROZEN_ROWS_INVALID")
    by_key = {
        (row.get("document"), row.get("line"), row.get("target")): row
        for row in frozen_rows if isinstance(row, dict)
    }
    by_target: dict[str, list[dict[str, Any]]] = {}
    for row in frozen_rows:
        if isinstance(row, dict) and isinstance(row.get("target"), str):
            by_target.setdefault(row["target"], []).append(row)
    filing_rows = current_unresolved_reference_rows(root, FILING_REFERENCE_RE)
    corrected_keys = {
        (row["document"], row["line"], row["target"])
        for row in current_unresolved_reference_rows(root, CORRECTED_REFERENCE_RE)
    }
    rows: list[dict[str, Any]] = []
    for current in filing_rows:
        key = (current["document"], current["line"], current["target"])
        if key not in corrected_keys and current["containing_token_resolves"]:
            resolution = {
                "kind": "CONTAINED_RESOLVED_CANONICAL_TOKEN",
                "canonical_token": current["containing_token"],
            }
        else:
            candidates = [by_key[key]] if key in by_key else by_target.get(str(current["target"]), [])
            if not candidates:
                raise DocsInfoError(f"UNRECONCILED_CURRENT_REFERENCE:{key}")
            if len({candidate.get("disposition") for candidate in candidates}) != 1:
                raise DocsInfoError(f"AMBIGUOUS_CURRENT_DISPOSITION:{key}")
            preferred = "historical" if "/archive/" in str(current["document"]) else "reference"
            selected = next(
                (candidate for candidate in candidates
                 if candidate.get("visible_classification") == preferred),
                sorted(candidates, key=lambda candidate: (
                    str(candidate.get("document")), int(candidate.get("line", 0)),
                    str(candidate.get("target")),
                ))[0],
            )
            resolution = {
                "kind": "EXPLICIT_FILING_DISPOSITION",
                "source_document": selected["document"],
                "source_line": selected["line"],
                "source_target": selected["target"],
                "disposition": selected["disposition"],
                "visible_classification": selected["visible_classification"],
            }
        rows.append({
            "document": current["document"], "line": current["line"],
            "target": current["target"], "resolution": resolution,
        })
    rows.sort(key=lambda row: (row["document"], row["line"], row["target"]))
    kinds = [row["resolution"]["kind"] for row in rows]
    return {
        "schema_version": "ember-current-reference-reconciliation-v1",
        "source": {
            **prior_source,
            "frozen_dispositions_raw_sha256": sha256_file(root / REFERENCE_DISPOSITIONS_PATH),
        },
        "classifiers": {
            "filing_regex": FILING_REFERENCE_RE.pattern,
            "filing_regex_sha256": sha256_bytes(FILING_REFERENCE_RE.pattern.encode("utf-8")),
            "corrected_regex": CORRECTED_REFERENCE_RE.pattern,
            "corrected_regex_sha256": sha256_bytes(CORRECTED_REFERENCE_RE.pattern.encode("utf-8")),
        },
        "counts": {
            "documents": 1 + len(list((root / "docs").rglob("*.md"))),
            "filing_classifier_current_unresolved": len(rows),
            "corrected_classifier_current_unresolved": len(corrected_keys),
            "explicit_filing_dispositions": kinds.count("EXPLICIT_FILING_DISPOSITION"),
            "contained_resolved_canonical_tokens": kinds.count("CONTAINED_RESOLVED_CANONICAL_TOKEN"),
        },
        "rows": rows,
        "rows_sha256": sha256_bytes(canonical_compact(rows)),
    }


def validate_reference_dispositions(root: Path, value: dict[str, Any]) -> list[dict[str, Any]]:
    if value.get("schema_version") != "ember-reference-dispositions-v1":
        raise DocsInfoError("REFERENCE_DISPOSITION_SCHEMA_INVALID")
    census = value.get("source_census")
    if (
        not isinstance(census, dict)
        or census.get("consumer_reference_count") != 2189
        or census.get("unresolved_consumer_reference_count") != 445
        or census.get("raw_sha256")
        != "5a2da304d5f40cc99b6fd23dbdd092866f48eb97a282416ffada52cbf105fce7"
        or census.get("self_sha256")
        != "ad77a19d985a5f7772e04b782900f30b648ee78720c4446d7fc7d38a4a967b04"
    ):
        raise DocsInfoError("REFERENCE_DISPOSITION_CENSUS_INVALID")
    authority = value.get("scope_authority")
    if (
        not isinstance(authority, dict)
        or authority.get("artifact_sha256")
        != "c2eee97ca0ea1f24ef80f5a0a128ac48b88a0632c5a9b774f735648eb8c4fe54"
        or authority.get("artifact_lines") != [221, 221]
    ):
        raise DocsInfoError("REFERENCE_DISPOSITION_AUTHORITY_INVALID")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) != 445:
        raise DocsInfoError("REFERENCE_DISPOSITION_COUNT_INVALID")
    seen: set[tuple[str, int, str]] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "document",
            "line",
            "target",
            "disposition",
            "visible_classification",
        }:
            raise DocsInfoError("REFERENCE_DISPOSITION_ROW_INVALID")
        key = (row["document"], row["line"], row["target"])
        if key in seen:
            raise DocsInfoError(f"REFERENCE_DISPOSITION_DUPLICATE:{key}")
        seen.add(key)
        if row["disposition"] not in REFERENCE_DISPOSITIONS:
            raise DocsInfoError(f"REFERENCE_DISPOSITION_INVALID:{key}")
        if row["disposition"] == "CLASSIFIER_ROW_OUTSIDE_CURRENT_NORMATIVE_ENTRY_SCOPE" and row[
            "visible_classification"
        ] not in {"reference", "historical", "superseded"}:
            raise DocsInfoError(f"REFERENCE_CLASSIFICATION_INVALID:{key}")
        if not (root / str(row["document"])).is_file():
            raise DocsInfoError(f"REFERENCE_DISPOSITION_DOCUMENT_MISSING:{key}")
    expected_sha = sha256_bytes(canonical_json(rows))
    if value.get("row_set_sha256") != expected_sha:
        raise DocsInfoError("REFERENCE_DISPOSITION_ROW_SET_STALE")
    markdown = value.get("markdown_link_dispositions")
    if not isinstance(markdown, list) or len(markdown) != 2:
        raise DocsInfoError("MARKDOWN_LINK_DISPOSITION_COUNT_INVALID")
    expected_links = {
        ("docs/domains/governance/roadmap/README.md", 8, "../../INVARIANT.md", "docs/authority/INVARIANT.md"),
        (
            "docs/domains/governance/roadmap/README.md",
            9,
            "../../GOAL.md",
            "docs/domains/governance/authority/GOAL.md",
        ),
    }
    observed_links = {
        (row.get("document"), row.get("line"), row.get("old_target"), row.get("canonical_target"))
        for row in markdown
        if isinstance(row, dict) and row.get("disposition") == "RESOLVED_AT_CURRENT_HEAD"
    }
    if observed_links != expected_links:
        raise DocsInfoError("MARKDOWN_LINK_DISPOSITION_INVALID")
    for _, _, _, target in observed_links:
        if not (root / target).is_file():
            raise DocsInfoError(f"MARKDOWN_LINK_CANONICAL_TARGET_MISSING:{target}")
    return rows


def public_command_host_argv(
    root: Path, argv: list[str], *, binding: dict[str, str] | None = None,
) -> list[str]:
    if not argv:
        raise DocsInfoError("PUBLIC_COMMAND_ARGV_INVALID")
    if argv[0].lower() not in {"python", "python.exe", "py", "py.exe"}:
        return argv
    if sys.platform != "win32":
        interpreter = binding["resolved_path"] if binding is not None else sys.executable
        return [interpreter, *argv[1:]]
    raw = os.environ.get("EMBER_PUBLIC_PYTHON_LAUNCHER_JSON")
    if not raw:
        raise DocsInfoError("PUBLIC_COMMAND_DIRECT_PYTHON_REFUSED")
    try:
        launcher = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DocsInfoError("PUBLIC_COMMAND_HEADLESS_LAUNCHER_INVALID") from error
    file_index = launcher.index("-File") if isinstance(launcher, list) and "-File" in launcher else -1
    repo_launcher = (root.resolve() / PUBLIC_PYTHON_LAUNCHER_PATH).resolve()
    try:
        repo_launcher.relative_to(root.resolve())
    except ValueError as error:
        raise DocsInfoError("PUBLIC_COMMAND_HEADLESS_LAUNCHER_INVALID") from error
    if (
        not isinstance(launcher, list)
        or not launcher
        or not all(isinstance(value, str) and value for value in launcher)
        or Path(launcher[0]).name.lower() not in {"powershell.exe", "pwsh.exe"}
        or "-NoProfile" not in launcher
        or "-NonInteractive" not in launcher
        or file_index < 0
        or file_index + 1 >= len(launcher)
        or Path(launcher[file_index + 1]).resolve() != repo_launcher
        or not repo_launcher.is_file()
        or sha256_file(repo_launcher) != PUBLIC_PYTHON_LAUNCHER_SHA256
        or launcher[-1] != "--"
    ):
        raise DocsInfoError("PUBLIC_COMMAND_HEADLESS_LAUNCHER_INVALID")
    return [*launcher, *argv[1:]]


def portable_interpreter_relative_path(relative: str) -> Path:
    """Resolve a receipt path without inheriting the producer host's separators."""
    windows_path = PureWindowsPath(relative)
    posix_path = PurePosixPath(relative.replace("\\", "/"))
    if (
        windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.is_absolute()
        or ".." in posix_path.parts
    ):
        raise DocsInfoError("PUBLIC_COMMAND_INTERPRETER_OUTSIDE_CHECKOUT_REFUSED")
    parts = tuple(part for part in posix_path.parts if part not in {"", "."})
    if not parts:
        raise DocsInfoError("PUBLIC_COMMAND_INTERPRETER_BINDING_INVALID")
    return Path(*parts)


def load_public_interpreter_binding(root: Path) -> dict[str, str]:
    """Resolve only the self-hashed interpreter bound by bootstrap custody."""
    receipt_path = root.resolve() / PUBLIC_INTERPRETER_RECEIPT_PATH
    if not receipt_path.is_file():
        raise DocsInfoError("PUBLIC_COMMAND_INTERPRETER_RECEIPT_MISSING")
    receipt = load_json(receipt_path)
    claimed = receipt.pop("self_sha256", None)
    if not isinstance(claimed, str) or not re.fullmatch(r"[0-9a-f]{64}", claimed):
        raise DocsInfoError("PUBLIC_COMMAND_INTERPRETER_RECEIPT_SELF_HASH_INVALID")
    if sha256_bytes(canonical_compact(receipt)) != claimed:
        raise DocsInfoError("PUBLIC_COMMAND_INTERPRETER_RECEIPT_SELF_HASH_INVALID")
    if (
        receipt.get("schema_version") != "ember-python-environment-install-receipt-v1"
        or receipt.get("result") != "PASS"
        or not isinstance(receipt.get("identity"), dict)
    ):
        raise DocsInfoError("PUBLIC_COMMAND_INTERPRETER_RECEIPT_NOT_PASS")
    binding = receipt["identity"].get("isolated_interpreter")
    if not isinstance(binding, dict) or set(binding) != {
        "path", "python_version", "package_set_sha256",
    }:
        raise DocsInfoError("PUBLIC_COMMAND_INTERPRETER_BINDING_INVALID")
    relative = binding.get("path")
    if (
        not isinstance(relative, str)
        or not relative
        or not isinstance(binding.get("python_version"), str)
        or not binding["python_version"]
        or not isinstance(binding.get("package_set_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", binding["package_set_sha256"])
    ):
        raise DocsInfoError("PUBLIC_COMMAND_INTERPRETER_BINDING_INVALID")
    relative_path = portable_interpreter_relative_path(relative)
    checkout_root = root.resolve()
    interpreter = checkout_root / relative_path
    try:
        interpreter.relative_to(checkout_root)
    except ValueError as error:
        raise DocsInfoError("PUBLIC_COMMAND_INTERPRETER_OUTSIDE_CHECKOUT_REFUSED") from error
    if not interpreter.is_file():
        raise DocsInfoError("PUBLIC_COMMAND_INTERPRETER_MISSING")
    return {
        "path": relative,
        "python_version": binding["python_version"],
        "package_set_sha256": binding["package_set_sha256"],
        "resolved_path": str(interpreter),
    }


def run_public_commands(root: Path, commands: dict[str, Any]) -> list[dict[str, Any]]:
    rows = commands.get("commands")
    if not isinstance(rows, list):
        raise DocsInfoError("PUBLIC_COMMAND_SET_INVALID")
    results = []
    for row in rows:
        manifest_argv = [str(value) for value in row.get("argv", [])]
        cwd = (root / str(row.get("cwd", "."))).resolve()
        command_id = str(row.get("id", ""))
        binding = None
        environment = None
        if manifest_argv and manifest_argv[0].lower() in {"python", "python.exe", "py", "py.exe"} and command_id != "bootstrap-python":
            binding = load_public_interpreter_binding(root)
            if sys.platform == "win32":
                environment = os.environ.copy()
                environment["CODEX_PYTHON"] = binding["resolved_path"]
        host_argv = public_command_host_argv(root, manifest_argv, binding=binding)
        run_kwargs = {}
        if environment is not None:
            run_kwargs["env"] = environment
        completed = subprocess.run(
            host_argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            creationflags=NO_WINDOW,
            **run_kwargs,
        )
        if command_id == "bootstrap-python" and completed.returncode == 0:
            binding = load_public_interpreter_binding(root)
        result = {
            "id": row.get("id"),
            "manifest_argv": manifest_argv,
            "host_argv": host_argv,
            "host_argv_sha256": sha256_bytes(canonical_json(host_argv)),
            "cwd": str(cwd),
            "returncode": completed.returncode,
            "stdout_sha256": sha256_bytes(completed.stdout.encode("utf-8")),
            "stderr_sha256": sha256_bytes(completed.stderr.encode("utf-8")),
            "interpreter_binding": (
                {key: binding[key] for key in ("path", "python_version", "package_set_sha256")}
                if binding is not None else None
            ),
        }
        results.append(result)
        if completed.returncode != 0:
            raise DocsInfoError(f"PUBLIC_COMMAND_FAILED:{row.get('id')}:{completed.returncode}")
    return results


def score_reader_study(study: dict[str, Any]) -> dict[str, Any]:
    if study.get("schema_version") != "ember-doc-reader-study-v2":
        raise DocsInfoError("READER_STUDY_SCHEMA_INVALID")
    if study.get("instrument_sha256") != READER_INSTRUMENT_SHA256:
        raise DocsInfoError("READER_STUDY_INSTRUMENT_INVALID")
    questions = study.get("questions")
    readers = study.get("readers")
    if not isinstance(questions, list) or len(questions) != 8 or len(set(questions)) != 8:
        raise DocsInfoError("READER_QUESTION_SET_INVALID")
    if not isinstance(readers, list) or len(readers) != 2:
        raise DocsInfoError("READER_SAMPLE_INVALID")
    correct = 0
    reader_ids: set[str] = set()
    elapsed: dict[str, int] = {}
    for reader in readers:
        reader_id = reader.get("reader_id")
        if not isinstance(reader_id, str) or not reader_id:
            raise DocsInfoError("READER_ELIGIBILITY_INVALID")
        if sha256_bytes(reader_id.encode("utf-8")) in PREDECESSOR_READER_ID_SHA256S:
            raise DocsInfoError("READER_ID_REUSE_REFUSED")
        if not reader.get("eligible") or reader.get("authored_prose") or reader_id in reader_ids:
            raise DocsInfoError("READER_ELIGIBILITY_INVALID")
        reader_ids.add(reader_id)
        answers = reader.get("answers")
        if not isinstance(answers, dict) or set(answers) != set(questions):
            raise DocsInfoError("READER_STUDY_INCOMPLETE")
        if reader.get("unexplained_blocking_terms"):
            raise DocsInfoError("READER_STUDY_INCOMPLETE")
        for question in questions:
            if answers[question].get("materially_correct") is not True:
                raise DocsInfoError("READER_STUDY_INCOMPLETE")
            correct += 1
        elapsed[str(reader_id)] = int(reader.get("elapsed_seconds", 0))
    return {
        "schema_version": "ember-doc-reader-study-receipt-v2",
        "result": "PASS",
        "reader_count": 2,
        "question_count": 8,
        "correct_answers": correct,
        "blocking_terms": 0,
        "elapsed_seconds": elapsed,
    }


def check_repository(root: Path, *, run_commands: bool) -> dict[str, Any]:
    root = root.resolve()
    metadata = load_json(root / METADATA_PATH)
    claims_value = load_json(root / CLAIM_MAP_PATH)
    commands_value = load_json(root / COMMANDS_PATH)
    question_destinations = load_json(root / QUESTION_DESTINATIONS_PATH)
    reference_dispositions = load_json(root / REFERENCE_DISPOSITIONS_PATH)
    current_reference_reconciliation = load_json(
        root / CURRENT_REFERENCE_RECONCILIATION_PATH
    )
    reader_instrument = load_json(root / READER_INSTRUMENT_PATH)
    authority = load_json(root / DOMAIN_AUTHORITY_PATH)
    rows = validate_metadata(root, metadata)
    claims = validate_claim_map(root, claims_value)
    readme_counts = validate_readme(root / "README.md")
    domains = validate_domains(root, rows, authority)
    retired = metadata.get("retired_paths", [])
    if not isinstance(retired, list):
        raise DocsInfoError("RETIRED_PATHS_INVALID")
    references = validate_references(root, rows, retired)
    commands = validate_commands_manifest(commands_value)
    validate_public_command_docs(root, commands)
    validate_reader_instrument(root, reader_instrument)
    destinations = validate_question_destinations(root, question_destinations, rows, reader_instrument)
    dispositions = validate_reference_dispositions(root, reference_dispositions)
    current_reconciliation = validate_current_reference_reconciliation(
        root, current_reference_reconciliation, reference_dispositions
    )
    expected_index = render_index(metadata)
    index_path = root / INDEX_PATH
    if not index_path.is_file() or index_path.read_text(encoding="utf-8") != expected_index:
        raise DocsInfoError("GENERATED_INDEX_STALE")
    command_results = run_public_commands(root, commands_value) if run_commands else []
    return {
        "schema_version": "ember-doc-information-system-receipt-v1",
        "result": "PASS",
        "metadata_document_count": len(rows),
        "claim_count": len(claims),
        "domain_count": len(domains),
        "public_command_count": len(commands),
        "question_destination_count": len(destinations),
        "reference_disposition_count": len(dispositions),
        "current_reference_reconciliation_count": len(current_reconciliation),
        "commands_executed": len(command_results),
        "command_results": command_results,
        **readme_counts,
        **references,
        "metadata_raw_sha256": sha256_file(root / METADATA_PATH),
        "claim_map_raw_sha256": sha256_file(root / CLAIM_MAP_PATH),
        "command_manifest_raw_sha256": sha256_file(root / COMMANDS_PATH),
        "question_destinations_raw_sha256": sha256_file(root / QUESTION_DESTINATIONS_PATH),
        "reference_dispositions_raw_sha256": sha256_file(root / REFERENCE_DISPOSITIONS_PATH),
        "current_reference_reconciliation_raw_sha256": sha256_file(
            root / CURRENT_REFERENCE_RECONCILIATION_PATH
        ),
        "reader_instrument_raw_sha256": sha256_file(root / READER_INSTRUMENT_PATH),
        "generated_index_sha256": sha256_file(index_path),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "command",
        choices=["generate", "check", "score-study", "reconcile-references"],
    )
    value.add_argument("--root", type=Path, default=Path("."))
    value.add_argument("--run-commands", action="store_true")
    value.add_argument("--study", type=Path)
    value.add_argument("--output", type=Path)
    return value


def write_final_receipt(output: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    finalized = dict(receipt)
    finalized["self_sha256"] = sha256_bytes(canonical_json(finalized))
    write_new(output, canonical_json(finalized))
    return finalized


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        root = arguments.root.resolve()
        if arguments.command == "generate":
            metadata = load_json(root / METADATA_PATH)
            output = root / INDEX_PATH
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(render_index(metadata), encoding="utf-8", newline="\n")
            receipt: dict[str, Any] = {"result": "GENERATED", "path": str(INDEX_PATH)}
        elif arguments.command == "check":
            receipt = check_repository(root, run_commands=arguments.run_commands)
            if arguments.output is not None:
                receipt = write_final_receipt(arguments.output, receipt)
        elif arguments.command == "reconcile-references":
            if arguments.output is None:
                raise DocsInfoError("OUTPUT_REQUIRED")
            receipt = build_current_reference_reconciliation(
                root,
                load_json(root / REFERENCE_DISPOSITIONS_PATH),
                load_json(root / CURRENT_REFERENCE_RECONCILIATION_PATH),
            )
            write_new(
                arguments.output,
                json.dumps(
                    receipt, indent=2, sort_keys=True, ensure_ascii=False
                ).encode("utf-8") + b"\n",
            )
        else:
            if arguments.study is None or arguments.output is None:
                raise DocsInfoError("STUDY_AND_OUTPUT_REQUIRED")
            receipt = score_reader_study(load_json(arguments.study))
            receipt["study_raw_sha256"] = sha256_file(arguments.study)
            receipt["self_sha256"] = sha256_bytes(canonical_json(receipt))
            write_new(arguments.output, canonical_json(receipt))
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0
    except (DocsInfoError, OSError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
