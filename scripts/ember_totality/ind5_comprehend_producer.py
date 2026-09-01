#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ind5_comprehend_producer.py -- issue #88: IND-5 COMPREHEND re-spec.

Operator directive (2026-07-04, verbatim class): no board condition may
require operator action -- conditions must be properties of the SYSTEM, not
of the operator. The OLD IND-5 [A] leg (a dated, transcription-marked
operator-attestation object) violated this by construction: it is a fact
about a human mind, unfalsifiable by the system, and it parked a board RED
on a person. This producer replaces the GREEN-path semantics of [A] with
four machine-checkable comprehensibility legs, receipts-only:

  1. entry_point_integrity -- docs/operator/README.md resolves and every doc
     it DIRECTLY links exists on disk.
  2. completeness          -- every operator-facing surface the CLI's OWN
     command registry (execution tree) exposes is named somewhere in the
     docs/operator/ tree (by name or alias, whole-word match); unnamed
     commands are the gap, enumerated verbatim.
  3. freshness             -- every backtick-quoted slash-command the docs
     cite as real (excluding lines that themselves describe it as an
     UNRECOGNIZED/UNKNOWN example -- see KNOWN_BAD_EXAMPLE_TOKENS) actually
     exists in the CURRENT live command registry; a doc-cited name absent
     from the live dump is a stale doc, RED.
  4. executability         -- every extracted runnable example (a small,
     explicit verb whitelist: mkdir/cp/New-Item/Copy-Item/python -c) EXECUTES
     exit-0 against the live tree. Examples this producer cannot safely run
     headless (an interactive TUI/REPL boot -- ember.exe, ember-world-state-
     repl.ts) are EXCLUDED with a disclosed, non-empty reason -- never
     silently skipped, never silently passed.

  "Keybinds": this CLI ships no separate keybind-registry file distinct
  from its slash-command registry (verified by inspection, issue #88 notes)
  -- command names/aliases ARE the operator-facing surface set; folded into
  legs 2/3 above rather than a bespoke parser for a registry that does not
  exist.

Board semantics (test_c_ind.py owns the aggregate verdict; this producer
only writes the receipt): IND-5 GREEN iff all four legs' `passed` is True.

Audit continuity: the OLD attestation field is retained verbatim under
`attestation_superseded_by` -- history is not rewritten, and the OLD field's
script-authored-invalid trap (`invalid_comprehension_by_script`) stays
enforced by test_c_ind.py so a legacy claim cannot be faked retroactively.

Run:  PYTHONIOENCODING=utf-8 python ind5_comprehend_producer.py
        [--root <contract-tree>] [--exec-root <execution-tree>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # scripts/ember_totality
REPO_ROOT_DEFAULT = HERE.parent.parent           # ember-goalforge (contract tree)
sys.path.insert(0, str(REPO_ROOT_DEFAULT))
# issue2015 exact-local-import:src/ember/governance/scripts/lib/invariant.py
import importlib.util as _ember_2560a87c017c05b0_importlib
import sys as _ember_2560a87c017c05b0_sys
from pathlib import Path as _ember_2560a87c017c05b0_Path
_ember_2560a87c017c05b0_path = _ember_2560a87c017c05b0_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'lib', 'invariant.py')
if not _ember_2560a87c017c05b0_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/lib/invariant.py')
_ember_2560a87c017c05b0_aliases = ('_ember_issue2015_2560a87c017c05b0', 'invariant', 'scripts.lib.invariant')
_ember_2560a87c017c05b0_existing = []
for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
    _ember_2560a87c017c05b0_candidate = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
    if _ember_2560a87c017c05b0_candidate is not None and all(_ember_2560a87c017c05b0_candidate is not item for item in _ember_2560a87c017c05b0_existing):
        _ember_2560a87c017c05b0_existing.append(_ember_2560a87c017c05b0_candidate)
if len(_ember_2560a87c017c05b0_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/lib/invariant.py')
if _ember_2560a87c017c05b0_existing:
    _ember_2560a87c017c05b0_module = _ember_2560a87c017c05b0_existing[0]
    _ember_2560a87c017c05b0_observed = getattr(_ember_2560a87c017c05b0_module, '__file__', None)
    if _ember_2560a87c017c05b0_observed is None or _ember_2560a87c017c05b0_Path(_ember_2560a87c017c05b0_observed).resolve() != _ember_2560a87c017c05b0_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/lib/invariant.py')
else:
    _ember_2560a87c017c05b0_spec = _ember_2560a87c017c05b0_importlib.spec_from_file_location('_ember_issue2015_2560a87c017c05b0', _ember_2560a87c017c05b0_path)
    if _ember_2560a87c017c05b0_spec is None or _ember_2560a87c017c05b0_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/lib/invariant.py')
    _ember_2560a87c017c05b0_module = _ember_2560a87c017c05b0_importlib.module_from_spec(_ember_2560a87c017c05b0_spec)
    for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
        _ember_2560a87c017c05b0_prior = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
        if _ember_2560a87c017c05b0_prior is not None and _ember_2560a87c017c05b0_prior is not _ember_2560a87c017c05b0_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lib/invariant.py')
        _ember_2560a87c017c05b0_sys.modules[_ember_2560a87c017c05b0_alias] = _ember_2560a87c017c05b0_module
    try:
        _ember_2560a87c017c05b0_spec.loader.exec_module(_ember_2560a87c017c05b0_module)
    except BaseException:
        for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
            if _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias) is _ember_2560a87c017c05b0_module:
                _ember_2560a87c017c05b0_sys.modules.pop(_ember_2560a87c017c05b0_alias, None)
        raise
for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
    _ember_2560a87c017c05b0_prior = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
    if _ember_2560a87c017c05b0_prior is not None and _ember_2560a87c017c05b0_prior is not _ember_2560a87c017c05b0_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lib/invariant.py')
    _ember_2560a87c017c05b0_sys.modules[_ember_2560a87c017c05b0_alias] = _ember_2560a87c017c05b0_module
_stamp_invariant = getattr(_ember_2560a87c017c05b0_module, 'stamp')
_verify_invariant = getattr(_ember_2560a87c017c05b0_module, 'verify')
# issue2015 exact-local-import-end:src/ember/governance/scripts/lib/invariant.py  # noqa: E402 -- gh #625 point 1

# receipt_check.py's R2 rule requires any *sha256*-named field to carry a
# disclosed sha_convention; matches exactly what src/ember/governance/scripts/lib/invariant.py's
# stamp() does (Path.read_bytes() + sha256, no normalization).
INVARIANT_SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
# Environment variable override for execution tree root; default points to external location
# EMBER_EXEC_ROOT env var can override. Default: <local-exec-root> (frozen spec v1 convention)
_exec_root = os.environ.get("EMBER_EXEC_ROOT")
if not _exec_root:
    raise ValueError("EMBER_EXEC_ROOT env var is required. Example: <local-exec-root>")
EXEC_ROOT_DEFAULT = Path(_exec_root)
REGISTRY_DUMP_SCRIPT = Path(__file__).resolve().parent.parent.parent / \
    "scratch" / "ind5-registry-dump" / "dump_registry.ts"
README_REL = "docs/operator/README.md"
OPERATOR_DOCS_REL = "docs/operator"

# A doc line describing an intentionally-nonexistent example command (e.g.
# interact.md's own "/xyzzy" bad-input demonstration) must never be read as
# a freshness claim. Small, explicit, documented -- never a silent filter.
KNOWN_BAD_EXAMPLE_TOKENS = {"xyzzy"}
BAD_EXAMPLE_LINE_MARKERS = ("unrecognized", "unknown command", "bad-input", "bad input")

# Executability: a small, explicit, safe verb whitelist. Anything outside
# this set that looks like a command (bun/node/ember.exe invocations that
# boot an interactive TUI or long-running build) is EXCLUDED with a reason,
# never executed and never silently dropped from the receipt.
SAFE_VERBS = ("mkdir", "New-Item", "cp", "Copy-Item")
SAFE_INLINE_PREFIX = "python -c"
INTERACTIVE_MARKERS = (
    "ember.exe", "ember-cured.exe", "ember-world-state-repl", "bun install", "bun run build",
)

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_BACKTICK_SLASH_RE = re.compile(r"`(/[A-Za-z][\w-]*)`")
_WORD_RE = re.compile(r"[A-Za-z][\w-]*")


# ---------------------------------------------------------------------------
# Leg 1: entry_point_integrity
# ---------------------------------------------------------------------------

def extract_readme_links(readme_text: str) -> list[str]:
    """Direct markdown-link targets from README.md text, external/anchor
    links excluded (not doc pointers)."""
    out = []
    for m in _LINK_RE.finditer(readme_text):
        target = m.group(1).strip()
        if not target or target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        out.append(target)
    return out


def check_entry_point_integrity(root: Path) -> dict:
    readme = root / README_REL
    if not readme.is_file():
        return {
            "passed": False, "readme_path": README_REL, "linked_docs": [], "dead_links": [],
            "reason": f"{README_REL} does not exist under root",
        }
    text = readme.read_text(encoding="utf-8", errors="replace")
    links = sorted(set(extract_readme_links(text)))
    dead = sorted(l for l in links if not (readme.parent / l).is_file())
    return {
        "passed": not dead,
        "readme_path": README_REL,
        "linked_docs": links,
        "dead_links": dead,
        "reason": "all linked docs resolve" if not dead else f"dead link(s): {dead}",
    }


# ---------------------------------------------------------------------------
# Live command registry (execution tree) -- shared by legs 2 and 3
# ---------------------------------------------------------------------------

def run_registry_dump(exec_root: Path, dump_script: Path = REGISTRY_DUMP_SCRIPT,
                       bun_bin: str = "bun", timeout: int = 30) -> dict:
    """Invoke the bun dump helper against exec_root's ember-cli src by
    ABSOLUTE import path (never writes into the execution tree). Returns
    {"ok": True, "commands": [...]} or {"ok": False, "error": "..."}."""
    cli_src = exec_root / "tools" / "ember-cli" / "src"
    if not cli_src.is_dir():
        return {"ok": False, "error": f"execution-tree ember-cli src not found: {cli_src}"}
    if not dump_script.is_file():
        return {"ok": False, "error": f"registry dump helper missing: {dump_script}"}
    # Windows: bun installs as bun.cmd; subprocess.run(list, shell=False)
    # cannot exec a .cmd wrapper directly (WinError 2), so resolve via
    # shutil.which() first -- PATHEXT-aware, works cross-platform (a no-op
    # resolve on POSIX where bun is a real executable already on PATH).
    resolved_bun = shutil.which(bun_bin) or bun_bin
    try:
        proc = subprocess.run(
            [resolved_bun, "run", str(dump_script), str(cli_src)],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"registry dump failed to execute: {exc}"}
    if proc.returncode != 0:
        return {"ok": False, "error": f"registry dump exited {proc.returncode}: {proc.stderr.strip()[:500]}"}
    try:
        commands = json.loads(proc.stdout.strip())
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"registry dump produced non-JSON stdout: {exc}"}
    return {"ok": True, "commands": commands}


def _all_doc_text(operator_docs_dir: Path) -> str:
    parts = []
    if operator_docs_dir.is_dir():
        for p in sorted(operator_docs_dir.glob("*.md")):
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _doc_word_set(operator_docs_dir: Path) -> set[str]:
    return set(_WORD_RE.findall(_all_doc_text(operator_docs_dir)))


# ---------------------------------------------------------------------------
# Leg 2: completeness
# ---------------------------------------------------------------------------

def check_completeness(live_commands: list[dict], operator_docs_dir: Path) -> dict:
    words = _doc_word_set(operator_docs_dir)
    undocumented = []
    for cmd in live_commands:
        names = [cmd.get("name", "")] + list(cmd.get("aliases") or [])
        names = [n for n in names if n]
        if not any(n in words for n in names):
            undocumented.append({"name": cmd.get("name"), "aliases": cmd.get("aliases") or []})
    return {
        "passed": not undocumented,
        "live_command_count": len(live_commands),
        "undocumented_commands": undocumented,
        "reason": ("every live command named somewhere in docs/operator/" if not undocumented
                   else f"{len(undocumented)} live command(s) undocumented: "
                        f"{[c['name'] for c in undocumented]}"),
    }


# ---------------------------------------------------------------------------
# Leg 3: freshness
# ---------------------------------------------------------------------------

def extract_cited_slash_commands(operator_docs_dir: Path) -> dict[str, list[str]]:
    """Backtick-quoted /token mentions per doc file, EXCLUDING lines that
    describe the token as an intentionally-nonexistent example (a doc
    demonstrating error-handling behavior, not claiming a real command)."""
    cited: dict[str, list[str]] = {}
    if not operator_docs_dir.is_dir():
        return cited
    for p in sorted(operator_docs_dir.glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            lower = line.lower()
            if any(marker in lower for marker in BAD_EXAMPLE_LINE_MARKERS):
                continue
            for m in _BACKTICK_SLASH_RE.finditer(line):
                token = m.group(1)[1:]  # strip leading '/'
                if token in KNOWN_BAD_EXAMPLE_TOKENS:
                    continue
                cited.setdefault(token, [])
                rel = p.name
                if rel not in cited[token]:
                    cited[token].append(rel)
    return cited


def check_freshness(live_commands: list[dict], operator_docs_dir: Path) -> dict:
    live_names = set()
    for cmd in live_commands:
        if cmd.get("name"):
            live_names.add(cmd["name"])
        for a in cmd.get("aliases") or []:
            live_names.add(a)
    cited = extract_cited_slash_commands(operator_docs_dir)
    stale = {tok: docs for tok, docs in cited.items() if tok not in live_names}
    return {
        "passed": not stale,
        "cited_slash_commands": cited,
        "stale_citations": stale,
        "reason": ("every cited slash-command exists in the live registry" if not stale
                   else f"stale doc citation(s), absent from live registry: {stale}"),
    }


# ---------------------------------------------------------------------------
# Leg 4: executability
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*```(\w*)\s*$")


def extract_runnable_examples(operator_docs_dir: Path) -> list[dict]:
    """Verb-whitelist extraction: SAFE lines (mkdir/cp/New-Item/Copy-Item/
    python -c) are marked runnable, tagged with the fence language they came
    from (sh/powershell/none -- "none" = a bare inline backtick span in
    prose, e.g. customize.md's python -c one-liner). Lines naming an
    interactive-boot marker are marked excluded with a reason. Everything
    else (prose, cd, plain tool names) is not an "example" at all and is not
    returned. Fence-language tracking matters because a POSIX ```sh block
    (`mkdir -p`) and a ```powershell block (`New-Item`) each need their OWN
    interpreter -- running both through one generic shell picks the wrong
    one for at least one of them (Windows cmd.exe understands neither
    `-p` nor `New-Item`)."""
    examples = []
    if not operator_docs_dir.is_dir():
        return examples
    for p in sorted(operator_docs_dir.glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        in_fence = False
        fence_lang = None
        for raw_line in text.splitlines():
            fence_m = _FENCE_RE.match(raw_line)
            if fence_m:
                if in_fence:
                    in_fence, fence_lang = False, None
                else:
                    in_fence, fence_lang = True, (fence_m.group(1) or "sh")
                continue
            candidates = [(raw_line.strip(), fence_lang)] if in_fence else [
                (m.group(1), None) for m in re.finditer(r"`([^`]+)`", raw_line)
            ]
            for line, lang in candidates:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if any(marker in line for marker in INTERACTIVE_MARKERS):
                    examples.append({
                        "doc": p.name, "line": line, "fence_lang": lang, "status": "excluded_interactive",
                        "reason": "boots an interactive TUI/REPL or a long-running build step; "
                                  "cannot exit-0 check headless (see IND-1/IND-3's own PTY-driven "
                                  "receipts for that verification instead)",
                    })
                    continue
                first_word = line.split(None, 1)[0] if line.split() else ""
                if first_word in SAFE_VERBS or line.startswith(SAFE_INLINE_PREFIX):
                    examples.append({"doc": p.name, "line": line, "fence_lang": lang, "status": "candidate"})
    return examples


def _run_example(line: str, fence_lang: str | None, cwd: Path, timeout: int = 30) -> dict:
    """Dispatch to the interpreter the fence language actually names. A
    plain `python -c "..."` inline span (fence_lang None) is a self-
    contained, cross-platform invocation and runs directly. An unavailable
    interpreter on this host is reported as such, never silently passed."""
    if line.startswith(SAFE_INLINE_PREFIX) and fence_lang is None:
        argv = ["python", "-c", line[len(SAFE_INLINE_PREFIX):].strip().strip('"')]
    elif fence_lang == "powershell":
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if not ps:
            return {"executed": False, "error": "no powershell/pwsh interpreter found on this host"}
        argv = [ps, "-NoProfile", "-NonInteractive", "-Command", line]
    else:  # "sh"/"bash"/default fence language for shell blocks
        sh = shutil.which("bash") or shutil.which("sh")
        if not sh:
            return {"executed": False, "error": "no bash/sh interpreter found on this host"}
        argv = [sh, "-c", line]
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"executed": True, "exit_code": None, "error": f"{type(exc).__name__}: {exc}"}
    return {"executed": True, "exit_code": proc.returncode,
             "stderr_tail": (proc.stderr or "")[-500:]}


def check_executability(operator_docs_dir: Path, run_cwd: Path) -> dict:
    examples = extract_runnable_examples(operator_docs_dir)
    results = []
    all_ok = True
    for ex in examples:
        if ex["status"] == "excluded_interactive":
            if not ex.get("reason"):
                all_ok = False  # an undisclosed exclusion is itself a failure
            results.append(ex)
            continue
        run = _run_example(ex["line"], ex.get("fence_lang"), run_cwd)
        passed = run.get("executed") and run.get("exit_code") == 0
        if not passed:
            all_ok = False
        results.append({**ex, **run, "passed": passed})
    return {
        "passed": all_ok,
        "examples": results,
        "reason": ("every runnable example exited 0; every excluded example disclosed a reason"
                   if all_ok else "one or more runnable examples failed, or an exclusion lacked a disclosed reason"),
    }


# ---------------------------------------------------------------------------
# Receipt assembly
# ---------------------------------------------------------------------------

def _find_old_attestation_receipts(root: Path) -> list[str]:
    ind_dir = root / "receipts" / "ember-operator-independence"
    if not ind_dir.is_dir():
        return []
    found = []
    for p in sorted(ind_dir.glob("*.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict) and obj.get("leg") in ("a_attested", "s_checkable"):
            found.append(str(p.relative_to(root)))
    return found


def build_ind5_receipt(root: Path, exec_root: Path) -> dict:
    dump = run_registry_dump(exec_root)
    live_commands = dump.get("commands", []) if dump.get("ok") else []
    operator_docs_dir = root / OPERATOR_DOCS_REL

    leg_epi = check_entry_point_integrity(root)
    leg_completeness = (
        check_completeness(live_commands, operator_docs_dir) if dump.get("ok")
        else {"passed": False, "reason": f"registry dump unavailable: {dump.get('error')}"}
    )
    leg_freshness = (
        check_freshness(live_commands, operator_docs_dir) if dump.get("ok")
        else {"passed": False, "reason": f"registry dump unavailable: {dump.get('error')}"}
    )
    leg_executability = check_executability(operator_docs_dir, root)

    legs = {
        "entry_point_integrity": leg_epi,
        "completeness": leg_completeness,
        "freshness": leg_freshness,
        "executability": leg_executability,
    }
    all_passed = all(bool(v.get("passed")) for v in legs.values())

    return {
        "receipt_class": "IND-5",
        "leg": "comprehend_v2",
        "spec_amendment": {
            "date": "2026-07-04",
            "issue": "#88",
            "rationale": (
                "operator directive (verbatim class, 2026-07-04): no board condition may "
                "require operator action -- conditions must be properties of the system, not "
                "the operator. The OLD [A] leg (operator-attestation object) violated this by "
                "construction: unfalsifiable by the system, a fact about a human mind, parking "
                "a board RED on a person. Replaced with four machine-checkable "
                "comprehensibility legs (entry_point_integrity, completeness, freshness, "
                "executability); GREEN iff all four pass."
            ),
            "supersedes": "the two-leg [S]+[A] shape (ind5-s-checkable / ind5-a-attested receipts)",
        },
        "attestation_superseded_by": {
            "note": (
                "the OLD [A] operator-attestation object (and the OLD [S] organism_component_docs "
                "shape) is retained here for audit continuity only; NEITHER is evaluated by this "
                "new leg and NEITHER counts toward GREEN. The script-authored-invalid trap for "
                "the OLD [A] field (invalid_comprehension_by_script) stays enforced by "
                "test_c_ind.py so a legacy claim cannot be faked retroactively."
            ),
            "old_receipts_found": _find_old_attestation_receipts(root),
        },
        "exec_root": str(exec_root),
        "registry_dump_ok": dump.get("ok", False),
        "registry_dump_error": dump.get("error") if not dump.get("ok") else None,
        "legs": legs,
        "all_four_legs_passed": all_passed,
        "ts": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="issue #88 IND-5 comprehend_v2 producer")
    ap.add_argument("--root", default=str(REPO_ROOT_DEFAULT))
    ap.add_argument("--exec-root", default=str(EXEC_ROOT_DEFAULT))
    args = ap.parse_args()
    root = Path(args.root).resolve()
    exec_root = Path(args.exec_root).resolve()

    # gh #625 point 1, fail-closed: verify BEFORE the receipt is written,
    # against the CONTRACT tree (root) -- the tree the receipt is written
    # into, which may differ from this script's own location via --root.
    _verify_invariant(str(root))

    receipt = build_ind5_receipt(root, exec_root)
    _stamp_invariant(receipt, repo_root=str(root))
    receipt["sha_convention"] = INVARIANT_SHA_CONVENTION
    out_dir = root / "receipts" / "ember-operator-independence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ind5-comprehend-v2-{receipt['ts']}.json"
    out_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    verdict = "PASS" if receipt["all_four_legs_passed"] else "FAIL"
    print(f"{verdict} wrote {out_path}")
    for name, leg in receipt["legs"].items():
        print(f"  leg={name} passed={leg.get('passed')} reason={leg.get('reason')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

