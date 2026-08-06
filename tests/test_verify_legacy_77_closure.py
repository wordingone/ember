# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import scripts.verify_legacy_77_closure as verifier

class Legacy77VerifierTests(unittest.TestCase):
    def packet(self):
        root = Path(tempfile.mkdtemp())
        for rel in ("docs/issue-closure", "manifests", "receipts/legacy-77-closure"):
            (root / rel).mkdir(parents=True)
        rows=[]
        for n in verifier.TARGETS:
            rows.append({"issue_number":n,"title":"x","url":f"https://github.com/wordingone/ember/issues/{n}","author":"wordingone","created_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:00Z","current_state":"open","state_reason":"NONE_REPORTED","labels":[],"milestone":None,"assignees":[],"body_sha256":"a"*64,"conversation_sha256":"b"*64,"source_snapshot":{},"clauses":[{"id":f"I{n:04d}-C01","text":"full acceptance","status":"UNMET","source_citations":[],"master_evidence":[],"proof_class":"ISSUE_ACCEPTANCE_EXECUTION","falsifier":"f","dependencies":[]}],"linked_prs":[],"relevant_evidence":[],"proposed_route":"EXECUTE","route_rationale":"r","residual_risk":"risk","canonical_successor":None,"required_engineering":"e","required_pr_plan":[{"status":"PENDING_EXECUTION_PR"}],"matching_pr_set":[],"claim_boundary":"no claim"})
        next(row for row in rows if row["issue_number"] == 764)["matching_pr_set"]=[{"pr_number":1511,"url":"https://github.com/wordingone/ember/pull/1511","head":"075f40a7d19fd681ec932860fb568e3e31f316a8","base":"d648d7f9f692134bf51478d3303267666b04e342"}]
        master="d648d7f9f692134bf51478d3303267666b04e342"
        census={"schema_version":"legacy-77-census-v1","repository":"wordingone/ember","goal_id":"EMBER-02","workstream_id":"EMBER-02A","next_executed_outcome":"EMBER-02 first sufficiently pretrained clean-genesis 3B Ember","public_master_sha":master,"captured_at":"2026-08-06T00:00:00Z","target_issue_numbers":verifier.TARGETS,"coverage_freeze":False,"coverage_status":"CONSTRUCTION_IN_PROGRESS","deletion_authority":"NOT_GRANTED","issues":rows,"claim_boundary":"no claim"}
        nodes=[{"id":f"I{n:04d}","kind":"issue"} for n in verifier.TARGETS]+[{"id":"M702-CURRENT-NATIVE-CPUOFFLOAD","kind":"shared_mechanism"},{"id":"M707-OPTIMIZER-IDENTITY","kind":"shared_mechanism"}]
        dag={"schema_version":"legacy-77-dependency-dag-v1","repository":"wordingone/ember","goal_id":"EMBER-02","workstream_id":"EMBER-02A","public_master_sha":master,"deletion_authority":"NOT_GRANTED","nodes":nodes,"edges":[],"topological_order":[]}
        ledger=[]
        for row in rows:
            item={"goal_id":"EMBER-02","workstream_id":"EMBER-02A","next_executed_outcome":"EMBER-02 first sufficiently pretrained clean-genesis 3B Ember","issue_number":row["issue_number"],"disposition":"EXECUTE","body_sha256":row["body_sha256"],"conversation_sha256":row["conversation_sha256"],"public_master_sha":master,"matching_pr_set":row["matching_pr_set"],"coverage_status":"CONSTRUCTION_IN_PROGRESS","claim_boundary":"no claim"}
            item["row_sha256"]=hashlib.sha256(verifier.canon(item)).hexdigest(); ledger.append(item)
        (root/"docs/issue-closure/legacy-77-census.json").write_text(json.dumps(census),encoding="utf-8")
        (root/"manifests/legacy-77-dependency-dag-v1.json").write_text(json.dumps(dag),encoding="utf-8")
        (root/"receipts/legacy-77-closure/ledger.jsonl").write_text("".join(json.dumps(x)+"\n" for x in ledger),encoding="utf-8")
        return root
    def check(self, root):
        return verifier.verify(root/"docs/issue-closure/legacy-77-census.json",root/"manifests/legacy-77-dependency-dag-v1.json",root/"receipts/legacy-77-closure/ledger.jsonl","d648d7f9f692134bf51478d3303267666b04e342")
    def test_positive_construction_packet(self):
        self.assertEqual(self.check(self.packet())["status"],"CONSTRUCTION_IN_PROGRESS")
    def test_rejects_duplicate_target(self):
        root=self.packet(); p=root/"docs/issue-closure/legacy-77-census.json"; c=json.loads(p.read_text()); c["issues"][1]["issue_number"]=c["issues"][0]["issue_number"]; p.write_text(json.dumps(c)); self.assertEqual(self.check(root)["status"],"REJECT")
    def test_rejects_unknown_row_field(self):
        root=self.packet(); p=root/"docs/issue-closure/legacy-77-census.json"; c=json.loads(p.read_text()); c["issues"][0]["extra"]=True; p.write_text(json.dumps(c)); self.assertEqual(self.check(root)["status"],"REJECT")
    def test_rejects_deletion_authority(self):
        root=self.packet(); p=root/"manifests/legacy-77-dependency-dag-v1.json"; d=json.loads(p.read_text()); d["deletion_authority"]="GRANTED_EXACT_ROWS"; p.write_text(json.dumps(d)); self.assertEqual(self.check(root)["status"],"REJECT")

if __name__ == "__main__":
    unittest.main()
