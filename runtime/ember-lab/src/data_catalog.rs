// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

use crate::{EmberLabError, Result};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

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
    let mut merged = existing.to_vec();
    for record in incoming {
        let identity = record_sort_key(record);
        if let Some(current) = merged
            .iter()
            .find(|candidate| record_sort_key(candidate) == identity)
        {
            if current != record {
                return invalid(format!(
                    "record identity {}/{} is already bound to different bytes",
                    string_value(object(record, "record")?, "kind", "record")?,
                    identity.1
                ));
            }
        } else {
            merged.push(record.clone());
        }
    }
    merged.sort_by_key(record_sort_key);
    Ok(merged)
}

fn merge_edges(existing: &[Value], incoming: &[Value]) -> Result<Vec<Value>> {
    let mut merged = existing.to_vec();
    for edge in incoming {
        let identity = edge_sort_key(edge);
        if let Some(current) = merged
            .iter()
            .find(|candidate| edge_sort_key(candidate) == identity)
        {
            if current != edge {
                return invalid(format!(
                    "edge identity is already bound to different bytes: {:?}",
                    identity
                ));
            }
        } else {
            merged.push(edge.clone());
        }
    }
    merged.sort_by_key(edge_sort_key);
    Ok(merged)
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
        let targets = outgoing_targets(&edges, "membership_object", "membership", id)?;
        require_exactly_one(&targets, "membership", id, "membership_object")?;
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
            "object_ids": outgoing_targets(&edges, "evaluation_object", "protected_eval", id)?,
            "overlap_state": string_value(row, "overlap_state", "protected evaluation record")?,
            "receipt_ids": outgoing_targets(&edges, "evaluation_receipt", "protected_eval", id)?,
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
            "dataset_version_ids": outgoing_targets(&edges, "consumer_dataset", "consumer_attempt", id)?,
            "evaluation_ids": outgoing_targets(&edges, "consumer_evaluation", "consumer_attempt", id)?,
            "model_sha256": string_value(row, "model_sha256", "consumer attempt record")?,
            "receipt_ids": outgoing_targets(&edges, "consumer_receipt", "consumer_attempt", id)?,
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
                matches!(value, "train" | "validation" | "test" | "protected_eval")
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
                    matches!(value, "clear" | "excluded" | "refused")
                })?;
            }
            optional_string(row, "exclusion_reason", "protected evaluation record")?;
            required_string(
                row,
                "overlap_state",
                "protected evaluation record",
                |value| matches!(value, "disjoint" | "overlap_detected" | "unknown"),
            )?;
            nonnegative_integer(row, "frozen_at_ms", "protected evaluation record")?;
            let clean = string_value(row, "ngram_ruling", "protected evaluation record")?
                == "clear"
                && string_value(row, "near_dup_ruling", "protected evaluation record")? == "clear"
                && string_value(row, "overlap_state", "protected evaluation record")? == "disjoint";
            let exclusion_reason = row.get("exclusion_reason").and_then(Value::as_str);
            if clean != exclusion_reason.is_none() {
                return invalid(
                    "protected evaluation exclusion_reason must be absent only for a fully disjoint clear ruling",
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
    object(
        row.get("payload")
            .ok_or_else(|| invalid_error("edge payload is missing"))?,
        "edge payload",
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

fn validate_required_relations(records: &[Value], edges: &[Value]) -> Result<()> {
    let mut admitted_training_objects = BTreeSet::new();
    let mut protected_evaluation_objects = BTreeSet::new();
    for record in records {
        let row = object(record, "record")?;
        let kind = string_value(row, "kind", "record")?;
        let id = string_value(row, "id", "record")?;
        match kind {
            "source" if string_value(row, "license_verdict", "source record")? == "accepted" => {
                let objects = outgoing_targets(edges, "source_object", "source", id)?;
                require_nonempty(&objects, "accepted source", id, "source_object")?;
                for object_id in objects {
                    let receipts =
                        outgoing_targets(edges, "object_receipt", "immutable_object", &object_id)?;
                    require_nonempty(&receipts, "source object", &object_id, "object_receipt")?;
                }
            }
            "dataset_version" => {
                let parents = outgoing_targets(edges, "dataset_parent", kind, id)?;
                let transforms = outgoing_targets(edges, "dataset_transform", kind, id)?;
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
                            &parents,
                            "derived dataset version",
                            id,
                            "dataset_parent",
                        )?;
                        require_exactly_one(
                            &transforms,
                            "derived dataset version",
                            id,
                            "dataset_transform",
                        )?;
                        let transform_parents = outgoing_targets(
                            edges,
                            "transform_parent",
                            "transform",
                            &transforms[0],
                        )?;
                        require_exactly_one(
                            &transform_parents,
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
                    &outgoing_targets(edges, "transform_parent", kind, id)?,
                    "transform",
                    id,
                    "transform_parent",
                )?;
                require_nonempty(
                    &outgoing_targets(edges, "transform_input", kind, id)?,
                    "transform",
                    id,
                    "transform_input",
                )?;
                require_nonempty(
                    &outgoing_targets(edges, "transform_output", kind, id)?,
                    "transform",
                    id,
                    "transform_output",
                )?;
                require_exactly_one(
                    &outgoing_targets(edges, "transform_receipt", kind, id)?,
                    "transform",
                    id,
                    "transform_receipt",
                )?;
            }
            "membership" => {
                require_exactly_one(
                    &incoming_sources(edges, "version_membership", kind, id)?,
                    "membership",
                    id,
                    "version_membership",
                )?;
                let objects = outgoing_targets(edges, "membership_object", kind, id)?;
                require_exactly_one(&objects, "membership", id, "membership_object")?;
                let expected_object = format!(
                    "sha256:{}",
                    required_sha(row, "exact_sha256", "membership record")?
                );
                if objects[0] != expected_object {
                    return invalid(format!(
                        "membership {id} exact_sha256 does not match membership_object"
                    ));
                }
                if string_value(row, "split", "membership record")? == "train"
                    && string_value(row, "admission_state", "membership record")? == "admitted"
                {
                    admitted_training_objects.insert(objects[0].clone());
                }
            }
            "protected_eval" => {
                let objects = outgoing_targets(edges, "evaluation_object", kind, id)?;
                require_exactly_one(&objects, "protected evaluation", id, "evaluation_object")?;
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
                    &outgoing_targets(edges, "evaluation_receipt", kind, id)?,
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
                        &outgoing_targets(edges, edge_kind, kind, id)?,
                        "consumer attempt",
                        id,
                        edge_kind,
                    )?;
                }
            }
            "experience" => {
                for edge_kind in ["experience_consumer", "experience_receipt"] {
                    require_exactly_one(
                        &outgoing_targets(edges, edge_kind, kind, id)?,
                        "experience",
                        id,
                        edge_kind,
                    )?;
                }
            }
            "receipt" if string_value(row, "state", "receipt record")? == "superseded" => {
                require_exactly_one(
                    &incoming_sources(edges, "receipt_supersession", kind, id)?,
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
    Ok(())
}

fn outgoing_targets(
    edges: &[Value],
    edge_kind: &str,
    from_kind: &str,
    from_id: &str,
) -> Result<Vec<String>> {
    let mut targets = Vec::new();
    for edge in edges {
        let row = object(edge, "edge")?;
        if string_value(row, "kind", "edge")? == edge_kind
            && string_value(row, "from_kind", "edge")? == from_kind
            && string_value(row, "from_id", "edge")? == from_id
        {
            targets.push(string_value(row, "to_id", "edge")?.to_string());
        }
    }
    Ok(targets)
}

fn incoming_sources(
    edges: &[Value],
    edge_kind: &str,
    to_kind: &str,
    to_id: &str,
) -> Result<Vec<String>> {
    let mut sources = Vec::new();
    for edge in edges {
        let row = object(edge, "edge")?;
        if string_value(row, "kind", "edge")? == edge_kind
            && string_value(row, "to_kind", "edge")? == to_kind
            && string_value(row, "to_id", "edge")? == to_id
        {
            sources.push(string_value(row, "from_id", "edge")?.to_string());
        }
    }
    Ok(sources)
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
