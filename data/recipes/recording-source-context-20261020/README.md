# Recording query to exact credits and artist context

The ordinary catalog can now start with a caller-supplied recording MBID, read
its exact ordered primary credits, and return each credited artist's own direct
genre claims and bounded shared-genre artist context. This uses the existing
artist-navigation queries in one read transaction. It does not assign genres to
recordings, inherit every artist in a credit component, rank works, or establish
musical relevance. Existing artist-detail static exports remain separate.

The retained CC0 catalog supports 1,031 recording queries, 1,242 ordered
recording-credit member occurrences and 351 credited artists. Of those recordings,
81 have at least one credited artist with direct genre context; 950 have none.
Seven credited artists connect to 35 source genre QIDs, yielding 419 recording /
credited-artist / genre paths. These are source joins, not independent votes.
The 1,344 member tuples in the complete catalog include release credits as well;
this query uses recording-level primary links only.

## Build and query

Run from the repository root after `.venv/bin/poe sync`:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/replay_cc0_cultural_catalog.py \
  --core-source data/release/musicbrainz-credit-catalog-v1/objects/musicbrainz-credit-catalog/sha256/13921b94a5a0c77c625713b5e272d40d081c67de3eb5b1299c8c1c48baf6d6ba.json \
  --core-source-sha256 13921b94a5a0c77c625713b5e272d40d081c67de3eb5b1299c8c1c48baf6d6ba \
  --cultural-pack data/examples/cultural-context \
  --cultural-receipt-sha256 3c931909700e2840dff10e2afd2463e9123faa2a7b36e5fc1b90c472677453a7 \
  --independent-pack data/examples/independent-cultural-context \
  --independent-receipt-sha256 df9763aef5b3f5801cc9ef999ecd34b24b97c588dc25679a2adaf8432461cfa5 \
  --register-core-custody --output .cache/recording-context-catalog
```

The fresh build retains both ingestion orders. Keep the reported physical SQLite
SHA256 externally; then query either database:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/query_recording_context.py \
  --database .cache/recording-context-catalog/musicbrainz-first.sqlite \
  --database-sha256 PRINTED_DATABASE_SHA256 \
  --recording-mbid 00526a18-e31d-4b1f-bc6a-c6c7e318694d \
  --genre-limit 10 --related-limit 5
```

The async API is `PublicRecordingNavigationStore(path).recording_context(mbid,
genre_limit=10, related_limit=5)`. It retains native artist MBIDs, positions,
credited names, join phrases, both link/definition provenance IDs and source keys.
Each artist context is the existing independently bounded artist response, starting
at offset zero; the ordinary artist APIs support later pages. Unknown and
unauthorized recording identities share `recording_unavailable`, without an
internal ID/title. Withheld credits disclose no unauthorized members or counts.
Multiple eligible conflicting ordered credits return `credit_conflict`; repeated
identical observations retain their independent provenance. Gapped source order
is rejected, never reindexed. There is no name matching or heuristic fallback.

Only exact expected typed recording-key owners participate in identity lookup.
Hidden duplicate owners and wrong-kind owners veto; another MusicBrainz entity
kind may legitimately use the same UUID. Artist-only legacy `source_id` aliases
do not resolve recordings. Same-entity contradictory MusicBrainz typed values,
raw/normalized mismatches and noncanonical caller IDs fail closed. No identity
repair is attempted.

Requests are bounded to one recording, 64 primary-credit observations, 32 members
per credit and 1..10 genre/related results per artist. Overflow aborts; no silently
truncated credit is returned. The CLI has 120-second CPU/wall and 1 GB address-space
bounds, a 100 MB standalone database cap and 2 MB JSON output cap. It rejects
SQLite sidecars and uses SQLite `immutable=1` for the pinned main-file read,
then checks the external physical database pin before and after the read. A real
WAL counterfactual created after the first digest is ignored. The ordinary async
API keeps a read transaction over the caller's current catalog, including WAL. URI escaping supports ordinary filenames containing `?` or `#`.

## Honest fresh source registration

The older catalog has verified retained MusicBrainz safe projections but lacks
registered snapshot/artifact rows for its hydration and native credits. The new
query correctly returns unavailable there. The explicit fresh-build opt-in
registers the exact validated embedded hydration/credit artifact bytes and writes
`core-hydration.json`, `core-credits.json` and `core-custody.json`. It records local
replay time, never an invented upstream acquisition time or original HTTP body.
MusicBrainz cached projections retain historical response hashes, not those bodies.
Wikidata context retains and independently replays raw SPARQL response bodies.

Only this freshly staged opt-in build canonicalizes the two already-approved
MusicBrainz source license spellings from `CC0` to `CC0-1.0`. It changes no source
policy or permissions, and does not modify archived databases, sealed artifacts,
legacy restore defaults or source facts. Registration validates the exact existing
source/policy/provenance, is idempotent, and rolls back both source registrations
on conflict. The runtime reuses `ExportEligibility(..., use_kind='display')` for
own identities/names/link/definition custody and suppression checks. It does not
weaken that helper for legacy missing inventory. Artist genre and related-artist
context reuse the existing display-authorized direct-claim APIs.

These metadata are CC0, attributed to MusicBrainz and Wikidata contributors;
[MusicBrainz licensing](https://musicbrainz.org/doc/About/Data_License) and
[Wikidata licensing](https://www.wikidata.org/wiki/Wikidata:Licensing) describe the
source boundaries. No audio rights, listener relevance or recording classification
are claimed. Research models, failed Jamendo study, reserved style fold 4 and
blocked-source routes remain unchanged. No fitting, acquisition, UI/default change
or new external cost occurs.

## Verification

Focused tests exercise the retained complete cohort in both orders, source-chain
suppression/release, whole-credit member veto, exact-key ambiguity, source order,
unknown/suppressed indistinguishability, conflicting credits, async/CLI use,
physical pins, special URI filenames, exact artifact bytes, atomic registration
failure and legacy default behavior. Full checks and final independent proof pins
are recorded in `results.json` after completion. Local evidence paths describe
current executor custody, not checked-in or guaranteed future inputs.


An independent standard-library oracle parsed the retained core projections and
raw SPARQL source, without importing the query implementation. Both full catalogs
matched all 1,031 exact native recording credits, 1,242 ordered member occurrences,
419 artist-source genre paths and 277 bounded related-artist results. The normalized
native credit/context graph hash is
`36540a98f06fb1cc11b02687c0f4323aeb263e202111fdf45a672a14a554bbbe` in both orders.
Related-artist ties retain the existing local catalog-ID rule and were checked per
database; native tie order across insertion orders is not claimed.

Twenty-five negative controls passed, including both core source chains' source,
provenance, snapshot and artifact display/all vetoes, unrelated-use no-ops,
recording/member vetoes, exact direct facts and hidden duplicate ownership.
Twenty-four releases restored exact outputs. A guarded copied-input build denied
original-source reads, network and subprocess operations; complete consumer runs
actively tested SQLite-write/network/subprocess denial. Actual forbidden operations
were zero. The actual immutable CLI result matches its corresponding API result.

Final consumer binding:
`/workspace/recording-source-context-20261020/final-consumers/runtime-binding.json`,
SHA256 `c959425a137d70f1dcd599c0446ba54ecb37d354ed066d7a1cb4d562d74b6166`.
The legacy catalog also returned unavailable for all 1,031 recording queries under
the final runtime, without exposing an internal ID/title/credits or changing that
database. The unchanged builder has its separate guarded receipt under `source-proof/`;
the older combined runtime binding there predates the immutable CLI delta and is
historical. All final per-file pins are in `results.json`. The first full-check
attempt was stopped after finding that WAL gap; it is not recorded as a pass.
Final `poe check` passed: 2,429 Python tests in 241.351 seconds (36 skipped),
122 Node tests passed (44 skipped), and formatting/lint/type checks passed. Log:
`/tmp/recording-context-full-final.log`. Focused checks passed 17 tests and, separately,
the late-WAL actual-CLI regression (one test).

Luna independently reviewed the six frozen runtime hashes and found no material
code or documentation blocker.
