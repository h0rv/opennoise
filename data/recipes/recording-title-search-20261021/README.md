# Recording display-title lookup

A caller can now search retained recording display titles and receive exact native
MBID candidates with the existing ordered-credit/artist-context response. Ordinary
`Database.search` and the static site are unchanged. They did not provide this
recording lookup: the retained catalog has no recording FTS documents and the old
ordinary search explicitly selects artists/genres. `artist_works` ranks supplied
candidates; it does not resolve a caller's title.

The retained cohort contains 1,031 recording identities, 1,023 distinct display
titles, 183 non-ASCII titles and eight duplicate-title pairs. Equal titles remain
separate MBIDs. These titles derive from the separately pinned retained hydration
artifact's track titles (1,115 track rows); duplicate recording-ID titles agree.
The safe cached credit projections retain neither recording nor track titles.
This is not independent verification of an original HTTP recording-title field.
The portable core source is pinned at `13921b94a5a0c77c625713b5e272d40d081c67de3eb5b1299c8c1c48baf6d6ba`;
the retained hydration artifact at `9d2a7925eddf2cbf0260e502ca2b71d0a4ec92ac953d9e630f836adc08836ce3`.
Source custody and CC0 attribution remain those of the
[recording-context recipe](../recording-source-context-20261020/README.md).

## Interface and matching

`PublicRecordingNavigationStore(path).search_recordings(query, offset=0, limit=10,
genre_limit=10, related_limit=5)` returns `RecordingSearchResponse.results`, a tuple
of ordinary recording-context candidates. One read transaction covers matching,
identity checks, pagination and contexts. CLI example after building the explicit
fresh registered catalog using the preceding recipe:

```sh
.venv/bin/poe sync
PYTHONPATH="$PWD/src" .venv/bin/python scripts/query_recording_context.py \
  --database .cache/recording-context-catalog/musicbrainz-first.sqlite \
  --database-sha256 EXTERNALLY_RETAINED_DATABASE_SHA256 \
  --query 'Metal Gear Solid' --offset 0 --limit 10
```

`--query` and `--recording-mbid` are mutually exclusive. Exact-MBID output remains
unchanged; search pagination is rejected in exact-ID mode. Both modes retain the
pinned immutable main-file read, sidecar refusal, before/after physical pin checks,
100 MB database/2 MB output caps and 120-second CPU/wall/1 GB process bounds.

Matching is a literal substring after Unicode NFKC, casefold and whitespace
collapse, implemented by a deterministic connection-local SQLite function. There
is no FTS operator/wildcard interpretation, diacritic removal, fuzzy identity join,
learned score or automatic first-match choice. Query text is at most 200 characters
and must contain meaningful alphanumeric text. Results sort by normalized eligible
matched title, then native MBID. Multiple matched observations of one MBID dedupe
before pagination; the emitted matched title itself is authorized for both uses.

Both the exact recording identifier and the matched title require their own
registered CC0 chain with **local_search and display** permission on the same
observation. Suppressions are checked before deduplication and pagination. Hidden
exact duplicate owners veto; no alternate identity is chosen. No hidden totals or
snippets are returned. Credit availability is separate: a searchable recording may
have withheld credits, without disclosing their unauthorized members.

The scan refuses more than 100,000 recording-name observations or 10,000 raw matched
name candidates; it never returns a falsely complete truncated candidate pool.
Offsets are integers in 0..10,000 and limits in 1..10. At the retained scale this
requires no new FTS index, ingestion mutation or artifact export.

## Verification and custody

An independent source-title oracle checked 1,023 full-title queries and their 1,135
expected substring memberships, reaching all 1,031 native IDs. In each ingestion
order, 193 Unicode/literal variant queries and 66 pages also passed; 2,002 complete
contexts matched the prior verified recording-context outputs. The 1,282 query-page
native-ID sequences agree across insertion orders. Twenty-four negative controls
passed, with 23 exact release restorations: local_search/display/all source-chain
vetoes, identity/title eligibility before pagination, unrelated uses, independent
credit display/search behavior and hidden duplicate ownership. Active network,
subprocess and SQLite-write denial probes passed with zero actual forbidden attempts.
Final hashes, check counts and executor-local evidence paths are in `results.json`.

During preliminary assessment, `Database(path)` was accidentally used with its
writable default for three baseline searches, changing the old proof database's
journal header. Whole-file hash reconstruction independently confirmed only journal
flags/counters changed; no facts changed. The changed file and old receipt remain
preserved, never silently repinned. New standalone copies have their own explicit
pins, and all subsequent observations use read-only connections. The full correction
is bound in `results.json`; those local paths are not promised future inputs.

This adds title access, not new recordings, features, human judgments or model
quality. Artist genre context remains the credited artists' source context, never
recording genre membership or musical relevance. No fitting, acquisition, UI,
experimental promotion or new external cost occurred. The stopped study, reserved
Jamendo style fold and source-specific denials remain unchanged.

Full `poe check` passed: 2,437 Python tests in 262.068 seconds (36 skipped),
122 Node tests passed (44 skipped), and formatting/lint/type checks passed.
Log: `/tmp/recording-title-full.log`. Luna reviewed the source/docs and passed
eight focused tests independently.
