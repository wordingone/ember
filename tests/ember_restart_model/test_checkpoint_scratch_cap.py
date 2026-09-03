# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import io
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "ember-restart-3b"))

from checkpoint_scratch import ScratchCappedWriter  # noqa: E402


class TestScratchCappedWriter:
    def test_rejects_before_an_over_cap_write_changes_the_destination(self) -> None:
        destination = io.BytesIO()
        writer = ScratchCappedWriter(destination, 4)

        assert writer.write(b"ab") == 2

        try:
            writer.write(b"cde")
        except RuntimeError as error:
            assert "checkpoint transient scratch exceeds 4 bytes" in str(error)
        else:
            raise AssertionError("over-cap write was accepted")

        assert destination.getvalue() == b"ab"

    def test_accepts_a_write_that_ends_exactly_at_the_cap(self) -> None:
        destination = io.BytesIO()
        writer = ScratchCappedWriter(destination, 4)

        assert writer.write(b"abcd") == 4
        assert destination.getvalue() == b"abcd"
