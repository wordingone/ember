"""fp30_total_consistency.py — token-total consistency validator: every
artifact pinning the corpus total must track the LIVE tokenizer-freeze
receipt (#216).

Born from the 2026-06-11 shard-run refusal: two gated instruments held
different count semantics (freeze counted text-borne reserved-band ids;
the shard writer's band contract refuses them) and nothing mechanical
watched the seam. The decided remedy (rule frozen pre-census, mail
14628) re-derives the counts and re-freezes — which makes every literal
pin of the old total STALE the moment the new freeze lands. This
validator is the standing alarm + the registration checklist:

  live freeze   = newest receipts/tokenizer-freeze-*.json by timestamp
                  (must be receipt_check-clean; carries
                  real_token_counts.total)
  tracked pins  = configs/v0-pretrain-config.json real_token_total
                  scripts/v0_pretrain_launch_gate.py TOKENIZER_RECEIPT
                  (must NAME the live freeze receipt)
                  the live fp27-prereg receipt's BASE_POLICY budget
                  literal (prose pin — substring check)

`--check` exits non-zero naming each STALE pin (the deviation-
registration worklist, mechanically derived). Today (pre-re-freeze) all
pins MATCH; the check flips red on the re-freeze until the registered-
deviation updates land, then green again — and stays as a pre-launch
standing audit. Historical preregs that pinned the OLD receipt BY SHA
at their freeze time (e.g. fp-26 premises) are intentionally NOT
tracked: a freeze's premise pins are facts about its freeze moment,
not live references.

`--selftest` pure-logic on temp fixtures (match / stale-value /
stale-name / missing branches).
"""
import argparse
import glob as globmod
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_check import validate_receipt             # noqa: E402

CONFIG = "configs/v0-pretrain-config.json"
GATE = "scripts/v0_pretrain_launch_gate.py"
FP27_GLOB = "receipts/fp27-prereg-*.json"
FREEZE_GLOB = "receipts/tokenizer-freeze-*.json"


def live_freeze(nc=NC):
    """(name, total) of the newest clean tokenizer-freeze receipt."""
    hits = sorted(globmod.glob(f"{nc}/{FREEZE_GLOB}"))
    for p in reversed(hits):                  # newest ts-name last
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if validate_receipt(d):
            continue
        tot = (d.get("real_token_counts") or {}).get("total")
        if isinstance(tot, int) and tot > 0:
            return os.path.basename(p), tot
    return None, None


def check(nc=NC):
    """List of STALE findings (empty = every tracked pin matches)."""
    name, total = live_freeze(nc)
    if name is None:
        return ["no clean tokenizer-freeze receipt with "
                "real_token_counts.total on disk"]
    stale = []
    # config literal
    cp = f"{nc}/{CONFIG}"
    if not os.path.exists(cp):
        stale.append(f"{CONFIG} missing")
    else:
        cd = json.load(open(cp, encoding="utf-8"))
        got = (cd.get("data") or {}).get("real_token_total",
                                         cd.get("real_token_total"))
        if got != total:
            stale.append(f"{CONFIG} data.real_token_total={got} != live "
                         f"freeze {total} ({name})")
    # launch gate must NAME the live freeze receipt
    gp = f"{nc}/{GATE}"
    if not os.path.exists(gp):
        stale.append(f"{GATE} missing")
    else:
        src = open(gp, encoding="utf-8").read()
        m = re.search(r'TOKENIZER_RECEIPT\s*=\s*"([^"]+)"', src)
        if not m:
            stale.append(f"{GATE}: TOKENIZER_RECEIPT constant not found")
        elif m.group(1) != name:
            stale.append(f"{GATE} TOKENIZER_RECEIPT={m.group(1)} != live "
                         f"freeze {name}")
    # live fp-27 prereg prose budget pin (newest fp27 receipt)
    fps = sorted(globmod.glob(f"{nc}/{FP27_GLOB}"))
    if not fps:
        stale.append("no fp27-prereg receipt on disk")
    else:
        d = json.load(open(fps[-1], encoding="utf-8"))
        prose = json.dumps(d.get("base_policy", {}))
        if f"{total:,}" not in prose and str(total) not in prose:
            stale.append(f"{os.path.basename(fps[-1])} base_policy does not "
                         f"carry the live freeze total {total} — register "
                         f"the deviation (old/new + census sha)")
    return stale


def _selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(f"{td}/receipts")
        os.makedirs(f"{td}/configs")
        os.makedirs(f"{td}/scripts")

        def freeze(ts, total):
            json.dump({"ticket": "TOK", "ts": ts,
                       "real_token_counts": {"total": total},
                       "sha_convention": "x"},
                      open(f"{td}/receipts/tokenizer-freeze-{ts}.json", "w"))

        freeze("20260101T000000Z", 100)
        json.dump({"data": {"real_token_total": 100}},
                  open(f"{td}/{CONFIG}", "w"))
        open(f"{td}/{GATE}", "w").write(
            'TOKENIZER_RECEIPT = "tokenizer-freeze-20260101T000000Z.json"\n')
        json.dump({"ticket": "FP27", "ts": "x",
                   "base_policy": {"primary": "budget 100 tokens"}},
                  open(f"{td}/receipts/fp27-prereg-20260101T000001Z.json",
                       "w"))
        assert check(nc=td) == [], check(nc=td)          # all MATCH
        # a NEWER freeze with a different total flips every pin stale
        freeze("20260102T000000Z", 105)
        st = check(nc=td)
        assert len(st) == 3, st
        assert any("real_token_total" in x for x in st)
        assert any("TOKENIZER_RECEIPT" in x for x in st)
        assert any("base_policy" in x for x in st)
        # registering the deviations goes green again
        json.dump({"data": {"real_token_total": 105}},
                  open(f"{td}/{CONFIG}", "w"))
        open(f"{td}/{GATE}", "w").write(
            'TOKENIZER_RECEIPT = "tokenizer-freeze-20260102T000000Z.json"\n')
        json.dump({"ticket": "FP27", "ts": "x",
                   "base_policy": {"primary": "budget 105 tokens "
                                              "(deviation registered)"}},
                  open(f"{td}/receipts/fp27-prereg-20260102T000002Z.json",
                       "w"))
        assert check(nc=td) == [], check(nc=td)
        # dirty newest freeze is skipped (falls back to older clean one)
        open(f"{td}/receipts/tokenizer-freeze-20260103T000000Z.json",
             "w").write('{"ts": "x"}')                   # missing ticket
        name, total = live_freeze(nc=td)
        assert name == "tokenizer-freeze-20260102T000000Z.json"
    # live-tree: pins must match TODAY (pre-re-freeze)
    assert check() == [], check()
    print("FP30_TOTAL_CONSISTENCY_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    name, total = live_freeze()
    print(f"live freeze: {name} total={total}")
    stale = check()
    if stale:
        for x in stale:
            print(f"STALE PIN: {x}")
        raise SystemExit("FP30_TOTAL_CONSISTENCY_RED — register the "
                         "deviations above")
    print("FP30_TOTAL_CONSISTENCY_GREEN")


if __name__ == "__main__":
    main()
