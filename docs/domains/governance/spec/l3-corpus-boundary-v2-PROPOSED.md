# L3 Corpus Boundary Ruling v2 — PROPOSED

**STATUS: PROPOSED** — constitutional interpretation; binding only on operator ratification (GOAL.md precedence: INVARIANT > constitution > protocol docs). Derived via adversarial panel review; provenance: research loop 2026-07-07.

---

## The Ruling (8 principles)

1. **Custody point (normative)** — Custody begins at the earliest point where a named DATASET/COLLECTION object with its own membership decisions exists. Everything constituting that object's membership and content is in audit scope — regardless of who executed it or when. De minimis scope: ONLY item-level transforms applied uniformly and membership-blindly (codec, resize, ISP). "Uniform and membership-blind" is the checkable predicate.

2. **External-model-free, not model-free** — The constitutional predicate is EXTERNAL. Locally-trained learned components, trained on L4-receipted clean data under corpus lineage, are admissible in ANY pipeline role. External-trained components of any capacity (fastText, off-the-shelf embeddings, pretrained hash nets) are taint in membership/content roles. Deterministic non-fit procedures (regex, fixed published hash algorithms, byte dedup) are always admissible.

3. **Metadata provenance** — Membership rules may consume only human-authored, physical (EXIF dims/timestamps), or legal (license string) metadata fields. Model-generated fields (Flickr interestingness, ORES scores, platform quality ranks) are taint INPUTS. Enumerative membership rules (lookup tables, hash lists, per-item allowlists) are banned unless stateable as a pre-registered human-authorable predicate.

4. **Vintage → per-modality artifact-vintage RISK PRIOR** — No blanket post-2022 ban. Plausible-synthesis content classes require positive human-provenance evidence (institutional scan records, recording session receipts, edit histories); artifact-vintage guards apply per modality (e.g. speech recordings ≤ pre-TTS-boom releases unless provenance-receipted).

5. **Upstream recovery** — Item enumeration from the upstream's OWN catalog (never the derived dataset's manifests — inheriting its item list inherits its rejections); bootstrap trained flat-start on receipted-clean pairs; the abandoned external-processed artifact may NEVER serve as validation/tuning target for the replacement pipeline (agreement-with-the-banned-artifact is distillation through the evaluation channel).

6. **Realized corpus** — Rule evaluates the corpus AS REALIZED — attrition/fetch failure receipted; frozen tarballs and point-in-time archives preferred; URL-resolution against live moderated platforms beyond an attrition threshold is archive-required or taint (selection-by-survival imports platform moderation models).

7. **Support provenance** — Human review cleanses label quality only, never upstream selection taint — the candidate pool over which humans decide must itself be clean (AudioSet's human confirmation does not cure query-by-example nomination).

8. **Degeneracy amendment** — AudioSet adds the row "learned nomination + human confirm = still taint."

---

## Boundary-Derivation: Three Candidate Rulings (Degeneracy Audit)

### A. Bytes-Only (REJECTED)

**Text:** Only model-authored bytes taint.

**Why killed:** Admits LAION; contradicts L3's own constitutional text ("filters, ranks, scores, or selects"). Rejected by the constitutional text itself.

---

### B. Any-Model-Anywhere (REJECTED)

**Text:** Whole causal history — any model touched the upstream supply chain.

**Why killed:** Camera-ISP neural denoising taints every modern photo; clean set = ∅; C1 unsatisfiable BY INTERPRETATION → manufactures a fake scope expansion. Rejected by degeneracy + constitutional coherence (a reading under which the constitution self-defeats cannot be intended).

---

### C. Custody-Scoped Re-Derivability (ADOPTED)

**Text:** A membership/content decision is CLEAN iff exactly recomputable from raw item + metadata by a local model-free rule (resolution floor: yes; license field: yes; learned aesthetic score: no — requires external model weights).

**Why kept:** Discriminates all six grounded cases correctly; survives out-of-distribution induction (OCR-authored text = M1 taint; scan-image + human catalog metadata = clean; corpus-lineage OCR = clean under principle 2's generator clause).

---

## Six-Source Classification (from grounding section)

| Source | Documented pipeline | L3-relevant decision | Pipeline custody |
|---|---|---|---|
| Wikimedia PD12M (12.4M img-txt) | GLAM→8.7M flagged for removal (method undocumented) → 256px floor → **"aesthetic score assigned to each image using a model trained on internal dataset"**, bottom 50% EXCLUDED | learned aesthetic model SELECTS half corpus | upstream ~38M pool on Source.Plus; HF-hosted |
| YFCC100M (99.2M photos) | CC-license-metadata selection only; text = human titles/tags | none documented | 12.5GB metadata archive durable; image bytes = Flickr URLs (rot) |
| LibriSpeech (1000h) | LibriVox PD audiobooks **decoded by external ASR (VoxForge-trained, Kaldi)**; Smith-Waterman match vs reference to segment; disagreeing segments dropped | ASR segments AND gates membership | raw upstream = LibriVox chapters + Gutenberg texts, both PD/durable |
| AudioSet | YouTube candidates via metadata AND **"query-by-example method"**; humans confirm labels only | learned similarity NOMINATES membership | YouTube bytes (rot + ToS) |
| Common Voice (CC0) | volunteers READ sentences; dual human review (2 upvotes) | none (human record + human validate) | versioned tarballs, durable |
| Smithsonian Open Access | institutional curation; CC0; 5.1M 2D/3D images + 11M metadata records | none documented (human/institutional) | bulk JSON GitHub (weekly refresh) + AWS open data |

---

## Named Accepted Residuals (Documented, never assumed away)

- **Human cognition out of audit scope:** a curator's model-assisted search is invisible to pipeline documentation.
- **Upstream platform internals:** undocumented platform-side quality/moderation operations.
- **Date-metadata trust:** artifact-vintage guards rely on human-provided timestamps in metadata.

---

## Smuggled Assumptions Caught (Extracted this review)

1. **Enactment authority** — This ruling is a CONSTITUTIONAL INTERPRETATION changing what data enters training ⇒ ships as PROPOSED governance artifact for operator ratification, never enacted unilaterally.

2. **Upstream obtainability** — PD12M's 38M pre-cut pool; LibriVox raw upstream is rank-0 until per-source probes receipt it (no assumption of availability).

3. **"Human = clean" is a practicable line** over DOCUMENTED pipeline steps, not a metaphysical claim about human cognition.

---

## References

- **Grounding sources:** Wikimedia Foundation (PD12M), YFCC (Yahoo Flickr Creative Commons), LibriVox project, AudioSet documentation, Common Voice project, Smithsonian Institution Open Access metadata.
- **Field-level citations:** constitutional text, L3 + L4 definitions, corpus lineage specification.
