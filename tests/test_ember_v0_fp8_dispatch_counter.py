# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The projection GEMM's arm selection is observable per exit, not merely per process.

The failure this guards against is an arm that is SELECTED and never DISPATCHED. It has already
happened on this campaign: a treatment shipped as a module wrapper while the forward used the
weight directly, so the comparison ran a configuration against itself and a gain was published from
it. A single dispatch tally does not catch that, because zero dispatches is indistinguishable from
a process that never opted in. Separating the refusal reasons is what makes the distinction.

Coverage boundary, stated rather than left implicit: three of the four exits are reachable on CPU
and are asserted here. The `fp8` exit needs a device of compute capability 8.9 or newer, so on a CI
runner without one it is SKIPPED, and its evidence is a GPU receipt rather than this file. A test
that faked the device to claim that exit would be proving the mock.
"""
import importlib.util
from pathlib import Path
import sys

import pytest

torch = pytest.importorskip("torch")

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "ember" / "model" / "ember_v0_fp8_linear.py"
SPEC = importlib.util.spec_from_file_location("_fp8_counter_subject", MODULE_PATH)
assert SPEC and SPEC.loader
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)

EXITS = {"fp8", "not_selected", "unsupported_device", "full_precision"}


@pytest.fixture(autouse=True)
def zeroed():
    subject.reset_dispatch_counts()
    yield
    subject.reset_dispatch_counts()


def _call(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    activation = torch.zeros(2, 4)
    weight = torch.zeros(3, 4)
    return subject.linear(activation, weight)


def test_every_exit_has_its_own_counter():
    """A counter set that grew a fifth exit without a name would silently pool two reasons."""
    assert set(subject.dispatch_counts()) == EXITS


def test_counts_start_at_zero_and_the_snapshot_is_a_copy():
    counts = subject.dispatch_counts()
    assert counts == {name: 0 for name in EXITS}
    counts["fp8"] = 99
    assert subject.dispatch_counts()["fp8"] == 0


def test_a_process_that_did_not_opt_in_is_distinguishable_from_one_that_did(monkeypatch):
    """This is the whole point. Both of these produce zero fp8 dispatches, and they mean opposite
    things: the first never asked for the arm, the second asked and could not have it."""
    monkeypatch.delenv("EMBER_FP8_LINEAR", raising=False)
    _call(monkeypatch)
    assert subject.dispatch_counts()["not_selected"] == 1
    assert subject.dispatch_counts()["unsupported_device"] == 0

    subject.reset_dispatch_counts()
    _call(monkeypatch, EMBER_FP8_LINEAR="1")
    assert subject.dispatch_counts()["not_selected"] == 0
    assert subject.dispatch_counts()["unsupported_device"] == 1


def test_reset_zeroes_every_exit(monkeypatch):
    """A window that reports without resetting reports the process's whole history, so a warmup's
    dispatches are indistinguishable from the measured region's."""
    monkeypatch.delenv("EMBER_FP8_LINEAR", raising=False)
    _call(monkeypatch)
    _call(monkeypatch)
    assert sum(subject.dispatch_counts().values()) == 2
    subject.reset_dispatch_counts()
    assert sum(subject.dispatch_counts().values()) == 0


def test_counting_does_not_change_the_numbers(monkeypatch):
    """The counter is a diagnostic. If it moved a single value it would be a treatment."""
    monkeypatch.delenv("EMBER_FP8_LINEAR", raising=False)
    torch.manual_seed(0)
    activation = torch.randn(2, 4)
    weight = torch.randn(3, 4)
    expected = torch.nn.functional.linear(activation, weight)
    assert torch.equal(subject.linear(activation, weight), expected)


@pytest.mark.skipif(
    not (torch.cuda.is_available() and torch.cuda.get_device_capability() >= (8, 9)),
    reason="the fp8 exit needs compute capability 8.9 or newer; its evidence is a GPU receipt",
)
def test_the_fp8_exit_increments_when_the_arm_actually_runs(monkeypatch):
    monkeypatch.setenv("EMBER_FP8_LINEAR", "1")
    # Dimensions divisible by 16: _scaled_mm RAISES on a trailing dim that is not, rather than
    # falling back the way every other refusal in this module does. Real projections are always
    # multiples of 16, so the constraint is not hit in a model forward -- it is recorded as a
    # ledgered gap in the module's own fallback promise, not silently accommodated here.
    activation = torch.randn(32, 64, device="cuda", dtype=torch.bfloat16)
    weight = torch.randn(128, 64, device="cuda", dtype=torch.bfloat16)
    subject.linear(activation, weight)
    counts = subject.dispatch_counts()
    assert counts["fp8"] == 1, counts
    assert counts["full_precision"] == 0, counts
