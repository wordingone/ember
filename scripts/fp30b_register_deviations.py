"""fp30b_register_deviations.py — #218's apply-half: register the
token-total deviations against the superseding tokenizer-freeze receipt
(#238; fire carrier #218; frozen rule mail 14628).

fp30_total_consistency.py is the DETECT half: when the re-derived freeze
lands, `--check` flips RED naming each stale pin. This module is the
APPLY half — it turns that worklist into registered deviations
mechanically, fail-closed, receipt-emitting:

  config pin    — configs/v0-pretrain-config.json  "real_token_total":
                  textual single-match edit (whole-file json round-trip
                  would reformat the frozen contract; a 0- or >1-match
                  regex is a refusal, never a guess).
  gate pin      — scripts/v0_pretrain_launch_gate.py TOKENIZER_RECEIPT
                  constant: same single-match discipline.
  fp-27 pin     — the live fp27-prereg receipt's base_policy budget
                  literal: a SUCCESSOR receipt is emitted (newest-glob =
                  live, same binding fp30 uses) carrying every original
                  field byte-for-byte through json round-trip, the
                  base_policy prose re-pointed old->new total (digit and
                  comma forms), plus a deviation_registrations block.
                  The original frozen receipt is never touched.

Preconditions (each a named refusal, never a warning):
  * fp30 --check must be RED (a green tree has nothing to register);
  * the live freeze receipt must be git-tracked and clean (a pin
    registered against uncommitted evidence is the clean-export defect
    class, audit 14650);
  * the census receipt (deviation-size evidence per the frozen rule)
    must exist — newest receipts/special-id-census-*.json or --census;
  * post-apply, fp30 --check must come back GREEN or the run raises.

Bare invocation exits NONZERO: this executor mutates the config
contract, exactly the class the audit policy (mail 14644) requires to
be staged-fail-closed.

`--selftest` pure-logic on a fixture tree; `--apply` fires on the live
tree (manual fire, on Eli's freeze-receipt mail).
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

SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")
CENSUS_GLOB = "receipts/special-id-census-*.json"
BASIS = ("count-semantics remedy frozen pre-census (mail 14628 / STATE "
         "2026-06-11 ~13:35Z): band contract supreme; counting instrument "
         "re-aligned; literal pins of the old total updated as REGISTERED "
         "deviations, old/new + census sha recorded; fp-26/fp-27 freezes "
         "otherwise untouched")

_CONFIG_PIN = re.compile(r'("real_token_total"\s*:\s*)(\d+)')
_GATE_PIN = re.compile(r'(TOKENIZER_RECEIPT\s*=\s*")([^"]+)(")')


class Refusal(SystemExit):
    def __init__(self, msg):
        super().__init__(f"FP30B_REFUSED: {msg}")


def _sha(path):
    h = hashlib.sha256()
    h.update(open(path, "rb").read())
    return h.hexdigest()


def _tracked_and_clean(path, nc):
    """True / False / None (None = not a git work tree, e.g. selftest
    tmpdir — accepted with a note, same convention as the E1b gate)."""
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


def _single_sub(pattern, repl, text, what):
    hits = pattern.findall(text)
    if len(hits) != 1:
        raise Refusal(f"{what}: expected exactly 1 pin match, found "
                      f"{len(hits)} — textual edit refused, never guessed")
    return pattern.sub(repl, text, count=1)


def resolve_census(nc, explicit=None):
    if explicit:
        p = explicit if os.path.isabs(explicit) else f"{nc}/{explicit}"
        if not os.path.exists(p):
            raise Refusal(f"census receipt {explicit} not found")
        return p
    hits = sorted(globmod.glob(f"{nc}/{CENSUS_GLOB}"))
    if not hits:
        raise Refusal(f"no census receipt ({CENSUS_GLOB}) — the frozen "
                      "rule requires census sha as deviation-size "
                      "evidence; pass --census")
    return hits[-1]


def apply(nc=NC, census=None):
    # -- preconditions ------------------------------------------------
    stale = fp30.check(nc)
    if not stale:
        raise Refusal("fp30 --check is GREEN — nothing to register "
                      "(the superseding freeze has not landed)")
    name, total = fp30.live_freeze(nc)
    if name is None:
        raise Refusal("no clean production tokenizer-freeze receipt")
    fpath = f"{nc}/receipts/{name}"
    tracked = _tracked_and_clean(fpath, nc)
    if tracked is False:
        raise Refusal(f"freeze receipt {name} is untracked or dirty — "
                      "commit it first (clean-export class, audit 14650)")
    cpath = resolve_census(nc, census)
    census_tracked = _tracked_and_clean(cpath, nc)
    if census_tracked is False:
        raise Refusal(f"census receipt {os.path.basename(cpath)} is "
                      "untracked or dirty — commit it first")

    registrations = []

    # -- config pin ---------------------------------------------------
    cfg_path = f"{nc}/{fp30.CONFIG}"
    src = open(cfg_path, encoding="utf-8", newline="").read()
    m = _CONFIG_PIN.search(src)
    old_cfg = int(m.group(2)) if m else None
    if any("real_token_total" in s for s in stale):
        new = _single_sub(_CONFIG_PIN, rf"\g<1>{total}", src,
                          fp30.CONFIG)
        open(cfg_path, "w", encoding="utf-8", newline="").write(new)
        registrations.append({"pin": f"{fp30.CONFIG} data.real_token_total",
                              "old": old_cfg, "new": total})

    # -- gate pin -----------------------------------------------------
    gate_path = f"{nc}/{fp30.GATE}"
    gsrc = open(gate_path, encoding="utf-8", newline="").read()
    gm = _GATE_PIN.search(gsrc)
    old_gate = gm.group(2) if gm else None
    if any("TOKENIZER_RECEIPT" in s for s in stale):
        gnew = _single_sub(_GATE_PIN, rf"\g<1>{name}\g<3>", gsrc,
                           fp30.GATE)
        open(gate_path, "w", encoding="utf-8", newline="").write(gnew)
        registrations.append({"pin": f"{fp30.GATE} TOKENIZER_RECEIPT",
                              "old": old_gate, "new": name})

    # -- fp-27 successor receipt ---------------------------------------
    if any("base_policy" in s for s in stale):
        fps = sorted(globmod.glob(f"{nc}/{fp30.FP27_GLOB}"))
        if not fps:
            raise Refusal("no fp27-prereg receipt to supersede")
        old_fp27 = os.path.basename(fps[-1])
        d = json.load(open(fps[-1], encoding="utf-8"))
        olds = {old_cfg} if old_cfg else set()
        # the stale prose may carry digit or comma form of ANY old total;
        # derive candidates from the prose itself when config gave none
        def repoint(v):
            if not isinstance(v, str):
                return v, False
            out, hit = v, False
            for o in sorted(olds, reverse=True):
                for f_old, f_new in ((str(o), str(total)),
                                     (f"{o:,}", f"{total:,}")):
                    if f_old in out:
                        out = out.replace(f_old, f_new)
                        hit = True
            return out, hit

        any_hit = False
        bp = d.get("base_policy", {})
        for k, v in list(bp.items()):
            nv, hit = repoint(v)
            bp[k] = nv
            any_hit = any_hit or hit
        if not any_hit:
            raise Refusal(f"{old_fp27} base_policy carries no occurrence "
                          f"of the old total {old_cfg} — cannot re-point; "
                          "register manually with eyes on the prose")
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        d["ts"] = ts
        d["supersedes"] = old_fp27
        d.setdefault("deviation_registrations", []).append({
            "field": "base_policy budget literal",
            "old_total": old_cfg, "new_total": total,
            "freeze_receipt": name, "freeze_sha256": _sha(fpath),
            "census_receipt": os.path.basename(cpath),
            "census_sha256": _sha(cpath),
            "basis": BASIS, "ts": ts,
        })
        succ = f"{nc}/receipts/fp27-prereg-{ts}.json"
        checked_write(succ, d)
        registrations.append({"pin": "fp27 base_policy budget literal",
                              "old": old_fp27,
                              "new": os.path.basename(succ)})

    # -- post-assert ----------------------------------------------------
    post = fp30.check(nc)
    if post:
        raise SystemExit(f"FP30B_POST_CHECK_RED after apply — tree diff "
                         f"needs eyes: {post}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP30B-DEVIATION-REGISTRATION",
        "ts": ts,
        "issue": 218,
        "freeze_receipt": name,
        "freeze_sha256": _sha(fpath),
        "freeze_tracked_clean": tracked,
        "new_total": total,
        "census_receipt": os.path.basename(cpath),
        "census_sha256": _sha(cpath),
        "registrations": registrations,
        "stale_worklist_consumed": stale,
        "post_check": "GREEN",
        "basis": BASIS,
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }
    out = f"{nc}/receipts/fp30b-deviation-registration-{ts}.json"
    checked_write(out, receipt)
    f = validate_receipt(json.load(open(out, encoding="utf-8")))
    if f:
        raise SystemExit(f"emitted receipt FAILS receipt_check: {f}")
    return receipt, out


def _fixture(td, new_freeze=False):
    os.makedirs(f"{td}/receipts", exist_ok=True)
    os.makedirs(f"{td}/configs", exist_ok=True)
    os.makedirs(f"{td}/scripts", exist_ok=True)
    json.dump({"ticket": "TOK", "ts": "a",
               "real_token_counts": {"total": 100},
               "sha_convention": "x"},
              open(f"{td}/receipts/tokenizer-freeze-20260101T000000Z.json",
                   "w"))
    open(f"{td}/{fp30.CONFIG}", "w").write(
        '{\n "data": {\n  "real_token_total": 100\n }\n}\n')
    open(f"{td}/{fp30.GATE}", "w").write(
        'TOKENIZER_RECEIPT = "tokenizer-freeze-20260101T000000Z.json"\n')
    json.dump({"ticket": "FP27", "ts": "a",
               "base_policy": {"primary": "budget 100 tokens of the "
                                          "frozen corpus"},
               "sha_convention": "x"},
              open(f"{td}/receipts/fp27-prereg-20260101T000001Z.json", "w"))
    json.dump({"ticket": "CENSUS", "ts": "a", "text_borne_reserved": 2,
               "sha_convention": "x"},
              open(f"{td}/receipts/special-id-census-20260102T000000Z.json",
                   "w"))
    if new_freeze:
        json.dump({"ticket": "TOK", "ts": "b",
                   "real_token_counts": {"total": 105},
                   "sha_convention": "x"},
                  open(f"{td}/receipts/"
                       f"tokenizer-freeze-20260102T000000Z.json", "w"))


def _selftest():
    import tempfile
    # refusal: green tree has nothing to register
    with tempfile.TemporaryDirectory() as td:
        _fixture(td, new_freeze=False)
        try:
            apply(nc=td)
            raise AssertionError("green tree must refuse")
        except Refusal as e:
            assert "GREEN" in str(e), e
    # refusal: no census receipt
    with tempfile.TemporaryDirectory() as td:
        _fixture(td, new_freeze=True)
        os.remove(f"{td}/receipts/special-id-census-20260102T000000Z.json")
        try:
            apply(nc=td)
            raise AssertionError("missing census must refuse")
        except Refusal as e:
            assert "census" in str(e), e
    # refusal: ambiguous config pin (two matches)
    with tempfile.TemporaryDirectory() as td:
        _fixture(td, new_freeze=True)
        open(f"{td}/{fp30.CONFIG}", "w").write(
            '{"data": {"real_token_total": 100}, "real_token_total": 100}')
        try:
            apply(nc=td)
            raise AssertionError("ambiguous pin must refuse")
        except Refusal as e:
            assert "exactly 1" in str(e), e
    # happy path: RED -> apply -> GREEN, all three pins re-pointed
    with tempfile.TemporaryDirectory() as td:
        _fixture(td, new_freeze=True)
        assert len(fp30.check(td)) == 3
        receipt, out = apply(nc=td)
        assert fp30.check(td) == [], fp30.check(td)
        assert receipt["new_total"] == 105
        assert receipt["post_check"] == "GREEN"
        assert len(receipt["registrations"]) == 3, receipt["registrations"]
        pins = {r["pin"]: r for r in receipt["registrations"]}
        assert pins[f"{fp30.CONFIG} data.real_token_total"]["old"] == 100
        gate_src = open(f"{td}/{fp30.GATE}").read()
        assert "20260102T000000Z" in gate_src
        cfg = json.load(open(f"{td}/{fp30.CONFIG}"))
        assert cfg["data"]["real_token_total"] == 105
        # config edit was textual: surrounding structure intact
        assert open(f"{td}/{fp30.CONFIG}", encoding="utf-8").read().startswith(
            '{\n "data"')
        succ = sorted(globmod.glob(f"{td}/receipts/fp27-prereg-*.json"))[-1]
        sd = json.load(open(succ))
        assert "105" in sd["base_policy"]["primary"]
        assert sd["supersedes"] == "fp27-prereg-20260101T000001Z.json"
        dr = sd["deviation_registrations"][0]
        assert dr["old_total"] == 100 and dr["new_total"] == 105
        assert dr["census_receipt"].startswith("special-id-census-")
        assert validate_receipt(receipt) == [], validate_receipt(receipt)
        # idempotence: second apply refuses on the now-green tree
        try:
            apply(nc=td)
            raise AssertionError("second apply must refuse")
        except Refusal:
            pass
    # live tree TODAY must refuse (fp30 green pre-re-freeze) — proves the
    # executor cannot fire early
    try:
        apply(nc=NC)
        raise AssertionError("live tree must refuse while fp30 is green")
    except Refusal as e:
        assert "GREEN" in str(e) or "census" in str(e), e
    print("FP30B_REGISTER_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--census", help="explicit census receipt path "
                                     "(default: newest special-id-census-*)")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if not a.apply:
        print("FP30B_REGISTER_STAGED (--apply registers the deviations; "
              "fires on the superseding freeze receipt, #218)")
        raise SystemExit(1)
    receipt, out = apply(census=a.census)
    print(json.dumps(receipt["registrations"], indent=1))
    print(f"FP30B_REGISTER_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
