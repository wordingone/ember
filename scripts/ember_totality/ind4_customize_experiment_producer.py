#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ind4_customize_experiment_producer.py -- C-IND, IND-4 CUSTOMIZE+EXPERIMENT
producer (DG-W2g board pass, refs C-IND legs).

Produces the two receipts test_c_ind.py's _validate_ind4() requires, both
from EXECUTED runs of real, already-existing repo machinery -- no
hand-crafted JSON:

  leg="customize" -- exercises src/ember/governance/scripts/v0_config_check.py's real check()
    function against a SANDBOX COPY of the live configs/v0-pretrain-config.json
    (the live file itself is never touched). "before" is the untouched
    sandbox copy (must be green, matching the live contract); "after" is the
    SAME copy with one real config-surface edit (governor.vram_fraction
    0.80 -> 0.95), which the checker's own governor-floor rule must catch.
    This demonstrates the CUSTOMIZE verb: a config-surface change with a
    real, machine-verified before/after delta -- not a fabricated pair.

  leg="experiment_reproduction" -- re-runs scripts/loop_econ_gate.py
    --selftest fresh (a real subprocess execution) and diffs the resulting
    receipt against a pre-existing BANKED receipt already on disk under
    receipts/, byte-for-byte except the `ts` timestamp field (the selftest's
    three fixed AC cases are deterministic by construction -- see
    loop_econ_gate.py's run_selftest()). within_tolerance=True iff every
    non-ts field matches exactly.

Run:  PYTHONIOENCODING=utf-8 python ind4_customize_experiment_producer.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent               # scripts/ember_totality
REPO_ROOT = HERE.parent.parent                        # ember worktree root
SCRIPTS_DIR = REPO_ROOT / "scripts"
RECEIPTS_OUT_DIR = REPO_ROOT / "receipts" / "ind4-customize-experiment"
SANDBOX_DIR = REPO_ROOT / "scratch" / "ind4-customize"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(REPO_ROOT))
from scripts.lib.invariant import stamp as _stamp_invariant, verify as _verify_invariant  # noqa: E402 -- gh #625 point 1

# receipt_check.py's R2 rule requires any *sha256*-named field to carry a
# disclosed sha_convention; matches exactly what scripts/lib/invariant.py's
# stamp() does (Path.read_bytes() + sha256, no normalization).
INVARIANT_SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now_ts() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _relpath(path: Path) -> str:
    """Repo-relative, forward-slash path -- never an absolute local path (this
    repo is PUBLIC; tools/repo-guard.sh fails any commit embedding one)."""
    return path.relative_to(REPO_ROOT).as_posix()


def _sanitize(text: str) -> str:
    """Strips this machine's absolute repo-root prefix from captured
    subprocess output, replacing it with a repo-relative, forward-slash form.
    Applied to every subprocess stdout/stderr blob before it is written into a
    receipt -- a receipt is public-repo content, not a local debug log."""
    root_str = str(REPO_ROOT)
    out = text.replace(root_str.replace("/", "\\"), ".").replace(root_str, ".")
    return out.replace("\\", "/")


# ---------------------------------------------------------------------------
# leg: customize
# ---------------------------------------------------------------------------

def build_customize_receipt() -> dict:
    from v0_config_check import check  # real repo module, unmodified

    live_config_path = REPO_ROOT / "configs" / "v0-pretrain-config.json"
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    sandbox_path = SANDBOX_DIR / "v0-pretrain-config-sandbox.json"
    shutil.copyfile(live_config_path, sandbox_path)  # live file never touched

    before_cfg = json.loads(sandbox_path.read_text(encoding="utf-8"))
    before_violations = check(copy.deepcopy(before_cfg))
    before_hash = _sha256(sandbox_path)

    # Real config-surface edit: loosen the governor floor (a value an
    # operator could plausibly try), which the checker's own governor-floor
    # rule (v0_config_check.py check(), GOVERNOR_FLOOR) must catch.
    after_cfg = copy.deepcopy(before_cfg)
    original_vram_fraction = after_cfg.get("governor", {}).get("vram_fraction")
    after_cfg.setdefault("governor", {})["vram_fraction"] = 0.95
    sandbox_path.write_text(json.dumps(after_cfg, indent=2), encoding="utf-8")
    after_violations = check(copy.deepcopy(after_cfg))
    after_hash = _sha256(sandbox_path)

    edit_caught = any("vram_fraction" in v for v in after_violations)

    return {
        "receipt_class": "IND-4",
        "leg": "customize",
        "producer": "ind4_customize_experiment_producer.py",
        "config_file_edited": _relpath(sandbox_path),
        "live_config_never_touched": _relpath(live_config_path),
        "edit_applied": {
            "field": "governor.vram_fraction",
            "from": original_vram_fraction,
            "to": 0.95,
        },
        "before": {
            "sha256": before_hash,
            "violations": before_violations,
            "green": before_violations == [],
        },
        "after": {
            "sha256": after_hash,
            "violations": after_violations,
            "green": after_violations == [],
        },
        "edit_caught_by_checker": edit_caught,
        "checker_module": "src/ember/governance/scripts/v0_config_check.py",
        "ts": _now_ts(),
    }


# ---------------------------------------------------------------------------
# leg: experiment_reproduction
# ---------------------------------------------------------------------------

def build_experiment_reproduction_receipt(banked_receipt_path: Path) -> dict:
    receipts_dir = REPO_ROOT / "receipts"
    pre_existing = set(receipts_dir.glob("loop-econ-gate-selftest-*.json"))

    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "loop_econ_gate.py"), "--selftest"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    stdout = _sanitize(proc.stdout or "")

    post_existing = set(receipts_dir.glob("loop-econ-gate-selftest-*.json"))
    new_files = sorted(post_existing - pre_existing)
    if len(new_files) != 1:
        return {
            "receipt_class": "IND-4",
            "leg": "experiment_reproduction",
            "producer": "ind4_customize_experiment_producer.py",
            "error": f"expected exactly 1 new receipt from selftest run, found {len(new_files)}: {new_files}",
            "selftest_exit_code": proc.returncode,
            "selftest_stdout": stdout,
            "within_tolerance": False,
            "ts": _now_ts(),
        }
    fresh_path = new_files[0]

    # gh #625: invariant_sha256 + sha_convention are now stamped by
    # loop_econ_gate.py at write time (point 1). Both are properties of the
    # repo/schema at execution time, not of the AC-case correctness this
    # comparison verifies, and the pre-existing banked receipt predates both
    # fields entirely -- excluded from the byte-for-byte comparison the same
    # way 'ts' already is.
    EXCLUDED_COMPARISON_FIELDS = {"ts", "invariant_sha256", "sha_convention"}
    banked_obj = json.loads(banked_receipt_path.read_text(encoding="utf-8"))
    fresh_obj = json.loads(fresh_path.read_text(encoding="utf-8"))
    banked_no_ts = {k: v for k, v in banked_obj.items() if k not in EXCLUDED_COMPARISON_FIELDS}
    fresh_no_ts = {k: v for k, v in fresh_obj.items() if k not in EXCLUDED_COMPARISON_FIELDS}
    within_tolerance = banked_no_ts == fresh_no_ts

    return {
        "receipt_class": "IND-4",
        "leg": "experiment_reproduction",
        "producer": "ind4_customize_experiment_producer.py",
        "banked_receipt_ref": _relpath(banked_receipt_path),
        "banked_receipt_sha256": _sha256(banked_receipt_path),
        "fresh_receipt_ref": _relpath(fresh_path),
        "fresh_receipt_sha256": _sha256(fresh_path),
        "comparison_method": "field-equality of parsed JSON excluding the 'ts', 'invariant_sha256', and 'sha_convention' fields",
        "within_tolerance": within_tolerance,
        "selftest_command": "python scripts/loop_econ_gate.py --selftest",
        "selftest_exit_code": proc.returncode,
        "selftest_stdout": stdout,
        "ts": _now_ts(),
    }


def main() -> int:
    # gh #625 point 1, fail-closed: verify BEFORE any receipt is written.
    _verify_invariant(str(REPO_ROOT))

    RECEIPTS_OUT_DIR.mkdir(parents=True, exist_ok=True)

    banked_receipt_path = REPO_ROOT / "receipts" / "loop-econ-gate-selftest-20260705T031933Z.json"
    if not banked_receipt_path.is_file():
        print(f"FAIL banked receipt not found: {banked_receipt_path}")
        return 1

    customize_receipt = build_customize_receipt()
    _stamp_invariant(customize_receipt, repo_root=str(REPO_ROOT))
    customize_receipt["sha_convention"] = INVARIANT_SHA_CONVENTION
    customize_out = RECEIPTS_OUT_DIR / f"ind4-customize-{customize_receipt['ts']}.json"
    customize_out.write_text(json.dumps(customize_receipt, indent=2), encoding="utf-8")

    exp_receipt = build_experiment_reproduction_receipt(banked_receipt_path)
    _stamp_invariant(exp_receipt, repo_root=str(REPO_ROOT))
    exp_receipt["sha_convention"] = INVARIANT_SHA_CONVENTION
    exp_out = RECEIPTS_OUT_DIR / f"ind4-experiment-reproduction-{exp_receipt['ts']}.json"
    exp_out.write_text(json.dumps(exp_receipt, indent=2), encoding="utf-8")

    print(f"customize: wrote {customize_out} (edit_caught_by_checker={customize_receipt['edit_caught_by_checker']})")
    print(f"experiment_reproduction: wrote {exp_out} (within_tolerance={exp_receipt.get('within_tolerance')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
