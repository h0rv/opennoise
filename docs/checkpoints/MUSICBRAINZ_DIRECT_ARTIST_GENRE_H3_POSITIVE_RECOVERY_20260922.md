# MusicBrainz direct artist genre H3 positive recovery

This local evaluation compares exact `(seed_id, lowercase MusicBrainz artist
MBID)` pairs. It verified the direct custody object before opening the bridge
or H3 SQLite database. The H3 genre join uses the retained `source_id` mapping
from `genres.id` to `enao-legacy` item IDs. It does not use names or aliases.

Inputs were the custody receipt `a6f874aea86f66519801b4b61f89d8150a4102a8c9266ed8f9ad31ceebf54bd9`,
the custody object `b1fc1ac9428832cb4543710b716e2d47eb8cc62dc052ed4d768ffb27dd1dcc3e`,
reconciliation bytes `c87fe5b67c0974b30d5ae1d2a9f66b22b122126230cd2561837c94897514f022`,
bridge receipt bytes `ad0f468aa68c366d99cf23e5e69dc000b0105b48f10ab9cbf1adbcbad686d4dd`,
H3 raw bytes `863a513a6da89735a69373a46ba58f6975eddb5d065964c577dfcacf18fffe20`,
and H3 SQLite bytes `098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df`.
The H3 rebuild receipt bytes were
`e157c37da8b22111a4c3ae2f04c1ed3f6ae360076919a4eef2358f8c98d311c2`.
The completed report file hash was
`9cb1ef6122a077714fa4aa7309a9012008c7bb05c5ef76892b234c20e95e776d`.
Its embedded output hash was
`71908999df0825c2852c41ff060ddee05c8381221e9903b54b7237cfba02dd49`.

The run found 387,435 custody observations, 80,928 bridge-covered direct
pairs, 22,159 distinct H3 positive pairs in the 697-seed custody scope, and
7,945 exact overlaps. Micro positive recovery was `0.35854506069768494`.
Macro positive recovery was `0.3345636272517754`, with 654 of 695 H3-positive
seeds having a hit. Two custody seeds had no H3 positive and were abstentions.

The completed command was:

```sh
.venv/bin/python scripts/evaluate_musicbrainz_direct_artist_genre_h3_positive_recovery.py \
  --custody-receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --custody-object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects \
  --reconciliation .cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json \
  --bridge .cache/musicbrainz-full-seed-targets/pipeline/musicbrainz-spotify-bridge-v1.json \
  --bridge-receipt .cache/musicbrainz-full-seed-targets/pipeline/musicbrainz-spotify-bridge-v1.receipt.json \
  --bridge-receipt-sha256 ad0f468aa68c366d99cf23e5e69dc000b0105b48f10ab9cbf1adbcbad686d4dd \
  --historical-rebuild-receipt .cache/historical-custody-vault/historical-h3-rebuild-receipt-v1.json \
  --historical-rebuild-receipt-sha256 e157c37da8b22111a4c3ae2f04c1ed3f6ae360076919a4eef2358f8c98d311c2 \
  --expected-h3-raw-sha256 863a513a6da89735a69373a46ba58f6975eddb5d065964c577dfcacf18fffe20 \
  --expected-h3-database-sha256 098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df \
  --historical-database .cache/historical-custody-vault/historical-h3/membership/sha256/098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df.sqlite \
  --output /tmp/musix-exact-pair-final.json
```

The script refuses to replace an existing output file.

This is positive-only historical coverage. It does not treat missing pairs as
negative evidence, report precision, establish artist genre correctness, or
approve a release.
