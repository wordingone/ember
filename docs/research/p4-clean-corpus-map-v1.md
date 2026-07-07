# P4: Clean-Corpus Map v1

**Derived:** research loop tick 8, panel-reviewed (2026-07-07). Per-source classification under L3 Corpus Boundary Ruling v2. All feasibility figures preserve "unreceipted" estimate flags as documented.

---

## 1. Grounded Source Inventory (Six Primary Sources)

| Source | Documented pipeline | L3 Classification | Custody shape | Notes |
|---|---|---|---|---|
| Wikimedia PD12M | GLAM→flagged removal (method undocumented) → 256px floor → learned-aesthetic model cuts bottom 50% | **RADIOACTIVE (aesthetic-model selection)** | upstream 38M pre-cut pool (Source.Plus); HF-hosted | re-derivation ≈ 1.1TB or 372GB (12M slice) |
| YFCC100M | CC-metadata selection; human titles/tags | CANDIDATE (human captions clean; image bytes rot) | 12.5GB metadata archive durable; Flickr URLs subject to rot | pairing density, not image count, is wall |
| LibriSpeech | LibriVox PD + external-ASR (VoxForge-Kaldi) decode + Smith-Waterman segment + disagreement drop | **RADIOACTIVE (external ASR taint)** | raw upstream clean (LibriVox chapters + Gutenberg texts, both PD/durable) | upstream recovery = chapter-level pairing; utterance segmentation requires local CTC bootstrap |
| AudioSet | YouTube metadata + query-by-example nomination + human label confirmation | **RADIOACTIVE (learned nomination, not cured by human confirm)** | YouTube bytes (rot + ToS) | human review does not clean upstream selection bias |
| Common Voice | volunteer-read sentences + dual human review (2 upvotes minimum) | **CLEAN** | versioned tarballs (durable) | no learned selection; human-authored text + human validation |
| Smithsonian Open Access | institutional curation; CC0 license; 5.1M images + 11M metadata | **CLEAN** | bulk JSON on GitHub (weekly refresh) + AWS open data | curatorial selection is documented and human-auditable |

---

## 2. Bootstrap Tracks (Unlocked by Ruling v2 §2)

### T1: Corpus-Lineage OCR

**Purpose:** Reopen scanned-PD text universe (potential 100B+ tokens) + enable figure-caption pairing.

**Mechanism:** Train local OCR on SYNTHETIC RENDERINGS of known texts (e.g., Gutenberg public-domain texts rasterized locally with varied fonts/degradation). Rendered images = perfectly labeled, zero external model dependency, clean by construction.

**Validation:** held-out rendering accuracy only (never agreement with external cuts).

**Kill criterion:** synthetic rendering cannot reach usable OCR accuracy on held-out test set.

---

### T2: Corpus-Lineage CTC Aligner

**Purpose:** Replace external ASR in LibriVox audio-text pairing; enable utterance-level segmentation without external model taint.

**Mechanism:** Energy-split seeds + proportional-text weak labels → train tiny local CTC → iterative force-align + re-train on LibriVox raw chapters. The LibriSpeech recipe with external ASR replaced by corpus-owned model.

**Validation:** alignment-consistency receipts (never agreement with LibriSpeech cuts).

**Kill criterion:** CTC bootstrap fails to converge on weak labels (measured by alignment-consistency, not external-set agreement).

---

## 3. Clean-Corpus Candidate Map (Per-Modality)

### Audio-Text (Strongest pairing hypothesis)

**Sources:**
- LibriVox raw chapters + their Gutenberg source texts (PD, human-read, chapter-level alignment by construction)
- Common Voice CC0 (validated short-utterance supplement)

**Architecture:** Chapter-level pairs via upstream metadata; utterance-level segmentation via T2 bootstrap (corpus-lineage CTC).

**Pairing density:** natural chapter-level granularity; utterance density subject to CTC convergence.

---

### Image-Text (Pairing density is the wall)

**Sources:**
- Smithsonian Open Access (5.1M CC0 + curatorial metadata text)
- Wikimedia Commons PD/CC0 slice (human captions/categories)
- YFCC100M CC subset (human titles/tags; noisy)
- Public-domain scientific literature figure+caption pairs (pre-1928)
- Chronicling America newspaper photo captions (PD)

**Pairing density:** caption-grade ~5.5–21M pairs (verify-corrected via panel); label-grade ~14–35M. **Roughly 20–70× below CLIP-scale pairing.** Density, not image raw count, is the constraint.

---

### Text

**Scope:** Out of P4 (already receipted in-house under corpus lineage; w2 shards-v0).

---

## 4. Feasibility Facts (Verified arithmetic; facts only, no scope proposal)

- **Dense-Chinchilla compute baseline:** 27B parameters from scratch on one 4090 ≈ 48 years (8.7e22 FLOPs @ 35% MFU). The corpus map prices the DATA side; compute feasibility is external to P4.

- **Clean text budget (unreceipted estimate):** ~10–30B tokens (Gutenberg + Wikisource-proofread + government/legal documents). **OCR-taint consequence:** scanned-PD universes (HathiTrust, Internet Archive, Chronicling America) remain closed until T1 bootstrap completes.

- **Image-text pairing budget (verify-corrected):** ~5.5–21M caption-grade pairs; ~14–35M label-grade pairs. **Pairing density, not raw image count, is the load-bearing constraint.** Roughly 20–70× below CLIP-scale.

- **PD12M upstream recovery:** struck as non-shippable (aesthetic-model selection = C(b) taint per ruling v2); upstream re-derivation from 38M pre-cut pool ≈ **1.1TB** (or 12M slice ≈ **372GB**).

- **Minimal credible tri-modal corpus: 250–500GB**. ⇒ **The >100GB operator disk escalation is a PREREQUISITE of P4 execution** (authorization-to-obtain; surfaced with ratification ask).

- **LibriVox chapter-level pairing:** clean by construction. Utterance-level segmentation via T2 is a **multi-week sub-project**; CTC bootstrap from weak labels is seed-stage heuristic; readers' insertions/edition drift explain the field's turn to external ASR.

---

## 5. Kill Criteria (The map is a test, not a demo)

A **source DROPS** if:
- Documented non-external-model-free step at/after custody point (receipt = the documentation quote from source inventory), OR
- Failed obtainability probe (no bulk-access path within infrastructure/network constraints).

A **bootstrap track DROPS** if:
- **T1:** Synthetic rendering cannot reach usable OCR accuracy on held-out renderings.
- **T2:** CTC bootstrap fails to converge on weak labels (measured by alignment-consistency, never agreement with external cuts).

The **ruling itself** dies only by operator rejection — it is a PROPOSED governance artifact.

---

## 6. Open Obtainability Probes (Rank-0: Not yet receipted)

Per-source probes required before any data ingestion. **No data acquisition until Ruling v2 is ratified.**

### Wikimedia (PD12M upstream recovery)

- [ ] Source.Plus bulk-access protocol (38M item enumeration)
- [ ] Item-resolution method (URL rot prevalence)
- [ ] Bandwidth/quota caps on bulk fetch

### YFCC100M

- [ ] Metadata-archive current URL + integrity check (checksums)
- [ ] Multimedia Commons AWS mirror status (maintenance/availability)
- [ ] Bulk-listing protocol (no individual fetches per item)

### LibriVox (chapters + Gutenberg pairing)

- [ ] LibriVox bulk-metadata export (MP3 stream listing)
- [ ] Gutenberg Project plain-text bulk availability (current API/tarball)
- [ ] Chapter-boundary alignment verification (metadata-provided vs. manual audit)

### Common Voice

- [ ] Versioned tarball download link + release schedule
- [ ] Dual-review metadata format (upvote counts machine-readable)
- [ ] Language/demographic breakdown (CC0 subset filtering)

### Smithsonian Open Access

- [ ] JSON bulk export schedule + stability (weekly GitHub refresh)
- [ ] License-metadata quality (per-item CC0 assertion vs. collection-level)
- [ ] Image-URL resolution (AWS mirror vs. Smithsonian direct)

### Pre-1928 Scientific Literature (figure-caption pairing)

- [ ] Archive source (Google Books, HathiTrust, Internet Archive)
- [ ] Metadata availability (publication date, figure captions tagged)
- [ ] Bulk-export feasibility (rights clearance, bulk-download protocols)

### Chronicling America (newspaper captions)

- [ ] Bulk-metadata endpoint + photo-subset filtering
- [ ] OCR-quality attestation (existing metadata vs. T1 re-OCR post-receipt)
- [ ] Archive stability (Library of Congress maintenance)

---

## 7. Upstream Recovery Facts

- **PD12M aesthetic-model taint:** clean upstream = 38M pre-filtered pool on Source.Plus (before the internal learned-aesthetic cut). Not the 12.4M as-published.

- **LibriSpeech external-ASR taint:** clean upstream = raw LibriVox chapter downloads + Gutenberg plain-text (both durable, PD). Not the published 1000h cuts.

- **AudioSet, LAION/DataComp class:** no clean upstream custody point. Dropped entirely.

---

## 8. Integration Constraints

- No validation/tuning on the abandoned external-processed artifacts (agreement-with-the-banned-source is distillation through evaluation).
- Chapter-level LibriVox pairing: construction-guaranteed clean. Utterance segmentation: subject to T2 bootstrap completion.
- Pairing density (image-text) is the feasibility wall — scale measured in pairing count, not raw image population.
- Synthetic rendering for OCR training must use varied fonts, degradation, and corruption types — OCR quality ceiling determined by rendering realism on held-out test set.

---

## 9. References

- **Constitutional foundation:** L3 (anti-distillation corpus scope), L4 (receipted lineage).
- **Ruling v2:** docs/spec/l3-corpus-boundary-v2-PROPOSED.md (this repo).
- **Upstream archives:** LibriVox (librivox.org), Gutenberg Project (gutenberg.org), Smithsonian Open Access (www.si.edu), Common Voice (commonvoice.mozilla.org), Chronicling America (chroniclingamerica.loc.gov), Internet Archive (archive.org).
- **Feasibility:** verified arithmetic from panel synthesis; estimates marked "unreceipted" are provisional pending bulk-access probes.
