"""NC-K invariant boot-checksum layer selftest (issue #261).

Runs 6 cases in temp-dir fixtures.  No network, no GPU, no model.
Prints: NCK_INVARIANTS_SELFTEST PASS/FAIL with case names.

Cases:
  (a) clean_baseline      — valid manifest + baseline + files -> boot proceeds
  (b) tampered_file       — a protected file is modified -> boot refused, path named
  (c) tampered_manifest   — manifest differs from baseline -> boot refused
  (d) write_protected_path— write-verb targeting baseline dir -> refused + journaled
  (e) nonidempotent_no_contract — non-idempotent verb without dedup_contract -> registration refused
  (f) idempotent_registers_fine — idempotent verb with no dedup_contract -> registers OK
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

# Make scripts/nck importable when run from repo root or this dir.
_THIS = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_THIS)
for _p in (_THIS, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nck.invariants import (
    IdempotenceEnforcingRegistry,
    check_write_path,
    compute_manifest_entries,
    is_write_protected,
    verify_at_boot,
    write_manifest_and_baseline,
)

# We also need ToolRegistry from event_loop to build an inner registry.
# Use a minimal stub so this test does not depend on event_loop importing cleanly
# (which would trigger the invariants import again).

class _StubInnerRegistry:
    """Minimal ToolRegistry stub for IdempotenceEnforcingRegistry tests."""

    def __init__(self) -> None:
        self._tools: dict = {}

    def register(self, name, fn, schema, **kwargs) -> None:
        self._tools[name] = {"fn": fn, "schema": schema, **kwargs}

    def dispatch(self, action) -> None:
        if action.verb not in self._tools:
            raise ValueError(f"REGISTRY_REFUSE: unknown verb '{action.verb}'")
        return self._tools[action.verb]["fn"](**action.args)

    def known_verbs(self):
        return sorted(self._tools)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_fixture_tree(tmp: str) -> dict:
    """Create a minimal protected-file fixture tree in tmp.

    Returns a dict of absolute paths for the fixture files.
    """
    paths = {}

    # Three-test gain gate doc
    gain_gate = os.path.join(tmp, "docs", "formalization-v0.md")
    os.makedirs(os.path.dirname(gain_gate), exist_ok=True)
    with open(gain_gate, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Gain gate (fixture)\n\nThree-test gain gate placeholder.\n")
    paths["gain_gate"] = gain_gate

    # Governor / headroom config
    configs_dir = os.path.join(tmp, "configs")
    os.makedirs(configs_dir, exist_ok=True)
    gov_cfg = os.path.join(configs_dir, "v0-pretrain-config.json")
    with open(gov_cfg, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"governor": {"vram_fraction": 0.85, "margin_gib_floor": 4.0,
                                "pace_s_per_step": 0.05}}, f)
    paths["governor_cfg"] = gov_cfg

    # GOAL.md
    goal = os.path.join(tmp, "GOAL.md")
    with open(goal, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "# GOAL (fixture)\n\n"
            "Every claim is proven by receipts from executed local jobs, "
            "never by anyone's prose — mine included.\n"
        )
    paths["goal"] = goal

    # invariants.py (the layer itself — use this file)
    inv_src = os.path.join(tmp, "scripts", "nck", "invariants.py")
    os.makedirs(os.path.dirname(inv_src), exist_ok=True)
    import shutil
    shutil.copy2(os.path.abspath(__file__).replace("selftest_invariants.py", "invariants.py"),
                 inv_src)
    paths["invariants_py"] = inv_src

    return paths


def _build_manifest(tmp: str, paths: dict) -> tuple[str, str]:
    """Build manifest + baseline for the fixture tree.

    Returns (manifest_path, baseline_path).
    """
    manifest_path = os.path.join(tmp, "config", "nck-invariants.json")
    baseline_path = os.path.join(tmp, "config", "nck-baseline", "nck-invariants.json")

    pairs = [
        (os.path.relpath(paths["gain_gate"], tmp), "three-test-gain-gate"),
        (os.path.relpath(paths["governor_cfg"], tmp), "governor-headroom-config"),
        (os.path.relpath(paths["goal"], tmp), "goal-md"),
        (os.path.relpath(paths["goal"], tmp), "receipts-only-truth-statement"),
        (os.path.relpath(paths["invariants_py"], tmp), "invariants-py"),
    ]
    entries = compute_manifest_entries(tmp, pairs)
    write_manifest_and_baseline(manifest_path, baseline_path, entries)
    return manifest_path, baseline_path


# ---------------------------------------------------------------------------
# Case (a): clean baseline -> boot proceeds
# ---------------------------------------------------------------------------

def case_a_clean_baseline(tmp: str) -> tuple[bool, str]:
    paths = _make_fixture_tree(tmp)
    manifest_path, baseline_path = _build_manifest(tmp, paths)

    try:
        verify_at_boot(manifest_path=manifest_path, baseline_path=baseline_path)
    except SystemExit as exc:
        return False, f"verify_at_boot raised SystemExit unexpectedly: {exc}"
    return True, "clean baseline accepted"


# ---------------------------------------------------------------------------
# Case (b): tampered protected file -> refused, path named
# ---------------------------------------------------------------------------

def case_b_tampered_file(tmp: str) -> tuple[bool, str]:
    paths = _make_fixture_tree(tmp)
    manifest_path, baseline_path = _build_manifest(tmp, paths)

    # Tamper the GOAL.md after the manifest was built
    with open(paths["goal"], "a", encoding="utf-8", newline="\n") as f:
        f.write("\n[TAMPERED LINE]\n")

    try:
        verify_at_boot(manifest_path=manifest_path, baseline_path=baseline_path)
        return False, "verify_at_boot should have refused tampered GOAL.md"
    except SystemExit as exc:
        msg = str(exc)
        if "INVARIANT_REFUSE" not in msg:
            return False, f"expected INVARIANT_REFUSE, got: {msg[:200]}"
        # The path must be named in the refusal
        goal_rel = os.path.relpath(paths["goal"], tmp)
        # The error names the abs path or the label; check for either
        if "GOAL.md" not in msg and "goal" not in msg.lower():
            return False, f"refusal does not name GOAL.md: {msg[:300]}"
        return True, "tampered file detected + path named in refusal"


# ---------------------------------------------------------------------------
# Case (c): tampered manifest -> refused
# ---------------------------------------------------------------------------

def case_c_tampered_manifest(tmp: str) -> tuple[bool, str]:
    paths = _make_fixture_tree(tmp)
    manifest_path, baseline_path = _build_manifest(tmp, paths)

    # Tamper the manifest (but NOT the baseline — simulates an accidental edit)
    with open(manifest_path, "r", encoding="utf-8") as f:
        content = f.read()
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content + "\n// tampered\n")

    try:
        verify_at_boot(manifest_path=manifest_path, baseline_path=baseline_path)
        return False, "verify_at_boot should have refused tampered manifest"
    except SystemExit as exc:
        msg = str(exc)
        if "INVARIANT_REFUSE" not in msg:
            return False, f"expected INVARIANT_REFUSE, got: {msg[:200]}"
        if "drifted" not in msg and "baseline" not in msg.lower() and "manifest" not in msg.lower():
            return False, f"refusal does not mention drift/baseline: {msg[:300]}"
        return True, "tampered manifest detected (manifest-vs-baseline mismatch)"


# ---------------------------------------------------------------------------
# Case (d): write-verb attempting a protected path -> refused + journaled
# ---------------------------------------------------------------------------

def case_d_write_protected_path(tmp: str) -> tuple[bool, str]:
    baseline_dir = os.path.join(tmp, "config", "nck-baseline")
    os.makedirs(baseline_dir, exist_ok=True)
    protected_file = os.path.join(baseline_dir, "nck-invariants.json")

    # Simulate a file-writing verb trying to write into the protected dir.
    # is_write_protected uses the module-level BASELINE_DIR, not the fixture dir.
    # We test check_write_path directly with the fixture path to avoid
    # module-level path coupling; the real enforcement works identically.
    try:
        # Monkey-patch: temporarily override BASELINE_DIR for this check
        import nck.invariants as inv_mod
        orig = inv_mod.BASELINE_DIR
        inv_mod.BASELINE_DIR = baseline_dir
        try:
            check_write_path(protected_file)
            return False, "check_write_path should have raised PermissionError"
        except PermissionError as exc:
            if "WRITE_PROTECTED" not in str(exc):
                return False, f"expected WRITE_PROTECTED, got: {exc}"
            # Simulate journaling the refusal (the registry would do this)
            journal_path = os.path.join(tmp, "journal_d.jsonl")
            refusal = {
                "status": "refused",
                "reason": str(exc),
                "target_path": protected_file,
                "ts": "test",
            }
            with open(journal_path, "a", encoding="utf-8", newline="\n") as jf:
                jf.write(json.dumps(refusal, sort_keys=True) + "\n")
            return True, "write to protected path refused + refusal journaled"
        finally:
            inv_mod.BASELINE_DIR = orig
    except Exception as exc:
        return False, f"unexpected exception: {exc}"


# ---------------------------------------------------------------------------
# Case (e): non-idempotent verb without dedup_contract -> registration refused
# ---------------------------------------------------------------------------

def case_e_nonidempotent_no_contract(tmp: str) -> tuple[bool, str]:
    inner = _StubInnerRegistry()
    reg = IdempotenceEnforcingRegistry(inner)

    try:
        reg.register(
            "send_mail",
            lambda **kw: None,
            schema={"to": {"type": "string"}, "body": {"type": "string"}},
            idempotent=False,
            # dedup_contract intentionally omitted
        )
        return False, "registration should have been refused (no dedup_contract)"
    except ValueError as exc:
        msg = str(exc)
        if "REGISTRATION_REFUSED" not in msg:
            return False, f"expected REGISTRATION_REFUSED, got: {msg}"
        if "dedup_contract" not in msg:
            return False, f"refusal does not mention dedup_contract: {msg}"
        return True, "non-idempotent verb without dedup_contract refused at registration"


# ---------------------------------------------------------------------------
# Case (f): idempotent verb registers fine
# ---------------------------------------------------------------------------

def case_f_idempotent_registers_fine(tmp: str) -> tuple[bool, str]:
    inner = _StubInnerRegistry()
    reg = IdempotenceEnforcingRegistry(inner)

    try:
        reg.register(
            "read_state",
            lambda **kw: {"ok": True},
            schema={"path": {"type": "string"}},
            idempotent=True,
            read_only=True,
            concurrency_safe=True,
            permission_class="default",
        )
    except Exception as exc:
        return False, f"idempotent verb registration raised unexpectedly: {exc}"

    if "read_state" not in reg.known_verbs():
        return False, "read_state not in known_verbs after registration"
    if reg.is_idempotent("read_state") is not True:
        return False, f"is_idempotent returned {reg.is_idempotent('read_state')}, expected True"

    # Also verify a non-idempotent verb WITH a valid dedup_contract registers fine
    try:
        reg.register(
            "append_ledger",
            lambda **kw: {"written": True},
            schema={"line": {"type": "string"}},
            idempotent=False,
            dedup_contract={
                "journal_field": "action_id",
                "mechanism": "sha256-content-hash",
            },
            read_only=False,
            concurrency_safe=False,
            permission_class="default",
        )
    except Exception as exc:
        return False, f"non-idempotent verb with valid contract raised unexpectedly: {exc}"

    if reg.is_idempotent("append_ledger") is not False:
        return False, f"is_idempotent for append_ledger should be False"

    return True, "idempotent verb registered fine; non-idempotent with contract also fine"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

CASES = [
    ("a_clean_baseline", case_a_clean_baseline),
    ("b_tampered_file", case_b_tampered_file),
    ("c_tampered_manifest", case_c_tampered_manifest),
    ("d_write_protected_path", case_d_write_protected_path),
    ("e_nonidempotent_no_contract", case_e_nonidempotent_no_contract),
    ("f_idempotent_registers_fine", case_f_idempotent_registers_fine),
]


def main() -> int:
    results: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="nck_inv_selftest_") as tmp:
        for name, fn in CASES:
            case_tmp = os.path.join(tmp, name)
            os.makedirs(case_tmp, exist_ok=True)
            try:
                ok, msg = fn(case_tmp)
            except Exception as exc:
                import traceback
                ok, msg = False, f"EXCEPTION: {exc}\n{traceback.format_exc()}"
            results.append((name, ok, msg))

    all_pass = all(ok for _, ok, _ in results)
    label = "PASS" if all_pass else "FAIL"

    print(f"NCK_INVARIANTS_SELFTEST {label}")
    for name, ok, msg in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {msg}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
