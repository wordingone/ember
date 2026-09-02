# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""t2_wcode.py — W-code round-1 plain-SFT arm (contract row 9, arm A).

Trains the 3B core on its OWN verified W-code episodes (on-policy: every
ledger mbpp:* record was sampled by the core itself in w1 — the t5 harm
receipt killed off-policy expert imitation, this arm is the honest
replacement). World-filtered: the ARC seed episodes (DSL surface form,
t5-proven coding damage −4..−28pp) are EXCLUDED; whether worlds mix in one
adapter is a later-round design question (replay-mix arm, round-2 AC).

Pipeline: receipts/ledger/episodes.jsonl --filter mbpp:*--> receipts/ledger/views/wcode-r1.jsonl
(derived view, regenerated every run) -> bits-weighted dataset (frontier dict
caps, eng #5: easy 2 / mid 4 / frontier 8) -> t2_round.train_lora (same
proven QLoRA recipe + governor) -> adapters/r1w-q3[-control].

--control: matched-budget arm from control_pool mbpp:* fails (G2), counts
mirrored per-task against the arm-A dataset.

Receipt: receipts/t2-r1w-q3[-control]-<ts>.json with the no-silent-caps
frontier block. G1 eval surface after both arms: w1_mbpp --split validation
(43 heldout tasks) base vs adapter vs control; t5 harm gate on the adapter.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py

NC = "<local-path>"
RECEIPTS = f"{NC}/receipts"
VIEWS = f"{NC}/receipts/ledger/views"


def write_view(src_path, view_path, prefix="mbpp:"):
    """Filter a ledger file to one world -> derived view file. Returns recs."""
    recs = []
    with open(src_path) as f:
        for line in f:
            r = json.loads(line)
            if r["task"].startswith(prefix):
                recs.append(r)
    os.makedirs(os.path.dirname(view_path), exist_ok=True)
    with open(view_path, "w", encoding="utf-8", newline="\n") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--tag", default="r1w-q3")
    # NOTE: shifts args_fp vs pre-#70 receipts (schema fingerprint; tags pin
    # comparisons) — same acknowledged shift as eng #26's --reward.
    ap.add_argument("--license-allow", default=None,
                    help="comma list of license classes the views keep "
                         "(eng #70); default = no filter; UNKNOWN is "
                         "fail-closed (never allow-listable)")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore them

    import sys
    sys.path.insert(0, f"{NC}/scripts")
    from frontier import caps_from_records, ext_clean, load_ext_flags, \
        report_block
    from ledger_license import census as license_census, filter_records, \
        parse_allow
    from t2_round import CONTROL_POOL, LEDGER, ADAPTERS, build_dataset, \
        train_lora

    allow = parse_allow(args.license_allow) if args.license_allow else None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = args.tag + ("-control" if args.control else "")

    arm_recs = write_view(LEDGER, f"{VIEWS}/wcode-r1.jsonl")
    if not arm_recs:
        raise SystemExit("t2_wcode: no mbpp:* records in ledger — ingest first")
    # eng #11 (FPR receipt 22.1%): quarantine ext-flagged episodes AT BUILD —
    # the view is a build artifact, the ledger keeps everything. Re-write the
    # view ext-clean so build_dataset reads only clean records.
    flags = load_ext_flags([f"{RECEIPTS}/v-ext-flags-*.jsonl"])
    n_before = len(arm_recs)
    arm_recs = ext_clean(arm_recs, flags)
    ext_excluded = n_before - len(arm_recs)
    lic_block = None
    if allow:  # eng #70: license filter AT BUILD, same pattern as ext_clean —
        # the rewritten view below is the license-filtered artifact.
        pre_census = license_census(arm_recs)
        n_pre = len(arm_recs)
        arm_recs = filter_records(arm_recs, allow)
        lic_block = {"allow": sorted(allow),
                     "world_before_by_class": pre_census,
                     "world_before": n_pre, "world_after": len(arm_recs)}
    with open(f"{VIEWS}/wcode-r1.jsonl", "w", encoding="utf-8", newline="\n") as vf:
        for r in arm_recs:
            vf.write(json.dumps(r) + "\n")
    caps = caps_from_records(arm_recs)

    match_texts = None
    if args.control:
        arm_examples, verified_counts = build_dataset(
            f"{VIEWS}/wcode-r1.jsonl", cap=caps)
        ctrl_recs = write_view(CONTROL_POOL, f"{VIEWS}/wcode-r1-control.jsonl")
        if allow:  # eng #70: control view license-filtered too
            n_ctl = len(ctrl_recs)
            ctrl_recs = filter_records(ctrl_recs, allow)
            with open(f"{VIEWS}/wcode-r1-control.jsonl", "w", encoding="utf-8", newline="\n") as vf:
                for r in ctrl_recs:
                    vf.write(json.dumps(r) + "\n")
            lic_block["control_before"] = n_ctl
            lic_block["control_after"] = len(ctrl_recs)
        examples, counts = build_dataset(f"{VIEWS}/wcode-r1-control.jsonl",
                                         match_counts=verified_counts)
        # G2 matched budget = matched OPTIMIZER STEPS: mirror arm A's
        # EFFECTIVE text count (post the <200 repeat rule). Caught live
        # 2026-06-10: control 180 distinct fails hit the repeat (x5 -> 174
        # steps) while arm A's 294 did not (57 steps) — killed + fixed.
        n_a = len(arm_examples)
        match_texts = n_a if n_a >= 200 else n_a * max(5, 200 // max(n_a, 1))
    else:
        examples, counts = build_dataset(f"{VIEWS}/wcode-r1.jsonl", cap=caps)

    from receipt_fp import args_fingerprint  # eng #10
    receipt = {"ticket": "NC0-T2-WCODE", "ts": ts, "control": args.control,
               "args_fp": args_fingerprint(vars(args)),
               "model": args.model, "world": "mbpp", "round": 1,
               "ledger_records_world": n_before,
               "ext_excluded": ext_excluded,
               "ext_flag_sources": f"{RECEIPTS}/v-ext-flags-*.jsonl",
               "frontier_ext_clean": report_block(arm_recs),
               "dataset": {"n_examples": len(examples),
                           "n_tasks": len(counts)},
               "excluded": "ARC seed episodes (off-policy DSL, t5 harm "
                           "receipt 20260610T203520Z)"}
    if lic_block:  # eng #70: filter visibility — never a silent cap
        receipt["license_filter"] = lic_block
    if not examples:
        receipt["verdict"] = "EMPTY-DATASET (gate before training)"
    else:
        t0 = time.time()
        receipt["match_texts"] = match_texts
        receipt["training"] = train_lora(args.model, examples,
                                         f"{ADAPTERS}/{tag}",
                                         match_texts=match_texts)
        receipt["training"]["secs"] = round(time.time() - t0, 1)
        receipt["adapter"] = f"{ADAPTERS}/{tag}"

    os.makedirs(RECEIPTS, exist_ok=True)
    checked_write(f"{RECEIPTS}/t2-{tag}-{ts}.json", receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k != "frontier"},
                     indent=2, default=str))
    print("T2_WCODE_DONE")


if __name__ == "__main__":
    main()
