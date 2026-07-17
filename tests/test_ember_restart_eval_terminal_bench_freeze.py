import pytest
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,hashlib
import importlib.util
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


def test_freeze_canonicalizes_equivalent_task_selection_order():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _write_task(root, image="example.invalid/bounded@sha256:" + "a" * 64)
        second = root / "another-task"; second.mkdir()
        (second / "task.toml").write_text("\n".join((
            'schema_version = "1.1"',
            "[task]",
            'name = "terminal-bench/another-task"',
            "[environment]",
            'docker_image = "example.invalid/another@sha256:' + "b" * 64 + '"',
            "allow_internet = false",
        )), encoding="utf-8")
        output = root / "frozen.json"
        completed = subprocess.run([sys.executable, str(SCRIPT), "--task-root", str(root), "--task-id", "bounded-task", "--task-id", "another-task", "--output", str(output)], capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr
        assert [task["task_id"] for task in json.loads(output.read_text(encoding="utf-8"))["tasks"]] == ["another-task", "bounded-task"]

def test_terminal_task_metadata_is_read_once_for_parse_and_digest(monkeypatch):
    spec = importlib.util.spec_from_file_location("ember_restart_eval_terminal_bench_freeze", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _write_task(root, image="example.invalid/bounded@sha256:" + "a" * 64)
        task_path = root / "bounded-task" / "task.toml"
        expected_sha256 = __import__("hashlib").sha256(task_path.read_bytes()).hexdigest()
        original_open = Path.open
        reads = 0
        def once_open(self, *args, **kwargs):
            nonlocal reads
            if self == task_path:
                reads += 1
                if reads > 1:
                    raise AssertionError("task metadata reopened after parsing")
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", once_open)
        record = module._task(root, "bounded-task")
        assert record["task_toml_sha256"] == expected_sha256
        assert reads == 1
def test_cleans_temporary_payload_when_terminal_metadata_publication_fails(monkeypatch):
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);_write_task(root,image='example.invalid/bounded@sha256:'+'a'*64);output=root/'frozen.json';spec=importlib.util.spec_from_file_location('terminal_freeze_publication',SCRIPT);module=importlib.util.module_from_spec(spec);assert spec.loader is not None;spec.loader.exec_module(module);monkeypatch.setattr(sys,'argv',[str(SCRIPT),'--task-root',str(root),'--task-id','bounded-task','--output',str(output)]);monkeypatch.setattr(module.os,'replace',lambda *_:(_ for _ in ()).throw(OSError('replace denied')))
  with pytest.raises(OSError,match='replace denied'):module.main()
  assert not output.exists() and not list(root.glob('tmp*'))


def test_freezer_emits_source_and_adapter_derived_protocol_identity():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);_write_task(root,image='example.invalid/bounded@sha256:'+'a'*64);output=root/'frozen.json';completed=_invoke(root,output)
        assert completed.returncode==0,completed.stderr
        frozen=json.loads(output.read_text(encoding='utf-8'));custody=json.loads((Path(__file__).resolve().parents[1]/'manifests'/'ember-restart-terminal-bench-custody-v1.json').read_text(encoding='utf-8'))
        assert frozen['schema_version']=='ember-restart-terminal-bench-freeze-v2'
        assert frozen['source_commit']==custody['source_commit'] and frozen['source_tree']==custody['source_tree']
        assert frozen['scoring_adapter_sha256']==hashlib.sha256((Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_terminal_bench.py').read_bytes()).hexdigest()
        assert frozen['protocol_sha256']

def test_freezer_refuses_stale_custody_protocol(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("terminal_freeze_protocol", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    custody = json.loads((SCRIPT.parents[1] / "manifests" / "ember-restart-terminal-bench-custody-v1.json").read_text(encoding="utf-8"))
    custody["protocol_sha256"] = "0" * 64
    path = tmp_path / "custody.json"
    path.write_text(json.dumps(custody), encoding="utf-8")
    monkeypatch.setattr(module, "CUSTODY", path)
    with pytest.raises(ValueError, match="protocol"):
        module._custody_identity()