# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The pack look-ahead must not retain every pack it draws when its consumer never asks for the row digest.
The governed hour never calls _row_digest, and an unbounded map kept 4,096 position lists per update until the host
ran out of memory near update 28.8k."""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'src/ember/infrastructure/tools/ember-restart-3b/cia_step_runner.py'


def load_runner():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('cia_step_runner_drawn_digest_bound', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Inner:
    def __init__(self, count):
        self.cursor, self.index, self.maximum_steps = {'at': 0}, 0, count

    def next_pack(self):
        pack = {'token_ids': [1] * 8, 'target_ids': [1] * 8, 'positions': [[p, 0, 0] for p in range(8)],
                'document_starts': [0], 'index': self.index}
        self.index += 1
        self.cursor = {'at': self.index}
        return pack


class DrawnDigestBound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner()

    def setUp(self):
        self.runner._DRAWN_DIGESTS.clear()

    def test_a_consumer_that_never_pops_retains_a_bounded_number(self):
        packs = self.runner.LookaheadPacks(Inner(200))
        drawn = [packs.next_pack() for _ in range(150)]
        self.assertLessEqual(len(self.runner._DRAWN_DIGESTS), self.runner._DRAWN_DIGESTS_CAP)
        self.assertEqual(len(drawn), 150)

    def test_the_in_flight_digest_is_still_the_producers(self):
        packs = self.runner.LookaheadPacks(Inner(10))
        pack = packs.next_pack()
        self.assertEqual(self.runner._row_digest(pack), self.runner._pack_digest([pack]))
        self.assertNotIn(id(pack), self.runner._DRAWN_DIGESTS)

    def test_unbounded_insertion_is_the_defect(self):
        # The red: the pre-cure insertion, repeated, grows without limit.
        for index in range(50):
            pack = {'index': index}
            self.runner._DRAWN_DIGESTS[id(pack)] = (pack, 'x')
        self.assertGreater(len(self.runner._DRAWN_DIGESTS), self.runner._DRAWN_DIGESTS_CAP)


if __name__ == '__main__':
    unittest.main()
