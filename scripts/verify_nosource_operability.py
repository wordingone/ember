# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#!/usr/bin/env python3
"""Executable acceptance harness for the no-source operability gate.

The pre-training gate requires the spine to be operable through ember-cli by
a person who has read no source file: every control a visible affordance, a
mouse click or a single keystroke -- no flags, no script paths, no knowledge
of which file to invoke. Until now that bar was judged per-capture by a
human. This harness MEASURES the statically-measurable half and names the
half it cannot measure.

DESIGN RULE - HONESTY OVER GREEN (same rule as verify_ember01_completion.py).
Every check carries one of:

    resolved-true    measured and holds
    resolved-false   measured and fails
    undecidable      cannot be decided statically; the receipt names exactly
                     what a human must look at

Overall verdict is FAIL unless every gating check is resolved-true. An
undecidable check never silently passes; it is reported and excluded from
the PASS claim, which is therefore explicitly partial.

WHAT IS MEASURED
  L1  Root launcher exists: a double-clickable / single-command artifact at
      the repository ROOT (.cmd/.bat/.ps1/.exe/.sh or extensionless
      executable). A `bin` entry pointing at a .ts inside tools/ does NOT
      count: reaching it requires knowing a path and having bun -- that is
      source knowledge.
  L2  Launcher is documented: README.md or docs/START-HERE.md names the
      launcher file, so a no-source reader can find it.
  L3  Spine-function surface: each gate-named function (custody+identity,
      data/tokenizer lineage, checkpoint save/load, owned serving,
      benchmarking, 3B training launch) is exposed as a NAMED command with a
      DESCRIPTION inside ember-cli's command registry. A function with no
      named command is unreachable without source knowledge.

FAIL-CLOSED: a missing file, unreadable directory, unparseable package.json,
or an empty command registry is resolved-false, never a silent pass.

WHAT IS NOT MEASURED (permanently undecidable here, human capture required):
  - whether the command actually appears as a visible affordance in the
    running UI (menu/palette rendering);
  - whether operating it takes one click/keystroke rather than typed flags;
  - whether the launched process reaches a usable first pixel.

Usage:  python scripts/verify_nosource_operability.py [--root PATH] [--json]
Exit 0 = PASS (of the measurable half), 1 = FAIL, 2 = harness error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LAUNCHER_SUFFIXES = {".cmd", ".bat", ".ps1", ".exe", ".sh"}
LAUNCHER_NAME_HINT = re.compile(r"^(ember|launch|start|run)", re.IGNORECASE)
DOC_FILES = ("README.md", "docs/START-HERE.md")
COMMANDS_DIR = "tools/ember-cli/src/commands"
PACKAGE_JSON = "tools/ember-cli/src/package.json"

# Gate-named spine functions -> keywords that must appear in a NAMED command
# module (module name or file body). Keywords are lowercase substrings.
SPINE_FUNCTIONS = {
    "custody_and_identity_manifest": ["custody", "identity"],
    "data_tokenizer_lineage": ["tokenizer", "lineage"],
    "checkpoint_save_load": ["checkpoint"],
    "owned_serving_path": ["owned", "serve", "seat"],
    "benchmarking": ["benchmark"],
    "training_launch_3b": ["train"],
}

NAME_RE = re.compile(r'name:\s*"([a-z0-9-]+)"')
DESC_RE = re.compile(r"description:")


def check(state: str, evidence: str) -> dict:
    return {"state": state, "evidence": evidence}


def find_root_launchers(root: Path) -> list[str]:
    found = []
    try:
        entries = sorted(p for p in root.iterdir() if p.is_file())
    except OSError as exc:
        raise RuntimeError(f"repo root unreadable: {exc}") from exc
    for p in entries:
        if p.suffix.lower() in LAUNCHER_SUFFIXES:
            found.append(p.name)
        elif p.suffix == "" and LAUNCHER_NAME_HINT.match(p.name):
            found.append(p.name)
    return found


def load_commands(root: Path) -> tuple[dict[str, dict], list[str]]:
    """Return {module_stem: {names:[], has_description:bool, body:str}}, errors."""
    errors: list[str] = []
    cmd_dir = root / COMMANDS_DIR
    if not cmd_dir.is_dir():
        errors.append(f"command registry missing: {COMMANDS_DIR}")
        return {}, errors
    modules: dict[str, dict] = {}
    for f in sorted(cmd_dir.glob("*.ts")):
        if f.name.endswith(".test.ts"):
            continue
        try:
            body = f.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            errors.append(f"unreadable command module {f.name}: {exc}")
            continue
        names = NAME_RE.findall(body)
        modules[f.stem] = {
            "names": names,
            "has_description": bool(DESC_RE.search(body)),
            "body_lower": body.lower(),
        }
    if not modules:
        errors.append(f"command registry empty: {COMMANDS_DIR}")
    return modules, errors


def run(root: Path) -> dict:
    report: dict = {"root": str(root), "checks": {}, "spine": {}, "undecidable": []}
    checks = report["checks"]

    # L1 root launcher -----------------------------------------------------
    launchers = find_root_launchers(root)
    if launchers:
        checks["L1_root_launcher"] = check(
            "resolved-true", f"root launcher artifact(s): {launchers}"
        )
    else:
        checks["L1_root_launcher"] = check(
            "resolved-false",
            "no .cmd/.bat/.ps1/.exe/.sh or executable-named file at repo root; "
            "launching requires a source path (package.json bin -> ./entrypoints/"
            "main.ts needs bun + path knowledge, which is source knowledge)",
        )

    # package.json fail-closed parse (evidence for the L1 verdict) --------
    pkg_path = root / PACKAGE_JSON
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        bin_entry = pkg.get("bin")
        if not isinstance(bin_entry, dict) or not bin_entry:
            checks["L1b_package_bin"] = check(
                "resolved-false", f"{PACKAGE_JSON}: bin entry missing/empty"
            )
        else:
            checks["L1b_package_bin"] = check(
                "resolved-true", f"bin = {bin_entry} (informational; a .ts bin "
                "target is NOT a no-source launcher)"
            )
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        checks["L1b_package_bin"] = check(
            "resolved-false", f"{PACKAGE_JSON} missing/unparseable: {exc}"
        )

    # L2 launcher documented ----------------------------------------------
    if launchers:
        doc_hits = []
        for rel in DOC_FILES:
            fp = root / rel
            try:
                text = fp.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeError):
                continue
            for launcher in launchers:
                if launcher in text:
                    doc_hits.append(f"{rel} mentions {launcher}")
        if doc_hits:
            checks["L2_launcher_documented"] = check("resolved-true", "; ".join(doc_hits))
        else:
            checks["L2_launcher_documented"] = check(
                "resolved-false",
                f"launcher(s) {launchers} named in neither "
                + " nor ".join(DOC_FILES)
                + " -- an undocumented launcher is undiscoverable",
            )
    else:
        checks["L2_launcher_documented"] = check(
            "resolved-false", "no launcher to document (see L1)"
        )

    # L3 spine-function command surface -----------------------------------
    modules, cmd_errors = load_commands(root)
    for err in cmd_errors:
        checks.setdefault("L3_registry_errors", check("resolved-false", err))
    launch_ok = checks["L1_root_launcher"]["state"] == "resolved-true"
    for func, keywords in SPINE_FUNCTIONS.items():
        hit = None
        # Pass 1: keyword in the command NAME or module stem (strong match).
        # Pass 2: keyword only in the module body (weak match, flagged).
        for strong in (True, False):
            for stem, m in modules.items():
                if not m["names"] or not m["has_description"]:
                    continue
                hay = stem.lower() + " " + " ".join(m["names"])
                if strong and any(k in hay for k in keywords):
                    hit = f"command {m['names']} in {stem}.ts (named + described)"
                    break
                if not strong and any(k in m["body_lower"] for k in keywords):
                    hit = (
                        f"command {m['names']} in {stem}.ts (named + described; "
                        f"WEAK match: keyword only in module body)"
                    )
                    break
            if hit:
                break
        if hit is None:
            report["spine"][func] = check(
                "resolved-false",
                f"no named+described command module matches {keywords}",
            )
        elif not launch_ok:
            report["spine"][func] = check(
                "resolved-false",
                f"{hit} -- exists in the body, but the body itself is "
                "unreachable without source knowledge (L1 failed), so a "
                "no-source operator cannot reach it",
            )
        else:
            report["spine"][func] = check("resolved-true", hit)

    # Permanently undecidable half ----------------------------------------
    report["undecidable"] = [
        "UI affordance visibility: does each command render as a visible "
        "menu/palette item in the running cockpit? (human capture required)",
        "Interaction cost: is each control one click / one keystroke, with "
        "no typed flags? (human capture required)",
        "Launch experience: does the launcher reach a usable first pixel "
        "without prompts for paths/flags? (human capture required)",
    ]

    gating = list(checks.values()) + list(report["spine"].values())
    report["verdict"] = (
        "PASS (measurable half only; undecidable items remain human-judged)"
        if all(c["state"] == "resolved-true" for c in gating)
        else "FAIL"
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--json", action="store_true", help="emit machine JSON only")
    args = ap.parse_args()
    root = Path(args.root)
    if not root.is_dir():
        print(f"FAIL: root not a directory: {root}", file=sys.stderr)
        return 1
    try:
        report = run(root)
    except RuntimeError as exc:
        print(f"FAIL (fail-closed): {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"no-source operability verdict: {report['verdict']}")
        for k, c in report["checks"].items():
            print(f"  [{c['state']:>14}] {k}: {c['evidence']}")
        print("  spine functions:")
        for k, c in report["spine"].items():
            print(f"  [{c['state']:>14}] {k}: {c['evidence']}")
        print("  undecidable (human capture required):")
        for u in report["undecidable"]:
            print(f"    - {u}")
    return 0 if report["verdict"].startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
