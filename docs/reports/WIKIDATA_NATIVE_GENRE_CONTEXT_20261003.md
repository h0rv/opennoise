# Native genre vocabulary and typed hierarchy context

A separate immutable CC0 source pack now hydrates **all 1,003 observed P136 genre QIDs and 314 directly referenced P279 parents**. All 1,317 requested entities have native responses. The pack preserves **2,048 native P279 statements and 1,789 P31 type statements**, with the original references in losslessly compressed raw captures. P31 supplies type context and is never a similarity edge. These source statements do not establish Spotify-level broad/sub/micro genres or human-reviewed musical fit.

The vocabulary is derived from the exact raw P136 statements of the 9,992 verified native artist crosswalks, not Every Noise labels. One outward P279 hop is selected from those original genre entities before its separate hydration. The plan permits at most 50 requests and 1,450 new parent QIDs. The actual 28 requests all returned HTTP 200; all 314 observed outward parents were requested, so the cap omitted none. Further parent-of-parent labels are outside this one-hop capture and remain explicit QID gaps rather than invented labels or positions.

[The evidence JSON](WIKIDATA_NATIVE_GENRE_CONTEXT_20261003.json) records actual graph coverage, retained/unhydrated targets, native label availability, request times and byte counts. It binds the preceding verified artist source receipt and the separately captured official CC0 licensing proof. It is a source artifact; a graph-distance model or calibrated music-membership evaluator needs its own frozen evaluation and evidence.

## Replay

The preserved pack is `/dev/shm/opennoise-wikidata-native-genre-context-v1`, containing 60 files and 6,442,994 bytes. Projection SHA256: `fc74ba372292a9d5125f7d8ad9f63885b16087a690bcfe489974a2a79696781f`. Receipt SHA256: `afdcc330cd2ed670d7e36e39bb54ca0ca6c4873a389bb4a10c4680c96b6877e9`.

```sh
PYTHONPATH=src .venv/bin/python scripts/acquire_wikidata_genre_context.py \
  --verify --output /path/to/opennoise-wikidata-native-genre-context-v1 \
  --artists /path/to/opennoise-wikidata-entities-10000-v3 \
  --core /path/to/musicbrainz-core-artist-identities-20261002-v1
```

Offline replay first verifies the complete upstream identity/artist pack. It then independently derives the observed vocabulary and outward parent roster, verifies the exact closed capture/file plan and actual status/time ledgers, checks both compressed and original native-byte hashes, and reconstructs the projected typed claims. No network call or model fit occurs. Fresh strict replay passed. Six focused tests cover lossless custody, original-byte tampering, HTTP failure admission, explicit unavailable vocabulary coverage, exclusion of P31 from the parent plan, and exclusion of Every Noise identifiers. Formatting, lint and type checks pass.

No source pack was overwritten. Original artist captures, earlier interrupted experiments and existing recovery artifacts remain preserved. This vocabulary is broader native evidence for the separately named full-input reconstruction; its source discovery remains capped and genre-skewed, and no worldwide completeness or parity claim follows from these counts.

The full native API snapshots contain two Every Noise URL references in unused P9881 statements on Q108951349 and Q116296482. These bytes remain preserved for source auditing. The compact projection consumes only P31/P279 statements and native labels, and excludes P9881 entirely. No Every Noise identifier or URL selects the vocabulary, joins an identity, supplies a model feature or becomes a training label. This is an explicit consumption boundary, not a claim that every original API byte lacks external metadata.
