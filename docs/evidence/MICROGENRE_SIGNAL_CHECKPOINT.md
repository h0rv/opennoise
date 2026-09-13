# Microgenre signal checkpoint

This checkpoint answers a deliberately narrow question: can a graph made from
positive, open evidence recover held-out granular relations without using a
historical map? It consumes a source-neutral JSON contract, so an adapter can
provide genre-to-artist membership, artist similarity, broader-to-granular
hierarchy, and regional/era lineage without coupling the baseline to one
database.

The baseline is lightweight and inspectable. It uses weighted artist/genre
overlap, positive PMI among genre memberships, artist-similarity propagation,
and regional/era overlap. Granularity labels are optional evaluation-only
metadata and are not construction inputs: hierarchy candidates score every
directed genre pair and reject cycles while allowing multiple parents. It emits
review candidates only. It never publishes memberships, selects a single
parent, or creates coordinates.

Every Noise is prohibited as construction evidence. Immutable legacy names are
allowed only as vocabulary. The contract has no coordinate, legacy-membership,
or legacy-neighbor fields; it rejects historical and Spotify source IDs, and
records false flags for every historical input category.

Evaluation uses a deterministic edge-ID split over positive open edges. For
each relation it reports held-out coverage, recall, abstention, confirmed
positive hit rate, hit-rate@k, and recall@k. "Confirmed" means the candidate
matches a held-out open positive. Unconfirmed generated pairs are not
negatives, so no field is called precision and the hit rates are not a claim
of global precision.

The included fixture intentionally spans IDM/electronic music, the
rock → punk → post-punk path with Joy Division and New Order memberships, and
Nigeria/Brazil regional-cultural cases (Afrobeat/Afrobeats and Samba/Pagode).
It is a contract fixture, not a source-of-truth data release.

Run the sealed JSON checkpoint with:

```bash
uv run poe build-microgenre-signal-checkpoint
```

Set `OPENNOISE_MICROGENRE_SIGNAL_INPUT` and `OPENNOISE_MICROGENRE_SIGNAL_OUTPUT`.
