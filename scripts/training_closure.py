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
  against the repo, plus exec edges recovered from ``.py`` string literals
  (``Path(__file__).with_name("verify_training_data.py")`` and friends).
* ``dynamic_call_sites`` finds the call shapes a static walk CANNOT follow --
  ``subprocess``, ``importlib``, ``runpy``, ``__import__``. Every closure member
  that uses one must declare it in the manifest, and a declaration for a file
  that no longer uses one is equally a failure. An undeclared dynamic edge is a
  red, not a gap.
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
import pathlib
import sys
from typing import Any, Iterable, NamedTuple


MANIFEST_RELATIVE_PATH = "manifests/training-dependency-closure.json"
MANIFEST_SCHEMA_VERSION = "ember-training-dependency-closure-v1"


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


class ClosureAudit(NamedTuple):
    """Result of comparing the declared closure against the walked one."""

    ok: bool
    declared: tuple[str, ...]
    reachable: tuple[str, ...]
    undeclared: tuple[str, ...]
    missing: tuple[str, ...]
    undeclared_dynamic: tuple[str, ...]
    stale_dynamic: tuple[str, ...]

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
                "closure members reach code through subprocess/importlib/runpy/"
                f"__import__ without a dynamic_call_sites entry in "
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
        and targets
        and all(isinstance(target, str) and target for target in targets)
        for path, targets in sites.items()
    ):
        raise ValueError(
            "training dependency closure manifest dynamic_call_sites must map "
            "each path to a non-empty list of declared targets"
        )
    return manifest


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

    return tuple(
        sorted({*manifest["entrypoints"], *manifest["dynamic_entrypoints"]})
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
    """Repo ``.py`` programs named by string literals inside ``source``.

    Covers the shapes the training chain actually uses to spawn siblings:
    ``Path(__file__).with_name("verify_training_data.py")`` and the
    repo-relative ``"tools/ember-restart-3b/verify_capability_record.py"``.
    """

    edges: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        literal = node.value
        if not literal.endswith(".py") or "\n" in literal:
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
        return function.id == "__import__"
    if not isinstance(function, ast.Attribute):
        return False
    if function.attr not in DYNAMIC_CALL_NAMES:
        return False
    root = function.value
    while isinstance(root, ast.Attribute):
        root = root.value
    return isinstance(root, ast.Name) and root.id in DYNAMIC_CALL_ROOTS


def dynamic_call_sites(root: pathlib.Path, relative: str) -> bool:
    """Whether ``relative`` reaches code through a call the walk cannot follow."""

    source = pathlib.Path(root) / relative
    try:
        tree = ast.parse(source.read_bytes(), filename=str(source))
    except (OSError, SyntaxError, ValueError):
        return False
    return any(_is_dynamic_call(node) for node in ast.walk(tree))


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

    return ClosureAudit(
        ok=not undeclared
        and not missing
        and not undeclared_dynamic
        and not stale_dynamic,
        declared=declared,
        reachable=reachable,
        undeclared=undeclared,
        missing=missing,
        undeclared_dynamic=undeclared_dynamic,
        stale_dynamic=stale_dynamic,
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
