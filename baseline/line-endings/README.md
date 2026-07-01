# Line Ending Policy

Status: DRAFT.

The final `/baseline` directory must be mechanically safe across Windows and Unix checkouts.

Required final controls:

- repo-level `.gitattributes` expectations for `baseline/**`;
- `scripts/check_line_endings.py` receipt in both repos;
- manifest hash after checkout normalization;
- no mixed line endings in scripts, schemas, receipts, or reports.

Suggested `.gitattributes` block:

```gitattributes
baseline/** text eol=lf
baseline/**/*.ps1 text eol=crlf
baseline/**/*.bat text eol=crlf
```

The exact policy may change if the repos already enforce a stronger rule, but the final packet must include a verifier receipt proving the rule.
## Repo Observations On 2026-06-29

- `B:\M\ember\.gitattributes` has `* text=auto eol=lf`, byte-pins several receipt/config/doc paths with `-text`, and enforces `*.sh` and `*.py` as LF.
- `B:\M\ember-public\.gitattributes` enforces several byte-pinned paths and `*.sh`/`*.py` as LF, but differs from the private checkout and did not explicitly mention `baseline/**`.

Final promotion must add or verify an explicit `baseline/**` rule in both repos, then run `scripts/check_line_endings.py` from each checkout and store the receipt.