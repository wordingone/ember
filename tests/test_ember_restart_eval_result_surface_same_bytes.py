# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_result_surface.py"


def test_result_surface_passes_the_same_input_bytes_to_admission_after_path_replacement(monkeypatch, tmp_path):
    specification = importlib.util.spec_from_file_location("result_surface_same_bytes", SCRIPT)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    source = tmp_path / "source.json"
    output = tmp_path / "output.md"
    original = json.dumps({"result": "MEASURED", "capability": "text"}).encode("utf-8")
    source.write_bytes(original)

    def admitted(_manifest, _registry, input_bytes):
        assert input_bytes == original
        source.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "capability": "audio"}), encoding="utf-8")
        return True

    monkeypatch.setattr(module, "_admitted", admitted)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(source), "--admission-manifest", str(tmp_path / "manifest"), "--trusted-verifier-registry", str(tmp_path / "registry"), "--output", str(output)])
    module.main()
    rendered = output.read_text(encoding="utf-8")
    assert "Status: MEASURED CAPABILITY" in rendered
    assert "Capability: text" in rendered
