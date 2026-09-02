# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import copy
import unittest

from src.ember.governance.scripts.github.deprecated_labels import RetirementError, apply, build_plan


class Client:
    def __init__(self):
        self.calls = []

    def edit_item_labels(self, **kwargs):
        self.calls.append(("edit", kwargs))

    def delete_label(self, name):
        self.calls.append(("delete", name))


class DeprecatedLabelTests(unittest.TestCase):
    def snapshot(self):
        return {
            "repository": "wordingone/ember",
            "labels": [{"name": "kind:defect"}, {"name": "bug"}],
            "items": [
                {
                    "item_type": "issue",
                    "number": 1,
                    "state": "CLOSED",
                    "labels": ["bug"],
                }
            ],
        }

    def manifest(self):
        return {"labels": [{"name": "kind:defect"}]}

    def migrations(self):
        return {"rules": [{"source_label": "bug"}]}

    def test_plan_preserves_closed_history_and_retires_definition(self):
        plan = build_plan(self.snapshot(), self.manifest(), self.migrations())
        self.assertEqual(["bug"], plan["deprecated_labels"])
        self.assertEqual(1, plan["closed_item_changes"][0]["number"])
        self.assertEqual(0, plan["body_mutation_count"])

    def test_open_use_refuses(self):
        snapshot = self.snapshot()
        snapshot["items"][0]["state"] = "OPEN"
        with self.assertRaises(RetirementError):
            build_plan(snapshot, self.manifest(), self.migrations())

    def test_unknown_noncanonical_label_refuses(self):
        snapshot = self.snapshot()
        snapshot["labels"].append({"name": "mystery"})
        with self.assertRaises(RetirementError):
            build_plan(snapshot, self.manifest(), self.migrations())

    def test_apply_checks_digest_and_orders_removal_before_delete(self):
        snapshot = self.snapshot()
        plan = build_plan(snapshot, self.manifest(), self.migrations())
        client = Client()
        receipt = apply(plan, snapshot, client, confirm=True)
        self.assertEqual("edit", client.calls[0][0])
        self.assertEqual(("delete", "bug"), client.calls[1])
        self.assertEqual("APPLIED", receipt["status"])
        changed = copy.deepcopy(snapshot)
        changed["items"][0]["labels"] = []
        with self.assertRaises(RetirementError):
            apply(plan, changed, Client(), confirm=True)


if __name__ == "__main__":
    unittest.main()
