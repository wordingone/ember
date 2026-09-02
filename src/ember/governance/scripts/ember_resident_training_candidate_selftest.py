#!/usr/bin/env python3
"""Selftest entrypoint for ember_resident_training_candidate."""
from __future__ import annotations

import ember_resident_training_candidate as candidate


def main() -> int:
    return candidate.selftest()


if __name__ == "__main__":
    raise SystemExit(main())
