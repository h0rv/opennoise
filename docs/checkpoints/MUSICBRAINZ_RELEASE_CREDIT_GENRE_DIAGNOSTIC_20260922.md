# MusicBrainz release-credit genre diagnostic

This is a local research diagnostic. It does not export, serve, model, or
publish its output.

Run it from the repository root:

```sh
poe sync
.venv/bin/python scripts/build_release_credit_genre_diagnostic.py
```

The script uses only these pinned local files:

| Input | SHA-256 |
| --- | --- |
| Release-group evidence artifact | `0a626b524a2e5976f47be13b29b8d44b1dabe54098443512b548c1abd4348de6` |
| Release-group evidence database | `980b2c58e16b024d282ca1acc58b98dcab292f0e1a50917812d1b59df0340c8a` |
| Credit-catalog report | `f9ab6d74552935ecf198e28ea9f3875caf67cfcad9ee95883328c59954fcde00` |
| Credit-catalog database | `100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63` |

The command writes `.cache/musicbrainz-release-credit-genre-diagnostic-v1/report.json`.
It verifies all input bytes before parsing or querying, rehashes the databases
after querying, and writes a replay-verifiable logical output hash.

For the pinned inputs, the diagnostic found 87 exact release-group IDs, 284
release-group support claims, and 3,132 exact credit matches. Its logical
output hash is `b9a3434816e8d3bbc7f8ecfd04323539f8f87ea2a985171dab208b03574bc64a`.

Each result is an exact MusicBrainz artist-ID overlap between a release-group
genre/tag support row and a separately cached release or recording credit. The
genre/tag remains release-group contextual support. It is explicitly not a
direct artist genre-membership claim.
