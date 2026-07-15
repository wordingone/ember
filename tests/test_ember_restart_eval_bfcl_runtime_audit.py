# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_bfcl_runtime_audit.py"


def make_source(root: Path, dependency: str = "openai>=1.86.0", live_network: bool = True) -> str:
    evaluator = root / "berkeley-function-call-leaderboard"
    (evaluator / "bfcl_eval" / "eval_checker" / "multi_turn_eval" / "func_source_code").mkdir(parents=True)
    (root / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    (evaluator / "pyproject.toml").write_text("[project]\ndependencies = [\"%s\"]\n" % dependency, encoding="utf-8")
    body = "import requests\nrequests.get('https://example.invalid')\n" if live_network else "pass\n"
    (evaluator / "bfcl_eval" / "eval_checker" / "multi_turn_eval" / "func_source_code" / "web_search.py").write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "audit@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "audit"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def test_bfcl_runtime_audit_holds_unpinned_dependencies_and_live_tool_network():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "bfcl"
        commit = make_source(root)
        output = root.parent / "audit.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--bfcl-root", str(root), "--expected-commit", commit, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "RUNTIME_HELD_UNPINNED_DEPENDENCY_AND_LIVE_TOOL_NETWORK"
        assert payload["target_execution_permitted"] is False
        assert payload["mutable_dependencies"] == ["openai>=1.86.0"]
        assert payload["live_network_tool_source"] is True


def test_bfcl_runtime_audit_keeps_digest_pinned_dependencies_held_when_live_tool_network_remains():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "bfcl"
        commit = make_source(root, dependency="openai @ https://example.invalid/openai.whl#sha256=" + "a" * 64)
        output = root.parent / "audit.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--bfcl-root", str(root), "--expected-commit", commit, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["mutable_dependencies"] == []
        assert payload["live_network_tool_source"] is True
        assert payload["target_execution_permitted"] is False


def test_bfcl_runtime_audit_ignores_quoted_metadata_outside_dependency_list():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "bfcl"
        commit = make_source(root)
        project = root / "berkeley-function-call-leaderboard" / "pyproject.toml"
        project.write_text('[project]\nname = "BFCL"\nrepository = "https://example.invalid"\ndependencies = ["openai>=1.86.0"]\n', encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "metadata"], check=True)
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        output = root.parent / "audit.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--bfcl-root", str(root), "--expected-commit", commit, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(output.read_text(encoding="utf-8"))["mutable_dependencies"] == ["openai>=1.86.0"]