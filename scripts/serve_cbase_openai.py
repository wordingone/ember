#!/usr/bin/env python3
"""serve_cbase_openai.py — OpenAI-compatible HTTP endpoint for cbase 2.2B rung-2 (refs #508).

Serves the ember-created checkpoint (b1-snapshot) behind /v1/completions and /v1/chat/completions,
compatible with external benchmark harnesses (lm_eval, etc.).

Usage:
  python serve_cbase_openai.py [--device cuda|cpu] [--port 8083] [--checkpoint PATH]

Startup requirements:
  - Config is INFERRED from checkpoint tensor shapes (post-grow; intermediate_size differs from seed).
  - One-model-at-a-time guard: refuses --device cuda if :8082/health (27B reference) answers.
  - Frozen training tokenizer loaded from scripts/tokenizer/tokenizer.json.
  - Startup log + /health endpoint report inferred dims.

Test suite: CPU-only (no GPU in CI), schema validation via TestClient.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM, AutoTokenizer
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError as e:
    print(f"ERROR: Missing required dependency: {e}", file=sys.stderr)
    print("Install: pip install torch transformers fastapi pydantic uvicorn tokenizers", file=sys.stderr)
    sys.exit(1)

# ============================================================================
# Configuration & Constants
# ============================================================================

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_PATH_DEFAULT = (
    REPO_ROOT / "models" / "cbase-grow-rung" / "rung2-event-grow-rung2-20260708-real" / "b1-snapshot" / "model.pt"
)
TOKENIZER_PATH_DEFAULT = REPO_ROOT / "scripts" / "tokenizer" / "tokenizer.json"
MANIFEST_PATH_DEFAULT = CHECKPOINT_PATH_DEFAULT.parent / "manifest.json"

PORT_DEFAULT = 8083
PORT_REFERENCE_SERVER = 8082  # 27B reference server

logger = logging.getLogger(__name__)


# ============================================================================
# Request/Response Models
# ============================================================================

class CompletionRequest(BaseModel):
    model: str = "cbase-2.2b"
    prompt: str
    max_tokens: int = Field(default=256, le=2048)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, ge=0.0, le=1.0)
    top_k: int = Field(default=40, ge=0)
    do_sample: bool = False


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "cbase-2.2b"
    messages: list[ChatMessage]
    max_tokens: int = Field(default=256, le=2048)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class CompletionChoice(BaseModel):
    text: str = ""
    message: dict | None = None
    finish_reason: str = "length"
    index: int = 0


class CompletionResponse(BaseModel):
    id: str = ""
    object: str = "text_completion"
    created: int = 0
    model: str = "cbase-2.2b"
    choices: list[CompletionChoice]
    usage: dict


# ============================================================================
# Config Inference from Checkpoint
# ============================================================================

def infer_model_config(state_dict: dict[str, torch.Tensor]) -> dict[str, Any]:
    """Infer LlamaConfig from checkpoint state_dict shapes.

    The checkpoint is POST-GROW (net2net FF-widening applied), so intermediate_size
    differs from the seed config. Extract dims from actual tensor shapes.

    Returns dict with keys: vocab_size, hidden_size, intermediate_size, num_hidden_layers,
    num_attention_heads, num_key_value_heads, max_position_embeddings, tie_word_embeddings.
    """
    config = {
        "vocab_size": 32000,        # invariant
        "hidden_size": 1024,        # invariant
        "num_attention_heads": 16,  # invariant
        "num_key_value_heads": 16,  # invariant
        "max_position_embeddings": 1024,  # invariant
        "tie_word_embeddings": True,  # invariant
        "intermediate_size": 4096,  # will be overwritten if found
        "num_hidden_layers": 20,    # will be overwritten if found
    }

    # Scan state_dict for shapes
    num_layers = 0
    for key, tensor in state_dict.items():
        # vocab_size and hidden_size from embedding
        if "model.embed_tokens.weight" in key:
            config["vocab_size"] = tensor.shape[0]
            config["hidden_size"] = tensor.shape[1]

        # intermediate_size from MLP gate_proj (weight shape: [intermediate, hidden])
        if "model.layers.0.mlp.gate_proj.weight" in key:
            config["intermediate_size"] = tensor.shape[0]

        # Count layers
        if "model.layers." in key:
            layer_idx = int(key.split("model.layers.")[1].split(".")[0])
            num_layers = max(num_layers, layer_idx + 1)

    if num_layers > 0:
        config["num_hidden_layers"] = num_layers

    return config


# ============================================================================
# VRAM Guard: One-model-at-a-time enforcement
# ============================================================================

def check_reference_server(url: str = f"http://127.0.0.1:{PORT_REFERENCE_SERVER}/health", timeout: int = 2) -> bool:
    """Check if the 27B reference server is running (occupying GPU).

    Returns True if reachable, False otherwise.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


# ============================================================================
# Model & Tokenizer Management
# ============================================================================

class ModelServer:
    """Singleton: loads and manages the model, tokenizer, and inference lock."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self.model = None
        self.tokenizer = None
        self.config = None
        self.device = "cpu"
        self.infer_lock = threading.Lock()  # Serialize GPU inference
        self.startup_log = []

    def load(self, checkpoint_path: Path, device: str = "cpu", tokenizer_path: Path | None = None) -> None:
        """Load model and tokenizer. Device='cuda' blocked if reference server is running."""

        self.device = device
        msg = f"[{datetime.now(timezone.utc).isoformat()}] Loading model..."
        print(msg, flush=True)
        self.startup_log.append(msg)

        # VRAM guard: one-model-at-a-time
        if device == "cuda":
            if check_reference_server():
                err = (
                    f"REFUSED: --device cuda requested, but :8082/health (27B reference) is alive. "
                    f"One-model-at-a-time rule enforced. Use --device cpu or wait for :8082 to be freed."
                )
                msg = f"[{datetime.now(timezone.utc).isoformat()}] {err}"
                self.startup_log.append(msg)
                print(f"ERROR: {err}", file=sys.stderr)
                raise RuntimeError(err)

        # Checkpoint SHA256 validation
        msg = f"[{datetime.now(timezone.utc).isoformat()}] Validating checkpoint SHA256..."
        print(msg, flush=True)
        self.startup_log.append(msg)

        checkpoint_sha = self._sha256_file(checkpoint_path)
        manifest_path = checkpoint_path.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        claimed_sha = (manifest.get("files") or {}).get("model.pt")

        if checkpoint_sha != claimed_sha:
            err = f"Checkpoint SHA256 mismatch: {checkpoint_sha} != {claimed_sha}"
            msg = f"[{datetime.now(timezone.utc).isoformat()}] ERROR: {err}"
            self.startup_log.append(msg)
            print(f"ERROR: {err}", file=sys.stderr)
            raise ValueError(err)

        msg = f"[{datetime.now(timezone.utc).isoformat()}] Checkpoint SHA256 verified: {checkpoint_sha[:16]}..."
        print(msg, flush=True)
        self.startup_log.append(msg)

        # Load state_dict
        msg = f"[{datetime.now(timezone.utc).isoformat()}] Loading state_dict from {checkpoint_path.name}..."
        print(msg, flush=True)
        self.startup_log.append(msg)

        state_dict = torch.load(checkpoint_path, map_location="cpu", weights_only=True)

        # Infer config from shapes
        config_dict = infer_model_config(state_dict)
        self.config = LlamaConfig(**config_dict)

        msg = (
            f"[{datetime.now(timezone.utc).isoformat()}] Config inferred: "
            f"vocab={self.config.vocab_size}, hidden={self.config.hidden_size}, "
            f"intermediate={self.config.intermediate_size}, layers={self.config.num_hidden_layers}"
        )
        print(msg, flush=True)
        self.startup_log.append(msg)

        # Build and load model
        msg = f"[{datetime.now(timezone.utc).isoformat()}] Building model and loading state_dict..."
        print(msg, flush=True)
        self.startup_log.append(msg)

        self.model = LlamaForCausalLM(self.config)
        self.model.load_state_dict(state_dict)
        self.model = self.model.to(device)
        if device == "cuda":
            self.model = self.model.to(torch.bfloat16)
        self.model.eval()

        msg = f"[{datetime.now(timezone.utc).isoformat()}] Model loaded on device={device}"
        print(msg, flush=True)
        self.startup_log.append(msg)

        # Load tokenizer
        if tokenizer_path is None:
            tokenizer_path = TOKENIZER_PATH_DEFAULT

        msg = f"[{datetime.now(timezone.utc).isoformat()}] Loading tokenizer from {tokenizer_path.name}..."
        print(msg, flush=True)
        self.startup_log.append(msg)

        if not tokenizer_path.exists():
            err = f"Tokenizer not found: {tokenizer_path}"
            msg = f"[{datetime.now(timezone.utc).isoformat()}] ERROR: {err}"
            self.startup_log.append(msg)
            print(f"ERROR: {err}", file=sys.stderr)
            raise FileNotFoundError(err)

        from tokenizers import Tokenizer as TokenizersTokenizer
        tk = TokenizersTokenizer.from_file(str(tokenizer_path))
        self.tokenizer = tk

        msg = f"[{datetime.now(timezone.utc).isoformat()}] Tokenizer loaded (vocab_size inferred from checkpoint)"
        print(msg, flush=True)
        self.startup_log.append(msg)

        msg = f"[{datetime.now(timezone.utc).isoformat()}] Server startup complete. Ready for requests."
        print(msg, flush=True)
        self.startup_log.append(msg)

    def generate(self, prompt: str, max_tokens: int = 256, temperature: float = 0.7,
                 top_k: int = 40, top_p: float = 0.95, do_sample: bool = False) -> tuple[str, dict]:
        """Generate completion. Serialized (one-at-a-time on GPU).

        Returns: (completion_text, usage_dict)
        """
        with self.infer_lock:
            # Encode prompt
            encoded = self.tokenizer.encode(prompt, add_special_tokens=False)
            input_ids = encoded.ids

            if not input_ids:
                return "", {"prompt_tokens": 0, "completion_tokens": 0}

            # Prepare input tensor
            inp = torch.tensor([input_ids], device=self.device)

            # Generate (with or without sampling)
            with torch.no_grad():
                if self.device == "cuda":
                    with torch.cuda.amp.autocast(dtype=torch.bfloat16):
                        out = self.model.generate(
                            inp,
                            max_new_tokens=min(max_tokens, 2048),
                            temperature=temperature if do_sample else None,
                            top_k=top_k if do_sample else None,
                            top_p=top_p if do_sample else None,
                            do_sample=do_sample,
                            pad_token_id=self.tokenizer.get_vocab().get("<pad>", 0),
                        )
                else:
                    out = self.model.generate(
                        inp,
                        max_new_tokens=min(max_tokens, 2048),
                        do_sample=False,
                        pad_token_id=0,
                    )

            # Extract new tokens and decode
            new_ids = out[0, len(input_ids):].tolist()
            completion_text = self.tokenizer.decode(new_ids)

            usage = {
                "prompt_tokens": len(input_ids),
                "completion_tokens": len(new_ids),
                "total_tokens": len(input_ids) + len(new_ids),
            }

            return completion_text, usage

    @staticmethod
    def _sha256_file(path: Path) -> str:
        """Compute SHA256 of file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(title="Ember cbase 2.2B OpenAI API", version="1.0")
model_server = ModelServer()


@app.on_event("startup")
async def startup():
    """Load model on startup."""
    args = app.state.args
    model_server.load(
        checkpoint_path=args.checkpoint,
        device=args.device,
        tokenizer_path=args.tokenizer if args.tokenizer else None,
    )


@app.get("/health")
async def health():
    """Health check endpoint. Reports config and startup status."""
    if model_server.model is None:
        return {"status": "loading"}

    return {
        "status": "ready",
        "model": "cbase-2.2b",
        "device": model_server.device,
        "config": {
            "vocab_size": model_server.config.vocab_size,
            "hidden_size": model_server.config.hidden_size,
            "intermediate_size": model_server.config.intermediate_size,
            "num_hidden_layers": model_server.config.num_hidden_layers,
            "num_attention_heads": model_server.config.num_attention_heads,
        } if model_server.config else {},
        "startup_log": model_server.startup_log[-5:],  # Last 5 log lines
    }


@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible /v1/models endpoint."""
    return {
        "object": "list",
        "data": [
            {
                "id": "cbase-2.2b",
                "object": "model",
                "owned_by": "ember",
                "permission": [],
                "created": int(time.time()),
            }
        ],
    }


@app.post("/v1/completions")
async def completions(req: CompletionRequest):
    """OpenAI-compatible /v1/completions endpoint."""
    if model_server.model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    completion_text, usage = model_server.generate(
        prompt=req.prompt,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        top_k=req.top_k,
        top_p=req.top_p,
        do_sample=req.do_sample or req.temperature > 0.0,
    )

    return CompletionResponse(
        id=f"cmpl-{int(time.time() * 1000)}",
        created=int(time.time()),
        choices=[CompletionChoice(text=completion_text, finish_reason="length")],
        usage=usage,
    )


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    """OpenAI-compatible /v1/chat/completions endpoint (naive routing).

    Extracts the last user message and routes to /v1/completions.
    Returns choice with role=assistant in message field.
    """
    if model_server.model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    # Extract last user message as prompt
    prompt = ""
    for msg in reversed(req.messages):
        if msg.role == "user":
            prompt = msg.content
            break

    if not prompt:
        raise HTTPException(status_code=400, detail="No user message found")

    completion_text, usage = model_server.generate(
        prompt=prompt,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        do_sample=req.temperature > 0.0,
    )

    return CompletionResponse(
        id=f"chatcmpl-{int(time.time() * 1000)}",
        created=int(time.time()),
        choices=[
            CompletionChoice(
                message={"role": "assistant", "content": completion_text},
                finish_reason="length",
            )
        ],
        usage=usage,
    )


# ============================================================================
# CLI & Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=CHECKPOINT_PATH_DEFAULT,
        help=f"Path to model checkpoint (default: {CHECKPOINT_PATH_DEFAULT.name})",
    )
    parser.add_argument(
        "--tokenizer",
        type=Path,
        default=TOKENIZER_PATH_DEFAULT,
        help=f"Path to tokenizer.json (default: {TOKENIZER_PATH_DEFAULT.name})",
    )
    parser.add_argument(
        "--device",
        choices=["cuda", "cpu"],
        default="cpu",
        help="Device: cuda (GPU) or cpu. VRAM guard: refuses cuda if :8082/health answers.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=PORT_DEFAULT,
        help=f"Port to listen on (default: {PORT_DEFAULT})",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )

    args = parser.parse_args()

    # Verify checkpoint exists
    if not args.checkpoint.exists():
        print(f"ERROR: Checkpoint not found: {args.checkpoint}", file=sys.stderr)
        sys.exit(1)

    # Store args in app.state for use in startup event
    app.state.args = args

    print(f"Starting server on {args.host}:{args.port} (device={args.device})", flush=True)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
