# ListenBrainz recording catalog coverage

This is a local-only readiness measurement. It changes no release catalog,
model, map, static asset, source vault, or deployment.

## Exact cohort

The bounded 250,000-record ListenBrainz prefix probe now has a separate local
cohort artifact at `.cache/listenbrainz-recording-id-cohort-v1/artifact.json`.
It retains only the 2,098 selected canonical MusicBrainz recording UUIDs and
their source/coverage receipt. It retains no listener IDs, raw listens,
recording names, artists, pair IDs, rankings, or genre claims. The cohort is
bound to raw archive SHA-256
`690950fabaac58656df2b5e41ebf90f0f007e3e743b321c09c5c02d9e5fa757d` and
its sorted UUID-set hash is
`4533fdd3255f6b7f1d2ad6c1463479652ca81241113e10547ecca4f856f8659d`.

## Existing local exact joins

The receipt at `.cache/listenbrainz-recording-catalog-coverage-v1/artifact-stable.json`
reads five retained SQLite catalogs in read-only mode. Each row binds the
catalog file SHA-256 and its exact MusicBrainz recording-ID set hash. Joins are
strict UUID intersections. No title, artist, release, or inferred alias join
was attempted.

Each catalog must be a non-symlink regular file. The reader records its file
identity and SHA-256 before and after the SQLite query and rejects a changed
input. It accepts at most eight local catalogs and 100,000 recording IDs per
catalog. This is a stable local read check, not a claim of atomic filesystem
snapshots under a hostile concurrent writer.

| Local catalog | Exact recording IDs | Cohort overlap |
| --- | ---: | ---: |
| Current public catalog | 623 | 6 |
| 72-seed metadata hydration | 1,252 | 7 |
| 60-seed metadata hydration | 562 | 1 |
| 20-seed metadata hydration | 857 | 6 |
| Local catalog-expansion candidate | 1,031 | 2 |
| Union of all five | 1,606 | 8 |

The union reaches 8 of 2,098 exact cohort IDs (0.3813%). The slices overlap
substantially, so joining every retained local catalog does not materially
improve coverage. This is a catalog-coverage measurement, not a statement
about recording existence in MusicBrainz or a negative result for unresolved
recordings.

## Frontier

The MetaBrainz Dataset Hoster documents an exact recording-to-release lookup
and MusicBrainz Canonical Data lookup. The latter is a normalized
artist-credit/recording-name lookup, so it is not safe as an identity bridge
for this cohort. The exact release lookup may support a future bounded batch
metadata experiment, but it cannot by itself provide artist credit or validate
name-based joins. The canonical MusicBrainz data mapping is a possible exact
recording-alias source, but no unbounded download or query was made here.

The next safe experiment is a receipt-bound, explicitly size-limited exact
recording-ID batch against a documented canonical-data artifact or release
lookup. It must measure input coverage and response coverage first, retain only
source receipts and exact IDs, and abstain from any recording-to-artist or
genre claim not present in the source response.
