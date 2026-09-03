# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""RED-first contract for the #1975 expand/migrate/contract layout seam."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from repository_layout import (  # noqa: E402
    LayoutAuthority,
    LayoutPair,
    resolve_closed_layout_pair,
    resolve_repository_authority,
)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def pair() -> LayoutPair:
    return LayoutPair(
        name="fixture",
        canonical_relative="domains/model/canonical.bin",
        canonical_sha256=sha256(b"canonical"),
        legacy_relative="legacy/legacy.bin",
        legacy_sha256=sha256(b"legacy"),
    )


@pytest.mark.parametrize(
    ("selected", "expected_relative", "expected_raw"),
    [
        ("legacy", "legacy/legacy.bin", b"legacy"),
        ("canonical", "domains/model/canonical.bin", b"canonical"),
    ],
)
def test_closed_pair_selects_one_atomic_path_and_pin(
    tmp_path: Path,
    selected: str,
    expected_relative: str,
    expected_raw: bytes,
) -> None:
    spec = pair()
    relative = (
        spec.legacy_relative if selected == "legacy" else spec.canonical_relative
    )
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(expected_raw)

    resolved = resolve_closed_layout_pair(tmp_path, spec)

    assert resolved == LayoutAuthority(
        name="fixture",
        path=path,
        relative_path=expected_relative,
        expected_sha256=sha256(expected_raw),
    )


@pytest.mark.parametrize("present", ["neither", "both"])
def test_closed_pair_refuses_missing_or_ambiguous_authority(
    tmp_path: Path, present: str
) -> None:
    spec = pair()
    if present == "both":
        for relative, raw in (
            (spec.legacy_relative, b"legacy"),
            (spec.canonical_relative, b"canonical"),
        ):
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
    with pytest.raises(ValueError, match="exactly one"):
        resolve_closed_layout_pair(tmp_path, spec)


def test_closed_pair_refuses_bytes_outside_selected_pin(tmp_path: Path) -> None:
    spec = pair()
    path = tmp_path / spec.legacy_relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash drift"):
        resolve_closed_layout_pair(tmp_path, spec)

@pytest.mark.parametrize(
    "relative",
    [
        "tools/ember-restart-3b/certified_train_launch.py",
        "tools/ember-restart-3b/eval_canary_image.py",
        "tools/ember-restart-3b/launch_packet.py",
        "tools/ember-restart-3b/parameter_counter.py",
        "tools/ember-restart-3b/production_rung.py",
        "tools/ember-restart-3b/remint_specialist_stream.py",
        "tools/ember-restart-3b/serve_owned_openai.py",
    ],
)
def test_production_consumers_use_the_closed_layout_seam(relative: str) -> None:
    source = (ROOT / relative).read_text(encoding="utf-8")
    assert "resolve_repository_authority" in source


@pytest.mark.parametrize(
    "forbidden",
    [
        'ROOT / "tokenizer" / "tokenizer.json"',
        'root / "tokenizer" / "tokenizer.json"',
        'Path("tokenizer/tokenizer.json")',
        'TOKENIZER_RELATIVE = "tokenizer/tokenizer.json"',
        '_P2B_STREAM_MANIFEST_SHA256 = "25d4f681',
        '_P2B_STREAM_BUILD_RECEIPT_SHA256 = "2daf3de3',
    ],
)
def test_production_consumers_have_no_unmediated_transition_authority(
    forbidden: str,
) -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "tools" / "ember-restart-3b").glob("*.py")
    )
    assert forbidden not in source


def test_versioned_pair_prefers_canonical_without_falling_back_on_drift(
    tmp_path: Path,
) -> None:
    spec = LayoutPair(
        name="versioned-fixture",
        canonical_relative="canonical/v2.json",
        canonical_sha256=sha256(b"v2"),
        legacy_relative="legacy/v1.json",
        legacy_sha256=sha256(b"v1"),
        canonical_preferred=True,
    )
    canonical = tmp_path / spec.canonical_relative
    legacy = tmp_path / spec.legacy_relative
    canonical.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    canonical.write_bytes(b"v2")
    legacy.write_bytes(b"v1")

    resolved = resolve_closed_layout_pair(tmp_path, spec)
    assert resolved.path == canonical
    assert resolved.expected_sha256 == sha256(b"v2")

    canonical.write_bytes(b"drifted")
    with pytest.raises(ValueError, match="hash drift"):
        resolve_closed_layout_pair(tmp_path, spec)


@pytest.mark.parametrize(
    "name", ["specialist_stream_manifest", "specialist_stream_build_receipt"]
)
def test_specialist_authorities_declare_canonical_preference(name: str) -> None:
    import repository_layout

    assert repository_layout._AUTHORITIES[name].canonical_preferred is True


@pytest.mark.parametrize(
    "relative",
    [
        "tests/ember_restart_model/fixtures/eval-canary-image-v1/build_fixture.py",
        "tests/ember_restart_model/test_a1_certified_launch.py",
        "tests/ember_restart_model/test_certified_train_launch.py",
        "tests/ember_restart_model/test_checkpoint_artifacts.py",
        "tests/ember_restart_model/test_counter_cli.py",
        "tests/ember_restart_model/test_frozen_tokenizer_decoder.py",
        "tests/ember_restart_model/test_infer.py",
        "tests/ember_restart_model/test_issue1508_attempt_retention_layout.py",
        "tests/ember_restart_model/test_launch_packet.py",
        "tests/ember_restart_model/test_specialist_stream.py",
        "tests/ember_restart_model/test_tokenizer_reconstruction.py",
    ],
)
def test_transition_sensitive_test_consumers_use_repository_layout(
    relative: str,
) -> None:
    source = (ROOT / relative).read_text(encoding="utf-8")
    assert "repository_layout" in source


def test_eval_canary_fixture_names_logical_tokenizer_authority() -> None:
    manifest = (
        ROOT
        / "tests"
        / "ember_restart_model"
        / "fixtures"
        / "eval-canary-image-v1"
        / "manifest.json"
    ).read_text(encoding="utf-8")
    assert '"file": "repository-authority:tokenizer"' in manifest


def test_specialist_pin_tuples_are_atomic_and_closed() -> None:
    import repository_layout

    tuples = repository_layout.allowed_authority_pin_tuples(
        ("specialist_stream_manifest", "specialist_stream_build_receipt")
    )
    assert tuples == (
        (
            "f4a59d65e98a7b90d9e2e6ca49df2dccf334cfbac107793a4d719f3354b1f7b1",
            "26c1c82e91739449eec8a9bf41b1f89f0c091dbd9b8a958f69dcdccd9e89f01d",
        ),
        (
            "25d4f681af1d43c12dda718b7cd0ddf75613a46a7d5053b7ddf5436e0cbf9a22",
            "2daf3de395c83dc19707cb81f31c12c1484d9c19de2249c8eb8aec1b5a179c9d",
        ),
    )
    assert (tuples[0][0], tuples[1][1]) not in tuples
    assert (tuples[1][0], tuples[0][1]) not in tuples
    with pytest.raises(ValueError, match="unknown repository layout authority"):
        repository_layout.allowed_authority_pin_tuples(("unknown",))


@pytest.mark.parametrize("name", sorted((
    "tokenizer",
    "frontier_receipt",
    "specialist_stream_manifest",
    "specialist_stream_build_receipt",
)))
def test_real_authority_selection_matches_declared_mode_and_bytes(name: str) -> None:
    import repository_layout

    pair = repository_layout._AUTHORITIES[name]
    resolved = resolve_repository_authority(ROOT, name)
    canonical_present = (ROOT / pair.canonical_relative).is_file()
    legacy_present = (ROOT / pair.legacy_relative).is_file()
    if pair.canonical_preferred:
        assert canonical_present or legacy_present
        expected_relative = pair.canonical_relative if canonical_present else pair.legacy_relative
    else:
        assert canonical_present != legacy_present
        expected_relative = pair.canonical_relative if canonical_present else pair.legacy_relative
    assert resolved.relative_path == expected_relative
    assert resolved.expected_sha256 == sha256(resolved.path.read_bytes())
