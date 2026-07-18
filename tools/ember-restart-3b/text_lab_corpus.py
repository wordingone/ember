# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""L4 manifest gate for planned, non-acquired AI-lab shared-text sources."""
from __future__ import annotations
import hashlib
import json
from typing import Any, Iterable

DOMAINS = ("mathematics", "statistics", "physics", "computer_science", "ml_ai", "training_infrastructure", "formal_logic", "software_engineering", "data_evaluation", "scientific_method", "application_worlds")
LICENSES = {"CC0-1.0", "CC-BY-4.0", "MIT", "Apache-2.0", "BSD-3-Clause", "PDDL-1.0"}

def _root(rows: Iterable[dict[str, Any]], split: str) -> str:
    digest=hashlib.sha256(f"ember-text-lab-corpus-v1\0{split}\0".encode())
    for row in sorted((x for x in rows if x["split"] == split), key=lambda x:(x["domain"],x["source_id"])):
        digest.update(row["domain"].encode()+b"\0"+row["source_id"].encode()+b"\0"+bytes.fromhex(row["content_sha256"]))
    return digest.hexdigest()

def _validate(rows: list[dict[str, Any]], frozen: set[str]) -> None:
    if not rows: raise ValueError("text corpus source set is empty")
    seen=set(); by_domain={domain:0 for domain in DOMAINS}
    for row in rows:
        if not isinstance(row,dict) or set(row) != {"source_id","domain","license_spdx","content_sha256","l4_receipt","split"}: raise ValueError("source row schema is invalid")
        domain=row["domain"]; content=row["content_sha256"]; receipt=row["l4_receipt"]
        if domain not in by_domain or row["split"] not in {"train","heldout"}: raise ValueError("source domain or split is invalid")
        if row["license_spdx"] not in LICENSES: raise ValueError("source license is not permitted")
        if not isinstance(content,str) or len(content)!=64 or content.lower()!=content: raise ValueError("source content hash is invalid")
        if content in seen: raise ValueError("duplicate source content is forbidden")
        if content in frozen: raise ValueError("source contaminates frozen eval")
        if not isinstance(receipt,dict) or receipt != {"schema_version":"ember-text-source-receipt-v1","result":"VERIFIED","source_sha256":content,"generator":"local-normalizer-v1","verifier":"local-license-provenance-v1","model_mediated":False,"borrowed_labels":False}: raise ValueError("source L4 provenance receipt is invalid")
        seen.add(content); by_domain[domain]+=1
    if any(count < 2 for count in by_domain.values()): raise ValueError("each charter domain requires two independent sources")

def build_manifest(entries: Iterable[dict[str, Any]], *, frozen_eval_hashes: set[str]) -> dict[str, Any]:
    rows=[dict(x) for x in entries]; _validate(rows,frozen_eval_hashes)
    return {"schema_version":"ember-text-lab-corpus-manifest-v1","result":"PREFLIGHT_ONLY","boundary":"NO_ACQUISITION_NO_TRAINING_NO_SUFFICIENT_PRETRAINING_CLAIM","domains":list(DOMAINS),"sources":sorted(rows,key=lambda x:(x["domain"],x["source_id"])),"frozen_eval_hashes":sorted(frozen_eval_hashes),"train_root_sha256":_root(rows,"train"),"heldout_root_sha256":_root(rows,"heldout")}

def validate_manifest(manifest: dict[str, Any], *, frozen_eval_hashes: set[str]) -> dict[str,str]:
    if not isinstance(manifest,dict) or manifest.get("schema_version")!="ember-text-lab-corpus-manifest-v1" or manifest.get("result")!="PREFLIGHT_ONLY": raise ValueError("text corpus manifest is not preflight-only")
    rows=manifest.get("sources")
    if manifest.get("domains") != list(DOMAINS) or not isinstance(rows,list) or set(manifest.get("frozen_eval_hashes",[])) != frozen_eval_hashes: raise ValueError("text corpus manifest binding is invalid")
    _validate(rows,frozen_eval_hashes)
    if manifest.get("train_root_sha256") != _root(rows,"train") or manifest.get("heldout_root_sha256") != _root(rows,"heldout"): raise ValueError("text corpus split root does not match")
    return {"result":"PREFLIGHT_ONLY","train_root_sha256":manifest["train_root_sha256"],"heldout_root_sha256":manifest["heldout_root_sha256"]}