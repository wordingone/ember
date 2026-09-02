#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_c_e2b_e2b_arm.py -- E2B ember_work-arm training harness (issue #23,
diff-list area 1: "No producer function exists yet for 'train E2B's head-LoRA
for N steps then eval' -- this is genuinely new code, not a parameter tweak").

Per docs/domains/governance/spec/e2b-paired-protocol-v1.md v1.1 clause 1: the E2B arm of the
ember_work leg must receive the SAME iGRPO/LoRA training procedure fire-4's
owned arm used (N=4, M=4, max_depth=1, epsilon=0.2, temperature=1.5, 1024
steps, 16 checkpoint evals every 64 steps), at E2B's head linear via the
non-mutating LoRAAdapter wrapper (v1.2 clause 2) -- NEVER a merge, so the
tied lm_head/embed_tokens hazard (v1.2's mechanism correction) never applies.

THE GENUINE GAP this module closes: every existing igrpo/rlm mechanism
(ember_resident_igrpo.py, never edited here) hard-codes the convenience that
Ember's OWN tokenizer places the 10 action-band tokens (digits 0-7 + FINAL=8
+ RECURSE=9) at RAW TOKEN IDS 0-9 -- an accident of Ember's vocab layout, not
a property of the mechanism (see ember_c14_owned_run.py::_ActionBandPolicy's
own docstring: "LOAD-BEARING INTERFACE-MISMATCH RESOLUTION -- discovered
empirically"). E2B's tokenizer has no such convenience: its raw ids 0-9 are
whatever they are (almost certainly not digit tokens). _RemappedActionBandPolicy
below is the bridge -- it discovers the REAL E2B token ids for the strings
"0".."9" once (via the tokenizer, never assumed), and translates every
abstract action-int (0-9) crossing the policy boundary (context construction,
sampled actions, forward-pass logits) through that lookup, so
igrpo_stage1/igrpo_stage2/igrpo_loss/train_one_step (none edited by this
module) see EXACTLY the same (batch, seq, 10) contract they already expect
from Ember's own core -- E2B is presented as if its native vocab were also
size-10, without ever touching ember_resident_igrpo.py.

Reuses, never reimplements: resident_adapter.LoRAAdapter (the proven-safe
head-linear wrapper -- see scratch/c-e2b-merge/e2b_lora_attach_probe_v2_head.py,
verdict HEAD_LORA_ATTACH_AND_ZERO_LR_BACKWARD_OK_TIED_TENSOR_UNTOUCHED),
ember_phase3_c14.igrpo_trainer.train_one_step (the single trainable-update
authority fire-4's own --live run called), ember_c14_owned_run._ActionBandPolicy
(subclassed, not copied -- sample_action/log_prob_sequence/forward's outer
shape are inherited unchanged), ember_c14_owned_run._make_checkpoint_eval_callback
and _eval_one_task (the SAME greedy temperature=0.0 eval every other arm uses).

The training LOOP itself (this module's other genuinely new piece) mirrors
ember_c14_contract_rig.py::_stub_eval_arm_C_and_deleted's C-arm loop shape
(lines 541-577) -- cycle train_tasks, call train_one_step, fire the
checkpoint callback at the interval -- WITHOUT dragging in that function's
Arm A/B/Deleted apparatus, which is Ember's OWN internal ablation study and
not part of what the v1 protocol asks the E2B arm to do (train once, eval
periodically, report the final battery score).

Rails: no GPU allocation anywhere in this file (device is whatever the
caller's e2b_model already lives on); no commits; importable and fully
exercisable against a CPU stub model (see cmd_dry_run's stub in
ember_c_e2b_paired_run.py) without ever touching the real ~9.6GB E2B
safetensors.
"""
from __future__ import annotations

import copy
import itertools
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional

import torch

_SCRIPT_DIR = Path(__file__).resolve().parent
_PHASE3_DIR = _SCRIPT_DIR / "ember_phase3_c14"
for _p in (_SCRIPT_DIR, _PHASE3_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

BAND = 10  # 0-7 digit actions, 8=FINAL, 9=RECURSE -- ember_resident_igrpo.VOCAB_SIZE

# Documented EXPECTED LoRA compute dtype (assertion aid, not an active
# cast -- see attach_e2b_lora() and resident_adapter.LoRALayer.forward()
# for where dtype actually gets handled). ember_c_e2b_paired_run.py::
# load_e2b_model() explicitly loads E2B's real weights at dtype=torch.
# bfloat16; resident_adapter.LoRALayer's lora_A/lora_B are constructed
# with no dtype argument at all (torch.empty/torch.zeros default to fp32).
# A GATE-0 --live re-fire hit exactly this mismatch 2026-07-04 at
# resident_adapter.py:119 (scratch/gate0-live-20260704b.log has the
# trace); this file's FIRST cure attempt blanket-cast the whole attached
# policy (base + LoRA) to one dtype, which the maintainer rejected on
# adjudication: it silently upcasts E2B's real bf16 weights to fp32
# (doubling ~9.6GB to ~19.2GB, and drifting from the checkpoint's pinned
# native precision). The ACTUAL fix (PEFT-style boundary cast) lives in
# LoRALayer.forward() itself: the base stays at its loaded dtype, the
# LoRA layer stays at its own construction dtype (this constant), and
# forward() casts across that boundary internally per call. This constant
# now exists only so a future drift in LoRALayer.__init__'s construction
# default is caught by the assertion in train_e2b_ember_work_arm() below,
# not to drive a cast anywhere in this file.
E2B_TRAIN_COMPUTE_DTYPE = torch.float32


class E2BDigitTokenNotSingleToken(RuntimeError):
    """Raised when the base tokenizer does not encode some digit string
    "0".."9" as EXACTLY one token -- fails closed rather than silently
    building an action band over a multi-token (or zero-token) string,
    which would corrupt every action's identity."""


def discover_action_token_ids(tokenizer) -> List[int]:
    """Return the 10 real token ids for the strings "0".."9", in that order,
    for whatever `tokenizer` the base model actually uses.

    Convention (deliberately uniform, imposes no Ember-specific vocabulary
    meaning on the foreign model): action i in 0..7 maps to the token for
    str(i); action 8 (FINAL) and action 9 (RECURSE) map to the tokens for
    "8" and "9" respectively -- the SAME ten single-digit strings any
    reasonable tokenizer represents as single tokens, carrying the SAME
    control meaning Ember's own accidental digit-id layout happens to give
    them. Verified, never assumed: each string must encode to exactly one
    token id, or this raises E2BDigitTokenNotSingleToken naming the offender
    (fail-closed -- an ambiguous or multi-token digit would silently corrupt
    every downstream action's identity).
    """
    ids: List[int] = []
    for digit in range(BAND):
        s = str(digit)
        encoded = tokenizer.encode(s, add_special_tokens=False)
        if hasattr(encoded, "ids"):  # tokenizers.Tokenizer.encode -> Encoding
            encoded = encoded.ids
        if len(encoded) != 1:
            raise E2BDigitTokenNotSingleToken(
                f"E2B_DIGIT_TOKEN_NOT_SINGLE_TOKEN: base tokenizer encodes "
                f"{s!r} as {len(encoded)} token(s) ({encoded!r}), expected "
                f"exactly 1 -- cannot build a 10-token action band from a "
                f"multi-token digit string. This must be resolved (e.g. by "
                f"a different digit representation) before this base model "
                f"can serve as the E2B ember_work arm."
            )
        ids.append(int(encoded[0]))
    if len(set(ids)) != BAND:
        raise E2BDigitTokenNotSingleToken(
            f"E2B_DIGIT_TOKEN_IDS_COLLIDE: discovered action token ids are "
            f"not all distinct: {ids!r} -- two different digit strings "
            f"encoded to the same token id, which would make two distinct "
            f"actions indistinguishable to the policy."
        )
    return ids


class _RemappedActionBandPolicy:
    """Generalizes ember_c14_owned_run._ActionBandPolicy to a foreign base
    model/tokenizer whose native vocab does NOT place the action-band tokens
    at raw ids 0..9 (see this module's docstring for why that placement is
    an accident of Ember's own tokenizer, not a property of the mechanism
    every other igrpo/rlm function assumes).

    Composition, not subclassing: earlier drafts of this class subclassed
    _ActionBandPolicy directly, but its own __deepcopy__ override (needed by
    igrpo_step/train_one_step, which copy.deepcopy(policy) every step to
    snapshot pi_theta_old) hard-codes construction of a PLAIN
    `_ActionBandPolicy(...)` in its fallback branch for any base shape other
    than LoRAAdapter(_OwnedCorePolicy) -- silently dropping this class's own
    `_action_token_ids` and reverting to unmapped (wrong) behaviour for the
    ref-policy snapshot every single training step. Composition avoids
    inheriting that trap: this class owns its OWN __deepcopy__, so a
    reconstructed ref-policy is always the correct type with the correct
    mapping.
    """

    def __init__(self, base_lora_adapter, action_token_ids: List[int], band: int = BAND):
        if len(action_token_ids) != band:
            raise ValueError(
                f"action_token_ids must have exactly {band} entries, got {len(action_token_ids)}"
            )
        self.base = base_lora_adapter
        self.band = band
        self._action_token_ids = action_token_ids

    # -- module-parameter delegation (train_one_step/igrpo_step read these
    #    directly off `policy`, never assuming a specific wrapper type) ----
    def parameters(self, *a, **kw):
        return self.base.parameters(*a, **kw)

    def named_parameters(self, *a, **kw):
        return self.base.named_parameters(*a, **kw)

    def state_dict(self, *a, **kw):
        return self.base.state_dict(*a, **kw)

    def load_state_dict(self, *a, **kw):
        return self.base.load_state_dict(*a, **kw)

    def train(self, mode: bool = True):
        self.base.train(mode)
        return self

    def eval(self):
        self.base.eval()
        return self

    def adapter_state_dict(self):
        return self.base.adapter_state_dict()

    def adapter_param_hash(self):
        return self.base.adapter_param_hash()

    def restore_pre_adapter_state(self, pre_snapshot) -> None:
        self.base.restore_pre_adapter_state(pre_snapshot)

    def _base_device(self):
        try:
            import torch  # noqa: E402
            return next(self.base.parameters()).device
        except StopIteration:
            import torch  # noqa: E402
            return torch.device("cpu")

    def _to_base_device(self, x):
        import torch  # noqa: E402
        return x.to(self._base_device()) if isinstance(x, torch.Tensor) else x

    @staticmethod
    def _unwrap_logits(raw_output):
        return raw_output.logits if hasattr(raw_output, "logits") else raw_output

    def _remap_to_real(self, ids):
        import torch  # noqa: E402
        idx = torch.as_tensor(self._action_token_ids, dtype=torch.long, device=ids.device)
        return idx[ids.long()]

    # -- the interface igrpo_stage1/igrpo_stage2/igrpo_loss/train_one_step
    #    actually call on `policy` --------------------------------------

    def __call__(self, *args, **kwargs):
        return self.forward(*args, **kwargs)

    def forward(self, *args, **kwargs):
        """policy.forward(full_input)[0] contract (ember_resident_igrpo.py
        ~line 1361): full_input is (1, seq) of ABSTRACT action-ints (0-9);
        must return (1, seq, band) logits over those same 10 abstract slots,
        gradient-tracked."""
        import torch  # noqa: E402

        if not args:
            raise TypeError("_RemappedActionBandPolicy.forward() requires the context tensor")
        ctx = args[0]
        real_ctx = self._to_base_device(self._remap_to_real(ctx))
        out = self.base(real_ctx, *args[1:], **kwargs)
        full_logits = self._unwrap_logits(out)
        real_ids = self._to_base_device(torch.as_tensor(self._action_token_ids, dtype=torch.long))
        band_logits = full_logits.index_select(-1, real_ids)
        return band_logits.to("cpu")

    def sample_action(self, context_ids, temperature: float = 1.0) -> int:
        import torch  # noqa: E402

        if not isinstance(context_ids, torch.Tensor):
            context_ids = torch.as_tensor(context_ids, dtype=torch.long)
        with torch.no_grad():
            band_logits = self._sample_step_logits(context_ids)
        if temperature <= 0:
            return int(band_logits.argmax().item())
        probs = torch.nn.functional.softmax(band_logits / max(temperature, 1e-6), dim=-1)
        return int(torch.multinomial(probs, 1).item())

    def _sample_step_logits(self, context_ids):
        """Last-position band logits for sample_action -- no KV-cache fast
        path (that optimization in _ActionBandPolicy is gated on the owned
        core's forward_step, which E2B's raw HF model does not expose;
        correctness over speed here, matching this module's CPU-dry-run/
        GPU-single-job scope, not a hot per-token sampling loop at scale)."""
        real_ctx = self._to_base_device(self._remap_to_real(context_ids)).unsqueeze(0)
        out = self.base(real_ctx)
        full_logits = self._unwrap_logits(out)
        last = full_logits[0, -1, :]
        import torch  # noqa: E402
        real_ids = self._to_base_device(torch.as_tensor(self._action_token_ids, dtype=torch.long))
        return last.index_select(0, real_ids).to("cpu")

    def log_prob_sequence(self, *args, **kwargs):
        # Verified DEAD on the real training path (ember_resident_igrpo.py's
        # igrpo_loss computes log-probs inline via policy.forward(...)[0] +
        # gather, never via this method -- grepped, no call site outside
        # TinyPolicyTransformer's own standalone tests). Kept as a named,
        # honest refusal rather than a silently-wrong implementation.
        raise AttributeError(
            "_RemappedActionBandPolicy.log_prob_sequence() is intentionally "
            "unimplemented -- verified unused by igrpo_loss/igrpo_stage1/"
            "igrpo_stage2's actual training computation (they call "
            "policy.forward(...)[0] directly); if a future caller needs it, "
            "that verification must be redone first."
        )

    def __deepcopy__(self, memo: dict) -> "_RemappedActionBandPolicy":
        if id(self) in memo:
            return memo[id(self)]

        # Fail-closed rail (issue #48 cure spec, 2026-07-04): the ONLY
        # requires_grad=True tensors anywhere under self.base (the
        # LoRAAdapter) must be the attached LoRA layer's own parameters
        # ("lora.lora_A"/"lora.lora_B"). If anything else is trainable,
        # refuse -- sharing frozen storage below would silently corrupt
        # the pi_old snapshot for a base that ISN'T actually fully frozen.
        trainable_outside_lora = [
            name for name, p in self.base.named_parameters()
            if p.requires_grad and not name.startswith("lora.")
        ]
        if trainable_outside_lora:
            raise RuntimeError(
                "_RemappedActionBandPolicy.__deepcopy__ refuses to memo-share "
                f"frozen storage: found requires_grad=True parameter(s) "
                f"outside the LoRA attach point: {trainable_outside_lora}. "
                "Sharing would silently corrupt the pi_old snapshot."
            )

        # Pre-seed the memo: every frozen (requires_grad=False) Parameter/
        # buffer of self.base maps to ITSELF. copy.deepcopy honors memo
        # identity-mapping, so these tensors' STORAGE is SHARED between
        # pi_old and the live policy instead of genuinely copied --
        # train_one_step's per-step pi_old snapshot was doing an
        # O(full-model) ~4.7GB memcpy every one of 1056 steps on a base
        # that is FROZEN by protocol (never trained), a hard OOM refusal
        # under concurrent build-lane load and pure waste even where it
        # fit. Only the trainable LoRA adapter genuinely deep-copies --
        # exactly the pi_old semantics train_one_step needs: the snapshot
        # differs from the live policy ONLY in the weights training
        # actually changes.
        for t in itertools.chain(self.base.parameters(), self.base.buffers()):
            if not getattr(t, "requires_grad", False):
                memo[id(t)] = t

        new_base = copy.deepcopy(self.base, memo)
        new_policy = _RemappedActionBandPolicy(
            new_base, action_token_ids=list(self._action_token_ids), band=self.band
        )
        memo[id(self)] = new_policy
        return new_policy


def attach_e2b_lora(e2b_model, action_token_ids: List[int], rank: int = 8) -> _RemappedActionBandPolicy:
    """Attach a fresh, zero-effect LoRA at e2b_model's head linear (the
    non-mutating wrapper mechanism -- v1.2 clause 2; proven safe against the
    tied lm_head/embed_tokens hazard by
    scratch/c-e2b-merge/e2b_lora_attach_probe_v2_head.py) and wrap the result
    in the action-band remap bridge."""
    from resident_adapter import LoRAAdapter  # noqa: E402

    # No cast here (maintainer adjudication, 2026-07-04, supersedes this
    # function's first cure attempt): the frozen base stays EXACTLY at
    # whatever dtype its caller loaded it (E2B's checkpoint-native bf16 via
    # load_e2b_model() -- pin preserved, memory unchanged). LoRALayer's own
    # parameters stay fp32-by-default (resident_adapter.LoRALayer.__init__)
    # so the adapter's Adam optimizer state is never computed at bf16
    # (bf16's 8 mantissa bits + eps-swamping would add optimizer noise to
    # exactly the signal a surpass-vs-e2b gate measures -- the worst place
    # to lose precision). The dtype boundary between the two now lives
    # inside LoRALayer.forward() itself (resident_adapter.py) -- a PEFT-
    # style cast-in/compute/cast-out at the LoRA math's own edge, not here.
    lora_adapter = LoRAAdapter(e2b_model, target_layer_name="lm_head", rank=rank, freeze_base=True)
    return _RemappedActionBandPolicy(lora_adapter, action_token_ids=action_token_ids, band=BAND)


def run_e2b_training_loop(
    policy: _RemappedActionBandPolicy,
    optimizer,
    train_tasks: list,
    n_train_steps: int,
    checkpoint_callback: Optional[Callable[[int, Any], None]] = None,
    checkpoint_interval: Optional[int] = None,
    igrpo_n: int = 4,
    igrpo_m: int = 4,
    max_depth: int = 1,
    epsilon: float = 0.2,
    temperature: float = 1.5,
) -> None:
    """Mirrors ember_c14_contract_rig.py::_stub_eval_arm_C_and_deleted's
    C-arm training loop shape (lines 541-577) -- cycle train_tasks, call
    train_one_step (the SAME single trainable-update authority fire-4's own
    --live run used), fire the checkpoint callback at the interval -- WITHOUT
    that function's Arm A/B/Deleted apparatus (Ember's own internal ablation
    study, not part of what the E2B arm needs). Hyperparameters (N=4, M=4,
    max_depth=1, epsilon=0.2, temperature=1.5) match fire-4's own recorded
    run exactly (ember_c14_owned_run.py's cmd_live _train_fn defaults) for
    genuine procedural parity between the two arms, per v1.1 clause 1."""
    from igrpo_trainer import train_one_step  # noqa: E402

    for step_idx in range(n_train_steps):
        task = train_tasks[step_idx % len(train_tasks)]
        extra_kwargs = {"exemplars": task.exemplars} if getattr(task, "exemplars", None) is not None else {}
        train_one_step(
            policy=policy,
            state_val=task.state_val,
            optimizer=optimizer,
            N=igrpo_n,
            M=igrpo_m,
            max_depth=max_depth,
            beta=0.0,
            temperature=temperature,
            epsilon=epsilon,
            assert_changed=False,
            **extra_kwargs,
        )
        if checkpoint_callback is not None and checkpoint_interval:
            step_num = step_idx + 1
            if step_num % checkpoint_interval == 0:
                checkpoint_callback(step_num, policy)


def train_e2b_ember_work_arm(
    e2b_model,
    e2b_tokenizer,
    corpus,
    verifier: Callable,
    n_train_steps: int,
    checkpoint_interval: int,
    lr: float = 1e-3,
    rank: int = 8,
    igrpo_n: int = 4,
    igrpo_m: int = 4,
    max_depth: int = 1,
    epsilon: float = 0.2,
    temperature: float = 1.5,
) -> dict:
    """Orchestrates the whole E2B ember_work arm: discover the action-token
    mapping from e2b_tokenizer, attach LoRA at the head linear, train
    n_train_steps with checkpoint evals every checkpoint_interval steps
    (reusing ember_c14_owned_run._make_checkpoint_eval_callback/_eval_one_task
    unchanged), then run one final full-battery eval identical in shape to
    fire-4's own recorded final row.

    Returns a dict: {action_token_ids, checkpoint_evals (list, same shape
    _CHECKPOINT_EVALS rows have), final_eval (same shape as one
    checkpoint_evals row), policy (the trained _RemappedActionBandPolicy,
    for the caller to run founder_likeness generation through)}.
    """
    import torch  # noqa: E402
    from ember_c14_owned_run import _make_checkpoint_eval_callback, _eval_one_task  # noqa: E402

    action_token_ids = discover_action_token_ids(e2b_tokenizer)
    policy = attach_e2b_lora(e2b_model, action_token_ids, rank=rank)
    optimizer = torch.optim.Adam(policy.parameters(), lr=lr)

    # Asserted, not assumed (maintainer requirement, 2026-07-04): read the
    # ACTUAL dtypes off the live policy rather than trusting a constant --
    # base_dtype echoes whatever load_e2b_model() (or a --dry-run/--smoke
    # stub) really loaded, lora_compute_dtype echoes LoRALayer's own
    # construction. Both surface in the receipt so a future drift in
    # either loader is visible, never silently assumed correct.
    lora_adapter = policy.base  # _RemappedActionBandPolicy.base -> LoRAAdapter
    base_dtype = str(next(lora_adapter.base.parameters()).dtype)
    lora_compute_dtype = str(lora_adapter.lora.lora_A.dtype)
    assert lora_compute_dtype == str(E2B_TRAIN_COMPUTE_DTYPE), (
        f"LoRALayer's default construction dtype drifted from the documented "
        f"expectation: got {lora_compute_dtype}, expected {E2B_TRAIN_COMPUTE_DTYPE}"
    )

    # Structural counts for the issue #48 deepcopy-share cure receipt field
    # (policy_snapshot_mode below): how many tensors _RemappedActionBandPolicy.
    # __deepcopy__ WILL share (frozen) vs genuinely copy (trainable LoRA) on
    # every one of train_one_step's per-step pi_old snapshots. Computed once,
    # structurally, from the attached policy -- not by actually running
    # deepcopy n_train_steps times.
    n_shared_tensors = sum(
        1 for t in itertools.chain(policy.base.parameters(), policy.base.buffers())
        if not getattr(t, "requires_grad", False)
    )
    n_copied_tensors = sum(1 for p in policy.base.parameters() if p.requires_grad)

    checkpoint_evals: list = []
    checkpoint_callback = (
        _make_checkpoint_eval_callback(corpus, verifier, checkpoint_evals)
        if checkpoint_interval else None
    )

    run_e2b_training_loop(
        policy, optimizer, corpus.train, n_train_steps,
        checkpoint_callback=checkpoint_callback, checkpoint_interval=checkpoint_interval,
        igrpo_n=igrpo_n, igrpo_m=igrpo_m, max_depth=max_depth, epsilon=epsilon, temperature=temperature,
    )

    train_rows = [
        _eval_one_task(policy, task, verifier, max_depth=0, temperature=0.0)
        for task in corpus.train
    ]
    heldout_rows = [
        _eval_one_task(policy, task, verifier, max_depth=0, temperature=0.0)
        for task in corpus.heldout
    ]
    final_eval = {
        "step": n_train_steps,
        "train_pass_count": sum(1 for r in train_rows if r["reward"] == 1.0),
        "train_total": len(train_rows),
        "heldout_pass_count": sum(1 for r in heldout_rows if r["reward"] == 1.0),
        "heldout_total": len(heldout_rows),
        "train_rows": train_rows,
        "heldout_rows": heldout_rows,
    }

    return {
        "action_token_ids": action_token_ids,
        "checkpoint_evals": checkpoint_evals,
        "final_eval": final_eval,
        "policy": policy,
        "base_dtype": base_dtype,
        "lora_compute_dtype": lora_compute_dtype,
        "policy_snapshot_mode": "frozen-base-shared",
        "n_shared_tensors": n_shared_tensors,
        "n_copied_tensors": n_copied_tensors,
    }
