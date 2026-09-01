#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Census tracked Python self-location expressions and fail closed on stale roots."""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCHEMA = "ember-self-location-census-v1"
BASELINE_SCHEMA = "ember-self-location-baseline-v1"
BASELINE_EXPIRY_AUTHORITY = "OPERATOR_ONLY"
BASELINE_EXPIRY_CONSEQUENCE = (
    "after this date the gate fails on every baselined row, blocking all pull requests"
)


class Unsupported(ValueError):
    pass


@dataclass(frozen=True)
class DerivedPath:
    path: Path
    depends_on_file: bool


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _integer(node: ast.AST) -> int:
    if isinstance(node, ast.Constant) and type(node.value) is int and node.value >= 0:
        return node.value
    raise Unsupported("parent index is not a nonnegative integer literal")


def _derive(node: ast.AST, file_path: Path, aliases: dict[str, DerivedPath]) -> DerivedPath:
    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return DerivedPath(file_path, True)
        if node.id in aliases:
            return aliases[node.id]
        raise Unsupported(f"unknown alias {node.id}")
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return DerivedPath(Path(node.value), False)
    if isinstance(node, ast.Call):
        name = _call_name(node.func)
        if name in {"Path", "pathlib.Path"} and len(node.args) == 1:
            return _derive(node.args[0], file_path, aliases)
        if name == "str" and len(node.args) == 1:
            return _derive(node.args[0], file_path, aliases)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "resolve" and not node.args:
            base = _derive(node.func.value, file_path, aliases)
            return DerivedPath(base.path.resolve(), base.depends_on_file)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath":
            base = _derive(node.func.value, file_path, aliases)
            parts = [_derive(arg, file_path, aliases) for arg in node.args]
            if any(part.depends_on_file for part in parts):
                raise Unsupported("joinpath suffix may not itself depend on __file__")
            return DerivedPath(base.path.joinpath(*(str(part.path) for part in parts)), base.depends_on_file)
        if name in {"os.path.abspath", "abspath"} and len(node.args) == 1:
            base = _derive(node.args[0], file_path, aliases)
            return DerivedPath(Path(os.path.abspath(base.path)), base.depends_on_file)
        if name in {"os.path.dirname", "dirname"} and len(node.args) == 1:
            base = _derive(node.args[0], file_path, aliases)
            return DerivedPath(base.path.parent, base.depends_on_file)
        if name in {"os.path.join", "join"} and node.args:
            base = _derive(node.args[0], file_path, aliases)
            parts = [_derive(arg, file_path, aliases) for arg in node.args[1:]]
            if any(part.depends_on_file for part in parts):
                raise Unsupported("join suffix may not itself depend on __file__")
            return DerivedPath(base.path.joinpath(*(str(part.path) for part in parts)), base.depends_on_file)
        raise Unsupported(f"call outside closed grammar: {name or type(node.func).__name__}")
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _derive(node.value, file_path, aliases)
        return DerivedPath(base.path.parent, base.depends_on_file)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
        base = _derive(node.value.value, file_path, aliases)
        return DerivedPath(base.path.parents[_integer(node.slice)], base.depends_on_file)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _derive(node.left, file_path, aliases)
        right = _derive(node.right, file_path, aliases)
        if right.depends_on_file:
            raise Unsupported("path suffix may not depend on __file__")
        return DerivedPath(left.path / str(right.path), left.depends_on_file)
    raise Unsupported(f"node outside closed grammar: {type(node).__name__}")


def _root_like(name: str) -> bool:
    upper = name.upper()
    return "ROOT" in upper or upper == "HERE" or upper.endswith("_DIR") or upper.endswith("DIR")


def _portable_evaluated_path(root: Path, resolved: Path) -> str:
    """Render a resolved path without serializing the host checkout location."""
    relative = os.path.relpath(resolved, root).replace("\\", "/")
    return "<root>" if relative == "." else f"<root>/{relative}"


def _row(
    *, root: Path, path: Path, target: str, node: ast.AST, derived: DerivedPath | None,
    error: str | None,
) -> dict[str, object]:
    relative = path.relative_to(root).as_posix()
    expression = ast.unparse(node)
    expression_sha = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
    expectation = (
        "repo_root"
        if target != "<sys.path.insert>" and ("ROOT" in target.upper() or target.upper() in {"REPO", "REPOSITORY"})
        else "derived_location_only"
    )
    if derived is None:
        status, evaluated = "UNEVALUABLE", None
    else:
        resolved = derived.path.resolve()
        evaluated = _portable_evaluated_path(root, resolved)
        expected = root if expectation == "repo_root" else derived.path
        status = "MATCH" if os.path.normcase(str(resolved)) == os.path.normcase(str(expected.resolve())) else "MISMATCH"
    return {
        "path": relative,
        "line": getattr(node, "lineno", 0),
        "target": target,
        "expression": expression,
        "expression_sha256": expression_sha,
        "expectation": expectation,
        "evaluated_path": evaluated,
        "status": status,
        "error": error,
    }


def scan_files(root: Path, paths: Iterable[Path]) -> list[dict[str, object]]:
    root = root.resolve()
    rows: list[dict[str, object]] = []
    for path in sorted((item.resolve() for item in paths), key=lambda item: item.as_posix()):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        aliases: dict[str, DerivedPath] = {}
        for statement in tree.body:
            target: str | None = None
            value: ast.AST | None = None
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
                target, value = statement.targets[0].id, statement.value
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value is not None:
                target, value = statement.target.id, statement.value
            if target is not None and value is not None:
                try:
                    derived = _derive(value, path, aliases)
                except Unsupported as exc:
                    if _root_like(target):
                        rows.append(_row(root=root, path=path, target=target, node=value, derived=None, error=str(exc)))
                    continue
                if derived.depends_on_file:
                    aliases[target] = derived
                    rows.append(_row(root=root, path=path, target=target, node=value, derived=derived, error=None))
                continue
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                call = statement.value
                if _call_name(call.func) == "sys.path.insert" and len(call.args) >= 2:
                    try:
                        derived = _derive(call.args[1], path, aliases)
                        rows.append(_row(root=root, path=path, target="<sys.path.insert>", node=call.args[1], derived=derived, error=None))
                    except Unsupported as exc:
                        rows.append(_row(root=root, path=path, target="<sys.path.insert>", node=call.args[1], derived=None, error=str(exc)))
    return rows


def tracked_python_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", "*.py"],
        check=True, capture_output=True,
    )
    return [root / item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]


def _baseline_key(row: dict[str, object]) -> tuple[object, ...]:
    return tuple(
        row.get(key)
        for key in (
            "path", "line", "target", "expression_sha256", "evaluated_path", "status",
        )
    )


def enforce_baseline(rows: list[dict[str, object]], baseline: dict[str, object], today: dt.date) -> list[str]:
    if baseline.get("schema_version") != BASELINE_SCHEMA or not isinstance(baseline.get("rows"), list):
        return ["BASELINE_SCHEMA_INVALID"]
    unsigned = dict(baseline)
    claimed = unsigned.pop("self_sha256", None)
    computed = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if claimed != computed:
        return ["BASELINE_SELF_HASH_INVALID"]
    try:
        minted = dt.date.fromisoformat(str(baseline["minted_on"]))
        expires = dt.date.fromisoformat(str(baseline["expires_on"]))
    except (KeyError, ValueError):
        return ["BASELINE_DATES_INVALID"]
    baseline_rows = baseline["rows"]
    if (
        minted > expires
        or baseline.get("expiry_change_authority") != BASELINE_EXPIRY_AUTHORITY
        or baseline.get("expiry_consequence") != BASELINE_EXPIRY_CONSEQUENCE
        or baseline.get("baselined_row_count") != len(baseline_rows)
        or baseline.get("maximum_rows") != len(baseline_rows)
    ):
        return ["BASELINE_POLICY_INVALID"]
    failures = [row for row in rows if row["status"] != "MATCH"]
    allowed = {_baseline_key(row) for row in baseline_rows}
    current = {_baseline_key(row) for row in failures}
    errors: list[str] = []
    if today > expires and current:
        errors.append("BASELINE_EXPIRED_WITH_REMAINING_ROWS")
    if len(failures) > int(baseline.get("maximum_rows", -1)):
        errors.append("BASELINE_COUNT_GROWTH")
    if not current <= allowed:
        errors.append("NEW_OR_DRIFTED_SELF_LOCATION_ROW")
    return errors


def build_report(root: Path, paths: Iterable[Path], baseline: dict[str, object], today: dt.date) -> dict[str, object]:
    rows = scan_files(root, paths)
    errors = enforce_baseline(rows, baseline, today)
    return {
        "schema_version": SCHEMA,
        "result": "PASS" if not errors else "REFUSED",
        "root": str(root.resolve()),
        "tracked_python_files": len(list(paths)) if not isinstance(paths, list) else len(paths),
        "examined_rows": len(rows),
        "match_rows": sum(row["status"] == "MATCH" for row in rows),
        "mismatch_rows": sum(row["status"] == "MISMATCH" for row in rows),
        "unevaluable_rows": sum(row["status"] == "UNEVALUABLE" for row in rows),
        "errors": errors,
        "rows": rows,
    }


def mint_baseline(
    rows: list[dict[str, object]], *, minted_on: dt.date, expires_on: dt.date,
) -> dict[str, object]:
    if minted_on > expires_on:
        raise ValueError("baseline expiry precedes mint date")
    failures = [row for row in rows if row["status"] != "MATCH"]
    baseline: dict[str, object] = {
        "schema_version": BASELINE_SCHEMA,
        "minted_on": minted_on.isoformat(),
        "expires_on": expires_on.isoformat(),
        "expiry_change_authority": BASELINE_EXPIRY_AUTHORITY,
        "expiry_consequence": BASELINE_EXPIRY_CONSEQUENCE,
        "baselined_row_count": len(failures),
        "maximum_rows": len(failures),
        "rows": failures,
    }
    baseline["self_sha256"] = hashlib.sha256(
        json.dumps(baseline, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return baseline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.datetime.now(dt.timezone.utc).date())
    parser.add_argument("--mint-baseline-expiry", type=dt.date.fromisoformat)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    paths = tracked_python_files(root)
    if args.mint_baseline_expiry is not None:
        if args.baseline.exists():
            parser.error("baseline mint is no-overwrite")
        payload = mint_baseline(
            scan_files(root, paths), minted_on=args.today, expires_on=args.mint_baseline_expiry,
        )
        args.baseline.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"result": "BASELINE_MINTED", "rows": payload["maximum_rows"], "self_sha256": payload["self_sha256"]}, sort_keys=True))
        return 0
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    report = build_report(root, paths, baseline, args.today)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
