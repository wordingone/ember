"""v_reachguard.py — object-graph reachability guard for the sandbox (#86, eng-23).

Closes the SECOND live-confirmed false-accept class from the soundness probe
set (receipt ts 20260611T000301Z): a submitted program reaches
non-allow-listed objects (os, the underlying builtins, file handles) by
traversing the CPython object graph instead of importing them — reaching
non-allow-listed objects via attribute chains such as:

    ().__class__.__base__.__subclasses__()      # enumerate every loaded class
    fn.__globals__['__builtins__']['__import__'] # reach the underlying importer

so the `__import__` allow-list (`_safe_import`) never fires and V records a
false-accept `verified` with no import event. eng-21 (the strict comparator)
closed the comparison-DISPATCH class; this closes the object-graph
TRAVERSAL class. Both are sandbox-soundness, not answer-correctness.

Mechanism — a pure-AST pre-scan of the submitted source, run BEFORE
`exec` in t1_probe.run_program, fail-closed (a flagged program yields a
normal FAIL verdict with a `REACHGUARD:` sentinel in the error field; the
sandbox truncates error to 200 chars, so the sentinel is prefix-first).

It refuses, by NAME, the introspection/traversal attributes that have no
use in a grid/string transform but are the rungs of every reachability chain:
`__subclasses__ __bases__ __base__ __mro__ __subclasshook__ __globals__
__code__ __closure__ __func__ __self__ __getattribute__ __builtins__
__dict__`. It does NOT touch the data-model dunders legitimate code defines
or reads (`__init__ __len__ __eq__ __iter__ __getitem__ __name__ __class__
...`) — `__class__` alone reaches nothing without one of the forbidden
rungs, and `__name__` is load-bearing in the production canon preamble
(`type(x).__name__`). The forbidden set is matched against:

  - attribute access            x.__subclasses__
  - constant-string getattr     getattr(x, "__subclasses__")  (and set/del/has)
  - DYNAMIC getattr name        getattr(x, "__sub" + "classes__")  -> fail-closed
    (a transform never needs to COMPUTE an attribute name at runtime; this is
     the only residual gap of a name-based scan, so it is refused outright)
  - bare global names           __builtins__, __import__  (Subscript reach root)

Verified zero-flag against all verified ledger episode sources before the
live leg (receipt in the PR); the daemon re-runs the unchanged soundness
probe (the subclasses-reachability probe must flip to BLOCKED) and the
fp-8 zero-new-flips leg over all 956 mbpp episodes.

`python v_reachguard.py --selftest` is pure-logic and runs anywhere.
"""
import ast
import sys

SENTINEL = "REACHGUARD"  # prefix-first: t1_probe formats error f"{type}: {msg}"[:200]

# Attribute names that reach the object graph / a frame's globals / the real
# builtins. NOT the data-model dunders (those have legit uses); these do not.
FORBIDDEN_ATTRS = frozenset({
    "__subclasses__", "__bases__", "__base__", "__mro__", "__subclasshook__",
    "__globals__", "__code__", "__closure__", "__func__", "__self__",
    "__getattribute__", "__builtins__", "__dict__",
})

# Bare names that are reachability ROOTS even without attribute access (Subscript
# reach, e.g. __builtins__['__import__']). __import__ as a NAME is never used
# by import-statement code; episodes import via `import x` (allow-listed).
FORBIDDEN_NAMES = frozenset({"__builtins__", "__import__"})

# Attribute-resolving builtins whose target name we must inspect.
_GETATTR_FAMILY = frozenset({"getattr", "setattr", "delattr", "hasattr"})


def scan(src):
    """Return a `REACHGUARD:<reason>` string if `src` reaches non-allow-listed
    objects via object-graph traversal, else None. Unparsable source is NOT
    flagged here — the sandbox's own exec raises SyntaxError and fails it
    (keeping this guard's verdict surface to the reachability class only)."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        # unparsable (incl. null bytes) — let the sandbox's own exec fail it;
        # this guard's verdict surface stays scoped to the reachability class
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            return f"{SENTINEL}:attr {node.attr}"
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            return f"{SENTINEL}:name {node.id}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in _GETATTR_FAMILY and len(node.args) >= 2:
            name_arg = node.args[1]
            if isinstance(name_arg, ast.Constant) \
                    and isinstance(name_arg.value, str):
                if name_arg.value in FORBIDDEN_ATTRS:
                    return f"{SENTINEL}:{node.func.id}-const {name_arg.value}"
            else:
                # dynamic/computed attribute name — fail-closed
                return f"{SENTINEL}:{node.func.id}-dynamic"
    return None


def _selftest():
    # the live reachability chain the probe walks -> BLOCKED
    assert scan("def p():\n return (1).__class__.__base__.__subclasses__()\n")
    assert scan("x = ().__class__.__bases__[0].__subclasses__()\n")
    assert scan("y = f.__globals__['__builtins__']\n")
    assert scan("z = g.__code__\n") and scan("w = m.__mro__\n")
    # constant-string getattr form of the same access -> BLOCKED
    assert scan("getattr(o, '__subclasses__')()\n")
    assert scan("getattr(int, '__bases__')\n")
    # dynamic attribute construction (string-concat bypass) -> fail-closed
    assert scan("getattr(o, '__sub' + 'classes__')()\n")
    assert scan("n = '__subclasses__'\ngetattr(o, n)()\n")
    # bare reachability-root names -> BLOCKED
    assert scan("__builtins__['__import__']('os')\n")
    assert scan("__import__('os')\n")
    # reason strings are sentinel-prefixed (transport contract)
    assert scan("a.__globals__").startswith(SENTINEL + ":")

    # legitimate programs are NOT flagged ------------------------------------
    assert scan("def solve(grid):\n    return [row[:] for row in grid]\n") is None
    assert scan("import numpy as np\n"
                "def solve(g):\n    return np.array(g).T.tolist()\n") is None
    # data-model dunders legit code defines/reads stay allowed
    assert scan("class P:\n    def __init__(self):\n        self.n = 0\n"
                "    def __len__(self):\n        return self.n\n") is None
    assert scan("for i, x in enumerate(xs):\n    print(x.__class__)\n") is None
    # the canon preamble's type(x).__name__ must pass (else every harness flips)
    assert scan('def f(x):\n    return type(x).__name__\n') is None
    # legit 2-arg getattr on an ordinary attribute name passes
    assert scan("getattr(obj, 'value', 0)\n") is None
    assert scan("hasattr(x, 'append')\n") is None
    # legit dict access named 'globals' as a plain key is fine (not a call)
    assert scan("d = {'globals': 1}\nv = d['globals']\n") is None
    print("V_REACHGUARD_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        raise SystemExit("v_reachguard: pass --selftest "
                         "(scan() is imported by t1_probe.run_program)")
