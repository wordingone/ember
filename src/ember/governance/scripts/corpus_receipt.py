# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Generate a corpus receipt from catalog state, and name every property the catalog cannot answer.

The dataset card for the public mirror has been maintained by hand, which means the corpus's
scientific composition is asserted rather than derived. This reads the data catalog -- the
authoritative record, content-addressed and independent of where any file currently sits -- and
emits the composition as a receipt bound to a snapshot digest.

Three commitments hold this together, and each of them exists because its opposite has already
produced a wrong answer somewhere in this repository.

**An unmeasurable property is reported as UNMEASURED, never as zero.** A composition report whose
absent fields render as empty categories is worse than no report, because an empty category reads
as a finding. Every requested property appears in the output with either a number or the reason the
catalog cannot yield one.

**Fields are selected by NAME.** Record payloads carry several digests and several timestamps;
selecting "the hash" or "the first integer" yields a plausible value that survives inspection and
is wrong.

**Mass is reported alongside count.** Object counts and byte mass rank the corpus differently -- one
domain can hold half the objects and a twentieth of the bytes -- and a sampler draws on mass. A
count-only distribution is a shape claim wearing a distribution claim's clothes.

Catalog roots are supplied by the caller. There is deliberately no absolute default: a checked-in
absolute path is a root this repository's own self-location gate refuses, and it would bind the
receipt to one host.
"""
from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import sqlite3
from typing import Any

SCHEMA_VERSION = "ember-corpus-receipt/v1"

RECORD_KINDS = (
    "source",
    "immutable_object",
    "dataset_version",
    "transform",
    "membership",
    "protected_eval",
    "consumer_attempt",
    "experience",
    "receipt",
)

# Every property the corpus's scientific-observability contract asks for, mapped to how this script
# answers it. A value beginning with "gap:" is one the catalog structurally cannot answer; those are
# emitted in `unmeasured_properties` so a reader never mistakes silence for a zero.
REQUESTED_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("acquired_sources", "count of source records"),
    ("admitted_memberships", "membership rows by admission_state"),
    ("raw_bytes", "sum of immutable_object.byte_count over distinct digests"),
    ("major_domains", "membership.domain, by count and by mass"),
    ("source_families", "source.canonical_url host distribution"),
    ("modality_coverage", "immutable_object.media_type, by count and by mass"),
    ("split_partition", "membership.split, by count and by mass"),
    ("licence_status", "source.license_verdict and distinct license_text_sha256"),
    ("tokenizer_identity", "membership.tokenizer_sha256"),
    ("corpus_snapshot_id", "digest over the admitted identity set, computed here"),
    ("exact_deduplication", "distinct exact_sha256 against membership count"),
    (
        "near_deduplication",
        "gap: near_dedup_cluster is projected as the object's own digest, so every"
        " object is its own cluster and the field carries no near-duplicate information",
    ),
    (
        "languages",
        "gap: no record kind carries a language field, so the mirror's language"
        " metadata is asserted rather than measured",
    ),
    (
        "total_admitted_tokens",
        "gap: memberships carry byte windows (window_start, window_end), not token counts",
    ),
    (
        "normalized_text_bytes",
        "gap: there is no normalized-artifact record kind, so the source -> normalized ->"
        " admitted -> tokenized chain has no second link to measure",
    ),
    (
        "duplicate_rejection_rate",
        "gap: rejection is representable at the source level (license_verdict refused) but"
        " not at the document level, so a rejected document leaves no row to count",
    ),
    (
        "quality_rejection_rate",
        "gap: same -- a document filtered during admission leaves no catalog row",
    ),
    (
        "redistribution_rights",
        "gap: license_verdict is a two-value enum, so acquire, train and redistribute are"
        " fused into one boolean; a public mirror needs them separable",
    ),
    (
        "eval_overlap_measurement",
        "gap: the train/heldout split is recorded, but no measured overlap check is stored",
    ),
)


class CatalogReadError(RuntimeError):
    """A catalog database could not be read as catalog state."""


def load_records(path: str) -> tuple[list[dict[str, Any]], int]:
    """Read every catalog record from one database, read-only.

    ``immutable=1`` keeps this off the write-ahead log: a live projector may hold the writer lock,
    and a census must never be the reason a projection fails.
    """
    try:
        connection = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
    except sqlite3.Error as error:  # pragma: no cover - surfaced with the path attached
        raise CatalogReadError(f"catalog unreadable: {path}") from error
    try:
        rows = connection.execute(
            "select kind, record_id, payload_json from data_catalog_records"
        ).fetchall()
    except sqlite3.Error as error:
        raise CatalogReadError(f"catalog has no record table: {path}") from error
    finally:
        connection.close()

    records: list[dict[str, Any]] = []
    unparseable = 0
    for kind, record_id, payload in rows:
        try:
            body = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            unparseable += 1
            continue
        if not isinstance(body, dict):
            unparseable += 1
            continue
        body["_kind"] = kind
        body["_record_id"] = record_id
        records.append(body)
    return records, unparseable


def source_family(url: object) -> str:
    """The host a source was acquired from, or an explicit unstated marker."""
    if not isinstance(url, str) or "://" not in url:
        return "<unstated>"
    return url.split("://", 1)[1].split("/", 1)[0].lower()


def media_family(media_type: object) -> str:
    """The top-level modality of a media type: text, image, audio, video, application."""
    if not isinstance(media_type, str) or "/" not in media_type:
        return "<unstated>"
    return media_type.split(";", 1)[0].split("/", 1)[0].strip().lower()


def build_receipt(catalog_paths: list[str]) -> dict[str, Any]:
    """Aggregate every catalog into one receipt, deduplicating records by identity.

    The per-domain and per-split catalogs overlap by construction, so records are keyed by
    ``(kind, record_id)``. Summing the catalogs instead would multiply-count every shared object,
    which inflates precisely the totals a reader trusts most.
    """
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    unparseable = 0
    for path in catalog_paths:
        records, bad = load_records(path)
        unparseable += bad
        for record in records:
            seen.setdefault((record["_kind"], record["_record_id"]), record)

    by_kind = collections.Counter(kind for kind, _ in seen)
    sources = [r for r in seen.values() if r["_kind"] == "source"]
    objects = [r for r in seen.values() if r["_kind"] == "immutable_object"]
    memberships = [r for r in seen.values() if r["_kind"] == "membership"]
    datasets = [r for r in seen.values() if r["_kind"] == "dataset_version"]

    # Object identity is its digest, so mass is summed over distinct digests rather than over
    # records: the same object admitted into two domains is one object's worth of bytes.
    size_of: dict[str, int] = {}
    media_of: dict[str, str] = {}
    for record in objects:
        digest = record.get("sha256")
        if not isinstance(digest, str) or digest in size_of:
            continue
        byte_count = record.get("byte_count")
        size_of[digest] = byte_count if isinstance(byte_count, int) else 0
        media_of[digest] = str(record.get("media_type", "<unstated>"))

    domain_count: collections.Counter[tuple[str, str]] = collections.Counter()
    domain_mass: collections.Counter[tuple[str, str]] = collections.Counter()
    modality_count: collections.Counter[str] = collections.Counter()
    modality_mass: collections.Counter[str] = collections.Counter()
    split_count: collections.Counter[str] = collections.Counter()
    split_mass: collections.Counter[str] = collections.Counter()
    admission = collections.Counter(
        str(m.get("admission_state", "<unstated>")) for m in memberships)
    tokenizers = collections.Counter(
        str(m.get("tokenizer_sha256", "<unstated>")) for m in memberships)

    unresolved = 0
    exact_digests: set[str] = set()
    clusters: set[str] = set()
    for membership in memberships:
        digest = membership.get("exact_sha256")
        cluster = membership.get("near_dedup_cluster")
        if isinstance(cluster, str):
            clusters.add(cluster)
        if not isinstance(digest, str) or digest not in size_of:
            unresolved += 1
            continue
        exact_digests.add(digest)
        size = size_of[digest]
        domain = str(membership.get("domain", "<unstated>"))
        split = str(membership.get("split", "<unstated>"))
        domain_count[(domain, split)] += 1
        domain_mass[(domain, split)] += size
        split_count[split] += 1
        split_mass[split] += size
        family = media_family(media_of.get(digest))
        modality_count[family] += 1
        modality_mass[family] += size

    # The snapshot digest covers the admitted identity set -- content, domain and split -- so two
    # runs that drew from the same corpus produce the same id, and any admission or re-split
    # changes it.
    identity_lines = sorted(
        f"{m.get('exact_sha256')}:{m.get('domain')}:{m.get('split')}" for m in memberships)
    snapshot = hashlib.sha256("\n".join(identity_lines).encode("utf-8")).hexdigest()

    licence_texts = {
        s.get("license_text_sha256") for s in sources
        if isinstance(s.get("license_text_sha256"), str)
    }
    total_mass = sum(size_of.values())

    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_snapshot_id": f"ec-{snapshot[:16]}",
        "corpus_snapshot_sha256": snapshot,
        "catalogs_read": len(catalog_paths),
        "unparseable_records": unparseable,
        "memberships_without_object": unresolved,
        "record_counts": {kind: by_kind[kind] for kind in RECORD_KINDS if by_kind[kind]},
        "acquired_sources": len(sources),
        "admitted_memberships": len(memberships),
        "distinct_admitted_objects": len(exact_digests),
        "raw_bytes": total_mass,
        "admission_states": dict(admission),
        "split_by_count": dict(split_count.most_common()),
        "split_by_mass": dict(split_mass.most_common()),
        "domains_by_mass": {
            f"{domain}/{split}": {"objects": domain_count[(domain, split)], "bytes": mass}
            for (domain, split), mass in domain_mass.most_common()
        },
        "modality_by_mass": {
            family: {"objects": modality_count[family], "bytes": mass}
            for family, mass in modality_mass.most_common()
        },
        "source_families": dict(
            collections.Counter(
                source_family(s.get("canonical_url")) for s in sources).most_common()),
        "license_verdicts": dict(
            collections.Counter(str(s.get("license_verdict", "<unstated>")) for s in sources)),
        "distinct_license_texts": len(licence_texts),
        "named_licences": 0,
        "tokenizer_identities": dict(tokenizers),
        "dataset_versions": sorted(
            str(d.get("id") or d.get("_record_id")) for d in datasets),
        # Measured rather than assumed: if the cluster count equals the distinct-digest count,
        # near-deduplication has not run and any figure read from the field is an exact-duplicate
        # figure under a near-duplicate name.
        "near_dedup_informative": len(clusters) != len(exact_digests),
        "unmeasured_properties": {
            name: how[5:].strip() for name, how in REQUESTED_PROPERTIES if how.startswith("gap:")
        },
        "measured_properties": {
            name: how for name, how in REQUESTED_PROPERTIES if not how.startswith("gap:")
        },
    }


def render(receipt: dict[str, Any]) -> str:
    """A human-readable rendering that states the unmeasured set as prominently as the numbers."""
    lines = [
        f"corpus snapshot        : {receipt['corpus_snapshot_id']}",
        f"catalogs read          : {receipt['catalogs_read']}",
        f"acquired sources       : {receipt['acquired_sources']}",
        f"admitted memberships   : {receipt['admitted_memberships']}"
        f"  (distinct objects {receipt['distinct_admitted_objects']})",
        f"raw bytes              : {receipt['raw_bytes']:,}",
        f"admission states       : {receipt['admission_states']}",
        f"split by mass          : {receipt['split_by_mass']}",
        f"licence verdicts       : {receipt['license_verdicts']}"
        f"  distinct texts {receipt['distinct_license_texts']}"
        f"  named {receipt['named_licences']}",
        f"near-dedup informative : {receipt['near_dedup_informative']}",
        "",
        "domains by mass:",
    ]
    lines.extend(
        f"  {key:<40}{value['objects']:>10,}{value['bytes']:>18,}"
        for key, value in receipt["domains_by_mass"].items()
    )
    lines.append("")
    lines.append("modality by mass:")
    lines.extend(
        f"  {key:<40}{value['objects']:>10,}{value['bytes']:>18,}"
        for key, value in receipt["modality_by_mass"].items()
    )
    lines.append("")
    lines.append(f"UNMEASURED ({len(receipt['unmeasured_properties'])}) "
                 "-- reported as absent, never as zero:")
    lines.extend(
        f"  {name}: {why}" for name, why in sorted(receipt["unmeasured_properties"].items()))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--roots",
        required=True,
        action="append",
        help="glob matching catalog SQLite databases; repeatable, no default by design",
    )
    parser.add_argument("--json", default=None, help="write the receipt to this path")
    parser.add_argument(
        "--require-catalogs",
        type=int,
        default=1,
        help="refuse when fewer than this many catalogs match, so an empty glob is an error",
    )
    args = parser.parse_args(argv)

    paths: list[str] = []
    for pattern in args.roots:
        paths.extend(glob.glob(pattern))
    paths = sorted(set(paths))

    # An empty glob must fail rather than emit a receipt of zeroes: a zero-row receipt is
    # indistinguishable from a genuinely empty corpus, and it is the more likely reading.
    if len(paths) < args.require_catalogs:
        parser.error(
            f"matched {len(paths)} catalog(s), require at least {args.require_catalogs}")

    receipt = build_receipt(paths)
    print(render(receipt))

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
