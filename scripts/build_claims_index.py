#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
Build receipts/INDEX.jsonl and receipts/CLAIMS.md from receipts/**/*.json.

Additive, read-only w.r.t. the receipts corpus: it never renames, moves, or
deletes a receipt. Every field in the index is one already present in the
receipt's own JSON schema (ticket / ts / issue / verdict / pass, plus any key
whose name contains "claim" or "condition") — this script does not invent a
semantic mapping onto GOAL.md board conditions, since receipt payloads can
legitimately contain unrelated substrings that collide with condition IDs
(e.g. SMILES ring-closure labels "C1".."C4" inside dataset-preview fields).

Usage:
    python scripts/build_claims_index.py [--receipts-dir PATH]

Regenerate after adding receipts. Output is sorted and byte-identical across
runs given the same input, so regeneration diffs cleanly in review.
"""

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_RECEIPTS_DIR = Path(__file__).resolve().parent.parent / "receipts"

# Optional era annotation (docs/spec/issue-reference-v1.md, R4). Off by default:
# when no --sidecar is supplied, output is byte-identical to the pre-R4 schema,
# so the existing output contract is untouched. Importing the normalizer is
# best-effort so this script never hard-fails if it is run standalone.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from normalize_issue_reference import Sidecar, normalize
except Exception:  # noqa: BLE001 — annotation is strictly optional
    Sidecar = None
    normalize = None

CLAIM_OR_CONDITION_FIELD = re.compile(r"(claim|condition)", re.IGNORECASE)
DIRECT_FIELDS = ("ticket", "ts", "issue", "verdict", "pass")
MAX_VALUE_CHARS = 200
MAX_CLAIM_FIELD_CHARS = 120

# Fallback encodings tried in order after utf-8 fails to decode a receipt.
FALLBACK_ENCODINGS = ("utf-8-sig", "utf-16")


def _compact(value, limit=MAX_VALUE_CHARS):
    """Render any JSON value as a short, deterministic single-line string."""
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        text = "true" if value else "false"
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _normalize_issue(value) -> "str | None":
    if value is None:
        return None
    text = str(value).strip()
    if text.startswith("#"):
        text = text[1:]
    return text or None


def load_json_lenient(path: Path):
    """Return (data, error). Never raises — tries a small set of encodings."""
    raw = path.read_bytes()
    last_error = None
    for encoding in ("utf-8",) + FALLBACK_ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        try:
            return json.loads(text), None
        except json.JSONDecodeError as exc:
            last_error = exc
            # A decode succeeded but parse failed — a different encoding
            # won't fix broken JSON, so stop trying further encodings.
            break
    return None, last_error


def build_row(rel_path: str, data: dict) -> "dict | None":
    row = {"path": rel_path}

    if "ticket" in data:
        row["ticket"] = data["ticket"]
    if "ts" in data:
        row["ts"] = data["ts"]
    if "issue" in data:
        normalized = _normalize_issue(data["issue"])
        if normalized is not None:
            row["issue"] = normalized
    if "verdict" in data:
        row["verdict"] = _compact(data["verdict"])
    if isinstance(data.get("pass"), bool):
        row["pass"] = data["pass"]

    claim_fields = {
        key: _compact(val, MAX_CLAIM_FIELD_CHARS)
        for key, val in data.items()
        if key not in DIRECT_FIELDS and CLAIM_OR_CONDITION_FIELD.search(key)
    }
    if claim_fields:
        row["claim_fields"] = dict(sorted(claim_fields.items()))

    informative = any(k in row for k in ("ticket", "issue", "verdict", "pass", "claim_fields"))
    return row if informative else None


def annotate_eras(rows, sidecar) -> None:
    """Add an ``era`` field to each row that carries an ``issue`` number.

    Uses the issue-reference normalizer in LENIENT mode: an in-range or
    unmappable number becomes ``unknown:<n>`` rather than failing the whole
    index build. This is purely additive — rows without an ``issue`` are
    untouched, and the function is only called when a sidecar is supplied.
    """
    if normalize is None:
        return
    for row in rows:
        issue = row.get("issue")
        if issue is None:
            continue
        canonical = normalize(str(issue), sidecar, strict=False)
        row["era"] = canonical.split(":", 1)[0]


def build_index(receipts_dir: Path):
    """Scan receipts_dir/**/*.json and return (rows, stats)."""
    receipts_dir = Path(receipts_dir)
    files = sorted(receipts_dir.rglob("*.json"))

    rows = []
    stats = {"scanned": 0, "indexed": 0, "unparseable": 0, "non_dict": 0, "non_informative": 0}

    for file_path in files:
        stats["scanned"] += 1
        data, error = load_json_lenient(file_path)
        if error is not None:
            stats["unparseable"] += 1
            continue
        if not isinstance(data, dict):
            stats["non_dict"] += 1
            continue

        rel_path = file_path.relative_to(receipts_dir.parent).as_posix()
        row = build_row(rel_path, data)
        if row is None:
            stats["non_informative"] += 1
            continue

        rows.append(row)
        stats["indexed"] += 1

    rows.sort(key=lambda r: r["path"])
    return rows, stats


def render_index_jsonl(rows) -> str:
    lines = [json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows]
    return "\n".join(lines) + ("\n" if lines else "")


def render_claims_md(rows) -> str:
    by_issue: "dict[str, list[dict]]" = {}
    by_ticket: "dict[str, list[dict]]" = {}
    for row in rows:
        if row.get("issue"):
            by_issue.setdefault(row["issue"], []).append(row)
        if row.get("ticket"):
            by_ticket.setdefault(row["ticket"], []).append(row)

    lines = [
        "# Claims index",
        "",
        "Generated by `scripts/build_claims_index.py` from the `ticket` / `issue` / "
        "`verdict` / `pass` fields, plus any key whose name contains `claim` or "
        "`condition`, already present in each receipt's own JSON schema. This is "
        "derived output — do not hand-edit. Regenerate with:",
        "",
        "```",
        "python scripts/build_claims_index.py",
        "```",
        "",
        f"Rows indexed: {len(rows)}. Machine-readable form: `receipts/INDEX.jsonl`.",
        "",
        "## By GitHub issue",
        "",
    ]

    if by_issue:
        for issue in sorted(by_issue, key=lambda x: (len(x), x)):
            lines.append(f"### #{issue}")
            for row in sorted(by_issue[issue], key=lambda r: r["path"]):
                lines.append(f"- `{row['path']}`")
            lines.append("")
    else:
        lines.append("_none found_")
        lines.append("")

    lines.append("## By ticket")
    lines.append("")
    for ticket in sorted(by_ticket):
        ticket_rows = sorted(by_ticket[ticket], key=lambda r: r["path"])
        verdicts = sorted({r["verdict"] for r in ticket_rows if "verdict" in r})
        lines.append(f"### {ticket}")
        if verdicts:
            lines.append(f"verdict(s): {'; '.join(verdicts)}")
        for row in ticket_rows:
            lines.append(f"- `{row['path']}`")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def write_outputs(receipts_dir: Path, rows) -> None:
    receipts_dir = Path(receipts_dir)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    (receipts_dir / "INDEX.jsonl").write_text(render_index_jsonl(rows), encoding="utf-8", newline="\n")
    (receipts_dir / "CLAIMS.md").write_text(render_claims_md(rows), encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--receipts-dir", default=str(DEFAULT_RECEIPTS_DIR), help="Path to the receipts/ directory")
    parser.add_argument(
        "--sidecar",
        default=None,
        help="Optional issue-reference sidecar JSON (docs/spec/issue-reference-v1.md). "
        "When supplied, each indexed row with an issue number gains an 'era' field. "
        "Default output (no --sidecar) is byte-identical to the pre-R4 schema.",
    )
    args = parser.parse_args(argv)

    receipts_dir = Path(args.receipts_dir).resolve()
    rows, stats = build_index(receipts_dir)
    if args.sidecar:
        if Sidecar is None:
            parser.error("--sidecar requested but normalize_issue_reference is unavailable")
        annotate_eras(rows, Sidecar.from_path(args.sidecar))
    write_outputs(receipts_dir, rows)

    print(
        "scanned={scanned} indexed={indexed} unparseable={unparseable} "
        "non_dict={non_dict} non_informative={non_informative}".format(**stats)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
