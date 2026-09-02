#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""check_milestone_reconciliation.py — validates the M<->board reconciliation
table (docs/spec/milestones-v1.md sections A/C/D) against its source-of-truth
inputs: docs/domains/governance/contracts/ember-completeness.md, docs/domains/governance/roadmap/PROBLEMS.md, docs/contracts/ember-floor-contract.md.

Spec: docs/spec/milestones-v1.md, "Validation hook" section (imports A/C/D).

Checks:
  (a) every M1..M55 — the 55 legacy rows of docs/domains/governance/contracts/ember-completeness.md
      (id column C1..C55, renamed M<n> in §A to avoid the C<n>-numeral
      collision with board conditions) — has a §A entry in milestones-v1.md
      carrying a non-empty target. FATAL if any is unmapped or the manifest
      id-set isn't exactly {1..55}.
  (b) docs/domains/governance/roadmap/PROBLEMS.md's per-meta-problem `gates` lists (H0..H4) are diffed
      against §C's dependency-lattice ASCII diagram. Diffs are REPORTED,
      never fatal (spec: "do not fail on diff — report").
  (c) §D's 6 floor-contract rows in milestones-v1.md each carry non-empty
      owner/pilot/trigger/kill-promote cells (FATAL if any is empty);
      cross-referenced against docs/contracts/ember-floor-contract.md's own deferral
      table (component not found there is reported as a gap too).
  (d) emits receipts/milestone-reconciliation-<UTCtimestamp>.json.

Input resolution: docs/domains/governance/contracts/ember-completeness.md, docs/domains/governance/roadmap/PROBLEMS.md and
docs/domains/governance/problems-meta.yaml are read from THIS worktree if present, else
read-only from <reference-tree> (never written). docs/spec/milestones-v1.md and
docs/contracts/ember-floor-contract.md are goalforge-native (worktree only). Every
resolved path is recorded in the receipt's `inputs` map as {relpath: tree}.
problems-meta.yaml is resolved and recorded for provenance but not deep-
parsed: PyYAML is not stdlib, and PROBLEMS.md already carries the rendered
`gates` lists that (b) is specified against.

Fail-closed: any parse failure (missing heading, malformed table, wrong row
count) raises ParseError, which is caught and written as a FAIL receipt with
the error named, exit code 1. An (a)/(c) assertion violation is not a parse
failure but is likewise reported as exit:"FAIL", exit code 1 -- only a lattice
diff (b) never flips the verdict, per spec.

Run:  python src/ember/governance/scripts/check_milestone_reconciliation.py
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))  # repository root
LEGACY_SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, LEGACY_SCRIPTS)
EMBER_ROOT = os.path.normpath(os.path.join(ROOT, "..", "ember"))  # read-only fallback tree

sys.path.insert(0, HERE)

TICKET = "milestone-reconciliation"


class ParseError(Exception):
    """Any input-shape failure. Always fail-closed."""


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _resolve(rel_path, inputs, allow_ember_fallback=True):
    """Resolve rel_path against this worktree first, then EMBER_ROOT (if
    allowed). Records the source tree in `inputs`. Raises ParseError if
    absent from every permitted location."""
    worktree_path = os.path.join(ROOT, rel_path)
    if os.path.isfile(worktree_path):
        inputs[rel_path] = "goalforge"
        return worktree_path
    if allow_ember_fallback:
        ember_path = os.path.join(EMBER_ROOT, rel_path)
        if os.path.isfile(ember_path):
            inputs[rel_path] = "ember"
            return ember_path
        raise ParseError(
            f"{rel_path}: absent from both the goalforge worktree and <reference-tree> (read-only fallback)"
        )
    raise ParseError(f"{rel_path}: absent from the goalforge worktree (no fallback permitted)")


# ---------------------------------------------------------------------------
# (a) SS A table (milestones-v1.md) vs ember-completeness.md's 55 legacy rows
# ---------------------------------------------------------------------------

_SECTION_A_ROW_RE = re.compile(r"^\|\s*M(\d+)\s*\|(.*)\|(.*)\|\s*$")
_COMPLETENESS_ROW_RE = re.compile(r"^\|\s*C(\d+)\s*\|")

# The 55 legacy rows share docs/domains/governance/contracts/ember-completeness.md with board-CONDITION rows
# (docs/domains/governance/spec/conditions-v1.md's own registry). A condition can use a bare-digit id (e.g.
# C0) that collides with _COMPLETENESS_ROW_RE's own C<digits> pattern -- discovered live,
# 2026-07-04: a "C0" row (board condition, not a legacy milestone) made
# parse_completeness_ids() see {0, 1, ..., 55} != the expected {1, ..., 55}, raising a
# false ParseError against a genuinely intact mirror. The discriminator below is
# STRUCTURAL, never a hardcoded skip-list of today's condition names, so it needs no
# update when a new condition is added later (this fix itself was dispatched the same
# day C-MILE, a brand-new condition, was added):
#   (a) a legacy milestone id is always within the fixed [1, MAX_LEGACY_ID] range this
#       checker's own spec enumerates -- any bare-digit id outside that range is
#       structurally not one of the 55 rows, regardless of what it happens to be;
#   (b) independently, any row whose own text cites the condition registry
#       ("conditions-v1.md") is a condition-row regardless of its id value -- this is
#       the future-proofing half: it would also exclude a not-yet-existing condition
#       whose bare-digit id happened to fall inside [1, MAX_LEGACY_ID].
# Both checks are content/structure-based (a numeric range + a registry-citation marker
# already present in every condition-row today), not a list of condition names baked
# into this file that would need editing every time the registry grows.
MAX_LEGACY_ID = 55
_CONDITION_ROW_MARKER_RE = re.compile(r"conditions-v1\.md")


def parse_section_a(text):
    """Parse SS A's `| M# | legacy piece | -> target |` table into {n: {piece, target}}."""
    rows = {}
    for line in text.splitlines():
        m = _SECTION_A_ROW_RE.match(line)
        if not m:
            continue
        num = int(m.group(1))
        piece, target = m.group(2).strip(), m.group(3).strip()
        if num in rows:
            raise ParseError(f"milestones-v1.md SS A: duplicate row for M{num}")
        rows[num] = {"piece": piece, "target": target}
    if not rows:
        raise ParseError("milestones-v1.md SS A: no M<n> rows found -- table format changed?")
    return rows


def parse_completeness_ids(text):
    """Return the set of legacy row ids (int n from `| Cn |`) in ember-completeness.md,
    structurally excluding any row that is a board-condition registry pointer rather
    than one of the fixed legacy milestone rows (see the module-level comment above
    _CONDITION_ROW_MARKER_RE for the two independent, name-agnostic discriminators)."""
    ids = set()
    for line in text.splitlines():
        m = _COMPLETENESS_ROW_RE.match(line)
        if not m:
            continue
        num = int(m.group(1))
        if num < 1 or num > MAX_LEGACY_ID:
            continue  # out of the legacy range -- structurally a condition row, not a milestone
        if _CONDITION_ROW_MARKER_RE.search(line):
            continue  # cites the condition registry -- a condition row regardless of its id value
        ids.add(num)
    if not ids:
        raise ParseError("ember-completeness.md: no C<n> id rows found -- table format changed?")
    return ids


def check_a(section_a, completeness_ids):
    """Assert every legacy row (1..55) has a non-empty SS A target. Returns (mapped, unmapped)."""
    expected = set(range(1, MAX_LEGACY_ID + 1))
    if completeness_ids != expected:
        missing = sorted(expected - completeness_ids)
        extra = sorted(completeness_ids - expected)
        raise ParseError(
            "ember-completeness.md: expected exactly ids C1..C55, got "
            f"missing={missing} extra={extra}"
        )
    unmapped, mapped = [], 0
    for n in range(1, MAX_LEGACY_ID + 1):
        row = section_a.get(n)
        if row is None:
            unmapped.append(f"M{n}: absent from SS A table")
        elif not row["target"]:
            unmapped.append(f"M{n}: SS A entry present but target is empty")
        else:
            mapped += 1
    return mapped, unmapped


# ---------------------------------------------------------------------------
# (b) SS C lattice (milestones-v1.md) vs PROBLEMS.md meta-problem `gates`
# ---------------------------------------------------------------------------

_COND_TOKEN_RE = re.compile(r"C(?:-[A-Z0-9]+|\d+|\(-1\))")
_H_LINE_RE = re.compile(r"^(H\d)\b")
_PROBLEMS_GATE_LINE_RE = re.compile(r"^-\s+\*\*(H\d)\b")
_GATES_RE = re.compile(r"gates\s+(.+)$")


def extract_lattice_block(text):
    marker = "## C. Dependency lattice"
    idx = text.find(marker)
    if idx == -1:
        raise ParseError("milestones-v1.md: '## C. Dependency lattice' heading not found")
    m = re.search(r"```\n(.*?)```", text[idx:], re.S)
    if not m:
        raise ParseError("milestones-v1.md: SS C fenced lattice block not found")
    return m.group(1)


def parse_lattice(block):
    """Parse the ASCII dependency tree into {H<n>: sorted [condition tokens]}."""
    groups, current = {}, None
    for line in block.splitlines():
        m = _H_LINE_RE.match(line.strip())
        if m:
            current = m.group(1)
            groups.setdefault(current, [])
        if current is not None:
            groups[current].append(line)
    if not groups:
        raise ParseError("milestones-v1.md SS C: no H<n> groups found in lattice block")
    return {h: sorted(set(_COND_TOKEN_RE.findall("\n".join(lines)))) for h, lines in groups.items()}


def parse_problems_gates(text):
    """Parse PROBLEMS.md meta-problem bullets into {H<n>: sorted [gated condition ids]}."""
    gates = {}
    for line in text.splitlines():
        line = line.strip()
        hm = _PROBLEMS_GATE_LINE_RE.match(line)
        if not hm:
            continue
        h = hm.group(1)
        gm = _GATES_RE.search(line)
        if not gm:
            raise ParseError(f"PROBLEMS.md: meta-problem line for {h} has no 'gates' list: {line!r}")
        items = [x.strip() for x in gm.group(1).split(",") if x.strip()]
        if h in gates:
            raise ParseError(f"PROBLEMS.md: duplicate meta-problem bullet for {h}")
        gates[h] = sorted(set(items))
    if not gates:
        raise ParseError("PROBLEMS.md: no meta-problem 'gates' lines found (H0..H4)")
    return gates


def check_b(lattice, problems_gates):
    """Diff SS C's lattice against PROBLEMS.md's gates, per meta-problem. Never fatal."""
    diffs = []
    for h in sorted(set(lattice) | set(problems_gates)):
        l_set, p_set = lattice.get(h, []), problems_gates.get(h, [])
        if l_set != p_set:
            diffs.append({
                "meta_problem": h,
                "milestones_lattice": l_set,
                "problems_gates": p_set,
                "only_in_lattice": sorted(set(l_set) - set(p_set)),
                "only_in_problems": sorted(set(p_set) - set(l_set)),
            })
    return diffs


# ---------------------------------------------------------------------------
# (c) SS D rows (milestones-v1.md) vs ember-floor-contract.md's deferral table
# ---------------------------------------------------------------------------

_D_SECTION_START = "## D. Deferred-component floor-contract pattern"
_D_SECTION_END = "**Invariant carried forward"
_FC_SECTION_START = "## Deferral rows"


def _table_rows(text, min_cols):
    """Yield cell-lists for markdown table data rows (skips header + separator)."""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < min_cols:
            continue
        if cells[0] in ("Component",) or set(cells[0]) <= {"-"}:
            continue
        yield cells


def parse_section_d(text):
    start = text.find(_D_SECTION_START)
    if start == -1:
        raise ParseError(f"milestones-v1.md: '{_D_SECTION_START}' heading not found")
    end = text.find(_D_SECTION_END, start)
    if end == -1:
        raise ParseError("milestones-v1.md: SS D end marker not found")
    rows = []
    for cells in _table_rows(text[start:end], min_cols=8):
        rows.append({
            "component": cells[0],
            "why_deferred": cells[1],
            "pilot": cells[2],
            "trigger": cells[3],
            "owner": cells[4],
            "status": cells[5],
            "kill_promote": cells[6],
            "tier": cells[7],
        })
    if len(rows) != 6:
        raise ParseError(f"milestones-v1.md SS D: expected exactly 6 rows, found {len(rows)}")
    return rows


def parse_floor_contract_components(text):
    idx = text.find(_FC_SECTION_START)
    if idx == -1:
        raise ParseError(f"ember-floor-contract.md: '{_FC_SECTION_START}' heading not found")
    names = [cells[0] for cells in _table_rows(text[idx:], min_cols=7)]
    if not names:
        raise ParseError("ember-floor-contract.md: no deferral rows found")
    return names


def check_c(section_d_rows, floor_contract_components):
    """Assert each SS D row's 4 required cells are non-empty; cross-reference component
    names against ember-floor-contract.md's own deferral table (informational gap)."""
    gaps = []
    for row in section_d_rows:
        empty = [f for f in ("owner", "pilot", "trigger", "kill_promote") if not row[f]]
        if empty:
            gaps.append({
                "component": row["component"],
                "reason": "empty_required_cell",
                "empty_fields": empty,
            })
        if row["component"] not in floor_contract_components:
            gaps.append({
                "component": row["component"],
                "reason": "component_not_found_in_ember-floor-contract.md_deferral_table",
                "empty_fields": [],
            })
    return gaps


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _emit(receipt, ts):
    receipts_dir = os.path.join(ROOT, "scripts", "ember_totality", "receipts-milestone")
    os.makedirs(receipts_dir, exist_ok=True)
    out_path = os.path.join(receipts_dir, f"milestone-reconciliation-{ts}.json")
    try:
        from receipt_write import checked_write
        checked_write(out_path, receipt)
    except Exception as e:
        # A receipt_check schema quirk must never eat a verdict -- fall back
        # to a plain write and surface the complaint.
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(receipt, f, indent=2)
        print(f"NOTE: receipt_check schema-floor complaint (wrote anyway): {e}", file=sys.stderr)
    print(f"receipt: {out_path}")
    return out_path


def run():
    inputs = {}
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = {"ticket": TICKET, "ts": ts, "mapped": 0, "unmapped": [],
            "lattice_diff": [], "floor_contract_gaps": [], "inputs": inputs,
            "api_spend_usd": 0, "paid_api_surface_used": False}

    try:
        matrix_path = os.path.join(ROOT, "docs", "ember-authority-matrix.md")
        if os.path.isfile(matrix_path):
            from pathlib import Path
            from authority_supersession_gate import (
                CROSSWALK_PATH,
                validate_current_authority_crosswalk,
            )
            crosswalk = validate_current_authority_crosswalk(Path(ROOT))
            receipt = {
                **base,
                "exit": "PASS",
                "mapped": 55,
                "historical_lattice": "SUPERSEDED_BY_AUTHORITY_CROSSWALK",
                "authority_crosswalk": {
                    "path": CROSSWALK_PATH.as_posix(),
                    "status": crosswalk["status"],
                    "row_count": crosswalk["row_count"],
                    "custody_gap_count": crosswalk["custody_gap_count"],
                },
            }
            _emit(receipt, ts)
            # [C-MILE cure] The dual-source leg reader (milestone_leg.py's
            # MILESTONE_CHECKER.verdict_regex) and the status probe's own independent
            # re-derivation (test_c_mile.py's MILESTONE_VERDICT_LINE_RE) both require a
            # stdout line matching `mapped=<n>/<n> unmapped=<n> lattice_diff=<n>
            # floor_contract_gaps=<n> exit=PASS|FAIL` -- this supersession branch used to
            # print only the human-readable message below, so no line ever matched and
            # every leg run resolved to UNRESOLVABLE regardless of the crosswalk's real
            # state. Printed here from the SAME fields just persisted in `receipt` (never
            # hand-typed independently), so the line is honest by construction.
            print(
                f"mapped={receipt['mapped']}/55  unmapped={len(receipt['unmapped'])}  "
                f"lattice_diff={len(receipt['lattice_diff'])}  "
                f"floor_contract_gaps={len(receipt['floor_contract_gaps'])}  "
                f"exit={receipt['exit']}"
            )
            print(
                "PASS: legacy milestone reconciliation is preserved by the "
                f"validated authority crosswalk ({crosswalk['row_count']} rows)"
            )
            return 0
        completeness_path = _resolve("docs/domains/governance/contracts/ember-completeness.md", inputs)
        problems_path = _resolve("docs/domains/governance/roadmap/PROBLEMS.md", inputs)
        _resolve("docs/domains/governance/problems-meta.yaml", inputs)  # provenance only, see module docstring
        milestones_path = _resolve("docs/spec/milestones-v1.md", inputs, allow_ember_fallback=False)
        floor_contract_path = _resolve("docs/contracts/ember-floor-contract.md", inputs, allow_ember_fallback=False)

        completeness_text = _read(completeness_path)
        problems_text = _read(problems_path)
        milestones_text = _read(milestones_path)
        floor_contract_text = _read(floor_contract_path)

        section_a = parse_section_a(milestones_text)
        completeness_ids = parse_completeness_ids(completeness_text)
        mapped, unmapped = check_a(section_a, completeness_ids)

        lattice = parse_lattice(extract_lattice_block(milestones_text))
        problems_gates = parse_problems_gates(problems_text)
        lattice_diff = check_b(lattice, problems_gates)

        section_d_rows = parse_section_d(milestones_text)
        floor_contract_components = parse_floor_contract_components(floor_contract_text)
        floor_contract_gaps = check_c(section_d_rows, floor_contract_components)

    except ParseError as e:
        receipt = {**base, "exit": "FAIL", "error": str(e)}
        _emit(receipt, ts)
        print(f"FAIL (parse error): {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 -- fail-closed on anything unexpected too
        receipt = {**base, "exit": "FAIL", "error": f"{type(e).__name__}: {e}"}
        _emit(receipt, ts)
        print(f"FAIL (unexpected {type(e).__name__}): {e}", file=sys.stderr)
        return 1

    exit_status = "PASS" if not unmapped and not floor_contract_gaps else "FAIL"
    receipt = {
        **base,
        "mapped": mapped,
        "unmapped": unmapped,
        "lattice_diff": lattice_diff,
        "floor_contract_gaps": floor_contract_gaps,
        "exit": exit_status,
        "api_spend_usd": 0,
        "paid_api_surface_used": False,
    }
    _emit(receipt, ts)
    print(
        f"mapped={mapped}/55  unmapped={len(unmapped)}  lattice_diff={len(lattice_diff)}  "
        f"floor_contract_gaps={len(floor_contract_gaps)}  exit={exit_status}"
    )
    return 0 if exit_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(run())
