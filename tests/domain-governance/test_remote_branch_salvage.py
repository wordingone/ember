# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# issue2015 exact-local-import:src/ember/governance/scripts/collect_remote_branch_salvage.py
import importlib.util as _ember_cb3304647ace68df_importlib
import sys as _ember_cb3304647ace68df_sys
from pathlib import Path as _ember_cb3304647ace68df_Path
_ember_cb3304647ace68df_path = _ember_cb3304647ace68df_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'collect_remote_branch_salvage.py')
if not _ember_cb3304647ace68df_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/collect_remote_branch_salvage.py')
_ember_cb3304647ace68df_aliases = ('_ember_issue2015_cb3304647ace68df', 'collect_remote_branch_salvage', 'scripts.collect_remote_branch_salvage', 'src.ember.governance.scripts.collect_remote_branch_salvage')
_ember_cb3304647ace68df_existing = []
for _ember_cb3304647ace68df_alias in _ember_cb3304647ace68df_aliases:
    _ember_cb3304647ace68df_candidate = _ember_cb3304647ace68df_sys.modules.get(_ember_cb3304647ace68df_alias)
    if _ember_cb3304647ace68df_candidate is not None and all(_ember_cb3304647ace68df_candidate is not item for item in _ember_cb3304647ace68df_existing):
        _ember_cb3304647ace68df_existing.append(_ember_cb3304647ace68df_candidate)
if len(_ember_cb3304647ace68df_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/collect_remote_branch_salvage.py')
if _ember_cb3304647ace68df_existing:
    _ember_cb3304647ace68df_module = _ember_cb3304647ace68df_existing[0]
    _ember_cb3304647ace68df_observed = getattr(_ember_cb3304647ace68df_module, '__file__', None)
    if _ember_cb3304647ace68df_observed is None or _ember_cb3304647ace68df_Path(_ember_cb3304647ace68df_observed).resolve() != _ember_cb3304647ace68df_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/collect_remote_branch_salvage.py')
else:
    _ember_cb3304647ace68df_spec = _ember_cb3304647ace68df_importlib.spec_from_file_location('_ember_issue2015_cb3304647ace68df', _ember_cb3304647ace68df_path)
    if _ember_cb3304647ace68df_spec is None or _ember_cb3304647ace68df_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/collect_remote_branch_salvage.py')
    _ember_cb3304647ace68df_module = _ember_cb3304647ace68df_importlib.module_from_spec(_ember_cb3304647ace68df_spec)
    for _ember_cb3304647ace68df_alias in _ember_cb3304647ace68df_aliases:
        _ember_cb3304647ace68df_prior = _ember_cb3304647ace68df_sys.modules.get(_ember_cb3304647ace68df_alias)
        if _ember_cb3304647ace68df_prior is not None and _ember_cb3304647ace68df_prior is not _ember_cb3304647ace68df_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/collect_remote_branch_salvage.py')
        _ember_cb3304647ace68df_sys.modules[_ember_cb3304647ace68df_alias] = _ember_cb3304647ace68df_module
    try:
        _ember_cb3304647ace68df_spec.loader.exec_module(_ember_cb3304647ace68df_module)
    except BaseException:
        for _ember_cb3304647ace68df_alias in _ember_cb3304647ace68df_aliases:
            if _ember_cb3304647ace68df_sys.modules.get(_ember_cb3304647ace68df_alias) is _ember_cb3304647ace68df_module:
                _ember_cb3304647ace68df_sys.modules.pop(_ember_cb3304647ace68df_alias, None)
        raise
for _ember_cb3304647ace68df_alias in _ember_cb3304647ace68df_aliases:
    _ember_cb3304647ace68df_prior = _ember_cb3304647ace68df_sys.modules.get(_ember_cb3304647ace68df_alias)
    if _ember_cb3304647ace68df_prior is not None and _ember_cb3304647ace68df_prior is not _ember_cb3304647ace68df_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/collect_remote_branch_salvage.py')
    _ember_cb3304647ace68df_sys.modules[_ember_cb3304647ace68df_alias] = _ember_cb3304647ace68df_module
_citations = getattr(_ember_cb3304647ace68df_module, '_citations')
# issue2015 exact-local-import-end:src/ember/governance/scripts/collect_remote_branch_salvage.py
# issue2015 exact-local-import:src/ember/governance/scripts/remote_branch_salvage.py
import importlib.util as _ember_538fc81bfbcace5e_importlib
import sys as _ember_538fc81bfbcace5e_sys
from pathlib import Path as _ember_538fc81bfbcace5e_Path
_ember_538fc81bfbcace5e_path = _ember_538fc81bfbcace5e_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'remote_branch_salvage.py')
if not _ember_538fc81bfbcace5e_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/remote_branch_salvage.py')
_ember_538fc81bfbcace5e_aliases = ('_ember_issue2015_538fc81bfbcace5e', 'remote_branch_salvage', 'scripts.remote_branch_salvage', 'src.ember.governance.scripts.remote_branch_salvage')
_ember_538fc81bfbcace5e_existing = []
for _ember_538fc81bfbcace5e_alias in _ember_538fc81bfbcace5e_aliases:
    _ember_538fc81bfbcace5e_candidate = _ember_538fc81bfbcace5e_sys.modules.get(_ember_538fc81bfbcace5e_alias)
    if _ember_538fc81bfbcace5e_candidate is not None and all(_ember_538fc81bfbcace5e_candidate is not item for item in _ember_538fc81bfbcace5e_existing):
        _ember_538fc81bfbcace5e_existing.append(_ember_538fc81bfbcace5e_candidate)
if len(_ember_538fc81bfbcace5e_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/remote_branch_salvage.py')
if _ember_538fc81bfbcace5e_existing:
    _ember_538fc81bfbcace5e_module = _ember_538fc81bfbcace5e_existing[0]
    _ember_538fc81bfbcace5e_observed = getattr(_ember_538fc81bfbcace5e_module, '__file__', None)
    if _ember_538fc81bfbcace5e_observed is None or _ember_538fc81bfbcace5e_Path(_ember_538fc81bfbcace5e_observed).resolve() != _ember_538fc81bfbcace5e_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/remote_branch_salvage.py')
else:
    _ember_538fc81bfbcace5e_spec = _ember_538fc81bfbcace5e_importlib.spec_from_file_location('_ember_issue2015_538fc81bfbcace5e', _ember_538fc81bfbcace5e_path)
    if _ember_538fc81bfbcace5e_spec is None or _ember_538fc81bfbcace5e_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/remote_branch_salvage.py')
    _ember_538fc81bfbcace5e_module = _ember_538fc81bfbcace5e_importlib.module_from_spec(_ember_538fc81bfbcace5e_spec)
    for _ember_538fc81bfbcace5e_alias in _ember_538fc81bfbcace5e_aliases:
        _ember_538fc81bfbcace5e_prior = _ember_538fc81bfbcace5e_sys.modules.get(_ember_538fc81bfbcace5e_alias)
        if _ember_538fc81bfbcace5e_prior is not None and _ember_538fc81bfbcace5e_prior is not _ember_538fc81bfbcace5e_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/remote_branch_salvage.py')
        _ember_538fc81bfbcace5e_sys.modules[_ember_538fc81bfbcace5e_alias] = _ember_538fc81bfbcace5e_module
    try:
        _ember_538fc81bfbcace5e_spec.loader.exec_module(_ember_538fc81bfbcace5e_module)
    except BaseException:
        for _ember_538fc81bfbcace5e_alias in _ember_538fc81bfbcace5e_aliases:
            if _ember_538fc81bfbcace5e_sys.modules.get(_ember_538fc81bfbcace5e_alias) is _ember_538fc81bfbcace5e_module:
                _ember_538fc81bfbcace5e_sys.modules.pop(_ember_538fc81bfbcace5e_alias, None)
        raise
for _ember_538fc81bfbcace5e_alias in _ember_538fc81bfbcace5e_aliases:
    _ember_538fc81bfbcace5e_prior = _ember_538fc81bfbcace5e_sys.modules.get(_ember_538fc81bfbcace5e_alias)
    if _ember_538fc81bfbcace5e_prior is not None and _ember_538fc81bfbcace5e_prior is not _ember_538fc81bfbcace5e_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/remote_branch_salvage.py')
    _ember_538fc81bfbcace5e_sys.modules[_ember_538fc81bfbcace5e_alias] = _ember_538fc81bfbcace5e_module
PacketError = getattr(_ember_538fc81bfbcace5e_module, 'PacketError')
build_packet = getattr(_ember_538fc81bfbcace5e_module, 'build_packet')
build_public_summary = getattr(_ember_538fc81bfbcace5e_module, 'build_public_summary')
validate_packet = getattr(_ember_538fc81bfbcace5e_module, 'validate_packet')
validate_public_summary = getattr(_ember_538fc81bfbcace5e_module, 'validate_public_summary')
# issue2015 exact-local-import-end:src/ember/governance/scripts/remote_branch_salvage.py


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
        self.assertEqual(packet["rows"][0]["disposition"], "NEGATIVE_KEEP")
        self.assertFalse(packet["rows"][0]["deletion_proposed"])
        self.assertIn("independent raw-source", packet["rows"][0]["falsifier"])
        self.assertEqual(packet["rows"][1]["ref"], "refs/heads/master")
        self.assertEqual(packet["rows"][1]["disposition"], "NEGATIVE_KEEP")
        self.assertFalse(packet["rows"][1]["deletion_proposed"])
        self.assertEqual(packet["safe_to_delete_refs"], [])
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

    def test_inconsistent_reachability_is_rejected(self) -> None:
        invalid = (
            {"status": "IDENTICAL", "ahead_by": 1, "behind_by": 0, "merge_base": sha("b")},
            {"status": "BEHIND", "ahead_by": 5, "behind_by": 4, "merge_base": sha("b")},
            {"status": "AHEAD", "ahead_by": 1, "behind_by": 2, "merge_base": sha("b")},
            {"status": "DIVERGED", "ahead_by": 0, "behind_by": 2, "merge_base": sha("b")},
            {"status": "NO_COMMON_ANCESTOR", "ahead_by": 0, "behind_by": 0, "merge_base": sha("b")},
            {"status": "ERROR", "ahead_by": 1, "behind_by": 0, "merge_base": None},
        )
        for reachability in invalid:
            with self.subTest(reachability=reachability):
                value = capture()
                value["branches"][1]["reachability"] = reachability
                with self.assertRaises(PacketError):
                    build_packet(value)

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
        self.assertEqual(summary["proposal_refs_utf8_hex"], [])

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

    def test_public_tree_scan_never_self_attests_external_custody_complete(self) -> None:
        master = sha("a")
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"{master}:receipts/example.json:7:matched\n{master}:docs/example.md:9:matched\n",
            stderr="",
        )
        with patch("src.ember.governance.scripts.collect_remote_branch_salvage._run_git", return_value=completed):
            public, custody = _citations(Path("."), master, "feat/example", sha("b"))
        self.assertTrue(public["complete"])
        self.assertEqual(public["citations"], ["docs/example.md:9", "receipts/example.json:7"])
        self.assertEqual(custody, {"complete": False, "citations": []})

    def test_collector_cli_imports_from_repository_root(self) -> None:
        root = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
        result = subprocess.run(
            [sys.executable, "-B", "src/ember/governance/scripts/collect_remote_branch_salvage.py", "--help"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--raw-root", result.stdout)


if __name__ == "__main__":
    unittest.main()
