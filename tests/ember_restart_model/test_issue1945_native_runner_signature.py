# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute the real resident step caller with the strict native decoder API.

Small CPU owners exercise forward, backward, routing-buffer completion and
AdamW application. Capture objects represent the interface only; these tests
do not execute CUDA graphs or qualify the streamed training loss.
"""
import contextlib
import importlib.util
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import torch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'src/ember/infrastructure/tools/ember-restart-3b'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'src'))
PATH = TOOLS / 'cia_step_runner.py'
SPEC = importlib.util.spec_from_file_location('native_signature_step_runner', PATH)
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
from ember.model.ember_v0_decoder import CIADecoder


class NativeModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = torch.nn.Embedding(16, 4)
        self.output = torch.nn.Linear(4, 16)
        self._resident_experts = (0, 1, 8, 18)
        self._cuda_execution = SimpleNamespace(cache=SimpleNamespace(
            lease_count=0, miss_count=0, eviction_count=0,
            transfer_bytes=0, transfer_seconds=0.0))
        self.active = False
        self.calls = 0
        self.hidden_requested = False

    @contextlib.contextmanager
    def candidate_step(self):
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def embed_text(self, tokens):
        if not self.active:
            raise AssertionError('embedding outside candidate context')
        return self.embedding(tokens)

    def finish(self, embedded, collector, *, hidden):
        if not self.active:
            raise AssertionError('forward outside candidate context')
        buffers = runner.routing_buffers((2, 2), torch.device('cpu'))
        collector('global', dict(
            geometry=SimpleNamespace(lengths=buffers.lengths, chunks=buffers.chunks),
            priors=torch.zeros(2, 25, dtype=torch.float32),
            ranked=torch.tensor([[0, 1], [0, 1]], dtype=torch.int64),
            candidates=torch.tensor([[0, 1], [0, 1]], dtype=torch.int64)))
        for layer in buffers.LAYERS:
            collector('local', dict(
                layer=layer, winners=torch.zeros(2, dtype=torch.int64),
                logits=torch.zeros(2, 2, dtype=torch.float32),
                gates=torch.full((2,), .5, dtype=torch.float32),
                valid=torch.tensor(True)))
        self.calls += 1
        self.hidden_requested = hidden
        return (embedded if hidden else self.output(embedded)), ()

    # Exact pre-streamed native keywords, deliberately without **kwargs.
    def forward(self, embedded, positions, *, document_starts=(0,), return_routes=False,
                route_observer=None, route_plan=None, batch_documents=False,
                return_device_routes=False, device_route_collector=None):
        inspect.signature(CIADecoder.forward).bind(
            self, embedded, positions, document_starts=document_starts,
            return_routes=return_routes, batch_documents=batch_documents,
            return_device_routes=return_device_routes,
            device_route_collector=device_route_collector)
        if document_starts != (0, 2) or not (return_routes and batch_documents and return_device_routes):
            raise AssertionError('resident call contract changed')
        return self.finish(embedded, device_route_collector, hidden=False)


class HiddenModel(NativeModel):
    def forward(self, embedded, positions, *, document_starts, return_routes,
                batch_documents, return_device_routes, device_route_collector,
                training_hidden):
        if training_hidden is not True:
            raise AssertionError('hidden output needs an explicit true keyword')
        return self.finish(embedded, device_route_collector, hidden=True)


class CaptureInterface:
    captured = False

    def __init__(self, model, *, head_output=None):
        self.model = model
        self.execution = model._cuda_execution
        self.execution.segmented = self
        if head_output is not None:
            self._cia_head_output = head_output

    def zero_grad(self, *, optimizer):
        optimizer.zero_grad(set_to_none=False)

    def loss(self, values, targets):
        logits = self.model.output(values) if getattr(self, '_cia_head_output', None) == 'hidden' else values
        return torch.nn.functional.cross_entropy(logits.float(), targets)


class NativeSignatureTests(unittest.TestCase):
    def run_step(self, *, captured, head_output=None):
        torch.manual_seed(1945)
        model = HiddenModel() if head_output == 'hidden' else NativeModel()
        before = model.embedding.weight.detach().clone()
        optimizer = torch.optim.AdamW(model.parameters(), lr=.01, weight_decay=0, foreach=False)
        capture = CaptureInterface(model, head_output=head_output) if captured else None
        pack = dict(token_ids=[0, 1, 2, 3], target_ids=[1, 2, 3, 4],
                    positions=[[0, 0, 0], [1, 0, 0], [0, 0, 0], [1, 0, 0]],
                    document_starts=[0, 2], phase='measured')
        row = runner.measure_step(model, optimizer, pack, device=torch.device('cpu'),
                                  batch_documents=True, capture=capture)
        self.assertEqual(model.calls, 1)
        self.assertFalse(model.active)
        self.assertIsNotNone(model.embedding.weight.grad)
        self.assertFalse(torch.equal(before, model.embedding.weight))
        self.assertEqual(row['applied_positions'], 4)
        self.assertEqual(row['routes_digest_grammar'], 'device-buffers-v1')
        self.assertEqual(model.hidden_requested, head_output == 'hidden')
        self.assertEqual(row['training_head'], 'cce-document-v1' if head_output == 'hidden' else 'native')
        self.assertFalse(torch.cuda.is_initialized())

    def test_resident_native_step_uses_strict_original_decoder_signature(self):
        self.run_step(captured=False)

    def test_native_capture_without_output_marker_preserves_original_signature(self):
        self.run_step(captured=True)

    def test_native_capture_with_logits_marker_preserves_original_signature(self):
        self.run_step(captured=True, head_output='logits')

    def test_hidden_capture_still_requests_true_from_capable_decoder(self):
        self.run_step(captured=True, head_output='hidden')


if __name__ == '__main__':
    unittest.main()
