# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Live clean-genesis launch caller: input identity reaches gate and validator."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

# issue2015 exact-local-import:tools/ember-restart-3b/input_identity.py
import importlib.util as _ember_420977719a554907_importlib
import sys as _ember_420977719a554907_sys
from pathlib import Path as _ember_420977719a554907_Path
_ember_420977719a554907_path = _ember_420977719a554907_Path(__file__).resolve().parents[5].joinpath('tools', 'ember-restart-3b', 'input_identity.py')
if not _ember_420977719a554907_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:tools/ember-restart-3b/input_identity.py')
_ember_420977719a554907_aliases = ('_ember_issue2015_420977719a554907', 'input_identity', 'tools.ember-restart-3b.input_identity')
_ember_420977719a554907_existing = []
for _ember_420977719a554907_alias in _ember_420977719a554907_aliases:
    _ember_420977719a554907_candidate = _ember_420977719a554907_sys.modules.get(_ember_420977719a554907_alias)
    if _ember_420977719a554907_candidate is not None and all(_ember_420977719a554907_candidate is not item for item in _ember_420977719a554907_existing):
        _ember_420977719a554907_existing.append(_ember_420977719a554907_candidate)
if len(_ember_420977719a554907_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:tools/ember-restart-3b/input_identity.py')
if _ember_420977719a554907_existing:
    _ember_420977719a554907_module = _ember_420977719a554907_existing[0]
    _ember_420977719a554907_observed = getattr(_ember_420977719a554907_module, '__file__', None)
    if _ember_420977719a554907_observed is None or _ember_420977719a554907_Path(_ember_420977719a554907_observed).resolve() != _ember_420977719a554907_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:tools/ember-restart-3b/input_identity.py')
else:
    _ember_420977719a554907_spec = _ember_420977719a554907_importlib.spec_from_file_location('_ember_issue2015_420977719a554907', _ember_420977719a554907_path)
    if _ember_420977719a554907_spec is None or _ember_420977719a554907_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:tools/ember-restart-3b/input_identity.py')
    _ember_420977719a554907_module = _ember_420977719a554907_importlib.module_from_spec(_ember_420977719a554907_spec)
    for _ember_420977719a554907_alias in _ember_420977719a554907_aliases:
        _ember_420977719a554907_prior = _ember_420977719a554907_sys.modules.get(_ember_420977719a554907_alias)
        if _ember_420977719a554907_prior is not None and _ember_420977719a554907_prior is not _ember_420977719a554907_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:tools/ember-restart-3b/input_identity.py')
        _ember_420977719a554907_sys.modules[_ember_420977719a554907_alias] = _ember_420977719a554907_module
    try:
        _ember_420977719a554907_spec.loader.exec_module(_ember_420977719a554907_module)
    except BaseException:
        for _ember_420977719a554907_alias in _ember_420977719a554907_aliases:
            if _ember_420977719a554907_sys.modules.get(_ember_420977719a554907_alias) is _ember_420977719a554907_module:
                _ember_420977719a554907_sys.modules.pop(_ember_420977719a554907_alias, None)
        raise
for _ember_420977719a554907_alias in _ember_420977719a554907_aliases:
    _ember_420977719a554907_prior = _ember_420977719a554907_sys.modules.get(_ember_420977719a554907_alias)
    if _ember_420977719a554907_prior is not None and _ember_420977719a554907_prior is not _ember_420977719a554907_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:tools/ember-restart-3b/input_identity.py')
    _ember_420977719a554907_sys.modules[_ember_420977719a554907_alias] = _ember_420977719a554907_module
build_launch_packet = getattr(_ember_420977719a554907_module, 'build_launch_packet')
emit_integration_receipt = getattr(_ember_420977719a554907_module, 'emit_integration_receipt')
validate_launch_packet = getattr(_ember_420977719a554907_module, 'validate_launch_packet')
# issue2015 exact-local-import-end:tools/ember-restart-3b/input_identity.py
# issue2015 exact-local-import:tools/ember-restart-3b/text_lab_corpus.py
import importlib.util as _ember_19a226af4399225d_importlib
import sys as _ember_19a226af4399225d_sys
from pathlib import Path as _ember_19a226af4399225d_Path
_ember_19a226af4399225d_path = _ember_19a226af4399225d_Path(__file__).resolve().parents[5].joinpath('tools', 'ember-restart-3b', 'text_lab_corpus.py')
if not _ember_19a226af4399225d_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:tools/ember-restart-3b/text_lab_corpus.py')
_ember_19a226af4399225d_aliases = ('_ember_issue2015_19a226af4399225d', 'text_lab_corpus', 'tools.ember-restart-3b.text_lab_corpus')
_ember_19a226af4399225d_existing = []
for _ember_19a226af4399225d_alias in _ember_19a226af4399225d_aliases:
    _ember_19a226af4399225d_candidate = _ember_19a226af4399225d_sys.modules.get(_ember_19a226af4399225d_alias)
    if _ember_19a226af4399225d_candidate is not None and all(_ember_19a226af4399225d_candidate is not item for item in _ember_19a226af4399225d_existing):
        _ember_19a226af4399225d_existing.append(_ember_19a226af4399225d_candidate)
if len(_ember_19a226af4399225d_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:tools/ember-restart-3b/text_lab_corpus.py')
if _ember_19a226af4399225d_existing:
    _ember_19a226af4399225d_module = _ember_19a226af4399225d_existing[0]
    _ember_19a226af4399225d_observed = getattr(_ember_19a226af4399225d_module, '__file__', None)
    if _ember_19a226af4399225d_observed is None or _ember_19a226af4399225d_Path(_ember_19a226af4399225d_observed).resolve() != _ember_19a226af4399225d_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:tools/ember-restart-3b/text_lab_corpus.py')
else:
    _ember_19a226af4399225d_spec = _ember_19a226af4399225d_importlib.spec_from_file_location('_ember_issue2015_19a226af4399225d', _ember_19a226af4399225d_path)
    if _ember_19a226af4399225d_spec is None or _ember_19a226af4399225d_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:tools/ember-restart-3b/text_lab_corpus.py')
    _ember_19a226af4399225d_module = _ember_19a226af4399225d_importlib.module_from_spec(_ember_19a226af4399225d_spec)
    for _ember_19a226af4399225d_alias in _ember_19a226af4399225d_aliases:
        _ember_19a226af4399225d_prior = _ember_19a226af4399225d_sys.modules.get(_ember_19a226af4399225d_alias)
        if _ember_19a226af4399225d_prior is not None and _ember_19a226af4399225d_prior is not _ember_19a226af4399225d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:tools/ember-restart-3b/text_lab_corpus.py')
        _ember_19a226af4399225d_sys.modules[_ember_19a226af4399225d_alias] = _ember_19a226af4399225d_module
    try:
        _ember_19a226af4399225d_spec.loader.exec_module(_ember_19a226af4399225d_module)
    except BaseException:
        for _ember_19a226af4399225d_alias in _ember_19a226af4399225d_aliases:
            if _ember_19a226af4399225d_sys.modules.get(_ember_19a226af4399225d_alias) is _ember_19a226af4399225d_module:
                _ember_19a226af4399225d_sys.modules.pop(_ember_19a226af4399225d_alias, None)
        raise
for _ember_19a226af4399225d_alias in _ember_19a226af4399225d_aliases:
    _ember_19a226af4399225d_prior = _ember_19a226af4399225d_sys.modules.get(_ember_19a226af4399225d_alias)
    if _ember_19a226af4399225d_prior is not None and _ember_19a226af4399225d_prior is not _ember_19a226af4399225d_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:tools/ember-restart-3b/text_lab_corpus.py')
    _ember_19a226af4399225d_sys.modules[_ember_19a226af4399225d_alias] = _ember_19a226af4399225d_module
validate_authority_index = getattr(_ember_19a226af4399225d_module, 'validate_authority_index')
# issue2015 exact-local-import-end:tools/ember-restart-3b/text_lab_corpus.py


def _code_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or len(value) != 40:
        raise RuntimeError("the live launch caller requires an exact Git commit")
    return value


def run_launch(
    *,
    repo_root: Path | None = None,
    input_identity_arg: str | None = None,
    code_commit: str | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    """Resolve, forward, consume, and receipt the selected owned shard identity."""

    root = (repo_root or next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())).resolve()
    config_path = root / "configs" / "ember-restart-3b.json"
    packet = build_launch_packet(
        repo_root=root,
        config_path=config_path,
        input_identity_arg=input_identity_arg,
    )
    validation = validate_launch_packet(packet, repo_root=root)
    receipt = emit_integration_receipt(
        packet,
        validation,
        code_commit=code_commit or _code_commit(root),
    )
    return packet, validation, receipt


def run_text_lab_preflight(
    *,
    repo_root: Path | None = None,
    receipt_custody_root: Path | None = None,
) -> dict[str, Any]:
    """Validate exact checked-in shared-text authority before a CUDA-facing route."""
    root = (repo_root or next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())).resolve()
    authority = validate_authority_index(
        root,
        receipt_custody_root=receipt_custody_root,
    )
    return {
        "schema_version": "ember-text-lab-preflight-receipt-v1",
        **authority,
        "live_head": _code_commit(root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the owned input identity for an Ember launch.")
    parser.add_argument("--input-identity", default=None, help="Repository-relative identity manifest; omit for the contract default.")
    parser.add_argument("--print-receipt", action="store_true", help="Print the path-free receipt JSON.")
    parser.add_argument("--text-lab-preflight", action="store_true")
    args = parser.parse_args(argv)
    if args.text_lab_preflight:
        print(json.dumps(run_text_lab_preflight(), sort_keys=True))
        return 0
    _, validation, receipt = run_launch(input_identity_arg=args.input_identity)
    print(json.dumps(receipt if args.print_receipt else validation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
