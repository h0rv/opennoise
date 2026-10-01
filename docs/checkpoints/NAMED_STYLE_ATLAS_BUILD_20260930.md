# Named source style atlas build, 2026-09-30

The local atlas adds singular named musical values to the learned-community explorer. It is a candidate style surface, not a verified genre taxonomy or a sonic reconstruction of Every Noise. The export remains local research and is not publicly deployed.

## Final retained export

The final browser-certified renderer is `.cache/named-style-atlas-20260930-final`,
receipt `40d40e21d05c45f0b0aa7d43fe4392d9739696ea35f0778bee068e1c46e34924`.
It preserves all v3 data and changes only the HTML and JavaScript wording;
42,861 other files remain byte-identical. Independent verification checked all
42,863 files, every artist profile and all cohort totals. Chromium passed
desktop/mobile, exact-ID and name search, full pagination, history and filters,
with 45 local requests and zero external/media requests or runtime errors.
Evidence is retained in `.cache/named-style-atlas-browser-20260930-final-verified`.
The reported 355 ms readiness is one local observation, not a latency percentile.

`.cache/named-style-atlas-20260930-v3` is the final primary-v2 export. Its self-hashed receipt is `e09925cb3c4fc1996740cc35bc677155f5fc124b3abcf161f14b7d1a3cd3cfd6`; every one of its 42,863 declared files and 1,400,236,653 bytes was verified. Original full source construction took 134.985 seconds with a measured peak RSS of 287,023,104 bytes. V3 is a verified clone of retained v2 (`a683830c817ba222eaf5b8b1ab83a5caffc5b0ad2a9d7d6db46fb678991396e6`) with atomic replacements of display rows and renderer assets. All artist profiles, role cohort pages, search bytes and musical geometry remain byte-identical to v2.

| Output measure | Exact count |
| --- | ---: |
| Source artist identities | 198,409 |
| Named artists / unresolved names | 198,390 / 19 |
| Input feature observations | 615,812 |
| Observed artist-feature memberships | 434,067 |
| Credited release-context memberships | 777 |
| Inferred feature proposals | 594,776 |
| Candidate style atoms | 14,060 |
| Positioned / unpositioned atoms | 3,196 / 10,864 |
| Source geometry edges | 15,571 |
| Default named styles / positioned styles | 2,226 / 1,934 |
| Dictionary names / repeated candidates / raw candidates | 1,447 / 779 / 11,834 |
| Artist-feature / release-context / proposal cohort pages | 17,718 / 261 / 6,722 |

Source namespace support is independently checked against the entire feature cache: 387,435 artist-genre pairs, 154,908 artist-tag pairs, 605 release-genre pairs and 777 release-tag pairs. Namespace support and role cohorts can overlap; `source_artist_support` counts each artist once across source roles. Inferred memberships never increase source support or the display evidence tier.

## Construction and source custody

The implementation is `src/opennoise/deployment/style_atlas.py`; the only command wrapper is `scripts/build_local_style_atlas.py`. The project remains Python 3.13 and static-only, with Poe as its task runner.

```sh
.venv/bin/python scripts/build_local_style_atlas.py \
  --source .cache/parity-source-explorer-20260930-v3 \
  --features .cache/microgenre-features-primary-v2/artist-features.jsonl \
  --enrichment .cache/artist-feature-enrichment-primary-v2 \
  --output .cache/named-style-atlas-NEW
```

The output must be a fresh path within project `.cache`. Existing outputs and symlink escapes are rejected. Source receipts and every declared artifact byte are checked before consumption. Feature input lineage verifies source caches and excludes audio and historical assignments. Prediction artifacts must bind the exact feature hash, frozen model hash, observed source values, cue references and training support counts. Every feature-cache artist must have an exact source profile and complete prediction record. Names are joined only after geometry and musical identities are constructed.

| Binding | SHA-256 |
| --- | --- |
| Feature payload | `0c298b1241b03e642dbc7b13981f59b9008cb1fdc4e01186b5fe55e7f2c78748` |
| Feature receipt file | `00f3cd770b04368999a1685641bff00a37bdb606b68926b57d44e13603d78b1f` |
| Source-profile explorer output | `0deaa234b5637ca734b6558022ad3e1fab1573ee45f7547e37b144deff1d84a9` |
| Prediction output | `c987e91f4de32dc7d254f9d1e69ddf8185dd5bbae0503c73e9f67dcb6575d63c` |
| Enrichment model | `f2cc996bb657a64ab49d3ca4223d61754008bed67473f844c45c364915a958f2` |
| Exact native-name dictionary | `dd0d201c0942d55d423a6af4f45c2bee15675c4182b1d076c61c13b0773a9577` |
| Frozen v3 display builder | `5f60e0d995e769c245bac718d30e73e4c3fdce6e522525b979466b5e50e9ca70` |

Artist tags remain observed artist features; credited release genres and tags remain context. The atlas never turns a tag, a dictionary spelling match, a release credit or a model proposal into native artist genre truth. The original 697 direct proper genres remain represented by the source catalog. The atlas's `native_genre_ids` is an exact canonical-name dictionary join only.

Style IDs are `style-` plus the first 24 hexadecimal digits of SHA-256 over the canonical musical value. Original labels and source features are preserved. Sparse source musical cooccurrence uses distinct artists, cosine weights, joint support of at least two artists, and at most 12 neighbors per style. Shared spectral and rectangular-atlas helpers perform offline layout. Repeated identical artist-support columns abstain from separate coordinates; insufficiently supported nodes remain searchable. Proposed memberships, display names, historical reference geometry and audio are not geometry inputs.

## Display recipe and static API

`named-style-display-v3` shows exact dictionary names and source candidates supported by at least five distinct source artists, with a reversible display screen. Clear ranking, record-label, event and biographical labels plus reviewed pure nationality, occupation, status and technical labels stay in the raw tier. Exclusions apply to display only and do not delete source atoms, artist rows or proposals. Legitimate compounds such as `finnish string quartet` and `festival trap` remain eligible. The recipe is not a semantic classifier; future label review and independent musical relevance evaluation remain necessary.

`data.json` supplies style IDs, names, aliases, source namespace/union support, role counts, coordinates or abstentions, evidence tiers, suppression reasons and detail routes. `styles/{id}.json` adds complete cohort page paths for `observed_artist_feature`, `credited_release_context` and `inferred_feature_proposal`. Every cohort page contains at most 100 exact-MBID artists; pages are sorted by Unicode-casefolded display name and exact ID. Artist profiles live in `artists/{first-three-MBID-hex}.json`, retain full source evidence and proposal cues, and are searchable through the compact source-bound `artist-search.json`. All atlas memberships mark `native_fact: false`.

Static assets are `index.html`, `style-atlas.css` and `style-atlas.js`. A fresh display-only refresh can be created without recomputing memberships or geometry:

```sh
.venv/bin/python scripts/build_local_style_atlas.py \
  --refresh-from .cache/named-style-atlas-20260930-v2 \
  --output .cache/named-style-atlas-NEW-DISPLAY
```

## Code freeze, resource guards and evaluation

The exact eight source-module bindings used by retained v3, plus the command wrapper, are preserved in `.cache/named-style-atlas-codefreeze-20260930-v3`. Its independently sealed receipt is `936fdcc5ce214305d8a223c885407d5e300ca1fa7cdff58f4655df05a50c98f6`. Some repository modules subsequently changed for bulk feature acquisition; the retained export binds its frozen snapshots, not those later module versions. Exact replay requires those snapshots together with the repository and locked dependencies.

The repository's future-input resource guard is now `named-style-resource-v2`: at most 50,000 source values, 250,000 artists, 5,000,000 feature observations, 512 musical values per artist, 50,000,000 source pair observations and 64 MiB per proposal shard. The vocabulary bound increased from 30,000 to 50,000 because the future primary-v4 source universe contains approximately 31,900 values. This is a resource-only extension and does not truncate that universe or alter retained primary-v2 output. Row and pair-work limits are unchanged. Future full construction receipts record the guard revision and value bound.

Ten focused tests pass, covering source roles, native-fact exclusion, canonical source evidence, duplicate-support abstention, sparse joint support, dense pair-work rejection, exact full pagination, distinct source unions, display review and create-only behavior. Scoped Ruff and type checks pass. Browser certification is maintained by the renderer's separate harness and does not establish musical validity.

The independent evaluation report `.cache/named-style-atlas-parity-audit-20260930-v3` is sealed by `f64a8a1b79a9c10e7ce40ca4340ee819c639b6b9bdcff19f590cdd362c472c8f`. It rereads actual v3 names and ten sentinel artist profiles. Using the historical H2 reference only after construction, all candidate names match 1,621 of 6,291 reference strings (25.77%); the default display matches 986 (15.67%). These are dated spelling diagnostics, not a genre identity bridge or a parity percentage. See `NAMED_STYLE_ATLAS_PARITY_AUDIT_20260930.md` for scope and unresolved quality gaps.

The removed v1 draft and its prior audit hash are explicitly documented in that migrated checkpoint. V2 and final v3 are retained. Source captures, feature caches and research models were not removed. Core metadata is CC0-1.0; tag-derived output retains CC-BY-NC-SA-3.0 obligations. Public export and public serving remain unauthorized by these research receipts.
