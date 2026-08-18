# Issue 1719 deterministic arXiv paper-list selector

Status: source carrier only. The selector emits a fetch input; it does not retrieve, admit, tokenize, or train on a paper.

## Purpose

Several unresolved corpus rows share one already-frozen arXiv OAI snapshot but require different exact content licenses, categories, dates, thematic subsets, and disjointness exclusions. The existing CC-BY residue splitter remains unchanged. This carrier adds one general selector instead of one script per row.

## Closed input

The caller supplies a strict JSON specification with exactly:

- a caller-declared `as_of` timestamp;
- one enumerated canonical content-license URL, compared by exact string equality;
- a sorted unique category allowlist and explicit `any` or `all` mode;
- an optional closed inclusive creation-date interval;
- an optional regex whose pattern, `search` or `fullmatch` mode, and case flag are recorded verbatim;
- zero or more prior paper lists, each reopened by raw SHA-256;
- a stable selection label.

Only the canonical CC0 and CC-BY-4.0 URLs are enumerated. Scheme or trailing-slash variants are not normalized. A near variant is separately counted as `license_url_variant`.

## Deterministic derivation

The selector reopens and hashes every XML page, parses every OAI record, and applies one reason-precedence chain: missing metadata, exact license, category, date, optional text filter, then bound exclusion. Versioned or malformed identifiers and duplicates refuse the whole operation. Accepted IDs are ordered by the full SHA-256 of the raw unversioned ID.

The manifest records the complete page inventory, raw specification binding, prior-list bindings, exact predicate, output hash, and exhaustive rejected counts. Production asserts:

`accepted + sum(rejected_by_reason) == parsed`

An empty selection refuses. Output is staged, independently rederived, renamed without overwrite, and reopened with an exact two-file custody set.

## Consumer boundary

The dedicated test passes the emitted `paper-list.txt` through the existing `arxiv_fetch.read_paper_list` function. This proves the first real fetch consumer accepts the emitted format without making a network call. Actual fetches remain separately governed by per-row byte caps, content-license evidence, the 250 GiB floor, and connector receipts.

## Claim boundary

This source carrier proves only deterministic list selection from frozen bytes. It supplies no corpus admission, model execution, benchmark, capability, milestone-completion, or issue-terminal evidence.
