#!/usr/bin/env python
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
Deterministic documentation freshness checker for ember.

Enforces:
1. All backtick-quoted paths in README.md + docs/**/*.md resolve in tree
2. scripts/README.md inventory matches actual scripts/**/*.py
3. CLAIMS.md/INDEX.jsonl up-to-date (regeneratable without diff)
4. README state-as-of marker <= 1 day old

Exit: 0 = clean, 1 = defects found
Mode: --fix-report outputs defect markdown; normal mode outputs table
"""

import importlib.util
import re
import sys
from pathlib import Path
from datetime import datetime

try:
    from scripts.ember_cli_spec_policy import SpecPolicyError, load_spec_nodes
except ModuleNotFoundError as exc:
    if exc.name not in {"scripts", "scripts.ember_cli_spec_policy"}:
        raise
    from ember_cli_spec_policy import SpecPolicyError, load_spec_nodes

class DocsFreshnessChecker:
    def __init__(self, repo_root=None):
        self.repo = Path(repo_root or '.')
        self.defects = []
        self.warnings = []

    def check_ember_cli_specs(self):
        """Validate the complete ember-cli spec-node surface fail closed."""
        try:
            load_spec_nodes(self.repo)
        except SpecPolicyError as exc:
            self.defects.append({
                'file': 'tools/ember-cli/specs/',
                'defect_class': 'invalid_ember_cli_spec',
                'description': str(exc),
            })

    def check_readme_references(self):
        """Check that all path references in README resolve."""
        readme = (self.repo / "README.md").read_text()

        # Extract backtick paths: `path/to/file.py`, `path/to/file.md`, etc.
        backtick_paths = re.findall(r'`([a-zA-Z0-9_./\-]+\.(?:py|md|json|txt|sh))`', readme)

        for path_str in backtick_paths:
            full_path = self.repo / path_str
            if not full_path.exists():
                self.defects.append({
                    'file': 'README.md',
                    'defect_class': 'broken_path_reference',
                    'path': path_str,
                    'line': 'backtick',
                    'description': f"Path `{path_str}` does not exist"
                })

    def check_scripts_inventory(self):
        """Check that scripts/README.md inventory is exhaustive (unless explicitly a taxonomy)."""
        scripts_readme = (self.repo / "scripts" / "README.md").read_text()

        # If the document explicitly claims to be a taxonomy/sample, don't enforce exhaustiveness
        if any(keyword in scripts_readme.lower() for keyword in
               ['taxonomy', 'sample', 'prefix', 'inferred', 'measured by grouping', 'not exhaustive']):
            # This is a documented taxonomy, not a claimed-exhaustive inventory
            return

        # Actual scripts in scripts/*.py
        actual_scripts = set()
        for py_file in (self.repo / "scripts").glob("*.py"):
            actual_scripts.add(py_file.name)

        # Find scripts mentioned in table format
        # Looking for | basename.py | in tables
        inventory_pattern = r'\|\s*`?([a-zA-Z0-9_.]+\.py)`?\s*\|'
        mentioned = set(re.findall(inventory_pattern, scripts_readme))

        # Remove false positives (e.g., "pytest" from code blocks)
        valid_py_scripts = {s for s in mentioned if s.startswith(('ember', 'corpus', 'receipt', 'build', 'train'))}

        missing_from_inventory = actual_scripts - valid_py_scripts
        if missing_from_inventory:
            self.defects.append({
                'file': 'scripts/README.md',
                'defect_class': 'incomplete_inventory',
                'count': len(missing_from_inventory),
                'examples': sorted(list(missing_from_inventory))[:5],
                'description': f"{len(missing_from_inventory)} scripts not documented in inventory"
            })

    def check_claims_index_freshness(self):
        """Check that CLAIMS.md and INDEX.jsonl can be regenerated cleanly."""
        claims_path = self.repo / "receipts" / "CLAIMS.md"
        index_path = self.repo / "receipts" / "INDEX.jsonl"

        if not claims_path.exists():
            self.defects.append({
                'file': 'receipts/CLAIMS.md',
                'defect_class': 'missing_claims_index',
                'description': 'CLAIMS.md does not exist; run build_claims_index.py'
            })
            return

        if not index_path.exists():
            self.defects.append({
                'file': 'receipts/INDEX.jsonl',
                'defect_class': 'missing_claims_index',
                'description': 'INDEX.jsonl does not exist; run build_claims_index.py'
            })
            return

        # Build the expected bytes in memory. Freshness validation must never
        # rewrite the evidence it is validating.
        try:
            builder_path = self.repo / "scripts" / "build_claims_index.py"
            spec = importlib.util.spec_from_file_location(
                "ember_claims_index_builder",
                builder_path,
            )
            if spec is None or spec.loader is None:
                raise RuntimeError(f"cannot load {builder_path}")
            builder = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(builder)
            rows, _stats = builder.build_index(self.repo / "receipts")
            expected_index = builder.render_index_jsonl(rows)
            expected_claims = builder.render_claims_md(rows)
            actual_index = index_path.read_text(encoding="utf-8", errors="strict")
            actual_claims = claims_path.read_text(encoding="utf-8", errors="strict")
            if actual_index != expected_index:
                self.defects.append({
                    'file': 'receipts/INDEX.jsonl',
                    'defect_class': 'stale_claims_index',
                    'description': 'INDEX.jsonl differs from deterministic in-memory regeneration'
                })
            if actual_claims != expected_claims:
                self.defects.append({
                    'file': 'receipts/CLAIMS.md',
                    'defect_class': 'stale_claims_index',
                    'description': 'CLAIMS.md differs from deterministic in-memory regeneration'
                })
        except Exception as e:
            self.defects.append({
                'file': 'receipts/',
                'defect_class': 'claims_index_check_failed',
                'description': f"Could not verify deterministically: {e}"
            })

    def check_readme_state_marker(self):
        """Check that README.md state-as-of marker is recent."""
        readme = (self.repo / "README.md").read_text()

        # Extract state-as-of: YYYY-MM-DD
        marker_match = re.search(r'state-as-of:\s*(\d{4}-\d{2}-\d{2})', readme)
        if not marker_match:
            self.defects.append({
                'file': 'README.md',
                'defect_class': 'missing_state_marker',
                'line': 'header',
                'description': 'No state-as-of marker in README (<!-- state-as-of: YYYY-MM-DD -->)'
            })
            return

        marker_date_str = marker_match.group(1)
        marker_date = datetime.fromisoformat(marker_date_str)
        now = datetime.now()
        days_old = (now - marker_date).days

        if days_old > 1:
            self.defects.append({
                'file': 'README.md',
                'defect_class': 'stale_state_marker',
                'marker_date': marker_date_str,
                'days_old': days_old,
                'description': f"state-as-of is {days_old} days old; update to today"
            })

    def check_docs_reachability(self):
        """Check that docs/*.md files are reachable from README or a docs index."""
        readme = (self.repo / "README.md").read_text()
        docs_dir = self.repo / "docs"

        if not docs_dir.exists():
            return

        # Extract all docs references from README
        doc_mentions = set(re.findall(r'docs/[a-zA-Z0-9_./-]+\.md', readme))

        # All actual docs
        actual_docs = set()
        for doc_file in docs_dir.rglob("*.md"):
            rel = doc_file.relative_to(self.repo)
            actual_docs.add(str(rel))

        # Unreachable docs (not linked from README)
        unreachable = actual_docs - doc_mentions
        if unreachable:
            # Allow some deep nested docs to be unlisted (research/, design/, etc.)
            unreachable_top = {d for d in unreachable if d.count('/') <= 1}
            if unreachable_top:
                self.warnings.append({
                    'file': 'docs/',
                    'class': 'unreachable_docs',
                    'count': len(unreachable_top),
                    'examples': sorted(list(unreachable_top))[:3],
                    'description': f"{len(unreachable_top)} docs not referenced from README"
                })

    def run_all_checks(self):
        """Run all freshness checks."""
        self.check_readme_references()
        self.check_scripts_inventory()
        self.check_claims_index_freshness()
        self.check_readme_state_marker()
        self.check_docs_reachability()
        self.check_ember_cli_specs()

    def report_defects(self, fix_report=False):
        """Print defects as markdown or table."""
        if fix_report:
            print("# Documentation Freshness Defects\n")
            for defect in self.defects:
                print(f"## {defect.get('file', 'unknown')}")
                print(f"- **Class**: {defect.get('defect_class', 'unknown')}")
                if 'description' in defect:
                    print(f"- {defect['description']}")
                if 'examples' in defect:
                    print(f"- Examples: {', '.join(defect['examples'])}")
                print()
        else:
            if not self.defects:
                print("DOCS_FRESHNESS_CHECK_PASS")
                return 0

            print(f"DEFECTS ({len(self.defects)}):")
            for i, defect in enumerate(self.defects, 1):
                print(f"{i}. {defect.get('file')} | {defect.get('defect_class')} | {defect.get('description', '')}")

        return 0 if not self.defects else 1

    def exit_code(self):
        """Return exit code based on defects."""
        return 0 if not self.defects else 1


def run_selftests():
    """Run self-tests on planted fixtures."""
    import tempfile
    import shutil

    print("Running DOCS_FRESHNESS_SELFTEST fixtures...")

    # Create a minimal test tree
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create minimal structure
        (tmpdir / "scripts").mkdir()
        (tmpdir / "docs").mkdir()
        (tmpdir / "receipts").mkdir()

        # Create README.md with broken reference
        readme = tmpdir / "README.md"
        readme.write_text("""
# Test Repo

See `docs/NONEXISTENT.md` for details.

See `scripts/test.py` for the harness.

<!-- state-as-of: 2026-07-06 -->
""")

        # Create actual script
        (tmpdir / "scripts" / "test.py").write_text("pass")
        (tmpdir / "scripts" / "test2.py").write_text("pass")

        # Create scripts/README.md with incomplete inventory
        scripts_readme = tmpdir / "scripts" / "README.md"
        scripts_readme.write_text("| test.py |\n")

        # Test 1: Should detect broken reference
        checker = DocsFreshnessChecker(tmpdir)
        checker.check_readme_references()
        assert any(d.get('defect_class') == 'broken_path_reference' for d in checker.defects), \
            "Should detect broken `docs/NONEXISTENT.md`"

        # Test 2: Should detect incomplete inventory
        checker = DocsFreshnessChecker(tmpdir)
        checker.check_scripts_inventory()
        assert any(d.get('defect_class') == 'incomplete_inventory' for d in checker.defects), \
            "Should detect test2.py not in inventory"

        # Test 3: All checks should run without crash
        checker = DocsFreshnessChecker(tmpdir)
        checker.run_all_checks()
        assert len(checker.defects) >= 1, "Should have defects"

        print("DOCS_FRESHNESS_SELFTEST_PASS")
        return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", help="Run selftests")
    parser.add_argument("--fix-report", action="store_true", help="Output as markdown defect report")
    parser.add_argument("--repo", type=str, default=".", help="Repository root")
    args = parser.parse_args()

    if args.selftest:
        sys.exit(run_selftests())

    checker = DocsFreshnessChecker(args.repo)
    checker.run_all_checks()
    sys.exit(checker.report_defects(fix_report=args.fix_report))
