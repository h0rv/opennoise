# Full retained-input reconstruction

The separately named `open-foundation-full-input-v3` profile rebuilds the retained
open source inputs without either sealed legacy release file. It does not claim
to reproduce that release or complete Every Noise parity. The portable profile
and all earlier outputs remain intact.

The verified export at `/dev/shm/opennoise-full-input-foundation-20261003-v4`
contains every one of the pinned MusicBrainz core projection's **2,999,670 artist
identities**. Complete ordered browse pages, an exact MBID index and prefix
search cover the same denominator. Native names stay literal; duplicate names
remain distinct identities. Search uses Unicode NFKC casefold, with 6,000 shared
browse pages and a **223,421-byte** lexical bounds index. No server, 55,000-file
prefix index or duplicate search payload is necessary.

There are **10,553 artists with source details**, **10,309 with observed direct
Wikidata genre statements**, and **1,018 observed genre QIDs**. The newer native
entity acquisition was selected from a capped, genre-positive Wikidata scan;
these are source observations from a biased cohort, not a representative musical
classification of three million artists. The remaining **2,989,361 identities
have no observed genre** in this reconstruction. Unknown genres remain unknown.

The full optional FMA catalog contains **109,727 native track records**,
**16,916 native artist records** and **164 genre definitions**. Its **168 exact
artist bridges** use literal native URLs and matching MusicBrainz entity kinds.
FMA track annotations remain separate track context, never factual MusicBrainz
artist genres. This namespace carries **CC BY 4.0** attribution; MusicBrainz,
Wikidata and native AcousticBrainz facts remain **CC0**. Eight separately named
FMA audio examples retain their individual source licenses. Thirty-six exact
recording requests produced nine source provider destinations; availability and
regional access were not checked, and provider metadata grants no media license.

Native numeric examples cover 55 exact credited recordings. The typed Wikidata
context preserves 1,003 observed genre QIDs and 314 source parent entities, with
literal P31 types and P279 edges. These edges are not musical distances,
calibrated artist memberships or a semantic map.

## Construction and validation

Run `scripts/build_full_input_foundation.py build --output NEW_DIRECTORY` with
`PYTHONPATH=src` and the locked Python environment. Optional roles are explicit:
`--entity-pack`, `--listening-pack`, `--genre-context-pack`, and the jointly
required `--fma-source`, `--fma-projection`, `--fma-bridge`, `--fma-static` inputs;
`--fma-listening-pack` adds separately licensed audio. `--identity-base` can reuse
an existing immutable identity substrate after replaying its entire pinned
source stream and all copied identity indexes. It never copies old musical
projections. Output directories must be new; JSON writes refuse replacement.

`validate` requires the same input roles and checks the closed output file set,
source receipts, native claims and credits, every database identity against the
complete pinned source stream, every browse/MBID/search view and each full genre
cohort. It also rejects forged completeness, license, featured-cohort and
missingness declarations. The full source projection is pinned independently of
its supplied receipt. No missing sealed legacy input is renamed or substituted.

An initial completed export failed only while writing its receipt because an
audio input role used the wrong filename. The `seal` operation created the
previously absent receipt without replacing any generated file. Sealing alone
is **not validation**. Subsequent full replay succeeded: receipt
`03046fcb703c729dc8cc2651ba22672339b950377887ea5da3548d22d98583d1`,
2,999,670 native rows checked, 149.32 seconds and 298,788 KiB peak resident memory.
The bound validator source hashes and exact counts are in
[evidence/full-input-reconstruction-20261003.json](evidence/full-input-reconstruction-20261003.json).
Earlier OOM attempts and intermediate outputs remain preserved.

This evidence establishes source and export correctness. Independent musical
review, calibrated musical memberships, broad representative listening,
semantic geometry and full end-to-end acceptance remain separate requirements.

## Verified research extension

The final candidate `/dev/shm/opennoise-full-input-foundation-20261003-v8` adds
three separately named research namespaces: the native FMA descriptor map,
FMA track source-component memberships, and experimental exact-MBID Wikidata
source-label completion. Native artist details remain byte-identical immutable
links to the verified source-only export. A separate set of 256 exact-ID shards
contains the supplementary fields; suggestions never replace observed genres.
The source-label model covers 9,992 exact identities with 48,246 suggestions.
Its full-seed and musical membership probabilities remain null. Mathematical
FMA coordinates remain descriptor context, with CC BY 4.0 attribution.

The genre index is now 101,551 bytes of labels, exact counts and lazy cohort
routes; every full cohort remains exported and independently checked. Source
coverage and musical missingness counts above remain unchanged. The five current
UI assets expose source facts and research suggestions separately. Actual browser
validation is a separate, receipt-bound requirement.

Use the `assemble` command with `--source-base` and its exact successful
`--source-proof`, plus the same native input roles and optional `--fma-map`,
`--fma-memberships`, `--artist-source-completion` roles. It requires a new output.
`--research-base` optionally reuses existing supplement shards only after exact
re-derivation and byte comparison. It does not use that candidate as source
proof. The final `construction.json` records actual Git base, dirty source-file
hashes, construction/UI/model hashes, invocation arguments, exact input bindings,
page and normalization parameters, and the absence of construction randomness.
Frozen model declarations and code snapshots remain in their own namespaces.

Fresh whole-source replay succeeded for receipt
`ccf4135e3fb18dca9369de22b5b512d9d08f81d88060b5730a435d4bff3f3de1`:
20,533 closed files, all 2,999,670 native identities, every complete index,
source detail, direct-genre cohort and research supplement. Construction and
validator implementation hashes match exactly. Runtime was 153.545 seconds,
with 150,344 KiB peak resident memory. The native entity verifier streams each
row and compares every reconstructed field through its canonical hash, avoiding
retention of the entire 48 MB native projection and a second decoded copy.
A focused test rejects changed country/reference claim metadata as well as
invented musical probabilities and unobserved model seeds.

[evidence/full-input-reconstruction-v8-20261003.json](evidence/full-input-reconstruction-v8-20261003.json)
contains the actual replay and resource records. Earlier partial assemblies and
OOM replay attempts remain preserved. This establishes engineering evidence;
independent musical judgments, broad licensed listening, useful microgenre
calibration, semantic musical geometry and full parity remain unmet.
