#!/usr/bin/env python3
"""sp-6 duty-battery selftest (#269, both halves).

Content half: 20 episodes, 4 families x 5, unique ids, verbs from the closed
enum, target patterns compile. Encoding half: per-episode event streams match
the #260 event-loop shapes (source/kind/payload schemas), deterministic
synthetic timestamps, {root}-templated paths only (no machine paths),
fixture<->payload consistency. Fail-closed.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

BATTERY = Path(__file__).resolve().parent.parent / "docs" / "sp6-duty-battery.jsonl"
ENCODINGS = Path(__file__).resolve().parent.parent / "docs" / "sp6-duty-battery-encodings.jsonl"

# #260 event-loop shape contract (scripts/nck/event_loop.py):
# Event(source, kind, payload, ts). MailSource is stub pending #259 — the
# mail_arrived shape below is the FROZEN interface #259 must emit.
SOURCE_KINDS = {
    "mail": {"mail_arrived"},
    "schedule": {"tick_due"},
    "job_receipt": {"receipt_arrived"},
    "file_watch": {"file_new", "file_changed"},
}
PAYLOAD_REQUIRED = {
    "mail": {"id", "from", "subject", "body", "channel"},
    "schedule": {"id", "interval_s"},
    "job_receipt": {"path", "data"},
    "file_watch": {"path", "size"},
}
FAMILY_SOURCE = {
    "mail-triage": "mail",
    "receipt-gating": "job_receipt",
    "schedule": "schedule",
    "file-hygiene": "file_watch",
}
TS_RE = re.compile(r"^20260622T\d{6}Z$")
MACHINE_PATH_RE = re.compile(r"[A-Za-z]:[\\/]|/mnt/|/home/|/Users/")

VERB_ENUM = {
    "reply", "ack-begin", "challenge", "no-action", "clarify",
    "gate-pass", "gate-fail", "dedup", "escalate",
    "execute-due", "heartbeat-only", "monitor", "gate-then-next",
    "clear-lock", "repair-escalate", "flag-missing", "report", "clean",
}
FAMILIES = {"mail-triage", "receipt-gating", "schedule", "file-hygiene"}
REQUIRED = {"id", "family", "event", "expected_verb", "target_pattern", "notes"}


def main() -> int:
    fails = []
    rows = [json.loads(l) for l in BATTERY.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(rows) != 20:
        fails.append(f"expected 20 episodes, got {len(rows)}")
    ids = [r.get("id") for r in rows]
    if len(set(ids)) != len(ids):
        fails.append(f"duplicate ids: {[i for i, c in Counter(ids).items() if c > 1]}")
    fam_counts = Counter(r.get("family") for r in rows)
    if set(fam_counts) != FAMILIES or any(v != 5 for v in fam_counts.values()):
        fails.append(f"family balance wrong: {dict(fam_counts)} (need 4 families x 5)")
    for r in rows:
        missing = REQUIRED - set(r)
        if missing:
            fails.append(f"{r.get('id','?')}: missing fields {sorted(missing)}")
        if r.get("expected_verb") not in VERB_ENUM:
            fails.append(f"{r.get('id')}: verb {r.get('expected_verb')!r} not in enum")
        try:
            re.compile(r.get("target_pattern", ""))
        except re.error as exc:
            fails.append(f"{r.get('id')}: target_pattern does not compile: {exc}")
    # selectivity episodes (correct answer = no outward action) must exist
    silent = [r["id"] for r in rows if r["expected_verb"] in {"no-action", "heartbeat-only", "dedup", "clean"}]
    if len(silent) < 3:
        fails.append(f"need >=3 silence-correct episodes (selectivity), got {silent}")

    # ---- encoding half ----
    enc_rows = [json.loads(l) for l in ENCODINGS.read_text(encoding="utf-8").splitlines() if l.strip()]
    enc_by_id = {e.get("id"): e for e in enc_rows}
    battery_ids = set(ids)
    if set(enc_by_id) != battery_ids:
        fails.append(f"encoding ids != battery ids: only-enc={sorted(set(enc_by_id)-battery_ids)} "
                     f"only-battery={sorted(battery_ids-set(enc_by_id))}")
    fam_by_id = {r["id"]: r["family"] for r in rows}
    for e in enc_rows:
        eid = e.get("id", "?")
        events = e.get("events", [])
        fixtures = e.get("fixtures", [])
        want_n = 2 if eid == "M5" else 1
        if len(events) != want_n:
            fails.append(f"{eid}: expected {want_n} event(s), got {len(events)}")
        # no machine-absolute paths anywhere in the row
        blob = json.dumps(e)
        if MACHINE_PATH_RE.search(blob):
            fails.append(f"{eid}: machine-absolute path found in row (must be {{root}}-templated)")
        want_source = FAMILY_SOURCE.get(fam_by_id.get(eid, ""), None)
        fixture_relpaths = {f.get("relpath") for f in fixtures}
        for ev in events:
            src, kind, ts = ev.get("source"), ev.get("kind"), ev.get("ts", "")
            payload = ev.get("payload", {})
            if src not in SOURCE_KINDS:
                fails.append(f"{eid}: unknown source {src!r}")
                continue
            if kind not in SOURCE_KINDS[src]:
                fails.append(f"{eid}: kind {kind!r} invalid for source {src!r}")
            if want_source and src != want_source:
                fails.append(f"{eid}: family {fam_by_id[eid]!r} must encode source "
                             f"{want_source!r}, got {src!r}")
            if not TS_RE.match(ts):
                fails.append(f"{eid}: ts {ts!r} not a synthetic 20260622T......Z stamp")
            missing_keys = PAYLOAD_REQUIRED[src] - set(payload)
            if missing_keys:
                fails.append(f"{eid}: payload missing {sorted(missing_keys)} for source {src!r}")
            # path-bearing sources: the watched/parsed file must exist as a fixture
            if src in ("file_watch", "job_receipt"):
                p = payload.get("path", "")
                if not p.startswith("{root}/"):
                    fails.append(f"{eid}: payload.path {p!r} must start with '{{root}}/'")
                elif p[len("{root}/"):] not in fixture_relpaths:
                    fails.append(f"{eid}: payload.path {p!r} has no matching fixture")
            # job_receipt: inline data must equal the fixture file's content
            if src == "job_receipt":
                rel = payload.get("path", "")[len("{root}/"):]
                fx = next((f for f in fixtures if f.get("relpath") == rel), None)
                if fx is not None and fx.get("content_json") != payload.get("data"):
                    fails.append(f"{eid}: payload.data != fixture content_json for {rel}")
        for fx in fixtures:
            rel = fx.get("relpath", "")
            if not rel or rel.startswith("{root}") or rel.startswith("/") or ":" in rel:
                fails.append(f"{eid}: fixture relpath {rel!r} must be sandbox-relative")
            if ("content_json" in fx) == ("content_text" in fx):
                fails.append(f"{eid}: fixture {rel!r} needs exactly one of content_json/content_text")
            off = fx.get("mtime_offset_s", 0)
            if not isinstance(off, int) or off > 0:
                fails.append(f"{eid}: fixture {rel!r} mtime_offset_s must be int <= 0")

    if fails:
        print("SP6_BATTERY_SELFTEST FAIL:")
        for f in fails:
            print(f"  - {f}")
        return 1
    n_events = sum(len(e.get("events", [])) for e in enc_rows)
    n_fixtures = sum(len(e.get("fixtures", [])) for e in enc_rows)
    print(f"SP6_BATTERY_SELFTEST PASS: 20 episodes, 4x5 families, "
          f"{len(silent)} silence-correct, all patterns compile; "
          f"encodings: {n_events} events, {n_fixtures} fixtures, "
          f"shapes match #260 event-loop contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
