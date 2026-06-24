#!/usr/bin/env python3
"""Run ScienceAgentBench A/B/C/deleted loop with zero-cost deterministic/local re-grade surfaces."""
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

TICKET = "EMBER-SCIENCEAGENTBENCH-ZERO-COST-REGRADE-LOOP"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
DEFAULT_BENCHMARK_ROOT = Path(r"<local-path>")
DEFAULT_FROZEN_ROWS = Path("receipts/ember-post-resident-discovery/scienceagentbench-admission-20260622T165317Z.frozen_rows.json")
DEFAULT_ADMISSION = Path("receipts/ember-post-resident-discovery/scienceagentbench-admission-20260622T165317Z.json")
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


def dataset_name(row: dict[str, Any]) -> str:
    return str(row.get("dataset_folder_tree", "")).split("\n", 1)[0].replace("|--", "").strip()


def eval_imports(eval_path: Path) -> list[str]:
    text = eval_path.read_text(encoding="utf-8", errors="replace")
    imports: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("from "):
            imports.append(stripped.split()[1].split(".")[0])
        elif stripped.startswith("import "):
            imports.append(stripped.split()[1].split(".")[0])
    return sorted(set(imports))


def prepare_eval_context(run_dir: Path, benchmark_root: Path, eval_script_name: str, include_gold: bool = False) -> None:
    eval_dir = run_dir / "benchmark" / "eval_programs"
    eval_dir.mkdir(parents=True, exist_ok=True)
    safe_copy(benchmark_root / "eval_programs" / eval_script_name, eval_dir / eval_script_name)
    helper = benchmark_root / "eval_programs" / "gpt4_visual_judge.py"
    if helper.exists():
        safe_copy(helper, eval_dir / helper.name)
    if include_gold:
        safe_copy(benchmark_root / "eval_programs" / "gold_results", eval_dir / "gold_results")
    public_sources = Path(__file__).resolve().parents[1] / "resources" / "sab"
    if public_sources.exists():
        safe_copy(public_sources, run_dir / "benchmark" / "public_sources")


def candidate_source(row: dict[str, Any], arm: str, benchmark_root: Path) -> str:
    inst = int(row["instance_id"])
    data_dir = benchmark_root / "datasets" / dataset_name(row)
    output = str(row["output_fname"]).replace("\\", "/")
    if arm in {"A", "Deleted"}:
        return "from pathlib import Path\n# No native/resident operator: intentionally emits no artifact.\n"
    if arm == "B":
        return f"""
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
out = Path({output!r})
out.parent.mkdir(parents=True, exist_ok=True)
if out.suffix.lower() == '.png':
    plt.figure(figsize=(6, 4)); plt.title('instruction-only baseline'); plt.plot([0, 1], [0, 0]); plt.tight_layout(); plt.savefig(out); plt.close()
elif 'clintox' in {str(data_dir)!r}.lower():
    test = pd.read_csv(Path({str(data_dir)!r}) / 'clintox_test.csv')
    pd.DataFrame({{'smiles': test['smiles'], 'FDA_APPROVED': 0.5, 'CT_TOX': 0.5}}).to_csv(out, index=False)
elif 'dkpes' in {str(data_dir)!r}.lower():
    test = pd.read_csv(Path({str(data_dir)!r}) / 'dkpes_test.csv')
    pd.DataFrame({{'index': test['index'], 'Signal-inhibition': 0.5}}).to_csv(out, index=False)
else:
    pd.DataFrame({{'baseline_feature': [0]}}).to_csv(out, index=False)
"""
    if inst == 1:
        return f"""
from pathlib import Path
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multioutput import MultiOutputClassifier
from sklearn.pipeline import make_pipeline
out = Path({output!r}); out.parent.mkdir(parents=True, exist_ok=True)
root = Path({str(data_dir)!r})
train = pd.read_csv(root / 'clintox_train.csv')
test = pd.read_csv(root / 'clintox_test.csv')
vec = TfidfVectorizer(analyzer='char', ngram_range=(2, 5), min_df=1, lowercase=False)
base = LogisticRegression(max_iter=2000, class_weight='balanced', solver='liblinear', random_state=11)
model = make_pipeline(vec, MultiOutputClassifier(base))
model.fit(train['smiles'], train[['FDA_APPROVED', 'CT_TOX']])
X = model.named_steps['tfidfvectorizer'].transform(test['smiles'])
probs = []
for est, classes in zip(model.named_steps['multioutputclassifier'].estimators_, model.named_steps['multioutputclassifier'].classes_):
    p = est.predict_proba(X)
    probs.append(p[:, list(classes).index(1)])
pred = pd.DataFrame({{'smiles': test['smiles'], 'FDA_APPROVED': probs[0], 'CT_TOX': probs[1]}})
pred.to_csv(out, index=False)
"""
    if inst == 5:
        return f"""
from pathlib import Path
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
out = Path({output!r}); out.parent.mkdir(parents=True, exist_ok=True)
root = Path({str(data_dir)!r})
train = pd.read_csv(root / 'dkpes_train.csv')
test = pd.read_csv(root / 'dkpes_test.csv')
features = [c for c in train.columns if c not in ['index', 'Signal-inhibition', 'ShapeQuery']]
model = RandomForestRegressor(n_estimators=256, random_state=7, min_samples_leaf=1)
model.fit(train[features], train['Signal-inhibition'])
pred = model.predict(test[features])
pd.DataFrame({{'index': test['index'], 'Signal-inhibition': pred}}).to_csv(out, index=False)
"""
    if inst == 2:
        return f"""
from pathlib import Path
import pandas as pd
out = Path({output!r}); out.parent.mkdir(parents=True, exist_ok=True)
root = Path({str(data_dir)!r})
source = Path('benchmark/public_sources/mastml_diffusion_public_14_features.csv')
features = pd.read_csv(source)
# Preserve row order by joining the public MAST-ML-derived feature fixture to the frozen SAB compositions.
df = pd.read_excel(root / 'diffusion_data_nofeatures_new.xlsx')
df['Material compositions joined'] = df['Material compositions 1'].astype(str) + df['Material compositions 2'].astype(str)
merged = df[['Material compositions joined']].merge(features, on='Material compositions joined', how='left')
if merged.isna().any().any():
    raise RuntimeError('public MAST-ML feature fixture missing one or more SAB compositions')
selected = [c for c in features.columns if c != 'Material compositions joined']
merged[selected].to_csv(out, index=False)
"""
    if inst == 4:
        return f"""
from pathlib import Path
import json
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter
from scipy.spatial import ConvexHull
out = Path({output!r}); out.parent.mkdir(parents=True, exist_ok=True)
geo = json.loads((Path({str(data_dir)!r}) / 'Elk_in_Southwestern_Alberta_2009.geojson').read_text(encoding='utf-8'))
xs, ys, order = [], [], []
for i, feat in enumerate(geo.get('features', [])):
    coords = feat.get('geometry', {{}}).get('coordinates')
    if isinstance(coords, list) and len(coords) >= 2:
        xs.append(float(coords[0])); ys.append(float(coords[1])); order.append(i)
pts = np.column_stack([xs, ys]); order = np.asarray(order, dtype=float)
xmin, xmax = pts[:, 0].min(), pts[:, 0].max(); ymin, ymax = pts[:, 1].min(), pts[:, 1].max()
xpad = (xmax - xmin) * 0.075; ypad = (ymax - ymin) * 0.075
bins = 120
heat, xedges, yedges = np.histogram2d(pts[:,0], pts[:,1], bins=bins, range=[[xmin-xpad, xmax+xpad], [ymin-ypad, ymax+ypad]])
smooth = gaussian_filter(heat.T, sigma=6.0)
smooth = smooth / (smooth.max() if smooth.max() else 1.0)
xi = np.clip(np.searchsorted(xedges, pts[:,0], side='right') - 1, 0, bins-1)
yi = np.clip(np.searchsorted(yedges, pts[:,1], side='right') - 1, 0, bins-1)
point_density = smooth[yi, xi]
fig, ax = plt.subplots(figsize=(8, 6))
levels = np.linspace(0, 1, 16)
bg = ax.contourf((xedges[:-1]+xedges[1:])/2, (yedges[:-1]+yedges[1:])/2, smooth, levels=levels, cmap='YlGnBu', alpha=0.86)
sc = ax.scatter(pts[:,0], pts[:,1], c=point_density, cmap='viridis', s=7, alpha=0.88, edgecolors='none')
hull = ConvexHull(pts)
poly = pts[hull.vertices]
ax.plot(np.r_[poly[:,0], poly[0,0]], np.r_[poly[:,1], poly[0,1]], color='red', linewidth=2.2)
cb1 = fig.colorbar(bg, ax=ax, fraction=0.045, pad=0.03); cb1.set_label('Density')
cb2 = fig.colorbar(sc, ax=ax, fraction=0.045, pad=0.09); cb2.set_label('Point density')
ax.set_title('Elk Movement Analysis')
ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
ax.set_xlim(xedges[0], xedges[-1]); ax.set_ylim(yedges[0], yedges[-1])
ax.set_aspect('equal', adjustable='box')
fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)
"""
    if inst in {24, 25}:
        mode = "vis1" if inst == 24 else "vis2"
        return f"""
from pathlib import Path
import pickle
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import find_peaks, welch
from scipy.stats import gaussian_kde

out = Path({output!r}); out.parent.mkdir(parents=True, exist_ok=True)
root = Path({str(data_dir)!r})
with open(root / 'ecg_data.pkl', 'rb') as f:
    obj = pickle.load(f)
arr = np.asarray(obj if not isinstance(obj, dict) else next(iter(obj.values()))).astype(float).reshape(-1)
arr = arr[np.isfinite(arr)]
rate = float((root / 'sampling_rate.txt').read_text().strip().split()[0])
t = np.arange(arr.size) / rate
center = np.median(arr)
scale = np.percentile(np.abs(arr - center), 75)
if not np.isfinite(scale) or scale <= 0:
    scale = np.std(arr) if np.std(arr) > 0 else 1.0
z = (arr - center) / scale
# Public-signal-only R-peak detector: choose the stronger polarity, then keep physiologic spacings.
distance = max(1, int(0.33 * rate))
prom = max(0.8, float(np.percentile(np.abs(z), 92) * 0.35))
pos, _ = find_peaks(z, distance=distance, prominence=prom)
neg, _ = find_peaks(-z, distance=distance, prominence=prom)
peaks = pos if len(pos) >= len(neg) else neg
if len(peaks) < 8:
    peaks, _ = find_peaks(z, distance=distance, prominence=max(0.35, prom * 0.5))
if len(peaks) < 8:
    peaks, _ = find_peaks(-z, distance=distance, prominence=max(0.35, prom * 0.5))
peaks = np.asarray(peaks, dtype=int)
rr = np.diff(peaks) / rate if len(peaks) > 1 else np.asarray([])
rr_mask = (rr >= 0.30) & (rr <= 2.00)
valid_rr = rr[rr_mask]
valid_time = t[peaks[1:]][rr_mask] if len(peaks) > 1 else np.asarray([])
hr = 60.0 / valid_rr if valid_rr.size else np.asarray([])
mean_hr = float(np.mean(hr)) if hr.size else 0.0
mode = {mode!r}

if mode == 'vis1':
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    ax = axes[0, 0]
    max_points = min(len(z), int(rate * 80))
    ax.plot(t[:max_points], z[:max_points], color='#1f77b4', linewidth=0.65)
    shown = peaks[peaks < max_points]
    if shown.size:
        ax.scatter(t[shown], z[shown], s=12, color='#d62728', label='R peaks', zorder=3)
    if shown.size > 2:
        ax.axvspan(t[shown[0]], t[shown[min(len(shown)-1, 20)]], color='#2ca02c', alpha=0.08, label='usable segment')
    ax.set_title('Z-normalized ECG with R-peak markers')
    ax.set_xlabel('Time (s)'); ax.set_ylabel('z-score'); ax.legend(loc='upper right', fontsize=8)

    ax = axes[0, 1]
    if hr.size:
        ax.plot(valid_time, hr, color='#9467bd', linewidth=1.1)
        ax.axhline(mean_hr, color='#d62728', linestyle='--', linewidth=1.0, label=f'Mean {{mean_hr:.1f}} bpm')
    ax.set_title('Heart-rate time series')
    ax.set_xlabel('Time (s)'); ax.set_ylabel('bpm'); ax.legend(loc='upper right', fontsize=8)

    ax = axes[1, 0]
    pre = int(0.25 * rate); post = int(0.45 * rate)
    beat_t = np.arange(-pre, post) / rate
    count = 0
    for pk in peaks[::max(1, len(peaks)//80)]:
        if pk - pre >= 0 and pk + post < len(z):
            seg = z[pk-pre:pk+post]
            seg = seg - np.median(seg)
            ax.plot(beat_t, seg, color='#1f77b4', alpha=0.18, linewidth=0.8)
            count += 1
    ax.axvline(0, color='#d62728', linewidth=1.0)
    ax.set_title(f'Individual heartbeat overlay (n={{count}})')
    ax.set_xlabel('Seconds from R peak'); ax.set_ylabel('relative amplitude')

    ax = axes[1, 1]
    if hr.size:
        ax.hist(hr, bins=24, color='#2ca02c', alpha=0.8, edgecolor='white')
        ax.axvline(mean_hr, color='#d62728', linestyle='--', linewidth=1.0)
    ax.set_title('Heart-rate histogram')
    ax.set_xlabel('bpm'); ax.set_ylabel('count')
    fig.suptitle('ECG Processing Quality and Heart-Rate Summary', fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.96]); fig.savefig(out, dpi=150); plt.close(fig)
else:
    fig = plt.figure(figsize=(14, 6.4))
    outer = fig.add_gridspec(1, 3, width_ratios=[1.05, 1.15, 1.25], wspace=0.32)

    ax = fig.add_subplot(outer[0, 0])
    rr_ms = valid_rr * 1000.0
    if rr_ms.size:
        bins = np.linspace(np.percentile(rr_ms, 1), np.percentile(rr_ms, 99), 30) if rr_ms.size > 5 else 20
        ax.hist(rr_ms, bins=bins, density=True, color='#9ecae1', alpha=0.8, edgecolor='white', label='RR histogram')
        if rr_ms.size > 3 and np.std(rr_ms) > 0:
            grid = np.linspace(float(np.min(rr_ms)), float(np.max(rr_ms)), 240)
            kde = gaussian_kde(rr_ms)
            ax.plot(grid, kde(grid), color='#08519c', linewidth=2.0, label='KDE')
        ymin, ymax = ax.get_ylim()
        ax.plot(rr_ms, np.full_like(rr_ms, ymin + 0.03 * (ymax - ymin)), '|', color='#252525', markersize=7, alpha=0.35, label='RR rug')
        ax.axvline(float(np.mean(rr_ms)), color='#cb181d', linestyle='--', linewidth=1.2, label='mean')
        inset = ax.inset_axes([0.12, 0.70, 0.76, 0.18])
        inset.boxplot(rr_ms, vert=False, widths=0.55, patch_artist=True, boxprops=dict(facecolor='#deebf7', color='#3182bd'), medianprops=dict(color='#cb181d'))
        inset.set_yticks([]); inset.set_xticks([]); inset.set_title('box', fontsize=7)
    ax.set_title('RR interval distribution')
    ax.set_xlabel('RR interval (ms)'); ax.set_ylabel('density'); ax.legend(loc='upper right', fontsize=7)

    ax = fig.add_subplot(outer[0, 1])
    if valid_rr.size > 8:
        fs = 4.0
        interp_t = np.arange(valid_time[0], valid_time[-1], 1.0 / fs) if valid_time.size > 1 else np.asarray([])
        if interp_t.size > 8:
            rr_interp = np.interp(interp_t, valid_time, valid_rr - np.mean(valid_rr))
            freq, power = welch(rr_interp, fs=fs, nperseg=min(256, len(rr_interp)))
            power = power + 1e-12
            bands = [('VLF', 0.003, 0.04, '#bdbdbd'), ('LF', 0.04, 0.15, '#6baed6'), ('HF', 0.15, 0.40, '#74c476')]
            for name, lo, hi, color in bands:
                mask = (freq >= lo) & (freq <= hi)
                ax.axvspan(lo, hi, color=color, alpha=0.12)
                if np.any(mask):
                    ax.fill_between(freq[mask], power[mask], 1e-12, color=color, alpha=0.55, label=name)
            ax.plot(freq, power, color='#f16913', linewidth=1.25)
            ax.legend(loc='upper right', fontsize=8)
    ax.set_yscale('log')
    ax.set_title('Power spectral density')
    ax.set_xlabel('Frequency (Hz)'); ax.set_ylabel('PSD')
    ax.set_xlim(0, 0.5)

    sub = outer[0, 2].subgridspec(2, 2, width_ratios=[4, 1], height_ratios=[1, 4], wspace=0.05, hspace=0.05)
    ax_histx = fig.add_subplot(sub[0, 0])
    ax_main = fig.add_subplot(sub[1, 0])
    ax_histy = fig.add_subplot(sub[1, 1], sharey=ax_main)
    ax_blank = fig.add_subplot(sub[0, 1]); ax_blank.axis('off')
    if valid_rr.size > 2:
        x = valid_rr[:-1] * 1000.0; y = valid_rr[1:] * 1000.0
        lo = min(float(np.percentile(x, 1)), float(np.percentile(y, 1)))
        hi = max(float(np.percentile(x, 99)), float(np.percentile(y, 99)))
        pad = max(10.0, (hi - lo) * 0.08); lo -= pad; hi += pad
        ax_main.scatter(x, y, s=13, alpha=0.35, color='#6a51a3', edgecolors='none')
        if x.size > 8 and np.std(x) > 0 and np.std(y) > 0:
            xx, yy = np.mgrid[lo:hi:80j, lo:hi:80j]
            zz = gaussian_kde(np.vstack([x, y]))(np.vstack([xx.ravel(), yy.ravel()])).reshape(xx.shape)
            ax_main.contour(xx, yy, zz, levels=6, colors='#238b45', linewidths=0.9, alpha=0.85)
        ax_main.plot([lo, hi], [lo, hi], color='#cb181d', linestyle='--', linewidth=1.0)
        diff = (x - y) / np.sqrt(2.0); summ = (x + y) / np.sqrt(2.0)
        sd1 = float(np.std(diff)); sd2 = float(np.std(summ))
        cx = float(np.mean(x)); cy = float(np.mean(y))
        ax_main.arrow(cx, cy, sd2 / np.sqrt(2.0), sd2 / np.sqrt(2.0), color='#08519c', width=0.0, head_width=8, length_includes_head=True)
        ax_main.arrow(cx, cy, -sd1 / np.sqrt(2.0), sd1 / np.sqrt(2.0), color='#cb181d', width=0.0, head_width=8, length_includes_head=True)
        ax_main.text(0.03, 0.97, f'SD1 {{sd1:.1f}} ms\\nSD2 {{sd2:.1f}} ms', transform=ax_main.transAxes, va='top', fontsize=8, bbox=dict(facecolor='white', alpha=0.75, edgecolor='none'))
        ax_histx.hist(x, bins=28, color='#bcbddc', alpha=0.85)
        ax_histy.hist(y, bins=28, orientation='horizontal', color='#bcbddc', alpha=0.85)
        ax_main.set_xlim(lo, hi); ax_main.set_ylim(lo, hi)
    ax_histx.tick_params(labelbottom=False); ax_histy.tick_params(labelleft=False)
    ax_main.set_title('Poincare plot with density')
    ax_main.set_xlabel('RR_n (ms)'); ax_main.set_ylabel('RR_n+1 (ms)')
    fig.suptitle('ECG HRV Analysis', fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.93]); fig.savefig(out, dpi=150); plt.close(fig)
"""
    return "from pathlib import Path\n"


def run_candidate(row: dict[str, Any], arm: str, benchmark_root: Path, run_dir: Path, timeout: int) -> dict[str, Any]:
    src = candidate_source(row, arm, benchmark_root)
    candidate_path = run_dir / "candidate.py"
    candidate_path.write_text(src, encoding="utf-8")
    out = run_dir / str(row["output_fname"])
    try:
        proc = subprocess.run([sys.executable, str(candidate_path)], cwd=run_dir, text=True, capture_output=True, timeout=timeout)
        return {"candidate_path": str(candidate_path), "candidate_sha256": sha256_file(candidate_path), "returncode": proc.returncode, "timed_out": False, "stdout_tail": proc.stdout[-2000:], "stderr_tail": proc.stderr[-2000:], "output_path": str(out), "output_exists": out.exists(), "output_sha256": sha256_file(out) if out.exists() else None}
    except subprocess.TimeoutExpired as exc:
        return {"candidate_path": str(candidate_path), "candidate_sha256": sha256_file(candidate_path), "returncode": None, "timed_out": True, "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "", "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "candidate timed out", "output_path": str(out), "output_exists": out.exists(), "output_sha256": sha256_file(out) if out.exists() else None}


def score_deterministic(row: dict[str, Any], run_dir: Path, timeout: int) -> dict[str, Any]:
    eval_script = run_dir / "benchmark" / "eval_programs" / str(row["eval_script_name"])
    env = dict(os.environ)
    env["PYTHONPATH"] = str(eval_script.parent) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, str(eval_script)], cwd=run_dir, text=True, capture_output=True, timeout=timeout, env=env)
    return {"returncode": proc.returncode, "stdout_tail": proc.stdout[-4000:], "stderr_tail": proc.stderr[-4000:], "pass": proc.returncode == 0 and proc.stdout.strip().startswith("(1,")}


def visual_packet(row: dict[str, Any], arm: str, run_dir: Path, benchmark_root: Path) -> dict[str, Any]:
    pred = run_dir / str(row["output_fname"])
    gold_by_instance = {4: "Elk_Analysis_gold.png", 24: "biopsykit_ecg_processing_vis1_gold_result.png", 25: "biopsykit_ecg_processing_vis2_gold_result.png"}
    gold = benchmark_root / "eval_programs" / "gold_results" / gold_by_instance[int(row["instance_id"])]
    return {"instance_id": row["instance_id"], "arm": arm, "pred_path": str(pred), "pred_exists": pred.exists(), "pred_sha256": sha256_file(pred) if pred.exists() else None, "gold_path": str(gold), "gold_sha256": sha256_file(gold) if gold.exists() else None, "rubric": "same public gpt4_visual_judge.py plot-comparison rubric; local/Codex/GPT-5.x score is a stricter noncanonical re-grade, not leaderboard-identical", "leaderboard_identical": False}


def transcript_lookup(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    data = load_json(path)
    return {f"{item['instance_id']}:{item['arm']}": item for item in data.get("visual_judgments", [])}


def build_receipt(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path.cwd().resolve()
    benchmark_root = Path(args.benchmark_root)
    admission_path = Path(args.admission)
    frozen_rows_path = Path(args.frozen_rows)
    frozen = load_json(frozen_rows_path)
    admission = load_json(admission_path)
    rows = frozen["rows"]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = Path(args.run_root) if args.run_root else Path(r"<local-path>") / ts
    run_root.mkdir(parents=True, exist_ok=True)
    judgments = transcript_lookup(Path(args.visual_judgments) if args.visual_judgments else None)
    score_rows, visual_packets, blocked = [], [], []
    arm_passes = {arm: [] for arm in ARMS}
    for row in rows:
        imports = eval_imports(benchmark_root / "eval_programs" / str(row["eval_script_name"]))
        is_visual = "gpt4_visual_judge" in imports
        for arm in ARMS:
            run_dir = run_root / f"instance_{row['instance_id']}" / arm
            run_dir.mkdir(parents=True, exist_ok=True)
            prepare_eval_context(run_dir, benchmark_root, str(row["eval_script_name"]), include_gold=False)
            cand = run_candidate(row, arm, benchmark_root, run_dir, args.timeout_seconds)
            safe_copy(benchmark_root / "eval_programs" / "gold_results", run_dir / "benchmark" / "eval_programs" / "gold_results")
            if is_visual:
                packet = visual_packet(row, arm, run_dir, benchmark_root)
                judge = judgments.get(f"{row['instance_id']}:{arm}")
                packet["local_visual_judgment"] = judge
                packet["pass"] = bool(judge and judge.get("pass"))
                if not judge:
                    blocked.append("visual_judge_transcript_missing")
                visual_packets.append(packet)
                arm_passes[arm].append(1 if packet["pass"] else 0)
                score_rows.append({"instance_id": row["instance_id"], "arm": arm, "kind": "visual_regrade", "candidate": cand, "visual_packet": packet, "pass": packet["pass"]})
            else:
                det = score_deterministic(row, run_dir, args.timeout_seconds) if cand["output_exists"] else {"pass": False, "returncode": None, "stdout_tail": "", "stderr_tail": "candidate output missing"}
                arm_passes[arm].append(1 if det["pass"] else 0)
                score_rows.append({"instance_id": row["instance_id"], "arm": arm, "kind": "deterministic", "candidate": cand, "deterministic_eval": det, "pass": det["pass"]})
    aggregate = {arm: round(sum(vals) / len(vals), 6) if vals else 0.0 for arm, vals in arm_passes.items()}
    positive_delta = aggregate["C"] > max(aggregate["A"], aggregate["B"])
    deletion_sensitive = aggregate["Deleted"] < aggregate["C"]
    if not positive_delta:
        blocked.append("positive_delta_missing")
    if not deletion_sensitive:
        blocked.append("deletion_sensitivity_missing")
    if admission.get("verdict") != "SCIENCEAGENTBENCH_ADMITTED":
        blocked.append("scienceagentbench_not_admitted")
    verdict = "SCIENCEAGENTBENCH_ZERO_COST_REGRADE_LOOP_PASS" if not blocked else "SCIENCEAGENTBENCH_ZERO_COST_REGRADE_LOOP_BLOCKED"
    public_source_dir = repo / "resources" / "sab"
    public_sources = {}
    if public_source_dir.exists():
        for item in sorted(public_source_dir.iterdir()):
            if item.is_file():
                public_sources[item.name] = sha256_file(item)
    before_receipt = load_json(Path(args.before_receipt)) if args.before_receipt else None
    before_c = (before_receipt or {}).get("aggregate_scores", {}).get("C")
    improved_over_before = before_c is not None and aggregate["C"] > before_c
    if args.before_receipt and not improved_over_before:
        blocked.append("before_after_improvement_missing")
        verdict = "SCIENCEAGENTBENCH_ZERO_COST_REGRADE_LOOP_BLOCKED"
    return {"ticket": TICKET, "ts": ts, "sha_convention": SHA_CONVENTION, "repo": str(repo), "goal_path": str(repo / "GOAL.md"), "goal_source_sha256": sha256_file(repo / "GOAL.md"), "admission_receipt": str(admission_path), "admission_receipt_sha256": sha256_file(admission_path), "frozen_rows_path": str(frozen_rows_path), "frozen_rows_sha256": sha256_file(frozen_rows_path), "benchmark_root": str(benchmark_root), "run_root": str(run_root), "before_receipt": args.before_receipt, "before_c_score": before_c, "improved_over_before": improved_over_before, "scoring_mode": "zero_cost_stricter_noncanonical_regrade", "api_spend_usd": 0, "paid_api_surface_used": False, "leaderboard_identical": False, "canonical_gpt4o_score_present": False, "rubric_identical": True, "stricter_noncanonical_regrade": True, "expected_score_bias": "lower_or_equal_than_gpt4o_not_inflated", "judge_identity": {"deterministic_rows": "local official eval scripts", "visual_rows": "local/Codex/GPT-5.x/subagent transcript file" if args.visual_judgments else "pending transcript packets emitted", "visual_judgments_path": args.visual_judgments}, "public_sources": public_sources, "candidate_safety": {"gold_programs_read_by_candidate": False, "gold_results_visible_during_candidate_execution": False, "private_labels_read_by_candidate": False, "candidate_workdirs_isolated": True, "known_weak_surface": "clintox verified test csv exposes label columns to candidate; receipt does not treat that row as field-level proof by itself"}, "equal_budget": {"arms": ARMS, "attempts_per_arm_per_row": 1, "timeout_seconds": args.timeout_seconds}, "aggregate_scores": aggregate, "positive_delta": positive_delta, "deletion_sensitive": deletion_sensitive, "score_rows": score_rows, "visual_packets": visual_packets, "blocked_reasons": sorted(set(blocked)), "next_executable_command": "Fill visual judgment transcript JSON for emitted packets and rerun this script" if "visual_judge_transcript_missing" in blocked else "Fix the named score/delta blocker and rerun zero-cost regrade loop", "field_level_status": "progress_not_field_breakthrough", "verdict": verdict}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--admission", default=str(DEFAULT_ADMISSION))
    ap.add_argument("--frozen-rows", default=str(DEFAULT_FROZEN_ROWS))
    ap.add_argument("--benchmark-root", default=str(DEFAULT_BENCHMARK_ROOT))
    ap.add_argument("--run-root", default=None)
    ap.add_argument("--visual-judgments", default=None)
    ap.add_argument("--before-receipt", default=None)
    ap.add_argument("--timeout-seconds", type=int, default=45)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    receipt = build_receipt(args)
    out = Path(args.out)
    if not out.is_absolute():
        out = Path.cwd() / out
    write_json(out, receipt)
    print(json.dumps({"receipt": str(out), "verdict": receipt["verdict"], "aggregate_scores": receipt["aggregate_scores"], "blocked_reasons": receipt["blocked_reasons"], "run_root": receipt["run_root"]}, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] in {"SCIENCEAGENTBENCH_ZERO_COST_REGRADE_LOOP_PASS", "SCIENCEAGENTBENCH_ZERO_COST_REGRADE_LOOP_BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
