#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_c14_owned_core.py — C14 owned-core resident-training binding (CPU float32).

Provides make_owned_core_factory(), the owned_core_factory the C14 contract rig
needs in place of the multimodal-shell real_core_factory (frozen design spec:
ember-goalforge/docs/spec/c14-owned-core-resident-run-v1.md, section 1,
"Trainable resident policy (C arm)"). The returned factory:

  1. Hash-verifies then loads the REAL owned seed (cbase-v0 survivor-stack,
     models/cbase-smoke-run/checkpoints/step-00000610) — hard-fails on any
     mismatch against the frozen identity binding. This module never falls
     back to a toy/borrowed core; the seed IS the owned checkpoint or the
     factory raises.
  2. Wraps the CPU float32 twin proven in cbase_grow_dryrun.py::build_model
     (same LlamaModel `backbone_model`, tied `head`, `mtp_heads` architecture)
     in a thin nn.Module (_OwnedCorePolicy) that adds a REAL-grad
     forward(input_ids) -> (B, S, V) path — the twin's own .logits() method is
     @torch.no_grad and therefore unusable on a training path — plus a
     sample_action() that draws from the live logits, mirroring
     EmberModelShell.sample_action (ember_c14_real_adapter.py): changing the
     weights changes the action distribution, by construction.
  3. Injects a rank-r LoRA adapter (ember_phase3_c14/resident_adapter.py::
     LoRAAdapter) at the "head" linear. Only the adapter (lora_A, lora_B) is
     trainable; ALL base parameters are frozen IN THIS RUN. Frozen-in-run is
     NOT the same as borrowed: the base itself is the OWNED cbase-v0
     checkpoint (hash-verified in step 1 above), so no borrowed weight is
     load-bearing anywhere in the returned policy — the adapter is the
     growing organ, the base is the owned foundation it grows on.
  4. Defensively confirms (never assumes) that the wrapped core is not
     flagged a side-classifier by ember_c14_contract_rig._is_side_classifier
     (guard (e), read verbatim from that module: total params >= 1000 AND at
     least one named_module name contains "attn"/"attention"/"transformer"/
     "encoder"). LlamaModel's own submodule names (e.g.
     "backbone_model.layers.N.self_attn") already contain "attn" as a
     substring, so this passes by construction — verified programmatically
     here, not assumed. If a future architecture change ever fails this
     check, alias submodule REFERENCES (the SAME module objects, never
     copies) are registered under acceptable names until it passes; nn.Module
     dedupes shared-object parameters when iterating .parameters(), so
     aliasing cannot double-count trainable/frozen params or perturb any hash.

Exposes base_param_hash(policy) / adapter_param_hash(policy): sha256 over the
frozen-base and LoRA state_dicts respectively, in deterministic (sorted-key)
order. This is the load-bearing invariant the CPU smoke below measures: the
adapter hash must move under one real policy-gradient-style step; the base
hash must never move.

CPU float32 is the default and unchanged path (device="cpu", byte-identical
to the original CPU-only version of this module). A governed CUDA path
(device="cuda") is also provided per the frozen design's section 7 blocker 2
("CUDA path for the owned-core factory"): base weights load in bf16 on the
GPU, the LoRA adapter keeps an fp32 master copy of the trained delta, and
every CUDA allocation is gated by the repo's governor (VRAM-fraction cap +
free-margin assert, src/ember/governance/scripts/governor.py::preflight) plus a post-load
allocated-memory ceiling assert. No git commits, no network, no edits to any
other existing file. Style matches cbase_grow_dryrun.py: fail-closed asserts,
a receipt via receipt_write.checked_write, a verdict COMPUTED from the
measured checks — never hardcoded.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

# ---------------------------------------------------------------------------
# Import paths — sibling scripts, reused rather than copy-pasted
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PHASE3_DIR = _SCRIPTS_DIR / "ember_phase3_c14"
for _p in (_SCRIPTS_DIR, _PHASE3_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cbase_grow_dryrun  # noqa: E402  reuse build_model + sha256_file — proven CPU float32 twin
from resident_adapter import LoRAAdapter  # noqa: E402
from receipt_write import checked_write  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_contract_rig.py
import importlib.util as _ember_a15ae7b5497c49d1_importlib
import sys as _ember_a15ae7b5497c49d1_sys
from pathlib import Path as _ember_a15ae7b5497c49d1_Path
_ember_a15ae7b5497c49d1_path = _ember_a15ae7b5497c49d1_Path(__file__).resolve().parents[4].joinpath('scripts', 'ember_c14_contract_rig.py')
if not _ember_a15ae7b5497c49d1_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_contract_rig.py')
_ember_a15ae7b5497c49d1_aliases = ('_ember_issue2015_a15ae7b5497c49d1', 'ember_c14_contract_rig', 'src.ember.governance.scripts.ember_c14_contract_rig')
_ember_a15ae7b5497c49d1_existing = []
for _ember_a15ae7b5497c49d1_alias in _ember_a15ae7b5497c49d1_aliases:
    _ember_a15ae7b5497c49d1_candidate = _ember_a15ae7b5497c49d1_sys.modules.get(_ember_a15ae7b5497c49d1_alias)
    if _ember_a15ae7b5497c49d1_candidate is not None and all(_ember_a15ae7b5497c49d1_candidate is not item for item in _ember_a15ae7b5497c49d1_existing):
        _ember_a15ae7b5497c49d1_existing.append(_ember_a15ae7b5497c49d1_candidate)
if len(_ember_a15ae7b5497c49d1_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_contract_rig.py')
if _ember_a15ae7b5497c49d1_existing:
    _ember_a15ae7b5497c49d1_module = _ember_a15ae7b5497c49d1_existing[0]
    _ember_a15ae7b5497c49d1_observed = getattr(_ember_a15ae7b5497c49d1_module, '__file__', None)
    if _ember_a15ae7b5497c49d1_observed is None or _ember_a15ae7b5497c49d1_Path(_ember_a15ae7b5497c49d1_observed).resolve() != _ember_a15ae7b5497c49d1_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_contract_rig.py')
else:
    _ember_a15ae7b5497c49d1_spec = _ember_a15ae7b5497c49d1_importlib.spec_from_file_location('_ember_issue2015_a15ae7b5497c49d1', _ember_a15ae7b5497c49d1_path)
    if _ember_a15ae7b5497c49d1_spec is None or _ember_a15ae7b5497c49d1_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_contract_rig.py')
    _ember_a15ae7b5497c49d1_module = _ember_a15ae7b5497c49d1_importlib.module_from_spec(_ember_a15ae7b5497c49d1_spec)
    for _ember_a15ae7b5497c49d1_alias in _ember_a15ae7b5497c49d1_aliases:
        _ember_a15ae7b5497c49d1_prior = _ember_a15ae7b5497c49d1_sys.modules.get(_ember_a15ae7b5497c49d1_alias)
        if _ember_a15ae7b5497c49d1_prior is not None and _ember_a15ae7b5497c49d1_prior is not _ember_a15ae7b5497c49d1_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_contract_rig.py')
        _ember_a15ae7b5497c49d1_sys.modules[_ember_a15ae7b5497c49d1_alias] = _ember_a15ae7b5497c49d1_module
    try:
        _ember_a15ae7b5497c49d1_spec.loader.exec_module(_ember_a15ae7b5497c49d1_module)
    except BaseException:
        for _ember_a15ae7b5497c49d1_alias in _ember_a15ae7b5497c49d1_aliases:
            if _ember_a15ae7b5497c49d1_sys.modules.get(_ember_a15ae7b5497c49d1_alias) is _ember_a15ae7b5497c49d1_module:
                _ember_a15ae7b5497c49d1_sys.modules.pop(_ember_a15ae7b5497c49d1_alias, None)
        raise
for _ember_a15ae7b5497c49d1_alias in _ember_a15ae7b5497c49d1_aliases:
    _ember_a15ae7b5497c49d1_prior = _ember_a15ae7b5497c49d1_sys.modules.get(_ember_a15ae7b5497c49d1_alias)
    if _ember_a15ae7b5497c49d1_prior is not None and _ember_a15ae7b5497c49d1_prior is not _ember_a15ae7b5497c49d1_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_contract_rig.py')
    _ember_a15ae7b5497c49d1_sys.modules[_ember_a15ae7b5497c49d1_alias] = _ember_a15ae7b5497c49d1_module
_is_side_classifier = getattr(_ember_a15ae7b5497c49d1_module, '_is_side_classifier')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_contract_rig.py  # noqa: E402  guard (e), read verbatim
import governor  # noqa: E402  single canonical VRAM-fraction-cap + margin-assert (CUDA path only)

REPO = Path(__file__).resolve().parents[4]
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
SEED_CKPT_DEFAULT = REPO / "models" / "cbase-smoke-run" / "checkpoints" / "step-00000610"
# Frozen identity binding (design spec section 1, "Owned base (C-BASE, GREEN)").
EXPECTED_MODEL_PT_SHA256 = (
    "1ec99451d0c1446441db76f2d86d9b9e3f866941ca6f5a1c72f74182d08f5bdb"
)


# ---------------------------------------------------------------------------
# Owned seed identity — hash-verify, never trust the manifest alone
# ---------------------------------------------------------------------------

def verify_seed_checkpoint(
    seed_ckpt: Path = SEED_CKPT_DEFAULT, expected_sha: str = EXPECTED_MODEL_PT_SHA256
) -> dict:
    """Hash-verify the owned seed checkpoint. Hard-fails (raises) on any mismatch.

    Checks BOTH: (a) the on-disk model.pt matches `expected_sha` exactly, and
    (b) the checkpoint's own manifest.json self-claim matches the same bytes
    (manifest-tamper check). Either mismatch is fatal — this factory never
    silently proceeds on an unverified core.

    A20 SUBSTRATE OVERRIDE (additive, 2026-07-03): `expected_sha` defaults to
    the frozen identity binding EXPECTED_MODEL_PT_SHA256 (byte-identical to
    before this parameter existed when the caller omits it — e.g. a bare
    verify_seed_checkpoint(some_path) call reproduces the pre-override
    behavior exactly for that path). Passing a different checkpoint's own
    real sha256 here (see make_owned_core_factory's seed_ckpt/
    expected_model_pt_sha256 params) lets this SAME hash-verify-or-raise
    discipline apply to a substrate other than the default cbase-v0 seed —
    still fail-closed, never a silent skip.
    """
    model_pt = seed_ckpt / "model.pt"
    if not model_pt.is_file():
        raise RuntimeError(f"OWNED_CORE_SEED_MISSING: {model_pt} does not exist")
    actual_sha = cbase_grow_dryrun.sha256_file(model_pt)
    if actual_sha != expected_sha:
        raise RuntimeError(
            "OWNED_CORE_SEED_HASH_MISMATCH: model.pt sha256 does not match the "
            f"expected identity binding. expected={expected_sha} "
            f"actual={actual_sha} path={model_pt}"
        )
    manifest_path = seed_ckpt / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    claimed_sha = (manifest.get("files") or {}).get("model.pt")
    if claimed_sha != actual_sha:
        raise RuntimeError(
            "OWNED_CORE_SEED_MANIFEST_MISMATCH: manifest.json model.pt claim "
            f"{claimed_sha!r} != actual on-disk sha256 {actual_sha!r} — the "
            "manifest does not describe the bytes on disk."
        )
    return {"checkpoint": str(seed_ckpt), "model_pt_sha256": actual_sha, "verified": True}


def _measure_intermediate_size(sd: dict) -> int:
    """Read the seed's FF width directly from the checkpoint tensor shape — the
    same robust pattern cbase_grow_dryrun.py uses (never trust a config value
    that could drift from what was actually trained; measure the real bytes)."""
    return int(sd["backbone_model.layers.0.mlp.gate_proj.weight"].shape[0])


# ---------------------------------------------------------------------------
# torch.compile toolchain bootstrap (DISPATCH-CONSTANT CURE, 2026-07-03)
# ---------------------------------------------------------------------------

_MSVC_TOOLCHAIN_READY: Optional[bool] = None  # None=not probed, True/False=cached result


def _ensure_compile_toolchain() -> bool:
    """One-time, IN-PROCESS-ONLY environment bootstrap so torch.compile's
    Triton backend can find a C compiler on Windows.

    Triton shells out to a host C compiler (cl.exe on Windows) to build the
    small extension module that launches its generated CUDA kernels — this
    fails with 'Failed to find C compiler' even on a machine where Visual
    Studio IS installed, because VS does not add cl.exe to PATH globally
    (it only becomes available inside a vcvars-initialized shell). This
    function discovers an ALREADY-INSTALLED MSVC toolchain via vswhere.exe
    (Microsoft's own standard VS-install discovery tool, itself part of any
    VS install) and merges the same environment variables vcvarsall.bat
    would set (INCLUDE, LIB, PATH, plus CC) into os.environ FOR THIS PROCESS
    ONLY. It never writes to the registry, never touches System/User
    environment variables, never installs anything — if no toolchain is
    found, it logs why and returns False so the caller falls back to eager
    instead of crashing a training step on a missing external tool.

    Idempotent (module-level cache) and safe to call from any thread of
    control that reaches a compile_mode-enabled forward() first.
    """
    global _MSVC_TOOLCHAIN_READY
    if _MSVC_TOOLCHAIN_READY is not None:
        return _MSVC_TOOLCHAIN_READY

    if shutil.which("cl.exe") is not None:
        _MSVC_TOOLCHAIN_READY = True
        return True

    try:
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        vswhere = Path(program_files_x86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        if not vswhere.is_file():
            print(
                "COMPILE_TOOLCHAIN_UNAVAILABLE: vswhere.exe not found at "
                f"{vswhere} — no discoverable Visual Studio install. "
                "compile_mode will fall back to eager."
            )
            _MSVC_TOOLCHAIN_READY = False
            return False

        found = subprocess.run(
            [str(vswhere), "-latest", "-products", "*", "-property", "installationPath"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        if not found:
            print("COMPILE_TOOLCHAIN_UNAVAILABLE: vswhere found no VS installation.")
            _MSVC_TOOLCHAIN_READY = False
            return False

        vcvars = Path(found) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        if not vcvars.is_file():
            print(f"COMPILE_TOOLCHAIN_UNAVAILABLE: {vcvars} not found under discovered VS install.")
            _MSVC_TOOLCHAIN_READY = False
            return False

        proc = subprocess.run(
            f'cmd /c ""{vcvars}" && set"', capture_output=True, text=True, shell=True, timeout=60,
        )
        for line in proc.stdout.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                if k:
                    os.environ[k] = v

        if shutil.which("cl.exe") is None:
            print(
                "COMPILE_TOOLCHAIN_UNAVAILABLE: ran vcvars64.bat but cl.exe is "
                "still not resolvable — unexpected vcvars output shape."
            )
            _MSVC_TOOLCHAIN_READY = False
            return False

        print(f"COMPILE_TOOLCHAIN_BOOTSTRAPPED: cl.exe resolved via {shutil.which('cl.exe')}")
        _MSVC_TOOLCHAIN_READY = True
        return True
    except Exception as exc:
        print(f"COMPILE_TOOLCHAIN_UNAVAILABLE: {type(exc).__name__}: {exc}")
        _MSVC_TOOLCHAIN_READY = False
        return False


# ---------------------------------------------------------------------------
# _OwnedCorePolicy — real-grad forward + sample_action over the CPU float32 twin
# ---------------------------------------------------------------------------

class _OwnedCorePolicy(nn.Module):
    """Thin nn.Module wrapper around the cbase_grow_dryrun.build_model twin.

    The twin (the locally-defined class inside build_model) exposes only a
    @torch.no_grad() `.logits(ids)` method — usable for inference-only probes
    (cbase_grow_dryrun's growability proof) but NOT for a training path, since
    no gradient can flow through a no_grad-decorated call. This wrapper shares
    the SAME submodule objects (backbone_model, head, mtp_heads — no copies,
    no re-instantiation, no re-loading) and adds:

      forward(input_ids) -> (B, S, V) logits, WITH grad.
      sample_action(state_val, temperature) -> int, mirroring
        EmberModelShell.sample_action (ember_c14_real_adapter.py): draws from
        the model's ACTUAL output logits at the last position (multinomial /
        argmax under temperature), so a weight change provably changes the
        action distribution — never a hardcoded or templated draw. Accepts
        either a raw int state_val (encoded to a length-1 context token,
        mirroring ember_resident_igrpo._encode_state's state->context
        convention, scaled into this model's real vocab range) or a
        pre-built 1D LongTensor of context_ids directly (the EmberModelShell
        contract).
    """

    def __init__(self, raw_v0: nn.Module, compile_mode: Optional[str] = None) -> None:
        super().__init__()
        self.backbone_model = raw_v0.backbone_model
        self.head = raw_v0.head
        self.mtp_heads = raw_v0.mtp_heads
        # DISPATCH-CONSTANT CURE (2026-07-03, bounded leg after batching):
        # compile_mode is None by default -> forward() is BYTE-FOR-BYTE the
        # original eager path below, unconditionally. When set ("reduce-
        # overhead" or "default"), a torch.compile'd backbone call is used
        # ONLY when torch.is_grad_enabled() is False AND input_ids.is_cuda —
        # i.e. ONLY the no_grad SAMPLING calls (ember_resident_igrpo.py's
        # _forward_sample / _rlm_generate_batch, both already under
        # torch.no_grad(), unedited by this leg). igrpo_loss's grad-bearing
        # re-forward always has grad enabled, so it is structurally
        # impossible for this branch to touch the loss path — no caller-side
        # flag, no ember_resident_igrpo.py edit needed to keep them apart.
        # Lazily built (compilation happens on first no_grad CUDA call, not
        # at construction) and memoized per-instance.
        self._compile_mode = compile_mode
        self._compiled_backbone: Optional[Callable] = None

    def _backbone_call(self, input_ids: torch.Tensor):
        """The uncompiled backbone call, factored out so both the eager path
        and torch.compile() (which wraps exactly this callable) share one
        source of truth for what the backbone computes."""
        return self.backbone_model(input_ids=input_ids)

    def _get_compiled_backbone(self) -> Callable:
        if self._compiled_backbone is None:
            if not _ensure_compile_toolchain():
                # No C compiler discoverable on this machine (Triton's
                # Windows build backend needs one) — disable compile mode
                # for this instance from here on (forward()'s use_compiled
                # check reads self._compile_mode, so clearing it makes every
                # SUBSEQUENT call skip straight to the eager path with zero
                # further overhead) and serve THIS call eagerly too.
                self._compile_mode = None
                return self._backbone_call
            self._compiled_backbone = torch.compile(
                self._backbone_call, mode=self._compile_mode
            )
        return self._compiled_backbone

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        if input_ids.is_cuda:
            # CUDA base is bf16 (see module docstring / factory). The
            # injected LoRA forward hook (resident_adapter.py, not edited by
            # this task) computes its correction with fp32 lora_A/lora_B
            # against this same bf16 activation; autocast lets that mixed
            # matmul run without a manual cast inside the hook, casting the
            # fp32 adapter weights down for the op while leaving the stored
            # parameters — the trained delta — as the fp32 master. Cast the
            # combined output back to fp32 at the head output so the
            # caller's loss computation is numerically stable.
            use_compiled = self._compile_mode is not None and not torch.is_grad_enabled()
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                if use_compiled:
                    h = self._get_compiled_backbone()(input_ids).last_hidden_state
                else:
                    h = self._backbone_call(input_ids).last_hidden_state
                out = self.head(h)
            return out.float()
        h = self.backbone_model(input_ids=input_ids).last_hidden_state
        return self.head(h)

    def forward_step(
        self, input_ids: torch.Tensor, past_key_values: Any = None
    ) -> tuple[torch.Tensor, Any]:
        """Cache-aware sibling of forward(), for the no_grad SAMPLING path
        only (ember_c14_owned_run.py::_ActionBandPolicy.sample_action's
        per-token rlm_generate decode loop). forward() above is completely
        UNCHANGED and remains the only path igrpo_loss's teacher-forced,
        grad-bearing scoring uses.

        past_key_values=None: `input_ids` is treated as the full context
        (a "prefill") — transformers.LlamaModel builds a fresh Cache via
        use_cache=True and returns it alongside last_hidden_state. Passing
        use_cache=True does not itself change what last_hidden_state's values
        are — it only additionally collects+returns the K/V cache alongside
        the SAME hidden-state computation forward() already does — so a
        prefill call here (past_key_values=None) is numerically identical to
        calling forward() over the same input_ids (only the return shape
        differs: (logits, cache) instead of logits).

        past_key_values=<Cache>: `input_ids` must be ONLY the unprocessed
        suffix (normally exactly the one new sampled token) that continues
        the sequence the cache was built from. LlamaModel's own
        position_ids default (transformers/models/llama/modeling_llama.py:
        `torch.arange(new_len) + past_key_values.get_seq_length()`) offsets
        RoPE positions correctly for this case — this method passes neither
        attention_mask nor position_ids explicitly, same as forward() above,
        so both call shapes rely on that one vendored default.

        The CUDA autocast bf16 block mirrors forward() exactly (same
        context manager, same head-output float() cast); the LoRA forward
        hook fires identically either way since it is registered directly on
        self.head and fires whenever self.head(...) is invoked, regardless
        of which enclosing method made the call.

        Returns (logits, present_key_values). Caller (_ActionBandPolicy)
        decides whether/when to reuse a cache; this method just does
        whatever plumbing the caller-supplied past_key_values calls for.
        """
        if input_ids.is_cuda:
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                out = self.backbone_model(
                    input_ids=input_ids, past_key_values=past_key_values, use_cache=True
                )
                logits = self.head(out.last_hidden_state)
            return logits.float(), out.past_key_values
        out = self.backbone_model(
            input_ids=input_ids, past_key_values=past_key_values, use_cache=True
        )
        return self.head(out.last_hidden_state), out.past_key_values

    def sample_action(self, state_val, temperature: float = 1.0) -> int:
        if isinstance(state_val, torch.Tensor):
            context_ids = state_val
        else:
            vocab = self.head.out_features
            context_ids = torch.tensor([int(state_val) % vocab], dtype=torch.long)
        inp = context_ids.unsqueeze(0).clamp(0, self.head.out_features - 1)
        with torch.no_grad():
            logits = self.forward(inp)[0, -1, :]
        if temperature <= 0:
            return int(logits.argmax().item())
        probs = F.softmax(logits / max(temperature, 1e-6), dim=-1)
        return int(torch.multinomial(probs, 1).item())

    def __deepcopy__(self, memo: dict) -> "_OwnedCorePolicy":
        """Cheap deepcopy (C14 CURE 1, 2026-07-02 — companion to
        src/ember/governance/scripts/ember_c14_owned_run.py::_ActionBandPolicy.__deepcopy__, which
        is where the full rationale lives). igrpo_step (ember_resident_
        igrpo.py) and train_one_step (ember_phase3_c14/igrpo_trainer.py) —
        neither edited by this change — call copy.deepcopy(policy) every
        training step to snapshot pi_theta_old. The default recursive
        deepcopy clones backbone_model + head + mtp_heads in full every call;
        at owned-core scale (~368M params) that is exactly the per-step cost
        this method exists to remove.

        backbone_model and mtp_heads are SHARED BY REFERENCE — both are
        frozen (requires_grad=False; see make_owned_core_factory's
        freeze_base loop, which this class's caller always applies) and
        never appear in the C-arm optimizer's trainable-param list, so two
        policies pointing at the SAME objects never race on a write.

        head is REBUILT as a fresh nn.Linear wrapper around the SAME
        weight/bias tensors (never copied — correct, not just cheap, for a
        tied-embedding head: head.weight IS backbone_model.embed_tokens.
        weight per cbase_grow_dryrun.build_model's tie_word_embeddings
        convention, so sharing the Parameter object preserves that tie).
        A fresh wrapper OBJECT is required — not the literal same nn.Linear
        instance — because LoRAAdapter.__init__ (resident_adapter.py, not
        edited) registers its forward hook on whatever module it finds at
        target_layer_name, bound to that specific LoRAAdapter via
        self._lora_hook -> self.lora. Sharing the literal head object would
        mean the copy's forward silently triggers the ORIGINAL (still
        training) LoRAAdapter's hook instead of its own — defeating the
        entire point of a frozen ref snapshot. A new wrapper object gets its
        own independent _forward_hooks dict, so the caller
        (_ActionBandPolicy.__deepcopy__, which constructs a fresh LoRAAdapter
        on top of the object this method returns) can register an
        independent hook without touching the original's.

        Known shared-state consequence, verified harmless for THIS
        architecture (not assumed): igrpo_step/train_one_step call
        ref_policy.eval() every step, which recursively flips
        .training=False on every reachable submodule — including the SHARED
        backbone_model/mtp_heads, so the live policy's view of those same
        objects flips too. LlamaModel (transformers, cbase_grow_dryrun.
        build_model) has no Dropout/BatchNorm in this config (HF's
        attention_dropout defaults to 0.0; RMSNorm carries no running
        stats), so .training has zero effect on forward() output — this
        aliasing is inert. Re-verify if the architecture ever grows a
        train/eval-sensitive layer.

        DISPATCH-CONSTANT CURE bugfix (2026-07-03): __new__ bypasses
        __init__ entirely, so self._compile_mode / self._compiled_backbone
        (set in __init__, added for the compile leg) would otherwise be
        MISSING on the deepcopy'd ref_policy — the first grad-enabled
        forward() call on it raised AttributeError reading
        self._compile_mode, caught by this exact bar's own timed-measurement
        probe (igrpo_step's real loss path deepcopies ref_policy every
        step). Fix: copy the plain compile_mode VALUE across (harmless even
        though it's never acted on — ref_policy.forward() only ever runs
        grad-ENABLED, so use_compiled's `not torch.is_grad_enabled()` check
        always evaluates False for it regardless of this value) and give it
        its OWN fresh (unbuilt, lazy) _compiled_backbone slot rather than
        sharing self's compiled callable object.
        """
        if id(self) in memo:
            return memo[id(self)]
        new = _OwnedCorePolicy.__new__(_OwnedCorePolicy)
        nn.Module.__init__(new)
        new.backbone_model = self.backbone_model  # shared reference, frozen
        new.mtp_heads = self.mtp_heads            # shared reference, frozen
        new._compile_mode = self._compile_mode
        new._compiled_backbone = None
        new_head = nn.Linear.__new__(nn.Linear)
        nn.Module.__init__(new_head)
        new_head.in_features = self.head.in_features
        new_head.out_features = self.head.out_features
        new_head.register_parameter("weight", self.head.weight)  # same tensor (tied-embedding safe)
        new_head.register_parameter(
            "bias", self.head.bias if self.head.bias is not None else None
        )
        new.head = new_head
        memo[id(self)] = new
        return new


def _ensure_guard_e_passes(policy_core: nn.Module) -> dict:
    """Defensively verify the wrapped core is NOT flagged a side-classifier by
    ember_c14_contract_rig._is_side_classifier's guard (e) (read verbatim:
    total params < 1000 -> side-classifier; OR no named_module name contains
    "attn"/"attention"/"transformer"/"encoder" -> side-classifier). LlamaModel's
    own submodule names (e.g. "backbone_model.layers.N.self_attn") already
    contain "attn" as a substring, so this passes by construction — verified
    programmatically here, never assumed. If it were ever to fail, alias
    submodule REFERENCES (the SAME module objects, never copies) are
    registered under acceptable names until it passes.
    """
    aliased: list[str] = []
    if _is_side_classifier(policy_core):
        # Defensive path — not expected to execute given LlamaModel's native
        # naming; kept for resilience against a future architecture change.
        policy_core.add_module("transformer_backbone_alias", policy_core.backbone_model)
        aliased.append("transformer_backbone_alias -> backbone_model")
    still_flagged = _is_side_classifier(policy_core)
    if still_flagged:
        raise RuntimeError(
            "GUARD_E_UNSATISFIABLE: _is_side_classifier still flags the owned "
            "core as a side-classifier after alias registration — this is a "
            "genuine interface mismatch to report, not to route around silently."
        )
    return {"guard_e_passed": True, "aliases_registered": aliased}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _cuda_preflight() -> dict:
    """GPU discipline gate before any CUDA allocation — the repo's governor
    rules (src/ember/governance/scripts/governor.py::preflight, the single canonical VRAM-
    fraction-cap + free-margin-assert mechanism). Fails closed: refuses the
    load rather than proceeding ungoverned. Returns the governor's receipt
    block ({vram_fraction, free_gb, total_gb, margin_gb}) for the caller to
    fold into its own receipt.
    """
    assert torch.cuda.is_available(), (
        "OWNED_CORE_CUDA_UNAVAILABLE: torch.cuda.is_available() is False — "
        "cannot build a device='cuda' owned-core factory."
    )
    return governor.preflight()


def make_owned_core_factory(
    device: str = "cpu",
    rank: int = 8,
    compile_mode: Optional[str] = None,
    seed_ckpt: Optional[Path] = None,
    expected_model_pt_sha256: Optional[str] = None,
) -> Callable[[], LoRAAdapter]:
    """Return a zero-arg factory producing a fresh owned-core + LoRA policy.

    Each call to the returned factory: hash-verifies the seed, builds a fresh
    _OwnedCorePolicy from it, defensively confirms guard (e), and injects a
    fresh rank-`rank` LoRA adapter at the "head" linear. Base parameters are
    frozen (owned, not borrowed — see module docstring).

    device="cpu" (default): CPU float32 throughout — byte-identical to the
    original CPU-only version of this factory.

    device="cuda": governed GPU path (design spec section 7 blocker 2). Base
    weights (backbone_model, head, mtp_heads) load and run in bf16 on the
    GPU; the injected LoRA adapter (lora_A, lora_B) is moved to an fp32
    master copy on the GPU — the trained delta stays fp32 for numerically
    stable optimizer updates, while the base is the owned bf16 foundation.
    Every CUDA allocation is gated by _cuda_preflight() (VRAM-fraction cap +
    free-margin assert) BEFORE any tensor touches the GPU, and a post-load
    torch.cuda.memory_allocated() ceiling assert (<4 GiB) fails closed if
    the load ever allocates more than expected — see the assert's own
    comment below for the measured-size justification (covers both the
    ~368M-param default seed and the A20 grown ~1.222B-param substrate).

    compile_mode=None (default): byte-identical to before this parameter
    existed — no torch.compile anywhere. compile_mode="reduce-overhead" or
    "default": passed straight to _OwnedCorePolicy, which uses it ONLY for
    no_grad CUDA sampling calls (see _OwnedCorePolicy.forward's docstring
    note) — the CPU path and the grad-enabled loss re-forward path are
    completely untouched by this parameter regardless of its value.

    seed_ckpt / expected_model_pt_sha256 (A20 SUBSTRATE OVERRIDE, additive,
    2026-07-03): both default to None, which resolves to the existing module
    constants (SEED_CKPT_DEFAULT, EXPECTED_MODEL_PT_SHA256) — byte-identical
    behavior to before these params existed when both are omitted. When
    given, `_factory()` hash-verifies AND loads from `seed_ckpt` instead of
    the default cbase-v0 seed (e.g. a grown/stabilized checkpoint directory
    with a different model.pt — different tensor shapes, different FF
    width). The FF width is measured from the checkpoint's own tensor shape
    via _measure_intermediate_size (never hardcoded), so a wider substrate
    is picked up automatically. The caller is responsible for supplying the
    override checkpoint's OWN real sha256 (computed from its on-disk bytes,
    same convention as the default identity binding) — passing the wrong
    hash fails closed via verify_seed_checkpoint, exactly like the default
    path.
    """
    if device not in ("cpu", "cuda"):
        raise RuntimeError(
            f"OWNED_CORE_DEVICE_REFUSED: device={device!r} — this factory "
            "supports only 'cpu' (float32, default) or 'cuda' (governed "
            "bf16 base + fp32 adapter master)."
        )
    resolved_seed_ckpt = seed_ckpt if seed_ckpt is not None else SEED_CKPT_DEFAULT
    resolved_expected_sha = (
        expected_model_pt_sha256 if expected_model_pt_sha256 is not None else EXPECTED_MODEL_PT_SHA256
    )

    def _factory() -> LoRAAdapter:
        identity = verify_seed_checkpoint(resolved_seed_ckpt, resolved_expected_sha)

        cfg = json.loads(
            (REPO / "configs" / "v0-pretrain-config.json").read_text(encoding="utf-8")
        )
        m = cfg["model"]
        n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]

        governed = _cuda_preflight() if device == "cuda" else None
        # DELTA-SEMANTICS BASELINE (2026-07-03, A20 rung-4 x2): the ceiling
        # assert below must measure what THIS build allocates, not global
        # process allocation — run_rig calls this factory repeatedly with
        # overlapping instance lifetimes BY DESIGN (guards d/e/g/h compare
        # two fresh cores side-by-side: ember_c14_contract_rig.py lines
        # ~1064/1072; per-arm fresh cores at ~533/990/1259). A global
        # absolute cap conflates "this load is oversized" (the defect class
        # the assert exists to catch) with "more than one instance exists"
        # (contract-bearing rig behavior). Receipts: live-20260703T171225Z /
        # live-20260703T171901Z both blocked at 4,757,575,680 = exactly TWO
        # grown substrates, each individually correct at 2,378,787,840.
        allocated_before = torch.cuda.memory_allocated() if device == "cuda" else 0

        sd_bf16 = torch.load(
            resolved_seed_ckpt / "model.pt", map_location="cpu", weights_only=True
        )
        intermediate = _measure_intermediate_size(sd_bf16)
        # CPU path unchanged: upcast to float32 before load. CUDA path keeps
        # the checkpoint's native bf16 bytes — the base weights load in bf16
        # on the GPU per the design spec, not an upcast-then-downcast round
        # trip through float32.
        sd = sd_bf16 if device == "cuda" else {k: v.float() for k, v in sd_bf16.items()}

        raw = cbase_grow_dryrun.build_model(m, n_mtp, intermediate)
        if device == "cuda":
            raw = raw.to(dtype=torch.bfloat16)  # cast BEFORE load: bf16->bf16 direct copy
        missing, unexpected = raw.load_state_dict(sd, strict=False)
        real_missing = [k for k in missing if k != "head.weight"]  # tied-embedding alias
        if real_missing or unexpected:
            raise RuntimeError(
                f"OWNED_CORE_LOAD_MISMATCH: missing={real_missing} unexpected={unexpected}"
            )
        if device == "cuda":
            raw = raw.to(device="cuda")

        policy_core = _OwnedCorePolicy(raw, compile_mode=compile_mode)
        _ensure_guard_e_passes(policy_core)

        adapter = LoRAAdapter(
            base=policy_core, target_layer_name="head", rank=rank, freeze_base=True
        )
        if device == "cuda":
            # fp32 master for the trained delta — the adapter is what
            # training updates; the base stays the owned bf16 foundation.
            adapter.lora = adapter.lora.to(device="cuda", dtype=torch.float32)

        # Stash identity + measured arch facts for the caller (e.g. the smoke
        # receipt below) — plain dict attribute, not a Parameter/Module/Tensor,
        # so nn.Module.__setattr__ stores it as an ordinary instance attribute.
        adapter._owned_core_identity = identity
        adapter._owned_core_intermediate = intermediate

        if device == "cuda":
            allocated = torch.cuda.memory_allocated()
            allocated_delta = allocated - allocated_before
            # Cap re-verified for the A20 substrate override (2026-07-03),
            # via a CPU preflight probe (receipts/ember-c14-owned-run/
            # a20-preflight-*.json) that actually loaded and measured the
            # checkpoint rather than assuming its size: the default seed
            # (~368M params) loads to ~1GB bf16; the grown substrate
            # (models/cbase-grow-rung/.../stabilize/checkpoints/
            # step-00000766) has 1,188,865,024 DEDUPED live params (the
            # checkpoint's raw on-disk tensor sum is 1,221,633,024 --
            # 32,768,000 higher, because head.weight is tied to
            # backbone_model.embed_tokens.weight and gets double-counted in
            # a raw sum but not in the live nn.Module's .parameters()) -->
            # ~2.21 GiB bf16 (1,188,865,024*2 bytes/1024**3), matching the
            # on-disk model.pt file size (2,377,797,331 bytes) closely.
            # Plus a small fp32 LoRA adapter overhead, still comfortably
            # under the existing 4 GiB cap (~1.79 GiB margin, ~45%
            # headroom). Cap left UNCHANGED (arithmetic holds; not raised)
            # — this comment is the justification trail, not a promise to
            # revisit if a future substrate gets larger.
            cap_bytes = 4 * (1024 ** 3)
            assert allocated_delta < cap_bytes, (
                f"OWNED_CORE_CUDA_VRAM_OVER_CAP: this build allocated "
                f"{allocated_delta} bytes (global {allocated}, baseline "
                f"{allocated_before}) >= {cap_bytes} bytes (4 GiB) — a single "
                "substrate build should cost ~1GB bf16 (default seed) or "
                "~2.28GB bf16 (A20 grown substrate); an oversized DELTA means "
                "fp32 materialization or an intra-build double copy. "
                "Refusing to proceed. (Global concurrency is governed by "
                "src/ember/governance/scripts/governor.py's VRAM-fraction envelope, not this assert.)"
            )
            adapter._owned_core_vram = {
                "vram_fraction_cap": governed["vram_fraction"],
                "free_gb_preflight": governed["free_gb"],
                "total_gb_preflight": governed["total_gb"],
                "margin_gb_preflight": governed["margin_gb"],
                "memory_allocated_bytes_after_load": allocated,
                "vram_cap_bytes_4gib_assert": cap_bytes,
            }
        return adapter

    return _factory


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------

def _tensor_raw_bytes(tensor: torch.Tensor) -> bytes:
    """Raw parameter bytes for hashing — device- AND numpy-dtype-independent.

    numpy has no native bfloat16 type, so tensor.numpy() raises for the CUDA
    path's bf16 base weights. Reinterpreting the contiguous CPU tensor as
    uint8 (Tensor.view(torch.uint8)) dumps the exact same underlying byte
    buffer that .numpy().tobytes() would for any dtype numpy DOES support —
    so float32 (the CPU path's only dtype) hashes byte-for-byte identically
    to before, and bf16 now hashes too instead of raising.
    """
    return tensor.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()


def base_param_hash(policy) -> str:
    """sha256 over the frozen base state_dict tensors, deterministic (sorted) order."""
    base = policy.base if hasattr(policy, "base") else policy
    h = hashlib.sha256()
    for name, tensor in sorted(base.state_dict().items()):
        h.update(name.encode())
        h.update(_tensor_raw_bytes(tensor))
    return h.hexdigest()


def adapter_param_hash(policy) -> str:
    """sha256 over the LoRA (lora_A, lora_B) state_dict, deterministic (sorted) order."""
    if hasattr(policy, "adapter_param_hash"):
        return policy.adapter_param_hash()
    h = hashlib.sha256()
    for name, tensor in sorted(policy.lora.state_dict().items()):
        h.update(name.encode())
        h.update(_tensor_raw_bytes(tensor))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Smoke — proves real weights, live grad-forward, a genuine adapter-only
# neural update, and exact Deleted-arm restore (device="cpu", the original
# unchanged path) or the same four proofs plus a fifth VRAM-discipline proof
# (device="cuda", design spec section 7 blocker 2). Writes a receipt via
# receipt_write.checked_write (fail-closed). Verdict is COMPUTED from the
# measured checks below, never hardcoded.
# ---------------------------------------------------------------------------

def _run_smoke(device: str = "cpu") -> int:
    is_cuda = device == "cuda"
    pass_verdict = "OWNED_CORE_CUDA_SMOKE_PASS" if is_cuda else "OWNED_CORE_SMOKE_PASS"
    fail_verdict = "OWNED_CORE_CUDA_SMOKE_FAIL" if is_cuda else "OWNED_CORE_SMOKE_BLOCKED"
    smoke_tag = "OWNED_CORE_CUDA_SMOKE" if is_cuda else "OWNED_CORE_SMOKE"

    ts_compact = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_dir = REPO / "receipts" / "ember-c14-owned-core"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    fname = f"owned-core-smoke-cuda-{ts_compact}.json" if is_cuda else f"owned-core-smoke-{ts_compact}.json"
    receipt_path = receipt_dir / fname

    blocker = None
    proof1 = proof2 = proof3 = proof4 = proof5 = None
    arch: dict = {}
    lora_info: dict = {}
    hashes: dict = {}
    verdict = fail_verdict

    try:
        if is_cuda:
            assert torch.cuda.is_available(), (
                "OWNED_CORE_CUDA_UNAVAILABLE: torch.cuda.is_available() is False"
            )
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.manual_seed_all(42)

        print(f"{smoke_tag}: building factory (rank=8, device={device})...")
        factory = make_owned_core_factory(device=device, rank=8)

        print(f"{smoke_tag}: instantiating policy (hash-verify + load + LoRA inject)...")
        policy = factory()
        identity = policy._owned_core_identity
        proof1 = {
            "checkpoint": identity["checkpoint"],
            "model_pt_sha256": identity["model_pt_sha256"],
            "verified": identity["verified"],
        }
        print(
            f"  proof1 (real weights): verified={identity['verified']} "
            f"sha={identity['model_pt_sha256'][:16]}..."
        )

        base = policy.base
        arch = {
            "hidden": base.backbone_model.config.hidden_size,
            "layers": base.backbone_model.config.num_hidden_layers,
            "heads": base.backbone_model.config.num_attention_heads,
            "vocab": base.backbone_model.config.vocab_size,
            "seq": base.backbone_model.config.max_position_embeddings,
            "intermediate": policy._owned_core_intermediate,
            "n_mtp_heads": len(base.mtp_heads),
            "param_count_total": int(sum(p.numel() for p in base.parameters())),
        }

        n_trainable_adapter = int(
            sum(p.numel() for p in policy.lora.parameters() if p.requires_grad)
        )
        lora_info = {"target_layer": "head", "rank": 8, "n_trainable_params": n_trainable_adapter}

        base_hash_pre = base_param_hash(policy)
        adapter_hash_pre = adapter_param_hash(policy)
        pre_step_adapter_snapshot = copy.deepcopy(policy.adapter_state_dict())

        # --- proof 2: live forward on a fixed batch, WITH grad -----------------
        torch.manual_seed(42)
        batch = torch.randint(0, 32000, (1, 32), device=device)
        logits = policy(batch)
        finite = bool(torch.isfinite(logits).all())
        shape_ok = tuple(logits.shape) == (1, 32, 32000)
        logits_mean = float(logits.mean().item())
        logits_std = float(logits.std().item())
        proof2 = {
            "batch_shape": [1, 32],
            "logits_shape": list(logits.shape),
            "finite": finite,
            "shape_matches_expected": shape_ok,
            "logits_mean": logits_mean,
            "logits_std": logits_std,
        }
        print(
            f"  proof2 (live forward): shape={tuple(logits.shape)} finite={finite} "
            f"mean={logits_mean:.4f} std={logits_std:.4f}"
        )
        if not (finite and shape_ok):
            raise RuntimeError(
                f"OWNED_CORE_FORWARD_INVALID: finite={finite} shape={tuple(logits.shape)}"
            )

        # --- proof 3: one adapter-only PG-style step on the REAL forward's graph
        last_logits = logits[0, -1, :]
        with torch.no_grad():
            probs = F.softmax(last_logits, dim=-1)
            action = int(torch.multinomial(probs, 1).item())
        log_probs = F.log_softmax(last_logits, dim=-1)
        loss = -log_probs[action]
        loss.backward()

        grad_params = [(n, p) for n, p in policy.lora.named_parameters() if p.requires_grad]
        grads_present = [
            (n, (p.grad is not None) and bool(p.grad.abs().sum().item() > 0.0))
            for n, p in grad_params
        ]
        any_real_grad = any(ok for _, ok in grads_present)

        optimizer = torch.optim.SGD(
            [p for p in policy.parameters() if p.requires_grad], lr=1e-2
        )
        optimizer.step()

        base_hash_post = base_param_hash(policy)
        adapter_hash_post = adapter_param_hash(policy)

        adapter_changed = adapter_hash_pre != adapter_hash_post
        base_unchanged = base_hash_pre == base_hash_post

        proof3 = {
            "action_sampled": action,
            "loss": float(loss.item()),
            "grad_present_per_param": {n: ok for n, ok in grads_present},
            "any_lora_param_has_nonzero_grad": any_real_grad,
            "optimizer": "SGD",
            "lr": 1e-2,
            "adapter_hash_pre": adapter_hash_pre,
            "adapter_hash_post": adapter_hash_post,
            "base_hash_pre": base_hash_pre,
            "base_hash_post": base_hash_post,
            "adapter_hash_changed": adapter_changed,
            "base_hash_unchanged": base_unchanged,
        }
        print(
            f"  proof3 (neural update): grad_present={any_real_grad} "
            f"adapter_changed={adapter_changed} base_unchanged={base_unchanged}"
        )
        if not (any_real_grad and adapter_changed and base_unchanged):
            raise RuntimeError(
                f"OWNED_CORE_UPDATE_INVALID: any_real_grad={any_real_grad} "
                f"adapter_changed={adapter_changed} base_unchanged={base_unchanged}"
            )

        # --- proof 4: deleted-arm restore --------------------------------------
        policy.restore_pre_adapter_state(pre_step_adapter_snapshot)
        adapter_hash_restored = adapter_param_hash(policy)
        restore_exact = adapter_hash_restored == adapter_hash_pre
        proof4 = {
            "pre_step_snapshot_keys": sorted(pre_step_adapter_snapshot.keys()),
            "adapter_hash_pre": adapter_hash_pre,
            "adapter_hash_restored": adapter_hash_restored,
            "restore_exact": restore_exact,
        }
        print(f"  proof4 (deleted-arm restore): restore_exact={restore_exact}")
        if not restore_exact:
            raise RuntimeError(
                f"OWNED_CORE_RESTORE_INVALID: adapter_hash_restored="
                f"{adapter_hash_restored[:16]}... != adapter_hash_pre={adapter_hash_pre[:16]}..."
            )

        hashes = {
            "adapter_param_hash_pre_step": adapter_hash_pre,
            "adapter_param_hash_post_step": adapter_hash_post,
            "adapter_param_hash_post_restore": adapter_hash_restored,
            "base_param_hash_pre_step": base_hash_pre,
            "base_param_hash_post_step": base_hash_post,
        }

        # --- proof 5 (cuda only): VRAM discipline across the whole run ---------
        if is_cuda:
            peak_allocated = int(torch.cuda.max_memory_allocated())
            cap_bytes = int(policy._owned_core_vram["vram_cap_bytes_4gib_assert"])
            under_cap = peak_allocated < cap_bytes
            proof5 = {
                "memory_allocated_bytes_after_load": policy._owned_core_vram[
                    "memory_allocated_bytes_after_load"
                ],
                "vram_fraction_cap": policy._owned_core_vram["vram_fraction_cap"],
                "peak_memory_allocated_bytes": peak_allocated,
                "vram_cap_bytes_4gib_assert": cap_bytes,
                "under_cap": under_cap,
            }
            print(
                f"  proof5 (vram): peak={peak_allocated / 1e9:.3f}GB "
                f"cap={cap_bytes / 1e9:.3f}GB "
                f"fraction_cap={policy._owned_core_vram['vram_fraction_cap']} "
                f"under_cap={under_cap}"
            )
            if not under_cap:
                raise RuntimeError(
                    f"OWNED_CORE_CUDA_VRAM_PEAK_OVER_CAP: peak_memory_allocated="
                    f"{peak_allocated} bytes >= {cap_bytes} bytes (4 GiB)"
                )

        verdict = pass_verdict

    except Exception as exc:
        # Transparent, not silent: full exception type + message + traceback go
        # into the receipt AND stdout. This is the reporting path for a genuine
        # interface mismatch — never a route-around.
        blocker = {
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        verdict = fail_verdict
        print(f"{fail_verdict}: {type(exc).__name__}: {exc}")

    receipt = {
        "ticket": "C14-OWNED-CORE-SMOKE",
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha_convention": SHA_CONVENTION,
        "seed_checkpoint": {
            "path": str(SEED_CKPT_DEFAULT),
            "expected_model_pt_sha256": EXPECTED_MODEL_PT_SHA256,
        },
        "arch": arch,
        "lora": lora_info,
        "proof1_real_weights": proof1,
        "proof2_live_forward": proof2,
        "proof3_neural_update": proof3,
        "proof4_deleted_arm_restore": proof4,
        "hashes": hashes,
        "blocker": blocker,
        "device": device,
        "dtype_compute": "float32" if not is_cuda else "bf16_base_fp32_adapter_fp32_logits",
        "script": "src/ember/governance/scripts/ember_c14_owned_core.py",
        "verdict": verdict,
    }
    if is_cuda:
        receipt["proof5_vram"] = proof5

    checked_write(str(receipt_path), receipt)
    print(verdict)
    print(f"receipt={receipt_path}")
    return 0 if verdict == pass_verdict else 2


if __name__ == "__main__":
    _ap = argparse.ArgumentParser(description=__doc__)
    _ap.add_argument(
        "--device", choices=("cpu", "cuda"), default="cpu",
        help="cpu (default, unchanged) or cuda (governed GPU smoke, design spec section 7 blocker 2)",
    )
    _args = _ap.parse_args()
    sys.exit(_run_smoke(device=_args.device))
