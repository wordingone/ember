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
/// Repo-relative directory that holds the trainer entrypoints.
pub const TRAINER_DIR: &str = "src/ember/infrastructure/tools/ember-restart-3b";
/// Opening docstring lines of the trainer entrypoints: a renamed copy still carries them.
const TRAINER_FINGERPRINTS: &[&str] = &[
    "\"\"\"Daemon-dispatched CIA-3B step measurements; no checkpoint or qualification credit.\"\"\"",
];
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
    if cert.get("kind").is_some() && cert["kind"] != KIND_FRESH {
        if cert["kind"] != KIND_DECLARED_REPEAT {
            return Err("certificate kind is neither fresh nor declared-repeat".into());
        }
        verify_declared_repeat(&cert, &ledger_path, &receipt_path)?;
        return issue(conn, certificate_bytes, now_ms);
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

/// Certificate kinds. A certificate without `kind` is fresh data under a C1/C2 receipt. A declared-repeat
/// certificate is for an hour whose extension rows repeat admitted catalog text that earlier hours trained: its
/// receipt comes from the declared-repeat gate (catalog_declared_repeat_gate.py), and `kind` is part of the
/// certified bytes, so a repeat hour can never be presented as fresh data.
pub const KIND_FRESH: &str = "fresh";
pub const KIND_DECLARED_REPEAT: &str = "declared-repeat";

/// Declared-repeat issuance. The daemon itself (a) re-hashes the ledger, epoch-label sidecar, declaration and
/// receipt; (b) computes the extension sha from the ledger lines at and after `parent_rows`; (c) checks every
/// sidecar row at and after `parent_rows` is `repeat_declared` with `ledger_pass_index >= 1`. It then requires
/// the receipt to be a declared-repeat PASS over exactly those rows, bound to the same extension, declaration
/// and sidecar, with zero unadmitted rows. Claim boundary: span-to-catalog membership is mapped python-side
/// (map_ledger_spans over the catalog export named by sha in the receipt); the daemon trusts that mapping only
/// through the receipt bytes it re-hashed.
fn verify_declared_repeat(
    cert: &Value,
    ledger_path: &str,
    receipt_path: &str,
) -> Result<(), String> {
    let s = |v: &Value, k: &str| {
        v[k].as_str()
            .map(str::to_string)
            .ok_or_else(|| format!("declared-repeat certificate lacks {k}"))
    };
    let (side_path, decl_path) = (s(cert, "sidecar_path")?, s(cert, "declaration_path")?);
    if file_sha256(&side_path)? != s(cert, "sidecar_sha256")? {
        return Err("epoch-label sidecar bytes do not match sidecar_sha256".into());
    }
    if file_sha256(&decl_path)? != s(cert, "declaration_sha256")? {
        return Err("declaration bytes do not match declaration_sha256".into());
    }
    let parent_rows = cert["parent_rows"]
        .as_u64()
        .ok_or("declared-repeat certificate lacks parent_rows")? as usize;
    let ledger = std::fs::read(ledger_path).map_err(|e| e.to_string())?;
    let lines: Vec<&[u8]> = ledger
        .split(|b| *b == b'\n')
        .filter(|l| !l.is_empty())
        .collect();
    if parent_rows >= lines.len() {
        return Err("declared-repeat certificate has no extension rows".into());
    }
    let mut h = Sha256::new();
    for l in &lines[parent_rows..] {
        h.update(l);
        h.update(b"\n");
    }
    let extension = format!("{:x}", h.finalize());
    if cert["extension_ledger_sha256"].as_str() != Some(extension.as_str()) {
        return Err("extension_ledger_sha256 is not the ledger rows after parent_rows".into());
    }
    let side: Value =
        serde_json::from_slice(&std::fs::read(&side_path).map_err(|e| e.to_string())?)
            .map_err(|e| format!("sidecar is not JSON: {e}"))?;
    let rows = side["rows"].as_array().ok_or("sidecar lacks rows")?;
    if rows.len() != lines.len() {
        return Err("sidecar row count is not the ledger row count".into());
    }
    for (i, r) in rows.iter().enumerate().skip(parent_rows) {
        if r["repeat_declared"] != true || r["ledger_pass_index"].as_u64().unwrap_or(0) < 1 {
            return Err(format!(
                "extension row {i} is not a declared repeat (repeat_declared and ledger_pass_index >= 1)"
            ));
        }
    }
    let receipt: Value =
        serde_json::from_slice(&std::fs::read(receipt_path).map_err(|e| e.to_string())?)
            .map_err(|e| format!("declared-repeat receipt is not JSON: {e}"))?;
    if receipt["kind"] != KIND_DECLARED_REPEAT || receipt["verdict"] != "PASS" {
        return Err("receipt is not a declared-repeat PASS".into());
    }
    let n = (lines.len() - parent_rows) as u64;
    let checks = [
        (
            receipt["extension_ledger_sha256"].as_str() == Some(extension.as_str()),
            "extension rows",
        ),
        (
            receipt["declaration_sha256"] == cert["declaration_sha256"],
            "declaration",
        ),
        (
            receipt["sidecar_sha256"] == cert["sidecar_sha256"],
            "sidecar",
        ),
        (receipt["rows_checked"].as_u64() == Some(n), "row count"),
        (
            receipt["unadmitted_rows"].as_u64() == Some(0),
            "zero unadmitted rows",
        ),
        (
            receipt["c1_basis"] == "catalog-admitted",
            "c1_basis catalog-admitted",
        ),
    ];
    if let Some((_, what)) = checks.iter().find(|(ok, _)| !ok) {
        return Err(format!("declared-repeat receipt does not bind {what}"));
    }
    Ok(())
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

fn git(dir: &Path, args: &[&str]) -> Result<String, String> {
    let out = std::process::Command::new("git")
        .arg("-C")
        .arg(dir)
        .args(args)
        .output()
        .map_err(|e| format!("git: {e}"))?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).trim().to_string());
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

/// True when a program imports a trainer module or carries a trainer's opening docstring.
pub fn reaches_trainer(text: &str) -> bool {
    let modules: Vec<&str> = TRAINER_ENTRYPOINTS
        .iter()
        .map(|e| e.trim_end_matches(".py"))
        .collect();
    text.lines().any(|line| {
        let t = line.trim();
        TRAINER_FINGERPRINTS.contains(&t)
            || modules.iter().any(|m| {
                t.starts_with(&format!("import {m}"))
                    || t.starts_with(&format!("from {m} "))
                    || t.contains(&format!("import_module(\"{m}\""))
                    || t.contains(&format!("import_module('{m}'"))
                    || t.contains(&format!("\"{m}.py\""))
            })
    })
}

/// A program needs a certificate when its name is a trainer entrypoint or its bytes reach the trainer.
pub fn needs_certificate(program: &Path) -> bool {
    is_trainer_entrypoint(program)
        || std::fs::read(program).is_ok_and(|b| reaches_trainer(&String::from_utf8_lossy(&b)))
}

/// A certified program must be a trainer entrypoint at its own path inside a git checkout whose HEAD is the
/// certified tree and whose working tree is clean (untracked files included).
fn check_code_tree(program: &Path, code_tree_sha: &str) -> Result<(), String> {
    let canon =
        std::fs::canonicalize(program).map_err(|e| format!("{}: {e}", program.display()))?;
    let refuse_copy = || {
        format!(
            "{} is not a trainer entrypoint under {TRAINER_DIR}; copies are refused",
            canon.display()
        )
    };
    if !is_trainer_entrypoint(&canon) {
        return Err(refuse_copy());
    }
    let dir = canon.parent().ok_or("program has no parent directory")?;
    let top = std::fs::canonicalize(
        git(dir, &["rev-parse", "--show-toplevel"]).map_err(|_| refuse_copy())?,
    )
    .map_err(|e| format!("repo root: {e}"))?;
    let name = canon
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or_default();
    let expected = std::fs::canonicalize(top.join(TRAINER_DIR).join(name)).ok();
    if !is_trainer_entrypoint(&canon) || expected.as_deref() != Some(canon.as_path()) {
        return Err(format!(
            "{} is not a trainer entrypoint under {TRAINER_DIR}; copies are refused",
            canon.display()
        ));
    }
    let head = git(&top, &["rev-parse", "HEAD"])?;
    if head != code_tree_sha {
        return Err(format!(
            "checkout HEAD {head} is not the certified code tree {code_tree_sha}"
        ));
    }
    if !git(&top, &["status", "--porcelain", "--untracked-files=all"])?.is_empty() {
        return Err("checkout has uncommitted or untracked changes".into());
    }
    Ok(())
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
    if !needs_certificate(program) {
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
    let row: Option<(String, String, String, Option<String>)> = conn
        .query_row(
            "SELECT ledger_sha256, parent_manifest_sha256, code_tree_sha, consumed_by_job_id FROM run_certificates WHERE certificate_sha256=?1",
            params![sha],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    let Some((ledger, parent, code_tree, consumed)) = row else {
        return refuse("certificate was not issued by this ember-lab");
    };
    if let Some(j) = consumed {
        return refuse(&format!("certificate already admitted job {j}"));
    }
    if !binding_shas.iter().any(|b| *b == ledger) {
        return refuse("manifest does not bind the certified data ledger");
    }
    if !binding_shas.iter().any(|b| *b == parent) {
        return refuse("manifest does not bind the certified parent manifest");
    }
    if let Err(why) = check_code_tree(program, &code_tree) {
        return refuse(&why);
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
    fn cert(ledger: &str, parent: &str, tree: &str) -> Vec<u8> {
        json!({"schema_version": CERTIFICATE_SCHEMA, "ledger_sha256": ledger, "c1c2_receipt_sha256": "b".repeat(64),
               "parent_manifest_sha256": parent, "code_tree_sha": tree})
        .to_string()
        .into_bytes()
    }
    fn sh(dir: &Path, args: &[&str]) {
        assert!(std::process::Command::new("git")
            .arg("-C")
            .arg(dir)
            .args(args)
            .status()
            .unwrap()
            .success());
    }
    #[test]
    fn wall_a() {
        let c = Connection::open_in_memory().unwrap();
        migrate(&c).unwrap();
        let root = std::env::temp_dir().join(format!("walla-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let repo = root.join("repo");
        std::fs::create_dir_all(repo.join(TRAINER_DIR)).unwrap();
        let trainer = repo.join(TRAINER_DIR).join("cia_step_runner.py");
        let body = format!(
            "{}
print('train')
",
            TRAINER_FINGERPRINTS[0]
        );
        std::fs::write(&trainer, &body).unwrap();
        sh(&repo, &["init", "-q"]);
        sh(
            &repo,
            &["-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"],
        );
        sh(
            &repo,
            &[
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-qm",
                "t",
            ],
        );
        let head = git(&repo, &["rev-parse", "HEAD"]).unwrap();
        let (led, par) = ("a".repeat(64), "c".repeat(64));
        let b = [led.as_str(), par.as_str()];
        let mut env = BTreeMap::new();
        // non-trainer programs are untouched
        std::fs::write(
            root.join("score.py"),
            "print(1)
",
        )
        .unwrap();
        assert_eq!(
            admit(&c, &root.join("score.py"), &env, &[], "j0", 1),
            Ok(None)
        );
        // a renamed copy, and an importer, both need a certificate
        let copy = root.join("renamed.py");
        std::fs::write(&copy, &body).unwrap();
        let importer = root.join("wrap.py");
        std::fs::write(
            &importer,
            "import cia_step_runner
",
        )
        .unwrap();
        for p in [&trainer, &copy, &importer] {
            assert!(admit(&c, p, &env, &b, "j1", 1)
                .unwrap_err()
                .contains("lacks"));
        }
        env.insert(CERTIFICATE_ENV.into(), "e".repeat(64));
        assert!(admit(&c, &trainer, &env, &b, "j1", 1)
            .unwrap_err()
            .contains("not issued"));
        assert!(issue(&c, b"{}", 1).is_err());
        let sha = issue(&c, &cert(&led, &par, &head), 1).unwrap();
        env.insert(CERTIFICATE_ENV.into(), sha.clone());
        // ledger or parent not bound
        assert!(admit(&c, &trainer, &env, &[&par], "j1", 1)
            .unwrap_err()
            .contains("data ledger"));
        assert!(admit(&c, &trainer, &env, &[&led], "j1", 1)
            .unwrap_err()
            .contains("parent manifest"));
        // a copy outside the trainer path is refused even with a valid certificate
        assert!(admit(&c, &copy, &env, &b, "j1", 1)
            .unwrap_err()
            .contains("copies are refused"));
        // an edited trainer (dirty tree) and an untracked file are refused
        std::fs::write(
            &trainer,
            format!(
                "{body}#x
"
            ),
        )
        .unwrap();
        assert!(admit(&c, &trainer, &env, &b, "j1", 1)
            .unwrap_err()
            .contains("uncommitted"));
        std::fs::write(&trainer, &body).unwrap();
        std::fs::write(repo.join(TRAINER_DIR).join("extra.py"), "").unwrap();
        assert!(admit(&c, &trainer, &env, &b, "j1", 1)
            .unwrap_err()
            .contains("untracked"));
        std::fs::remove_file(repo.join(TRAINER_DIR).join("extra.py")).unwrap();
        // a certificate for another tree is refused
        let other = issue(&c, &cert(&led, &par, &"d".repeat(40)), 1).unwrap();
        env.insert(CERTIFICATE_ENV.into(), other);
        assert!(admit(&c, &trainer, &env, &b, "j1", 1)
            .unwrap_err()
            .contains("not the certified code tree"));
        // admitted once, never twice
        env.insert(CERTIFICATE_ENV.into(), sha.clone());
        assert_eq!(
            admit(&c, &trainer, &env, &b, "j1", 2),
            Ok(Some(sha.clone()))
        );
        assert!(admit(&c, &trainer, &env, &b, "j2", 3)
            .unwrap_err()
            .contains("already admitted job j1"));
        #[cfg(windows)]
        assert!(is_trainer_entrypoint(Path::new(r"C:\t\CIA_STEP_RUNNER.PY")));
        let _ = std::fs::remove_dir_all(&root);
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
    #[test]
    fn declared_repeat_issuance() {
        let c = Connection::open_in_memory().unwrap();
        migrate(&c).unwrap();
        let d = std::env::temp_dir().join(format!("runcert-dr-{}", std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        let sha = |b: &[u8]| format!("{:x}", Sha256::digest(b));
        let led = b"{\"r\":0}\n{\"r\":1}\n{\"r\":2}\n".to_vec();
        let ext = sha(b"{\"r\":2}\n");
        std::fs::write(d.join("l.jsonl"), &led).unwrap();
        std::fs::write(d.join("decl.md"), b"declaration\n").unwrap();
        let decl = sha(b"declaration\n");
        // (sidecar row 2 repeat flag, row 2 pass index, receipt unadmitted rows, receipt kind)
        let mk = |rep: bool, pass: u64, unadmitted: u64, rkind: &str| {
            let side = json!({"rows": [{"repeat_declared": false, "ledger_pass_index": 0},
                                       {"repeat_declared": true, "ledger_pass_index": 1},
                                       {"repeat_declared": rep, "ledger_pass_index": pass}]})
            .to_string();
            std::fs::write(d.join("s.json"), &side).unwrap();
            let r = json!({"kind": rkind, "verdict": "PASS", "extension_ledger_sha256": ext,
                           "declaration_sha256": decl, "sidecar_sha256": sha(side.as_bytes()),
                           "rows_checked": 1, "unadmitted_rows": unadmitted, "c1_basis": "catalog-admitted"})
            .to_string();
            std::fs::write(d.join("r.json"), &r).unwrap();
            json!({"schema_version": CERTIFICATE_SCHEMA, "kind": KIND_DECLARED_REPEAT, "parent_rows": 2,
                   "ledger_path": d.join("l.jsonl"), "ledger_sha256": sha(&led), "extension_ledger_sha256": ext,
                   "c1c2_receipt_path": d.join("r.json"), "c1c2_receipt_sha256": sha(r.as_bytes()),
                   "sidecar_path": d.join("s.json"), "sidecar_sha256": sha(side.as_bytes()),
                   "declaration_path": d.join("decl.md"), "declaration_sha256": decl,
                   "parent_manifest_sha256": "c".repeat(64), "code_tree_sha": "d".repeat(40)})
            .to_string()
        };
        let err = |b: String| issue_verified(&c, b.as_bytes(), 1).unwrap_err();
        // red: a fresh row inside a declared-repeat certificate
        assert!(err(mk(false, 0, 0, KIND_DECLARED_REPEAT))
            .contains("extension row 2 is not a declared repeat"));
        assert!(err(mk(true, 0, 0, KIND_DECLARED_REPEAT)).contains("extension row 2"));
        // red: an unadmitted row reported by the gate
        assert!(err(mk(true, 1, 1, KIND_DECLARED_REPEAT)).contains("zero unadmitted rows"));
        // red: a fresh-data receipt cannot back a declared-repeat certificate
        assert!(err(mk(true, 1, 0, "c1c2")).contains("declared-repeat PASS"));
        // red: an extension sha that is not the rows after parent_rows
        let mut bad: Value = serde_json::from_str(&mk(true, 1, 0, KIND_DECLARED_REPEAT)).unwrap();
        bad["extension_ledger_sha256"] = json!("0".repeat(64));
        assert!(err(bad.to_string()).contains("rows after parent_rows"));
        // red: an unknown kind
        let mut bad: Value = serde_json::from_str(&mk(true, 1, 0, KIND_DECLARED_REPEAT)).unwrap();
        bad["kind"] = json!("other");
        assert!(err(bad.to_string()).contains("neither fresh nor declared-repeat"));
        // pass, and the stored certificate carries the kind
        let ok = mk(true, 1, 0, KIND_DECLARED_REPEAT);
        let s = issue_verified(&c, ok.as_bytes(), 1).unwrap();
        let stored: String = c
            .query_row(
                "SELECT certificate_json FROM run_certificates WHERE certificate_sha256=?1",
                [&s],
                |r| r.get(0),
            )
            .unwrap();
        assert!(stored.contains("\"kind\":\"declared-repeat\""));
        std::fs::remove_dir_all(&d).ok();
    }
}
