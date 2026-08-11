# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "cond4_behavior_surface.py"
SPEC = importlib.util.spec_from_file_location("cond4_behavior_surface", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
surface = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(surface)


def _write_module(path: Path, unrelated: str = "UNRELATED = 1", relevant: str = "return value + 1") -> None:
    path.write_text(
        "\n".join(
            [
                "import json",
                unrelated,
                "def helper(value):",
                f"    {relevant}",
                "def exercised(value):",
                "    return helper(value)",
                "def unrelated_function():",
                "    return 'outside'",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )


def test_surface_digest_ignores_outside_edit_and_rejects_inside_edit(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    _write_module(module)
    spec = {"verifier.py": ["exercised", "helper"]}
    baseline = surface.build_surface_manifest(tmp_path, spec)

    _write_module(module, unrelated="UNRELATED = 2")
    assert surface.build_surface_manifest(tmp_path, spec) == baseline

    _write_module(module, unrelated="UNRELATED = 2", relevant="return value + 2")
    changed = surface.build_surface_manifest(tmp_path, spec)
    assert changed["aggregate_sha256"] != baseline["aggregate_sha256"]
    with pytest.raises(surface.SurfaceRefusal, match="COND4_SURFACE_MISMATCH"):
        surface.validate_surface_manifest(tmp_path, baseline)


def test_surface_digest_cannot_omit_a_called_top_level_helper(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    _write_module(module)
    baseline = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    _write_module(module, relevant="return value + 2")

    assert surface.build_surface_manifest(
        tmp_path, {"verifier.py": ["exercised"]}
    )["aggregate_sha256"] != baseline["aggregate_sha256"]


def test_surface_validation_rejects_removed_reachable_helper(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    _write_module(module)
    manifest = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    module.write_text(
        "def exercised(value):\n    return value\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(surface.SurfaceRefusal, match="COND4_SURFACE_MISMATCH"):
        surface.validate_surface_manifest(tmp_path, manifest)


def test_surface_rejects_duplicate_roots(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    _write_module(module)
    with pytest.raises(surface.SurfaceRefusal, match="COND4_SURFACE_SCHEMA_INVALID"):
        surface.build_surface_manifest(
            tmp_path, {"verifier.py": ["exercised", "exercised"]}
        )


@pytest.mark.parametrize(
    "body",
    [
        "def exercised(value):\n    return globals()['helper'](value)\n\ndef helper(value):\n    return value\n",
        "def exercised(value):\n    callback = value\n    return callback()\n",
        "def exercised(value):\n    return make_runner().run(value)\n",
        "def exercised(obj):\n    return obj.run()\n",
    ],
)
def test_surface_refuses_unresolved_calls_without_output(
    tmp_path: Path, body: str
) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(body, encoding="utf-8", newline="\n")
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    with pytest.raises(
        surface.SurfaceRefusal, match="COND4_SURFACE_DYNAMIC_CALL_UNRESOLVED"
    ):
        surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before


def test_surface_records_import_builtin_and_static_attribute_calls(
    tmp_path: Path,
) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        "import json\ndef exercised(value):\n    return json.dumps(sorted(value))\n",
        encoding="utf-8",
        newline="\n",
    )

    manifest = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert manifest["files"][0]["external_calls"] == [
        "json.dumps",
        "sorted",
    ]
    assert manifest["files"][0]["dynamic_call_bindings"] == []


def test_surface_resolves_method_on_result_of_imported_call(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        "import hashlib\ndef exercised(value):\n    return hashlib.sha256(value).hexdigest()\n",
        encoding="utf-8",
        newline="\n",
    )

    manifest = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert manifest["files"][0]["external_calls"] == [
        "hashlib.sha256",
        "hashlib.sha256.hexdigest",
    ]
    assert manifest["files"][0]["dynamic_call_bindings"] == []


def test_surface_resolves_method_on_literal_value(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        "def exercised(values):\n    return ','.join(values)\n",
        encoding="utf-8",
        newline="\n",
    )

    manifest = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert manifest["files"][0]["external_calls"] == ["str.join"]
    assert manifest["files"][0]["dynamic_call_bindings"] == []


def test_surface_digest_binds_referenced_module_assignment(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        "LIMIT = 1\ndef exercised(value):\n    return value + LIMIT\n",
        encoding="utf-8",
        newline="\n",
    )
    before = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    module.write_text(
        "LIMIT = 2\ndef exercised(value):\n    return value + LIMIT\n",
        encoding="utf-8",
        newline="\n",
    )
    after = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert before["aggregate_sha256"] != after["aggregate_sha256"]


def test_surface_digest_binds_referenced_module_import(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        "import hashlib\ndef exercised(value):\n    return hashlib.sha256(value).hexdigest()\n",
        encoding="utf-8",
        newline="\n",
    )
    before = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    module.write_text(
        "import fakehash as hashlib\ndef exercised(value):\n    return hashlib.sha256(value).hexdigest()\n",
        encoding="utf-8",
        newline="\n",
    )
    after = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert before["aggregate_sha256"] != after["aggregate_sha256"]


def test_surface_digest_ignores_unreferenced_module_assignment(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        "UNUSED = 1\ndef exercised(value):\n    return value + 1\n",
        encoding="utf-8",
        newline="\n",
    )
    before = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    module.write_text(
        "UNUSED = 2\ndef exercised(value):\n    return value + 1\n",
        encoding="utf-8",
        newline="\n",
    )
    after = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert before == after


def test_surface_accepts_explicit_builtin_exception_reference(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        "def exercised(value):\n    try:\n        return int(value)\n    except TypeError:\n        return 0\n",
        encoding="utf-8",
        newline="\n",
    )

    manifest = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert manifest["files"][0]["symbols"][0]["name"] == "exercised"


def test_surface_digest_binds_referenced_module_docstring(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        '"""first"""\ndef exercised():\n    return __doc__\n',
        encoding="utf-8",
        newline="\n",
    )
    before = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    module.write_text(
        '"""second"""\ndef exercised():\n    return __doc__\n',
        encoding="utf-8",
        newline="\n",
    )
    after = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert before["aggregate_sha256"] != after["aggregate_sha256"]


def test_surface_requires_exact_explicit_local_receiver_binding(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        "def exercised():\n    created = []\n    created.append('x')\n    return created\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(
        surface.SurfaceRefusal, match="COND4_SURFACE_DYNAMIC_CALL_UNRESOLVED"
    ):
        surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    spec = {
        "verifier.py": {
            "roots": ["exercised"],
            "dynamic_call_bindings": ["created.append"],
        }
    }
    manifest = surface.build_surface_manifest(tmp_path, spec)
    assert manifest["files"][0]["dynamic_call_bindings"] == ["created.append"]
    assert "explicit:created.append" in manifest["files"][0]["external_calls"]

    extra = {
        "verifier.py": {
            "roots": ["exercised"],
            "dynamic_call_bindings": ["created.append", "created.clear"],
        }
    }
    with pytest.raises(
        surface.SurfaceRefusal, match="COND4_SURFACE_UNUSED_DYNAMIC_BINDING"
    ):
        surface.build_surface_manifest(tmp_path, extra)


def test_explicit_binding_cannot_mask_reachable_same_module_helper(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        "class Holder:\n    pass\n\ndef helper():\n    return 1\n\ndef exercised(obj):\n    return obj.helper()\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(
        surface.SurfaceRefusal, match="COND4_SURFACE_DYNAMIC_CALL_UNRESOLVED"
    ):
        surface.build_surface_manifest(
            tmp_path,
            {
                "verifier.py": {
                    "roots": ["exercised"],
                    "dynamic_call_bindings": ["obj.helper"],
                }
            },
        )


@pytest.mark.parametrize(
    "body",
    [
        "def exercised(value):\n    return json.dumps(value)\n\ndef other():\n    import json\n    return json.dumps(1)\n",
        "def helper(value):\n    return value + 1\n\ndef exercised(helper):\n    return helper(1)\n",
        "import json\ndef exercised(json):\n    return json.dumps(1)\n",
        "import json\ndef exercised(value):\n    json = value\n    return json.dumps(1)\n",
    ],
)
def test_surface_refuses_cross_scope_or_shadowed_bindings_without_output(
    tmp_path: Path, body: str
) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(body, encoding="utf-8", newline="\n")
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    with pytest.raises(
        surface.SurfaceRefusal, match="COND4_SURFACE_DYNAMIC_CALL_UNRESOLVED"
    ):
        surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before


def test_surface_accepts_import_scoped_to_the_exercised_root(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        "def exercised(value):\n    import json\n    return json.dumps(value)\n",
        encoding="utf-8",
        newline="\n",
    )

    manifest = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert manifest["files"][0]["external_calls"] == ["json.dumps"]


def test_nested_signature_does_not_shadow_parent_global_helper(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(
        "def helper(value):\n    return value + 1\n\ndef exercised():\n    def nested(helper):\n        return helper\n    return helper(1)\n",
        encoding="utf-8",
        newline="\n",
    )

    manifest = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert [row["name"] for row in manifest["files"][0]["symbols"]] == [
        "exercised",
        "helper",
    ]


@pytest.mark.parametrize(
    "body",
    [
        "def helper(value):\n    return value\n\ndef exercised():\n    callback = lambda helper: helper()\n    return callback\n",
        "def helper(value):\n    return value\n\ndef exercised():\n    def nested(helper):\n        return helper()\n    return nested\n",
        "def helper(value):\n    return value\n\ndef exercised(xs):\n    return [helper(x) for helper in xs]\n",
        "def helper(value):\n    return value\n\ndef exercised(value):\n    match value:\n        case {'helper': helper}:\n            return helper()\n",
        "def helper(value):\n    return value\n\ndef exercised():\n    try:\n        raise Exception()\n    except Exception as helper:\n        return helper()\n",
    ],
)
def test_surface_refuses_anonymous_or_capture_shadowing_without_output(
    tmp_path: Path, body: str
) -> None:
    module = tmp_path / "verifier.py"
    module.write_text(body, encoding="utf-8", newline="\n")
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    with pytest.raises(
        surface.SurfaceRefusal, match="COND4_SURFACE_DYNAMIC_CALL_UNRESOLVED"
    ):
        surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})

    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before


def test_surface_refuses_foreign_path_without_output(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    foreign = tmp_path / "foreign.py"
    foreign.write_text("def exercised():\n    return 1\n", encoding="utf-8", newline="\n")
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}

    with pytest.raises(surface.SurfaceRefusal, match="COND4_SURFACE_PATH_OUTSIDE_ROOT"):
        surface.build_surface_manifest(root, {"../foreign.py": ["exercised"]})

    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before


def test_surface_manifest_is_closed_and_missing_symbol_refuses(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    _write_module(module)
    with pytest.raises(surface.SurfaceRefusal, match="COND4_SURFACE_SYMBOL_MISSING"):
        surface.build_surface_manifest(tmp_path, {"verifier.py": ["missing"]})

    manifest = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})
    manifest["extra"] = True
    with pytest.raises(surface.SurfaceRefusal, match="COND4_SURFACE_SCHEMA_INVALID"):
        surface.validate_surface_manifest(tmp_path, manifest)


def test_execution_evidence_requires_all_axes_timing_and_load_stats() -> None:
    evidence = {
        "schema": "ember-cond4-execution-evidence-v1",
        "subject": {
            "behavior_surface_validator_sha256": hashlib.sha256(
                Path(surface.__file__).read_bytes()
            ).hexdigest(),
            "checkpoint_manifest_sha256": "a" * 64,
            "surface_aggregate_sha256": "b" * 64,
            "checkpoint_bytes_loaded": 123,
            "load_count": 1,
        },
        "axes": [
            {
                "axis": axis,
                "duration_ms": index + 1,
                "rejected": True,
                "finding_codes": [f"finding.{axis}"],
            }
            for index, axis in enumerate(surface.COND4_AXES)
        ],
    }
    surface.validate_execution_evidence(evidence)

    hollow = json.loads(json.dumps(evidence))
    del hollow["axes"][0]["duration_ms"]
    with pytest.raises(surface.SurfaceRefusal, match="COND4_EXECUTION_EVIDENCE_INVALID"):
        surface.validate_execution_evidence(hollow)

    duplicate = json.loads(json.dumps(evidence))
    duplicate["axes"][-1]["axis"] = duplicate["axes"][0]["axis"]
    with pytest.raises(surface.SurfaceRefusal, match="COND4_EXECUTION_EVIDENCE_INVALID"):
        surface.validate_execution_evidence(duplicate)


def test_execution_packet_binds_evidence_to_revalidated_surface(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    _write_module(module)
    validator = tmp_path / surface.VALIDATOR_REL
    validator.parent.mkdir(parents=True)
    validator.write_bytes(Path(surface.__file__).read_bytes())
    manifest = surface.build_surface_manifest(tmp_path, {"verifier.py": ["exercised"]})
    evidence = {
        "schema": "ember-cond4-execution-evidence-v1",
        "subject": {
            "behavior_surface_validator_sha256": hashlib.sha256(
                Path(surface.__file__).read_bytes()
            ).hexdigest(),
            "checkpoint_manifest_sha256": "a" * 64,
            "surface_aggregate_sha256": manifest["aggregate_sha256"],
            "checkpoint_bytes_loaded": 123,
            "load_count": 1,
        },
        "axes": [
            {
                "axis": axis,
                "duration_ms": index + 1,
                "rejected": True,
                "finding_codes": [f"finding.{axis}"],
            }
            for index, axis in enumerate(surface.COND4_AXES)
        ],
    }

    surface.validate_execution_packet(tmp_path, manifest, evidence)

    tampered = json.loads(json.dumps(evidence))
    tampered["subject"]["surface_aggregate_sha256"] = "c" * 64
    with pytest.raises(
        surface.SurfaceRefusal, match="COND4_EXECUTION_SURFACE_MISMATCH"
    ):
        surface.validate_execution_packet(tmp_path, manifest, tampered)

    stale_validator = json.loads(json.dumps(evidence))
    stale_validator["subject"]["behavior_surface_validator_sha256"] = "0" * 64
    with pytest.raises(
        surface.SurfaceRefusal, match="COND4_EXECUTION_VALIDATOR_MISMATCH"
    ):
        surface.validate_execution_packet(tmp_path, manifest, stale_validator)


def test_manifest_aggregate_binds_ordered_symbol_rows(tmp_path: Path) -> None:
    module = tmp_path / "verifier.py"
    _write_module(module)
    manifest = surface.build_surface_manifest(tmp_path, {"verifier.py": ["helper", "exercised"]})
    row = manifest["files"][0]
    identity = {
        "roots": row["roots"],
        "symbols": row["symbols"],
        "module_bindings": row["module_bindings"],
        "external_calls": row["external_calls"],
        "dynamic_call_bindings": row["dynamic_call_bindings"],
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert manifest["files"][0]["sha256"] == hashlib.sha256(canonical).hexdigest()
