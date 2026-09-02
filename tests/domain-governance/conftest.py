"""Pytest fixtures for test_owned_core_widen.py"""
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def config():
    """Load the owned-core-widen config."""
    repo_root = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
    config_path = repo_root / "configs" / "owned-core-widen-config.json"

    assert config_path.exists(), f"Config not found at {config_path}"

    with open(config_path, "r") as f:
        return json.load(f)


@pytest.fixture
def target_params(config: dict):
    """Calculate target params from config."""
    src = config["source_owned_core"]
    widen = config["widen_operator"]

    hidden_dim = src["arch"]["hidden"]
    vocab_size = src["arch"]["vocab"]
    target_rank = widen["target_rank"]

    return target_rank * (hidden_dim + vocab_size)
