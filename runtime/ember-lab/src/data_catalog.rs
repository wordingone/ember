// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use crate::{EmberLabError, Result};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

const MANIFEST_SCHEMA: &str = "ember-data-catalog-manifest-v1";
const RECORD_KINDS: &[&str] = &[
    "source",
    "immutable_object",
    "dataset_version",
    "transform",
    "membership",
    "protected_eval",
    "consumer_attempt",
    "experience",
    "receipt",
];
const EDGE_KINDS: &[&str] = &[
    "source_object",
    "object_receipt",
    "dataset_parent",
    "transform_parent",
    "transform_input",
    "transform_output",
    "transform_receipt",
    "dataset_transform",
    "version_membership",
    "membership_object",
    "evaluation_object",
    "evaluation_receipt",
    "consumer_dataset",
    "consumer_evaluation",
    "consumer_receipt",
    "experience_consumer",
    "experience_receipt",
    "receipt_supersession",
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DataCatalogImportOutcome {
    pub manifest_sha256: String,
    pub inserted_records: usize,
    pub inserted_edges: usize,
}

pub(crate) fn migrate(conn: &Connection) -> Result<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS data_catalog_records(
             kind TEXT NOT NULL CHECK(kind IN ('source','immutable_object','dataset_version','transform','membership','protected_eval','consumer_attempt','experience','receipt')),
             record_id TEXT NOT NULL,
             payload_json TEXT NOT NULL,
             payload_sha256 TEXT NOT NULL,
             PRIMARY KEY(kind,record_id)
         );
         CREATE TABLE IF NOT EXISTS data_catalog_edges(
             kind TEXT NOT NULL CHECK(kind IN ('source_object','object_receipt','dataset_parent','transform_parent','transform_input','transform_output','transform_receipt','dataset_transform','version_membership','membership_object','evaluation_object','evaluation_receipt','consumer_dataset','consumer_evaluation','consumer_receipt','experience_consumer','experience_receipt','receipt_supersession')),
             from_kind TEXT NOT NULL,
             from_id TEXT NOT NULL,
             to_kind TEXT NOT NULL,
             to_id TEXT NOT NULL,
             ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
             payload_json TEXT NOT NULL,
             payload_sha256 TEXT NOT NULL,
             PRIMARY KEY(kind,from_kind,from_id,to_kind,to_id,ordinal),
             FOREIGN KEY(from_kind,from_id)
                 REFERENCES data_catalog_records(kind,record_id),
             FOREIGN KEY(to_kind,to_id)
                 REFERENCES data_catalog_records(kind,record_id)
         );
         CREATE TABLE IF NOT EXISTS data_catalog_imports(
             manifest_sha256 TEXT PRIMARY KEY,
             schema_version TEXT NOT NULL CHECK(schema_version='ember-data-catalog-manifest-v1'),
             record_count INTEGER NOT NULL CHECK(record_count >= 0),
             edge_count INTEGER NOT NULL CHECK(edge_count >= 0),
             imported_at_ms INTEGER NOT NULL CHECK(imported_at_ms >= 0)
         );
         CREATE TABLE IF NOT EXISTS data_catalog_location_events(
             seq INTEGER PRIMARY KEY AUTOINCREMENT,
             object_kind TEXT NOT NULL CHECK(object_kind='immutable_object'),
             object_id TEXT NOT NULL,
             volume TEXT NOT NULL,
             locator TEXT NOT NULL,
             event TEXT NOT NULL CHECK(event IN ('registered','retired')),
             event_at_ms INTEGER NOT NULL CHECK(event_at_ms >= 0),
             reason TEXT,
             payload_json TEXT NOT NULL,
             payload_sha256 TEXT NOT NULL,
             FOREIGN KEY(object_kind,object_id)
                 REFERENCES data_catalog_records(kind,record_id)
         );
         CREATE INDEX IF NOT EXISTS data_catalog_location_events_by_tuple
             ON data_catalog_location_events(object_id,volume,locator,seq);
         CREATE TABLE IF NOT EXISTS data_catalog_admission_events(
             seq INTEGER PRIMARY KEY AUTOINCREMENT,
             membership_id TEXT NOT NULL,
             from_state TEXT NOT NULL CHECK(from_state IN ('admitted','excluded','refused','quarantined')),
             to_state TEXT NOT NULL CHECK(to_state IN ('admitted','excluded','refused','quarantined')),
             reason TEXT NOT NULL,
             audit_self_sha256 TEXT NOT NULL,
             event_at_ms INTEGER NOT NULL CHECK(event_at_ms >= 0),
             payload_json TEXT NOT NULL,
             payload_sha256 TEXT NOT NULL
         );",
    )?;
    Ok(())
}

pub(crate) fn import_manifest(
    conn: &mut Connection,
    bytes: &[u8],
    imported_at_ms: i64,
) -> Result<DataCatalogImportOutcome> {
    let manifest: Value = serde_json::from_slice(bytes)?;
    let root = object(&manifest, "manifest")?;
    exact_keys(root, &["edges", "records", "schema_version"], "manifest")?;
    required_string(root, "schema_version", "manifest", |value| {
        value == MANIFEST_SCHEMA
    })?;
    let records = required_array(root, "records", "manifest")?;
    let edges = required_array(root, "edges", "manifest")?;
    let normalized_records = normalize_records(records)?;
    let normalized_edges = normalize_edges(edges)?;
    let canonical = canonical_manifest_bytes(&normalized_records, &normalized_edges)?;
    let manifest_sha256 = sha256(&canonical);

    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let existing_records = normalize_records(&query_payloads(
        &tx,
        "SELECT payload_json FROM data_catalog_records ORDER BY kind,record_id",
    )?)?;
    let existing_edges = normalize_edges(&query_payloads(
        &tx,
        "SELECT payload_json FROM data_catalog_edges
         ORDER BY kind,from_kind,from_id,to_kind,to_id,ordinal",
    )?)?;
    let combined_records = merge_records(&existing_records, &normalized_records)?;
    let combined_edges = merge_edges(&existing_edges, &normalized_edges)?;
    validate_edge_endpoints(&combined_records, &combined_edges)?;
    validate_required_relations(&combined_records, &combined_edges)?;

    let mut inserted_records = 0;
    for record in &normalized_records {
        let row = object(record, "record")?;
        let kind = string_value(row, "kind", "record")?;
        let record_id = string_value(row, "id", "record")?;
        let payload_json = serde_json::to_string(record)?;
        let payload_sha256 = sha256(payload_json.as_bytes());
        let changed = tx.execute(
            "INSERT OR IGNORE INTO data_catalog_records(
                 kind,record_id,payload_json,payload_sha256
             ) VALUES(?1,?2,?3,?4)",
            params![kind, record_id, payload_json, payload_sha256],
        )?;
        if changed == 1 {
            inserted_records += 1;
        } else {
            let existing: Option<(String, String)> = tx
                .query_row(
                    "SELECT payload_json,payload_sha256
                     FROM data_catalog_records WHERE kind=?1 AND record_id=?2",
                    params![kind, record_id],
                    |row| Ok((row.get(0)?, row.get(1)?)),
                )
                .optional()?;
            if existing.as_ref() != Some(&(payload_json, payload_sha256)) {
                return invalid(format!(
                    "record identity {kind}/{record_id} is already bound to different bytes"
                ));
            }
        }
    }

    let mut inserted_edges = 0;
    for edge in &normalized_edges {
        let row = object(edge, "edge")?;
        let kind = string_value(row, "kind", "edge")?;
        let from_kind = string_value(row, "from_kind", "edge")?;
        let from_id = string_value(row, "from_id", "edge")?;
        let to_kind = string_value(row, "to_kind", "edge")?;
        let to_id = string_value(row, "to_id", "edge")?;
        let ordinal = integer_value(row, "ordinal", "edge")?;
        let payload_json = serde_json::to_string(edge)?;
        let payload_sha256 = sha256(payload_json.as_bytes());
        let changed = tx.execute(
            "INSERT OR IGNORE INTO data_catalog_edges(
                 kind,from_kind,from_id,to_kind,to_id,ordinal,payload_json,payload_sha256
             ) VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
            params![
                kind,
                from_kind,
                from_id,
                to_kind,
                to_id,
                ordinal,
                payload_json,
                payload_sha256
            ],
        )?;
        if changed == 1 {
            inserted_edges += 1;
        } else {
            let existing: Option<(String, String)> = tx
                .query_row(
                    "SELECT payload_json,payload_sha256 FROM data_catalog_edges
                     WHERE kind=?1 AND from_kind=?2 AND from_id=?3
                       AND to_kind=?4 AND to_id=?5 AND ordinal=?6",
                    params![kind, from_kind, from_id, to_kind, to_id, ordinal],
                    |row| Ok((row.get(0)?, row.get(1)?)),
                )
                .optional()?;
            if existing.as_ref() != Some(&(payload_json, payload_sha256)) {
                return invalid(format!(
                    "edge identity {kind}/{from_kind}/{from_id}/{to_kind}/{to_id}/{ordinal} is already bound to different bytes"
                ));
            }
        }
    }

    tx.execute(
        "INSERT OR IGNORE INTO data_catalog_imports(
             manifest_sha256,schema_version,record_count,edge_count,imported_at_ms
         ) VALUES(?1,?2,?3,?4,?5)",
        params![
            manifest_sha256,
            MANIFEST_SCHEMA,
            normalized_records.len(),
            normalized_edges.len(),
            imported_at_ms
        ],
    )?;
    tx.commit()?;
    Ok(DataCatalogImportOutcome {
        manifest_sha256,
        inserted_records,
        inserted_edges,
    })
}

fn merge_records(existing: &[Value], incoming: &[Value]) -> Result<Vec<Value>> {
    let mut merged: BTreeMap<(usize, String), Value> = existing
        .iter()
        .cloned()
        .map(|record| (record_sort_key(&record), record))
        .collect();
    for record in incoming {
        let identity = record_sort_key(record);
        if let Some(current) = merged.get(&identity) {
            if current != record {
                return invalid(format!(
                    "record identity {}/{} is already bound to different bytes",
                    string_value(object(record, "record")?, "kind", "record")?,
                    identity.1
                ));
            }
        } else {
            merged.insert(identity, record.clone());
        }
    }
    Ok(merged.into_values().collect())
}

fn merge_edges(existing: &[Value], incoming: &[Value]) -> Result<Vec<Value>> {
    let mut merged: BTreeMap<(usize, String, String, i64), Value> = existing
        .iter()
        .cloned()
        .map(|edge| (edge_sort_key(&edge), edge))
        .collect();
    for edge in incoming {
        let identity = edge_sort_key(edge);
        if let Some(current) = merged.get(&identity) {
            if current != edge {
                return invalid(format!(
                    "edge identity is already bound to different bytes: {:?}",
                    identity
                ));
            }
        } else {
            merged.insert(identity, edge.clone());
        }
    }
    Ok(merged.into_values().collect())
}

pub(crate) fn export_manifest(conn: &Connection) -> Result<Vec<u8>> {
    let records = query_payloads(
        conn,
        "SELECT payload_json FROM data_catalog_records ORDER BY kind,record_id",
    )?;
    let edges = query_payloads(
        conn,
        "SELECT payload_json FROM data_catalog_edges
         ORDER BY kind,from_kind,from_id,to_kind,to_id,ordinal",
    )?;
    let records = normalize_records(&records)?;
    let edges = normalize_edges(&edges)?;
    canonical_manifest_bytes(&records, &edges)
}

pub(crate) fn status(conn: &Connection) -> Result<Value> {
    let records = normalize_records(&query_payloads(
        conn,
        "SELECT payload_json FROM data_catalog_records ORDER BY kind,record_id",
    )?)?;
    let edges = normalize_edges(&query_payloads(
        conn,
        "SELECT payload_json FROM data_catalog_edges
         ORDER BY kind,from_kind,from_id,to_kind,to_id,ordinal",
    )?)?;
    validate_edge_endpoints(&records, &edges)?;
    validate_required_relations(&records, &edges)?;
    let relations = RelationIndex::from_edges(&edges)?;

    let mut record_counts: BTreeMap<&str, usize> =
        RECORD_KINDS.iter().map(|kind| (*kind, 0)).collect();
    let mut object_bytes = BTreeMap::new();
    let mut total_object_bytes = 0_u64;
    let mut available_object_bytes = 0_u64;
    let mut unresolved_blockers = Vec::new();
    for record in &records {
        let row = object(record, "record")?;
        let kind = string_value(row, "kind", "record")?;
        let id = string_value(row, "id", "record")?;
        *record_counts.get_mut(kind).expect("validated record kind") += 1;
        if kind == "immutable_object" {
            let bytes = integer_value(row, "byte_count", "immutable object record")? as u64;
            total_object_bytes = total_object_bytes
                .checked_add(bytes)
                .ok_or_else(|| invalid_error("catalog object byte total overflowed"))?;
            if string_value(row, "custody_state", "immutable object record")? == "available" {
                available_object_bytes = available_object_bytes
                    .checked_add(bytes)
                    .ok_or_else(|| invalid_error("available object byte total overflowed"))?;
            }
            object_bytes.insert(id.to_string(), bytes);
        }
        if let Some(state) = unresolved_state(row, kind)? {
            unresolved_blockers.push(json!({
                "id": id,
                "kind": kind,
                "state": state,
            }));
        }
    }

    #[derive(Default)]
    struct DomainSummary {
        admitted_bytes: u64,
        admitted_memberships: usize,
        exact_hashes: BTreeSet<String>,
        near_dedup_clusters: BTreeSet<String>,
        splits: BTreeMap<String, usize>,
    }
    let mut domain_summaries: BTreeMap<String, DomainSummary> = BTreeMap::new();
    for record in &records {
        let row = object(record, "record")?;
        if string_value(row, "kind", "record")? != "membership"
            || string_value(row, "admission_state", "membership record")? != "admitted"
        {
            continue;
        }
        let id = string_value(row, "id", "membership record")?;
        let targets = relations.outgoing("membership_object", "membership", id);
        require_exactly_one(targets, "membership", id, "membership_object")?;
        let bytes = object_bytes
            .get(&targets[0])
            .copied()
            .ok_or_else(|| invalid_error("membership object bytes are unavailable"))?;
        let summary = domain_summaries
            .entry(string_value(row, "domain", "membership record")?.to_string())
            .or_default();
        summary.admitted_bytes = summary
            .admitted_bytes
            .checked_add(bytes)
            .ok_or_else(|| invalid_error("domain admitted byte total overflowed"))?;
        summary.admitted_memberships += 1;
        summary
            .exact_hashes
            .insert(string_value(row, "exact_sha256", "membership record")?.to_string());
        summary
            .near_dedup_clusters
            .insert(string_value(row, "near_dedup_cluster", "membership record")?.to_string());
        *summary
            .splits
            .entry(string_value(row, "split", "membership record")?.to_string())
            .or_default() += 1;
    }
    let domains: Vec<Value> = domain_summaries
        .into_iter()
        .map(|(domain, summary)| {
            json!({
                "domain": domain,
                "admitted_bytes": summary.admitted_bytes,
                "admitted_memberships": summary.admitted_memberships,
                "exact_hashes": summary.exact_hashes.len(),
                "near_dedup_clusters": summary.near_dedup_clusters.len(),
                "splits": summary.splits,
            })
        })
        .collect();

    let mut evaluations = Vec::new();
    for record in &records {
        let row = object(record, "record")?;
        if string_value(row, "kind", "record")? != "protected_eval" {
            continue;
        }
        let id = string_value(row, "id", "protected evaluation record")?;
        evaluations.push(json!({
            "evaluation_id": id,
            "exclusion_reason": row.get("exclusion_reason").cloned().unwrap_or(Value::Null),
            "near_dup_ruling": string_value(row, "near_dup_ruling", "protected evaluation record")?,
            "ngram_ruling": string_value(row, "ngram_ruling", "protected evaluation record")?,
            "object_ids": relations.outgoing("evaluation_object", "protected_eval", id),
            "overlap_state": string_value(row, "overlap_state", "protected evaluation record")?,
            "receipt_ids": relations.outgoing("evaluation_receipt", "protected_eval", id),
        }));
    }

    let mut consumers = Vec::new();
    for record in &records {
        let row = object(record, "record")?;
        if string_value(row, "kind", "record")? != "consumer_attempt" {
            continue;
        }
        let id = string_value(row, "id", "consumer attempt record")?;
        consumers.push(json!({
            "attempt_id": id,
            "checkpoint_sha256": string_value(row, "checkpoint_sha256", "consumer attempt record")?,
            "dataset_version_ids": relations.outgoing("consumer_dataset", "consumer_attempt", id),
            "evaluation_ids": relations.outgoing("consumer_evaluation", "consumer_attempt", id),
            "model_sha256": string_value(row, "model_sha256", "consumer attempt record")?,
            "receipt_ids": relations.outgoing("consumer_receipt", "consumer_attempt", id),
            "state": string_value(row, "state", "consumer attempt record")?,
        }));
    }

    Ok(json!({
        "schema_version": "ember-data-catalog-status-v1",
        "record_counts": record_counts,
        "custody": {
            "total_object_bytes": total_object_bytes,
            "available_object_bytes": available_object_bytes,
        },
        "domains": domains,
        "evaluations": evaluations,
        "unresolved_blockers": unresolved_blockers,
        "consumers": consumers,
    }))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactLocationInput {
    pub volume: String,
    pub locator: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactLocationOutcome {
    pub volume: String,
    pub locator: String,
    pub newly_registered: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisterArtifactOutcome {
    pub object_id: String,
    pub object_newly_registered: bool,
    pub locations: Vec<ArtifactLocationOutcome>,
}

/// Registers a checkpoint/artifact and one or more of its physical locations in a single
/// transaction: the object identity reuses `immutable_object`'s existing shape/validation
/// (#1581), and each location is appended to `data_catalog_location_events` idempotently by
/// (object,volume,locator) identity. Re-registering the same object+location is a no-op;
/// re-registering the same object with different byte_count/media_type refuses.
pub(crate) fn register_artifact(
    conn: &mut Connection,
    sha256_hex: &str,
    byte_count: i64,
    media_type: &str,
    locations: &[ArtifactLocationInput],
    registered_at_ms: i64,
) -> Result<RegisterArtifactOutcome> {
    if locations.is_empty() {
        return invalid("artifact registration requires at least one location");
    }
    let digest = validate_hex_sha256(sha256_hex)?.to_string();
    if byte_count <= 0 {
        return invalid("artifact byte_count must be positive");
    }
    if media_type.is_empty() {
        return invalid("artifact media_type must be nonempty");
    }
    let object_id = format!("sha256:{digest}");
    let record = json!({
        "kind": "immutable_object",
        "id": object_id,
        "sha256": digest,
        "byte_count": byte_count,
        "media_type": media_type,
        "locator": format!("sha256/{}/{digest}", &digest[..2]),
        "custody_state": "available",
    });
    validate_record(&record)?;

    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;

    let payload_json = serde_json::to_string(&record)?;
    let payload_sha256 = sha256(payload_json.as_bytes());
    let changed = tx.execute(
        "INSERT OR IGNORE INTO data_catalog_records(kind,record_id,payload_json,payload_sha256)
         VALUES('immutable_object',?1,?2,?3)",
        params![object_id, payload_json, payload_sha256],
    )?;
    let object_newly_registered = changed == 1;
    if !object_newly_registered {
        let existing: (String, String) = tx.query_row(
            "SELECT payload_json,payload_sha256 FROM data_catalog_records
             WHERE kind='immutable_object' AND record_id=?1",
            params![object_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )?;
        if existing != (payload_json, payload_sha256) {
            return invalid(format!(
                "artifact {object_id} is already registered with a different byte_count/media_type"
            ));
        }
    }

    let mut outcomes = Vec::with_capacity(locations.len());
    let mut seen = BTreeSet::new();
    for location in locations {
        validate_volume(&location.volume)?;
        validate_locator(&location.locator)?;
        if !seen.insert((location.volume.clone(), location.locator.clone())) {
            return invalid(format!(
                "duplicate location {}/{} in one registration call",
                location.volume, location.locator
            ));
        }
        let latest = latest_location_event(&tx, &object_id, &location.volume, &location.locator)?;
        let newly_registered = if latest.as_deref() == Some("registered") {
            false
        } else {
            insert_location_event(
                &tx,
                &object_id,
                &location.volume,
                &location.locator,
                "registered",
                registered_at_ms,
                None,
            )?;
            true
        };
        outcomes.push(ArtifactLocationOutcome {
            volume: location.volume.clone(),
            locator: location.locator.clone(),
            newly_registered,
        });
    }

    tx.commit()?;
    Ok(RegisterArtifactOutcome {
        object_id,
        object_newly_registered,
        locations: outcomes,
    })
}

/// Retires a previously registered location as an explicit catalog event -- never a row
/// deletion. Refuses if the object was never registered or the location is not currently
/// in the `registered` state (already retired, or never registered).
pub(crate) fn retire_artifact_location(
    conn: &mut Connection,
    sha256_hex: &str,
    volume: &str,
    locator: &str,
    retired_at_ms: i64,
    reason: &str,
) -> Result<()> {
    let digest = validate_hex_sha256(sha256_hex)?.to_string();
    if reason.is_empty() {
        return invalid("location retirement requires a nonempty reason");
    }
    validate_volume(volume)?;
    validate_locator(locator)?;
    let object_id = format!("sha256:{digest}");

    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let object_exists: Option<String> = tx
        .query_row(
            "SELECT record_id FROM data_catalog_records
             WHERE kind='immutable_object' AND record_id=?1",
            params![object_id],
            |row| row.get(0),
        )
        .optional()?;
    if object_exists.is_none() {
        return invalid(format!("artifact {object_id} is not registered"));
    }
    let latest = latest_location_event(&tx, &object_id, volume, locator)?;
    if latest.as_deref() != Some("registered") {
        return invalid(format!(
            "location {volume}/{locator} for {object_id} is not currently registered"
        ));
    }
    insert_location_event(
        &tx,
        &object_id,
        volume,
        locator,
        "retired",
        retired_at_ms,
        Some(reason),
    )?;
    tx.commit()?;
    Ok(())
}

fn insert_location_event(
    conn: &Connection,
    object_id: &str,
    volume: &str,
    locator: &str,
    event: &str,
    event_at_ms: i64,
    reason: Option<&str>,
) -> Result<()> {
    let payload = json!({
        "object_id": object_id,
        "volume": volume,
        "locator": locator,
        "event": event,
        "event_at_ms": event_at_ms,
        "reason": reason,
    });
    let payload_json = serde_json::to_string(&payload)?;
    let payload_sha256 = sha256(payload_json.as_bytes());
    conn.execute(
        "INSERT INTO data_catalog_location_events(
             object_kind,object_id,volume,locator,event,event_at_ms,reason,payload_json,payload_sha256
         ) VALUES('immutable_object',?1,?2,?3,?4,?5,?6,?7,?8)",
        params![
            object_id,
            volume,
            locator,
            event,
            event_at_ms,
            reason,
            payload_json,
            payload_sha256
        ],
    )?;
    Ok(())
}

fn latest_location_event(
    conn: &Connection,
    object_id: &str,
    volume: &str,
    locator: &str,
) -> Result<Option<String>> {
    Ok(conn
        .query_row(
            "SELECT event FROM data_catalog_location_events
             WHERE object_id=?1 AND volume=?2 AND locator=?3
             ORDER BY seq DESC LIMIT 1",
            params![object_id, volume, locator],
            |row| row.get(0),
        )
        .optional()?)
}

fn active_locations_for(conn: &Connection, object_id: &str) -> Result<Vec<(String, String)>> {
    let mut statement = conn.prepare(
        "SELECT volume,locator,event FROM data_catalog_location_events
         WHERE object_id=?1 ORDER BY volume,locator,seq",
    )?;
    let rows = statement.query_map(params![object_id], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
        ))
    })?;
    let mut latest: BTreeMap<(String, String), String> = BTreeMap::new();
    for row in rows {
        let (volume, locator, event) = row?;
        latest.insert((volume, locator), event);
    }
    Ok(latest
        .into_iter()
        .filter(|(_, event)| event == "registered")
        .map(|(key, _)| key)
        .collect())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum CustodyVerdict {
    Verified,
    SizeMismatch,
    AbsentAtRegisteredLocation,
    NoRegisteredLocation,
}

impl CustodyVerdict {
    fn as_str(self) -> &'static str {
        match self {
            Self::Verified => "verified",
            Self::SizeMismatch => "size_mismatch",
            Self::AbsentAtRegisteredLocation => "absent_at_registered_location",
            Self::NoRegisteredLocation => "no_registered_location",
        }
    }
}

/// Resolves each pinned hash to its currently active (registered, not retired) locations and
/// verifies existence + byte count against a caller-supplied volume->root mapping. The catalog
/// itself never stores an absolute host path (#1581/#1507 portability contract); the root map
/// is a verification-time-only input, never persisted. Fails closed (returns Err) if an active
/// location's volume has no supplied root, rather than guessing a verdict for it. `rehash`
/// additionally recomputes the full SHA-256 of on-disk bytes; a rehash mismatch is folded into
/// `size_mismatch` (declared identity does not match actual bytes), since the receipt's verdict
/// enum is closed to the four values #1721 names.
pub(crate) fn custody_verify(
    conn: &Connection,
    hashes: &[String],
    roots: &BTreeMap<String, PathBuf>,
    rehash: bool,
    verified_at_ms: i64,
) -> Result<Value> {
    let mut results = Vec::with_capacity(hashes.len());
    let mut admitted = true;
    for hash in hashes {
        let digest = validate_hex_sha256(hash)?.to_string();
        let object_id = format!("sha256:{digest}");
        let object_row: Option<String> = conn
            .query_row(
                "SELECT payload_json FROM data_catalog_records
                 WHERE kind='immutable_object' AND record_id=?1",
                params![object_id],
                |row| row.get(0),
            )
            .optional()?;
        let active_locations = active_locations_for(conn, &object_id)?;

        let Some(object_payload) = object_row.filter(|_| !active_locations.is_empty()) else {
            admitted = false;
            results.push(json!({
                "sha256": digest,
                "verdict": CustodyVerdict::NoRegisteredLocation.as_str(),
                "locations": [],
            }));
            continue;
        };

        let expected_bytes = {
            let record: Value = serde_json::from_str(&object_payload)?;
            let row = object(&record, "immutable object record")?;
            integer_value(row, "byte_count", "immutable object record")?
        };

        let mut location_reports = Vec::with_capacity(active_locations.len());
        let mut any_verified = false;
        let mut any_size_mismatch = false;
        for (volume, locator) in &active_locations {
            let root = roots.get(volume).ok_or_else(|| {
                invalid_error(format!(
                    "custody verify has no root mapping supplied for volume {volume}"
                ))
            })?;
            let candidate = root.join(locator);
            let verdict = match std::fs::metadata(&candidate) {
                Ok(meta) if meta.len() as i64 != expected_bytes => CustodyVerdict::SizeMismatch,
                Ok(_) if rehash => match crate::hash_file(&candidate) {
                    Ok(actual) if actual == digest => CustodyVerdict::Verified,
                    Ok(_) => CustodyVerdict::SizeMismatch,
                    Err(_) => CustodyVerdict::AbsentAtRegisteredLocation,
                },
                Ok(_) => CustodyVerdict::Verified,
                Err(_) => CustodyVerdict::AbsentAtRegisteredLocation,
            };
            match verdict {
                CustodyVerdict::Verified => any_verified = true,
                CustodyVerdict::SizeMismatch => any_size_mismatch = true,
                _ => {}
            }
            location_reports.push(json!({
                "volume": volume,
                "locator": locator,
                "verdict": verdict.as_str(),
            }));
        }
        let hash_verdict = if any_verified {
            CustodyVerdict::Verified
        } else if any_size_mismatch {
            CustodyVerdict::SizeMismatch
        } else {
            CustodyVerdict::AbsentAtRegisteredLocation
        };
        if hash_verdict != CustodyVerdict::Verified {
            admitted = false;
        }
        results.push(json!({
            "sha256": digest,
            "verdict": hash_verdict.as_str(),
            "locations": location_reports,
        }));
    }
    Ok(json!({
        "schema_version": "ember-custody-verify-receipt-v1",
        "verified_at_ms": verified_at_ms,
        "rehash": rehash,
        "admitted": admitted,
        "results": results,
    }))
}

fn validate_volume(value: &str) -> Result<()> {
    validate_identity(value, "artifact location volume")
}

fn validate_locator(value: &str) -> Result<()> {
    let looks_like_drive_prefix = value.len() >= 2 && value.as_bytes()[1] == b':';
    if value.is_empty()
        || value.len() > 4096
        || value.starts_with('/')
        || value.starts_with('\\')
        || looks_like_drive_prefix
        || value.split(['/', '\\']).any(|segment| segment == "..")
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'/' | b'.' | b'_' | b'-'))
    {
        return invalid(format!(
            "artifact location locator {value} is not a portable relative path"
        ));
    }
    Ok(())
}

fn validate_hex_sha256(value: &str) -> Result<&str> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return invalid("value must be 64 lowercase hexadecimal characters");
    }
    Ok(value)
}

fn unresolved_state(row: &Map<String, Value>, kind: &str) -> Result<Option<String>> {
    let state = match kind {
        "source" if string_value(row, "license_verdict", "source record")? != "accepted" => {
            Some(string_value(row, "license_verdict", "source record")?)
        }
        "immutable_object"
            if string_value(row, "custody_state", "immutable object record")? != "available" =>
        {
            Some(string_value(
                row,
                "custody_state",
                "immutable object record",
            )?)
        }
        "dataset_version"
            if string_value(row, "state", "dataset version record")? != "admitted" =>
        {
            Some(string_value(row, "state", "dataset version record")?)
        }
        "transform"
            if string_value(row, "determinism_state", "transform record")? != "deterministic" =>
        {
            Some(string_value(row, "determinism_state", "transform record")?)
        }
        "membership"
            if string_value(row, "admission_state", "membership record")? != "admitted" =>
        {
            Some(string_value(row, "admission_state", "membership record")?)
        }
        "protected_eval"
            if string_value(row, "overlap_state", "protected evaluation record")? != "disjoint"
                || string_value(row, "ngram_ruling", "protected evaluation record")? != "clear"
                || string_value(row, "near_dup_ruling", "protected evaluation record")?
                    != "clear" =>
        {
            Some(string_value(
                row,
                "overlap_state",
                "protected evaluation record",
            )?)
        }
        "consumer_attempt"
            if string_value(row, "state", "consumer attempt record")? == "refused" =>
        {
            Some("refused")
        }
        "experience" if string_value(row, "deletion_state", "experience record")? != "active" => {
            Some(string_value(row, "deletion_state", "experience record")?)
        }
        "receipt" if string_value(row, "state", "receipt record")? == "refused" => Some("refused"),
        _ => None,
    };
    Ok(state.map(str::to_string))
}

fn query_payloads(conn: &Connection, sql: &str) -> Result<Vec<Value>> {
    let mut statement = conn.prepare(sql)?;
    let rows = statement.query_map([], |row| row.get::<_, String>(0))?;
    let mut values = Vec::new();
    for row in rows {
        values.push(serde_json::from_str(&row?)?);
    }
    Ok(values)
}

fn normalize_records(records: &[Value]) -> Result<Vec<Value>> {
    let mut normalized = records.to_vec();
    let mut identities = BTreeSet::new();
    for record in &normalized {
        validate_record(record)?;
        let row = object(record, "record")?;
        let identity = (
            string_value(row, "kind", "record")?.to_string(),
            string_value(row, "id", "record")?.to_string(),
        );
        if !identities.insert(identity.clone()) {
            return invalid(format!(
                "duplicate record identity {}/{}",
                identity.0, identity.1
            ));
        }
    }
    normalized.sort_by_key(record_sort_key);
    Ok(normalized)
}

fn normalize_edges(edges: &[Value]) -> Result<Vec<Value>> {
    let mut normalized = edges.to_vec();
    let mut identities = BTreeSet::new();
    for edge in &normalized {
        validate_edge(edge)?;
        let row = object(edge, "edge")?;
        let identity = (
            string_value(row, "kind", "edge")?.to_string(),
            string_value(row, "from_kind", "edge")?.to_string(),
            string_value(row, "from_id", "edge")?.to_string(),
            string_value(row, "to_kind", "edge")?.to_string(),
            string_value(row, "to_id", "edge")?.to_string(),
            integer_value(row, "ordinal", "edge")?,
        );
        if !identities.insert(identity.clone()) {
            return invalid(format!(
                "duplicate edge identity {}/{}/{}/{}/{}/{}",
                identity.0, identity.1, identity.2, identity.3, identity.4, identity.5
            ));
        }
    }
    normalized.sort_by_key(edge_sort_key);
    Ok(normalized)
}

fn validate_record(value: &Value) -> Result<()> {
    let row = object(value, "record")?;
    let kind = string_value(row, "kind", "record")?;
    if !RECORD_KINDS.contains(&kind) {
        return invalid(format!("unknown record kind {kind}"));
    }
    let id = string_value(row, "id", "record")?;
    validate_identity(id, "record id")?;
    match kind {
        "source" => {
            exact_keys(
                row,
                &[
                    "access_class",
                    "acquired_at_ms",
                    "canonical_url",
                    "id",
                    "kind",
                    "license_text_sha256",
                    "license_verdict",
                    "refusal_reason",
                    "revision",
                ],
                "source record",
            )?;
            required_string(row, "canonical_url", "source record", |value| {
                value.starts_with("https://")
            })?;
            required_string(row, "revision", "source record", |value| !value.is_empty())?;
            required_sha(row, "license_text_sha256", "source record")?;
            required_string(row, "license_verdict", "source record", |value| {
                matches!(value, "accepted" | "refused")
            })?;
            required_string(row, "access_class", "source record", |value| {
                matches!(value, "public" | "restricted" | "local_owned")
            })?;
            nonnegative_integer(row, "acquired_at_ms", "source record")?;
            optional_string(row, "refusal_reason", "source record")?;
            let verdict = string_value(row, "license_verdict", "source record")?;
            let reason = row.get("refusal_reason").and_then(Value::as_str);
            if (verdict == "accepted" && reason.is_some())
                || (verdict == "refused" && reason.is_none())
            {
                return invalid("source refusal_reason does not match license_verdict");
            }
        }
        "immutable_object" => {
            exact_keys(
                row,
                &[
                    "byte_count",
                    "custody_state",
                    "id",
                    "kind",
                    "locator",
                    "media_type",
                    "sha256",
                ],
                "immutable object record",
            )?;
            let digest = required_sha(row, "sha256", "immutable object record")?;
            if id != format!("sha256:{digest}") {
                return invalid("immutable object id must equal sha256:<sha256>");
            }
            positive_integer(row, "byte_count", "immutable object record")?;
            required_string(row, "media_type", "immutable object record", |value| {
                !value.is_empty()
            })?;
            let locator = string_value(row, "locator", "immutable object record")?;
            if locator != format!("sha256/{}/{digest}", &digest[..2]) {
                return invalid("immutable object locator is not the canonical relative locator");
            }
            required_string(row, "custody_state", "immutable object record", |value| {
                matches!(value, "available" | "quarantined" | "missing" | "deleted")
            })?;
        }
        "dataset_version" => {
            exact_keys(
                row,
                &[
                    "created_at_ms",
                    "id",
                    "kind",
                    "manifest_sha256",
                    "name",
                    "state",
                    "version_class",
                ],
                "dataset version record",
            )?;
            required_string(row, "name", "dataset version record", |value| {
                !value.is_empty()
            })?;
            required_sha(row, "manifest_sha256", "dataset version record")?;
            nonnegative_integer(row, "created_at_ms", "dataset version record")?;
            required_string(row, "version_class", "dataset version record", |value| {
                matches!(value, "genesis" | "derived")
            })?;
            required_string(row, "state", "dataset version record", |value| {
                matches!(value, "candidate" | "admitted" | "retired" | "refused")
            })?;
        }
        "transform" => {
            exact_keys(
                row,
                &[
                    "code_sha256",
                    "config_sha256",
                    "determinism_state",
                    "id",
                    "kind",
                    "parameters_sha256",
                    "producer_identity",
                ],
                "transform record",
            )?;
            required_string(row, "producer_identity", "transform record", |value| {
                validate_identity(value, "transform producer identity").is_ok()
            })?;
            required_sha(row, "code_sha256", "transform record")?;
            required_sha(row, "config_sha256", "transform record")?;
            required_sha(row, "parameters_sha256", "transform record")?;
            required_string(row, "determinism_state", "transform record", |value| {
                matches!(value, "deterministic" | "refused")
            })?;
        }
        "membership" => {
            exact_keys(
                row,
                &[
                    "admission_state",
                    "domain",
                    "exact_sha256",
                    "id",
                    "kind",
                    "near_dedup_cluster",
                    "register",
                    "shard_id",
                    "split",
                    "tokenizer_sha256",
                    "window_end",
                    "window_start",
                ],
                "membership record",
            )?;
            for (key, label) in [
                ("domain", "membership domain"),
                ("shard_id", "membership shard identity"),
                ("near_dedup_cluster", "membership near-dedup cluster"),
            ] {
                required_string(row, key, "membership record", |value| {
                    validate_identity(value, label).is_ok()
                })?;
            }
            required_string(row, "register", "membership record", |value| {
                matches!(value, "L3" | "L4" | "L5" | "experience")
            })?;
            required_string(row, "split", "membership record", |value| {
                matches!(
                    value,
                    "train" | "heldout" | "validation" | "test" | "protected_eval"
                )
            })?;
            required_sha(row, "tokenizer_sha256", "membership record")?;
            required_sha(row, "exact_sha256", "membership record")?;
            let window_start = integer_value(row, "window_start", "membership record")?;
            let window_end = integer_value(row, "window_end", "membership record")?;
            if window_start < 0 || window_end <= window_start {
                return invalid("membership window must be a nonempty nonnegative range");
            }
            required_string(row, "admission_state", "membership record", |value| {
                matches!(value, "admitted" | "excluded" | "refused" | "quarantined")
            })?;
        }
        "protected_eval" => {
            exact_keys(
                row,
                &[
                    "exclusion_reason",
                    "frozen_at_ms",
                    "frozen_manifest_sha256",
                    "id",
                    "kind",
                    "near_dup_ruling",
                    "ngram_ruling",
                    "overlap_state",
                    "test_set_sha256",
                ],
                "protected evaluation record",
            )?;
            required_sha(row, "frozen_manifest_sha256", "protected evaluation record")?;
            required_sha(row, "test_set_sha256", "protected evaluation record")?;
            for key in ["ngram_ruling", "near_dup_ruling"] {
                required_string(row, key, "protected evaluation record", |value| {
                    matches!(value, "clear" | "excluded" | "refused" | "not_run")
                })?;
            }
            optional_string(row, "exclusion_reason", "protected evaluation record")?;
            required_string(
                row,
                "overlap_state",
                "protected evaluation record",
                |value| {
                    matches!(
                        value,
                        "disjoint" | "isolated" | "overlap_detected" | "unknown"
                    )
                },
            )?;
            nonnegative_integer(row, "frozen_at_ms", "protected evaluation record")?;
            let ngram_ruling = string_value(row, "ngram_ruling", "protected evaluation record")?;
            let near_dup_ruling =
                string_value(row, "near_dup_ruling", "protected evaluation record")?;
            let overlap_state = string_value(row, "overlap_state", "protected evaluation record")?;
            let clean = ngram_ruling == "clear"
                && near_dup_ruling == "clear"
                && overlap_state == "disjoint";
            let not_run = ngram_ruling == "not_run"
                && near_dup_ruling == "not_run"
                && overlap_state == "isolated";
            if (ngram_ruling == "not_run"
                || near_dup_ruling == "not_run"
                || overlap_state == "isolated")
                && !not_run
            {
                return invalid(
                    "protected evaluation not_run rulings require the exact not_run/not_run/isolated tuple",
                );
            }
            let exclusion_reason = row.get("exclusion_reason").and_then(Value::as_str);
            if (clean || not_run) != exclusion_reason.is_none() {
                return invalid(
                    "protected evaluation exclusion_reason must be absent only for a fully disjoint clear ruling or an isolated not_run evaluation",
                );
            }
        }
        "consumer_attempt" => {
            exact_keys(
                row,
                &[
                    "checkpoint_sha256",
                    "config_sha256",
                    "evaluator_sha256",
                    "id",
                    "kind",
                    "model_sha256",
                    "run_attempt_id",
                    "source_tree_sha",
                    "state",
                    "tokenizer_sha256",
                ],
                "consumer attempt record",
            )?;
            let run_attempt_id = string_value(row, "run_attempt_id", "consumer attempt record")?;
            validate_identity(run_attempt_id, "consumer run attempt identity")?;
            if id != run_attempt_id {
                return invalid("consumer attempt id must equal run_attempt_id");
            }
            for key in [
                "model_sha256",
                "checkpoint_sha256",
                "tokenizer_sha256",
                "config_sha256",
                "evaluator_sha256",
            ] {
                required_sha(row, key, "consumer attempt record")?;
            }
            required_git_sha(row, "source_tree_sha", "consumer attempt record")?;
            required_string(row, "state", "consumer attempt record", |value| {
                matches!(value, "admitted" | "refused" | "completed")
            })?;
        }
        "experience" => {
            exact_keys(
                row,
                &[
                    "action_sha256",
                    "deletion_state",
                    "id",
                    "kind",
                    "model_sha256",
                    "observation_sha256",
                    "observed_at_ms",
                    "outcome_sha256",
                    "privacy_class",
                    "retention_class",
                    "sequence",
                    "task_identity",
                    "tool_call_sha256",
                    "uncertainty_basis_points",
                    "verifier_sha256",
                ],
                "experience record",
            )?;
            required_string(row, "task_identity", "experience record", |value| {
                validate_identity(value, "experience task identity").is_ok()
            })?;
            for key in [
                "observation_sha256",
                "action_sha256",
                "verifier_sha256",
                "outcome_sha256",
                "model_sha256",
            ] {
                required_sha(row, key, "experience record")?;
            }
            optional_sha(row, "tool_call_sha256", "experience record")?;
            let uncertainty = integer_value(row, "uncertainty_basis_points", "experience record")?;
            if !(0..=10_000).contains(&uncertainty) {
                return invalid("experience uncertainty_basis_points must be in 0..=10000");
            }
            nonnegative_integer(row, "observed_at_ms", "experience record")?;
            nonnegative_integer(row, "sequence", "experience record")?;
            required_string(row, "privacy_class", "experience record", |value| {
                matches!(value, "public" | "private" | "restricted")
            })?;
            required_string(row, "retention_class", "experience record", |value| {
                matches!(value, "ephemeral" | "retained" | "legal_hold")
            })?;
            required_string(row, "deletion_state", "experience record", |value| {
                matches!(value, "active" | "deleted" | "quarantined")
            })?;
        }
        "receipt" => {
            exact_keys(
                row,
                &[
                    "id",
                    "kind",
                    "observed_at_ms",
                    "producing_authority",
                    "receipt_class",
                    "sha256",
                    "state",
                ],
                "receipt record",
            )?;
            let digest = required_sha(row, "sha256", "receipt record")?;
            if id != format!("sha256:{digest}") {
                return invalid("receipt id must equal sha256:<sha256>");
            }
            required_string(row, "producing_authority", "receipt record", |value| {
                matches!(
                    value,
                    "ember_lab" | "corpus_connector" | "evaluation" | "training"
                )
            })?;
            required_string(row, "receipt_class", "receipt record", |value| {
                matches!(
                    value,
                    "acquisition" | "transform" | "evaluation" | "consumer" | "experience"
                )
            })?;
            nonnegative_integer(row, "observed_at_ms", "receipt record")?;
            required_string(row, "state", "receipt record", |value| {
                matches!(value, "accepted" | "refused" | "superseded")
            })?;
        }
        _ => unreachable!(),
    }
    Ok(())
}

fn validate_edge(value: &Value) -> Result<()> {
    let row = object(value, "edge")?;
    exact_keys(
        row,
        &[
            "from_id",
            "from_kind",
            "kind",
            "ordinal",
            "payload",
            "to_id",
            "to_kind",
        ],
        "edge",
    )?;
    let kind = string_value(row, "kind", "edge")?;
    if !EDGE_KINDS.contains(&kind) {
        return invalid(format!("unknown edge kind {kind}"));
    }
    let from_kind = string_value(row, "from_kind", "edge")?;
    let to_kind = string_value(row, "to_kind", "edge")?;
    if !RECORD_KINDS.contains(&from_kind) || !RECORD_KINDS.contains(&to_kind) {
        return invalid("edge endpoint uses an unknown record kind");
    }
    validate_identity(string_value(row, "from_id", "edge")?, "edge from_id")?;
    validate_identity(string_value(row, "to_id", "edge")?, "edge to_id")?;
    nonnegative_integer(row, "ordinal", "edge")?;
    validate_edge_payload(
        kind,
        row.get("payload")
            .ok_or_else(|| invalid_error("edge payload is missing"))?,
    )?;
    let expected = match kind {
        "source_object" => ("source", "immutable_object"),
        "object_receipt" => ("immutable_object", "receipt"),
        "dataset_parent" => ("dataset_version", "dataset_version"),
        "transform_parent" => ("transform", "dataset_version"),
        "transform_input" | "transform_output" => ("transform", "immutable_object"),
        "transform_receipt" => ("transform", "receipt"),
        "dataset_transform" => ("dataset_version", "transform"),
        "version_membership" => ("dataset_version", "membership"),
        "membership_object" => ("membership", "immutable_object"),
        "evaluation_object" => ("protected_eval", "immutable_object"),
        "evaluation_receipt" => ("protected_eval", "receipt"),
        "consumer_dataset" => ("consumer_attempt", "dataset_version"),
        "consumer_evaluation" => ("consumer_attempt", "protected_eval"),
        "consumer_receipt" => ("consumer_attempt", "receipt"),
        "experience_consumer" => ("experience", "consumer_attempt"),
        "experience_receipt" => ("experience", "receipt"),
        "receipt_supersession" => ("receipt", "receipt"),
        _ => unreachable!(),
    };
    if (from_kind, to_kind) != expected {
        return invalid(format!(
            "edge kind {kind} requires {} -> {}",
            expected.0, expected.1
        ));
    }
    Ok(())
}

fn validate_edge_endpoints(records: &[Value], edges: &[Value]) -> Result<()> {
    let identities: BTreeSet<(String, String)> = records
        .iter()
        .map(|record| {
            let row = object(record, "record")?;
            Ok((
                string_value(row, "kind", "record")?.to_string(),
                string_value(row, "id", "record")?.to_string(),
            ))
        })
        .collect::<Result<_>>()?;
    for edge in edges {
        let row = object(edge, "edge")?;
        for (kind_key, id_key) in [("from_kind", "from_id"), ("to_kind", "to_id")] {
            let endpoint = (
                string_value(row, kind_key, "edge")?.to_string(),
                string_value(row, id_key, "edge")?.to_string(),
            );
            if !identities.contains(&endpoint) {
                return invalid(format!(
                    "edge endpoint {}/{} is absent from the manifest",
                    endpoint.0, endpoint.1
                ));
            }
        }
    }
    Ok(())
}

#[derive(Default)]
struct RelationIndex {
    outgoing: BTreeMap<(String, String, String), Vec<String>>,
    incoming: BTreeMap<(String, String, String), Vec<String>>,
}

impl RelationIndex {
    fn from_edges(edges: &[Value]) -> Result<Self> {
        let mut index = Self::default();
        for edge in edges {
            let row = object(edge, "edge")?;
            let edge_kind = string_value(row, "kind", "edge")?.to_string();
            let from_kind = string_value(row, "from_kind", "edge")?.to_string();
            let from_id = string_value(row, "from_id", "edge")?.to_string();
            let to_kind = string_value(row, "to_kind", "edge")?.to_string();
            let to_id = string_value(row, "to_id", "edge")?.to_string();
            index
                .outgoing
                .entry((edge_kind.clone(), from_kind, from_id.clone()))
                .or_default()
                .push(to_id.clone());
            index
                .incoming
                .entry((edge_kind, to_kind, to_id))
                .or_default()
                .push(from_id);
        }
        Ok(index)
    }

    fn outgoing(&self, edge_kind: &str, from_kind: &str, from_id: &str) -> &[String] {
        self.outgoing
            .get(&(
                edge_kind.to_string(),
                from_kind.to_string(),
                from_id.to_string(),
            ))
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    fn incoming(&self, edge_kind: &str, to_kind: &str, to_id: &str) -> &[String] {
        self.incoming
            .get(&(
                edge_kind.to_string(),
                to_kind.to_string(),
                to_id.to_string(),
            ))
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }
}

fn validate_required_relations(records: &[Value], edges: &[Value]) -> Result<()> {
    validate_receipt_supersession(records, edges)?;
    let relations = RelationIndex::from_edges(edges)?;
    validate_not_run_evaluation_consumers_with_index(records, &relations)?;
    let mut admitted_training_objects = BTreeSet::new();
    let mut admitted_heldout_objects = BTreeSet::new();
    let mut protected_evaluation_objects = BTreeSet::new();
    for record in records {
        let row = object(record, "record")?;
        let kind = string_value(row, "kind", "record")?;
        let id = string_value(row, "id", "record")?;
        match kind {
            "source" if string_value(row, "license_verdict", "source record")? == "accepted" => {
                let objects = relations.outgoing("source_object", "source", id);
                require_nonempty(objects, "accepted source", id, "source_object")?;
                for object_id in objects {
                    let receipts =
                        relations.outgoing("object_receipt", "immutable_object", object_id);
                    require_nonempty(receipts, "source object", object_id, "object_receipt")?;
                }
            }
            "dataset_version" => {
                let parents = relations.outgoing("dataset_parent", kind, id);
                let transforms = relations.outgoing("dataset_transform", kind, id);
                match string_value(row, "version_class", "dataset version record")? {
                    "genesis" => {
                        if !parents.is_empty() || !transforms.is_empty() {
                            return invalid(format!(
                                "genesis dataset version {id} cannot claim parent or transform lineage"
                            ));
                        }
                    }
                    "derived" => {
                        require_exactly_one(
                            parents,
                            "derived dataset version",
                            id,
                            "dataset_parent",
                        )?;
                        require_exactly_one(
                            transforms,
                            "derived dataset version",
                            id,
                            "dataset_transform",
                        )?;
                        let transform_parents =
                            relations.outgoing("transform_parent", "transform", &transforms[0]);
                        require_exactly_one(
                            transform_parents,
                            "dataset transform",
                            &transforms[0],
                            "transform_parent",
                        )?;
                        if transform_parents[0] != parents[0] {
                            return invalid(format!(
                                "derived dataset version {id} and transform {} bind different parents",
                                transforms[0]
                            ));
                        }
                    }
                    _ => unreachable!(),
                }
            }
            "transform" => {
                require_exactly_one(
                    relations.outgoing("transform_parent", kind, id),
                    "transform",
                    id,
                    "transform_parent",
                )?;
                require_nonempty(
                    relations.outgoing("transform_input", kind, id),
                    "transform",
                    id,
                    "transform_input",
                )?;
                require_nonempty(
                    relations.outgoing("transform_output", kind, id),
                    "transform",
                    id,
                    "transform_output",
                )?;
                require_exactly_one(
                    relations.outgoing("transform_receipt", kind, id),
                    "transform",
                    id,
                    "transform_receipt",
                )?;
            }
            "membership" => {
                require_exactly_one(
                    relations.incoming("version_membership", kind, id),
                    "membership",
                    id,
                    "version_membership",
                )?;
                let objects = relations.outgoing("membership_object", kind, id);
                require_exactly_one(objects, "membership", id, "membership_object")?;
                let expected_object = format!(
                    "sha256:{}",
                    required_sha(row, "exact_sha256", "membership record")?
                );
                if objects[0] != expected_object {
                    return invalid(format!(
                        "membership {id} exact_sha256 does not match membership_object"
                    ));
                }
                if string_value(row, "admission_state", "membership record")? == "admitted" {
                    match string_value(row, "split", "membership record")? {
                        "train" => {
                            admitted_training_objects.insert(objects[0].clone());
                        }
                        "heldout" => {
                            admitted_heldout_objects.insert(objects[0].clone());
                        }
                        _ => {}
                    }
                }
            }
            "protected_eval" => {
                let objects = relations.outgoing("evaluation_object", kind, id);
                require_exactly_one(objects, "protected evaluation", id, "evaluation_object")?;
                let expected_object = format!(
                    "sha256:{}",
                    required_sha(row, "test_set_sha256", "protected evaluation record")?
                );
                if objects[0] != expected_object {
                    return invalid(format!(
                        "protected evaluation {id} test_set_sha256 does not match evaluation_object"
                    ));
                }
                if string_value(row, "overlap_state", "protected evaluation record")? == "disjoint"
                {
                    protected_evaluation_objects.insert(objects[0].clone());
                }
                require_exactly_one(
                    relations.outgoing("evaluation_receipt", kind, id),
                    "protected evaluation",
                    id,
                    "evaluation_receipt",
                )?;
            }
            "consumer_attempt" => {
                for edge_kind in [
                    "consumer_dataset",
                    "consumer_evaluation",
                    "consumer_receipt",
                ] {
                    require_exactly_one(
                        relations.outgoing(edge_kind, kind, id),
                        "consumer attempt",
                        id,
                        edge_kind,
                    )?;
                }
            }
            "experience" => {
                for edge_kind in ["experience_consumer", "experience_receipt"] {
                    require_exactly_one(
                        relations.outgoing(edge_kind, kind, id),
                        "experience",
                        id,
                        edge_kind,
                    )?;
                }
            }
            "receipt" if string_value(row, "state", "receipt record")? == "superseded" => {
                require_exactly_one(
                    relations.incoming("receipt_supersession", kind, id),
                    "superseded receipt",
                    id,
                    "receipt_supersession",
                )?;
            }
            _ => {}
        }
    }
    if let Some(overlap) = admitted_training_objects
        .intersection(&protected_evaluation_objects)
        .next()
    {
        return invalid(format!(
            "admitted training membership overlaps protected evaluation object {overlap}"
        ));
    }
    if let Some(overlap) = admitted_training_objects
        .intersection(&admitted_heldout_objects)
        .next()
    {
        return invalid(format!(
            "admitted heldout membership overlaps admitted training object {overlap}"
        ));
    }
    Ok(())
}

#[cfg(test)]
fn validate_not_run_evaluation_consumers(records: &[Value], edges: &[Value]) -> Result<()> {
    let relations = RelationIndex::from_edges(edges)?;
    validate_not_run_evaluation_consumers_with_index(records, &relations)
}

fn validate_not_run_evaluation_consumers_with_index(
    records: &[Value],
    relations: &RelationIndex,
) -> Result<()> {
    let admitted_training_memberships: Vec<&Map<String, Value>> = records
        .iter()
        .filter_map(Value::as_object)
        .filter(|row| {
            row.get("kind").and_then(Value::as_str) == Some("membership")
                && row.get("split").and_then(Value::as_str) == Some("train")
                && row.get("admission_state").and_then(Value::as_str) == Some("admitted")
        })
        .collect();
    for record in records {
        let row = object(record, "record")?;
        if string_value(row, "kind", "record")? != "protected_eval"
            || string_value(row, "ngram_ruling", "protected evaluation record")? != "not_run"
        {
            continue;
        }
        let id = string_value(row, "id", "protected evaluation record")?;
        let consumers = relations.incoming("consumer_evaluation", "protected_eval", id);
        require_exactly_one(
            consumers,
            "not_run protected evaluation",
            id,
            "consumer_evaluation",
        )?;
        if !consumers[0].starts_with("attempt:issue1581-catalog-evaluation:") {
            return invalid(format!(
                "not_run protected evaluation {id} is not bound to an evaluation consumer"
            ));
        }
        let evaluation_objects = relations.outgoing("evaluation_object", "protected_eval", id);
        require_exactly_one(
            evaluation_objects,
            "not_run protected evaluation",
            id,
            "evaluation_object",
        )?;
        for membership in &admitted_training_memberships {
            let membership_id = string_value(membership, "id", "membership record")?;
            if relations
                .outgoing("membership_object", "membership", membership_id)
                .contains(&evaluation_objects[0])
            {
                return invalid(format!(
                    "not_run protected evaluation {id} cannot be an admitted training object"
                ));
            }
        }
    }
    Ok(())
}

fn validate_edge_payload(kind: &str, value: &Value) -> Result<()> {
    let payload = object(value, &format!("{kind} edge payload"))?;
    // Relation semantics are carried by the closed edge columns and endpoint
    // record schemas. Every current relation deliberately has an empty
    // payload, so unknown or future fields must refuse rather than persist
    // an unvalidated authority extension.
    let expected: &[&str] = match kind {
        "source_object"
        | "object_receipt"
        | "dataset_parent"
        | "transform_parent"
        | "transform_input"
        | "transform_output"
        | "transform_receipt"
        | "dataset_transform"
        | "version_membership"
        | "membership_object"
        | "evaluation_object"
        | "evaluation_receipt"
        | "consumer_dataset"
        | "consumer_evaluation"
        | "consumer_receipt"
        | "experience_consumer"
        | "experience_receipt"
        | "receipt_supersession" => &[],
        _ => unreachable!("edge kind is validated before its payload"),
    };
    exact_keys(payload, expected, &format!("{kind} edge payload"))
}

fn validate_receipt_supersession(records: &[Value], edges: &[Value]) -> Result<()> {
    let receipt_states: BTreeMap<String, String> = records
        .iter()
        .filter(|record| record.get("kind").and_then(Value::as_str) == Some("receipt"))
        .map(|record| {
            let row = object(record, "receipt record")?;
            Ok((
                string_value(row, "id", "receipt record")?.to_string(),
                string_value(row, "state", "receipt record")?.to_string(),
            ))
        })
        .collect::<Result<_>>()?;

    for edge in edges {
        let row = object(edge, "edge")?;
        if string_value(row, "kind", "edge")? != "receipt_supersession" {
            continue;
        }
        let from_id = string_value(row, "from_id", "edge")?;
        let to_id = string_value(row, "to_id", "edge")?;
        let from_state = receipt_states
            .get(from_id)
            .ok_or_else(|| invalid_error("receipt supersession source is foreign"))?;
        let to_state = receipt_states
            .get(to_id)
            .ok_or_else(|| invalid_error("receipt supersession target is foreign"))?;
        if from_id == to_id
            || !matches!(from_state.as_str(), "accepted" | "refused")
            || to_state != "superseded"
        {
            return invalid(format!(
                "receipt supersession must point from a non-stale receipt to a distinct superseded receipt: {from_id} ({from_state}) -> {to_id} ({to_state})"
            ));
        }
    }
    Ok(())
}

fn require_nonempty(values: &[String], subject: &str, id: &str, edge_kind: &str) -> Result<()> {
    if values.is_empty() {
        return invalid(format!("{subject} {id} requires {edge_kind}"));
    }
    Ok(())
}

fn require_exactly_one(values: &[String], subject: &str, id: &str, edge_kind: &str) -> Result<()> {
    if values.len() != 1 {
        return invalid(format!(
            "{subject} {id} requires exactly one {edge_kind} relation"
        ));
    }
    Ok(())
}

fn canonical_manifest_bytes(records: &[Value], edges: &[Value]) -> Result<Vec<u8>> {
    Ok(serde_json::to_vec(&json!({
        "schema_version": MANIFEST_SCHEMA,
        "records": records,
        "edges": edges,
    }))?)
}

fn record_sort_key(value: &Value) -> (usize, String) {
    let row = value.as_object().expect("validated record");
    let kind = row
        .get("kind")
        .and_then(Value::as_str)
        .expect("validated kind");
    let rank = RECORD_KINDS
        .iter()
        .position(|candidate| candidate == &kind)
        .unwrap();
    (
        rank,
        row.get("id").and_then(Value::as_str).unwrap().to_string(),
    )
}

fn edge_sort_key(value: &Value) -> (usize, String, String, i64) {
    let row = value.as_object().expect("validated edge");
    let kind = row
        .get("kind")
        .and_then(Value::as_str)
        .expect("validated kind");
    let rank = EDGE_KINDS
        .iter()
        .position(|candidate| candidate == &kind)
        .unwrap();
    (
        rank,
        row.get("from_id")
            .and_then(Value::as_str)
            .unwrap()
            .to_string(),
        row.get("to_id")
            .and_then(Value::as_str)
            .unwrap()
            .to_string(),
        row.get("ordinal").and_then(Value::as_i64).unwrap(),
    )
}

fn object<'a>(value: &'a Value, context: &str) -> Result<&'a Map<String, Value>> {
    value
        .as_object()
        .ok_or_else(|| invalid_error(format!("{context} must be an object")))
}

fn required_array<'a>(
    row: &'a Map<String, Value>,
    key: &str,
    context: &str,
) -> Result<&'a Vec<Value>> {
    row.get(key)
        .and_then(Value::as_array)
        .ok_or_else(|| invalid_error(format!("{context}.{key} must be an array")))
}

fn string_value<'a>(row: &'a Map<String, Value>, key: &str, context: &str) -> Result<&'a str> {
    row.get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| invalid_error(format!("{context}.{key} must be a string")))
}

fn integer_value(row: &Map<String, Value>, key: &str, context: &str) -> Result<i64> {
    row.get(key)
        .and_then(Value::as_i64)
        .ok_or_else(|| invalid_error(format!("{context}.{key} must be an integer")))
}

fn required_string(
    row: &Map<String, Value>,
    key: &str,
    context: &str,
    predicate: impl FnOnce(&str) -> bool,
) -> Result<()> {
    let value = string_value(row, key, context)?;
    if !predicate(value) {
        return invalid(format!("{context}.{key} is invalid"));
    }
    Ok(())
}

fn optional_string(row: &Map<String, Value>, key: &str, context: &str) -> Result<()> {
    match row.get(key) {
        Some(Value::Null) | Some(Value::String(_)) => Ok(()),
        _ => invalid(format!("{context}.{key} must be a string or null")),
    }
}

fn required_sha<'a>(row: &'a Map<String, Value>, key: &str, context: &str) -> Result<&'a str> {
    let value = string_value(row, key, context)?;
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return invalid(format!(
            "{context}.{key} must be 64 lowercase hexadecimal characters"
        ));
    }
    Ok(value)
}

fn optional_sha(row: &Map<String, Value>, key: &str, context: &str) -> Result<()> {
    match row.get(key) {
        Some(Value::Null) => Ok(()),
        Some(Value::String(_)) => {
            required_sha(row, key, context)?;
            Ok(())
        }
        _ => invalid(format!("{context}.{key} must be a SHA-256 or null")),
    }
}

fn required_git_sha<'a>(row: &'a Map<String, Value>, key: &str, context: &str) -> Result<&'a str> {
    let value = string_value(row, key, context)?;
    if value.len() != 40
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return invalid(format!(
            "{context}.{key} must be 40 lowercase hexadecimal characters"
        ));
    }
    Ok(value)
}

fn nonnegative_integer(row: &Map<String, Value>, key: &str, context: &str) -> Result<()> {
    if integer_value(row, key, context)? < 0 {
        return invalid(format!("{context}.{key} must be nonnegative"));
    }
    Ok(())
}

fn positive_integer(row: &Map<String, Value>, key: &str, context: &str) -> Result<()> {
    if integer_value(row, key, context)? <= 0 {
        return invalid(format!("{context}.{key} must be positive"));
    }
    Ok(())
}

fn validate_identity(value: &str, context: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 160
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b':' | b'.' | b'_' | b'-'))
    {
        return invalid(format!("{context} is not a stable portable identity"));
    }
    Ok(())
}

fn exact_keys(row: &Map<String, Value>, expected: &[&str], context: &str) -> Result<()> {
    let actual: BTreeSet<&str> = row.keys().map(String::as_str).collect();
    let expected: BTreeSet<&str> = expected.iter().copied().collect();
    if actual != expected {
        return invalid(format!("{context} has missing or unknown fields"));
    }
    Ok(())
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn invalid<T>(detail: impl Into<String>) -> Result<T> {
    Err(invalid_error(detail))
}

fn invalid_error(detail: impl Into<String>) -> EmberLabError {
    EmberLabError::InvalidDataCatalog {
        detail: detail.into(),
    }
}

const OVERLAP_AUDIT_SCHEMA: &str = "ember-data-catalog-train-heldout-intersection-audit-v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QuarantineOverlapOutcome {
    pub audit_self_sha256: String,
    pub overlap_count: usize,
    pub quarantined: usize,
    pub already_quarantined: usize,
}

/// Remediates a REFUSED train/heldout intersection audit (#2105): every heldout membership the
/// audit names is moved `admitted -> quarantined` in one transaction, each move is appended to
/// `data_catalog_admission_events`, and the whole graph is re-validated before commit so the
/// commit itself proves the overlap set is empty afterwards. The audit is bound by its own
/// `self_sha256` (recomputed over the canonical audit body) and every named pair must exist in
/// THIS catalog as an admitted heldout membership and an admitted train membership over the same
/// object; a row that names anything else refuses the whole call.
pub(crate) fn quarantine_overlap_memberships(
    conn: &mut Connection,
    audit_bytes: &[u8],
    reason: &str,
    quarantined_at_ms: i64,
) -> Result<QuarantineOverlapOutcome> {
    if reason.is_empty() {
        return invalid("overlap quarantine requires a nonempty reason");
    }
    let audit: Value = serde_json::from_slice(audit_bytes)?;
    let root = object(&audit, "overlap audit")?;
    required_string(root, "schema_version", "overlap audit", |value| {
        value == OVERLAP_AUDIT_SCHEMA
    })?;
    required_string(root, "result", "overlap audit", |value| value == "REFUSED")?;
    let claimed_self = required_sha(root, "self_sha256", "overlap audit")?.to_string();
    let mut body = root.clone();
    body.remove("self_sha256");
    let computed_self = sha256(&canonical_json_bytes(&Value::Object(body))?);
    if computed_self != claimed_self {
        return invalid(format!(
            "overlap audit self_sha256 {claimed_self} does not match its body ({computed_self})"
        ));
    }
    let overlaps = required_array(root, "overlaps", "overlap audit")?;
    if overlaps.is_empty() {
        return invalid("overlap audit names no overlaps; nothing to quarantine");
    }

    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let mut quarantined = 0;
    let mut already_quarantined = 0;
    let mut seen = BTreeSet::new();
    for (index, overlap) in overlaps.iter().enumerate() {
        let row = object(overlap, "overlap row")?;
        let digest = required_sha(row, "exact_sha256", "overlap row")?;
        let heldout_id = string_value(row, "heldout_membership_record_id", "overlap row")?;
        let train_id = string_value(row, "train_membership_record_id", "overlap row")?;
        if !seen.insert(heldout_id.to_string()) {
            return invalid(format!(
                "overlap row {index} repeats heldout membership {heldout_id}"
            ));
        }
        let train = membership_payload(&tx, train_id)?.ok_or_else(|| {
            invalid_error(format!(
                "overlap row {index} names train membership {train_id} that is not in this catalog"
            ))
        })?;
        let train_row = object(&train, "train membership")?;
        if string_value(train_row, "split", "train membership")? != "train"
            || string_value(train_row, "admission_state", "train membership")? != "admitted"
            || string_value(train_row, "exact_sha256", "train membership")? != digest
        {
            return invalid(format!(
                "overlap row {index}: {train_id} is not an admitted train membership over {digest}"
            ));
        }
        let heldout = membership_payload(&tx, heldout_id)?.ok_or_else(|| {
            invalid_error(format!(
                "overlap row {index} names heldout membership {heldout_id} that is not in this catalog"
            ))
        })?;
        let heldout_row = object(&heldout, "heldout membership")?;
        if string_value(heldout_row, "split", "heldout membership")? != "heldout"
            || string_value(heldout_row, "exact_sha256", "heldout membership")? != digest
        {
            return invalid(format!(
                "overlap row {index}: {heldout_id} is not a heldout membership over {digest}"
            ));
        }
        let from_state = string_value(heldout_row, "admission_state", "heldout membership")?;
        match from_state {
            "quarantined" => {
                already_quarantined += 1;
                continue;
            }
            "admitted" => {}
            other => {
                return invalid(format!(
                    "overlap row {index}: {heldout_id} is {other}, not admitted; refusing to relabel"
                ));
            }
        }
        let mut updated_row = heldout_row.clone();
        updated_row.insert("admission_state".into(), json!("quarantined"));
        let updated = Value::Object(updated_row);
        validate_record(&updated)?;
        let payload_json = serde_json::to_string(&updated)?;
        let payload_sha256 = sha256(payload_json.as_bytes());
        let changed = tx.execute(
            "UPDATE data_catalog_records SET payload_json=?1,payload_sha256=?2
             WHERE kind='membership' AND record_id=?3",
            params![payload_json, payload_sha256, heldout_id],
        )?;
        if changed != 1 {
            return invalid(format!(
                "overlap row {index}: membership {heldout_id} vanished during quarantine"
            ));
        }
        let event = json!({
            "membership_id": heldout_id,
            "from_state": "admitted",
            "to_state": "quarantined",
            "reason": reason,
            "audit_self_sha256": claimed_self,
            "train_membership_id": train_id,
            "exact_sha256": digest,
            "event_at_ms": quarantined_at_ms,
        });
        let event_json = serde_json::to_string(&event)?;
        let event_sha256 = sha256(event_json.as_bytes());
        tx.execute(
            "INSERT INTO data_catalog_admission_events(
                 membership_id,from_state,to_state,reason,audit_self_sha256,event_at_ms,
                 payload_json,payload_sha256
             ) VALUES(?1,'admitted','quarantined',?2,?3,?4,?5,?6)",
            params![
                heldout_id,
                reason,
                claimed_self,
                quarantined_at_ms,
                event_json,
                event_sha256
            ],
        )?;
        quarantined += 1;
    }

    // The commit is the proof: the remediated graph must satisfy every relation invariant,
    // including "no admitted heldout membership overlaps an admitted training object".
    let records = normalize_records(&query_payloads(
        &tx,
        "SELECT payload_json FROM data_catalog_records ORDER BY kind,record_id",
    )?)?;
    let edges = normalize_edges(&query_payloads(
        &tx,
        "SELECT payload_json FROM data_catalog_edges
         ORDER BY kind,from_kind,from_id,to_kind,to_id,ordinal",
    )?)?;
    validate_edge_endpoints(&records, &edges)?;
    validate_required_relations(&records, &edges)?;
    tx.commit()?;
    Ok(QuarantineOverlapOutcome {
        audit_self_sha256: claimed_self,
        overlap_count: overlaps.len(),
        quarantined,
        already_quarantined,
    })
}

fn membership_payload(conn: &Connection, record_id: &str) -> Result<Option<Value>> {
    let payload: Option<String> = conn
        .query_row(
            "SELECT payload_json FROM data_catalog_records
             WHERE kind='membership' AND record_id=?1",
            params![record_id],
            |row| row.get(0),
        )
        .optional()?;
    Ok(match payload {
        Some(text) => Some(serde_json::from_str(&text)?),
        None => None,
    })
}

/// Canonical form shared with the Python audit producer: keys sorted, compact separators,
/// non-ASCII escaped (`json.dumps(sort_keys=True, separators=(",", ":"))`).
fn canonical_json_bytes(value: &Value) -> Result<Vec<u8>> {
    let mut out = String::new();
    write_canonical_json(value, &mut out)?;
    Ok(out.into_bytes())
}

fn write_canonical_json(value: &Value, out: &mut String) -> Result<()> {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(flag) => out.push_str(if *flag { "true" } else { "false" }),
        Value::Number(number) => out.push_str(&number.to_string()),
        Value::String(text) => write_canonical_string(text, out),
        Value::Array(items) => {
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_canonical_json(item, out)?;
            }
            out.push(']');
        }
        Value::Object(map) => {
            let sorted: BTreeMap<&String, &Value> = map.iter().collect();
            out.push('{');
            for (index, (key, item)) in sorted.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_canonical_string(key, out);
                out.push(':');
                write_canonical_json(item, out)?;
            }
            out.push('}');
        }
    }
    Ok(())
}

fn write_canonical_string(text: &str, out: &mut String) {
    out.push('"');
    for ch in text.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            ch if (ch as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", ch as u32)),
            ch if (ch as u32) < 0x80 => out.push(ch),
            ch => {
                let mut units = [0u16; 2];
                for unit in ch.encode_utf16(&mut units) {
                    out.push_str(&format!("\\u{:04x}", unit));
                }
            }
        }
    }
    out.push('"');
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{Duration, Instant};

    fn not_run_record() -> Value {
        json!({
            "kind": "protected_eval",
            "id": "evaluation:heldout-not-run",
            "frozen_manifest_sha256": "a".repeat(64),
            "test_set_sha256": "a".repeat(64),
            "ngram_ruling": "not_run",
            "near_dup_ruling": "not_run",
            "exclusion_reason": null,
            "overlap_state": "isolated",
            "frozen_at_ms": 0
        })
    }

    fn edge(kind: &str, from_kind: &str, from_id: &str, to_kind: &str, to_id: &str) -> Value {
        json!({
            "kind": kind,
            "from_kind": from_kind,
            "from_id": from_id,
            "to_kind": to_kind,
            "to_id": to_id,
            "ordinal": 0,
            "payload": {}
        })
    }

    #[test]
    fn not_run_tuple_requires_an_evaluation_consumer() {
        let record = not_run_record();
        validate_record(&record).expect("the exact not_run/not_run/isolated tuple is valid");
        let evaluation_edge = edge(
            "consumer_evaluation",
            "consumer_attempt",
            "attempt:issue1581-catalog-evaluation:abc",
            "protected_eval",
            "evaluation:heldout-not-run",
        );
        let evaluation_object_edge = edge(
            "evaluation_object",
            "protected_eval",
            "evaluation:heldout-not-run",
            "immutable_object",
            &format!("sha256:{}", "a".repeat(64)),
        );
        validate_not_run_evaluation_consumers(
            std::slice::from_ref(&record),
            &[evaluation_edge, evaluation_object_edge.clone()],
        )
        .expect("evaluation consumer may bind an isolated not_run record");

        let training_edge = edge(
            "consumer_evaluation",
            "consumer_attempt",
            "attempt:issue1581-catalog-preflight:abc",
            "protected_eval",
            "evaluation:heldout-not-run",
        );
        assert!(validate_not_run_evaluation_consumers(
            std::slice::from_ref(&record),
            &[training_edge, evaluation_object_edge]
        )
        .is_err());

        let mut invalid_tuple = record;
        invalid_tuple["overlap_state"] = json!("disjoint");
        assert!(validate_record(&invalid_tuple).is_err());
    }

    #[test]
    fn not_run_object_can_never_be_an_admitted_training_object() {
        let record = not_run_record();
        let membership = json!({
            "kind": "membership",
            "id": "membership:train",
            "split": "train",
            "admission_state": "admitted"
        });
        let object_id = format!("sha256:{}", "a".repeat(64));
        let edges = vec![
            edge(
                "consumer_evaluation",
                "consumer_attempt",
                "attempt:issue1581-catalog-evaluation:abc",
                "protected_eval",
                "evaluation:heldout-not-run",
            ),
            edge(
                "evaluation_object",
                "protected_eval",
                "evaluation:heldout-not-run",
                "immutable_object",
                &object_id,
            ),
            edge(
                "membership_object",
                "membership",
                "membership:train",
                "immutable_object",
                &object_id,
            ),
        ];
        assert!(validate_not_run_evaluation_consumers(&[record, membership], &edges).is_err());
    }

    #[test]
    fn admitted_heldout_membership_cannot_overlap_training_object_at_import() {
        let digest = "b".repeat(64);
        let object_id = format!("sha256:{digest}");
        let records = vec![
            json!({
                "kind": "dataset_version",
                "id": "dataset:train",
                "version_class": "genesis"
            }),
            json!({
                "kind": "dataset_version",
                "id": "dataset:heldout",
                "version_class": "genesis"
            }),
            json!({
                "kind": "membership",
                "id": "membership:train",
                "split": "train",
                "admission_state": "admitted",
                "exact_sha256": digest
            }),
            json!({
                "kind": "membership",
                "id": "membership:heldout",
                "split": "heldout",
                "admission_state": "admitted",
                "exact_sha256": "b".repeat(64)
            }),
        ];
        let edges = vec![
            edge(
                "version_membership",
                "dataset_version",
                "dataset:train",
                "membership",
                "membership:train",
            ),
            edge(
                "membership_object",
                "membership",
                "membership:train",
                "immutable_object",
                &object_id,
            ),
            edge(
                "version_membership",
                "dataset_version",
                "dataset:heldout",
                "membership",
                "membership:heldout",
            ),
            edge(
                "membership_object",
                "membership",
                "membership:heldout",
                "immutable_object",
                &object_id,
            ),
        ];

        let error = validate_required_relations(&records, &edges)
            .expect_err("the import must reject one object admitted into train and heldout");
        assert!(error
            .to_string()
            .contains("admitted heldout membership overlaps admitted training object"));
    }

    #[test]
    fn relation_index_serves_row8_scale_without_per_record_edge_rescans() {
        let edge_count = 50_000;
        let edges: Vec<Value> = (0..edge_count)
            .map(|index| {
                edge(
                    "membership_object",
                    "membership",
                    &format!("membership:row8:{index}"),
                    "immutable_object",
                    &format!("sha256:{index:064x}"),
                )
            })
            .collect();

        let started = Instant::now();
        let relations = RelationIndex::from_edges(&edges).expect("row8 relation index");
        for index in 0..edge_count {
            assert_eq!(
                relations.outgoing(
                    "membership_object",
                    "membership",
                    &format!("membership:row8:{index}"),
                ),
                &[format!("sha256:{index:064x}")]
            );
        }
        assert!(
            started.elapsed() < Duration::from_secs(10),
            "indexed row8 relation lookup exceeded 10 seconds"
        );
    }

    fn quarantine_fixture_manifest(heldout_admission_state: &str) -> Vec<u8> {
        let digest = "c".repeat(64);
        let object_id = format!("sha256:{digest}");
        let membership = |id: &str, split: &str, admission_state: &str| {
            json!({
                "kind": "membership",
                "id": id,
                "admission_state": admission_state,
                "domain": "statistics",
                "exact_sha256": digest,
                "near_dedup_cluster": "cluster-1",
                "register": "L3",
                "shard_id": "shard-1",
                "split": split,
                "tokenizer_sha256": "d".repeat(64),
                "window_end": 8,
                "window_start": 0
            })
        };
        let dataset = |id: &str| {
            json!({
                "kind": "dataset_version",
                "id": id,
                "created_at_ms": 0,
                "manifest_sha256": "e".repeat(64),
                "name": id,
                "state": "admitted",
                "version_class": "genesis"
            })
        };
        let manifest = json!({
            "schema_version": MANIFEST_SCHEMA,
            "records": [
                dataset("dataset:train"),
                dataset("dataset:heldout"),
                {
                    "kind": "immutable_object",
                    "id": object_id,
                    "sha256": digest,
                    "byte_count": 8,
                    "media_type": "text/plain",
                    "locator": format!("sha256/{}/{digest}", &digest[..2]),
                    "custody_state": "available"
                },
                membership("membership:train-1", "train", "admitted"),
                membership("membership:heldout-1", "heldout", heldout_admission_state),
            ],
            "edges": [
                edge("version_membership", "dataset_version", "dataset:train", "membership", "membership:train-1"),
                edge("membership_object", "membership", "membership:train-1", "immutable_object", &object_id),
                edge("version_membership", "dataset_version", "dataset:heldout", "membership", "membership:heldout-1"),
                edge("membership_object", "membership", "membership:heldout-1", "immutable_object", &object_id),
            ]
        });
        serde_json::to_vec(&manifest).unwrap()
    }

    /// The predecessor catalogs were produced before the overlap invariant existed, so the
    /// overlapping state can only be reached by writing the row directly, never by import.
    fn overlapping_catalog() -> Connection {
        let mut conn = Connection::open_in_memory().unwrap();
        migrate(&conn).unwrap();
        import_manifest(&mut conn, &quarantine_fixture_manifest("excluded"), 0)
            .expect("a non-overlapping catalog imports");
        let payload: String = conn
            .query_row(
                "SELECT payload_json FROM data_catalog_records WHERE record_id='membership:heldout-1'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        let mut record: Value = serde_json::from_str(&payload).unwrap();
        record["admission_state"] = json!("admitted");
        let payload_json = serde_json::to_string(&record).unwrap();
        conn.execute(
            "UPDATE data_catalog_records SET payload_json=?1,payload_sha256=?2
             WHERE record_id='membership:heldout-1'",
            params![payload_json.clone(), sha256(payload_json.as_bytes())],
        )
        .unwrap();
        conn
    }

    fn graph_validation(conn: &Connection) -> Result<()> {
        let records = normalize_records(
            &query_payloads(conn, "SELECT payload_json FROM data_catalog_records").unwrap(),
        )?;
        let edges = normalize_edges(&query_payloads(
            conn,
            "SELECT payload_json FROM data_catalog_edges",
        )?)?;
        validate_required_relations(&records, &edges)
    }

    fn overlap_audit(
        heldout_id: &str,
        train_id: &str,
        digest: &str,
        self_sha: Option<&str>,
    ) -> Vec<u8> {
        let mut body = json!({
            "schema_version": OVERLAP_AUDIT_SCHEMA,
            "result": "REFUSED",
            "catalog_raw_sha256": "f".repeat(64),
            "overlap_object_count": 1,
            "overlap_relation_count": 1,
            "scanned_membership_count": 2,
            "overlaps": [{
                "exact_sha256": digest,
                "heldout_dataset_id": "dataset:heldout",
                "heldout_domain": "statistics",
                "heldout_membership_record_id": heldout_id,
                "object_media_type": "text/plain",
                "train_dataset_id": "dataset:train",
                "train_domain": "statistics",
                "train_membership_record_id": train_id
            }]
        });
        let computed = sha256(&canonical_json_bytes(&body).unwrap());
        body["self_sha256"] = json!(self_sha.map(str::to_string).unwrap_or(computed));
        serde_json::to_vec(&body).unwrap()
    }

    #[test]
    fn quarantine_clears_the_overlap_and_the_commit_proves_it() {
        let mut conn = overlapping_catalog();
        let before = graph_validation(&conn).expect_err("the planted overlap must be invalid");
        assert!(before
            .to_string()
            .contains("admitted heldout membership overlaps"));

        let digest = "c".repeat(64);
        let audit = overlap_audit("membership:heldout-1", "membership:train-1", &digest, None);
        let outcome =
            quarantine_overlap_memberships(&mut conn, &audit, "issue2105 remediation", 7).unwrap();
        assert_eq!(outcome.overlap_count, 1);
        assert_eq!(outcome.quarantined, 1);
        assert_eq!(outcome.already_quarantined, 0);
        graph_validation(&conn).expect("the remediated graph satisfies every relation invariant");

        let (state, events): (String, i64) = conn
            .query_row(
                "SELECT json_extract(payload_json,'$.admission_state'),
                        (SELECT COUNT(*) FROM data_catalog_admission_events)
                 FROM data_catalog_records WHERE record_id='membership:heldout-1'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap();
        assert_eq!(state, "quarantined");
        assert_eq!(events, 1);

        let again =
            quarantine_overlap_memberships(&mut conn, &audit, "issue2105 remediation", 8).unwrap();
        assert_eq!((again.quarantined, again.already_quarantined), (0, 1));
    }

    #[test]
    fn quarantine_refuses_a_row_that_is_not_an_overlap_in_this_catalog() {
        let mut conn = overlapping_catalog();
        let digest = "c".repeat(64);
        // Planted negative: the train side names the heldout membership itself, which is not an
        // admitted train membership over the object; nothing may be relabelled.
        let audit = overlap_audit(
            "membership:heldout-1",
            "membership:heldout-1",
            &digest,
            None,
        );
        let error = quarantine_overlap_memberships(&mut conn, &audit, "planted", 1)
            .expect_err("a row that is not an admitted train/heldout pair refuses");
        assert!(error
            .to_string()
            .contains("not an admitted train membership"));
        let state: String = conn
            .query_row(
                "SELECT json_extract(payload_json,'$.admission_state')
                 FROM data_catalog_records WHERE record_id='membership:heldout-1'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(
            state, "admitted",
            "a refused call leaves the catalog untouched"
        );
        let events: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM data_catalog_admission_events",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(events, 0);
    }

    #[test]
    fn quarantine_refuses_an_audit_whose_self_hash_does_not_bind_its_body() {
        let mut conn = overlapping_catalog();
        let digest = "c".repeat(64);
        let audit = overlap_audit(
            "membership:heldout-1",
            "membership:train-1",
            &digest,
            Some(&"0".repeat(64)),
        );
        let error = quarantine_overlap_memberships(&mut conn, &audit, "planted", 1)
            .expect_err("a self_sha256 that does not match the body refuses");
        assert!(error.to_string().contains("does not match its body"));
    }

    #[test]
    fn canonical_json_matches_python_sorted_compact_ascii_dumps() {
        // json.dumps({"b": 1, "a": "é", "c": [true, None, "x\"y"]}, sort_keys=True, separators=(",", ":"))
        let value = json!({"b": 1, "a": "é", "c": [true, null, "x\"y"]});
        assert_eq!(
            String::from_utf8(canonical_json_bytes(&value).unwrap()).unwrap(),
            r#"{"a":"\u00e9","b":1,"c":[true,null,"x\"y"]}"#
        );
    }
}
