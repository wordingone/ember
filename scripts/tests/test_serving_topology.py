#!/usr/bin/env python3
"""test_serving_topology.py — pytest suite for serving topology contract (#516).

CPU-only, no real servers. Tests include:
  - Registry operations (register, deregister, read, find)
  - Identity assertion (success, mismatch, missing fields)
  - Topology drift detection (unregistered server, dead row)

Run via: pytest scripts/tests/test_serving_topology.py -v
"""

import json
import os
import sys
import tempfile
import unittest.mock as mock
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO

import pytest

# Add scripts to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from serving_registry import register, deregister, read, find_for_model
from endpoint_identity import assert_endpoint_identity


class TestServingRegistry:
    """Test serving_registry module."""

    def test_register_single(self):
        """Test registering a single server."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            row = register(8082, "/path/to/model27b", 1234, "watchdog", "cuda", registry_path)

            assert row["port"] == 8082
            assert row["model_path"] == "/path/to/model27b"
            assert row["pid"] == 1234
            assert row["launched_by"] == "watchdog"
            assert row["device"] == "cuda"
            assert "ts" in row

            # Verify persisted
            rows = read(registry_path)
            assert len(rows) == 1
            assert rows[0]["port"] == 8082

    def test_register_multiple(self):
        """Test registering multiple servers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            register(8082, "/path/to/model27b", 1234, "watchdog", "cuda", registry_path)
            register(8083, "/path/to/model2.2b", 5678, "serve_cbase_openai", "cuda", registry_path)

            rows = read(registry_path)
            assert len(rows) == 2
            assert rows[0]["port"] == 8082
            assert rows[1]["port"] == 8083

    def test_deregister_by_port(self):
        """Test deregistering by port."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            register(8082, "/path/to/model27b", 1234, "watchdog", "cuda", registry_path)
            register(8083, "/path/to/model2.2b", 5678, "serve_cbase_openai", "cuda", registry_path)

            removed = deregister(port=8082, registry_path=registry_path)
            assert removed == 1

            rows = read(registry_path)
            assert len(rows) == 1
            assert rows[0]["port"] == 8083

    def test_deregister_by_pid(self):
        """Test deregistering by pid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            register(8082, "/path/to/model27b", 1234, "watchdog", "cuda", registry_path)
            register(8083, "/path/to/model2.2b", 5678, "serve_cbase_openai", "cuda", registry_path)

            removed = deregister(pid=5678, registry_path=registry_path)
            assert removed == 1

            rows = read(registry_path)
            assert len(rows) == 1
            assert rows[0]["pid"] == 1234

    def test_read_nonexistent(self):
        """Test reading a nonexistent registry returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "nonexistent.json"
            rows = read(registry_path)
            assert rows == []

    def test_find_for_model_found(self):
        """Test finding a server by model path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            register(8082, "/path/to/model27b", 1234, "watchdog", "cuda", registry_path)
            register(8083, "/path/to/model2.2b", 5678, "serve_cbase_openai", "cuda", registry_path)

            found = find_for_model("/path/to/model27b", registry_path)
            assert found is not None
            assert found["port"] == 8082
            assert found["pid"] == 1234

    def test_find_for_model_not_found(self):
        """Test finding a nonexistent model returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            register(8082, "/path/to/model27b", 1234, "watchdog", "cuda", registry_path)

            found = find_for_model("/path/to/nonexistent", registry_path)
            assert found is None


class TestEndpointIdentity:
    """Test endpoint_identity module."""

    def test_assert_endpoint_identity_success(self):
        """Test successful identity assertion with matching model."""

        def mock_urlopen(url, *args, **kwargs):
            # url can be a string or Request object
            url_str = url.full_url if hasattr(url, 'full_url') else str(url)

            if "/v1/models" in url_str:
                response_data = json.dumps({"data": [{"id": "cbase-27b"}]})
            elif "/v1/completions" in url_str:
                response_data = json.dumps(
                    {
                        "model": "cbase-27b",
                        "choices": [{"text": "test"}],
                    }
                )
            else:
                raise ValueError(f"Unexpected URL: {url_str}")

            response_obj = mock.MagicMock()
            response_obj.read.return_value = response_data.encode("utf-8")
            response_obj.__enter__ = lambda s: s
            response_obj.__exit__ = lambda s, *a: None
            return response_obj

        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = assert_endpoint_identity("http://localhost:8082", "27b")
            assert result["models_field"] == "cbase-27b"
            assert result["completion_model_field"] == "cbase-27b"
            assert "ts" in result

    def test_assert_endpoint_identity_model_mismatch(self):
        """Test identity assertion fails on model mismatch between endpoints."""

        def mock_urlopen(url, *args, **kwargs):
            # url can be a string or Request object
            url_str = url.full_url if hasattr(url, 'full_url') else str(url)

            if "/v1/models" in url_str:
                response_data = json.dumps({"data": [{"id": "cbase-27b"}]})
            elif "/v1/completions" in url_str:
                response_data = json.dumps(
                    {
                        "model": "cbase-2.2b",  # Different model!
                        "choices": [{"text": "test"}],
                    }
                )
            else:
                raise ValueError(f"Unexpected URL: {url_str}")

            response_obj = mock.MagicMock()
            response_obj.read.return_value = response_data.encode("utf-8")
            response_obj.__enter__ = lambda s: s
            response_obj.__exit__ = lambda s, *a: None
            return response_obj

        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with pytest.raises(ValueError, match="Model mismatch"):
                assert_endpoint_identity("http://localhost:8082", "27b")

    def test_assert_endpoint_identity_substring_mismatch(self):
        """Test identity assertion fails on substring mismatch."""

        def mock_urlopen(url, *args, **kwargs):
            # url can be a string or Request object
            url_str = url.full_url if hasattr(url, 'full_url') else str(url)

            if "/v1/models" in url_str:
                response_data = json.dumps({"data": [{"id": "cbase-2.2b"}]})
            elif "/v1/completions" in url_str:
                response_data = json.dumps(
                    {
                        "model": "cbase-2.2b",
                        "choices": [{"text": "test"}],
                    }
                )
            else:
                raise ValueError(f"Unexpected URL: {url_str}")

            response_obj = mock.MagicMock()
            response_obj.read.return_value = response_data.encode("utf-8")
            response_obj.__enter__ = lambda s: s
            response_obj.__exit__ = lambda s, *a: None
            return response_obj

        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with pytest.raises(ValueError, match="does not contain"):
                assert_endpoint_identity("http://localhost:8082", "27b")  # expects 27b, got 2.2b

    def test_assert_endpoint_identity_connection_failure(self):
        """Test identity assertion fails on connection error."""

        def mock_urlopen_fail(url, *args, **kwargs):
            raise ConnectionError("Connection refused")

        with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen_fail):
            with pytest.raises(ValueError, match="Failed to fetch"):
                assert_endpoint_identity("http://localhost:8082", "27b")


class TestTopologyDrift:
    """Test topology drift detection (mock process listing)."""

    def test_unregistered_server_detected(self):
        """Test that an unregistered server (in process list but not registry) is detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            # Registry has one entry: 8082 with PID 1000
            register(8082, "/path/to/model27b", 1000, "watchdog", "cuda", registry_path)

            # Simulate process list having PIDs [1000, 2000] (2000 is unregistered)
            mock_live_pids = [1000, 2000]

            rows = read(registry_path)
            registered_pids = {r["pid"] for r in rows}

            unregistered = set(mock_live_pids) - registered_pids
            assert 2000 in unregistered, "Should detect unregistered PID 2000"

    def test_dead_server_detected(self):
        """Test that a dead registered server (in registry but not process list) is detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            # Registry has one entry: 8082 with PID 1000 (dead)
            register(8082, "/path/to/model27b", 1000, "watchdog", "cuda", registry_path)

            # Simulate process list having no servers (empty)
            mock_live_pids = []

            rows = read(registry_path)
            registered_pids = {r["pid"] for r in rows}

            dead = registered_pids - set(mock_live_pids)
            assert 1000 in dead, "Should detect dead PID 1000"

    def test_topology_consistency(self):
        """Test that topology is consistent when live PIDs match registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            # Register two servers
            register(8082, "/path/to/model27b", 1000, "watchdog", "cuda", registry_path)
            register(8083, "/path/to/model2.2b", 2000, "serve_cbase_openai", "cuda", registry_path)

            # Simulate process list matching registry
            mock_live_pids = [1000, 2000]

            rows = read(registry_path)
            registered_pids = {r["pid"] for r in rows}

            unregistered = set(mock_live_pids) - registered_pids
            dead = registered_pids - set(mock_live_pids)

            assert len(unregistered) == 0, "Should have no unregistered PIDs"
            assert len(dead) == 0, "Should have no dead PIDs"


# Optional: test that can be run from CLI
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
