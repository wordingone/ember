# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools" / "ember-restart-3b" / "disk_budget_runner.py"


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


def test_windows_actual_child_and_taskkill_both_receive_create_no_window(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert module._no_window_creationflags() == 0x08000000
    for function, attribute in ((module.run_budgeted, "Popen"), (module.terminate_tree, "run")):
        calls = subprocess_calls(function, attribute)
        assert len(calls) == 1
        keyword = next((item for item in calls[0].keywords if item.arg == "creationflags"), None)
        assert keyword is not None
        assert isinstance(keyword.value, ast.Call)
        assert isinstance(keyword.value.func, ast.Name)
        assert keyword.value.func.id == "_no_window_creationflags"
        if attribute == "Popen":
            keywords = {item.arg: item.value for item in calls[0].keywords}
            for stream in ("stdout", "stderr"):
                assert isinstance(keywords.get(stream), ast.Attribute)
                assert isinstance(keywords[stream].value, ast.Name)
                assert keywords[stream].value.id == "sys"
                assert keywords[stream].attr == stream
    monkeypatch.setattr(module.sys, "platform", "linux")
    assert module._no_window_creationflags() == 0
