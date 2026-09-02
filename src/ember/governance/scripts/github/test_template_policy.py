# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest
from pathlib import Path

from src.ember.governance.scripts.github import template_policy
# issue2015 exact-local-import:src/ember/governance/scripts/check_pr_authority_binding.py
import importlib.util as _ember_fab48fcd56c3e48d_importlib
import sys as _ember_fab48fcd56c3e48d_sys
from pathlib import Path as _ember_fab48fcd56c3e48d_Path
_ember_fab48fcd56c3e48d_path = _ember_fab48fcd56c3e48d_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'governance', 'scripts', 'check_pr_authority_binding.py')
if not _ember_fab48fcd56c3e48d_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/check_pr_authority_binding.py')
_ember_fab48fcd56c3e48d_aliases = ('_ember_issue2015_fab48fcd56c3e48d', 'check_pr_authority_binding', 'scripts.check_pr_authority_binding', 'src.ember.governance.scripts.check_pr_authority_binding')
_ember_fab48fcd56c3e48d_existing = []
for _ember_fab48fcd56c3e48d_alias in _ember_fab48fcd56c3e48d_aliases:
    _ember_fab48fcd56c3e48d_candidate = _ember_fab48fcd56c3e48d_sys.modules.get(_ember_fab48fcd56c3e48d_alias)
    if _ember_fab48fcd56c3e48d_candidate is not None and all(_ember_fab48fcd56c3e48d_candidate is not item for item in _ember_fab48fcd56c3e48d_existing):
        _ember_fab48fcd56c3e48d_existing.append(_ember_fab48fcd56c3e48d_candidate)
if len(_ember_fab48fcd56c3e48d_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/check_pr_authority_binding.py')
if _ember_fab48fcd56c3e48d_existing:
    _ember_fab48fcd56c3e48d_module = _ember_fab48fcd56c3e48d_existing[0]
    _ember_fab48fcd56c3e48d_observed = getattr(_ember_fab48fcd56c3e48d_module, '__file__', None)
    if _ember_fab48fcd56c3e48d_observed is None or _ember_fab48fcd56c3e48d_Path(_ember_fab48fcd56c3e48d_observed).resolve() != _ember_fab48fcd56c3e48d_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/check_pr_authority_binding.py')
else:
    _ember_fab48fcd56c3e48d_spec = _ember_fab48fcd56c3e48d_importlib.spec_from_file_location('_ember_issue2015_fab48fcd56c3e48d', _ember_fab48fcd56c3e48d_path)
    if _ember_fab48fcd56c3e48d_spec is None or _ember_fab48fcd56c3e48d_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/check_pr_authority_binding.py')
    _ember_fab48fcd56c3e48d_module = _ember_fab48fcd56c3e48d_importlib.module_from_spec(_ember_fab48fcd56c3e48d_spec)
    for _ember_fab48fcd56c3e48d_alias in _ember_fab48fcd56c3e48d_aliases:
        _ember_fab48fcd56c3e48d_prior = _ember_fab48fcd56c3e48d_sys.modules.get(_ember_fab48fcd56c3e48d_alias)
        if _ember_fab48fcd56c3e48d_prior is not None and _ember_fab48fcd56c3e48d_prior is not _ember_fab48fcd56c3e48d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/check_pr_authority_binding.py')
        _ember_fab48fcd56c3e48d_sys.modules[_ember_fab48fcd56c3e48d_alias] = _ember_fab48fcd56c3e48d_module
    try:
        _ember_fab48fcd56c3e48d_spec.loader.exec_module(_ember_fab48fcd56c3e48d_module)
    except BaseException:
        for _ember_fab48fcd56c3e48d_alias in _ember_fab48fcd56c3e48d_aliases:
            if _ember_fab48fcd56c3e48d_sys.modules.get(_ember_fab48fcd56c3e48d_alias) is _ember_fab48fcd56c3e48d_module:
                _ember_fab48fcd56c3e48d_sys.modules.pop(_ember_fab48fcd56c3e48d_alias, None)
        raise
for _ember_fab48fcd56c3e48d_alias in _ember_fab48fcd56c3e48d_aliases:
    _ember_fab48fcd56c3e48d_prior = _ember_fab48fcd56c3e48d_sys.modules.get(_ember_fab48fcd56c3e48d_alias)
    if _ember_fab48fcd56c3e48d_prior is not None and _ember_fab48fcd56c3e48d_prior is not _ember_fab48fcd56c3e48d_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/check_pr_authority_binding.py')
    _ember_fab48fcd56c3e48d_sys.modules[_ember_fab48fcd56c3e48d_alias] = _ember_fab48fcd56c3e48d_module
load_goal_binding = getattr(_ember_fab48fcd56c3e48d_module, 'load_goal_binding')
validate_pr_body = getattr(_ember_fab48fcd56c3e48d_module, 'validate_pr_body')
# issue2015 exact-local-import-end:src/ember/governance/scripts/check_pr_authority_binding.py


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())


class TemplatePolicyTests(unittest.TestCase):
    def test_repository_templates_are_complete_and_parse(self) -> None:
        result = template_policy.validate(ROOT)
        self.assertEqual([], result["errors"])
        self.assertEqual(10, result["issue_form_count"])
        self.assertEqual(10, result["pr_template_count"])

    def test_every_pr_template_passes_literal_authority_validator(self) -> None:
        goal, outcome, workstreams = load_goal_binding(ROOT)
        paths = sorted((ROOT / ".github" / "PULL_REQUEST_TEMPLATE").glob("*.md"))
        paths.append(ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md")
        self.assertEqual(11, len(paths))
        for path in paths:
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file())
                self.assertEqual(
                    [],
                    validate_pr_body(
                        path.read_text(encoding="utf-8"),
                        goal,
                        outcome,
                        workstreams,
                    ),
                )

    def test_defect_form_preserves_truthful_uncertainty(self) -> None:
        form = template_policy._strict_yaml(
            ROOT / ".github" / "ISSUE_TEMPLATE" / "01-defect.yml"
        )
        required_by_id = {
            row["id"]: row.get("validations", {}).get("required")
            for row in form["body"]
            if isinstance(row, dict) and "id" in row
        }
        for field in (
            "observed_behavior",
            "expected_behavior",
            "exact_reproduction",
            "environment",
            "commit_or_build_identity",
            "impact",
        ):
            self.assertIs(True, required_by_id[field])
        for field in (
            "first_known_failing_version",
            "last_known_working_version",
            "workaround",
            "required_regression_proof",
        ):
            self.assertIsNot(True, required_by_id[field])


if __name__ == "__main__":
    unittest.main()
