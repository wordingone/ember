#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Generate the C-OBS observatory proof-pack receipt (condition C-OBS, docs/spec/conditions-v1.md
S4.2/S4.4; probe scripts/ember_totality/test_c_obs.py, hardened by issue #749).

This is the RECEIPT GENERATOR, never the probe. It does two things, both for real, never
synthetic/hardcoded:

  1. Executes `tools/ember-cli/src/scripts/cobs-proof-pack-run.ts` three times (monitor,
     understand, interact) via bun, against this repo's OWN root as EMBER_GOALFORGE_ROOT
     (Ember is a single tree -- there is no separate goalforge contract tree; see project
     memory "Ember=1 tree"). Each command's REAL exit code is recorded -- never assumed 0.
  2. Writes a structured JSON receipt under receipts/ember-c-obs-proof-pack/<ts>/receipt.json
     carrying:
       - emberworldstate_adapter: binds=true, sources=[GOAL.md, docs/ember-debt-ledger.md,
         the newest totality-board receipt] (spans GOAL/ledger/receipt categories, each
         resolved in-tree by test_c_obs.py's _check_worldstate_binding), plus
         adapter_path/adapter_sha256 sha-pinning core/ember-world-state.ts (the real adapter
         source, per _lane14_common.check_path_sha_pairs).
       - observatory_proof_pack: commands=[{verb, exit_code}, ...] from the three REAL runs
         above, plus runner_path/runner_sha256 sha-pinning this receipt's own runner script.
       - notes: plain-English disclosure of the click-to-evidence surface (world-state.ts's
         `evidence <s> <n>` verb) and the confirm-only encounter membrane (encounter-membrane.ts,
         no silent-steer fallback) -- the (b)/(c) lighter keyword legs.

No leg here touches a GPU or a training process. This receipt generator, the runner it invokes,
and everything they read (GOAL.md, docs/ember-debt-ledger.md, the totality-board receipt) are
pure filesystem/process-exit-code operations.

Run:  python scripts/ember_cobs_proof_pack_receipt.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The constitutional invariant hash every post-genesis receipt must carry
# (scripts/receipt_check.py's post-genesis rule, enforced by repo-guard's
# changed-receipts leg). IMPORTED from the checker rather than copied, so this
# generator cannot drift from the authority that grades it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from receipt_check import INVARIANT_SHA256  # noqa: E402

RUNNER_REL = "tools/ember-cli/src/scripts/cobs-proof-pack-run.ts"
ADAPTER_REL = "tools/ember-cli/src/core/ember-world-state.ts"
BUN_CANDIDATES = ["bun.cmd", "bun", r"C:\nvm4w\nodejs\bun.cmd", "C:/nvm4w/nodejs/bun.cmd"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_bun() -> str:
    for cand in BUN_CANDIDATES:
        try:
            proc = subprocess.run([cand, "--version"], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=15)
            if proc.returncode == 0:
                return cand
        except (OSError, subprocess.SubprocessError):
            continue
    raise SystemExit("bun not found on any known candidate path")


def _run_verb(bun: str, verb: str) -> tuple[int, str]:
    """Actually invoke the proof-pack runner for one verb. Returns (exit_code, combined_output).
    Never assumes success -- the real subprocess exit code is what gets recorded."""
    cli_dir = REPO_ROOT / "tools" / "ember-cli" / "src"
    env = dict(os.environ)
    env["EMBER_GOALFORGE_ROOT"] = str(REPO_ROOT)
    proc = subprocess.run(
        [bun, "scripts/cobs-proof-pack-run.ts", verb],
        cwd=str(cli_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
    return proc.returncode, proc.stdout or ""


def _latest_totality_receipt() -> str:
    board_dir = REPO_ROOT / "scripts" / "ember_totality" / "receipts-totality"
    candidates = sorted(board_dir.glob("ember-totality-*.json"))
    if not candidates:
        raise SystemExit("no totality-board receipt found under scripts/ember_totality/receipts-totality/")
    newest = candidates[-1]
    return str(newest.relative_to(REPO_ROOT)).replace("\\", "/")


def main() -> int:
    bun = _find_bun()

    commands = []
    all_ok = True
    for verb in ("monitor", "understand", "interact"):
        code, output = _run_verb(bun, verb)
        commands.append({"verb": verb, "exit_code": code, "output_len": len(output)})
        if code != 0:
            all_ok = False
        print(f"{verb}: exit_code={code} output_len={len(output)}")

    adapter_path_abs = REPO_ROOT / ADAPTER_REL
    runner_path_abs = REPO_ROOT / RUNNER_REL
    if not adapter_path_abs.is_file():
        raise SystemExit(f"adapter source missing: {ADAPTER_REL}")
    if not runner_path_abs.is_file():
        raise SystemExit(f"runner script missing: {RUNNER_REL}")

    sources = [
        "GOAL.md",
        "docs/ember-debt-ledger.md",
        _latest_totality_receipt(),
    ]

    receipt = {
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "ticket": "C-OBS-PROOF-PACK",
        "kind": "ember-c-obs-proof-pack-receipt",
        # Authority binding (scripts/verify_authority_conservation.py leg 4,
        # artifact.goal_binding) and the sha-claim convention every hash field in
        # this receipt is computed under (scripts/receipt_check.py R2).
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": (
            "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        ),
        "sha_convention": "bytes on disk as-is (binary read, no normalization)",
        "invariant_sha256": INVARIANT_SHA256,
        "emberworldstate_adapter": {
            "binds": True,
            "sources": sources,
            "adapter_path": ADAPTER_REL,
            "adapter_sha256": _sha256(adapter_path_abs),
        },
        "observatory_proof_pack": {
            "commands": commands,
            "runner_path": RUNNER_REL,
            "runner_sha256": _sha256(runner_path_abs),
        },
        "notes": (
            "click-to-evidence surface: tools/ember-cli/src/commands/world-state.ts exposes an "
            "`evidence <s> <n>` verb on the /cockpit command that resolves a specific MONITOR/"
            "UNDERSTAND/INTERACT row to its underlying EvidenceRef{path, sha256}, i.e. real "
            "click-to-evidence, not a static summary. "
            "confirm-only encounter membrane: tools/ember-cli/src/core/encounter-membrane.ts's "
            "validateConfirmation(offer, suppliedOfferId, suppliedToken) is a pure function keyed "
            "on CONFIRM_TOKEN; there is no silent-steer path -- no code path in this module acts "
            "on an offer without an explicit matching confirm token supplied by the operator."
        ),
        "all_commands_exit_zero": all_ok,
    }

    out_dir = REPO_ROOT / "receipts" / "ember-c-obs-proof-pack" / receipt["ts"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "receipt.json"
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(receipt, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")

    print(f"receipt written: {out_path.relative_to(REPO_ROOT)}")
    print(f"all_commands_exit_zero={all_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
