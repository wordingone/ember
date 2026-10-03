#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""G1: refuse protected CONTENT anywhere in a release bundle (spec v6, 9169818b).

The key-name guard in issue1947_release_execute.forbid_protected_bytes catches a protected answer
only when it sits under a key called "gold" or "answer". This guard matches the bytes themselves:
every dict key and every str/bytes leaf is compared against the protected universe by exact
digest, by normalized digest, and by any 24-character window of a normalized protected text.

Authority files are frozen artifacts that carry no self_sha256, so each is loaded by the exact
raw-byte pin held below and never rewritten. A pin changes only through a reviewed source change.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import re
import types
from pathlib import Path
from typing import Any, Iterable

# Raw-byte pins (sha256 of the file bytes exactly as frozen). Spec v6 G-F1 / V5-G-F1-ED99.
UNION_V3_SHA256 = "1b411ba4991df87f0012107e83b82a9457d9bb6628b2acdeca4612192062d80b"
AMENDMENT_V4_SHA256 = "2f545114796dc3dc49bcbc09d848a12e1e3d8a65fdbb7d83ddfee31af89473bd"
POLICY_V2_SHA256 = "490f5014f3839f5a3465f475a1f704666ed25348816d087cae53a57330d4495a"
PRODUCER_CONTRACTS_SHA256 = "ed99bae67b646f2f9973b70f8f58a9a49cb7b70bef7db3b05dfa8b159da547ec"
PINNED_SCHEMA_VERSION = 1

# The normalizer is the reviewed #1581 detector source (mail 48061, 48060), loaded from a file whose
# raw bytes must equal this pin. It exports normalize_n1, normalize_n2 and POLICY_SHA256. Never reimplemented.
NORMALIZER_SHA256 = "cd7097e4296092821b12e650360d4661508cf1e6ace4d4dc73caad77417ea98c"

WINDOW = 24  # ruling 47292: ruled value, no measured basis claimed.
HEX64 = re.compile(r"[0-9a-f]{64}")

# Typed hash fields: a 64-hex leaf is exempt from exact/normalized matching only directly under one
# of these keys of an item, and only when validate_row's own check of it passed.
TYPED_HASH_FIELDS = frozenset({"gold_item_sha256"})


class ProtectedContentRefusal(ValueError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _check_pin(pin: str) -> None:
    if not isinstance(pin, str) or HEX64.fullmatch(pin) is None:
        raise ProtectedContentRefusal("PIN_MALFORMED")


def load_raw_pinned(path: Path, pin: str, label: str) -> dict[str, Any]:
    """Load a frozen artifact by its exact raw-byte pin; never mutate it."""
    _check_pin(pin)
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ProtectedContentRefusal(f"PROTECTED_SET_UNAVAILABLE:{label}:unreadable") from exc
    if _sha(raw) != pin:
        raise ProtectedContentRefusal(f"PROTECTED_SET_UNAVAILABLE:{label}:pin_mismatch")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtectedContentRefusal(f"PROTECTED_SET_UNAVAILABLE:{label}:undecodable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != PINNED_SCHEMA_VERSION:
        raise ProtectedContentRefusal(f"PROTECTED_SET_UNAVAILABLE:{label}:schema")
    return value


def load_self_hashed(path: Path, label: str) -> dict[str, Any]:
    """Load a produced receipt that carries its own self_sha256 (canonical JSON without it)."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtectedContentRefusal(f"PROTECTED_SET_UNAVAILABLE:{label}:unreadable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != PINNED_SCHEMA_VERSION:
        raise ProtectedContentRefusal(f"PROTECTED_SET_UNAVAILABLE:{label}:schema")
    body = dict(value)
    claimed = body.pop("self_sha256", None)
    canon = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    if not isinstance(claimed, str) or claimed != _sha(canon):
        raise ProtectedContentRefusal(f"PROTECTED_SET_UNAVAILABLE:{label}:self_hash")
    return value


def load_normalizer(path: Path, pin: str = NORMALIZER_SHA256):
    """Import the reviewed detector source from `path`, refusing unless its raw bytes equal `pin`."""
    _check_pin(pin)
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ProtectedContentRefusal("NORMALIZER_UNAVAILABLE") from exc
    if _sha(raw) != pin:
        raise ProtectedContentRefusal("NORMALIZER_PIN_MISMATCH")
    spec = importlib.util.spec_from_file_location("issue1947_bound_normalizer", path)
    if spec is None or spec.loader is None:
        raise ProtectedContentRefusal("NORMALIZER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, "POLICY_SHA256", None) != POLICY_V2_SHA256:
        raise ProtectedContentRefusal("NORMALIZER_POLICY_MISMATCH")
    n1, n2 = getattr(module, "normalize_n1", None), getattr(module, "normalize_n2", None)
    if not callable(n1) or not callable(n2):
        raise ProtectedContentRefusal("NORMALIZER_UNAVAILABLE")
    return types.SimpleNamespace(n1=n1, n2=n2)


class ProtectedIndex:
    """Exact digests, normalized digests and the 24-char window set of the resolved universe."""

    def __init__(self, records: Iterable[dict[str, Any]], normalizer) -> None:
        self.exact: set[str] = set()
        self.normalized: set[str] = set()
        self.windows: set[str] = set()
        self.n2 = normalizer.n2
        for record in records:
            text = record.get("text")
            raw = record.get("raw_sha256")
            if isinstance(raw, str) and HEX64.fullmatch(raw):
                self.exact.add(raw)
            if isinstance(text, str):
                self.exact.add(_sha(text.encode("utf-8")))
                norm = self.n2(text)
                self.normalized.add(_sha(norm.encode("utf-8")))
                for i in range(len(norm) - WINDOW + 1):
                    self.windows.add(norm[i:i + WINDOW])

    def match(self, leaf: str | bytes, *, exact_ok: bool, fragment_ok: bool) -> str | None:
        raw = leaf if isinstance(leaf, bytes) else leaf.encode("utf-8")
        if exact_ok and _sha(raw) in self.exact:
            return "PROTECTED_CONTENT_EXACT"
        if isinstance(leaf, bytes):
            try:
                leaf = leaf.decode("utf-8")
            except UnicodeDecodeError:
                return None
        norm = self.n2(leaf)
        if exact_ok and _sha(norm.encode("utf-8")) in self.normalized:
            return "PROTECTED_CONTENT_NORMALIZED"
        if fragment_ok:
            for i in range(len(norm) - WINDOW + 1):
                if norm[i:i + WINDOW] in self.windows:
                    return "PROTECTED_CONTENT_EMBEDDED"
        return None


def coverage_status(index_receipt: dict[str, Any], contracts: dict[str, Any]) -> tuple[str, list[str]]:
    """COMPLETE only when every declared record/id/field/media/role count is observed exactly."""
    expected = contracts.get("coverage_expected") or {}
    observed = index_receipt.get("coverage_observed") or {}
    missing = []
    if not expected:
        missing.append("contracts:coverage_expected_absent")
    for key, want in sorted(expected.items()):
        if observed.get(key) != want:
            missing.append(f"{key}:{observed.get(key)}!={want}")
    return ("COMPLETE" if not missing else "INCOMPLETE"), missing


def _bound_prediction(item: dict[str, Any], producer_predictions: dict[str, str]) -> bool:
    pred = item.get("prediction")
    if not isinstance(pred, str):
        return False
    bound = producer_predictions.get(item.get("item_id"))
    return isinstance(bound, str) and bound == _sha(pred.encode("utf-8"))


def scan(
    bundle: Any,
    index: ProtectedIndex,
    *,
    validated_items: set[int] = frozenset(),
    producer_predictions: dict[str, str] | None = None,
) -> None:
    """Refuse on the first protected key or leaf. validated_items holds id() of item dicts that
    validate_row admitted; producer_predictions maps item_id -> prediction sha bound by the
    re-verified producer receipt."""
    producer_predictions = producer_predictions or {}

    def walk(value: Any, path: str, parent: Any, key: str | None) -> None:
        if isinstance(value, dict):
            for k, child in value.items():
                if isinstance(k, str):
                    hit = index.match(k, exact_ok=True, fragment_ok=True)
                    if hit:
                        raise ProtectedContentRefusal(f"{hit}:{path}")
                walk(child, f"{path}.{k}", value, k)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, f"{path}[{i}]", value, None)
        elif isinstance(value, (str, bytes)):
            in_item = isinstance(parent, dict) and id(parent) in validated_items
            typed_hash = (
                in_item and key in TYPED_HASH_FIELDS and isinstance(value, str)
                and HEX64.fullmatch(value) is not None
            )
            bound_pred = in_item and key == "prediction" and _bound_prediction(parent, producer_predictions)
            if bound_pred:
                return
            hit = index.match(value, exact_ok=not typed_hash, fragment_ok=not typed_hash)
            if hit:
                raise ProtectedContentRefusal(f"{hit}:{path}")

    walk(bundle, "bundle", None, None)


def check_bundle(
    bundle: Any,
    *,
    index: ProtectedIndex,
    claim: str,
    coverage: tuple[str, list[str]],
    validated_items: set[int] = frozenset(),
    producer_predictions: dict[str, str] | None = None,
) -> dict[str, Any]:
    status, missing = coverage
    if claim == "COMPLETE" and status != "COMPLETE":
        raise ProtectedContentRefusal(f"PROTECTED_UNIVERSE_INCOMPLETE:{missing[0]}")
    if claim not in {"COMPLETE", "INCOMPLETE"}:
        raise ProtectedContentRefusal(f"CLAIM_UNKNOWN:{claim}")
    scan(bundle, index, validated_items=validated_items, producer_predictions=producer_predictions)
    return {"status": "ACCEPTED", "claim": claim, "coverage": status, "unresolved": missing}
