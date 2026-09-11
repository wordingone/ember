# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# goal_id: EMBER-02
# workstream_id: EMBER-02A
"""Fixed CPU fixtures compare batched routing with the unchanged scalar selectors."""
import dataclasses
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ember.model import ember_v0_routing as routing


class StepRoutingTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.weight = torch.eye(1024)
        self.keys = torch.zeros(12, 25, 1024)
        self.keys[:, 0, 0] = -1
        self.keys[:, 1, 1] = 1
        self.keys[:, 7, 0] = 1

    def context(self):
        return routing.StepRouting(self.weight.clone(), self.weight.clone(), self.keys.clone(), "g")

    def documents(self, lengths=(1024, 257), *, dtype=torch.float32):
        docs = []
        for index, length in enumerate(lengths):
            value = torch.zeros(length, 1024, dtype=dtype)
            value[:, index % 2] = 1
            docs.append(value)
        return docs

    def setup_batch(self, ctx, docs):
        chunks, selections = [], []
        offset = 0
        for index, doc in enumerate(docs):
            request = f"r{index}"
            epochs = {start: ctx.select_global(doc, position=start, document_start=0,
                                               request=request)
                      for start in range(0, len(doc), 1024)}
            selections.append(epochs)
            chunks.extend(routing.ChunkSpec(offset, start, epochs[(start // 1024) * 1024], request)
                          for start in range(0, len(doc), 256))
            offset += len(doc)
        return tuple(chunks), selections

    def test_exact_routes_logits_receipts_and_gates_across_epochs(self):
        docs = self.documents((1281, 257), dtype=torch.bfloat16)
        ctx = self.context()
        chunks, selections = self.setup_batch(ctx, docs)
        batch = ctx.select_local_batch(torch.cat(docs), chunks, sparse_depth=3, capture=True)
        records = batch.locals()
        self.assertEqual(len(records), len(chunks))
        self.assertEqual(selections[0][0].experts, (0, 1))
        self.assertEqual(selections[0][1024].experts[0], 7)
        for index, chunk in enumerate(chunks):
            doc_index = int(chunk.request[1:])
            doc = docs[doc_index]
            legacy_global = routing.select_global(doc, self.weight, self.keys,
                position=chunk.start, document_start=0, generation="g", request=chunk.request)
            for name in ("experts", "history_digest", "keys_digest", "prior_digest"):
                self.assertEqual(getattr(chunk.selection, name), getattr(legacy_global, name))
            legacy = routing.select_local(doc, self.weight, self.keys, legacy_global,
                position=chunk.start, document_start=0, generation="g", request=chunk.request,
                sparse_depth=3, capture=True)
            self.assertEqual(batch.experts[index], legacy.expert)
            self.assertTrue(torch.equal(batch.logits[index].view(torch.uint8),
                                        legacy.logits.view(torch.uint8)))
            self.assertEqual(records[index].history_digest, legacy.history_digest)
            actual = routing.observe_local(records[index], document=doc_index, layer=7)
            expected = routing.observe_local(legacy, document=doc_index, layer=7)
            self.assertEqual(actual.logits, expected.logits)
            self.assertEqual(actual.margin, expected.margin)
            for name in ("summary", "keys_slice", "prior_slice"):
                self.assertTrue(torch.equal(getattr(actual, name), getattr(expected, name)))
            slot = tuple(sorted(legacy_global.experts)).index(legacy.expert)
            self.assertTrue(torch.equal(batch.gates[index], routing.unit_task_gate(legacy.logits, slot)))

    def test_gate_value_and_gradient_match_scalar_fp32_and_fp64(self):
        for dtype in (torch.float32, torch.float64):
            actual = torch.tensor([[0., 0.], [0.1, 0.10000001], [700., -700.]],
                                  dtype=dtype, requires_grad=True)
            expected = actual.detach().clone().requires_grad_()
            slots = torch.tensor([0, 1, 0])
            gates = routing.unit_task_gate_batch(actual, slots)
            reference = torch.stack([routing.unit_task_gate(row, slot)
                                     for row, slot in zip(expected, (0, 1, 0))])
            self.assertTrue(torch.equal(gates, reference))
            scales = torch.tensor([1., 3., 7.], dtype=dtype)
            (gates * scales).sum().backward()
            (reference * scales).sum().backward()
            self.assertTrue(torch.equal(actual.grad, expected.grad))

    def test_local_graph_gradient_matches_scalar(self):
        docs = self.documents((257,))
        hidden = docs[0].clone().requires_grad_()
        reference_hidden = hidden.detach().clone().requires_grad_()
        local_weight = self.weight.clone().requires_grad_()
        reference_weight = local_weight.detach().clone().requires_grad_()
        ctx = routing.StepRouting(self.weight, local_weight, self.keys, "g")
        chunks, _ = self.setup_batch(ctx, docs)
        batch = ctx.select_local_batch(hidden, chunks, sparse_depth=0)
        reference = [routing.select_local(reference_hidden, reference_weight, self.keys,
            chunk.selection, position=chunk.start, document_start=0, generation="g", request="r0",
            sparse_depth=0) for chunk in chunks]
        gates = [routing.unit_task_gate(row.logits, tuple(sorted(chunks[0].selection.experts)).index(row.expert))
                 for row in reference]
        ctx.close()  # Closing the cache must leave returned autograd graphs usable.
        batch.gates.sum().backward()
        torch.stack(gates).sum().backward()
        self.assertTrue(torch.equal(hidden.grad, reference_hidden.grad))
        self.assertTrue(torch.equal(local_weight.grad, reference_weight.grad))

    def test_one_drain_per_global_and_layer_and_none_for_late_capture(self):
        ctx = self.context()
        docs = self.documents()
        with patch.object(routing._RoutingPayload, "drain", autospec=True,
                          side_effect=routing._RoutingPayload.drain) as drain:
            chunks, _ = self.setup_batch(ctx, docs)
            self.assertEqual(drain.call_count, 2)
            batch = ctx.select_local_batch(torch.cat(docs), chunks, sparse_depth=0, capture=True)
            self.assertEqual(drain.call_count, 3)
            batch.locals()
            batch.locals()
            self.assertEqual(drain.call_count, 3)

    def test_exact_chunk_partition_refuses_missing_duplicate_reordered_and_overlap(self):
        for change in (lambda rows: rows[:-1], lambda rows: rows + rows[-1:],
                       lambda rows: tuple(reversed(rows)),
                       lambda rows: rows[:-1] + (dataclasses.replace(rows[-1], document_offset=0),),
                       lambda rows: (dataclasses.replace(rows[0], start=1),) + rows[1:]):
            ctx = self.context()
            docs = self.documents()
            chunks, _ = self.setup_batch(ctx, docs)
            with self.assertRaises(ValueError):
                ctx.select_local_batch(torch.cat(docs), change(chunks), sparse_depth=0)

    def test_epoch_and_request_and_context_ownership(self):
        docs = self.documents((1281,))
        ctx = self.context()
        chunks, selections = self.setup_batch(ctx, docs)
        other = self.context()
        _, other_selections = self.setup_batch(other, docs)
        replacements = (dataclasses.replace(chunks[0].selection), other_selections[0][0],
                        selections[0][1024])
        for foreign in replacements:
            altered = (dataclasses.replace(chunks[0], selection=foreign),) + chunks[1:]
            with self.assertRaises(ValueError):
                ctx.select_local_batch(docs[0], altered, sparse_depth=0)
        with self.assertRaises(ValueError):
            ctx.select_local_batch(docs[0], (dataclasses.replace(chunks[0], request="other"),)
                                   + chunks[1:], sparse_depth=0)

    def test_exact_byte_mutation_including_data_alias_and_signed_zero(self):
        for target in ("keys", "global_query", "local_query", "prior"):
            ctx = self.context()
            chunks, _ = self.setup_batch(ctx, self.documents((257,)))
            tensor = chunks[0].selection.log_prior if target == "prior" else getattr(ctx, "_" + target)
            if target == "prior":
                tensor.data[0] += 1
            else:
                # The sign bit changes while numeric equality still reports equality.
                tensor.data.reshape(-1)[10] = -0.0
            with self.assertRaises(ValueError):
                ctx.select_local_batch(self.documents((257,))[0], chunks, sparse_depth=0)

    def test_capture_is_selection_time_and_uncaptured_materialization_refuses(self):
        ctx = self.context()
        docs = self.documents((257,), dtype=torch.bfloat16)
        chunks, _ = self.setup_batch(ctx, docs)
        batch = ctx.select_local_batch(docs[0], chunks, sparse_depth=0, capture=True)
        original = batch.locals()
        expected = routing.observe_local(original[1], document=0, layer=1)
        docs[0].fill_(9)
        batch.logits.data.fill_(13)
        chunks[0].selection.log_prior.data.fill_(17)
        original[1].summary.fill_(21)  # A prior caller cannot rewrite the cached record either.
        again = routing.observe_local(batch.locals()[1], document=0, layer=1)
        self.assertEqual(again.history_digest, expected.history_digest)
        self.assertEqual(again.logits, expected.logits)
        self.assertEqual(again.margin, expected.margin)
        self.assertTrue(torch.equal(again.summary, expected.summary))
        ctx = self.context()
        docs = self.documents((257,))
        chunks, _ = self.setup_batch(ctx, docs)
        plain = ctx.select_local_batch(docs[0], chunks, sparse_depth=0)
        with self.assertRaises(ValueError):
            plain.locals()

    def test_future_nonfinite_values_are_not_visible_history(self):
        ctx = self.context()
        docs = self.documents((257,))
        chunks, _ = self.setup_batch(ctx, docs)
        hidden = docs[0].clone()
        hidden[0] = float("nan")
        hidden[256] = float("nan")
        ctx.select_local_batch(hidden, chunks, sparse_depth=0)
        hidden[255] = float("nan")
        with self.assertRaises(ValueError):
            ctx.select_local_batch(hidden, chunks, sparse_depth=0)

    def test_nonfinite_global_inputs_and_closed_context_refuse(self):
        for field in ("keys", "global_query", "local_query"):
            ctx = self.context()
            getattr(ctx, "_" + field).data.reshape(-1)[0] = float("nan")
            with self.assertRaises(ValueError):
                ctx.select_global(self.documents((257,))[0], position=0, document_start=0, request="r")
        ctx = self.context()
        ctx.close()
        with self.assertRaises(ValueError):
            ctx.select_global(self.documents((257,))[0], position=0, document_start=0, request="r")

    def test_nonzero_document_start_refuses_before_registration_or_payload(self):
        ctx = self.context()
        doc = self.documents((270,), dtype=torch.bfloat16)[0]
        with patch.object(routing._RoutingPayload, "drain", autospec=True) as drain:
            with self.assertRaisesRegex(ValueError, "document_start must be zero"):
                ctx.select_global(doc, position=5, document_start=5, request="r")
            drain.assert_not_called()
        self.assertEqual(ctx._documents, {})
        self.assertEqual(ctx._selections, {})
        self.assertIsNone(ctx._keys_digest)

    def test_document_length_start_and_required_epoch_are_bound(self):
        ctx = self.context()
        doc = self.documents((1281,))[0]
        selection = ctx.select_global(doc, position=0, document_start=0, request="r")
        for changed, start in ((doc[:1024], 0), (doc, 1)):
            with self.assertRaises(ValueError):
                ctx.select_global(changed, position=1024, document_start=start, request="r")
        chunks = tuple(routing.ChunkSpec(0, start, selection, "r") for start in range(0, len(doc), 256))
        with self.assertRaises(ValueError):
            ctx.select_local_batch(doc, chunks, sparse_depth=0)

    def test_standalone_batch_gate_validates_slots_shape_and_finiteness(self):
        for slots in (torch.tensor([2, 0]), torch.tensor([-1, 1]), torch.tensor([0., 1.]),
                      torch.tensor([[0, 1]])):
            with self.assertRaises(ValueError):
                routing.unit_task_gate_batch(torch.zeros(2, 2), slots)
        with self.assertRaises(ValueError):
            routing.unit_task_gate_batch(torch.tensor([[float("nan"), 0.]]), torch.tensor([0]))


if __name__ == "__main__":
    unittest.main()
