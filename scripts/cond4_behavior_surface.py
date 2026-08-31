# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic closed behavior-surface custody for the EMBER-01 cond4 battery.

Callers declare cross-module top-level roots. The manifest derives every
reachable same-module definition and refuses call targets that cannot be
resolved through lexical imports, explicit builtins, or that closed definition
graph. Edits elsewhere do not force an expensive battery replay. Execution
evidence remains a separate closed receipt, so a surface rebind cannot
masquerade as a real eight-axis execution.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


SURFACE_SCHEMA = "ember-cond4-behavior-surface-v1"
EXECUTION_SCHEMA = "ember-cond4-execution-evidence-v1"
VALIDATOR_REL = "scripts/cond4_behavior_surface.py"
COND4_AXES = (
    "checkpoint_bytes",
    "param_count",
    "tokenizer",
    "data_learned_signal",
    "mechanism",
    "backend",
    "benchmark_id",
    "comparator",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DYNAMIC_CALLS = {"eval", "exec", "getattr", "globals", "locals"}
_CALL_BINDING = re.compile(
    r"^[A-Za-z_]\w*(?:(?:\.[A-Za-z_]\w*)|(?:\[(?:['\"][A-Za-z_]\w*['\"]|[0-9]+)\]))+$"
)
_ALLOWED_BUILTIN_CALLS = {
    "all",
    "abs",
    "any",
    "bool",
    "bytes",
    "dict",
    "enumerate",
    "Exception",
    "float",
    "frozenset",
    "int",
    "isinstance",
    "KeyError",
    "len",
    "list",
    "map",
    "max",
    "min",
    "OSError",
    "print",
    "range",
    "reversed",
    "set",
    "sorted",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "TypeError",
    "UnicodeDecodeError",
    "ValueError",
    "RuntimeError",
    "zip",
}


class SurfaceRefusal(ValueError):
    """Named, path-free cond4 custody refusal."""


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _relative_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
    candidate = (root / relative).resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise SurfaceRefusal("COND4_SURFACE_PATH_OUTSIDE_ROOT") from exc
    if not candidate.is_file():
        raise SurfaceRefusal("COND4_SURFACE_PATH_INVALID")
    return candidate


def _definition_bytes(source: bytes, node: ast.AST) -> bytes:
    first_line = getattr(node, "lineno", None)
    last_line = getattr(node, "end_lineno", None)
    decorators = getattr(node, "decorator_list", ())
    if decorators:
        first_line = min(first_line, *(item.lineno for item in decorators))
    if not isinstance(first_line, int) or not isinstance(last_line, int):
        raise SurfaceRefusal("COND4_SURFACE_AST_RANGE_INVALID")
    lines = source.splitlines(keepends=True)
    return b"".join(lines[first_line - 1 : last_line])


class _ScopeFacts(ast.NodeVisitor):
    def __init__(self, root: ast.AST) -> None:
        self.root = root
        self.imports: set[str] = set()
        self.bound_names: set[str] = set()
        self.loaded_names: set[str] = set()
        self.nested: dict[str, ast.AST] = {}
        self.lambdas: list[ast.Lambda] = []
        self.calls: list[ast.Call] = []
        self.has_nonlocal_binding = False

    def _visit_arguments(self, arguments: ast.arguments) -> None:
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ):
            self.bound_names.add(argument.arg)
        if arguments.vararg is not None:
            self.bound_names.add(arguments.vararg.arg)
        if arguments.kwarg is not None:
            self.bound_names.add(arguments.kwarg.arg)
        for default in (*arguments.defaults, *arguments.kw_defaults):
            if default is not None:
                self.visit(default)

    def _visit_function_outer_expressions(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ):
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if node.args.vararg is not None and node.args.vararg.annotation is not None:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
            self.visit(node.args.kwarg.annotation)
        if node.returns is not None:
            self.visit(node.returns)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            self._visit_function_outer_expressions(node)
            self._visit_arguments(node.args)
            for statement in node.body:
                self.visit(statement)
            return
        self.nested[node.name] = node
        self._visit_function_outer_expressions(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            self._visit_function_outer_expressions(node)
            self._visit_arguments(node.args)
            for statement in node.body:
                self.visit(statement)
            return
        self.nested[node.name] = node
        self._visit_function_outer_expressions(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node is self.root:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword.value)
            for statement in node.body:
                self.visit(statement)
            return
        self.nested[node.name] = node
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.imports.add(alias.asname or alias.name)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.bound_names.add(node.id)
        elif isinstance(node.ctx, ast.Load):
            self.loaded_names.add(node.id)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        if node is self.root:
            self._visit_arguments(node.args)
            self.visit(node.body)
            return
        self.lambdas.append(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if isinstance(node.name, str):
            self.bound_names.add(node.name)
        if node.type is not None:
            self.visit(node.type)
        for statement in node.body:
            self.visit(statement)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self.bound_names.add(node.name)
        if node.pattern is not None:
            self.visit(node.pattern)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self.bound_names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self.bound_names.add(node.rest)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.has_nonlocal_binding = True

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.has_nonlocal_binding = True

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)


def _scope_facts(node: ast.AST) -> _ScopeFacts:
    facts = _ScopeFacts(node)
    facts.visit(node)
    return facts


def _attribute_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(parts)])


def _known_call_origin(
    node: ast.AST,
    definitions: Mapping[str, ast.AST],
    module_names: set[str],
    nested_names: set[str],
    shadowed_names: set[str],
) -> str | None:
    if isinstance(node, ast.Name):
        if node.id in shadowed_names:
            return None
        if (
            node.id in definitions
            or node.id in module_names
            or node.id in nested_names
            or node.id in _ALLOWED_BUILTIN_CALLS
        ):
            return node.id
        return None
    if isinstance(node, ast.Attribute):
        dotted = _attribute_name(node)
        if dotted is None:
            return None
        root = dotted.split(".", 1)[0]
        if root in shadowed_names:
            return None
        if (
            root in definitions
            or root in module_names
            or root in nested_names
            or root in _ALLOWED_BUILTIN_CALLS
        ):
            return dotted
        return None
    if isinstance(node, ast.Call):
        return _known_call_origin(
            node.func, definitions, module_names, nested_names, shadowed_names
        )
    if isinstance(node, ast.Constant):
        return type(node.value).__name__
    return None


def _resolved_calls(
    node: ast.AST,
    definitions: Mapping[str, ast.AST],
    module_names: set[str],
    allowed_dynamic_calls: set[str],
) -> tuple[set[str], set[str], set[str], set[str]]:
    local_calls: set[str] = set()
    external_calls: set[str] = set()
    used_dynamic_calls: set[str] = set()
    used_module_names: set[str] = set()

    def analyze_scope(
        scope: ast.AST,
        inherited_imports: set[str],
        inherited_nested: set[str],
        inherited_shadowed: set[str],
    ) -> None:
        facts = _scope_facts(scope)
        if facts.has_nonlocal_binding:
            scope_name = getattr(scope, "name", type(scope).__name__)
            raise SurfaceRefusal(
                f"COND4_SURFACE_DYNAMIC_SCOPE_UNRESOLVED:{scope_name}"
            )
        ambiguous = facts.imports & facts.bound_names
        imported_names = (inherited_imports | facts.imports) - ambiguous
        nested_names = inherited_nested | set(facts.nested)
        shadowed_names = inherited_shadowed | facts.bound_names | ambiguous
        call_target_names = {
            call.func.id for call in facts.calls if isinstance(call.func, ast.Name)
        }
        call_target_names.update(
            dotted.split(".", 1)[0]
            for call in facts.calls
            if isinstance(call.func, ast.Attribute)
            for dotted in [_attribute_name(call.func)]
            if dotted is not None
        )

        for call in facts.calls:
            target = call.func
            if isinstance(target, ast.Name):
                name = target.id
                if name in _DYNAMIC_CALLS or name in shadowed_names:
                    raise SurfaceRefusal(f"COND4_SURFACE_DYNAMIC_CALL_UNRESOLVED:{name}")
                if name in nested_names:
                    external_calls.add(name)
                elif name in definitions:
                    local_calls.add(name)
                elif name in imported_names or name in _ALLOWED_BUILTIN_CALLS:
                    external_calls.add(name)
                elif name in module_names:
                    used_module_names.add(name)
                    external_calls.add(name)
                else:
                    raise SurfaceRefusal(f"COND4_SURFACE_DYNAMIC_CALL_UNRESOLVED:{name}")
                continue
            if isinstance(target, ast.Attribute):
                dotted = _attribute_name(target)
                binding = dotted or ast.unparse(target)
                origin = _known_call_origin(
                    target.value,
                    definitions,
                    imported_names | module_names,
                    nested_names,
                    shadowed_names,
                )
                if dotted is None and isinstance(target.value, ast.Call):
                    called = _known_call_origin(
                        target.value.func,
                        definitions,
                        imported_names | module_names,
                        nested_names,
                        shadowed_names,
                    )
                    if called is not None:
                        dotted = f"{called}.{target.attr}"
                        origin = called
                elif dotted is None and origin is not None:
                    dotted = f"{origin}.{target.attr}"
                if origin is None and binding in allowed_dynamic_calls:
                    if target.attr in definitions:
                        raise SurfaceRefusal(
                            f"COND4_SURFACE_DYNAMIC_CALL_UNRESOLVED:{binding}"
                        )
                    used_dynamic_calls.add(binding)
                    external_calls.add(f"explicit:{binding}")
                    continue
                if origin is None or dotted is None or dotted.split(".", 1)[0] in _DYNAMIC_CALLS:
                    raise SurfaceRefusal(
                        "COND4_SURFACE_DYNAMIC_CALL_UNRESOLVED:"
                        + (dotted or ast.unparse(target))
                    )
                root_name = dotted.split(".", 1)[0]
                if root_name in definitions:
                    local_calls.add(root_name)
                elif root_name in module_names:
                    used_module_names.add(root_name)
                external_calls.add(dotted)
                continue
            raise SurfaceRefusal(
                f"COND4_SURFACE_DYNAMIC_CALL_UNRESOLVED:{type(target).__name__}"
            )

        for name in facts.loaded_names:
            if (
                name in call_target_names
                or name in _DYNAMIC_CALLS
                or name in shadowed_names
                or name in imported_names
                or name in nested_names
                or name in _ALLOWED_BUILTIN_CALLS
            ):
                continue
            if name in definitions:
                local_calls.add(name)
            elif name in module_names:
                used_module_names.add(name)
            else:
                raise SurfaceRefusal(f"COND4_SURFACE_GLOBAL_UNRESOLVED:{name}")

        for nested in facts.nested.values():
            analyze_scope(
                nested,
                imported_names,
                nested_names,
                shadowed_names,
            )
        for nested_lambda in facts.lambdas:
            analyze_scope(
                nested_lambda,
                imported_names,
                nested_names,
                shadowed_names,
            )

    analyze_scope(node, set(), set(), set())
    return local_calls, external_calls, used_dynamic_calls, used_module_names


def _module_binding_map(tree: ast.Module) -> dict[str, list[ast.stmt]]:
    bindings: dict[str, list[ast.stmt]] = {}
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        bindings["__doc__"] = [tree.body[0]]
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        facts = _scope_facts(statement)
        for name in sorted(facts.imports | facts.bound_names):
            bindings.setdefault(name, []).append(statement)
    return bindings


def _module_binding_rows(
    source: bytes,
    binding_map: Mapping[str, Sequence[ast.stmt]],
    used_names: set[str],
) -> list[dict[str, Any]]:
    statements: dict[int, ast.stmt] = {}
    for name in used_names:
        rows = binding_map.get(name)
        if not rows:
            raise SurfaceRefusal(f"COND4_SURFACE_GLOBAL_UNRESOLVED:{name}")
        for statement in rows:
            statements[id(statement)] = statement
    result: list[dict[str, Any]] = []
    for statement in sorted(
        statements.values(), key=lambda item: (item.lineno, item.end_lineno or item.lineno)
    ):
        blob = _definition_bytes(source, statement)
        names = sorted(
            name for name, rows in binding_map.items() if any(row is statement for row in rows)
        )
        result.append(
            {
                "names": names,
                "sha256": hashlib.sha256(blob).hexdigest(),
                "size_bytes": len(blob),
            }
        )
    return result


def _closed_symbol_rows(
    path: Path,
    roots: Sequence[str],
    dynamic_call_bindings: Sequence[str] = (),
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    source = path.read_bytes()
    try:
        tree = ast.parse(source, filename=path.name)
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise SurfaceRefusal("COND4_SURFACE_SOURCE_INVALID") from exc
    definitions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    ordered_roots = sorted(roots)
    if (
        not ordered_roots
        or len(ordered_roots) != len(set(ordered_roots))
        or any(not isinstance(name, str) or not name for name in ordered_roots)
    ):
        raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
    if any(name not in definitions for name in ordered_roots):
        raise SurfaceRefusal("COND4_SURFACE_SYMBOL_MISSING")
    ordered_dynamic = sorted(dynamic_call_bindings)
    if (
        len(ordered_dynamic) != len(set(ordered_dynamic))
        or any(
            not isinstance(name, str)
            or not _CALL_BINDING.fullmatch(name)
            for name in ordered_dynamic
        )
    ):
        raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")

    module_bindings = _module_binding_map(tree)
    module_names = set(module_bindings)
    if set(definitions) & module_names:
        raise SurfaceRefusal("COND4_SURFACE_MODULE_BINDING_AMBIGUOUS")
    pending = list(ordered_roots)
    closed: set[str] = set()
    external_calls: set[str] = set()
    used_dynamic_calls: set[str] = set()
    used_module_names: set[str] = set()
    while pending:
        name = pending.pop(0)
        if name in closed:
            continue
        closed.add(name)
        local, external, used_dynamic, used_module = _resolved_calls(
            definitions[name],
            definitions,
            module_names,
            set(ordered_dynamic),
        )
        pending.extend(sorted(local - closed))
        external_calls.update(external)
        used_dynamic_calls.update(used_dynamic)
        used_module_names.update(used_module)

    if used_dynamic_calls != set(ordered_dynamic):
        raise SurfaceRefusal("COND4_SURFACE_UNUSED_DYNAMIC_BINDING")

    rows: list[dict[str, Any]] = []
    for name in sorted(closed):
        blob = _definition_bytes(source, definitions[name])
        rows.append(
            {
                "name": name,
                "sha256": hashlib.sha256(blob).hexdigest(),
                "size_bytes": len(blob),
            }
        )
    binding_rows = _module_binding_rows(source, module_bindings, used_module_names)
    return ordered_roots, rows, binding_rows, sorted(external_calls), ordered_dynamic


def _file_specification(value: Any) -> tuple[Sequence[str], Sequence[str]]:
    if isinstance(value, Mapping):
        if set(value) != {"roots", "dynamic_call_bindings"}:
            raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
        roots = value.get("roots")
        bindings = value.get("dynamic_call_bindings")
        if not isinstance(roots, Sequence) or isinstance(roots, (str, bytes)):
            raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
        if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
            raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
        return roots, bindings
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
    return value, ()


def build_surface_manifest(
    root: Path, specification: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(specification, Mapping) or not specification:
        raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
    files: list[dict[str, Any]] = []
    for relative in sorted(specification):
        path = _relative_file(root, relative)
        requested_roots, requested_bindings = _file_specification(specification[relative])
        (
            roots,
            symbols,
            module_bindings,
            external_calls,
            dynamic_call_bindings,
        ) = _closed_symbol_rows(
            path,
            requested_roots,
            requested_bindings,
        )
        identity = {
            "roots": roots,
            "symbols": symbols,
            "module_bindings": module_bindings,
            "external_calls": external_calls,
            "dynamic_call_bindings": dynamic_call_bindings,
        }
        files.append(
            {
                "path": relative,
                "roots": roots,
                "symbols": symbols,
                "module_bindings": module_bindings,
                "external_calls": external_calls,
                "dynamic_call_bindings": dynamic_call_bindings,
                "sha256": _canonical_sha256(identity),
            }
        )
    return {
        "schema": SURFACE_SCHEMA,
        "files": files,
        "aggregate_sha256": _canonical_sha256(files),
    }


def _surface_specification(manifest: Mapping[str, Any]) -> dict[str, dict[str, list[str]]]:
    if set(manifest) != {"schema", "files", "aggregate_sha256"}:
        raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
    if manifest.get("schema") != SURFACE_SCHEMA:
        raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
    specification: dict[str, dict[str, list[str]]] = {}
    for row in files:
        if not isinstance(row, dict) or set(row) != {
            "path",
            "roots",
            "symbols",
            "module_bindings",
            "external_calls",
            "dynamic_call_bindings",
            "sha256",
        }:
            raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
        path = row.get("path")
        roots = row.get("roots")
        symbols = row.get("symbols")
        module_bindings = row.get("module_bindings")
        external_calls = row.get("external_calls")
        dynamic_call_bindings = row.get("dynamic_call_bindings")
        if (
            not isinstance(path, str)
            or path in specification
            or not isinstance(roots, list)
            or not roots
            or not all(isinstance(name, str) and name for name in roots)
            or roots != sorted(set(roots))
            or not isinstance(symbols, list)
            or not isinstance(module_bindings, list)
            or not isinstance(external_calls, list)
            or external_calls != sorted(set(external_calls))
            or not all(isinstance(name, str) and name for name in external_calls)
            or not isinstance(dynamic_call_bindings, list)
            or dynamic_call_bindings != sorted(set(dynamic_call_bindings))
            or not all(
                isinstance(name, str) and _CALL_BINDING.fullmatch(name)
                for name in dynamic_call_bindings
            )
        ):
            raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
        for symbol in symbols:
            if not isinstance(symbol, dict) or set(symbol) != {"name", "sha256", "size_bytes"}:
                raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
            name = symbol.get("name")
            digest = symbol.get("sha256")
            size = symbol.get("size_bytes")
            if not isinstance(name, str) or not _SHA256.fullmatch(str(digest)):
                raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
        for binding in module_bindings:
            if not isinstance(binding, dict) or set(binding) != {
                "names",
                "sha256",
                "size_bytes",
            }:
                raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
            names = binding.get("names")
            digest = binding.get("sha256")
            size = binding.get("size_bytes")
            if (
                not isinstance(names, list)
                or not names
                or names != sorted(set(names))
                or not all(isinstance(name, str) and name for name in names)
                or not _SHA256.fullmatch(str(digest))
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size <= 0
            ):
                raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
        if not _SHA256.fullmatch(str(row.get("sha256"))) or row.get("sha256") != _canonical_sha256(
            {
                "roots": roots,
                "symbols": symbols,
                "module_bindings": module_bindings,
                "external_calls": external_calls,
                "dynamic_call_bindings": dynamic_call_bindings,
            }
        ):
            raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
        specification[path] = {
            "roots": roots,
            "dynamic_call_bindings": dynamic_call_bindings,
        }
    if not _SHA256.fullmatch(str(manifest.get("aggregate_sha256"))):
        raise SurfaceRefusal("COND4_SURFACE_SCHEMA_INVALID")
    return specification


def validate_surface_manifest(root: Path, manifest: Mapping[str, Any]) -> None:
    specification = _surface_specification(manifest)
    current = build_surface_manifest(root, specification)
    if current != manifest:
        raise SurfaceRefusal("COND4_SURFACE_MISMATCH")


def validate_execution_evidence(evidence: Mapping[str, Any]) -> None:
    if not isinstance(evidence, Mapping) or set(evidence) != {"schema", "subject", "axes"}:
        raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
    if evidence.get("schema") != EXECUTION_SCHEMA:
        raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
    subject = evidence.get("subject")
    if not isinstance(subject, Mapping) or set(subject) != {
        "behavior_surface_validator_sha256",
        "checkpoint_manifest_sha256",
        "surface_aggregate_sha256",
        "checkpoint_bytes_loaded",
        "load_count",
    }:
        raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
    if not _SHA256.fullmatch(str(subject.get("behavior_surface_validator_sha256"))):
        raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
    if not _SHA256.fullmatch(str(subject.get("checkpoint_manifest_sha256"))):
        raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
    if not _SHA256.fullmatch(str(subject.get("surface_aggregate_sha256"))):
        raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
    for field in ("checkpoint_bytes_loaded", "load_count"):
        value = subject.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
    rows = evidence.get("axes")
    if not isinstance(rows, list) or len(rows) != len(COND4_AXES):
        raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "axis",
            "duration_ms",
            "rejected",
            "finding_codes",
        }:
            raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
        axis = row.get("axis")
        duration = row.get("duration_ms")
        findings = row.get("finding_codes")
        if axis not in COND4_AXES or axis in seen:
            raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
        if row.get("rejected") is not True:
            raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
        if not isinstance(findings, list) or not findings or not all(
            isinstance(item, str) and item for item in findings
        ):
            raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")
        seen.add(axis)
    if seen != set(COND4_AXES):
        raise SurfaceRefusal("COND4_EXECUTION_EVIDENCE_INVALID")


def validate_execution_packet(
    root: Path,
    manifest: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    validator_candidate = root / VALIDATOR_REL
    validator_path = validator_candidate.resolve(strict=True)
    validator_parent_candidate = root / "scripts"
    if validator_path.parent != validator_parent_candidate.resolve():
        raise SurfaceRefusal("COND4_EXECUTION_VALIDATOR_MISMATCH")
    validator_sha256 = hashlib.sha256(validator_path.read_bytes()).hexdigest()
    subject = evidence.get("subject") if isinstance(evidence, Mapping) else None
    if (
        not isinstance(subject, Mapping)
        or subject.get("behavior_surface_validator_sha256") != validator_sha256
    ):
        raise SurfaceRefusal("COND4_EXECUTION_VALIDATOR_MISMATCH")
    validate_surface_manifest(root, manifest)
    validate_execution_evidence(evidence)
    subject = evidence["subject"]
    if subject["surface_aggregate_sha256"] != manifest["aggregate_sha256"]:
        raise SurfaceRefusal("COND4_EXECUTION_SURFACE_MISMATCH")
