#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute hash-bound Spider scorers and publish row-complete terminal evidence."""
import argparse, contextlib, hashlib, importlib.metadata, importlib.util, io, json, os, shutil, sqlite3, subprocess, sys, tempfile
from pathlib import Path

MANIFEST_KEYS = {
 "exact_match_source_commit", "exact_match_evaluation_py_sha256",
 "exact_match_process_sql_py_sha256", "execution_match_source_commit",
 "execution_match_evaluation_py_sha256", "execution_match_exec_eval_py_sha256",
 "execution_match_exec_subprocess_py_sha256",
 "execution_match_process_sql_py_sha256", "examples_raw_sha256",
 "gold_raw_sha256", "tables_raw_sha256", "database_tree_manifest_sha256",
 "ordered_row_set_sha256", "prediction_envelope_raw_sha256",
 "inference_receipt_raw_sha256", "model_sha256", "checkpoint_sha256",
 "tokenizer_sha256", "config_sha256", "ember_source_commit",
 "per_row_timeout_seconds", "nltk_version", "punkt_tab_tree_manifest_sha256",
 "sqlparse_version", "sqlparse_tree_manifest_sha256",
 "admission_receipt_raw_sha256", "catalog_fragment_raw_sha256",
 "license_sidecar_raw_sha256",
}
HASH_KEYS = {key for key in MANIFEST_KEYS if key.endswith("_sha256")}
WORKER_CLASSES = {"EXECUTED","MUTATING_SQL_REFUSED","SYNTAX_ERROR","SCHEMA_ERROR","RUNTIME_ERROR","EXACT_SCORER_ERROR","EXECUTION_SCORER_ERROR","SCORER_ERROR"}
MODEL_OUTCOME_CLASSES = {"EXECUTED","SYNTAX_ERROR","SCHEMA_ERROR","RUNTIME_ERROR","MUTATING_SQL_REFUSED"}
_OWNED_PROCESS_MODULE = None
SPIDER_LICENSE_TOP_KEYS = {"schema_version","benchmark_id","authorities","dataset_attribution","self_sha256"}
SPIDER_LICENSE_AUTHORITY_KEYS = {"authority_id","asset_class","license_spdx","license_text_raw_sha256","upstream_url","artifact_url","artifact_identity","artifact_bytes","artifact_raw_sha256"}
SPIDER_LICENSE_ATTRIBUTION_KEYS = {"title","creators_citation","source_url","license_url","modifications","disclosure"}
SPIDER_LICENSE_AUTHORITIES = {
 "spider-code":{"asset_class":"code_scorer","license_spdx":"Apache-2.0","upstream_url":"https://github.com/taoyds/spider.git","artifact_url":"https://github.com/taoyds/spider/tree/b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c","artifact_identity":"git-tree:7687d1f709b5f2a645835d0c6c2ac13796e33491"},
 "spider-dataset":{"asset_class":"protected_eval_dataset","license_spdx":"CC-BY-SA-4.0","upstream_url":"https://yale-lily.github.io/spider","artifact_url":"https://drive.google.com/file/d/1403EGqzIDoHMdQF4c9Bkyl7dZLZ5Wt6J/view?usp=sharing","artifact_identity":"spider_data.zip"},
}

def _is_sha256(value: object) -> bool:
 return isinstance(value,str) and len(value)==64 and all(c in "0123456789abcdef" for c in value)

def parse_manifest(raw: bytes) -> dict:
 try: document=json.loads(raw)
 except (UnicodeError,json.JSONDecodeError) as exc: raise ValueError("manifest is unreadable") from exc
 if not isinstance(document,dict): raise ValueError("manifest must be an object")
 missing=sorted(MANIFEST_KEYS-set(document));unknown=sorted(set(document)-MANIFEST_KEYS)
 if missing: raise ValueError("manifest missing keys: "+", ".join(missing))
 if unknown: raise ValueError("manifest unknown keys: "+", ".join(unknown))
 for key in sorted(HASH_KEYS):
  if not _is_sha256(document[key]): raise ValueError(f"manifest {key} must be lowercase sha256")
 for key in ("exact_match_source_commit","execution_match_source_commit","ember_source_commit"):
  if not isinstance(document[key],str) or len(document[key])!=40 or not all(c in "0123456789abcdef" for c in document[key]): raise ValueError(f"manifest {key} must be lowercase git sha")
 timeout=document["per_row_timeout_seconds"]
 if isinstance(timeout,bool) or not isinstance(timeout,int) or not 1<=timeout<=3600: raise ValueError("manifest timeout must be an integer from 1 through 3600")
 if not isinstance(document["nltk_version"],str) or not document["nltk_version"].strip(): raise ValueError("manifest nltk_version must be a non-empty string")
 if not isinstance(document["sqlparse_version"],str) or not document["sqlparse_version"].strip(): raise ValueError("manifest sqlparse_version must be a non-empty string")
 return document

def load_manifest(path: Path) -> dict:
 try: return parse_manifest(read_file_bytes(path,"manifest"))
 except OSError as exc: raise ValueError("manifest is unreadable") from exc

def canonical(value: object) -> bytes:
 return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")

def sha256_bytes(value: bytes) -> str:
 return hashlib.sha256(value).hexdigest()

def sha256_file(path: Path) -> str:
 with path.open("rb") as handle:
  digest=hashlib.sha256()
  for block in iter(lambda:handle.read(1024*1024),b""): digest.update(block)
 return digest.hexdigest()

def build_frozen_rows(examples: list[dict], gold: list[tuple[str,str]]) -> list[dict]:
 if not isinstance(examples,list) or len(examples)!=len(gold) or not examples: raise ValueError("examples and gold must have one identical non-empty row set")
 result=[]
 for index,(example,gold_row) in enumerate(zip(examples,gold)):
  if not isinstance(example,dict) or set(example)!={"db_id","question","query"}: raise ValueError("example rows must carry only db_id, question, query")
  gold_sql,db_id=gold_row
  if not all(isinstance(value,str) and value.strip() for value in (example["db_id"],example["question"],example["query"],gold_sql,db_id)): raise ValueError("gold and example values must be non-empty strings")
  if example["db_id"]!=db_id or example["query"]!=gold_sql: raise ValueError("gold identity does not match the frozen example")
  gold_sha=sha256_bytes(gold_sql.encode("utf-8"))
  identity={"index":index,"db_id":db_id,"question":example["question"],"gold_sql_sha256":gold_sha}
  result.append({**identity,"gold_sql":gold_sql,"row_id":sha256_bytes(canonical(identity))})
 return result

def ordered_row_set_sha256(rows_: list[dict]) -> str:
 return sha256_bytes(canonical([row["row_id"] for row in rows_]))

def validate_prediction_envelope(envelope: object, rows_: list[dict], inference_hash: str) -> list[str]:
 if not isinstance(envelope,dict) or set(envelope)!={"schema_version","inference_receipt_raw_sha256","rows"}: raise ValueError("prediction envelope schema is closed")
 if envelope["schema_version"]!="ember-spider-prediction-envelope-v1" or envelope["inference_receipt_raw_sha256"]!=inference_hash: raise ValueError("prediction envelope inference identity mismatch")
 items=envelope["rows"]
 if not isinstance(items,list) or len(items)!=len(rows_): raise ValueError("prediction row set must exactly cover frozen rows")
 expected=[row["row_id"] for row in rows_]
 actual=[];predictions=[]
 for item in items:
  if not isinstance(item,dict) or set(item)!={"row_id","sql"} or not isinstance(item["sql"],str) or not item["sql"].strip(): raise ValueError("prediction rows require exact row_id and non-empty sql")
  actual.append(item["row_id"]);predictions.append(item["sql"])
 if actual!=expected or len(set(actual))!=len(actual): raise ValueError("prediction row identities are missing, duplicate, extra, or reordered")
 return predictions

def verify_bound_file(path: Path, expected: str, label: str) -> None:
 if not path.is_file() or path.is_symlink(): raise ValueError(f"{label} is missing, non-file, or symlinked")
 actual=sha256_file(path)
 if actual!=expected: raise ValueError(f"{label} sha256 {actual} does not equal {expected}")

def _safe_relative(path: str) -> bool:
 candidate=Path(path)
 return isinstance(path,str) and bool(path) and "\\" not in path and not candidate.is_absolute() and candidate.drive=="" and all(part not in ("",".","..") for part in candidate.parts)

def verify_database_tree(manifest_path: Path, database_root: Path, expected_hash: str) -> dict[str,Path]:
 verify_bound_file(manifest_path,expected_hash,"database tree manifest")
 if not database_root.is_dir() or database_root.is_symlink(): raise ValueError("database root is missing, non-directory, or symlinked")
 try: document=json.loads(manifest_path.read_text(encoding="utf-8"))
 except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise ValueError("database tree manifest is unreadable") from exc
 if not isinstance(document,dict) or set(document)!={"schema_version","files"} or document.get("schema_version")!="ember-spider-database-tree-manifest-v1" or not isinstance(document.get("files"),list) or not document["files"]: raise ValueError("database tree manifest schema is closed")
 databases={};seen=set()
 for index,row in enumerate(document["files"]):
  if not isinstance(row,dict) or set(row)!={"path","size","sha256"} or not _safe_relative(row.get("path")) or isinstance(row.get("size"),bool) or not isinstance(row.get("size"),int) or row["size"]<0 or not _is_sha256(row.get("sha256")) or row["path"] in seen: raise ValueError(f"database tree row {index} is invalid")
  seen.add(row["path"]);target=database_root.joinpath(*Path(row["path"]).parts)
  verify_bound_file(target,row["sha256"],f"database tree {row['path']}")
  if target.stat().st_size!=row["size"]: raise ValueError(f"database tree {row['path']} byte count drifted")
  relative=Path(row["path"])
  if len(relative.parts)==2 and relative.suffix==".sqlite" and relative.stem==relative.parts[0]: databases[relative.parts[0]]=target
 actual=set()
 for target in database_root.rglob("*"):
  if target.is_symlink(): raise ValueError("database tree contains a symlink")
  if target.is_file(): actual.add(target.relative_to(database_root).as_posix())
 if actual!=seen: raise ValueError("database tree has missing or extra files")
 if not databases: raise ValueError("database tree has no canonical db/db.sqlite entries")
 return databases

def verify_punkt_tab_tree(nltk_data_root: Path, expected_manifest_hash: str, expected_nltk_version: str) -> Path:
 try: actual_version=importlib.metadata.version("nltk")
 except importlib.metadata.PackageNotFoundError as exc: raise ValueError("pinned nltk runtime is unavailable") from exc
 if actual_version!=expected_nltk_version: raise ValueError(f"nltk version {actual_version} does not equal {expected_nltk_version}")
 if not nltk_data_root.is_dir() or nltk_data_root.is_symlink(): raise ValueError("nltk data root is missing, non-directory, or symlinked")
 manifest_path=nltk_data_root/"punkt-tab-tree-manifest.json"
 verify_bound_file(manifest_path,expected_manifest_hash,"punkt_tab tree manifest")
 try: document=json.loads(manifest_path.read_text(encoding="utf-8"))
 except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise ValueError("punkt_tab tree manifest is unreadable") from exc
 if not isinstance(document,dict) or set(document)!={"schema_version","tree_root","files"} or document.get("schema_version")!="ember-punkt-tab-tree-manifest-v1" or document.get("tree_root")!="tokenizers/punkt_tab/english" or not isinstance(document.get("files"),list) or not document["files"]: raise ValueError("punkt_tab tree manifest schema is closed")
 expected={}
 for index,row in enumerate(document["files"]):
  if not isinstance(row,dict) or set(row)!={"path","sha256","size"} or not _safe_relative(row.get("path")) or not _is_sha256(row.get("sha256")) or isinstance(row.get("size"),bool) or not isinstance(row.get("size"),int) or row["size"]<0 or row["path"] in expected: raise ValueError(f"punkt_tab tree row {index} is invalid")
  expected[row["path"]]=row
 english=nltk_data_root/"tokenizers"/"punkt_tab"/"english"
 if not english.is_dir() or english.is_symlink(): raise ValueError("punkt_tab english tree is missing, non-directory, or symlinked")
 actual={}
 for target in english.rglob("*"):
  if target.is_symlink(): raise ValueError("punkt_tab english tree contains a symlink")
  if target.is_file(): actual[target.relative_to(english).as_posix()]=target
 if set(actual)!=set(expected): raise ValueError("punkt_tab english tree has missing or extra files")
 for relative,target in actual.items():
  row=expected[relative]
  if target.stat().st_size!=row["size"] or sha256_file(target)!=row["sha256"]: raise ValueError(f"punkt_tab tree {relative} bytes drifted")
 return english

def verify_sqlparse_tree(custody_root: Path, expected_manifest_hash: str, expected_version: str) -> Path:
 if not custody_root.is_dir() or custody_root.is_symlink(): raise ValueError("sqlparse custody root is missing, non-directory, or symlinked")
 manifest_path=custody_root/"sqlparse-tree-manifest.json"
 verify_bound_file(manifest_path,expected_manifest_hash,"sqlparse tree manifest")
 try: document=json.loads(manifest_path.read_text(encoding="utf-8"))
 except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise ValueError("sqlparse tree manifest is unreadable") from exc
 if not isinstance(document,dict) or set(document)!={"schema_version","package","version","tree_root","files"} or document.get("schema_version")!="ember-sqlparse-tree-manifest-v1" or document.get("package")!="sqlparse" or document.get("version")!=expected_version or document.get("tree_root")!="pyroot" or not isinstance(document.get("files"),list) or not document["files"]: raise ValueError("sqlparse tree manifest schema or version is invalid")
 expected={}
 for index,row in enumerate(document["files"]):
  if not isinstance(row,dict) or set(row)!={"path","sha256","size"} or not _safe_relative(row.get("path")) or not _is_sha256(row.get("sha256")) or isinstance(row.get("size"),bool) or not isinstance(row.get("size"),int) or row["size"]<0 or row["path"] in expected: raise ValueError(f"sqlparse tree row {index} is invalid")
  expected[row["path"]]=row
 pyroot=custody_root/"pyroot"
 if not pyroot.is_dir() or pyroot.is_symlink(): raise ValueError("sqlparse pyroot is missing, non-directory, or symlinked")
 actual={}
 for target in pyroot.rglob("*"):
  if target.is_symlink(): raise ValueError("sqlparse tree contains a symlink")
  if target.is_file(): actual[target.relative_to(pyroot).as_posix()]=target
 if set(actual)!=set(expected): raise ValueError("sqlparse tree has missing or extra files")
 for relative,target in actual.items():
  row=expected[relative]
  if target.stat().st_size!=row["size"] or sha256_file(target)!=row["sha256"]: raise ValueError(f"sqlparse tree {relative} bytes drifted")
 distributions=[item for item in importlib.metadata.distributions(path=[str(pyroot)]) if item.metadata.get("Name","").lower()=="sqlparse"]
 if len(distributions)!=1 or distributions[0].version!=expected_version: raise ValueError("sqlparse tree distribution version mismatch")
 return pyroot

@contextlib.contextmanager
def pinned_nltk_data(nltk_data_root: Path):
 previous_environment=os.environ.get("NLTK_DATA")
 os.environ["NLTK_DATA"]=str(nltk_data_root)
 import nltk
 previous_paths=list(nltk.data.path)
 nltk.data.path[:]=[str(nltk_data_root)]
 try: yield
 finally:
  nltk.data.path[:]=previous_paths
  if previous_environment is None: os.environ.pop("NLTK_DATA",None)
  else: os.environ["NLTK_DATA"]=previous_environment

@contextlib.contextmanager
def pinned_sqlparse_root(pyroot: Path):
 previous={name:module for name,module in sys.modules.items() if name=="sqlparse" or name.startswith("sqlparse.")}
 for name in previous: sys.modules.pop(name,None)
 sys.path.insert(0,str(pyroot))
 try: yield
 finally:
  for name in list(sys.modules):
   if name=="sqlparse" or name.startswith("sqlparse."): sys.modules.pop(name,None)
  sys.modules.update(previous)
  try: sys.path.remove(str(pyroot))
  except ValueError: pass

def _owned_process_runner():
 global _OWNED_PROCESS_MODULE
 if _OWNED_PROCESS_MODULE is not None: return _OWNED_PROCESS_MODULE.OwnedProcessRunner()
 source=Path(__file__).resolve().parents[1]/"src"/"ember"/"governance"/"scripts"/"owned_process.py"
 spec=importlib.util.spec_from_file_location("spider_terminal_owned_process",source)
 if spec is None or spec.loader is None: raise RuntimeError("owned process runner is unavailable")
 _OWNED_PROCESS_MODULE=importlib.util.module_from_spec(spec);sys.modules[spec.name]=_OWNED_PROCESS_MODULE;spec.loader.exec_module(_OWNED_PROCESS_MODULE)
 return _OWNED_PROCESS_MODULE.OwnedProcessRunner()

def _headless_python_command(*arguments: str) -> list[str]:
 return [sys.executable,*arguments]

def _load_scorer(root: Path, filename: str, name: str):
 source=root/filename
 if not source.is_file(): raise ValueError(f"pinned scorer file missing: {source}")
 for collision in ("process_sql","exec_eval","exec_subprocess","parse"):
  sys.modules.pop(collision,None)
 sys.path.insert(0,str(root))
 try:
  spec=importlib.util.spec_from_file_location(name,source)
  if spec is None or spec.loader is None: raise ValueError(f"cannot load pinned scorer: {source}")
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
 finally: sys.path.pop(0)

def exact_match_row(exact_root: Path, tables: Path, database: Path, db_id: str, prediction: str, gold: str) -> bool:
 scorer=_load_scorer(exact_root,"evaluation.py","ember_issue1964_exact")
 schema=scorer.Schema(scorer.get_schema(str(database)));evaluator=scorer.Evaluator()
 gold_sql=scorer.get_sql(schema,gold)
 try: prediction_sql=scorer.get_sql(schema,prediction)
 except Exception: return False
 key_map=scorer.build_foreign_key_map_from_json(str(tables))[db_id]
 gold_columns=scorer.build_valid_col_units(gold_sql["from"]["table_units"],schema)
 gold_sql=scorer.rebuild_sql_col(gold_columns,scorer.rebuild_sql_val(gold_sql),key_map)
 prediction_columns=scorer.build_valid_col_units(prediction_sql["from"]["table_units"],schema)
 prediction_sql=scorer.rebuild_sql_col(prediction_columns,scorer.rebuild_sql_val(prediction_sql),key_map)
 return bool(evaluator.eval_exact_match(prediction_sql,gold_sql))

def execution_match_row(execution_root: Path, database: Path, prediction: str, gold: str, timeout_seconds: int) -> bool:
 scorer=_load_scorer(execution_root,"evaluation.py","ember_issue1964_execution")
 imported=sys.modules.get("exec_eval")
 if imported is not None: imported.TIMEOUT=timeout_seconds
 return bool(scorer.eval_exec_match(str(database),prediction,gold,False,False,False))

def score_row(exact_root: Path, execution_root: Path, tables: Path, database: Path, row: dict, prediction: str, timeout_seconds: int, nltk_data_root: Path, sqlparse_pyroot: Path) -> dict:
 before=sha256_file(database);started=__import__("time").monotonic_ns()
 with tempfile.TemporaryDirectory() as directory:
  root=Path(directory);disposable=root/database.name;shutil.copy2(database,disposable)
  payload={"exact_root":str(exact_root),"execution_root":str(execution_root),"tables":str(tables),"database":str(disposable),"row":row,"prediction":prediction,"nltk_data_root":str(nltk_data_root),"sqlparse_pyroot":str(sqlparse_pyroot)}
  payload_path=root/"row-worker-input.json";payload_path.write_bytes(canonical(payload))
  command=_headless_python_command("-B",str(Path(__file__).resolve()),"--owned-row-worker",str(payload_path))
  completed=_owned_process_runner().run(command,timeout_s=timeout_seconds)
  if completed.status=="terminated": worker={"exact_correct":False,"execution_correct":False,"execution_class":"SCORER_TIMEOUT","detail":"authoritative scorer row exceeded the manifest timeout","scorer_stdout":"","scorer_stderr":""}
  elif completed.returncode!=0: worker={"exact_correct":False,"execution_correct":False,"execution_class":"SCORER_ERROR","detail":completed.stderr.strip(),"scorer_stdout":completed.stdout,"scorer_stderr":""}
  else:
   try: worker=json.loads(completed.stdout)
   except json.JSONDecodeError: worker={"exact_correct":False,"execution_correct":False,"execution_class":"SCORER_ERROR","detail":"owned scorer returned non-JSON transport output","scorer_stdout":completed.stdout,"scorer_stderr":completed.stderr}
  if not isinstance(worker,dict) or set(worker) not in ({"exact_correct","execution_correct","execution_class","scorer_stdout","scorer_stderr"},{"exact_correct","execution_correct","execution_class","detail","scorer_stdout","scorer_stderr"}) or not isinstance(worker.get("exact_correct"),bool) or not isinstance(worker.get("execution_correct"),bool) or worker.get("execution_class") not in WORKER_CLASSES|{"SCORER_TIMEOUT"} or not isinstance(worker.get("scorer_stdout"),str) or not isinstance(worker.get("scorer_stderr"),str) or ("detail" in worker and not isinstance(worker["detail"],str)):
   worker={"exact_correct":False,"execution_correct":False,"execution_class":"SCORER_ERROR","detail":"owned scorer transport schema is invalid","scorer_stdout":completed.stdout,"scorer_stderr":completed.stderr}
 if sha256_file(database)!=before: raise RuntimeError("canonical database custody changed")
 result={"row_id":row["row_id"],"db_id":row["db_id"],"prediction_sha256":sha256_bytes(prediction.encode()),"gold_sha256":sha256_bytes(row["gold_sql"].encode()),"exact_correct":worker["exact_correct"],"execution_correct":worker["execution_correct"],"execution_class":worker["execution_class"],"duration_ms":max(0,(__import__("time").monotonic_ns()-started)//1_000_000),"_owned_cleanup_verified":completed.cleanup_verified,"_scorer_stdout":worker["scorer_stdout"],"_scorer_stderr":worker["scorer_stderr"]+completed.stderr}
 if "detail" in worker: result["detail"]=worker["detail"]
 return result

SQL_PROBE = r'''import hashlib,json,sqlite3,sys
path,query=sys.argv[1],sys.argv[2]
denied={sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_ALTER_TABLE,sqlite3.SQLITE_DROP_TABLE,sqlite3.SQLITE_DROP_INDEX,sqlite3.SQLITE_DROP_TRIGGER,sqlite3.SQLITE_DROP_VIEW,sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_CREATE_INDEX,sqlite3.SQLITE_CREATE_TRIGGER,sqlite3.SQLITE_CREATE_VIEW,sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH}
connection=sqlite3.connect(path)
connection.set_authorizer(lambda action,*unused: sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK)
try:
 rows=connection.execute(query).fetchall()
 raw=json.dumps(rows,sort_keys=True,separators=(",",":"),default=str).encode()
 print(json.dumps({"class":"EXECUTED","result_sha256":hashlib.sha256(raw).hexdigest()}))
except sqlite3.Error as error:
 message=str(error).lower()
 if "not authorized" in message: cls="MUTATING_SQL_REFUSED"
 elif "syntax error" in message or "incomplete input" in message: cls="SYNTAX_ERROR"
 elif "no such table" in message or "no such column" in message: cls="SCHEMA_ERROR"
 else: cls="RUNTIME_ERROR"
 print(json.dumps({"class":cls,"detail":str(error)}))
finally: connection.close()
'''

def _probe_sql_in_process(database: Path, query: str) -> dict:
 denied={sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_ALTER_TABLE,sqlite3.SQLITE_DROP_TABLE,sqlite3.SQLITE_DROP_INDEX,sqlite3.SQLITE_DROP_TRIGGER,sqlite3.SQLITE_DROP_VIEW,sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_CREATE_INDEX,sqlite3.SQLITE_CREATE_TRIGGER,sqlite3.SQLITE_CREATE_VIEW,sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH}
 connection=sqlite3.connect(database)
 connection.set_authorizer(lambda action,*unused: sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK)
 try:
  rows_=connection.execute(query).fetchall();raw=json.dumps(rows_,sort_keys=True,separators=(",",":"),default=str).encode()
  return {"class":"EXECUTED","result_sha256":sha256_bytes(raw)}
 except sqlite3.Error as error:
  message=str(error).lower()
  if "not authorized" in message: cls="MUTATING_SQL_REFUSED"
  elif "syntax error" in message or "incomplete input" in message: cls="SYNTAX_ERROR"
  elif "no such table" in message or "no such column" in message: cls="SCHEMA_ERROR"
  else: cls="RUNTIME_ERROR"
  return {"class":cls,"detail":str(error)}
 finally: connection.close()

def _owned_row_worker(payload_path: Path) -> dict:
 payload=json.loads(payload_path.read_bytes())
 required={"exact_root","execution_root","tables","database","row","prediction","nltk_data_root","sqlparse_pyroot"}
 if not isinstance(payload,dict) or set(payload)!=required or not isinstance(payload.get("row"),dict) or not isinstance(payload.get("prediction"),str): raise ValueError("owned row worker input schema is invalid")
 row=payload["row"];database=Path(payload["database"]);prediction=payload["prediction"]
 probe=_probe_sql_in_process(database,prediction);exact=False;execution=False
 with pinned_nltk_data(Path(payload["nltk_data_root"])), pinned_sqlparse_root(Path(payload["sqlparse_pyroot"])):
  try: exact=exact_match_row(Path(payload["exact_root"]),Path(payload["tables"]),database,row["db_id"],prediction,row["gold_sql"])
  except Exception as exc: probe.update({"class":"EXACT_SCORER_ERROR","detail":f"{type(exc).__name__}: {exc}"})
  if probe.get("class")=="EXECUTED":
   try: execution=execution_match_row(Path(payload["execution_root"]),database,prediction,row["gold_sql"],3600)
   except Exception as exc: probe.update({"class":"EXECUTION_SCORER_ERROR","detail":f"{type(exc).__name__}: {exc}"})
 result={"exact_correct":exact,"execution_correct":execution,"execution_class":probe["class"]}
 if "detail" in probe: result["detail"]=probe["detail"]
 return result

def _owned_row_worker_cli(payload_path: Path) -> int:
 stdout=io.StringIO();stderr=io.StringIO()
 try:
  with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr): result=_owned_row_worker(payload_path)
 except Exception as exc:
  result={"exact_correct":False,"execution_correct":False,"execution_class":"SCORER_ERROR","detail":f"{type(exc).__name__}: {exc}"}
 result["scorer_stdout"]=stdout.getvalue();result["scorer_stderr"]=stderr.getvalue()
 sys.stdout.buffer.write(canonical(result));return 0

def probe_sql_disposable(database: Path, query: str, timeout_seconds: int) -> dict:
 before=sha256_file(database)
 with tempfile.TemporaryDirectory() as directory:
  disposable=Path(directory)/database.name;shutil.copy2(database,disposable)
  command=_headless_python_command("-B","-c",SQL_PROBE,str(disposable),query)
  completed=_owned_process_runner().run(command,timeout_s=timeout_seconds)
  if completed.status=="terminated": result={"class":"TIMEOUT"}
  else:
   if completed.returncode!=0: result={"class":"SCORER_PROCESS_ERROR","detail":completed.stderr.strip()}
   else:
    try: result=json.loads(completed.stdout)
    except json.JSONDecodeError: result={"class":"SCORER_OUTPUT_ERROR"}
  result["_owned_cleanup_verified"]=completed.cleanup_verified
  result["_scorer_stdout"]=completed.stdout
  result["_scorer_stderr"]=completed.stderr
 if sha256_file(database)!=before: raise RuntimeError("canonical database custody changed")
 return result

def git_commit(root: Path) -> str:
 creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
 completed=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],text=True,capture_output=True,check=False,timeout=30,creationflags=creationflags)
 if completed.returncode!=0: raise ValueError("git source commit is unavailable")
 return completed.stdout.strip()

def verify_git_commit(root: Path, expected: str, label: str) -> None:
 if git_commit(root)!=expected: raise ValueError(f"{label} source commit mismatch")

def git_status_rows(root: Path) -> list[str]:
 creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
 completed=subprocess.run(["git","-C",str(root),"status","--porcelain=v1","--untracked-files=all"],text=True,capture_output=True,check=False,timeout=30,creationflags=creationflags)
 if completed.returncode!=0: raise ValueError("git source status is unavailable")
 return completed.stdout.splitlines()

def verify_clean_git_root(root: Path, expected: str, label: str) -> None:
 verify_git_commit(root,expected,label)
 for row in git_status_rows(root):
  path=row[3:].replace("\\","/") if len(row)>=4 else ""
  bytecode=row.startswith("?? ") and path.endswith(".pyc") and (path.startswith("__pycache__/") or "/__pycache__/" in path)
  if not bytecode: raise ValueError(f"{label} source root is not clean: {row}")

def git_file_bytes(root: Path, commit: str, relative: Path) -> bytes:
 creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
 completed=subprocess.run(["git","-C",str(root),"show",f"{commit}:{relative.as_posix()}"],capture_output=True,check=False,timeout=30,creationflags=creationflags)
 if completed.returncode!=0: raise ValueError(f"committed Ember file is unavailable: {relative.as_posix()}")
 return completed.stdout

def ember_import_files(root: Path) -> set[Path]:
 resolved_root=root.resolve();result={Path(__file__).resolve()}
 for module in tuple(sys.modules.values()):
  value=getattr(module,"__file__",None)
  if not value: continue
  try: candidate=Path(value).resolve();candidate.relative_to(resolved_root)
  except (OSError,ValueError): continue
  if candidate.is_file(): result.add(candidate)
 return result

def verify_ember_import_bytes(root: Path, expected: str) -> None:
 verify_git_commit(root,expected,"Ember")
 _owned_process_runner()
 resolved_root=root.resolve()
 for target in ember_import_files(resolved_root):
  if target.is_symlink() or not target.is_file(): raise ValueError("bound Ember import is missing or symlinked")
  relative=target.relative_to(resolved_root)
  if target.read_bytes()!=git_file_bytes(resolved_root,expected,relative): raise ValueError(f"bound Ember import is modified: {relative.as_posix()}")

def _owned_import_set_cli() -> int:
 _owned_process_runner();root=Path(__file__).resolve().parents[1]
 relative=sorted(path.relative_to(root).as_posix() for path in ember_import_files(root))
 sys.stdout.buffer.write(canonical(relative));return 0

def read_bound_bytes(path: Path, expected: str, label: str) -> bytes:
 raw=read_file_bytes(path,label);actual=sha256_bytes(raw)
 if actual!=expected: raise ValueError(f"{label} sha256 {actual} does not equal {expected}")
 return raw

def read_file_bytes(path: Path, label: str) -> bytes:
 if not path.is_file() or path.is_symlink(): raise ValueError(f"{label} is missing, non-file, or symlinked")
 return path.read_bytes()

def load_gold(raw: bytes) -> list[tuple[str,str]]:
 try: lines=raw.decode("utf-8").splitlines()
 except UnicodeDecodeError as exc: raise ValueError("gold is not UTF-8") from exc
 result=[]
 for index,line in enumerate(lines):
  parts=line.split("\t")
  if len(parts)!=2 or not all(part.strip() for part in parts): raise ValueError(f"gold row {index} is invalid")
  result.append((parts[0],parts[1]))
 if not result: raise ValueError("gold must be non-empty")
 return result

def validate_inference_receipt(raw: bytes, manifest: dict) -> dict:
 try: receipt=json.loads(raw)
 except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise ValueError("inference receipt is unreadable") from exc
 keys={"schema_version","result","model_sha256","checkpoint_sha256","tokenizer_sha256","config_sha256","ember_source_commit","self_sha256"}
 if not isinstance(receipt,dict) or set(receipt)!=keys or receipt.get("schema_version")!="ember-spider-inference-receipt-v1" or receipt.get("result")!="PASS": raise ValueError("inference receipt schema is closed and must be PASS")
 claimed=receipt.pop("self_sha256")
 if claimed!=sha256_bytes(canonical(receipt)): raise ValueError("inference receipt self hash is invalid")
 receipt["self_sha256"]=claimed
 for key in ("model_sha256","checkpoint_sha256","tokenizer_sha256","config_sha256","ember_source_commit"):
  if receipt.get(key)!=manifest[key]: raise ValueError(f"inference receipt {key} substitution")
 return receipt

def _closed_self_hashed(raw: bytes, keys: set[str], schema_version: str) -> dict:
 try: value=json.loads(raw)
 except (UnicodeDecodeError,json.JSONDecodeError): raise ValueError("bound JSON is unreadable")
 if not isinstance(value,dict) or set(value)!=keys or value.get("schema_version")!=schema_version: raise ValueError("bound JSON schema is closed")
 claimed=value.get("self_sha256");unsigned={key:item for key,item in value.items() if key!="self_sha256"}
 if not _is_sha256(claimed) or claimed!=sha256_bytes(canonical(unsigned)): raise ValueError("bound JSON self hash is invalid")
 return value

def validate_spider_license_sidecar(raw: bytes) -> dict:
 sidecar=_closed_self_hashed(raw,SPIDER_LICENSE_TOP_KEYS,"ember-spider-license-sidecar-v2")
 if sidecar.get("benchmark_id")!="spider": raise ValueError("Spider license sidecar identity mismatch")
 authorities=sidecar.get("authorities")
 if not isinstance(authorities,list) or [row.get("authority_id") if isinstance(row,dict) else None for row in authorities]!=sorted(SPIDER_LICENSE_AUTHORITIES): raise ValueError("Spider license authorities are absent, extra, or reordered")
 license_hashes=set()
 for row in authorities:
  if set(row)!=SPIDER_LICENSE_AUTHORITY_KEYS: raise ValueError("Spider license authority row schema is closed")
  expected=SPIDER_LICENSE_AUTHORITIES[row["authority_id"]]
  if any(row.get(key)!=item for key,item in expected.items()): raise ValueError("Spider license authority identity mismatch")
  if not _is_sha256(row.get("license_text_raw_sha256")) or not _is_sha256(row.get("artifact_raw_sha256")): raise ValueError("Spider license authority raw identity is invalid")
  artifact_bytes=row.get("artifact_bytes")
  if isinstance(artifact_bytes,bool) or not isinstance(artifact_bytes,int) or artifact_bytes<=0: raise ValueError("Spider license authority artifact bytes are invalid")
  license_hashes.add(row["license_text_raw_sha256"])
 if len(license_hashes)!=len(authorities): raise ValueError("Spider code and dataset license text identities are conflated")
 attribution=sidecar.get("dataset_attribution")
 if not isinstance(attribution,dict) or set(attribution)!=SPIDER_LICENSE_ATTRIBUTION_KEYS or any(not isinstance(item,str) or not item.strip() for item in attribution.values()) or attribution.get("source_url")!="https://yale-lily.github.io/spider" or attribution.get("license_url")!="https://creativecommons.org/licenses/by-sa/4.0/legalcode": raise ValueError("Spider dataset attribution is incomplete or substituted")
 return sidecar

def validate_1581_admission_binding(admission_raw: bytes, catalog_raw: bytes, license_raw: bytes, manifest: dict) -> bool:
 """Return False, never partial credit, for an absent or unverifiable #1581 binding."""
 try:
  if sha256_bytes(admission_raw)!=manifest["admission_receipt_raw_sha256"]: raise ValueError("admission receipt raw identity mismatch")
  if sha256_bytes(catalog_raw)!=manifest["catalog_fragment_raw_sha256"]: raise ValueError("catalog fragment raw identity mismatch")
  if sha256_bytes(license_raw)!=manifest["license_sidecar_raw_sha256"]: raise ValueError("license sidecar raw identity mismatch")
  validate_spider_license_sidecar(license_raw)
  receipt_keys={"schema_version","result","benchmark_id","protected_eval_id","catalog_fragment_raw_sha256","license_sidecar_raw_sha256","ordered_row_set_sha256","examples_raw_sha256","gold_raw_sha256","tables_raw_sha256","database_tree_manifest_sha256","self_sha256"}
  receipt=_closed_self_hashed(admission_raw,receipt_keys,"ember-spider-1581-admission-receipt-v1")
  if receipt["result"]!="ADMITTED_FOR_PROTECTED_EVALUATION" or receipt["benchmark_id"]!="spider": raise ValueError("admission receipt verdict is not Spider admitted")
  for key in ("catalog_fragment_raw_sha256","license_sidecar_raw_sha256","ordered_row_set_sha256","examples_raw_sha256","gold_raw_sha256","tables_raw_sha256","database_tree_manifest_sha256"):
   if not _is_sha256(receipt[key]) or receipt[key]!=manifest[key]: raise ValueError(f"admission receipt {key} substitution")
  try: fragment=json.loads(catalog_raw)
  except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise ValueError("catalog fragment is unreadable") from exc
  if not isinstance(fragment,dict) or set(fragment)!={"schema_version","records","edges"} or fragment.get("schema_version")!="ember-data-catalog-manifest-v1" or not isinstance(fragment.get("records"),list) or not isinstance(fragment.get("edges"),list): raise ValueError("catalog fragment schema is closed")
  protected=[row for row in fragment["records"] if isinstance(row,dict) and row.get("id")==receipt["protected_eval_id"] and row.get("kind")=="protected_eval"]
  if len(protected)!=1: raise ValueError("catalog fragment protected evaluation identity is absent or ambiguous")
  evaluation=protected[0]
  if evaluation.get("exclusion_reason") is not None or evaluation.get("overlap_state")!="isolated" or evaluation.get("near_dup_ruling") not in {"not_run","pass"} or evaluation.get("ngram_ruling") not in {"not_run","pass"} or not _is_sha256(evaluation.get("test_set_sha256")): raise ValueError("catalog fragment protected evaluation is not admitted")
  attempts={row.get("id") for row in fragment["records"] if isinstance(row,dict) and row.get("kind")=="consumer_attempt" and row.get("state")=="admitted"}
  consumer_edges=[edge for edge in fragment["edges"] if isinstance(edge,dict) and edge.get("kind")=="consumer_evaluation" and edge.get("from_id") in attempts and edge.get("from_kind")=="consumer_attempt" and edge.get("to_id")==receipt["protected_eval_id"] and edge.get("to_kind")=="protected_eval"]
  object_edges=[edge for edge in fragment["edges"] if isinstance(edge,dict) and edge.get("kind")=="evaluation_object" and edge.get("from_id")==receipt["protected_eval_id"] and edge.get("from_kind")=="protected_eval" and edge.get("to_id")==f"sha256:{evaluation['test_set_sha256']}" and edge.get("to_kind")=="immutable_object"]
  if len(consumer_edges)!=1 or len(object_edges)!=1: raise ValueError("catalog fragment admission edges are absent or ambiguous")
  return True
 except (KeyError,TypeError,ValueError): return False

def admission_missing_results(rows_: list[dict], predictions: list[str]) -> list[dict]:
 return [{"row_id":row["row_id"],"db_id":row["db_id"],"prediction_sha256":sha256_bytes(prediction.encode()),"gold_sha256":sha256_bytes(row["gold_sql"].encode()),"exact_correct":False,"execution_correct":False,"execution_class":"MISSING_1581_ADMISSION_BINDING_FOR_SPIDER","duration_ms":0,"_owned_cleanup_verified":True,"_scorer_stdout":"","_scorer_stderr":""} for row,prediction in zip(rows_,predictions)]

def verify_scorer_sources(exact_root: Path, execution_root: Path, manifest: dict) -> None:
 verify_clean_git_root(exact_root,manifest["exact_match_source_commit"],"exact scorer")
 verify_clean_git_root(execution_root,manifest["execution_match_source_commit"],"execution scorer")
 for root,rows_ in (
  (exact_root,(("evaluation.py","exact_match_evaluation_py_sha256"),("process_sql.py","exact_match_process_sql_py_sha256"))),
  (execution_root,(("evaluation.py","execution_match_evaluation_py_sha256"),("exec_eval.py","execution_match_exec_eval_py_sha256"),("exec_subprocess.py","execution_match_exec_subprocess_py_sha256"),("process_sql.py","execution_match_process_sql_py_sha256"))),
 ):
  for filename,key in rows_: verify_bound_file(root/filename,manifest[key],f"pinned scorer {filename}")

def self_hashed(value: dict) -> dict:
 result=dict(value);result["self_sha256"]=sha256_bytes(canonical(result));return result

def build_resource_receipt(results: list[dict], timeout_seconds: int) -> dict:
 processes=[{"row_id":row["row_id"],"cleanup_verified":bool(row.get("_owned_cleanup_verified")),"stdout_raw_sha256":sha256_bytes(row.get("_scorer_stdout","").encode()),"stderr_raw_sha256":sha256_bytes(row.get("_scorer_stderr","").encode())} for row in results]
 return self_hashed({"schema_version":"ember-issue1964-spider-resource-receipt-v1","per_row_timeout_seconds":timeout_seconds,"row_processes":processes,"cleanup_verified":all(item["cleanup_verified"] for item in processes)})

def build_terminal_receipt(manifest: dict, manifest_raw_sha256: str, results: list[dict], resource_receipt_raw_sha256: str) -> dict:
 rows_=[{key:value for key,value in row.items() if not key.startswith("_")} for row in results]
 sample_count=len(rows_)
 if sample_count==0: raise ValueError("terminal receipt requires a non-empty row set")
 class_counts={}
 for row in rows_: class_counts[row["execution_class"]]=class_counts.get(row["execution_class"],0)+1
 exact_correct=sum(bool(row["exact_correct"]) for row in rows_);execution_correct=sum(bool(row["execution_correct"]) for row in rows_)
 stdout_raw="".join(row.get("_scorer_stdout","") for row in results).encode();stderr_raw="".join(row.get("_scorer_stderr","") for row in results).encode()
 cleanup_verified=all(bool(row.get("_owned_cleanup_verified")) for row in results)
 if not cleanup_verified: raise ValueError("owned scorer cleanup is not verified")
 covered=all(row["execution_class"] in MODEL_OUTCOME_CLASSES for row in rows_);verdict="COVERED" if covered else "NOT_COVERED"
 claim="COVERED proves one complete frozen Spider evaluator execution for one exact prediction/checkpoint lineage; it does not by itself close issue 1964 or issue 1947." if covered else "NOT_COVERED preserves the complete row evidence but grants zero issue 1964 or issue 1947 coverage credit because at least one row was not authoritatively adjudicated."
 return self_hashed({"schema_version":"ember-issue1964-spider-terminal-evaluator-v1","result":verdict,"input_manifest_raw_sha256":manifest_raw_sha256,"input_bindings":manifest,"sample_count":sample_count,"exact_correct":exact_correct,"execution_correct":execution_correct,"exact_match":exact_correct/sample_count,"execution_match":execution_correct/sample_count,"row_class_counts":dict(sorted(class_counts.items())),"ordered_row_result_set_sha256":sha256_bytes(canonical(rows_)),"scorer_stdout_raw_sha256":sha256_bytes(stdout_raw),"scorer_stderr_raw_sha256":sha256_bytes(stderr_raw),"resource_receipt_raw_sha256":resource_receipt_raw_sha256,"cleanup_verified":True,"rows":rows_,"claim_boundary":claim})

def write_new(path: Path, value: dict) -> None:
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open("xb") as handle: handle.write(canonical(value))

def main(argv: list[str] | None=None) -> int:
 p=argparse.ArgumentParser()
 for name in ("manifest","examples","gold","tables","database-tree-manifest","database-root","prediction-envelope","inference-receipt","admission-receipt","catalog-fragment","license-sidecar","exact-scorer-root","execution-scorer-root","nltk-data-root","sqlparse-root","resource-receipt-output","score-output"): p.add_argument(f"--{name}",required=True,type=Path)
 a=p.parse_args(argv)
 try:
  if a.score_output.exists() or a.resource_receipt_output.exists(): raise ValueError("output paths must not pre-exist")
  manifest_raw=read_file_bytes(a.manifest,"input manifest");manifest=parse_manifest(manifest_raw)
  verify_ember_import_bytes(Path(__file__).resolve().parents[1],manifest["ember_source_commit"])
  examples_raw=read_bound_bytes(a.examples,manifest["examples_raw_sha256"],"examples")
  gold_raw=read_bound_bytes(a.gold,manifest["gold_raw_sha256"],"gold")
  read_bound_bytes(a.tables,manifest["tables_raw_sha256"],"tables")
  try: examples=json.loads(examples_raw)
  except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise ValueError("examples are unreadable") from exc
  frozen_rows=build_frozen_rows(examples,load_gold(gold_raw))
  if ordered_row_set_sha256(frozen_rows)!=manifest["ordered_row_set_sha256"]: raise ValueError("ordered row set identity mismatch")
  databases=verify_database_tree(a.database_tree_manifest,a.database_root,manifest["database_tree_manifest_sha256"])
  prediction_raw=read_bound_bytes(a.prediction_envelope,manifest["prediction_envelope_raw_sha256"],"prediction envelope")
  inference_raw=read_bound_bytes(a.inference_receipt,manifest["inference_receipt_raw_sha256"],"inference receipt")
  validate_inference_receipt(inference_raw,manifest)
  predictions=validate_prediction_envelope(json.loads(prediction_raw),frozen_rows,manifest["inference_receipt_raw_sha256"])
  def maybe_bytes(path: Path, label: str) -> bytes:
   try: return read_file_bytes(path,label)
   except (OSError,ValueError): return b""
  admission_valid=validate_1581_admission_binding(maybe_bytes(a.admission_receipt,"admission receipt"),maybe_bytes(a.catalog_fragment,"catalog fragment"),maybe_bytes(a.license_sidecar,"license sidecar"),manifest)
  if not admission_valid:
   results=admission_missing_results(frozen_rows,predictions)
   resource=build_resource_receipt(results,manifest["per_row_timeout_seconds"]);resource_raw=canonical(resource)
   terminal=build_terminal_receipt(manifest,sha256_bytes(manifest_raw),results,sha256_bytes(resource_raw))
   write_new(a.resource_receipt_output,resource);write_new(a.score_output,terminal)
   return 0
  verify_scorer_sources(a.exact_scorer_root,a.execution_scorer_root,manifest)
  verify_punkt_tab_tree(a.nltk_data_root,manifest["punkt_tab_tree_manifest_sha256"],manifest["nltk_version"])
  sqlparse_pyroot=verify_sqlparse_tree(a.sqlparse_root,manifest["sqlparse_tree_manifest_sha256"],manifest["sqlparse_version"])
  results=[]
  for row,prediction in zip(frozen_rows,predictions):
   database=databases.get(row["db_id"])
   if database is None:
    results.append({"row_id":row["row_id"],"db_id":row["db_id"],"prediction_sha256":sha256_bytes(prediction.encode()),"gold_sha256":sha256_bytes(row["gold_sql"].encode()),"exact_correct":False,"execution_correct":False,"execution_class":"MISSING_DATABASE","duration_ms":0,"_owned_cleanup_verified":True,"_scorer_stdout":"","_scorer_stderr":""})
   else: results.append(score_row(a.exact_scorer_root,a.execution_scorer_root,a.tables,database,row,prediction,manifest["per_row_timeout_seconds"],a.nltk_data_root,sqlparse_pyroot))
  resource=build_resource_receipt(results,manifest["per_row_timeout_seconds"]);resource_raw=canonical(resource)
  terminal=build_terminal_receipt(manifest,sha256_bytes(manifest_raw),results,sha256_bytes(resource_raw))
  write_new(a.resource_receipt_output,resource);write_new(a.score_output,terminal)
 except (OSError,ValueError,RuntimeError,json.JSONDecodeError,subprocess.SubprocessError) as exc:
  p.error(str(exc))
 return 0

if __name__=="__main__":
 if len(sys.argv)==2 and sys.argv[1]=="--owned-import-set": raise SystemExit(_owned_import_set_cli())
 if len(sys.argv)==3 and sys.argv[1]=="--owned-row-worker": raise SystemExit(_owned_row_worker_cli(Path(sys.argv[2])))
 raise SystemExit(main())
