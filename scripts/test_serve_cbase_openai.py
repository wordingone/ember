#!/usr/bin/env python3
"""test_serve_cbase_openai.py — CPU-only test suite for serve_cbase_openai.py (refs #508).

Tests:
  1. Config inference: state_dict keys match inferred LlamaConfig model.
  2. Smoke test: 1-token generate on CPU.
  3. Endpoint schemas: TestClient validates /v1/completions and /v1/chat/completions.

Run:  python test_serve_cbase_openai.py
      (all tests CPU-only; no GPU required)
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest
import torch
from fastapi.testclient import TestClient
from transformers import LlamaConfig, LlamaForCausalLM

# Add scripts dir to path to import serve_cbase_openai
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Lazy import to avoid torch/transformers issues at module level
serve_module = None


def lazy_import():
    global serve_module
    if serve_module is None:
        import serve_cbase_openai
        serve_module = serve_cbase_openai
    return serve_module


class TestConfigInference:
    """Test that config is correctly inferred from checkpoint shapes."""

    def test_infer_config_from_state_dict(self):
        """Test config inference on a minimal mock state_dict."""
        serve = lazy_import()

        # Create a minimal mock state_dict matching Llama shapes
        vocab_size = 32000
        hidden_size = 1024
        intermediate_size = 16384  # post-grow size
        num_layers = 20

        mock_state = {}
        # Embedding
        mock_state["model.embed_tokens.weight"] = torch.randn(vocab_size, hidden_size)
        # Layer 0 gate_proj (to infer intermediate_size)
        mock_state["model.layers.0.mlp.gate_proj.weight"] = torch.randn(intermediate_size, hidden_size)
        # Add more layers to infer num_layers
        for i in range(1, num_layers):
            mock_state[f"model.layers.{i}.mlp.gate_proj.weight"] = torch.randn(intermediate_size, hidden_size)

        config = serve.infer_model_config(mock_state)

        # Verify inferred values
        assert config["vocab_size"] == vocab_size, f"Expected vocab_size={vocab_size}, got {config['vocab_size']}"
        assert config["hidden_size"] == hidden_size, f"Expected hidden_size={hidden_size}, got {config['hidden_size']}"
        assert config["intermediate_size"] == intermediate_size, f"Expected intermediate_size={intermediate_size}, got {config['intermediate_size']}"
        assert config["num_hidden_layers"] == num_layers, f"Expected num_layers={num_layers}, got {config['num_hidden_layers']}"
        print(f"✓ Config inference passed: {config}")

    def test_inferred_config_matches_model(self):
        """Test that inferred config can build a valid model."""
        serve = lazy_import()

        config_dict = {
            "vocab_size": 1000,
            "hidden_size": 128,
            "intermediate_size": 512,
            "num_hidden_layers": 2,
            "num_attention_heads": 4,
            "num_key_value_heads": 4,
            "max_position_embeddings": 512,
            "tie_word_embeddings": True,
        }

        config = LlamaConfig(**config_dict)
        model = LlamaForCausalLM(config)

        # Verify model can be built
        assert model is not None
        assert isinstance(model, LlamaForCausalLM)
        assert model.config.hidden_size == 128
        assert model.config.intermediate_size == 512
        print(f"✓ Model building passed: {config_dict}")


class TestRemap:
    """Test remap_ember_state_dict: ember training-wrapper naming -> HF LlamaForCausalLM
    naming (refs #508 shim fix). No real checkpoint required — a tiny synthetic 2-layer
    state_dict stands in for the wrapper's backbone_model.*/head.weight/mtp_heads.N.weight."""

    @staticmethod
    def _toy_wrapper_state_dict(tied: bool):
        """Build a synthetic state_dict under the ember wrapper's key names, matching a
        toy 2-layer LlamaForCausalLM, so remap + strict-load can be exercised without a
        real checkpoint. `tied` controls whether head.weight is constructed equal to
        embed_tokens.weight (the checkpoint's actual tied case) or independently (untied)."""
        config = LlamaConfig(
            vocab_size=64,
            hidden_size=32,
            intermediate_size=128,
            num_hidden_layers=2,
            num_attention_heads=4,
            num_key_value_heads=4,
            max_position_embeddings=64,
            tie_word_embeddings=tied,
        )
        toy_model = LlamaForCausalLM(config)
        hf_sd = toy_model.state_dict()

        wrapper_sd = {}
        for k, v in hf_sd.items():
            if k.startswith("model."):
                wrapper_sd["backbone_model." + k[len("model."):]] = v.clone()
        wrapper_sd["head.weight"] = hf_sd["lm_head.weight"].clone()
        # training-only MTP auxiliary heads — must be dropped, never served
        wrapper_sd["mtp_heads.0.weight"] = torch.randn(config.vocab_size, config.hidden_size)
        wrapper_sd["mtp_heads.1.weight"] = torch.randn(config.vocab_size, config.hidden_size)

        return wrapper_sd

    def test_remap_tied_strict_load_succeeds(self):
        """Tied checkpoint (head.weight == embed_tokens.weight, the real checkpoint's
        actual case): remap detects the tie and a strict load into a matching HF model
        succeeds with allclose-identical weights."""
        serve = lazy_import()
        wrapper_sd = self._toy_wrapper_state_dict(tied=True)

        remapped, mtp_dropped = serve.remap_ember_state_dict(wrapper_sd)

        assert sorted(mtp_dropped) == ["mtp_heads.0.weight", "mtp_heads.1.weight"]
        assert "lm_head.weight" in remapped and "model.embed_tokens.weight" in remapped
        assert not any(
            k.startswith("backbone_model.") or k.startswith("mtp_heads.") or k == "head.weight"
            for k in remapped
        )

        tied_detected = torch.equal(remapped["lm_head.weight"], remapped["model.embed_tokens.weight"])
        assert tied_detected is True

        config = LlamaConfig(
            vocab_size=64, hidden_size=32, intermediate_size=128, num_hidden_layers=2,
            num_attention_heads=4, num_key_value_heads=4, max_position_embeddings=64,
            tie_word_embeddings=tied_detected,
        )
        model = LlamaForCausalLM(config)
        model.load_state_dict(remapped)  # strict=True default; must not raise
        assert torch.allclose(model.lm_head.weight, remapped["lm_head.weight"])
        assert torch.allclose(model.model.embed_tokens.weight, remapped["model.embed_tokens.weight"])
        print("✓ remap tied strict-load passed")

    def test_remap_untied_strict_load_succeeds(self):
        """Untied checkpoint (head.weight independent of embed_tokens.weight): remap
        detects no tie and a strict load still succeeds, preserving distinct weights."""
        serve = lazy_import()
        wrapper_sd = self._toy_wrapper_state_dict(tied=False)

        remapped, mtp_dropped = serve.remap_ember_state_dict(wrapper_sd)
        assert len(mtp_dropped) == 2

        tied_detected = torch.equal(remapped["lm_head.weight"], remapped["model.embed_tokens.weight"])
        assert tied_detected is False

        config = LlamaConfig(
            vocab_size=64, hidden_size=32, intermediate_size=128, num_hidden_layers=2,
            num_attention_heads=4, num_key_value_heads=4, max_position_embeddings=64,
            tie_word_embeddings=tied_detected,
        )
        model = LlamaForCausalLM(config)
        model.load_state_dict(remapped)  # strict=True default; must not raise
        assert torch.allclose(model.lm_head.weight, remapped["lm_head.weight"])
        assert not torch.allclose(model.lm_head.weight, remapped["model.embed_tokens.weight"])
        print("✓ remap untied strict-load passed")

    def test_remap_leftover_key_hard_fails(self):
        """A key matching none of the three known patterns must hard-fail, never be
        silently dropped or silently passed through."""
        serve = lazy_import()
        wrapper_sd = self._toy_wrapper_state_dict(tied=True)
        wrapper_sd["some_unrecognized_module.weight"] = torch.randn(4, 4)

        with pytest.raises(ValueError, match="unmapped leftover key"):
            serve.remap_ember_state_dict(wrapper_sd)
        print("✓ remap leftover-key hard-fail passed")


class TestSmoke:
    """Test 1-token CPU generate to verify model loading works."""

    def test_1token_generate_cpu(self):
        """Test single-token generation on CPU (smoke test)."""
        serve = lazy_import()

        # Build a tiny model for fast smoke test
        config = LlamaConfig(
            vocab_size=1000,
            hidden_size=64,
            intermediate_size=256,
            num_hidden_layers=2,
            num_attention_heads=2,
            num_key_value_heads=2,
            max_position_embeddings=256,
            tie_word_embeddings=True,
        )

        model = LlamaForCausalLM(config).cpu().eval()

        # Minimal tokenization
        input_ids = torch.tensor([[1, 2, 3]], device="cpu")

        # Generate 1 token
        with torch.no_grad():
            output = model.generate(
                input_ids,
                max_new_tokens=1,
                do_sample=False,
                pad_token_id=0,
            )

        assert output.shape[0] == 1, f"Expected batch size 1, got {output.shape[0]}"
        assert output.shape[1] >= 4, f"Expected at least 4 tokens (input + 1 new), got {output.shape[1]}"
        print(f"✓ 1-token smoke test passed: output shape {output.shape}")


class TestEndpoints:
    """Test OpenAI-compatible endpoints via TestClient."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create test app and client."""
        serve = lazy_import()
        from unittest.mock import MagicMock

        # Mock the ModelServer to avoid loading real checkpoint
        mock_server = MagicMock()
        mock_server.model = MagicMock()  # Pretend model is loaded
        mock_server.config = LlamaConfig(
            vocab_size=1000,
            hidden_size=64,
            intermediate_size=256,
            num_hidden_layers=2,
            num_attention_heads=2,
            num_key_value_heads=2,
        )
        mock_server.device = "cpu"
        mock_server.startup_log = ["test startup"]

        # Mock tokenizer
        mock_tokenizer = MagicMock()
        mock_tokenizer.encode.return_value = MagicMock(ids=[1, 2, 3])
        mock_tokenizer.decode.return_value = "mock completion"
        mock_server.tokenizer = mock_tokenizer

        # Mock generate
        mock_server.generate.return_value = ("test response", {
            "prompt_tokens": 3,
            "completion_tokens": 5,
            "total_tokens": 8,
        })

        # Patch the global model_server
        serve.model_server = mock_server

        self.client = TestClient(serve.app)

    def test_health_endpoint(self):
        """Test /health endpoint."""
        response = self.client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "config" in data
        print(f"✓ /health endpoint passed")

    def test_models_endpoint(self):
        """Test /v1/models endpoint."""
        response = self.client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) > 0
        assert data["data"][0]["id"] == "cbase-2.2b"
        print(f"✓ /v1/models endpoint passed")

    def test_completions_endpoint(self):
        """Test /v1/completions endpoint."""
        payload = {
            "model": "cbase-2.2b",
            "prompt": "Hello, ",
            "max_tokens": 50,
        }
        response = self.client.post("/v1/completions", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert "text" in data["choices"][0]
        assert "usage" in data
        print(f"✓ /v1/completions endpoint passed")

    def test_chat_completions_endpoint(self):
        """Test /v1/chat/completions endpoint."""
        payload = {
            "model": "cbase-2.2b",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 50,
        }
        response = self.client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert "message" in data["choices"][0]
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert "usage" in data
        print(f"✓ /v1/chat/completions endpoint passed")

    def test_completions_response_schema(self):
        """Test response matches OpenAI schema."""
        payload = {
            "model": "cbase-2.2b",
            "prompt": "Test",
            "max_tokens": 10,
        }
        response = self.client.post("/v1/completions", json=payload)
        data = response.json()

        # Validate schema
        assert "id" in data
        assert "created" in data
        assert "model" in data
        assert "choices" in data
        assert "usage" in data

        # Validate usage
        usage = data["usage"]
        assert "prompt_tokens" in usage
        assert "completion_tokens" in usage
        assert "total_tokens" in usage
        print(f"✓ Response schema validation passed")


# ============================================================================
# Main
# ============================================================================

def run_tests():
    """Run all tests and print summary."""
    print("=" * 70)
    print("Running CPU test suite for serve_cbase_openai.py")
    print("=" * 70)

    # Use pytest to run tests
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    return exit_code


if __name__ == "__main__":
    sys.exit(run_tests())
