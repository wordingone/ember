# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
# goal_id: EMBER-02
# workstream_id: EMBER-02A
"""Full CIA shape graph; metadata-only, no learned weights or GPU."""
import sys
import unittest
from pathlib import Path
import torch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ember.model.ember_v0_decoder import CIADecoder, rotate_three_axis
from ember.model.ember_v0_inventory import equation_inventory


class CIADecoderTests(unittest.TestCase):
    def setUp(self):
        self.model = CIADecoder()

    def test_actual_parameters_match_complete_inventory(self):
        actual = self.model.parameter_inventory()
        expected = {s.name: s.shape for s in equation_inventory()}
        self.assertEqual({name: tuple(p.shape) for name, p in actual.items()}, expected)
        self.assertEqual(sum(p.numel() for p in actual.values()), 3_082_539_008)
        self.assertEqual(len({id(p) for p in actual.values()}), len(actual))
        self.assertTrue(all(isinstance(p, torch.nn.Parameter) and p.device.type == "meta" for p in actual.values()))

    def test_full_text_decoder_shape_and_tied_output(self):
        text = self.model.embed_text(torch.empty(4, dtype=torch.long, device="meta"))
        logits = self.model.trace_fixed_route(text, torch.empty(4, 3, dtype=torch.long, device="meta"), experts=(0,) * 12)
        self.assertEqual(tuple(logits.shape), (4, 32768))
        logits.sum().backward()
        params = self.model.parameter_inventory()
        self.assertIsNotNone(params["embedding.weight"].grad)
        self.assertIsNotNone(params["experts.0.layers.1.up.weight"].grad)
        self.assertIsNone(params["experts.1.layers.1.up.weight"].grad)

    def test_raw_adapters_join_one_decoder(self):
        image = self.model.embed_image(torch.empty(2, 768, device="meta", dtype=torch.bfloat16))
        audio = self.model.embed_audio(torch.empty(3, 640, device="meta", dtype=torch.bfloat16))
        values = torch.cat((image, audio))
        logits = self.model.trace_fixed_route(values, torch.empty(5, 3, dtype=torch.long, device="meta"), experts=(24,) * 12)
        logits.sum().backward()
        params = self.model.parameter_inventory()
        self.assertIsNotNone(params["image.weight"].grad)
        self.assertIsNotNone(params["audio.weight"].grad)
        self.assertEqual(tuple(logits.shape), (5, 32768))

    def test_each_global_expert_has_executable_projection_path(self):
        values = torch.empty(1, 1024, device="meta", dtype=torch.bfloat16)
        for expert in range(25):
            for layer in range(1, 24, 2):
                self.assertEqual(tuple(self.model.expert_block(values, expert=expert, layer=layer).shape), (1, 1024))

    def test_aliased_expert_objects_are_refused(self):
        self.model.weights["experts__1__layers__1__up__weight"] = self.model.weights["experts__0__layers__1__up__weight"]
        with self.assertRaisesRegex(ValueError, "alias"):
            self.model.parameter_inventory()

    def test_fixed_route_is_explicitly_non_learning(self):
        with self.assertRaises(ValueError):
            self.model.embed_text(torch.zeros(4, dtype=torch.long))
        with self.assertRaises(ValueError):
            self.model.trace_fixed_route(torch.empty(4, 1024, device="meta"), torch.empty(4, 3, dtype=torch.long, device="meta"), experts=(25,) * 12)

    def test_undeclared_parameters_refused(self):
        self.model.unassigned = torch.nn.Parameter(torch.empty(1, device="meta"))
        with self.assertRaisesRegex(ValueError, "undeclared"):
            self.model.parameter_inventory()

    def test_wrong_parameter_dtype_refused(self):
        self.model.float()
        with self.assertRaisesRegex(ValueError, "BF16"):
            self.model.parameter_inventory()

    def test_update_support_controls_actual_parameters_and_clears_gradients(self):
        params = self.model.parameter_inventory()
        for name in ("router.global_query.weight", "experts.2.layers.1.up.weight"):
            params[name].grad = torch.empty_like(params[name])
        selected = self.model.apply_update_support("core+expert-set", experts=(2,))
        self.assertTrue(params["embedding.weight"].requires_grad)
        self.assertTrue(params["experts.2.layers.1.up.weight"].requires_grad)
        self.assertFalse(params["router.global_query.weight"].requires_grad)
        self.assertFalse(params["experts.3.layers.1.up.weight"].requires_grad)
        self.assertTrue(all(p.grad is None for p in params.values()))
        self.assertEqual({id(p) for p in selected}, {id(p) for p in params.values() if p.requires_grad})
        self.assertEqual(self.model.apply_update_support("memory-only"), ())
        self.assertTrue(all(not p.requires_grad for p in params.values()))

    def test_rope_zero_positions_identity_on_fixed_tensors(self):
        values = torch.arange(128, dtype=torch.float32).reshape(2, 1, 64)
        positions = torch.zeros(2, 3, dtype=torch.long)
        torch.testing.assert_close(rotate_three_axis(values, positions), values)

    def test_routing_gate_consumes_owned_router_parameters(self):
        history = torch.empty(8, 1024, device='meta', dtype=torch.bfloat16)
        local = torch.empty(1024, device='meta', dtype=torch.bfloat16)
        gate = self.model.trace_routing_gate(history, local, sparse_depth=0, experts=(0, 2), selected_slot=0)
        gate.backward()
        params = self.model.parameter_inventory()
        for name in ('router.global_query.weight', 'router.local_query.weight', 'router.layers.1.keys'):
            self.assertIsNotNone(params[name].grad)

    def test_routing_trace_rejects_wrong_parameter_dtype(self):
        self.model.float()
        history = torch.empty(8, 1024, device='meta', dtype=torch.bfloat16)
        local = torch.empty(1024, device='meta', dtype=torch.bfloat16)
        with self.assertRaisesRegex(ValueError, 'BF16'):
            self.model.trace_routing_gate(history, local, sparse_depth=0, experts=(0, 2), selected_slot=0)

    def test_rope_image_axis_does_not_change_other_axes(self):
        values = torch.ones(2, 1, 64)
        positions = torch.zeros(2, 3, dtype=torch.long)
        positions[:, 1] = 2
        changed = rotate_three_axis(values, positions)
        torch.testing.assert_close(changed[..., :32], values[..., :32])
        torch.testing.assert_close(changed[..., 48:], values[..., 48:])
        self.assertFalse(torch.equal(changed[..., 32:48], values[..., 32:48]))


if __name__ == "__main__":
    unittest.main()
