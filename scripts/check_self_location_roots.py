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
BASELINE_GOAL_BINDING = {
    "goal_id": "EMBER-02",
    "workstream_id": "EMBER-02A",
    "next_executed_outcome": (
        "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    ),
}


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


def _marker_condition_name(test: ast.AST, target: str) -> str:
    """Return the marker filename from `(target / "name").is_file()`, or refuse.

    Only the three existence predicates are admitted, and only over a literal name joined to the
    comprehension's own target. Anything else changes what the search means.
    """

    if not isinstance(test, ast.Call) or test.args or test.keywords:
        raise Unsupported("repo-marker condition is not a bare existence call")
    if not isinstance(test.func, ast.Attribute) or test.func.attr not in {
        "is_file", "exists", "is_dir"
    }:
        raise Unsupported("repo-marker condition is not an existence predicate")
    joined = test.func.value
    if (
        not isinstance(joined, ast.BinOp)
        or not isinstance(joined.op, ast.Div)
        or not isinstance(joined.left, ast.Name)
        or joined.left.id != target
        or not isinstance(joined.right, ast.Constant)
        or not isinstance(joined.right.value, str)
    ):
        raise Unsupported("repo-marker condition is not target / literal")
    return joined.right.value


def _derive_repo_marker_walk(
    node: ast.AST, file_path: Path, aliases: dict[str, DerivedPath]
) -> DerivedPath:
    """Evaluate `next(p for p in <__file__ derived>.parents if (p / "marker").is_file())`."""

    if not isinstance(node, (ast.GeneratorExp, ast.ListComp)):
        raise Unsupported("next() argument is not a comprehension over parents")
    if len(node.generators) != 1:
        raise Unsupported("repo-marker walk has more than one comprehension")
    comprehension = node.generators[0]
    if comprehension.is_async or len(comprehension.ifs) != 1:
        raise Unsupported("repo-marker walk needs exactly one synchronous condition")
    if not isinstance(comprehension.target, ast.Name):
        raise Unsupported("repo-marker walk target is not a plain name")
    target = comprehension.target.id
    if not isinstance(node.elt, ast.Name) or node.elt.id != target:
        raise Unsupported("repo-marker walk yields something other than the parent")
    if not isinstance(comprehension.iter, ast.Attribute) or comprehension.iter.attr != "parents":
        raise Unsupported("repo-marker walk does not iterate .parents")

    base = _derive(comprehension.iter.value, file_path, aliases)
    if not base.depends_on_file:
        # The whole point of the rule is that the search STARTS at this file. A walk rooted
        # anywhere else cannot be evaluated from the source alone, and answering it against this
        # checkout would report a verdict for an expression never actually evaluated.
        raise Unsupported("repo-marker walk does not start at __file__")

    marker = _marker_condition_name(comprehension.ifs[0], target)
    for parent in base.path.parents:
        if (parent / marker).exists():
            return DerivedPath(parent, True)
    raise Unsupported(f"no parent carries the repo marker {marker}")


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
        if name in {"os.path.normpath", "normpath"} and len(node.args) == 1:
            # Purely textual: normpath collapses `..` and redundant separators without consulting
            # the filesystem, so the grammar can apply it exactly rather than approximate it. It
            # carries depends_on_file through, which is what keeps the row EMITTED -- a derivation
            # that loses that flag is dropped by scan_files, so a cure that severed it would delete
            # the row instead of arming it.
            base = _derive(node.args[0], file_path, aliases)
            return DerivedPath(Path(os.path.normpath(base.path)), base.depends_on_file)
        if name in {"os.path.dirname", "dirname"} and len(node.args) == 1:
            base = _derive(node.args[0], file_path, aliases)
            return DerivedPath(base.path.parent, base.depends_on_file)
        if name in {"os.path.join", "join"} and node.args:
            base = _derive(node.args[0], file_path, aliases)
            parts = [_derive(arg, file_path, aliases) for arg in node.args[1:]]
            if any(part.depends_on_file for part in parts):
                raise Unsupported("join suffix may not itself depend on __file__")
            return DerivedPath(base.path.joinpath(*(str(part.path) for part in parts)), base.depends_on_file)
        if name == "next" and len(node.args) == 1 and not node.keywords:
            return _derive_repo_marker_walk(node.args[0], file_path, aliases)
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
    if isinstance(node, ast.JoinedStr):
        # An f-string that concatenates already-derivable parts is the same expression as the
        # `/` and joinpath forms this grammar already resolves -- f"{NC}/scripts" and NC / "scripts"
        # differ in spelling, not in what they denote. Each part must itself RESOLVE: a part the
        # grammar cannot derive still raises, so this extension makes rows evaluable (and therefore
        # able to FAIL on MATCH) rather than making them stop being counted.
        segments: list[str] = []
        depends = False
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                segments.append(value.value)
                continue
            if not isinstance(value, ast.FormattedValue):
                raise Unsupported(
                    f"f-string part outside closed grammar: {type(value).__name__}"
                )
            if value.conversion != -1 or value.format_spec is not None:
                # !r / !s / :spec change the rendered text, so the path in the source is not the
                # path the grammar would compute. Refuse rather than guess.
                raise Unsupported("f-string part applies a conversion or format spec")
            part = _derive(value.value, file_path, aliases)
            segments.append(str(part.path))
            depends = depends or part.depends_on_file
        return DerivedPath(Path("".join(segments)), depends)
    raise Unsupported(f"node outside closed grammar: {type(node).__name__}")


def _root_like(name: str) -> bool:
    upper = name.upper()
    return "ROOT" in upper or upper == "HERE" or upper.endswith("_DIR") or upper.endswith("DIR")


# Recognised by NAME, exactly as _derive already recognises `Path` and `os.path.dirname`. A module
# that rebound one of these to something returning a path would defeat the check, which is why the
# set is closed and short rather than a general list of calls that look uninteresting.
_NOT_A_PATH_CALLS = frozenset({"set", "frozenset", "re.compile"})


def _provably_not_a_path(node: ast.AST) -> bool:
    """Is this binding's value incapable of being a path, whatever its NAME suggests?

    _root_like is purely name-based -- it matches any identifier containing ROOT or ending in DIR --
    so a compiled regex called _DRIVE_ROOT_RE, a set of field names called ROOT_FIELDS and a dict of
    exceptions called ROOT_EXCEPTIONS all enter the census by coincidence of naming. They refuse,
    correctly, and then sit in the baseline as UNEVALUABLE rows about which no justification can say
    anything truer than "this was never a path".

    Dropping them is a scope reduction, so it owes the test that governs those: could any removed row
    have failed? No. Each is UNEVALUABLE, a status that can never become MATCH or MISMATCH, and the
    value is not a path. Nor is the watch lost. The census is recomputed from source on every run, so
    repointing one of these names at a host path yields a fresh, unbaselined row on the next scan --
    which is precisely the failure this gate exists to catch.

    Set and Dict, not List and Tuple. The difference is not that a set of paths is unimaginable; it is
    that a set and a dict have no element ORDER, so there is no stable per-element identity for a row
    to be keyed on. A list or tuple has indices, and its elements here genuinely do reach __file__ --
    those rows are a named successor (one row per element), not noise, and they stay.
    """
    if isinstance(node, (ast.Set, ast.SetComp, ast.Dict, ast.DictComp)):
        return True
    return isinstance(node, ast.Call) and _call_name(node.func) in _NOT_A_PATH_CALLS


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
    root_like_name = target != "<sys.path.insert>" and (
        "ROOT" in target.upper() or target.upper() in {"REPO", "REPOSITORY"}
    )
    # A binding that joins segments onto a root names a subdirectory, whatever it is called, so
    # it makes no claim about where the repository is and cannot be measured against the root.
    # f"{ROOT}/sub" appends segments exactly as ROOT / "sub" does, so the two spellings must
    # get the same expectation. Without this a root-named target bound to a segment-appending
    # f-string would be measured against the repository root and fail for appending a
    # subdirectory -- a false MISMATCH the `/` form is explicitly exempted from.
    appends_segments = (
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
    ) or (isinstance(node, ast.JoinedStr) and len(node.values) > 1)
    expectation = (
        "repo_root" if root_like_name and not appends_segments else "derived_location_only"
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
                    if _root_like(target) and not _provably_not_a_path(value):
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
        or any(baseline.get(key) != value for key, value in BASELINE_GOAL_BINDING.items())
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


class UnjustifiedRows(Exception):
    """Raised when a mint is asked to baseline a row for which no reason was supplied.

    Carries the rows themselves rather than a count, because the caller's next action is to write
    those justifications and a count does not say which.
    """

    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__(f"{len(rows)} baselined rows carry no justification")
        self.rows = rows


def _justification_key(row: dict[str, object]) -> tuple[object, object, object]:
    """Justifications are keyed on where the binding IS, not on what it evaluated to.

    Deliberately NOT `_baseline_key`: that key includes `status` and `evaluated_path`, so a row whose
    status changes -- exactly what a grammar cure does -- would silently lose the reason someone
    wrote for it. The reason belongs to the binding at a location, and the binding is what a person
    read when they wrote it.
    """
    return (row.get("path"), row.get("line"), row.get("target"))


def mint_baseline(
    rows: list[dict[str, object]], *, minted_on: dt.date, expires_on: dt.date,
    justifications: dict[tuple[object, object, object], str] | None = None,
) -> dict[str, object]:
    if minted_on > expires_on:
        raise ValueError("baseline expiry precedes mint date")
    failures = [row for row in rows if row["status"] != "MATCH"]
    if justifications is not None:
        missing = [row for row in failures
                   if not (justifications.get(_justification_key(row)) or "").strip()]
        if missing:
            raise UnjustifiedRows(missing)
        failures = [dict(row, justification=justifications[_justification_key(row)])
                    for row in failures]
    baseline: dict[str, object] = {
        "schema_version": BASELINE_SCHEMA,
        **BASELINE_GOAL_BINDING,
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
    parser.add_argument(
        "--justifications", type=Path,
        help=("JSON array of {path, line, target, justification} objects. When given, the mint "
              "refuses unless EVERY baselined row is covered, and names the ones that are not."),
    )
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    paths = tracked_python_files(root)
    if args.mint_baseline_expiry is not None:
        if args.baseline.exists():
            parser.error("baseline mint is no-overwrite")
        supplied = None
        if args.justifications is not None:
            supplied = {
                (row["path"], row["line"], row["target"]): row.get("justification") or ""
                for row in json.loads(args.justifications.read_text(encoding="utf-8"))
            }
        try:
            payload = mint_baseline(
                scan_files(root, paths), minted_on=args.today,
                expires_on=args.mint_baseline_expiry, justifications=supplied,
            )
        except UnjustifiedRows as unjustified:
            print(json.dumps({
                "result": "BASELINE_MINT_REFUSED",
                "reason": "rows carry no justification",
                "count": len(unjustified.rows),
                "rows": [{k: row.get(k) for k in ("path", "line", "target", "status")}
                         for row in unjustified.rows],
            }, sort_keys=True))
            return 2
        args.baseline.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="",
        )
        print(json.dumps({"result": "BASELINE_MINTED", "rows": payload["maximum_rows"], "self_sha256": payload["self_sha256"]}, sort_keys=True))
        return 0
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    report = build_report(root, paths, baseline, args.today)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
