# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Declared-lr lineage (#2119 H43): a child whose optimizer identity differs from its parent's only in lr publishes
under an hour declaration; an undeclared lr difference refuses; a same-lr child keeps today's lineage."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(ROOT / 'src'))
_spec = importlib.util.spec_from_file_location('parameter_counter_lr', TOOL / 'parameter_counter.py')
counter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(counter)


def identity(lr):
    hp = dict(lr=lr, betas=[0.9, 0.95], eps=1e-8, weight_decay=0.1)
    return dict(kind='adamw', defaults=dict(hp), param_groups=[dict(params=['a', 'b'], hyperparameters=dict(hp))])


DECL = dict(declared_lr=0.0003, source='hour.declared_lr')


class DeclaredLrLineage(unittest.TestCase):
    def test_declared_lr_child_publishes(self):
        record = counter._cia_lr_transition({'optimizer_identity': identity(0.001)}, {'optimizer_identity': identity(0.0003)}, DECL)
        self.assertEqual(record, dict(parent_lr=0.001, child_lr=0.0003, declared_lr=0.0003, source='hour.declared_lr'))

    def test_undeclared_lr_difference_refuses(self):
        with self.assertRaisesRegex(ValueError, 'optimizer_identity differ'):
            counter._cia_lr_transition({'optimizer_identity': identity(0.001)}, {'optimizer_identity': identity(0.0003)}, None)

    def test_declaration_must_match_child_lr(self):
        with self.assertRaisesRegex(ValueError, 'declared lr is not the child'):
            counter._cia_lr_transition({'optimizer_identity': identity(0.001)}, {'optimizer_identity': identity(0.0005)}, DECL)

    def test_non_lr_difference_refuses_even_declared(self):
        child = identity(0.0003)
        child['defaults']['weight_decay'] = 0.0
        with self.assertRaisesRegex(ValueError, 'optimizer_identity differ'):
            counter._cia_lr_transition({'optimizer_identity': identity(0.001)}, {'optimizer_identity': child}, DECL)

    def test_same_lr_child_has_no_lr_record(self):
        self.assertIsNone(counter._cia_lr_transition({'optimizer_identity': identity(0.001)}, {'optimizer_identity': identity(0.001)}, None))
        self.assertIsNone(counter._cia_lr_transition({'optimizer_identity': identity(0.001)}, {'optimizer_identity': identity(0.001)}, DECL))


if __name__ == '__main__':
    unittest.main()
