# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_terminal_bench_freeze.py"


def _write_task(root: Path, *, image: str, allow_internet: str = "false") -> None:
    task = root / "bounded-task"
    task.mkdir()
    (task / "task.toml").write_text(
        "\n".join((
            'schema_version = "1.1"',
            "[task]",
            'name = "terminal-bench/bounded-task"',
            "[environment]",
            f'docker_image = "{image}"',
            f"allow_internet = {allow_internet}",
        )),
        encoding="utf-8",
    )


def _invoke(root: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--task-root", str(root), "--task-id", "bounded-task", "--output", str(output)],
        capture_output=True,
        text=True,
    )


def test_freezes_only_digest_pinned_no_internet_task_metadata():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _write_task(root, image="example.invalid/bounded@sha256:" + "a" * 64)
        output = root / "frozen.json"

        completed = _invoke(root, output)

        assert completed.returncode == 0, completed.stderr
        frozen = json.loads(output.read_text(encoding="utf-8"))
        assert frozen["result"] == "PREFLIGHT_ONLY"
        assert frozen["tasks"] == [{"task_id": "bounded-task", "task_toml_sha256": frozen["tasks"][0]["task_toml_sha256"], "docker_image_sha256": "a" * 64}]


def test_rejects_tag_only_or_network_enabled_task_before_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _write_task(root, image="example.invalid/bounded:latest", allow_internet="true")
        output = root / "frozen.json"

        completed = _invoke(root, output)

        assert completed.returncode != 0
        assert not output.exists()
