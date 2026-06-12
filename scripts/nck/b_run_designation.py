#!/usr/bin/env python3
"""sp-6b B-run designation resolver (part of #282).

Mechanically resolves THE ember checkpoint for the official B3 run per the
frozen rule (docs/sp6b-designation-rule-v0.md): highest-step COMPLETE
checkpoint across the named lineage dirs, inside the resolution window.
Pure function of the checkpoint dirs + clock — reads NOTHING from receipts/
(battery scores cannot reach the choice).

CLI:
  --run                 required to resolve (staged guard, house pattern)
  --write               emit receipts/b-run-designation-<ts>.json
  --checkpoints-dir D   lineage checkpoint dir (repeatable; scan order =
                        CLI order; later dir wins step-number ties)
  --now ISO8601Z        clock injection for the selftest (default: UTC now)
  --override-window     proceed outside the window; requires --deviation-note
  --deviation-note S    fp-30b-class justification recorded in the receipt
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    from nck.seat_adapter import TEMPLATE_HASH
except ImportError:
    from seat_adapter import TEMPLATE_HASH  # type: ignore[no-redef]

RULE_VERSION = "sp6b-designation-rule-v0"
RULE_DOC = Path(__file__).resolve().parent.parent.parent / "docs" / "sp6b-designation-rule-v0.md"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Frozen resolution window (UTC) — refusal outside unless registered deviation
WINDOW_START = datetime(2026, 6, 20, 0, 0, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 21, 23, 59, 59, tzinfo=timezone.utc)

DEFAULT_LINEAGE = [
    Path("B:/M/avir/eli/state/ember-eng/runs/v0-r1s1/checkpoints"),
]

_STAGED_MSG = (
    "STAGED: b_run_designation loaded but not triggered. "
    "Pass --run to resolve (and --write to record the receipt). "
    "Exit-1 is the evidence-promotion gate."
)


class DesignationRefuse(Exception):
    """Raised when the resolver cannot produce a valid designation."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_step(name: str) -> int | None:
    """step-00025000 -> 25000; None for non-checkpoint names."""
    if not name.startswith("step-"):
        return None
    try:
        return int(name[len("step-"):])
    except ValueError:
        return None


def _is_complete(ckpt_dir: Path) -> bool:
    """COMPLETE = non-empty model.pt AND parseable manifest.json."""
    model = ckpt_dir / "model.pt"
    manifest = ckpt_dir / "manifest.json"
    if not (model.is_file() and model.stat().st_size > 0 and manifest.is_file()):
        return False
    try:
        json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return True


def scan_candidates(lineage_dirs: list[Path]) -> list[dict]:
    """Enumerate candidate checkpoints across lineage dirs in scan order.

    Returns [{path, step, complete, mtime, lineage_index}] sorted by
    (step, lineage_index) — so the frozen tie-break (later dir wins) is the
    natural max().
    """
    candidates: list[dict] = []
    for li, d in enumerate(lineage_dirs):
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            step = _parse_step(entry.name)
            if step is None or not entry.is_dir():
                continue
            candidates.append({
                "path": str(entry),
                "step": step,
                "complete": _is_complete(entry),
                "mtime": entry.stat().st_mtime,
                "lineage_index": li,
            })
    candidates.sort(key=lambda c: (c["step"], c["lineage_index"]))
    return candidates


def resolve(
    lineage_dirs: list[Path],
    now: datetime,
    override_window: bool = False,
    deviation_note: str = "",
) -> dict:
    """Apply the frozen rule. Returns the designation record (no I/O writes).

    Raises DesignationRefuse on: outside-window without registered deviation,
    no candidates, or no COMPLETE candidate.
    """
    in_window = WINDOW_START <= now <= WINDOW_END
    if not in_window:
        if not override_window:
            raise DesignationRefuse(
                f"WINDOW_REFUSE: resolution time {now.isoformat()} outside frozen "
                f"window [{WINDOW_START.isoformat()} .. {WINDOW_END.isoformat()}]. "
                "Override requires --override-window + --deviation-note "
                "(fp-30b-class registered deviation)."
            )
        if not deviation_note.strip():
            raise DesignationRefuse(
                "DEVIATION_NOTE_REQUIRED: --override-window without a "
                "--deviation-note is not a registered deviation."
            )

    candidates = scan_candidates(lineage_dirs)
    if not candidates:
        raise DesignationRefuse(
            f"NO_CANDIDATES: no step-* checkpoint dirs found under "
            f"{[str(d) for d in lineage_dirs]}."
        )

    complete = [c for c in candidates if c["complete"]]
    if not complete:
        raise DesignationRefuse(
            "NO_COMPLETE_CANDIDATE: checkpoints exist but none are COMPLETE "
            "(non-empty model.pt + parseable manifest.json)."
        )

    designated = complete[-1]  # max (step, lineage_index) by sort order
    step_collision = sum(1 for c in complete if c["step"] == designated["step"]) > 1

    model_sha = _sha256_file(Path(designated["path"]) / "model.pt")

    return {
        "ticket": "SP6B-B-RUN-DESIGNATION",
        "rule_version": RULE_VERSION,
        "rule_doc_sha256": _sha256_file(RULE_DOC),
        "resolved_at": now.strftime("%Y%m%dT%H%M%SZ"),
        "window": {
            "start": WINDOW_START.strftime("%Y%m%dT%H%M%SZ"),
            "end": WINDOW_END.strftime("%Y%m%dT%H%M%SZ"),
            "in_window": in_window,
            "override": (not in_window),
            "deviation_note": deviation_note if not in_window else "",
        },
        "lineage_dirs": [str(d) for d in lineage_dirs],
        "candidates": [
            {k: c[k] for k in ("path", "step", "complete", "lineage_index")}
            for c in candidates
        ],
        "designated": {
            "path": designated["path"],
            "step": designated["step"],
            "model_pt_sha256": model_sha,
            "step_collision_flag": step_collision,
        },
        "template_hash": TEMPLATE_HASH,
        "binding": (
            "The B-run receipt must embed this receipt's sha256 and bind the "
            "SAME model_pt_sha256, or the B-run is void."
        ),
    }


def main() -> int:
    args = sys.argv[1:]
    if "--run" not in args:
        print(_STAGED_MSG)
        return 1

    lineage: list[Path] = []
    for i, a in enumerate(args):
        if a == "--checkpoints-dir":
            lineage.append(Path(args[i + 1]))
    if not lineage:
        lineage = list(DEFAULT_LINEAGE)

    if "--now" in args:
        raw = args[args.index("--now") + 1]
        now = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    override = "--override-window" in args
    note = ""
    if "--deviation-note" in args:
        note = args[args.index("--deviation-note") + 1]

    try:
        rec = resolve(lineage, now, override_window=override, deviation_note=note)
    except DesignationRefuse as e:
        print(f"DESIGNATION_REFUSE: {e}")
        return 1

    print(
        f"DESIGNATED: step-{rec['designated']['step']:08d} "
        f"sha={rec['designated']['model_pt_sha256'][:16]}... "
        f"({len(rec['candidates'])} candidates scanned)"
    )

    if "--write" in args:
        ts = rec["resolved_at"]
        out = REPO_ROOT / "receipts" / f"b-run-designation-{ts}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        print(f"RECEIPT: {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
