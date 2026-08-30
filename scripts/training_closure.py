# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Training dependency closure: the declared path set, its guard, and its hash.

The certified launch chain used to bind the WHOLE repository tip, so any merge
between verification and launch invalidated a pending certificate. This module
is the single implementation of the narrower binding:

* ``load_manifest`` reads ``manifests/training-dependency-closure.json`` -- the
  DECLARED training-relevant path set (entrypoints, everything they import, the
  configs and sibling programs they execute, and the manifest itself).
* ``walk_reachable`` recomputes what the entrypoints actually reach: static
  imports (at any nesting depth, so function-level imports count) resolved
  against the repo, plus executable-script edges recovered from string
  literals (``Path(__file__).with_name("verify_training_data.py")`` and
  friends).
* ``dynamic_call_sites`` finds the call shapes a static walk CANNOT follow --
  ``subprocess``, ``importlib``, ``runpy``, ``__import__``, ``exec``/``eval``,
  and process-launching ``os`` calls. Every closure member that uses one must
  declare it in the manifest, and a declaration for a file that no longer uses
  one is equally a failure. An undeclared dynamic edge is a red, not a gap.
* ``audit_closure`` compares all of that against the declaration and is the
  machine-enforced boundary -- a reachable file outside the manifest, a manifest
  entry that does not exist, or an undeclared dynamic edge is a failure. The
  boundary therefore cannot rot in someone's head.
* ``compute_closure_hash`` is the content hash over the declared set at a given
  tree. Verification pins it into the certificate; launch recomputes it live.

Data dependencies (configs, policy JSON) are declared, not walked: a static
walker cannot honestly prove which JSON a program reads, and a dishonest
"machine-detected" data edge would be worse than an explicit declaration. They
are still inside the hash, so changing one still demands re-verification.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import sys
from typing import Any, Iterable, NamedTuple


MANIFEST_RELATIVE_PATH = "manifests/training-dependency-closure.json"
MANIFEST_SCHEMA_VERSION = "ember-training-dependency-closure-v1"
SUPPLEMENT_RELATIVE_PATH = (
    "tools/ember-restart-3b/training-dependency-closure-supplement.json"
)
SUPPLEMENT_SCHEMA_VERSION = "ember-training-dependency-closure-supplement-v1"


# Call shapes a static import walk cannot follow. A closure member using one
# must declare it; see dynamic_call_sites().
DYNAMIC_CALL_NAMES = frozenset(
    {
        "__import__",
        "call",
        "check_call",
        "check_output",
        "import_module",
        "Popen",
        "run",
        "run_module",
        "run_path",
        "spec_from_file_location",
    }
)
DYNAMIC_CALL_ROOTS = frozenset({"builtins", "importlib", "runpy", "subprocess"})
DYNAMIC_BARE_CALL_NAMES = frozenset({"__import__", "eval", "exec"})
EXECUTABLE_LITERAL_SUFFIXES = (".cmd", ".ps1", ".py", ".sh")


class ClosureAudit(NamedTuple):
    """Result of comparing the declared closure against the walked one."""

    ok: bool
    declared: tuple[str, ...]
    reachable: tuple[str, ...]
    undeclared: tuple[str, ...]
    missing: tuple[str, ...]
    undeclared_dynamic: tuple[str, ...]
    stale_dynamic: tuple[str, ...]
    undeclared_dynamic_targets: tuple[str, ...]
    invalid_dynamic_targets: tuple[str, ...]

    def failure_report(self) -> str:
        lines: list[str] = []
        if self.undeclared:
            lines.append(
                "reachable from the training entrypoints but OUTSIDE "
                f"{MANIFEST_RELATIVE_PATH}:"
            )
            lines.extend(f"  + {path}" for path in self.undeclared)
        if self.missing:
            lines.append(
                f"declared in {MANIFEST_RELATIVE_PATH} but absent from the tree:"
            )
            lines.extend(f"  - {path}" for path in self.missing)
        if self.undeclared_dynamic:
            lines.append(
                "closure members reach code through a dynamic import, eval, "
                f"exec, or process launch without a dynamic_call_sites entry in "
                f"{MANIFEST_RELATIVE_PATH} (declare the target, or the edge is "
                "invisible to the walk):"
            )
            lines.extend(f"  ? {path}" for path in self.undeclared_dynamic)
        if self.stale_dynamic:
            lines.append(
                "dynamic_call_sites declares files that no longer make such a "
                "call (drop the entry so the declaration stays honest):"
            )
            lines.extend(f"  ! {path}" for path in self.stale_dynamic)
        if self.undeclared_dynamic_targets:
            lines.append(
                "dynamic_call_sites omits repo targets detected at declared "
                "dynamic callers:"
            )
            lines.extend(f"  ?> {edge}" for edge in self.undeclared_dynamic_targets)
        if self.invalid_dynamic_targets:
            lines.append(
                "dynamic_call_sites declares targets that are not closure members:"
            )
            lines.extend(f"  !> {edge}" for edge in self.invalid_dynamic_targets)
        if lines:
            lines.append(
                "Note: changing tools/ember-restart-3b/parameter_counter.py is "
                "inside the closure and moves counter_sha256, so any checkpoint "
                "you intend to RESUME must have its counter receipt re-run "
                "against the new counter (run_vertical_slice's "
                "require_counter_success_receipt compares the live counter "
                "bytes)."
            )
        return "\n".join(lines)


def _repo_relative(root: pathlib.Path, path: pathlib.Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def load_manifest(root: pathlib.Path) -> dict[str, Any]:
    """Load and shape-check the closure manifest at ``root``."""

    manifest_path = pathlib.Path(root) / MANIFEST_RELATIVE_PATH
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("training dependency closure manifest is unreadable") from error
    if not isinstance(manifest, dict):
        raise ValueError("training dependency closure manifest must be an object")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("training dependency closure manifest schema")
    for key in ("entrypoints", "dynamic_entrypoints", "code", "data"):
        value = manifest.get(key)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise ValueError(
                f"training dependency closure manifest {key} must be a list of paths"
            )
    sites = manifest.get("dynamic_call_sites")
    if not isinstance(sites, dict) or not all(
        isinstance(path, str)
        and path
        and isinstance(targets, list)
        and all(
            isinstance(target, str)
            and target
            and "\\" not in target
            and not target.startswith("/")
            and ":" not in target
            and ".." not in pathlib.PurePosixPath(target).parts
            for target in targets
        )
        for path, targets in sites.items()
    ):
        raise ValueError(
            "training dependency closure manifest dynamic_call_sites must map "
            "each path to a list of repo-relative declared targets"
        )
    notes = manifest.get("dynamic_call_site_notes", {})
    if not isinstance(notes, dict) or not all(
        isinstance(path, str)
        and path in sites
        and isinstance(note, str)
        and note.strip()
        for path, note in notes.items()
    ):
        raise ValueError(
            "training dependency closure manifest dynamic_call_site_notes must "
            "map declared dynamic paths to non-empty prose"
        )
    if any(not targets and path not in notes for path, targets in sites.items()):
        raise ValueError(
            "dynamic_call_sites entries without repo targets require a "
            "dynamic_call_site_notes explanation"
        )
    supplement = load_supplement(root)
    if supplement is not None:
        manifest = _merge_supplement(manifest, supplement)
    return manifest


def _safe_repo_relative(path: str) -> bool:
    return (
        bool(path)
        and "\\" not in path
        and not path.startswith("/")
        and ":" not in path
        and ".." not in pathlib.PurePosixPath(path).parts
    )


def _validate_call_sites(document: dict[str, Any], label: str) -> None:
    sites = document.get("dynamic_call_sites")
    if not isinstance(sites, dict) or not all(
        isinstance(path, str)
        and _safe_repo_relative(path)
        and isinstance(targets, list)
        and all(
            isinstance(target, str) and _safe_repo_relative(target)
            for target in targets
        )
        for path, targets in sites.items()
    ):
        raise ValueError(
            f"training dependency closure {label} dynamic_call_sites must map "
            "each path to a list of repo-relative declared targets"
        )
    notes = document.get("dynamic_call_site_notes", {})
    if not isinstance(notes, dict) or not all(
        isinstance(path, str)
        and path in sites
        and isinstance(note, str)
        and note.strip()
        for path, note in notes.items()
    ):
        raise ValueError(
            f"training dependency closure {label} dynamic_call_site_notes must "
            "map declared dynamic paths to non-empty prose"
        )
    if any(not targets and path not in notes for path, targets in sites.items()):
        raise ValueError(
            f"training dependency closure {label} dynamic_call_sites entries "
            "without repo targets require a dynamic_call_site_notes explanation"
        )


def load_supplement(root: pathlib.Path) -> dict[str, Any] | None:
    """Load the optional per-workstream supplement, or None when absent.

    Absent means exactly the legacy behavior. A present-but-invalid supplement
    is a refusal, never silently ignored. The goal_id/workstream_id/
    next_executed_outcome keys are tolerated for the repository's
    authority-conservation gate, the sole validator of their values.
    """

    supplement_path = pathlib.Path(root) / SUPPLEMENT_RELATIVE_PATH
    if not os.path.lexists(supplement_path):
        return None
    try:
        supplement = json.loads(supplement_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            "training dependency closure supplement is unreadable"
        ) from error
    if not isinstance(supplement, dict):
        raise ValueError("training dependency closure supplement must be an object")
    if supplement.get("schema_version") != SUPPLEMENT_SCHEMA_VERSION:
        raise ValueError("training dependency closure supplement schema")
    allowed_keys = {
        "schema_version",
        "goal_id",
        "workstream_id",
        "next_executed_outcome",
        "purpose",
        "entrypoints",
        "dynamic_entrypoints",
        "code",
        "data",
        "dynamic_call_sites",
        "dynamic_call_site_notes",
    }
    unknown = sorted(set(supplement) - allowed_keys)
    if unknown:
        raise ValueError(
            "training dependency closure supplement carries unknown keys: "
            + ", ".join(unknown)
        )
    for key in ("entrypoints", "dynamic_entrypoints", "code", "data"):
        value = supplement.setdefault(key, [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) and _safe_repo_relative(item) for item in value
        ):
            raise ValueError(
                f"training dependency closure supplement {key} must be a list "
                "of safe repo-relative paths"
            )
    supplement.setdefault("dynamic_call_sites", {})
    _validate_call_sites(supplement, "supplement")
    return supplement


def _merge_supplement(
    manifest: dict[str, Any], supplement: dict[str, Any]
) -> dict[str, Any]:
    base_members = {
        member
        for key in ("entrypoints", "dynamic_entrypoints", "code", "data")
        for member in manifest[key]
    }
    seen: set[str] = set()
    for key in ("entrypoints", "dynamic_entrypoints", "code", "data"):
        for member in supplement[key]:
            if member == SUPPLEMENT_RELATIVE_PATH:
                raise ValueError(
                    "training dependency closure supplement must not list "
                    "itself; the self-declaration is implicit"
                )
            if member in base_members:
                raise ValueError(
                    "training dependency closure supplement re-declares a "
                    f"manifest member: {member}"
                )
            if member in seen:
                raise ValueError(
                    "training dependency closure supplement declares a member "
                    f"twice: {member}"
                )
            seen.add(member)
    supplement_members = seen
    undeclared_callers = sorted(
        caller
        for caller in supplement["dynamic_call_sites"]
        if caller not in base_members and caller not in supplement_members
    )
    if undeclared_callers:
        raise ValueError(
            "training dependency closure supplement dynamic_call_sites callers "
            "must be declared members: " + ", ".join(undeclared_callers)
        )
    duplicate_sites = sorted(
        set(manifest["dynamic_call_sites"]) & set(supplement["dynamic_call_sites"])
    )
    if duplicate_sites:
        raise ValueError(
            "training dependency closure supplement re-declares "
            "dynamic_call_sites for: " + ", ".join(duplicate_sites)
        )
    merged = dict(manifest)
    for key in ("entrypoints", "dynamic_entrypoints", "code", "data"):
        merged[key] = [*manifest[key], *supplement[key]]
    merged["dynamic_call_sites"] = {
        **manifest["dynamic_call_sites"],
        **supplement["dynamic_call_sites"],
    }
    merged["dynamic_call_site_notes"] = {
        **manifest.get("dynamic_call_site_notes", {}),
        **supplement.get("dynamic_call_site_notes", {}),
    }
    # The supplement declares itself, exactly as the manifest does: editing
    # the declaration must move the closure hash.
    merged["data"] = [*merged["data"], SUPPLEMENT_RELATIVE_PATH]
    return merged


def declared_paths(manifest: dict[str, Any]) -> tuple[str, ...]:
    """Every repo-relative path the manifest declares, deduplicated and sorted.

    The manifest declares itself: editing the declaration changes the hash.
    """

    paths = {
        *manifest["entrypoints"],
        *manifest["dynamic_entrypoints"],
        *manifest["code"],
        *manifest["data"],
        MANIFEST_RELATIVE_PATH,
    }
    return tuple(sorted(paths))


def walk_seeds(manifest: dict[str, Any]) -> tuple[str, ...]:
    """Where the reachability walk starts.

    The training entrypoints, plus the repo programs that are loaded through
    ``importlib.util.spec_from_file_location`` from paths assembled out of
    several literals -- a static walker cannot recover those, so they are
    declared, and declaring one still subjects ITS imports to the walk.
    """

    dynamic_targets = {
        target
        for targets in manifest["dynamic_call_sites"].values()
        for target in targets
    }
    return tuple(
        sorted(
            {
                *manifest["entrypoints"],
                *manifest["dynamic_entrypoints"],
                *dynamic_targets,
            }
        )
    )


def _module_candidates(
    root: pathlib.Path, source: pathlib.Path, module: str, level: int
) -> Iterable[pathlib.Path]:
    parts = module.split(".") if module else []
    if level:
        base = source.parent
        for _ in range(level - 1):
            base = base.parent
        bases = [base]
    else:
        # Sibling-directory first: the training entrypoints run as scripts, so
        # their own directory leads sys.path ahead of the repository root.
        bases = [source.parent, root]
    for base in bases:
        target = base.joinpath(*parts) if parts else base
        yield target.with_suffix(".py")
        yield target / "__init__.py"


def _import_edges(
    root: pathlib.Path, source: pathlib.Path, tree: ast.Module
) -> set[str]:
    edges: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            requests = [(alias.name, 0) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            requests = [(node.module or "", node.level)]
        else:
            continue
        for module, level in requests:
            for candidate in _module_candidates(root, source, module, level):
                if not candidate.is_file():
                    continue
                relative = _repo_relative(root, candidate)
                if relative is not None:
                    edges.add(relative)
                break
    return edges


def _exec_edges(root: pathlib.Path, source: pathlib.Path, tree: ast.Module) -> set[str]:
    """Repo executable programs named by string literals inside ``source``.

    Covers the shapes the training chain actually uses to spawn siblings:
    ``Path(__file__).with_name("verify_training_data.py")`` and the
    repo-relative ``"tools/ember-restart-3b/verify_capability_record.py"``.
    Script targets remain closure edges across Python, PowerShell, cmd, and sh.
    """

    edges: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        literal = node.value
        if not literal.endswith(EXECUTABLE_LITERAL_SUFFIXES) or "\n" in literal:
            continue
        for candidate in (source.parent / literal, root / literal):
            if not candidate.is_file():
                continue
            relative = _repo_relative(root, candidate)
            if relative is not None:
                edges.add(relative)
            break
    return edges


def _is_dynamic_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    if isinstance(function, ast.Name):
        return function.id in DYNAMIC_BARE_CALL_NAMES
    if not isinstance(function, ast.Attribute):
        return False
    root = function.value
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return False
    if root.id == "os":
        return (
            function.attr in {"popen", "posix_spawn", "posix_spawnp", "system"}
            or function.attr.startswith("exec")
            or function.attr.startswith("spawn")
        )
    return root.id in DYNAMIC_CALL_ROOTS and function.attr in (
        DYNAMIC_CALL_NAMES | DYNAMIC_BARE_CALL_NAMES
    )


def dynamic_call_sites(root: pathlib.Path, relative: str) -> bool:
    """Whether ``relative`` reaches code through a call the walk cannot follow."""

    source = pathlib.Path(root) / relative
    try:
        tree = ast.parse(source.read_bytes(), filename=str(source))
    except (OSError, SyntaxError, ValueError):
        return False
    return any(_is_dynamic_call(node) for node in ast.walk(tree))


def _resolved_path_values(
    root: pathlib.Path,
    source: pathlib.Path,
    node: ast.AST,
    assignments: dict[str, list[ast.AST]],
    resolving: frozenset[str] = frozenset(),
) -> set[pathlib.Path]:
    """Conservatively resolve path expressions used by dynamic calls."""

    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return {source}
        if node.id in {"root", "repo_root", "source_root"}:
            return {root}
        if node.id in assignments and node.id not in resolving:
            return {
                path
                for value in assignments[node.id]
                for path in _resolved_path_values(
                    root,
                    source,
                    value,
                    assignments,
                    resolving | {node.id},
                )
            }
        return set()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value
        if not value or "\n" in value:
            return set()
        return {root / value, source.parent / value}
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return {
            path
            for item in node.elts
            for path in _resolved_path_values(
                root, source, item, assignments, resolving
            )
        }
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _resolved_path_values(root, source, node.left, assignments, resolving)
        right = _resolved_path_values(root, source, node.right, assignments, resolving)
        right_suffixes: set[pathlib.Path] = set()
        for path in right:
            for base in (root, source.parent):
                try:
                    right_suffixes.add(path.relative_to(base))
                except ValueError:
                    continue
        return {base / suffix for base in left for suffix in right_suffixes}
    if isinstance(node, ast.Attribute):
        base = _resolved_path_values(root, source, node.value, assignments, resolving)
        if node.attr == "parent":
            return {path.parent for path in base}
        return base
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
        if node.value.attr != "parents":
            return set()
        base = _resolved_path_values(
            root, source, node.value.value, assignments, resolving
        )
        index = node.slice.value if isinstance(node.slice, ast.Constant) else None
        if not isinstance(index, int) or index < 0:
            return set()
        return {path.parents[index] for path in base if len(path.parents) > index}
    if isinstance(node, ast.Call):
        function = node.func
        if isinstance(function, ast.Name) and function.id in {"Path", "str"}:
            if not node.args:
                return set()
            return _resolved_path_values(
                root, source, node.args[0], assignments, resolving
            )
        if isinstance(function, ast.Name) and function.id == "_path":
            if len(node.args) < 2:
                return set()
            values = _resolved_path_values(
                root, source, node.args[1], assignments, resolving
            )
            return values
        if isinstance(function, ast.Attribute) and function.attr in {
            "resolve",
            "absolute",
        }:
            return _resolved_path_values(
                root, source, function.value, assignments, resolving
            )
        paths: set[pathlib.Path] = set()
        for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
            paths.update(
                _resolved_path_values(
                    root, source, argument, assignments, resolving
                )
            )
        return paths
    return set()


def dynamic_repo_targets(root: pathlib.Path, relative: str) -> tuple[str, ...]:
    """Repo files passed to a dynamic call in ``relative``."""

    root = pathlib.Path(root).resolve()
    source = root / relative
    try:
        tree = ast.parse(source.read_bytes(), filename=str(source))
    except (OSError, SyntaxError, ValueError):
        return ()
    assignments: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            assignments.setdefault(node.target.id, []).append(node.value)
    targets: set[str] = set()
    for node in ast.walk(tree):
        if not _is_dynamic_call(node):
            continue
        assert isinstance(node, ast.Call)
        function = node.func
        name = (
            function.id
            if isinstance(function, ast.Name)
            else function.attr if isinstance(function, ast.Attribute) else ""
        )
        if name == "spec_from_file_location" and len(node.args) >= 2:
            target_arguments = [node.args[1]]
        elif node.args and name in {
            "run_path",
            "run_module",
            "call",
            "check_call",
            "check_output",
            "Popen",
            "run",
            "popen",
            "posix_spawn",
            "posix_spawnp",
            "system",
        }:
            target_arguments = [node.args[0]]
        else:
            target_arguments = []
        for argument in target_arguments:
            for candidate in _resolved_path_values(
                root, source, argument, assignments
            ):
                if not candidate.is_file():
                    continue
                if candidate.suffix.lower() not in EXECUTABLE_LITERAL_SUFFIXES:
                    continue
                repo_relative = _repo_relative(root, candidate)
                if repo_relative is not None:
                    targets.add(repo_relative)
    return tuple(sorted(targets))


def walk_reachable(
    root: pathlib.Path, entrypoints: Iterable[str]
) -> tuple[str, ...]:
    """Every repo ``.py`` file reachable from ``entrypoints`` by import or exec."""

    root = pathlib.Path(root).resolve()
    pending = [str(entry) for entry in entrypoints]
    seen: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in seen:
            continue
        source = root / relative
        if not source.is_file():
            # A missing entrypoint is reported by audit_closure as `missing`;
            # the walk simply cannot descend through it.
            continue
        seen.add(relative)
        try:
            tree = ast.parse(source.read_bytes(), filename=str(source))
        except (OSError, SyntaxError, ValueError):
            continue
        pending.extend(_import_edges(root, source, tree))
        pending.extend(_exec_edges(root, source, tree))
    return tuple(sorted(seen))


def audit_closure(root: pathlib.Path, manifest: dict[str, Any] | None = None) -> ClosureAudit:
    """Compare the declared closure at ``root`` against the walked one."""

    root = pathlib.Path(root).resolve()
    manifest = manifest if manifest is not None else load_manifest(root)
    declared = declared_paths(manifest)
    reachable = walk_reachable(root, walk_seeds(manifest))
    declared_set = set(declared)
    undeclared = tuple(sorted(set(reachable) - declared_set))
    missing = tuple(
        sorted(path for path in declared if not (root / path).is_file())
    )

    dynamic_declared = set(manifest["dynamic_call_sites"])
    dynamic_actual = {
        relative
        for relative in declared
        if relative.endswith(".py")
        and (root / relative).is_file()
        and dynamic_call_sites(root, relative)
    }
    undeclared_dynamic = tuple(sorted(dynamic_actual - dynamic_declared))
    stale_dynamic = tuple(
        sorted(path for path in dynamic_declared - dynamic_actual if (root / path).is_file())
    )
    invalid_dynamic_targets = tuple(
        sorted(
            f"{caller} -> {target}"
            for caller, targets in manifest["dynamic_call_sites"].items()
            for target in targets
            if target not in declared_set or not (root / target).is_file()
        )
    )
    undeclared_dynamic_targets = tuple(
        sorted(
            f"{caller} -> {target}"
            for caller in dynamic_actual & dynamic_declared
            for target in dynamic_repo_targets(root, caller)
            if target not in set(manifest["dynamic_call_sites"][caller])
        )
    )

    return ClosureAudit(
        ok=not undeclared
        and not missing
        and not undeclared_dynamic
        and not stale_dynamic
        and not undeclared_dynamic_targets
        and not invalid_dynamic_targets,
        declared=declared,
        reachable=reachable,
        undeclared=undeclared,
        missing=missing,
        undeclared_dynamic=undeclared_dynamic,
        stale_dynamic=stale_dynamic,
        undeclared_dynamic_targets=undeclared_dynamic_targets,
        invalid_dynamic_targets=invalid_dynamic_targets,
    )


def compute_closure_hash(
    root: pathlib.Path, manifest: dict[str, Any] | None = None
) -> str:
    """Deterministic content hash over the declared closure files at ``root``.

    Sorted repo-relative POSIX paths; per-file sha256 of the raw bytes; one
    ``<path>\\0<sha256>\\n`` record each; sha256 over the concatenation. Depends
    only on the declared paths and their bytes, so the same tree always hashes
    the same and a tip that moved outside the closure does not move the hash.
    """

    root = pathlib.Path(root).resolve()
    manifest = manifest if manifest is not None else load_manifest(root)
    digest = hashlib.sha256()
    for relative in declared_paths(manifest):
        path = root / relative
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise ValueError(
                f"training dependency closure file is unreadable: {relative}"
            ) from error
        digest.update(
            f"{relative}\0{hashlib.sha256(payload).hexdigest()}\n".encode("utf-8")
        )
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(pathlib.Path(__file__).resolve().parents[1]),
        type=pathlib.Path,
    )
    parser.add_argument(
        "--print-hash",
        action="store_true",
        help="print the closure hash instead of auditing the boundary",
    )
    arguments = parser.parse_args(argv)
    try:
        manifest = load_manifest(arguments.root)
        if arguments.print_hash:
            print(compute_closure_hash(arguments.root, manifest))
            return 0
        audit = audit_closure(arguments.root, manifest)
    except ValueError as error:
        print(f"TRAINING_CLOSURE FAIL: {error}", file=sys.stderr)
        return 2
    if not audit.ok:
        print("TRAINING_CLOSURE FAIL", file=sys.stderr)
        print(audit.failure_report(), file=sys.stderr)
        return 1
    print(
        f"TRAINING_CLOSURE PASS: {len(audit.declared)} declared files, "
        f"{len(audit.reachable)} reachable, hash "
        f"{compute_closure_hash(arguments.root, manifest)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
