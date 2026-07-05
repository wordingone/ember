#!/usr/bin/env python3
"""Ember totality test — Condition C0 (status probe / TDD).

C0 — No additional Ember loops before resident-training preconditions.
  R: before any further cycle/loop/benchmark/growth/scale-up/readiness/proof,
     the clean-room `avir-cli` resident harness precondition and both RLM and
     iGRPO preconditions (C14) are receipted.
  Does NOT count: existing loop receipts (historical only); any loop run before
     this gate. These three are non-killable; no successor-replacement escape.
  Invalid-token: invalid_precondition_bypass
  CHK: C14 PASS present AND dated before any cited loop receipt.

Gloss (task): no additional Ember loops before resident-training preconditions:
  C14 PASS dated BEFORE any cited loop receipt.
Receipt hint: C14 receipt timestamp vs loop receipt timestamps.

This is a STATUS PROBE. It always exits 0 and prints exactly one line. C0 is a
STANDING PROCESS-INVARIANT (GOAL.md §4.0(9)), not a STATE-condition: it never
prints RED/GREEN/UNEVALUABLE. It renders one of AUDIT-OK / AUDIT-INCIDENT (a
cadence audit from the goalforge-clear epoch) or, pre-epoch (no operator-
acceptance object exists yet), AUDIT-PENDING-EPOCH — never RED. Pre-epoch
history is explicitly OUT OF AUDIT SCOPE (§4.0(9)): this probe only ever
scans receipts dated at/after the epoch once one exists.

Run ONLY via:  wsl python3 <this file>
Under WSL the B: drive may mount at /b/ or /mnt/b/ on this host.
"""

# [PATH-REWRITE 2026-07-01] Imported from
# B:/M/avir/leo/state/ember-totality-build/ into
# B:/M/ember-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at B:/M/avir/leo/state/kai-converge (and /mnt/b/M/...,
# /b/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. kai-converge does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import glob
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from receipt_ts_authority import effective_event_ts  # noqa: E402 -- shared
# ordering-authority helper (#60); the ONLY place internal-ts-
# vs-filename-stamp resolution is implemented -- test_c14.py imports the same
# module so the two probes can never drift into different orderings.

# --- Locate kai-converge robustly across WSL mount conventions ----------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "kai-converge"))
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

# --- Invalid-tokens (negative assertions) ------------------------------------
# C0's explicit ✗ token, PLUS the C14-disqualifying tokens that render any
# cited resident-training "PASS" label invalid (C14 §4.2). C0's CHK requires a
# *real* C14 PASS; a PASS revoked by the conflation guard or downgraded to a
# symbolic/runner/parity-with-model interpretation is NOT a C14 PASS.
INVALID_TOKENS = [
    "invalid_precondition_bypass",                            # C0 explicit ✗
    # C14 failure modes that disqualify a "PASS" label from counting as C14 PASS:
    "SYMBOLIC_PROXY_PASS",
    "RUNNER_OR_PARTIAL_NEURAL_PROGRESS_NOT_RESIDENT_ORGAN_CLEARANCE",
    "RESIDENT_GATE_CONFLATION_GUARD_BLOCKED",
    "PARITY_WITH_MODEL_NOT_TOOL",
    "invalid_paper_to_spec_only",
    "precondition_scaffold_only",
    "invalid_floor_contract_unaccounted",
    "invalid_unread_rlm_igrpo_source",
]

TS_RE = re.compile(r"(\d{8}T\d{6}Z)")


class _Verdict(Exception):
    """Internal control-flow signal carrying a scan's raw finding (RED/GREEN)
    up to main(), which relabels it against the epoch before printing.
    Never surfaced to the probe's stdout contract directly."""
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def emit(color, reason):
    """Raise the scan's raw finding. main() catches this and relabels it
    (AUDIT-PENDING-EPOCH pre-epoch with the finding folded in as informational
    context, or AUDIT-OK/AUDIT-INCIDENT post-epoch) before ever printing."""
    raise _Verdict(color, reason)


def _norm_ts(ts):
    """Normalize an ISO8601-ish timestamp to the compact YYYYMMDDTHHMMSSZ form
    used by this codebase's receipt filenames, so an epoch ts written in
    extended form ("2026-07-02T10:44:25Z") still compares correctly against
    filename stamps ("20260702T104425Z")."""
    return re.sub(r"[^0-9A-Za-z]", "", ts or "")


def _effective_ts(path, data):
    """A gate receipt's EFFECTIVE timestamp for epoch-WINDOW eligibility.

    An "import edition" (see resident-training-gate-<ts>-import-edition.json)
    is, by its own import_provenance block, a scope-trimmed COPY of a
    pre-existing artifact -- "Original receipt was NOT edited" -- not a new
    gate event. Per the C14 spec's supersession clause (docs/spec/
    c14-owned-core-resident-run-v1.md: only a new executed run counts) and
    GOAL.md's process-invariant framing, a copy cannot manufacture a fresh
    in-window PASS out of pre-epoch substance merely by being written to
    disk under a later filename. When present, import_edition_of_ts is
    therefore the receipt's true date for window purposes; the filename
    stamp is used only when no import_provenance is present (the normal,
    non-imported case).
    """
    imported_of = (data.get("import_provenance") or {}).get("import_edition_of_ts")
    return _norm_ts(imported_of) if imported_of else ts_from_name(path)


def find_epoch():
    """Return (epoch_ts, epoch_path) for the goalforge-clear operator-
    acceptance object (docs/spec/operator-acceptance-v1.md schema
    acceptance/v1, scope goalforge-clear, stored at
    receipts/acceptance/goalforge-clear-<date>.json), or (None, None) if no
    epoch has been recorded yet. GOAL.md §4.0(9): the epoch is the operator
    acceptance of this goal; C0 is a process-invariant with no meaning before
    it exists. epoch_ts is normalized (see _norm_ts) for stable comparison.
    """
    if ROOT is None:
        return None, None
    acc_dir = os.path.join(ROOT, "receipts", "acceptance")
    if not os.path.isdir(acc_dir):
        return None, None
    candidates = sorted(glob.glob(os.path.join(acc_dir, "goalforge-clear-*.json")))
    for path in reversed(candidates):
        try:
            raw, obj = load_json(path)
        except Exception:
            continue
        if obj.get("schema") == "acceptance/v1" and obj.get("scope") == "goalforge-clear":
            ts = obj.get("ts")
            if ts:
                return _norm_ts(ts), path
    return None, None


def ts_from_name(path):
    """Extract a sortable 20260622T011305Z-style stamp from a filename."""
    m = TS_RE.search(os.path.basename(path))
    return m.group(1) if m else None


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    return raw, json.loads(raw)


# --- Incident-disposition support (issue #31, docs/spec/
# c0-incident-cure-contract.md §5) -------------------------------------------
# There is no disposition concept in scan()'s core detection; these helpers
# add ONE additional, independently-verified escape hatch checked only on the
# RED paths that would otherwise flag invalid_precondition_bypass. Nothing
# here changes what counts as an in-window loop artifact or a real C14 PASS
# -- _loop_paths_in_window and _window_filter_gate_receipts/_vet_gate_receipts
# are the SAME computations scan() itself uses (factored out so a disposition
# check can reuse them verbatim, never a second, drifting definition).

def _sha256_of(path):
    """Content-identity hash of an on-disk artifact, recomputed live from
    actual bytes -- never trusted from any receipt's self-reported field.
    A regular file hashes its own bytes. A directory (e.g. a loop-artifact
    directory NODE such as receipts/ember-d3-native-loop/<ts>/, which
    _loop_paths_in_window treats as a single artifact -- see docs/spec/
    c0-incident-cure-contract.md §3 item 3) has no bytes of its own, so it
    hashes a deterministic digest of every regular file recursively inside
    it (sorted relative path, then that file's own sha256, newline-joined)."""
    if os.path.isdir(path):
        h = hashlib.sha256()
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames.sort()
            for fn in sorted(filenames):
                fp = os.path.join(dirpath, fn)
                rel = os.path.relpath(fp, path).replace(os.sep, "/")
                with open(fp, "rb") as fh:
                    inner = hashlib.sha256(fh.read()).hexdigest()
                h.update(rel.encode("utf-8"))
                h.update(b"\x00")
                h.update(inner.encode("utf-8"))
                h.update(b"\n")
        return h.hexdigest()
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _relpath_key(path):
    """Normalize an absolute or repo-relative on-disk path to a stable,
    forward-slash, ROOT-relative identity string, so paths built from a glob
    and paths built from a disposition's JSON `path` field compare equal
    regardless of OS separator or absolute/relative spelling."""
    try:
        rel = os.path.relpath(os.path.abspath(path), ROOT)
    except ValueError:
        rel = os.path.abspath(path)
    return rel.replace(os.sep, "/")


def _resolve_disposition_path(path_field):
    """Resolve a disposition receipt's claimed `path` field (repo-root-
    relative, forward-slash, per the c0-disposition schema) to an absolute
    on-disk path under ROOT. Returns None if the field is missing/blank or
    the path does not exist on disk -- a disposition citing a nonexistent
    artifact is never valid."""
    if not isinstance(path_field, str) or not path_field.strip():
        return None
    norm = path_field.strip().replace("\\", "/")
    candidate = os.path.join(ROOT, *[part for part in norm.split("/") if part])
    if not os.path.exists(candidate):
        return None
    return candidate


def _loop_paths_in_window(min_ts):
    """Enumerate cited Ember loop artifacts (the d3 native loop plus round/
    local-loop receipt variants), filtered to those whose OWN basename
    timestamp is >= min_ts (or unfiltered if min_ts is None). Shared by
    scan() (which derives n_loops/earliest_loop from this set) and
    _find_valid_disposition() (which must recompute the SAME live set to
    exact-set-match a disposition's incident_receipts against it) so the two
    can never drift apart."""
    loop_globs = [
        os.path.join(ROOT, "receipts", "ember-d3-native-loop", "**", "*"),
        os.path.join(ROOT, "receipts", "round-local-loop-*.json"),
        os.path.join(ROOT, "receipts", "*local-loop*.json"),
    ]
    loop_paths_all = set()
    for g in loop_globs:
        loop_paths_all.update(glob.glob(g, recursive=True))
    return {
        p for p in loop_paths_all
        if min_ts is None or (ts_from_name(p) or "") >= min_ts
    }


def _window_filter_gate_receipts(gate_receipts_all, min_ts):
    """Filter gate receipts to those EFFECTIVELY dated (see _effective_ts,
    which resolves import-edition lineage) at or after min_ts. Shared by
    scan() (its own primary in-window C14 vetting) and
    _find_valid_disposition() (which must vet an authorizing_c14_receipt
    against the IDENTICAL in-window gate-receipt set scan() uses -- an
    authorizing receipt that is pre-epoch, or an import-edition of pre-epoch
    substance, must never qualify as authorization merely by being named in
    a disposition) so the two can never drift apart."""
    out = []
    for rp in gate_receipts_all:
        try:
            _raw, data = load_json(rp)
        except Exception:
            out.append(rp)  # unreadable: let vetting's own error path handle it
            continue
        eff_ts = _effective_ts(rp, data)
        if min_ts is None or (eff_ts or "") >= min_ts:
            out.append(rp)
    return out


def _vet_gate_receipts(gate_receipts):
    """Run the real-C14-PASS vetting predicate over a list of gate receipt
    paths: a receipt counts as a real, undisqualified PASS only if its
    operative verdict is RESIDENT_TRAINING_GATE_PASS, status PASS, every
    component PASS, no disqualifying invalid-token is the operative
    interpretation, it is not revoked by a conflation-guard audit, and it is
    not superseded by a chronologically-later BLOCKED gate run.

    This is scan()'s own vetting logic, factored out unchanged so
    _find_valid_disposition() can apply the IDENTICAL predicate to an
    authorizing_c14_receipt (on the disposition's own in-window gate-receipt
    set, via _window_filter_gate_receipts) instead of duplicating and
    drifting from it -- a disposition can never launder a disqualified,
    revoked, or superseded receipt into an authorizer merely by asserting it
    in JSON.

    Returns (real_passes, revoked, audits, latest_verdict, latest_stamp,
    latest_blocked_stamp); real_passes is a list of (stamp, path)."""
    revoked = set()
    audits = []
    real_passes = []
    latest_verdict = None
    latest_stamp = None
    latest_blocked_stamp = None

    for rp in gate_receipts:
        try:
            raw, data = load_json(rp)
        except Exception as exc:
            audits.append(f"{os.path.basename(rp)}: unreadable ({exc})")
            continue
        # Ordering authority = internal ts, filename only as fallback
        # (#60; effective_event_ts is the single shared
        # implementation, see receipt_ts_authority.py). A divergence >120s
        # between the two is itself a receipt-hygiene smell, surfaced here.
        stamp, _ts_source, div_note = effective_event_ts(rp, data)
        if div_note:
            audits.append(div_note)
        verdict = data.get("verdict")
        status = data.get("resident_training_gate_status")

        if stamp and (latest_stamp is None or stamp > latest_stamp):
            latest_stamp = stamp
            latest_verdict = verdict or status

        is_blocked = (status == "BLOCKED") or \
            (isinstance(verdict, str) and "BLOCKED" in verdict)
        if is_blocked and stamp and \
                (latest_blocked_stamp is None or stamp > latest_blocked_stamp):
            latest_blocked_stamp = stamp

        # A conflation-audit receipt always carries a `conflation_guard`
        # rulebook dict (PASS and BLOCKED alike) -- presence of the field is
        # NOT a block signal. Revoke only when the audit actually blocked:
        # BLOCKED verdict or non-empty block_reasons.
        is_conflation_audit = bool(data.get("conflation_guard")) or \
            "CONFLATION_GUARD" in str(verdict or "")
        if is_conflation_audit:
            conflation_blocked = "BLOCKED" in str(verdict or "") or \
                bool(data.get("block_reasons"))
            tgt = data.get("resident_training_receipt_path", "")
            if conflation_blocked:
                if tgt:
                    revoked.add(os.path.basename(tgt.replace("\\", "/")))
                audits.append(
                    f"{os.path.basename(rp)}: CONFLATION_GUARD_BLOCKED revokes "
                    f"{os.path.basename(tgt.replace(chr(92), '/')) if tgt else '?'}"
                )
            else:
                audits.append(
                    f"{os.path.basename(rp)}: conflation guard PASS "
                    f"(reconciles {os.path.basename(tgt.replace(chr(92), '/')) if tgt else '?'})"
                )
            continue

        if not (verdict == "RESIDENT_TRAINING_GATE_PASS" and status == "PASS"):
            continue

        interp = (data.get("resident_pass_interpretation") or "")
        parity = (data.get("full_parity_classification") or "") + \
                 (data.get("full_parity_verdict") or "")
        operative = " ".join([str(verdict), str(status), str(interp), str(parity)])
        op_hits = [t for t in INVALID_TOKENS
                   if t.lower() in operative.lower()]

        comp = data.get("component_status") or {}
        comp_bad = [k for k, v in comp.items() if v != "PASS"]

        if op_hits or comp_bad:
            audits.append(
                f"{os.path.basename(rp)}: PASS-labeled but disqualified "
                f"(op_tokens={op_hits}, non_PASS_components={comp_bad[:3]})"
            )
            continue

        real_passes.append((stamp, rp))

    real_passes = [
        (s, p) for (s, p) in real_passes
        if os.path.basename(p) not in revoked
    ]
    if latest_blocked_stamp is not None:
        superseded = [(s, p) for (s, p) in real_passes
                      if s is not None and s < latest_blocked_stamp]
        for s, p in superseded:
            audits.append(
                f"{os.path.basename(p)}: PASS @ {s} SUPERSEDED by later "
                f"BLOCKED gate @ {latest_blocked_stamp}")
        real_passes = [(s, p) for (s, p) in real_passes
                       if s is None or s >= latest_blocked_stamp]

    return real_passes, revoked, audits, latest_verdict, latest_stamp, latest_blocked_stamp


def _find_valid_disposition(loop_paths_in_window, gate_receipts_all, epoch_ts):
    """Return a disposition reason string if a receipted, independently
    verified process-invariant-incident-disposition (receipts/ember-process-
    incident-dispositions/c0-disposition-*.json, docs/spec/
    c0-incident-cure-contract.md §5.1) covers EXACTLY the current in-window
    loop artifact set, else None. ALL of the following must hold, verified
    against live on-disk content every call -- the disposition's own claims
    (its incident_receipts sha256 list, its scope_classification verdict
    string) are never trusted, only used as the claim to independently
    re-check:

      (a) EXACT-SET match: the CURRENT in-window loop artifact identity set
          (loop_paths_in_window, hashed fresh via _sha256_of) and the
          disposition's claimed incident_receipts set (each entry's sha256
          re-verified against the actual on-disk bytes at its path, live)
          must be identical. A subset, superset, or any single stale/wrong
          hash invalidates the disposition; a NEW loop artifact landing
          later automatically breaks the match and the row returns to
          AUDIT-INCIDENT with zero further code involved -- detection stays
          live for a new, distinct bypass.
      (b) same-epoch binding: the disposition's epoch_ref.epoch_ts must
          equal the epoch_ts (min_ts) active for THIS scan() call -- a
          disposition cannot be laundered across a later re-epoch.
      (c) authorizing_c14_receipt must independently re-pass the IDENTICAL
          real-PASS vetting scan() applies to its own primary gate-receipt
          window (_window_filter_gate_receipts + _vet_gate_receipts, reused
          verbatim, never duplicated) -- a fabricated, disqualified,
          revoked, superseded, or pre-epoch receipt does not count as
          authorization merely by being named in JSON.
      (d) operator_visibility.surfaced_via must be non-empty -- a
          disposition filed but never surfaced anywhere is not
          operator-visible.

    Multiple c0-disposition-*.json files are considered latest-filename-first;
    the first one that independently verifies wins.
    """
    if epoch_ts is None:
        return None
    disp_dir = os.path.join(ROOT, "receipts", "ember-process-incident-dispositions")
    if not os.path.isdir(disp_dir):
        return None

    live_set = {_relpath_key(p): _sha256_of(p) for p in loop_paths_in_window}
    if not live_set:
        return None  # nothing to dispose -- disposition is meaningless here

    candidates = sorted(
        glob.glob(os.path.join(disp_dir, "c0-disposition-*.json")), reverse=True
    )
    for disp_path in candidates:
        try:
            _raw, obj = load_json(disp_path)
        except Exception:
            continue
        if obj.get("receipt_type") != "process_invariant_incident_disposition":
            continue
        if obj.get("row_id") != "C0":
            continue

        # (b) same-epoch binding.
        epoch_ref = obj.get("epoch_ref") or {}
        disp_epoch_ts = _norm_ts(epoch_ref.get("epoch_ts") or "")
        if not disp_epoch_ts or disp_epoch_ts != epoch_ts:
            continue

        # (d) operator visibility.
        surfaced_via = (
            (obj.get("operator_visibility") or {}).get("surfaced_via") or ""
        ).strip()
        if not surfaced_via:
            continue

        # (a) exact-set match -- recompute the claimed side from actual
        # on-disk bytes; the disposition's own sha256 field is only the
        # claim being verified, never trusted directly.
        claimed_entries = obj.get("incident_receipts")
        if not isinstance(claimed_entries, list) or not claimed_entries:
            continue
        claimed_set = {}
        valid = True
        for entry in claimed_entries:
            if not isinstance(entry, dict):
                valid = False
                break
            resolved = _resolve_disposition_path(entry.get("path"))
            claimed_sha = entry.get("sha256")
            if resolved is None or not claimed_sha:
                valid = False
                break
            actual_sha = _sha256_of(resolved)
            if actual_sha != claimed_sha:
                valid = False  # stale or fabricated claim vs live content
                break
            claimed_set[_relpath_key(resolved)] = actual_sha
        if not valid or claimed_set != live_set:
            continue

        # (c) authorizing_c14_receipt re-vetted, never trusted as-labeled.
        auth = obj.get("authorizing_c14_receipt") or {}
        auth_resolved = _resolve_disposition_path(auth.get("path"))
        if auth_resolved is None or not os.path.isfile(auth_resolved):
            continue
        auth_claimed_sha = auth.get("sha256")
        if auth_claimed_sha and _sha256_of(auth_resolved) != auth_claimed_sha:
            continue

        gate_receipts_window = _window_filter_gate_receipts(gate_receipts_all, epoch_ts)
        real_passes, _revoked, _audits, _lv, _ls, _lbs = \
            _vet_gate_receipts(gate_receipts_window)
        real_pass_stamps = {
            os.path.abspath(p): s for (s, p) in real_passes
        }
        auth_abspath = os.path.abspath(auth_resolved)
        if auth_abspath not in real_pass_stamps:
            continue
        auth_stamp = real_pass_stamps[auth_abspath]

        return (
            f"disposition {os.path.basename(disp_path)} (surfaced via "
            f"{surfaced_via}) exact-set-verified against {len(live_set)} "
            f"in-window loop artifact(s), authorized by independently "
            f"re-vetted C14 PASS {os.path.basename(auth_resolved)} @ {auth_stamp}"
        )

    return None


def scan(min_ts):
    """Run the C0 detection logic and raise a _Verdict(RED|GREEN, reason).

    min_ts=None means unfiltered (whole-corpus, informational -- used
    pre-epoch since there is no epoch to filter against yet). min_ts=<stamp>
    means filtered to receipts dated >= min_ts (the real post-epoch audit).
    The RED/GREEN label here is a raw finding, not the final printed status
    -- main() relabels it against epoch existence before printing.
    """
    if ROOT is None:
        emit("RED", "C0: state root not found under any known WSL mount -- "
                     "cannot inspect any receipt")

    window = f">= {min_ts}" if min_ts is not None else "ALL (unfiltered, pre-epoch)"

    gate_dir = os.path.join(ROOT, "receipts", "ember-resident-training-gate")
    if not os.path.isdir(gate_dir):
        # No C14 evidence at all in the window: vacuously no loop could have
        # been authorized either -- falls through to the vacuous-satisfaction
        # branch below via empty gate_receipts/loop_paths.
        gate_receipts_all = []
    else:
        gate_receipts_all = sorted(glob.glob(os.path.join(gate_dir, "*.json")))

    # --- (A) Enumerate cited Ember loop receipts, filtered to the window ----
    # The d3 native loop is the cited Ember loop; round-local-loop is another.
    loop_paths = _loop_paths_in_window(min_ts)
    loop_stamps = sorted(
        s for s in (ts_from_name(p) for p in loop_paths) if s is not None
    )
    earliest_loop = loop_stamps[0] if loop_stamps else None
    n_loops = len(loop_stamps)

    # --- (B) Find the authoritative C14 resident-training-gate verdict,
    # filtered to the window ---------------------------------------------
    # Inspect every resident-training-gate receipt in the window. A receipt
    # counts as a real C14 PASS only if its operative verdict is
    # RESIDENT_TRAINING_GATE_PASS, status PASS, every component PASS, and no
    # disqualifying invalid-token is the operative verdict. A later
    # conflation-guard audit that names a PASS receipt and BLOCKS it revokes
    # that PASS.
    # Window eligibility is resolved on the EFFECTIVE ts (import-edition
    # lineage honored via _effective_ts) rather than the on-disk filename
    # stamp, so an import-edition of pre-epoch, already-disqualified
    # substance cannot count as an in-window PASS candidate merely by being
    # copied to a fresh filename (see docs/audit/c0-c14-pass-wording-audit-
    # 20260703.md for the incident this closes).
    gate_receipts = _window_filter_gate_receipts(gate_receipts_all, min_ts)
    if not gate_receipts:
        if not loop_paths:
            # Vacuous: no C14 receipt AND no loop cited in the window ->
            # nothing has happened to file an incident against.
            emit("GREEN",
                 f"C0: no resident-training-gate receipt or Ember loop "
                 f"receipt exists in window {window} -> vacuously no "
                 "precondition-bypass finding")
        emit("RED",
             f"C0: {n_loops} Ember loop receipt(s) cited in window {window} "
             "but the resident-training-gate dir has no matching C14 "
             "receipt -> precondition ABSENT, loops ran WITHOUT "
             "authorization -> invalid_precondition_bypass")

    # Vet every in-window gate receipt against the real-C14-PASS predicate
    # (verdict/status/component/token checks, conflation-guard revocation,
    # BLOCKED-run supersession -- see _vet_gate_receipts docstring). Factored
    # out so _find_valid_disposition() can re-apply the IDENTICAL predicate
    # to a disposition's authorizing_c14_receipt without duplicating it.
    real_passes, revoked, audits, latest_verdict, latest_stamp, \
        latest_blocked_stamp = _vet_gate_receipts(gate_receipts)

    # --- (C) Decide RED/GREEN for the window ---------------------------------
    if not real_passes:
        disposition = _find_valid_disposition(loop_paths, gate_receipts_all, min_ts)
        if disposition:
            emit("GREEN",
                 f"C0: post-epoch incident DISPOSED per receipted, verified "
                 f"disposition -- {disposition}")
        reason = (
            f"C0: NO valid C14 RESIDENT_TRAINING_GATE_PASS exists in window "
            f"{window} (latest gate verdict={latest_verdict!r} @ {latest_stamp}; "
            f"{len(revoked)} PASS-label(s) revoked by conflation guard; "
            f"{n_loops} cited loop receipt(s) in window "
            f"earliest={earliest_loop}). Loops ran WITHOUT a satisfied "
            f"precondition -> invalid_precondition_bypass. "
            f"audits={audits[:3]}"
        )
        emit("RED", reason)

    # A valid C14 PASS exists in the window. CHK: it must predate the
    # earliest cited loop in the window.
    real_passes.sort()
    earliest_pass_stamp, earliest_pass_path = real_passes[0]

    if earliest_loop is None:
        # No loops cited in the window at all -> C0's prohibition is
        # vacuously satisfied AND a real C14 PASS exists.
        emit("GREEN",
             f"C0: valid C14 PASS {os.path.basename(earliest_pass_path)} "
             f"@ {earliest_pass_stamp} present and NO Ember loop receipts "
             f"cited in window {window} -> no precondition bypass")

    if earliest_pass_stamp is not None and earliest_loop is not None \
            and earliest_pass_stamp < earliest_loop:
        emit("GREEN",
             f"C0: valid C14 PASS {os.path.basename(earliest_pass_path)} "
             f"@ {earliest_pass_stamp} predates earliest cited loop "
             f"@ {earliest_loop} ({n_loops} loops, window {window}) -> "
             f"precondition satisfied before any loop")

    disposition = _find_valid_disposition(loop_paths, gate_receipts_all, min_ts)
    if disposition:
        emit("GREEN",
             f"C0: post-epoch incident DISPOSED per receipted, verified "
             f"disposition -- {disposition}")
    emit("RED",
         f"C0: a C14 PASS exists @ {earliest_pass_stamp} but does NOT "
         f"predate the earliest cited loop @ {earliest_loop} ({n_loops} "
         f"loops, window {window}) -> loop ran before the precondition "
         f"gate -> invalid_precondition_bypass")


def main():
    """Resolve the epoch, run scan() in the appropriate window, and relabel
    the raw RED/GREEN finding against the AUDIT-OK/AUDIT-INCIDENT/
    AUDIT-PENDING-EPOCH contract (GOAL.md §4.0(9)) before printing.
    """
    epoch_ts, epoch_path = find_epoch()
    try:
        scan(epoch_ts)  # None -> unfiltered/informational; else -> real audit
    except _Verdict as v:
        raw_status, raw_reason = v.status, v.reason

    if epoch_ts is None:
        print(
            f"AUDIT-PENDING-EPOCH {raw_reason} "
            f"[PRE-EPOCH INFORMATIONAL finding={raw_status} -- no "
            "goalforge-clear operator-acceptance object exists yet at "
            "receipts/acceptance/goalforge-clear-*.json (schema "
            "acceptance/v1); this is NOT an audit verdict, pre-epoch "
            "history is OUT OF AUDIT SCOPE per GOAL.md §4.0(9), the actual "
            "status is never RED/GREEN/UNEVALUABLE for this row]"
        )
        return
    final_status = "AUDIT-OK" if raw_status == "GREEN" else "AUDIT-INCIDENT"
    print(f"{final_status} {raw_reason}")


if __name__ == "__main__":
    main()
