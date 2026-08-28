# Frozen tokenizer decoder convention

`tokenizer/tokenizer.json` is a byte-frozen Ember artifact. Its on-disk
`pre_tokenizer.type` is `ByteLevel`, while its on-disk `decoder` is `null`.
Changing those bytes would invalidate existing tokenizer and lineage hashes, so
decode consumers must not repair the tracked artifact in place.

Any Ember consumer that decodes IDs from these frozen bytes must call
`tools/ember-restart-3b/frozen_tokenizer_decoder.py::
attach_frozen_bytelevel_decoder` on the
same byte snapshot used to construct the `tokenizers.Tokenizer`. The helper:

1. strictly decodes and parses the tokenizer JSON;
2. verifies that the pre-tokenizer type is exactly `ByteLevel`;
3. preserves an explicit on-disk decoder without overriding it; and
4. attaches `tokenizers.decoders.ByteLevel()` in memory only when the on-disk
   decoder is `null`.

Unknown or malformed tokenizer contracts fail closed. Consumers must not guess
a decoder from filenames, configuration prose, or a separately read file.
Future tokenizer re-freezes may include an explicit decoder; once they do, the
helper preserves that decoder and performs no in-memory override.

This convention repairs text reconstruction only. It does not establish model,
training, benchmark, or capability evidence.
