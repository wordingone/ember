# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Triton C-compiler binding for the CIA fused elementwise path (#1945).

The governed measurement-2 worker refused on 2026-09-11 with Triton's "Failed to find C compiler": Triton looks for
its bundled TinyCC under sysconfig's platlib (the system site) while the wheel is installed in the user site, and the
governed environment carries no cl/gcc/clang on PATH. These CPU-only cases prove `bind_triton_c_compiler` resolves the
INSTALLED Triton package's bundled tcc module-relatively, records its sha256, exports it as CC exactly once, honours an
explicit CC that exists, refuses a missing compiler without falling back, and runs before the first inductor compile.
They do not compile anything and establish no throughput or conformance claim.
"""
import hashlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ember.model import ember_v0_decoder as subject  # noqa: E402

RUNNER = Path(__file__).resolve().parents[1] / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "cia_step_runner.py"


class _Env:
    """Save/restore CC, the module cache and the fake triton module around each case."""

    def __enter__(self):
        self.cc = os.environ.get("CC")
        self.triton = sys.modules.get("triton")
        self.compiler = subject._C_COMPILER
        self.fused = dict(subject._FUSED)
        os.environ.pop("CC", None)
        subject._C_COMPILER = None
        subject._FUSED.clear()
        return self

    def __exit__(self, *exc):
        if self.cc is None:
            os.environ.pop("CC", None)
        else:
            os.environ["CC"] = self.cc
        if self.triton is None:
            sys.modules.pop("triton", None)
        else:
            sys.modules["triton"] = self.triton
        subject._C_COMPILER = self.compiler
        subject._FUSED.clear()
        subject._FUSED.update(self.fused)


def fake_triton(root, *, with_tcc=True):
    """A stand-in triton package rooted at `root`, with or without runtime/tcc/tcc.exe."""
    package = Path(root) / "site-packages" / "triton"
    (package / "runtime" / "tcc").mkdir(parents=True)
    (package / "__init__.py").write_bytes(b"")
    if with_tcc:
        (package / "runtime" / "tcc" / "tcc.exe").write_bytes(b"MZ-tinycc-stand-in-" + os.urandom(8))
    module = types.ModuleType("triton")
    module.__file__ = str(package / "__init__.py")
    sys.modules["triton"] = module
    # The binding resolves the module path (8.3 short names / case on Windows), so the expectation is resolved too.
    return (package / "runtime" / "tcc" / "tcc.exe").resolve()


class BundledCompilerTests(unittest.TestCase):
    def test_resolves_installed_triton_bundled_tcc_and_exports_cc_once(self):
        with _Env(), tempfile.TemporaryDirectory() as root:
            tcc = fake_triton(root)
            binding = subject.bind_triton_c_compiler()
            self.assertEqual(binding["path"], str(tcc))
            self.assertEqual(binding["sha256"], hashlib.sha256(tcc.read_bytes()).hexdigest())
            self.assertEqual(binding["source"], "triton bundled tcc")
            self.assertEqual(os.environ["CC"], str(tcc))
            # Cached: a second call neither re-reads nor re-resolves (the file may be gone; the binding stands).
            tcc.unlink()
            sys.modules.pop("triton")
            self.assertEqual(subject.bind_triton_c_compiler(), binding)
            self.assertIsNot(subject.bind_triton_c_compiler(), binding)  # a copy, not the cache itself

    def test_resolution_is_module_relative_not_sysconfig(self):
        import sysconfig
        with _Env(), tempfile.TemporaryDirectory() as root:
            tcc = fake_triton(root)
            platlib = Path(sysconfig.get_paths()["platlib"]) / "triton" / "runtime" / "tcc" / "tcc.exe"
            self.assertNotEqual(str(tcc), str(platlib))
            self.assertEqual(subject.bind_triton_c_compiler()["path"], str(tcc))

    def test_missing_bundled_tcc_refuses_without_fallback(self):
        with _Env(), tempfile.TemporaryDirectory() as root:
            fake_triton(root, with_tcc=False)
            with self.assertRaises(RuntimeError) as caught:
                subject.bind_triton_c_compiler()
            self.assertIn("bundled TinyCC", str(caught.exception))
            self.assertNotIn("CC", os.environ)
            self.assertIsNone(subject._C_COMPILER)


class ExplicitCompilerTests(unittest.TestCase):
    def test_explicit_existing_cc_is_used_and_recorded(self):
        with _Env(), tempfile.TemporaryDirectory() as root:
            explicit = Path(root) / "cl.exe"
            explicit.write_bytes(b"explicit-compiler")
            os.environ["CC"] = str(explicit)
            fake_triton(root)  # present, but must not be chosen over an explicit CC
            binding = subject.bind_triton_c_compiler()
            self.assertEqual(binding["path"], str(explicit))
            self.assertEqual(binding["source"], "explicit CC")
            self.assertEqual(binding["sha256"], hashlib.sha256(b"explicit-compiler").hexdigest())
            self.assertEqual(os.environ["CC"], str(explicit))

    def test_explicit_missing_cc_refuses(self):
        with _Env(), tempfile.TemporaryDirectory() as root:
            os.environ["CC"] = str(Path(root) / "absent.exe")
            fake_triton(root)
            with self.assertRaises(RuntimeError) as caught:
                subject.bind_triton_c_compiler()
            self.assertIn("does not exist", str(caught.exception))
            self.assertIsNone(subject._C_COMPILER)


class OrderingTests(unittest.TestCase):
    def test_fused_elementwise_binds_before_the_first_compile(self):
        import torch
        with _Env(), tempfile.TemporaryDirectory() as root:
            tcc = fake_triton(root)
            seen = []
            original = torch.compile

            def recording_compile(function):
                seen.append((os.environ.get("CC"), subject._C_COMPILER is not None))
                return function

            torch.compile = recording_compile
            try:
                self.assertIs(subject.fused_elementwise("norm"), subject._rms_norm)
                self.assertIs(subject.fused_elementwise("norm"), subject._rms_norm)  # cached; no second compile
            finally:
                torch.compile = original
            self.assertEqual(seen, [(str(tcc), True)])

    def test_fused_elementwise_refuses_before_compiling_when_no_compiler(self):
        import torch
        with _Env(), tempfile.TemporaryDirectory() as root:
            fake_triton(root, with_tcc=False)
            original = torch.compile
            torch.compile = lambda function: self.fail("compile reached without a bound compiler")
            try:
                with self.assertRaises(RuntimeError):
                    subject.fused_elementwise("norm")
            finally:
                torch.compile = original
            self.assertEqual(subject._FUSED, {})

    def test_worker_binds_before_activation_and_records_it(self):
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("def worker(")
        body = source[start:source.index("\ndef ", start + 1)]
        bind = body.index("bind_triton_c_compiler()")
        self.assertLess(bind, body.index("model.activate_cuda(device)"))
        self.assertLess(bind, body.index("measure_step("))
        self.assertIn("'c_compiler': c_compiler", body)


if __name__ == "__main__":
    unittest.main()
