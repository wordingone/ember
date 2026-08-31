#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_cobs_capture.py -- C-OBS cockpit proof-pack capture harness (gh issue #10).

Runs the REAL observatory proof-pack -- tools/ember-cli/src/core/ember-world-state-repl.ts --
in a visible ConPTY (never headless, per operator rule), scripts a MONITOR/UNDERSTAND/INTERACT/
evidence/act/confirm/decline session against it, and assembles a receipt proving the C-OBS triad:

  (a) real GOAL/ledger/receipts -> EmberWorldState adapter binding (no hand-maintained mirror --
      the REPL calls buildEmberWorldState() fresh at boot and snapshots the result to disk).
  (b) click-to-evidence: `evidence <surface> <n>` resolves a rendered claim to its real source
      path + sha256.
  (c) confirm-only encounter membrane: `act` only OFFERS; only the exact `confirm <id>` executes;
      a decline and a bogus confirm are BOTH exercised live to prove the no-silent-steer path.
  (d) user-runnable observatory proof-pack: the exact command sequence below is the proof-pack --
      an operator can run `node core/ember-world-state-repl.ts` himself and type the same lines.

Adapted from the proven surface-2 / IND-1 ConPTY-drive pattern (this tree's own
ember_surface2_capture.py, read in full before this harness was written): node-pty resolved via
EMBER_PTY_MODULE (env-only, no default baked in), a short neutral scratch root (ConPTY transcripts
wrap long paths across render columns, defeating substring redaction), and the SAME reused driver
(scripts/ember_surface2_pty_driver.cjs -- not copied, invoked directly) since it is already generic
(spawns any exe/args pair, records raw+chunks+driver-receipt).

Read-only w.r.t. training/GPU: this harness never touches a training process, never imports torch,
never opens the GPU. It reads the goalforge contract tree's docs/domains/governance/authority/GOAL.md / docs/domains/governance/ledgers/ember-debt-ledger.md /
newest totality-board receipt (via the adapter it drives), and writes only under this tree's
scratch/ and receipts/, plus an import-edition copy into the goalforge tree's receipts/ (the only
tree test_c_obs.py's evidence scan inspects).

Usage: python ember_cobs_capture.py [--dry-run]

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix over the staged original -- EXEC_ROOT and GOALFORGE_ROOT's
default both carried an absolute drive-letter-rooted literal, which tripped the
repo's leak-gate on the path shape and was non-functional off the export machine
either way. EXEC_ROOT now computes from __file__ (functionally identical: this
file's grandparent directory is the repo root); GOALFORGE_ROOT's default now
computes as EXEC_ROOT's sibling "ember-goalforge" (same on-disk convention the
original hardcoded, still overridable via EMBER_GOALFORGE_ROOT). No other lines
changed. See receipts/ember-c-scale/land210f-*.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EXEC_ROOT = str(Path(__file__).resolve().parent.parent)
GOALFORGE_ROOT = os.environ.get(
    "EMBER_GOALFORGE_ROOT", os.path.join(os.path.dirname(EXEC_ROOT), "ember-goalforge")
)

CORE_DIR = os.path.join(EXEC_ROOT, "tools", "ember-cli", "src", "core")
REPL_SCRIPT = os.path.join(CORE_DIR, "ember-world-state-repl.ts")
ADAPTER_SCRIPT = os.path.join(CORE_DIR, "ember-world-state.ts")
MEMBRANE_SCRIPT = os.path.join(CORE_DIR, "encounter-membrane.ts")
COMMAND_SCRIPT = os.path.join(EXEC_ROOT, "tools", "ember-cli", "src", "commands", "world-state.ts")

PTY_DRIVER = os.path.join(EXEC_ROOT, "scripts", "ember_surface2_pty_driver.cjs")
THIS_SCRIPT = os.path.abspath(__file__)

NODE_EXE = os.environ.get("EMBER_NODE_EXE", "C:/nvm4w/nodejs/node.exe")

EXEC_RECEIPTS_DIR = os.path.join(EXEC_ROOT, "receipts", "ember-cockpit-c-obs")
GOALFORGE_RECEIPTS_DIR = os.path.join(GOALFORGE_ROOT, "receipts", "ember-cockpit-c-obs")

# Short, neutral default (mirrors ember_surface2_capture.py's SCRATCH_ROOT discipline): ConPTY
# transcripts wrap long paths across render columns, defeating substring redaction, so a short
# working root means the transcript never contains anything identifying to redact.
SCRATCH_ROOT = os.environ.get("EMBER_COBS_SCRATCH", os.path.join(EXEC_ROOT, "scratch", "cobs"))
# node-pty resolution is env-only (no default path baked into the tree, matching surface2).
NODE_PTY_MODULE = os.environ.get("EMBER_PTY_MODULE", "")

TICKET = "EMBER-ISSUE-10-C-OBS-COCKPIT"


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha1_hex(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def dash_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H-%M-%S") + "Z"


def compact_ts(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S") + "Z"


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07", "", s)


def _redact(value):
    """Replace the session scratch root and any session-identifying token with a neutral
    placeholder in anything written into a receipt. Paths stay real on disk; only the
    receipt's persisted copies are redacted (mirrors ember_surface2_capture.py's _redact)."""
    if isinstance(value, str):
        out = value.replace(SCRATCH_ROOT, "<scratchpad>").replace(
            SCRATCH_ROOT.replace("\\", "/"), "<scratchpad>"
        )
        out = re.sub(r"B--M-[A-Za-z0-9-]+", "<session>", out)
        out = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<session>", out
        )
        return out
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="skip the PTY capture, just prep dirs and check preconditions")
    args = ap.parse_args()

    for required in (REPL_SCRIPT, ADAPTER_SCRIPT, MEMBRANE_SCRIPT, PTY_DRIVER):
        if not os.path.isfile(required):
            print(f"GAP: {required} not found -- aborting.")
            return 1
    if not os.path.isfile(NODE_EXE):
        print(f"GAP: node executable not found at {NODE_EXE} (set EMBER_NODE_EXE) -- aborting.")
        return 1

    os.makedirs(SCRATCH_ROOT, exist_ok=True)
    cwd_dir = os.path.join(SCRATCH_ROOT, "cwd")
    outdir = os.path.join(SCRATCH_ROOT, "driver-out")
    state_dir = os.path.join(cwd_dir, "state")
    os.makedirs(cwd_dir, exist_ok=True)
    os.makedirs(outdir, exist_ok=True)
    # appendFile/writeFile do not create missing parent dirs -- pre-create (found empirically by
    # the surface2 precedent for its control channel; same class of gap here).
    os.makedirs(state_dir, exist_ok=True)

    snapshot_path = os.path.join(state_dir, "world-state-snapshot.json")
    encounter_log_path = os.path.join(state_dir, "encounters.jsonl")

    if args.dry_run:
        print("[cobs-capture] --dry-run: preconditions OK, skipping PTY capture")
        return 0

    cr = "\r"
    ctrl_c = "\x03"
    scenario = {
        "exe": NODE_EXE,
        "args": [REPL_SCRIPT],
        "env": {
            "EMBER_GOALFORGE_ROOT": GOALFORGE_ROOT,
            "EMBER_COBS_WORLDSTATE_SNAPSHOT": snapshot_path,
            "EMBER_COBS_ENCOUNTER_LOG": encounter_log_path,
        },
        "outdir": outdir,
        "cwd": cwd_dir,
        "name": "cobs-cockpit-capture",
        "cols": 120,
        "rows": 40,
        "deadline_ms": 17000,
        "steps": [
            {"at_ms": 2500, "input": "monitor"},
            {"at_ms": 2900, "input": cr},
            {"at_ms": 4200, "input": "understand"},
            {"at_ms": 4600, "input": cr},
            {"at_ms": 5900, "input": "interact"},
            {"at_ms": 6300, "input": cr},
            {"at_ms": 7400, "input": "evidence monitor 0"},
            {"at_ms": 7800, "input": cr},
            {"at_ms": 8600, "input": "evidence understand 0"},
            {"at_ms": 9000, "input": cr},
            {"at_ms": 9800, "input": "act interact 0"},
            {"at_ms": 10200, "input": cr},
            {"at_ms": 11000, "input": "decline off-1"},
            {"at_ms": 11400, "input": cr},
            {"at_ms": 12200, "input": "act interact 0"},
            {"at_ms": 12600, "input": cr},
            {"at_ms": 13400, "input": "confirm off-2"},
            {"at_ms": 13800, "input": cr},
            {"at_ms": 14600, "input": "confirm off-999"},
            {"at_ms": 15000, "input": cr},
            {"at_ms": 15600, "input": "quit"},
            {"at_ms": 16000, "input": cr},
            {"at_ms": 16400, "input": ctrl_c},
        ],
    }
    scenario_path = os.path.join(SCRATCH_ROOT, "scenario.json")
    with open(scenario_path, "w", encoding="utf-8") as fh:
        json.dump(scenario, fh, indent=1)

    print(
        "[cobs-capture] side effect: opening a visible ConPTY window running "
        "node core/ember-world-state-repl.ts for ~17s (no GPU, no training process touched) -- "
        "will close cleanly"
    )
    env = dict(os.environ)
    if not NODE_PTY_MODULE:
        raise SystemExit("EMBER_PTY_MODULE env var is required (no default baked in)")
    env["EMBER_PTY_MODULE"] = NODE_PTY_MODULE

    start_ts = datetime.now(timezone.utc)
    proc = subprocess.run(
        ["node", PTY_DRIVER, scenario_path],
        cwd=SCRATCH_ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    print("[cobs-capture] driver stdout:", proc.stdout.strip())
    if proc.returncode != 0:
        print("[cobs-capture] driver stderr:", proc.stderr.strip())
        print(f"GAP: pty driver exited {proc.returncode}, aborting capture")
        return 1

    driver_receipt_path = os.path.join(outdir, scenario["name"] + ".driver-receipt.json")
    with open(driver_receipt_path, "r", encoding="utf-8") as fh:
        driver_result = json.load(fh)

    raw_path = os.path.join(outdir, scenario["name"] + ".raw")
    with open(raw_path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    transcript_clean = strip_ansi(raw)

    if not os.path.isfile(snapshot_path):
        print(f"GAP: world-state snapshot not written at {snapshot_path} -- adapter did not run")
        return 1
    with open(snapshot_path, "r", encoding="utf-8") as fh:
        world_state = json.load(fh)

    encounters = []
    if os.path.isfile(encounter_log_path):
        with open(encounter_log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    encounters.append(json.loads(line))
                except Exception:
                    pass

    # --- render-verified evidence (grep the REAL transcript, never assumed) -------------------
    render_checks = {
        "monitor_rendered": "MONITOR: board ts=" in transcript_clean,
        "understand_rendered": 'UNDERSTAND: goal="' in transcript_clean,
        "interact_rendered": "INTERACT: drive/inspect cycles" in transcript_clean,
        "click_to_evidence_rendered": "EVIDENCE PATH:" in transcript_clean,
        "offer_off1_rendered": "OFFER off-1 action=" in transcript_clean,
        "declined_off1_rendered": "DECLINED off-1" in transcript_clean,
        "confirmed_off1_absent": "CONFIRMED off-1" not in transcript_clean,
        "offer_off2_rendered": "OFFER off-2 action=" in transcript_clean,
        "confirmed_off2_rendered": "CONFIRMED off-2 action=" in transcript_clean,
        "rejected_bogus_confirm_rendered": "REJECTED off-999" in transcript_clean,
    }
    all_checks_pass = all(render_checks.values())

    encounter_kinds = [(e.get("kind"), e.get("decision")) for e in encounters]
    encounter_checks = {
        "offer_off1_logged": ("offer", None) in [(k, None) for k, d in encounter_kinds if k == "offer"] and any(
            e.get("offerId") == "off-1" and e.get("kind") == "offer" for e in encounters
        ),
        "declined_off1_logged": any(
            e.get("offerId") == "off-1" and e.get("decision") == "declined" for e in encounters
        ),
        "confirmed_off2_logged": any(
            e.get("offerId") == "off-2" and e.get("decision") == "confirmed" for e in encounters
        ),
        "rejected_off999_logged": any(
            e.get("offerId") == "off-999" and e.get("decision") == "rejected" for e in encounters
        ),
    }
    all_encounter_checks_pass = all(encounter_checks.values())

    verdict = "PASS" if (all_checks_pass and all_encounter_checks_pass) else "FAIL"

    end_ts = datetime.now(timezone.utc)
    total_secs = (end_ts - start_ts).total_seconds()
    ts_compact = compact_ts(end_ts)

    args_fingerprint_src = json.dumps({"scenario": "cobs-cockpit-capture", "dry_run": False}, sort_keys=True)

    receipt = {
        # --- unified schema v4 required envelope (docs/spec/receipts-v1.md sec2) --------------
        "ticket": TICKET,
        "ts": ts_compact,
        "kind": "job",
        "verdict": verdict,
        "generator": {
            "path": "scripts/ember_cobs_capture.py",
            "sha256": sha256_of(THIS_SCRIPT),
        },
        "execution": {
            "pid": driver_result.get("pid"),
            "host": socket.gethostname(),
            "start_ts": start_ts.isoformat().replace("+00:00", "Z"),
            "total_secs": round(total_secs, 3),
            "model_load_secs": None,
            "overhead_secs": None,
            "overhead_pct": None,
        },
        "inputs_sha": {"args_fingerprint": sha1_hex(args_fingerprint_src)[:16]},
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",

        # C(-1) clear-packet declaration (docs/spec is test_c_neg1.py's own top-level field
        # names): this receipt renders a top-level "verdict", making it a decisive-claim receipt
        # under that condition's definition, so it must declare its own spend truthfully rather
        # than land undeclared. True and checkable: this capture harness never calls a paid API,
        # hosted model, or metered cloud surface -- it reads local goalforge markdown/JSON files
        # and drives a local `node` subprocess in a local ConPTY window. Zero increment.
        "api_spend_usd": 0,
        "paid_api_surface_used": False,

        # --- C-OBS triad (gh issue #10) -------------------------------------------------------
        "surface": "C-OBS",
        "receipt_class": "Cockpit (job/proof-pack) -- gh issue #10 triad",
        "provenance": "live_cockpit_proofpack_run",

        "adapter_binding": {
            "summary": (
                "Real GOAL/ledger/receipts -> EmberWorldState adapter binding: "
                "tools/ember-cli/src/core/ember-world-state.ts's buildEmberWorldState() reads the "
                "goalforge contract tree's docs/domains/governance/authority/GOAL.md, docs/domains/governance/ledgers/ember-debt-ledger.md, and the newest "
                "scripts/ember_totality/receipts-totality board receipt fresh on every call -- no "
                "hand-maintained mirror -- and returns a typed EmberWorldState object (monitor / "
                "understand / interact claims, each carrying an EvidenceRef back to its real "
                "source file and sha256)."
            ),
            "sources": world_state.get("sources"),
            "world_state_snapshot": {
                "path": "state/world-state-snapshot.json",
                "sha256": sha256_of(snapshot_path),
                "monitor_board_ts": world_state.get("monitor", {}).get("boardTs"),
                "monitor_condition_count": len(world_state.get("monitor", {}).get("conditions", [])),
                "understand_topology_count": len(world_state.get("understand", {}).get("topology", [])),
                "interact_ledger_row_count": len(world_state.get("interact", {}).get("ledgerRows", [])),
            },
            "adapter_source_sha256": {
                "tools/ember-cli/src/core/ember-world-state.ts": sha256_of(ADAPTER_SCRIPT),
                "tools/ember-cli/src/core/encounter-membrane.ts": sha256_of(MEMBRANE_SCRIPT),
                "tools/ember-cli/src/core/ember-world-state-repl.ts": sha256_of(REPL_SCRIPT),
                "tools/ember-cli/src/commands/world-state.ts": sha256_of(COMMAND_SCRIPT),
            },
        },

        "click_to_evidence": {
            "summary": (
                "click-to-evidence surface: every rendered MONITOR/UNDERSTAND/INTERACT claim "
                "resolves to its real receipt path on interaction, via `evidence <surface> <n>`."
            ),
            "rendered": render_checks["click_to_evidence_rendered"],
        },

        "confirm_only_membrane": {
            "summary": (
                "confirm-only encounter membrane: no silent-steer path -- every action the "
                "cockpit offers requires the exact confirm token, matched to the exact "
                "outstanding offer, before it executes; declining, a wrong offer id, or any "
                "other input never auto-acts."
            ),
            "encounters": encounters,
            "no_silent_steer_proof": {
                "declined_offer_never_executed": (
                    "off-1 was offered then DECLINED; the transcript shows OFFER off-1 and "
                    "DECLINED off-1 but never CONFIRMED off-1 -- the declined action never ran."
                ),
                "bogus_confirm_rejected": (
                    "confirm off-999 was attempted with no outstanding off-999 offer; the "
                    "membrane returned REJECTED off-999 and logged decision=rejected -- no "
                    "action taken."
                ),
                "checks": {**render_checks, **encounter_checks},
            },
        },

        "user_runnable_proof_pack": {
            "summary": (
                "user-runnable observatory proof-pack: MONITOR, UNDERSTAND, and INTERACT, run by "
                "the operator himself via `node tools/ember-cli/src/core/ember-world-state-repl.ts`"
                ", in a visible ConPTY (never headless), emitting live state read fresh from the "
                "goalforge tree at boot."
            ),
            "how_to_run_yourself": (
                "cd tools/ember-cli/src && node core/ember-world-state-repl.ts   "
                "then type: monitor / understand / interact / evidence <surface> <n> / "
                "act <surface> <n> / confirm <id> / decline <id> / quit"
            ),
            "transcript_path": "terminal-transcript-clean.txt",
        },

        "future_rebuild_gap": {
            "detail": (
                "A registered /cockpit slash command (tools/ember-cli/src/commands/world-state.ts,"
                " aliases /world /cobs) wires this same adapter+membrane into command-registry.ts's"
                " getBuiltinCommands() for the compiled cockpit binary, but reaching the currently"
                " compiled ember-cured.exe requires `bun build ... --compile --outfile ember.exe`,"
                " which this session's rails withhold (no binary rebuild). Today's proof-pack runs"
                " the identical core modules directly via node, needing no rebuild -- the"
                " alternative path gh issue #10's refined triad explicitly allows."
            ),
            "requires_rebuild": True,
            "command_registry_diff_files": [
                "tools/ember-cli/src/command-registry.ts",
                "tools/ember-cli/src/commands/world-state.ts",
            ],
        },

        "render_evidence": render_checks,
        "encounter_checks": encounter_checks,

        "render_path": {
            "binary": None,
            "cockpit_process": "node core/ember-world-state-repl.ts (standalone proof-pack, not the compiled ember-cured.exe)",
            "cockpit": "visible ConPTY (useConpty:true), never headless",
            "driver": "scripts/ember_surface2_pty_driver.cjs (reused unmodified; generic exe/args spawn+capture, proven by the surface-2/IND-1 precedent)",
        },

        "live_process_touched": False,
        "gpu_used": False,
        "driver_result": driver_result,
    }

    receipt_dirname = ts_compact
    exec_receipt_dir = os.path.join(EXEC_RECEIPTS_DIR, receipt_dirname)
    os.makedirs(exec_receipt_dir, exist_ok=True)

    receipt_path = os.path.join(exec_receipt_dir, "receipt.json")
    with open(receipt_path, "w", encoding="utf-8") as fh:
        json.dump(_redact(receipt), fh, indent=1)
    print(f"[cobs-capture] wrote execution-tree receipt: {receipt_path}")

    transcript_path = os.path.join(exec_receipt_dir, "terminal-transcript-clean.txt")
    with open(transcript_path, "w", encoding="utf-8") as fh:
        fh.write(_redact(transcript_clean))
    print(f"[cobs-capture] wrote transcript: {transcript_path}")

    snapshot_copy_path = os.path.join(exec_receipt_dir, "world-state-snapshot.json")
    shutil.copyfile(snapshot_path, snapshot_copy_path)

    encounters_copy_path = os.path.join(exec_receipt_dir, "encounters.jsonl")
    if os.path.isfile(encounter_log_path):
        shutil.copyfile(encounter_log_path, encounters_copy_path)

    # --- import-edition copy into the goalforge tree's evidence surface ----------------------
    # This is the ONLY tree test_c_obs.py's _iter_evidence_files() inspects (receipts/, ledger/,
    # baseline/ directly under the goalforge repo root) -- the execution-tree copy above is the
    # source-of-truth run; this is what makes the probe able to see it.
    import_dirname = f"{ts_compact}-import-edition"
    goalforge_receipt_dir = os.path.join(GOALFORGE_RECEIPTS_DIR, import_dirname)
    os.makedirs(goalforge_receipt_dir, exist_ok=True)
    for fname in ("receipt.json", "terminal-transcript-clean.txt", "world-state-snapshot.json", "encounters.jsonl"):
        src = os.path.join(exec_receipt_dir, fname)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(goalforge_receipt_dir, fname))
    print(f"[cobs-capture] wrote import-edition receipt into goalforge tree: {goalforge_receipt_dir}")

    print(json.dumps({
        "verdict": verdict,
        "exec_receipt_dir": exec_receipt_dir,
        "goalforge_receipt_dir": goalforge_receipt_dir,
        "render_evidence": render_checks,
        "encounter_checks": encounter_checks,
    }, indent=1))

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
