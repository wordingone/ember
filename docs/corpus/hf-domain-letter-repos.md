# HF corpus publication: one repo per charter domain letter

Convention for publishing acquired corpus rows to the Hugging Face Hub, per the
research lead's ruling of 2026-08-14, governing issue #1720.

## The convention

```
wordingone/ember-corpus-<letter>-<domain-shortname>                     # permissive rows
wordingone/ember-corpus-<letter>-<domain-shortname>-cc-by-sa-<version>  # one per SA version present
  README.md              # per-source license table (see below)
  NOTICE                 # SA repos only: date-range -> licence-version map
  raw/<source-slug>/     # one subdirectory per acquired row
```

- The **per-domain repo is the auditable unit**, not the row. 44 rows must not
  become 44 repos.
- **Split by domain letter AND by licence family.** A share-alike row may only sit
  in a repo whose own licence identity is that same CC-BY-SA version. Hugging Face
  carries one licence field per repo, so mixing an SA row in with other-licence
  rows would mislabel the repo.
- **Private by default.** A repo goes public only when *every* row inside it has
  verified redistribution rights.

### Labelling a share-alike row

Stack Exchange relicensed its subscriber content twice, so a single whole-site
dump spans multiple licence versions (measured below). Two rules follow:

- **The label is the EARLIEST version present in the dump**, not the latest and
  not simply "the most restrictive" — the earliest version's obligations are the
  ones binding on the whole artifact. A dump spanning more than one version is
  labelled `CC-BY-SA-<earliest>-mixed`.
- **Every SA repo carries a `NOTICE`** mapping date ranges to licence versions,
  plus attribution naming the source and version. The label alone is lossy; the
  NOTICE is what makes the mix auditable.

Repo ids are derived mechanically from `wave_manifest.CHARTER_DOMAINS`, which is
already the charter's letter -> shortname authority; they are not a second
hand-maintained list. Slug rule: lowercase, `/` and space -> `-`, drop other
non-alphanumerics.

| Letter | `CHARTER_DOMAINS` shortname | Repo id |
|---|---|---|
| A | Math | `wordingone/ember-corpus-a-math` |
| B | Stats/Inference | `wordingone/ember-corpus-b-stats-inference` |
| C | Physics/Dynamics | `wordingone/ember-corpus-c-physics-dynamics` |
| D | CS/Systems | `wordingone/ember-corpus-d-cs-systems` |
| E | ML/AI | `wordingone/ember-corpus-e-ml-ai` |
| F | Training-infra/CUDA/HW | `wordingone/ember-corpus-f-training-infra-cuda-hw` |
| G | Logic/Proof | `wordingone/ember-corpus-g-logic-proof` |
| H | SWE | `wordingone/ember-corpus-h-swe` |
| I | Data/Eval/Decon | `wordingone/ember-corpus-i-data-eval-decon` |
| J | Sci-method/Lab-ops | `wordingone/ember-corpus-j-sci-method-lab-ops` |
| K | Application worlds | `wordingone/ember-corpus-k-application-worlds` |

The derived name for A reproduces the ruling's own worked example
(`ember-corpus-a-math`), which is why the derivation is preferred over a fresh
list. The `baseline` pseudo-domain in `CHARTER_DOMAINS` is not a charter letter
and gets no repo.

## Existing hub state — this is not greenfield

One repo exists under the account today: **`wordingone/ember-custody`**, and it
is **public**. It is the mirror-only custody-inventory sync from issue #1308
(`scripts/hf_custody/`, `docs/custody/hf-sync.md`) — a different surface with a
different purpose. It is **not** renamed, folded in, or otherwise touched by
this convention. No `ember-corpus-*` repo exists yet.

`hf_fetch.py` is a **download** connector (hub -> local) and is not the
publication path; the only upload code in the repo is `scripts/hf_custody/sync.py`.
Naming/layout logic therefore belongs on the publication side, not in
`hf_fetch.py`.

## Row placement for the currently landed rows

Source of truth: the acquisition lane's dated resolution map
(`_resolution-map-20260814.json`, schema `acq-lead-resolution-map-v1`) in the
out-of-tree corpus data root, which records 13 LANDED rows. That tree is
already filed by charter letter (`text-lab/<LETTER>/<row>/`), so placement is a
direct lift.

| Row | Letter | Licence | Destination repo |
|---|---|---|---|
| openstax-math | A | CC-BY-4.0 | `ember-corpus-a-math` |
| stackexchange-math | A | CC-BY-SA-2.5-mixed | `ember-corpus-a-math-cc-by-sa-2-5` |
| metamath-set-mm | B | CC0-1.0 | `ember-corpus-b-stats-inference` |
| stackexchange-stats | B | CC-BY-SA-2.5-mixed | `ember-corpus-b-stats-inference-cc-by-sa-2-5` |
| stackexchange-physics | C | CC-BY-SA-2.5-mixed | `ember-corpus-c-physics-dynamics-cc-by-sa-2-5` |
| stackexchange-cs | D | CC-BY-SA-2.5-mixed | `ember-corpus-d-cs-systems-cc-by-sa-2-5` |
| stackexchange-ai | E | CC-BY-SA-3.0-mixed | `ember-corpus-e-ml-ai-cc-by-sa-3-0` |
| llvm-docs | F | Apache-2.0 WITH LLVM-exception | `ember-corpus-f-training-infra-cuda-hw` |
| lean-mathlib-docs | G | Apache-2.0 | `ember-corpus-g-logic-proof` |
| python-language-docs | H | Python-2.0 | `ember-corpus-h-swe` |
| rust-reference-docs | H | MIT OR Apache-2.0 | `ember-corpus-h-swe` |
| ros-docs | K | CC-BY-4.0 | `ember-corpus-k-application-worlds` |
| stackexchange-robotics | K | CC-BY-SA-2.5-mixed | `ember-corpus-k-application-worlds-cc-by-sa-2-5` |

Every row sits at `raw/<row-slug>/` inside its destination repo.

StackExchange does **not** map to a single letter: the six fetched sites land in
six different domains (A, B, C, D, E, K), one row each. There is no
"StackExchange repo" under this convention, by design — the repo is the domain
plus the licence family, and the row is the site.

### Measured licence versions

Every StackExchange row was recorded as `CC-BY-SA-4.0`. All six labels were
wrong. Measured from each dump's own `Posts.xml` `CreationDate` range mapped onto
Stack Exchange's relicensing boundaries (2.5 before 2011-04-08; 3.0 to
2018-05-02; 4.0 after), 5,026,471 posts across the six dumps:

| Row | Earliest post | Latest post | Posts | Versions spanned | Label |
|---|---|---|---|---|---|
| stackexchange-math | 2010-03-27 | 2024-03-31 | 3,792,437 | 2.5 / 3.0 / 4.0 | CC-BY-SA-2.5-mixed |
| stackexchange-stats | 2009-02-02 | 2024-03-31 | 425,736 | 2.5 / 3.0 / 4.0 | CC-BY-SA-2.5-mixed |
| stackexchange-physics | 2010-08-24 | 2024-03-31 | 577,301 | 2.5 / 3.0 / 4.0 | CC-BY-SA-2.5-mixed |
| stackexchange-cs | 2008-11-25 | 2024-03-31 | 105,373 | 2.5 / 3.0 / 4.0 | CC-BY-SA-2.5-mixed |
| stackexchange-ai | 2016-08-02 | 2024-03-31 | 26,764 | 3.0 / 4.0 | CC-BY-SA-3.0-mixed |
| stackexchange-robotics | 2011-02-13 | 2024-03-31 | 98,860 | 2.5 / 3.0 / 4.0 | CC-BY-SA-2.5-mixed |

Several earliest dates predate their own site's launch (cs 2008 against a 2012
launch, stats 2009 against 2010, robotics 2011 against 2012). That is not an
error: Stack Exchange migrates posts between sites and preserves the original
`CreationDate`, which is the correct signal here because the licence attaches
when the content was contributed, not when it was moved.

The version mapping assumes the licence attaches at contribution time and that
the relicensing was not retroactive. The dates are measured; that mapping is an
interpretation and is the research lead's to confirm.

`metamath-set-mm` (a CC0 formal-proof corpus) is recorded as **B**
Stats/Inference `train-0`, where **G** Logic/Proof looks like its natural home.
It stays in **B**: moving it is zero-sum against the two-independent-sources-per-
domain floor in `text_lab_corpus._validate` — B holds exactly two landed rows and
would drop to one, while G would rise from one to two, leaving the same number of
domains short. The reassignment only becomes safe once B has another source.

## README license table (required in every repo)

Each repo's `README.md` carries one row per `raw/` subdirectory:

| column | source |
|---|---|
| `source` | row slug (the `raw/<slug>/` directory name) |
| `license` | the row's resolved license, as evidenced |
| `license_evidence` | the external artifact the license was read from |
| `admissible` | whether the license is in the training-admission allow-list |
| `sha256` | row content hash from its connector receipt |

Share-alike rows carry two extra columns, `license_earliest` and
`license_versions_spanned`, so the repo-level label can be checked against the
per-row measurement rather than trusted.

Licenses are read from the source itself (GitHub license API, OpenStax CMS
`license_url`, HF card frontmatter), never from the `wave_manifest` table's own
assertion — `BulkVein.build_argv` already refuses self-referential evidence.

## Publication gate: private until every row is redistributable

The public/private decision is per repo. **Every domain repo starts private**,
and the public bar is unchanged by anything below: a repo flips public only when
every row inside it has verified redistribution rights.

Nine of the thirteen landed rows carry a license outside
`tools/ember-restart-3b/text_lab_corpus.py`'s `LICENSES` allow-list
(`CC0-1.0`, `CC-BY-4.0`, `MIT`, `Apache-2.0`, `BSD-3-Clause`, `PDDL-1.0`).
Ruled 2026-08-14, those nine resolve into three different problems, not one:

| Rows | Licence | Status |
|---|---|---|
| six StackExchange | CC-BY-SA | **Admitted** for acquisition, private hosting, and training. Share-alike obligations attach to redistribution, which the public bar already gates. |
| python-language-docs | Python-2.0 | **Admitted.** Permissive; its absence from the allow-list is a gap in the list, not a property of the licence. |
| llvm-docs, rust-reference-docs | compound SPDX | **Validator defect, not a policy question.** `Apache-2.0-WITH-LLVM-exception` and `MIT-OR-Apache-2.0` are malformed — SPDX operators are space-delimited. Fixed in `wave_manifest.py` under #1720's follow-up, together with a parser that resolves `OR`/`WITH` against the allow-list instead of string-matching it. |

Admission and redistribution are separate gates and are kept separate here. The
allow-list governs what may be *trained on*; the public flag governs what may be
*redistributed*. A CC-BY-SA row clears the first and still waits on the second.

Widening `LICENSES` to record the two admissions is **not** a one-line edit.
`validate_authority_index` requires every one of the 44 candidate rows to carry
`allowed_license_spdx == sorted(LICENSES)`, and those rows are sha256-bound into
the authority index — so any change to the set invalidates all 44 and forces an
authority-artifact regeneration. Sequencing is the research lead's call, not a
side effect of this document.

### Open

The Hugging Face `license:` metadata value for a `CC-BY-SA-2.5-mixed` repo. The
Hub's identifier list has no `cc-by-sa-2.5` — it starts at 3.0 — so the five
2.5-labelled repos have no correct value to declare. Options are `other` with the
real label in the card body, or the nearest available identifier with a NOTICE
correction; neither is chosen yet. Repo creation waits on this.
