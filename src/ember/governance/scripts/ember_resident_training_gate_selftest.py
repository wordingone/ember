#!/usr/bin/env python3
"""Selftest entrypoint for ember_resident_training_gate."""
from __future__ import annotations

import ember_resident_training_gate as gate


def main() -> int:
    return gate.selftest()


if __name__ == "__main__":
    raise SystemExit(main())
