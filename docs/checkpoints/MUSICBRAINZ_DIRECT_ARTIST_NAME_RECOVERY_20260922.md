# MusicBrainz direct artist-name recovery

This checkpoint records a completed local recovery
path for exact canonical artist names absent from direct-name custody v1.
The target set is derived only as the set difference between the verified
direct-artist MBIDs and verified v1 name-custody MBIDs. It does not use names,
credited-as values, seed labels, or historical assignments to construct the
join.

The production builder accepts only the pinned 2026-08-29 archive SHA-256,
byte size, and snapshot. Its overridable source-binding seam is private and is
used only by synthetic tests. Before hashing or parsing the source, the builder
creates the output parents and checks that both are writable and have at least
16 MiB free for the bounded object and receipt.

The builder reuses the bounded raw-record iterator for the artist archive. It
verifies the archive's complete compressed-byte SHA-256 and byte size before
parsing. Each emitted name variant retains the iterator's record-content
SHA-256 and ordinal. That record hash covers the JSON bytes without the line-feed
delimiter; the raw iterator payload uses the same delimiter-stripped bytes.
Repeated identical names are
counted; multiple distinct names for one target MBID are represented only as
explicit conflict evidence and are not exposed by
`iter_verified_unique_recovered_names`.

The replay hashes and minimally parses all 2,970,393 artist records once; it
is a streaming pass with bounded raw records and target-name aggregation, not
a SQLite import, and it has no resume checkpoint. The archive hash precheck
reads all 1.6 GiB compressed bytes once before that parse pass.

The typed receipt accounts for unique names, conflicted MBIDs, MBIDs with only
invalid names, and targets not observed, and binds the input custody receipts,
archive bytes, and compressed object checksum. Export, serving, and membership
authorization remain false. The CLI's default object and receipt paths are
under the ignored local `.cache/musicbrainz-direct-artist-name-recovery-v1/`
directory; no serving or public export is produced.

The pinned replay recovered one unique name for each of the 34,005 targets:
34,005 unique MBIDs, zero conflicts, zero invalid-name-only IDs, and zero
missing IDs. It observed 34,005 target records; malformed, oversized, and
duplicate-same-name counts were also zero. The typed receipt is
`.cache/musicbrainz-direct-artist-name-recovery-v1/receipt.json` (output SHA-256
`cccb11be61d74adea12f8f0eec32bbece4bc93aadf25e8d0abd5f96ba7193a7b`). Its
2,637,761-byte object is
`.cache/musicbrainz-direct-artist-name-recovery-v1/objects/musicbrainz-direct-artist-name-recovery/sha256/192c564e9b6a0eea26a2b00d80d13338a58616bec80d5d2da513468c64191939.jsonl.zst`
(SHA-256 `192c564e9b6a0eea26a2b00d80d13338a58616bec80d5d2da513468c64191939`).
The receipt binds the pinned archive and v1 custody inputs; receipt/object
verification succeeded. Public export, serving, and membership authorization
remain false. The artifact remains local; this is not a public release.

Synthetic tests cover exact-MBID target selection, repeated names, conflicts,
invalid names and IDs, malformed records, missing targets, bounded raw-record
provenance, append-only output, and verifier rejection of rehashed false
conflict accounting.
