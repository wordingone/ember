#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
Static import census runner for nativization measurement.

Parses the substrate diagnostic map and measures borrowed dependencies across layers.
Pure-local, no GPU, no network.
"""

from __future__ import annotations

import ast
import hashlib
import json
import fnmatch
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nativization_motion_trace import (
    TRACE_PHASES,
    TRACE_RUN_ID,
    TRACE_SCHEMA_VERSION,
    PHASE_ENTRYPOINTS,
    _reachable_projection,
    build_trace,
    canonical_json_bytes,
    ensure_source_tree_clean,
    git_blob_bytes,
    git_blob_sha256,
    sha256_bytes,
    source_commit,
    _semantic_layer_reachable,
)


TICKET = "S5-NATIVIZATION-MOTION"
GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


@dataclass
class LayerMeasurement:
    name: str
    borrowed_deps: list[str]
    borrowed_deps_count: int
    borrowed_loc: int
    owned_loc: int
    borrowed_binaries: list[str]
    critical_path_share: dict[str, Any] | None = None


@dataclass
class NativizationMotionReceipt:
    schema_version: str
    ts: str
    ticket: str
    goal_id: str
    workstream_id: str
    next_executed_outcome: str
    sha_convention: str
    invariant_sha256: str
    map_source_sha: str
    source_commit: str
    run_import_manifest_sha256: str
    run_import_trace_sha256: str
    run_import_trace_producer_sha256: str
    layers: list[dict[str, Any]]
    deltas: dict[str, Any] | None
    next_home_candidate: str | None
    method: str
    limits: list[str]
    predecessor_receipt_path: str | None
    predecessor_receipt_sha256: str | None
    predecessor_source_commit: str | None


def sha256_file(path: Path) -> str:
    """Compute SHA256 of file contents (binary)."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return "sha256:" + h.hexdigest()


def parse_diagnostic_map(diagnostic_path: Path) -> list[str]:
    """Parse layer list from diagnostic markdown.

    Extracts layer names from the table under the heading
    "## The inherited stack, bottom → top, with the blocking line"

    Fails loudly if the expected heading structure drifts.
    """
    content = diagnostic_path.read_text(encoding="utf-8")

    # Find the expected heading
    heading = "## The inherited stack, bottom → top, with the blocking line"
    if heading not in content:
        raise ValueError(
            f"Expected heading not found in {diagnostic_path}: {heading}\n"
            "Diagnostic map structure has drifted. Cannot proceed without the exact heading."
        )

    # Extract the section after the heading
    heading_idx = content.find(heading)
    section = content[heading_idx:]

    # Find the table start (markdown table with |)
    table_start = section.find("\n|---|")
    if table_start == -1:
        raise ValueError(
            f"Expected table format not found in diagnostic section.\n"
            "Cannot parse layer names from diagnostic map."
        )

    # Parse the table rows (skip header and separator rows)
    layers = []
    lines = section[table_start:].split("\n")

    for line in lines[2:]:  # Skip header and separator rows
        line = line.strip()
        if not line or not line.startswith("|"):
            break

        # Parse table row: | layer | what it is | relationship |
        cols = [c.strip() for c in line.split("|")[1:-1]]
        if len(cols) >= 1 and cols[0]:
            layer_name = cols[0]
            # Skip the blocking line marker (contains — or ** or starts with -)
            if "—" in layer_name or layer_name.startswith("**") or layer_name.startswith("-"):
                continue
            layers.append(layer_name)

    if not layers:
        raise ValueError("No layers parsed from diagnostic table")

    return layers


def get_layer_file_globs(layer_name: str) -> list[str]:
    """Map layer names to file glob patterns.

    This is a v1 heuristic mapping. Refined based on actual codebase structure.
    """
    mapping = {
        "CUDA kernels (cuBLAS matmul, elementwise)": [
            "tools/**/*.py",
            "scripts/**/*cuda*.py",
        ],
        "Tensor abstraction (storage/strides/dtype)": [
            "tools/**/*tensor*.py",
            "scripts/**/*tensor*.py",
        ],
        "Autograd (`grad_fn` graph, `backward()`)": [
            "tools/**/*autograd*.py",
            "scripts/**/*autograd*.py",
            "tools/**/*grad*.py",
        ],
        "Optimizer (Adam/Muon: separable state + update)": [
            "tools/**/*optim*.py",
            "scripts/**/*optim*.py",
            "tools/**/*adam*.py",
        ],
        "Training loop (fwd → loss → backward → step)": [
            "tools/**/*train*.py",
            "scripts/**/*train*.py",
            "scripts/train*.py",
            "baseline/**/*.py",
        ],
    }

    if layer_name not in mapping:
        raise ValueError(f"closed layer predicate is not defined for {layer_name}")
    return list(mapping[layer_name])


def collect_imports(file_path: Path) -> tuple[set[str], int]:
    """Extract imported packages from a Python file.

    Returns (set of external package names, total line count with imports).
    Excludes stdlib and ember-owned modules.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return set(), 0

    lines = content.split("\n")
    imported_packages = set()
    lines_with_imports = 0

    # Python stdlib modules to exclude
    stdlib_mods = {
        "sys", "os", "re", "json", "pathlib", "typing", "dataclasses",
        "hashlib", "subprocess", "argparse", "tempfile", "shutil", "copy",
        "itertools", "functools", "collections", "abc", "enum", "datetime",
        "time", "random", "math", "statistics", "decimal", "fractions",
        "contextlib", "inspect", "warnings", "io", "codecs", "locale",
        "gettext", "struct", "pickle", "copyreg", "types", "pydoc",
        "ast", "html", "urllib", "csv", "sqlite3", "unittest", "logging",
        "traceback", "platform", "queue", "signal", "threading", "multiprocessing",
        "gc", "runpy", "glob", "fnmatch", "tempfile", "textwrap",
    }

    # Ember-owned modules (in tools/, scripts/)
    ember_modules = {"ember", "tools", "scripts"}

    for line in lines:
        stripped = line.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith("#"):
            continue

        # Skip if line is inside a string literal (basic heuristic)
        if stripped.startswith(('"""', "'''", '"', "'")):
            continue

        # Match import statements
        import_match = re.match(r"^(?:from|import)\s+([^\s\.]+)", stripped)
        if import_match:
            pkg = import_match.group(1).split(".")[0]

            # Validate that it's a real identifier (no trailing punctuation/special chars)
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", pkg):
                continue

            # Exclude stdlib and ember-owned
            if pkg not in stdlib_mods and pkg not in ember_modules:
                imported_packages.add(pkg)

            lines_with_imports += 1

    return imported_packages, lines_with_imports


def _stdlib_modules() -> set[str]:
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    return {
        "sys", "os", "re", "json", "pathlib", "typing", "dataclasses",
        "hashlib", "subprocess", "argparse", "tempfile", "shutil", "copy",
        "itertools", "functools", "collections", "abc", "enum", "datetime",
        "time", "random", "math", "statistics", "decimal", "fractions",
        "contextlib", "inspect", "warnings", "io", "codecs", "locale",
        "gettext", "struct", "pickle", "copyreg", "types", "pydoc", "ast",
        "html", "urllib", "csv", "sqlite3", "unittest", "logging", "traceback",
        "platform", "queue", "signal", "threading", "multiprocessing", "gc",
        "runpy", "glob", "fnmatch", "textwrap",
    }


def _owned_import_path(repo_root: Path, file_path: Path, module: str, commit: str) -> str | None:
    candidates = [
        file_path.parent / f"{module.split('.')[-1]}.py",
        repo_root / (module.replace(".", "/") + ".py"),
        repo_root / "tools" / "ember-restart-3b" / f"{module.split('.')[-1]}.py",
    ]
    for candidate in candidates:
        try:
            relative = candidate.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            continue
        try:
            git_blob_bytes(repo_root, commit, relative)
        except ValueError:
            continue
        return relative
    return None


def collect_import_metrics(
    file_path: Path,
    repo_root: Path,
    commit: str,
) -> tuple[set[str], set[str], int, int]:
    try:
        payload = git_blob_bytes(repo_root, commit, file_path.resolve().relative_to(repo_root.resolve()).as_posix())
        if file_path.read_bytes() != payload:
            raise ValueError("measured source bytes drifted from exact Git authority")
        tree = ast.parse(payload.decode("utf-8"), filename=str(file_path))
    except (OSError, SyntaxError, UnicodeError, ValueError) as exc:
        raise ValueError("measured source bytes are not exact Git authority") from exc
    external: set[str] = set()
    owned: set[str] = set()
    borrowed_loc = 0
    owned_loc = 0
    stdlib = _stdlib_modules()
    for node in ast.walk(tree):
        module = None
        if isinstance(node, ast.Import):
            module = node.names[0].name
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
        if not module:
            continue
        top = module.split(".")[0]
        span = (getattr(node, "end_lineno", node.lineno) - node.lineno) + 1
        if top in stdlib:
            continue
        if _owned_import_path(repo_root, file_path, module, commit) is not None:
            owned.add(top)
            owned_loc += span
        else:
            external.add(top)
            borrowed_loc += span
    return external, owned, borrowed_loc, owned_loc


def scan_binaries(file_path: Path) -> set[str]:
    """Extract external binary names from subprocess/exec calls.

    Looks for: subprocess, os.system, os.exec*, Popen, run, check_call, etc.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return set()

    binaries = set()

    # Common external binaries we look for
    known_binaries = {"llama-server", "docker", "git", "bun", "python", "pip", "npm"}

    # Patterns: subprocess.run/Popen/check_call/call with string arguments
    patterns = [
        r'subprocess\.(run|Popen|check_call|call)\s*\(\s*["\']([^"\']+)["\']',
        r'os\.system\s*\(\s*["\']([^"\']+)["\']',
        r'os\.exec[lv]+\s*\(\s*["\']([^"\']+)["\']',
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, content):
            cmd = match.group(2) if match.lastindex >= 2 else match.group(1)
            # Extract first token (the binary name)
            binary = cmd.split()[0] if cmd else ""
            if binary and any(known in binary for known in known_binaries):
                binaries.add(binary.strip("./"))

    return binaries


def measure_layer(
    root: Path,
    layer_name: str,
    file_globs: list[str],
    critical_path_share: dict[str, Any] | None = None,
    *,
    source_commit: str | None = None,
) -> LayerMeasurement:
    """Measure borrowed/owned imports from exact Git-bound source bytes."""
    all_imports: set[str] = set()
    total_borrowed_loc = 0
    total_owned_loc = 0
    all_binaries: set[str] = set()
    files_to_scan: set[Path] = set()
    for glob_pattern in file_globs:
        for file_path in root.glob(glob_pattern):
            if file_path.is_file() and file_path.suffix == ".py":
                files_to_scan.add(file_path)
    commit = source_commit
    if commit is None and (root / ".git").exists():
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD^{commit}"],
                cwd=root, capture_output=True, text=True, check=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            commit = None
    for file_path in sorted(files_to_scan):
        if commit:
            imports, _owned, borrowed_loc, owned_loc = collect_import_metrics(
                file_path, root, commit
            )
        else:
            imports, borrowed_loc = collect_imports(file_path)
            owned_loc = 0
        all_imports.update(imports)
        total_borrowed_loc += borrowed_loc
        total_owned_loc += owned_loc
        all_binaries.update(scan_binaries(file_path))
    return LayerMeasurement(
        name=layer_name,
        borrowed_deps=sorted(all_imports),
        borrowed_deps_count=len(all_imports),
        borrowed_loc=total_borrowed_loc,
        owned_loc=total_owned_loc,
        borrowed_binaries=sorted(all_binaries),
        critical_path_share=critical_path_share,
    )

def compute_deltas(
    current_layers: list[LayerMeasurement],
    prior_receipt: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Compute numeric deltas vs prior receipt.

    First receipt: delta is None (disclosed as null).
    """
    if prior_receipt is None:
        return None

    deltas: dict[str, Any] = {}

    for layer in current_layers:
        prior_layer = next(
            (l for l in prior_receipt.get("layers", []) if l["name"] == layer.name),
            None,
        )

        if prior_layer:
            delta_deps = layer.borrowed_deps_count - prior_layer["borrowed_deps_count"]
            delta_loc = layer.borrowed_loc - prior_layer["borrowed_loc"]

            deltas[layer.name] = {
                "borrowed_deps_delta": delta_deps,
                "borrowed_loc_delta": delta_loc,
            }

    return deltas if deltas else None


def identify_next_home_candidate(
    layers: list[LayerMeasurement],
    diagnostic_path: Path,
) -> str | None:
    """Identify next layer to nativize (highest borrowed_deps not yet marked home).

    v1 proxy: ranked by borrowed_deps count.
    This is a RANKING HEURISTIC, not a wall-receipt measurement.
    """
    # Find layer with highest borrowed_deps
    if not layers:
        return None

    # Sort by borrowed_deps_count descending
    sorted_layers = sorted(layers, key=lambda l: l.borrowed_deps_count, reverse=True)

    if sorted_layers:
        return sorted_layers[0].name

    return None


def load_prior_receipt(
    repo_root: Path,
    receipt_path: Path | None,
    expected_sha256: str | None,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if receipt_path is None and expected_sha256 is None:
        return None, None, None
    if receipt_path is None or expected_sha256 is None:
        raise ValueError("predecessor receipt path and hash are both required")
    expected = _require_hex(expected_sha256, length=64, label="predecessor receipt hash")
    path = Path(receipt_path).resolve()
    try:
        relative = path.relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("predecessor receipt must be under repo root") from exc
    if not relative.startswith("receipts/nativization-motion/"):
        raise ValueError("predecessor receipt path is outside governed receipt root")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError("predecessor receipt cannot be read") from exc
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError("predecessor receipt hash mismatch")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("predecessor receipt is malformed") from exc
    if not isinstance(document, dict) or not isinstance(document.get("layers"), list):
        raise ValueError("predecessor receipt is not a motion receipt")
    prior_source = document.get("source_commit")
    if not isinstance(prior_source, str) or not _source_commit_is_usable(repo_root, prior_source):
        raise ValueError("predecessor receipt source commit is not governed")
    return document, actual, relative

def get_invariant_sha(root: Path) -> str:
    """Get the invariant_sha256 from INVARIANT.md.

    This is a fixed value that should be included in every receipt.
    """
    invariant_path = root / "INVARIANT.md"
    if not invariant_path.exists():
        return "sha256:unknown"

    return hashlib.sha256(invariant_path.read_bytes()).hexdigest()


def _require_hex(value: Any, *, length: int, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}", value):
        raise ValueError(f"run import manifest {label} must be lowercase {length}-hex")
    return value



def _source_commit_is_usable(repo_root: Path, value: str) -> bool:
    if not (repo_root / ".git").exists() or value == "0" * 40:
        return False
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", f"{value}^{{commit}}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", value, "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _trace_layer_rows(
    repo_root: Path,
    layer_names: list[str],
    trace: dict[str, Any],
    trace_sha256: str,
) -> list[dict[str, Any]]:
    del repo_root, trace_sha256
    events_by_layer: dict[str, list[dict[str, Any]]] = {name: [] for name in layer_names}
    for event in trace["events"]:
        if event["layer"] in events_by_layer:
            events_by_layer[event["layer"]].append(event)
    rows: list[dict[str, Any]] = []
    for name in layer_names:
        events = events_by_layer[name]
        if len(events) != len(TRACE_PHASES):
            raise ValueError("run import trace must contain one rooted event per phase and layer")
        if {event["phase"] for event in events} != set(TRACE_PHASES):
            raise ValueError("run import trace phases are incomplete")
        phase_reachability = {event["phase"]: event["layer_reachability_sha256"] for event in events}
        share = {
            phase: bool(next(event for event in events if event["phase"] == phase)["layer_reachable"])
            for phase in TRACE_PHASES
        }
        share["evidence"] = (
            f"rooted-import-graph-v3:{sha256_bytes(canonical_json_bytes(phase_reachability))}"
        )
        rows.append({"name": name, "trace_events": events, "critical_path_share": share})
    return rows


def build_run_import_manifest(
    repo_root: Path,
    layer_names: list[str],
    *,
    output_path: Path | None = None,
    producer_sha256: str | None = None,
) -> tuple[Path, str]:
    """Derive a closed manifest from hashed production source trace events."""
    root = repo_root.resolve()
    ensure_source_tree_clean(root)
    bound_source_commit = source_commit(root)
    patterns = {name: get_layer_file_globs(name) for name in layer_names}
    trace = build_trace(root, layer_names, patterns, bound_source_commit)
    trace_sha = sha256_bytes(canonical_json_bytes(trace))
    trace_producer = hashlib.sha256(Path(__file__).with_name("nativization_motion_trace.py").read_bytes()).hexdigest()
    manifest = {
        "schema_version": "ember-run-import-manifest-v1",
        "run_id": TRACE_RUN_ID,
        "source_commit": bound_source_commit,
        "producer_sha256": producer_sha256 or trace_producer,
        "trace_sha256": trace_sha,
        "trace": trace,
        "layers": _trace_layer_rows(root, layer_names, trace, trace_sha),
    }
    path = output_path or root / "manifests" / "run-import-manifest-v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(manifest)
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


def load_run_import_manifest(
    repo_root: Path,
    manifest_path: Path | None,
    expected_sha256: str | None,
    layer_names: list[str] | None,
) -> tuple[dict[str, Any], str]:
    if manifest_path is None or expected_sha256 is None:
        raise ValueError("run import manifest path and expected hash are required")
    expected = _require_hex(expected_sha256, length=64, label="expected hash")
    root = repo_root.resolve()
    path = Path(manifest_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("run import manifest must be under repo root") from exc
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError("run import manifest cannot be read") from exc
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError("run import manifest hash mismatch")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("run import manifest is malformed") from exc
    if not isinstance(document, dict):
        raise ValueError("run import manifest must be an object")
    required = {"schema_version", "run_id", "source_commit", "producer_sha256", "trace_sha256", "trace", "layers"}
    if set(document) != required:
        raise ValueError("run import manifest fields are not closed")
    if document["schema_version"] != "ember-run-import-manifest-v1" or document["run_id"] != TRACE_RUN_ID:
        raise ValueError("run import manifest schema or run id mismatch")
    source = _require_hex(document["source_commit"], length=40, label="source_commit")
    if not _source_commit_is_usable(root, source):
        raise ValueError("run import manifest source commit is not an exact governed Git ancestor")
    producer_sha = _require_hex(document["producer_sha256"], length=64, label="producer_sha256")
    producer_relative = "scripts/nativization_motion_trace.py"
    producer_path = root / producer_relative
    if producer_path.is_file():
        current_producer_sha = git_blob_sha256(root, source, producer_relative)
        if hashlib.sha256(producer_path.read_bytes()).hexdigest() != current_producer_sha:
            raise ValueError("run import trace producer bytes drifted from Git source authority")
    else:
        current_producer_sha = hashlib.sha256(Path(__file__).with_name("nativization_motion_trace.py").read_bytes()).hexdigest()
    if producer_sha != current_producer_sha:
        raise ValueError("run import manifest trace producer hash is stale")
    trace = document["trace"]
    if not isinstance(trace, dict) or set(trace) != {"schema_version", "run_id", "events"}:
        raise ValueError("run import trace fields are not closed")
    if trace["schema_version"] != TRACE_SCHEMA_VERSION or trace["run_id"] != TRACE_RUN_ID:
        raise ValueError("run import trace schema mismatch")
    trace_sha = _require_hex(document["trace_sha256"], length=64, label="trace_sha256")
    if trace_sha != sha256_bytes(canonical_json_bytes(trace)):
        raise ValueError("run import trace hash mismatch")
    events = trace["events"]
    if not isinstance(events, list) or not events:
        raise ValueError("run import trace events are required")
    rows = document["layers"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("run import manifest layers mismatch")
    expected_names = set(layer_names) if layer_names is not None else None
    seen: set[str] = set()
    events_by_layer: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        required_event = {"layer", "phase", "entrypoint", "entrypoint_sha256", "layer_patterns", "reachable", "reachability_sha256", "layer_reachable", "layer_reachability_sha256"}
        if not isinstance(event, dict) or set(event) != required_event:
            raise ValueError("run import trace event fields are not closed")
        if not isinstance(event["layer"], str) or event["phase"] not in TRACE_PHASES:
            raise ValueError("run import trace event identity is invalid")
        phase = event["phase"]
        if event["entrypoint"] != PHASE_ENTRYPOINTS[phase]:
            raise ValueError("run import trace entrypoint is not a governed phase root")
        entrypoint = (root / event["entrypoint"]).resolve()
        try:
            entrypoint.relative_to(root)
        except ValueError as exc:
            raise ValueError("run import trace entrypoint escapes repo root") from exc
        _require_hex(event["entrypoint_sha256"], length=64, label="entrypoint hash")
        entrypoint_relative = event["entrypoint"]
        try:
            entrypoint_blob = git_blob_bytes(root, source, entrypoint_relative)
        except ValueError as exc:
            raise ValueError("run import trace entrypoint Git blob is unavailable") from exc
        if not entrypoint.is_file() or entrypoint.read_bytes() != entrypoint_blob:
            raise ValueError("run import trace entrypoint bytes drifted from Git source authority")
        if hashlib.sha256(entrypoint_blob).hexdigest() != event["entrypoint_sha256"]:
            raise ValueError("run import trace entrypoint hash is not Git-bound")
        patterns = event["layer_patterns"]
        if patterns != get_layer_file_globs(event["layer"]):
            raise ValueError("run import trace layer predicate drifted")
        if not isinstance(patterns, list) or not patterns or not all(isinstance(item, str) for item in patterns):
            raise ValueError("run import trace layer predicate is invalid")
        reachable = event["reachable"]
        if not isinstance(reachable, list) or not reachable:
            raise ValueError("run import trace reachability is required")
        for item in reachable:
            if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
                raise ValueError("run import trace reachable entry fields are not closed")
            _require_hex(item["sha256"], length=64, label="reachable source hash")
            item_path = (root / item["path"]).resolve()
            try:
                item_path.relative_to(root)
            except ValueError as exc:
                raise ValueError("run import trace reachable source escapes repo root") from exc
            try:
                blob = git_blob_bytes(root, source, item["path"])
            except ValueError as exc:
                raise ValueError("run import trace reachable source is not a tracked Git blob") from exc
            if not item_path.is_file() or item_path.read_bytes() != blob:
                raise ValueError("run import trace reachable source bytes drifted from Git source authority")
            if hashlib.sha256(blob).hexdigest() != item["sha256"]:
                raise ValueError("run import trace reachable source hash is not Git-bound")
        expected_reachable = _reachable_projection(root, event["entrypoint"], source)
        if reachable != expected_reachable:
            raise ValueError("run import trace reachability is not rooted in the governed entrypoint")
        _require_hex(event["reachability_sha256"], length=64, label="reachability hash")
        if event["reachability_sha256"] != sha256_bytes(canonical_json_bytes(reachable)):
            raise ValueError("run import trace reachability hash mismatch")
        layer_reachable = event["layer_reachable"]
        if not isinstance(layer_reachable, list):
            raise ValueError("run import trace layer reachability is invalid")
        expected_layer_reachable = _semantic_layer_reachable(
            root, source, event["layer"], reachable
        )
        if layer_reachable != expected_layer_reachable:
            raise ValueError("run import trace layer reachability is not predicate-derived")
        _require_hex(event["layer_reachability_sha256"], length=64, label="layer reachability hash")
        if event["layer_reachability_sha256"] != sha256_bytes(canonical_json_bytes(layer_reachable)):
            raise ValueError("run import trace layer reachability hash mismatch")
        events_by_layer.setdefault(event["layer"], []).append(event)
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"name", "trace_events", "critical_path_share"}:
            raise ValueError("run import manifest layer fields are not closed")
        name = row["name"]
        if not isinstance(name, str) or (expected_names is not None and name not in expected_names) or name in seen:
            raise ValueError("run import manifest layer names mismatch")
        seen.add(name)
        row_events = row["trace_events"]
        if not isinstance(row_events, list) or row_events != events_by_layer.get(name):
            raise ValueError("run import manifest layer trace does not match governed events")
        if len(row_events) != len(TRACE_PHASES) or {event["phase"] for event in row_events} != set(TRACE_PHASES):
            raise ValueError("run import manifest layer trace phases are incomplete")
        phase_reachability = {event["phase"]: event["layer_reachability_sha256"] for event in row_events}
        expected_share = {
            phase: bool(next(event for event in row_events if event["phase"] == phase)["layer_reachable"])
            for phase in TRACE_PHASES
        }
        expected_share["evidence"] = (
            f"rooted-import-graph-v3:{sha256_bytes(canonical_json_bytes(phase_reachability))}"
        )
        if row["critical_path_share"] != expected_share:
            raise ValueError("run import manifest critical path share is not rooted trace-derived")
    if expected_names is not None and seen != expected_names:
        raise ValueError("run import manifest layer names mismatch")
    return document, actual

def run_nativization_motion(
    repo_root: Path,
    *,
    run_import_manifest_path: Path | None = None,
    expected_run_import_manifest_sha256: str | None = None,
    prior_receipt_path: Path | None = None,
    expected_prior_receipt_sha256: str | None = None,
) -> str:
    """Main runner: measure nativization status and write receipt.

    Returns path to the written receipt.
    """
    if run_import_manifest_path is None or expected_run_import_manifest_sha256 is None:
        raise ValueError("run import manifest path and expected hash are required")

    # Bind the exact production run manifest before parsing any mutable diagnostic text.
    run_manifest, run_manifest_sha = load_run_import_manifest(
        repo_root, run_import_manifest_path, expected_run_import_manifest_sha256, None
    )

    # Find diagnostic and receipts paths
    diagnostic_path = repo_root / "docs" / "design" / "ember-owned-substrate-diagnostic.md"
    receipts_dir = repo_root / "receipts" / "nativization-motion"

    if not diagnostic_path.exists():
        raise FileNotFoundError(f"Diagnostic map not found: {diagnostic_path}")

    # Parse layers from diagnostic and require exact manifest coverage.
    layer_names = parse_diagnostic_map(diagnostic_path)
    run_layers = {row["name"]: row["critical_path_share"] for row in run_manifest["layers"]}
    if set(run_layers) != set(layer_names):
        raise ValueError("run import manifest layer names mismatch")

    # Measure each layer
    layers: list[LayerMeasurement] = []
    for layer_name in layer_names:
        file_globs = get_layer_file_globs(layer_name)
        measurement = measure_layer(repo_root, layer_name, file_globs, run_layers[layer_name])
        layers.append(measurement)

    # Load only the caller-declared predecessor; never select a mutable latest file.
    if prior_receipt_path is None and expected_prior_receipt_sha256 is None:
        if list(receipts_dir.glob("nm-*.json")):
            raise ValueError("explicit predecessor receipt path and hash are required")
    prior_receipt, prior_sha, prior_relative = load_prior_receipt(
        repo_root, prior_receipt_path, expected_prior_receipt_sha256
    )
    deltas = compute_deltas(layers, prior_receipt)

    # Identify next home candidate
    next_home = identify_next_home_candidate(layers, diagnostic_path)

    # Get timestamps and hashes
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    utc_ts = now.strftime("%Y%m%dT%H%M%SZ")

    invariant_sha = get_invariant_sha(repo_root)
    map_source_sha = sha256_file(diagnostic_path)

    # Build receipt
    receipt = NativizationMotionReceipt(
        schema_version="ember-nativization-motion-receipt-v2",
        ts=ts,
        ticket=TICKET,
        goal_id=GOAL_ID,
        workstream_id=WORKSTREAM_ID,
        next_executed_outcome=NEXT_EXECUTED_OUTCOME,
        sha_convention=SHA_CONVENTION,
        invariant_sha256=invariant_sha,
        map_source_sha=map_source_sha,
        source_commit=run_manifest["source_commit"],
        run_import_manifest_sha256=run_manifest_sha,
        run_import_trace_sha256=run_manifest["trace_sha256"],
        run_import_trace_producer_sha256=run_manifest["producer_sha256"],
        layers=[asdict(layer) for layer in layers],
        deltas=deltas,
        next_home_candidate=next_home,
        method="phase-rooted-import-graph-v1",
        limits=[
            "dynamic imports not detected",
            "vendored code treated as external",
            "binary dependencies of dependencies not scanned",
            "relative imports are resolved only within the governed repository root",
        ],
        predecessor_receipt_path=prior_relative,
        predecessor_receipt_sha256=prior_sha,
        predecessor_source_commit=prior_receipt.get("source_commit") if prior_receipt else None,
    )

    # Write receipt
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / f"nm-{utc_ts}.json"

    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(asdict(receipt), f, indent=2)

    print(f"Receipt written: {receipt_path}")
    print(f"Layers measured: {len(layers)}")
    print(f"Next home candidate: {next_home}")

    return str(receipt_path)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: nativization_motion.py <repo-root> <run-import-manifest> <manifest-sha256>", file=sys.stderr)
        sys.exit(2)
    repo_root = Path(sys.argv[1])
    manifest_path = Path(sys.argv[2])
    manifest_sha = sys.argv[3]

    try:
        receipt_path = run_nativization_motion(
            repo_root,
            run_import_manifest_path=manifest_path,
            expected_run_import_manifest_sha256=manifest_sha,
        )
        print(f"Success: {receipt_path}")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
