#!/usr/bin/env python3
"""Regression tests for the standalone C7 deletion-test fixture."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("c7_deletion_test.py")
SPEC = importlib.util.spec_from_file_location("c7_deletion_test_fixture_subject", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
SUBJECT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SUBJECT
SPEC.loader.exec_module(SUBJECT)


class C7DeletionFixtureTests(unittest.TestCase):
    def test_every_heldout_state_has_a_distinct_training_counterpart(self) -> None:
        corpus = SUBJECT._make_toy_corpus_loadbearing()
        training_signatures = {
            (task.task_slice, task.state_val, task.correct_action)
            for task in corpus.train_tasks
        }

        missing = [
            task.task_id
            for task in corpus.heldout_tasks
            if (task.task_slice, task.state_val, task.correct_action)
            not in training_signatures
        ]

        self.assertEqual(
            [],
            missing,
            "the load-bearing fixture cannot evaluate states the active arm never trains on",
        )

    def test_default_standalone_fixture_proves_the_deletion_gap(self) -> None:
        self.assertTrue(SUBJECT._run_selftest(verbose=False))


if __name__ == "__main__":
    unittest.main()
