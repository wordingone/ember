# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Offline argparser round-trip tests for the wave_manifest.py CLI (issue #1439).

Bar-1 permanent coverage for the wave-2 vein CLI's argument surface: every
accepted arg set must survive parse -> serialize -> re-parse unchanged, the
serialized form must be a fixed point, and everything the parser is supposed
to reject must exit with argparse's usage error (SystemExit code 2) without
touching any other machinery. No network, no subprocess, no filesystem
writes -- pure argparse.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
import unittest
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wave_manifest as wm  # noqa: E402

# Every destination build_parser() produces. serialize_args() below is only a
# faithful inverse while this set is exhaustive; the guard test locks the two
# together so a new CLI option cannot silently escape round-trip coverage.
PARSER_DESTS = {"domain", "include_bulk", "bulk_budget_bytes", "execute"}


def serialize_args(args: argparse.Namespace) -> List[str]:
    """Reconstruct a canonical argv from a parsed namespace."""
    argv: List[str] = []
    if args.domain is not None:
        argv += ["--domain", args.domain]
    if args.include_bulk:
        argv.append("--include-bulk")
    if args.bulk_budget_bytes is not None:
        argv += ["--bulk-budget-bytes", str(args.bulk_budget_bytes)]
    if args.execute:
        argv.append("--execute")
    return argv


def parse(argv: List[str]) -> argparse.Namespace:
    return wm.build_parser().parse_args(argv)


ACCEPTED_ARG_SETS: List[List[str]] = [
    [],  # all defaults
    ["--include-bulk"],
    ["--execute"],
    ["--include-bulk", "--execute"],
    ["--bulk-budget-bytes", "1"],  # minimal positive budget
    ["--bulk-budget-bytes", "0"],  # parser accepts; main() blocks it (falsy)
    ["--bulk-budget-bytes", "-5"],  # parser accepts; range is enforced downstream
    ["--bulk-budget-bytes", str(10**18)],  # arbitrary-precision int survives
    ["--domain", "baseline", "--include-bulk", "--execute", "--bulk-budget-bytes", "1000000"],
    # options in non-canonical order must canonicalize to the same namespace
    ["--execute", "--bulk-budget-bytes", "7", "--domain", "G", "--include-bulk"],
] + [["--domain", d] for d in sorted(wm.CHARTER_DOMAINS)]  # every legal choice, "baseline" included


class RoundTripTests(unittest.TestCase):
    def test_serializer_covers_every_parser_destination(self):
        self.assertEqual(set(vars(parse([]))), PARSER_DESTS,
                         "build_parser() grew/lost an option; update serialize_args + PARSER_DESTS")

    def test_parse_serialize_reparse_is_identity(self):
        for argv in ACCEPTED_ARG_SETS:
            with self.subTest(argv=argv):
                first = parse(argv)
                canonical = serialize_args(first)
                second = parse(canonical)
                self.assertEqual(vars(first), vars(second))

    def test_serialized_form_is_a_fixed_point(self):
        for argv in ACCEPTED_ARG_SETS:
            with self.subTest(argv=argv):
                canonical = serialize_args(parse(argv))
                self.assertEqual(serialize_args(parse(canonical)), canonical)

    def test_fresh_parsers_agree(self):
        # build_parser() must hold no shared mutable state across builds
        for argv in ACCEPTED_ARG_SETS:
            with self.subTest(argv=argv):
                self.assertEqual(
                    vars(wm.build_parser().parse_args(argv)),
                    vars(wm.build_parser().parse_args(argv)),
                )

    def test_defaults_serialize_to_empty_argv(self):
        self.assertEqual(serialize_args(parse([])), [])


class RejectionTests(unittest.TestCase):
    REJECTED_ARG_SETS: List[List[str]] = [
        ["--domain", "Z"],  # not a charter domain
        ["--domain", "a"],  # choices are case-sensitive
        ["--domain", "Baseline"],  # exact-token choice only
        ["--domain"],  # missing value
        ["--bulk-budget-bytes", "abc"],  # not an int
        ["--bulk-budget-bytes", "1.5"],  # float rejected by type=int
        ["--bulk-budget-bytes", ""],  # empty string not an int
        ["--bulk-budget-bytes"],  # missing value
        ["--no-such-flag"],
        ["stray-positional"],  # parser defines no positionals
    ]

    def test_rejected_arg_sets_exit_with_usage_error(self):
        for argv in self.REJECTED_ARG_SETS:
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        parse(argv)
                self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
