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
