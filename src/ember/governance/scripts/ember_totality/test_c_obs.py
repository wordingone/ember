#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_c_obs.py — STATUS PROBE for Ember goal condition C-OBS.

Condition (authoritative, <spec> §4.2 / §4.4):
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

[ISSUE #749 cure, docs/domains/governance/charter/probe-authoring-contract.md] Execution-binding hardening.
The pre-cure (a) worldstate-binding and (d) proof-pack conjuncts were pure
keyword/prose scans over any evidence-subdir file -- a hand-authored .md or
.json containing the right words satisfied CHK with zero recompute. Both are
now decisive, structured-receipt-only checks: (a) requires a real
`emberworldstate_adapter` block naming GOAL/ledger/receipt sources that
RESOLVE in-tree (spanning >=2 of the three categories) and sha-pins its own
adapter source file via the proven `_lane14_common.check_path_sha_pairs`
pattern (test_c4.py/test_c5.py's template); (d) requires an
`observatory_proof_pack` block whose commands cover monitor+understand+interact
each with an EXPLICIT `exit_code == 0` (a missing/absent exit_code REJECTS,
never defaults to a pass) and sha-pins its own runner script the same way. A
receipt carrying only self-attested keywords/booleans with no resolvable
in-tree pointer now fails both checks. (b) click-to-evidence and (c)
confirm-only-membrane remain lighter keyword checks but are ANDed with, never
a substitute for, (a)/(d) (checklist item 5).

TDD discipline: this is a STATUS PROBE. It ALWAYS exits 0; it prints exactly one
line "RED <reason>" or "GREEN <reason>" so the totality board can aggregate.
It determines RED/GREEN by REALLY inspecting state under <external-state> — it never
hardcodes the verdict.

Run ONLY via:  wsl python3 <this file>
Under WSL the execution root is /mnt/b OR /b depending on the mount; both are probed.
"""

# [PATH-REWRITE 2026-07-01] Imported from
# <<external>>/state/ember-totality-build/ into
# <local-exec-root>-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at <<external>>/state/<external-state> (and /mnt<local-mount-point>/M/...,
# <local-mount-point>/M/..., <TEMP_WORKSPACE>/... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed via pathlib from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
LEGACY_TOTALITY = REPO_ROOT / "scripts" / "ember_totality"
sys.path.insert(0, str(LEGACY_TOTALITY))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lane14_common import check_path_sha_pairs, resolve_in_tree  # noqa: E402


# ---------------------------------------------------------------------------
# Locate the real state root (<external-state>). The receipts-only truth source.
# ---------------------------------------------------------------------------

def _find_state_root() -> Path | None:
    _repo_root = REPO_ROOT
    _env_root = os.environ.get("EMBER_TOTALITY_ROOT")
    candidates = [
        Path(_env_root) if _env_root else None,
        _repo_root,
        _repo_root / "<external-state>",
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


def _iter_evidence_json(root: Path):
    """Yield (path, parsed_dict) for .json files under evidence-surface subtrees
    (receipts/, ledger/, baseline/) that parse as a JSON object. [ISSUE #749
    cure, docs/domains/governance/charter/probe-authoring-contract.md] The decisive (a) worldstate-binding
    and (d) proof-pack conjuncts require a REAL structured receipt whose claimed
    pointers (source paths, runner path, sha256, exit codes) can be resolved and
    recomputed -- never a keyword match against prose (.md is excluded here on
    purpose; it stays eligible for the lighter (b)/(c) auxiliary checks and the
    tree-wide negative scan)."""
    for sub in EVIDENCE_SUBDIRS:
        sub_root = root / sub
        if not sub_root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(sub_root):
            if ".git" in dirpath.split(os.sep):
                continue
            for name in filenames:
                if not name.endswith(".json"):
                    continue
                p = Path(dirpath) / name
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        obj = json.load(fh)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(obj, dict):
                    yield p, obj


_STUB_MARKERS = (
    "synthetic", "p0 stub", "p0-stub", "stub_only", "stubbed",
    "_not_executable", "not_executable", "placeholder", "no adapter receipts",
)


def _check_worldstate_binding(obj, root):
    """(a) execution-binding recompute: the receipt's `emberworldstate_adapter`
    block must name real GOAL/ledger/receipt sources that RESOLVE in-tree
    (never existence-only trust of the claim), span at least two of those three
    categories, name no stub marker, and sha-pin its own adapter source code
    via the proven `<field>_path`/`<field>_sha256` pattern. Returns
    (ok: bool, detail_or_None)."""
    block = obj.get("emberworldstate_adapter")
    if not isinstance(block, dict):
        return False, None
    if block.get("binds") is not True:
        return False, None
    if any(m in json.dumps(block).lower() for m in _STUB_MARKERS):
        return False, None

    sources = block.get("sources")
    if not isinstance(sources, list) or not sources:
        return False, None
    resolved_categories = set()
    for s in sources:
        if not isinstance(s, str) or resolve_in_tree(s, root) is None:
            continue  # off-tree/missing claimed source -- not real evidence
        low_s = s.lower()
        for cat in ("goal", "ledger", "receipt"):
            if cat in low_s:
                resolved_categories.add(cat)
    if len(resolved_categories) < 2:
        return False, None  # must span >=2 of GOAL/ledger/receipts, in-tree, not a single unverified claim

    ok, _n, detail = check_path_sha_pairs(block, root)
    if not ok:
        return False, f"adapter source-code binding failed: {detail}"
    return True, f"sources resolved in-tree ({sorted(resolved_categories)}); {detail}"


def _check_proofpack(obj, root):
    """(d) execution-binding recompute: the receipt's `observatory_proof_pack`
    block must name commands whose `verb` covers monitor+understand+interact
    each with an EXPLICIT `exit_code == 0` (a missing/absent exit_code is a
    REJECT, never a silent pass -- checklist item 7), and sha-pin its own
    runner script in-tree. Returns (ok: bool, detail_or_None)."""
    block = obj.get("observatory_proof_pack")
    if not isinstance(block, dict):
        return False, None
    commands = block.get("commands")
    if not isinstance(commands, list) or not commands:
        return False, None
    verbs_seen = set()
    for c in commands:
        if not isinstance(c, dict):
            continue
        verb = c.get("verb")
        if verb not in ("monitor", "understand", "interact"):
            continue
        if c.get("exit_code") != 0:  # missing/non-zero -- reject, never default-pass
            continue
        verbs_seen.add(verb)
    if not {"monitor", "understand", "interact"} <= verbs_seen:
        return False, None

    ok, _n, detail = check_path_sha_pairs(block, root)
    if not ok:
        return False, f"proof-pack runner binding failed: {detail}"
    return True, f"commands cover monitor+understand+interact, each exit_code=0; {detail}"


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

    # [ISSUE #749 cure] (a) and (d) execution-binding scan: structured JSON
    # receipts only, resolved+recomputed via _check_worldstate_binding /
    # _check_proofpack (never a keyword match against prose). Decisive --
    # ANDed with, never substitutable by, the lighter (b)/(c) keyword checks
    # below.
    for p, obj in _iter_evidence_json(root):
        rel = str(p.relative_to(root))

        if not has_worldstate_binding:
            ok, detail = _check_worldstate_binding(obj, root)
            if ok:
                has_worldstate_binding = True
                worldstate_evidence = f"{rel} ({detail})"

        if not has_user_proofpack:
            ok, detail = _check_proofpack(obj, root)
            if ok:
                has_user_proofpack = True
                proofpack_evidence = f"{rel} ({detail})"

    # Positive scan: evidence surfaces only (receipts/, ledger/, baseline/),
    # never governing-text descriptions or .py sources -- see EVIDENCE_SUBDIRS.
    # (b)/(c) remain lighter structural/keyword checks (checklist item 5:
    # auxiliary, ANDed with the execution-bound (a)/(d) checks above, never
    # independently sufficient for GREEN on their own).
    for p, text in _iter_evidence_files(root):
        low = text.lower()

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
        print("RED <external-state> state root not found on any of "
              "/mnt/b, /b, B: — cannot inspect real receipts")
        return 0

    verdict, reason, _invalid = _inspect(root)
    print(f"{verdict} {reason}")
    return 0


if __name__ == "__main__":
    # STATUS PROBE: always exit 0; verdict is in stdout.
    sys.exit(main())
