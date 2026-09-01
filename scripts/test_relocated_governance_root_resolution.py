# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v0_config_check_resolves_repository_config() -> None:
    module = _load(
        "v0_config_check_root_test",
        "src/ember/governance/scripts/v0_config_check.py",
    )

    expected = ROOT / "configs" / "v0-pretrain-config.json"
    assert Path(module.NC) == ROOT
    assert Path(module.CONFIG) == expected
    assert expected.is_file()


def test_nck_invariants_resolves_repository_config_and_write_surface() -> None:
    module = _load(
        "nck_invariants_root_test",
        "src/ember/governance/scripts/nck/invariants.py",
    )

    assert Path(module.MANIFEST_PATH) == ROOT / "configs" / "nck-invariants.json"
    assert Path(module.BASELINE_DIR) == ROOT / "configs" / "nck-baseline"
    assert Path(module.WRITE_SURFACE_ROOT) == ROOT


def test_relocated_modules_have_no_legacy_triple_dirname_root_expression() -> None:
    legacy = (
        "os.path.dirname(os.path.dirname(os.path.dirname("
        "os.path.abspath(__file__))))"
    )
    for relative_path in (
        "src/ember/governance/scripts/v0_config_check.py",
        "src/ember/governance/scripts/nck/invariants.py",
    ):
        assert legacy not in (ROOT / relative_path).read_text(encoding="utf-8")
