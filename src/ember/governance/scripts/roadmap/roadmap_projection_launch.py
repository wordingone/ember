#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Adapt the roadmap runner to the safe wrapper's file-backed JSON transport."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load(
    Path(__file__).with_name("roadmap_projection_runner.py"),
    "roadmap_projection_runner",
)
original_load = runner.load


def load_with_file_transport(path: Path):
    base = original_load(path)

    class FileSafeGitHub(base.SafeGitHub):
        def api(
            self,
            endpoint: str,
            *,
            method: str = "GET",
            payload=None,
            paginate: bool = False,
        ):
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.wrapper),
                "api",
                endpoint,
            ]
            if method != "GET":
                command.extend(["--method", method])
            if paginate:
                command.extend(["--paginate", "--slurp"])
            with tempfile.TemporaryDirectory(
                prefix="ember-roadmap-gh-"
            ) as temporary:
                if payload is not None:
                    request_payload = payload
                    if (
                        endpoint.endswith("/milestones")
                        and isinstance(payload, dict)
                        and payload.get("due_on") is None
                    ):
                        request_payload = dict(payload)
                        request_payload.pop("due_on", None)
                    request = Path(temporary) / "request.json"
                    request.write_text(
                        json.dumps(request_payload),
                        encoding="utf-8",
                        newline="\n",
                    )
                    command.extend(["--input", str(request)])
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
            if result.returncode != 0:
                raise base.ExecutionError(
                    f"GitHub {method} refused for {endpoint}: "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
            output = result.stdout.strip()
            if not output:
                return None
            try:
                return json.loads(output)
            except json.JSONDecodeError as exc:
                raise base.ExecutionError(
                    f"GitHub response is not JSON for {endpoint}"
                ) from exc

    base.SafeGitHub = FileSafeGitHub
    return base


runner.load = load_with_file_transport


if __name__ == "__main__":
    raise SystemExit(runner.main())
