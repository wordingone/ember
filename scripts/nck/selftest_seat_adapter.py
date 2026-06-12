#!/usr/bin/env python3
"""Fail-closed selftest for the sp-6c seat adapter (#307).

Validates ADAPTER MECHANICS with scripted generate_fns — no model is loaded.

Cases:
  (a) TEMPLATE_HASH matches the pinned literal (template freeze: any edit to
      a frozen constant must change this file in the same diff)
  (b) prompt determinism + machine-invariance: the same episode materialized
      into two DIFFERENT tempdirs yields byte-identical prompts
  (c) parser: well-formed multi-action text -> ordered actions with args;
      {root} substituted into sandbox paths
  (d) parser silence: prose/malformed/non-enum-verb text -> zero actions
  (e) anti-spray cap: more than MAX_ACTIONS_PER_EVENT lines -> cap enforced
  (f) end-to-end action episode via the rig (M3): correct scripted seat
      scores PASS, wrong-verb seat scores FAIL
  (g) end-to-end silence episode via the rig (M4): prose-only seat PASS,
      outward-spray seat FAIL
  (h) pinned mtimes: materialize() pins offset-0 fixtures to REPLAY_EPOCH
      and F1's lock to REPLAY_EPOCH-7200 (age_s deterministic in prompts)
  (i) deictic guard: to='sender' not matching the actual sender normalizes
      to 'literal-sender' (cannot game '^sender$')

Exit 0 + "SP6C_SEAT_ADAPTER_SELFTEST PASS" on all pass.
Exit 1 + named FAILs on any failure.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Ensure the nck package is importable regardless of cwd
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from nck.seat_adapter import (
    MAX_ACTIONS_PER_EVENT,
    TEMPLATE_HASH,
    VERB_ENUM,
    build_prompt,
    make_seat_core,
    parse_actions,
)
from nck.replay_rig import (
    REPLAY_EPOCH,
    _normalize_target,
    build_events,
    join_battery_encodings,
    materialize,
    replay_episode,
    score_episode,
)
from nck.event_loop import Action, Event

# Pinned at freeze. Any change to a frozen template constant changes this
# hash; updating the pin here is the visible registered-deviation diff.
PINNED_TEMPLATE_HASH = "0a085406cff23321fc71f3e1a50a6f64b79a72fe69498339c4b4752f90b480f9"


def main() -> int:
    fails: list[str] = []
    episodes = {ep["id"]: ep for ep in join_battery_encodings()}

    # (a) template hash pin
    if TEMPLATE_HASH != PINNED_TEMPLATE_HASH:
        fails.append(
            f"(a) TEMPLATE_HASH {TEMPLATE_HASH} != pinned {PINNED_TEMPLATE_HASH} — "
            "template constants changed without updating the pin"
        )

    # (b) prompt determinism + machine-invariance across different sandboxes
    ep_f1 = episodes["F1"]
    with tempfile.TemporaryDirectory(prefix="sp6c-a-") as dir_a, \
            tempfile.TemporaryDirectory(prefix="sp6c-b-") as dir_b:
        materialize(ep_f1, dir_a)
        materialize(ep_f1, dir_b)
        ev_a = build_events(ep_f1, dir_a)[0]
        ev_b = build_events(ep_f1, dir_b)[0]
        p_a1 = build_prompt(ev_a, dir_a)
        p_a2 = build_prompt(ev_a, dir_a)
        p_b = build_prompt(ev_b, dir_b)
        if p_a1 != p_a2:
            fails.append("(b) same sandbox, two renders differ — nondeterministic prompt")
        if p_a1 != p_b:
            fails.append(
                "(b) different tempdirs yield different prompts — sandbox path "
                "leaks into the prompt (machine-invariance broken)"
            )
        if "{root}" not in p_a1 or dir_a in p_a1:
            fails.append("(b) prompt must be {root}-templated with no absolute sandbox path")
        if "age_s=7200" not in p_a1:
            fails.append("(b) F1 lock age_s=7200 not rendered (mtime pin or age render broken)")

    # (c) parser well-formed
    text = (
        "Considering the event, the receipt clears the bar.\n"
        "ACTION: gate-pass | path={root}/receipts/job-1.json\n"
        "some interleaved prose\n"
        "ACTION: report | to=owner | metric=91.2\n"
    )
    acts = parse_actions(text, sandbox_dir="SBX")
    if [a.verb for a in acts] != ["gate-pass", "report"]:
        fails.append(f"(c) verbs parsed wrong: {[a.verb for a in acts]}")
    elif acts[0].args.get("path") != "SBX/receipts/job-1.json":
        fails.append(f"(c) {{root}} not substituted: {acts[0].args}")
    elif acts[1].args.get("to") != "owner" or acts[1].args.get("metric") != "91.2":
        fails.append(f"(c) args parsed wrong: {acts[1].args}")

    # (d) silence on prose / malformed / non-enum verbs
    for label, junk in [
        ("prose", "No duty applies here. Staying silent.\n"),
        ("malformed", "ACTION reply to=eli\nACT: reply | to=eli\n"),
        ("non-enum", "ACTION: self-destruct | to=owner\nACTION: rm-rf | path=/\n"),
        ("empty", ""),
    ]:
        got = parse_actions(junk)
        if got:
            fails.append(f"(d) {label} text produced actions: {[(a.verb, a.args) for a in got]}")

    # (e) anti-spray cap
    spray = "\n".join("ACTION: reply | to=eli" for _ in range(MAX_ACTIONS_PER_EVENT + 3))
    capped = parse_actions(spray)
    if len(capped) != MAX_ACTIONS_PER_EVENT:
        fails.append(f"(e) cap broken: {len(capped)} actions parsed, cap {MAX_ACTIONS_PER_EVENT}")

    # (f) end-to-end M3 (action episode): correct seat PASS, wrong-verb seat FAIL
    ep_m3 = episodes["M3"]
    with tempfile.TemporaryDirectory(prefix="sp6c-m3-") as tmp:
        materialize(ep_m3, tmp)
        good = make_seat_core(lambda _p: "ACTION: challenge | to=eli\n")
        actions = replay_episode(ep_m3, good, tmp)
        score = score_episode(ep_m3, actions, sandbox_dir=tmp)
        if not score["pass"]:
            fails.append(f"(f) correct M3 seat scored FAIL: {score['reason']}")
    with tempfile.TemporaryDirectory(prefix="sp6c-m3w-") as tmp:
        materialize(ep_m3, tmp)
        wrong = make_seat_core(lambda _p: "ACTION: reply | to=eli\n")
        actions = replay_episode(ep_m3, wrong, tmp)
        score = score_episode(ep_m3, actions, sandbox_dir=tmp)
        if score["pass"]:
            fails.append("(f) wrong-verb M3 seat scored PASS — scoring not discriminating")

    # (f2) seat core actually receives the sandbox (world state in prompt)
    seen_prompts: list[str] = []

    def _probe_gen(prompt: str) -> str:
        seen_prompts.append(prompt)
        return ""

    ep_s4 = episodes["S4"]
    with tempfile.TemporaryDirectory(prefix="sp6c-s4-") as tmp:
        materialize(ep_s4, tmp)
        replay_episode(ep_s4, make_seat_core(_probe_gen), tmp)
    if not seen_prompts or "state/schedule.json" not in seen_prompts[0]:
        fails.append("(f2) S4 prompt missing world-state fixture — 3-arg protocol broken")

    # (g) end-to-end M4 (silence episode)
    ep_m4 = episodes["M4"]
    with tempfile.TemporaryDirectory(prefix="sp6c-m4-") as tmp:
        materialize(ep_m4, tmp)
        quiet = make_seat_core(lambda _p: "Broadcast, no obligation for this seat.\n")
        score = score_episode(ep_m4, replay_episode(ep_m4, quiet, tmp), sandbox_dir=tmp)
        if not score["pass"]:
            fails.append(f"(g) silent M4 seat scored FAIL: {score['reason']}")
    with tempfile.TemporaryDirectory(prefix="sp6c-m4s-") as tmp:
        materialize(ep_m4, tmp)
        noisy = make_seat_core(lambda _p: "ACTION: reply | to=mira\n")
        score = score_episode(ep_m4, replay_episode(ep_m4, noisy, tmp), sandbox_dir=tmp)
        if score["pass"]:
            fails.append("(g) outward-spray M4 seat scored PASS — silence rule broken")

    # (h) pinned mtimes
    with tempfile.TemporaryDirectory(prefix="sp6c-mt-") as tmp:
        materialize(ep_f1, tmp)
        lock = Path(tmp) / "locks" / "run.lock"
        policy = Path(tmp) / "config" / "replay-policy.json"
        if abs(lock.stat().st_mtime - (REPLAY_EPOCH - 7200)) > 2:
            fails.append(f"(h) F1 lock mtime not pinned to epoch-7200: {lock.stat().st_mtime}")
        if abs(policy.stat().st_mtime - REPLAY_EPOCH) > 2:
            fails.append(f"(h) offset-0 fixture mtime not pinned to epoch: {policy.stat().st_mtime}")

    # (i) deictic guard
    evt = Event(source="mail", kind="mail_arrived", payload={"from": "eli"}, ts="x")
    t = _normalize_target(Action(verb="reply", args={"to": "sender"}), evt, "")
    if t != "literal-sender":
        fails.append(f"(i) literal to='sender' normalized to {t!r}, expected 'literal-sender'")
    t = _normalize_target(Action(verb="reply", args={"to": "eli"}), evt, "")
    if t != "sender":
        fails.append(f"(i) genuine sender normalized to {t!r}, expected 'sender'")

    # sanity: verb enum matches the battery selftest's enum size
    if len(VERB_ENUM) != 18:
        fails.append(f"verb enum size {len(VERB_ENUM)} != 18")

    if fails:
        print("SP6C_SEAT_ADAPTER_SELFTEST FAIL:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print(
        "SP6C_SEAT_ADAPTER_SELFTEST PASS: template hash pinned, prompts "
        "machine-invariant, parser closed-grammar + capped, end-to-end "
        "PASS/FAIL discrimination on M3/M4, mtimes pinned, deictic guard live"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
