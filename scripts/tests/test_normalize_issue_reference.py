#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for normalize_issue_reference (docs/spec/issue-reference-v1.md, R4)."""

import json
import tempfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from normalize_issue_reference import (  # noqa: E402
    AmbiguousReferenceError,
    Sidecar,
    normalize,
)


def _sidecar(boundary=200, mapping=None):
    return Sidecar(genesis_boundary=boundary, mapping=mapping or {})


# --- explicit-qualifier canonicalization -----------------------------------

def test_explicit_legacy_qualifier():
    assert normalize("legacy:12", _sidecar(), strict=True) == "legacy:12"


def test_explicit_github_qualifier():
    assert normalize("github:29", _sidecar(), strict=True) == "github:29"


def test_explicit_unknown_qualifier_passes_through():
    assert normalize("unknown:5", _sidecar(), strict=True) == "unknown:5"


def test_alias_legacy():
    assert normalize("L#207", _sidecar(), strict=True) == "legacy:207"


def test_alias_github():
    assert normalize("gh#29", _sidecar(), strict=True) == "github:29"
    assert normalize("GH-29", _sidecar(), strict=True) == "github:29"


def test_qualifier_needs_no_sidecar():
    # An explicit qualifier resolves even with an empty sidecar in strict mode.
    assert normalize("legacy:207", Sidecar.empty(), strict=True) == "legacy:207"


# --- genesis boundary -------------------------------------------------------

def test_above_boundary_is_unambiguously_github():
    # boundary 200; #250 exceeds the legacy range -> github, no map entry needed.
    assert normalize("#250", _sidecar(boundary=200), strict=True) == "github:250"


def test_at_or_below_boundary_is_ambiguous_without_map():
    # #150 <= boundary 200 and unmapped -> ambiguous.
    with tempfile.TemporaryDirectory():
        try:
            normalize("#150", _sidecar(boundary=200), strict=True)
        except AmbiguousReferenceError:
            pass
        else:
            raise AssertionError("expected AmbiguousReferenceError for in-range bare ref")


def test_boundary_exact_value_is_in_range():
    # #200 == boundary is still within the legacy range (not strictly greater).
    try:
        normalize("#200", _sidecar(boundary=200), strict=True)
    except AmbiguousReferenceError:
        pass
    else:
        raise AssertionError("boundary value itself must be treated as ambiguous")


# --- fail closed on ambiguous unqualified refs ------------------------------

def test_strict_fails_closed_on_bare_ambiguous():
    try:
        normalize("#207", _sidecar(boundary=300), strict=True)
    except AmbiguousReferenceError:
        pass
    else:
        raise AssertionError("strict mode must fail closed on ambiguous #207")


def test_no_sidecar_makes_every_bare_ref_ambiguous():
    # Empty sidecar => genesis_boundary is +inf => even a large number is ambiguous.
    try:
        normalize("#99999", Sidecar.empty(), strict=True)
    except AmbiguousReferenceError:
        pass
    else:
        raise AssertionError("with no sidecar, every bare ref must be ambiguous in strict mode")


def test_lenient_returns_unknown_not_a_guess():
    assert normalize("#207", _sidecar(boundary=300), strict=False) == "unknown:207"


# --- sidecar mapping resolves; bytes are not mutated ------------------------

def test_sidecar_map_resolves_in_range_ref():
    sc = _sidecar(boundary=300, mapping={"207": "legacy"})
    assert normalize("#207", sc, strict=True) == "legacy:207"


def test_sidecar_map_can_pin_above_boundary_to_legacy():
    sc = _sidecar(boundary=100, mapping={"250": "legacy"})
    assert normalize("#250", sc, strict=True) == "legacy:250"


def test_sidecar_is_resolution_not_mutation():
    # The sidecar is a separate document; resolving a ref never touches the
    # source that cites it. We assert the citing bytes are unchanged after
    # resolution.
    with tempfile.TemporaryDirectory() as tmp:
        citing = Path(tmp) / "CLAIMS.md"
        original = "See #207 and #29 for context.\n"
        citing.write_text(original, encoding="utf-8")

        side = Path(tmp) / "sidecar.json"
        side.write_text(json.dumps({"genesis_boundary": 300, "map": {"207": "legacy", "29": "github"}}), encoding="utf-8")

        sc = Sidecar.from_path(side)
        assert normalize("#207", sc, strict=True) == "legacy:207"
        assert normalize("#29", sc, strict=True) == "github:29"
        # The historical file is byte-identical — resolution mutated nothing.
        assert citing.read_text(encoding="utf-8") == original


def test_sidecar_from_dict_roundtrip():
    sc = Sidecar.from_dict({"genesis_boundary": 200, "map": {"5": "github"}})
    assert normalize("#5", sc, strict=True) == "github:5"


# --- negative control: unqualifiable ref stays unknown, never guessed -------

def test_negative_control_unparseable_is_unknown_not_guessed():
    # A genuinely unqualifiable ref must NOT be guessed into a real era.
    assert normalize("not-an-issue", _sidecar(), strict=False).startswith("unknown:")


def test_negative_control_unparseable_fails_closed_in_strict():
    try:
        normalize("not-an-issue", _sidecar(), strict=True)
    except AmbiguousReferenceError:
        pass
    else:
        raise AssertionError("unparseable ref must fail closed in strict mode")


# --- validation of sidecar inputs ------------------------------------------

def test_invalid_era_in_sidecar_rejected():
    try:
        Sidecar(genesis_boundary=10, mapping={"5": "made-up"})
    except ValueError:
        pass
    else:
        raise AssertionError("sidecar must reject a non-legacy/github era")


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc!r}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
