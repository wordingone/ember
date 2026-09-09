<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Ember data-family register, version 1

The register required by the 2026-08-17 full-spectrum amendment to the data-plane parent. Its
purpose is to make the shape of what Ember does *not* have explicit, so that no major
machine-learnable data family disappears from scope by never having been considered.

## How to read this, and what it is not

**This version maps the landscape and states honest verdicts. It acquires nothing.** Every row
whose acquisition state reads `NOT_STARTED` means exactly that: zero bytes on disk, no catalog
identity, no consumer. The amendment lists nine things that do not count as coverage — an
architecture supporting the modality, a tokenizer, an expert named for it, a synthetic fixture, a
roadmap mention, a schema able to store it, an adapter spec, a tiny hand-authored example, a future
milestone. None of those are recorded here as coverage, including for families where Ember has such
artifacts already.

**License verdicts are the part most easily faked, so they are the part stated most carefully.** A
verdict reads `ADJUDICATED` only where the actual license text of the actual artifact has been read
and recorded. Everywhere else it reads `ADJUDICATION_REQUIRED`, with the candidate named so the
adjudication has a subject. A representative source named in this table is a *candidate for
adjudication*, never an approval, and never evidence that its bytes may be fetched.

**The family list is a floor, not a ceiling.** The amendment names thirteen known gaps and says
plainly that a family absent because the audit never considered it is a completion defect. Families
14 through 28 below are the audit's own additions. Their presence is the audit doing its job; if a
reader knows of a major family absent from this table, that absence is a defect in this document.

## Column meanings

| column | meaning |
|---|---|
| `data_family` | the family as the field would name it |
| `important_subtypes` | materially distinct subtypes, each of which may need its own row later |
| `representative_sources` | candidates for adjudication; naming one approves nothing |
| `license/access verdict` | `ADJUDICATED` only with license text read; else `ADJUDICATION_REQUIRED` |
| `raw_format` | the format bytes actually arrive in |
| `train/heldout plan` | how the split would be drawn, and what contamination risk it carries |
| `acquisition state` | `NOT_STARTED`, `IN_PROGRESS`, `PARTIAL`, `ADMITTED`, or `REFUSED` |
| `downloaded bytes` | measured bytes in the corpus root; `0` unless measured |
| `processing pipeline` | the transform to canonical representation; `none` if unbuilt |
| `validation method` | how correctness of the processed form would be checked |
| `catalog identity` | the catalog row; `none` if absent |
| `downstream consumer` | what would actually train on it; `none` if nothing would |
| `blocker/refusal reason` | why it is not admitted, stated as a fact rather than a plan |

---

## Part 1 — the thirteen families named in the amendment

### 1. Video

- **important_subtypes**: untrimmed long-form; short-form clips; egocentric; screen recordings and UI interaction; instructional with aligned narration; surveillance/static-camera; synthetic/rendered.
- **representative_sources**: ADJUDICATION_REQUIRED. Large web-video collections are the obvious candidates and are also the ones most likely to fail adjudication on rights to the underlying media rather than to the index.
- **license/access verdict**: ADJUDICATION_REQUIRED. Note the trap specific to this family: many well-known video "datasets" distribute *identifiers*, not bytes. The dataset's own license governs the identifier list; the media each identifier points at carries its own separate and usually incompatible terms. A verdict on the list is not a verdict on the media.
- **raw_format**: container files (mp4/webm/mkv) wrapping compressed video and usually audio; frame-sequence archives; latent/feature dumps in some redistributions.
- **train/heldout plan**: split by *source channel or uploader*, never by clip. Clip-level splitting leaks because near-duplicate clips from one source land on both sides.
- **acquisition state**: NOT_STARTED.
- **downloaded bytes**: 0.
- **processing pipeline**: none. Would need decode, resample to a fixed rate, shot segmentation, and an audio/text alignment path.
- **validation method**: decode-integrity on every file, duration-versus-metadata agreement, and a blank-frame detector to catch truncated downloads.
- **catalog identity**: none.
- **downstream consumer**: none. The architecture's image path exists; no video path consumes it.
- **blocker/refusal reason**: no adjudicated source; and the storage envelope is a real constraint rather than an afterthought — video at any useful scale is the largest single byte demand in this table.

### 2. Natural speech and real-world audio at scale

- **important_subtypes**: read speech; conversational/spontaneous; telephony (narrowband); broadcast; far-field/multi-microphone; non-speech environmental sound; overlapping multi-speaker.
- **representative_sources**: ADJUDICATION_REQUIRED. Public-domain audiobook corpora and permissively licensed volunteer speech collections are the strongest candidates precisely because their rights position is clean.
- **license/access verdict**: ADJUDICATION_REQUIRED. Speech carries a second question beyond copyright: whether speakers consented to redistribution. A permissive license does not settle it.
- **raw_format**: waveform (flac/wav/mp3/opus) plus transcript files, alignment files, and speaker metadata.
- **train/heldout plan**: split by *speaker*, disjointly. Speaker overlap between train and heldout is the standard way this family's evaluations become meaningless.
- **acquisition state**: NOT_STARTED.
- **downloaded bytes**: 0.
- **processing pipeline**: none. The architecture declares a 16 kHz sample rate, 640-sample frame and 320-sample stride, so a resample-and-frame path is specified but unbuilt.
- **validation method**: decode integrity, sample-rate agreement with the declared rate, transcript/audio duration ratio within bounds, and a silence-fraction check.
- **catalog identity**: none.
- **downstream consumer**: none. An audio embedding path exists in the decoder; nothing feeds it.
- **blocker/refusal reason**: no adjudicated source; no resample/framing pipeline.

### 3. Sensor and time-series data

- **important_subtypes**: inertial (IMU/accelerometer); physiological (EEG, ECG, PPG); industrial and SCADA telemetry; financial series; energy and grid; environmental sensors; vehicle CAN-bus.
- **representative_sources**: ADJUDICATION_REQUIRED. Open machine-learning repositories and government/industrial open-data portals are the plausible candidates.
- **license/access verdict**: ADJUDICATION_REQUIRED. Physiological subtypes are effectively medical data and inherit the constraints of row 12 regardless of where they are published.
- **raw_format**: CSV, Parquet, HDF5, domain binary formats (EDF for EEG, MDF for vehicle logs).
- **train/heldout plan**: split by *time*, forward only, with a gap between train end and heldout start. Random splitting of a time series is contamination by construction; financial subtypes additionally need the gap to exceed any label horizon.
- **acquisition state**: NOT_STARTED.
- **downloaded bytes**: 0.
- **processing pipeline**: none. Would need per-channel normalization with statistics computed on train only, resampling to a common rate, and an explicit missing-value representation.
- **validation method**: monotonic timestamps, sampling-rate consistency, and a bound on the fraction of imputed values.
- **catalog identity**: none.
- **downstream consumer**: none.
- **blocker/refusal reason**: no adjudicated source; and no decision on how a continuous multi-channel signal is represented to a token-sequence model, which is a genuine open design question rather than an implementation gap.

### 4. Native graph datasets

- **important_subtypes**: knowledge graphs; citation networks; social networks; molecular graphs (see row 11); road/transport networks; program dependency and call graphs; heterogeneous/typed graphs.
- **representative_sources**: ADJUDICATION_REQUIRED. Established open graph-learning benchmark collections and openly licensed knowledge bases are the candidates.
- **license/access verdict**: ADJUDICATION_REQUIRED. Social-network subtypes carry a personal-data question that is independent of the license and in several jurisdictions is not waivable by the publisher.
- **raw_format**: edge lists, adjacency structures, RDF/Turtle, GraphML, framework-specific binary.
- **train/heldout plan**: transductive versus inductive is a decision, not a detail. Inductive splits by disjoint subgraph and is the honest one; transductive edge-masking leaks structure.
- **acquisition state**: NOT_STARTED.
- **downloaded bytes**: 0.
- **processing pipeline**: none.
- **validation method**: referential integrity of every edge endpoint, declared-versus-actual node and edge counts, and a connected-component census.
- **catalog identity**: none.
- **downstream consumer**: none.
- **blocker/refusal reason**: no adjudicated source; no serialization decision for graph structure into the decoder's sequence interface.

### 5. Native tabular learning

- **important_subtypes**: heterogeneous mixed-type tables; high-cardinality categorical; wide sparse; longitudinal/panel; relational multi-table with joins.
- **representative_sources**: ADJUDICATION_REQUIRED. Long-standing open ML repositories and open-government data portals.
- **license/access verdict**: ADJUDICATION_REQUIRED. Individually low-risk and individually low-value: this family's rows are small, so adjudication cost per admitted byte is the highest in the table, and batching adjudication by publisher rather than by dataset is the sane approach.
- **raw_format**: CSV, Parquet, ARFF, SQLite.
- **train/heldout plan**: stratified by target where a target exists; grouped by entity where rows repeat per entity.
- **acquisition state**: NOT_STARTED.
- **downloaded bytes**: 0.
- **processing pipeline**: none. Serialization of a row to text is the standard approach and is lossy in a way that needs to be a recorded decision.
- **validation method**: schema conformance, declared-versus-actual row counts, and a null-fraction bound per column.
- **catalog identity**: none.
- **downstream consumer**: none.
- **blocker/refusal reason**: no adjudicated source; no row-serialization decision.

### 6. Geospatial, satellite, and GIS

- **important_subtypes**: multispectral and hyperspectral satellite; aerial/drone imagery; SAR; vector map data; digital elevation models; land-cover label rasters.
- **representative_sources**: ADJUDICATION_REQUIRED. Publicly funded earth-observation programs are the strongest candidates in the whole table on rights, because several publish explicitly into the public domain or under free-reuse terms.
- **license/access verdict**: ADJUDICATION_REQUIRED, but this is the family where adjudication is most likely to *succeed* cleanly.
- **raw_format**: GeoTIFF, COG, NetCDF, HDF5, shapefile/GeoPackage, LAS for elevation-derived products.
- **train/heldout plan**: split by *geography*, with a spatial buffer between train and heldout tiles. Adjacent tiles overlap in content; random tile splits leak.
- **acquisition state**: NOT_STARTED.
- **downloaded bytes**: 0.
- **processing pipeline**: none. Would need band selection, reprojection to a common CRS, tiling, and a decision on how more-than-three-band imagery reaches an image path that assumes three.
- **validation method**: georeference validity, CRS agreement, per-band value ranges, and a no-data-fraction bound.
- **catalog identity**: none.
- **downstream consumer**: none.
- **blocker/refusal reason**: no adjudicated source; the multispectral-to-three-channel decision is unmade; bytes are large.

### 7. Point clouds, LiDAR, and depth

- **important_subtypes**: terrestrial and mobile LiDAR; airborne LiDAR; automotive rotating-scanner sweeps; RGB-D indoor scans; structured-light and photogrammetric reconstructions.
- **representative_sources**: ADJUDICATION_REQUIRED. Autonomous-driving research collections and indoor-scan datasets are the candidates; several of the former restrict commercial use, which is a verdict-relevant distinction that must be recorded rather than assumed away.
- **license/access verdict**: ADJUDICATION_REQUIRED.
- **raw_format**: LAS/LAZ, PLY, PCD, per-frame binary sweeps, RGB-D image pairs plus intrinsics.
- **train/heldout plan**: split by *scene or capture session*. Frames from one session are near-duplicates.
- **acquisition state**: NOT_STARTED.
- **downloaded bytes**: 0.
- **processing pipeline**: none. Needs a decision between voxelization, sampling to a fixed point count, or a range-image projection — each of which changes what the model can learn.
- **validation method**: point-count agreement with headers, coordinate-range sanity, and intrinsics consistency for depth pairs.
- **catalog identity**: none.
- **downstream consumer**: none.
- **blocker/refusal reason**: no adjudicated source; no point-set representation decision.

### 8. 3D meshes, CAD, and BIM

- **important_subtypes**: artist-authored meshes; scanned/reconstructed meshes; parametric CAD with construction history; boundary-representation solids; BIM building models; procedural/parametric assets.
- **representative_sources**: ADJUDICATION_REQUIRED. Large 3D object collections aggregate uploads under heterogeneous per-object licenses; that heterogeneity means a per-object verdict, not a per-dataset one.
- **license/access verdict**: ADJUDICATION_REQUIRED. Flagged as the family most likely to produce a *mixed* verdict inside one archive.
- **raw_format**: OBJ, glTF/GLB, FBX, STEP, IFC, USD, native CAD formats.
- **train/heldout plan**: split by *object identity and by creator*, since a creator's assets share style and topology.
- **acquisition state**: NOT_STARTED. Recorded in the amendment as previously mapped and never sourced; that remains accurate, and mapping is explicitly not coverage.
- **downloaded bytes**: 0.
- **processing pipeline**: none.
- **validation method**: manifold and watertightness checks, face/vertex counts against headers, and unit-scale consistency.
- **catalog identity**: none.
- **downstream consumer**: none.
- **blocker/refusal reason**: no adjudicated source; per-object license heterogeneity makes bulk admission unsafe; no mesh representation decision.

### 9. Real robotics and embodied demonstrations

- **important_subtypes**: teleoperated manipulation; autonomous rollouts; human demonstration video with action labels; simulation-to-real paired sets; navigation traces; dexterous/multi-finger manipulation.
- **representative_sources**: ADJUDICATION_REQUIRED. Recent large multi-institution robot-trajectory collections are the candidates.
- **license/access verdict**: ADJUDICATION_REQUIRED. Aggregated collections often inherit per-contributor terms, which is the same heterogeneity trap as row 8.
- **raw_format**: episodic record formats holding synchronized observation streams, action vectors, and rewards; often with paired video.
- **train/heldout plan**: split by *embodiment and by task*, and hold out at least one whole embodiment to make a transfer claim testable at all.
- **acquisition state**: NOT_STARTED. The amendment records the trajectory representation as mapped and never sourced; still accurate.
- **downloaded bytes**: 0.
- **processing pipeline**: none.
- **validation method**: per-episode step-count agreement, action-dimension consistency within an embodiment, and observation/action timestamp alignment.
- **catalog identity**: none.
- **downstream consumer**: none.
- **blocker/refusal reason**: no adjudicated source; continuous action vectors have no decided representation in a discrete sequence model.

### 10. Biological sequences

- **important_subtypes**: genomic DNA; transcriptomic RNA; protein primary sequence; protein structure; multiple-sequence alignments; variant call sets.
- **representative_sources**: ADJUDICATION_REQUIRED. The major public biological sequence archives are the candidates and several are explicitly open, which makes this family — like row 6 — a likely clean adjudication.
- **license/access verdict**: ADJUDICATION_REQUIRED. One caution that is easy to miss: human variant data can be personally identifying even when the archive is open, which is a separate question from the license.
- **raw_format**: FASTA, FASTQ, PDB/mmCIF, VCF, BAM.
- **train/heldout plan**: split by *sequence-identity clustering* at a stated threshold, never at random. Homologous sequences across a random split is the field's best-known contamination failure.
- **acquisition state**: NOT_STARTED.
- **downloaded bytes**: 0.
- **processing pipeline**: none. Tokenization choice (nucleotide, codon, k-mer, learned) is an unmade decision with large consequences.
- **validation method**: alphabet conformance, length distribution against the source's own statistics, and clustering-threshold verification on the produced split.
- **catalog identity**: none.
- **downstream consumer**: none.
- **blocker/refusal reason**: no adjudicated source; no tokenization decision.

### 11. Molecular and chemical structures

- **important_subtypes**: small molecules; reactions; crystal structures; conformer ensembles; quantum-chemical property sets; polymers.
- **representative_sources**: ADJUDICATION_REQUIRED. Open chemical databases and computed-property collections are candidates; some widely used structural databases are explicitly *not* freely redistributable, and that distinction is exactly what adjudication is for.
- **license/access verdict**: ADJUDICATION_REQUIRED.
- **raw_format**: SMILES/SELFIES strings, SDF/MOL, CIF, XYZ, quantum-chemistry output files.
- **train/heldout plan**: split by *scaffold*, not at random. Random molecular splits overstate generalization by a wide and well-documented margin.
- **acquisition state**: NOT_STARTED.
- **downloaded bytes**: 0.
- **processing pipeline**: none. Requires canonicalization, because the same molecule has many valid string forms and an uncanonicalized corpus trains the model on notation.
- **validation method**: parse-and-round-trip every structure, valence checks, and duplicate detection after canonicalization.
- **catalog identity**: none.
- **downstream consumer**: none.
- **blocker/refusal reason**: no adjudicated source; no canonicalization pipeline.

### 12. Medical modalities

- **important_subtypes**: radiology (CT, MRI, X-ray, ultrasound); digital pathology whole-slide images; clinical physiological signals; clinical notes; ophthalmic and dermatologic imaging.
- **representative_sources**: ADJUDICATION_REQUIRED. De-identified research collections released under data-use agreements are the realistic candidates.
- **license/access verdict**: ADJUDICATION_REQUIRED, and this row is flagged as the one most likely to end in **REFUSED**. Access is typically governed by a data-use agreement with named-person credentialing and explicit redistribution prohibitions. A data-use agreement is not a license, and a corpus that cannot be redistributed cannot enter a content-addressed catalog intended to be mirrored — that is a structural conflict with the data plane's own design, not a paperwork problem.
- **raw_format**: DICOM, NIfTI, whole-slide pyramidal formats, waveform formats, free text.
- **train/heldout plan**: split by *patient*, disjointly, always.
- **acquisition state**: NOT_STARTED.
- **downloaded bytes**: 0.
- **processing pipeline**: none.
- **validation method**: de-identification verification as a gate rather than a check — including burned-in text in pixel data, which survives header scrubbing.
- **catalog identity**: none.
- **downstream consumer**: none.
- **blocker/refusal reason**: redistribution terms conflict with mirrored content-addressed custody. This family plausibly closes as an evidence-backed REFUSAL rather than an acquisition, which the amendment explicitly permits.

### 13. Rich paired multimodal corpora

- **important_subtypes**: image-caption; video-audio-text; speech-text; 3D-language; action-vision; document-image-text; chart/diagram-text.
- **representative_sources**: ADJUDICATION_REQUIRED. Openly licensed encyclopedic media with captions is the cleanest candidate; web-scraped alt-text collections are the largest and the worst on rights.
- **license/access verdict**: ADJUDICATION_REQUIRED. Same identifier-versus-media trap as row 1, and it is the dominant risk here.
- **raw_format**: image or media files plus paired text, or identifier lists plus text.
- **train/heldout plan**: split by *media identity*, deduplicated perceptually first, since the same image recurs across sources with different captions.
- **acquisition state**: NOT_STARTED.
- **downloaded bytes**: 0.
- **processing pipeline**: none.
- **validation method**: pair-integrity (every text has its media and the reverse), perceptual-hash deduplication, and a caption-length distribution check to catch placeholder alt-text.
- **catalog identity**: none.
- **downstream consumer**: none. The decoder has image, audio, and text embedding paths and a modality index; nothing supplies aligned pairs.
- **blocker/refusal reason**: no adjudicated source. This is the highest-value row in the table for the declared architecture, because typed modality boundaries into one shared core are exactly what paired data trains.

---

## Part 2 — families added by this audit

The amendment requires that the audit surface families beyond its own floor. These are those
families. Each is materially distinct from every row above, not a subtype of one.

### 14. Natural-language text

The family Ember actually has. Recorded here because a register that omits the one family with
bytes on disk is not a register. Subtypes: web crawl; books; encyclopedic; news; academic; forum and
conversational; reference. **acquisition state**: the text-lab program's 44-slot table is the live
instrument for this row, and its state is that table's state rather than a number restated here.
**blocker/refusal reason**: 14 of the 44 slots carry unresolved licenses.

### 15. Source code and software artifacts

Distinct from text: it has execution semantics, a test oracle, and per-repository licenses that vary
inside a single archive. Subtypes: source across languages; version-control history and diffs; issue
and review discussion; build configuration; notebooks. **license/access verdict**:
ADJUDICATION_REQUIRED, per repository, and permissive-license filtering is the standard and
insufficient answer — attribution obligations survive the filter. **acquisition state**: NOT_STARTED.

### 16. Mathematics and formal proof

Subtypes: informal mathematical prose; formalized libraries in proof assistants; competition
problems with solutions; theorem-proving traces; symbolic computation. Distinct because it carries a
machine-checkable correctness oracle, which almost nothing else in this table does.
**acquisition state**: NOT_STARTED.

### 17. Still images without paired text

Distinct from row 13: classification and detection corpora carry labels, not language. Subtypes:
object-centric classification; detection and segmentation with masks; fine-grained domains; texture
and material. **acquisition state**: NOT_STARTED.

### 18. Documents, OCR, and layout

Scanned and born-digital documents where *spatial arrangement carries meaning*. Subtypes: scanned
historical print; forms; tables in documents; receipts and invoices; handwritten manuscripts;
academic PDFs with figures. Distinct from both text and images because the layout is the signal.
**acquisition state**: NOT_STARTED.

### 19. Music and symbolic audio

Distinct from row 2: music has harmonic and rhythmic structure and a symbolic representation that
speech lacks. Subtypes: recorded audio; symbolic scores (MIDI, MusicXML); stems and multitrack;
performance and expression data. **license/access verdict**: ADJUDICATION_REQUIRED, and recorded
music is the single worst rights position in this entire table. **acquisition state**: NOT_STARTED.

### 20. Handwriting, sketch, and vector drawing

Online (stroke-sequence) and offline (image) forms are materially different data. Subtypes:
handwritten text; freehand sketch strokes; technical drawings; diagram and flowchart vector sources.
**acquisition state**: NOT_STARTED.

### 21. Weather and climate

Separated from rows 3 and 6 because reanalysis products are gridded four-dimensional fields with
their own formats, scale, and split semantics. Subtypes: reanalysis; forecast model output; station
observations; radar and satellite-derived products; climate projections. **license/access verdict**:
ADJUDICATION_REQUIRED, and likely clean — major reanalysis products are openly licensed.
**acquisition state**: NOT_STARTED.

### 22. Astronomical survey data

Subtypes: photometric survey images; spectra; time-domain light curves; radio interferometry;
gravitational-wave strain. Almost universally open, and structurally unusual in carrying calibrated
physical uncertainty per measurement. **acquisition state**: NOT_STARTED.

### 23. Simulation and physics-engine rollouts

Distinct from row 9: synthetic, cheaply scalable, and carries exact ground-truth state that real
capture never has. Subtypes: rigid-body and contact rollouts; fluid and continuum; particle systems;
rendered synthetic scenes with perfect labels. **license/access verdict**: generatable in-house,
which sidesteps adjudication entirely and makes this the cheapest row in the table to start.
**acquisition state**: NOT_STARTED. **blocker/refusal reason**: none rights-side; purely unbuilt.

### 24. Game and interactive-environment trajectories

Distinct from row 9 (not embodied, no simulation-to-real gap) and from row 23 (an agent and a
reward, not passive dynamics). Subtypes: board and card game records; video-game play traces; RL
benchmark environment rollouts; human demonstration in games. **acquisition state**: NOT_STARTED.

### 25. Event streams, logs, and interaction sequences

Subtypes: user interaction and clickstream; recommendation interaction matrices; system and
application logs; transaction sequences; network flow records. Distinct from row 3 because events are
discrete, irregularly spaced, and typed rather than sampled. **license/access verdict**:
ADJUDICATION_REQUIRED, with a personal-data question that usually dominates the license question.
**acquisition state**: NOT_STARTED.

### 26. Security and network telemetry

Subtypes: packet captures; intrusion-detection labelled traffic; malware binaries and behavioural
traces; vulnerability corpora. Called out separately because acquiring it has handling obligations no
other row has, and because a malware corpus on a training host is a decision with consequences beyond
data governance. **acquisition state**: NOT_STARTED. **blocker/refusal reason**: handling constraints
unassessed; a plausible evidence-backed REFUSAL.

### 27. Materials and crystallography

Distinct from row 11: periodic crystal structures with lattice symmetry rather than discrete
molecules. Subtypes: computed materials property databases; experimental crystal structures;
phase diagrams; microscopy of microstructure. **acquisition state**: NOT_STARTED.

### 28. Single-cell and omics assays

Distinct from row 10: measurement matrices over cells and conditions, not sequences. Subtypes:
single-cell transcriptomics; proteomics; metabolomics; spatial transcriptomics; perturbation screens.
**acquisition state**: NOT_STARTED.

---

## Summary of the register's own state

| | count |
|---|---|
| families mapped | 28 |
| amendment floor | 13 |
| families added by this audit | 15 |
| families with `ADJUDICATED` license verdict | **0** |
| families with any downloaded bytes | **1** (row 14, via the text-lab slot table) |
| families with a catalog identity | 0 |
| families with a downstream consumer | 0 |
| families likely to close as evidence-backed REFUSAL | 2 (rows 12 and 26) |

The honest headline: **the register now exists and every row in it is empty.** That is a real
advance over a register that does not exist, because the shape and size of the gap is now stated
rather than unknown — but it is not acquisition, and nothing here should be read as coverage of any
family. Under the amendment's own list of what does not count as coverage, this document is a map,
which is the one thing it claims to be.

## Immediate consequences worth acting on

1. **Rows 6, 21, 22, and 23 are the cheapest starts** — publicly funded earth observation, open
   reanalysis, open astronomical surveys, and self-generated simulation. Three have the cleanest
   rights position in the table and the fourth needs no rights at all.
2. **Row 13 is the highest-value row for the declared architecture** and one of the worst on rights.
   That tension is the single most important sourcing decision this parent faces.
3. **Rows 12 and 26 should be adjudicated toward refusal early**, not left open. A family that will
   end in a refusal costs nothing to refuse now and blocks closure indefinitely if left ambiguous.
4. **The 14 unresolved text slots (row 14) are the only place bytes already exist**, which makes
   them the highest-return adjudication per unit of effort in the whole table.
