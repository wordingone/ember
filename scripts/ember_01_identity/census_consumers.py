#!/usr/bin/env python3
# goal_id: EMBER-01
# workstream_id: EMBER-01C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build a deterministic, evidence-linked census of Ember identity surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Iterable


SCHEMA = "ember-identity-consumer-census-v1"
GOAL_ID = "EMBER-01"
WORKSTREAM_ID = "EMBER-01C"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cu",
    ".h",
    ".hpp",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".ps1",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
EXECUTABLE_SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cu", ".h", ".hpp", ".js", ".ps1", ".py", ".rs", ".sh", ".ts", ".tsx"
}
DISCOVERY_EXCLUDED_DIRS = {
    ".git", ".pytest_cache", "__pycache__", "node_modules", "target", ".venv", "venv"
}

EXCLUDED_PREFIXES = (
    ".git/",
    "node_modules/",
)
EXCLUDED_PATHS = {
    "manifests/ember-01-identity/consumer-census-v1.json",
    "manifests/ember-01-identity/consumer-census-stability-v1.json",
}

CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "architecture_config": (
        r"\b(?:LlamaConfig|AutoConfig|model_config|architecture(?:_id|_hash)?|hidden_size|intermediate_size|num_hidden_layers)\b",
    ),
    "training_optimizer": (
        r"\b(?:optimizer(?:_state)?|effective_tokens|trained_tokens|training_steps|global_step|backward\(|\.step\(\))\b",
    ),
    "checkpoint_save_load": (
        r"\b(?:torch\.save|torch\.load|save_pretrained|from_pretrained|load_state_dict|state_dict|checkpoint(?:_[a-z0-9]+)*)\b",
    ),
    "serving_runtime": (
        r"\b(?:EMBER_MODEL_URL|serving[-_]registry|model_path|llama-server|brain[-_]server|/v1/models|/v1/chat/completions|serverUrl|model endpoint)\b",
    ),
    "cli_operator_surface": (
        r"\b(?:LOCAL_MODEL_ID|EMBER_MODEL_NAME|models\.json|modelName|model loaded|model unloaded|model endpoint|provider)\b",
    ),
    "evaluation_benchmark": (
        r"\b(?:benchmark_id|benchmark[-_]name|subject_checkpoint|comparator|counts_toward|completion_count|eval(?:uation)?_result|score)\b",
    ),
    "publication_report": (
        r"\b(?:model[-_ ]card|research[-_ ]paper|paper(?:_path|_id|_draft)?|recorded[-_ ]demo|demo(?:_path|_id)?|dashboard)\b",
    ),
    "borrowed_reference": (
        r"\b(?:qwen|reference_only|borrowed_reference|frozen_reference|reference server)\b",
    ),
    "process_registry_watchdog": (
        r"\b(?:planned[-_]outage|watchdog|process_identity|resource_lease|pid|launched_by|kill_receipt)\b",
    ),
    "parameter_identity": (
        r"\b(?:parameter_count|param_count|total_parameters|unique_parameters|active_parameters|trainable_parameters|served_parameters|actually_trained)\b",
    ),
    "tokenizer_data_lineage": (
        r"\b(?:tokenizer(?:_path|_id|_hash)?|corpus(?:_id|_hash)?|curriculum|sample_order|data_lineage|clean_genesis)\b",
    ),
    "mechanism_identity": (
        r"\b(?:expert(?:_id|_bank)?|router|adapter|lora|upcycl[a-z]*|memory(?:_|\s)+(?:substrate|system)|world(?:_|\s)+model|dream(?:ing)?(?:_|\s)+loop|verified(?:_|\s)+experience(?:_|\s)+update|deletion(?:_|\s)+(?:object|test)|mechanism_id)\b",
    ),
    "receipt_identity": (
        r"\b(?:receipt(?:_[a-z0-9]+)*|evidence_receipts)\b",
    ),
}

COMPILED = {
    category: tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)
    for category, patterns in CATEGORY_PATTERNS.items()
}

INTEGRATION_REQUIREMENTS = {
    "unclassified_file": "treat as identity-affecting until EMBER-01A proves and binds its exact role",
    "architecture_config": "bind canonical architecture bytes and reject inferred identity",
    "training_optimizer": "bind optimizer, numerics, ordering, update set, and checkpoint ancestry",
    "checkpoint_save_load": "validate full identity before save, load, conversion, recovery, or merge",
    "serving_runtime": "bind server identity to verified checkpoint and executable bytes",
    "cli_operator_surface": "render disposition and checkpoint identity; fail closed when absent",
    "evaluation_benchmark": "bind exact subject, comparator, harness, split, result, uncertainty, and receipt",
    "publication_report": "generate publication claims only from validated manifests and receipts",
    "borrowed_reference": "force REFERENCE_ONLY and prohibit lineage or completion credit",
    "process_registry_watchdog": "derive runtime state from manifest-bound control-plane authority",
    "parameter_identity": "emit all six parameter axes from independently verified evidence",
    "tokenizer_data_lineage": "bind tokenizer, corpus, order, curriculum, verifier, and provenance bytes",
    "mechanism_identity": "bind mechanism bytes, state transitions, merge ancestry, and deletion evidence",
    "receipt_identity": "resolve content-addressed receipts and bind them to the exact checkpoint, verifier, evidence class, and result",
}
SEMANTIC_PROFILES = {
    category: {
        "derived_label": category.replace("_", " ") + " identity or claim",
        "protocol": "source-line identity marker protocol",
        "failure_behavior": "consumer may infer, default, preserve, or fail without full artifact identity",
        "claim_effect": "may affect identity, capability, progress, serving, or completion claims",
        "conflict": "local metadata or operational state can be mistaken for checkpoint-bound neural truth",
        "integration_requirement": requirement,
    }
    for category, requirement in INTEGRATION_REQUIREMENTS.items()
}


SEMANTIC_FIELDS = {
    "current_input", "derived_label", "protocol", "failure_behavior",
    "claim_effect", "conflict", "integration_requirement",
}


def _semantic_fields(
    category: str,
    matched_terms: list[str],
    *,
    exact: dict[str, str] | None,
    line_scoped: bool,
    source_role: str,
) -> dict[str, str]:
    if exact is not None:
        return {"record_class": "VERIFIED_CONSUMER", **exact}
    return {
        "record_class": (
            "CANDIDATE_EXECUTABLE_MATCH" if line_scoped else "CANDIDATE_EVIDENCE_MATCH"
        ),
        "current_input": ",".join(matched_terms),
        "review_state": "UNADJUDICATED",
        "claim_effect": "NO_CREDIT",
        "integration_requirement": INTEGRATION_REQUIREMENTS[category],
    }


def _excluded(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    name = Path(normalized).name.lower()
    return (
        any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES)
        or normalized in EXCLUDED_PATHS
    )


def _source_role(rel: str) -> str:
    normalized = rel.replace("\\", "/").lower()
    suffix = Path(normalized).suffix
    if suffix in EXECUTABLE_SOURCE_SUFFIXES:
        return "EXECUTABLE_CANDIDATE"
    if suffix not in SOURCE_SUFFIXES:
        return "OPAQUE_FILE"
    if suffix in {".md", ".rst", ".txt"}:
        return "DOCUMENTATION_EVIDENCE"
    return "DATA_EVIDENCE"


def _public_path(relative: str, redactions: Iterable[str]) -> str:
    rendered = relative
    for term in sorted({item for item in redactions if item}, key=str.casefold):
        token = "{redacted-" + hashlib.sha256(term.casefold().encode("utf-8")).hexdigest()[:12] + "}"
        pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
        rendered = re.sub(pattern, token, rendered, flags=re.IGNORECASE)
    return rendered


def tracked_files(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip())
    return sorted(
        raw.decode("utf-8", errors="strict")
        for raw in completed.stdout.split(b"\0")
        if raw
    )


def discover_filesystem_sources(
    root: Path, *, include_prefixes: Iterable[str] | None = None
) -> tuple[list[str], list[dict[str, str]]]:
    """Discover source files without following links or exposing the host root."""
    root = root.resolve()
    if not root.exists():
        return [], [{"path": ".", "error_class": "FileNotFoundError"}]
    files: list[str] = []
    errors: list[dict[str, str]] = []
    includes = tuple(
        sorted({prefix.replace("\\", "/") for prefix in include_prefixes or []})
    )
    pending: list[tuple[Path, str]] = [(root, "")]
    while pending:
        directory, relative = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name.casefold())
        except OSError as exc:
            errors.append({"path": relative or ".", "error_class": type(exc).__name__})
            continue
        for entry in reversed(entries):
            child_relative = f"{relative}/{entry.name}" if relative else entry.name
            normalized = child_relative.replace("\\", "/")
            try:
                if entry.is_symlink():
                    errors.append({"path": normalized, "error_class": "SymlinkSkipped"})
                elif entry.is_dir(follow_symlinks=False):
                    directory_prefix = normalized.rstrip("/") + "/"
                    if (
                        entry.name not in DISCOVERY_EXCLUDED_DIRS
                        and not any(directory_prefix.startswith(prefix) for prefix in EXCLUDED_PREFIXES)
                    ):
                        pending.append((Path(entry.path), normalized))
                elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in SOURCE_SUFFIXES:
                    if not includes or any(
                        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
                        for prefix in includes
                    ):
                        files.append(normalized)
            except OSError as exc:
                errors.append({"path": normalized, "error_class": type(exc).__name__})
    return sorted(files), sorted(errors, key=lambda row: (row["path"], row["error_class"]))


def filesystem_source_id(root: Path, files: Iterable[str], errors: list[dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(set(files)):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            with (root / relative).open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            digest.update(type(exc).__name__.encode("ascii", errors="replace"))
        digest.update(b"\0")
    digest.update(json.dumps(errors, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def source_commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    commit = completed.stdout.strip().lower()
    if completed.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise RuntimeError("unable to bind census to an exact source commit")
    return commit


def _git_tree_files(root: Path, commit: str) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--name-only", commit],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip())
    return sorted(
        item.decode("utf-8", errors="strict")
        for item in completed.stdout.split(b"\0")
        if item
    )


def _git_blob_contents(root: Path, commit: str, paths: Iterable[str]) -> dict[str, bytes]:
    ordered = list(paths)
    if not ordered:
        return {}
    queries = "".join(f"{commit}:{path}\n" for path in ordered).encode("utf-8")
    completed = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input=queries,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip())
    output = completed.stdout
    offset = 0
    contents: dict[str, bytes] = {}
    for path in ordered:
        line_end = output.find(b"\n", offset)
        if line_end < 0:
            raise RuntimeError(f"truncated git cat-file header for {path}")
        header = output[offset:line_end].decode("utf-8", errors="replace")
        offset = line_end + 1
        parts = header.rsplit(" ", 2)
        if len(parts) != 3 or parts[1] != "blob" or not parts[2].isdigit():
            raise RuntimeError(f"unable to resolve committed blob for {path}: {header}")
        size = int(parts[2])
        contents[path] = output[offset : offset + size]
        offset += size
        if output[offset : offset + 1] != b"\n":
            raise RuntimeError(f"invalid git cat-file delimiter for {path}")
        offset += 1
    return contents


def build_census(
    root: Path,
    *,
    tracked_files: Iterable[str] | None = None,
    source_commit: str | None = None,
    root_id: str = "public-master",
    surface: str = "public",
    source_contents: dict[str, bytes] | None = None,
    path_redactions: Iterable[str] = (),
    consumer_semantics: Iterable[dict[str, str]] = (),
) -> dict:
    root = root.resolve()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", root_id):
        raise ValueError("root_id must be a stable logical identifier")
    if surface not in {"public", "private", "live-local", "archive"}:
        raise ValueError("unsupported identity surface")
    bound_commit = source_commit if source_commit is not None else globals()["source_commit"](root)
    if not re.fullmatch(r"[0-9a-f]{40,64}", bound_commit):
        raise ValueError("source_commit must be an exact hexadecimal Git object ID")
    candidates = sorted(set(tracked_files if tracked_files is not None else globals()["tracked_files"](root)))
    evidence: list[dict[str, object]] = []
    scanned = 0
    excluded = 0
    evidence_files: set[str] = set()
    category_files: dict[str, set[str]] = {
        category: set() for category in INTEGRATION_REQUIREMENTS
    }
    raw_match_counts: dict[str, int] = {category: 0 for category in COMPILED}
    semantics_index: dict[tuple[str, str, str, str], dict[str, str]] = {}
    matched_semantics: set[tuple[str, str, str, str]] = set()
    for row in consumer_semantics:
        required_semantic_keys = {
            "root_id", "path", "category", "evidence_sha256", *SEMANTIC_FIELDS
        }
        if (
            not isinstance(row, dict)
            or set(row) not in (required_semantic_keys, required_semantic_keys | {"consumer_id"})
        ):
            raise ValueError("consumer semantics rows use a closed schema")
        if not re.fullmatch(r"[0-9a-f]{64}", row["evidence_sha256"]):
            raise ValueError("consumer semantics evidence_sha256 must be exact")
        key = (row["root_id"], row["path"], row["category"], row["evidence_sha256"])
        if key in semantics_index:
            raise ValueError(f"duplicate consumer semantics row: {key}")
        semantics_index[key] = {
            **({"consumer_id": row["consumer_id"]} if "consumer_id" in row else {}),
            **{field: row[field] for field in SEMANTIC_FIELDS},
        }

    for raw_rel in candidates:
        rel = raw_rel.replace("\\", "/")
        public_rel = _public_path(rel, path_redactions)
        path_sha256 = hashlib.sha256(rel.encode("utf-8")).hexdigest()
        path = root / rel
        if _excluded(rel):
            excluded += 1
            continue
        if source_contents is None and not path.is_file():
            continue
        scanned += 1
        try:
            if source_contents is None:
                content_bytes = path.read_bytes()
            else:
                content_bytes = source_contents[rel]
        except (KeyError, OSError):
            scanned -= 1
            continue
        content_sha256 = hashlib.sha256(content_bytes).hexdigest()
        source_role = _source_role(rel)
        if source_role == "OPAQUE_FILE":
            evidence.append({
                "category": "unclassified_file",
                "root_id": root_id,
                "surface": surface,
                "path": public_rel,
                "path_sha256": path_sha256,
                "line": 0,
                "line_sha256": content_sha256,
                "content_sha256": content_sha256,
                "evidence_scope": "WHOLE_FILE",
                "source_role": source_role,
                "matched_terms": [],
                **_semantic_fields(
                    "unclassified_file", [], exact=None, line_scoped=False,
                    source_role=source_role,
                ),
            })
            evidence_files.add(public_rel)
            category_files["unclassified_file"].add(public_rel)
            continue
        try:
            text_content = content_bytes.decode("utf-8")
            lines = text_content.splitlines()
        except UnicodeDecodeError:
            evidence.append({
                "category": "unclassified_file",
                "root_id": root_id,
                "surface": surface,
                "path": public_rel,
                "path_sha256": path_sha256,
                "line": 0,
                "line_sha256": content_sha256,
                "content_sha256": content_sha256,
                "evidence_scope": "WHOLE_FILE",
                "source_role": "OPAQUE_FILE",
                "matched_terms": [],
                **_semantic_fields(
                    "unclassified_file", [], exact=None, line_scoped=False,
                    source_role="OPAQUE_FILE",
                ),
            })
            evidence_files.add(public_rel)
            category_files["unclassified_file"].add(public_rel)
            continue
        line_scoped = Path(rel).suffix.lower() in EXECUTABLE_SOURCE_SUFFIXES
        file_matches: dict[str, dict[str, object]] = {}
        matched_categories: set[str] = set()
        for line_number, line in enumerate(lines, start=1):
            excerpt = line.strip()
            if not excerpt:
                continue
            for category, patterns in COMPILED.items():
                matched_terms = sorted(
                    {
                        match.group(0)
                        for pattern in patterns
                        for match in pattern.finditer(line)
                    },
                    key=lambda value: (value.casefold(), value),
                )
                if matched_terms:
                    raw_match_counts[category] += 1
                    matched_categories.add(category)
                    line_sha256 = hashlib.sha256(line.encode("utf-8")).hexdigest()
                    if line_scoped:
                        semantic_key = (root_id, public_rel, category, line_sha256)
                        exact_semantics = semantics_index.get(semantic_key)
                        if exact_semantics is not None:
                            matched_semantics.add(semantic_key)
                        evidence.append(
                            {
                                "category": category,
                                "root_id": root_id,
                                "surface": surface,
                                "path": public_rel,
                                "path_sha256": path_sha256,
                                "line": line_number,
                                "line_sha256": line_sha256,
                                "content_sha256": content_sha256,
                                "evidence_scope": "LINE",
                                "source_role": source_role,
                                "matched_terms": matched_terms,
                                **_semantic_fields(
                                    category,
                                    matched_terms,
                                    exact=exact_semantics,
                                    line_scoped=True,
                                    source_role=source_role,
                                ),
                            }
                        )
                    else:
                        record = file_matches.setdefault(
                            category,
                            {"line": line_number, "line_sha256": line_sha256, "matched_terms": set()},
                        )
                        record["matched_terms"].update(matched_terms)
        for category, record in sorted(file_matches.items()):
            matched_terms = sorted(
                record["matched_terms"], key=lambda value: (value.casefold(), value)
            )
            semantic_key = (root_id, public_rel, category, content_sha256)
            exact_semantics = semantics_index.get(semantic_key)
            if exact_semantics is not None:
                matched_semantics.add(semantic_key)
            evidence.append(
                {
                    "category": category,
                    "root_id": root_id,
                    "surface": surface,
                    "path": public_rel,
                    "path_sha256": path_sha256,
                    "line": record["line"],
                    "line_sha256": record["line_sha256"],
                    "content_sha256": content_sha256,
                    "evidence_scope": "FILE_CATEGORY",
                    "source_role": source_role,
                    "matched_terms": matched_terms,
                    **_semantic_fields(
                        category,
                        matched_terms,
                        exact=exact_semantics,
                        line_scoped=False,
                        source_role=source_role,
                    ),
                }
            )
        if not matched_categories:
            evidence.append({
                "category": "unclassified_file",
                "root_id": root_id,
                "surface": surface,
                "path": public_rel,
                "path_sha256": path_sha256,
                "line": 0,
                "line_sha256": content_sha256,
                "content_sha256": content_sha256,
                "evidence_scope": "WHOLE_FILE",
                "source_role": source_role,
                "matched_terms": [],
                **_semantic_fields(
                    "unclassified_file", [], exact=None, line_scoped=False,
                    source_role=source_role,
                ),
            })
            matched_categories.add("unclassified_file")
        if matched_categories:
            evidence_files.add(public_rel)
            for category in matched_categories:
                category_files[category].add(public_rel)

    evidence.sort(key=lambda row: (str(row["path"]), int(row["line"]), str(row["category"])))
    unmatched_semantics = sorted(set(semantics_index) - matched_semantics)
    if unmatched_semantics:
        raise ValueError(f"consumer semantics rows did not resolve: {unmatched_semantics}")
    categories = {
        category: {
            "files": sorted(paths),
            "file_count": len(paths),
            "evidence_count": sum(1 for row in evidence if row["category"] == category),
            "raw_match_count": raw_match_counts.get(category, 0),
        }
        for category, paths in sorted(category_files.items())
    }
    return {
        "schema": SCHEMA,
        "root_id": root_id,
        "surface": surface,
        "source_commit": bound_commit,
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "coverage": {
            "tracked_candidates": len(candidates),
            "files_scanned": scanned,
            "files_excluded": excluded,
            "files_with_identity_evidence": len(evidence_files),
            "files_accounted": scanned + excluded,
            "identity_evidence_rows": len(evidence),
            "exclusion_prefixes": list(EXCLUDED_PREFIXES),
            "source_suffixes": ["ALL_TRACKED_FILES"],
        },
        "categories": categories,
        "semantic_profiles": SEMANTIC_PROFILES,
        "evidence": evidence,
    }


def build_git_census(
    root: Path, *, source_commit: str, root_id: str, surface: str,
    path_redactions: Iterable[str] = (),
    consumer_semantics: Iterable[dict[str, str]] = (),
) -> dict:
    candidates = _git_tree_files(root, source_commit)
    source_paths = [path for path in candidates if not _excluded(path)]
    contents = _git_blob_contents(root, source_commit, source_paths)
    return build_census(
        root,
        tracked_files=candidates,
        source_commit=source_commit,
        root_id=root_id,
        surface=surface,
        source_contents=contents,
        path_redactions=path_redactions,
        consumer_semantics=consumer_semantics,
    )


def _apply_adjudication_policy(
    evidence: list[dict[str, object]],
    roots: list[dict[str, object]],
    policy: dict | None,
) -> None:
    if policy is None:
        return
    expected_roles = {
        "EXECUTABLE_CANDIDATE": "CONSERVATIVE_CONSUMER",
        "DOCUMENTATION_EVIDENCE": "REVIEWED_IDENTITY_SOURCE",
        "DATA_EVIDENCE": "REVIEWED_IDENTITY_SOURCE",
        "OPAQUE_FILE": "CONSERVATIVE_CONSUMER",
    }
    if (
        not isinstance(policy, dict)
        or set(policy) != {"schema", "policy_id", "root_id", "source_commit", "roles"}
        or policy.get("schema") != "ember-conservative-candidate-adjudication-v1"
        or policy.get("policy_id") != "fail-closed-static-superset-v1"
        or policy.get("roles") != expected_roles
        or not isinstance(policy.get("root_id"), str)
        or not re.fullmatch(r"[0-9a-f]{40,64}", str(policy.get("source_commit")))
    ):
        raise ValueError("candidate adjudication policy is invalid")
    matching_roots = [
        row for row in roots
        if row["root_id"] == policy["root_id"]
        and row["source_commit"] == policy["source_commit"]
    ]
    if len(matching_roots) != 1:
        raise ValueError("candidate adjudication policy is not bound to an exact census root")
    for row in evidence:
        if (
            row["root_id"] != policy["root_id"]
            or row.get("record_class") == "VERIFIED_CONSUMER"
        ):
            continue
        source_role = str(row["source_role"])
        if source_role not in expected_roles:
            raise ValueError(f"candidate adjudication has no closed role rule: {source_role}")
        row["record_class"] = expected_roles[source_role]
        row["review_state"] = "POLICY_ADJUDICATED"
        row["review_basis"] = policy["policy_id"]
        row["claim_effect"] = "NO_CREDIT"
        row["derived_label"] = (
            "FAIL_CLOSED_CONSERVATIVE_CONSUMER"
            if row["record_class"] == "CONSERVATIVE_CONSUMER"
            else "CONTENT_BOUND_IDENTITY_SOURCE"
        )
        row["protocol"] = "STATIC_FILE_INVENTORY_NOT_RUNTIME_VERIFIED"
        row["failure_behavior"] = (
            "MUST_NOT_AFFECT_ADMITTED_IDENTITY_UNTIL_EXPLICITLY_BOUND"
        )
        row["conflict"] = (
            "CONSERVATIVE_CLASSIFICATION_MAY_OVERAPPROXIMATE_BUT_CANNOT_OMIT"
        )


def summarize_snapshot_adjudication(payload: object, policy: object) -> dict:
    expected_roles = {
        "EXECUTABLE_CANDIDATE": "CONSERVATIVE_CONSUMER",
        "DOCUMENTATION_EVIDENCE": "REVIEWED_IDENTITY_SOURCE",
        "DATA_EVIDENCE": "REVIEWED_IDENTITY_SOURCE",
        "OPAQUE_FILE": "CONSERVATIVE_CONSUMER",
    }
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("evidence"), list)
        or not isinstance(policy, dict)
        or set(policy) != {
            "schema", "policy_id", "snapshot_sha256", "roles",
            "adjudication_counts", "unadjudicated_count",
            "global_consumer_completeness",
        }
        or policy.get("schema") != "ember-snapshot-adjudication-overlay-v1"
        or policy.get("policy_id") != "fail-closed-static-superset-v1"
        or not re.fullmatch(r"[0-9a-f]{64}", str(policy.get("snapshot_sha256")))
        or policy.get("roles") != expected_roles
    ):
        raise ValueError("snapshot adjudication overlay is invalid")
    counts: Counter[str] = Counter()
    for row in payload["evidence"]:
        if not isinstance(row, dict):
            raise ValueError("snapshot evidence row is invalid")
        if row.get("record_class") == "VERIFIED_CONSUMER":
            continue
        path = row.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("snapshot evidence path is invalid")
        source_role = _source_role(path)
        counts[expected_roles[source_role]] += 1
    result = {
        "adjudication_counts": dict(sorted(counts.items())),
        "unadjudicated_count": 0,
        "global_consumer_completeness": "ENVIRONMENTAL_DISCOVERY_ONLY",
    }
    if any(policy[key] != value for key, value in result.items()):
        raise ValueError("snapshot adjudication overlay counts do not replay")
    return result


def build_census_set(
    root_specs: Iterable[dict],
    *,
    consumer_semantics: Iterable[dict[str, str]] = (),
    adjudication_policy: dict | None = None,
) -> dict:
    """Combine logical public/private/live roots without serializing host paths."""
    built: list[dict] = []
    seen: set[str] = set()
    semantics = list(consumer_semantics)
    for spec in root_specs:
        root_id = spec["root_id"]
        if root_id in seen:
            raise ValueError(f"duplicate root_id: {root_id}")
        seen.add(root_id)
        root_semantics = [row for row in semantics if row.get("root_id") == root_id]
        root_path = Path(spec["root"])
        discovery_errors: list[dict[str, str]] = []
        tracked = spec.get("tracked_files")
        bound_source = spec.get("source_commit")
        if spec.get("mode", "git") == "filesystem":
            tracked, discovery_errors = discover_filesystem_sources(
                root_path, include_prefixes=spec.get("include_prefixes")
            )
            bound_source = filesystem_source_id(root_path, tracked, discovery_errors)
        if spec.get("mode", "git") == "git" and tracked is None:
            row = build_git_census(
                root_path,
                source_commit=bound_source or globals()["source_commit"](root_path),
                root_id=root_id,
                surface=spec["surface"],
                path_redactions=spec.get("path_redactions", ()),
                consumer_semantics=root_semantics,
            )
        else:
            row = build_census(
                root_path,
                tracked_files=tracked,
                source_commit=bound_source,
                root_id=root_id,
                surface=spec["surface"],
                path_redactions=spec.get("path_redactions", ()),
                consumer_semantics=root_semantics,
            )
        row["discovery_errors"] = discovery_errors
        row["availability"] = "MISSING" if any(
            error["path"] == "." and error["error_class"] == "FileNotFoundError"
            for error in discovery_errors
        ) else ("PARTIAL" if discovery_errors else "AVAILABLE")
        built.append(row)
    unknown_semantic_roots = sorted(
        {row.get("root_id") for row in semantics} - seen
    )
    if unknown_semantic_roots:
        raise ValueError(
            f"consumer semantics reference unknown roots: {unknown_semantic_roots}"
        )
    built.sort(key=lambda row: row["root_id"])
    roots = [
        {
            "root_id": row["root_id"],
            "surface": row["surface"],
            "source_commit": row["source_commit"],
            "coverage": row["coverage"],
            "availability": row["availability"],
            "discovery_errors": row["discovery_errors"],
        }
        for row in built
    ]
    evidence = sorted(
        (item for row in built for item in row["evidence"]),
        key=lambda item: (
            item["root_id"], item["path"], item["line"], item["category"]
        ),
    )
    _apply_adjudication_policy(evidence, roots, adjudication_policy)
    canonical_subject = json.dumps(
        {"roots": roots, "semantic_profiles": SEMANTIC_PROFILES, "evidence": evidence},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    discovered = [
        row for row in evidence if row.get("record_class") != "VERIFIED_CONSUMER"
    ]
    candidates = [
        row for row in discovered
        if str(row.get("record_class", "")).startswith("CANDIDATE_")
    ]
    adjudicated = [
        row for row in discovered if row.get("review_state") == "POLICY_ADJUDICATED"
    ]
    complete = (
        adjudication_policy is not None
        and not candidates
        and len(roots) == 1
        and all(row["root_id"] == adjudication_policy["root_id"] for row in evidence)
        and all(
            row["availability"] == "AVAILABLE"
            and row["coverage"]["files_accounted"]
                == row["coverage"]["tracked_candidates"]
            for row in roots
        )
    )
    return {
        "schema": "ember-identity-consumer-census-set-v1",
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "roots": roots,
        "semantic_profiles": SEMANTIC_PROFILES,
        "evidence": evidence,
        "candidate_discovery": {
            "record_count": len(discovered),
            "unadjudicated_count": len(candidates),
            "source_role_counts": dict(sorted(Counter(
                str(row["source_role"]) for row in discovered
            ).items())),
            **({"adjudication_counts": dict(sorted(Counter(
                str(row["record_class"]) for row in adjudicated
            ).items()))} if adjudication_policy is not None else {}),
            "global_consumer_completeness": (
                "CONSERVATIVE_SUPERSET_COMPLETE" if complete else "NOT_CLAIMED"
            ),
        },
        "canonical_subject_sha256": hashlib.sha256(canonical_subject).hexdigest(),
    }


def resolve_root_locator_spec(
    payload: object, *, repo_root: Path, replay_profile: str | None = None
) -> list[dict]:
    """Resolve a checked-in logical locator spec without publishing host paths."""
    if not isinstance(payload, dict) or set(payload) not in (
        {"schema", "portable_root_id", "roots"},
        {"authority", "schema", "portable_root_id", "roots"}
    ):
        raise ValueError("root locator spec uses a closed top-level schema")
    if payload.get("schema") != "ember-census-root-locators-v1":
        raise ValueError("unsupported root locator spec schema")
    roots = payload.get("roots")
    if not isinstance(roots, list) or not roots:
        raise ValueError("root locator spec requires root rows")
    if replay_profile not in (None, "full", "portable"):
        raise ValueError("unsupported replay profile")
    if replay_profile == "portable":
        roots = [
            row for row in roots
            if isinstance(row, dict) and row.get("root_id") == payload.get("portable_root_id")
        ]
        if len(roots) != 1:
            raise ValueError("portable replay root must resolve exactly once")
    resolved: list[dict] = []
    for raw in roots:
        if not isinstance(raw, dict) or not isinstance(raw.get("locator"), dict):
            raise ValueError("root locator row is invalid")
        row = dict(raw)
        locator = row.pop("locator")
        redactions_env = row.pop("path_redactions_env", None)
        if set(locator) == {"kind"} and locator.get("kind") == "repo_root":
            root = repo_root.resolve()
        elif set(locator) == {"kind", "env"} and locator.get("kind") == "env":
            name = locator.get("env")
            value = os.environ.get(name, "") if isinstance(name, str) else ""
            if not value:
                raise ValueError(f"required census root environment variable is absent: {name}")
            root = Path(value).resolve()
        elif set(locator) == {"kind"} and locator.get("kind") == "missing":
            root = repo_root.resolve() / "__configured_missing_root__"
            if root.exists():
                raise ValueError("configured missing-root sentinel unexpectedly exists")
        else:
            raise ValueError("unsupported root locator")
        if redactions_env is not None:
            if not isinstance(redactions_env, str) or not redactions_env:
                raise ValueError("path_redactions_env must name an environment variable")
            row["path_redactions"] = [
                item.strip() for item in os.environ.get(redactions_env, "").split(",")
                if item.strip()
            ]
        row["root"] = root
        resolved.append(row)
    return resolved


def materialize_scoped_semantics(scope: object, semantics: object) -> list[dict[str, str]]:
    if not isinstance(scope, dict) or set(scope) != {
        "authority", "schema", "scope_id", "root_id", "source_commit",
        "claim_boundary", "global_consumer_completeness",
        "candidate_adjudication", "consumers",
    }:
        raise ValueError("consumer scope uses a closed schema")
    if (
        scope.get("schema") != "ember-reviewed-consumer-scope-v1"
        or scope.get("root_id") != "public-master"
        or not re.fullmatch(r"[0-9a-f]{40}", str(scope.get("source_commit")))
        or scope.get("global_consumer_completeness")
            != "CONSERVATIVE_SUPERSET_COMPLETE"
        or not isinstance(scope.get("consumers"), list)
        or not isinstance(semantics, list)
    ):
        raise ValueError("consumer scope is invalid")
    adjudication = scope.get("candidate_adjudication")
    if (
        not isinstance(adjudication, dict)
        or adjudication.get("root_id") != scope["root_id"]
        or adjudication.get("source_commit") != scope["source_commit"]
    ):
        raise ValueError("consumer scope adjudication is not bound to its exact root")
    semantic_index: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in semantics:
        if not isinstance(row, dict):
            raise ValueError("semantics row is invalid")
        key = (str(row.get("path")), str(row.get("category")), str(row.get("evidence_sha256")))
        if key in semantic_index:
            raise ValueError(f"ambiguous semantics selector: {key}")
        semantic_index[key] = row
    resolved: list[dict[str, str]] = []
    consumer_ids: set[str] = set()
    for selector in scope["consumers"]:
        if not isinstance(selector, dict) or set(selector) != {
            "consumer_id", "path", "category", "evidence_sha256"
        }:
            raise ValueError("consumer selector is invalid")
        consumer_id = selector["consumer_id"]
        if not isinstance(consumer_id, str) or not consumer_id or consumer_id in consumer_ids:
            raise ValueError("consumer IDs must be unique nonempty strings")
        consumer_ids.add(consumer_id)
        key = (selector["path"], selector["category"], selector["evidence_sha256"])
        source = semantic_index.get(key)
        if source is None:
            raise ValueError(f"consumer scope selector has no reviewed semantics: {key}")
        resolved.append({
            "consumer_id": consumer_id,
            "root_id": scope["root_id"],
            "path": selector["path"],
            "category": selector["category"],
            "evidence_sha256": selector["evidence_sha256"],
            **{field: source[field] for field in SEMANTIC_FIELDS},
        })
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    root_group = parser.add_mutually_exclusive_group()
    root_group.add_argument("--roots-spec", type=Path)
    root_group.add_argument("--root-locator-spec", type=Path)
    parser.add_argument("--semantics-manifest", type=Path)
    parser.add_argument("--consumer-scope", type=Path)
    parser.add_argument("--replay-profile", choices=("full", "portable"), default="full")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.roots_spec or args.root_locator_spec:
        if args.root_locator_spec:
            locator_payload = json.loads(args.root_locator_spec.read_text(encoding="utf-8"))
            raw_specs = resolve_root_locator_spec(
                locator_payload, repo_root=args.root, replay_profile=args.replay_profile
            )
        else:
            raw_specs = json.loads(args.roots_spec.read_text(encoding="utf-8"))
        if not isinstance(raw_specs, list) or not all(isinstance(item, dict) for item in raw_specs):
            raise ValueError("roots spec must be a list of root objects")
        semantics = (
            json.loads(args.semantics_manifest.read_text(encoding="utf-8"))
            if args.semantics_manifest else []
        )
        if not isinstance(semantics, list):
            raise ValueError("semantics manifest must be a list")
        scope = (
            json.loads(args.consumer_scope.read_text(encoding="utf-8"))
            if args.consumer_scope else None
        )
        if scope is not None:
            semantics = materialize_scoped_semantics(scope, semantics)
        payload = build_census_set(
            raw_specs,
            consumer_semantics=semantics,
            adjudication_policy=(
                scope["candidate_adjudication"] if scope is not None else None
            ),
        )
        if scope is not None:
            resolved_ids = sorted(
                row["consumer_id"] for row in payload["evidence"]
                if row.get("record_class") == "VERIFIED_CONSUMER"
            )
            required_ids = sorted(row["consumer_id"] for row in scope["consumers"])
            if resolved_ids != required_ids:
                raise ValueError("reviewed consumer scope did not resolve exactly")
            payload["verified_consumer_scope"] = {
                "scope_id": scope["scope_id"],
                "root_id": scope["root_id"],
                "source_commit": scope["source_commit"],
                "required_consumer_ids": required_ids,
                "resolved_consumer_ids": resolved_ids,
                "status": "REVIEWED_SCOPE_COMPLETE",
            }
            payload["global_consumer_completeness"] = scope[
                "global_consumer_completeness"
            ]
            if (
                payload["candidate_discovery"]["global_consumer_completeness"]
                != scope["global_consumer_completeness"]
            ):
                raise ValueError("global consumer completeness policy did not close")
    else:
        payload = build_census(args.root)
    rendered = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
