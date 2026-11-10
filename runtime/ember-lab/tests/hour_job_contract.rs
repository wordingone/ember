// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

//! The shared golden fixture of the hour start contract. ember-cli's `/resume-hour`
//! (`commands/resume-hour.test.ts`) reads the same file; both implementations must satisfy every case.

use ember_lab::hour_job::{
    bash_refusal, dispatch_name_ok, hour_env, is_ember_key, sha_well_formed, REDIRECT,
};
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

fn contract() -> Value {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("src/ember/infrastructure/tools/ember-cli/src/commands/resume-hour-contract.json");
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|error| panic!("contract fixture {}: {error}", path.display()));
    let value: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(value["schema"], "resume-hour-contract-v1");
    value
}

#[test]
fn redirect_is_the_cockpit_redirect_byte_for_byte() {
    assert_eq!(REDIRECT, contract()["redirect"].as_str().unwrap());
}

#[test]
fn dispatch_names_match_every_golden_case() {
    let contract = contract();
    let cases = contract["name_cases"].as_array().unwrap();
    assert!(cases.len() >= 10);
    for case in cases {
        let name = case["name"].as_str().unwrap();
        assert_eq!(
            dispatch_name_ok(name),
            case["ok"].as_bool().unwrap(),
            "name case {name:?}"
        );
    }
}

#[test]
fn sha_shapes_match_every_golden_case() {
    let contract = contract();
    for case in contract["sha_cases"].as_array().unwrap() {
        let sha = case["sha"].as_str().unwrap();
        assert_eq!(
            sha_well_formed(sha),
            case["well_formed"].as_bool().unwrap(),
            "sha case {sha:?}"
        );
    }
}

#[test]
fn ember_keys_match_every_golden_case() {
    let contract = contract();
    for case in contract["ember_key_cases"].as_array().unwrap() {
        let key = case["key"].as_str().unwrap();
        assert_eq!(
            is_ember_key(key),
            case["ember"].as_bool().unwrap(),
            "key case {key:?}"
        );
    }
}

#[test]
fn hour_env_matches_every_golden_case() {
    let contract = contract();
    for case in contract["env_cases"].as_array().unwrap() {
        let input: BTreeMap<String, String> = case["in"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
            .collect();
        let expected: BTreeMap<String, String> = case["out"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
            .collect();
        assert_eq!(hour_env(input), expected);
    }
}

#[test]
fn the_system32_shim_is_refused_in_every_golden_spelling() {
    let contract = contract();
    for shim in contract["bash_shim_cases"].as_array().unwrap() {
        let shim = shim.as_str().unwrap();
        assert!(bash_refusal(Path::new(shim)).is_some(), "{shim}");
    }
}
