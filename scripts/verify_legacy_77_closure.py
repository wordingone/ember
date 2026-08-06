# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TARGETS = [35,54,99,113,118,124,125,140,154,200,203,206,211,214,242,252,280,303,321,345,354,370,440,466,480,485,488,518,546,552,562,565,585,594,627,649,650,651,652,653,654,655,656,657,658,659,663,676,685,688,696,700,701,702,703,704,705,707,711,735,739,756,757,764,774,779,782,785,786,787,802,812,869,872,894,898,917]
SHA = "^[0-9a-f]{64}$"

def canon(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def digest(v):
    return hashlib.sha256(canon(v)).hexdigest()

def reject(ok, errors, condition, message):
    if condition:
        errors.append(message)

def verify(census_path: Path, dag_path: Path, ledger_path: Path, expected_master: str | None = None):
    errors = []
    try:
        census = json.loads(census_path.read_text(encoding="utf-8"))
        dag = json.loads(dag_path.read_text(encoding="utf-8"))
        ledger = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception as exc:
        return {"status": "REJECT", "errors": [f"read/parse: {exc}"]}
    expected_census = {"schema_version","repository","goal_id","workstream_id","next_executed_outcome","public_master_sha","captured_at","target_issue_numbers","coverage_freeze","coverage_status","deletion_authority","issues","claim_boundary"}
    reject(True, errors, set(census) != expected_census, "census top-level schema is not closed")
    reject(True, errors, census.get("target_issue_numbers") != TARGETS, "target universe is not exactly the fixed 77")
    reject(True, errors, census.get("deletion_authority") != "NOT_GRANTED", "construction census may not grant deletion authority")
    reject(True, errors, census.get("coverage_freeze") is not False, "construction census cannot claim coverage freeze")
    if expected_master:
        reject(True, errors, census.get("public_master_sha") != expected_master, "stale public master")
    rows = census.get("issues") if isinstance(census.get("issues"), list) else []
    reject(True, errors, len(rows) != 77, "census does not contain exactly 77 rows")
    numbers = [r.get("issue_number") for r in rows if isinstance(r, dict)]
    reject(True, errors, len(numbers) != len(set(numbers)), "duplicate issue row")
    reject(True, errors, set(numbers) != set(TARGETS), "missing or extra issue row")
    row_keys = {"issue_number","title","url","author","created_at","updated_at","current_state","state_reason","labels","milestone","assignees","body_sha256","conversation_sha256","source_snapshot","clauses","linked_prs","relevant_evidence","proposed_route","route_rationale","residual_risk","canonical_successor","required_engineering","required_pr_plan","matching_pr_set","claim_boundary"}
    for row in rows:
        if not isinstance(row, dict):
            errors.append("non-object issue row")
            continue
        reject(True, errors, set(row) != row_keys, f"row {row.get('issue_number')} schema is not closed")
        reject(True, errors, not isinstance(row.get("body_sha256"), str) or __import__("re").fullmatch(SHA, row["body_sha256"]) is None, f"row {row.get('issue_number')} bad body hash")
        reject(True, errors, not isinstance(row.get("conversation_sha256"), str) or row["conversation_sha256"] == "PENDING_FROM_RAW_COMMENT_TIMELINE" or __import__("re").fullmatch(SHA, row["conversation_sha256"]) is None, f"row {row.get('issue_number')} bad conversation hash")
        reject(True, errors, row.get("proposed_route") != "EXECUTE", f"row {row.get('issue_number')} uses a non-executable temporary route")
        clauses = row.get("clauses")
        reject(True, errors, not isinstance(clauses, list) or not clauses, f"row {row.get('issue_number')} has no clauses")
        if isinstance(clauses, list):
            for clause in clauses:
                ck = {"id","text","status","source_citations","master_evidence","proof_class","falsifier","dependencies"}
                reject(True, errors, not isinstance(clause, dict) or set(clause) != ck, f"row {row.get('issue_number')} clause schema")
                if isinstance(clause, dict):
                    reject(True, errors, clause.get("status") not in {"PROVED","UNMET","OBSOLETE_BY_RULING","TRANSFER_REQUIRED"}, f"row {row.get('issue_number')} invalid clause status")
                    reject(True, errors, not clause.get("text"), f"row {row.get('issue_number')} clause text missing")
        if row.get("issue_number") == 764:
            prs = row.get("matching_pr_set") or []
            reject(True, errors, not any(x.get("pr_number") == 1511 and x.get("head") == "07e2e43e44fbdefd1d19e10a56429b2f597559bf" for x in prs if isinstance(x, dict)), "#764 is not bound to the current-native producer PR")
    expected_dag = {"schema_version","repository","goal_id","workstream_id","public_master_sha","deletion_authority","nodes","edges","topological_order"}
    reject(True, errors, set(dag) != expected_dag, "DAG schema is not closed")
    reject(True, errors, dag.get("deletion_authority") != "NOT_GRANTED", "DAG grants deletion authority")
    nodes = dag.get("nodes") if isinstance(dag.get("nodes"), list) else []
    node_ids = [x.get("id") for x in nodes if isinstance(x, dict)]
    expected_nodes = {f"I{n:04d}" for n in TARGETS} | {"M702-CURRENT-NATIVE-CPUOFFLOAD","M707-OPTIMIZER-IDENTITY"}
    reject(True, errors, set(node_ids) != expected_nodes or len(node_ids) != len(set(node_ids)), "DAG node set mismatch")
    edges = dag.get("edges") if isinstance(dag.get("edges"), list) else []
    adjacency = {x: [] for x in expected_nodes}
    for edge in edges:
        reject(True, errors, not isinstance(edge, dict) or set(edge) != {"from","to","reason"}, "DAG edge schema")
        if isinstance(edge, dict) and edge.get("from") in adjacency and edge.get("to") in adjacency:
            adjacency[edge["from"]].append(edge["to"])
        else:
            errors.append("DAG edge references unknown node")
    seen, active = set(), set()
    def dfs(node):
        if node in active:
            errors.append("DAG cycle detected")
            return
        if node in seen:
            return
        active.add(node)
        for child in adjacency[node]:
            dfs(child)
        active.remove(node); seen.add(node)
    for node in expected_nodes:
        dfs(node)
    ledger_keys = {"goal_id","workstream_id","next_executed_outcome","issue_number","disposition","body_sha256","conversation_sha256","public_master_sha","matching_pr_set","coverage_status","claim_boundary","row_sha256"}
    reject(True, errors, len(ledger) != 77, "ledger does not contain exactly 77 rows")
    ledger_by_num = {}
    for row in ledger:
        reject(True, errors, set(row) != ledger_keys, f"ledger row {row.get('issue_number')} schema")
        if row.get("goal_id") != "EMBER-02" or row.get("workstream_id") != "EMBER-02A" or row.get("next_executed_outcome") != "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember":
            errors.append(f"ledger row {row.get('issue_number')} authority mismatch")
        n = row.get("issue_number")
        if n in ledger_by_num:
            errors.append(f"duplicate ledger row {n}")
        ledger_by_num[n] = row
        copy = dict(row); copy.pop("row_sha256", None)
        reject(True, errors, row.get("row_sha256") != hashlib.sha256(canon(copy)).hexdigest(), f"ledger row {n} digest mismatch")
    for row in rows:
        n = row["issue_number"]; l = ledger_by_num.get(n)
        reject(True, errors, l is None, f"ledger missing {n}")
        if l:
            for key in ("body_sha256","conversation_sha256"):
                reject(True, errors, l[key] != row[key], f"ledger/census {n} {key} mismatch")
    status = "REJECT" if errors else "CONSTRUCTION_IN_PROGRESS"
    return {"status": status, "coverage_freeze_ready": False, "issues": len(rows), "public_master_sha": census.get("public_master_sha"), "deletion_authority": census.get("deletion_authority"), "errors": errors}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--master-sha")
    args = ap.parse_args()
    root = Path(args.root)
    result = verify(root / "docs/issue-closure/legacy-77-census.json", root / "manifests/legacy-77-dependency-dag-v1.json", root / "receipts/legacy-77-closure/ledger.jsonl", args.master_sha)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["status"] == "CONSTRUCTION_IN_PROGRESS" else 2)

if __name__ == "__main__":
    main()
