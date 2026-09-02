# PDF-to-UTF-8 corpus extraction

This carrier adds a bounded, receipt-producing transform for connector-acquired
PDFs that cannot enter the text corpus as strict UTF-8. It does not acquire
data, run OCR, admit corpus rows by itself, or replace the source PDF.

## Runtime and dependency

Extraction is deliberately pinned to CPython 3.10 and `pypdf==6.16.1`. Install
the wheel into an isolated target using the repository lock file:

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -File $env:USERPROFILE\.codex\headless-python.ps1 -- -B -m pip install --require-hashes --only-binary=:all: --no-deps --target <dependency-target> -r src\ember\infrastructure\tools\corpus_connectors\requirements-pdf-to-utf8.cfg
```

Set `PYTHONPATH` to that isolated target when invoking
`src/ember/infrastructure/tools/corpus_connectors/pdf_to_utf8.py`. The producer refuses any other Python
major/minor or pypdf version. Its receipt binds the wheel digest, installed
Python-source tree digest, full Python version, producer digest, source
connector receipt, immutable source PDF, limits, normalized output, and receipt
self-hash.

## Closed behavior

- The connector receipt must contain exactly one regular, non-reparse PDF whose
  bytes and hashes rederive.
- The source PDF remains in its original connector custody.
- Extraction uses pypdf only. OCR, subprocesses, system PDF tools, network
  fallback, and alternate parsers are forbidden.
- Page count, decoded content bytes, and normalized UTF-8 output bytes are
  bounded. Empty extracted text is refused.
- Text is normalized to Unicode NFC, LF newlines, and exactly one trailing
  newline.
- Output custody is exclusive/no-overwrite. The receipt is published last, and
  verification reopens the source and independently re-extracts byte-identical
  output.
- `text_lab_corpus.adapt_pdf_extraction_receipt` is the only admission adapter;
  it re-verifies the transform and then applies the existing publisher and
  license-evidence rules.

## Test split

The pure refusal/contract tests run under the repository CI interpreter. Tests
that execute pypdf are explicitly skipped outside CPython 3.10 with the reason
`approved PDF extraction integration requires named Python 3.10`. The complete
producer and adapter integration suites must additionally pass under the named
CPython 3.10 runtime with the pinned wheel before review or publication.

This is source capability only. The C-heldout-1, D-train-1, and J-heldout-1
artifacts must be produced after this carrier is independently reviewed and
merged; their own receipts and downstream authority-index admission remain
separate execution evidence.
