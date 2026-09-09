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



@pytest.mark.parametrize("package", ("ember.model", "src.ember.model"))
@pytest.mark.parametrize("suffix,symbol", MODULES.items())
def test_temporary_old_names_preserve_source_path_and_export_objects(package, suffix, symbol, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    monkeypatch.syspath_prepend(str(ROOT / "src"))
    old_suffix = f"cia_{suffix}" if suffix not in {"fp8_linear", "model"} else suffix
    old = importlib.import_module(f"{package}.{old_suffix}")
    versioned = importlib.import_module(f"{package}.ember_v0_{suffix}")
    assert Path(old.__file__).resolve() == (MODEL_DIR / f"{old_suffix}.py").resolve()
    assert getattr(old, symbol) is getattr(versioned, symbol)
    if suffix == "model":
        assert old._swiglu_product is versioned._swiglu_product


def test_temporary_standalone_model_reuses_versioned_classes_and_fp8(monkeypatch):
    loaded = []
    for index in range(2):
        name = f"_ember_v0_compatibility_probe_{index}"
        spec = importlib.util.spec_from_file_location(name, MODEL_DIR / "model.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded.append(module)
    versioned = sys.modules["ember_v0_model"]
    assert Path(versioned.__file__).resolve() == (MODEL_DIR / "ember_v0_model.py").resolve()
    assert loaded[0].UnifiedDecoder is loaded[1].UnifiedDecoder is versioned.UnifiedDecoder
    assert loaded[0]._swiglu_product is versioned._swiglu_product
    assert loaded[0].fp8_linear is loaded[1].fp8_linear is versioned.fp8_linear


def test_temporary_source_fragment_matches_canonical_attention_bytes():
    old = (MODEL_DIR / "model.py").read_text(encoding="utf-8")
    canonical = (MODEL_DIR / "ember_v0_model.py").read_text(encoding="utf-8")
    expected = canonical[canonical.index("class RotaryCoordinates("):canonical.index("class SwiGLUExpert(")]
    observed = old[old.index("class RotaryCoordinates("):old.index("# Runtime callers retain")]
    assert observed == expected
