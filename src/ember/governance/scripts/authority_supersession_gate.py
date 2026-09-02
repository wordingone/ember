#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Shared fail-closed consumer for Ember's authority supersession crosswalk."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


CROSSWALK_PATH = (
    Path("manifests")
    / "authority"
    / "issue-35-authority-supersession-crosswalk-v1.json"
)
MATRIX_PATH = (
    Path("docs")
    / "domains"
    / "governance"
    / "authority"
    / "ember-authority-matrix.md"
)
MATRIX_PATHS = (
    Path("docs") / "ember-authority-matrix.md",
    Path("docs") / "authority" / "ember-authority-matrix.md",
    MATRIX_PATH,
)
VERIFIER_PATH = (
    Path("src")
    / "ember"
    / "governance"
    / "scripts"
    / "verify_authority_supersession_crosswalk.py"
)
VERIFIER_PATHS = (
    Path("scripts") / "verify_authority_supersession_crosswalk.py",
    VERIFIER_PATH,
)


class AuthoritySupersessionGateError(ValueError):
    """The current-authority crosswalk is absent, malformed, or stale."""


def _select_unique_path(root: Path, label: str, candidates: tuple[Path, ...]) -> Path | None:
    present = [candidate for candidate in candidates if (root / candidate).is_file()]
    if len(present) > 1:
        rendered = ", ".join(path.as_posix() for path in present)
        raise AuthoritySupersessionGateError(
            f"duplicate {label} layouts; expected exactly one, found: {rendered}"
        )
    return present[0] if present else None


def _load_verifier(root: Path):
    relative = _select_unique_path(root, "authority supersession verifier", VERIFIER_PATHS)
    if relative is None:
        raise AuthoritySupersessionGateError(
            "authority supersession verifier is absent: "
            + ", ".join(path.as_posix() for path in VERIFIER_PATHS)
        )
    path = root / relative
    spec = importlib.util.spec_from_file_location(
        "ember_authority_supersession_verifier", path
    )
    if spec is None or spec.loader is None:
        raise AuthoritySupersessionGateError("cannot load authority supersession verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_current_authority_crosswalk(
    root: Path,
    *,
    require_current_authority: bool = True,
) -> dict[str, Any] | None:
    """Validate the canonical packet when the current D-matrix is present.

    Legacy isolated fixtures without a current authority matrix may opt out.
    A real current-authority tree may never omit the packet or verifier.
    """

    root = root.resolve()
    matrix_path = _select_unique_path(root, "current authority matrix", MATRIX_PATHS)
    if matrix_path is None:
        if require_current_authority:
            raise AuthoritySupersessionGateError(
                "current authority matrix is absent: "
                + ", ".join(path.as_posix() for path in MATRIX_PATHS)
            )
        return None
    crosswalk = root / CROSSWALK_PATH
    if not crosswalk.is_file():
        raise AuthoritySupersessionGateError(
            f"authority supersession crosswalk is absent: {CROSSWALK_PATH.as_posix()}"
        )
    try:
        payload = json.loads(crosswalk.read_text(encoding="utf-8", errors="strict"))
        module = _load_verifier(root)
        return module.validate_crosswalk(root, payload)
    except AuthoritySupersessionGateError:
        raise
    except Exception as exc:
        raise AuthoritySupersessionGateError(str(exc)) from exc
