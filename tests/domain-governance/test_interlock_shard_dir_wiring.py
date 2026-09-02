# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Test for shard_dir wiring to launch-gate interlock (refs #793)."""

import os
import sys
import pytest
from unittest import mock
from pathlib import Path

# Add scripts to path for imports
test_dir = Path(__file__).parent
scripts_dir = test_dir.parent / "scripts"
sys.path.insert(0, str(scripts_dir))


def test_check_launch_interlock_forwards_shard_dir():
    """Verify that _check_launch_interlock forwards shard_dir to the launch gate."""
    from timeshare_pretrain import _check_launch_interlock

    # Mock the v0_pretrain_launch_gate.gate function to capture kwargs
    gate_kwargs = {}

    def mock_gate(date, **kwargs):
        gate_kwargs.update(kwargs)
        # Return all-green rows to pass the gate
        return [
            ("corpus", "GREEN", "ok"),
            ("tokenizer", "GREEN", "ok"),
            ("shards", "GREEN", "ok"),
            ("config", "GREEN", "ok"),
            ("governor", "GREEN", "ok"),
            ("world", "GREEN", "ok"),
            ("budget", "GREEN", "ok"),
            ("prereg", "GREEN", "ok"),
        ]

    # Set up environment: authorize launch
    with mock.patch.dict(os.environ, {"EMBER_GATE_AUTHORIZED": "1"}):
        # Patch the imported gate module
        with mock.patch("v0_pretrain_launch_gate.gate", side_effect=mock_gate):
            # Also patch registry_gate subprocess call
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0

                # TEST 1: Call with shard_dir and verify it's forwarded
                gate_kwargs.clear()
                _check_launch_interlock(live=True, shard_dir="/tmp/test_shards")

                assert "shard_dir_override" in gate_kwargs, \
                    "shard_dir_override not found in gate kwargs"
                assert gate_kwargs["shard_dir_override"] == "/tmp/test_shards", \
                    f"Expected shard_dir_override='/tmp/test_shards', got {gate_kwargs.get('shard_dir_override')}"

                # TEST 2: Call without shard_dir and verify default (None)
                gate_kwargs.clear()
                _check_launch_interlock(live=True, shard_dir=None)

                assert "shard_dir_override" in gate_kwargs, \
                    "shard_dir_override not found in gate kwargs"
                assert gate_kwargs["shard_dir_override"] is None, \
                    f"Expected shard_dir_override=None (default), got {gate_kwargs.get('shard_dir_override')}"

                # TEST 3: Call without shard_dir kwarg at all (implicit default)
                gate_kwargs.clear()
                _check_launch_interlock(live=True)

                assert "shard_dir_override" in gate_kwargs, \
                    "shard_dir_override not found in gate kwargs"
                assert gate_kwargs["shard_dir_override"] is None, \
                    f"Expected shard_dir_override=None (implicit default), got {gate_kwargs.get('shard_dir_override')}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
