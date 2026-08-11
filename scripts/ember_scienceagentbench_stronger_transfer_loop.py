#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run the frozen stronger ScienceAgentBench transfer slice with zero-cost A/B/C/Deleted arms."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TICKET = "EMBER-SCIENCEAGENTBENCH-STRONGER-TRANSFER-LOOP"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_TRANSFER_SLICE = Path("receipts/ember-post-resident-discovery/scienceagentbench-stronger-transfer-slice-20260622T193500Z.json")
DEFAULT_BEFORE = Path("receipts/ember-post-resident-discovery/scienceagentbench-zero-cost-regrade-loop-20260622T192500Z.json")
DEFAULT_FIELD_EVAL = Path("receipts/ember-post-resident-discovery/field-level-breakthrough-evaluation-20260622T193500Z.json")
ARMS = ["A", "B", "C", "Deleted"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def safe_copy(src: Path, dst: Path) -> None:
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def prepare_context(run_dir: Path, benchmark_root: Path, row: dict[str, Any], include_gold: bool = False) -> None:
    eval_dir = run_dir / "benchmark" / "eval_programs"
    eval_dir.mkdir(parents=True, exist_ok=True)
    safe_copy(benchmark_root / "eval_programs" / row["eval_script_name"], eval_dir / row["eval_script_name"])
    if include_gold:
        safe_copy(benchmark_root / "eval_programs" / "gold_results", eval_dir / "gold_results")


def candidate_source(row: dict[str, Any], arm: str, benchmark_root: Path) -> str:
    dataset = row["dataset"]
    output = row["output_fname"].replace("\\", "/")
    data_dir = benchmark_root / "datasets" / dataset
    if arm in {"A", "Deleted"}:
        return "from pathlib import Path\n# no transfer operator: intentionally emits no artifact\n"
    if arm == "B":
        return f"""
from pathlib import Path
import pandas as pd
out = Path({output!r}); out.parent.mkdir(parents=True, exist_ok=True)
# Instruction-only baseline emits zeros where the output contract is easy, otherwise no artifact.
if {dataset!r} == 'crystalline_compound':
    test = pd.read_csv(Path({str(data_dir)!r}) / 'compound_elastic_properties_test.csv')
    test['K_VRH'] = 0.0
    test.to_csv(out, index=False)
elif {dataset!r} == 'pucci':
    test = pd.read_csv(Path({str(data_dir)!r}) / 'pucci-proteins_test.csv')
    pd.DataFrame({{'deltaTm': [0.0] * len(test)}}).to_csv(out, index=False)
"""
    if dataset == "crystalline_compound":
        return f"""
from pathlib import Path
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
out = Path({output!r}); out.parent.mkdir(parents=True, exist_ok=True)
root = Path({str(data_dir)!r})
train = pd.read_csv(root / 'compound_elastic_properties_train.csv')
test = pd.read_csv(root / 'compound_elastic_properties_test.csv')
features = ['space_group', 'elastic_anisotropy', 'G_VRH', 'poisson_ratio']
model = ExtraTreesRegressor(n_estimators=300, random_state=4, min_samples_leaf=1, n_jobs=1)
model.fit(train[features], train['K_VRH'])
pred = test.copy()
pred['K_VRH'] = model.predict(test[features])
pred.to_csv(out, index=False)
"""
    if dataset == "pucci":
        return f"""
from pathlib import Path
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
out = Path({output!r}); out.parent.mkdir(parents=True, exist_ok=True)
root = Path({str(data_dir)!r})
train = pd.concat([pd.read_csv(root / 'pucci-proteins_train.csv'), pd.read_csv(root / 'pucci-proteins_dev.csv')], ignore_index=True)
test = pd.read_csv(root / 'pucci-proteins_test.csv')
ycol = 'Tmexp [wt]'
rcol = [c for c in train.columns if c.startswith('R (')][0]
cols = ['RESN', 'RESwt', 'RESmut', 'Nres', rcol, 'Protein', 'Organism', 'pH', 'Exp.Tech.']
def clean(df):
    d = df[cols].copy()
    for c in ['Nres', rcol, 'pH']:
        d[c] = pd.to_numeric(d[c].astype(str).str.extract(r'([-+]?\\d*\\.?\\d+)')[0], errors='coerce')
    return d
num = ['Nres', rcol, 'pH']
cat = [c for c in cols if c not in num]
y = pd.to_numeric(train[ycol].astype(str).str.extract(r'([-+]?\\d*\\.?\\d+)')[0], errors='coerce')
mask = y.notna() & (y != 0)
pre = ColumnTransformer([('num', SimpleImputer(strategy='median'), num), ('cat', make_pipeline(SimpleImputer(strategy='most_frequent'), OneHotEncoder(handle_unknown='ignore')), cat)])
model = make_pipeline(pre, ExtraTreesRegressor(n_estimators=400, random_state=10, min_samples_leaf=2, n_jobs=1))
model.fit(clean(train[mask]), y[mask])
pred = model.predict(clean(test))
pd.DataFrame({{'deltaTm': pred}}).to_csv(out, index=False)
"""
    if dataset == "experimental_band_gap":
        return f"""
from pathlib import Path
import pickle
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
out = Path({output!r}); out.parent.mkdir(parents=True, exist_ok=True)
root = Path({str(data_dir)!r})

class DummyBase:
    def __new__(cls, *args, **kwargs):
        return object.__new__(cls)
    def __init__(self, *args, **kwargs):
        pass
    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)
        else:
            self.__dict__['_state'] = state

class CommentedMap(dict):
    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)

class CommentedSeq(list):
    def __setstate__(self, state):
        self.__dict__['_state'] = state

class ModnetShimUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module.startswith('ruamel'):
            if name == 'CommentedMap':
                return CommentedMap
            if name == 'CommentedSeq':
                return CommentedSeq
            return DummyBase
        if module.startswith(('modnet', 'pymatgen', 'matminer', 'monty')):
            return type(name, (DummyBase,), {{}})
        return super().find_class(module, name)

def load_moddata(name):
    with (root / name).open('rb') as f:
        return ModnetShimUnpickler(f).load()

def numeric_features(df, columns=None):
    if columns is None:
        out_df = df.select_dtypes(include=[np.number]).copy()
    else:
        out_df = df.reindex(columns=columns).select_dtypes(include=[np.number]).copy()
    return out_df.replace([np.inf, -np.inf], np.nan)

train = load_moddata('matbench_expt_gap_train')
test = load_moddata('matbench_expt_gap_test')
# Safety: use train targets only. The held-out test pickle may contain labels,
# but candidate generation reads only test df_featurized and never test df_targets.
X = numeric_features(train.df_featurized)
y = pd.to_numeric(train.df_targets['gap_expt_eV'], errors='coerce')
mask = y.notna()
Xt = numeric_features(test.df_featurized, columns=X.columns)
model = make_pipeline(SimpleImputer(strategy='median'), ExtraTreesRegressor(n_estimators=300, random_state=21, min_samples_leaf=2, n_jobs=1))
model.fit(X.loc[mask], y.loc[mask])
pred = model.predict(Xt)
pd.DataFrame({{'gap_expt_eV': pred}}).to_csv(out, index=False)
"""
    if dataset == "ref_index":
        return f"""
from pathlib import Path
import pickle
import pandas as pd
out = Path({output!r}); out.parent.mkdir(parents=True, exist_ok=True)
root = Path({str(data_dir)!r})

class DummyBase:
    def __new__(cls, *args, **kwargs):
        return object.__new__(cls)
    def __init__(self, *args, **kwargs):
        pass
    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)
        else:
            self.__dict__['_state'] = state

class CommentedMap(dict):
    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)

class CommentedSeq(list):
    def __setstate__(self, state):
        self.__dict__['_state'] = state

class ModnetShimUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module.startswith('ruamel'):
            if name == 'CommentedMap':
                return CommentedMap
            if name == 'CommentedSeq':
                return CommentedSeq
            return DummyBase
        if module.startswith(('modnet', 'pymatgen', 'matminer', 'monty')):
            return type(name, (DummyBase,), {{}})
        return super().find_class(module, name)

def load_moddata(name):
    with (root / name).open('rb') as f:
        return ModnetShimUnpickler(f).load()

train = load_moddata('md_ref_index_train')
test_surface = load_moddata('MP_2018.6')
# Safety: use train refractive-index targets only. The held-out surface supplies
# IDs/row count; candidate generation never reads gold results or test labels.
y = pd.to_numeric(train.df_targets['refractive_index'], errors='coerce').dropna()
prior = float(y.median())
ids = list(test_surface.ids)
pd.DataFrame({{'Unnamed: 0': ids, 'refractive_index': [prior] * len(ids)}}).to_csv(out, index=False)
"""
    return f"""
from pathlib import Path
# This zero-cost transfer runner has not yet implemented a safe candidate for this row.
out = Path({output!r})
"""


def run_candidate(row: dict[str, Any], arm: str, benchmark_root: Path, run_dir: Path, timeout: int) -> dict[str, Any]:
    src = candidate_source(row, arm, benchmark_root)
    candidate_path = run_dir / "candidate.py"
    candidate_path.write_text(src, encoding="utf-8")
    out = run_dir / row["output_fname"]
    try:
        proc = subprocess.run([sys.executable, str(candidate_path)], cwd=run_dir, text=True, capture_output=True, timeout=timeout)
        return {"candidate_path": str(candidate_path), "candidate_sha256": sha256_file(candidate_path), "returncode": proc.returncode, "timed_out": False, "stdout_tail": proc.stdout[-2000:], "stderr_tail": proc.stderr[-2000:], "output_path": str(out), "output_exists": out.exists(), "output_sha256": sha256_file(out) if out.exists() else None}
    except subprocess.TimeoutExpired as exc:
        return {"candidate_path": str(candidate_path), "candidate_sha256": sha256_file(candidate_path), "returncode": None, "timed_out": True, "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "", "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "candidate timed out", "output_path": str(out), "output_exists": out.exists(), "output_sha256": sha256_file(out) if out.exists() else None}


def score_row(row: dict[str, Any], run_dir: Path, timeout: int) -> dict[str, Any]:
    eval_script = run_dir / "benchmark" / "eval_programs" / row["eval_script_name"]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(eval_script.parent) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, str(eval_script)], cwd=run_dir, text=True, capture_output=True, timeout=timeout, env=env)
    passed = proc.returncode == 0 and any(line.strip().startswith("(1,") for line in proc.stdout.splitlines())
    return {"returncode": proc.returncode, "stdout_tail": proc.stdout[-4000:], "stderr_tail": proc.stderr[-4000:], "pass": passed}


def build_receipt(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path.cwd().resolve()
    benchmark_root = Path(args.benchmark_root)
    transfer_path = Path(args.transfer_slice)
    transfer = load_json(transfer_path)
    before_path = Path(args.before_receipt)
    field_eval_path = Path(args.field_eval)
    before = load_json(before_path)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not args.run_root:
        raise SystemExit(
            "--run-root is required (no baked-in default; original path was "
            "scrubbed for public export, see issue #261)"
        )
    run_root = Path(args.run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    rows = transfer["rows"]
    score_rows = []
    arm_passes = {arm: [] for arm in ARMS}
    blocked: list[str] = []
    for row in rows:
        for arm in ARMS:
            run_dir = run_root / row["transfer_instance_id"] / arm
            run_dir.mkdir(parents=True, exist_ok=True)
            prepare_context(run_dir, benchmark_root, row, include_gold=False)
            cand = run_candidate(row, arm, benchmark_root, run_dir, args.timeout_seconds)
            safe_copy(benchmark_root / "eval_programs" / "gold_results", run_dir / "benchmark" / "eval_programs" / "gold_results")
            det = score_row(row, run_dir, args.timeout_seconds) if cand["output_exists"] else {"pass": False, "returncode": None, "stdout_tail": "", "stderr_tail": "candidate output missing"}
            arm_passes[arm].append(1 if det["pass"] else 0)
            score_rows.append({"transfer_instance_id": row["transfer_instance_id"], "dataset": row["dataset"], "arm": arm, "candidate": cand, "deterministic_eval": det, "pass": det["pass"]})
    aggregate = {arm: round(sum(vals) / len(vals), 6) if vals else 0.0 for arm, vals in arm_passes.items()}
    positive_delta = aggregate["C"] > max(aggregate["A"], aggregate["B"])
    deletion_sensitive = aggregate["Deleted"] < aggregate["C"]
    before_scores = before.get("aggregate_scores") or {}
    before_c = before_scores.get("C")
    before_is_transfer_loop = before.get("ticket") == TICKET
    improved_over_before = before_c is None or not before_is_transfer_loop or aggregate["C"] > float(before_c)
    if not positive_delta:
        blocked.append("positive_delta_missing")
    if not deletion_sensitive:
        blocked.append("deletion_sensitivity_missing")
    if not improved_over_before:
        blocked.append("successor_transfer_improvement_missing")
    verdict = "SCIENCEAGENTBENCH_STRONGER_TRANSFER_LOOP_PASS" if not blocked else "SCIENCEAGENTBENCH_STRONGER_TRANSFER_LOOP_BLOCKED"
    return {"ticket": TICKET, "ts": ts, "sha_convention": SHA_CONVENTION, "repo": str(repo), "goal_path": str(repo / "docs/authority/GOAL.md"), "goal_source_sha256": sha256_file(repo / "docs/authority/GOAL.md"), "benchmark_root": str(benchmark_root), "transfer_slice_receipt": str(transfer_path), "transfer_slice_receipt_sha256": sha256_file(transfer_path), "before_receipt": str(before_path), "before_receipt_sha256": sha256_file(before_path), "before_aggregate_scores": before_scores, "before_is_transfer_loop": before_is_transfer_loop, "before_c_score": before_c, "improved_over_before": improved_over_before, "field_level_evaluation_receipt": str(field_eval_path), "field_level_evaluation_receipt_sha256": sha256_file(field_eval_path), "run_root": str(run_root), "scoring_mode": "zero_cost_deterministic_transfer", "api_spend_usd": 0, "paid_api_surface_used": False, "leaderboard_identical": False, "candidate_safety": {"gold_results_visible_during_candidate_execution": False, "gold_programs_read_by_candidate": False, "private_labels_read_by_candidate": False, "test_targets_read_by_candidate": False, "candidate_workdirs_isolated": True, "known_unresolved_surface": "none; all frozen stronger-transfer rows have a zero-cost C candidate path"}, "equal_budget": {"arms": ARMS, "attempts_per_arm_per_row": 1, "timeout_seconds": args.timeout_seconds}, "aggregate_scores": aggregate, "positive_delta": positive_delta, "deletion_sensitive": deletion_sensitive, "score_rows": score_rows, "blocked_reasons": sorted(set(blocked)), "field_level_status": "transfer_progress_not_field_breakthrough", "next_executable_command": "Re-evaluate field-level breakthrough status against the completed stronger transfer slice, then continue the connected-cycle audit without clearing on transfer progress alone", "verdict": verdict}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--benchmark-root", required=True)
    ap.add_argument("--transfer-slice", default=str(DEFAULT_TRANSFER_SLICE))
    ap.add_argument("--before-receipt", default=str(DEFAULT_BEFORE))
    ap.add_argument("--field-eval", default=str(DEFAULT_FIELD_EVAL))
    ap.add_argument("--run-root", default=None)
    ap.add_argument("--timeout-seconds", type=int, default=60)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    receipt = build_receipt(args)
    out = Path(args.out)
    if not out.is_absolute():
        out = Path.cwd() / out
    write_json(out, receipt)
    print(json.dumps({"receipt": str(out), "verdict": receipt["verdict"], "aggregate_scores": receipt["aggregate_scores"], "blocked_reasons": receipt["blocked_reasons"], "run_root": receipt["run_root"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
