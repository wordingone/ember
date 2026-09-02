# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import tempfile
from pathlib import Path


def load_checker(root: Path):
    spec = importlib.util.spec_from_file_location("check_line_endings", root / "tools" / "check_line_endings.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_detects_crlf_and_accepts_lf():
    root = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
    checker = load_checker(root)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        lf = tmp / "lf.ts"
        crlf = tmp / "crlf.ts"
        binary = tmp / "bin.dat"
        lf.write_bytes(b"const x = 1;\n")
        crlf.write_bytes(b"const y = 2;\r\n")
        binary.write_bytes(b"\x00\r\n")

        assert checker.find_crlf_files([lf], tmp) == []
        assert checker.find_crlf_files([binary], tmp) == []
        assert checker.find_crlf_files([crlf], tmp) == ["crlf.ts"]


if __name__ == "__main__":
    test_detects_crlf_and_accepts_lf()
    print("check_line_endings_selftest: PASS")