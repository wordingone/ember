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
    "receipts/",
    "tests/",
    "scripts/tests/",
    "scripts/ember_01_identity/",
    "docs/ember-01-identity/",
    "manifests/ember-01-identity/",
    "tests/fixtures/",
    "docs/verification/receipts-",
    "scripts/ember_totality/receipts-",
)

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
        r"\b(?:expert(?:_id|_bank)?|router|memory_substrate|world_model|deletion_object|mechanism_id)\b",
    ),
}

COMPILED = {
    category: tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)
    for category, patterns in CATEGORY_PATTERNS.items()
}

INTEGRATION_REQUIREMENTS = {
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


def _semantic_fields(category: str, matched_terms: list[str]) -> dict[str, str]:
    return {
        "current_input": ",".join(matched_terms),
        "derived_label": category,
        "protocol": category,
        "failure_behavior": category,
        "claim_effect": category,
        "conflict": category,
        "integration_requirement": category,
    }


def _excluded(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    name = Path(normalized).name.lower()
    return (
        any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES)
        or ".test." in name
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


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
    category_files: dict[str, set[str]] = {category: set() for category in COMPILED}
    raw_match_counts: dict[str, int] = {category: 0 for category in COMPILED}

    for raw_rel in candidates:
        rel = raw_rel.replace("\\", "/")
        public_rel = _public_path(rel, path_redactions)
        path_sha256 = hashlib.sha256(rel.encode("utf-8")).hexdigest()
        path = root / rel
        if _excluded(rel) or Path(rel).suffix.lower() not in SOURCE_SUFFIXES:
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
            text_content = content_bytes.decode("utf-8")
            lines = text_content.splitlines()
        except (OSError, UnicodeDecodeError):
            excluded += 1
            scanned -= 1
            continue
        content_sha256 = hashlib.sha256(content_bytes).hexdigest()
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
                                "matched_terms": matched_terms,
                                **_semantic_fields(category, matched_terms),
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
                    "matched_terms": matched_terms,
                    **_semantic_fields(category, matched_terms),
                }
            )
        if matched_categories:
            evidence_files.add(public_rel)
            for category in matched_categories:
                category_files[category].add(public_rel)

    evidence.sort(key=lambda row: (str(row["path"]), int(row["line"]), str(row["category"])))
    categories = {
        category: {
            "files": sorted(paths),
            "file_count": len(paths),
            "evidence_count": sum(1 for row in evidence if row["category"] == category),
            "raw_match_count": raw_match_counts[category],
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
            "identity_evidence_rows": len(evidence),
            "exclusion_prefixes": list(EXCLUDED_PREFIXES),
            "source_suffixes": sorted(SOURCE_SUFFIXES),
        },
        "categories": categories,
        "semantic_profiles": SEMANTIC_PROFILES,
        "evidence": evidence,
    }


def build_git_census(
    root: Path, *, source_commit: str, root_id: str, surface: str,
    path_redactions: Iterable[str] = (),
) -> dict:
    candidates = _git_tree_files(root, source_commit)
    source_paths = [
        path for path in candidates
        if not _excluded(path) and Path(path).suffix.lower() in SOURCE_SUFFIXES
    ]
    contents = _git_blob_contents(root, source_commit, source_paths)
    return build_census(
        root,
        tracked_files=candidates,
        source_commit=source_commit,
        root_id=root_id,
        surface=surface,
        source_contents=contents,
        path_redactions=path_redactions,
    )


def build_census_set(root_specs: Iterable[dict]) -> dict:
    """Combine logical public/private/live roots without serializing host paths."""
    built: list[dict] = []
    seen: set[str] = set()
    for spec in root_specs:
        root_id = spec["root_id"]
        if root_id in seen:
            raise ValueError(f"duplicate root_id: {root_id}")
        seen.add(root_id)
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
            )
        else:
            row = build_census(
                root_path,
                tracked_files=tracked,
                source_commit=bound_source,
                root_id=root_id,
                surface=spec["surface"],
                path_redactions=spec.get("path_redactions", ()),
            )
        row["discovery_errors"] = discovery_errors
        row["availability"] = "MISSING" if any(
            error["path"] == "." and error["error_class"] == "FileNotFoundError"
            for error in discovery_errors
        ) else ("PARTIAL" if discovery_errors else "AVAILABLE")
        built.append(row)
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
    canonical_subject = json.dumps(
        {"roots": roots, "semantic_profiles": SEMANTIC_PROFILES, "evidence": evidence},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return {
        "schema": "ember-identity-consumer-census-set-v1",
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "roots": roots,
        "semantic_profiles": SEMANTIC_PROFILES,
        "evidence": evidence,
        "canonical_subject_sha256": hashlib.sha256(canonical_subject).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--roots-spec", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.roots_spec:
        raw_specs = json.loads(args.roots_spec.read_text(encoding="utf-8"))
        if not isinstance(raw_specs, list) or not all(isinstance(item, dict) for item in raw_specs):
            raise ValueError("roots spec must be a list of root objects")
        payload = build_census_set(raw_specs)
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
