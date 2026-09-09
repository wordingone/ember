# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Versioned module imports preserve package and standalone caller contracts."""
import importlib
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "src" / "ember" / "model"
MODULES = {
    "contract": "validate_cia_architecture",
    "decoder": "CIADecoder",
    "inventory": "equation_inventory",
    "residency": "ExpertCache",
    "routing": "select_global",
    "fp8_linear": "linear",
    "model": "UnifiedDecoder",
}


@pytest.mark.parametrize("package", ("ember.model", "src.ember.model"))
@pytest.mark.parametrize("suffix,symbol", MODULES.items())
def test_versioned_module_imports_resolve_this_checkout(package, suffix, symbol, monkeypatch):
    expected = MODEL_DIR / f"ember_v0_{suffix}.py"
    assert expected.is_file(), f"versioned module missing: {expected.name}"
    monkeypatch.syspath_prepend(str(ROOT))
    monkeypatch.syspath_prepend(str(ROOT / "src"))
    module = importlib.import_module(f"{package}.ember_v0_{suffix}")
    assert Path(module.__file__).resolve() == expected.resolve()
    assert callable(getattr(module, symbol))


def test_standalone_model_reuses_its_versioned_fp8_sibling(monkeypatch):
    path = MODEL_DIR / "ember_v0_model.py"
    assert path.is_file(), "versioned standalone model missing"
    loaded = []
    for index in range(2):
        name = f"_ember_v0_filename_probe_{index}"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded.append(module)
    assert Path(loaded[0].fp8_linear.__file__).resolve() == (MODEL_DIR / "ember_v0_fp8_linear.py").resolve()
    assert loaded[0].fp8_linear is loaded[1].fp8_linear
    assert callable(loaded[0].UnifiedDecoder)


def test_seven_old_filenames_are_retired():
    old = [f"cia_{suffix}.py" for suffix in ("contract", "decoder", "inventory", "residency", "routing")]
    old.extend(("fp8_linear.py", "model.py"))
    assert not [name for name in old if (MODEL_DIR / name).exists()]


def test_helper_package_exports_the_versioned_decoder(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    package = importlib.import_module("src.ember.infrastructure.tools.ember-restart-3b")
    model = importlib.import_module("src.ember.model.ember_v0_model")
    assert package.UnifiedDecoder is model.UnifiedDecoder
    assert package.RestartDecoderConfig is model.RestartDecoderConfig


def test_native_source_identity_hashes_the_versioned_model(monkeypatch):
    import hashlib
    monkeypatch.syspath_prepend(str(ROOT))
    monkeypatch.syspath_prepend(str(ROOT / "src/ember/infrastructure/tools/ember-restart-3b"))
    screen = importlib.import_module("native_compute_screen")
    observed = screen._source_closure(ROOT)
    assert set(observed) == set(screen._SOURCE_NAMES)
    assert observed["model.py"] == hashlib.sha256((MODEL_DIR / "ember_v0_model.py").read_bytes()).hexdigest()
