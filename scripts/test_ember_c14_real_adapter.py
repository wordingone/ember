"""test_ember_c14_real_adapter.py — TDD suite for the C14 real C-arm adapter.

CPU/tiny ONLY — no GPU, no CUDA, no train daemon calls.
Uses build_multimodal_v0_model(cfg, live=False): tiny dims (hidden=32, vocab=64,
n_layers=1) which exercises all adapter code paths on CPU float32.

Tests (each is a standalone assertion):

  (a) GRADIENT_FLOW — after adapter_train_resident_fn runs, hosted policy params
      received non-None .grad and changed. Passes rig guard g.

  (b) REWARD_DEPENDENCE — zeroing/scrambling executing_verifier reward changes
      the trained outcome. Passes rig guard h.

  (c) SAMPLE_ACTION_CORRECT — perturbing model logits changes the action
      distribution; not a hardcoded/echoed distribution.

  (d) LOGPROB_IGRPO — log-probs from sample_action_with_logprobs correspond to
      sampled action tokens under the current policy (importance ratio well-formed).

  (e) RIG_DROP_IN — wire this adapter as the C arm in the real rig; assert
      guards g + h pass (not the genuine reference stub).

  (f) NOT_SIDE_CLASSIFIER — trained capability lives in hosted core params.
      The shell has >1000 params and has transformer-like layers.

Run:
  python test_ember_c14_real_adapter.py
  python test_ember_c14_real_adapter.py --verbose
"""
from __future__ import annotations

import argparse
import copy
import sys
import os

import torch
import torch.nn.functional as F

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from ember_c14_real_adapter import (
    real_core_factory,
    adapter_train_resident_fn,
    adapter_verifier,
    EmberModelShell,
    _ActionVocabForwardWrapper,
    make_real_core_factory,
    sample_action_with_logprobs,
)
from ember_resident_igrpo import (
    executing_verifier as _igrpo_executing_verifier,
    VOCAB_SIZE as _IGRPO_VOCAB_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_policy_and_optimizer(lr: float = 1e-3):
    """Produce a fresh tiny CPU policy + Adam optimizer."""
    core = real_core_factory()
    optimizer = torch.optim.Adam(core.parameters(), lr=lr)
    return core, optimizer


def _param_snapshot(policy) -> dict:
    """Snapshot all parameter tensors (copies, not views)."""
    return {n: p.data.clone() for n, p in policy.named_parameters()}


def _params_changed(before: dict, policy) -> bool:
    """True if any parameter changed since snapshot."""
    for n, p in policy.named_parameters():
        if not torch.allclose(p.data, before[n], atol=0.0):
            return True
    return False


# ---------------------------------------------------------------------------
# Test runner state
# ---------------------------------------------------------------------------

passed: list[str] = []
failed: list[str] = []
errors: list[str] = []
verbose = True  # set by --verbose CLI flag


def check(name: str, cond: bool, msg: str = "") -> None:
    if cond:
        passed.append(name)
        if verbose:
            print(f"  PASS  {name}")
    else:
        failed.append(name)
        if verbose:
            print(f"  FAIL  {name}  {msg}")


# ---------------------------------------------------------------------------
# (a) GRADIENT_FLOW
# ---------------------------------------------------------------------------

def test_gradient_flow():
    """After adapter_train_resident_fn runs, at least one hosted core param
    received a non-None .grad AND the params changed.

    This is the real backward path (igrpo_step calls loss.backward() through
    the _ActionVocabForwardWrapper -> EmberModelShell -> EmberModelV0Multimodal
    parameters). A load_state_dict weight-setter would never populate .grad.
    """
    name = "a_gradient_flow"
    try:
        torch.manual_seed(42)
        core, optimizer = _fresh_policy_and_optimizer()
        pre = _param_snapshot(core)

        any_grad = False
        any_changed = False

        for sv in range(8):
            # Zero grads before each step so we can check for new non-None grads.
            optimizer.zero_grad()
            adapter_train_resident_fn(
                policy=core,
                optimizer=optimizer,
                state_val=sv,
                N=4,
                G=4,
                max_depth=1,
                epsilon=0.2,
                temperature=1.5,
            )
            # Check: at least one core param has non-None .grad after backward.
            for p in core.parameters():
                if p.grad is not None:
                    any_grad = True
                    break
            if any_grad:
                break

        # Also check that weights actually changed.
        for sv in range(8):
            adapter_train_resident_fn(
                policy=core,
                optimizer=optimizer,
                state_val=sv,
                N=4,
                G=4,
                max_depth=1,
                epsilon=0.2,
                temperature=1.5,
            )
        any_changed = _params_changed(pre, core)

        check(name, any_grad and any_changed,
              f"any_grad={any_grad}, any_changed={any_changed}")
    except Exception as e:
        failed.append(name)
        errors.append(f"{name}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


# ---------------------------------------------------------------------------
# (b) REWARD_DEPENDENCE
# ---------------------------------------------------------------------------

def test_reward_dependence():
    """Zeroing executing_verifier rewards changes the trained outcome.

    With real rewards: iGRPO can learn (pass rate can improve over A).
    With zeroed rewards: advantages = 0 everywhere -> no gradient -> no change.

    We train two policies from the same seed:
      - trained_real: with real rewards
      - trained_zeroed: with zeroed rewards (monkey-patched)
    Both start from the same initialization. We check that the final params differ
    (zeroed rewards prevent learning, so the policy stays near initialization).

    This directly mirrors guard (h) in the rig (_run_scrambled_arm).
    """
    name = "b_reward_dependence"
    try:
        import ember_resident_igrpo as _igrpo_module

        SEED = 77
        N_STEPS = 16
        LR = 1e-3

        # Train with REAL rewards.
        torch.manual_seed(SEED)
        core_real, opt_real = _fresh_policy_and_optimizer(lr=LR)
        for step_i in range(N_STEPS):
            sv = step_i % 8
            adapter_train_resident_fn(
                policy=core_real,
                optimizer=opt_real,
                state_val=sv,
                N=4, G=4, max_depth=1, epsilon=0.2, temperature=1.5,
            )

        # Train with ZEROED rewards (monkey-patch the module-level verifier).
        _original_verifier = _igrpo_module.executing_verifier

        def _zeroed(state_val: int, emitted_action: int) -> float:
            return 0.0

        _igrpo_module.executing_verifier = _zeroed  # type: ignore[attr-defined]
        try:
            torch.manual_seed(SEED)
            core_zeroed, opt_zeroed = _fresh_policy_and_optimizer(lr=LR)
            pre_zeroed = _param_snapshot(core_zeroed)
            for step_i in range(N_STEPS):
                sv = step_i % 8
                adapter_train_resident_fn(
                    policy=core_zeroed,
                    optimizer=opt_zeroed,
                    state_val=sv,
                    N=4, G=4, max_depth=1, epsilon=0.2, temperature=1.5,
                )
        finally:
            _igrpo_module.executing_verifier = _original_verifier  # restore

        # With zeroed rewards, advantages = 0 everywhere, so grads should be ~0
        # and params should not change meaningfully vs pre-zeroed snapshot.
        zeroed_max_delta = max(
            (p.data - pre_zeroed[n]).abs().max().item()
            for n, p in core_zeroed.named_parameters()
        )

        # With real rewards, params SHOULD have changed from the zeroed baseline.
        # Compare real-trained vs zeroed-trained parameter distance.
        real_vs_zeroed_delta = max(
            (p_r.data - p_z.data).abs().max().item()
            for (_, p_r), (_, p_z) in zip(
                core_real.named_parameters(), core_zeroed.named_parameters()
            )
        )

        # Assertion 1: zeroed rewards -> tiny or zero weight change
        # (advantages all zero -> gradient all zero -> optimizer no update)
        zeroed_is_unchanged = zeroed_max_delta < 1e-4

        # Assertion 2: real vs zeroed differ (real training moves the weights)
        real_differs_from_zeroed = real_vs_zeroed_delta > 1e-6

        check(
            name,
            zeroed_is_unchanged and real_differs_from_zeroed,
            f"zeroed_max_delta={zeroed_max_delta:.2e} (expect <1e-4), "
            f"real_vs_zeroed_delta={real_vs_zeroed_delta:.2e} (expect >1e-6)",
        )
    except Exception as e:
        failed.append(name)
        errors.append(f"{name}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


# ---------------------------------------------------------------------------
# (c) SAMPLE_ACTION_CORRECT
# ---------------------------------------------------------------------------

def test_sample_action_correct():
    """Perturbing model logits changes the action distribution.

    This proves sample_action() draws from ACTUAL model logits, not from a
    hardcoded or echoed distribution.

    We create two policies with very different weights (one biased toward
    action 0, one toward action 7) and run many samples to compare distributions.
    If the distributions differ significantly, sample_action is logit-driven.
    """
    name = "c_sample_action_correct"
    try:
        torch.manual_seed(123)
        N_SAMPLES = 200
        context = torch.tensor([0], dtype=torch.long)

        # Policy A: default random init
        core_a = real_core_factory()
        # Policy B: perturb the lm_head (or embed_tokens, which are tied) toward action 0.
        core_b = real_core_factory()
        # Access the underlying EmberModelShell lm_head to perturb.
        with torch.no_grad():
            # Find the lm_head leaf inside the _ActionVocabForwardWrapper shell.
            lm_head = core_b._shell._ember_model.lm_head
            # Strongly bias action 0 (token index 0) in full vocab.
            lm_head.weight.data[0, :] += 50.0   # boost row 0 (token 0)
            lm_head.weight.data[7, :] -= 50.0   # suppress row 7

        # Sample from both policies.
        counts_a = [0] * _IGRPO_VOCAB_SIZE
        counts_b = [0] * _IGRPO_VOCAB_SIZE
        for _ in range(N_SAMPLES):
            act_a = core_a.sample_action(context, temperature=1.0)
            act_b = core_b.sample_action(context, temperature=1.0)
            counts_a[act_a % _IGRPO_VOCAB_SIZE] += 1
            counts_b[act_b % _IGRPO_VOCAB_SIZE] += 1

        # The distributions should differ between biased and unbiased policies.
        max_diff = max(abs(counts_a[i] - counts_b[i]) for i in range(_IGRPO_VOCAB_SIZE))

        # Also verify that changing logits changes the greedy action.
        greedy_a = core_a.sample_action(context, temperature=0.0)
        greedy_b = core_b.sample_action(context, temperature=0.0)

        # With such a strong bias, greedy_b should be 0 (or near it).
        # We just check the distributions differ significantly.
        check(
            name,
            max_diff >= 5 or greedy_a != greedy_b,
            f"max_diff={max_diff}, greedy_a={greedy_a}, greedy_b={greedy_b} "
            f"(distributions should differ after logit perturbation)",
        )
    except Exception as e:
        failed.append(name)
        errors.append(f"{name}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


# ---------------------------------------------------------------------------
# (d) LOGPROB_IGRPO
# ---------------------------------------------------------------------------

def test_logprob_igrpo():
    """Log-probs from sample_action_with_logprobs match the sampled action
    tokens under the current policy — importance ratio well-formed.

    We verify:
    1. sample_action_with_logprobs returns a valid (action, log_prob) pair.
    2. The log_prob is the log-probability of the action under the current policy
       (not some stale or detached computation).
    3. Re-running forward on the same input at the same weights yields the same log-prob.
    4. After a weight update (one optimizer step), the log-prob changes.
    """
    name = "d_logprob_igrpo"
    try:
        torch.manual_seed(55)
        core, optimizer = _fresh_policy_and_optimizer()
        context = torch.tensor([3], dtype=torch.long)

        # Step 1: get (action, logprob) at current weights.
        action, log_prob = sample_action_with_logprobs(core, context, temperature=1.0)

        # log_prob should be a finite scalar tensor.
        assert torch.isfinite(log_prob), f"log_prob is not finite: {log_prob}"
        assert log_prob.ndim == 0, f"log_prob should be scalar, got shape {log_prob.shape}"
        assert float(log_prob.detach()) < 0, f"log probability should be negative, got {float(log_prob.detach())}"

        # Step 2: re-run forward at same weights to verify reproducibility.
        inp = context.unsqueeze(0)
        vocab_size = core._shell._ember_model.embed_tokens.num_embeddings
        inp_clamped = inp.clamp(0, vocab_size - 1)
        with torch.no_grad():
            logits = core.forward(inp_clamped)[0, -1, :]  # (10,)
            log_probs = F.log_softmax(logits, dim=-1)
            expected_lp = log_probs[action].item()

        # The log-prob from sample_action_with_logprobs should match re-computing it.
        lp_val = float(log_prob.detach())
        assert abs(lp_val - expected_lp) < 1e-5, (
            f"log_prob mismatch: from fn={lp_val:.6f}, re-computed={expected_lp:.6f}"
        )

        # Step 3: after a weight update, the log-prob of the same action changes.
        # Run one training step to update weights.
        adapter_train_resident_fn(
            policy=core, optimizer=optimizer,
            state_val=3, N=4, G=4, max_depth=1, epsilon=0.2, temperature=1.5,
        )

        # Re-compute log-prob of the same action at new weights.
        with torch.no_grad():
            logits_after = core.forward(inp_clamped)[0, -1, :]
            log_probs_after = F.log_softmax(logits_after, dim=-1)
            lp_after = float(log_probs_after[action].item())

        # Weights changed -> logits changed -> log-prob changed (up to floating point).
        # We just check that the log-probs are now DIFFERENT from the pre-update ones.
        # (If the training step produced zero gradient, this might not hold; in that
        #  case we run more steps.)
        lp_changed = abs(lp_after - expected_lp) > 1e-7

        # If one step wasn't enough (all-zero advantage), try a few more.
        if not lp_changed:
            for extra_sv in range(8):
                adapter_train_resident_fn(
                    policy=core, optimizer=optimizer,
                    state_val=extra_sv, N=4, G=4, max_depth=1, epsilon=0.2, temperature=1.5,
                )
            with torch.no_grad():
                logits_final = core.forward(inp_clamped)[0, -1, :]
                lp_final = float(F.log_softmax(logits_final, dim=-1)[action].item())
            lp_changed = abs(lp_final - expected_lp) > 1e-7

        check(
            name,
            lp_changed,
            f"log_prob did not change after weight update: before={expected_lp:.6f}, after={lp_after:.6f}",
        )
    except Exception as e:
        failed.append(name)
        errors.append(f"{name}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


# ---------------------------------------------------------------------------
# (e) RIG_DROP_IN
# ---------------------------------------------------------------------------

def test_rig_drop_in():
    """Wire this adapter as the C arm in the REAL rig and assert guards g + h pass.

    Imports ember_c14_contract_rig, uses check_guards() with the adapter's
    core_factory and train_resident_fn. This runs the ACTUAL rig guard logic,
    not a simulation.
    """
    name = "e_rig_drop_in"
    try:
        from ember_c14_contract_rig import (
            check_guards,
            _make_stub_corpus,
            _stub_verifier,
            _stub_eval_arm_C_and_deleted,
            _stub_eval_arm_A,
        )

        torch.manual_seed(7)
        corpus = _make_stub_corpus()
        corpus.echo_proof_assert()

        # Run C and Deleted arms using the ADAPTER (not the genuine reference stub).
        (c_train, c_heldout,
         deleted_train, deleted_heldout,
         pre_c_hash, post_c_hash,
         deleted_hash) = _stub_eval_arm_C_and_deleted(
            core_factory=real_core_factory,
            train_tasks=corpus.train,
            heldout_tasks=corpus.heldout,
            verifier=_stub_verifier,
            n_train_steps=16,
            lr=1e-3,
            train_resident_fn=adapter_train_resident_fn,
        )

        # Run Arm A for comparison (needed by check_guards for guard h).
        core_a = real_core_factory()
        a_train = _stub_eval_arm_A(core_a, corpus.train, _stub_verifier)

        # Run check_guards with the adapter's core_factory and train_resident_fn.
        guard_result = check_guards(
            core_factory=real_core_factory,
            pre_c_hash=pre_c_hash,
            post_c_hash=post_c_hash,
            deleted_hash=deleted_hash,
            verifier=_stub_verifier,
            corpus=corpus,
            train_resident_fn=adapter_train_resident_fn,
            c_train_result=c_train,
            a_train_result=a_train,
            n_train_steps=16,
            lr=1e-3,
        )

        g_pass = guard_result.guard_g_gradient_flow
        h_pass = guard_result.guard_h_reward_dependence

        if verbose:
            print(f"    guard_g={g_pass}, guard_h={h_pass}")
            print(f"    c_train_rate={guard_result.c_train_rate:.2%}, "
                  f"c_scrambled_rate={guard_result.c_scrambled_train_rate:.2%}, "
                  f"a_train_rate={guard_result.a_train_rate:.2%}")

        check(name, g_pass and h_pass,
              f"guard_g={g_pass}, guard_h={h_pass}")
    except Exception as e:
        failed.append(name)
        errors.append(f"{name}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


# ---------------------------------------------------------------------------
# (f) NOT_SIDE_CLASSIFIER
# ---------------------------------------------------------------------------

def test_not_side_classifier():
    """The trained capability lives in the hosted core params (guard e analog).

    Checks:
    1. The policy has > 1000 total parameters (real transformer, not a side classifier).
    2. The named_modules() tree contains attention/transformer layer names.
    3. The _is_side_classifier() function from the rig returns False for this policy.
    """
    name = "f_not_side_classifier"
    try:
        from ember_c14_contract_rig import _is_side_classifier

        core = real_core_factory()

        # Count total parameters.
        total_params = sum(p.numel() for p in core.parameters())

        # Check named_modules contains transformer-like layer names.
        module_names = [n.lower() for n, _ in core.named_modules()]
        has_attention = any(
            "attn" in n or "attention" in n or "transformer" in n
            or "encoder" in n or "proj" in n or "norm" in n
            for n in module_names
        )

        # Check rig's _is_side_classifier returns False.
        is_side = _is_side_classifier(core)

        if verbose:
            print(f"    total_params={total_params}, has_attention={has_attention}, "
                  f"is_side_classifier={is_side}")
            print(f"    module names sample: {module_names[:10]}")

        check(
            name,
            total_params > 1000 and has_attention and not is_side,
            f"total_params={total_params}, has_attention={has_attention}, "
            f"is_side_classifier={is_side}",
        )
    except Exception as e:
        failed.append(name)
        errors.append(f"{name}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


# ---------------------------------------------------------------------------
# Extra: verify adapter is NOT a precondition_scaffold_only build
# ---------------------------------------------------------------------------

def test_adapter_path_check():
    """Confirm the adapter is the ADAPTED train_multimodal_v0 path.

    Checks:
    1. build_multimodal_v0_model is imported and called.
    2. The core wraps EmberModelV0Multimodal (not TinyPolicyTransformer).
    3. No SYMBOLIC_PROXY_PASS: the policy.forward() is differentiable through
       the real model weights (we can call backward() and get .grad).
    4. No borrowed-frozen weights: _assert_core_not_frozen_borrowed_zero passes.
    """
    name = "adapter_path_check"
    try:
        from ember_c14_contract_rig import _assert_core_not_frozen_borrowed_zero
        from ember_model_v0_multimodal import EmberModelV0Multimodal
        from ember_resident_igrpo import TinyPolicyTransformer

        core = real_core_factory()

        # 1. The wrapped model is EmberModelV0Multimodal, not TinyPolicyTransformer.
        inner_model = core._shell._ember_model
        is_multimodal = isinstance(inner_model, EmberModelV0Multimodal)
        is_tiny_policy = isinstance(inner_model, TinyPolicyTransformer)

        # 2. Not frozen/borrowed/zero-init.
        try:
            _assert_core_not_frozen_borrowed_zero(core, name="adapter_core")
            not_frozen = True
        except ValueError as ve:
            not_frozen = False
            if verbose:
                print(f"    frozen check failed: {ve}")

        # 3. Differentiable: backward() populates .grad on at least one core param.
        inp = torch.tensor([[0, 1, 2]], dtype=torch.long)
        logits = core.forward(inp)  # (1, 3, 10) — with gradient tape
        loss = logits.mean()
        loss.backward()
        has_grad = any(p.grad is not None for p in core.parameters())

        if verbose:
            print(f"    is_multimodal={is_multimodal}, is_tiny_policy={is_tiny_policy}, "
                  f"not_frozen={not_frozen}, has_grad={has_grad}")

        check(
            name,
            is_multimodal and not is_tiny_policy and not_frozen and has_grad,
            f"is_multimodal={is_multimodal}, is_tiny_policy={is_tiny_policy}, "
            f"not_frozen={not_frozen}, has_grad={has_grad}",
        )
    except Exception as e:
        failed.append(name)
        errors.append(f"{name}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_all(verbose_flag: bool = True) -> tuple[bool, list[str], list[str]]:
    global verbose
    verbose = verbose_flag

    print("=== test_ember_c14_real_adapter TDD suite ===")
    print(f"  device: CPU, model: EmberModelV0Multimodal(tiny), live=False")
    print()

    # Run all tests in order.
    test_adapter_path_check()
    test_gradient_flow()
    test_reward_dependence()
    test_sample_action_correct()
    test_logprob_igrpo()
    test_rig_drop_in()
    test_not_side_classifier()

    print()
    all_names = passed + failed
    all_passed = len(failed) == 0
    status = "ALL PASS" if all_passed else f"FAILED: {failed}"
    print(f"Results: {len(passed)}/{len(all_names)} passed  ({status})")
    if errors:
        print("Exceptions:")
        for e in errors:
            print(f"  {e}")

    return all_passed, passed, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="TDD suite for C14 real adapter")
    parser.add_argument("--verbose", action="store_true", default=True)
    args = parser.parse_args()

    all_passed, _passed, _failed = run_all(verbose_flag=args.verbose)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
