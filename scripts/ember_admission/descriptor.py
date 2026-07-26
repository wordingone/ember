# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed input-descriptor validation for the owned-admission producer."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Mapping


ROLE_KEYS = {"role", "path", "sha256"}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ROLE_RE = re.compile(r"[a-z][a-z0-9_.-]*")
REQUIRED_ROLES = {
    "artifact_bundle",
    "checkpoint",
    "identity_trusted_verifier_registry",
    "identity_manifest",
    "receipt_bundle",
    "restart_model_config",
    "restart_run_manifest",
    "tensor_hashes",
    "tensor_manifest",
    "restart_trusted_verifier_registry",
}


def _valid_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    if any(character.isspace() or ord(character) < 32 for character in value):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and ":" not in path.parts[0]
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.as_posix() == value
    )


def validate_descriptor(payload: Mapping[str, Any]) -> None:
    candidate_id = payload.get("candidate_id")
    if (
        not isinstance(candidate_id, str)
        or ROLE_RE.fullmatch(candidate_id) is None
    ):
        raise ValueError("descriptor.candidate_id")
    rows = payload.get("roles")
    if not isinstance(rows, list):
        raise ValueError("descriptor.roles")
    names: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != ROLE_KEYS:
            raise ValueError("descriptor.roles")
        role = row.get("role")
        allowed_role = (
            isinstance(role, str)
            and (
                role in REQUIRED_ROLES
                or (
                    role.startswith("restart_dependency:")
                    and ROLE_RE.fullmatch(role.removeprefix("restart_dependency:"))
                    is not None
                )
            )
        )
        if not allowed_role:
            raise ValueError("descriptor.roles")
        if not _valid_relative_path(row.get("path")):
            raise ValueError("descriptor.path")
        if (
            not isinstance(row.get("sha256"), str)
            or SHA256_RE.fullmatch(row["sha256"]) is None
        ):
            raise ValueError("descriptor.sha256")
        names.append(role)
    if len(names) != len(set(names)) or not REQUIRED_ROLES.issubset(names):
        raise ValueError("descriptor.roles")
