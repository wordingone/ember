# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for the corpus receipt generator.

Each test targets a way the receipt could report a comfortable wrong answer rather than a way it
could crash. The failure mode this generator exists to prevent is a plausible number, not an
exception: an inflated total from double-counting overlapping catalogs, a near-duplicate figure that
is really an exact-duplicate figure, or a receipt of zeroes emitted for a glob that matched nothing.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "ember" / "governance" / "scripts" / "corpus_receipt.py"
)

# The root is derived from this file's own location, never from an environment variable: an
# environment override is itself a way to make a root not location-derived, which is the property
# the repository's self-location gate exists to hold.
_spec = importlib.util.spec_from_file_location("_corpus_receipt_under_test", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
corpus_receipt = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = corpus_receipt
_spec.loader.exec_module(corpus_receipt)


def write_catalog(path: Path, records: list[tuple[str, str, dict]]) -> Path:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE data_catalog_records("
            "kind TEXT NOT NULL, record_id TEXT NOT NULL, payload_json TEXT NOT NULL,"
            "PRIMARY KEY(kind, record_id))"
        )
        connection.executemany(
            "INSERT INTO data_catalog_records(kind, record_id, payload_json) VALUES(?,?,?)",
            [(kind, record_id, json.dumps(payload)) for kind, record_id, payload in records],
        )
        connection.commit()
    finally:
        connection.close()
    return path


def object_record(digest: str, byte_count: int, media_type: str) -> tuple[str, str, dict]:
    return (
        "immutable_object",
        f"sha256:{digest}",
        {
            "id": f"sha256:{digest}",
            "sha256": digest,
            "byte_count": byte_count,
            "media_type": media_type,
            "locator": f"sha256/{digest[:2]}/{digest}",
            "custody_state": "available",
        },
    )


def membership_record(
    digest: str, domain: str, split: str, cluster: str | None = None
) -> tuple[str, str, dict]:
    return (
        "membership",
        f"membership:{domain}-{split}:{digest}",
        {
            "id": f"membership:{domain}-{split}:{digest}",
            "domain": domain,
            "split": split,
            "exact_sha256": digest,
            "near_dedup_cluster": cluster if cluster is not None else f"sha256:{digest}",
            "admission_state": "admitted",
            "tokenizer_sha256": "e" * 64,
        },
    )


def source_record(url: str, licence_digest: str) -> tuple[str, str, dict]:
    return (
        "source",
        f"source:{licence_digest[:8]}",
        {
            "id": f"source:{licence_digest[:8]}",
            "canonical_url": url,
            "revision": "sha256:" + "0" * 64,
            "license_text_sha256": licence_digest,
            "license_verdict": "accepted",
            "access_class": "public",
            "acquired_at_ms": 1,
            "refusal_reason": None,
        },
    )


@pytest.fixture()
def two_overlapping_catalogs(tmp_path: Path) -> list[str]:
    """Two catalogs that share one object, as the per-domain catalogs really do."""
    shared = "a" * 64
    only_first = "b" * 64
    only_second = "c" * 64

    write_catalog(
        tmp_path / "first.sqlite3",
        [
            source_record("https://example.invalid/one", "1" * 64),
            object_record(shared, 1_000, "text/plain; charset=utf-8"),
            object_record(only_first, 3_000, "application/pdf"),
            membership_record(shared, "mathematics", "train"),
            membership_record(only_first, "mathematics", "train"),
        ],
    )
    write_catalog(
        tmp_path / "second.sqlite3",
        [
            source_record("https://other.invalid/two", "2" * 64),
            object_record(shared, 1_000, "text/plain; charset=utf-8"),
            object_record(only_second, 6_000, "image/png"),
            membership_record(shared, "mathematics", "train"),
            membership_record(only_second, "statistics", "heldout"),
        ],
    )
    return [str(tmp_path / "*.sqlite3")]


def test_overlapping_catalogs_are_not_double_counted(two_overlapping_catalogs: list[str]) -> None:
    """The shared object contributes its bytes once, not once per catalog."""
    paths = sorted(Path(two_overlapping_catalogs[0]).parent.glob("*.sqlite3"))
    receipt = corpus_receipt.build_receipt([str(p) for p in paths])

    assert receipt["distinct_admitted_objects"] == 3
    # 1,000 + 3,000 + 6,000 -- the shared 1,000 counted once even though two catalogs carry it.
    assert receipt["raw_bytes"] == 10_000


def test_mass_and_count_rank_domains_differently(two_overlapping_catalogs: list[str]) -> None:
    """statistics holds fewer objects than mathematics and more bytes; both are reported."""
    paths = sorted(Path(two_overlapping_catalogs[0]).parent.glob("*.sqlite3"))
    receipt = corpus_receipt.build_receipt([str(p) for p in paths])

    maths = receipt["domains_by_mass"]["mathematics/train"]
    stats = receipt["domains_by_mass"]["statistics/heldout"]
    assert maths["objects"] > stats["objects"]
    assert maths["bytes"] < stats["bytes"]


def test_near_dedup_is_reported_uninformative_when_cluster_is_the_digest(
    two_overlapping_catalogs: list[str],
) -> None:
    """Every object being its own cluster must be reported as no information, not as full dedup."""
    paths = sorted(Path(two_overlapping_catalogs[0]).parent.glob("*.sqlite3"))
    receipt = corpus_receipt.build_receipt([str(p) for p in paths])
    assert receipt["near_dedup_informative"] is False


def test_near_dedup_is_reported_informative_when_clusters_merge(tmp_path: Path) -> None:
    """The same check must be able to report True, or it is a check that cannot change state."""
    first, second = "d" * 64, "e" * 64
    write_catalog(
        tmp_path / "merged.sqlite3",
        [
            object_record(first, 10, "text/plain; charset=utf-8"),
            object_record(second, 10, "text/plain; charset=utf-8"),
            membership_record(first, "mathematics", "train", cluster="cluster:shared"),
            membership_record(second, "mathematics", "train", cluster="cluster:shared"),
        ],
    )
    receipt = corpus_receipt.build_receipt([str(tmp_path / "merged.sqlite3")])
    assert receipt["near_dedup_informative"] is True


def test_unmeasured_properties_are_named_not_zeroed(two_overlapping_catalogs: list[str]) -> None:
    """Language, tokens and rejection rates appear as reasons, never as numeric zeroes."""
    paths = sorted(Path(two_overlapping_catalogs[0]).parent.glob("*.sqlite3"))
    receipt = corpus_receipt.build_receipt([str(p) for p in paths])

    unmeasured = receipt["unmeasured_properties"]
    for name in (
        "languages",
        "total_admitted_tokens",
        "normalized_text_bytes",
        "duplicate_rejection_rate",
        "quality_rejection_rate",
        "redistribution_rights",
    ):
        assert name in unmeasured, name
        assert unmeasured[name], f"{name} must carry a reason"
        assert name not in receipt, f"{name} must not also appear as a number"


def test_snapshot_id_changes_when_the_split_changes(tmp_path: Path) -> None:
    """Re-splitting the same bytes is a different corpus and must produce a different id."""
    digest = "f" * 64
    write_catalog(
        tmp_path / "train.sqlite3",
        [object_record(digest, 5, "text/plain"), membership_record(digest, "maths", "train")],
    )
    write_catalog(
        tmp_path / "heldout.sqlite3",
        [object_record(digest, 5, "text/plain"), membership_record(digest, "maths", "heldout")],
    )
    train = corpus_receipt.build_receipt([str(tmp_path / "train.sqlite3")])
    heldout = corpus_receipt.build_receipt([str(tmp_path / "heldout.sqlite3")])
    assert train["corpus_snapshot_id"] != heldout["corpus_snapshot_id"]


def test_snapshot_id_is_stable_across_catalog_ordering(
    two_overlapping_catalogs: list[str],
) -> None:
    """The id must depend on the corpus, not on the order the catalogs happened to be read."""
    paths = [str(p) for p in sorted(Path(two_overlapping_catalogs[0]).parent.glob("*.sqlite3"))]
    assert (
        corpus_receipt.build_receipt(paths)["corpus_snapshot_sha256"]
        == corpus_receipt.build_receipt(list(reversed(paths)))["corpus_snapshot_sha256"]
    )


def test_empty_glob_refuses_rather_than_emitting_zeroes(tmp_path: Path) -> None:
    """A receipt of zeroes is indistinguishable from an empty corpus, so it must not be emitted."""
    with pytest.raises(SystemExit) as excinfo:
        corpus_receipt.main(["--roots", str(tmp_path / "nothing-*.sqlite3")])
    assert excinfo.value.code != 0


def test_unparseable_payloads_are_counted_not_dropped_silently(tmp_path: Path) -> None:
    """A record the reader cannot parse is surfaced, because silent loss looks like absence."""
    path = tmp_path / "damaged.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE data_catalog_records("
            "kind TEXT NOT NULL, record_id TEXT NOT NULL, payload_json TEXT NOT NULL,"
            "PRIMARY KEY(kind, record_id))"
        )
        connection.execute(
            "INSERT INTO data_catalog_records VALUES('source','source:bad','{not json')")
        connection.commit()
    finally:
        connection.close()

    receipt = corpus_receipt.build_receipt([str(path)])
    assert receipt["unparseable_records"] == 1


def test_media_family_classes_the_modalities_the_corpus_actually_holds() -> None:
    assert corpus_receipt.media_family("text/plain; charset=utf-8") == "text"
    assert corpus_receipt.media_family("application/x-ndjson+zstd") == "application"
    assert corpus_receipt.media_family("video/mp4") == "video"
    assert corpus_receipt.media_family("audio/flac") == "audio"
    assert corpus_receipt.media_family(None) == "<unstated>"


def test_source_family_reports_unstated_rather_than_guessing() -> None:
    assert corpus_receipt.source_family("https://huggingface.co/datasets/x") == "huggingface.co"
    assert corpus_receipt.source_family("not-a-url") == "<unstated>"
    assert corpus_receipt.source_family(None) == "<unstated>"
