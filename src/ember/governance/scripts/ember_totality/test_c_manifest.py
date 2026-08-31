#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""C-MANIFEST -- completeness manifest enumerates EVERY planned piece -- status probe (TDD).

Authoritative condition (<<external>>/state/<spec>, §4.3 C-MANIFEST):

  R:  docs/contracts/ember-completeness.md enumerates every planned/known piece
      (id, subgoal S1-S7, AC, test, receipt pointer, status). A planned piece
      absent from the manifest is a gate violation -- planning and
      manifest-entry are the same act.
  invalid token (does-NOT-count): invalid_unmanifested_piece
  CHK: the manifest enumerates every planned piece with the required fields,
      and no planned piece is absent (an absent piece == invalid_unmanifested_piece).

Receipt/artifact inspected (REAL): <<external>>/state/<external-state>/docs/contracts/ember-completeness.md
and the authoritative goal file's enumerated §4 conditions
(<<external>>/state/<spec>), which ARE planned pieces of the organism.

This file is a STATUS PROBE, not a unit test: it always exits 0 and prints a
single line "RED <reason>" or "GREEN <reason>" by REALLY inspecting state. It
never hardcodes the verdict.

Run (Git Bash):  wsl python3 \
  <<external>>/state/ember-totality-build/test_c_manifest.py
"""

# [PATH-REWRITE 2026-07-01] Imported from
# <<external>>/state/ember-totality-build/ into
# <local-exec-root>-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at <<external>>/state/<external-state> (and /mnt<local-mount-point>/M/...,
# <local-mount-point>/M/..., <TEMP_WORKSPACE>/... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# --- locate the external state root + goal file regardless of path convention -----
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
# [RULING-DRIFT CORRECTION, 2026-07-06, gh #254] dropped the vestigial third
# REPO_ROOT-relative fallback candidate: EMBER_TOTALITY_ROOT and REPO_ROOT already
# cover every real invocation shape, and the dropped candidate never resolved to
# anything -- a latent probe defect if it were ever reached first.
_NC_ROOTS = [p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT) if p]
# The §4 condition-bullet prose now lives in docs/domains/governance/spec/conditions-v1.md (the
# canonical registry, docs/domains/governance/authority/GOAL.md §4 header); docs/domains/governance/authority/GOAL.md itself is tried too (its §4
# may inline amendments/bullets directly). Order = most-authoritative first.
# [RULING-DRIFT CORRECTION, 2026-07-06, gh #254] dropped the vestigial legacy
# "<spec>" last-resort candidate: a literal bracketed placeholder never exists
# verbatim on disk, so it could never resolve on any real tree -- a latent
# probe defect if the first two candidates were ever both absent.
#
# [LANE-14 REPAIR 2, 2026-07-02] These candidates MUST be resolved relative to
# the resolved nc_root (which honors EMBER_TOTALITY_ROOT), not the fixed
# REPO_ROOT global -- otherwise a probe run against an isolated fixture root
# (the control-suite isolation mechanism) silently falls through to the REAL
# repo's goal file for the denominator while correctly using the fixture's
# manifest, which both breaks control isolation and is a latent correctness
# risk if the two locations ever diverge. See _goal_files_for(root).
def _goal_files_for(root: str) -> list[str]:
    return [
        os.path.join(root, "docs", "spec", "conditions-v1.md"),
        os.path.join(root, "docs/domains/governance/authority/GOAL.md"),
    ]

# Invalid-token whose REAL match -> RED (does-NOT-count); negative assertion.
INVALID_TOKEN = "invalid_unmanifested_piece"

# Required fields of each manifest row (the R spec).
_VALID_SUBGOALS = {"S1", "S2", "S3", "S4", "S5", "S6", "S7"}


def _first_existing(cands: list[str]) -> str | None:
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _parse_legacy_id_map(text: str) -> dict[str, str]:
    """Parse the manifest's own "| Legacy ID | Current ID |" table (present since the
    2026-06-?? id-scheme migration from C1..C55 condition-numbered rows to M1..M55
    piece-numbered rows). Returns {legacy_c_id: current_m_id}. [RULING-DRIFT
    CORRECTION, 2026-07-06, gh #254]: _parse_manifest_rows used to require id cells to
    start with "C", so it silently matched only this 2-column legacy table (which
    fails the >=6-cell check and lands in `malformed`, never `rows`) while skipping
    the real 6-column M1..M55 data table entirely -- the file's actual, current
    manifest rows were never parsed at all, producing the false "no parseable rows
    found" verdict. This map lets the id-matching step below translate a §4
    condition's legacy C-id to its current M-id before checking manifestation."""
    legacy_map: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) != 2:
            continue
        legacy, current = cells[0], cells[1]
        if re.match(r"^C[\w()−\-]+$", legacy) and re.match(r"^M[\w()−\-]+$", current):
            legacy_map[legacy] = current
    return legacy_map


def _parse_manifest_rows(text: str) -> tuple[list[dict], list[str]]:
    """Parse the markdown table rows. Returns (rows, malformed[])."""
    rows: list[dict] = []
    malformed: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        # header / separator rows
        if not cells or cells[0] in ("id", "") or set(cells[0]) <= set("-: "):
            continue
        # a data row: id | subgoal | piece | AC/test | receipt | status
        # [LANE-14 REPAIR 2b, 2026-07-02] row-id class gains U+2212 to mirror
        # _CID_RE's goal-side repair -- "C(−1)" rows were skipped as non-data
        # rows, leaving that condition permanently ABSENT however the manifest
        # spelled it (fail-closed asymmetry between the two parsers).
        # [RULING-DRIFT CORRECTION, 2026-07-06, gh #254]: the manifest's own row-id
        # scheme migrated from C1..C55 to M1..M55 (see _parse_legacy_id_map's
        # docstring) -- widened to accept both prefixes so the CURRENT 6-column
        # M-numbered data rows are actually parsed, not silently skipped.
        if not re.match(r"^[CM][\w()−\-]+$", cells[0]):
            continue
        # [RULING-DRIFT CORRECTION, 2026-07-06, gh #254]: a genuine 2-cell row here is
        # the "| Legacy ID | Current ID |" cross-reference table (see
        # _parse_legacy_id_map), not a malformed manifest row -- skip it silently
        # rather than counting 55 harmless legacy-map entries as field-incomplete
        # manifest rows, which would falsely RED an otherwise-complete manifest.
        if len(cells) == 2:
            continue
        if len(cells) < 6:
            malformed.append(f"{cells[0]} (only {len(cells)} cells)")
            continue
        cid, subgoal, piece, ac, receipt, status = cells[0], cells[1], cells[2], cells[3], cells[4], cells[5]
        row = {
            "id": cid, "subgoal": subgoal, "piece": piece,
            "ac": ac, "receipt": receipt, "status": status,
        }
        # field-completeness: id, subgoal in S1-S7, AC, receipt-pointer, status all present
        if subgoal not in _VALID_SUBGOALS:
            malformed.append(f"{cid} (subgoal '{subgoal}' not S1-S7)")
        if not ac:
            malformed.append(f"{cid} (empty AC/test)")
        # [HARDEN, audit 2026-07-10T20:38:26Z] receipt-cell non-emptiness --
        # id/subgoal/AC/status were all field-completeness-checked but the
        # receipt cell itself never was, so a row citing NOTHING as its
        # evidence pointer still counted as a complete, manifested row.
        if not receipt:
            malformed.append(f"{cid} (empty receipt)")
        if not status:
            malformed.append(f"{cid} (empty status)")
        rows.append(row)
    return rows, malformed


# [LANE-14 REPAIR 2, 2026-07-02] Tolerant separators: the original alternation
# (--|—| -) missed bullets using en-dash "–" (U+2013), a bare colon+bold-close
# ":**", or bold-close alone "**" immediately after the id -- each silently
# dropped that condition from the denominator (fail-open: fewer planned pieces
# means GREEN is easier to reach). The id-capture class also gains the unicode
# minus sign U+2212 (distinct from ASCII hyphen U+002D), which the live goal
# file actually uses inside "C(−1)" -- without it that condition's bullet
# never matched at all and silently vanished from the count.
#
# [HARDEN, audit 2026-07-10T20:38:26Z] the alternation had no bare "."
# separator -- the live goal file's own §4 machinery bullets, "- **C-MANIFEST.**"
# and "- **C-TALLY.**" (period immediately after the id, before the bold-close),
# both failed to match and silently vanished from the denominator (38 seen vs
# the true 40). Widened to accept "." so these two genuinely-planned pieces are
# counted; the cure is same-PR: docs/contracts/ember-completeness.md gains real rows for
# both (see the "Additional condition rows" table) so GREEN stays honest.
_CID_RE = re.compile(r"^\s*-\s*\*\*(C[\w()−\-]+?)\s*(?:--|—|–|:|\*\*|\.| -)")

# Denominator floor: the live goal's §4 enumerates dozens of conditions. A
# parsed count below this means the parser broke or the goal drifted out from
# under it -- proceeding would silently shrink the denominator (fail-open).
_MIN_PLAUSIBLE_SECTION4_COUNT = 20


def _goal_section4_condition_ids(goal_text: str) -> list[str]:
    """Enumerate the §4 goal conditions -- these ARE planned pieces of the organism.

    Matches bullet lines of the form '- **C-XXX -- ...' / '- **C14 -- ...' inside
    §4 (the explicit completion bar). Each is a planned piece that the manifest
    must enumerate; an absent one == invalid_unmanifested_piece.
    """
    ids: list[str] = []
    in_s4 = False
    for line in goal_text.splitlines():
        if re.match(r"^##+\s*4[.)\s]", line):
            in_s4 = True
            continue
        if in_s4 and re.match(r"^##+\s*5[.)\s]", line):
            break
        if not in_s4:
            continue
        # condition bullets look like:  - **C-PORT -- ...  or  - **C14: ...
        m = _CID_RE.match(line)
        if m:
            cid = m.group(1).rstrip("-*:")
            ids.append(cid)
    # de-dup preserve order
    seen = set()
    out = []
    for c in ids:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def main() -> int:
    nc_root = _first_existing(_NC_ROOTS)
    if nc_root is None:
        print(f"RED <external-state> root not found at any known path (tried {_NC_ROOTS})")
        return 0

    matrix_path = os.path.join(nc_root, "docs", "ember-authority-matrix.md")
    if os.path.isfile(matrix_path):
        scripts_path = os.path.join(nc_root, "scripts")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        try:
            from authority_supersession_gate import validate_current_authority_crosswalk
            validate_current_authority_crosswalk(Path(nc_root))
        except Exception as exc:
            print(f"RED authority supersession crosswalk invalid: {exc}")
            return 0

    manifest_path = os.path.join(nc_root, "docs", "ember-completeness.md")
    if not os.path.exists(manifest_path):
        # positive artifact genuinely absent
        print(f"RED docs/contracts/ember-completeness.md ABSENT under {nc_root} "
              f"-- the completeness manifest (the C-MANIFEST artifact) does not exist")
        return 0

    manifest_text = _read(manifest_path)

    # (2) NEGATIVE assertion: the invalid-token must not appear as a real marker
    # in the manifest or in any receipt. Its presence is a literal does-NOT-count.
    if INVALID_TOKEN in manifest_text:
        print(f"RED {INVALID_TOKEN} marker present literally in "
              f"docs/contracts/ember-completeness.md (a planned piece flagged unmanifested)")
        return 0

    rows, malformed = _parse_manifest_rows(manifest_text)
    if not rows:
        print(f"RED docs/contracts/ember-completeness.md present but NO parseable "
              f"(id|subgoal|piece|AC|receipt|status) rows found")
        return 0

    if malformed:
        print(f"RED manifest has {len(rows)} rows but {len(malformed)} are "
              f"field-incomplete (R requires id+subgoal[S1-S7]+AC+receipt+status); "
              f"first={malformed[0]}")
        return 0

    manifested_ids = {r["id"] for r in rows}
    legacy_id_map = _parse_legacy_id_map(manifest_text)

    # The planned pieces the manifest MUST enumerate include the goal file's §4
    # conditions (each is an explicit planned/known piece of the organism). An
    # absent §4 condition == invalid_unmanifested_piece by the C-MANIFEST rule.
    # Resolved relative to nc_root (honors EMBER_TOTALITY_ROOT) -- NOT the fixed
    # REPO_ROOT global -- so an isolated control fixture's goal file is what
    # actually gets parsed, matching how manifest_path is already resolved.
    goal_files = _goal_files_for(nc_root)
    goal_path = _first_existing(goal_files)
    if goal_path is None:
        print(f"RED no authoritative goal/registry file found among {goal_files} "
              "-- cannot enumerate the planned-piece denominator (§4 conditions)")
        return 0
    goal_text = _read(goal_path)
    section4_ids = _goal_section4_condition_ids(goal_text)
    if len(section4_ids) < _MIN_PLAUSIBLE_SECTION4_COUNT:
        print(
            f"RED denominator implausibly small (<{_MIN_PLAUSIBLE_SECTION4_COUNT}) "
            f"-- parser/goal drift: only {len(section4_ids)} §4 condition(s) parsed "
            f"from {goal_path}"
        )
        return 0

    # A §4 condition is "manifested" iff its id appears as a manifest row id --
    # DIRECTLY, or via the manifest's own "Legacy ID -> Current ID" table if the
    # condition's C-id was renamed to an M-id ([RULING-DRIFT CORRECTION, 2026-07-06,
    # gh #254]: the manifest was originally dated 2026-06-12 with rows C1..C55 keyed
    # to S1-S7; it has since migrated its own row-id scheme to M1..M55 and records
    # the C->M mapping in-file. The 2026-06-23 goal rewrite added
    # C-PORT/C-FED/C-GROW/C-ORGANISM/C-OBS/C-ANAT/C-EFF/C-BASE/... after that
    # migration, so they have no legacy-map entry and are checked directly against
    # manifested_ids -- if truly not yet rowed, they correctly stay unmanifested.)
    unmanifested = [
        cid for cid in section4_ids
        if legacy_id_map.get(cid, cid) not in manifested_ids
    ]

    if unmanifested:
        print(
            f"RED {INVALID_TOKEN}: {len(unmanifested)}/{len(section4_ids)} §4 "
            f"planned condition(s) ABSENT from docs/contracts/ember-completeness.md "
            f"({len(rows)} rows present, ids M1..M{len(rows)} per the in-file "
            f"legacy-id migration, {len(legacy_id_map)} legacy C-id mappings "
            f"applied); missing={','.join(unmanifested)}"
        )
        return 0

    # GREEN: every §4 planned piece is enumerated with complete fields, and no
    # invalid_unmanifested_piece marker exists.
    print(
        f"GREEN C-MANIFEST CHK satisfied: docs/contracts/ember-completeness.md enumerates "
        f"all {len(rows)} rows with complete fields (id+subgoal[S1-S7]+AC+receipt+"
        f"status), every §4 planned condition ({len(section4_ids)}) is manifested, "
        f"and no {INVALID_TOKEN} marker present"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
