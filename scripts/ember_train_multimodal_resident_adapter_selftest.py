#!/usr/bin/env python3
"""Selftest entrypoint for ember_train_multimodal_resident_adapter."""
from __future__ import annotations

import ember_train_multimodal_resident_adapter as adapter


def main() -> int:
    return adapter.selftest()


if __name__ == "__main__":
    raise SystemExit(main())
