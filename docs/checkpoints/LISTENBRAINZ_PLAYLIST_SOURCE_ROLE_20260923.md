# ListenBrainz playlist source-route role classifier

This small local-only classifier records how a playlist was discovered. It
does not establish human curation, genre quality, playlist quality, source
independence, or any model/serving/publication eligibility.

The official ListenBrainz playlist documentation describes the user playlist
listing at `GET /1/user/<user>/playlists`, the `createdfor` listing, and the
recommendations listing. The server implementation identifies the ordinary
user listing as playlists created by that user. Therefore only a retained,
content-addressed observation of that exact ordinary listing route receives
the source role `user_created`. This is route provenance, not a claim that the
playlist is human curated.

`GET /1/user/<user>/playlists/createdfor` and
`GET /1/user/<user>/playlists/recommendations` retain their distinct route
labels but receive source role `unknown`. The former means only that a playlist
was created for the user; the latter means only that it appeared on a
recommendation listing. Neither establishes that the playlist itself was
algorithmically generated. An exact direct playlist fetch, title search
discovery, unsupported route, missing observation, and any creator string also
remain `unknown`.

The receipt fixes `human_curation_established=false`, `export_allowed=false`,
and `serving_allowed=false`. It contains route URL and content identity only;
creator text is intentionally not an input. It deliberately does not attach a
playlist MBID to a listing receipt: that would require parsing a retained raw
listing and proving membership. The existing 2026-09-23 playlist bundle was
acquired through an ordinary user listing but has not been rewritten with a new
route receipt, so its existing curator values remain `unknown`.

Sources: [ListenBrainz playlist API documentation](https://listenbrainz.readthedocs.io/en/latest/users/api/playlist.html)
and the [server playlist query implementation](https://github.com/metabrainz/listenbrainz-server/blob/master/listenbrainz/db/playlist.py).
