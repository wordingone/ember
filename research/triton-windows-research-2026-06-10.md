# Triton-Windows Research Dossier — Issue #27 Probe (b)
# Native-Windows torch + triton-windows + bitsandbytes 4-bit smoke
# RTX 4090 (Ada, sm_89), Windows 11, Python on Windows (no WSL)
# Prepared 2026-06-10

---

## Pins Table

| # | Item | Pin | Notes | Citation |
|---|------|-----|-------|----------|
| 1 | **torch Windows cu12x wheel** | `torch==2.7.0` via `--index-url https://download.pytorch.org/whl/cu126` **or** `cu128` | Latest stable (2.7.0, May 2026). Both cu126 and cu128 ship Windows win_amd64 wheels for Python 3.10–3.13 for torch 2.7.0. Earlier claim that cu126 is "the recommended CUDA variant on Windows" retracted — the PyTorch 2.7 release blog covers Linux/cu128 only and does not confirm cu126 Windows preference. Choice: cu126 requires CUDA 12.6 driver (≥531.18); cu128 requires CUDA 12.8 driver (≥545.xx). Match to installed driver. | [download.pytorch.org/whl/cu126/torch/](https://download.pytorch.org/whl/cu126/torch/) (verified: torch-2.7.0+cu126-cp310..cp313-win_amd64.whl present); [download.pytorch.org/whl/cu128/torch/](https://download.pytorch.org/whl/cu128/torch/) (verified: torch-2.7.0+cu128-cp310..cp313-win_amd64.whl present); [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/); [forum thread with cu126](https://discuss.pytorch.org/t/torch-version-2-7-0-cu126/219650) |
| 2 | **triton-windows package** | `pip name: triton-windows`, `version: 3.3.x` (for torch 2.7) — install with `pip install -U "triton-windows<3.4"` | `woct0rdho/triton-windows` was archived 2026-02-18; canonical repo moved to `triton-lang/triton-windows`. PyPI package name unchanged: `triton-windows`. Latest release on PyPI: **3.7.0.post26** (2026-05-14, for torch≥2.12). For torch 2.7, Triton 3.3 is the correct minor. | [triton-lang/triton-windows](https://github.com/triton-lang/triton-windows); [woct0rdho archived](https://github.com/woct0rdho/triton-windows); [PyPI triton-windows](https://pypi.org/project/triton-windows/) |
| 2a | **triton-windows ↔ torch compat matrix** | torch 2.6→triton 3.2; torch 2.7→triton 3.3; torch 2.8→triton 3.4; torch 2.9→triton 3.5; torch 2.10→triton 3.6; torch 2.12→triton 3.7. Each torch *minor* is only guaranteed with one triton *minor*. | — | [triton-lang/triton-windows README](https://github.com/triton-lang/triton-windows) |
| 3 | **bitsandbytes Windows 4-bit nf4** | `bitsandbytes==0.49.2` (latest stable, 2026-02-16). `win_amd64` wheel ships on PyPI. CUDA 11.8–12.6 and 12.8–12.9 targets include `sm89` (Ada). NF4/FP4 quantization supported from CC 6.0+. | Preview wheel `1.33.7.preview` also available but 0.49.2 is stable. Windows CUDA 12.8/12.9 wheels target sm100/sm120 but also sm89. PyPI install is plain `pip install bitsandbytes`. | [bitsandbytes PyPI](https://pypi.org/project/bitsandbytes/); [official installation guide](https://huggingface.co/docs/bitsandbytes/main/en/installation) |
| 3a | **bitsandbytes paged optimizers on Windows** | **NOT SUPPORTED.** `cudaMemPrefetchAsync()` is not available on Windows; CUDA unified memory oversubscription is not supported on Windows per NVIDIA docs (CUDA Programming Guide §unified-memory). Paged optimizers will fail. Use `adamw_torch` (standard) or `adamw_8bit` (non-paged) instead. | Issue #453 confirmed (fetched 2026-06-10): reporter states `cudaMemPrefetchAsync()` unavailable on Windows and cites NVIDIA CUDA Programming Guide for lack of memory oversubscription on Windows. Root limitation is a platform/driver constraint, not a bnb bug. Issue closed as duplicate. | [bnb issue #453](https://github.com/bitsandbytes-foundation/bitsandbytes/issues/453) (fetched — root cause confirmed: cudaMemPrefetchAsync + unified-memory oversubscription unsupported on Windows per NVIDIA docs); [NVIDIA CUDA Programming Guide — Unified Memory on Windows](https://docs.nvidia.com/cuda/cuda-c-programming-guide/#um-win) |
| 4 | **peft** | `peft==0.19.1` (2026-04-16). Python ≥ 3.10. Compatible with torch 2.4+. | — | [peft PyPI](https://pypi.org/project/peft/) |
| 4a | **transformers** | `transformers==5.11.0` (2026-06-10). Python ≥ 3.10, torch ≥ 2.4. | — | [transformers PyPI](https://pypi.org/project/transformers/) |
| 4b | **trl** | `trl==1.5.1` (2026-05-27). Python ≥ 3.10. Integrates peft + bitsandbytes via extras `trl[quantization]`. | — | [trl PyPI](https://pypi.org/project/trl/) |
| 5a | **Failure mode: triton-windows not recognized as `triton`** | Some libraries (older transformers, xformers) check for `pytorch-triton` or bare `triton` in metadata, not `triton-windows`. Transformers ≥4.55 has a known bug in `import_utils.py` where the triton detection falls back to checking `pytorch-triton` only — causing MXFP4 models to fall back to bf16 and CPU offload. Workaround: transformers 5.x likely fixes this (PR #39986 referenced); verify with `import triton` succeeding in the env. | `triton-windows` package provides the `triton` import namespace correctly, but pip dependency resolvers may not alias it. If a downstream `requires_dist` check fails, run `pip install triton-windows` *before* `transformers`, or patch the requirements check. | [transformers issue #39985](https://github.com/huggingface/transformers/issues/39985); [woct0rdho issue #98](https://github.com/woct0rdho/triton-windows/issues/98) |
| 5b | **Failure mode: inductor code cache rename on Windows** | `torch/_inductor/codecache.py` used `tmp_path.rename()` which fails on Windows when a file already exists (Windows disallows overwriting via rename). Affects `mode="max-autotune"` compile. **Status: closed/fixed** (replaced with `tmp_path.replace()`). Avoid `torch.compile(mode="max-autotune")` on Windows if on a torch version predating the fix. | Does not affect plain LoRA training without `torch.compile`. | [pytorch issue #138211](https://github.com/pytorch/pytorch/issues/138211) |
| 5c | **Failure mode: long paths in triton cache** | Triton JIT cache lands in `%USERPROFILE%\.triton\cache` and `%LOCALAPPDATA%\Temp\torchinductor_<user>`. Deep project trees can exceed the 260-char MAX_PATH limit. Mitigation: enable Windows long-path support (`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`) and run `git config --global core.longpaths true`. The triton-windows README recommends placing the project in a shallow path (e.g. `C:\triton`) when building. | For *running* (not building) triton-windows from PyPI this is less acute but cache path length can still hit the limit. | [PyTorch compile troubleshooting](https://docs.pytorch.org/docs/stable/torch.compiler_troubleshooting.html); [triton-windows README](https://github.com/woct0rdho/triton-windows) |
| 5d | **Failure mode: UTF-8 / console encoding** | Python on Windows defaults to cp1252 (or the system locale) unless `PYTHONUTF8=1` is set. HuggingFace tokenizer/dataset code emitting unicode characters to stdout can raise `UnicodeEncodeError`. Set `PYTHONUTF8=1` in the shell before running the smoke. | — | UNVERIFIED — no live page confirming this as a current known issue; inferred from Windows Python encoding behavior documented at [python.org](https://docs.python.org/3/using/windows.html) but not confirmed by a fetched HF/torch issue page for this specific error in 2025–2026. |
| 6 | **unsloth on native Windows** | **Works natively without WSL.** Unsloth Studio and the `unsloth` pip package both support Windows 11 natively. Install via conda + `pip install unsloth`. Known exclusion: **vLLM does not run on native Windows** — GRPO training via vLLM backend must use WSL or Linux. For a plain 1-step LoRA SFT smoke (no vLLM), unsloth is usable on Windows. | Unsloth is an *optional accelerator*; it is not required for the smoke. The smoke can run with plain peft+trl without unsloth. If included, verify no vLLM dependency is pulled in. | [unsloth Windows install docs](https://unsloth.ai/docs/get-started/install/windows-installation); [unsloth GitHub](https://github.com/unslothai/unsloth) |

---

## Known Failure Modes Summary

| Mode | Severity for 1-step smoke | Mitigation |
|------|--------------------------|------------|
| triton-windows not recognized as `triton` by older lib checks | MEDIUM — silent fallback to bf16 | Use transformers 5.x; check `import triton` works |
| Paged optimizers (`adamw_bnb_paged`) crash | HIGH if used | Use `adamw_torch` or `adamw_8bit` (non-paged) |
| Long paths in triton/inductor cache | LOW-MEDIUM | Enable `LongPathsEnabled`; use short project path |
| Inductor `rename()` bug (max-autotune) | LOW — only with `torch.compile` | Skip `torch.compile` for smoke |
| UTF-8 console encoding error | LOW | Set `PYTHONUTF8=1` (UNVERIFIED as current issue) |
| unsloth + vLLM on Windows | N/A for plain SFT smoke | Exclude vLLM; use plain peft/trl |

---

## Recommended pip install (venv recipe)

```powershell
# 1. Create and activate a clean venv (Python 3.12 recommended)
python -m venv .venv-ember-smoke
.\.venv-ember-smoke\Scripts\Activate.ps1

# 2. Install PyTorch 2.7.0 — choose cu126 OR cu128 to match your installed CUDA driver
#    cu126: CUDA 12.6 driver (≥531.18); cu128: CUDA 12.8 driver (≥545.xx)
#    Both have confirmed win_amd64 wheels for Python 3.10–3.13 (verified from download.pytorch.org indexes)
pip install torch==2.7.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
# OR: pip install torch==2.7.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126

# 3. Install triton-windows for torch 2.7 (triton 3.3.x)
pip install -U "triton-windows<3.4"

# 4. Install HF stack pinned
pip install bitsandbytes==0.49.2 transformers==5.11.0 peft==0.19.1 trl==1.5.1 accelerate datasets

# 5. Env guards before running the smoke
$env:PYTHONUTF8 = "1"
# (Optional but recommended) Enable long paths:
#   Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1
```

Single-line form (deps only, no env guards — cu128 shown; substitute cu126 if on CUDA 12.6 driver):
```
pip install torch==2.7.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 && pip install "triton-windows<3.4" bitsandbytes==0.49.2 transformers==5.11.0 peft==0.19.1 trl==1.5.1 accelerate datasets
```

**Training config note:** Do NOT use `optim="paged_adamw_8bit"` or any paged optimizer — these fail on Windows (pin 3a). Use `optim="adamw_torch"` for the smoke, or `optim="adamw_8bit"` (non-paged 8-bit adam from bnb).

---

## UNVERIFIED items

| Item | Why unverified |
|------|----------------|
| Pin 5d — UTF-8/console encoding as a current known issue in torch/HF 2025–2026 | No live fetched page confirmed a current HF or torch issue citing this specific error. The encoding behavior is documented Windows Python behavior but no issue receipt was obtained. Mark as "anticipated" not "confirmed." |
| triton-lang/triton-windows as "official" triton repo | The fetched page calls it a "community fork" not the official triton-lang repo; some search results claim it was adopted by triton-lang. The pip package name and maintainers are the same (`woctordho`, `jammm`). Treat as the current canonical source for `triton-windows` wheels regardless of org affiliation. |
| bitsandbytes Windows win_amd64 wheel first introduced version | PyPI release history shows 0.49.x has win_amd64 wheel; the exact version that *first* added it was not confirmed from a fetched page (search stated 0.49.0 / December 2024 but the PyPI page for 0.49.2 did not provide first-introduced history). |

---

## Sources (fetched pages)
- [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/)
- [PyTorch 2.7 release blog](https://pytorch.org/blog/pytorch-2-7/)
- [download.pytorch.org/whl/cu126/torch/](https://download.pytorch.org/whl/cu126/torch/) — **fetched 2026-06-10**: torch-2.7.0+cu126-cp310..cp313-win_amd64.whl confirmed present
- [download.pytorch.org/whl/cu128/torch/](https://download.pytorch.org/whl/cu128/torch/) — **fetched 2026-06-10**: torch-2.7.0+cu128-cp310..cp313-win_amd64.whl confirmed present
- [triton-lang/triton-windows](https://github.com/triton-lang/triton-windows)
- [woct0rdho/triton-windows (archived)](https://github.com/woct0rdho/triton-windows)
- [PyPI triton-windows](https://pypi.org/project/triton-windows/)
- [bitsandbytes PyPI](https://pypi.org/project/bitsandbytes/)
- [bitsandbytes installation guide (HF)](https://huggingface.co/docs/bitsandbytes/main/en/installation)
- [bitsandbytes issue #453 — cudaMemPrefetchAsync Windows](https://github.com/bitsandbytes-foundation/bitsandbytes/issues/453) — **fetched 2026-06-10**: root cause confirmed (cudaMemPrefetchAsync unavailable + unified-memory oversubscription unsupported on Windows per NVIDIA docs; closed as duplicate)
- [NVIDIA CUDA Programming Guide — Unified Memory on Windows](https://docs.nvidia.com/cuda/cuda-c-programming-guide/#um-win)
- [transformers issue #39985 — triton-windows not detected](https://github.com/huggingface/transformers/issues/39985)
- [pytorch issue #138211 — inductor cache rename on Windows](https://github.com/pytorch/pytorch/issues/138211)
- [woct0rdho issue #98 — triton-windows not recognized as triton](https://github.com/woct0rdho/triton-windows/issues/98)
- [unsloth Windows install](https://unsloth.ai/docs/get-started/install/windows-installation)
- [peft PyPI](https://pypi.org/project/peft/)
- [trl PyPI](https://pypi.org/project/trl/)
- [transformers PyPI](https://pypi.org/project/transformers/)
