# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = (
    ROOT / "tools" / "ember-restart-3b" / "frozen_tokenizer_decoder.py"
)
if str(ROOT / "tools" / "ember-restart-3b") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
from repository_layout import resolve_repository_authority  # noqa: E402

FROZEN_TOKENIZER_PATH = resolve_repository_authority(ROOT, "tokenizer").path


def _load_helper():
    assert HELPER_PATH.is_file(), "shared frozen-tokenizer decoder helper is absent"
    spec = importlib.util.spec_from_file_location(
        "frozen_tokenizer_decoder",
        HELPER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.attach_frozen_bytelevel_decoder


def test_real_frozen_tokenizer_attaches_bytelevel_decoder_without_byte_drift() -> None:
    from tokenizers import Tokenizer

    raw = FROZEN_TOKENIZER_PATH.read_bytes()
    before_sha256 = hashlib.sha256(raw).hexdigest()
    tokenizer = Tokenizer.from_str(raw.decode("utf-8"))
    text = " hello\nEmber"
    token_ids = tokenizer.encode(text).ids

    assert tokenizer.decode(token_ids, skip_special_tokens=False) != text

    result = _load_helper()(tokenizer, raw)

    assert tokenizer.decode(token_ids, skip_special_tokens=False) == text
    assert result == {
        "attached": True,
        "reason": "attached ByteLevel decoder in memory",
    }
    assert (
        hashlib.sha256(FROZEN_TOKENIZER_PATH.read_bytes()).hexdigest() == before_sha256
    )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"\xff", "strict UTF-8"),
        (b"{", "valid JSON object"),
        (
            json.dumps(
                {
                    "pre_tokenizer": {"type": "Whitespace"},
                    "decoder": None,
                }
            ).encode("utf-8"),
            "pre_tokenizer.type must be ByteLevel",
        ),
    ],
)
def test_helper_refuses_untrusted_tokenizer_contracts(
    raw: bytes,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _load_helper()(SimpleNamespace(decoder=None), raw)


def test_helper_preserves_explicit_on_disk_decoder() -> None:
    marker = object()
    tokenizer = SimpleNamespace(decoder=marker)
    raw = json.dumps(
        {
            "pre_tokenizer": {"type": "ByteLevel"},
            "decoder": {"type": "ByteLevel"},
        }
    ).encode("utf-8")

    result = _load_helper()(tokenizer, raw)

    assert tokenizer.decoder is marker
    assert result == {
        "attached": False,
        "reason": "explicit on-disk decoder preserved",
    }
