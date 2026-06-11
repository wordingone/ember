"""fp32_r10_failure_taxonomy.py — daemon-failure taxonomy from the job
store (#234, fp-32 ledger row R10 discharge).

R10 sits at 'observational' (lifetime failed/total from train_list). The
launch-planning question is narrower: are there EVIDENCED spontaneous
mid-run deaths of long-running training jobs in the ember era, and what
does one interruption cost given receipted bit-exact resume?

Per-job logs for pre-log_name failures are EXPIRED (legacy shared
eval.log/train.log overwritten by later jobs), so the taxonomy is
derived from the store itself:

  era table     — month -> {total, failed} (March = csi-classifier era,
                  a different project; June = ember/nc-ladder era).
  gap bound     — for each June failure, seconds until the NEXT dispatch
                  in the store. A failure followed within GAP_FAST_S by
                  the next dispatch was a fast-fail (died at/near start,
                  operator relaunched) — setup-class, not a mid-run
                  death. Heuristic caveat: dispatches can overlap
                  (parent+eval sub-jobs), so the gap is an operator-
                  iteration bound, not a hard process-lifetime bound;
                  it is only ever used to classify TOWARD benign with
                  the caveat recorded, never to evidence a death.
  classes       — ROOT-CAUSED > MISUSE-CLASS > NON-EMBER-TRACK >
                  FAST-FAIL-BOUNDED > UNKNOWN-EVIDENCE-EXPIRED.

Anything not provably benign stays UNKNOWN — the headline counts
evidenced mid-run deaths (receipt-grade) and unknowns (honest residue)
separately, and the pessimistic interruption budget treats every
unknown as if it were a mid-run death.

Store path: resolved via glob (WSL UNC share from Windows, ~ inside
WSL). The resolved path contains a home directory name and is NEVER
written to code, receipt, or output — recorded as the redacted form.

`--selftest` pure-logic on fixtures; `--run` reads the live store and
emits receipts/fp32-r10-taxonomy-<ts>.json. Read-only on the store.
"""
import glob as globmod
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write                 # noqa: E402
from receipt_check import validate_receipt              # noqa: E402

SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")
STORE_REDACTED = "~/.avir/train/jobs.json (WSL Ubuntu, auto-resolved)"
GAP_FAST_S = 600                       # fast-fail bound (operator relaunch)
EMBER_MONTH = "2026-06"
EMBER_PATH_MARK = "/nc-ladder/"
MISUSE_BASENAMES = {"check_mail.py", "peek_mail_check.py"}
ROOT_CAUSED = {
    "93e74934": ("R3 torch.compile dynamo NameError at bench cell — "
                 "root-caused, per-cell containment added; "
                 "receipts/fp32-step-econ-20260611T142831Z.json"),
    "cb003e88": ("D-gate harness effective-count divisor bug — caught "
                 "live, fixed same session; successful re-run receipted "
                 "receipts/d-gate-adapter_model-20260611T070448Z.json"),
}
RESUME_EVIDENCE = "receipts/v0ext-selftest-20260611T150308Z.json"
V0_RUN_DAYS = 3.352                    # fp-32 b24 projection (ledger R1)


def resolve_store():
    """First match wins; resolved path is used but never recorded."""
    pats = (os.environ.get("FP32_R10_STORE") or "",
            "//wsl.localhost/Ubuntu/home/*/.avir/train/jobs.json",
            os.path.expanduser("~/.avir/train/jobs.json"))
    for pat in pats:
        hits = globmod.glob(pat) if pat else []
        if hits:
            return hits[0]
    raise SystemExit("FP32_R10_STORE_NOT_FOUND (daemon job store)")


def _parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def classify(jobs):
    """jobs: dict id -> record (job store shape). Returns the analysis
    block (era table + June-failure rows + counts)."""
    recs = sorted(jobs.values(), key=lambda j: j["started_at"])
    starts = [_parse_ts(j["started_at"]) for j in recs]

    era = {}
    for j in recs:
        m = j["started_at"][:7]
        era.setdefault(m, {"total": 0, "failed": 0})
        era[m]["total"] += 1
        if j.get("status") == "failed":
            era[m]["failed"] += 1

    rows = []
    for i, j in enumerate(recs):
        if j.get("status") != "failed" or j["started_at"][:7] != EMBER_MONTH:
            continue
        script = (j.get("config") or {}).get("script", "")
        base = os.path.basename(script)
        gap = None
        for k in range(i + 1, len(recs)):
            if starts[k] > starts[i]:
                gap = round((starts[k] - starts[i]).total_seconds(), 1)
                break
        if j["job_id"] in ROOT_CAUSED:
            cls, why = "ROOT-CAUSED", ROOT_CAUSED[j["job_id"]]
        elif base in MISUSE_BASENAMES:
            cls, why = "MISUSE-CLASS", ("daemon used as a WSL shell — not a "
                                        "training job; no launch relevance")
        elif EMBER_PATH_MARK not in script:
            cls, why = "NON-EMBER-TRACK", ("script outside nc-ladder — "
                                           "counts toward daemon reliability "
                                           "denominator only")
        elif gap is not None and gap <= GAP_FAST_S:
            cls, why = "FAST-FAIL-BOUNDED", (f"next dispatch {gap}s after "
                                             f"start — operator fast-fail "
                                             f"iteration (setup-class)")
        else:
            cls, why = "UNKNOWN-EVIDENCE-EXPIRED", (
                "pre-log_name job; legacy shared log overwritten — cannot "
                "classify; treated as mid-run death in the pessimistic "
                "interruption budget")
        rows.append({"job_id": j["job_id"], "script": base,
                     "started_at": j["started_at"],
                     "gap_to_next_dispatch_s": gap, "class": cls,
                     "basis": why})

    counts = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    return {"era_table": era, "june_failure_rows": rows,
            "class_counts": counts}


def interruption_budget(analysis):
    """Pessimistic budget: every UNKNOWN counted as a mid-run death over
    the observed ember-era span; scaled to the projected v0 run."""
    rows = analysis["june_failure_rows"]
    unknowns = [r for r in rows if r["class"] == "UNKNOWN-EVIDENCE-EXPIRED"]
    ember_rows = [r for r in rows
                  if r["class"] not in ("NON-EMBER-TRACK", "MISUSE-CLASS")]
    if rows:
        days = sorted(r["started_at"][:10] for r in rows)
        span_days = max(
            ( _parse_ts(days[-1] + "T23:59:59+00:00")
              - _parse_ts(days[0] + "T00:00:00+00:00")).total_seconds()
            / 86400.0, 1.0)
    else:
        span_days = 1.0
    rate = len(unknowns) / span_days
    return {
        "evidenced_midrun_deaths_june_ember": 0,
        "note_on_evidence": ("evidenced count is 0 by construction (no "
                             "death was evidenced); UNKNOWN rows are the "
                             "honest residue — not evidence of deaths, "
                             "unclassifiable, budgeted pessimistically"),
        "june_ember_failures": len(ember_rows),
        "unknown_rows": len(unknowns),
        "observed_span_days": round(span_days, 1),
        "pessimistic_interruptions_per_day": round(rate, 3),
        "pessimistic_interruptions_v0_run": round(rate * V0_RUN_DAYS, 2),
        "v0_run_days_basis": V0_RUN_DAYS,
        "cost_per_interruption": (
            "bounded by one checkpoint interval + restart overhead — "
            f"resume is bit-exact ({RESUME_EVIDENCE}); cadence decision "
            "stays measure-first (#231)"),
    }


def run(store_path):
    raw = open(store_path, "rb").read()
    jobs = json.loads(raw.decode("utf-8"))
    analysis = classify(jobs)
    budget = interruption_budget(analysis)
    return {
        "ticket": "FP32-R10-TAXONOMY",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "issue": 234,
        "store": {"path": STORE_REDACTED,
                  "sha256": hashlib.sha256(raw).hexdigest(),
                  "n_jobs": len(jobs),
                  "read_note": "store mutates with every dispatch — the "
                               "sha pins the exact snapshot analyzed"},
        "analysis": analysis,
        "interruption_budget": budget,
        "caveats": [
            "gap_to_next_dispatch is an operator-iteration bound, not a "
            "hard process-lifetime bound (dispatches can overlap); it "
            "only ever classifies TOWARD benign, never evidences a death",
            "pre-log_name failures have expired logs (legacy shared-log "
            "overwrite) — per-job log_name now retains evidence forward",
            "March era is a different project (pre-ember) — reported in "
            "the era table, excluded from launch-relevant classification",
        ],
        "provenance_rule": "every row re-derived from the named store "
                           "snapshot's fields by this script's arithmetic "
                           "— no free-typed numbers",
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


def _fixture():
    def j(jid, ts, status, script, typ="eval"):
        return {"job_id": jid, "type": typ, "status": status,
                "started_at": ts, "pid": 1,
                "config": {"script": script, "output_dir": "/tmp/x"}}
    s_emb = "/mnt/b/M/avir/leo/state/nc-ladder/scripts/t2_x.py"
    s_web = "/mnt/b/M/avir/leo/state/wasm-build/rebuild_66.py"
    return {
        # march era — different project
        "m1": j("m1", "2026-03-07T06:00:00+00:00", "failed",
                "/mnt/b/M/avir/products/csi/train.py"),
        # june: fast-fail pair (90 s gap), then success
        "a1": j("a1", "2026-06-10T03:00:00+00:00", "failed", s_emb),
        "a2": j("a2", "2026-06-10T03:01:30+00:00", "failed", s_emb),
        "a3": j("a3", "2026-06-10T03:03:00+00:00", "completed", s_emb),
        # june: root-caused (id pinned in ROOT_CAUSED)
        "93e74934": j("93e74934", "2026-06-11T14:23:32+00:00", "failed",
                      "/mnt/b/M/avir/leo/state/nc-ladder/scripts/"
                      "fp32_step_econ_bench.py"),
        # june: misuse + non-ember
        "c1": j("c1", "2026-06-10T05:00:00+00:00", "failed",
                "/mnt/b/M/avir/leo/state/nc-ladder/scripts/check_mail.py"),
        "w1": j("w1", "2026-06-10T06:00:00+00:00", "failed", s_web),
        # june: trailing failure with NO bounding successor -> UNKNOWN
        "u1": j("u1", "2026-06-11T20:00:00+00:00", "failed", s_emb),
    }


def _selftest():
    a = classify(_fixture())
    assert a["era_table"]["2026-03"] == {"total": 1, "failed": 1}
    assert a["era_table"]["2026-06"]["failed"] == 6, a["era_table"]
    by = {r["job_id"]: r for r in a["june_failure_rows"]}
    assert by["a1"]["class"] == "FAST-FAIL-BOUNDED" and \
        by["a1"]["gap_to_next_dispatch_s"] == 90.0, by["a1"]
    assert by["a2"]["class"] == "FAST-FAIL-BOUNDED"
    assert by["93e74934"]["class"] == "ROOT-CAUSED"
    assert by["c1"]["class"] == "MISUSE-CLASS"
    assert by["w1"]["class"] == "NON-EMBER-TRACK"
    assert by["u1"]["class"] == "UNKNOWN-EVIDENCE-EXPIRED", by["u1"]
    assert "m1" not in by                       # march excluded from rows
    b = interruption_budget(a)
    assert b["unknown_rows"] == 1 and b["june_ember_failures"] == 4
    assert b["observed_span_days"] == 2.0, b
    assert b["pessimistic_interruptions_per_day"] == 0.5
    # receipt shape on the fixture
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "jobs.json")
        json.dump(_fixture(), open(p, "w"))
        r = run(p)
        assert r["store"]["path"] == STORE_REDACTED
        assert "home" not in json.dumps(r), "path leak"
        assert validate_receipt(r) == [], validate_receipt(r)
    print("FP32_R10_TAXONOMY_SELFTEST_PASS")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return
    if "--run" not in sys.argv:
        print("FP32_R10_TAXONOMY_STAGED (--run analyzes the live store)")
        raise SystemExit(1)
    receipt = run(resolve_store())
    out = f"{NC}/receipts/fp32-r10-taxonomy-{receipt['ts']}.json"
    checked_write(out, receipt)
    f = validate_receipt(json.load(open(out, encoding="utf-8")))
    if f:
        raise SystemExit(f"emitted receipt FAILS receipt_check: {f}")
    print(json.dumps({"era": receipt["analysis"]["era_table"],
                      "classes": receipt["analysis"]["class_counts"],
                      "budget": receipt["interruption_budget"]}, indent=1))
    print(f"FP32_R10_TAXONOMY_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
