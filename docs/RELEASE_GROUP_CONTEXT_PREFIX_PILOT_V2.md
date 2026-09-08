# Release-group context prefix v2

This local, non-training pilot reads the first 100,000 release-group records
from the approved cached MusicBrainz archive. It writes only to
`.cache/release-group-context-prefix-pilot-v2` through the Poe task:

```bash
uv run poe build-release-group-context-prefix-v2
```

The builder refuses an existing output root and writes a sibling staging
directory before its final rename. It binds the complete 6,291-seed universe
by source ID, source-content hash, and the stable fingerprint of sorted
`(source_item_id, source_external_id, seed_name)` triples. Producer-local
seed-input hashes are intentionally not compared because their hash domains
differ.

Every stored token is checked against the full reconciliation vocabulary,
MusicBrainz genre IDs, and the reviewed tag-only alias configuration using the
production label normalizer. `context_token.source_vote_count` preserves a
positive source count; a missing source count remains `NULL`. The report
records the derived database hash and size, stored-row counts, and the split
between weighted and unweighted rows.

## Full cached-run checkpoint

The 2026-09-08 bounded run completed with `records_seen == 100000`, 5 malformed
records, 117,929 stored rows for 14,501 artists, and 405,254 masked
artist-token occurrences. The SQLite database is 15,208,448 bytes with SHA-256
`7fa36f01447d8f0fa663044b8abee697e4ab24b760b670aaa9e65a013a8aa6ca`;
`PRAGMA integrity_check` returned `ok`. All 117,929 retained rows had a
positive source vote count in this prefix; that is an observation of this
sample, not a general schema guarantee.

An independent audit rebuilt the 724 genre IDs, 6,291 normalized canonical
tokens, and one tag-only reviewed alias from the reconciliation/configuration,
then checked every database row in SQL using the production normalizer. It
found zero masked leaks. In particular, it found zero normalized `hip hop`
rows and zero `IDM` tag rows. The 752 `IDM` genre rows are intentionally
retained: the reviewed `IDM` alias is explicitly tag-only and does not expand
to a genre-name exclusion.

Against v1's 128,956 rows and 15,086 artists, v2 has 11,027 fewer rows and
585 fewer artists. Every v2 row overlaps v1; the 11,027 v1-only rows are the
additional exclusions introduced by the canonical and reviewed-alias mask.
This remains a local, non-training, non-promotion research artifact.
