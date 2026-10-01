# Local album discovery context

`scripts/query_local_musicbrainz_album_context.py` queries an exact native genre
name or canonical credited artist MBID. It composes existing verified local
album examples, startup-certified artist evidence, and an optional playlist
join report. It reads metadata only and adds no server or Poe task.

After `poe sync`, use retained research inputs explicitly:

```sh
.venv/bin/python scripts/query_local_musicbrainz_album_context.py \
  --album-report /path/to/album-examples/report.json \
  --evidence-db /path/to/evidence.sqlite \
  --evidence-artifact /path/to/evidence/artifact.json \
  --adapter-report /path/to/adapter/report.json \
  --reconciliation /path/to/seed-reconciliation.json \
  --genre-name "Rock" --limit 10
```

Use `--artist-mbid UUID` instead of `--genre-name` for an exact credited artist
query. Add `--playlist-report /path/to/playlist-album-join/report.json` for
playlist context. The report is the existing `playlist-album-evidence-join-v2`
artifact, not a raw playlist or an account identifier. No network requests are
made. Invalid inputs return a nonzero exit status without a partial response.

Each result retains the native album observation, source-ordered artist credits,
direct artist seed observations with their proper-genre or tag facet and evidence
reference, separate album-supported seed evidence, and exact release-group
playlist contexts. Multiple recording paths to the same release group remain
separate. Names do not provide identity joins. Playlist counts do not rank
albums or artists.

The query checks the shared release-group archive hash and byte count, selected
seed identities, and the optional playlist report's logical hash, source
bindings, and count accounting. Matching playlist contexts must retain the same
native record hash, genre observation, and ordered credited artist IDs. The CLI
also verifies the reconciliation file's byte hash against the album report.

Album results are limited to 25 and credited artist queries to 100 distinct
IDs. Artist seed sections preserve remaining counts, and the response reports
total and remaining album counts. Direct observation reads fail closed above
their declared bound. Output is deterministic JSON with no query timings.

An absent playlist report is `unavailable`; a supplied valid report with no
exact release-group overlap is `no_exact_matches`. Neither means the album is
absent from other playlists. Empty album results describe only the bounded
input report, not the MusicBrainz catalog.

The response remains local only with export, serving, and model-input flags
false. Credits, album support, and playlist membership never become direct
artist-genre claims. This query does not approve representative albums or
change the static release. Verification uses cross-source fixtures; this fresh
checkout does not contain the ignored research reports and archives required
to claim a retained-data run.
