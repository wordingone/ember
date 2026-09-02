#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Seal one immutable composite PDF authority from a closed JSON spec."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

# issue2015 exact-local-import:src/ember/infrastructure/tools/corpus_connectors/pdf_tree_to_utf8.py
import importlib.util as _ember_9de76725c0e67842_importlib
import sys as _ember_9de76725c0e67842_sys
from pathlib import Path as _ember_9de76725c0e67842_Path
_ember_9de76725c0e67842_path = _ember_9de76725c0e67842_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'infrastructure', 'tools', 'corpus_connectors', 'pdf_tree_to_utf8.py')
if not _ember_9de76725c0e67842_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/corpus_connectors/pdf_tree_to_utf8.py')
_ember_9de76725c0e67842_aliases = ('_ember_issue2015_9de76725c0e67842', 'pdf_tree_to_utf8', 'src.ember.infrastructure.tools.corpus_connectors.pdf_tree_to_utf8', 'tools.corpus_connectors.pdf_tree_to_utf8')
_ember_9de76725c0e67842_existing = []
for _ember_9de76725c0e67842_alias in _ember_9de76725c0e67842_aliases:
    _ember_9de76725c0e67842_candidate = _ember_9de76725c0e67842_sys.modules.get(_ember_9de76725c0e67842_alias)
    if _ember_9de76725c0e67842_candidate is not None and all(_ember_9de76725c0e67842_candidate is not item for item in _ember_9de76725c0e67842_existing):
        _ember_9de76725c0e67842_existing.append(_ember_9de76725c0e67842_candidate)
if len(_ember_9de76725c0e67842_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/corpus_connectors/pdf_tree_to_utf8.py')
if _ember_9de76725c0e67842_existing:
    _ember_9de76725c0e67842_module = _ember_9de76725c0e67842_existing[0]
    _ember_9de76725c0e67842_observed = getattr(_ember_9de76725c0e67842_module, '__file__', None)
    if _ember_9de76725c0e67842_observed is None or _ember_9de76725c0e67842_Path(_ember_9de76725c0e67842_observed).resolve() != _ember_9de76725c0e67842_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/corpus_connectors/pdf_tree_to_utf8.py')
else:
    _ember_9de76725c0e67842_spec = _ember_9de76725c0e67842_importlib.spec_from_file_location('_ember_issue2015_9de76725c0e67842', _ember_9de76725c0e67842_path)
    if _ember_9de76725c0e67842_spec is None or _ember_9de76725c0e67842_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/corpus_connectors/pdf_tree_to_utf8.py')
    _ember_9de76725c0e67842_module = _ember_9de76725c0e67842_importlib.module_from_spec(_ember_9de76725c0e67842_spec)
    for _ember_9de76725c0e67842_alias in _ember_9de76725c0e67842_aliases:
        _ember_9de76725c0e67842_prior = _ember_9de76725c0e67842_sys.modules.get(_ember_9de76725c0e67842_alias)
        if _ember_9de76725c0e67842_prior is not None and _ember_9de76725c0e67842_prior is not _ember_9de76725c0e67842_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/corpus_connectors/pdf_tree_to_utf8.py')
        _ember_9de76725c0e67842_sys.modules[_ember_9de76725c0e67842_alias] = _ember_9de76725c0e67842_module
    try:
        _ember_9de76725c0e67842_spec.loader.exec_module(_ember_9de76725c0e67842_module)
    except BaseException:
        for _ember_9de76725c0e67842_alias in _ember_9de76725c0e67842_aliases:
            if _ember_9de76725c0e67842_sys.modules.get(_ember_9de76725c0e67842_alias) is _ember_9de76725c0e67842_module:
                _ember_9de76725c0e67842_sys.modules.pop(_ember_9de76725c0e67842_alias, None)
        raise
for _ember_9de76725c0e67842_alias in _ember_9de76725c0e67842_aliases:
    _ember_9de76725c0e67842_prior = _ember_9de76725c0e67842_sys.modules.get(_ember_9de76725c0e67842_alias)
    if _ember_9de76725c0e67842_prior is not None and _ember_9de76725c0e67842_prior is not _ember_9de76725c0e67842_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/corpus_connectors/pdf_tree_to_utf8.py')
    _ember_9de76725c0e67842_sys.modules[_ember_9de76725c0e67842_alias] = _ember_9de76725c0e67842_module
PdfTreeExtractionRefusal = getattr(_ember_9de76725c0e67842_module, 'PdfTreeExtractionRefusal')
_write_exclusive = getattr(_ember_9de76725c0e67842_module, '_write_exclusive')
build_composite_connector_authority = getattr(_ember_9de76725c0e67842_module, 'build_composite_connector_authority')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/corpus_connectors/pdf_tree_to_utf8.py


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        raw = build_composite_connector_authority(spec_raw=args.spec.read_bytes())
        _write_exclusive(args.output, raw + b"\n")
    except (OSError, PdfTreeExtractionRefusal) as error:
        parser.error(str(error))
    print(json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
