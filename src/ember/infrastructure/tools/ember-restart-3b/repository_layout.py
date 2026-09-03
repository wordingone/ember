# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed expand/migrate/contract repository-layout authorities for #1975."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LayoutPair:
    """One atomic canonical/legacy path-and-pin transition pair."""

    name: str
    canonical_relative: str
    canonical_sha256: str
    legacy_relative: str
    legacy_sha256: str
    # False (strict XOR): relocation pairs — exactly one member may exist.
    # True (canonical-preferred): version-advancement pairs — the historical
    # legacy generation is retained beside the canonical one; the canonical
    # member is selected whenever present and NEVER falls back on hash drift.
    canonical_preferred: bool = False


@dataclass(frozen=True)
class LayoutAuthority:
    """The selected, hash-verified member of a layout pair."""

    name: str
    path: Path
    relative_path: str
    expected_sha256: str


_AUTHORITIES = {
    "tokenizer": LayoutPair(
        name="tokenizer",
        canonical_relative="domains/model/tokenizer/tokenizer.json",
        canonical_sha256="2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97",
        legacy_relative="tokenizer/tokenizer.json",
        legacy_sha256="2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97",
    ),
    "frontier_receipt": LayoutPair(
        name="frontier_receipt",
        canonical_relative="src/ember/governance/scripts/frontier_receipt.py",
        canonical_sha256="53eb74468168995dcb222864841055975ee709cb09a2a905b1ea5cba496428cc",
        legacy_relative="scripts/frontier_receipt.py",
        legacy_sha256="eb7782aeb758ac6c01c28bf19cdd6fd1eaa88d8b47e844394cb06f2a11519cea",
    ),
    "specialist_stream_manifest": LayoutPair(
        name="specialist_stream_manifest",
        canonical_relative="data/ember-restart-3b/owned-specialist-stream-v2-4096.json",
        canonical_sha256="8ac0bf3aa55d0e29c88f35372d33a9dd42d94c0115fc63ada719341528d373c6",
        legacy_relative="data/ember-restart-3b/owned-specialist-stream-v1-4096.json",
        legacy_sha256="9f9f0bba758dd7c0d445ea2bc6ebcb2132917d0214e952e8fbeee70008febe70",
        canonical_preferred=True,
    ),
    "specialist_stream_build_receipt": LayoutPair(
        name="specialist_stream_build_receipt",
        canonical_relative="data/ember-restart-3b/owned-specialist-stream-v2-4096-build-receipt.json",
        canonical_sha256="ba948d5a3c78a03a89227654f96b321c8e3225af6f0d8093198114f035a77a64",
        legacy_relative="data/ember-restart-3b/owned-specialist-stream-v1-4096-build-receipt.json",
        legacy_sha256="2daf3de395c83dc19707cb81f31c12c1484d9c19de2249c8eb8aec1b5a179c9d",
        canonical_preferred=True,
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_closed_layout_pair(repo_root: Path, pair: LayoutPair) -> LayoutAuthority:
    """Resolve exactly one pair member and verify its inseparable content pin."""

    canonical_path = repo_root / pair.canonical_relative
    legacy_path = repo_root / pair.legacy_relative
    canonical_present = canonical_path.is_file()
    legacy_present = legacy_path.is_file()
    if pair.canonical_preferred:
        if not canonical_present and not legacy_present:
            raise ValueError(
                f"layout authority {pair.name} has no canonical or legacy file"
            )
    elif canonical_present == legacy_present:
        raise ValueError(
            f"layout authority {pair.name} requires exactly one canonical or legacy file"
        )
    if canonical_present:
        path = canonical_path
        relative_path = pair.canonical_relative
        expected_sha256 = pair.canonical_sha256
    else:
        path = legacy_path
        relative_path = pair.legacy_relative
        expected_sha256 = pair.legacy_sha256
    actual_sha256 = _sha256(path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"layout authority {pair.name} hash drift: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    return LayoutAuthority(
        name=pair.name,
        path=path,
        relative_path=relative_path,
        expected_sha256=expected_sha256,
    )


def resolve_repository_authority(repo_root: Path, name: str) -> LayoutAuthority:
    """Resolve one named, closed repository-layout authority."""

    try:
        pair = _AUTHORITIES[name]
    except KeyError as error:
        raise ValueError(f"unknown repository layout authority: {name}") from error
    return resolve_closed_layout_pair(repo_root, pair)

def allowed_authority_pin_tuples(names: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """The two allowed atomic pin tuples across named authorities.

    Returns exactly (all-canonical, all-legacy) content pins in the order the
    names were given. A caller admitting only members of this return value can
    never accept a Cartesian mix of generations.
    """

    pairs = []
    for name in names:
        try:
            pairs.append(_AUTHORITIES[name])
        except KeyError as error:
            raise ValueError(f"unknown repository layout authority: {name}") from error
    return (
        tuple(pair.canonical_sha256 for pair in pairs),
        tuple(pair.legacy_sha256 for pair in pairs),
    )
