# Metadata representative publication

The public serving catalog already persists selected release-group and recording
representatives in `public_genre_representatives`. The displayable projection
applies the selected public-model, policy, source, and suppression boundaries.

The separate JSON artifact is a deterministic, immutable exchange form for the
same selected rows. Build it from the selected serving database, then publish it
through any `ObjectStore` implementation:

```sh
OPENNOISE_PUBLIC_DATABASE=data/public.sqlite \
OPENNOISE_METADATA_REPRESENTATIVES_OUTPUT=data/model/metadata-representatives-v1.json \
python scripts/build_metadata_representatives.py  # archived workflow; not a Poe task

OPENNOISE_METADATA_REPRESENTATIVES_ARTIFACT=data/model/metadata-representatives-v1.json \
OPENNOISE_METADATA_REPRESENTATIVES_OBJECT_STORE=data/objects \
OPENNOISE_METADATA_REPRESENTATIVES_RECEIPT=data/model/metadata-representatives-publication-v1.json \
python scripts/publish_metadata_representatives.py  # archived workflow; not a Poe task
```

Publication parses the JSON with its Pydantic boundary model before writing.
It accepts only `release_group` and `recording` metadata examples whose exact
typed identifier resolves to a MusicBrainz or Wikidata metadata page. It writes
the artifact to `metadata-representatives/sha256/<file-sha256>.json`; replays of
the same bytes are reused and conflicting bytes fail.

This path never fetches a source adapter, audio, previews, media assets, or
catalog/playback URLs. A recording is a track-level metadata proxy only. It does
not assert a recording-to-release relation, popularity, quality, consensus,
influence, or that every genre has an example of either kind.

Genre detail remains compact and server-rendered. The API fields are
`representative_album_metadata` and `representative_recording_metadata`; each
item includes its rank, direct evidence value, source count, evidence references,
and declared missing features. A currently suppressed source or public model
does not pass the displayable SQLite projection and therefore cannot appear in
the API or HTML.
