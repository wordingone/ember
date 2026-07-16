# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_spider_source_audit.py"


def test_source_audit_binds_exact_spider_source_and_absent_evaluation_assets():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "spider"
        root.mkdir()
        (root / "evaluation.py").write_text("print('evaluator')\n", encoding="utf-8")
        (root / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "audit@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "audit"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        output = root.parent / "audit.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--spider-root", str(root), "--expected-commit", commit, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "SOURCE_ONLY_NO_FROZEN_SQL_EVALUATION_ASSETS"
        assert payload["source_commit"] == commit
        assert payload["missing_assets"] == ["data/database", "data/dev_gold.sql", "data/tables.json"]


def test_source_audit_refuses_a_source_tree_with_evaluation_gold():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "spider"
        (root / "data").mkdir(parents=True)
        (root / "evaluation.py").write_text("print('evaluator')\n", encoding="utf-8")
        (root / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
        (root / "data" / "dev_gold.sql").write_text("select 1\tdb\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "audit@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "audit"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        output = root.parent / "audit.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--spider-root", str(root), "--expected-commit", commit, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert "evaluation assets are present" in result.stderr
        assert not output.exists()

def test_source_audit_replace_failure_cleans_real_cli_temporary_output(monkeypatch, tmp_path):
    import importlib.util
    import pytest
    spec = importlib.util.spec_from_file_location("spider_cleanup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "spider"
    root.mkdir()
    (root / "evaluation.py").write_text("print('evaluator')\n", encoding="utf-8")
    (root / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "audit@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "audit"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    output = tmp_path / "audit.json"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--spider-root", str(root), "--expected-commit", commit, "--output", str(output)])
    monkeypatch.setattr(module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("replace denied")))
    with pytest.raises(OSError, match="replace denied"):
        module.main()
    assert not output.exists()
    assert not list(tmp_path.glob("audit.json.*.tmp"))