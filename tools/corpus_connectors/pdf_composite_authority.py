#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Seal one immutable composite PDF authority from a closed JSON spec."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

from tools.corpus_connectors.pdf_tree_to_utf8 import (
    PdfTreeExtractionRefusal,
    _write_exclusive,
    build_composite_connector_authority,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        raw = build_composite_connector_authority(spec_raw=args.spec.read_bytes())
        _write_exclusive(args.output, raw + b"\n")
    except (OSError, PdfTreeExtractionRefusal) as error:
        parser.error(str(error))
    print(json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
