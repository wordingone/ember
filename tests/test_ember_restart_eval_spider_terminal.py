# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import importlib.util
import hashlib
import sqlite3
import json
import os
from types import SimpleNamespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ember_restart_eval_spider.py"


def load_module():
    spec = importlib.util.spec_from_file_location("spider_terminal_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_manifest() -> dict:
    digest = "0" * 64
    return {
        "exact_match_source_commit": "b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c",
        "exact_match_evaluation_py_sha256": digest,
        "exact_match_process_sql_py_sha256": digest,
        "execution_match_source_commit": "e97acc546ecbee8fa27fa8dbf025ef61493a876c",
        "execution_match_evaluation_py_sha256": digest,
        "execution_match_exec_eval_py_sha256": digest,
        "execution_match_exec_subprocess_py_sha256": digest,
        "execution_match_process_sql_py_sha256": digest,
        "examples_raw_sha256": digest,
        "gold_raw_sha256": digest,
        "tables_raw_sha256": digest,
        "database_tree_manifest_sha256": digest,
        "ordered_row_set_sha256": digest,
        "prediction_envelope_raw_sha256": digest,
        "inference_receipt_raw_sha256": digest,
        "model_sha256": digest,
        "checkpoint_sha256": digest,
        "tokenizer_sha256": digest,
        "config_sha256": digest,
        "ember_source_commit": "e440cf96b4340038ca276386224bd144254a3265",
        "per_row_timeout_seconds": 30,
        "nltk_version": "3.9.3",
        "punkt_tab_tree_manifest_sha256": digest,
        "sqlparse_version": "0.4.2",
        "sqlparse_tree_manifest_sha256": digest,
        "admission_receipt_raw_sha256": digest,
        "catalog_fragment_raw_sha256": digest,
        "license_sidecar_raw_sha256": digest,
    }


def write_manifest(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    return path


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_closed_manifest_accepts_the_exact_frozen_schema(tmp_path: Path) -> None:
    module = load_module()
    document = valid_manifest()
    assert module.load_manifest(write_manifest(tmp_path, document)) == document


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row.pop("per_row_timeout_seconds"), "missing keys"),
        (lambda row: row.update(smuggled=True), "unknown keys"),
        (lambda row: row.update(per_row_timeout_seconds=True), "timeout"),
        (lambda row: row.update(per_row_timeout_seconds=0), "timeout"),
        (lambda row: row.update(per_row_timeout_seconds=3601), "timeout"),
    ],
)
def test_closed_manifest_refuses_schema_and_timeout_drift(
    tmp_path: Path, mutation, message: str
) -> None:
    module = load_module()
    document = valid_manifest()
    mutation(document)
    with pytest.raises(ValueError, match=message):
        module.load_manifest(write_manifest(tmp_path, document))


def test_closed_manifest_refuses_non_hex_identity(tmp_path: Path) -> None:
    module = load_module()
    document = valid_manifest()
    document["checkpoint_sha256"] = "not-a-digest"
    with pytest.raises(ValueError, match="checkpoint_sha256"):
        module.load_manifest(write_manifest(tmp_path, document))


def admission_fixture(module):
    license_sidecar = module.self_hashed(
        {
            "schema_version": "ember-spider-license-sidecar-v1",
            "benchmark_id": "spider",
            "license_spdx": "Apache-2.0",
            "license_text_raw_sha256": "a" * 64,
            "upstream_url": "https://github.com/taoyds/spider.git",
        }
    )
    protected_eval_id = "evaluation:spider:" + "b" * 64
    fragment = {
        "schema_version": "ember-data-catalog-manifest-v1",
        "records": [
            {
                "id": protected_eval_id,
                "kind": "protected_eval",
                "exclusion_reason": None,
                "overlap_state": "isolated",
                "near_dup_ruling": "not_run",
                "ngram_ruling": "not_run",
                "frozen_at_ms": 1,
                "frozen_manifest_sha256": "c" * 64,
                "test_set_sha256": "c" * 64,
            },
            {
                "id": "attempt:spider:" + "d" * 64,
                "kind": "consumer_attempt",
                "state": "admitted",
                "run_attempt_id": "attempt:spider:" + "d" * 64,
                "source_tree_sha": "e" * 40,
                "model_sha256": "f" * 64,
                "checkpoint_sha256": "1" * 64,
                "tokenizer_sha256": "2" * 64,
                "config_sha256": "3" * 64,
                "evaluator_sha256": "4" * 64,
            },
        ],
        "edges": [
            {
                "from_id": "attempt:spider:" + "d" * 64,
                "from_kind": "consumer_attempt",
                "kind": "consumer_evaluation",
                "ordinal": 0,
                "payload": {},
                "to_id": protected_eval_id,
                "to_kind": "protected_eval",
            },
            {
                "from_id": protected_eval_id,
                "from_kind": "protected_eval",
                "kind": "evaluation_object",
                "ordinal": 0,
                "payload": {},
                "to_id": "sha256:" + "c" * 64,
                "to_kind": "immutable_object",
            },
        ],
    }
    fragment_raw = canonical(fragment)
    license_raw = canonical(license_sidecar)
    receipt = module.self_hashed(
        {
            "schema_version": "ember-spider-1581-admission-receipt-v1",
            "result": "ADMITTED_FOR_PROTECTED_EVALUATION",
            "benchmark_id": "spider",
            "protected_eval_id": protected_eval_id,
            "catalog_fragment_raw_sha256": hashlib.sha256(fragment_raw).hexdigest(),
            "license_sidecar_raw_sha256": hashlib.sha256(license_raw).hexdigest(),
            "ordered_row_set_sha256": "5" * 64,
            "examples_raw_sha256": "6" * 64,
            "gold_raw_sha256": "7" * 64,
            "tables_raw_sha256": "8" * 64,
            "database_tree_manifest_sha256": "9" * 64,
        }
    )
    return receipt, fragment, license_sidecar


def test_1581_admission_binding_accepts_one_closed_synthetic_fixture() -> None:
    module = load_module()
    receipt, fragment, license_sidecar = admission_fixture(module)
    manifest = valid_manifest()
    for key in (
        "ordered_row_set_sha256",
        "examples_raw_sha256",
        "gold_raw_sha256",
        "tables_raw_sha256",
        "database_tree_manifest_sha256",
    ):
        manifest[key] = receipt[key]
    receipt_raw = canonical(receipt)
    fragment_raw = canonical(fragment)
    license_raw = canonical(license_sidecar)
    manifest["admission_receipt_raw_sha256"] = hashlib.sha256(receipt_raw).hexdigest()
    manifest["catalog_fragment_raw_sha256"] = hashlib.sha256(fragment_raw).hexdigest()
    manifest["license_sidecar_raw_sha256"] = hashlib.sha256(license_raw).hexdigest()
    assert module.validate_1581_admission_binding(
        receipt_raw, fragment_raw, license_raw, manifest
    ) is True


@pytest.mark.parametrize("mutation", ["missing", "malformed", "identity_mismatch"])
def test_1581_admission_binding_refuses_absent_malformed_or_substituted_bytes(
    mutation: str,
) -> None:
    module = load_module()
    receipt, fragment, license_sidecar = admission_fixture(module)
    manifest = valid_manifest()
    for key in (
        "ordered_row_set_sha256",
        "examples_raw_sha256",
        "gold_raw_sha256",
        "tables_raw_sha256",
        "database_tree_manifest_sha256",
    ):
        manifest[key] = receipt[key]
    good_receipt_raw = canonical(receipt)
    fragment_raw = canonical(fragment)
    license_raw = canonical(license_sidecar)
    manifest["admission_receipt_raw_sha256"] = hashlib.sha256(good_receipt_raw).hexdigest()
    manifest["catalog_fragment_raw_sha256"] = hashlib.sha256(fragment_raw).hexdigest()
    manifest["license_sidecar_raw_sha256"] = hashlib.sha256(license_raw).hexdigest()
    if mutation == "missing":
        receipt_raw = b""
    elif mutation == "malformed":
        receipt_raw = b"{"
    else:
        receipt["catalog_fragment_raw_sha256"] = "0" * 64
        receipt_raw = canonical(receipt)
    assert module.validate_1581_admission_binding(
        receipt_raw, fragment_raw, license_raw, manifest
    ) is False


def test_row_contract_binds_identity_order_and_inference_lineage() -> None:
    module = load_module()
    gold = [("select 1", "db"), ("select 2", "db")]
    examples = [
        {"db_id": "db", "question": "one", "query": "select 1"},
        {"db_id": "db", "question": "two", "query": "select 2"},
    ]
    rows = module.build_frozen_rows(examples, gold)
    inference_hash = "1" * 64
    envelope = {
        "schema_version": "ember-spider-prediction-envelope-v1",
        "inference_receipt_raw_sha256": inference_hash,
        "rows": [
            {"row_id": row["row_id"], "sql": f"select {index + 1}"}
            for index, row in enumerate(rows)
        ],
    }
    expected = hashlib.sha256(canonical([row["row_id"] for row in rows])).hexdigest()
    assert module.validate_prediction_envelope(envelope, rows, inference_hash) == [
        "select 1",
        "select 2",
    ]
    assert module.ordered_row_set_sha256(rows) == expected


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "reordered", "empty"])
def test_prediction_row_set_drift_refuses(mutation: str) -> None:
    module = load_module()
    rows = module.build_frozen_rows(
        [
            {"db_id": "db", "question": "one", "query": "select 1"},
            {"db_id": "db", "question": "two", "query": "select 2"},
        ],
        [("select 1", "db"), ("select 2", "db")],
    )
    items = [
        {"row_id": rows[0]["row_id"], "sql": "select 1"},
        {"row_id": rows[1]["row_id"], "sql": "select 2"},
    ]
    if mutation == "missing":
        items.pop()
    elif mutation == "duplicate":
        items[1] = dict(items[0])
    elif mutation == "extra":
        items.append({"row_id": "f" * 64, "sql": "select 3"})
    elif mutation == "reordered":
        items.reverse()
    else:
        items[0]["sql"] = ""
    envelope = {
        "schema_version": "ember-spider-prediction-envelope-v1",
        "inference_receipt_raw_sha256": "1" * 64,
        "rows": items,
    }
    with pytest.raises(ValueError, match="prediction"):
        module.validate_prediction_envelope(envelope, rows, "1" * 64)


def test_example_gold_identity_mismatch_refuses() -> None:
    module = load_module()
    with pytest.raises(ValueError, match="gold"):
        module.build_frozen_rows(
            [{"db_id": "other", "question": "one", "query": "select 1"}],
            [("select 1", "db")],
        )


def test_bound_file_and_database_tree_verify_exact_bytes(tmp_path: Path) -> None:
    module = load_module()
    payload = tmp_path / "payload.json"
    payload.write_bytes(b"{}\n")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    module.verify_bound_file(payload, digest, "payload")
    database_root = tmp_path / "database"
    database = database_root / "db" / "db.sqlite"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"sqlite-fixture")
    tree = {
        "schema_version": "ember-spider-database-tree-manifest-v1",
        "files": [
            {
                "path": "db/db.sqlite",
                "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            }
        ],
    }
    tree_path = tmp_path / "tree.json"
    tree_path.write_bytes(canonical(tree))
    tree_hash = hashlib.sha256(tree_path.read_bytes()).hexdigest()
    assert module.verify_database_tree(tree_path, database_root, tree_hash) == {
        "db": database
    }


def test_database_tree_drift_and_path_escape_refuse(tmp_path: Path) -> None:
    module = load_module()
    database_root = tmp_path / "database"
    database_root.mkdir()
    tree_path = tmp_path / "tree.json"
    for relative in ("../escape.sqlite", "db\\db.sqlite", "/abs.sqlite"):
        tree = {
            "schema_version": "ember-spider-database-tree-manifest-v1",
            "files": [{"path": relative, "sha256": "0" * 64}],
        }
        tree_path.write_bytes(canonical(tree))
        with pytest.raises(ValueError, match="database tree"):
            module.verify_database_tree(
                tree_path,
                database_root,
                hashlib.sha256(tree_path.read_bytes()).hexdigest(),
            )


def test_database_tree_refuses_unmanifested_files(tmp_path: Path) -> None:
    module = load_module()
    database_root = tmp_path / "database"
    database = database_root / "db" / "db.sqlite"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"sqlite-fixture")
    tree_path = tmp_path / "tree.json"
    tree_path.write_bytes(
        canonical(
            {
                "schema_version": "ember-spider-database-tree-manifest-v1",
                "files": [
                    {
                        "path": "db/db.sqlite",
                        "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
                    }
                ],
            }
        )
    )
    (database_root / "unmanifested.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="missing or extra"):
        module.verify_database_tree(
            tree_path,
            database_root,
            hashlib.sha256(tree_path.read_bytes()).hexdigest(),
        )


def test_bound_file_drift_refuses(tmp_path: Path) -> None:
    module = load_module()
    payload = tmp_path / "payload.json"
    payload.write_bytes(b"changed")
    with pytest.raises(ValueError, match="payload"):
        module.verify_bound_file(payload, "0" * 64, "payload")


@pytest.mark.parametrize("status", [" M evaluation.py", "?? random.py"])
def test_scorer_root_cleanliness_refuses_dirty_or_shadowing_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    module = load_module()
    monkeypatch.setattr(module, "verify_git_commit", lambda *unused: None)
    monkeypatch.setattr(module, "git_status_rows", lambda unused: [status])
    with pytest.raises(ValueError, match="not clean"):
        module.verify_clean_git_root(tmp_path, "0" * 40, "scorer")


def test_scorer_root_cleanliness_allows_only_untracked_bytecode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    monkeypatch.setattr(module, "verify_git_commit", lambda *unused: None)
    monkeypatch.setattr(
        module,
        "git_status_rows",
        lambda unused: ["?? __pycache__/evaluation.cpython-310.pyc"],
    )
    module.verify_clean_git_root(tmp_path, "0" * 40, "scorer")


def test_ember_import_byte_verifier_refuses_modified_bound_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    source = tmp_path / "scripts" / "bound.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"modified")
    monkeypatch.setattr(module, "verify_git_commit", lambda *unused: None)
    monkeypatch.setattr(module, "_owned_process_runner", lambda: object())
    monkeypatch.setattr(module, "ember_import_files", lambda unused: {source})
    monkeypatch.setattr(module, "git_file_bytes", lambda *unused: b"committed")
    with pytest.raises(ValueError, match="modified"):
        module.verify_ember_import_bytes(tmp_path, "0" * 40)


def test_derived_ember_import_set_is_the_actual_two_file_runtime() -> None:
    module = load_module()
    command = module._headless_python_command(
        "-B", str(SCRIPT), "--owned-import-set"
    )
    completed = module._owned_process_runner().run(command, timeout_s=30)
    assert completed.returncode == 0, completed.stderr
    assert set(json.loads(completed.stdout)) == {
        "scripts/ember_restart_eval_spider.py",
        "scripts/owned_process.py",
    }


def write_punkt_tab_tree(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "nltk_data"
    english = root / "tokenizers" / "punkt_tab" / "english"
    english.mkdir(parents=True)
    payload = english / "abbrev_types.txt"
    payload.write_bytes(b"dr\n")
    document = {
        "schema_version": "ember-punkt-tab-tree-manifest-v1",
        "tree_root": "tokenizers/punkt_tab/english",
        "files": [
            {
                "path": payload.name,
                "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                "size": payload.stat().st_size,
            }
        ],
    }
    manifest = root / "punkt-tab-tree-manifest.json"
    manifest.write_bytes(canonical(document))
    return root, hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_punkt_tab_tree_binds_runtime_version_and_closed_file_set(
    tmp_path: Path,
) -> None:
    module = load_module()
    root, manifest_hash = write_punkt_tab_tree(tmp_path)
    assert module.verify_punkt_tab_tree(root, manifest_hash, "3.9.3") == (
        root / "tokenizers" / "punkt_tab" / "english"
    )


def test_punkt_tab_tree_refuses_absence_version_and_byte_drift(tmp_path: Path) -> None:
    module = load_module()
    with pytest.raises(ValueError, match="root"):
        module.verify_punkt_tab_tree(tmp_path / "absent", "0" * 64, "3.9.3")
    root, manifest_hash = write_punkt_tab_tree(tmp_path)
    with pytest.raises(ValueError, match="nltk version"):
        module.verify_punkt_tab_tree(root, manifest_hash, "0.0.0")
    (root / "tokenizers" / "punkt_tab" / "english" / "extra.tab").write_bytes(
        b"extra"
    )
    with pytest.raises(ValueError, match="missing or extra"):
        module.verify_punkt_tab_tree(root, manifest_hash, "3.9.3")


def test_sqlparse_tree_verifies_exact_custody_and_version() -> None:
    module = load_module()
    custody = os.environ.get("EMBER_SQLPARSE_ROOT")
    if not custody:
        pytest.skip("EMBER_SQLPARSE_ROOT is not configured")
    root = Path(custody)
    if not root.is_dir():
        pytest.skip("receipted sqlparse custody is unavailable")
    assert module.verify_sqlparse_tree(
        root,
        "05f3a5f46a54c0629af07bad317baa94b4a01b60d40474344a4e91a8386c0d98",
        "0.4.2",
    ) == root / "pyroot"
    with pytest.raises(ValueError, match="version"):
        module.verify_sqlparse_tree(
            root,
            "05f3a5f46a54c0629af07bad317baa94b4a01b60d40474344a4e91a8386c0d98",
            "0.0.0",
        )


def make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("create table item(value integer)")
    connection.execute("insert into item values (1)")
    connection.commit()
    connection.close()


def test_disposable_probe_classifies_success_syntax_schema_and_mutation(
    tmp_path: Path,
) -> None:
    module = load_module()
    canonical_database = tmp_path / "db.sqlite"
    make_database(canonical_database)
    before = canonical_database.read_bytes()
    assert module.probe_sql_disposable(canonical_database, "select value from item", 10)[
        "class"
    ] == "EXECUTED"
    assert module.probe_sql_disposable(canonical_database, "select from", 10)[
        "class"
    ] == "SYNTAX_ERROR"
    assert module.probe_sql_disposable(canonical_database, "select * from missing", 10)[
        "class"
    ] == "SCHEMA_ERROR"
    assert module.probe_sql_disposable(canonical_database, "delete from item", 10)[
        "class"
    ] == "MUTATING_SQL_REFUSED"
    assert canonical_database.read_bytes() == before


def test_disposable_probe_times_out_and_keeps_the_row_in_scope(tmp_path: Path) -> None:
    module = load_module()
    canonical_database = tmp_path / "db.sqlite"
    make_database(canonical_database)
    result = module.probe_sql_disposable(
        canonical_database,
        "with recursive cnt(x) as (select 1 union all select x+1 from cnt) "
        "select sum(x) from cnt",
        1,
    )
    assert result["class"] == "TIMEOUT"


def test_entire_authoritative_scorer_row_is_owned_and_hard_time_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    database = tmp_path / "db.sqlite"
    make_database(database)
    tables = tmp_path / "tables.json"
    tables.write_text("[]", encoding="utf-8")
    row = module.build_frozen_rows(
        [{"db_id": "db", "question": "value", "query": "select value from item"}],
        [("select value from item", "db")],
    )[0]

    class TerminatingRunner:
        def run(self, command, timeout_s):
            assert timeout_s == 1
            assert "--owned-row-worker" in command
            return SimpleNamespace(
                status="terminated",
                returncode=-1,
                stdout="",
                stderr="hard timeout",
                cleanup_verified=True,
            )

    monkeypatch.setattr(module, "_owned_process_runner", lambda: TerminatingRunner())
    monkeypatch.setattr(
        module,
        "probe_sql_disposable",
        lambda *unused: (_ for _ in ()).throw(
            AssertionError("the parent process must not execute or probe SQL")
        ),
    )
    result = module.score_row(
        tmp_path,
        tmp_path,
        tables,
        database,
        row,
        "select value from item",
        1,
        tmp_path,
        tmp_path,
    )
    assert result["execution_class"] == "SCORER_TIMEOUT"
    assert result["_owned_cleanup_verified"] is True
    assert database.exists()


def test_owned_scorer_garbage_output_fails_closed_as_scorer_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    database = tmp_path / "db.sqlite"
    make_database(database)
    tables = tmp_path / "tables.json"
    tables.write_text("[]", encoding="utf-8")
    row = module.build_frozen_rows(
        [{"db_id": "db", "question": "value", "query": "select value from item"}],
        [("select value from item", "db")],
    )[0]

    class GarbageRunner:
        def run(self, command, timeout_s):
            return SimpleNamespace(
                status="completed",
                returncode=0,
                stdout="not-json",
                stderr="",
                cleanup_verified=True,
            )

    monkeypatch.setattr(module, "_owned_process_runner", lambda: GarbageRunner())
    result = module.score_row(
        tmp_path,
        tmp_path,
        tables,
        database,
        row,
        "select value from item",
        1,
        tmp_path,
        tmp_path,
    )
    assert result["execution_class"] == "SCORER_ERROR"
    assert result["exact_correct"] is False
    assert result["execution_correct"] is False


def test_real_pinned_spider_exact_and_execution_smoke(tmp_path: Path) -> None:
    exact_root_text = os.environ.get("EMBER_SPIDER_EXACT_ROOT")
    execution_root_text = os.environ.get("EMBER_SPIDER_EXECUTION_ROOT")
    nltk_data_root_text = os.environ.get("EMBER_NLTK_DATA_ROOT")
    sqlparse_root_text = os.environ.get("EMBER_SQLPARSE_ROOT")
    if (
        not exact_root_text
        or not execution_root_text
        or not nltk_data_root_text
        or not sqlparse_root_text
    ):
        pytest.skip("real pinned Spider scorer roots are not available")
    module = load_module()
    database = tmp_path / "db.sqlite"
    make_database(database)
    tables = tmp_path / "tables.json"
    tables.write_text(
        json.dumps(
            [
                {
                    "db_id": "db",
                    "table_names_original": ["item"],
                    "table_names": ["item"],
                    "column_names_original": [[-1, "*"], [0, "value"]],
                    "column_names": [[-1, "*"], [0, "value"]],
                    "column_types": ["text", "number"],
                    "primary_keys": [],
                    "foreign_keys": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    row = module.build_frozen_rows(
        [{"db_id": "db", "question": "value", "query": "select value from item"}],
        [("select value from item", "db")],
    )[0]
    result = module.score_row(
        Path(exact_root_text),
        Path(execution_root_text),
        tables,
        database,
        row,
        "select value from item",
        30,
        Path(nltk_data_root_text),
        Path(sqlparse_root_text) / "pyroot",
    )
    assert result["exact_correct"] is True, result
    assert result["execution_correct"] is True, result
    assert result["execution_class"] == "EXECUTED"


def test_real_owned_scorer_worker_enforces_whole_row_timeout(tmp_path: Path) -> None:
    exact_root_text = os.environ.get("EMBER_SPIDER_EXACT_ROOT")
    execution_root_text = os.environ.get("EMBER_SPIDER_EXECUTION_ROOT")
    nltk_data_root_text = os.environ.get("EMBER_NLTK_DATA_ROOT")
    sqlparse_root_text = os.environ.get("EMBER_SQLPARSE_ROOT")
    if not all(
        (exact_root_text, execution_root_text, nltk_data_root_text, sqlparse_root_text)
    ):
        pytest.skip("real pinned terminal evaluator dependencies are unavailable")
    module = load_module()
    database = tmp_path / "db.sqlite"
    make_database(database)
    tables = tmp_path / "tables.json"
    tables.write_text("[]", encoding="utf-8")
    row = module.build_frozen_rows(
        [{"db_id": "db", "question": "value", "query": "select value from item"}],
        [("select value from item", "db")],
    )[0]
    before = database.read_bytes()
    result = module.score_row(
        Path(exact_root_text),
        Path(execution_root_text),
        tables,
        database,
        row,
        "with recursive cnt(x) as (select 1 union all select x+1 from cnt) "
        "select sum(x) from cnt",
        1,
        Path(nltk_data_root_text),
        Path(sqlparse_root_text) / "pyroot",
    )
    assert result["execution_class"] == "SCORER_TIMEOUT", result
    assert result["_owned_cleanup_verified"] is True
    assert database.read_bytes() == before


def test_terminal_receipt_hashes_rows_resources_and_self_without_threshold() -> None:
    module = load_module()
    result = {
        "row_id": "1" * 64,
        "db_id": "db",
        "prediction_sha256": "2" * 64,
        "gold_sha256": "3" * 64,
        "exact_correct": True,
        "execution_correct": False,
        "execution_class": "SYNTAX_ERROR",
        "duration_ms": 7,
        "_owned_cleanup_verified": True,
        "_scorer_stdout": "stdout",
        "_scorer_stderr": "stderr",
    }
    resource = module.build_resource_receipt([result], 30)
    resource_raw = canonical(resource)
    receipt = module.build_terminal_receipt(
        valid_manifest(), "4" * 64, [result], hashlib.sha256(resource_raw).hexdigest()
    )
    claimed = receipt.pop("self_sha256")
    assert claimed == hashlib.sha256(canonical(receipt)).hexdigest()
    assert receipt["ordered_row_result_set_sha256"] == hashlib.sha256(
        canonical(receipt["rows"])
    ).hexdigest()
    assert receipt["sample_count"] == 1
    assert receipt["exact_match"] == 1.0
    assert receipt["execution_match"] == 0.0
    assert receipt["row_class_counts"] == {"SYNTAX_ERROR": 1}
    assert "criterion_result" not in receipt
    assert resource["cleanup_verified"] is True
    resource_without_self = dict(resource)
    resource_self = resource_without_self.pop("self_sha256")
    assert resource_self == hashlib.sha256(canonical(resource_without_self)).hexdigest()


@pytest.mark.parametrize(
    "failure_class",
    [
        "MISSING_DATABASE",
        "SCORER_ERROR",
        "EXACT_SCORER_ERROR",
        "EXECUTION_SCORER_ERROR",
        "SCORER_TIMEOUT",
        "MISSING_1581_ADMISSION_BINDING_FOR_SPIDER",
    ],
)
def test_infrastructure_failure_classes_are_never_covered(failure_class: str) -> None:
    module = load_module()
    result = {
        "row_id": "1" * 64,
        "db_id": "db",
        "prediction_sha256": "2" * 64,
        "gold_sha256": "3" * 64,
        "exact_correct": False,
        "execution_correct": False,
        "execution_class": failure_class,
        "duration_ms": 1,
        "_owned_cleanup_verified": True,
        "_scorer_stdout": "",
        "_scorer_stderr": "",
    }
    receipt = module.build_terminal_receipt(
        valid_manifest(), "4" * 64, [result], "5" * 64
    )
    assert receipt["result"] == "NOT_COVERED"
    assert receipt["sample_count"] == 1


def test_missing_1581_binding_builds_row_complete_structural_not_covered() -> None:
    module = load_module()
    rows = module.build_frozen_rows(
        [{"db_id": "db", "question": "one", "query": "select 1"}],
        [("select 1", "db")],
    )
    results = module.admission_missing_results(rows, ["select 1"])
    receipt = module.build_terminal_receipt(valid_manifest(), "4" * 64, results, "5" * 64)
    assert receipt["result"] == "NOT_COVERED"
    assert receipt["sample_count"] == 1
    assert receipt["row_class_counts"] == {
        "MISSING_1581_ADMISSION_BINDING_FOR_SPIDER": 1
    }


def test_cli_missing_1581_files_publishes_structural_not_covered(
    tmp_path: Path, monkeypatch
) -> None:
    module = load_module()
    monkeypatch.setattr(module, "verify_ember_import_bytes", lambda *_: None)
    examples = tmp_path / "examples.json"
    gold = tmp_path / "gold.txt"
    tables = tmp_path / "tables.json"
    examples.write_bytes(
        canonical([{"db_id": "db", "question": "one", "query": "select 1"}])
    )
    gold.write_bytes(b"select 1\tdb\n")
    tables.write_bytes(b"[]")
    rows = module.build_frozen_rows(json.loads(examples.read_bytes()), [("select 1", "db")])
    database_root = tmp_path / "database"
    database = database_root / "db" / "db.sqlite"
    database.parent.mkdir(parents=True)
    make_database(database)
    database_tree = tmp_path / "database-tree.json"
    database_tree.write_bytes(
        canonical(
            {
                "schema_version": "ember-spider-database-tree-manifest-v1",
                "files": [
                    {
                        "path": "db/db.sqlite",
                        "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
                    }
                ],
            }
        )
    )
    manifest = valid_manifest()
    inference = module.self_hashed(
        {
            "schema_version": "ember-spider-inference-receipt-v1",
            "result": "PASS",
            "model_sha256": manifest["model_sha256"],
            "checkpoint_sha256": manifest["checkpoint_sha256"],
            "tokenizer_sha256": manifest["tokenizer_sha256"],
            "config_sha256": manifest["config_sha256"],
            "ember_source_commit": manifest["ember_source_commit"],
        }
    )
    inference_path = tmp_path / "inference.json"
    inference_path.write_bytes(canonical(inference))
    prediction = {
        "schema_version": "ember-spider-prediction-envelope-v1",
        "inference_receipt_raw_sha256": hashlib.sha256(inference_path.read_bytes()).hexdigest(),
        "rows": [{"row_id": rows[0]["row_id"], "sql": "select 1"}],
    }
    prediction_path = tmp_path / "prediction.json"
    prediction_path.write_bytes(canonical(prediction))
    manifest.update(
        examples_raw_sha256=hashlib.sha256(examples.read_bytes()).hexdigest(),
        gold_raw_sha256=hashlib.sha256(gold.read_bytes()).hexdigest(),
        tables_raw_sha256=hashlib.sha256(tables.read_bytes()).hexdigest(),
        database_tree_manifest_sha256=hashlib.sha256(database_tree.read_bytes()).hexdigest(),
        ordered_row_set_sha256=module.ordered_row_set_sha256(rows),
        prediction_envelope_raw_sha256=hashlib.sha256(prediction_path.read_bytes()).hexdigest(),
        inference_receipt_raw_sha256=hashlib.sha256(inference_path.read_bytes()).hexdigest(),
    )
    manifest_path = write_manifest(tmp_path, manifest)
    resource = tmp_path / "resource.json"
    score = tmp_path / "score.json"
    arguments = [
        "--manifest", str(manifest_path), "--examples", str(examples),
        "--gold", str(gold), "--tables", str(tables),
        "--database-tree-manifest", str(database_tree), "--database-root", str(database_root),
        "--prediction-envelope", str(prediction_path), "--inference-receipt", str(inference_path),
        "--admission-receipt", str(tmp_path / "missing-admission.json"),
        "--catalog-fragment", str(tmp_path / "missing-fragment.json"),
        "--license-sidecar", str(tmp_path / "missing-license.json"),
        "--exact-scorer-root", str(tmp_path / "absent-exact"),
        "--execution-scorer-root", str(tmp_path / "absent-execution"),
        "--nltk-data-root", str(tmp_path / "absent-nltk"),
        "--sqlparse-root", str(tmp_path / "absent-sqlparse"),
        "--resource-receipt-output", str(resource), "--score-output", str(score),
    ]
    assert module.main(arguments) == 0
    receipt = json.loads(score.read_bytes())
    assert receipt["result"] == "NOT_COVERED"
    assert receipt["row_class_counts"] == {
        "MISSING_1581_ADMISSION_BINDING_FOR_SPIDER": 1
    }


def test_full_manifest_bound_terminal_cli_with_real_scorers(tmp_path: Path) -> None:
    exact_root_text = os.environ.get("EMBER_SPIDER_EXACT_ROOT")
    execution_root_text = os.environ.get("EMBER_SPIDER_EXECUTION_ROOT")
    nltk_data_root_text = os.environ.get("EMBER_NLTK_DATA_ROOT")
    sqlparse_root_text = os.environ.get("EMBER_SQLPARSE_ROOT")
    if not all(
        (exact_root_text, execution_root_text, nltk_data_root_text, sqlparse_root_text)
    ):
        pytest.skip("real pinned terminal evaluator dependencies are unavailable")
    module = load_module()
    source_commit = module.git_commit(ROOT)
    exact_root = Path(exact_root_text)
    execution_root = Path(execution_root_text)
    examples = tmp_path / "examples.json"
    examples.write_bytes(
        canonical(
            [
                {
                    "db_id": "db",
                    "question": "value",
                    "query": "select value from item",
                }
            ]
        )
    )
    gold = tmp_path / "gold.txt"
    gold.write_text("select value from item\tdb\n", encoding="utf-8")
    tables = tmp_path / "tables.json"
    tables.write_text(
        json.dumps(
            [
                {
                    "db_id": "db",
                    "table_names_original": ["item"],
                    "table_names": ["item"],
                    "column_names_original": [[-1, "*"], [0, "value"]],
                    "column_names": [[-1, "*"], [0, "value"]],
                    "column_types": ["text", "number"],
                    "primary_keys": [],
                    "foreign_keys": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    database_root = tmp_path / "database"
    database = database_root / "db" / "db.sqlite"
    database.parent.mkdir(parents=True)
    make_database(database)
    database_tree = tmp_path / "database-tree.json"
    database_tree.write_bytes(
        canonical(
            {
                "schema_version": "ember-spider-database-tree-manifest-v1",
                "files": [
                    {
                        "path": "db/db.sqlite",
                        "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
                    }
                ],
            }
        )
    )
    frozen_rows = module.build_frozen_rows(
        json.loads(examples.read_bytes()), [("select value from item", "db")]
    )
    inference = {
        "schema_version": "ember-spider-inference-receipt-v1",
        "result": "PASS",
        "model_sha256": "5" * 64,
        "checkpoint_sha256": "6" * 64,
        "tokenizer_sha256": "7" * 64,
        "config_sha256": "8" * 64,
        "ember_source_commit": source_commit,
    }
    inference["self_sha256"] = hashlib.sha256(canonical(inference)).hexdigest()
    inference_path = tmp_path / "inference.json"
    inference_path.write_bytes(canonical(inference))
    prediction = {
        "schema_version": "ember-spider-prediction-envelope-v1",
        "inference_receipt_raw_sha256": hashlib.sha256(
            inference_path.read_bytes()
        ).hexdigest(),
        "rows": [{"row_id": frozen_rows[0]["row_id"], "sql": "select value from item"}],
    }
    prediction_path = tmp_path / "prediction.json"
    prediction_path.write_bytes(canonical(prediction))
    admission, catalog_fragment, license_sidecar = admission_fixture(module)
    admission.update(
        ordered_row_set_sha256=module.ordered_row_set_sha256(frozen_rows),
        examples_raw_sha256=hashlib.sha256(examples.read_bytes()).hexdigest(),
        gold_raw_sha256=hashlib.sha256(gold.read_bytes()).hexdigest(),
        tables_raw_sha256=hashlib.sha256(tables.read_bytes()).hexdigest(),
        database_tree_manifest_sha256=hashlib.sha256(database_tree.read_bytes()).hexdigest(),
    )
    admission.pop("self_sha256")
    admission["self_sha256"] = hashlib.sha256(canonical(admission)).hexdigest()
    admission_path = tmp_path / "admission.json"
    fragment_path = tmp_path / "catalog-fragment.json"
    license_path = tmp_path / "license-sidecar.json"
    admission_path.write_bytes(canonical(admission))
    fragment_path.write_bytes(canonical(catalog_fragment))
    license_path.write_bytes(canonical(license_sidecar))
    manifest = valid_manifest()
    manifest.update(
        exact_match_evaluation_py_sha256=hashlib.sha256(
            (exact_root / "evaluation.py").read_bytes()
        ).hexdigest(),
        exact_match_process_sql_py_sha256=hashlib.sha256(
            (exact_root / "process_sql.py").read_bytes()
        ).hexdigest(),
        execution_match_evaluation_py_sha256=hashlib.sha256(
            (execution_root / "evaluation.py").read_bytes()
        ).hexdigest(),
        execution_match_exec_eval_py_sha256=hashlib.sha256(
            (execution_root / "exec_eval.py").read_bytes()
        ).hexdigest(),
        execution_match_exec_subprocess_py_sha256=hashlib.sha256(
            (execution_root / "exec_subprocess.py").read_bytes()
        ).hexdigest(),
        execution_match_process_sql_py_sha256=hashlib.sha256(
            (execution_root / "process_sql.py").read_bytes()
        ).hexdigest(),
        examples_raw_sha256=hashlib.sha256(examples.read_bytes()).hexdigest(),
        gold_raw_sha256=hashlib.sha256(gold.read_bytes()).hexdigest(),
        tables_raw_sha256=hashlib.sha256(tables.read_bytes()).hexdigest(),
        database_tree_manifest_sha256=hashlib.sha256(
            database_tree.read_bytes()
        ).hexdigest(),
        ordered_row_set_sha256=module.ordered_row_set_sha256(frozen_rows),
        prediction_envelope_raw_sha256=hashlib.sha256(
            prediction_path.read_bytes()
        ).hexdigest(),
        inference_receipt_raw_sha256=hashlib.sha256(
            inference_path.read_bytes()
        ).hexdigest(),
        model_sha256="5" * 64,
        checkpoint_sha256="6" * 64,
        tokenizer_sha256="7" * 64,
        config_sha256="8" * 64,
        ember_source_commit=source_commit,
        punkt_tab_tree_manifest_sha256="e4edcf9c6c88b89029b3eca665c05791bd1c7d58d123b750a88f41b2f89ce628",
        sqlparse_tree_manifest_sha256="05f3a5f46a54c0629af07bad317baa94b4a01b60d40474344a4e91a8386c0d98",
        admission_receipt_raw_sha256=hashlib.sha256(admission_path.read_bytes()).hexdigest(),
        catalog_fragment_raw_sha256=hashlib.sha256(fragment_path.read_bytes()).hexdigest(),
        license_sidecar_raw_sha256=hashlib.sha256(license_path.read_bytes()).hexdigest(),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(canonical(manifest))
    resource = tmp_path / "resource.json"
    score = tmp_path / "score.json"
    assert (
        module.main(
            [
                "--manifest",
                str(manifest_path),
                "--examples",
                str(examples),
                "--gold",
                str(gold),
                "--tables",
                str(tables),
                "--database-tree-manifest",
                str(database_tree),
                "--database-root",
                str(database_root),
                "--prediction-envelope",
                str(prediction_path),
                "--inference-receipt",
                str(inference_path),
                "--admission-receipt",
                str(admission_path),
                "--catalog-fragment",
                str(fragment_path),
                "--license-sidecar",
                str(license_path),
                "--exact-scorer-root",
                str(exact_root),
                "--execution-scorer-root",
                str(execution_root),
                "--nltk-data-root",
                nltk_data_root_text,
                "--sqlparse-root",
                sqlparse_root_text,
                "--resource-receipt-output",
                str(resource),
                "--score-output",
                str(score),
            ]
        )
        == 0
    )
    receipt = json.loads(score.read_bytes())
    assert receipt["result"] == "COVERED"
    assert receipt["exact_match"] == 1.0
    assert receipt["execution_match"] == 1.0
    assert receipt["resource_receipt_raw_sha256"] == hashlib.sha256(
        resource.read_bytes()
    ).hexdigest()
    with pytest.raises(SystemExit):
        module.main(
            [
                "--manifest",
                str(manifest_path),
                "--examples",
                str(examples),
                "--gold",
                str(gold),
                "--tables",
                str(tables),
                "--database-tree-manifest",
                str(database_tree),
                "--database-root",
                str(database_root),
                "--prediction-envelope",
                str(prediction_path),
                "--inference-receipt",
                str(inference_path),
                "--admission-receipt",
                str(admission_path),
                "--catalog-fragment",
                str(fragment_path),
                "--license-sidecar",
                str(license_path),
                "--exact-scorer-root",
                str(exact_root),
                "--execution-scorer-root",
                str(execution_root),
                "--nltk-data-root",
                nltk_data_root_text,
                "--sqlparse-root",
                sqlparse_root_text,
                "--resource-receipt-output",
                str(resource),
                "--score-output",
                str(score),
            ]
        )
