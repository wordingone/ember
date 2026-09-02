# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Host-stable fixtures for the restart-model tests."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _stable_runner_preflight_host_capacity(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """Keep runner unit tests deterministic without changing governed test bytes."""

    if Path(str(request.node.path)).name != "test_runner_preflight.py":
        return

    real_temporary_directory = tempfile.TemporaryDirectory
    real_run = subprocess.run

    def temporary_directory(*args: Any, **kwargs: Any) -> tempfile.TemporaryDirectory:
        if kwargs.get("dir") == "C:/tmp":
            kwargs = dict(kwargs)
            kwargs.pop("dir")
        return real_temporary_directory(*args, **kwargs)

    def governed_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        command = args[0] if args else kwargs.get("args")
        if isinstance(command, (list, tuple)):
            rewritten = list(command)
            for index, token in enumerate(rewritten):
                if Path(str(token)).name != "disk_budget_runner.py":
                    continue
                runner = Path(str(token)).resolve()
                shim = tmp_path / "disk-budget-runner-capacity-fixture.py"
                shim.write_text(
                    "import importlib.util, pathlib, sys\n"
                    f"runner_path = pathlib.Path({str(runner)!r})\n"
                    "spec = importlib.util.spec_from_file_location("
                    "'_tested_disk_budget_runner', runner_path)\n"
                    "module = importlib.util.module_from_spec(spec)\n"
                    "spec.loader.exec_module(module)\n"
                    "module.current_free_gib = lambda: {'C': 1000.0, 'B': 1000.0}\n"
                    "sys.argv = [str(runner_path), *sys.argv[1:]]\n"
                    "raise SystemExit(module.main())\n",
                    encoding="utf-8",
                )
                rewritten[index] = str(shim)
                break
            if args:
                args = (rewritten, *args[1:])
            else:
                kwargs = dict(kwargs)
                kwargs["args"] = rewritten
        return real_run(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryDirectory", temporary_directory)
    monkeypatch.setattr(subprocess, "run", governed_run)
