# Local MusicBrainz Album discovery query

The local query reads the verified report at
`.cache/musicbrainz-release-group-album-examples-v1/report.json`. It accepts an
exact genre name or an exact credited artist MBID and returns deterministic
JSON. The query is a callable local module and a direct script. It adds no web
server or project task command.

Each result preserves its seed identity, native genre name and MBID, positive
genre vote count, album title, first release date, release-group MBID,
secondary types, and source-ordered credited artist MBIDs. An optional verified
local artist metadata artifact can supply canonical names by exact MBID.
Results identify the genre as a native proper-genre observation and the album
as a ranked source-context example. They state that the album does not define
the genre and that artist membership is not asserted.

Example command:

```sh
.venv/bin/python scripts/query_local_musicbrainz_album_examples.py --genre-name "Rock"
```

The fixture tests cover exact case-sensitive genre matching, exact credited
artist matching, preserved album and genre fields, explicit source roles,
query validation, and deterministic JSON output.
