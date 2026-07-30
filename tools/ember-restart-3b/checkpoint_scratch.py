# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Dependency-light transient checkpoint scratch enforcement."""

from __future__ import annotations

from typing import Any


class ScratchCappedWriter:
    """Reject a temporary shard before a write would cross its byte cap."""

    def __init__(self, handle: Any, max_bytes: int) -> None:
        self._handle = handle
        self._max_bytes = max_bytes

    def write(self, payload: bytes | bytearray | memoryview) -> int:
        projected_end = self._handle.tell() + len(payload)
        if projected_end > self._max_bytes:
            raise RuntimeError(
                f"checkpoint transient scratch exceeds {self._max_bytes} bytes"
            )
        return self._handle.write(payload)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)
