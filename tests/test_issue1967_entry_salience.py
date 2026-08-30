#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression checks for #1967 Q2/Q5 direct-answer salience."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
START_HERE = ROOT / "docs" / "guides" / "START-HERE.md"
INSTALL_COMMAND = "python tools/ember-restart-3b/python_environment.py install"


def introduction(path: Path) -> str:
    return path.read_text(encoding="utf-8").split("\n## ", 1)[0]


def section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    marker = f"## {heading}\n"
    assert marker in text
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


def test_q2_exact_constraint_is_in_both_direct_introductions() -> None:
    readme_intro = introduction(README)
    start_intro = introduction(START_HERE)

    assert readme_intro.count("one consumer GPU") == 1
    assert start_intro.count("one consumer GPU") == 1
    assert "public evidence" in readme_intro
    assert (
        "Borrowed learned or evaluative signals do not enter the target lineage."
        in readme_intro
    )


def assert_direct_install_route(text: str) -> None:
    normalized = " ".join(text.split())
    command_index = normalized.index(INSTALL_COMMAND)
    assert normalized.index("README") < command_index
    assert normalized.index("docs/guides/START-HERE.md") < command_index
    assert normalized.index("`tools/launchers/Ember.cmd` is the operator entry") < command_index
    assert normalized.index("Python uses") < command_index
    assert normalized.index("manifests/python-environment-v1.json") < command_index
    assert normalized.index("Rust uses") < command_index
    assert normalized.index("runtime/ember-lab/Cargo.toml") < command_index
    assert normalized.index("`ember-cli` uses") < command_index
    assert normalized.index("tools/ember-cli/src/package.json") < command_index


def test_q5_readme_direct_route_precedes_install_command() -> None:
    assert_direct_install_route(section(README, "Inspect or install"))


def test_q5_start_here_direct_route_precedes_install_command() -> None:
    assert_direct_install_route(
        section(START_HERE, "Install the measured Python environment")
    )
