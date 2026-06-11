"""v0_pretrain_launch_gate.py — fail-closed dispatch gate for the owned-core
v0 pretrain (NC2-own, c03 shape: 0.368B QAT, seq 1024, w1-governed 4090).

This shim embeds research/v0-launch-gate.md as named, receipt-checkable
assertions. The v0 trainer (#167 — scripts/timeshare_pretrain.py extended
against configs/v0-pretrain-config.json) is dispatched THROUGH this gate:
it loads each named receipt, receipt_checks it, verifies the pins, and
REFUSES with the failing G-row(s) named. No row is waivable except by the
user, by name. Same fail-closed grammar as fp25_surfaceb select mode.

Today's live state (recorded in the emitted receipt, not asserted here so
the selftest stays time-robust): G-prereg is GREEN (eng-48/#181 wired the
fp26 premise check). The blocking row is now G-shards (eng-49/#183): the
packed uint16 shards that ARE the live-training input have not been produced
(production HELD pending the shard-production call), so --live is correctly
refused. The other six rows are GREEN.
"""
import argparse
import copy
import datetime
import glob
import hashlib
import json
import os
import sys

NC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(NC, "scripts"))
from receipt_check import validate_receipt          # noqa: E402
import v0_config_check                              # noqa: E402
import fp26_prereg                                  # noqa: E402
import token_shards_v0                              # noqa: E402

# ---- binding pins (changing any of these is a contract change) -----------
ASSEMBLY_RECEIPT = "eng36-assembly-20260611T052337Z.json"
ASSEMBLY_SHA = ("a29d2e567f1853966cc72a4890eadc963164265e"
                "4f24a89cadea24d9ff5b80c2")
TOKENIZER_RECEIPT = "tokenizer-freeze-20260611T060423Z.json"
CONFIG = f"{NC}/configs/v0-pretrain-config.json"
DEADLINE = datetime.date(2026, 6, 22)
# fp19-bench receipted-unstacked days-to-compute-optimal for the c03-qat core
ENVELOPE_DAYS_FLOOR = 4.55
WORLD_SPECS = ["research/fp22-corpus-world.md", "research/world-choice-r2.md"]
RESERVED_BAND_N = 8           # NC2 v0 LOCK #1 (ids 0-7)
HARD_BAR_BYTES = 100 * 10**9  # corpus <100GB hard bar
FP26_PREREG_GLOB = "receipts/fp26-prereg-*.json"
TOKEN_SHARDS_GLOB = "receipts/token-shards-v0-*.json"
SHA_CONVENTION = ("sha256 over the exact on-disk file bytes, no "
                  "normalization; receipt paths carry the git -text pin")


# ---- helpers -------------------------------------------------------------
def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _receipt_clean(name):
    """(True, dict) if the receipt exists and passes receipt_check;
    (False, reason) otherwise. Fail-closed on every error path."""
    p = f"{NC}/receipts/{name}"
    if not os.path.exists(p):
        return False, f"{name} not on disk"
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return False, f"{name} unreadable: {e}"
    findings = validate_receipt(d)
    if findings:
        return False, f"{name} receipt_check FAIL: {findings}"
    return True, d


# ---- G-rows (each returns (status, detail); status in GREEN|BLOCKED) ------
def g_corpus():
    ok, d = _receipt_clean(ASSEMBLY_RECEIPT)
    if not ok:
        return "BLOCKED", d
    s = _sha(f"{NC}/receipts/{ASSEMBLY_RECEIPT}")
    if s != ASSEMBLY_SHA:
        return "BLOCKED", f"assembly sha {s[:12]} != pin {ASSEMBLY_SHA[:12]}"
    kept = d.get("totals", {}).get("text_bytes_kept")
    if kept is None:
        return "BLOCKED", "totals.text_bytes_kept missing"
    if kept >= HARD_BAR_BYTES:
        return "BLOCKED", f"text_bytes_kept {kept} >= 100GB hard bar"
    return "GREEN", f"sha pin match; {kept / 1e9:.2f} GB < 100 GB"


def g_tokenizer():
    ok, d = _receipt_clean(TOKENIZER_RECEIPT)
    if not ok:
        return "BLOCKED", d
    if d.get("assembly_receipt_sha256") != ASSEMBLY_SHA:
        return "BLOCKED", "tokenizer receipt does not pin the assembly sha"
    if d.get("tokens_pending_tokenizer_freeze") is not False:
        return "BLOCKED", "tokens_pending_tokenizer_freeze != false"
    tot = (d.get("real_token_counts") or {}).get("total")
    if not tot:
        return "BLOCKED", "real_token_counts.total missing/zero"
    band = d.get("reserved_band") or {}
    if len(band) != RESERVED_BAND_N:
        return "BLOCKED", f"reserved band {len(band)} ids != {RESERVED_BAND_N}"
    if d.get("vocab_size") != 32000:
        return "BLOCKED", f"vocab_size {d.get('vocab_size')} != 32000"
    return "GREEN", f"pin match; {tot:,} real tokens; band {RESERVED_BAND_N} ids"


def g_shards():
    # eng-49 (#183): the packed uint16 shards ARE the live-training input. The
    # gate previously had no row for them, so all-7-green printed "dispatch
    # permitted" with zero .bin on disk (fail-open w.r.t. the training input,
    # same class as eng-46/eng-48). A TOKEN-SHARDS-V0 receipt whose declared
    # shards are present + byte-matched is REQUIRED before --live. No receipt
    # -> BLOCKED (shards not produced; production is HELD pending the
    # shard-production call). token_shards_v0.validate_shards_receipt is
    # fail-closed and re-derives counts from the bytes.
    cands = sorted(glob.glob(f"{NC}/{TOKEN_SHARDS_GLOB}"))
    if not cands:
        return "BLOCKED", ("no token-shards-v0-*.json receipt — packed shards "
                           "not produced; --live has no training input "
                           "(production HELD pending the shard-production call)")
    name = os.path.basename(cands[-1])
    ok, d = _receipt_clean(name)
    if not ok:
        return "BLOCKED", d
    viol = token_shards_v0.validate_shards_receipt(d, NC)
    if viol:
        return "BLOCKED", f"{name} shard contract FAIL: {viol}"
    return "GREEN", f"{name} shards present + byte-matched; --live input ready"


def g_config():
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    v = v0_config_check.check(cfg, launch=True)
    if v:
        return "BLOCKED", f"v0_config_check launch violations: {v}"
    return "GREEN", "V0_CONFIG_GREEN (launch mode)"


def g_governor():
    # named independently per the gate table even though g_config folds it in
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    g = cfg.get("governor", {})
    f = v0_config_check.GOVERNOR_FLOOR
    if g.get("vram_fraction", 1.0) > f["vram_fraction"]:
        return "BLOCKED", "governor.vram_fraction looser than floor 0.80"
    if g.get("margin_gib_floor", 0) < f["margin_gib_floor"]:
        return "BLOCKED", "governor.margin_gib_floor below 1.5"
    if g.get("pace_s_per_step", 0) < f["pace_s_per_step"]:
        return "BLOCKED", "governor.pace_s_per_step below 0.05"
    return "GREEN", "floor vram<=0.80 / margin>=1.5GiB / pace>=0.05s (tighten-only)"


def g_world():
    missing = [w for w in WORLD_SPECS if not os.path.exists(f"{NC}/{w}")]
    if missing:
        return "BLOCKED", f"world spec missing: {missing}"
    return "GREEN", f"world specs present ({len(WORLD_SPECS)})"


def g_budget(launch_date):
    days = (DEADLINE - launch_date).days
    if days < ENVELOPE_DAYS_FLOOR:
        return "BLOCKED", (f"days-remaining {days} < envelope floor "
                           f"{ENVELOPE_DAYS_FLOOR} (fp19-bench unstacked)")
    return "GREEN", (f"{days} d to {DEADLINE.isoformat()} >= "
                     f"{ENVELOPE_DAYS_FLOOR} d unstacked envelope")


def g_prereg():
    cands = sorted(glob.glob(f"{NC}/{FP26_PREREG_GLOB}"))
    if not cands:
        return "BLOCKED", ("no fp26-prereg-*.json receipt — round-3 prereg "
                           "not frozen (awaits monitor MDE-wording reply, "
                           "mail 14582 ask #2)")
    name = os.path.basename(cands[-1])
    ok, d = _receipt_clean(name)
    if not ok:
        return "BLOCKED", d
    if not d.get("prereg_frozen"):
        return "BLOCKED", f"{name} lacks prereg_frozen:true"
    # eng-48 (#181): the frozen receipt existing + prereg_frozen:true is NOT
    # sufficient — the prereg's PREMISES must still hold (decision-artifact
    # sha, pinned premise receipts, support receipts). Without this call the
    # row was fail-OPEN (same class as eng-46): a drifted premise passed
    # silently. check_premises() is fail-closed; any violation blocks.
    premise_violations = fp26_prereg.check_premises(NC)
    if premise_violations:
        return "BLOCKED", (f"{name} frozen but prereg premises FAIL: "
                           f"{premise_violations}")
    return "GREEN", f"{name} frozen; premises hold"


ROWS = ["G-corpus", "G-tokenizer", "G-shards", "G-config", "G-governor",
        "G-world", "G-budget", "G-prereg"]


def gate(launch_date):
    """Returns [(row, status, detail), ...] in table order."""
    out = []
    for name in ROWS:
        if name == "G-corpus":
            st, dt = g_corpus()
        elif name == "G-tokenizer":
            st, dt = g_tokenizer()
        elif name == "G-shards":
            st, dt = g_shards()
        elif name == "G-config":
            st, dt = g_config()
        elif name == "G-governor":
            st, dt = g_governor()
        elif name == "G-world":
            st, dt = g_world()
        elif name == "G-budget":
            st, dt = g_budget(launch_date)
        elif name == "G-prereg":
            st, dt = g_prereg()
        out.append((name, st, dt))
    return out


def _utc_ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ")


def emit(launch_date, rows):
    ts = _utc_ts()
    blocked = [r[0] for r in rows if r[1] != "GREEN"]
    receipt = {
        "ticket": "V0-LAUNCH-GATE",
        "ts": ts,
        "launch_date": launch_date.isoformat(),
        "deadline": DEADLINE.isoformat(),
        "rows": {r[0]: {"status": r[1], "detail": r[2]} for r in rows},
        "all_green": not blocked,
        "blocked_rows": blocked,
        "pins": {
            "assembly_receipt": ASSEMBLY_RECEIPT,
            "assembly_sha256": ASSEMBLY_SHA,
            "tokenizer_receipt": TOKENIZER_RECEIPT,
            "config": "configs/v0-pretrain-config.json",
            "envelope_days_floor": ENVELOPE_DAYS_FLOOR,
        },
        "dispatch_rule": ("v0 pretrain refuses unless all_green; the failing "
                          "G-row(s) are named in blocked_rows. No row waivable "
                          "except by the user by name."),
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }
    path = f"{NC}/receipts/v0-launch-gate-{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    # checked write — the emitted receipt must itself pass receipt_check
    reloaded = json.load(open(path, encoding="utf-8"))
    findings = validate_receipt(reloaded)
    if findings:
        raise SystemExit(f"EMITTED RECEIPT FAILS receipt_check: {findings}")
    return path


def _print(rows):
    for name, st, dt in rows:
        mark = "OK " if st == "GREEN" else "XX "
        print(f"  {mark}{name:<12} {st:<8} {dt}")


def _selftest():
    from datetime import date
    # green-today rows (these are the frozen contract; if one breaks the
    # contract drifted and the selftest SHOULD fail)
    assert g_corpus()[0] == "GREEN", g_corpus()
    assert g_tokenizer()[0] == "GREEN", g_tokenizer()
    assert g_config()[0] == "GREEN", g_config()
    assert g_governor()[0] == "GREEN", g_governor()
    assert g_world()[0] == "GREEN", g_world()
    # shards: time-robust — BLOCKED iff no token-shards-v0 receipt is on disk
    # (eng-49 #183). Today none exists, so the row must BLOCK; this is what
    # keeps the gate from printing "dispatch permitted" with no training input.
    shard_cands = glob.glob(f"{NC}/{TOKEN_SHARDS_GLOB}")
    if not shard_cands:
        st, dt = g_shards()
        assert st == "BLOCKED" and "not produced" in dt, (st, dt)
    else:
        # a receipt present is GREEN only if its declared shards are present +
        # byte-matched; the validator is exercised in token_shards_v0 selftest.
        assert g_shards()[0] in ("GREEN", "BLOCKED")
    # budget: green with margin, blocks past the envelope floor
    assert g_budget(date(2026, 6, 11))[0] == "GREEN"
    assert g_budget(date(2026, 6, 20))[0] == "BLOCKED"   # 2 d < 4.55
    # prereg: blocked iff no frozen receipt (time-robust)
    cands = glob.glob(f"{NC}/{FP26_PREREG_GLOB}")
    if not cands:
        assert g_prereg()[0] == "BLOCKED", g_prereg()
    else:
        # eng-48 (#181): a frozen receipt present is GREEN only if the prereg
        # premises hold. A drifted premise (mutated decision sha) MUST flip
        # the row to BLOCKED — proves G-prereg is no longer fail-open.
        assert g_prereg()[0] == "GREEN", g_prereg()
        _good_dsha = fp26_prereg.DECISION_SHA
        fp26_prereg.DECISION_SHA = "0" * 64
        st, dt = g_prereg()
        assert st == "BLOCKED" and "premises FAIL" in dt, (st, dt)
        fp26_prereg.DECISION_SHA = _good_dsha
        assert g_prereg()[0] == "GREEN", g_prereg()
    # mutation: wrong assembly pin -> G-corpus blocks (fail-closed)
    global ASSEMBLY_SHA
    good = ASSEMBLY_SHA
    ASSEMBLY_SHA = "0" * 64
    assert g_corpus()[0] == "BLOCKED"
    ASSEMBLY_SHA = good
    assert g_corpus()[0] == "GREEN"
    # mutation: loosened governor floor is caught (launch fail-closed)
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    bad = copy.deepcopy(cfg)
    bad["governor"]["vram_fraction"] = 0.95
    assert v0_config_check.check(bad) != []
    # gate composition returns all rows
    rows = gate(date(2026, 6, 11))
    assert [r[0] for r in rows] == ROWS
    print("V0_LAUNCH_GATE_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit", action="store_true",
                    help="write the dated launch-gate receipt")
    ap.add_argument("--launch-date", default=None,
                    help="YYYY-MM-DD; default = today (system date)")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if a.launch_date:
        ld = datetime.date.fromisoformat(a.launch_date)
    else:
        ld = datetime.date.today()
    rows = gate(ld)
    _print(rows)
    blocked = [r[0] for r in rows if r[1] != "GREEN"]
    if a.emit:
        path = emit(ld, rows)
        print(f"receipt: {os.path.relpath(path, NC)}")
    if blocked:
        print(f"LAUNCH REFUSED — blocked rows: {', '.join(blocked)}")
        raise SystemExit(1)
    print("V0_LAUNCH_GATE_GREEN — dispatch permitted")


if __name__ == "__main__":
    main()
