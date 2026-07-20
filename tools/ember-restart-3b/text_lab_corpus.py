# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""L4 manifest gate for planned, non-acquired AI-lab shared-text sources."""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from jsonschema import Draft202012Validator
from typing import Any, Iterable

DOMAINS = ("mathematics", "statistics", "physics", "computer_science", "ml_ai", "training_infrastructure", "formal_logic", "software_engineering", "data_evaluation", "scientific_method", "application_worlds")
LICENSES = {"CC0-1.0", "CC-BY-4.0", "MIT", "Apache-2.0", "BSD-3-Clause", "PDDL-1.0"}
_UNRESOLVED_EVIDENCE = ["source_descriptor", "source_content", "license_evidence", "policy", "verifier_result"]

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

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_AUTHORITY_INDEX = "data/ember-restart-3b/text-lab-authority-index-v1.json"

def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def _authority_split_root(rows: Iterable[dict[str, Any]], split: str) -> str:
    digest = hashlib.sha256(f"ember-text-lab-candidate-descriptor-v2\0{split}\0".encode("utf-8"))
    fields = ("domain", "split", "source_id", "admission", "required_evidence", "allowed_license_spdx")
    for row in sorted((item for item in rows if item.get("split") == split), key=lambda item: (item.get("domain", ""), item.get("source_id", ""))):
        descriptor = {field: row.get(field) for field in fields}
        encoded = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()

def _path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("authority path is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise ValueError("authority path is not exact repository-relative")
    path = (root / relative).resolve()
    if not path.is_file() or root.resolve() not in path.parents:
        raise ValueError("authority path is absent or escapes root")
    return path

def _bound_json(root: Path, binding: object) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "schema"}:
        raise ValueError("authority artifact binding is invalid")
    expected = binding["sha256"]
    if not isinstance(expected, str) or _HEX.fullmatch(expected) is None:
        raise ValueError("authority hash is invalid")
    payload = _path(root, binding["path"]).read_bytes()
    if _sha_bytes(payload) != expected:
        raise ValueError("authority bytes do not match the bound hash")
    value = json.loads(payload)
    if not isinstance(value, dict): raise ValueError("authority JSON must be an object")
    schema = binding["schema"]
    if not isinstance(schema, dict): raise ValueError("authority schema binding is invalid")
    schema_bytes = _path(root, schema.get("path")).read_bytes()
    if _sha_bytes(schema_bytes) != schema.get("sha256"): raise ValueError("authority schema bytes are not bound")
    schema_value=json.loads(schema_bytes)
    if schema_value.get("$schema") != "https://json-schema.org/draft/2020-12/schema": raise ValueError("authority schema is not Draft 2020-12")
    errors=sorted(Draft202012Validator(schema_value).iter_errors(value),key=str)
    if errors: raise ValueError("authority schema rejects bytes: "+errors[0].message)
    return payload,value

def _commit(root: Path) -> str:
    value=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],text=True,capture_output=True,check=False).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}",value) is None: raise ValueError("exact source commit is unavailable")
    return value

def _protected_identifier_sets(root: Path, protected: list[object]) -> dict[str, set[str]]:
    if not protected:
        raise ValueError("protected evaluation registry is empty")
    expected = {"benchmark_id", "custody_manifest_path", "custody_manifest_sha256", "custody_state", "evidence", "protected_identifiers"}
    result = {"origin_id": set(), "snapshot_sha256": set(), "chunk_sha256": set(), "content_sha256": set()}
    seen: set[str] = set()
    for entry in protected:
        if not isinstance(entry, dict) or set(entry) != expected or not isinstance(entry["benchmark_id"], str) or entry["benchmark_id"] in seen:
            raise ValueError("protected evaluation registry entry is invalid")
        seen.add(entry["benchmark_id"])
        path = _path(root, entry["custody_manifest_path"])
        payload = path.read_bytes()
        if _sha_bytes(payload) != entry["custody_manifest_sha256"]:
            raise ValueError("protected custody manifest bytes changed")
        manifest = json.loads(payload)
        evidence = entry["evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {"upstream_tree_git_sha1", "license_sha256", "answer_dictionary_sha256", "eligible_id_set_sha256", "evaluator_sha256"}:
            raise ValueError("protected custody evidence is invalid")
        split = manifest.get("split", {}) if isinstance(manifest, dict) else {}
        evaluator = manifest.get("evaluator", {}) if isinstance(manifest, dict) else {}
        observed = {
            "upstream_tree_git_sha1": manifest.get("upstream_tree_git_sha1"),
            "license_sha256": manifest.get("license_sha256"),
            "answer_dictionary_sha256": split.get("answer_dictionary_sha256") if isinstance(split, dict) else None,
            "eligible_id_set_sha256": split.get("eligible_id_set_sha256") if isinstance(split, dict) else None,
            "evaluator_sha256": evaluator.get("sha256") if isinstance(evaluator, dict) else None,
        }
        if manifest.get("benchmark_id") != entry["benchmark_id"] or observed != evidence:
            raise ValueError("protected custody evidence does not match its manifest")
        identifiers = entry["protected_identifiers"]
        if not isinstance(identifiers, list):
            raise ValueError("protected identifiers are invalid")
        for identifier in identifiers:
            if not isinstance(identifier, dict) or set(identifier) != {"kind", "value"} or identifier["kind"] not in result or not isinstance(identifier["value"], str):
                raise ValueError("protected identifier is invalid")
            result[identifier["kind"]].add(identifier["value"])
    return result

def validate_authority_index(repo_root: Path, *, index_relative: str = _AUTHORITY_INDEX) -> dict[str, Any]:
    """Validate the non-acquired, exact-byte text authority before shared-text use."""
    root=repo_root.resolve(); index_bytes=_path(root,index_relative).read_bytes(); index=json.loads(index_bytes)
    if not isinstance(index,dict) or set(index)!={"schema_version","result","boundary","registry","receipt_bundle","corpus","input_identity"}: raise ValueError("text authority index is not closed")
    if index["schema_version"]!="ember-text-lab-authority-index-v1" or index["result"]!="PREFLIGHT_ONLY": raise ValueError("text authority index is not preflight-only")
    registry_bytes,registry=_bound_json(root,index["registry"]); bundle_bytes,bundle=_bound_json(root,index["receipt_bundle"]); corpus_bytes,corpus=_bound_json(root,index["corpus"]); _,identity=_bound_json(root,index["input_identity"])
    if corpus.get("registry_sha256")!=_sha_bytes(registry_bytes) or corpus.get("receipt_bundle_sha256")!=_sha_bytes(bundle_bytes): raise ValueError("corpus does not bind external authority")
    if identity.get("corpus_sha256")!=_sha_bytes(corpus_bytes) or not isinstance(identity.get("source_base_commit"),str) or re.fullmatch(r"[0-9a-f]{40}",identity["source_base_commit"]) is None: raise ValueError("input identity does not bind exact authority")
    base_check = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", identity["source_base_commit"], "HEAD"], capture_output=True, check=False)
    if base_check.returncode != 0: raise ValueError("input identity source-base commit is not a live ancestor")
    code_files = identity.get("code_files")
    expected_code = {"text_lab_corpus": "tools/ember-restart-3b/text_lab_corpus.py", "train": "tools/ember-restart-3b/train.py", "run_vertical_slice": "tools/ember-restart-3b/run_vertical_slice.py"}
    if not isinstance(code_files, dict) or set(code_files) != set(expected_code): raise ValueError("input identity code binding is invalid")
    for name, relative in expected_code.items():
        if code_files[name] != _sha_bytes(_path(root, relative).read_bytes()): raise ValueError("input identity code bytes changed")

    rows = corpus.get("sources"); candidates = bundle.get("candidates"); protected = registry.get("protected")
    if bundle.get("result") != "UNRESOLVED_CANDIDATE":
        raise ValueError("unresolved candidate bundle result is invalid")
    if not isinstance(rows, list) or not isinstance(candidates, list) or not isinstance(protected, list):
        raise ValueError("authority payload is incomplete")
    _protected_identifier_sets(root, protected)
    expected_fields = {"source_id", "domain", "split", "admission", "required_evidence", "allowed_license_spdx"}
    candidate_map = {item.get("source_id"): item for item in candidates if isinstance(item, dict)}
    if len(candidate_map) != len(candidates):
        raise ValueError("candidate source mapping is ambiguous")
    by_domain: dict[tuple[str, str], int] = {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_fields or not isinstance(row.get("source_id"), str) or row["source_id"] in seen:
            raise ValueError("candidate descriptor is invalid or duplicated")
        if not row["source_id"].startswith("candidate-") or row.get("domain") not in DOMAINS or row.get("split") not in {"train", "heldout"}:
            raise ValueError("candidate slot, domain, or split is invalid")
        if row.get("admission") != "UNRESOLVED_CANDIDATE" or row.get("required_evidence") != _UNRESOLVED_EVIDENCE or row.get("allowed_license_spdx") != sorted(LICENSES):
            raise ValueError("candidate descriptor has unverified authority claims")
        if candidate_map.get(row["source_id"]) != row:
            raise ValueError("candidate bundle does not bind exact descriptor bytes")
        seen.add(row["source_id"])
        by_domain[(row["domain"], row["split"])] = by_domain.get((row["domain"], row["split"]), 0) + 1
    if len(rows) != 44 or {row.get("domain") for row in rows} != set(DOMAINS):
        raise ValueError("authority corpus lacks eleven-domain source matrix")
    for domain in DOMAINS:
        if by_domain.get((domain, "train")) != 2 or by_domain.get((domain, "heldout")) != 2:
            raise ValueError("domain requires two train and two heldout candidate slots")
    if corpus.get("train_root_sha256") != _authority_split_root(rows, "train") or corpus.get("heldout_root_sha256") != _authority_split_root(rows, "heldout"):
        raise ValueError("authority corpus split root does not match")

    return {
        "result": "NOT_ADMITTED_SOURCE_EVIDENCE_MISSING",
        "authority_index_sha256": _sha_bytes(index_bytes),
        "registry_sha256": _sha_bytes(registry_bytes),
        "receipt_bundle_sha256": _sha_bytes(bundle_bytes),
        "corpus_sha256": _sha_bytes(corpus_bytes),
        "input_identity_sha256": _sha_bytes(_path(root, index["input_identity"]["path"]).read_bytes()),
        "train_root_sha256": corpus["train_root_sha256"],
        "heldout_root_sha256": corpus["heldout_root_sha256"],
        "domain_count": 11,
        "train_source_count": sum(x["split"] == "train" for x in rows),
        "heldout_source_count": sum(x["split"] == "heldout" for x in rows),
        "source_base_commit": identity["source_base_commit"],
        "code_files": code_files,
    }
