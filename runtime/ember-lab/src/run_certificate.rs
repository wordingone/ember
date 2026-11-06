// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! Wall A: the trainer runs only under a run certificate that ember-lab itself issued.
//!
//! `ember-lab resume` issues a certificate binding the composed data ledger, its C1/C2 receipt, the parent
//! checkpoint manifest and the code tree. The daemon's dispatch entry refuses any manifest whose program is a
//! trainer entrypoint unless the manifest names an issued, unconsumed certificate in
//! `env.EMBER_RUN_CERTIFICATE_SHA256` and binds the certified ledger by sha. A certificate admits exactly one job.
//!
//! Claim boundary: on one machine a same-user process could write this table directly. The wall is this
//! issuance ledger together with wall B (the pointer advances only for a certified child) and wall C (CI
//! refuses a change that removes or bypasses this check).
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::path::Path;

pub const CERTIFICATE_SCHEMA: &str = "ember-lab-run-certificate-v1";
pub const CERTIFICATE_ENV: &str = "EMBER_RUN_CERTIFICATE_SHA256";
/// Trainer entrypoints. A manifest whose program file name is one of these needs a certificate.
pub const TRAINER_ENTRYPOINTS: &[&str] = &["cia_step_runner.py", "certified_train_launch.py"];
const BOUND: &[&str] = &[
    "ledger_sha256",
    "c1c2_receipt_sha256",
    "parent_manifest_sha256",
    "code_tree_sha",
];

pub fn migrate(conn: &Connection) -> rusqlite::Result<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS run_certificates(
            certificate_sha256 TEXT PRIMARY KEY,
            ledger_sha256 TEXT NOT NULL,
            c1c2_receipt_sha256 TEXT NOT NULL,
            parent_manifest_sha256 TEXT NOT NULL,
            code_tree_sha TEXT NOT NULL,
            certificate_json TEXT NOT NULL,
            issued_at_ms INTEGER NOT NULL,
            consumed_by_job_id TEXT,
            consumed_at_ms INTEGER)",
    )
}

fn is_hex(v: &str, len: usize) -> bool {
    v.len() == len
        && v.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn file_sha256(path: &str) -> Result<String, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("{path}: {e}"))?;
    Ok(format!("{:x}", Sha256::digest(&bytes)))
}

/// Daemon-side issuance: the certificate must name `ledger_path` and `c1c2_receipt_path`; their bytes are
/// re-hashed here and must equal the certified shas, and the receipt must say PASS for this ledger. The caller's
/// own belief about either sha is never trusted.
pub fn issue_verified(
    conn: &Connection,
    certificate_bytes: &[u8],
    now_ms: i64,
) -> Result<String, String> {
    let cert: Value = serde_json::from_slice(certificate_bytes)
        .map_err(|e| format!("certificate is not JSON: {e}"))?;
    let path = |k: &str| {
        cert[k]
            .as_str()
            .map(str::to_string)
            .ok_or_else(|| format!("certificate lacks {k}"))
    };
    let (ledger_path, receipt_path) = (path("ledger_path")?, path("c1c2_receipt_path")?);
    if file_sha256(&ledger_path)? != cert["ledger_sha256"].as_str().unwrap_or_default() {
        return Err("composed ledger bytes do not match ledger_sha256".into());
    }
    if file_sha256(&receipt_path)? != cert["c1c2_receipt_sha256"].as_str().unwrap_or_default() {
        return Err("C1/C2 receipt bytes do not match c1c2_receipt_sha256".into());
    }
    let receipt: Value =
        serde_json::from_slice(&std::fs::read(&receipt_path).map_err(|e| e.to_string())?)
            .map_err(|e| format!("C1/C2 receipt is not JSON: {e}"))?;
    if receipt["verdict"] != "PASS" {
        return Err("C1/C2 receipt verdict is not PASS".into());
    }
    if receipt["inputs"]["candidate_sha256"] != cert["extension_ledger_sha256"] {
        return Err("C1/C2 receipt was not computed on this certificate's extension rows".into());
    }
    issue(conn, certificate_bytes, now_ms)
}

/// Records a certificate and returns its sha256 (over the exact bytes).
pub fn issue(conn: &Connection, certificate_bytes: &[u8], now_ms: i64) -> Result<String, String> {
    let cert: Value = serde_json::from_slice(certificate_bytes)
        .map_err(|e| format!("certificate is not JSON: {e}"))?;
    if cert["schema_version"] != CERTIFICATE_SCHEMA {
        return Err(format!(
            "certificate schema_version must be {CERTIFICATE_SCHEMA}"
        ));
    }
    let mut f = BTreeMap::new();
    for k in BOUND {
        let v = cert[*k]
            .as_str()
            .ok_or_else(|| format!("certificate lacks {k}"))?;
        let ok = if *k == "code_tree_sha" {
            is_hex(v, 40)
        } else {
            is_hex(v, 64)
        };
        if !ok {
            return Err(format!("certificate {k} is not lowercase hex"));
        }
        f.insert(*k, v.to_string());
    }
    let sha = format!("{:x}", Sha256::digest(certificate_bytes));
    conn.execute(
        "INSERT INTO run_certificates(certificate_sha256,ledger_sha256,c1c2_receipt_sha256,parent_manifest_sha256,code_tree_sha,certificate_json,issued_at_ms)
         VALUES(?1,?2,?3,?4,?5,?6,?7)",
        params![sha, f["ledger_sha256"], f["c1c2_receipt_sha256"], f["parent_manifest_sha256"], f["code_tree_sha"],
                String::from_utf8_lossy(certificate_bytes), now_ms],
    )
    .map_err(|e| format!("certificate issuance failed: {e}"))?;
    Ok(sha)
}

pub fn is_trainer_entrypoint(program: &Path) -> bool {
    program
        .file_name()
        .and_then(|n| n.to_str())
        .is_some_and(|n| {
            TRAINER_ENTRYPOINTS
                .iter()
                .any(|e| n.eq_ignore_ascii_case(e))
        })
}

/// Admits a dispatch, or refuses it. Non-trainer programs pass untouched (Ok(None)). A trainer program needs
/// an issued, unconsumed certificate whose ledger sha is among the manifest's binding shas; on admission the
/// certificate is consumed by `job_id` in the same statement, so it can never admit a second job.
pub fn admit(
    conn: &Connection,
    program: &Path,
    env: &BTreeMap<String, String>,
    binding_shas: &[&str],
    job_id: &str,
    now_ms: i64,
) -> Result<Option<String>, String> {
    if !is_trainer_entrypoint(program) {
        return Ok(None);
    }
    let refuse = |why: &str| {
        Err(format!(
            "RUN_CERTIFICATE_REQUIRED: {} refused: {why}",
            program.display()
        ))
    };
    let Some(sha) = env.get(CERTIFICATE_ENV) else {
        return refuse(&format!(
            "manifest env lacks {CERTIFICATE_ENV}; training starts only from ember-lab resume"
        ));
    };
    let row: Option<(String, Option<String>)> = conn
        .query_row(
            "SELECT ledger_sha256, consumed_by_job_id FROM run_certificates WHERE certificate_sha256=?1",
            params![sha],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    let Some((ledger, consumed)) = row else {
        return refuse("certificate was not issued by this ember-lab");
    };
    if let Some(j) = consumed {
        return refuse(&format!("certificate already admitted job {j}"));
    }
    if !binding_shas.iter().any(|b| *b == ledger) {
        return refuse("manifest does not bind the certified data ledger");
    }
    let n = conn
        .execute(
            "UPDATE run_certificates SET consumed_by_job_id=?1, consumed_at_ms=?2 WHERE certificate_sha256=?3 AND consumed_by_job_id IS NULL",
            params![job_id, now_ms, sha],
        )
        .map_err(|e| e.to_string())?;
    if n != 1 {
        return refuse("certificate was consumed concurrently");
    }
    Ok(Some(sha.clone()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn cert(ledger: &str) -> Vec<u8> {
        json!({"schema_version": CERTIFICATE_SCHEMA, "ledger_sha256": ledger, "c1c2_receipt_sha256": "b".repeat(64),
               "parent_manifest_sha256": "c".repeat(64), "code_tree_sha": "d".repeat(40)})
        .to_string()
        .into_bytes()
    }
    #[test]
    fn wall_a() {
        let c = Connection::open_in_memory().unwrap();
        migrate(&c).unwrap();
        let led = "a".repeat(64);
        let trainer = Path::new("x/ember-restart-3b/cia_step_runner.py");
        let mut env = BTreeMap::new();
        // non-trainer programs are untouched
        assert_eq!(
            admit(&c, Path::new("x/score.py"), &env, &[], "j0", 1),
            Ok(None)
        );
        // no certificate
        assert!(admit(&c, trainer, &env, &[&led], "j1", 1)
            .unwrap_err()
            .contains("lacks"));
        // unissued certificate
        env.insert(CERTIFICATE_ENV.into(), "e".repeat(64));
        assert!(admit(&c, trainer, &env, &[&led], "j1", 1)
            .unwrap_err()
            .contains("not issued"));
        // bad certificate refused at issuance
        assert!(issue(&c, b"{}", 1).is_err());
        let sha = issue(&c, &cert(&led), 1).unwrap();
        env.insert(CERTIFICATE_ENV.into(), sha.clone());
        // ledger not bound
        assert!(admit(&c, trainer, &env, &[&"f".repeat(64)], "j1", 1)
            .unwrap_err()
            .contains("ledger"));
        // admitted once
        assert_eq!(
            admit(&c, trainer, &env, &[&led], "j1", 2),
            Ok(Some(sha.clone()))
        );
        // never twice
        assert!(admit(&c, trainer, &env, &[&led], "j2", 3)
            .unwrap_err()
            .contains("already admitted job j1"));
        // case-insensitive entrypoint match (Windows paths)
        assert!(is_trainer_entrypoint(Path::new(
            "C:\\t\\CIA_STEP_RUNNER.PY"
        )));
    }
    #[test]
    fn issuance_rehashes_inputs() {
        let c = Connection::open_in_memory().unwrap();
        migrate(&c).unwrap();
        let d = std::env::temp_dir().join(format!("runcert-{}", std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        let sha = |b: &[u8]| format!("{:x}", Sha256::digest(b));
        let (led, ext) = (b"ledger\n".to_vec(), b"ext\n".to_vec());
        std::fs::write(d.join("l.jsonl"), &led).unwrap();
        let mk = |verdict: &str, cand: &str| {
            let r = json!({"verdict": verdict, "inputs": {"candidate_sha256": cand}}).to_string();
            std::fs::write(d.join("r.json"), &r).unwrap();
            json!({"schema_version": CERTIFICATE_SCHEMA, "ledger_path": d.join("l.jsonl"), "ledger_sha256": sha(&led),
                   "c1c2_receipt_path": d.join("r.json"), "c1c2_receipt_sha256": sha(r.as_bytes()),
                   "extension_ledger_sha256": sha(&ext), "parent_manifest_sha256": "c".repeat(64), "code_tree_sha": "d".repeat(40)})
            .to_string()
        };
        assert!(issue_verified(&c, mk("REFUSE", &sha(&ext)).as_bytes(), 1)
            .unwrap_err()
            .contains("not PASS"));
        assert!(
            issue_verified(&c, mk("PASS", &"0".repeat(64)).as_bytes(), 1)
                .unwrap_err()
                .contains("extension")
        );
        let mut bad: Value = serde_json::from_str(&mk("PASS", &sha(&ext))).unwrap();
        bad["ledger_sha256"] = json!("e".repeat(64));
        assert!(issue_verified(&c, bad.to_string().as_bytes(), 1)
            .unwrap_err()
            .contains("ledger bytes"));
        assert!(issue_verified(&c, mk("PASS", &sha(&ext)).as_bytes(), 1).is_ok());
        std::fs::remove_dir_all(&d).ok();
    }
}
