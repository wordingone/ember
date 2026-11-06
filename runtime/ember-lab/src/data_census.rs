// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! `ember-lab data-census --config <census.json>`: how much unique data Ember has, by modality and status.
//!
//! Reads ledgers, source-manifests and heldout hash arrays only (never raw corpus bytes), so it answers in
//! seconds. Statuses:
//! - `trained`: span objects in the trained stream `[0, trained_end)` of `trained_ledger`, minus exclusions;
//! - `admitted`: objects in an intake dir (`ledger.jsonl` + `source-manifest.jsonl`) with a source edge
//!   (origin + licence) and not yet trained;
//! - `unsourced`: intake objects without a source edge (C1 would refuse them);
//! - `excluded`: objects named in an exclusions file (`objects` array per JSON line), wherever they occur;
//! - `heldout`: sentence-hash arrays (`.npy`, 1-D), counted as hashes and bytes, never trainable.
//!
//! Unique tokens of an object = the length of the union of its span intervals (repeats count once).
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn lines(path: &Path) -> Result<Vec<Value>> {
    let f = fs::File::open(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut out = Vec::new();
    for (i, l) in BufReader::new(f).lines().enumerate() {
        let l = l?;
        if l.trim().is_empty() {
            continue;
        }
        out.push(
            serde_json::from_str(&l).map_err(|e| format!("{}:{}: {e}", path.display(), i + 1))?,
        );
    }
    Ok(out)
}

fn spans(row: &Value) -> Result<Vec<(String, u64, u64)>> {
    let mut v = Vec::new();
    for s in row["spans"].as_array().ok_or("ledger row without spans")? {
        let sha = s["sha256"]
            .as_str()
            .ok_or("span without sha256")?
            .to_string();
        let (a, b) = (
            s["token_start"].as_u64().ok_or("span token_start")?,
            s["token_end"].as_u64().ok_or("span token_end")?,
        );
        if b < a {
            return Err(format!("span {sha} ends before it starts").into());
        }
        v.push((sha, a, b));
    }
    Ok(v)
}

/// object sha -> unique tokens over the stream prefix [0, end) (None = whole ledger). Span offsets are
/// positions in a shared token stream, so an object's unique tokens = the length of the union of its spans
/// (a repeat of the same interval counts once).
fn object_extents(ledger: &Path, end: Option<u64>) -> Result<BTreeMap<String, u64>> {
    let mut iv: BTreeMap<String, Vec<(u64, u64)>> = BTreeMap::new();
    let mut pos = 0u64;
    for row in lines(ledger)? {
        let sp = spans(&row)?;
        let b0 = sp.first().map(|s| s.1).unwrap_or(0);
        for (sha, a, b) in sp {
            let g0 = pos + a - b0;
            if end.is_none_or(|e| g0 < e) {
                let cut = end.map_or(b, |e| b.min(a + (e - g0)));
                iv.entry(sha).or_default().push((a, cut));
            }
        }
        pos += row["n_tokens"]
            .as_u64()
            .ok_or("ledger row without n_tokens")?;
        if end.is_some_and(|e| pos >= e) {
            break;
        }
    }
    Ok(iv
        .into_iter()
        .map(|(k, mut v)| {
            v.sort_unstable();
            let (mut tot, mut cur) = (0u64, None::<(u64, u64)>);
            for (a, b) in v {
                cur = match cur {
                    Some((ca, cb)) if a <= cb => Some((ca, cb.max(b))),
                    Some((ca, cb)) => {
                        tot += cb - ca;
                        Some((a, b))
                    }
                    None => Some((a, b)),
                };
            }
            if let Some((ca, cb)) = cur {
                tot += cb - ca;
            }
            (k, tot)
        })
        .collect())
}

fn npy_len(path: &Path) -> Result<u64> {
    let mut head = [0u8; 256];
    let n = fs::File::open(path)?.read(&mut head)?;
    let h = String::from_utf8_lossy(&head[..n]);
    let i = h
        .find("'shape': (")
        .ok_or_else(|| format!("{}: no npy shape", path.display()))?;
    let rest = &h[i + 10..];
    let num: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
    Ok(num
        .parse()
        .map_err(|_| format!("{}: bad npy shape", path.display()))?)
}

#[derive(Default)]
struct Bucket {
    objects: u64,
    tokens: u64,
    bytes: u64,
    bytes_unknown: u64,
}

pub fn census(config: &Path) -> Result<Value> {
    let cfg: Value = serde_json::from_slice(&fs::read(config)?)?;
    let path = |v: &Value| PathBuf::from(v.as_str().unwrap_or_default());
    let mut excluded = BTreeSet::new();
    for f in cfg["exclusions"].as_array().cloned().unwrap_or_default() {
        for row in lines(&path(&f))? {
            for o in row["objects"].as_array().cloned().unwrap_or_default() {
                excluded.insert(
                    o.as_str()
                        .ok_or("exclusion object not a string")?
                        .to_string(),
                );
            }
        }
    }
    let mut buckets: BTreeMap<(String, String), Bucket> = BTreeMap::new();
    let mut add = |modality: &str, status: &str, tokens: u64, bytes: Option<u64>| {
        let b = buckets
            .entry((modality.to_string(), status.to_string()))
            .or_default();
        b.objects += 1;
        b.tokens += tokens;
        match bytes {
            Some(x) => b.bytes += x,
            None => b.bytes_unknown += 1,
        }
    };
    let trained_end = cfg["trained_end"]
        .as_u64()
        .ok_or("config trained_end missing")?;
    let trained_ledger = path(&cfg["trained_ledger"]);
    let trained = object_extents(&trained_ledger, Some(trained_end))?;
    let modality_of = |m: &Map<String, Value>| {
        m.get("modality")
            .and_then(Value::as_str)
            .unwrap_or("text")
            .to_string()
    };
    let mut manifests: BTreeMap<String, Map<String, Value>> = BTreeMap::new();
    let mut intake_objs: Vec<(String, u64)> = Vec::new();
    for d in cfg["intakes"].as_array().cloned().unwrap_or_default() {
        let d = path(&d);
        for m in lines(&d.join("source-manifest.jsonl"))? {
            if let (Some(sha), Some(obj)) = (m["object_sha256"].as_str(), m.as_object()) {
                manifests.insert(sha.to_string(), obj.clone());
            }
        }
        for (sha, t) in object_extents(&d.join("ledger.jsonl"), None)? {
            intake_objs.push((sha, t));
        }
    }
    let bytes_of = |sha: &str| {
        manifests
            .get(sha)
            .and_then(|m| m.get("bytes"))
            .and_then(Value::as_u64)
    };
    for (sha, t) in &trained {
        let m = manifests
            .get(sha)
            .map(modality_of)
            .unwrap_or_else(|| "text".into());
        add(
            &m,
            if excluded.contains(sha) {
                "excluded"
            } else {
                "trained"
            },
            *t,
            bytes_of(sha),
        );
    }
    let mut seen = BTreeSet::new();
    for (sha, t) in intake_objs {
        if trained.contains_key(&sha) || !seen.insert(sha.clone()) {
            continue;
        }
        let man = manifests.get(&sha);
        let sourced = man.is_some_and(|m| m.get("origin").is_some() && m.get("licence").is_some());
        let status = if excluded.contains(&sha) {
            "excluded"
        } else if sourced {
            "admitted"
        } else {
            "unsourced"
        };
        add(
            &man.map(modality_of).unwrap_or_else(|| "text".into()),
            status,
            t,
            bytes_of(&sha),
        );
    }
    let mut heldout = Vec::new();
    for f in cfg["heldout"].as_array().cloned().unwrap_or_default() {
        let p = path(&f);
        let n = npy_len(&p)?;
        let b = fs::metadata(&p)?.len();
        heldout.push(json!({"path": p.display().to_string(), "sentence_hashes": n, "bytes": b}));
        add("text", "heldout", 0, Some(b));
    }
    let rows: Vec<Value> = buckets
        .iter()
        .map(|((m, s), b)| {
            json!({"modality": m, "status": s, "objects": b.objects, "unique_tokens": b.tokens,
                                   "bytes": b.bytes, "objects_bytes_unknown": b.bytes_unknown})
        })
        .collect();
    let tok = |s: &str| {
        buckets
            .iter()
            .filter(|((_, st), _)| st == s)
            .map(|(_, b)| b.tokens)
            .sum::<u64>()
    };
    Ok(json!({
        "schema": "ember-lab-data-census-v1",
        "trained_ledger": trained_ledger.display().to_string(), "trained_end": trained_end,
        "totals": {"trained_unique_tokens": tok("trained"), "admitted_untrained_tokens": tok("admitted"),
                    "unsourced_tokens": tok("unsourced"), "excluded_tokens": tok("excluded")},
        "rows": rows, "heldout": heldout,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn row(spans: &[(&str, u64, u64)]) -> String {
        let n: u64 = spans.iter().map(|s| s.2 - s.1).sum();
        let sp: Vec<Value> = spans
            .iter()
            .map(|s| json!({"sha256": s.0, "token_start": s.1, "token_end": s.2}))
            .collect();
        json!({"n_tokens": n, "spans": sp}).to_string() + "\n"
    }
    #[test]
    fn statuses_and_repeats() {
        let d = std::env::temp_dir().join(format!("census-test-{}", std::process::id()));
        let i = d.join("intake");
        fs::create_dir_all(&i).unwrap();
        // trained: A twice (repeat counts once), X excluded; stream end cuts the last row in half
        fs::write(
            d.join("tr.jsonl"),
            row(&[("A", 0, 100)]) + &row(&[("A", 0, 100), ("X", 0, 50)]) + &row(&[("B", 0, 100)]),
        )
        .unwrap();
        fs::write(
            d.join("ex.jsonl"),
            json!({"objects": ["X"]}).to_string() + "\n",
        )
        .unwrap();
        fs::write(
            i.join("ledger.jsonl"),
            row(&[("C", 0, 40), ("U", 0, 30), ("A", 0, 10)]) + &row(&[("C", 40, 70), ("C", 0, 20)]),
        )
        .unwrap();
        fs::write(
            i.join("source-manifest.jsonl"),
            json!({"object_sha256": "C", "origin": "o", "licence": ["l"], "bytes": 9}).to_string()
                + "\n",
        )
        .unwrap();
        let mut npy =
            b"\x93NUMPY\x01\x00v\x00{'descr': '<u8', 'fortran_order': False, 'shape': (42,), }"
                .to_vec();
        npy.resize(128, b' ');
        fs::write(d.join("h.npy"), npy).unwrap();
        let cfg = json!({"trained_ledger": d.join("tr.jsonl"), "trained_end": 300, "exclusions": [d.join("ex.jsonl")],
                         "intakes": [i], "heldout": [d.join("h.npy")]});
        fs::write(d.join("c.json"), cfg.to_string()).unwrap();
        let r = census(&d.join("c.json")).unwrap();
        let t = &r["totals"];
        assert_eq!(t["trained_unique_tokens"], 150); // A 100 + B 50 (cut at 300)
        assert_eq!(t["excluded_tokens"], 50);
        assert_eq!(t["admitted_untrained_tokens"], 70);
        assert_eq!(t["unsourced_tokens"], 30);
        assert_eq!(r["heldout"][0]["sentence_hashes"], 42);
        fs::remove_dir_all(&d).ok();
    }
}
