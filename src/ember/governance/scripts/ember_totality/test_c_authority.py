#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Status probe for C-AUTHORITY, Ember authority conservation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
ROOT = Path(os.environ.get("EMBER_TOTALITY_ROOT", REPO_ROOT)).resolve()
VERIFIER = ROOT / "scripts" / "verify_authority_conservation.py"


def main() -> int:
    if not VERIFIER.is_file():
        print("RED C-AUTHORITY: conservation verifier missing")
        return 0
    command = [sys.executable, str(VERIFIER), "--root", str(ROOT), "--json"]
    selection = os.environ.get("EMBER_GOAL_SELECTION")
    if selection:
        command.extend(["--selection", selection])
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        detail = (result.stderr or result.stdout or "no output").strip().splitlines()[-1]
        print(f"RED C-AUTHORITY: verifier unparseable: {detail}")
        return 0
    if result.returncode == 0 and payload.get("ok") is True:
        legs = payload.get("certificate_legs", {})
        print(f"GREEN C-AUTHORITY: authority conservation passed ({len(legs)} legs)")
        return 0
    errors = payload.get("errors") or []
    codes = [str(item.get("code", "unknown")) for item in errors[:5]]
    print(f"RED C-AUTHORITY: authority conservation failed: {codes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
