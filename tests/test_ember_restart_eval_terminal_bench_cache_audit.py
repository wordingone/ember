# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_terminal_bench_cache_audit.py"
_SPEC = importlib.util.spec_from_file_location("terminal_cache_audit", SCRIPT)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)


def _write_task(root: Path, task_id: str, image: str, allow_internet: bool) -> None:
    task = root / task_id
    task.mkdir()
    (task / "task.toml").write_text(
        "\n".join(
            (
                'schema_version = "1.1"',
                "[task]",
                f'name = "terminal-bench/{task_id}"',
                "[environment]",
                f'docker_image = "{image}"',
                f"allow_internet = {str(allow_internet).lower()}",
            )
        ),
        encoding="utf-8",
    )


def test_cache_audit_counts_digest_and_network_eligibility():
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        _write_task(root, "tagged-online", "example.invalid/task:latest", True)
        _write_task(root, "pinned-offline", "example.invalid/task@sha256:" + "a" * 64, False)
        value = _MODULE.audit_task_root(root)
        assert value["task_count"] == 2
        assert value["digest_pinned_image_task_count"] == 1
        assert value["network_disabled_task_count"] == 1
        assert value["eligible_task_count"] == 1
        assert value["target_execution_permitted"] is False
        assert len(value["task_manifest_sha256"]) == 64


def test_cache_audit_accepts_harbor_task_ids_with_dots(tmp_path):
    _write_task(tmp_path, "install-windows-3.11", "example.invalid/task:latest", True)
    value = _MODULE.audit_task_root(tmp_path)
    assert value["task_count"] == 1


def test_cache_audit_rejects_task_identity_or_metadata_drift(tmp_path):
    _write_task(tmp_path, "wrong-name", "example.invalid/task:latest", True)
    (tmp_path / "wrong-name" / "task.toml").write_text(
        (tmp_path / "wrong-name" / "task.toml").read_text(encoding="utf-8").replace("terminal-bench/wrong-name", "terminal-bench/other"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="identity"):
        _MODULE.audit_task_root(tmp_path)


def test_cache_audit_publication_is_fresh_and_atomic(tmp_path):
    output = tmp_path / "audit.json"
    payload = {"result": "PREFLIGHT_ONLY", "task_count": 0}
    _MODULE.atomic_write(output, payload)
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    with pytest.raises(ValueError, match="must not pre-exist"):
        _MODULE.atomic_write(output, payload)