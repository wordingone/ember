# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""density_ab_a1.py — arm=a seed=1 wrapper for train MCP dispatch."""
import sys, os
sys.argv = ["density_ab_bench.py", "--arm", "a", "--seed", "1"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# issue2015 exact-local-import:scripts/density_ab_bench.py
import importlib.util as _ember_86fa83cbbef8e61b_importlib
import sys as _ember_86fa83cbbef8e61b_sys
from pathlib import Path as _ember_86fa83cbbef8e61b_Path
_ember_86fa83cbbef8e61b_path = _ember_86fa83cbbef8e61b_Path(__file__).resolve().parents[4].joinpath('scripts', 'density_ab_bench.py')
if not _ember_86fa83cbbef8e61b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/density_ab_bench.py')
_ember_86fa83cbbef8e61b_aliases = ('_ember_issue2015_86fa83cbbef8e61b', 'density_ab_bench', 'scripts.density_ab_bench')
_ember_86fa83cbbef8e61b_existing = []
for _ember_86fa83cbbef8e61b_alias in _ember_86fa83cbbef8e61b_aliases:
    _ember_86fa83cbbef8e61b_candidate = _ember_86fa83cbbef8e61b_sys.modules.get(_ember_86fa83cbbef8e61b_alias)
    if _ember_86fa83cbbef8e61b_candidate is not None and all(_ember_86fa83cbbef8e61b_candidate is not item for item in _ember_86fa83cbbef8e61b_existing):
        _ember_86fa83cbbef8e61b_existing.append(_ember_86fa83cbbef8e61b_candidate)
if len(_ember_86fa83cbbef8e61b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/density_ab_bench.py')
if _ember_86fa83cbbef8e61b_existing:
    _ember_86fa83cbbef8e61b_module = _ember_86fa83cbbef8e61b_existing[0]
    _ember_86fa83cbbef8e61b_observed = getattr(_ember_86fa83cbbef8e61b_module, '__file__', None)
    if _ember_86fa83cbbef8e61b_observed is None or _ember_86fa83cbbef8e61b_Path(_ember_86fa83cbbef8e61b_observed).resolve() != _ember_86fa83cbbef8e61b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/density_ab_bench.py')
else:
    _ember_86fa83cbbef8e61b_spec = _ember_86fa83cbbef8e61b_importlib.spec_from_file_location('_ember_issue2015_86fa83cbbef8e61b', _ember_86fa83cbbef8e61b_path)
    if _ember_86fa83cbbef8e61b_spec is None or _ember_86fa83cbbef8e61b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/density_ab_bench.py')
    _ember_86fa83cbbef8e61b_module = _ember_86fa83cbbef8e61b_importlib.module_from_spec(_ember_86fa83cbbef8e61b_spec)
    for _ember_86fa83cbbef8e61b_alias in _ember_86fa83cbbef8e61b_aliases:
        _ember_86fa83cbbef8e61b_prior = _ember_86fa83cbbef8e61b_sys.modules.get(_ember_86fa83cbbef8e61b_alias)
        if _ember_86fa83cbbef8e61b_prior is not None and _ember_86fa83cbbef8e61b_prior is not _ember_86fa83cbbef8e61b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/density_ab_bench.py')
        _ember_86fa83cbbef8e61b_sys.modules[_ember_86fa83cbbef8e61b_alias] = _ember_86fa83cbbef8e61b_module
    try:
        _ember_86fa83cbbef8e61b_spec.loader.exec_module(_ember_86fa83cbbef8e61b_module)
    except BaseException:
        for _ember_86fa83cbbef8e61b_alias in _ember_86fa83cbbef8e61b_aliases:
            if _ember_86fa83cbbef8e61b_sys.modules.get(_ember_86fa83cbbef8e61b_alias) is _ember_86fa83cbbef8e61b_module:
                _ember_86fa83cbbef8e61b_sys.modules.pop(_ember_86fa83cbbef8e61b_alias, None)
        raise
for _ember_86fa83cbbef8e61b_alias in _ember_86fa83cbbef8e61b_aliases:
    _ember_86fa83cbbef8e61b_prior = _ember_86fa83cbbef8e61b_sys.modules.get(_ember_86fa83cbbef8e61b_alias)
    if _ember_86fa83cbbef8e61b_prior is not None and _ember_86fa83cbbef8e61b_prior is not _ember_86fa83cbbef8e61b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/density_ab_bench.py')
    _ember_86fa83cbbef8e61b_sys.modules[_ember_86fa83cbbef8e61b_alias] = _ember_86fa83cbbef8e61b_module
main = getattr(_ember_86fa83cbbef8e61b_module, 'main')
# issue2015 exact-local-import-end:scripts/density_ab_bench.py
main()
