# Issue #321 scanned-text OCR preregistration conservation

Status: `SUPERSEDED_CURRENT_EMBER_02`

## Ruling

Issue #321's dated `T1 pilot`, research-loop tick, and old corpus-boundary vocabulary are not current execution authorities. The underlying scanned-public-domain OCR corpus-expansion question remains valid current-3B corpus science. Canonical EMBER-02 accepted the complete surviving contract before this ruling was prepared.

Canonical owner: [EMBER-02/#1116](https://github.com/wordingone/ember/issues/1116).

Accepted transfer: https://github.com/wordingone/ember/issues/1116#issuecomment-5221950934

## Historical evidence boundary

The public #321 record contains obtainability, font, and scan-custody probes, not M1, M2, M2.5, or M3 OCR results. It reports no admitted OCR corpus, training result, checkpoint, capability, sufficient-pretraining, or milestone completion. The July comments remain useful preregistration inputs: DP-credit-first search outperformed scan-first; year matches were not edition proof; qualifying font-file glyph coverage and several scan-image bytes were banked; and the transcription-governance choice remained unresolved.

## Lossless current-owner crosswalk

### M0 edition integrity and obtainability

- Bind at least three edition-pinned dual-observation books with exact scan/text identity, title-page pixel evidence, publisher/place/year, item-level archive metadata, public-domain eligibility, content hashes, and the scan-vs-scan printing-difference rule.
- Use DP-credit-first search by default. Define metadata-tier versus pixel-tier evidence, single-extant-printing semantics, accepted era strata, and every exclusion before intake.
- HathiTrust is unavailable unless a receipted access method exists. A different repository or printing is not silently substituted.
- Inter-edition disagreement at or above the registered M3 effect drops the book. Fewer than three qualifying books is a terminal refusal, not permission to shrink the pilot.

### M1 frozen calibration floor

- Freeze the nine strata as `book × page-third` and the RNG seed before inspecting scans. The target is approximately 100 hand-transcribed lines.
- Choose one explicit authority: operator transcription, or a ratified rule that measurement-only calibration is outside the token-selection boundary. The crosswalk does not choose between them.
- Only logged segmentation failures may be excluded; more than 10% blocks the pilot.
- Measure raw and preregistered-normalized CER (long-s, ligatures, and u/v), bootstrap its confidence interval, and call downstream deltas inside that interval `INCONCLUSIVE`.
- Preserve the `<=0.5%`, `0.5–2%`, and `>=2%` bands. The middle band expands to 300 lines and switches the fallback ground truth to the hand-corrected subset.

### M2 synthetic-seed comparison

- Compare modern-only and period-face font inventories while holding renderer, degradation, data, training, initialization, and evaluation identity fixed.
- Report per-book and aggregate CER. The AT-ST anchor is from a different regime and remains a disclosed decision anchor, not a truth claim.
- Preserve the `<=3%` proceed, `3–20%` flagged, and `>=20%` kill rules. Seed CER above 15% makes M3 void.

### M2.5 confidence falsifier

- Measure per-line confidence versus correctness, ranking AUC, and precision-at-threshold on the calibration set.
- If AUC is not above `0.5 + registered epsilon`, confidence does not rank correctness and M3 remains unrun.

### M3 one-round self-training

- Run exactly one registered self-training round using transcription-posterior ranking and masking augmentation, repeated three times with different pseudo-label subsamples.
- Spread at or above the registered delta is `INCONCLUSIVE`. Preserve the seed-CER regime bands, report every book separately, and prohibit pooling.
- Kill when CER worsens in a majority of repeats or top-confidence-decile CER is not below overall seed CER.
- Three books can promote only to a larger 10–20-book pilot, never to a corpus or capability claim.

### Corpus and toolchain authority

- Use deterministic projection-profile, Otsu, and connected-components segmentation. A real-scan probe must show less than 10% line failure on the registered crops.
- Ban bundled IA/LoC OCR text, confidence, and boxes from selection, cropping, edition matching, and verification.
- Bind font-file bytes, OFL/license, cmap/GSUB coverage (long-s, ct/st ligatures, and old-style numerals where claimed), source lineage, and the explicit human/non-generative creation-era ruling.
- Bind deterministic renderer inputs and pixel hashes. Enumerate only mirrored-page bleed-through, morphological spread/erosion, threshold jitter, geometric warp, blur, and JP2 recompression. No learned/GAN degrader or external learned signal is admissible.

### July amendments and banked inputs

- Preserve DP-credit-first as the winning search direction; year match alone is not edition evidence; a different repository copy triggers the printing-difference rule.
- The Berkeley 1725 long-s was observed in pixels. Five candidate scans banked 50/50 unconditional first-leaf JPEGs with hashes; these prove custody/obtainability, not title-page matches or OCR quality.
- Junicode and EB Garamond clear the receipted glyph bar. IM Fell lacks old-style numerals and requires per-book disclosure.
- Preserve the named drops: the audiobook release is the wrong artifact class; the Canadian/US edition mismatch is not interchangeable; the undated reprint remains unpinnable until dated. Source/access/jurisdiction/era facts remain preregistration inputs only.

### Resource, selection-bias, and claim law

- Freeze the bounded resource envelope before execution and use only current Ember Lab, governed execution, and corpus custody. Receipt every refusal, interruption, deletion, and rollback.
- Later admitted tokens must carry the exact form `ember-ocr-confidence>=tau, calibration-CER=X at tau`, never `verified`.
- Report selected-versus-rejected typography density and page-position composition so confidence selection cannot silently bias the realized corpus toward easy lines.
- No OCR, corpus, training, checkpoint, capability, sufficient-pretraining, or milestone credit exists until the complete current-authority M0→M3 chain passes.

The accepted transfer and this crosswalk retain every clause while the original issue/comments remain provenance. They do not infer the unresolved transcription-governance decision, loosen a kill rule, or substitute the banked probes for the M0→M3 experiment.

## Current architecture and claim boundary

Current Ember Lab, governed execution, and current corpus-custody contracts remain the sole authorities. This ruling creates no corpus, OCR, renderer, segmenter, launcher, model, experiment, selection, or receipt authority.

`NO_NEW_PARALLEL_AUTHORITY`

No OCR result, corpus admission, GPU run, training, checkpoint, benchmark, capability, sufficient-pretraining, or milestone-completion claim is made.

## Rollback

Revert this conservation commit and reopen #321 if the accepted #1116 transfer is removed or narrowed.
