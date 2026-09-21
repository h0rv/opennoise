# Static v3 release receipt

Commit `592fe7c0b775104b7808eb0f8d6e3557a38dbdbe` was deployed to the
existing Cloudflare Pages project on 2026-09-21. The deployment URL is
`https://19debf3a.opennoise.pages.dev`; the public domain is
`https://opennoise.horv.co`.

The local `dist`, deployment URL, and public domain served an identical
`opennoise-static-manifest.json` with SHA-256
`99f2079f85b8889501d40dfb0a98bcb48e98c036655bd4369c8c102a4f33e3aa`.
This checks the served asset manifest, not every interaction on the public
domain. The local loopback browser certification passed the strict label-exit
gate and wrote `artifacts/semantic-map/browser.json` (SHA-256
`e19ed4cfac733b3caa1099cca91b1926dbb5b5840839ada19bab0fa7c68bc483`)
and 17 screenshots. The captured artist panel shows spaced MusicBrainz and
Wikidata links.

The v3 layout has 2,945 placed names and no label reveal scale above `1e6`.
Its maximum is about 835,120; 3,346 retained names remain unplaced. The
static discovery asset has 1,008 artists, each with exact, policy-authorized
MusicBrainz and Wikidata links. The full Poe check passed formatting, Ruff,
ty, 670 Python tests, and schema tests. The standalone Node atlas test passed.

The release does not promote inferred memberships, resolve unreviewed genre
or identity candidates, or certify a fresh raw-source replay of the public
database. See [the roadmap](../ROADMAP.md) for those remaining gates.
