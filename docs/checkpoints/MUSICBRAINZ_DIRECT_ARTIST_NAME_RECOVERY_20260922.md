# MusicBrainz direct artist-name recovery

This checkpoint records an implemented but not yet executed local recovery
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

The replay hashes and minimally parses all 2.97 million artist records once;
it is a streaming pass with bounded raw records and target-name aggregation,
not a SQLite import, but it has no resume checkpoint. The archive hash
precheck reads all 1.6 GiB compressed bytes once before that parse pass.

The typed receipt accounts for unique names, conflicted MBIDs, MBIDs with only
invalid names, and targets not observed, and binds the input custody receipts,
archive bytes, and compressed object checksum. Export, serving, and membership
authorization remain false. The CLI's default object and receipt paths are
under the ignored local `.cache/musicbrainz-direct-artist-name-recovery-v1/`
directory; no serving or public export is produced.

Synthetic tests cover exact-MBID target selection, repeated names, conflicts,
invalid names and IDs, malformed records, missing targets, bounded raw-record
provenance, append-only output, and verifier rejection of rehashed false
conflict accounting. The pinned 1.6 GiB archive has not been scanned by this
recovery builder. Run it after resource review; outputs must remain local
pending separate policy review.
