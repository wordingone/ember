# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""v_compare.py — strict comparator in the production verify path (eng #76).

fp-5 confirmed the `__eq__`-dispatch false-accept class in V (a lying object
reaches builtin == and says yes); fp-8 (#63) measured the cost of closing it:
flip rate 0.21% (2/956 episodes, both container-kind), bits 2.2/573.2 (0.4%),
zero unknown-type flips (receipt fp8-vgate-20260611T001730Z). This module
ADOPTS the fp-8 reference semantics in production:

  - canon + assert decomposition are IMPORTED from fp8_vgate (single source —
    the gate and production can never drift apart silently);
  - every `assert L == R` test statement is rewritten to `_v_check((L), (R))`
    = raw == AND canonical-form equality AND unknown-type refusal;
  - any other assert shape (isclose/membership/chained — 160/3,184 on MBPP)
    passes through UNCHANGED;
  - DESIGN DECISION (issue #76 item 2): STRICT, no container coercion. The
    2 container-kind flips / 2.2 bits are accepted. Reasoning in the PR:
    tighten-never-relax gate discipline; a tuple/list coercion rule is a
    permanent carve-out re-opening exactly the kind-confusion class the
    soundness probe confirmed; and a wrong-kinded return is a real type-
    contract miss worth refusing training credit for.

`python v_compare.py --selftest` is pure-logic and runs anywhere.
`python v_compare.py --smoke` (POSIX sandbox, daemon window) re-verifies
every verified mbpp ledger episode under the PRODUCTION harness shape and
receipts agreement vs the raw-== verdicts (AC: identical except the
documented flips).
"""
import json
import sys

# issue2015 exact-local-import:src/ember/governance/scripts/fp8_vgate.py
import importlib.util as _ember_9d952c1b97eba781_importlib
import sys as _ember_9d952c1b97eba781_sys
from pathlib import Path as _ember_9d952c1b97eba781_Path
_ember_9d952c1b97eba781_path = _ember_9d952c1b97eba781_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'fp8_vgate.py')
if not _ember_9d952c1b97eba781_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/fp8_vgate.py')
_ember_9d952c1b97eba781_aliases = ('_ember_issue2015_9d952c1b97eba781', 'fp8_vgate', 'scripts.fp8_vgate')
_ember_9d952c1b97eba781_existing = []
for _ember_9d952c1b97eba781_alias in _ember_9d952c1b97eba781_aliases:
    _ember_9d952c1b97eba781_candidate = _ember_9d952c1b97eba781_sys.modules.get(_ember_9d952c1b97eba781_alias)
    if _ember_9d952c1b97eba781_candidate is not None and all(_ember_9d952c1b97eba781_candidate is not item for item in _ember_9d952c1b97eba781_existing):
        _ember_9d952c1b97eba781_existing.append(_ember_9d952c1b97eba781_candidate)
if len(_ember_9d952c1b97eba781_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/fp8_vgate.py')
if _ember_9d952c1b97eba781_existing:
    _ember_9d952c1b97eba781_module = _ember_9d952c1b97eba781_existing[0]
    _ember_9d952c1b97eba781_observed = getattr(_ember_9d952c1b97eba781_module, '__file__', None)
    if _ember_9d952c1b97eba781_observed is None or _ember_9d952c1b97eba781_Path(_ember_9d952c1b97eba781_observed).resolve() != _ember_9d952c1b97eba781_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/fp8_vgate.py')
else:
    _ember_9d952c1b97eba781_spec = _ember_9d952c1b97eba781_importlib.spec_from_file_location('_ember_issue2015_9d952c1b97eba781', _ember_9d952c1b97eba781_path)
    if _ember_9d952c1b97eba781_spec is None or _ember_9d952c1b97eba781_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/fp8_vgate.py')
    _ember_9d952c1b97eba781_module = _ember_9d952c1b97eba781_importlib.module_from_spec(_ember_9d952c1b97eba781_spec)
    for _ember_9d952c1b97eba781_alias in _ember_9d952c1b97eba781_aliases:
        _ember_9d952c1b97eba781_prior = _ember_9d952c1b97eba781_sys.modules.get(_ember_9d952c1b97eba781_alias)
        if _ember_9d952c1b97eba781_prior is not None and _ember_9d952c1b97eba781_prior is not _ember_9d952c1b97eba781_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp8_vgate.py')
        _ember_9d952c1b97eba781_sys.modules[_ember_9d952c1b97eba781_alias] = _ember_9d952c1b97eba781_module
    try:
        _ember_9d952c1b97eba781_spec.loader.exec_module(_ember_9d952c1b97eba781_module)
    except BaseException:
        for _ember_9d952c1b97eba781_alias in _ember_9d952c1b97eba781_aliases:
            if _ember_9d952c1b97eba781_sys.modules.get(_ember_9d952c1b97eba781_alias) is _ember_9d952c1b97eba781_module:
                _ember_9d952c1b97eba781_sys.modules.pop(_ember_9d952c1b97eba781_alias, None)
        raise
for _ember_9d952c1b97eba781_alias in _ember_9d952c1b97eba781_aliases:
    _ember_9d952c1b97eba781_prior = _ember_9d952c1b97eba781_sys.modules.get(_ember_9d952c1b97eba781_alias)
    if _ember_9d952c1b97eba781_prior is not None and _ember_9d952c1b97eba781_prior is not _ember_9d952c1b97eba781_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp8_vgate.py')
    _ember_9d952c1b97eba781_sys.modules[_ember_9d952c1b97eba781_alias] = _ember_9d952c1b97eba781_module
CANON_SRC = getattr(_ember_9d952c1b97eba781_module, 'CANON_SRC')
split_assert = getattr(_ember_9d952c1b97eba781_module, 'split_assert')
# issue2015 exact-local-import-end:src/ember/governance/scripts/fp8_vgate.py  # single source (#63)
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py

NC = "<local-path>"
RECEIPTS = f"{NC}/receipts"
LEDGER = f"{NC}/receipts/ledger/episodes.jsonl"

# Production check rides ON the fp-8 canon (embedded verbatim). Failure
# semantics differ from the gate's _fp8_check only in the message: the gate
# CLASSIFIES flips (FP8FLIP:*), production simply fails the assert.
STRICT_SRC = CANON_SRC + '''
def _v_check(left, right):
    if not (left == right):
        raise AssertionError("strict-verify: values differ under ==")
    try:
        ok = (_fp8_canon(left) == _fp8_canon(right))
    except TypeError as e:
        raise AssertionError("strict-verify: " + str(e))
    if not ok:
        raise AssertionError("strict-verify: kind mismatch "
                             "(== passed, canonical forms differ)")
'''


def instrument_tests(tests):
    """Rewrite each single `assert L == R` statement to the strict check.
    Any other shape (non-==, chained, multi-statement) is returned VERBATIM
    — comparator tightening touches only the == path (issue #76 item 4)."""
    out = []
    for t in tests:
        pair = split_assert(t)
        out.append(f"_v_check(({pair[0]}), ({pair[1]}))" if pair else t)
    return out


def strict_harness(imports, src, tests, stub):
    """The production W-code harness shape with the strict preamble: one
    harness, all (instrumented) tests joined — byte-layout mirror of the
    w1_mbpp builder with STRICT_SRC between src and tests."""
    return ("\n".join(imports) + "\n" + src + "\n" + STRICT_SRC + "\n" +
            "\n".join(instrument_tests(tests)) + stub)


def _smoke():
    """Re-verify every verified mbpp ledger episode under the production
    strict harness; receipt agreement vs the recorded raw verdicts."""
    from datetime import datetime, timezone
    sys.path.insert(0, f"{NC}/scripts")
    from t1_probe import execute_batch
    from w1_mbpp import SOLVE_STUB, load_split

    problems = {p["id"]: p for p in load_split("train")}
    eps = []
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if str(r.get("task", "")).startswith("mbpp:") \
                    and r.get("verified"):
                eps.append(r)

    jobs, meta = [], []
    skipped = 0
    for ep in eps:
        p = problems.get(int(ep["task"].split(":")[1]))
        if p is None:
            skipped += 1
            continue
        jobs.append((strict_harness(p["imports"], ep["src"], p["tests"],
                                    SOLVE_STUB), [], []))
        meta.append(ep)

    results = execute_batch(jobs)
    flips = []
    for ep, r in zip(meta, results):
        ok = bool(r.get("verified")) and not r.get("error")
        if not ok:
            flips.append({"key": ep["key"], "task": ep["task"],
                          "bits": ep.get("bits"),
                          "stratum": ep.get("stratum"),
                          "error": str(r.get("error") or "")[:160]})

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "ENG21-SMOKE", "ts": ts,
        "comparator": "strict (fp8 canon, no coercion) — eng #76",
        "harness_shape": "w1_mbpp production (joined tests, one job/episode)",
        "n_episodes": len(meta), "skipped_no_problem": skipped,
        "reverified": len(meta) - len(flips),
        "flipped": len(flips),
        "flips": flips,
        "expectation": "fp8-vgate-20260611T001730Z: 2 container-kind flips "
                       "expected, all others re-verify",
    }
    out = f"{RECEIPTS}/eng21-smoke-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"ENG21_SMOKE_DONE {out}")


def _selftest():
    ns = {}
    exec(STRICT_SRC, ns)
    check = ns["_v_check"]
    # strict pass: identical structures
    check([1, 2, {"a": (1, 2)}], [1, 2, {"a": (1, 2)}])
    # raw inequality fails (normal verify failure)
    try:
        check(1, 2)
        raise AssertionError("expected raw failure")
    except AssertionError as e:
        assert "values differ" in str(e), e
    # kind mismatch fails on raw-==-True flips: True == 1, 1 == 1.0,
    # [True] == [1] (the nested leaf-kind case raw == cannot see)
    for left, right in ((True, 1), (1, 1.0), ([True], [1])):
        assert left == right  # raw == passes — that's the false-accept
        try:
            check(left, right)
            raise AssertionError(f"expected strict flip on {left!r}")
        except AssertionError as e:
            assert "kind mismatch" in str(e), e
    # unknown-type refusal: lying __eq__ never reaches builtin compare
    class _Yes:
        def __eq__(self, o):
            return True
    try:
        check(_Yes(), 5)
        raise AssertionError("expected unknown-type refusal")
    except AssertionError as e:
        assert "unknown-type" in str(e), e
    # instrumentation: == shape rewritten, everything else verbatim
    tests = ["assert f(2) == (4,)",
             "assert math.isclose(f(2), 1.1, rel_tol=0.01)",
             "assert a == b == c",
             "assert f(3) == [1, 2], 'msg'"]
    inst = instrument_tests(tests)
    assert inst[0] == "_v_check((f(2)), ((4,)))", inst[0]
    assert inst[1] == tests[1]  # non-== untouched
    assert inst[2] == tests[2]  # chained untouched (raw semantics kept)
    assert inst[3] == "_v_check((f(3)), ([1, 2]))", inst[3]
    # harness layout: imports / src / preamble / tests / stub
    h = strict_harness(["import math"], "def f(x):\n    return x\n",
                       ["assert f(2) == 2"], "\n\ndef solve(grid):\n"
                       "    return [[0]]\n")
    assert h.index("import math") < h.index("def f(x):") \
        < h.index("def _v_check") < h.index("_v_check((f(2)), (2))") \
        < h.index("def solve(grid):")
    # end-to-end: instrumented harness executes and verdicts correctly
    exec(strict_harness([], "def f(x):\n    return x\n",
                        ["assert f(2) == 2"], "\n"), {})
    try:  # raw-True leaf-kind flip caught inside the real harness shape
        exec(strict_harness([], "def f(x):\n    return [x == x, 2]\n",
                            ["assert f(1) == [1, 2]"], "\n"), {})
        raise AssertionError("nested kind flip must fail strict")
    except AssertionError as e:
        assert "kind mismatch" in str(e), e
    try:  # plain wrong answer still fails like always
        exec(strict_harness([], "def f(x):\n    return x + 1\n",
                            ["assert f(2) == 2"], "\n"), {})
        raise AssertionError("wrong value must fail")
    except AssertionError as e:
        assert "values differ" in str(e), e
    print("V_COMPARE_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    elif "--smoke" in sys.argv:
        _smoke()
    else:
        raise SystemExit("v_compare: pass --selftest or --smoke")
