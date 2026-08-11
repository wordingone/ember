#!/usr/bin/env python3
# workstream_id: EMBER-02A
# goal_id: EMBER-02
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Technique-registry dispatch gate — reference implementation (#256, sp-7).

Contract: docs/contracts/registry-dispatch-gate-spec-v0.md. The daemon calls this as a
dispatch precondition (`python scripts/registry_gate.py --config <path>`);
exit 0 = dispatch may proceed, exit 1 = refused with rows named. Fail-closed:
unreadable registry or config refuses dispatch.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs" / "ledgers" / "technique-registry.jsonl"
RECEIPT_LOG = ROOT / "receipts" / "registry-gate.jsonl"

# Evidence states preserve observations without deleting research families.
# Terminal KILL/PARK/EXCLUDED/RETIRED vocabulary is intentionally illegal.
LEGAL_STATUSES = {
    "CANDIDATE",
    "TESTED_NEGATIVE",
    "TESTED_POSITIVE",
    "ADOPTED_CURRENT_CONFIG",
    "INACTIVE_CURRENT_CONFIG",
    "HISTORICAL_EVIDENCE",
    "RETEST_ELIGIBLE",
}
REQUIRED_FIELDS = {
    "id", "axis", "claim", "physics_ceiling", "proxy_protocol",
    "receipts", "measured_multiplier", "composes_with", "conflicts",
    "status", "source",
}
REQUIRED_NATIVE_CAPABILITIES = {
    "text", "image", "audio", "reasoning", "structured_tool_use"
}
POLICY_RE = re.compile(
    r"<!--\s*EMBER_AUTHORITY_V1\s*\r?\n(.*?)\r?\n-->", re.DOTALL
)

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


def normalize_config_path(raw: str, root: Path = ROOT) -> str:
    """Repo-relative form for the receipt log — never leak an absolute host
    path (#710). Under root -> forward-slash relpath; outside root (e.g. a
    temp workspace) -> `<EXTERNAL>/basename`, matching the manual
    `<TEMP_WORKSPACE>/...` redaction already used in receipts/registry-gate.jsonl.
    """
    p = Path(raw)
    abs_p = p if p.is_absolute() else (Path.cwd() / p)
    try:
        rel = abs_p.resolve().relative_to(root.resolve())
        return rel.as_posix()
    except ValueError:
        return f"<EXTERNAL>/{Path(raw).name}"


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
    adopt = [
        r["id"] for r in rows if r["status"] == "ADOPTED_CURRENT_CONFIG"
    ]
    reg = config.get("registry") or {}
    consumes = set(reg.get("consumes") or [])
    exemptions = {e.get("row_id"): e for e in (reg.get("exemptions") or [])}
    rows_by_id = {row["id"]: row for row in rows}
    unknown_consumed = sorted(consumes - set(rows_by_id))
    inactive_consumed = sorted(
        rid
        for rid in consumes.intersection(rows_by_id)
        if rows_by_id[rid]["status"] != "ADOPTED_CURRENT_CONFIG"
    )

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
    ok = not (
        missing
        or invalid_ex
        or contradicted
        or unknown_consumed
        or inactive_consumed
    )
    return {"ok": ok, "missing": missing, "invalid_exemptions": invalid_ex,
            "contradicted": contradicted, "unknown_consumed": unknown_consumed,
            "inactive_consumed": inactive_consumed,
            "warns": warns, "adopt_rows": adopt}


def check_dispatch_authority(
    config: dict, active_goal: str, next_executed_outcome: str
) -> tuple[bool, str]:
    """Config-specific authority gate; the tree-wide verifier runs separately."""
    if not isinstance(config, dict):
        return False, "config must be a JSON object"
    authority = config.get("authority")
    if not isinstance(authority, dict):
        return False, "authority object missing"
    artifact_class = authority.get("artifact_class")
    if artifact_class == "historical_only":
        return False, "historical config execution is denied"
    if authority.get("goal_id") != active_goal:
        return False, "goal_id does not match the active goal"
    if authority.get("next_executed_outcome") != next_executed_outcome:
        return False, "next_executed_outcome does not match docs/authority/GOAL.md"
    if artifact_class == "borrowed_reference":
        if authority.get("execution_authority") != "reference_only":
            return False, "borrowed reference execution_authority must be reference_only"
        if authority.get("frozen") is not True:
            return False, "borrowed reference must be frozen"
        if authority.get("lineage_ingress") is not False:
            return False, "borrowed reference lineage_ingress must be false"
        if authority.get("capability_credit") not in (None, "none"):
            return False, "borrowed reference capability_credit must be none"
        if authority.get("model_mediated_signals"):
            return False, "borrowed reference model_mediated_signals must be empty"
        return True, "frozen reference-seat authority binding passes"
    if artifact_class not in {"research_candidate", "model_milestone"}:
        return False, f"artifact_class {artifact_class!r} is not dispatchable"
    if authority.get("execution_authority") != "allowed":
        return False, "execution_authority is not allowed"
    total_parameters = authority.get("total_parameters")
    if not isinstance(total_parameters, int) or total_parameters < 3_000_000_000:
        return False, "total_parameters is below the 3B genesis boundary"
    capabilities = authority.get("native_capabilities")
    if (
        not isinstance(capabilities, list)
        or set(capabilities) != REQUIRED_NATIVE_CAPABILITIES
        or len(capabilities) != len(REQUIRED_NATIVE_CAPABILITIES)
    ):
        return False, "native_capabilities must be text,image,audio,reasoning,structured_tool_use"
    backbone = str(authority.get("published_family_backbone", "")).strip().lower()
    if backbone not in {"", "none"}:
        return False, "published_family_backbone is forbidden"
    if authority.get("model_mediated_signals"):
        return False, "model_mediated_signals must be empty"
    return True, "authority binding passes"


def load_goal_policy(root: Path = ROOT) -> dict:
    text = (root / "docs/authority/GOAL.md").read_text(encoding="utf-8")
    match = POLICY_RE.search(text)
    if not match:
        raise ValueError("docs/authority/GOAL.md EMBER_AUTHORITY_V1 block missing")
    policy = json.loads(match.group(1))
    if not isinstance(policy, dict):
        raise ValueError("docs/authority/GOAL.md authority policy must be an object")
    return policy


def load_goal_binding(root: Path = ROOT) -> tuple[str, str]:
    policy = load_goal_policy(root)
    active_goal = policy.get("active_goal_id")
    outcome = policy.get("next_executed_outcome")
    if not isinstance(active_goal, str) or not isinstance(outcome, str):
        raise ValueError("docs/authority/GOAL.md active goal binding missing")
    return active_goal, outcome


def run_authority_conservation(root: Path = ROOT) -> tuple[bool, str]:
    command = [
        sys.executable,
        str(root / "scripts" / "verify_authority_conservation.py"),
        "--root",
        str(root),
    ]
    selection = os.environ.get("EMBER_GOAL_SELECTION")
    if selection:
        command.extend(["--selection", selection])
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    detail = (result.stdout or result.stderr).strip()
    return result.returncode == 0, detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--no-receipt", action="store_true")
    args = ap.parse_args()
    try:
        rows = load_registry()
        config_path = Path(args.config).resolve()
        config_path.relative_to((ROOT / "configs").resolve())
        config = json.loads(config_path.read_text(encoding="utf-8"))
        policy = load_goal_policy()
        active_goal = policy.get("active_goal_id")
        next_outcome = policy.get("next_executed_outcome")
        if not isinstance(active_goal, str) or not isinstance(next_outcome, str):
            raise ValueError("docs/authority/GOAL.md active goal binding missing")
    except Exception as exc:  # fail-closed
        print(f"REGISTRY_GATE FAIL (fail-closed): {exc}")
        return 1
    authority_ok, authority_reason = check_dispatch_authority(
        config, active_goal, next_outcome
    )
    if not authority_ok:
        print(f"REGISTRY_GATE FAIL (authority): {authority_reason}")
        return 1
    if policy.get("authority_only_goal") is True:
        print("REGISTRY_GATE FAIL (authority): active goal is authority-only; all dispatch is denied")
        return 1
    conservation_ok, conservation_detail = run_authority_conservation()
    if not conservation_ok:
        print(f"REGISTRY_GATE FAIL (conservation): {conservation_detail}")
        return 1
    verdict = check(config, rows)
    line = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "goal_id": active_goal,
            "next_executed_outcome": next_outcome,
            "config_path": normalize_config_path(args.config), **verdict}
    if not args.no_receipt:
        RECEIPT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RECEIPT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
    print(f"REGISTRY_GATE {'PASS' if verdict['ok'] else 'FAIL'}: {json.dumps(verdict)}")
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
