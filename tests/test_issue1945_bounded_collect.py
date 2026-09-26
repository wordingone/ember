# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""With the collector disabled, the 64-step bound must reclaim a cycle that was still referenced at the previous pass.
A generation-0-only bound promotes it and never examines it again; two #1945 hours died of that on host commit."""
import gc
import importlib.util
import sys
import unittest
import weakref
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py'


def load_runner():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('cia_step_runner_bounded_collect', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Node:
    pass


def promoted_cycle():
    """A cycle alive at one bounded pass (the in-flight update) that becomes garbage before the next."""
    a, b = Node(), Node()
    a.other, b.other = b, a
    probe = weakref.ref(a)
    gc.collect(0)  # the pass that runs while the in-flight update still holds it: promoted to generation 1
    return probe


class BoundedCollect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner()

    def setUp(self):
        gc.collect()
        gc.disable()

    def tearDown(self):
        gc.enable()

    def test_a_promoted_cycle_is_reclaimed_at_the_next_pass(self):
        probe = promoted_cycle()
        self.runner.bounded_collect(63)
        self.assertIsNone(probe())

    def test_generation_zero_alone_leaks_it(self):
        # The defect the bound replaces, kept as the red: generation 0 never reaches a promoted cycle.
        probe = promoted_cycle()
        gc.collect(0)
        self.assertIsNotNone(probe())

    def test_every_4096th_pass_is_a_full_collection(self):
        seen = []
        original = gc.collect
        try:
            gc.collect = lambda generation=2: seen.append(generation) or 0
            for step in (63, 127, 4095, 8191):
                self.runner.bounded_collect(step)
        finally:
            gc.collect = original
        self.assertEqual(seen, [1, 1, 2, 2])


if __name__ == '__main__':
    unittest.main()
