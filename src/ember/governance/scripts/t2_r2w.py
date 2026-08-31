# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""t2_r2w.py — Round-2 W-code sft + control arms, CORRECTED data path.

DEVIATION RECORD (prereg §1.2, recorded per audit-§6): the #112 wrapper
t2_r2_sft computed the theta frontier filter for its receipt but then
delegated to `t2_round --round 2 --train-only`, which builds from the FULL
mixed ledger (ARC + W) with flat caps — the filtered set never reached
training. That is not the registered arm ("frontier-weighted theta=0.5"
on the W-code world). This runner implements the registered semantics,
reusing the proven round-1 pieces (t2_wcode.write_view, frontier.ext_clean,
t2_round.build_dataset/train_lora) and the r2_arms single-source rates:

  sft:     ledger --mbpp:*--> view --ext_clean--> --theta-filter (0,0.5]-->
           build_dataset (flat MAX_PER_TASK cap) --> train_lora
           -> adapters/r2-q3-sft
  control: control_pool --mbpp:*--> view, counts MIRRORED per-task against
           the sft arm's dataset (recomputed deterministically from the
           same ledger state) -> adapters/r2-q3-control

mtp/grpo arms are NOT here: t2_r2_mtp -> t2_mtp regenerates the W view
itself (bits-caps = the r1 default-recipe winner, correct as built);
t2_r2_grpo samples on-policy with verifier reward.

Launch interlock: --the lead-gate-token required (same shape as the #112
wrappers). --dry-run builds everything and writes a receipt but stops
before train_lora (CPU-safe preflight).

AST: python -c "import ast; ast.parse(open('src/ember/governance/scripts/t2_r2w.py').read())"
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from receipt_write import checked_write  # noqa: E402 (eng #107)

NC = "<local-path>"
if os.name == "nt":
    NC = "<local-path>"
RECEIPTS = f"{NC}/receipts"
VIEWS = f"{NC}/receipts/ledger/views"
LEDGER = f"{NC}/receipts/ledger/episodes.jsonl"
CONTROL_POOL = f"{NC}/receipts/ledger/control_pool.jsonl"
ADAPTERS = f"{NC}/adapters"

THETA = 0.5  # prereg §1.2 frozen

SHA_CONVENTION = ("sha256 over on-disk raw bytes "
                  "(binary read, no line-ending normalization)")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _view_entry(path, rows):
    """Receipt entry for a view file ALREADY written to disk — the sha
    is taken from the on-disk bytes post-write, so a downstream
    consumer's --expected-view-sha256 can be pinned straight from the
    certified receipt (eng #150)."""
    return {"path": path, "rows": rows, "sha256": file_sha256(path)}


def _require_gate_token():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--the lead-gate-token", default="")
    args, _ = ap.parse_known_args()
    if not args.maintainer_gate_token.strip():
        print(
            "ERROR: t2_r2w.py requires --the lead-gate-token=<non-empty> "
            "(round-2 launch interlock). Exiting without any work.",
            flush=True,
        )
        sys.exit(1)
    return args.maintainer_gate_token


_gate_token = _require_gate_token()


def build_sft_examples(allow=None):
    """Regenerate W-code views from the CURRENT ledger, ext-clean, apply
    the frozen theta filter, build the dataset. Returns
    (examples, counts, info_block, views). Deterministic from ledger
    state — the control arm recomputes this to mirror counts. `views`
    maps each view filename written here to its post-write
    path/rows/sha256 entry (eng #150)."""
    # issue2015 exact-local-import:scripts/frontier.py
    import importlib.util as _ember_d8c02810056e6c3d_importlib
    import sys as _ember_d8c02810056e6c3d_sys
    from pathlib import Path as _ember_d8c02810056e6c3d_Path
    _ember_d8c02810056e6c3d_path = _ember_d8c02810056e6c3d_Path(__file__).resolve().parents[4].joinpath('scripts', 'frontier.py')
    if not _ember_d8c02810056e6c3d_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/frontier.py')
    _ember_d8c02810056e6c3d_aliases = ('_ember_issue2015_d8c02810056e6c3d', 'frontier', 'scripts.frontier')
    _ember_d8c02810056e6c3d_existing = []
    for _ember_d8c02810056e6c3d_alias in _ember_d8c02810056e6c3d_aliases:
        _ember_d8c02810056e6c3d_candidate = _ember_d8c02810056e6c3d_sys.modules.get(_ember_d8c02810056e6c3d_alias)
        if _ember_d8c02810056e6c3d_candidate is not None and all(_ember_d8c02810056e6c3d_candidate is not item for item in _ember_d8c02810056e6c3d_existing):
            _ember_d8c02810056e6c3d_existing.append(_ember_d8c02810056e6c3d_candidate)
    if len(_ember_d8c02810056e6c3d_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/frontier.py')
    if _ember_d8c02810056e6c3d_existing:
        _ember_d8c02810056e6c3d_module = _ember_d8c02810056e6c3d_existing[0]
        _ember_d8c02810056e6c3d_observed = getattr(_ember_d8c02810056e6c3d_module, '__file__', None)
        if _ember_d8c02810056e6c3d_observed is None or _ember_d8c02810056e6c3d_Path(_ember_d8c02810056e6c3d_observed).resolve() != _ember_d8c02810056e6c3d_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/frontier.py')
    else:
        _ember_d8c02810056e6c3d_spec = _ember_d8c02810056e6c3d_importlib.spec_from_file_location('_ember_issue2015_d8c02810056e6c3d', _ember_d8c02810056e6c3d_path)
        if _ember_d8c02810056e6c3d_spec is None or _ember_d8c02810056e6c3d_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/frontier.py')
        _ember_d8c02810056e6c3d_module = _ember_d8c02810056e6c3d_importlib.module_from_spec(_ember_d8c02810056e6c3d_spec)
        for _ember_d8c02810056e6c3d_alias in _ember_d8c02810056e6c3d_aliases:
            _ember_d8c02810056e6c3d_prior = _ember_d8c02810056e6c3d_sys.modules.get(_ember_d8c02810056e6c3d_alias)
            if _ember_d8c02810056e6c3d_prior is not None and _ember_d8c02810056e6c3d_prior is not _ember_d8c02810056e6c3d_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/frontier.py')
            _ember_d8c02810056e6c3d_sys.modules[_ember_d8c02810056e6c3d_alias] = _ember_d8c02810056e6c3d_module
        try:
            _ember_d8c02810056e6c3d_spec.loader.exec_module(_ember_d8c02810056e6c3d_module)
        except BaseException:
            for _ember_d8c02810056e6c3d_alias in _ember_d8c02810056e6c3d_aliases:
                if _ember_d8c02810056e6c3d_sys.modules.get(_ember_d8c02810056e6c3d_alias) is _ember_d8c02810056e6c3d_module:
                    _ember_d8c02810056e6c3d_sys.modules.pop(_ember_d8c02810056e6c3d_alias, None)
            raise
    for _ember_d8c02810056e6c3d_alias in _ember_d8c02810056e6c3d_aliases:
        _ember_d8c02810056e6c3d_prior = _ember_d8c02810056e6c3d_sys.modules.get(_ember_d8c02810056e6c3d_alias)
        if _ember_d8c02810056e6c3d_prior is not None and _ember_d8c02810056e6c3d_prior is not _ember_d8c02810056e6c3d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/frontier.py')
        _ember_d8c02810056e6c3d_sys.modules[_ember_d8c02810056e6c3d_alias] = _ember_d8c02810056e6c3d_module
    ext_clean = getattr(_ember_d8c02810056e6c3d_module, 'ext_clean')
    load_ext_flags = getattr(_ember_d8c02810056e6c3d_module, 'load_ext_flags')
    # issue2015 exact-local-import-end:scripts/frontier.py
    # issue2015 exact-local-import:scripts/r2_arms.py
    import importlib.util as _ember_5e42585fbe8bb3e8_importlib
    import sys as _ember_5e42585fbe8bb3e8_sys
    from pathlib import Path as _ember_5e42585fbe8bb3e8_Path
    _ember_5e42585fbe8bb3e8_path = _ember_5e42585fbe8bb3e8_Path(__file__).resolve().parents[4].joinpath('scripts', 'r2_arms.py')
    if not _ember_5e42585fbe8bb3e8_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/r2_arms.py')
    _ember_5e42585fbe8bb3e8_aliases = ('_ember_issue2015_5e42585fbe8bb3e8', 'r2_arms', 'scripts.r2_arms')
    _ember_5e42585fbe8bb3e8_existing = []
    for _ember_5e42585fbe8bb3e8_alias in _ember_5e42585fbe8bb3e8_aliases:
        _ember_5e42585fbe8bb3e8_candidate = _ember_5e42585fbe8bb3e8_sys.modules.get(_ember_5e42585fbe8bb3e8_alias)
        if _ember_5e42585fbe8bb3e8_candidate is not None and all(_ember_5e42585fbe8bb3e8_candidate is not item for item in _ember_5e42585fbe8bb3e8_existing):
            _ember_5e42585fbe8bb3e8_existing.append(_ember_5e42585fbe8bb3e8_candidate)
    if len(_ember_5e42585fbe8bb3e8_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/r2_arms.py')
    if _ember_5e42585fbe8bb3e8_existing:
        _ember_5e42585fbe8bb3e8_module = _ember_5e42585fbe8bb3e8_existing[0]
        _ember_5e42585fbe8bb3e8_observed = getattr(_ember_5e42585fbe8bb3e8_module, '__file__', None)
        if _ember_5e42585fbe8bb3e8_observed is None or _ember_5e42585fbe8bb3e8_Path(_ember_5e42585fbe8bb3e8_observed).resolve() != _ember_5e42585fbe8bb3e8_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/r2_arms.py')
    else:
        _ember_5e42585fbe8bb3e8_spec = _ember_5e42585fbe8bb3e8_importlib.spec_from_file_location('_ember_issue2015_5e42585fbe8bb3e8', _ember_5e42585fbe8bb3e8_path)
        if _ember_5e42585fbe8bb3e8_spec is None or _ember_5e42585fbe8bb3e8_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/r2_arms.py')
        _ember_5e42585fbe8bb3e8_module = _ember_5e42585fbe8bb3e8_importlib.module_from_spec(_ember_5e42585fbe8bb3e8_spec)
        for _ember_5e42585fbe8bb3e8_alias in _ember_5e42585fbe8bb3e8_aliases:
            _ember_5e42585fbe8bb3e8_prior = _ember_5e42585fbe8bb3e8_sys.modules.get(_ember_5e42585fbe8bb3e8_alias)
            if _ember_5e42585fbe8bb3e8_prior is not None and _ember_5e42585fbe8bb3e8_prior is not _ember_5e42585fbe8bb3e8_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/r2_arms.py')
            _ember_5e42585fbe8bb3e8_sys.modules[_ember_5e42585fbe8bb3e8_alias] = _ember_5e42585fbe8bb3e8_module
        try:
            _ember_5e42585fbe8bb3e8_spec.loader.exec_module(_ember_5e42585fbe8bb3e8_module)
        except BaseException:
            for _ember_5e42585fbe8bb3e8_alias in _ember_5e42585fbe8bb3e8_aliases:
                if _ember_5e42585fbe8bb3e8_sys.modules.get(_ember_5e42585fbe8bb3e8_alias) is _ember_5e42585fbe8bb3e8_module:
                    _ember_5e42585fbe8bb3e8_sys.modules.pop(_ember_5e42585fbe8bb3e8_alias, None)
            raise
    for _ember_5e42585fbe8bb3e8_alias in _ember_5e42585fbe8bb3e8_aliases:
        _ember_5e42585fbe8bb3e8_prior = _ember_5e42585fbe8bb3e8_sys.modules.get(_ember_5e42585fbe8bb3e8_alias)
        if _ember_5e42585fbe8bb3e8_prior is not None and _ember_5e42585fbe8bb3e8_prior is not _ember_5e42585fbe8bb3e8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/r2_arms.py')
        _ember_5e42585fbe8bb3e8_sys.modules[_ember_5e42585fbe8bb3e8_alias] = _ember_5e42585fbe8bb3e8_module
    frontier_filter = getattr(_ember_5e42585fbe8bb3e8_module, 'frontier_filter')
    solve_rates_from_ledger = getattr(_ember_5e42585fbe8bb3e8_module, 'solve_rates_from_ledger')
    # issue2015 exact-local-import-end:scripts/r2_arms.py
    # issue2015 exact-local-import:scripts/t2_round.py
    import importlib.util as _ember_aa123631425aaf0a_importlib
    import sys as _ember_aa123631425aaf0a_sys
    from pathlib import Path as _ember_aa123631425aaf0a_Path
    _ember_aa123631425aaf0a_path = _ember_aa123631425aaf0a_Path(__file__).resolve().parents[4].joinpath('scripts', 't2_round.py')
    if not _ember_aa123631425aaf0a_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/t2_round.py')
    _ember_aa123631425aaf0a_aliases = ('_ember_issue2015_aa123631425aaf0a', 'scripts.t2_round', 't2_round')
    _ember_aa123631425aaf0a_existing = []
    for _ember_aa123631425aaf0a_alias in _ember_aa123631425aaf0a_aliases:
        _ember_aa123631425aaf0a_candidate = _ember_aa123631425aaf0a_sys.modules.get(_ember_aa123631425aaf0a_alias)
        if _ember_aa123631425aaf0a_candidate is not None and all(_ember_aa123631425aaf0a_candidate is not item for item in _ember_aa123631425aaf0a_existing):
            _ember_aa123631425aaf0a_existing.append(_ember_aa123631425aaf0a_candidate)
    if len(_ember_aa123631425aaf0a_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/t2_round.py')
    if _ember_aa123631425aaf0a_existing:
        _ember_aa123631425aaf0a_module = _ember_aa123631425aaf0a_existing[0]
        _ember_aa123631425aaf0a_observed = getattr(_ember_aa123631425aaf0a_module, '__file__', None)
        if _ember_aa123631425aaf0a_observed is None or _ember_aa123631425aaf0a_Path(_ember_aa123631425aaf0a_observed).resolve() != _ember_aa123631425aaf0a_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/t2_round.py')
    else:
        _ember_aa123631425aaf0a_spec = _ember_aa123631425aaf0a_importlib.spec_from_file_location('_ember_issue2015_aa123631425aaf0a', _ember_aa123631425aaf0a_path)
        if _ember_aa123631425aaf0a_spec is None or _ember_aa123631425aaf0a_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/t2_round.py')
        _ember_aa123631425aaf0a_module = _ember_aa123631425aaf0a_importlib.module_from_spec(_ember_aa123631425aaf0a_spec)
        for _ember_aa123631425aaf0a_alias in _ember_aa123631425aaf0a_aliases:
            _ember_aa123631425aaf0a_prior = _ember_aa123631425aaf0a_sys.modules.get(_ember_aa123631425aaf0a_alias)
            if _ember_aa123631425aaf0a_prior is not None and _ember_aa123631425aaf0a_prior is not _ember_aa123631425aaf0a_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/t2_round.py')
            _ember_aa123631425aaf0a_sys.modules[_ember_aa123631425aaf0a_alias] = _ember_aa123631425aaf0a_module
        try:
            _ember_aa123631425aaf0a_spec.loader.exec_module(_ember_aa123631425aaf0a_module)
        except BaseException:
            for _ember_aa123631425aaf0a_alias in _ember_aa123631425aaf0a_aliases:
                if _ember_aa123631425aaf0a_sys.modules.get(_ember_aa123631425aaf0a_alias) is _ember_aa123631425aaf0a_module:
                    _ember_aa123631425aaf0a_sys.modules.pop(_ember_aa123631425aaf0a_alias, None)
            raise
    for _ember_aa123631425aaf0a_alias in _ember_aa123631425aaf0a_aliases:
        _ember_aa123631425aaf0a_prior = _ember_aa123631425aaf0a_sys.modules.get(_ember_aa123631425aaf0a_alias)
        if _ember_aa123631425aaf0a_prior is not None and _ember_aa123631425aaf0a_prior is not _ember_aa123631425aaf0a_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/t2_round.py')
        _ember_aa123631425aaf0a_sys.modules[_ember_aa123631425aaf0a_alias] = _ember_aa123631425aaf0a_module
    build_dataset = getattr(_ember_aa123631425aaf0a_module, 'build_dataset')
    # issue2015 exact-local-import-end:scripts/t2_round.py
    # issue2015 exact-local-import:scripts/t2_wcode.py
    import importlib.util as _ember_ed04e2bafc742d3a_importlib
    import sys as _ember_ed04e2bafc742d3a_sys
    from pathlib import Path as _ember_ed04e2bafc742d3a_Path
    _ember_ed04e2bafc742d3a_path = _ember_ed04e2bafc742d3a_Path(__file__).resolve().parents[4].joinpath('scripts', 't2_wcode.py')
    if not _ember_ed04e2bafc742d3a_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/t2_wcode.py')
    _ember_ed04e2bafc742d3a_aliases = ('_ember_issue2015_ed04e2bafc742d3a', 'scripts.t2_wcode', 't2_wcode')
    _ember_ed04e2bafc742d3a_existing = []
    for _ember_ed04e2bafc742d3a_alias in _ember_ed04e2bafc742d3a_aliases:
        _ember_ed04e2bafc742d3a_candidate = _ember_ed04e2bafc742d3a_sys.modules.get(_ember_ed04e2bafc742d3a_alias)
        if _ember_ed04e2bafc742d3a_candidate is not None and all(_ember_ed04e2bafc742d3a_candidate is not item for item in _ember_ed04e2bafc742d3a_existing):
            _ember_ed04e2bafc742d3a_existing.append(_ember_ed04e2bafc742d3a_candidate)
    if len(_ember_ed04e2bafc742d3a_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/t2_wcode.py')
    if _ember_ed04e2bafc742d3a_existing:
        _ember_ed04e2bafc742d3a_module = _ember_ed04e2bafc742d3a_existing[0]
        _ember_ed04e2bafc742d3a_observed = getattr(_ember_ed04e2bafc742d3a_module, '__file__', None)
        if _ember_ed04e2bafc742d3a_observed is None or _ember_ed04e2bafc742d3a_Path(_ember_ed04e2bafc742d3a_observed).resolve() != _ember_ed04e2bafc742d3a_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/t2_wcode.py')
    else:
        _ember_ed04e2bafc742d3a_spec = _ember_ed04e2bafc742d3a_importlib.spec_from_file_location('_ember_issue2015_ed04e2bafc742d3a', _ember_ed04e2bafc742d3a_path)
        if _ember_ed04e2bafc742d3a_spec is None or _ember_ed04e2bafc742d3a_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/t2_wcode.py')
        _ember_ed04e2bafc742d3a_module = _ember_ed04e2bafc742d3a_importlib.module_from_spec(_ember_ed04e2bafc742d3a_spec)
        for _ember_ed04e2bafc742d3a_alias in _ember_ed04e2bafc742d3a_aliases:
            _ember_ed04e2bafc742d3a_prior = _ember_ed04e2bafc742d3a_sys.modules.get(_ember_ed04e2bafc742d3a_alias)
            if _ember_ed04e2bafc742d3a_prior is not None and _ember_ed04e2bafc742d3a_prior is not _ember_ed04e2bafc742d3a_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/t2_wcode.py')
            _ember_ed04e2bafc742d3a_sys.modules[_ember_ed04e2bafc742d3a_alias] = _ember_ed04e2bafc742d3a_module
        try:
            _ember_ed04e2bafc742d3a_spec.loader.exec_module(_ember_ed04e2bafc742d3a_module)
        except BaseException:
            for _ember_ed04e2bafc742d3a_alias in _ember_ed04e2bafc742d3a_aliases:
                if _ember_ed04e2bafc742d3a_sys.modules.get(_ember_ed04e2bafc742d3a_alias) is _ember_ed04e2bafc742d3a_module:
                    _ember_ed04e2bafc742d3a_sys.modules.pop(_ember_ed04e2bafc742d3a_alias, None)
            raise
    for _ember_ed04e2bafc742d3a_alias in _ember_ed04e2bafc742d3a_aliases:
        _ember_ed04e2bafc742d3a_prior = _ember_ed04e2bafc742d3a_sys.modules.get(_ember_ed04e2bafc742d3a_alias)
        if _ember_ed04e2bafc742d3a_prior is not None and _ember_ed04e2bafc742d3a_prior is not _ember_ed04e2bafc742d3a_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/t2_wcode.py')
        _ember_ed04e2bafc742d3a_sys.modules[_ember_ed04e2bafc742d3a_alias] = _ember_ed04e2bafc742d3a_module
    write_view = getattr(_ember_ed04e2bafc742d3a_module, 'write_view')
    # issue2015 exact-local-import-end:scripts/t2_wcode.py

    arm_recs = write_view(LEDGER, f"{VIEWS}/wcode-r2.jsonl")
    views = {"wcode-r2.jsonl":
             _view_entry(f"{VIEWS}/wcode-r2.jsonl", len(arm_recs))}
    arm_recs = ext_clean(arm_recs,
                         load_ext_flags([f"{RECEIPTS}/v-ext-flags-*.jsonl"]))

    rates = solve_rates_from_ledger(LEDGER, CONTROL_POOL)
    filtered = frontier_filter(arm_recs, rates, THETA)

    view_path = f"{VIEWS}/wcode-r2-sft.jsonl"
    with open(view_path, "w", encoding="utf-8", newline="\n") as vf:
        for r in filtered:
            vf.write(json.dumps(r) + "\n")
    views["wcode-r2-sft.jsonl"] = _view_entry(view_path, len(filtered))

    examples, counts = build_dataset(view_path, license_allow=allow)
    info = {
        "theta": THETA,
        "view_rows_wcode": len(arm_recs),
        "view_rows_after_theta": len(filtered),
        "tasks_wcode": len({r["task"] for r in arm_recs}),
        "tasks_after_theta": len({r["task"] for r in filtered}),
        "dataset_examples": len(examples),
        "dataset_tasks": len(counts),
        "rates_source": "r2_arms.solve_rates_from_ledger(ledger+control_pool)",
    }
    return examples, counts, info, views


def main():
    ap = argparse.ArgumentParser(description="Round-2 W-code sft/control arms "
                                             "(corrected data path).")
    ap.add_argument("--the lead-gate-token", required=True)
    ap.add_argument("--arm", choices=("sft", "control"), required=True)
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--tag-suffix", default="-q3")
    ap.add_argument("--license-allow", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="build dataset + receipt, no training (CPU preflight)")
    args, _unknown = ap.parse_known_args()  # daemon appends args; ignore

    sys.path.insert(0, f"{NC}/scripts")
    # issue2015 exact-local-import:scripts/ledger_license.py
    import importlib.util as _ember_af5eca6d54450d11_importlib
    import sys as _ember_af5eca6d54450d11_sys
    from pathlib import Path as _ember_af5eca6d54450d11_Path
    _ember_af5eca6d54450d11_path = _ember_af5eca6d54450d11_Path(__file__).resolve().parents[4].joinpath('scripts', 'ledger_license.py')
    if not _ember_af5eca6d54450d11_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/ledger_license.py')
    _ember_af5eca6d54450d11_aliases = ('_ember_issue2015_af5eca6d54450d11', 'ledger_license', 'scripts.ledger_license')
    _ember_af5eca6d54450d11_existing = []
    for _ember_af5eca6d54450d11_alias in _ember_af5eca6d54450d11_aliases:
        _ember_af5eca6d54450d11_candidate = _ember_af5eca6d54450d11_sys.modules.get(_ember_af5eca6d54450d11_alias)
        if _ember_af5eca6d54450d11_candidate is not None and all(_ember_af5eca6d54450d11_candidate is not item for item in _ember_af5eca6d54450d11_existing):
            _ember_af5eca6d54450d11_existing.append(_ember_af5eca6d54450d11_candidate)
    if len(_ember_af5eca6d54450d11_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/ledger_license.py')
    if _ember_af5eca6d54450d11_existing:
        _ember_af5eca6d54450d11_module = _ember_af5eca6d54450d11_existing[0]
        _ember_af5eca6d54450d11_observed = getattr(_ember_af5eca6d54450d11_module, '__file__', None)
        if _ember_af5eca6d54450d11_observed is None or _ember_af5eca6d54450d11_Path(_ember_af5eca6d54450d11_observed).resolve() != _ember_af5eca6d54450d11_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/ledger_license.py')
    else:
        _ember_af5eca6d54450d11_spec = _ember_af5eca6d54450d11_importlib.spec_from_file_location('_ember_issue2015_af5eca6d54450d11', _ember_af5eca6d54450d11_path)
        if _ember_af5eca6d54450d11_spec is None or _ember_af5eca6d54450d11_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/ledger_license.py')
        _ember_af5eca6d54450d11_module = _ember_af5eca6d54450d11_importlib.module_from_spec(_ember_af5eca6d54450d11_spec)
        for _ember_af5eca6d54450d11_alias in _ember_af5eca6d54450d11_aliases:
            _ember_af5eca6d54450d11_prior = _ember_af5eca6d54450d11_sys.modules.get(_ember_af5eca6d54450d11_alias)
            if _ember_af5eca6d54450d11_prior is not None and _ember_af5eca6d54450d11_prior is not _ember_af5eca6d54450d11_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ledger_license.py')
            _ember_af5eca6d54450d11_sys.modules[_ember_af5eca6d54450d11_alias] = _ember_af5eca6d54450d11_module
        try:
            _ember_af5eca6d54450d11_spec.loader.exec_module(_ember_af5eca6d54450d11_module)
        except BaseException:
            for _ember_af5eca6d54450d11_alias in _ember_af5eca6d54450d11_aliases:
                if _ember_af5eca6d54450d11_sys.modules.get(_ember_af5eca6d54450d11_alias) is _ember_af5eca6d54450d11_module:
                    _ember_af5eca6d54450d11_sys.modules.pop(_ember_af5eca6d54450d11_alias, None)
            raise
    for _ember_af5eca6d54450d11_alias in _ember_af5eca6d54450d11_aliases:
        _ember_af5eca6d54450d11_prior = _ember_af5eca6d54450d11_sys.modules.get(_ember_af5eca6d54450d11_alias)
        if _ember_af5eca6d54450d11_prior is not None and _ember_af5eca6d54450d11_prior is not _ember_af5eca6d54450d11_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ledger_license.py')
        _ember_af5eca6d54450d11_sys.modules[_ember_af5eca6d54450d11_alias] = _ember_af5eca6d54450d11_module
    parse_allow = getattr(_ember_af5eca6d54450d11_module, 'parse_allow')
    # issue2015 exact-local-import-end:scripts/ledger_license.py
    # issue2015 exact-local-import:scripts/t2_round.py
    import importlib.util as _ember_aa123631425aaf0a_importlib
    import sys as _ember_aa123631425aaf0a_sys
    from pathlib import Path as _ember_aa123631425aaf0a_Path
    _ember_aa123631425aaf0a_path = _ember_aa123631425aaf0a_Path(__file__).resolve().parents[4].joinpath('scripts', 't2_round.py')
    if not _ember_aa123631425aaf0a_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/t2_round.py')
    _ember_aa123631425aaf0a_aliases = ('_ember_issue2015_aa123631425aaf0a', 'scripts.t2_round', 't2_round')
    _ember_aa123631425aaf0a_existing = []
    for _ember_aa123631425aaf0a_alias in _ember_aa123631425aaf0a_aliases:
        _ember_aa123631425aaf0a_candidate = _ember_aa123631425aaf0a_sys.modules.get(_ember_aa123631425aaf0a_alias)
        if _ember_aa123631425aaf0a_candidate is not None and all(_ember_aa123631425aaf0a_candidate is not item for item in _ember_aa123631425aaf0a_existing):
            _ember_aa123631425aaf0a_existing.append(_ember_aa123631425aaf0a_candidate)
    if len(_ember_aa123631425aaf0a_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/t2_round.py')
    if _ember_aa123631425aaf0a_existing:
        _ember_aa123631425aaf0a_module = _ember_aa123631425aaf0a_existing[0]
        _ember_aa123631425aaf0a_observed = getattr(_ember_aa123631425aaf0a_module, '__file__', None)
        if _ember_aa123631425aaf0a_observed is None or _ember_aa123631425aaf0a_Path(_ember_aa123631425aaf0a_observed).resolve() != _ember_aa123631425aaf0a_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/t2_round.py')
    else:
        _ember_aa123631425aaf0a_spec = _ember_aa123631425aaf0a_importlib.spec_from_file_location('_ember_issue2015_aa123631425aaf0a', _ember_aa123631425aaf0a_path)
        if _ember_aa123631425aaf0a_spec is None or _ember_aa123631425aaf0a_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/t2_round.py')
        _ember_aa123631425aaf0a_module = _ember_aa123631425aaf0a_importlib.module_from_spec(_ember_aa123631425aaf0a_spec)
        for _ember_aa123631425aaf0a_alias in _ember_aa123631425aaf0a_aliases:
            _ember_aa123631425aaf0a_prior = _ember_aa123631425aaf0a_sys.modules.get(_ember_aa123631425aaf0a_alias)
            if _ember_aa123631425aaf0a_prior is not None and _ember_aa123631425aaf0a_prior is not _ember_aa123631425aaf0a_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/t2_round.py')
            _ember_aa123631425aaf0a_sys.modules[_ember_aa123631425aaf0a_alias] = _ember_aa123631425aaf0a_module
        try:
            _ember_aa123631425aaf0a_spec.loader.exec_module(_ember_aa123631425aaf0a_module)
        except BaseException:
            for _ember_aa123631425aaf0a_alias in _ember_aa123631425aaf0a_aliases:
                if _ember_aa123631425aaf0a_sys.modules.get(_ember_aa123631425aaf0a_alias) is _ember_aa123631425aaf0a_module:
                    _ember_aa123631425aaf0a_sys.modules.pop(_ember_aa123631425aaf0a_alias, None)
            raise
    for _ember_aa123631425aaf0a_alias in _ember_aa123631425aaf0a_aliases:
        _ember_aa123631425aaf0a_prior = _ember_aa123631425aaf0a_sys.modules.get(_ember_aa123631425aaf0a_alias)
        if _ember_aa123631425aaf0a_prior is not None and _ember_aa123631425aaf0a_prior is not _ember_aa123631425aaf0a_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/t2_round.py')
        _ember_aa123631425aaf0a_sys.modules[_ember_aa123631425aaf0a_alias] = _ember_aa123631425aaf0a_module
    build_dataset = getattr(_ember_aa123631425aaf0a_module, 'build_dataset')
    train_lora = getattr(_ember_aa123631425aaf0a_module, 'train_lora')
    # issue2015 exact-local-import-end:scripts/t2_round.py
    # issue2015 exact-local-import:scripts/t2_wcode.py
    import importlib.util as _ember_ed04e2bafc742d3a_importlib
    import sys as _ember_ed04e2bafc742d3a_sys
    from pathlib import Path as _ember_ed04e2bafc742d3a_Path
    _ember_ed04e2bafc742d3a_path = _ember_ed04e2bafc742d3a_Path(__file__).resolve().parents[4].joinpath('scripts', 't2_wcode.py')
    if not _ember_ed04e2bafc742d3a_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/t2_wcode.py')
    _ember_ed04e2bafc742d3a_aliases = ('_ember_issue2015_ed04e2bafc742d3a', 'scripts.t2_wcode', 't2_wcode')
    _ember_ed04e2bafc742d3a_existing = []
    for _ember_ed04e2bafc742d3a_alias in _ember_ed04e2bafc742d3a_aliases:
        _ember_ed04e2bafc742d3a_candidate = _ember_ed04e2bafc742d3a_sys.modules.get(_ember_ed04e2bafc742d3a_alias)
        if _ember_ed04e2bafc742d3a_candidate is not None and all(_ember_ed04e2bafc742d3a_candidate is not item for item in _ember_ed04e2bafc742d3a_existing):
            _ember_ed04e2bafc742d3a_existing.append(_ember_ed04e2bafc742d3a_candidate)
    if len(_ember_ed04e2bafc742d3a_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/t2_wcode.py')
    if _ember_ed04e2bafc742d3a_existing:
        _ember_ed04e2bafc742d3a_module = _ember_ed04e2bafc742d3a_existing[0]
        _ember_ed04e2bafc742d3a_observed = getattr(_ember_ed04e2bafc742d3a_module, '__file__', None)
        if _ember_ed04e2bafc742d3a_observed is None or _ember_ed04e2bafc742d3a_Path(_ember_ed04e2bafc742d3a_observed).resolve() != _ember_ed04e2bafc742d3a_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/t2_wcode.py')
    else:
        _ember_ed04e2bafc742d3a_spec = _ember_ed04e2bafc742d3a_importlib.spec_from_file_location('_ember_issue2015_ed04e2bafc742d3a', _ember_ed04e2bafc742d3a_path)
        if _ember_ed04e2bafc742d3a_spec is None or _ember_ed04e2bafc742d3a_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/t2_wcode.py')
        _ember_ed04e2bafc742d3a_module = _ember_ed04e2bafc742d3a_importlib.module_from_spec(_ember_ed04e2bafc742d3a_spec)
        for _ember_ed04e2bafc742d3a_alias in _ember_ed04e2bafc742d3a_aliases:
            _ember_ed04e2bafc742d3a_prior = _ember_ed04e2bafc742d3a_sys.modules.get(_ember_ed04e2bafc742d3a_alias)
            if _ember_ed04e2bafc742d3a_prior is not None and _ember_ed04e2bafc742d3a_prior is not _ember_ed04e2bafc742d3a_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/t2_wcode.py')
            _ember_ed04e2bafc742d3a_sys.modules[_ember_ed04e2bafc742d3a_alias] = _ember_ed04e2bafc742d3a_module
        try:
            _ember_ed04e2bafc742d3a_spec.loader.exec_module(_ember_ed04e2bafc742d3a_module)
        except BaseException:
            for _ember_ed04e2bafc742d3a_alias in _ember_ed04e2bafc742d3a_aliases:
                if _ember_ed04e2bafc742d3a_sys.modules.get(_ember_ed04e2bafc742d3a_alias) is _ember_ed04e2bafc742d3a_module:
                    _ember_ed04e2bafc742d3a_sys.modules.pop(_ember_ed04e2bafc742d3a_alias, None)
            raise
    for _ember_ed04e2bafc742d3a_alias in _ember_ed04e2bafc742d3a_aliases:
        _ember_ed04e2bafc742d3a_prior = _ember_ed04e2bafc742d3a_sys.modules.get(_ember_ed04e2bafc742d3a_alias)
        if _ember_ed04e2bafc742d3a_prior is not None and _ember_ed04e2bafc742d3a_prior is not _ember_ed04e2bafc742d3a_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/t2_wcode.py')
        _ember_ed04e2bafc742d3a_sys.modules[_ember_ed04e2bafc742d3a_alias] = _ember_ed04e2bafc742d3a_module
    write_view = getattr(_ember_ed04e2bafc742d3a_module, 'write_view')
    # issue2015 exact-local-import-end:scripts/t2_wcode.py
    # issue2015 exact-local-import:scripts/t1_probe.py
    import importlib.util as _ember_c32cf5e860218889_importlib
    import sys as _ember_c32cf5e860218889_sys
    from pathlib import Path as _ember_c32cf5e860218889_Path
    _ember_c32cf5e860218889_path = _ember_c32cf5e860218889_Path(__file__).resolve().parents[4].joinpath('scripts', 't1_probe.py')
    if not _ember_c32cf5e860218889_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/t1_probe.py')
    _ember_c32cf5e860218889_aliases = ('_ember_issue2015_c32cf5e860218889', 'scripts.t1_probe', 't1_probe')
    _ember_c32cf5e860218889_existing = []
    for _ember_c32cf5e860218889_alias in _ember_c32cf5e860218889_aliases:
        _ember_c32cf5e860218889_candidate = _ember_c32cf5e860218889_sys.modules.get(_ember_c32cf5e860218889_alias)
        if _ember_c32cf5e860218889_candidate is not None and all(_ember_c32cf5e860218889_candidate is not item for item in _ember_c32cf5e860218889_existing):
            _ember_c32cf5e860218889_existing.append(_ember_c32cf5e860218889_candidate)
    if len(_ember_c32cf5e860218889_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/t1_probe.py')
    if _ember_c32cf5e860218889_existing:
        _ember_c32cf5e860218889_module = _ember_c32cf5e860218889_existing[0]
        _ember_c32cf5e860218889_observed = getattr(_ember_c32cf5e860218889_module, '__file__', None)
        if _ember_c32cf5e860218889_observed is None or _ember_c32cf5e860218889_Path(_ember_c32cf5e860218889_observed).resolve() != _ember_c32cf5e860218889_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/t1_probe.py')
    else:
        _ember_c32cf5e860218889_spec = _ember_c32cf5e860218889_importlib.spec_from_file_location('_ember_issue2015_c32cf5e860218889', _ember_c32cf5e860218889_path)
        if _ember_c32cf5e860218889_spec is None or _ember_c32cf5e860218889_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/t1_probe.py')
        _ember_c32cf5e860218889_module = _ember_c32cf5e860218889_importlib.module_from_spec(_ember_c32cf5e860218889_spec)
        for _ember_c32cf5e860218889_alias in _ember_c32cf5e860218889_aliases:
            _ember_c32cf5e860218889_prior = _ember_c32cf5e860218889_sys.modules.get(_ember_c32cf5e860218889_alias)
            if _ember_c32cf5e860218889_prior is not None and _ember_c32cf5e860218889_prior is not _ember_c32cf5e860218889_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/t1_probe.py')
            _ember_c32cf5e860218889_sys.modules[_ember_c32cf5e860218889_alias] = _ember_c32cf5e860218889_module
        try:
            _ember_c32cf5e860218889_spec.loader.exec_module(_ember_c32cf5e860218889_module)
        except BaseException:
            for _ember_c32cf5e860218889_alias in _ember_c32cf5e860218889_aliases:
                if _ember_c32cf5e860218889_sys.modules.get(_ember_c32cf5e860218889_alias) is _ember_c32cf5e860218889_module:
                    _ember_c32cf5e860218889_sys.modules.pop(_ember_c32cf5e860218889_alias, None)
            raise
    for _ember_c32cf5e860218889_alias in _ember_c32cf5e860218889_aliases:
        _ember_c32cf5e860218889_prior = _ember_c32cf5e860218889_sys.modules.get(_ember_c32cf5e860218889_alias)
        if _ember_c32cf5e860218889_prior is not None and _ember_c32cf5e860218889_prior is not _ember_c32cf5e860218889_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/t1_probe.py')
        _ember_c32cf5e860218889_sys.modules[_ember_c32cf5e860218889_alias] = _ember_c32cf5e860218889_module
    pacing_snapshot = getattr(_ember_c32cf5e860218889_module, 'pacing_snapshot')
    # issue2015 exact-local-import-end:scripts/t1_probe.py

    allow = parse_allow(args.license_allow) if args.license_allow else None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    clean = args.tag_suffix.lstrip("-")
    tag = f"r2-{clean}-{args.arm}"

    sft_examples, sft_counts, info, views = build_sft_examples(allow)

    if args.arm == "sft":
        examples, counts = sft_examples, sft_counts
    else:
        ctrl_recs = write_view(CONTROL_POOL, f"{VIEWS}/wcode-r2-control.jsonl")
        views["wcode-r2-control.jsonl"] = _view_entry(
            f"{VIEWS}/wcode-r2-control.jsonl", len(ctrl_recs))
        examples, counts = build_dataset(f"{VIEWS}/wcode-r2-control.jsonl",
                                         match_counts=sft_counts,
                                         license_allow=allow)
        info["control_view_rows"] = len(ctrl_recs)
        info["control_examples"] = len(examples)
        info["mirrors"] = "sft per-task counts (recomputed, same ledger state)"

    receipt = {
        "ticket": "NC0-T2-R2W",
        "arm": args.arm,
        "tag": tag,
        "ts": ts,
        "round": 2,
        "model": args.model,
        "gate_token_present": bool(_gate_token),
        "deviation": ("prereg-§1.2 data-path correction: #112 t2_r2_sft "
                      "delegated to full-ledger flat-cap build; this runner "
                      "trains the registered W-code theta-filtered set"),
        "frontier_filter": info,
        "views_written": views,
        "sha_convention": SHA_CONVENTION,
        "dry_run": args.dry_run,
    }

    if not examples:
        receipt["verdict"] = "EMPTY-DATASET (gate before training)"
    elif not args.dry_run:
        t0 = time.time()
        receipt["training"] = train_lora(args.model, examples,
                                         f"{ADAPTERS}/{tag}")
        receipt["training"]["secs"] = round(time.time() - t0, 1)
        receipt["adapter"] = f"{ADAPTERS}/{tag}"

    receipt["pacing"] = pacing_snapshot()  # fp-14 convention, at write time
    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/t2-r2w-{args.arm}-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps({k: receipt[k] for k in
                      ("arm", "tag", "frontier_filter", "dry_run")}, indent=2))
    print(f"T2_R2W_DONE {out}")


if __name__ == "__main__":
    main()
