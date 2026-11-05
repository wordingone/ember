#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1945 H38 decode-prefetch refuter: did the two-ahead image decode actually hit, read off the hour's own rows.

WHY THIS EXISTS. H34 (receipt root cia-hour-a1-five-attn-stage-d4-20261007T102142Z) ran a whole governed hour with
EMBER_DECODE_TWO_AHEAD=1 accepted and recorded, and every one of its 68,269 rows read
`image_patches_source: "decoded-in-this-step"`. The flag named a feature; nothing read the outcome field the feature
writes. The mechanism: HourPacks fills a chained hour's image document at the GLOBAL position image_start + index,
while the step prefetched at the LOCAL index, so the prefetch key never matched, load_patches missed, and the step
thread decoded eight images synchronously inside every measured wall. The genesis hours of Sept 24-28 (image_start 0,
local == global) read `decoded-in-previous-step-wall` on 57,973 of 57,974 rows.

WHAT THIS READS. The first N measured rows of a run's rows.jsonl (default 1,200; `phase == "measured"`, the warm row
skipped), streamed and stopped at N so a 200 MB file is not read whole. For each row the value of
`image_patches_source` is counted into exactly one of three buckets:

  decoded-in-previous-step-wall   the prefetch HIT (the decode ran inside the previous update's wall)
  decoded-in-this-step            the prefetch MISSED (decoded synchronously on the step thread)
  residual                        neither value, or the field absent (a text-only pack carries no field)

The residual is a first-class number in the output, beside the buckets, never folded into either.

THE VERDICT. SUPPORTED when at least N - 2 of the N rows read `decoded-in-previous-step-wall`; otherwise REFUTED
(exit 3). The allowance of two is structural, not a tolerance: updates 1 and 2 are never prefetched, because the
first prefetch is issued inside update 1 for update 3 (two-ahead) and nothing ran before update 1. Fewer than N
measured rows in the file is a REFUSAL (exit 2), not a verdict on a smaller population.

PLACEMENT. This consumer reads the producer's rows and imports nothing from it, so it binds EMBER-02A beside
issue1945_hour_acceptance_predicate.py; the producer (cia_hour.py, cia_step_runner.py) binds EMBER-02B under the
path-prefix partition and carries the cure and its own in-hour assertion (clause decode-prefetch-actually-hit).

Before-state, run on H34's rows (read-only), is pasted in the pull request that lands this file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HIT = 'decoded-in-previous-step-wall'
MISS = 'decoded-in-this-step'
FIELD = 'image_patches_source'
DEFAULT_ROWS = 1200
STRUCTURAL_MISSES = 2  # updates 1 and 2: no earlier update existed to prefetch them
EXIT_SUPPORTED, EXIT_INSUFFICIENT, EXIT_REFUTED = 0, 2, 3
SCHEMA = 'ember-1945-h38-decode-prefetch-refuter-v1'
FIRST_MISSES_KEPT = 8


def census(rows_path: Path, count: int) -> dict:
    """Stream the first `count` measured rows and count image_patches_source into hit / miss / residual."""
    if type(count) is not int or count <= STRUCTURAL_MISSES:
        raise ValueError('row count must be an integer above the two structural misses')
    hit = miss = residual = measured = skipped = 0
    first_misses: list = []
    first_residual: list = []
    with Path(rows_path).open('r', encoding='utf-8') as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if type(row) is not dict:
                raise ValueError('rows.jsonl line is not an object')
            if row.get('phase') != 'measured':
                skipped += 1
                continue
            measured += 1
            value = row.get(FIELD)
            if value == HIT:
                hit += 1
            elif value == MISS:
                miss += 1
                if len(first_misses) < FIRST_MISSES_KEPT:
                    first_misses.append(row.get('index'))
            else:
                residual += 1
                if len(first_residual) < FIRST_MISSES_KEPT:
                    first_residual.append(row.get('index'))
            if measured >= count:
                break
    return dict(schema=SCHEMA, rows=str(rows_path), requested=count, measured=measured, skipped_non_measured=skipped,
                hit=hit, miss=miss, residual=residual, first_miss_indices=first_misses,
                first_residual_indices=first_residual, threshold=count - STRUCTURAL_MISSES)


def verdict(counts: dict) -> tuple[str, int]:
    if counts['measured'] < counts['requested']:
        return 'REFUSED insufficient-measured-rows', EXIT_INSUFFICIENT
    if counts['hit'] >= counts['threshold']:
        return 'SUPPORTED', EXIT_SUPPORTED
    return 'REFUTED', EXIT_REFUTED


def report(counts: dict, status: str) -> str:
    return '\n'.join([
        'rows %s' % counts['rows'],
        'measured rows read %d (requested %d; %d non-measured rows skipped)'
        % (counts['measured'], counts['requested'], counts['skipped_non_measured']),
        '%s %d' % (HIT, counts['hit']),
        '%s %d  first indices %s' % (MISS, counts['miss'], counts['first_miss_indices']),
        'residual %d (rows with neither value)  first indices %s' % (counts['residual'], counts['first_residual_indices']),
        'threshold >= %d of %d %s' % (counts['threshold'], counts['requested'], HIT),
        status,
    ])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rows', type=Path, required=True, help="a run's rows.jsonl (read only)")
    parser.add_argument('--rows-count', type=int, default=DEFAULT_ROWS,
                        help='measured rows to read from the front of the file (default %d)' % DEFAULT_ROWS)
    parser.add_argument('--json', type=Path, help='optional path to write the counts and verdict as JSON')
    args = parser.parse_args(argv)
    counts = census(args.rows, args.rows_count)
    status, code = verdict(counts)
    counts['status'] = status
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(counts, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    print(report(counts, status))
    return code


if __name__ == '__main__':
    sys.exit(main())
