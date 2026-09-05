#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed media-type census for the training-infrastructure connector."""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

from domain_manifest import _connector_media_type  # noqa: E402


def test_training_infrastructure_observed_media_types_are_closed() -> None:
    expected = {
        ".gitignore": "text/plain; charset=utf-8",
        "LICENSE": "text/plain; charset=utf-8",
        "Makefile": "text/plain; charset=utf-8",
        "LICENSE.code": "text/plain; charset=utf-8",
        "assets/diagram.odg": "application/vnd.oasis.opendocument.graphics",
        "assets/icon.ico": "image/x-icon",
        "assets/photo.jpg": "image/jpeg",
        "assets/screenshot.png": "image/png",
        "audio/1995-1837-0010.flac": "audio/flac",
        "build/kernel.out": "application/octet-stream",
        "examples/hello_gpu_ref": "application/octet-stream",
        "include/kernel.h": "text/x-c++hdr; charset=utf-8",
        "scripts/build.bat": "text/x-msdos-batch; charset=utf-8",
        "scripts/build.sh": "application/x-sh; charset=utf-8",
        "scripts/helper.py": "text/x-python; charset=utf-8",
        "src/kernel.cpp": "text/x-c++src; charset=utf-8",
        "src/kernel.cu": "text/x-cuda; charset=utf-8",
        "state/editor.swp": "application/x-vim-swap",
        "style/site.css": "text/css; charset=utf-8",
        "docs/guide.rst": "text/x-rst; charset=utf-8",
        "workflow/sphinx.yml": "application/yaml; charset=utf-8",
    }
    assert {
        path: _connector_media_type(PurePosixPath(path))
        for path in expected
    } == expected


@pytest.mark.parametrize(
    "path",
    ["payload.bin", "payload.exe", "payload.dll", "payload.json.gz.exe"],
)
def test_deceptive_or_unapproved_executable_suffixes_remain_refused(path: str) -> None:
    with pytest.raises(ValueError, match="unsupported media type"):
        _connector_media_type(PurePosixPath(path))
