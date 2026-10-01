# Source-declared external listening destinations

Captured ten exact benchmark MusicBrainz artists with URL relationships using
serial requests, 1.1 seconds between requests, no redirects, and a 3 MB aggregate
body limit. Actual source metadata totaled under 0.2 MB. No destination was
requested, no audio was downloaded, and no playback or embedding was introduced.

The verified CC0 pack `data/examples/artist-links` contains retained source
responses, per-response request URLs and SHA256 hashes, a projection hash and a
MusicBrainz data-license URL. It projects 52 source-declared destinations across
Spotify, Bandcamp, SoundCloud, YouTube and HTTPS official websites. Thirteen
Discogs source relationships are separately retained as `metadata_links`; these
are identity references, not listening destinations. Relation types and their
source identifiers remain explicit. No artist names or search URLs establish a
link. Source-declared destinations do not guarantee availability or listening
access.

`verify_artist_link_projection` checks receipt/license, source path containment,
source checksums, exact artist UUID/response identity/request URLs, and equality
of every projected artist to a fresh projection of the retained raw response.
Provider host matching prevents lookalike domains. Userinfo, HTTP, unusual ports,
IP official sites and malformed destination URLs are rejected.

Offline replay:

```sh
.venv/bin/python scripts/verify_artist_outbound_links.py data/examples/artist-links
```

Acquisition script: `scripts/acquire_artist_outbound_links.py`. It refuses an
existing output directory. Projection and helpers live in
`opennoise.serving.metadata.artist_links`; the UI agent owns optional integration
into local preview artist details. Three focused tests, Ruff and ty pass.
