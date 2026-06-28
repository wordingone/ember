#!/usr/bin/env python3
"""Technique-registry dispatch gate — reference implementation (#256, sp-7).

Contract: docs/registry-dispatch-gate-spec-v0.md. The daemon calls this as a
dispatch precondition (`python scripts/registry_gate.py --config <path>`);
exit 0 = dispatch may proceed, exit 1 = refused with rows named. Fail-closed:
unreadable registry or config refuses dispatch.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs" / "technique-registry.jsonl"
RECEIPT_LOG = ROOT / "receipts" / "registry-gate.jsonl"

LEGAL_STATUSES = {"CANDIDATE", "TESTED", "ADOPT", "KILL", "WATCH-NEGATIVE"}
REQUIRED_FIELDS = {
    "id", "axis", "claim", "physics_ceiling", "proxy_protocol",
    "receipts", "measured_multiplier", "composes_with", "conflicts",
    "status", "source",
}

# row id -> (key-substring, check(value)) — corroboration predicates over the
# flattened config. Missing key = WARN; present-and-contradicting = FAIL.
def _contains(sub):
    return lambda v: isinstance(v, str) and sub in v.lower()

PREDICATES = {
    "muon": ("optimizer", _contains("muon")),
    "wsd-schedule": ("sched", _contains("wsd")),
    "qat": ("qat", lambda v: bool(v)),
    "governor-pacing": (
        "vram_fraction",
        lambda v: isinstance(v, (int, float)) and v <= 0.85,
    ),
}


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, val in obj.items():
            out.update(flatten(val, f"{prefix}{k}." if prefix else f"{k}."))
    else:
        out[prefix.rstrip(".")] = obj
    return out


def load_registry(path=REGISTRY):
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            raise ValueError(f"registry line {n} missing fields {sorted(missing)}")
        if row["status"] not in LEGAL_STATUSES:
            raise ValueError(f"registry line {n} illegal status {row['status']!r}")
        rows.append(row)
    return rows


def check(config: dict, rows, today=None, root=ROOT):
    """Pure verdict — no I/O besides exemption receipt_path existence."""
    today = today or dt.date.today()
    adopt = [r["id"] for r in rows if r["status"] == "ADOPT"]
    reg = config.get("registry") or {}
    consumes = set(reg.get("consumes") or [])
    exemptions = {e.get("row_id"): e for e in (reg.get("exemptions") or [])}

    missing, invalid_ex, contradicted, warns = [], [], [], []
    for rid in adopt:
        if rid in consumes:
            key_sub, pred = PREDICATES.get(rid, (None, None))
            if key_sub:
                hits = [k for k in flatten(config) if key_sub in k.lower()
                        and not k.startswith("registry.")]
                if not hits:
                    warns.append(f"{rid}: no '{key_sub}' key to corroborate")
                elif not any(pred(flatten(config)[k]) for k in hits):
                    contradicted.append(rid)
            continue
        ex = exemptions.get(rid)
        if ex is None:
            missing.append(rid)
            continue
        try:
            expired = dt.date.fromisoformat(str(ex.get("expiry"))) < today
        except ValueError:
            expired = True
        receipt_ok = bool(ex.get("receipt_path")) and (root / ex["receipt_path"]).exists()
        if expired or not receipt_ok or not ex.get("reason"):
            invalid_ex.append(rid)
    ok = not (missing or invalid_ex or contradicted)
    return {"ok": ok, "missing": missing, "invalid_exemptions": invalid_ex,
            "contradicted": contradicted, "warns": warns, "adopt_rows": adopt}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--no-receipt", action="store_true")
    args = ap.parse_args()
    try:
        rows = load_registry()
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except Exception as exc:  # fail-closed
        print(f"REGISTRY_GATE FAIL (fail-closed): {exc}")
        return 1
    verdict = check(config, rows)
    line = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "config_path": args.config, **verdict}
    if not args.no_receipt:
        RECEIPT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RECEIPT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
    print(f"REGISTRY_GATE {'PASS' if verdict['ok'] else 'FAIL'}: {json.dumps(verdict)}")
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
