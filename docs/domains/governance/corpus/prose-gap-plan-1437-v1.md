# Issue #1437 prose-gap plan (PREP_ONLY)

Authority: current public master `73d7cd55ad5697877f2164ec887c25d27fc3db43`.
This is a CPU/file-only planning artifact. It does not fetch, move, select,
train, or claim a model/result.

1. **Current clean prose baseline.** The issue audit records 0.747B Wikipedia
   tokens plus 0.506B Gutenberg tokens = 1.253B planning tokens. This is a
   planning baseline, not a newly measured receipt.
2. **Gap target.** The issue names a 1.67B-token prose role gap after the
   `fineweb_edu` exclusion. No excluded classifier-derived source is admitted.
3. **Existing bytes.** arXiv abstracts are recorded as approximately
   0.405–0.670B tokens pending normalization/dedup/decontamination; the
   Stack Exchange dump is approximately 0.9–1.1B but remains UNVERIFIED until
   sampled; CourtListener metadata is near-zero usable prose and contributes
   zero to the plan.
4. **Rule-based candidate wave.** PubMed abstracts (pre-2022, NLM terms), US
   public-domain patents (USPTO), EuroParl/UN open multilingual text, and
   Gutenberg expansion are candidate sources. Each remains zero credited
   tokens until a human provenance/license record, raw-byte SHA/size, and
   canonical connector receipt are present. Their estimates are planning
   ranges only and are not an acquisition/result claim.
5. **Domain floor.** The current wave routing table covers A–K, but routing
   coverage is not acquisition coverage. The importer must recompute admitted
   domain coverage from canonical receipts before any governed training use.

Selection policy: `RULE_BASED` only. No fastText, classifier, embedding,
LLM/model-derived filter, score, rank, or selection is permitted.

## READY_FOR_COMPUTE remainder

Acquire only after the source-inventory bridge (#648) and a future governed
import receipt bind each source URL, SHA-256, bytes, license, human provenance,
fetched timestamp, and deterministic selection rule. Then run the bounded
normalize/dedup/decontaminate consumer and recompute the prose/domain ledger.
