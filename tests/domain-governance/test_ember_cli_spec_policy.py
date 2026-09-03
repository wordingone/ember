# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed tests for the ember-cli spec-node policy."""

from __future__ import annotations

from pathlib import Path

import pytest

# issue2015 exact-local-import:src/ember/governance/scripts/ember_cli_spec_policy.py
import importlib.util as _ember_a59d77302a2b1faf_importlib
import sys as _ember_a59d77302a2b1faf_sys
from pathlib import Path as _ember_a59d77302a2b1faf_Path
_ember_a59d77302a2b1faf_path = _ember_a59d77302a2b1faf_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'ember_cli_spec_policy.py')
if not _ember_a59d77302a2b1faf_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_cli_spec_policy.py')
_ember_a59d77302a2b1faf_aliases = ('_ember_issue2015_a59d77302a2b1faf', 'ember_cli_spec_policy', 'scripts.ember_cli_spec_policy', 'src.ember.governance.scripts.ember_cli_spec_policy')
_ember_a59d77302a2b1faf_existing = []
for _ember_a59d77302a2b1faf_alias in _ember_a59d77302a2b1faf_aliases:
    _ember_a59d77302a2b1faf_candidate = _ember_a59d77302a2b1faf_sys.modules.get(_ember_a59d77302a2b1faf_alias)
    if _ember_a59d77302a2b1faf_candidate is not None and all(_ember_a59d77302a2b1faf_candidate is not item for item in _ember_a59d77302a2b1faf_existing):
        _ember_a59d77302a2b1faf_existing.append(_ember_a59d77302a2b1faf_candidate)
if len(_ember_a59d77302a2b1faf_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_cli_spec_policy.py')
if _ember_a59d77302a2b1faf_existing:
    _ember_a59d77302a2b1faf_module = _ember_a59d77302a2b1faf_existing[0]
    _ember_a59d77302a2b1faf_observed = getattr(_ember_a59d77302a2b1faf_module, '__file__', None)
    if _ember_a59d77302a2b1faf_observed is None or _ember_a59d77302a2b1faf_Path(_ember_a59d77302a2b1faf_observed).resolve() != _ember_a59d77302a2b1faf_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_cli_spec_policy.py')
else:
    _ember_a59d77302a2b1faf_spec = _ember_a59d77302a2b1faf_importlib.spec_from_file_location('_ember_issue2015_a59d77302a2b1faf', _ember_a59d77302a2b1faf_path)
    if _ember_a59d77302a2b1faf_spec is None or _ember_a59d77302a2b1faf_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_cli_spec_policy.py')
    _ember_a59d77302a2b1faf_module = _ember_a59d77302a2b1faf_importlib.module_from_spec(_ember_a59d77302a2b1faf_spec)
    for _ember_a59d77302a2b1faf_alias in _ember_a59d77302a2b1faf_aliases:
        _ember_a59d77302a2b1faf_prior = _ember_a59d77302a2b1faf_sys.modules.get(_ember_a59d77302a2b1faf_alias)
        if _ember_a59d77302a2b1faf_prior is not None and _ember_a59d77302a2b1faf_prior is not _ember_a59d77302a2b1faf_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_cli_spec_policy.py')
        _ember_a59d77302a2b1faf_sys.modules[_ember_a59d77302a2b1faf_alias] = _ember_a59d77302a2b1faf_module
    try:
        _ember_a59d77302a2b1faf_spec.loader.exec_module(_ember_a59d77302a2b1faf_module)
    except BaseException:
        for _ember_a59d77302a2b1faf_alias in _ember_a59d77302a2b1faf_aliases:
            if _ember_a59d77302a2b1faf_sys.modules.get(_ember_a59d77302a2b1faf_alias) is _ember_a59d77302a2b1faf_module:
                _ember_a59d77302a2b1faf_sys.modules.pop(_ember_a59d77302a2b1faf_alias, None)
        raise
for _ember_a59d77302a2b1faf_alias in _ember_a59d77302a2b1faf_aliases:
    _ember_a59d77302a2b1faf_prior = _ember_a59d77302a2b1faf_sys.modules.get(_ember_a59d77302a2b1faf_alias)
    if _ember_a59d77302a2b1faf_prior is not None and _ember_a59d77302a2b1faf_prior is not _ember_a59d77302a2b1faf_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_cli_spec_policy.py')
    _ember_a59d77302a2b1faf_sys.modules[_ember_a59d77302a2b1faf_alias] = _ember_a59d77302a2b1faf_module
SpecPolicyError = getattr(_ember_a59d77302a2b1faf_module, 'SpecPolicyError')
load_spec_nodes = getattr(_ember_a59d77302a2b1faf_module, 'load_spec_nodes')
validate_added_component_coverage = getattr(_ember_a59d77302a2b1faf_module, 'validate_added_component_coverage')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_cli_spec_policy.py


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "src" / "ember" / "infrastructure" / "tools" / "ember-cli" / "specs").mkdir(parents=True)
    (tmp_path / "src" / "ember" / "infrastructure" / "tools" / "ember-cli" / "src" / "services").mkdir(parents=True)
    return tmp_path


def _write_shipped_spec(root: Path, *, consumer: str | None) -> Path:
    lines = ["# Spec — fixture", "", "Status: SHIPPED"]
    if consumer is not None:
        lines.append(f"Consumer: `{consumer}`")
    path = root / "src" / "ember" / "infrastructure" / "tools" / "ember-cli" / "specs" / "fixture.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_shipped_spec_requires_existing_consumer(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _write_shipped_spec(root, consumer=None)

    with pytest.raises(SpecPolicyError, match="consumer-required"):
        load_spec_nodes(root)

    _write_shipped_spec(
        root,
        consumer="src/ember/infrastructure/tools/ember-cli/src/services/missing.ts",
    )
    with pytest.raises(SpecPolicyError, match="consumer-missing"):
        load_spec_nodes(root)


def test_spec_nodes_reject_invalid_utf8_and_unsafe_consumer_paths(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    spec = root / "src" / "ember" / "infrastructure" / "tools" / "ember-cli" / "specs" / "fixture.md"
    spec.write_bytes(b"# Spec\n\nStatus: SHIPPED\nConsumer: `\xff`\n")

    with pytest.raises(SpecPolicyError, match="invalid-utf8"):
        load_spec_nodes(root)

    _write_shipped_spec(root, consumer="../outside.ts")
    with pytest.raises(SpecPolicyError, match="consumer-path-invalid"):
        load_spec_nodes(root)


def test_valid_shipped_spec_returns_normalized_consumer(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    consumer = root / "src" / "ember" / "infrastructure" / "tools" / "ember-cli" / "src" / "services" / "fixture.ts"
    consumer.write_text("export {};\n", encoding="utf-8")
    _write_shipped_spec(
        root,
        consumer="src/ember/infrastructure/tools/ember-cli/src/services/fixture.ts",
    )

    nodes = load_spec_nodes(root)

    assert len(nodes) == 1
    assert nodes[0].status == "SHIPPED"
    assert nodes[0].consumers == (
        "src/ember/infrastructure/tools/ember-cli/src/services/fixture.ts",
    )


def test_runtime_ember_lab_source_is_a_valid_cross_lane_consumer(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    consumer = root / "runtime" / "ember-lab" / "src" / "fixture.rs"
    consumer.parent.mkdir(parents=True)
    consumer.write_text("// governed runtime owner\n", encoding="utf-8")
    _write_shipped_spec(root, consumer="runtime/ember-lab/src/fixture.rs")

    nodes = load_spec_nodes(root)

    assert nodes[0].consumers == ("runtime/ember-lab/src/fixture.rs",)

    foreign = root / "runtime" / "other" / "fixture.rs"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("// not an allowed consumer lane\n", encoding="utf-8")
    _write_shipped_spec(root, consumer="runtime/other/fixture.rs")
    with pytest.raises(SpecPolicyError, match="consumer-path-invalid"):
        load_spec_nodes(root)


def test_added_component_requires_changed_spec_with_exact_consumer(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    component = root / "src" / "ember" / "infrastructure" / "tools" / "ember-cli" / "src" / "services" / "fixture.ts"
    component.write_text("export {};\n", encoding="utf-8")
    _write_shipped_spec(
        root,
        consumer="src/ember/infrastructure/tools/ember-cli/src/services/fixture.ts",
    )

    errors = validate_added_component_coverage(
        root,
        [
            {
                "filename": "src/ember/infrastructure/tools/ember-cli/src/services/fixture.ts",
                "status": "added",
            }
        ],
    )
    assert errors == [
        "spec-floor:added-component-unbound:"
        "src/ember/infrastructure/tools/ember-cli/src/services/fixture.ts"
    ]

    assert validate_added_component_coverage(
        root,
        [
            {
                "filename": "src/ember/infrastructure/tools/ember-cli/src/services/fixture.ts",
                "status": "added",
            },
            {
                "filename": "src/ember/infrastructure/tools/ember-cli/specs/fixture.md",
                "status": "modified",
            },
        ],
    ) == []


def test_changed_file_rows_fail_closed_on_unknown_shape(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    assert validate_added_component_coverage(
        root,
        [{"filename": "src/ember/infrastructure/tools/ember-cli/src/services/fixture.ts"}],
    ) == ["spec-floor:changed-file-row-invalid"]


def test_test_files_do_not_masquerade_as_new_components(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    assert validate_added_component_coverage(
        root,
        [{
            "filename": "src/ember/infrastructure/tools/ember-cli/src/services/fixture.test.ts",
            "status": "added",
        }],
    ) == []


def test_nested_production_component_requires_bound_spec(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    path = "src/ember/infrastructure/tools/ember-cli/src/services/feature/worker.ts"
    (root / "src" / "ember" / "infrastructure" / "tools" / "ember-cli" / "specs" / "open.md").write_text(
        "# Open fixture\n\nStatus: OPEN\n",
        encoding="utf-8",
    )

    assert validate_added_component_coverage(
        root,
        [{"filename": path, "status": "added"}],
    ) == [f"spec-floor:added-component-unbound:{path}"]
