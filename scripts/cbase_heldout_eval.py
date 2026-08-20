# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed heldout NLL evaluator for timeshare/cbase checkpoints (#760).

verify_slice_excludes_ruled_sources() consumes scripts/fineweb_exclusion.py
(#1436) to prove the frozen slice touches no byte owned by a RULED-excluded
source (fineweb_edu today) before any window is scored -- never re-derives
exclusion offsets or overlap arithmetic itself."""
from __future__ import annotations
import hashlib, json, math, re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
import numpy as np

class HeldoutEvalRefusal(ValueError):
    """The requested evaluation cannot be proved from the supplied bytes."""

def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def _json(path: Path) -> dict:
    try: value=json.loads(path.read_text(encoding="utf-8",errors="strict"))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise HeldoutEvalRefusal(f"JSON_UNREADABLE: {path.name}: {exc}") from exc
    if not isinstance(value,dict): raise HeldoutEvalRefusal(f"JSON_NOT_OBJECT: {path.name}")
    return value

def _storage_id(tensor):
    storage=tensor.untyped_storage()
    return (str(tensor.device),str(tensor.dtype),int(storage.data_ptr()),int(storage.nbytes()))

def _key_ending(state: Mapping[str,Any], suffix: str) -> str:
    keys=[key for key in state if key==suffix or key.endswith("."+suffix)]
    if len(keys)!=1: raise HeldoutEvalRefusal(f"CHECKPOINT_IDENTITY_KEY_AMBIGUOUS: suffix={suffix!r} matches={keys!r}")
    return keys[0]

def derive_checkpoint_identity(model_state: Mapping[str,Any]) -> dict:
    import torch
    tensors={key:value for key,value in model_state.items() if torch.is_tensor(value)}
    if not tensors: raise HeldoutEvalRefusal("CHECKPOINT_IDENTITY_EMPTY")
    embed_key=_key_ending(tensors,"backbone_model.embed_tokens.weight")
    head_key=_key_ending(tensors,"head.weight")
    gate_key=_key_ending(tensors,"backbone_model.layers.0.mlp.gate_proj.weight")
    embed=tensors[embed_key]; head=tensors[head_key]; gate=tensors[gate_key]
    if embed.ndim!=2 or head.ndim!=2 or gate.ndim!=2: raise HeldoutEvalRefusal("CHECKPOINT_IDENTITY_SHAPE_INVALID")
    state_count=sum(int(t.numel()) for t in tensors.values())
    seen={}; unique=0
    for tensor in tensors.values():
        ident=_storage_id(tensor)
        if ident not in seen:
            seen[ident]=True; unique += int(tensor.untyped_storage().nbytes()//tensor.element_size())
    layers=set()
    for key in tensors:
        match=re.search(r"(?:^|\.)backbone_model\.layers\.(\d+)\.",key)
        if match: layers.add(int(match.group(1)))
    if not layers or layers != set(range(max(layers)+1)): raise HeldoutEvalRefusal("CHECKPOINT_IDENTITY_LAYER_SET_INVALID")
    return {"unique_parameter_count":unique,"state_dict_parameter_count":state_count,"duplicate_parameter_count":state_count-unique,"vocab_size":int(embed.shape[0]),"hidden_size":int(embed.shape[1]),"feed_forward_width":int(gate.shape[0]),"layer_count":len(layers),"primary_head_tied":_storage_id(embed)==_storage_id(head)}

def verify_checkpoint_files(checkpoint_dir: str|Path, expected_pins: Mapping[str,str]|None=None) -> dict:
    root=Path(checkpoint_dir); manifest_path=root/"manifest.json"
    if not root.is_dir() or not manifest_path.is_file(): raise HeldoutEvalRefusal("CHECKPOINT_MANIFEST_MISSING")
    manifest=_json(manifest_path); files=manifest.get("files")
    if not isinstance(files,dict) or not files: raise HeldoutEvalRefusal("CHECKPOINT_FILE_MAP_INVALID")
    measured={}
    for name,expected in files.items():
        if not isinstance(name,str) or Path(name).name!=name or not re.fullmatch(r"[0-9a-f]{64}",str(expected)): raise HeldoutEvalRefusal("CHECKPOINT_FILE_MAP_INVALID")
        path=root/name
        if not path.is_file(): raise HeldoutEvalRefusal(f"CHECKPOINT_FILE_MISSING: {name}")
        measured[name]=_sha256(path)
        if measured[name]!=expected: raise HeldoutEvalRefusal(f"CHECKPOINT_SHA_MISMATCH: {name} expected={expected} actual={measured[name]}")
    manifest_sha=_sha256(manifest_path)
    if expected_pins is not None:
        for name,expected in expected_pins.items():
            actual=manifest_sha if name=="manifest.json" else measured.get(name)
            if actual!=expected: raise HeldoutEvalRefusal(f"CHECKPOINT_CUSTODY_PIN_MISMATCH: {name} expected={expected} actual={actual}")
    return {"manifest_step":manifest.get("step"),"files_sha256":measured,"manifest_sha256":manifest_sha,"manifest":manifest}

def _integer(row: Mapping[str,Any],name: str) -> int:
    value=row.get(name)
    if isinstance(value,bool) or not isinstance(value,int) or value<0: raise HeldoutEvalRefusal(f"SLICE_INTEGER_INVALID: {name}")
    return value

def _closed_keys(row: Mapping[str,Any], required: set[str], optional: set[str], code: str) -> None:
    keys=set(row)
    if not required.issubset(keys) or not keys.issubset(required|optional):
        raise HeldoutEvalRefusal(f"{code}: missing={sorted(required-keys)} extra={sorted(keys-required-optional)}")

def _digest(value: Any, *, length: int, code: str) -> str:
    if not isinstance(value,str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}",value): raise HeldoutEvalRefusal(code)
    return value

def _relative_receipt_path(value: Any, code: str) -> str:
    if not isinstance(value,str) or not value or "\\" in value or Path(value).is_absolute() or ".." in Path(value).parts: raise HeldoutEvalRefusal(code)
    return value

def load_frozen_slice_manifest(path: str|Path, expected_sha256: str) -> dict:
    path=Path(path); actual=_sha256(path)
    if actual!=expected_sha256: raise HeldoutEvalRefusal(f"MANIFEST_SHA_MISMATCH: expected={expected_sha256} actual={actual}")
    value=_json(path)
    _closed_keys(value,{"schema","issue","captured_public_master","source_corpus","selection_evidence","sequence","training_consumption","windows","expected_scored_token_count","scale","availability","claim_boundary"},set(),"SLICE_SCHEMA_INVALID")
    if value.get("schema")!="cbase-heldout-slice/v1" or value.get("issue")!="#760" or not isinstance(value.get("scale"),str) or not value["scale"] or not isinstance(value.get("claim_boundary"),str) or not value["claim_boundary"]: raise HeldoutEvalRefusal("SLICE_SCHEMA_INVALID")
    _digest(value.get("captured_public_master"),length=40,code="SLICE_PUBLIC_MASTER_INVALID")
    sequence=value.get("sequence"); source=value.get("source_corpus"); selection=value.get("selection_evidence"); windows=value.get("windows"); training=value.get("training_consumption"); availability=value.get("availability")
    if not all(isinstance(row,dict) for row in (sequence,source,selection,availability)) or not isinstance(windows,list) or not windows or not isinstance(training,list): raise HeldoutEvalRefusal("SLICE_SCHEMA_INVALID")
    _closed_keys(source,{"combined_sha256","receipt_path","receipt_sha256","shards"},set(),"SLICE_SOURCE_INVALID"); _digest(source.get("combined_sha256"),length=64,code="SLICE_SOURCE_DIGEST_INVALID"); _digest(source.get("receipt_sha256"),length=64,code="SLICE_SOURCE_DIGEST_INVALID"); _relative_receipt_path(source.get("receipt_path"),"SLICE_SOURCE_PATH_INVALID")
    _closed_keys(selection,{"path","sha256","batch_sha256","verdict"},set(),"SLICE_SELECTION_INVALID"); _relative_receipt_path(selection.get("path"),"SLICE_SELECTION_PATH_INVALID"); _digest(selection.get("sha256"),length=64,code="SLICE_SELECTION_DIGEST_INVALID"); _digest(selection.get("batch_sha256"),length=64,code="SLICE_SELECTION_DIGEST_INVALID")
    if selection.get("verdict") not in {"CLEAN","RULE_DERIVED_EXCLUSION_CLEAN"}: raise HeldoutEvalRefusal("SLICE_SELECTION_VERDICT_INVALID")
    _closed_keys(sequence,{"dtype","seq","n_mtp","separator_id","packed_bytes_per_token","scoring"},set(),"SLICE_SEQUENCE_INVALID")
    if sequence.get("dtype")!="<u2" or sequence.get("scoring")!="primary_next_token_only" or isinstance(sequence.get("packed_bytes_per_token"),bool) or not isinstance(sequence.get("packed_bytes_per_token"),(int,float)) or not math.isfinite(float(sequence["packed_bytes_per_token"])) or float(sequence["packed_bytes_per_token"])<=0: raise HeldoutEvalRefusal("SLICE_SEQUENCE_INVALID")
    seq=_integer(sequence,"seq"); _integer(sequence,"n_mtp"); _integer(sequence,"separator_id")
    if seq<1: raise HeldoutEvalRefusal("SLICE_SEQUENCE_INVALID")
    _closed_keys(availability,{"status","missing","note"},set(),"SLICE_AVAILABILITY_INVALID")
    if availability.get("status") not in {"AVAILABLE","UNMEASURABLE_MISSING_SHARD_BYTES"} or not isinstance(availability.get("missing"),list) or not all(isinstance(x,str) and Path(x).name==x for x in availability["missing"]) or not isinstance(availability.get("note"),str): raise HeldoutEvalRefusal("SLICE_AVAILABILITY_INVALID")
    shards=source.get("shards")
    if not isinstance(shards,list) or not shards: raise HeldoutEvalRefusal("SLICE_SOURCE_SHARDS_INVALID")
    shard_map={}
    for shard in shards:
        if not isinstance(shard,dict): raise HeldoutEvalRefusal("SLICE_SOURCE_SHARD_INVALID")
        _closed_keys(shard,{"name","sha256","n_tokens"},{"global_token_start","global_token_end_exclusive"},"SLICE_SOURCE_SHARD_INVALID")
        if not isinstance(shard.get("name"),str) or Path(shard["name"]).name!=shard["name"]: raise HeldoutEvalRefusal("SLICE_SOURCE_SHARD_INVALID")
        _digest(shard.get("sha256"),length=64,code="SLICE_SOURCE_SHARD_INVALID")
        if _integer(shard,"n_tokens")<1: raise HeldoutEvalRefusal("SLICE_SOURCE_SHARD_INVALID")
        if {"global_token_start","global_token_end_exclusive"}.issubset(shard) and _integer(shard,"global_token_end_exclusive")-_integer(shard,"global_token_start")!=shard["n_tokens"]: raise HeldoutEvalRefusal("SLICE_SOURCE_SHARD_INVALID")
        if shard["name"] in shard_map: raise HeldoutEvalRefusal("SLICE_SOURCE_SHARD_DUPLICATE")
        shard_map[shard["name"]]=shard
    training_ranges=[]
    for row in training:
        if not isinstance(row,dict): raise HeldoutEvalRefusal("TRAINING_RANGE_INVALID")
        _closed_keys(row,{"source","global_token_start","global_token_end_exclusive"},{"window_start","window_end_exclusive"},"SLICE_TRAINING_RANGE_INVALID")
        if not isinstance(row.get("source"),str) or not row["source"]: raise HeldoutEvalRefusal("SLICE_TRAINING_RANGE_INVALID")
        start=_integer(row,"global_token_start"); end=_integer(row,"global_token_end_exclusive")
        if end<=start: raise HeldoutEvalRefusal("SLICE_TRAINING_RANGE_INVALID")
        training_ranges.append((start,end))
    seen=set()
    for row in windows:
        if not isinstance(row,dict): raise HeldoutEvalRefusal("SLICE_WINDOW_INVALID")
        _closed_keys(row,{"window_index","shard_name","shard_token_start","shard_token_end_exclusive","global_token_start","global_token_end_exclusive"},{"source_shard_token_end_exclusive","source_global_token_end_exclusive"},"SLICE_WINDOW_INVALID")
        index=_integer(row,"window_index"); shard_name=row.get("shard_name")
        if index in seen or shard_name not in shard_map: raise HeldoutEvalRefusal("SLICE_WINDOW_INVALID")
        seen.add(index)
        ss=_integer(row,"shard_token_start"); se=_integer(row,"shard_token_end_exclusive"); gs=_integer(row,"global_token_start"); ge=_integer(row,"global_token_end_exclusive")
        if se-ss != seq+1 or ge-gs != seq+1: raise HeldoutEvalRefusal(f"TRUNCATED_SLICE: window={index} expected={seq+1} shard_len={se-ss} global_len={ge-gs}")
        if se>shard_map[shard_name]["n_tokens"]: raise HeldoutEvalRefusal("SLICE_WINDOW_OUT_OF_RANGE")
        for ts,te in training_ranges:
            if gs<te and ts<ge: raise HeldoutEvalRefusal(f"TRAINING_OVERLAP: eval=[{gs},{ge}) train=[{ts},{te})")
    expected=_integer(value,"expected_scored_token_count")
    if expected != len(windows)*seq: raise HeldoutEvalRefusal(f"TRUNCATED_SLICE: expected_scored_token_count={expected} derived={len(windows)*seq}")
    return value

def verify_rule_derived_selection(manifest: Mapping[str,Any], *, shard_dir: str|Path,
                                  nc: str|Path|None=None) -> None:
    """Re-derive the exact rule-owned window set; legacy n-gram CLEAN is unchanged."""
    selection=manifest["selection_evidence"]
    if selection["verdict"]=="CLEAN": return
    if selection["verdict"]!="RULE_DERIVED_EXCLUSION_CLEAN": raise HeldoutEvalRefusal("RULE_FREEZE_VERDICT_INVALID")
    root=Path(nc) if nc is not None else Path(__file__).resolve().parents[1]
    receipt_path=root/selection["path"]
    if not receipt_path.is_file() or _sha256(receipt_path)!=selection["sha256"] or selection["batch_sha256"]!=selection["sha256"]:
        raise HeldoutEvalRefusal("RULE_FREEZE_RECEIPT_IDENTITY_INVALID")
    receipt=_json(receipt_path)
    required={"ticket","issue","ts","schema","status","selection_rule_id","selection_rule",
              "exclusion_set","source_receipts","sequence","training_ranges","windows",
              "previous_refusal","producer","invariant_sha256","sha_convention","authority","claim_boundary"}
    _closed_keys(receipt,required,set(),"RULE_FREEZE_RECEIPT_SCHEMA_INVALID")
    if (receipt.get("ticket")!="ISSUE-1433-RULE-DERIVED-HELDOUT-FREEZE"
            or receipt.get("schema")!="cbase-heldout-rule-freeze/v1"
            or receipt.get("status")!="RULE_DERIVED_EXCLUSION_CLEAN"
            or receipt.get("selection_rule_id")!="EARLIEST_ADMISSIBLE_AFTER_EXCLUSION_FRONTIER_V1"):
        raise HeldoutEvalRefusal("RULE_FREEZE_RECEIPT_SCHEMA_INVALID")
    exclusion=receipt.get("exclusion_set")
    _closed_keys(exclusion,{"path","sha256","ranges_sha256","excluded_token_ranges"},set(),"RULE_FREEZE_EXCLUSION_INVALID")
    exclusion_path=root/_relative_receipt_path(exclusion.get("path"),"RULE_FREEZE_EXCLUSION_INVALID")
    _digest(exclusion.get("sha256"),length=64,code="RULE_FREEZE_EXCLUSION_INVALID")
    _digest(exclusion.get("ranges_sha256"),length=64,code="RULE_FREEZE_EXCLUSION_INVALID")
    try:
        import regenerate_cbase_heldout_slice as freezer
    except ImportError:
        import sys
        here=str(Path(__file__).resolve().parent)
        if here not in sys.path: sys.path.insert(0,here)
        import regenerate_cbase_heldout_slice as freezer
    try:
        exclusion_doc=freezer._load_exclusion_set(exclusion_path,exclusion["sha256"],shard_dir=Path(shard_dir))
        if exclusion_doc["excluded_token_ranges"]!=exclusion["excluded_token_ranges"]:
            raise HeldoutEvalRefusal("RULE_FREEZE_EXCLUSION_RANGE_MISMATCH")
        range_sha=hashlib.sha256(json.dumps(exclusion["excluded_token_ranges"],sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if range_sha!=exclusion["ranges_sha256"]: raise HeldoutEvalRefusal("RULE_FREEZE_EXCLUSION_RANGE_MISMATCH")
        shard_receipt=_json(root/manifest["source_corpus"]["receipt_path"])
        training=[tuple(row) for row in receipt["training_ranges"]]
        expected=freezer.select_earliest_admissible_windows(
            shard_receipt, excluded_ranges=[tuple(row) for row in exclusion["excluded_token_ranges"]],
            training_ranges=training, seq=int(receipt["sequence"]["seq"]),
            n_mtp=int(receipt["sequence"]["n_mtp"]), count=16)
    except (OSError,ValueError,SystemExit,KeyError,TypeError) as exc:
        if isinstance(exc,HeldoutEvalRefusal): raise
        raise HeldoutEvalRefusal(f"RULE_FREEZE_REDERIVATION_FAILED: {exc}") from exc
    if receipt["windows"]!=expected or manifest["windows"]!=expected:
        raise HeldoutEvalRefusal("RULE_FREEZE_EARLIEST_WINDOW_MISMATCH")

def _fineweb_exclusion_module():
    """Import scripts/fineweb_exclusion.py (#1436) as a sibling module.
    Explicit sys.path insertion mirrors that module's own pattern for
    importing token_shards_v0 -- defensive against pytest invocation
    contexts that don't already have scripts/ on sys.path."""
    import sys
    here=str(Path(__file__).resolve().parent)
    if here not in sys.path: sys.path.insert(0,here)
    try:
        import fineweb_exclusion
    except ImportError as exc:
        raise HeldoutEvalRefusal(f"FINEWEB_EXCLUSION_MODULE_UNAVAILABLE: {exc}") from exc
    return fineweb_exclusion

def verify_slice_excludes_ruled_sources(manifest: Mapping[str,Any], *, shard_dir: str|Path, nc: str|Path|None=None) -> list[tuple[int,int]]:
    """Fail-closed: prove no window in `manifest` touches a byte owned by a
    RULED-excluded source (fineweb_edu today; any future DROP-ruled source
    automatically -- fineweb_exclusion.ruled_excluded_sources reads the
    ruling receipt itself, not a hardcoded set, so a later exclusion is
    enforced here with no code change).

    This is a SEPARATE cross-check from load_frozen_slice_manifest's pure
    schema/self-consistency validation, deliberately: load_frozen_slice_manifest
    is exercised by hermetic tests against synthetic manifests whose
    source_corpus.receipt_path names no real on-disk receipt, and baking a
    real-corpus lookup into it would break every one of those tests. This
    function instead requires the caller to supply a real shard_dir and is
    invoked only from the CLI's production path, against production receipts
    -- #760 build spec: "your harness must not re-implement exclusion;
    consume the same module" (scripts/fineweb_exclusion.py, #1436).

    Checks each window's FULL read span -- global_token_start through
    source_global_token_end_exclusive when present (the seq+1+n_mtp bytes
    the loader actually reads off disk for MTP lookahead), falling back to
    global_token_end_exclusive otherwise -- against the excluded ranges, via
    fineweb_exclusion's own overlap primitive (never re-derived here: a
    degenerate empty-range special case already had to be discovered once,
    documented in that module's _overlaps docstring).

    Returns the excluded ranges that were checked (for receipting). Raises
    HeldoutEvalRefusal("SLICE_OVERLAPS_EXCLUDED_SOURCE: ...") on any overlap,
    or HeldoutEvalRefusal("EXCLUSION_DERIVATION_FAILED: ...") if the shard
    receipt the manifest itself declares (source_corpus.receipt_path) is not
    on disk or fails byte-true validation -- an undecidable exclusion is a
    refusal, never a silent pass. A validated receipt whose corpus simply
    carries no ruled-excluded source (e.g. a hermetic test fixture) is NOT
    a refusal -- enforcement_for_validated_receipt returns an empty range
    with a stated reason, mirroring fineweb_exclusion's own loader-default
    policy so this check and the loader can never disagree about what
    "nothing to exclude" means."""
    fx=_fineweb_exclusion_module()
    root=Path(nc) if nc is not None else Path(__file__).resolve().parents[1]
    receipt_name=Path(manifest["source_corpus"]["receipt_path"]).name
    receipt_path=root/"receipts"/receipt_name
    if not receipt_path.is_file(): raise HeldoutEvalRefusal(f"EXCLUSION_DERIVATION_FAILED: shard receipt not on disk: {receipt_path}")
    receipt=_json(receipt_path)
    violations=fx.validate_shards_receipt(receipt,str(root),shard_dir_override=str(shard_dir))
    if violations: raise HeldoutEvalRefusal(f"EXCLUSION_DERIVATION_FAILED: {receipt_name} FAILS validation against on-disk shard bytes: {violations}")
    # assembly_name comes from the shard receipt's OWN pinned premise, not
    # fineweb_exclusion's default constant -- a receipt already declares which
    # assembly it was built against (resolve_excluded_ranges_for_stream does
    # the same lookup for the same reason).
    assembly_name=((receipt.get("premises") or {}).get("assembly_receipt") or {}).get("name")
    if not assembly_name: raise HeldoutEvalRefusal(f"EXCLUSION_DERIVATION_FAILED: {receipt_name} has no premises.assembly_receipt.name")
    try:
        ranges,_reason=fx.enforcement_for_validated_receipt(receipt,nc=str(root),assembly_name=assembly_name)
    except ValueError as exc:
        raise HeldoutEvalRefusal(f"EXCLUSION_DERIVATION_FAILED: {exc}") from exc
    for row in manifest["windows"]:
        gs=int(row["global_token_start"]); ge=int(row.get("source_global_token_end_exclusive",row["global_token_end_exclusive"]))
        for es,ee in ranges:
            if fx._overlaps(gs,ge,es,ee): raise HeldoutEvalRefusal(f"SLICE_OVERLAPS_EXCLUDED_SOURCE: window={row['window_index']} eval=[{gs},{ge}) excluded=[{es},{ee})")
    return ranges

def read_eval_windows(shard_dir: str|Path, manifest: Mapping[str,Any]) -> list[dict]:
    root=Path(shard_dir); sequence=manifest["sequence"]; seq=int(sequence["seq"]); separator=int(sequence["separator_id"])
    source={row["name"]:row for row in manifest["source_corpus"]["shards"]}; used={row["shard_name"] for row in manifest["windows"]}
    arrays={}
    for name in sorted(used):
        path=root/name
        if not path.is_file(): raise HeldoutEvalRefusal(f"SHARD_MISSING: {name}")
        actual=_sha256(path)
        if actual!=source[name]["sha256"]: raise HeldoutEvalRefusal(f"SHARD_SHA_MISMATCH: {name} expected={source[name]['sha256']} actual={actual}")
        if path.stat().st_size != int(source[name]["n_tokens"])*2: raise HeldoutEvalRefusal(f"SHARD_SIZE_MISMATCH: {name}")
        arrays[name]=np.memmap(path,mode="r",dtype="<u2")
    output=[]
    for row in manifest["windows"]:
        name=row["shard_name"]; start=int(row["shard_token_start"]); end=int(row["shard_token_end_exclusive"]); full=np.asarray(arrays[name][start:end],dtype=np.int64)
        if len(full)!=seq+1: raise HeldoutEvalRefusal(f"TRUNCATED_SLICE: window={row['window_index']}")
        doc_index=int(np.count_nonzero(arrays[name][:start]==separator)); docs=[]
        for token in full[:-1]:
            if int(token)==separator: doc_index+=1
            docs.append(f"{name}:document-{doc_index}")
        output.append({"shard_name":name,"window_index":row["window_index"],"input_ids":full[:-1].tolist(),"target_ids":full[1:].tolist(),"document_ids":docs})
    if sum(len(row["target_ids"]) for row in output)!=manifest["expected_scored_token_count"]: raise HeldoutEvalRefusal("TRUNCATED_SLICE: scored token count mismatch")
    return output

def _vector_sha(values: Sequence[float]) -> str:
    payload=json.dumps([float(v) for v in values],separators=(",",":"),allow_nan=False).encode("ascii")
    return hashlib.sha256(payload).hexdigest()

def _loss_pass(model,windows,device):
    import torch
    import torch.nn.functional as F
    batch_means=[]; tokens=[]; docs=[]; shards=[]
    model.eval()
    with torch.no_grad():
        for row in windows:
            x=torch.as_tensor([row["input_ids"]],dtype=torch.long,device=device); y=torch.as_tensor([row["target_ids"]],dtype=torch.long,device=device); logits=model(x)
            losses=F.cross_entropy(logits.to(torch.float32).reshape(-1,logits.shape[-1]),y.reshape(-1),reduction="none")
            values=[float(v) for v in losses.detach().cpu().tolist()]
            if len(values)!=len(row["target_ids"]) or not all(math.isfinite(v) for v in values): raise HeldoutEvalRefusal("NONFINITE_LOSS")
            batch_means.append(float(sum(values)/len(values))); tokens.extend(values); docs.extend(row["document_ids"]); shards.extend([row["shard_name"]]*len(values))
    return batch_means,tokens,docs,shards

def evaluate_teacher_forced(model, windows: Sequence[Mapping[str,Any]], *, device: str, dtype: str, seed: int, packed_bytes_per_token: float, bootstrap_samples: int=2000) -> dict:
    if dtype not in {"float32","bfloat16"} or not windows or packed_bytes_per_token<=0 or bootstrap_samples<2: raise HeldoutEvalRefusal("EVALUATION_ARGUMENT_INVALID")
    first=_loss_pass(model,windows,device); second=_loss_pass(model,windows,device); h1=_vector_sha(first[0]); h2=_vector_sha(second[0])
    if h1!=h2 or first[1]!=second[1]: raise HeldoutEvalRefusal("DETERMINISM_MISMATCH")
    means=defaultdict(list); per_shard=defaultdict(set)
    for loss,doc,shard in zip(first[1],first[2],first[3]): means[doc].append(loss); per_shard[shard].add(doc)
    doc_means=np.asarray([sum(means[key])/len(means[key]) for key in sorted(means)],dtype=np.float64)
    if not len(doc_means): raise HeldoutEvalRefusal("DOCUMENT_SET_EMPTY")
    rng=np.random.default_rng(seed); draws=np.asarray([float(rng.choice(doc_means,size=len(doc_means),replace=True).mean()) for _ in range(bootstrap_samples)])
    low,high=[float(v) for v in np.quantile(draws,[0.025,0.975])]; mean=float(sum(first[1])/len(first[1]))
    return {"seed":seed,"dtype":dtype,"device":device,"batch_count":len(windows),"token_count":len(first[1]),"document_count":len(doc_means),"per_shard_document_counts":{k:len(v) for k,v in sorted(per_shard.items())},"mean_nll":mean,"bits_per_packed_byte":mean/math.log(2.0)/packed_bytes_per_token,"packed_bytes_per_token":packed_bytes_per_token,"bootstrap_samples":bootstrap_samples,"bootstrap_ci95":{"low":low,"high":high,"half_width":(high-low)/2.0,"unit":"document_mean_nll"},"per_batch_loss_vector_sha256":h1,"repeat_run_hashes":[h1,h2],"repeat_run_match":True}

def build_receipt(*,checkpoint: Mapping[str,Any],checkpoint_identity: Mapping[str,Any],slice_manifest_sha256: str,slice_manifest: Mapping[str,Any],evaluation: Mapping[str,Any],excluded_source_ranges: Sequence[tuple[int,int]]=()) -> dict:
    return {"schema":"cbase-heldout-eval/v1","issue":"#760","issue_refs":["#760","#1433"],"ts":datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),"scale":slice_manifest["scale"],"checkpoint":dict(checkpoint),"checkpoint_identity":dict(checkpoint_identity),"slice_manifest_sha256":slice_manifest_sha256,"evaluation":dict(evaluation),"excluded_source_ranges_verified":[list(r) for r in excluded_source_ranges],"api_spend_usd":0.0,"paid_api_surface_used":False,"claim_boundary":"heldout NLL/BPB measurement only; no capability, same-quality, or milestone-completion claim","markers":["HELDOUT_EVAL_DETERMINISM_PASS","HELDOUT_EVAL_NEGATIVE_FIXTURES_PASS","HELDOUT_SLICE_DISJOINT_PASS"]}

FROZEN_SLICE_PATH = Path(__file__).resolve().parents[1] / "manifests" / "cbase-heldout-slice-v1.json"
FROZEN_SLICE_SHA256 = "32052288e761d8a01375bec40bc04785fcd46d75db58b325b73090f23dd74c14"
CHECKPOINT_PINS = {
    "step25": {"model.pt":"3fa4ca09db7d749cb68e470ff07cd66d53706512e212a8482124a8872d55deac","optimizer.pt":"d52f5969887725551574a01c920342dff491a0f95cdff97ba4fe3511d83a70b0","rng.pt":"c9ca61ab0e5fb9661e54dc9bb2df294f3828390829c997330f9290a02aabc379","manifest.json":"3bd76c858576a3a0ac48bd2eecf3d33702116874529be640e627d4558f45d138"},
    "step50": {"model.pt":"8055a9f4b67711b8f1103dcf76228c5f303ba6d6170af17243b17b7c5289ea54","optimizer.pt":"324b988f73b8741bc3b04c4a18bf0823ec271d56ecc1c6608b269121524da250","rng.pt":"c9ca61ab0e5fb9661e54dc9bb2df294f3828390829c997330f9290a02aabc379","manifest.json":"af828fd6388c7d0c00ec688bf291f474b0158c308a022f3d19fffc58b6b68504"},
}
V5_CHECKPOINT_KIND = "v5"
V5_MINIMUM_GLOBAL_STEP = 100

HISTORICAL_EVAL_MODEL_CONTRACT = {"public_master":"db571b310b0ad20f8b257760cdc7c7ee69714929","w1_model_source_blob":"3dc627d49c5e48ceb8ab0c028eab68acb74e4f61","timeshare_source_blob":"ea367b382b975afd7afecbe86b6efa1148bd76ad","attention_heads":16,"max_sequence_length":1024}

def _build_read_only_eval_model(identity: Mapping[str,Any], mtp_count: int, device: str, seed: int):
    import torch
    from transformers import LlamaConfig, LlamaModel
    heads=HISTORICAL_EVAL_MODEL_CONTRACT["attention_heads"]
    if identity["hidden_size"] % heads: raise HeldoutEvalRefusal("ATTENTION_HEAD_PARTITION_INVALID")
    torch.manual_seed(seed)
    config=LlamaConfig(vocab_size=identity["vocab_size"],hidden_size=identity["hidden_size"],intermediate_size=identity["feed_forward_width"],num_hidden_layers=identity["layer_count"],num_attention_heads=heads,num_key_value_heads=heads,max_position_embeddings=HISTORICAL_EVAL_MODEL_CONTRACT["max_sequence_length"],tie_word_embeddings=False)
    class ReadOnlyHistoricalW1(torch.nn.Module):
        def __init__(self):
            super().__init__(); self.backbone_model=LlamaModel(config); self.head=torch.nn.Linear(identity["hidden_size"],identity["vocab_size"],bias=False); self.head.weight=self.backbone_model.embed_tokens.weight; self.mtp_heads=torch.nn.ModuleList([torch.nn.Linear(identity["hidden_size"],identity["vocab_size"],bias=False) for _ in range(mtp_count)])
        def forward(self,ids): return self.head(self.backbone_model(input_ids=ids).last_hidden_state)
    return ReadOnlyHistoricalW1().to(device).to(torch.bfloat16)

def _v5_scorer_module():
    """Reuse #1723's reviewed v5 byte verifier/model constructor verbatim."""
    import sys
    here=str(Path(__file__).resolve().parent)
    if here not in sys.path: sys.path.insert(0,here)
    try:
        import legb_live_candidate_v5_scorer
    except ImportError as exc:
        raise HeldoutEvalRefusal(f"V5_LOADER_UNAVAILABLE: {exc}") from exc
    return legb_live_candidate_v5_scorer

def verify_v5_checkpoint_for_heldout(checkpoint_dir: str|Path) -> dict:
    """Byte-verify a v5 checkpoint without constructing/scoring the model.

    A structural checkpoint such as seed-830013 may exercise this adapter
    seam, but only a WARM-100 checkpoint may pass ``load_v5_live_model`` and
    enter the NLL scorer.
    """
    module=_v5_scorer_module()
    try:
        return module.load_verified_v5_checkpoint(str(checkpoint_dir))
    except module.LiveCandidateRefusal as exc:
        raise HeldoutEvalRefusal(str(exc)) from exc

def _v5_digest(value: Any, code: str) -> str:
    if not isinstance(value,str) or not re.fullmatch(r"[0-9a-f]{64}",value):
        raise HeldoutEvalRefusal(code)
    return value

def load_v5_live_model(checkpoint_dir: str|Path, *, route: str|None, device: str,
                       max_position_embeddings: int):
    """Load the reviewed v5 model only for the genuine WARM-100 subject."""
    import os
    if not isinstance(route,str) or not route:
        raise HeldoutEvalRefusal("CHECKPOINT_ROUTE_REQUIRED")
    if isinstance(max_position_embeddings,bool) or not isinstance(max_position_embeddings,int) or max_position_embeddings<1:
        raise HeldoutEvalRefusal("MAX_POSITION_EMBEDDINGS_INVALID")
    if device.startswith("cuda") and os.environ.get("EMBER_GATE_AUTHORIZED")!="1":
        raise HeldoutEvalRefusal("CUDA_LEASE_NOT_AUTHORIZED")
    module=_v5_scorer_module()
    try:
        verified=module.load_verified_v5_checkpoint(str(checkpoint_dir))
    except module.LiveCandidateRefusal as exc:
        raise HeldoutEvalRefusal(str(exc)) from exc
    preflight_step=verified.get("global_step"); preflight_tokens=verified.get("tokens_seen")
    if isinstance(preflight_step,bool) or not isinstance(preflight_step,int) or preflight_step<V5_MINIMUM_GLOBAL_STEP:
        raise HeldoutEvalRefusal(
            f"WARM100_CHECKPOINT_REQUIRED: global_step={preflight_step!r} minimum={V5_MINIMUM_GLOBAL_STEP}")
    if isinstance(preflight_tokens,bool) or not isinstance(preflight_tokens,int) or preflight_tokens<1:
        raise HeldoutEvalRefusal("CHECKPOINT_TOKEN_CURSOR_INVALID")
    if (verified.get("manifest") or {}).get("active_expert_ids") != [route]:
        raise HeldoutEvalRefusal("CHECKPOINT_ROUTE_MISMATCH")
    try:
        scorer,binding=module.build_live_candidate_scorer(
            checkpoint_dir=str(checkpoint_dir),route=route,device=device,
            max_position_embeddings=max_position_embeddings)
    except module.LiveCandidateRefusal as exc:
        raise HeldoutEvalRefusal(str(exc)) from exc
    if not isinstance(binding,dict):
        raise HeldoutEvalRefusal("CHECKPOINT_V5_BINDING_INVALID")
    checkpoint=binding.get("checkpoint"); config=binding.get("model_config"); route_binding=binding.get("route")
    if not all(isinstance(row,dict) for row in (checkpoint,config,route_binding)):
        raise HeldoutEvalRefusal("CHECKPOINT_V5_BINDING_INVALID")
    if checkpoint.get("schema_version")!="ember-sparse-checkpoint-v5":
        raise HeldoutEvalRefusal("CHECKPOINT_SCHEMA_UNSUPPORTED")
    if (checkpoint.get("manifest_sha256")!=verified.get("manifest_sha256")
            or checkpoint.get("measured_shard_sha256")!=verified.get("measured_shard_sha256")):
        raise HeldoutEvalRefusal("CHECKPOINT_CHANGED_DURING_MODEL_LOAD")
    step=checkpoint.get("global_step"); tokens_seen=checkpoint.get("tokens_seen")
    if isinstance(step,bool) or not isinstance(step,int) or step<V5_MINIMUM_GLOBAL_STEP:
        raise HeldoutEvalRefusal(
            f"WARM100_CHECKPOINT_REQUIRED: global_step={step!r} minimum={V5_MINIMUM_GLOBAL_STEP}")
    if isinstance(tokens_seen,bool) or not isinstance(tokens_seen,int) or tokens_seen<1:
        raise HeldoutEvalRefusal("CHECKPOINT_TOKEN_CURSOR_INVALID")
    if (route_binding.get("selected")!=route
            or route_binding.get("manifest_declared_active_expert_ids")!=[route]
            or route_binding.get("selected_matches_manifest_declared") is not True):
        raise HeldoutEvalRefusal("CHECKPOINT_ROUTE_MISMATCH")
    if binding.get("tied_embeddings_reasserted") is not True:
        raise HeldoutEvalRefusal("PRIMARY_HEAD_NOT_TIED")
    measured=checkpoint.get("measured_shard_sha256")
    required=set(module.MODEL_SHARDS)
    if (not isinstance(measured,dict) or not required.issubset(measured)
            or any(not isinstance(name,str) or Path(name).name!=name
                   or not re.fullmatch(r"[0-9a-f]{64}",str(digest))
                   for name,digest in measured.items())):
        raise HeldoutEvalRefusal("CHECKPOINT_MODEL_SHARD_MAP_INVALID")
    _v5_digest(checkpoint.get("manifest_sha256"),"CHECKPOINT_MANIFEST_SHA_INVALID")
    _v5_digest(config.get("sha256"),"CHECKPOINT_MODEL_CONFIG_SHA_INVALID")
    dimensions=(config.get("hidden_size"),config.get("layers"),
                config.get("attention_heads"),config.get("vocab_size"))
    if any(isinstance(value,bool) or not isinstance(value,int) or value<1 for value in dimensions):
        raise HeldoutEvalRefusal("CHECKPOINT_MODEL_CONFIG_INVALID")
    tokenizer=binding.get("tokenizer")
    if (not isinstance(tokenizer,dict) or not isinstance(tokenizer.get("path"),str)
            or not tokenizer["path"] or not re.fullmatch(r"[0-9a-f]{64}",str(tokenizer.get("sha256")))):
        raise HeldoutEvalRefusal("CHECKPOINT_TOKENIZER_BINDING_INVALID")
    if (binding.get("requested_device")!=device
            or not isinstance(binding.get("realized_device"),str) or not binding["realized_device"]
            or not isinstance(binding.get("realized_dtype"),str) or not binding["realized_dtype"]
            or binding.get("max_position_embeddings")!=max_position_embeddings):
        raise HeldoutEvalRefusal("CHECKPOINT_RUNTIME_BINDING_INVALID")
    model=getattr(scorer,"model",None)
    if model is None:
        raise HeldoutEvalRefusal("CHECKPOINT_MODEL_UNAVAILABLE")
    loader_path=Path(module.__file__).resolve()
    receipt_checkpoint={
        **checkpoint,
        "model_config":dict(config),
        "route":dict(route_binding),
        "tokenizer":dict(tokenizer),
        "runtime":{
            "requested_device":binding["requested_device"],
            "realized_device":binding["realized_device"],
            "realized_dtype":binding["realized_dtype"],
            "max_position_embeddings":binding["max_position_embeddings"],
        },
        "v5_loader_source":{
            "path":"scripts/legb_live_candidate_v5_scorer.py",
            "sha256":_sha256(loader_path),
        },
    }
    identity={
        "architecture_revision":checkpoint.get("architecture_revision"),
        "contract_version":checkpoint.get("contract_version"),
        "hidden_size":config["hidden_size"],
        "layer_count":config["layers"],
        "attention_head_count":config["attention_heads"],
        "vocab_size":config["vocab_size"],
        "primary_head_tied":True,
        "selected_expert_route":route,
    }
    return model,identity,receipt_checkpoint

def load_live_model(checkpoint_dir: str|Path, checkpoint_kind: str, device: str, seed: int,
                    *, route: str|None=None, max_position_embeddings: int=1024):
    import os, torch
    if checkpoint_kind==V5_CHECKPOINT_KIND:
        return load_v5_live_model(checkpoint_dir,route=route,device=device,
                                  max_position_embeddings=max_position_embeddings)
    if checkpoint_kind not in CHECKPOINT_PINS: raise HeldoutEvalRefusal("CHECKPOINT_KIND_INVALID")
    if route is not None: raise HeldoutEvalRefusal("CHECKPOINT_ROUTE_NOT_APPLICABLE")
    if device.startswith("cuda") and os.environ.get("EMBER_GATE_AUTHORIZED")!="1": raise HeldoutEvalRefusal("CUDA_LEASE_NOT_AUTHORIZED")
    verified=verify_checkpoint_files(checkpoint_dir,CHECKPOINT_PINS[checkpoint_kind]); state=torch.load(Path(checkpoint_dir)/"model.pt",map_location="cpu",weights_only=True); identity=derive_checkpoint_identity(state)
    if not identity["primary_head_tied"]: raise HeldoutEvalRefusal("PRIMARY_HEAD_NOT_TIED")
    mtp={int(m.group(1)) for key in state for m in [re.search(r"(?:^|\.)mtp_heads\.(\d+)\.weight$",key)] if m}
    if mtp and mtp!=set(range(max(mtp)+1)): raise HeldoutEvalRefusal("MTP_HEAD_SET_INVALID")
    model=_build_read_only_eval_model(identity,len(mtp),device,seed); own=model.state_dict(); checkpoint_keys=set(state); own_keys=set(own); shape_mismatches={key:{"checkpoint":list(state[key].shape),"model":list(own[key].shape)} for key in sorted(checkpoint_keys&own_keys) if tuple(state[key].shape)!=tuple(own[key].shape)}
    if checkpoint_keys!=own_keys or shape_mismatches: raise HeldoutEvalRefusal(f"CHECKPOINT_MODEL_PARITY_MISMATCH: missing={sorted(checkpoint_keys-own_keys)} unexpected={sorted(own_keys-checkpoint_keys)} shapes={shape_mismatches}")
    model.load_state_dict(state,strict=True); identity["attention_head_count"]={"value":HISTORICAL_EVAL_MODEL_CONTRACT["attention_heads"],"source":"exact historical evaluator contract; tensor shapes cannot independently derive attention-head partition"}; identity["mtp_head_count"]=len(mtp); identity["historical_eval_model_contract"]=dict(HISTORICAL_EVAL_MODEL_CONTRACT)
    return model,identity,verified

def _write_receipt(path: Path, value: Mapping[str,Any]):
    path.parent.mkdir(parents=True,exist_ok=True); payload=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n"; path.write_text(payload,encoding="utf-8",newline="\n"); return _sha256(path)

def main(argv=None) -> int:
    import argparse, sys
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--validate-only",action="store_true"); parser.add_argument("--evaluate",action="store_true"); parser.add_argument("--slice-manifest",default=str(FROZEN_SLICE_PATH)); parser.add_argument("--expected-slice-sha256",default=FROZEN_SLICE_SHA256); parser.add_argument("--shard-dir",required=True); parser.add_argument("--nc",default=None,help="repo root for the fineweb-exclusion receipt lookup (default: this script's own checkout); override lets hermetic fixtures point at a self-contained receipts/ tree instead of the real repo's"); parser.add_argument("--checkpoint-dir"); parser.add_argument("--checkpoint-kind",choices=sorted((*CHECKPOINT_PINS,V5_CHECKPOINT_KIND))); parser.add_argument("--route",default=None,help="required expert route for v5 checkpoints; forbidden for historical checkpoints"); parser.add_argument("--max-position-embeddings",type=int,default=1024); parser.add_argument("--device",default="cpu"); parser.add_argument("--seed",type=int,default=83); parser.add_argument("--bootstrap-samples",type=int,default=2000); parser.add_argument("--out")
    args=parser.parse_args(argv)
    try:
        manifest=load_frozen_slice_manifest(args.slice_manifest,args.expected_slice_sha256); verify_rule_derived_selection(manifest,shard_dir=args.shard_dir,nc=args.nc); windows=read_eval_windows(args.shard_dir,manifest)
        excluded_ranges=verify_slice_excludes_ruled_sources(manifest,shard_dir=args.shard_dir,nc=args.nc)
        print("HELDOUT_SLICE_DISJOINT_PASS")
        if args.validate_only and not args.evaluate: return 0
        if args.evaluate and manifest["selection_evidence"]["verdict"]!="CLEAN":
            raise HeldoutEvalRefusal("RULE_DERIVED_VERDICT_NOT_SCORABLE: run and bind the real exact-window n-gram phase before evaluation")
        if not args.evaluate or not args.checkpoint_dir or not args.checkpoint_kind or not args.out: raise HeldoutEvalRefusal("EVALUATION_ARGUMENTS_MISSING")
        model,identity,checkpoint=load_live_model(args.checkpoint_dir,args.checkpoint_kind,args.device,args.seed,route=args.route,max_position_embeddings=args.max_position_embeddings); evaluation=evaluate_teacher_forced(model,windows,device=args.device,dtype="bfloat16",seed=args.seed,packed_bytes_per_token=float(manifest["sequence"]["packed_bytes_per_token"]),bootstrap_samples=args.bootstrap_samples); receipt=build_receipt(checkpoint=checkpoint,checkpoint_identity=identity,slice_manifest_sha256=args.expected_slice_sha256,slice_manifest=manifest,evaluation=evaluation,excluded_source_ranges=excluded_ranges); receipt["receipt_sha256"]=_write_receipt(Path(args.out),receipt); print("HELDOUT_EVAL_DETERMINISM_PASS"); print(json.dumps({"out":args.out,"mean_nll":evaluation["mean_nll"],"bits_per_packed_byte":evaluation["bits_per_packed_byte"],"scale":receipt["scale"]},sort_keys=True)); return 0
    except HeldoutEvalRefusal as exc:
        print(f"CBASE_HELDOUT_EVAL_REFUSED: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
