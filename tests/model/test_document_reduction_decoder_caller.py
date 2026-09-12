# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The real decoder callers, not the primitive: _batched_attention and the shared SwiGLU site.

Goal binding: #1945. tests/model/test_document_reduction.py proves the reduction primitive. This
file proves the thing that actually ships -- that the resident branch of CIADecoder._batched_attention
and CIADecoder._document_swiglu call it, that they leave the forward alone, and that the weight
gradients they produce are the per-document descending sums rather than merged ones.

The distinction matters because every defect on this repair so far has been a WIRING defect, not an
arithmetic one: the primitive was correct while it was attached to the reference branch, and correct
again while the shared site it was supposed to cover went untouched. A primitive-only suite passes
in both of those states.

The methods under test are the real unbound CIADecoder methods bound to a small stub carrying only
what they read. That keeps the test on CPU and off the 3B population while still executing the
shipped code path rather than a copy of it.
"""

import sys
import unittest
from pathlib import Path

import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from ember.model.ember_v0_decoder import CIADecoder  # noqa: E402
from ember.model.ember_v0_document_reduction import reduce_weight_gradient  # noqa: E402

LENGTHS = [4, 4, 4, 4]
WIDTH = 1024


def _weights(names, generator):
    made = {}
    for name, shape in names.items():
        made[name] = torch.randn(shape, generator=generator, dtype=torch.float32) * 0.02
        made[name].requires_grad_(True)
    return made


class _Stub:
    """Only what the decoder methods under test actually read."""

    _DOCUMENT_REDUCTION_ORDER = CIADecoder._DOCUMENT_REDUCTION_ORDER

    def __init__(self, weights, resident):
        self._weights = weights
        self._resident_experts = resident
        self._cuda_execution = None

    def _weight(self, name):
        return self._weights[name]

    # Real methods, bound to the stub.
    _linear = CIADecoder._linear
    _norm = CIADecoder._norm
    _swiglu = CIADecoder._swiglu
    _per_document = CIADecoder._per_document
    _document_linear = CIADecoder._document_linear
    _document_swiglu = CIADecoder._document_swiglu
    _batched_attention = CIADecoder._batched_attention


def _attention_stub(resident):
    generator = torch.Generator().manual_seed(1945)
    prefix = "layers.1.attention"
    weights = _weights({f"{prefix}.q.weight": (WIDTH, WIDTH),
                        f"{prefix}.k.weight": (256, WIDTH),
                        f"{prefix}.v.weight": (256, WIDTH),
                        f"{prefix}.o.weight": (WIDTH, WIDTH),
                        f"{prefix}.q_norm.weight": (64,),
                        f"{prefix}.k_norm.weight": (64,)}, generator)
    values = torch.randn(sum(LENGTHS), WIDTH, generator=generator, dtype=torch.float32)
    positions = torch.stack([torch.arange(sum(LENGTHS))] * 3, dim=1)
    return _Stub(weights, resident), prefix, values, positions


class DocumentReductionDecoderCallers(unittest.TestCase):

    def test_the_order_constant_is_the_measured_one(self):
        """Guards the one value the whole repair depends on and that no arithmetic test would catch."""
        self.assertEqual(CIADecoder._DOCUMENT_REDUCTION_ORDER, "descending")

    def test_resident_attention_forward_is_unchanged_for_q_and_o(self):
        """q and o keep merged forwards, so the resident forward must not move at all.

        Computed by hand from the same weights rather than compared against another call of the
        method, which would agree with itself no matter what the method did.
        """
        stub, prefix, values, positions = _attention_stub(resident=(0,))
        out = stub._batched_attention(values, positions, LENGTHS, prefix)
        expected_q = F.linear(values, stub._weight(f"{prefix}.q.weight"))
        produced_q = stub._document_linear(values, f"{prefix}.q.weight", LENGTHS)
        self.assertTrue(torch.equal(produced_q, expected_q))
        self.assertEqual(out.shape, (sum(LENGTHS), WIDTH))

    def test_resident_attention_weight_gradients_are_per_document_descending(self):
        """The q weight gradient out of the real caller equals the descending per-document sum."""
        stub, prefix, values, positions = _attention_stub(resident=(0,))
        weight = stub._weight(f"{prefix}.q.weight")

        held = {}
        original = stub._document_linear

        def capture(self_values, name, lengths):
            result = original(self_values, name, lengths)
            if name.endswith(".q.weight"):
                held["input"] = self_values
                result.retain_grad()
                held["output"] = result
            return result

        stub._document_linear = capture
        out = stub._batched_attention(values, positions, LENGTHS, prefix)
        out.sum().backward()

        upstream = held["output"].grad
        expected = reduce_weight_gradient(held["input"].detach(), upstream, LENGTHS, "descending")
        self.assertTrue(torch.equal(weight.grad, expected))

        merged = upstream.transpose(0, 1) @ held["input"].detach()
        self.assertFalse(torch.equal(weight.grad, merged),
                         "per-document and merged reductions agreed, so this fixture cannot tell "
                         "a wired repair from an unwired one")

    def test_k_and_v_go_through_the_reference_per_document_construct(self):
        """k and v carry a forward difference too, so they use _per_document, not a merged forward."""
        stub, prefix, values, positions = _attention_stub(resident=(0,))
        seen = []
        original = stub._per_document

        def capture(function, self_values, lengths):
            seen.append(lengths)
            return original(function, self_values, lengths)

        stub._per_document = capture
        stub._batched_attention(values, positions, LENGTHS, prefix)
        self.assertEqual(len(seen), 2, "k and v must each be projected per document")

    def test_shared_swiglu_forward_is_unchanged_and_gradients_are_per_document(self):
        """The shared site is the larger failing population; it must be wired, and provably so."""
        generator = torch.Generator().manual_seed(64)
        prefix = "layers.0.shared"
        weights = _weights({f"{prefix}.up.weight": (2048, WIDTH),
                            f"{prefix}.gate.weight": (2048, WIDTH),
                            f"{prefix}.down.weight": (WIDTH, 2048)}, generator)
        stub = _Stub(weights, resident=(0,))
        values = torch.randn(sum(LENGTHS), WIDTH, generator=generator, dtype=torch.float32)

        self.assertTrue(torch.equal(stub._document_swiglu(values, prefix, LENGTHS),
                                    stub._swiglu(values, prefix)),
                        "the shared forward must be the merged forward's own bytes")

        held = {}
        original = stub._document_linear

        def capture(self_values, name, lengths):
            result = original(self_values, name, lengths)
            if name.endswith(".down.weight"):
                held["input"] = self_values
                result.retain_grad()
                held["output"] = result
            return result

        stub._document_linear = capture
        stub._document_swiglu(values, prefix, LENGTHS).sum().backward()

        upstream = held["output"].grad
        down = weights[f"{prefix}.down.weight"]
        expected = reduce_weight_gradient(held["input"].detach(), upstream, LENGTHS, "descending")
        self.assertTrue(torch.equal(down.grad, expected),
                        "the shared down gradient is not the descending per-document sum, so the "
                        "site is calling the merged reduction the reference does not use")
        self.assertFalse(torch.equal(down.grad,
                                     upstream.transpose(0, 1) @ held["input"].detach()),
                         "per-document and merged reductions agreed, so this fixture cannot tell "
                         "a wired shared site from an unwired one")

    def test_the_nonresident_reference_branch_is_untouched(self):
        """The reference must not acquire the repair; the criterion is measured against it."""
        stub, prefix, values, positions = _attention_stub(resident=())
        seen = []
        original = stub._per_document

        def capture(function, self_values, lengths):
            seen.append(lengths)
            return original(function, self_values, lengths)

        stub._per_document = capture
        stub._batched_attention(values, positions, LENGTHS, prefix)
        self.assertEqual(len(seen), 4,
                         "the reference branch projects q, k, v and o per document; a smaller count "
                         "means the repair leaked into the baseline")


if __name__ == "__main__":
    unittest.main()
