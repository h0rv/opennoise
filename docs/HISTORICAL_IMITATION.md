# Bridge-backed historical imitation

This is the first measured artist-membership reconstruction loop.

It uses three immutable inputs:

1. The full MusicBrainz seed-target artifact supplies the 6,291-name target
   vocabulary, direct open positives, and contextual tags.
2. The sparse open-tag matrix persists only MusicBrainz artist/tag metadata.
   It has no historical input and can be rebuilt or stored independently.
3. The bridge joins accepted MusicBrainz artist IDs to the Spotify IDs in the
   sealed H3 database. Conflicted Spotify IDs are excluded. One MusicBrainz
   artist may retain multiple accepted Spotify aliases; repeated H3 aliases
   collapse to one `(genre, MusicBrainz artist)` positive.

H3 observations are unranked positive samples, capped near 50 per genre. They
are not complete memberships. Missing H3 observations are unknown, never
negative labels. No local H3 rank is read or used.
Open direct-evidence rows are intentionally reduced to binary distinct
`(genre, MusicBrainz artist)` membership for this first prototype baseline;
their source `positive_weight` is not used.

The evaluator runs two separate models:

- `open_only_baseline`: prototype vectors from open MusicBrainz direct
  positives and the complete persisted open-tag matrix only. It is then
  evaluated against H3, but H3 never enters its candidate universe, IDF,
  feature weights, or prototype construction.
- `historical_edge_holdout`: H3 positives train genre tag prototypes after a
  deterministic per-edge holdout, while retaining a configured minimum train
  count per label.

An independent deterministic whole-label cold split removes every H3 positive
for those labels from historical training. The historical model explicitly
abstains there; the open-only baseline remains the honest cold-label approach.

Metrics are binary-positive Recall@50, MRR, and NDCG@50 in macro and micro
forms. NDCG uses ideal binary ordering because H3 has no usable source rank.
Every artifact reports label/positive counts, bridge conflicts, unbridged rows,
feature-unavailable positives, and abstentions.
It also binds separate hashes for the open-only and historical feature indices.

The default laptop profile admits the sealed full source artifact's 815,723
direct observations, with a fail-closed one-million-observation ceiling. The
effective limits are recorded in the artifact `settings` and its receipt-bound
artifact hash.

Before querying H3, the runner copies it to a private working snapshot, checks
the source hash before and after that copy, and deletes the snapshot on either
success or failure. The workspace location is operational only and is never a
durable artifact identity.

## Sealed reference run

The first full run used the 6,291-name source artifact, a 88,328-artist / 212,696-row
open-tag matrix, and H3 database SHA
`098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df`.
The matrix logical hash is
`727a3b5c346658fa82d84f3d830504d817ed4c6cf01edf4c1923f7808b3a4a23`;
its matrix byte hash is
`849284cc2fb9d4f5779bd2286105d8b6c677392595c4bf16f561f29d96c8f71e`.
The evaluation logical hash is
`da03224d64674029fe3b6f28eb11413ecc5e66eee892a30b68a50214d0d0a2eb`;
its artifact byte hash is
`49cbf0baee62ffac06ec39d0c04b6d9bc9e776023165c478f0ce20884251d12f`.

The bridge resolved 120,288 of 306,136 H3 observations to 78,954 MusicBrainz
artists. It excluded 1,065 conflicted observations and could not bridge
184,783. At the unique-Spotify-ID level, 79,159 of 240,007 H3 IDs are accepted
by the bridge (32.98%).

| Partition | Positives | Predicted / abstained genres | Recall@50 micro / macro | MRR micro / macro | NDCG@50 micro / macro |
| --- | ---: | ---: | ---: | ---: | ---: |
| Open only | 120,163 | 2,204 / 3,865 | 0.0158202 / 0.0126250 | 0.0797969 / 0.0516543 | 0.0193621 / 0.0141373 |
| H3 edge holdout | 19,384 | 3,323 / 842 | 0.0305922 / 0.0268357 | 0.0301920 / 0.0199407 | 0.0185694 / 0.0145183 |
| H3 cold labels | 23,163 | 0 / 1,172 | 0 / 0 | 0 / 0 | 0 / 0 |

Cold labels intentionally receive no historical prototype, so all 1,172 cold
genres abstain. These are unranked positive-only measurements, not a claim of
complete membership, genre parity with Every Noise, or a full reproduction.

## Build order

```sh
poe build-musicbrainz-spotify-bridge
poe build-open-tag-feature-matrix
poe build-historical-imitation
```

The matrix builder reads the seed-target artifact through its streaming loader.
The bridge consumer likewise validates rows from disk incrementally and replays
the logical JSON hash without materializing the whole bridge JSON.
