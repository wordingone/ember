#!/usr/bin/env python3
"""Fail-closed selftest for the sp-6b replay rig (#282).

Validates RIG MECHANICS with fabricated action streams — NOT stub_core duty
performance. stub_core will NOT pass most episodes; that is expected and is
NOT what this selftest asserts.

Cases:
  (a) battery + encodings load and join 20/20
  (b) fixture materialization byte-correct: R1 receipt JSON and F2 corrupt text
  (c) {root} substitution complete — no literal '{root}' survives; pinned ts preserved
  (d) mtime offsets applied: F1's lock file mtime == REPLAY_EPOCH - 7200 (±2s)
  (e) determinism: verify_determinism() passes (two runs, identical streams+scores)
  (f) silence scoring: fabricated empty stream passes M4; OUTWARD action fails it
  (g) action scoring: fabricated 'challenge' + to==from passes M3 ('sender'); wrong verb fails
  (h) purity: receipts/ listing identical before and after the whole selftest

Exit 0 + "SP6B_REPLAY_RIG_SELFTEST PASS" on all pass.
Exit 1 + named FAILs on any failure.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure the nck package is importable regardless of cwd
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_NCK_DIR = Path(__file__).resolve().parent
if str(_NCK_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_NCK_DIR.parent))

from nck.replay_rig import (
    REPLAY_EPOCH,
    OUTWARD_VERBS,
    RigRefuse,
    join_battery_encodings,
    load_battery,
    load_encodings,
    materialize,
    build_events,
    replay_episode,
    score_episode,
    run_battery,
    verify_determinism,
    _make_noop_registry,
)
from nck.event_loop import Action, Event, stub_core


def _receipts_listing() -> frozenset[str]:
    """Return frozenset of filenames in the receipts/ directory."""
    receipts_dir = Path(__file__).resolve().parent.parent.parent / "receipts"
    if not receipts_dir.is_dir():
        return frozenset()
    return frozenset(receipts_dir.iterdir().__iter__().__class__ and
                     [f.name for f in receipts_dir.iterdir()])


def _receipts_listing_v2() -> frozenset[str]:
    receipts_dir = Path(__file__).resolve().parent.parent.parent / "receipts"
    if not receipts_dir.is_dir():
        return frozenset()
    return frozenset(f.name for f in receipts_dir.iterdir())


def main() -> int:
    fails: list[str] = []

    # Snapshot receipts dir BEFORE any tests
    receipts_before = _receipts_listing_v2()

    # -----------------------------------------------------------------------
    # (a) battery + encodings load and join 20/20
    # -----------------------------------------------------------------------
    try:
        battery = load_battery()
        if len(battery) != 20:
            fails.append(f"(a) load_battery: expected 20 rows, got {len(battery)}")
        encodings = load_encodings()
        if len(encodings) != 20:
            fails.append(f"(a) load_encodings: expected 20 rows, got {len(encodings)}")
        episodes = join_battery_encodings()
        if len(episodes) != 20:
            fails.append(f"(a) join: expected 20 merged episodes, got {len(episodes)}")
        # Verify each episode has both battery and encoding fields
        for ep in episodes:
            if "expected_verb" not in ep:
                fails.append(f"(a) join: episode {ep.get('id')!r} missing 'expected_verb'")
            if "events" not in ep:
                fails.append(f"(a) join: episode {ep.get('id')!r} missing 'events'")
    except Exception as exc:
        fails.append(f"(a) exception during load/join: {exc}")

    # -----------------------------------------------------------------------
    # (b) fixture materialization byte-correct
    # -----------------------------------------------------------------------
    try:
        episodes = join_battery_encodings()
        ep_by_id = {ep["id"]: ep for ep in episodes}

        # R1: materialized receipt file's parsed JSON == encoding's content_json
        r1 = ep_by_id["R1"]
        with tempfile.TemporaryDirectory(prefix="sp6b-selftest-r1-") as tmpdir:
            materialize(r1, tmpdir)
            # Find the receipt fixture (first fixture with content_json)
            r1_receipt_fx = next(
                (fx for fx in r1["fixtures"] if "content_json" in fx
                 and "receipts/" in fx.get("relpath", "")),
                None,
            )
            if r1_receipt_fx is None:
                fails.append("(b) R1: no receipt fixture with content_json found")
            else:
                dest = Path(tmpdir) / r1_receipt_fx["relpath"]
                parsed = json.loads(dest.read_text(encoding="utf-8"))
                if parsed != r1_receipt_fx["content_json"]:
                    fails.append(
                        f"(b) R1: materialized JSON != content_json.\n"
                        f"  got:      {parsed!r}\n"
                        f"  expected: {r1_receipt_fx['content_json']!r}"
                    )

        # F2: corrupt file is byte-identical to content_text
        f2 = ep_by_id["F2"]
        with tempfile.TemporaryDirectory(prefix="sp6b-selftest-f2-") as tmpdir:
            materialize(f2, tmpdir)
            f2_fx = next(
                (fx for fx in f2["fixtures"] if "content_text" in fx),
                None,
            )
            if f2_fx is None:
                fails.append("(b) F2: no content_text fixture found")
            else:
                dest = Path(tmpdir) / f2_fx["relpath"]
                on_disk = dest.read_text(encoding="utf-8")
                if on_disk != f2_fx["content_text"]:
                    fails.append(
                        f"(b) F2: materialized text != content_text.\n"
                        f"  got:      {on_disk!r}\n"
                        f"  expected: {f2_fx['content_text']!r}"
                    )
    except Exception as exc:
        fails.append(f"(b) exception during materialization check: {exc}")

    # -----------------------------------------------------------------------
    # (c) {root} substitution complete — no '{root}' in built event payloads;
    #     pinned ts preserved verbatim
    # -----------------------------------------------------------------------
    try:
        episodes = join_battery_encodings()
        for ep in episodes:
            with tempfile.TemporaryDirectory(prefix="sp6b-selftest-root-") as tmpdir:
                events = build_events(ep, tmpdir)
                for ev in events:
                    dumped = json.dumps(ev.payload)
                    if "{root}" in dumped:
                        fails.append(
                            f"(c) episode {ep['id']!r}: literal '{{root}}' remains "
                            f"in event payload after substitution: {dumped[:100]!r}"
                        )
                # Verify pinned ts preserved verbatim
                for ev_row, ev in zip(ep.get("events", []), events):
                    if ev.ts != ev_row["ts"]:
                        fails.append(
                            f"(c) episode {ep['id']!r}: ts not verbatim. "
                            f"expected {ev_row['ts']!r}, got {ev.ts!r}"
                        )
    except Exception as exc:
        fails.append(f"(c) exception during root-substitution check: {exc}")

    # -----------------------------------------------------------------------
    # (d) mtime offsets applied: F1's lock file mtime == REPLAY_EPOCH - 7200 (±2s)
    # -----------------------------------------------------------------------
    try:
        episodes = join_battery_encodings()
        f1 = next(ep for ep in episodes if ep["id"] == "F1")
        # Find the lock fixture (mtime_offset_s == -7200)
        lock_fx = next(
            (fx for fx in f1["fixtures"] if fx.get("mtime_offset_s") == -7200),
            None,
        )
        if lock_fx is None:
            fails.append("(d) F1: no fixture with mtime_offset_s == -7200 found")
        else:
            with tempfile.TemporaryDirectory(prefix="sp6b-selftest-f1-") as tmpdir:
                materialize(f1, tmpdir)
                dest = Path(tmpdir) / lock_fx["relpath"]
                actual_mtime = dest.stat().st_mtime
                expected_mtime = REPLAY_EPOCH - 7200
                if abs(actual_mtime - expected_mtime) > 2.0:
                    fails.append(
                        f"(d) F1: lock file mtime off by "
                        f"{abs(actual_mtime - expected_mtime):.1f}s. "
                        f"expected {expected_mtime}, got {actual_mtime}"
                    )
    except Exception as exc:
        fails.append(f"(d) exception during mtime check: {exc}")

    # -----------------------------------------------------------------------
    # (e) determinism: verify_determinism() passes
    # -----------------------------------------------------------------------
    try:
        verify_determinism(stub_core)
        # If it returns True without raising, it passed
    except AssertionError as ae:
        fails.append(f"(e) determinism FAIL: {ae}")
    except Exception as exc:
        fails.append(f"(e) exception during determinism check: {exc}")

    # -----------------------------------------------------------------------
    # (f) silence scoring
    # -----------------------------------------------------------------------
    try:
        episodes = join_battery_encodings()
        m4 = next(ep for ep in episodes if ep["id"] == "M4")

        # Empty action stream → PASS for M4
        score_empty = score_episode(m4, [])
        if not score_empty["pass"]:
            fails.append(
                f"(f) M4 with empty action stream should PASS silence; "
                f"got: {score_empty['reason']}"
            )

        # An OUTWARD action → FAIL for M4
        outward_verb = next(iter(OUTWARD_VERBS))  # pick any outward verb
        outward_action = Action(verb=outward_verb, args={})
        score_outward = score_episode(m4, [outward_action])
        if score_outward["pass"]:
            fails.append(
                f"(f) M4 with OUTWARD action ({outward_verb!r}) should FAIL silence; "
                f"got PASS"
            )

        # Non-outward action (e.g., heartbeat_touch internal) → PASS for M4
        noop_action = Action(verb="heartbeat_touch", args={})
        score_noop = score_episode(m4, [noop_action])
        if not score_noop["pass"]:
            fails.append(
                f"(f) M4 with non-outward action (heartbeat_touch) should PASS silence; "
                f"got: {score_noop['reason']}"
            )
    except Exception as exc:
        fails.append(f"(f) exception during silence scoring check: {exc}")

    # -----------------------------------------------------------------------
    # (g) action scoring: 'challenge' + to==from passes M3; wrong verb fails
    # -----------------------------------------------------------------------
    try:
        episodes = join_battery_encodings()
        m3 = next(ep for ep in episodes if ep["id"] == "M3")

        # M3 expects: verb='challenge', target_pattern='^sender$'
        # Build an event with 'from' = 'eli' (from the encoding)
        m3_first_ev_row = m3["events"][0]
        m3_from = m3_first_ev_row["payload"]["from"]  # 'eli'

        # Fabricate an action: verb='challenge', args={'to': m3_from}
        # → normalized target should be 'sender' (to == event payload 'from')
        challenge_action = Action(verb="challenge", args={"to": m3_from})

        with tempfile.TemporaryDirectory(prefix="sp6b-selftest-m3-") as tmpdir:
            score_ok = score_episode(m3, [challenge_action], sandbox_dir=tmpdir)
        if not score_ok["pass"]:
            fails.append(
                f"(g) M3 with challenge+to=={m3_from!r} should PASS "
                f"(normalized='sender', pattern='^sender$'); got: {score_ok['reason']}"
            )

        # Wrong verb (e.g., 'reply') → FAIL
        wrong_action = Action(verb="reply", args={"to": m3_from})
        with tempfile.TemporaryDirectory(prefix="sp6b-selftest-m3b-") as tmpdir:
            score_bad = score_episode(m3, [wrong_action], sandbox_dir=tmpdir)
        if score_bad["pass"]:
            fails.append(
                f"(g) M3 with wrong verb 'reply' should FAIL; got PASS"
            )

        # Correct verb but wrong 'to' (not sender) → FAIL
        wrong_to_action = Action(verb="challenge", args={"to": "mira"})
        with tempfile.TemporaryDirectory(prefix="sp6b-selftest-m3c-") as tmpdir:
            score_wrong_to = score_episode(m3, [wrong_to_action], sandbox_dir=tmpdir)
        if score_wrong_to["pass"]:
            fails.append(
                f"(g) M3 with challenge+to=='mira' (not sender) should FAIL; got PASS. "
                f"normalized target: {score_wrong_to['emitted']}"
            )
    except Exception as exc:
        fails.append(f"(g) exception during action scoring check: {exc}")

    # -----------------------------------------------------------------------
    # (h) purity: receipts/ listing identical before and after selftest
    # -----------------------------------------------------------------------
    receipts_after = _receipts_listing_v2()
    if receipts_after != receipts_before:
        new_files = sorted(receipts_after - receipts_before)
        removed_files = sorted(receipts_before - receipts_after)
        fails.append(
            f"(h) PURITY FAIL: receipts/ changed during selftest. "
            f"new={new_files}, removed={removed_files}"
        )

    # -----------------------------------------------------------------------
    # Result
    # -----------------------------------------------------------------------
    if fails:
        print("SP6B_REPLAY_RIG_SELFTEST FAIL:")
        for f in fails:
            print(f"  - {f}")
        return 1

    print("SP6B_REPLAY_RIG_SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
