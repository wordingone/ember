"""e1b_pair_assemble.py — FP32-E1B-LOSSMATCH pair-receipt assembler (#253, fp-32d).

The missing link between the trainer's leg runs and fp32_e1b_gate: consumes
2-3 leg receipts (order: base B=4, candidate, optional scaled-lr retry),
extracts the gate's LEG_REQUIRED fields VERBATIM (no recomputation, no
defaults), pins the pair-level premise (shard receipt + byte-sha, init_seed,
frozen seq/token_budget, data_order_basis), PRE-FLIGHTS check_pair
in-process, and writes receipts/fp32-e1b-lossmatch-<ts>.json ONLY when it
binds. The gate stays the separate authority — this script never emits a
verdict receipt.

Usage:
  python e1b_pair_assemble.py --legs base.json cand.json [retry.json]
         [--shard-receipt NAME] [--init-seed N] [--data-order-basis STR]
  python e1b_pair_assemble.py --selftest

Bare invocation exits 1 (evidence-promotion class, audit policy 14644).
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fp32_e1b_gate as gate  # noqa: E402 — single source for the contract
from receipt_write import checked_write  # noqa: E402

NC = gate.NC
SHARD_NAME_RE = re.compile(r"^token-shards-v0-\d{8}T\d{6}Z\.json$")


class Refuse(Exception):
    """Assembly refused — message names the leg/field/conflict. Nothing
    is written on any Refuse path."""


def _load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception as exc:
        raise Refuse(f"leg {path}: unreadable ({exc})")


def extract_leg(path):
    """VERBATIM extraction of exactly the gate's LEG_REQUIRED fields."""
    raw = _load(path)
    missing = [k for k in gate.LEG_REQUIRED if k not in raw]
    if missing:
        raise Refuse(f"leg {path}: missing required field(s) {missing} — "
                     f"the leg-receipt contract is gate.LEG_REQUIRED")
    return {k: raw[k] for k in gate.LEG_REQUIRED}, raw


def resolve_seed(raws, explicit):
    if explicit is not None:
        return int(explicit)
    seen = {r["init_seed"] for r in raws if "init_seed" in r}
    if len(seen) > 1:
        raise Refuse(f"init_seed conflict across legs: {sorted(seen)} — "
                     f"pair cannot bind")
    if not seen:
        raise Refuse("init_seed absent from all legs and no --init-seed "
                     "given — no defaults")
    return next(iter(seen))


def resolve_basis(raws, explicit):
    if explicit:
        return explicit
    seen = {r["data_order_basis"] for r in raws if "data_order_basis" in r}
    if len(seen) > 1:
        raise Refuse(f"data_order_basis conflict across legs: {sorted(seen)}")
    if not seen:
        raise Refuse("data_order_basis absent from all legs and no "
                     "--data-order-basis given — no defaults")
    return next(iter(seen))


def resolve_shard(nc, explicit):
    rdir = os.path.join(nc, "receipts")
    if explicit:
        name = os.path.basename(explicit)
    else:
        prod = sorted(n for n in os.listdir(rdir) if SHARD_NAME_RE.match(n))
        if not prod:
            raise Refuse("no production token-shards-v0-* receipt under "
                         "receipts/ and none named")
        name = prod[-1]  # newest by timestamp-name sort
    path = os.path.join(rdir, name)
    if not os.path.exists(path):
        raise Refuse(f"shard receipt {name} not found under receipts/")
    return name, gate._sha(path)


def assemble(leg_paths, nc=NC, shard=None, init_seed=None, basis=None):
    """Build the pair dict, pre-flight the gate, write only on bind.
    Returns (receipt_path, pair). Raises Refuse without writing."""
    if not 2 <= len(leg_paths) <= 3:
        raise Refuse(f"need 2-3 legs (base, candidate[, scaled-lr retry]), "
                     f"got {len(leg_paths)}")
    extracted = [extract_leg(p) for p in leg_paths]
    legs = [e[0] for e in extracted]
    raws = [e[1] for e in extracted]
    shard_name, shard_sha = resolve_shard(nc, shard)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pair = {
        "ticket": gate.PAIR_TICKET, "ts": ts,
        "shard_receipt": shard_name, "shard_set_sha256": shard_sha,
        "init_seed": resolve_seed(raws, init_seed),
        "seq": gate.SEQ, "token_budget": gate.TOKEN_BUDGET,
        "data_order_basis": resolve_basis(raws, basis),
        "legs": legs,
        "sha_convention": gate.SHA_CONVENTION,
        "assembled_from": [os.path.basename(p) for p in leg_paths],
    }
    findings = gate.check_pair(pair, nc=nc)
    if findings:
        raise Refuse("gate pre-flight refused the pair (nothing written):\n"
                     + "\n".join(f"  - {x}" for x in findings))
    out = os.path.join(nc, "receipts", f"fp32-e1b-lossmatch-{ts}.json")
    checked_write(out, pair)
    return out, pair


def _selftest():
    import copy
    import tempfile
    live_receipts = sorted(os.listdir(os.path.join(NC, "receipts")))
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(f"{td}/receipts")
        json.dump({"ticket": "TOKENIZER-FREEZE-V0", "ts": "20260101T000000Z",
                   "real_token_counts": {"total": 7_000_000_000},
                   "sha_convention": "x"},
                  open(f"{td}/receipts/tokenizer-freeze-20260101T000000Z.json", "w"))
        shard_name = "token-shards-v0-20260101T000001Z.json"
        json.dump({"ticket": gate.SHARDS_TICKET, "ts": "20260101T000001Z",
                   "total_stream_tokens": 7_000_000_000, "sha_convention": "x"},
                  open(f"{td}/receipts/{shard_name}", "w"))
        stale_name = "token-shards-v0-20251231T000000Z.json"
        json.dump({"ticket": gate.SHARDS_TICKET, "ts": "20251231T000000Z",
                   "total_stream_tokens": 6_900_000_000, "sha_convention": "x"},
                  open(f"{td}/receipts/{stale_name}", "w"))

        def leg_file(n, leg, extra=None):
            p = f"{td}/{n}.json"
            json.dump({**leg, **(extra or {})}, open(p, "w"))
            return p

        base = leg_file("base", gate._leg(4, 2.500),
                        {"init_seed": 23, "data_order_basis": "shard prefix, frozen order"})
        cand = leg_file("cand", gate._leg(16, 2.530),
                        {"init_seed": 23, "data_order_basis": "shard prefix, frozen order"})

        # (a) happy path: assembles, binds, gate verdict computable
        out, pair = assemble([base, cand], nc=td)
        assert os.path.exists(out), "receipt not written on bind"
        assert gate.check_pair(pair, nc=td) == []
        v = gate.verdict(pair)
        assert v[0] == "PASS", v

        # (b) missing leg field -> refuse, nothing new written
        before = set(os.listdir(f"{td}/receipts"))
        broken = copy.deepcopy(gate._leg(16, 2.53))
        del broken["ce_final10"]
        bp = leg_file("broken", broken, {"init_seed": 23,
                                         "data_order_basis": "shard prefix, frozen order"})
        try:
            assemble([base, bp], nc=td)
            raise AssertionError("missing field did not refuse")
        except Refuse as e:
            assert "ce_final10" in str(e) and "broken" in str(e)
        assert set(os.listdir(f"{td}/receipts")) == before, "wrote on refuse"

        # (c) seed conflict -> refuse
        c2 = leg_file("cand2", gate._leg(16, 2.53),
                      {"init_seed": 24, "data_order_basis": "shard prefix, frozen order"})
        try:
            assemble([base, c2], nc=td)
            raise AssertionError("seed conflict did not refuse")
        except Refuse as e:
            assert "init_seed conflict" in str(e)

        # (d) gate finding (non-frozen lr on first candidate) -> refuse, no write
        badlr = leg_file("badlr", gate._leg(16, 2.53, lr=gate.SCALED_LR),
                         {"init_seed": 23, "data_order_basis": "shard prefix, frozen order"})
        try:
            assemble([base, badlr], nc=td)
            raise AssertionError("gate finding did not refuse")
        except Refuse as e:
            assert "pre-flight refused" in str(e)
        assert set(os.listdir(f"{td}/receipts")) == before, "wrote on gate refuse"

        # (e) stale shard receipt -> refused via the gate's own provenance check
        try:
            assemble([base, cand], nc=td, shard=stale_name)
            raise AssertionError("stale shards did not refuse")
        except Refuse as e:
            assert "STALE SHARDS" in str(e)

    # live purity: the real receipts/ dir untouched by the selftest
    assert sorted(os.listdir(os.path.join(NC, "receipts"))) == live_receipts, \
        "selftest mutated live receipts/"
    print("E1B_PAIR_ASSEMBLE_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legs", nargs="*", default=[])
    ap.add_argument("--shard-receipt")
    ap.add_argument("--init-seed", type=int)
    ap.add_argument("--data-order-basis")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return 0
    if not args.legs:
        print("E1B_PAIR_ASSEMBLE_STAGED (pass --legs base cand [retry]; "
              "fires on Eli's E1b leg receipts — evidence-promotion class, "
              "bare invocation never writes)")
        return 1
    try:
        out, _ = assemble(args.legs, shard=args.shard_receipt,
                          init_seed=args.init_seed,
                          basis=args.data_order_basis)
    except Refuse as exc:
        print(f"E1B_PAIR_ASSEMBLE_REFUSED: {exc}")
        return 1
    print(f"E1B_PAIR_ASSEMBLE_DONE {out} (gate verdict is the gate's job: "
          f"python scripts/fp32_e1b_gate.py --pair {out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
