#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze suite readiness before central OWNED_ADMITTED receipt admission."""
from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path
FAMILIES={"text","reasoning","mathematics","coding","sql","browser_ui","terminal","image","audio","structured_tools","efficiency","retention","deletion_ablation"}
HEX40=re.compile(r"^[0-9a-f]{40}$");HEX64=re.compile(r"^[0-9a-f]{64}$")
def validate(value:dict)->list[str]:
 errors=[];target=value.get("target")
 if not isinstance(target,dict) or target.get("kind")!="owned_checkpoint":errors.append("TARGET_NOT_OWNED_CHECKPOINT")
 elif not HEX64.fullmatch(str(target.get("checkpoint_sha256",""))) or not target.get("lineage_manifest"):errors.append("TARGET_BINDING")
 comparators=value.get("comparators",[])
 if not isinstance(comparators,list):errors.append("COMPARATORS_NOT_LIST")
 else:
  for comparator in comparators:
   if not isinstance(comparator,dict):errors.append("COMPARATOR_OBJECT");continue
   if comparator.get("role")!="comparison_only":errors.append("COMPARATOR_ROLE")
   if not HEX40.fullmatch(str(comparator.get("revision",""))):errors.append("COMPARATOR_REVISION")
 suites=value.get("suites",[])
 if not isinstance(suites,list):errors.append("SUITES_NOT_LIST");suites=[]
 present=[suite.get("family") for suite in suites if isinstance(suite,dict)]
 missing=sorted(FAMILIES-set(present))
 if missing:errors.append("MISSING_FAMILIES: "+", ".join(missing))
 duplicates=sorted({family for family in present if present.count(family)>1})
 if duplicates:errors.append("DUPLICATE_FAMILIES: "+", ".join(duplicates))
 for suite in suites:
  if not isinstance(suite,dict):errors.append("SUITE_OBJECT");continue
  pins=(("dataset_revision",HEX40),("split_sha256",HEX64),("harness_commit",HEX40),("prompt_protocol_sha256",HEX64),("scoring_protocol_sha256",HEX64))
  if any(not pattern.fullmatch(str(suite.get(field,""))) for field,pattern in pins):errors.append("SUITE_PIN: "+str(suite.get("family","unknown")))
 execution=value.get("execution")
 if not isinstance(execution,dict) or execution.get("runner")!="disk_budget_runner.py" or not execution.get("receipt_namespace"):errors.append("EXECUTION_RECEIPT_CONTRACT")
 return errors
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--manifest",required=True,type=Path);a=p.parse_args()
 try:value=json.loads(a.manifest.read_text(encoding="utf-8"))
 except(OSError,json.JSONDecodeError)as exc:print("MANIFEST_READ: "+str(exc),file=sys.stderr);return 2
 errors=validate(value)
 if errors:print("\n".join(errors),file=sys.stderr);return 2
 print("EMBER_RESTART_EVAL_CONTRACT: VALID");return 0
if __name__=="__main__":raise SystemExit(main())
