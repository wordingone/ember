#!/usr/bin/env python3
"""test_surface2.py — STATUS PROBE for Ember goal condition C-SURFACE2.

Registry text: DRAFT, not yet landed in docs/spec/conditions-v1.md (see
scratch/surface2-registry-entry.md for the exact snippet). gh issue #11
("Surface-2 board probe: telemetry+steer receipts must be machine-checked,
not just ticketed"), FROZEN SPEC v1 (author tick, issue #11 comment). R: the
"inference+training visible & steerable" surface (GOAL #2; issue #10's
C-OBS cockpit-lane companion) is proven CURRENTLY alive by real telemetry
receipts under the EXECUTION tree, not merely ticketed/designed.

Root note: unlike every other probe in this package, the evidence this
probe reads does NOT live inside the contract repo (EMBER_TOTALITY_ROOT).
Surface-2 telemetry receipts live on the physically separate EXECUTION
tree. Root resolution: `EMBER_EXEC_ROOT` env var, default `<local-exec-root>`
(frozen spec v1, verbatim).

CHK enforced here (offline, filesystem + one local subprocess — git log,
no network): GREEN iff ALL THREE hold, checked in this order (first
failing clause is the reported reason, same short-circuit discipline as
test_c_proc.py / test_c_legib.py):

  (a) the NEWEST receipt under `<EMBER_EXEC_ROOT>/receipts/
      ember-surface2-telemetry/*/*.json` (excluding underscore-prefixed
      meta dirs such as `_gate/` — see below) is non-synthetic AND its
      `ts` is within STALE_DAYS=14 days of the newest work commit on
      EMBER_EXEC_ROOT (`git log -1 --format=%ct HEAD`). Non-synthetic is
      checked two ways, both real fields:
        - the sitewide convention `_synthetic_control_fixture: true`
          (same rejection field used by every other probe in this
          package, e.g. test_c_legib.py / test_c_proc.py);
        - the surface-2-specific field `synthetic_event` (a REAL field
          name pinned from the actual newest June-28 receipt,
          receipts/ember-surface2-telemetry/2026-06-28T05-30-45-Z/
          render-test-receipt.json, whose own `note` field reads
          "Synthetic marker event appended as test artifact; does NOT
          represent real training data." — a self-declared test fixture,
          not live telemetry, even though it carries no
          `_synthetic_control_fixture` flag).
      Stale telemetry (age > STALE_DAYS) or a synthetic newest receipt =
      RED, quoting which sub-check fired and the receipt name — the
      surface must be CURRENTLY alive, not archaeologically alive.
      Receipt-absent (no `*/*.json` found under the surface-2 telemetry
      dir) or tree-absent (the dir itself does not exist under
      EMBER_EXEC_ROOT) = RED (frozen spec v1, verbatim: "Receipt-absent
      or tree-absent = RED"). This is the one distinction from the
      EMBER_EXEC_ROOT-not-found case just below, which is UNEVALUABLE —
      that is a probe/environment failure ("could not even look"), while
      an EMBER_EXEC_ROOT that exists but has no surface-2 receipts is a
      real, looked-at absence (RED, per the frozen spec).

  (b) that receipt, or a SIBLING file in the same timestamped receipt
      directory, names a steer/kill event via a schema-checked field —
      not a keyword grep. The real schema is `FinetuneControlCmd` (
      tools/ember-cli/src/services/finetune-control.ts, spec:
      tools/ember-cli/specs/surface2-steerable-watch-control.md AC5-AC7):
      `{verb: "start"|"stop"|"pause"|"resume"|"adjust", runId?, lrScale?,
      ts}`, appended as one JSONL line per command to
      `state/ember-finetune-control.jsonl` (CONTROL_CHANNEL_PATH). Per
      that schema: `verb="stop"` is KILL; `verb` in {"pause","resume",
      "adjust"} is STEER (mid-run redirection); `verb="start"` is neither
      and does not count. The probe checks the literal `verb` key —
      first on the receipt itself (in case a receipt IS a captured
      control-channel record), then on every sibling file in the same
      directory (parsed whole-file as JSON, falling back to JSONL
      line-by-line, matching how the control channel is actually
      written). No event found = RED — this is also the clause that
      correctly stays RED on the real June-28 receipts today: the
      control-channel writer (Part B of the spec above) exists as tested
      CLI code, but the spec's own "NOT in this spec" section states the
      live receipt of the CLI actually steering/killing a REAL governed
      finetune "rides the next GPU window" — it has not happened yet,
      confirmed by receipts/ember-surface2-telemetry/_gate/verdict.json's
      own `finetune_watch_half: PENDING` verdict.

  (c) a token-delta anti-fixture field is present and >0 (the /metrics
      gate class — reference_local_model_receipt_metrics_antifixture_gate;
      doc shorthand `token_delta`, but the REAL field name observed in
      this receipt family is `metrics_delta`, pinned from
      receipts/ember-surface2-telemetry/2026-06-28T04-08-08Z/receipt.json
      (`"metrics_delta": 0`, a top-level int in the surface-2 schema).
      A sibling surface (surface-1, ember-cockpit-live) nests the same
      concept as `metrics_delta.tokens_predicted_delta` — the probe
      accepts either shape (plain number, or dict with that key) since
      both are real, observed shapes of the identically-named field
      across this repo's receipt families. Missing or <=0 = RED — no
      proof a real model process produced real output, not a canned
      marker.

Why offline except one subprocess: (a)'s age check needs the EXECUTION
tree's real commit clock (local bytes via git, same discipline as
test_c_proc.py's `_git`/`_commit_time` helpers) — no receipt could stand
in for that without becoming a second, driftable copy of git's own
timestamp.

DISCIPLINE: status probe — always exits 0, one line, real bytes decide, no
hardcoded verdict. RED / GREEN / UNEVALUABLE(env); receipt-absent is RED
(frozen spec v1 override of this package's usual receipt-absent-on-a-
scannable-tree convention — see clause (a) note above for the exact split
this probe draws between "tree not found" (UNEVALUABLE) and "tree found,
no receipts in it" (RED)).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# Environment variable override for execution tree root; default points to external location
# EMBER_EXEC_ROOT env var can override. Default: <local-exec-root> (frozen spec v1 convention)
DEFAULT_EXEC_ROOT = os.environ.get("EMBER_EXEC_ROOT", "<local-exec-root>")
STALE_DAYS = 14
SURFACE_SUBPATH = os.path.join("receipts", "ember-surface2-telemetry")
STEER_KILL_VERBS = {"stop", "pause", "resume", "adjust"}  # "start" excluded — neither steer nor kill

INVALID_TOKENS = [
    "invalid_surface2_receipt_absent",
    "invalid_surface2_synthetic_receipt",
    "invalid_surface2_stale_telemetry",
    "invalid_surface2_no_steer_kill_event",
    "invalid_surface2_token_delta_not_positive",
    "invalid_surface2_non_live_provenance",       # [ISSUE #97 cure 3]
    "invalid_surface2_no_rendered_telemetry",     # [ISSUE #97 cure 3]
]

# [ISSUE #97 cure 3, 2026-07-04] The 2026-07-03T07-03-09Z receipt self-
# declares provenance="replay_of_completed_run", live_process_touched=false,
# gpu_used=false, events_rendered=0, render_evidence.telemetry_status_bar_
# rendered=false -- it stitches together OTHER receipts (source_run.sources
# citing receipts/ember-c14-owned-run/*, a different receipt family/tree
# entirely) to replay a PAST completed run's console log through the
# surface-2 capture harness after the fact. It satisfied clauses (a)-(c) pre-
# cure and was scored GREEN for a "visible-LIVE" claim despite nothing ever
# having been live or rendered. Two failure classes, both real observed
# field values, never invented:
NON_LIVE_PROVENANCE_MARKERS = {
    "replay_of_completed_run", "replay", "reconstructed", "backfilled",
    "synthetic_replay", "post_hoc_replay",
}

COMPACT_TS_RE = re.compile(r"^\d{8}T\d{6}Z$")


def emit(color, reason):
    print(f"{color} {reason}")
    sys.exit(0)


def _parse_ts(ts):
    """Parse a receipt `ts` in either real observed form:
    ISO8601-with-millis-Z ("2026-06-28T04:08:08.145Z", used by receipt.json
    and render-test-receipt.json) or compact ("20260628T051503Z", used by
    finetune-watch-receipt.json). Returns epoch seconds (float) or None."""
    if not isinstance(ts, str) or not ts.strip():
        return None
    s = ts.strip()
    try:
        if COMPACT_TS_RE.match(s):
            dt = datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return dt.timestamp()
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _git(tree, *args):
    """Run git in `tree`; return (ok, stdout_or_error). Never raises."""
    try:
        r = subprocess.run(
            ["git", "-C", tree, *args],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0, r.stdout.strip()
    except Exception as exc:  # git missing / timeout -> env failure
        return False, str(exc)


def _newest_commit_epoch(tree):
    ok, out = _git(tree, "log", "-1", "--format=%ct", "HEAD")
    if not ok or not out.isdigit():
        return False, out
    return True, int(out)


def _iter_receipt_candidates(surface_dir):
    """Yield (path, mtime) for every *.json file one level under an
    immediate, non-underscore-prefixed subdirectory of surface_dir.
    Underscore-prefixed dirs (e.g. `_gate/`) are excluded: `_gate/
    verdict.json` is the review gate's own PARTIAL/PENDING assessment of the
    surface (a different, meta artifact class), never a raw per-run
    telemetry receipt — the three real timestamped sibling dirs observed
    2026-06-28 (`2026-06-28T04-08-08Z/`, `2026-06-28T05-15-00Z/`,
    `2026-06-28T05-30-45-Z/`) are the actual receipt-carrying shape."""
    if not os.path.isdir(surface_dir):
        return
    for entry in sorted(os.listdir(surface_dir)):
        if entry.startswith("_"):
            continue
        sub = os.path.join(surface_dir, entry)
        if not os.path.isdir(sub):
            continue
        for fn in sorted(os.listdir(sub)):
            if fn.endswith(".json"):
                p = os.path.join(sub, fn)
                try:
                    mtime = os.path.getmtime(p)
                except OSError:
                    mtime = 0
                yield p, mtime


def _pick_newest(surface_dir):
    """Returns (path, ts_epoch) for the receipt with the latest resolvable
    timestamp (parsed `ts` field; falls back to file mtime if `ts` is
    missing/unparseable, so a candidate is never silently dropped from
    ranking), or None if no candidate files exist at all."""
    best = None
    for path, mtime in _iter_receipt_candidates(surface_dir):
        ts_epoch = mtime
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            parsed = _parse_ts(data.get("ts"))
            if parsed is not None:
                ts_epoch = parsed
        except Exception:
            pass
        if best is None or ts_epoch > best[1]:
            best = (path, ts_epoch)
    return best


def _verb_of(obj):
    if isinstance(obj, dict):
        v = obj.get("verb")
        if isinstance(v, str) and v in STEER_KILL_VERBS:
            return v
    return None


def _find_steer_kill_event(receipt_path, data):
    """Schema-checked per FinetuneControlCmd (tools/ember-cli/src/services/
    finetune-control.ts): checks the receipt's own `verb` field first, then
    every sibling file in the same directory — whole-file JSON, falling
    back to JSONL line-by-line (the control channel's real on-disk format
    is one JSONL line per command). Returns (verb, source_filename) or
    (None, None)."""
    v = _verb_of(data)
    if v:
        return v, os.path.basename(receipt_path)

    d = os.path.dirname(receipt_path)
    try:
        siblings = sorted(os.listdir(d))
    except OSError:
        siblings = []
    for fn in siblings:
        p = os.path.join(d, fn)
        if p == receipt_path or not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                text = fh.read()
        except Exception:
            continue
        try:
            obj = json.loads(text)
            v = _verb_of(obj)
            if v:
                return v, fn
        except Exception:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                v = _verb_of(obj)
                if v:
                    return v, fn
    return None, None


def _token_delta_value(data):
    """metrics_delta is observed in two real shapes across this repo's
    receipt families: a plain number (surface-2's receipt.json) or a dict
    carrying `tokens_predicted_delta` (surface-1's cockpit-live receipt).
    Accepts either."""
    md = data.get("metrics_delta")
    if isinstance(md, dict):
        return md.get("tokens_predicted_delta")
    return md


def main():
    exec_root = os.environ.get("EMBER_EXEC_ROOT") or DEFAULT_EXEC_ROOT
    if not os.path.isdir(exec_root):
        emit("UNEVALUABLE", f"C-SURFACE2: execution root {exec_root} not found -- probe cannot look")

    surface_dir = os.path.join(exec_root, SURFACE_SUBPATH)
    picked = _pick_newest(surface_dir)
    if picked is None:
        emit("RED", f"C-SURFACE2: no receipt found under {SURFACE_SUBPATH.replace(os.sep, '/')}/ on "
                    f"{exec_root} (invalid_surface2_receipt_absent) -- receipt-absent or tree-absent")

    path, _ = picked
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        rel = os.path.relpath(path, exec_root).replace(os.sep, "/")
        emit("RED", f"C-SURFACE2: newest receipt {rel} unreadable ({exc}) (invalid_surface2_receipt_absent)")

    name = os.path.relpath(path, exec_root).replace(os.sep, "/")

    # --- clause (a): non-synthetic + freshness -----------------------------
    if data.get("_synthetic_control_fixture"):
        emit("RED", f"C-SURFACE2: newest receipt {name} is a synthetic control fixture, never evidence "
                    f"(invalid_surface2_synthetic_receipt)")
    if "synthetic_event" in data:
        note = data.get("note", "a test-injected marker, not real production telemetry")
        emit("RED", f"C-SURFACE2: newest receipt {name} carries a synthetic_event field -- {note!r} "
                    f"(invalid_surface2_synthetic_receipt)")

    # --- [ISSUE #97 cure 3] clause (a2): reject non-live provenance ---------
    # The "live" half of GOAL #2 ("visible & steerable") requires a currently
    # RUNNING process, not a replay of a past one. A receipt whose own
    # provenance field names a non-live origin, or whose own
    # live_process_touched flag reads False, self-disqualifies regardless of
    # anything else on the receipt -- the sitewide-cited source_run/sources
    # cross-receipt citation (kill the cross-tree citation: those paths are
    # NEVER read for this verdict, they only ever cite a DIFFERENT receipt
    # family, e.g. ember-c14-owned-run/, and citing another artifact is not
    # the same as this one being live) never overrides that self-declaration.
    prov = data.get("provenance")
    if isinstance(prov, str) and prov.strip().lower() in NON_LIVE_PROVENANCE_MARKERS:
        emit("RED", f"C-SURFACE2: newest receipt {name} self-declares provenance={prov!r} "
                    f"-- a replay of a completed run is not a currently-live process "
                    f"(invalid_surface2_non_live_provenance)")
    if data.get("live_process_touched") is False:
        emit("RED", f"C-SURFACE2: newest receipt {name} self-declares live_process_touched=false "
                    f"-- no live process was ever touched to produce this telemetry "
                    f"(invalid_surface2_non_live_provenance)")

    # --- [ISSUE #97 cure 3] clause (a3): require rendered-telemetry evidence.
    # Events INGESTED or CITED are not proof of a rendered visible surface
    # (GOAL #2 is "visible", not merely "logged"). A receipt's own
    # render_evidence block, if present, is authoritative: an explicit False
    # on the rendered flag hard-fails even if events_rendered looks nonzero
    # elsewhere. Absent a render_evidence block, fall back to events_rendered
    # itself (a plain ingested-count is NOT sufficient on its own unless no
    # stronger render_evidence signal exists to contradict it).
    render_evidence = data.get("render_evidence")
    events_rendered = data.get("events_rendered")
    if isinstance(render_evidence, dict) and render_evidence.get("telemetry_status_bar_rendered") is False:
        emit("RED", f"C-SURFACE2: newest receipt {name} render_evidence."
                    f"telemetry_status_bar_rendered=false -- events were ingested/cited but "
                    f"nothing was actually rendered to the visible surface "
                    f"(invalid_surface2_no_rendered_telemetry)")
    rendered_ok = (
        (isinstance(render_evidence, dict)
         and render_evidence.get("telemetry_status_bar_rendered") is True)
        or (isinstance(events_rendered, (int, float)) and not isinstance(events_rendered, bool)
            and events_rendered > 0)
    )
    if not rendered_ok:
        emit("RED", f"C-SURFACE2: newest receipt {name} has no rendered-telemetry evidence "
                    f"(events_rendered={events_rendered!r}, render_evidence={render_evidence!r}) "
                    f"-- ingestion or a cross-receipt citation is not proof of a rendered, "
                    f"visible surface (invalid_surface2_no_rendered_telemetry)")

    ts_epoch = _parse_ts(data.get("ts"))
    if ts_epoch is None:
        emit("UNEVALUABLE", f"C-SURFACE2: newest receipt {name} has no parseable ts field -- probe cannot look")

    ok, commit_ts_or_err = _newest_commit_epoch(exec_root)
    if not ok:
        emit("UNEVALUABLE", f"C-SURFACE2: could not read newest work commit on {exec_root} "
                            f"({commit_ts_or_err}) -- env failure")

    age_days = (commit_ts_or_err - ts_epoch) / 86400.0
    if age_days > STALE_DAYS:
        emit("RED", f"C-SURFACE2: newest receipt {name} (ts={data.get('ts')}) is {age_days:.1f} days older "
                    f"than the newest work commit on {exec_root} -- stale telemetry, the surface must be "
                    f"CURRENTLY alive, not archaeologically alive (invalid_surface2_stale_telemetry, "
                    f">{STALE_DAYS}d)")

    # --- clause (b): steer/kill control-channel event -----------------------
    verb, verb_src = _find_steer_kill_event(path, data)
    if not verb:
        emit("RED", f"C-SURFACE2: no steer/kill control-channel event (verb in "
                    f"{sorted(STEER_KILL_VERBS)}, schema per tools/ember-cli/src/services/"
                    f"finetune-control.ts FinetuneControlCmd) found in {name} or its siblings "
                    f"(invalid_surface2_no_steer_kill_event)")

    # --- clause (c): token-delta anti-fixture --------------------------------
    delta = _token_delta_value(data)
    if not (isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta > 0):
        emit("RED", f"C-SURFACE2: newest receipt {name} metrics_delta={delta!r} is not >0 -- no proof real "
                    f"tokens were produced (/metrics anti-fixture gate class; "
                    f"invalid_surface2_token_delta_not_positive)")

    emit("GREEN", f"C-SURFACE2 CHK satisfied by {name}: non-synthetic, {age_days:.1f}d <= {STALE_DAYS}d of "
                  f"newest work commit, steer/kill event verb={verb!r} from {verb_src}, token-delta={delta} "
                  f"> 0 (GOAL #2: inference+training visible & steerable, currently alive not ticketed)")


if __name__ == "__main__":
    main()
