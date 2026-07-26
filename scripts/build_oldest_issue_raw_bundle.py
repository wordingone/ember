#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build a deterministic JSON bundle of raw task-015 API source bytes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.oldest_issue_disposition import PacketError
from scripts.verify_oldest_issue_disposition_packet import write_raw_bundle


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        digest = write_raw_bundle(
            args.raw_root.resolve(strict=True),
            args.output,
        )
    except (OSError, PacketError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "bundle_sha256": digest,
                "status": "RAW_SOURCE_BUNDLE_VALID",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
