# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Temporary import compatibility until the EMBER-02B callers migrate (#2213)."""
# Remove after the #2213 EMBER-02B caller carrier merges, through the third EMBER-02A carrier.
import sys as _ember_v0_compat_sys
from pathlib import Path as _EmberV0CompatPath

if __package__:
    from . import ember_v0_fp8_linear as _ember_v0_compat_impl
else:
    _ember_v0_compat_dir = str(_EmberV0CompatPath(__file__).resolve().parent)
    _ember_v0_compat_sys.path.insert(0, _ember_v0_compat_dir)
    try:
        import ember_v0_fp8_linear as _ember_v0_compat_impl
    finally:
        _ember_v0_compat_sys.path.remove(_ember_v0_compat_dir)

if _EmberV0CompatPath(_ember_v0_compat_impl.__file__).resolve() != _EmberV0CompatPath(__file__).resolve().with_name("ember_v0_fp8_linear.py"):
    raise ImportError("VERSIONED_MODEL_COMPATIBILITY_SOURCE_MISMATCH")

# Preserve private exports while retaining the exact compatibility source path.
globals().update({name: value for name, value in vars(_ember_v0_compat_impl).items() if not name.startswith("__")})
