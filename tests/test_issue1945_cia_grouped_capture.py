# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Dynamic grouped capture preserves changing row counts and empty-group gradients."""
import os
import unittest
import torch


@unittest.skipUnless(os.environ.get('EMBER_CIA_CAPTURE_CUDA') == '1', 'explicit governed CUDA test required')
class GroupedCaptureTests(unittest.TestCase):
    def test_actual_expert_shapes_replay_changed_counts_with_stable_gradients(self):
        from ember.model.ember_v0_grouped_capture import grouped_mm
        torch.manual_seed(2163)
        torch.backends.cuda.matmul.allow_tf32 = False
        for k, n in ((1024, 3072), (3072, 1024)):
            a = (torch.randn(4096, k, device='cuda', dtype=torch.bfloat16) * .02).requires_grad_()
            b = (torch.randn(4, n, k, device='cuda', dtype=torch.bfloat16) * .02).transpose(1, 2).detach().requires_grad_()
            gradient = torch.randn(4096, n, device='cuda', dtype=torch.bfloat16) * .02
            offsets = torch.tensor([1024, 4096, 4096, 4096], device='cuda', dtype=torch.int32)
            def execute():
                value = grouped_mm(a, b, offsets)
                return value, *torch.autograd.grad(value, (a, b), gradient)
            stream = torch.cuda.Stream()
            stream.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(stream):
                execute()
                execute()
            torch.cuda.current_stream().wait_stream(stream)
            graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(graph):
                outputs = execute()
            for counts in ((1024, 3072, 0, 0), (4096, 0, 0, 0), (0, 0, 0, 4096), (1, 31, 2049, 2015)):
                offsets.copy_(torch.tensor(counts, device='cuda', dtype=torch.int32).cumsum(0, dtype=torch.int32))
                graph.replay()
                references = [[], [], []]
                start = 0
                for group, count in enumerate(counts):
                    end = start + count
                    x, dy, weight = a[start:end].detach().float(), gradient[start:end].float(), b[group].detach().float()
                    references[0].append((x @ weight).bfloat16())
                    references[1].append((dy @ weight.T).bfloat16())
                    references[2].append((x.T @ dy).bfloat16())
                    if count == 0:
                        self.assertEqual(int(outputs[2][group].count_nonzero()), 0)
                    start = end
                expected = (torch.cat(references[0]), torch.cat(references[1]), torch.stack(references[2]))
                for actual, reference in zip(outputs, expected):
                    difference = actual.detach().float() - reference.float()
                    self.assertTrue(bool(torch.isfinite(actual).all()))
                    self.assertLess(float(difference.norm() / reference.float().norm().clamp_min(1e-20)), .005)
                saved = tuple(value.clone() for value in outputs)
                for _ in range(3):
                    graph.replay()
                    for actual, reference in zip(outputs, saved):
                        self.assertTrue(torch.equal(actual, reference), 'same-input replay must be bitwise stable')
            del outputs, graph, a, b, gradient, offsets
            torch.cuda.empty_cache()


if __name__ == '__main__':
    unittest.main()
