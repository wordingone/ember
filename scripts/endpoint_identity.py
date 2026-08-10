#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""endpoint_identity.py — identity assertion for OpenAI-compatible endpoints (#516).

Contract: assert_endpoint_identity(base_url, expected_model_substring) verifies that
an endpoint serves the expected model by:
  1. GET /v1/models -> extract model field from response
  2. POST /v1/completions with 1-token prompt -> extract model field from choice
  3. Compare both against expected_model_substring
  4. Return {models_field, completion_model_field, ts} on match
  5. Raise on mismatch or connectivity failure

Receipts: every board probe that consumes a serving endpoint MUST record both fields.
A bare /health 200 is defective and insufficient for identity verification.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Optional


def _now_iso() -> str:
    """Return current UTC time in ISO8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_endpoint_identity(
    base_url: str,
    expected_model_substring: str,
    timeout_sec: int = 10,
) -> dict[str, Any]:
    """Verify endpoint identity by querying /v1/models and running a test completion.

    Args:
        base_url: e.g., "http://localhost:8082"
        expected_model_substring: substring to match (e.g., "27b", "2.2b")
        timeout_sec: request timeout in seconds

    Returns:
        {
            "models_field": "<model name from GET /v1/models>",
            "completion_model_field": "<model name from POST /v1/completions>",
            "ts": "<ISO8601 timestamp>",
        }

    Raises:
        ValueError: if endpoint is unreachable, response is malformed, or model mismatch
    """
    base_url = base_url.rstrip("/")

    # Fetch /v1/models
    models_url = f"{base_url}/v1/models"
    try:
        with urllib.request.urlopen(models_url, timeout=timeout_sec) as resp:
            models_response = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to fetch {models_url}: {e}") from e

    # Extract model field from models endpoint
    models_field = None
    if isinstance(models_response, dict):
        data = models_response.get("data")
        if isinstance(data, list) and len(data) > 0:
            models_field = data[0].get("id")

    if not models_field:
        raise ValueError(f"Could not extract model from {models_url}: response = {models_response}")

    # Run a 1-token completion
    completion_url = f"{base_url}/v1/completions"
    completion_request = {
        "model": models_field,
        "prompt": ".",
        "max_tokens": 1,
        "temperature": 0.0,
    }
    try:
        req = urllib.request.Request(
            completion_url,
            data=json.dumps(completion_request).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            completion_response = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to POST {completion_url}: {e}") from e

    # Extract model field from completion response
    completion_model_field = completion_response.get("model")
    if not completion_model_field:
        raise ValueError(
            f"Could not extract model from completion response: {completion_response}"
        )

    # Verify match
    if models_field != completion_model_field:
        raise ValueError(
            f"Model mismatch: /v1/models says {models_field!r}, "
            f"/v1/completions says {completion_model_field!r}"
        )

    # Verify substring match
    if expected_model_substring not in models_field:
        raise ValueError(
            f"Model {models_field!r} does not contain {expected_model_substring!r}"
        )

    return {
        "models_field": models_field,
        "completion_model_field": completion_model_field,
        "ts": _now_iso(),
    }


def assert_board_endpoint_identity(
    endpoint_url: str,
    expected_model_substring: str,
    *,
    assert_identity: Optional[Callable[[str, str], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Return one receipt-shaped board observation backed by model identity.

    Historical board callers pass a ``.../health`` URL.  This adapter removes
    only that exact suffix and delegates to :func:`assert_endpoint_identity`,
    so a reachable but foreign model is recorded as a failed observation rather
    than a green bare-health receipt.
    """
    normalized = endpoint_url.rstrip("/")
    if normalized.endswith("/health"):
        normalized = normalized[: -len("/health")]
    verifier = assert_identity or assert_endpoint_identity
    try:
        identity = verifier(normalized, expected_model_substring)
        return {"reachable": True, **identity}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


# Self-test (run via: python endpoint_identity.py selftest <url> <substring>)
def _selftest():
    """Quick self-test with a mock endpoint (test mode)."""
    import unittest.mock as mock

    # Mock endpoint that returns consistent model name
    def mock_urlopen(url, *args, **kwargs):
        from io import BytesIO

        # url can be a string or Request object
        url_str = url.full_url if hasattr(url, 'full_url') else str(url)

        if "/v1/models" in url_str:
            response_data = json.dumps({"data": [{"id": "test-model-27b"}]})
        elif "/v1/completions" in url_str:
            response_data = json.dumps(
                {
                    "model": "test-model-27b",
                    "choices": [{"text": "test"}],
                }
            )
        else:
            raise ValueError(f"Unexpected URL: {url_str}")

        return mock.MagicMock(__enter__=lambda s: s, __exit__=lambda *a: None,
                              read=lambda: response_data.encode("utf-8"))

    with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen):
        result = assert_endpoint_identity("http://localhost:8082", "27b")
        assert result["models_field"] == "test-model-27b"
        assert result["completion_model_field"] == "test-model-27b"
        assert "ts" in result
        print("Self-test passed!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
    else:
        print(__doc__)
