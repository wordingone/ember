# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import hashlib
import json
import unittest

from scripts.remote_branch_salvage import (
    PacketError,
    build_packet,
    build_public_summary,
    validate_packet,
    validate_public_summary,
)


def sha(ch: str) -> str:
    return ch * 40


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def row(name: str = "feat/contained", *, head: str | None = None) -> dict:
    head = head or sha("b")
    return {
        "name": name,
        "ref": f"refs/heads/{name}",
        "head_sha": head,
        "protected": False,
        "open_head_prs": [],
        "all_prs": [{"number": 7, "state": "closed", "head_sha": head, "merged": True, "merge_sha": sha("c"), "base_sha": sha("d")}],
        "reachability": {"status": "BEHIND", "ahead_by": 0, "behind_by": 4, "merge_base": head},
        "patch_blob_equivalence": {"status": "PROVEN", "canonical_survivor": sha("c"), "path_count": 1, "path_digest_sha256": "1" * 64, "patch_digest_sha256": "2" * 64},
        "exact_head_tags": [],
        "releases": [],
        "deployments": [],
        "public_consumers": {"complete": True, "citations": []},
        "custody_references": {"complete": True, "citations": []},
        "reconstruction": {"command": f"git fetch origin refs/heads/{name}:refs/remotes/origin/{name}", "expected_sha": head},
        "ref_stability": {"captured_sha": head, "preexecution_sha": head},
        "errors": [],
    }


def capture() -> dict:
    master = row("master", head=sha("a"))
    master["protected"] = True
    master["all_prs"] = []
    master["reachability"] = {"status": "IDENTICAL", "ahead_by": 0, "behind_by": 0, "merge_base": sha("a")}
    master["patch_blob_equivalence"] = {"status": "NOT_APPLICABLE", "canonical_survivor": sha("a"), "path_count": 0, "path_digest_sha256": hashlib.sha256(b"").hexdigest(), "patch_digest_sha256": hashlib.sha256(b"").hexdigest()}
    rows = [master, row()]
    return {
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        },
        "schema_version": "ember-remote-branch-capture-v1",
        "repository": "wordingone/ember",
        "master_sha": sha("a"),
        "captured_at": "2026-07-26T05:40:00Z",
        "pagination": {"complete": True, "page_size": 100, "link_headers_exhausted": True},
        "source_evidence": {key: "3" * 64 for key in ("branches_pre", "branches_post", "pulls", "tags", "releases", "deployments", "public_master")},
        "branches": rows,
        "selection_sha256": hashlib.sha256(canonical([[r["ref"], r["head_sha"]] for r in sorted(rows, key=lambda x: x["ref"])] )).hexdigest(),
    }


class RemoteBranchSalvageTests(unittest.TestCase):
    def test_builds_closed_non_authorizing_packet(self) -> None:
        packet = build_packet(capture())
        self.assertEqual(packet["branch_count"], 2)
        self.assertEqual(packet["deletion_authority"], "NOT_GRANTED")
        self.assertFalse(packet["public_mutation_performed"])
        self.assertEqual(packet["rows"][0]["ref"], "refs/heads/feat/contained")
        self.assertEqual(packet["rows"][0]["disposition"], "DISCARD_EVIDENCED")
        self.assertTrue(packet["rows"][0]["deletion_proposed"])
        self.assertEqual(packet["rows"][1]["ref"], "refs/heads/master")
        self.assertEqual(packet["rows"][1]["disposition"], "NEGATIVE_KEEP")
        self.assertFalse(packet["rows"][1]["deletion_proposed"])
        validate_packet(packet)

    def test_exact_authority_binding_survives_packet_build(self) -> None:
        packet = build_packet(capture())
        self.assertEqual(packet["authority"]["goal_id"], "EMBER-02")
        self.assertEqual(packet["authority"]["workstream_id"], "EMBER-02A")

    def test_wrong_authority_binding_is_rejected(self) -> None:
        value = capture()
        value["authority"]["workstream_id"] = "EMBER-02B"
        with self.assertRaises(PacketError):
            build_packet(value)

    def test_open_pr_fails_closed(self) -> None:
        value = capture()
        value["branches"][1]["open_head_prs"] = [{"number": 99, "head_sha": sha("b")}]
        packet = build_packet(value)
        self.assertEqual(packet["rows"][0]["disposition"], "NEGATIVE_KEEP")
        self.assertIn("open head PR", packet["rows"][0]["falsifier"])

    def test_open_pr_with_drifted_head_still_fails_closed(self) -> None:
        value = capture()
        value["branches"][1]["all_prs"].append({"number": 8, "state": "open", "head_sha": sha("f"), "merged": False, "merge_sha": None, "base_sha": sha("d")})
        packet = build_packet(value)
        self.assertEqual(packet["rows"][0]["disposition"], "NEGATIVE_KEEP")
        self.assertIn("open PR", packet["rows"][0]["falsifier"])

    def test_extra_packet_row_field_rejected(self) -> None:
        packet = build_packet(capture())
        packet["rows"][0]["unexpected"] = True
        body = dict(packet)
        body.pop("packet_sha256")
        packet["packet_sha256"] = hashlib.sha256(canonical(body)).hexdigest()
        with self.assertRaises(PacketError):
            validate_packet(packet)
    def test_unique_content_fails_closed(self) -> None:
        value = capture()
        value["branches"][1]["reachability"] = {"status": "DIVERGED", "ahead_by": 1, "behind_by": 4, "merge_base": sha("e")}
        value["branches"][1]["patch_blob_equivalence"]["status"] = "NOT_PROVEN"
        packet = build_packet(value)
        self.assertEqual(packet["rows"][0]["disposition"], "NEGATIVE_KEEP")

    def test_ref_drift_fails_closed(self) -> None:
        value = capture()
        value["branches"][1]["ref_stability"]["preexecution_sha"] = sha("f")
        packet = build_packet(value)
        self.assertEqual(packet["rows"][0]["disposition"], "NEGATIVE_KEEP")
        self.assertIn("ref drift", packet["rows"][0]["falsifier"])

    def test_incomplete_population_rejected(self) -> None:
        value = capture()
        value["pagination"]["complete"] = False
        with self.assertRaises(PacketError):
            build_packet(value)

    def test_duplicate_ref_rejected(self) -> None:
        value = capture()
        value["branches"].append(copy.deepcopy(value["branches"][1]))
        with self.assertRaises(PacketError):
            build_packet(value)

    def test_selection_digest_tamper_rejected(self) -> None:
        value = capture()
        value["selection_sha256"] = "0" * 64
        with self.assertRaises(PacketError):
            build_packet(value)

    def test_protection_unknown_fails_closed(self) -> None:
        value = capture()
        value["branches"][1]["protected"] = None
        packet = build_packet(value)
        self.assertEqual(packet["rows"][0]["disposition"], "NEGATIVE_KEEP")

    def test_consumer_or_custody_reference_fails_closed(self) -> None:
        for key in ("public_consumers", "custody_references"):
            value = capture()
            value["branches"][1][key]["citations"] = ["docs/example.md:1"]
            packet = build_packet(value)
            self.assertEqual(packet["rows"][0]["disposition"], "NEGATIVE_KEEP")

    def test_packet_evidence_tamper_rejected(self) -> None:
        packet = build_packet(capture())
        packet["rows"][0]["head_sha"] = sha("9")
        with self.assertRaises(PacketError):
            validate_packet(packet)

    def test_authority_escalation_rejected(self) -> None:
        packet = build_packet(capture())
        packet["deletion_authority"] = "GRANTED"
        with self.assertRaises(PacketError):
            validate_packet(packet)

    def test_unknown_fields_rejected(self) -> None:
        value = capture()
        value["unexpected"] = True
        with self.assertRaises(PacketError):
            build_packet(value)

    def test_public_summary_encodes_exact_refs_without_plaintext(self) -> None:
        packet = build_packet(capture())
        summary = build_public_summary(packet)
        validate_public_summary(summary)
        rendered = json.dumps(summary, sort_keys=True)
        self.assertNotIn("refs/heads/feat/contained", rendered)
        encoded = summary["rows"][0]["ref_utf8_hex"]
        self.assertEqual(bytes.fromhex(encoded).decode("utf-8"), "refs/heads/feat/contained")
        self.assertEqual(summary["proposal_refs_utf8_hex"], [encoded])

    def test_public_summary_tamper_is_rejected(self) -> None:
        summary = build_public_summary(build_packet(capture()))
        summary["rows"][0]["evidence_sha256"] = "9" * 64
        with self.assertRaises(PacketError):
            validate_public_summary(summary)

    def test_public_summary_cannot_escalate_authority(self) -> None:
        summary = build_public_summary(build_packet(capture()))
        summary["deletion_authority"] = "GRANTED"
        with self.assertRaises(PacketError):
            validate_public_summary(summary)


if __name__ == "__main__":
    unittest.main()
