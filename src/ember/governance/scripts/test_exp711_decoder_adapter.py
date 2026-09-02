# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
EXP711_PATH = ROOT / "scripts" / "exp711_intervals.py"
HELPER_PATH = (
    ROOT / "tools" / "ember-restart-3b" / "frozen_tokenizer_decoder.py"
)
TOKENIZER_PATH = ROOT / "domains" / "model" / "tokenizer" / "tokenizer.json"


def _shared_helper():
    spec = importlib.util.spec_from_file_location(
        "frozen_tokenizer_decoder",
        HELPER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.attach_frozen_bytelevel_decoder


def _production_adapter():
    tree = ast.parse(EXP711_PATH.read_text(encoding="utf-8"), EXP711_PATH.name)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_wire_bytelevel_decoder"
    )
    namespace = {"attach_frozen_bytelevel_decoder": _shared_helper()}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), EXP711_PATH.name, "exec"),
        namespace,
    )
    return namespace["_wire_bytelevel_decoder"]


def test_exp711_adapter_reuses_shared_helper_on_exact_frozen_bytes() -> None:
    from tokenizers import Tokenizer

    raw = TOKENIZER_PATH.read_bytes()
    before_sha256 = hashlib.sha256(raw).hexdigest()
    tokenizer = Tokenizer.from_str(raw.decode("utf-8"))
    text = " hello\nEmber"
    token_ids = tokenizer.encode(text).ids
    assert tokenizer.decode(token_ids, skip_special_tokens=False) != text

    result = _production_adapter()(tokenizer, str(TOKENIZER_PATH))

    assert tokenizer.decode(token_ids, skip_special_tokens=False) == text
    assert result["attached"] is True
    assert hashlib.sha256(TOKENIZER_PATH.read_bytes()).hexdigest() == before_sha256


def test_exp711_adapter_contains_no_second_decoder_implementation() -> None:
    source = EXP711_PATH.read_text(encoding="utf-8")
    assert "attach_frozen_bytelevel_decoder(tk, tokenizer_bytes)" in source
    assert "tk.decoder = decoders.ByteLevel()" not in source
