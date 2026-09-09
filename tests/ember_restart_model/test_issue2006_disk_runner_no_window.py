# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "disk_budget_runner.py"


def load_module():
    spec = importlib.util.spec_from_file_location("issue2006_disk_runner_no_window", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def subprocess_calls(function, attribute):
    tree = ast.parse(Path(function.__code__.co_filename).read_text(encoding="utf-8"))
    target = next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function.__name__)
    return [
        node for node in ast.walk(target)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == attribute
    ]


def test_windows_actual_child_receives_create_no_window_and_kill_path_spawns_nothing(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert module._no_window_creationflags() == 0x08000000
    calls = subprocess_calls(module.run_budgeted, "Popen")
    assert len(calls) == 1
    keyword = next((item for item in calls[0].keywords if item.arg == "creationflags"), None)
    assert keyword is not None
    assert isinstance(keyword.value, ast.Call)
    assert isinstance(keyword.value.func, ast.Name)
    assert keyword.value.func.id == "_no_window_creationflags"
    keywords = {item.arg: item.value for item in calls[0].keywords}
    for stream in ("stdout", "stderr"):
        assert isinstance(keywords.get(stream), ast.Attribute)
        assert isinstance(keywords[stream].value, ast.Name)
        assert keywords[stream].value.id == "sys"
        assert keywords[stream].attr == stream
    assert subprocess_calls(module.terminate_tree, "run") == []
    monkeypatch.setattr(module.sys, "platform", "linux")
    assert module._no_window_creationflags() == 0


def test_windows_termination_uses_retained_job_handle_without_process_creation(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module.sys, "platform", "win32")

    class Process:
        def poll(self):
            return None

        def terminate(self):
            raise AssertionError("direct process termination bypassed retained job")

    class Job:
        def __init__(self):
            self.calls = []

        def terminate(self, exit_code):
            self.calls.append(exit_code)

    job = Job()
    module.terminate_tree(Process(), retained_job=job)
    assert job.calls == [125]


def test_pretermination_receipt_is_immutable_and_self_hashed(tmp_path):
    module = load_module()
    path = tmp_path / "disk-budget-receipt.json.preterminate.json"
    digest = module._write_pretermination_receipt(
        path,
        command=["python", "child.py"],
        started_at_unix=1.0,
        stop_reason="B: operating reserve crossed",
        child_pid=123,
        retained_job=True,
    )
    raw = path.read_bytes()
    payload = json.loads(raw)
    assert payload["result"] == "TERMINATION_REQUIRED_RECEIPT_DURABLE"
    assert payload["termination_attempted"] is False
    assert payload["retained_job_handle"] is True
    unsigned = dict(payload)
    observed_self = unsigned.pop("self_sha256")
    assert observed_self == hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert digest == hashlib.sha256(raw).hexdigest()
    try:
        module._write_pretermination_receipt(
            path,
            command=["python", "child.py"],
            started_at_unix=1.0,
            stop_reason="B: operating reserve crossed",
            child_pid=123,
            retained_job=True,
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("pretermination receipt overwrite was not refused")



def test_cache_bootstrap_preserves_hidden_child_streams_and_exit(tmp_path):
    """Exercise the actual bootstrap, including nested CREATE_NO_WINDOW on Windows."""
    import os
    import subprocess
    import sys
    import pytest

    module = load_module()
    helper = Path.home() / ".codex/headless-python.ps1"
    if sys.platform == "win32" and not helper.is_file():
        pytest.skip("requires the installed no-console Python helper on Windows")
    cache = tmp_path / "tmp"
    cache.mkdir()
    assertion = tmp_path / "assertion.json"
    environment = dict(os.environ, TEMP=str(cache))
    bindings = json.dumps({"TEMP": str(cache)})
    payload = "import sys; print('BOOTSTRAP_OUT', flush=True); print('BOOTSTRAP_ERR', file=sys.stderr, flush=True); raise SystemExit(17)"
    if sys.platform == "win32":
        prefix = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                  "-File", str(helper), "--", "-B"]
    else:
        prefix = [sys.executable, "-B"]
    # Match the existing hidden-child policy: no new console even if a nested
    # call forgets creationflags. This does not supply or repair stdio handles.
    policy = (
        "import subprocess\n"
        "_run = subprocess.run\n"
        "def hidden_run(*args, **kwargs):\n"
        "    kwargs.setdefault('creationflags', getattr(subprocess, 'CREATE_NO_WINDOW', 0))\n"
        "    return _run(*args, **kwargs)\n"
        "subprocess.run = hidden_run\n"
    )
    result = subprocess.run(
        [*prefix, "-c", policy + module._CHILD_ENV_BOOTSTRAP,
         bindings, str(assertion), "sentinel-nonce", *prefix, "-c", payload],
        env=environment, capture_output=True, text=True, timeout=25,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 17
    assert result.stdout.strip() == "BOOTSTRAP_OUT"
    assert result.stderr.strip() == "BOOTSTRAP_ERR"
    assert json.loads(assertion.read_text())["nonce"] == "sentinel-nonce"
