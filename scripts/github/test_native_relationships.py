# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import copy
import unittest

from scripts.github.native_relationships import (
    RelationshipError,
    apply,
    build_plan,
    verify,
)


class FakeClient:
    def __init__(self):
        self.live = {}
        self.added = []

    def children(self, parent):
        return dict(self.live.get(parent, {}))

    def add(self, parent_node_id, child_node_id):
        parent = int(parent_node_id.removeprefix("P"))
        child = int(child_node_id.removeprefix("C"))
        self.live.setdefault(parent, {})[child] = child_node_id
        self.added.append((parent_node_id, child_node_id))


class NativeRelationshipTests(unittest.TestCase):
    def review(self):
        return {
            "repository": "wordingone/ember",
            "plan_sha256": "a" * 64,
            "rows": [
                {"number": 100, "node_id": "P100", "native_parent_issue": None},
                {"number": 2, "node_id": "C2", "native_parent_issue": 100},
                {"number": 3, "node_id": "C3", "native_parent_issue": 100},
            ],
        }

    def test_plan_is_closed_and_sorted(self):
        plan = build_plan(self.review())
        self.assertEqual([2, 3], [row["child"] for row in plan["edges"]])
        self.assertEqual(64, len(plan["plan_sha256"]))

    def test_invalid_parent_refuses(self):
        review = self.review()
        review["rows"][1]["native_parent_issue"] = 999
        with self.assertRaises(RelationshipError):
            build_plan(review)

    def test_apply_is_idempotent_and_verifies(self):
        plan = build_plan(self.review())
        client = FakeClient()
        receipt = apply(plan, client, confirm=True)
        self.assertEqual(2, receipt["added_count"])
        receipt = apply(plan, client, confirm=True)
        self.assertEqual(0, receipt["added_count"])
        self.assertEqual(2, receipt["already_present_count"])

    def test_tampered_plan_refuses(self):
        plan = build_plan(self.review())
        plan["edges"][0]["child"] = 9
        with self.assertRaises(RelationshipError):
            apply(plan, FakeClient(), confirm=True)

    def test_verify_refuses_missing(self):
        plan = build_plan(self.review())
        with self.assertRaises(RelationshipError):
            verify(plan, FakeClient())


if __name__ == "__main__":
    unittest.main()
