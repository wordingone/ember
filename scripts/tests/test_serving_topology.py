#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_serving_topology.py — pytest suite for serving topology contract (#516).

CPU-only, no real servers. Tests include:
  - Registry operations (register, deregister, read, find)
  - Identity assertion (success, mismatch, missing fields)
  - Topology drift detection (unregistered server, dead row)

Run via: pytest scripts/tests/test_serving_topology.py -v
"""

import ast
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

import endpoint_identity
import serving_registry
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

    def test_planned_outage_marker_uses_the_canonical_cockpit_state_path(self):
        """A wrong marker location must not silently disable planned-outage handling."""
        expected = Path("tools/ember-cli/state/planned-outage.json")
        assert getattr(serving_registry, "PLANNED_OUTAGE_MARKER_PATH", None) == expected


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

    def test_board_probe_records_both_endpoint_identity_fields(self):
        """A board receipt must never accept a bare /health response as identity."""
        calls = []

        def fake_assert(base_url, expected_model_substring):
            calls.append((base_url, expected_model_substring))
            return {
                "models_field": "cbase-27b",
                "completion_model_field": "cbase-27b",
                "ts": "2026-08-10T12:00:00Z",
            }

        probe = getattr(endpoint_identity, "assert_board_endpoint_identity", None)
        assert callable(probe), "shared board endpoint-identity probe is missing"
        result = probe(
            "http://127.0.0.1:8082/health",
            "27b",
            assert_identity=fake_assert,
        )

        assert calls == [("http://127.0.0.1:8082", "27b")]
        assert result == {
            "reachable": True,
            "models_field": "cbase-27b",
            "completion_model_field": "cbase-27b",
            "ts": "2026-08-10T12:00:00Z",
        }

    @pytest.mark.parametrize(
        "relative_path",
        [
            "cbase_grow_rung2_contended_launch_gate.py",
            "cbase_grow_rung2_gpu_offload_probe.py",
        ],
    )
    def test_board_conditions_delegate_to_the_shared_identity_probe(self, relative_path):
        """Removing the shared call would restore the defective bare-health receipt path."""
        source_path = Path(__file__).parent.parent / relative_path
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        probe_functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_probe_server"
        ]
        assert len(probe_functions) == 1
        calls = [node for node in ast.walk(probe_functions[0]) if isinstance(node, ast.Call)]
        assert any(
            isinstance(call.func, ast.Name)
            and call.func.id == "assert_board_endpoint_identity"
            for call in calls
        ), f"{relative_path} does not bind receipts to endpoint identity"

    def test_board_condition_consumer_census_is_closed(self):
        """The per-consumer proof must fail when a new health-based receipt appears."""
        scripts_dir = Path(__file__).parent.parent
        consumers = {
            path.relative_to(scripts_dir).as_posix()
            for path in scripts_dir.rglob("*.py")
            if "tests" not in path.relative_to(scripts_dir).parts
            and not path.name.startswith("test_")
            and "--server-health-url" in path.read_text(encoding="utf-8")
        }
        assert consumers == {
            "cbase_grow_rung2_contended_launch_gate.py",
            "cbase_grow_rung2_gpu_offload_probe.py",
        }


class TestServeCbaseRegistryLifecycle:
    def test_startup_registers_and_shutdown_deregisters_the_exact_process(self):
        """A running legacy shim must register after load and remove its real PID on exit."""
        source_path = Path(__file__).parent.parent / "serve_cbase_openai.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "startup" in functions
        assert "shutdown" in functions

        startup_calls = [node for node in ast.walk(functions["startup"]) if isinstance(node, ast.Call)]
        shutdown_calls = [node for node in ast.walk(functions["shutdown"]) if isinstance(node, ast.Call)]
        assert any(isinstance(call.func, ast.Name) and call.func.id == "register" for call in startup_calls)
        assert any(isinstance(call.func, ast.Name) and call.func.id == "deregister" for call in shutdown_calls)

        load_call = next(
            call for call in startup_calls
            if isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "model_server"
            and call.func.attr == "load"
        )
        register_call = next(
            call for call in startup_calls
            if isinstance(call.func, ast.Name) and call.func.id == "register"
        )
        assert register_call.lineno > load_call.lineno
        assert len(register_call.args) == 5
        assert isinstance(register_call.args[3], ast.Constant)
        assert register_call.args[3].value == "serve_cbase_openai"

        deregister_call = next(
            call for call in shutdown_calls
            if isinstance(call.func, ast.Name) and call.func.id == "deregister"
        )
        assert len(deregister_call.keywords) == 1
        assert deregister_call.keywords[0].arg == "pid"
        assert isinstance(deregister_call.keywords[0].value, ast.Call)
        assert isinstance(deregister_call.keywords[0].value.func, ast.Attribute)
        assert deregister_call.keywords[0].value.func.attr == "getpid"


class TestCliManagedSpawnAuthority:
    def test_legacy_spawn_path_carries_the_registry_integration_contract(self):
        """AC5 preserves the path but makes its registry obligation explicit."""
        source_path = (
            Path(__file__).parents[2]
            / "tools"
            / "ember-cli"
            / "src"
            / "entrypoints"
            / "owned-server-supervisor.ts"
        )
        source = source_path.read_text(encoding="utf-8")
        ensure_body = source.split("export async function ensureOwnedServer(", 1)[1]
        assert "(deps.spawnServer ?? defaultSpawnServer)(command)" in ensure_body
        assert "legacy direct-spawn path remains in this TypeScript owner" in ensure_body
        assert "must consult the canonical serving registry before spawning" in ensure_body
        assert "#1282" in ensure_body


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
