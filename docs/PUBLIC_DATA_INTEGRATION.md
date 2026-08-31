# Public data integration report

Branch: `integration/public-data`

Base: main `719c427`

## Stages

| Stage | Commit | Result |
| --- | --- | --- |
| Shared source foundation and MusicBrainz | `bf8a64e` | Strict domain models, async verified transport, explicit adapter and projector registries, resumable lifecycle, and the measured deterministic artist partition. |
| Wikidata | `c2b364a` | Bounded five-kind entity slice, statement evidence, hierarchy, and direct artist and release-group genre observations. |
| ListenBrainz | `8aa673b` | Privacy-thresholded fixed-window artist co-listen aggregates, coverage records, migration 0005, and a laptop-safe incremental task. |
| Metadata-only invariant | `1cb190f` | Audio and music bytes fail closed at manifest, transport, local file, archive member, parser, and object-store boundaries. |
| MusicBrainz genre evidence | `26c4738` | Positive official-genre counts persist as append-only membership evidence with deterministic caps and explicit supplementary-data modes. |

## Reconciliation decisions

- Source adapters parse and project only. They do not own lifecycle SQL.
- The shared runner owns policy, snapshots, artifacts, attempts, checkpoints,
  quarantine, provenance, idempotency, and transaction boundaries.
- Catalog projectors own direct SQLite writes for their projection kind.
- `CatalogProjection` is one closed union covering common artist, generic entity,
  artist co-listen evidence, and co-listen coverage projections.
- Generic entity partition IDs are namespace-qualified. Cross-source identity is
  resolved only by explicit identifiers, never by names.
- The hardened MusicBrainz checkpoint and failure runner was retained. The
  ListenBrainz artifact-level quarantine record was added to that runner instead
  of restoring the earlier source-specific iteration loop.
- Object storage remains the synchronous immutable implementation already on
  main. HTTP remains async; blocking parsing and SQLite execute behind the job
  boundary.
- There is no ORM. Pydantic models are frozen and strict. SQLite writes remain
  direct and transaction ownership stays explicit.

## MusicBrainz supplementary policy

MusicBrainz classifies tags and genre associations as supplementary data under
CC-BY-NC-SA-3.0. Noncommercial use requires MusicBrainz attribution and derived
works must use the same license. The official download page says genre data
requires the derived dataset and lists that dump under CC-BY-NC-SA-3.0. Sources:
[data license](https://musicbrainz.org/doc/About/Data_License) and
[dump license table](https://musicbrainz.org/doc/MusicBrainz_Database/Download).

The ordinary mixed JSON source permits normalization and local display but
denies embedding, training, and export. The separate
`musicbrainz_json_artist_research_20260829` mode is local-only and permits
noncommercial embedding and training while still denying export and
redistribution. Public model builds use CC0-compatible Wikidata and ListenBrainz
inputs unless output attribution and ShareAlike terms receive a separate review.

## Verification

- `ruff format --check .`: passed, 95 files checked.
- `ruff check .` with `ALL`: passed.
- `ty check` with all rules set to error: passed.
- Forty-three focused source, lifecycle, membership, no-audio, schema,
  ListenBrainz, and Wikidata tests passed.
- The no-audio tests cover media URLs and MIME types, common container
  signatures, archive members, local object storage, and dependency declarations.
- Bounded full discovery advanced through the adapter and album suites, then
  timed out in the pre-existing first Litestar `TestClient` app test. Running
  `tests.test_app.AppTests.test_empty_bounded_map_preserves_viewport_aspect`
  alone also timed out after five seconds. No integrated source test failed, but
  the full suite is not reported as passing.

## Measured data and limitations

- MusicBrainz adapter version 2 scanned 2,970,393 records and imported a
  deterministic 1/16 partition of 185,779 artists. That measured database has
  identity data only. Version 3 genre evidence has passed a real pipeline fixture
  but has not rerun the 1.6 GiB archive.
- The bounded Wikidata run accepted 230 entities and persisted 39 direct artist
  genre observations, 98 release-group genre observations, and 42 hierarchy
  relations.
- ListenBrainz ingestion stores only MusicBrainz-qualified aggregate artist pairs.
  It does not retain listener identities or submitted track and artist text, and
  it does not itself choose a similarity function.
- MusicBrainz release groups, releases, and recordings are not bulk imported.
  The existing parsers and schemas do not justify downloading the 22.49 GiB
  release archive on this laptop.
- These integrated foundations do not yet generate genre similarity or derived
  coordinates. Modeling must enforce active `embed` permission for every input
  and propagate any local-only input to a non-exportable derived artifact.
