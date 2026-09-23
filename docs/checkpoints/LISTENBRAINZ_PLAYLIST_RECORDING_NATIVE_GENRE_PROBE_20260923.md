# ListenBrainz playlist recording native genre probe

This is a bounded local-only probe for the 11 exact MusicBrainz recording
UUIDs shared by the pinned ten-playlist ListenBrainz cohort and
`data/public.sqlite`. The cohort has 527 distinct exact recording UUIDs, so
the catalog overlap is 11/527. The exact join uses UUID equality and the
catalog's semantic `musicbrainz_recording_id` identifier type. No names or
other identifiers participate.

The candidate UUIDs are:

```text
2d99fbc8-d2a0-43cb-976f-7358a3c35cfd
30f7fe25-008e-476a-acef-5cfb51de6aa8
44c3ead8-c238-4d1b-be18-c48fe828135b
494c7af6-b4ec-4897-b4c7-4663099377e6
5f231710-2468-4a9e-90a0-9e8cd38b60b0
8f721dd7-ac8b-423f-a04e-5e96f05ab2b9
90141c46-0f99-4435-a90a-af666d6599b7
aa9fb372-52bb-4afc-b8fb-3aae20672d79
b175c850-0249-48ae-af23-5543c56dd45f
f0d04f76-b77a-4e88-8cdd-37aeba83e6cb
f2ada1c9-fa39-4d15-aa11-9bd798a885a9
```

The live MusicBrainz attempt did not return a response within about one
minute and was interrupted. No response bytes, receipts, or report were
written. Native recording genre coverage is therefore unavailable; this is
not evidence that MusicBrainz returned no genres. The existing fixtures test
the offline parser, exact UUID overlap, and report summaries.

When network access permits, run
`./.venv/bin/python scripts/probe_listenbrainz_recording_genres.py --fetch`.
It verifies the pinned playlist bundle and public catalog hashes, selects the
same 11 exact IDs, and uses the existing MusicBrainz client's one-request per
second limit and a descriptive project User-Agent. The captured raw response
bytes and hash-bound entity observation report are written once under
`.cache/musicbrainz-playlist-recording-genre-probe-v1/`. Run the command
without `--fetch` to verify and replay a completed local capture.

The report distinguishes native proper genres from positive-count tags. Its
coverage summary counts distinct recordings with at least one native proper
genre having a positive source count; the documented `>2` threshold applies
to that number of recordings, not to genre vote counts. Tags do not count
toward this threshold. All observations remain recording-native facts. The
adapter fixes export, serving, and artist-membership propagation to false;
there is no propagation to recordings or artists, public model/export, or
deployment.

Focused offline checks passed:

```sh
./.venv/bin/python -m unittest \
  tests.ingest.musicbrainz.test_playlist_recording_genre_probe \
  tests.ingest.musicbrainz.test_entity_genre_observation \
  tests.adapters.test_musicbrainz
```
