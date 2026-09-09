# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# goal_id: EMBER-02
# workstream_id: EMBER-02A
"""Non-learning inventory mechanics, not a realized model qualification."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ember.model.ember_v0_inventory import equation_inventory, meta_inventory, update_support

class CIAInventoryTests(unittest.TestCase):
    def test_equations_expose_three_unassigned_reference_norms(self):
        specs = equation_inventory()
        self.assertEqual(sum(s.numel for s in specs), 3_082_539_008)
        self.assertEqual(3_082_542_080 - sum(s.numel for s in specs), 3 * 1024)

    def test_full_distinct_global_population_and_roles(self):
        specs = equation_inventory()
        self.assertEqual(len({s.name for s in specs}), len(specs))
        self.assertEqual({s.expert for s in specs if s.role == "expert"}, set(range(25)))
        for expert in range(25):
            self.assertEqual(sum(s.numel for s in specs if s.expert == expert), 113_246_208)
        self.assertEqual({s.role for s in specs}, {"core", "adapter", "router", "expert"})

    def test_meta_tensors_match_specs_without_allocating_weights(self):
        specs = equation_inventory()
        tensors = meta_inventory()
        self.assertEqual(set(tensors), {s.name for s in specs})
        self.assertEqual(sum(t.numel() for t in tensors.values()), 3_082_539_008)
        self.assertTrue(all(t.device.type == "meta" for t in tensors.values()))
        for spec in specs:
            self.assertEqual(tuple(tensors[spec.name].shape), spec.shape)

    def test_combined_update_excludes_router_and_other_experts(self):
        specs = equation_inventory()
        selected = update_support("core+expert-set", experts=(3, 9))
        expected = {s.name for s in specs if s.role in {"core", "adapter"} or s.expert in (3, 9)}
        self.assertEqual(selected, expected)
        self.assertFalse(selected & update_support("router-only"))
        self.assertTrue(update_support("expert-set", experts=(3,)) < selected)

    def test_router_and_memory_support(self):
        self.assertEqual(update_support("memory-only"), frozenset())
        self.assertEqual(update_support("router-only"), {s.name for s in equation_inventory() if s.role == "router"})

    def test_unsupported_or_ambiguous_loci_refused(self):
        for locus, experts in (("all", ()), ("expert-set", ()), ("expert-set", (True,)), ("expert-set", (25,)), ("core-only", (1,)), ("expert-set", (1, 1))):
            with self.subTest(locus=locus, experts=experts), self.assertRaises(ValueError):
                update_support(locus, experts=experts)

if __name__ == "__main__":
    unittest.main()
