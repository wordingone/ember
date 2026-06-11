"""fp8_vgate.py — verifier-change regression gate (#63, fp-8).

fp-5 confirmed two unguarded false-accept classes in V (`__eq__` dispatch,
object-graph reachability); the named fix is a canonicalized comparator.
fp-8 asks the next question down: tightening V is ITSELF a change with a
failure mode — a comparator that rejects valid solutions is a
FALSE-NEGATIVE regression on the measured floor, the dual of the 22.1%
ext-FPR. Who checks the checker? **The existing verified ledger does.**
This script IS that gate: it re-executes every verified W-code episode's
asserts under (a) the production raw `==` and (b) a reference tightened
comparator, and receipts the flip-rate + the bits carried by flipped
episodes. Any production comparator change must quote this receipt
(flip-rate, bits-cost, cause classes) before adoption — NC-K invariant-1
three-test applies to harness edits, and this receipt is the required
false-negative field.

Reference comparator (deliberately strict — the receipt COSTS the
strictness, it does not prescribe it):
  - leaves allow-listed by EXACT type: bool / int / float / str / bytes /
    NoneType — tagged, so True != 1 and 1 != 1.0 (numeric-kind flips);
  - containers list / tuple / set / frozenset / dict recurse, tagged by
    kind, so (4,5) != [4,5] (container-kind flips);
  - ANY other type refuses to normalize (unknown-type) — this is exactly
    the class that closes the `__eq__` false-accept path, because a lying
    object never reaches builtin comparison.

Flip causes, classified in-harness and transported through the sandbox's
error field (t1_probe formats f"{type}: {msg}"[:200], so explicit
AssertionError messages survive):
  FP8FLIP:unknown-type   — a side won't normalize (the false-credit class)
  FP8FLIP:container-kind — same content, different container kind
  FP8FLIP:numeric-kind   — equal under ==, different numeric type
  FP8FLIP:value          — canonical forms differ outright
  FP8RAWFAIL             — raw == itself failed on re-execution
                           (environment-dependent episode, counted apart)

Live leg: POSIX sandbox via the daemon (WSL window) — ~3 assert-jobs per
episode, trivially cheap (verify-timing receipt: 0.52 ms/job pooled).
`python fp8_vgate.py --selftest` is pure-logic and runs anywhere.
"""
import ast
import json
import sys
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
LEDGER = f"{NC}/ledger/episodes.jsonl"

# The canon preamble embedded in every harness. Self-contained stdlib.
CANON_SRC = '''
def _fp8_canon(x):
    t = type(x)
    if t is bool: return ("bool", x)
    if t is int: return ("int", x)
    if t is float: return ("float", x)
    if t is str: return ("str", x)
    if t is bytes: return ("bytes", x)
    if x is None: return ("none",)
    if t is list: return ("list", tuple(_fp8_canon(e) for e in x))
    if t is tuple: return ("tuple", tuple(_fp8_canon(e) for e in x))
    if t in (set, frozenset):
        return ("set", frozenset(_fp8_canon(e) for e in x))
    if t is dict:
        return ("dict", frozenset((_fp8_canon(k), _fp8_canon(v))
                                  for k, v in x.items()))
    raise TypeError("unknown-type:" + t.__name__)

def _fp8_classify(a, b):
    """a == b is True; canonical forms differ. Name why."""
    try:
        ca, cb = _fp8_canon(a), _fp8_canon(b)
    except TypeError:
        return "unknown-type"
    kinds = {ca[0], cb[0]}
    if len(kinds) == 2:
        if kinds <= {"bool", "int", "float"}: return "numeric-kind"
        if kinds <= {"list", "tuple", "set"}: return "container-kind"
        return "value"
    if ca[0] in ("list", "tuple", "set", "dict") and ca != cb:
        # same outer kind: recurse to find the first differing leaf pair
        return "container-kind" if _fp8_inner_kind_diff(a, b) else "value"
    return "value"

def _fp8_inner_kind_diff(a, b):
    try:
        if type(a) in (list, tuple) and type(b) in (list, tuple) \\
                and len(a) == len(b):
            return any(_fp8_pair_kind_diff(x, y) for x, y in zip(a, b))
    except Exception:
        pass
    return False

def _fp8_pair_kind_diff(x, y):
    try:
        if x == y and _fp8_canon(x) != _fp8_canon(y):
            return True
        if type(x) in (list, tuple) and type(y) in (list, tuple):
            return _fp8_inner_kind_diff(x, y)
    except Exception:
        pass
    return False

def _fp8_check(left, right):
    raw = (left == right)
    if not raw:
        raise AssertionError("FP8RAWFAIL")
    try:
        canon_ok = (_fp8_canon(left) == _fp8_canon(right))
    except TypeError:
        raise AssertionError("FP8FLIP:unknown-type")
    if not canon_ok:
        raise AssertionError("FP8FLIP:" + _fp8_classify(left, right))
'''

STUB = "\n\ndef solve(grid):\n    return [[0]]\n"


def split_assert(test_src):
    """'assert f(x) == y' -> (left_src, right_src) or None if not that
    exact shape (single Compare, single Eq)."""
    try:
        tree = ast.parse(test_src.strip())
    except SyntaxError:
        return None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assert):
        return None
    test = tree.body[0].test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 \
            or not isinstance(test.ops[0], ast.Eq):
        return None
    return ast.unparse(test.left), ast.unparse(test.comparators[0])


def build_harness(imports, src, left, right):
    head = "\n".join(imports)
    return (f"{head}\n{src}\n{CANON_SRC}\n"
            f"_fp8_check(({left}), ({right}))\n{STUB}")


def load_mbpp_episodes():
    eps = []
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if str(r.get("task", "")).startswith("mbpp:") and r.get("verified"):
                eps.append(r)
    return eps


def main():
    sys.path.insert(0, f"{NC}/scripts")
    from t1_probe import execute_batch
    from w1_mbpp import load_split

    problems = {p["id"]: p for p in load_split("train")}
    eps = load_mbpp_episodes()

    jobs, meta = [], []
    unparsed = 0
    for ep in eps:
        tid = int(ep["task"].split(":")[1])
        p = problems.get(tid)
        if p is None:
            continue
        for t in p["tests"]:
            pair = split_assert(t)
            if pair is None:
                unparsed += 1
                continue
            jobs.append((build_harness(p["imports"], ep["src"], *pair), [], []))
            meta.append(ep)

    results = execute_batch(jobs)
    flips = {}          # episode key -> worst cause
    raw_fail_eps = set()
    cause_counts = {}
    for ep, r in zip(meta, results):
        err = str(r.get("error") or "")
        if "FP8FLIP:" in err:
            cause = err.split("FP8FLIP:")[1].split()[0][:32]
            cause_counts[cause] = cause_counts.get(cause, 0) + 1
            flips.setdefault(ep["key"], (ep, cause))
        elif "FP8RAWFAIL" in err:
            raw_fail_eps.add(ep["key"])
        elif not r.get("verified") and err:
            cause_counts["other-error"] = cause_counts.get("other-error", 0) + 1

    flipped = [v for v in flips.values()]
    bits_cost = round(sum(ep.get("bits") or 0.0 for ep, _ in flipped), 1)
    total_bits = round(sum(ep.get("bits") or 0.0 for ep in eps), 1)
    by_stratum = {}
    for ep, _cause in flipped:
        s = ep.get("stratum") or "?"
        by_stratum[s] = by_stratum.get(s, 0) + 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP8-VGATE", "ts": ts,
        "ledger": "episodes.jsonl (verified mbpp rows)",
        "n_episodes": len(eps), "n_assert_jobs": len(jobs),
        "unparsed_asserts": unparsed,
        "raw_reexec_disagreements": len(raw_fail_eps),
        "flip_assert_counts_by_cause": cause_counts,
        "flipped_episodes": len(flipped),
        "flip_rate_pct": round(100 * len(flipped) / max(len(eps), 1), 2),
        "bits_cost_of_flips": bits_cost,
        "ledger_bits_total": total_bits,
        "flips_by_stratum": by_stratum,
        "gate": "any production comparator change must re-run this script "
                "and quote flip_rate_pct + bits_cost before adoption; "
                "verifier edits are artifacts under NC-K invariant-1 "
                "(held-out / control / deletion) with this receipt as the "
                "required false-negative field",
    }
    out = f"{RECEIPTS}/fp8-vgate-{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP8_VGATE_DONE {out}")


def _selftest():
    ns = {}
    exec(CANON_SRC, ns)
    canon, check = ns["_fp8_canon"], ns["_fp8_check"]
    # identical structures pass both comparators
    check([1, 2, {"a": (1, 2)}], [1, 2, {"a": (1, 2)}])
    # container-kind: tuple vs list, equal under ==
    assert (4, 5) != [4, 5]  # plain tuple/list unequal — use inner case
    try:
        check([(4, 5)], [(4, 5)])
    except AssertionError:
        raise SystemExit("identical nested must pass")
    # numeric-kind: True == 1 raw-passes, canon flips
    try:
        check(True, 1); raise SystemExit("expected flip")
    except AssertionError as e:
        assert "FP8FLIP:numeric-kind" in str(e), e
    # numeric-kind: 1 == 1.0
    try:
        check(1, 1.0); raise SystemExit("expected flip")
    except AssertionError as e:
        assert "FP8FLIP:numeric-kind" in str(e), e
    # unknown-type: lying __eq__ object NEVER reaches builtin compare
    class _Yes:
        def __eq__(self, o): return True
    try:
        check(_Yes(), 5); raise SystemExit("expected flip")
    except AssertionError as e:
        assert "FP8FLIP:unknown-type" in str(e), e
    # raw failure is its own marker
    try:
        check(1, 2); raise SystemExit("expected rawfail")
    except AssertionError as e:
        assert "FP8RAWFAIL" in str(e), e
    # canon dict/set semantics: order-free equality preserved
    assert canon({"b": 1, "a": 2}) == canon({"a": 2, "b": 1})
    assert canon({1, 2}) == canon({2, 1})
    # assert decomposition
    pair = split_assert("assert similar_elements((3, 4),(5, 4)) == (4,)")
    assert pair == ("similar_elements((3, 4), (5, 4))", "(4,)"), pair
    assert split_assert("assert math.isclose(f(2), 1.1, rel_tol=0.01)") is None
    assert split_assert("assert a == b == c") is None
    h = build_harness(["import math"], "def f(x):\n    return x\n",
                      "f(2)", "2")
    assert "_fp8_check((f(2)), (2))" in h and "def solve(grid):" in h
    print("FP8_VGATE_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
