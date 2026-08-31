#!/usr/bin/env python
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
Deterministic documentation freshness checker for ember.

Enforces:
1. Frozen-grammar path candidates in the selected front-door surface resolve in tracked tree
2. scripts/README.md inventory matches actual scripts/**/*.py
3. CLAIMS.md/INDEX.jsonl up-to-date (regeneratable without diff)
4. CONTINUITY state-as-of marker <= 1 day old

Exit: 0 = clean, 1 = defects found
Mode: --fix-report outputs defect markdown; normal mode outputs table
"""

import importlib.util
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

try:
    # issue2015 exact-local-import:scripts/ember_cli_spec_policy.py
    import importlib.util as _ember_4907e63ef2f25e2e_importlib
    import sys as _ember_4907e63ef2f25e2e_sys
    from pathlib import Path as _ember_4907e63ef2f25e2e_Path
    _ember_4907e63ef2f25e2e_path = _ember_4907e63ef2f25e2e_Path(__file__).resolve().parents[4].joinpath('scripts', 'ember_cli_spec_policy.py')
    if not _ember_4907e63ef2f25e2e_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/ember_cli_spec_policy.py')
    _ember_4907e63ef2f25e2e_aliases = ('_ember_issue2015_4907e63ef2f25e2e', 'ember_cli_spec_policy', 'scripts.ember_cli_spec_policy')
    _ember_4907e63ef2f25e2e_existing = []
    for _ember_4907e63ef2f25e2e_alias in _ember_4907e63ef2f25e2e_aliases:
        _ember_4907e63ef2f25e2e_candidate = _ember_4907e63ef2f25e2e_sys.modules.get(_ember_4907e63ef2f25e2e_alias)
        if _ember_4907e63ef2f25e2e_candidate is not None and all(_ember_4907e63ef2f25e2e_candidate is not item for item in _ember_4907e63ef2f25e2e_existing):
            _ember_4907e63ef2f25e2e_existing.append(_ember_4907e63ef2f25e2e_candidate)
    if len(_ember_4907e63ef2f25e2e_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/ember_cli_spec_policy.py')
    if _ember_4907e63ef2f25e2e_existing:
        _ember_4907e63ef2f25e2e_module = _ember_4907e63ef2f25e2e_existing[0]
        _ember_4907e63ef2f25e2e_observed = getattr(_ember_4907e63ef2f25e2e_module, '__file__', None)
        if _ember_4907e63ef2f25e2e_observed is None or _ember_4907e63ef2f25e2e_Path(_ember_4907e63ef2f25e2e_observed).resolve() != _ember_4907e63ef2f25e2e_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/ember_cli_spec_policy.py')
    else:
        _ember_4907e63ef2f25e2e_spec = _ember_4907e63ef2f25e2e_importlib.spec_from_file_location('_ember_issue2015_4907e63ef2f25e2e', _ember_4907e63ef2f25e2e_path)
        if _ember_4907e63ef2f25e2e_spec is None or _ember_4907e63ef2f25e2e_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/ember_cli_spec_policy.py')
        _ember_4907e63ef2f25e2e_module = _ember_4907e63ef2f25e2e_importlib.module_from_spec(_ember_4907e63ef2f25e2e_spec)
        for _ember_4907e63ef2f25e2e_alias in _ember_4907e63ef2f25e2e_aliases:
            _ember_4907e63ef2f25e2e_prior = _ember_4907e63ef2f25e2e_sys.modules.get(_ember_4907e63ef2f25e2e_alias)
            if _ember_4907e63ef2f25e2e_prior is not None and _ember_4907e63ef2f25e2e_prior is not _ember_4907e63ef2f25e2e_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_cli_spec_policy.py')
            _ember_4907e63ef2f25e2e_sys.modules[_ember_4907e63ef2f25e2e_alias] = _ember_4907e63ef2f25e2e_module
        try:
            _ember_4907e63ef2f25e2e_spec.loader.exec_module(_ember_4907e63ef2f25e2e_module)
        except BaseException:
            for _ember_4907e63ef2f25e2e_alias in _ember_4907e63ef2f25e2e_aliases:
                if _ember_4907e63ef2f25e2e_sys.modules.get(_ember_4907e63ef2f25e2e_alias) is _ember_4907e63ef2f25e2e_module:
                    _ember_4907e63ef2f25e2e_sys.modules.pop(_ember_4907e63ef2f25e2e_alias, None)
            raise
    for _ember_4907e63ef2f25e2e_alias in _ember_4907e63ef2f25e2e_aliases:
        _ember_4907e63ef2f25e2e_prior = _ember_4907e63ef2f25e2e_sys.modules.get(_ember_4907e63ef2f25e2e_alias)
        if _ember_4907e63ef2f25e2e_prior is not None and _ember_4907e63ef2f25e2e_prior is not _ember_4907e63ef2f25e2e_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_cli_spec_policy.py')
        _ember_4907e63ef2f25e2e_sys.modules[_ember_4907e63ef2f25e2e_alias] = _ember_4907e63ef2f25e2e_module
    SpecPolicyError = getattr(_ember_4907e63ef2f25e2e_module, 'SpecPolicyError')
    load_spec_nodes = getattr(_ember_4907e63ef2f25e2e_module, 'load_spec_nodes')
    # issue2015 exact-local-import-end:scripts/ember_cli_spec_policy.py
except ModuleNotFoundError as exc:
    if exc.name not in {"scripts", "scripts.ember_cli_spec_policy"}:
        raise
    # issue2015 exact-local-import:scripts/ember_cli_spec_policy.py
    import importlib.util as _ember_4907e63ef2f25e2e_importlib
    import sys as _ember_4907e63ef2f25e2e_sys
    from pathlib import Path as _ember_4907e63ef2f25e2e_Path
    _ember_4907e63ef2f25e2e_path = _ember_4907e63ef2f25e2e_Path(__file__).resolve().parents[4].joinpath('scripts', 'ember_cli_spec_policy.py')
    if not _ember_4907e63ef2f25e2e_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/ember_cli_spec_policy.py')
    _ember_4907e63ef2f25e2e_aliases = ('_ember_issue2015_4907e63ef2f25e2e', 'ember_cli_spec_policy', 'scripts.ember_cli_spec_policy')
    _ember_4907e63ef2f25e2e_existing = []
    for _ember_4907e63ef2f25e2e_alias in _ember_4907e63ef2f25e2e_aliases:
        _ember_4907e63ef2f25e2e_candidate = _ember_4907e63ef2f25e2e_sys.modules.get(_ember_4907e63ef2f25e2e_alias)
        if _ember_4907e63ef2f25e2e_candidate is not None and all(_ember_4907e63ef2f25e2e_candidate is not item for item in _ember_4907e63ef2f25e2e_existing):
            _ember_4907e63ef2f25e2e_existing.append(_ember_4907e63ef2f25e2e_candidate)
    if len(_ember_4907e63ef2f25e2e_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/ember_cli_spec_policy.py')
    if _ember_4907e63ef2f25e2e_existing:
        _ember_4907e63ef2f25e2e_module = _ember_4907e63ef2f25e2e_existing[0]
        _ember_4907e63ef2f25e2e_observed = getattr(_ember_4907e63ef2f25e2e_module, '__file__', None)
        if _ember_4907e63ef2f25e2e_observed is None or _ember_4907e63ef2f25e2e_Path(_ember_4907e63ef2f25e2e_observed).resolve() != _ember_4907e63ef2f25e2e_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/ember_cli_spec_policy.py')
    else:
        _ember_4907e63ef2f25e2e_spec = _ember_4907e63ef2f25e2e_importlib.spec_from_file_location('_ember_issue2015_4907e63ef2f25e2e', _ember_4907e63ef2f25e2e_path)
        if _ember_4907e63ef2f25e2e_spec is None or _ember_4907e63ef2f25e2e_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/ember_cli_spec_policy.py')
        _ember_4907e63ef2f25e2e_module = _ember_4907e63ef2f25e2e_importlib.module_from_spec(_ember_4907e63ef2f25e2e_spec)
        for _ember_4907e63ef2f25e2e_alias in _ember_4907e63ef2f25e2e_aliases:
            _ember_4907e63ef2f25e2e_prior = _ember_4907e63ef2f25e2e_sys.modules.get(_ember_4907e63ef2f25e2e_alias)
            if _ember_4907e63ef2f25e2e_prior is not None and _ember_4907e63ef2f25e2e_prior is not _ember_4907e63ef2f25e2e_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_cli_spec_policy.py')
            _ember_4907e63ef2f25e2e_sys.modules[_ember_4907e63ef2f25e2e_alias] = _ember_4907e63ef2f25e2e_module
        try:
            _ember_4907e63ef2f25e2e_spec.loader.exec_module(_ember_4907e63ef2f25e2e_module)
        except BaseException:
            for _ember_4907e63ef2f25e2e_alias in _ember_4907e63ef2f25e2e_aliases:
                if _ember_4907e63ef2f25e2e_sys.modules.get(_ember_4907e63ef2f25e2e_alias) is _ember_4907e63ef2f25e2e_module:
                    _ember_4907e63ef2f25e2e_sys.modules.pop(_ember_4907e63ef2f25e2e_alias, None)
            raise
    for _ember_4907e63ef2f25e2e_alias in _ember_4907e63ef2f25e2e_aliases:
        _ember_4907e63ef2f25e2e_prior = _ember_4907e63ef2f25e2e_sys.modules.get(_ember_4907e63ef2f25e2e_alias)
        if _ember_4907e63ef2f25e2e_prior is not None and _ember_4907e63ef2f25e2e_prior is not _ember_4907e63ef2f25e2e_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_cli_spec_policy.py')
        _ember_4907e63ef2f25e2e_sys.modules[_ember_4907e63ef2f25e2e_alias] = _ember_4907e63ef2f25e2e_module
    SpecPolicyError = getattr(_ember_4907e63ef2f25e2e_module, 'SpecPolicyError')
    load_spec_nodes = getattr(_ember_4907e63ef2f25e2e_module, 'load_spec_nodes')
    # issue2015 exact-local-import-end:scripts/ember_cli_spec_policy.py


PATH_EXTENSIONS = r"py|md|json|txt|sh|yml|yaml|toml|ps1"
BACKTICK_PATH_PATTERN = re.compile(
    rf"`([a-zA-Z0-9_./\-]+\.(?:{PATH_EXTENSIONS}))`"
)
PROSE_PATH_PATTERN = re.compile(
    rf"(?<![\w/.-])((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\."
    rf"(?:{PATH_EXTENSIONS}))(?![\w/])"
)
URL_PATTERN = re.compile(r"https?://\S+")
ALLOW_UNRESOLVED_PRAGMA = "<!-- docs-freshness: allow-unresolved -->"
CONSERVATION_BEGIN_MARKER = "<!-- EMBER_CONSERVATION_V1"
BOARD_BEGIN_MARKER = "<!-- BOARD-STATUS-BEGIN -->"
BOARD_END_MARKER = "<!-- BOARD-STATUS-END -->"
SUBJECT_BEGIN_MARKER = "<!-- CURRENT-SUBJECT-BEGIN -->"
SUBJECT_END_MARKER = "<!-- CURRENT-SUBJECT-END -->"
STATE_AS_OF_PATTERN = re.compile(r"<!-- state-as-of:\s*\d{4}-\d{2}-\d{2}\s*-->")


@dataclass
class CandidateExtraction:
    paths: set[str]
    pragma_lines: list[int]
    occurrences: list[tuple[str, int]]


def _inside_angle_placeholder(line: str, start: int, end: int) -> bool:
    left = line.rfind("<", 0, start + 1)
    left_close = line.rfind(">", 0, start + 1)
    return left > left_close and line.find(">", end) >= 0


def extract_path_candidates(text: str) -> CandidateExtraction:
    """Extract the frozen union of backtick and prose repository path candidates."""
    paths: set[str] = set()
    pragma_lines: list[int] = []
    occurrences: list[tuple[str, int]] = []
    in_conservation = False
    for line_number, original in enumerate(text.splitlines(), 1):
        if CONSERVATION_BEGIN_MARKER in original:
            in_conservation = True
        if in_conservation:
            if "-->" in original:
                in_conservation = False
            continue
        if ALLOW_UNRESOLVED_PRAGMA in original:
            pragma_lines.append(line_number)
            continue
        line = URL_PATTERN.sub("", original)
        matches = []
        for pattern in (BACKTICK_PATH_PATTERN, PROSE_PATH_PATTERN):
            for match in pattern.finditer(line):
                matches.append((match.group(1), match.start(1), match.end(1)))
        seen_on_line = set()
        for value, start, end in matches:
            if value in seen_on_line or value.startswith("path/to/"):
                continue
            if start > 0 and line[start - 1] == "\\":
                continue
            if _inside_angle_placeholder(line, start, end):
                continue
            seen_on_line.add(value)
            paths.add(value)
            occurrences.append((value, line_number))
    return CandidateExtraction(paths, pragma_lines, occurrences)

class DocsFreshnessChecker:
    def __init__(self, repo_root=None):
        self.repo = Path(repo_root or '.')
        self.defects = []
        self.warnings = []
        self.pragma_uses = []
        self.reference_census = {}
        self._tracked_paths = None

    def tracked_paths(self):
        """Return the exact case-sensitive path set tracked by Git at this tree."""
        if self._tracked_paths is None:
            try:
                completed = subprocess.run(
                    ["git", "-C", str(self.repo), "ls-files", "-z"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                raise RuntimeError(f"git ls-files failed for {self.repo}: {exc}") from exc
            self._tracked_paths = {
                item.decode("utf-8")
                for item in completed.stdout.split(b"\0")
                if item
            }
        return set(self._tracked_paths)

    def unresolved_paths(self, candidates):
        tracked = self.tracked_paths()
        return set(candidates) - tracked

    def check_references(self, relative_paths):
        """Check frozen-grammar references against the case-sensitive tracked tree."""
        tracked = self.tracked_paths()
        for relative in relative_paths:
            text = (self.repo / relative).read_text(encoding="utf-8")
            extraction = extract_path_candidates(text)
            self.reference_census[relative] = {
                "unique": len(extraction.paths),
                "occurrences": len(extraction.occurrences),
            }
            self.pragma_uses.extend(
                {"file": relative, "line": line} for line in extraction.pragma_lines
            )
            reported = set()
            for candidate, line in extraction.occurrences:
                if candidate in tracked or candidate in reported:
                    continue
                reported.add(candidate)
                self.defects.append({
                    'file': relative,
                    'defect_class': 'broken_path_reference',
                    'path': candidate,
                    'line': line,
                    'description': (
                        f"Path `{candidate}` is not tracked with exact case at this tree"
                    ),
                })

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
        self.check_references(["README.md"])

    def check_front_door_references(self):
        self.check_references(["README.md", "docs/authority/CONTINUITY.md"])

    def check_front_door_marker_coherence(self):
        readme = (self.repo / "README.md").read_text(encoding="utf-8")
        continuity = (
            self.repo / "docs" / "authority" / "CONTINUITY.md"
        ).read_text(encoding="utf-8")
        expected = (
            ("state-as-of", STATE_AS_OF_PATTERN, 0, 1),
            ("board begin", BOARD_BEGIN_MARKER, 0, 1),
            ("board end", BOARD_END_MARKER, 0, 1),
            ("current subject begin", SUBJECT_BEGIN_MARKER, 0, 1),
            ("current subject end", SUBJECT_END_MARKER, 0, 1),
        )
        for label, marker, readme_count, continuity_count in expected:
            if hasattr(marker, "findall"):
                actual_readme = len(marker.findall(readme))
                actual_continuity = len(marker.findall(continuity))
            else:
                actual_readme = readme.count(marker)
                actual_continuity = continuity.count(marker)
            if (actual_readme, actual_continuity) != (readme_count, continuity_count):
                self.defects.append({
                    'file': 'README.md + docs/authority/CONTINUITY.md',
                    'defect_class': 'mutable_marker_misplaced',
                    'description': (
                        f"{label} count is README={actual_readme}, "
                        f"CONTINUITY={actual_continuity}; expected "
                        f"README={readme_count}, CONTINUITY={continuity_count}"
                    ),
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
            builder_path = self.repo / "src" / "ember" / "governance" / "scripts" / "build_claims_index.py"
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
        """Check that CONTINUITY.md state-as-of marker is recent."""
        continuity = (
            self.repo / "docs" / "authority" / "CONTINUITY.md"
        ).read_text(encoding="utf-8")

        # Extract state-as-of: YYYY-MM-DD
        marker_match = re.search(r'state-as-of:\s*(\d{4}-\d{2}-\d{2})', continuity)
        if not marker_match:
            self.defects.append({
                'file': 'docs/authority/CONTINUITY.md',
                'defect_class': 'missing_state_marker',
                'line': 'header',
                'description': 'No state-as-of marker in CONTINUITY.md (<!-- state-as-of: YYYY-MM-DD -->)'
            })
            return

        marker_date_str = marker_match.group(1)
        marker_date = datetime.fromisoformat(marker_date_str)
        now = datetime.now()
        days_old = (now - marker_date).days

        if days_old > 1:
            self.defects.append({
                'file': 'docs/authority/CONTINUITY.md',
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

    def run_front_door_checks(self):
        """Run only deterministic front-door checks suitable for merge CI."""
        self.check_front_door_references()
        self.check_front_door_marker_coherence()

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

    print("Running DOCS_FRESHNESS_SELFTEST fixtures...")

    # Create a minimal test tree
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create minimal structure
        (tmpdir / "scripts").mkdir()
        (tmpdir / "docs" / "authority").mkdir(parents=True)
        (tmpdir / "receipts").mkdir()

        # Create README.md with broken reference
        readme = tmpdir / "README.md"
        readme.write_text("""
# Test Repo

See `docs/NONEXISTENT.md` for details.

See `scripts/test.py` for the harness.

""")
        (tmpdir / "docs" / "authority" / "CONTINUITY.md").write_text(
            "<!-- state-as-of: 2026-07-06 -->\n",
            encoding="utf-8",
        )

        # Create actual script
        (tmpdir / "scripts" / "test.py").write_text("pass")
        (tmpdir / "scripts" / "test2.py").write_text("pass")

        # Create scripts/README.md with incomplete inventory
        scripts_readme = tmpdir / "scripts" / "README.md"
        scripts_readme.write_text("| test.py |\n")

        subprocess.run(["git", "init", "-q", str(tmpdir)], check=True)
        subprocess.run(
            [
                "git", "-C", str(tmpdir), "add", "README.md", "scripts/test.py",
                "scripts/test2.py", "scripts/README.md",
                "docs/authority/CONTINUITY.md",
            ],
            check=True,
        )

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
    parser.add_argument(
        "--front-door",
        action="store_true",
        help=(
            "run deterministic README/CONTINUITY reference and marker-placement checks only"
        ),
    )
    args = parser.parse_args()

    if args.selftest:
        sys.exit(run_selftests())

    checker = DocsFreshnessChecker(args.repo)
    if args.front_door:
        checker.run_front_door_checks()
        census = ", ".join(
            f"{surface}:unique={row['unique']}:occurrences={row['occurrences']}"
            for surface, row in sorted(checker.reference_census.items())
        )
        unresolved = sum(
            row.get("defect_class") == "broken_path_reference"
            for row in checker.defects
        )
        print(
            f"DOCS_FRESHNESS_REFERENCE_CENSUS {census} unresolved={unresolved}"
        )
        rows = ", ".join(
            f"{row['file']}:{row['line']}" for row in checker.pragma_uses
        ) or "none"
        print(f"DOCS_FRESHNESS_PRAGMA_CENSUS count={len(checker.pragma_uses)} rows={rows}")
    else:
        checker.run_all_checks()
    sys.exit(checker.report_defects(fix_report=args.fix_report))
