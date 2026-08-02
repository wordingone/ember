# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Schema validation for the three loop/graph substrate document types.

Uses the `jsonschema` package when it is importable. When it is not, falls
back to a hand-rolled structural check (required fields + type + enum) so
this package never hard-depends on a non-stdlib library -- the substrate's
own constraint is "stdlib only, no new deps," and jsonschema is a bonus,
not a requirement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._atomic import read_json

try:
    import jsonschema  # type: ignore

    _HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover - exercised only where jsonschema is absent
    _HAVE_JSONSCHEMA = False


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas" / "loop-graph"

DOC_TYPES: dict[str, str] = {
    "authority": "authority-graph-v2.schema.json",
    "execution": "execution-graph-v1.schema.json",
    "receipt": "provenance-receipt-v1.schema.json",
}


class ValidationError(ValueError):
    def __init__(self, doc_type: str, errors: list[str]):
        self.doc_type = doc_type
        self.errors = errors
        super().__init__(f"{doc_type}: {'; '.join(errors)}")


def schema_path(doc_type: str) -> Path:
    if doc_type not in DOC_TYPES:
        raise KeyError(f"unknown loop-graph document type: {doc_type!r} (expected one of {sorted(DOC_TYPES)})")
    return SCHEMA_DIR / DOC_TYPES[doc_type]


def load_schema(doc_type: str) -> dict[str, Any]:
    return read_json(schema_path(doc_type))


def validate(document: Any, doc_type: str) -> list[str]:
    """Validate `document` against the named schema. Returns a list of error
    strings; empty list means valid."""
    schema = load_schema(doc_type)
    if _HAVE_JSONSCHEMA:
        validator = jsonschema.Draft202012Validator(schema)
        return [
            f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
            for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
        ]
    return _fallback_validate(document, schema)


def validate_or_raise(document: Any, doc_type: str) -> None:
    errors = validate(document, doc_type)
    if errors:
        raise ValidationError(doc_type, errors)


def validate_file(path: Path, doc_type: str) -> list[str]:
    return validate(read_json(path), doc_type)


def validate_jsonl_file(path: Path, doc_type: str) -> dict[int, list[str]]:
    """Validate every line of a JSONL file. Returns {line_number: errors} for
    lines that failed; empty dict means every line is valid."""
    from ._atomic import read_jsonl

    failures: dict[int, list[str]] = {}
    for index, row in enumerate(read_jsonl(path), start=1):
        errors = validate(row, doc_type)
        if errors:
            failures[index] = errors
    return failures


# --- fallback hand-rolled validator (no jsonschema installed) ---------------

_PY_TYPE_BY_JSON_TYPE = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


def _fallback_validate(document: Any, schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _check_node(document, schema, "<root>", errors, schema.get("$defs", {}))
    return errors


def _resolve(node_schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = node_schema.get("$ref")
    if ref and ref.startswith("#/$defs/"):
        return defs.get(ref.split("/")[-1], {})
    return node_schema


def _check_node(value: Any, node_schema: dict[str, Any], path: str, errors: list[str], defs: dict[str, Any]) -> None:
    node_schema = _resolve(node_schema, defs)

    if "const" in node_schema and value != node_schema["const"]:
        errors.append(f"{path}: expected const {node_schema['const']!r}, got {value!r}")
        return

    if "enum" in node_schema and value not in node_schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {node_schema['enum']}")
        return

    expected_type = node_schema.get("type")
    if expected_type:
        py_type = _PY_TYPE_BY_JSON_TYPE.get(expected_type)
        if py_type is not None and not isinstance(value, py_type):
            # bool is a subclass of int in Python; JSON schema treats them as distinct.
            if expected_type == "integer" and isinstance(value, bool):
                errors.append(f"{path}: expected integer, got bool")
            elif not (expected_type == "number" and isinstance(value, bool) is False and isinstance(value, py_type)):
                errors.append(f"{path}: expected {expected_type}, got {type(value).__name__}")
                return

    if expected_type == "object" or (expected_type is None and isinstance(value, dict)):
        if not isinstance(value, dict):
            return
        required = node_schema.get("required", [])
        for field in required:
            if field not in value:
                errors.append(f"{path}: missing required field {field!r}")
        properties = node_schema.get("properties", {})
        additional = node_schema.get("additionalProperties", True)
        for key, sub_value in value.items():
            if key in properties:
                _check_node(sub_value, properties[key], f"{path}/{key}", errors, defs)
            elif additional is False:
                errors.append(f"{path}: unexpected additional property {key!r}")
            elif isinstance(additional, dict):
                _check_node(sub_value, additional, f"{path}/{key}", errors, defs)

    elif expected_type == "array" or (expected_type is None and isinstance(value, list)):
        if not isinstance(value, list):
            return
        min_items = node_schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: expected at least {min_items} items, got {len(value)}")
        item_schema = node_schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _check_node(item, item_schema, f"{path}[{index}]", errors, defs)

    elif expected_type == "string" and isinstance(value, str):
        min_length = node_schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            errors.append(f"{path}: string shorter than minLength {min_length}")
        pattern = node_schema.get("pattern")
        if pattern:
            import re

            if not re.match(pattern, value):
                errors.append(f"{path}: {value!r} does not match pattern {pattern!r}")

    elif expected_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
        minimum = node_schema.get("minimum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: {value} below minimum {minimum}")
