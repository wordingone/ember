"""fp33_e1_open_base_inventory.py — local open-base model inventory for fp-33.

E1 leg of fp-33 (fp33-e2b-surpass-envelope.md). Inventories all open-source
models available locally (on-disk) or one-pull away, with:
  (a) params count (from config.json num_parameters or architecture derivation)
  (b) disk path (WSL2-canonical)
  (c) sha256 of config.json
  (d) license classification
  (e) on-disk vs one-pull status
  (f) HuggingFace model id (if determinable)

Scan roots:
  - ~/.cache/huggingface/hub/         (WSL2 HF cache)
  - /mnt/c/Users/Admin/.cache/huggingface/hub/  (Windows HF cache)
  - /mnt/b/M/avir/                    (avir project dirs)
  - /mnt/b/M/                         (any other B-drive models)

Decision: which models are viable as the open base for E2B-surpass comparison.
Receipt: receipts/fp33-e1-open-base-inventory-<ts>.json
Run via daemon (train window). --selftest is pure-logic, no disk I/O.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
NC   = os.path.dirname(HERE)
RECEIPTS = f"{NC}/receipts"

# License keywords → classification
_LICENSE_OPEN = {
    "apache-2.0", "apache 2.0", "apache2", "mit", "bsd", "cc-by",
    "cc-by-sa", "cc0", "gpl", "lgpl", "llama 2", "llama2",
    "llama 3", "llama3", "gemma",  # gemma ToU allows research use
}
_LICENSE_RESTRICTED = {"non-commercial", "research only", "cc-by-nc", "openrail"}

SCAN_ROOTS = [
    Path.home() / ".cache" / "huggingface" / "hub",
    Path("/mnt/c/Users/Admin/.cache/huggingface/hub"),
    # Narrow B-drive roots — full /mnt/b/M/ rglob is too slow over NTFS/WSL2
    Path("/mnt/b/M/avir/leo/state/nc-ladder"),
    Path("/mnt/b/M/avir/kai/state"),
    Path("/mnt/b/M/avir/mira/state"),
    Path("/mnt/b/M/avir/sage/state"),
    Path("/mnt/b/M/avir/jude/state"),
    Path("/mnt/b/M/models"),  # common model dump dir if it exists
]


def _sha256_file(path: Path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(chunk), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return "error"


def _count_params_from_config(cfg: dict) -> int | None:
    """Estimate param count from config.json fields."""
    # Explicit
    if "num_parameters" in cfg:
        return cfg["num_parameters"]
    # LlamaConfig / MistralConfig / GemmaConfig style
    h = cfg.get("hidden_size") or cfg.get("d_model") or cfg.get("n_embd")
    layers = cfg.get("num_hidden_layers") or cfg.get("n_layer") or cfg.get("num_layers")
    heads  = cfg.get("num_attention_heads") or cfg.get("n_head")
    vocab  = cfg.get("vocab_size")
    ff_mult = cfg.get("intermediate_size")
    if not (h and layers):
        return None
    # Embedding
    emb = h * (vocab or 32000)
    # Each transformer layer: QKV + O + 2×FF + 2×norms ~ (4h² + 2*ff_mult*h)
    ff = ff_mult or 4 * h
    kv_heads = cfg.get("num_key_value_heads", heads)
    kv_dim = h // heads * kv_heads if (heads and kv_heads) else h
    layer_params = h * h + h * kv_dim * 2 + h * h + 2 * ff * h + 2 * h
    return emb + layers * layer_params


def _license_from_dir(d: Path) -> str:
    for name in ("LICENSE", "LICENSE.txt", "README.md", "README"):
        f = d / name
        if f.exists():
            try:
                text = f.read_text(errors="replace").lower()[:4096]
                for kw in _LICENSE_RESTRICTED:
                    if kw in text:
                        return f"restricted:{kw}"
                for kw in _LICENSE_OPEN:
                    if kw in text:
                        return kw
            except OSError:
                pass
    return "unknown"


def _hf_model_id_from_path(p: Path) -> str | None:
    """Infer HF model id from HF hub cache layout: hub/models--org--name/snapshots/SHA/."""
    parts = p.parts
    for i, part in enumerate(parts):
        if part.startswith("models--"):
            return part[len("models--"):].replace("--", "/", 1)
    return None


def _scan_for_models(root: Path) -> list[dict]:
    """Walk root, find config.json files, assess each as a model candidate."""
    found = []
    if not root.exists():
        return found
    try:
        for config_path in root.rglob("config.json"):
            # Skip nested configs inside snapshots sub-dirs if a parent already found
            # (HF cache: models--org--name/snapshots/<sha>/config.json)
            d = config_path.parent
            try:
                cfg = json.loads(config_path.read_text(errors="replace"))
            except (json.JSONDecodeError, OSError):
                continue

            # Must have architectures or model_type to be a real model
            if not (cfg.get("architectures") or cfg.get("model_type")):
                continue

            # Check for weight files
            weight_files = sorted(
                list(d.glob("*.safetensors")) +
                list(d.glob("model*.bin")) +
                list(d.glob("pytorch_model*.bin"))
            )
            on_disk = bool(weight_files)
            total_weight_bytes = sum(f.stat().st_size for f in weight_files
                                     if f.exists()) if on_disk else 0

            params = _count_params_from_config(cfg)
            params_b = round(params / 1e9, 3) if params else None

            license_str = _license_from_dir(d)
            model_id = _hf_model_id_from_path(d)
            if not model_id:
                # Use the directory name heuristic
                model_id = d.name

            found.append({
                "model_id": model_id,
                "model_type": cfg.get("model_type") or (cfg.get("architectures") or ["?"])[0],
                "path": str(d),
                "on_disk": on_disk,
                "params": params,
                "params_b": params_b,
                "weight_files_count": len(weight_files),
                "weight_bytes": total_weight_bytes,
                "weight_gib": round(total_weight_bytes / (1 << 30), 2) if total_weight_bytes else 0.0,
                "license": license_str,
                "config_sha256": _sha256_file(config_path),
                "architectures": cfg.get("architectures", []),
            })
    except (PermissionError, OSError):
        pass
    return found


def classify_viability(entry: dict) -> str:
    """Is this model a viable open-base candidate for E2B-surpass?"""
    if not entry["on_disk"]:
        return "ONE_PULL"
    lic = entry["license"]
    if lic.startswith("restricted"):
        return "RESTRICTED"
    p = entry.get("params_b") or 0
    if p > 13:
        return "TOO_LARGE"  # >13B won't fit in 24GB full-tune comparison
    if p < 0.1:
        return "TOO_SMALL"
    return "VIABLE"


def main():
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print("[E1] scanning model directories ...", flush=True)
    t0 = time.perf_counter()

    all_models: list[dict] = []
    scan_results = {}
    for root in SCAN_ROOTS:
        count_before = len(all_models)
        models = _scan_for_models(root)
        # Deduplicate by config_sha256
        seen_shas = {m["config_sha256"] for m in all_models}
        fresh = [m for m in models if m["config_sha256"] not in seen_shas]
        all_models.extend(fresh)
        scan_results[str(root)] = {"found": len(models), "fresh": len(fresh)}
        print(f"  {root}: {len(fresh)} new", flush=True)

    elapsed = time.perf_counter() - t0

    # Classify + sort by viability then params
    for m in all_models:
        m["viability"] = classify_viability(m)

    viable = [m for m in all_models if m["viability"] == "VIABLE"]
    viable.sort(key=lambda m: m.get("params") or 0)

    print(f"[E1] {len(all_models)} models found, {len(viable)} viable", flush=True)

    receipt = {
        "ticket": "FP33-E1-OPEN-BASE-INVENTORY",
        "ts": ts,
        "scan_elapsed_s": round(elapsed, 2),
        "scan_roots": scan_results,
        "total_found": len(all_models),
        "viable_count": len(viable),
        "models": all_models,
        "viable_summary": [
            {
                "model_id": m["model_id"],
                "params_b": m["params_b"],
                "weight_gib": m["weight_gib"],
                "license": m["license"],
                "path": m["path"],
            }
            for m in viable
        ],
        "decision": "E2B-SURPASS target is ember v0 (0.37B c03-qat). "
                    "Open base = highest-quality on-disk model <=3B params, "
                    "license-open, same or smaller scale. "
                    "E2 will measure full-tune ceiling at 24GB vs this base.",
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/fp33-e1-open-base-inventory-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP33_E1_OPEN_BASE_INVENTORY_DONE {out}")
    return receipt


def _selftest():
    # param estimation
    cfg = {
        "model_type": "llama",
        "hidden_size": 2048,
        "num_hidden_layers": 22,
        "num_attention_heads": 32,
        "vocab_size": 32000,
        "intermediate_size": 5632,
    }
    p = _count_params_from_config(cfg)
    assert p is not None and p > 1e8, f"param count failed: {p}"
    # license classify
    assert classify_viability({"on_disk": False, "license": "apache-2.0", "params_b": 2.0}) == "ONE_PULL"
    assert classify_viability({"on_disk": True,  "license": "restricted:non-commercial", "params_b": 2.0}) == "RESTRICTED"
    assert classify_viability({"on_disk": True,  "license": "apache-2.0", "params_b": 0.05}) == "TOO_SMALL"
    assert classify_viability({"on_disk": True,  "license": "apache-2.0", "params_b": 2.0}) == "VIABLE"
    print("FP33_E1_OPEN_BASE_INVENTORY_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
