# MusicBrainz direct canonical artist name custody

The tracked `musicbrainz-direct-canonical-artist-name-custody-v1` object is a
compact custody-only projection of canonical artist name facts. It does not
authorize memberships, static export, serving, discovery changes, deployment,
or public claims.

The projection first reads the verified direct proper-genre custody object to
obtain its 198,409 exact artist MBIDs. It then joins only those UUID MBIDs to
the local release-group metadata database. A row is included only when
`artist_summary.canonical_name_variant_count` is one. The stored name comes
from the nested MusicBrainz `artist.name` field. The builder never reads or
uses a credited-as value as a fallback.

The object contains 164,404 canonical name facts and records 34,005 direct
MBIDs without an eligible name fact. There are no ambiguous name variants in
this source join. The canonical JSONL object contains only `artist_mbid` and
`canonical_name`, so it does not mix direct genre claims with name facts.

The compressed object is 4,993,301 bytes and is bounded to 30 MiB. Its
compressed SHA-256 is
`48a9854906c5e430acadae70371165e7c21a6d0e365e9a24177e2e5a37fc7291`.
Its uncompressed canonical-stream SHA-256 is
`b9bf174071fa604decc9ea67604e4b77dcab91256c2409042519a376b8431324`.
The receipt binds the direct custody receipt and object, the metadata artifact
and SQLite database, and the original release-group archive hash.

A checkout can verify the tracked receipt and compact object without the
ignored local metadata database. A full replay also needs the database and
its local artifact. Neither verification mode independently proves that the
ignored release-group archive was replayed when the metadata database was
built. The metadata artifact pins the source archive SHA-256, but the archive
is the remaining external trust root.

Verify tracked bytes only:

```sh
uv run python scripts/verify_musicbrainz_direct_canonical_artist_name_custody.py \
  --receipt config/releases/musicbrainz-direct-canonical-artist-name-custody-v1/receipt.json \
  --object-store data/release/musicbrainz-direct-canonical-artist-name-custody-v1/objects
```

Add the direct custody receipt and object store, plus the metadata artifact
and database paths, to replay the exact source bindings and the ordered
canonical-name stream hash. Both modes leave serving and deployment unchanged.
