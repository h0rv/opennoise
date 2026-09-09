# Genre seed universe

`genre_seed_universe` is a deterministic bridge from the retained Every Noise
H2 vocabulary to an approved catalog SQLite database. It consumes exactly the
H2 source ID, source content hash, source item ID, external ID, and genre name.
The H2 coordinates, colours, font sizes, representative artist or track,
sample and audio fields, H3 memberships, and historical neighbours are not
inputs. They may be present in the source artifact and are intentionally
ignored.

Catalog resolution is limited to exact normalized names and exact normalized
aliases. Normalization is NFKD, casefold, combining-mark removal, punctuation
to spaces, and whitespace collapse. A normalized label mapping to more than
one catalog identity is `ambiguous`; the artifact retains all candidates and
does not rank or select one. A unique canonical label is `direct_exact`, and a
unique alias is `alias_exact`.

For an otherwise unresolved name, a suffix token head that exactly matches one
catalog identity can be emitted as a `compositional_candidate`. Its explicit
components are review-only and never receive direct artist membership. Every
canonical membership carries only positive `direct_source_claim` evidence
read from `artist_genre_evidence`; no artist mapping is invented from names,
H2 representatives, H3 data, or compositional tokens.

Build the artifact with:

```sh
musix build-genre-seed-universe \
  --seed-artifact data/historical/historical-compatibility-v1.json \
  --catalog-database data/public.sqlite \
  --output data/model/genre-seed-universe-v1.json
```

Repeat `--catalog-database` to merge approved public and local-research
catalogs. Catalog databases are ordered by path, fingerprinted with SHA-256,
and their source keys are recorded. The artifact records per-seed
classification, all unresolved or ambiguous candidates, direct evidence
counts, distinct artist counts, evidence IDs and source references, input
hashes, and a deterministic output hash.

The Poe task `build-genre-seed-universe` reads
`MUSIX_H2_SEED_ARTIFACT`, `MUSIX_PUBLIC_DATABASE`, and
`MUSIX_GENRE_SEED_UNIVERSE_OUTPUT`. The command accepts a future imported
MusicBrainz v3 research SQLite database through the same repeatable option;
it does not open or inspect an active research database as part of this
release.
