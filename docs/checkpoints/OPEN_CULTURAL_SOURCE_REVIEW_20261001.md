# Open cultural context source review, 2026-10-01

## Decision and acquired pack

Wikidata is practical as a bounded, exact-MusicBrainz-ID cultural-context supplement. Its public structured data is CC0. Direct artist statements include genre (P136), country of origin (P495), place of formation (P740), and movement (P135). Each observation keeps the property, value QID, English value label, exact MusicBrainz artist ID, and Wikidata artist QID separate. Place and movement are contextual facts, not genre labels or proof of artist membership. The data is incomplete and not independently adjudicated.

The immutable local v2 acquisition is `.cache/open-cultural-context-wikidata-20261001-v2`. The 235,009-byte portable CC0 copy is checked in at [`data/examples/cultural-context`](../../data/examples/cultural-context/). It queried ten exact artists from the existing AcousticBrainz benchmark manifest and 100 deterministic source-catalog artists selected by exact ID from the local artist search and broad artist-genre strata. It used three GET requests and acquired 148,564 response bytes total, with no audio or user profiles. Wikidata returned 48 exact artist matches out of 110 (43.6%) and 130 direct claims: 108 P136, 14 P495, 7 P740, and 1 P135. All 130 claims had English value labels.

The local v2 manifest retains `source_genres` and `selection_stratum` from supplementary noncommercial artist-genre associations. The portable manifest removes those fields and the list of stratum labels; it keeps exact MBIDs, display names, roles, source-file hashes, and a disclosure of the selection method. Its `portable_derivation.source_manifest_sha256` and receipt field `derived_from_manifest_sha256` both bind it to the unchanged local v2 manifest SHA256 `0ceb4458cad7eda0b6111ce9cad9825f294af1273b63ea9221025553d56b53eb`. The raw Wikidata responses and CC0 artist and neighbor projections are byte-for-byte unchanged in the portable copy.

All ten benchmark MBIDs matched Wikidata through exact P434 identity. Autechre's entity had direct claims but no English artist label; the exact QID and MBID are still retained. Caribou's matched item is labelled “Dan Snaith” by Wikidata. Artist labels therefore remain display metadata, never identity keys.

| Benchmark artist | Exact Wikidata match | Artist display label | Returned contextual properties |
| --- | --- | --- | --- |
| Jon Hopkins | yes | Jon Hopkins | genre |
| Four Tet | yes | Four Tet | genre |
| Autechre | yes | no English label | genre, origin, formation place |
| Squarepusher | yes | Squarepusher | genre |
| Boards of Canada | yes | Boards of Canada | genre, origin, formation place |
| Floating Points | yes | Floating Points | genre |
| Caribou | yes | Dan Snaith | genre |
| Burial (UK dubstep) | yes | Burial | genre, origin |
| Aphex Twin | yes | Aphex Twin | genre |
| Brian Eno | yes | Brian Eno | genre |

The 100 candidate sample produced 12 benchmark-to-candidate shared-genre rows, all P136. Each has a Jaccard score calculated within P136 only and retains the shared QID and English label. There were no shared P495/P740/P135 rows in this cohort. For example, the P136 overlap between Floating Points and Si Zentner scores 0.5 with shared QID Q8341 (`jazz`). These are traceable metadata-overlap candidates, not ground-truth similarity judgments.

The earlier v1 pack `.cache/open-cultural-context-wikidata-20261001-v1` is preserved unchanged; it has QIDs without target labels. The original four-ID exploratory response in [`open_cultural_source_probe_20261001.json`](open_cultural_source_probe_20261001.json) is also retained with an explicit correction: requested UUID `e0e1a8f4-11c4-4918-9219-3d06049b63a1` was not verified as Four Tet. The frozen benchmark's Four Tet ID is `3bcff06f-675a-451f-9075-99e8657047e8`, and v2 uses that exact ID.

## Reproduction and verification

To acquire a new create-once pack at the default cache path (the command fails if that path already exists):

```sh
PYTHONPATH=src python scripts/probe_open_cultural_sources.py --acquire-pack
```

A portable example can be derived without network access into a fresh destination; output directories are create-once and existing destinations are rejected:

```sh
PYTHONPATH=src python scripts/probe_open_cultural_sources.py \
  --write-portable-pack \
  --pack-output .cache/open-cultural-context-wikidata-20261001-v2 \
  --portable-output /tmp/open-cultural-context-portable
```

The checked-in example can be verified and demonstrated without network access:

```sh
PYTHONPATH=src python scripts/probe_open_cultural_sources.py \
  --verify-pack --pack-output data/examples/cultural-context
PYTHONPATH=src python scripts/probe_open_cultural_sources.py \
  --demo --pack-output data/examples/cultural-context
```

The portable receipt records the Wikidata SPARQL endpoint, CC0 license, and source-manifest hash, and binds each exact raw response, portable manifest, direct claim projection, and benchmark neighbor output. Offline replay verifies the 110 requested IDs, 48 exact matches, 130 direct claims, explicitly listed unmatched IDs, and complete request-to-cohort coverage. It rejects absolute or escaping paths, symlinks, duplicate IDs, raw responses missing from the receipt, query or response hash mismatches, non-200 status, inaccurate byte/binding/match counts, and result sets reaching the 1,000-row endpoint limit because they may be truncated. Query batches contain no more than 50 UUIDs; each streamed response is capped at 2,000,000 bytes and total responses at 10,000,000 bytes.

## Source basis and limits

The local acquisition manifest retains supplementary MusicBrainz genre values
for cohort-selection auditing, under their original noncommercial/share-alike
terms. CC0 describes the Wikidata response and projection files. The separately
derived checked-in portable pack removes those selection claims and records its
original-manifest hash; it is the reusable CC0 example. Original local v1/v2
receipts remain immutable. New acquisitions state the license scope explicitly.

- [Wikidata Query Service](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service) documents the public SPARQL interface and query constraints.
- [Wikidata licensing](https://www.wikidata.org/wiki/Wikidata:Licensing) states structured data is dedicated to the public domain under CC0.
- Exact artist crosswalk: [MusicBrainz artist ID property P434](https://www.wikidata.org/wiki/Property:P434).
- Claims: [genre P136](https://www.wikidata.org/wiki/Property:P136), [country of origin P495](https://www.wikidata.org/wiki/Property:P495), [location of formation P740](https://www.wikidata.org/wiki/Property:P740), and [movement P135](https://www.wikidata.org/wiki/Property:P135).

Wikidata did not provide an artist similarity graph. ListenBrainz's public artist-radio route remains a randomized selection without stable scores or listener support, as documented in [the prior review](NEXT_OPEN_MUSIC_SOURCE_REVIEW_20260930.md). The established privacy-filtered local co-listen aggregate remains the better qualified similarity evidence.
