#!/usr/bin/env python3
"""fp-30d (#247 fire-time executor, prep issue #251) — shard-rerun gate.

Closes the stale-emission gap: `validate_shards_receipt` (and therefore the
launch gate's G-shards row) validates the freeze premise the shard receipt
NAMES — a stale-freeze emission whose premises are self-consistent (pinned to
a superseded but still-on-disk freeze) passes validation. The writer enforces
freeze-counts at emit time, but gate-time must not trust that the receipt came
from the current writer. This gate binds the shard receipt to the LIVE freeze
resolved by the fp30 binder:

  1. shard receipt is git-tracked + clean (committed evidence) and matches the
     PRODUCTION name pattern (selftest siblings can never bind — fp30 lesson);
  2. receipt_check PASS + validate_shards_receipt == [] (full byte-true
     re-scan on this checkout, eng-53 reserved/oob/parity included);
  3. premises.tokenizer_freeze_receipt NAME == live freeze name AND its sha
     matches the on-disk live freeze bytes;
  4. sum(per_source content_tokens) == live freeze real_token_counts.total;
  5. each per-source content count == the freeze's per-source count.

--fire emits receipts/fp30d-shard-gate-<ts>.json (GREEN or RED — failed
verdicts are receipted too) and exits 0 iff GREEN: that exit code is the
G-shards half of the launch authorization chain (mail 14665 autonomy clause —
the gate scripts ARE the authorization instrument). Bare invocation is staged
exit 1 per the 14644 policy (launch-evidence promotion class). --selftest runs
on temp fixtures only; live-tree contact is read-only with a purity snapshot.
"""
import argparse
import glob as globmod
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from receipt_write import checked_write                 # noqa: E402
from receipt_check import validate_receipt              # noqa: E402
import fp30_total_consistency as fp30                   # noqa: E402
import token_shards_v0 as tsv                           # noqa: E402

TICKET = "FP30D-SHARD-GATE"
SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")
# production emissions only — token-shards-v0-selftest-* / fixtures never bind
_SHARDS_NAME = re.compile(r"^token-shards-v0-\d{8}T\d{6}Z\.json$")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_ts():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _tracked_and_clean(path, nc):
    """True / False / None (None = not a git work tree, e.g. selftest
    tmpdir — accepted with a note, same convention as fp30b/E1b gates)."""
    rel = os.path.relpath(path, nc).replace(os.sep, "/")
    try:
        ls = subprocess.run(["git", "ls-files", "--error-unmatch", rel],
                            cwd=nc, capture_output=True, text=True)
        if "not a git repository" in (ls.stderr or "").lower():
            return None
        if ls.returncode != 0:
            return False
        st = subprocess.run(["git", "status", "--porcelain", "--", rel],
                            cwd=nc, capture_output=True, text=True)
        return st.stdout.strip() == ""
    except FileNotFoundError:
        return None


def resolve_shards_receipt(nc, explicit=None):
    """Path of the production shard receipt to gate (explicit or newest)."""
    if explicit:
        p = explicit if os.path.isabs(explicit) else f"{nc}/{explicit}"
        if not _SHARDS_NAME.match(os.path.basename(p)):
            return None, (f"{os.path.basename(p)} is not a production "
                          "token-shards-v0-<ts>.json name")
        if not os.path.exists(p):
            return None, f"{explicit} not on disk"
        return p, None
    hits = sorted(p for p in globmod.glob(f"{nc}/receipts/token-shards-v0-*.json")
                  if _SHARDS_NAME.match(os.path.basename(p)))
    if not hits:
        return None, ("no production token-shards-v0-<ts>.json receipt on "
                      "disk (emit not finished or receipt not committed)")
    return hits[-1], None                    # newest ts-name


def gate(nc=NC, receipt=None):
    """Pure gate: (verdict_dict, violations). Writes NOTHING."""
    v = []
    live_name, live_total = fp30.live_freeze(nc)
    if live_name is None:
        return None, ["no live production tokenizer-freeze receipt resolvable"]

    rpath, err = resolve_shards_receipt(nc, receipt)
    if err:
        return None, [err]
    rname = os.path.basename(rpath)

    tracked = _tracked_and_clean(rpath, nc)
    if tracked is False:
        v.append(f"{rname} not git-tracked+clean — commit the emission "
                 "receipt before gating (portable-chain policy)")
    try:
        d = json.load(open(rpath, encoding="utf-8"))
    except Exception as e:                   # noqa: BLE001
        return None, [f"{rname} unreadable: {e}"]

    for f in validate_receipt(d):
        v.append(f"receipt_check: {f}")
    for f in tsv.validate_shards_receipt(d, nc):
        v.append(f"shard-contract: {f}")

    # live-freeze binding (the checks validate_shards_receipt cannot do —
    # it verifies the premise the receipt NAMES, not the LIVE freeze)
    prem = ((d.get("premises") or {}).get("tokenizer_freeze_receipt")) or {}
    pname, psha = prem.get("name"), prem.get("sha256")
    if pname != live_name:
        v.append(f"freeze-binding: premise names {pname!r}, live freeze is "
                 f"{live_name!r} — stale emission")
    else:
        lp = f"{nc}/receipts/{live_name}"
        live_sha = _sha(lp)
        if psha != live_sha:
            v.append(f"freeze-binding: premise sha {str(psha)[:12]} != live "
                     f"freeze bytes {live_sha[:12]}")
    # content totals must reproduce the LIVE freeze counts (content only —
    # separators are writer-inserted and excluded from real_token_counts)
    try:
        fz = json.load(open(f"{nc}/receipts/{live_name}", encoding="utf-8"))
    except Exception as e:                   # noqa: BLE001
        return None, [f"live freeze {live_name} unreadable: {e}"]
    fz_counts = fz.get("real_token_counts") or {}
    ps = d.get("per_source") or {}
    content_total = sum(c.get("content_tokens", 0) for c in ps.values()
                        if isinstance(c, dict))
    if content_total != live_total:
        v.append(f"freeze-binding: sum(content_tokens) {content_total} != "
                 f"live freeze total {live_total}")
    for src, exp in fz_counts.items():
        if src == "total" or not isinstance(exp, int):
            continue
        got = (ps.get(src) or {}).get("content_tokens") \
            if isinstance(ps.get(src), dict) else None
        if got != exp:
            v.append(f"freeze-binding: {src} content_tokens {got} != "
                     f"freeze {exp}")

    verdict = {
        "ticket": TICKET,
        "ts": _utc_ts(),
        "issue": 247,
        "verdict": "GREEN" if not v else "RED",
        "violations": v,
        "shards_receipt": rname,
        "shards_receipt_sha256": _sha(rpath),
        "shards_receipt_tracked_clean": tracked,
        "live_freeze": live_name,
        "live_freeze_total": live_total,
        "binding_basis": ("shard receipt gated against the LIVE fp30-resolved "
                          "freeze, not the premise it names — stale "
                          "self-consistent emissions cannot certify G-shards"),
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }
    return verdict, v


def fire(nc=NC, receipt=None):
    verdict, v = gate(nc, receipt)
    if verdict is None:
        for f in v:
            print(f"FP30D_REFUSAL: {f}")
        raise SystemExit(1)
    out = f"{nc}/receipts/fp30d-shard-gate-{verdict['ts']}.json"
    checked_write(out, verdict)
    for f in v:
        print(f"  VIOLATION: {f}")
    print(f"FP30D_SHARD_GATE_{verdict['verdict']} {os.path.relpath(out, nc)}")
    raise SystemExit(0 if verdict["verdict"] == "GREEN" else 1)


# ---------------------------------------------------------------------------
# selftest — temp fixtures only; live contact READ-ONLY + purity snapshot
# ---------------------------------------------------------------------------
def _live_snapshot():
    rdir = f"{NC}/receipts"
    return tuple(sorted(os.listdir(rdir))) if os.path.isdir(rdir) else None


def _fixture(td):
    """Minimal tree where the production shard receipt binds a production
    freeze and passes validate_shards_receipt (mirrors the tsv selftest)."""
    import struct
    os.makedirs(f"{td}/receipts")
    os.makedirs(f"{td}/shards")
    os.makedirs(f"{td}/tokenizer")
    json.dump({"ticket": "FIXTURE-ASM", "ts": "20260101T000000Z"},
              open(f"{td}/receipts/fixture-assembly.json", "w"))
    json.dump({"vocab_size": 32000},
              open(f"{td}/tokenizer/tokenizer.json", "w"))

    ids = [8 + (i % 100) for i in range(4096)]
    with open(f"{td}/shards/v0-00000.bin", "wb") as fh:
        fh.write(b"".join(struct.pack("<H", x) for x in ids))
    total = 4096
    content = total - 5                       # 5 writer-inserted separators

    freeze_name = "tokenizer-freeze-20260101T000000Z.json"
    json.dump({"ticket": "TOKENIZER-FREEZE-V0", "ts": "20260101T000000Z",
               "real_token_counts": {"code_github_clean": content,
                                     "total": content}},
              open(f"{td}/receipts/{freeze_name}", "w"))

    per_source = {s: {"content_tokens": 0, "separator_tokens": 0,
                      "stream_tokens": 0} for s in tsv.EXPECTED_SOURCES}
    per_source["code_github_clean"] = {"content_tokens": content,
                                       "separator_tokens": 5,
                                       "stream_tokens": total}
    d = {
        "ticket": tsv.TICKET,
        "ts": "20260611T000000Z",
        "shard_dir": "shards",
        "shards": [{"name": "v0-00000.bin",
                    "sha256": _sha(f"{td}/shards/v0-00000.bin"),
                    "n_tokens": total}],
        "total_stream_tokens": total,
        "per_source": per_source,
        "separator_id": tsv.SEPARATOR_ID,
        "reserved_band_guard": {"reserved_ids": tsv.RESERVED_IDS,
                                "max_id_lt": tsv.VOCAB_SIZE,
                                "reserved_ids_observed_in_stream": 0},
        "loader_windows": {"seq": tsv.SEQ, "n_mtp": tsv.N_MTP,
                           "block_len": tsv.BLOCK_LEN,
                           "n_windows": (total - tsv.BLOCK_LEN) // tsv.SEQ + 1},
        "premises": {
            "assembly_receipt": {
                "name": "fixture-assembly.json",
                "sha256": _sha(f"{td}/receipts/fixture-assembly.json")},
            "tokenizer_freeze_receipt": {
                "name": freeze_name,
                "sha256": _sha(f"{td}/receipts/{freeze_name}")},
            "tokenizer_json": {
                "path": "tokenizer/tokenizer.json",
                "sha256": _sha(f"{td}/tokenizer/tokenizer.json")},
        },
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }
    sp = f"{td}/receipts/token-shards-v0-20260611T000000Z.json"
    json.dump(d, open(sp, "w"))
    return sp, freeze_name, content


def _selftest():
    import tempfile
    live_before = _live_snapshot()

    # happy path: GREEN, zero violations; emitted verdict passes receipt_check
    with tempfile.TemporaryDirectory() as td:
        _fixture(td)
        verdict, v = gate(nc=td)
        assert verdict and verdict["verdict"] == "GREEN", (verdict, v)
        assert verdict["shards_receipt_tracked_clean"] is None  # tmpdir
        assert validate_receipt(verdict) == [], validate_receipt(verdict)

    # stale emission: a NEWER production freeze supersedes the one the shard
    # receipt names -> binding violation names BOTH the premise and the total
    with tempfile.TemporaryDirectory() as td:
        _, _, content = _fixture(td)
        json.dump({"ticket": "TOKENIZER-FREEZE-V0", "ts": "20260102T000000Z",
                   "real_token_counts": {"code_github_clean": content + 4,
                                         "total": content + 4}},
                  open(f"{td}/receipts/tokenizer-freeze-20260102T000000Z.json",
                       "w"))
        verdict, v = gate(nc=td)
        assert verdict["verdict"] == "RED", v
        assert any("stale emission" in x for x in v), v
        assert any("!= live freeze total" in x for x in v), v

    # content-total drift vs the bound freeze -> RED even when premise matches
    with tempfile.TemporaryDirectory() as td:
        _, freeze_name, content = _fixture(td)
        fp = f"{td}/receipts/{freeze_name}"
        fz = json.load(open(fp))
        fz["real_token_counts"]["total"] = content + 1
        json.dump(fz, open(fp, "w"))
        # premise sha now drifts too — both violations must fire
        verdict, v = gate(nc=td)
        assert verdict["verdict"] == "RED", v
        assert any("sum(content_tokens)" in x for x in v), v
        assert any("premise sha" in x for x in v), v

    # no production shard receipt -> refusal (not a RED verdict)
    with tempfile.TemporaryDirectory() as td:
        _, freeze_name, _ = _fixture(td)
        os.remove(f"{td}/receipts/token-shards-v0-20260611T000000Z.json")
        verdict, v = gate(nc=td)
        assert verdict is None and any("no production" in x for x in v), v

    # selftest-sibling name can never bind (explicit or glob)
    with tempfile.TemporaryDirectory() as td:
        sp, _, _ = _fixture(td)
        sib = f"{td}/receipts/token-shards-v0-selftest-20260611T000000Z.json"
        os.replace(sp, sib)
        verdict, v = gate(nc=td)
        assert verdict is None and any("no production" in x for x in v), v
        verdict, v = gate(nc=td, receipt=f"receipts/{os.path.basename(sib)}")
        assert verdict is None and any("not a production" in x for x in v), v

    # live-tree contact is READ-ONLY: gate() on the live tree (whatever its
    # state — refusal pre-emit, verdict post-emit) writes nothing
    gate(nc=NC)
    assert _live_snapshot() == live_before, \
        "SELFTEST PURITY VIOLATION: live receipts changed during --selftest"
    print("FP30D_SHARD_GATE_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fire", action="store_true",
                    help="gate the committed emission receipt and write the "
                         "fp30d verdict receipt; exit 0 iff GREEN")
    ap.add_argument("--receipt", help="explicit shard receipt (default: "
                                      "newest production token-shards-v0-*)")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if not a.fire:
        print("FP30D_SHARD_GATE_STAGED (--fire gates the committed "
              "TOKEN-SHARDS-V0 emission against the live freeze; fires on "
              "#247's trigger)")
        raise SystemExit(1)
    fire(receipt=a.receipt)


if __name__ == "__main__":
    main()
