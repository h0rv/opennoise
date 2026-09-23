# MusicBrainz direct local static source replay

This check verifies an existing ignored-cache candidate. It does not write a
candidate, modify `dist`, authorize publication or serving, or run a build or
deployment.

The replay reads the local candidate manifest and shards first. It verifies
their self hashes, canonical JSON, content hashes, byte counts, row bounds,
strict `(seed_id, artist_mbid)` order, and pair uniqueness. It then reads the
pinned direct proper-genre, canonical-name, and recovered-name receipts. The
verifier checks that their receipt and object bindings agree, and that all
three sources deny public export.

Next, the verifier recomputes the candidate seed set from the receipt-verified
direct IDs, certified static discovery, and certified semantic atlas. The set
is `(direct IDs minus static discovery IDs) intersect placed atlas IDs`. The
result must contain exactly 412 sorted placed candidate-only IDs. It streams
each exact direct claim and each exact name fact into local temporary SQLite
relations, then compares them in both directions with the candidate rows. As
it reads rows for that comparison, it also makes a second shard integrity pass.
That pass checks the file type, byte count, bounded canonical JSONL rows, order,
pair uniqueness, and SHA-256 of the exact bytes used by the source comparison.

Every candidate row must have one direct source pair, with the same
MusicBrainz genre ID, source record ID, source record SHA-256, and evidence
reference. Every direct pair in the 412-seed scope must have one candidate
row. Every candidate name must match the exact-MBID canonical or recovered
name fact. This detects a self-consistent rewritten manifest and shard tree
that an integrity-only hash check would accept.

The real local replay completed on 2026-09-23.

| Measured property | Value |
| --- | ---: |
| Candidate manifest SHA-256 | `a8f0059e7c53c802af88f27d473f6fec35b8e2f137218470e9fc3bee1b71ee70` |
| Placed candidate-only seed IDs | 412 |
| Source and output pairs, each direction | 139,268 |
| JSONL shards | 503 |
| Direct custody receipt SHA-256 | `41842340be1b661d3a12a55979f10771e5ce333282e34b92b959208028a4f615` |
| Canonical-name receipt SHA-256 | `06445802bec5120d2068dfb51afc610211063f72994c1862bbc8bad05dda4f25` |
| Recovered-name receipt SHA-256 | `0282dc6c7f2f99828b2aedf64c370d32a5a69bfa4322c153a13fe755ad92693b` |

The replay command was:

```sh
.venv/bin/python scripts/verify_musicbrainz_direct_local_static_candidate.py \
  --output-directory .cache/musicbrainz-direct-local-static-candidate-v1 \
  --direct-custody-receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --direct-custody-receipt-sha256 41842340be1b661d3a12a55979f10771e5ce333282e34b92b959208028a4f615 \
  --direct-object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects \
  --canonical-name-receipt config/releases/musicbrainz-direct-canonical-artist-name-custody-v1/receipt.json \
  --canonical-name-receipt-sha256 06445802bec5120d2068dfb51afc610211063f72994c1862bbc8bad05dda4f25 \
  --canonical-name-object-store data/release/musicbrainz-direct-canonical-artist-name-custody-v1/objects \
  --recovered-name-receipt .cache/musicbrainz-direct-artist-name-recovery-v1/receipt.json \
  --recovered-name-receipt-sha256 0282dc6c7f2f99828b2aedf64c370d32a5a69bfa4322c153a13fe755ad92693b \
  --recovered-name-object-store .cache/musicbrainz-direct-artist-name-recovery-v1/objects \
  --static-discovery dist/assets/static-discovery.4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c.json \
  --certified-manifest dist/opennoise-static-manifest.json \
  --certified-layout dist/assets/semantic-atlas.730bca93300870d35b527f377eb883ae95a3f931aad7e820b013fa592c5bf4ac.json
```

The command printed the manifest hash above. The candidate remains local-only.
It is not a claim publication, v2 or v3 asset, serving input, or release gate.
