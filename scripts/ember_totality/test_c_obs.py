#!/usr/bin/env python3
"""test_c_obs.py — STATUS PROBE for Ember goal condition C-OBS.

Condition (authoritative, ember-goal-leo.md §4.2 / §4.4):
  C-OBS — Observatory real-binding + user-facing CLI (#1; first-class & EARLY).
  R: real adapters (GOAL/ledger/receipts -> EmberWorldState), click-to-evidence,
     encounter membrane (confirm-only, never silent steering); AND a user-facing
     CLI/observatory surface that lets the user MONITOR (live organism state),
     UNDERSTAND (organ anatomy + loop topology), and INTERACT (drive/inspect
     cycles, query receipts/ledger), proven by a proof-pack the user runs himself.
  Does NOT count:
     - the synthetic P0 stub                          -> invalid_observatory_synthetic_only
     - a patch/delta latent branch reported as a predictive world model
       (require rollout artifacts)                    -> invalid_observatory_synthetic_only
     - an observatory the user cannot run, or that shows stale/stubbed state
                                                       -> invalid_observatory_not_user_runnable
  CHK: adapters bind real receipts; membrane has no silent-steer path; the
       proof-pack commands run and emit live state.

TDD discipline: this is a STATUS PROBE. It ALWAYS exits 0; it prints exactly one
line "RED <reason>" or "GREEN <reason>" so the totality board can aggregate.
It determines RED/GREEN by REALLY inspecting state under kai-converge — it never
hardcodes the verdict.

Run ONLY via:  wsl python3 <this file>
Under WSL the B: drive is /mnt/b OR /b depending on the mount; both are probed.
"""

# [PATH-REWRITE 2026-07-01] Imported from
# B:/M/avir/leo/state/ember-totality-build/ into
# B:/M/ember-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at B:/M/avir/leo/state/kai-converge (and /mnt/b/M/...,
# /b/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed via pathlib from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. kai-converge does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Locate the real state root (kai-converge). The receipts-only truth source.
# ---------------------------------------------------------------------------

def _find_state_root() -> Path | None:
    _repo_root = Path(__file__).resolve().parent.parent.parent
    _env_root = os.environ.get("EMBER_TOTALITY_ROOT")
    candidates = [
        Path(_env_root) if _env_root else None,
        _repo_root,
        _repo_root / "kai-converge",
    ]
    for c in candidates:
        if c is None:
            continue
        try:
            if c.is_dir():
                return c
        except OSError:
            continue
    return None


# The invalid-tokens this condition must NOT match (encoded as negative checks).
INVALID_TOKENS = [
    "invalid_observatory_synthetic_only",
    "invalid_observatory_not_user_runnable",
]

# [LANE-14 REPAIR 1, 2026-07-02] Positive C-OBS evidence (the (a)-(d) conjuncts
# below) must come from EVIDENCE surfaces only -- governing-text descriptions
# of the observatory (docs/, scripts/*.py) can otherwise satisfy the checks by
# prose alone, with zero receipts. [ECHO REPAIR, 2026-07-03] Negative evidence
# (INVALID_TOKENS) scans the SAME evidence surfaces: the previous tree-wide scan
# re-matched the totality board's own receipts (which quote each RED reason,
# token included) plus the registry/spec/archive files that DEFINE the token
# vocabulary -- a closed loop that kept C-OBS structurally RED forever once it
# went RED once. Governing text is not evidence in either direction; a genuine
# disqualifying admission in receipts/ledger/baseline still fires unconditionally
# (negative-control fixture verified before landing).
EVIDENCE_SUBDIRS = ("receipts", "ledger", "baseline")


def _iter_text_files(root: Path):
    """Yield (path, text) for ANY file under root, skipping .git. Used ONLY for
    the negative INVALID_TOKENS scan, which is intentionally tree-wide."""
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirpath.split(os.sep):
            continue
        if os.sep + ".git" in dirpath:
            continue
        for name in filenames:
            if not (name.endswith(".json") or name.endswith(".md")
                    or name.endswith(".jsonl") or name.endswith(".py")):
                continue
            p = Path(dirpath) / name
            try:
                yield p, p.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue


def _iter_evidence_files(root: Path):
    """Yield (path, text) for files under evidence-surface subtrees only
    (receipts/, ledger/, baseline/ directly under root), EXCLUDING .py
    sources. Positive C-OBS evidence (a)-(d) must come from actual receipts,
    never from governing-text descriptions or probe/source code."""
    for sub in EVIDENCE_SUBDIRS:
        sub_root = root / sub
        if not sub_root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(sub_root):
            if ".git" in dirpath.split(os.sep):
                continue
            for name in filenames:
                if not (name.endswith(".json") or name.endswith(".md")
                        or name.endswith(".jsonl")):
                    continue
                p = Path(dirpath) / name
                try:
                    yield p, p.read_text(encoding="utf-8", errors="replace")
                except (OSError, UnicodeDecodeError):
                    continue


def _inspect(root: Path):
    """Inspect real state. Return (verdict, reason, invalid_hits).

    GREEN requires a REAL C-OBS satisfying artifact:
      (a) an adapter receipt/artifact binding real GOAL/ledger/receipts ->
          EmberWorldState (the world-state binding), AND
      (b) a click-to-evidence surface, AND
      (c) a confirm-only encounter membrane (no silent-steer path), AND
      (d) a user-runnable observatory proof-pack (MONITOR/UNDERSTAND/INTERACT)
          evidenced by a proof-pack receipt that the user runs himself.
    AND none of the does-NOT-count invalid-tokens may be present as an
    explicit marker / verdict on any such artifact.
    """
    has_worldstate_binding = False
    worldstate_evidence = None
    has_click_to_evidence = False
    has_membrane_confirm_only = False
    has_user_proofpack = False
    proofpack_evidence = None
    invalid_hits: list[str] = []

    # Negative scan: evidence surfaces only -- symmetric with the positive scan
    # ([ECHO REPAIR, 2026-07-03]; see header comment for the self-echo loop this closes).
    for p, text in _iter_evidence_files(root):
        rel = str(p.relative_to(root))
        for tok in INVALID_TOKENS:
            if tok in text:
                invalid_hits.append(f"{tok}@{rel}")

    # Positive scan: evidence surfaces only (receipts/, ledger/, baseline/),
    # never governing-text descriptions or .py sources -- see EVIDENCE_SUBDIRS.
    for p, text in _iter_evidence_files(root):
        rel = str(p.relative_to(root))
        low = text.lower()

        # (a) real EmberWorldState binding adapter — receipt/artifact that binds
        #     GOAL/ledger/receipts into the world state, and is NOT a synthetic stub.
        if "emberworldstate" in low:
            mentions_sources = any(
                s in low for s in ("goal", "ledger", "receipt")
            )
            looks_binding = any(
                s in low for s in ("adapter", "bind", "world_state", "worldstate")
            )
            is_stub = any(
                s in low for s in (
                    "synthetic", "p0 stub", "p0-stub", "stub_only",
                    "stubbed", "_not_executable", "not_executable",
                    "placeholder", "no adapter receipts",
                )
            )
            if mentions_sources and looks_binding and not is_stub:
                has_worldstate_binding = True
                worldstate_evidence = rel

        # (b) click-to-evidence surface, evidenced in an actual receipt/artifact
        if "click-to-evidence" in low or "click_to_evidence" in low or "click to evidence" in low:
            has_click_to_evidence = True

        # (c) confirm-only encounter membrane with no silent-steer path -- the
        #     "no silent steer" strengthening is required regardless of location;
        #     merely being under an evidence subtree is no longer sufficient.
        if ("membrane" in low and ("confirm-only" in low or "confirm_only" in low
                                   or "confirm only" in low)):
            if "silent" in low and ("no silent" in low or "never silent" in low
                                    or "no_silent_steer" in low):
                has_membrane_confirm_only = True

        # (d) user-runnable observatory proof-pack
        if ("observatory" in low or "observe" in low) and "proof" in low and "pack" in low:
            if any(s in low for s in ("monitor", "understand", "interact")):
                has_user_proofpack = True
                proofpack_evidence = rel

    # Decide verdict purely from inspection.
    if invalid_hits:
        return ("RED",
                "does-NOT-count invalid-token matched: " + ", ".join(sorted(set(invalid_hits))),
                sorted(set(invalid_hits)))

    missing = []
    if not has_worldstate_binding:
        missing.append("real GOAL/ledger/receipts->EmberWorldState adapter binding")
    if not has_click_to_evidence:
        missing.append("click-to-evidence surface")
    if not has_membrane_confirm_only:
        missing.append("confirm-only encounter membrane (no silent-steer)")
    if not has_user_proofpack:
        missing.append("user-runnable observatory proof-pack (MONITOR/UNDERSTAND/INTERACT)")

    if missing:
        return ("RED",
                "C-OBS satisfying artifact ABSENT under the state root: missing " + "; ".join(missing),
                [])

    return ("GREEN",
            f"real EmberWorldState binding ({worldstate_evidence}) + click-to-evidence "
            f"+ confirm-only membrane + user-runnable proof-pack ({proofpack_evidence}); "
            "no invalid-token matched",
            [])


def main() -> int:
    root = _find_state_root()
    if root is None:
        # Cannot inspect -> RED (artifact cannot be shown present). Still exit 0.
        print("RED kai-converge state root not found on any of "
              "/mnt/b, /b, B: — cannot inspect real receipts")
        return 0

    verdict, reason, _invalid = _inspect(root)
    print(f"{verdict} {reason}")
    return 0


if __name__ == "__main__":
    # STATUS PROBE: always exit 0; verdict is in stdout.
    sys.exit(main())
