# Evidence graph artist identity overlay

The evidence graph remains immutable. This sidecar maps every graph
`musicbrainz_artist` ID to an exact canonical release-credit name when the
sealed MusicBrainz metadata artifact has one. It records `metadata_missing`
or `ambiguous_name` instead of guessing.

The receipt binds graph and metadata database/receipt bytes and logical hashes.
Its portable input locators exclude machine-specific directories. Build with
`poe build-evidence-graph-artist-identities` and startup-certify the sidecar
before lookups. `genre_artist_evidence_for` returns bounded unique artists,
per-channel claim counts, representative provenance, and total/unnamed counts.
Membership observations have no fabricated weight.

This is a local research sidecar, not a public serving export. It uses no
historical identities, memberships, coordinates, or neighbors.

The sealed v1 build completed in 78.8 seconds. Its sidecar SHA-256 is
`bc3ba67ad04f46a7443c747bded1e087e9dd40eeb5a23813e539beef7291a1c9`
(182,124,544 bytes); receipt logical SHA-256 is
`0d237ff4010fe5071d70610d7bc0c1f494c2cb9d134603ef9e260b1786684204`.
It accounts for 552,283 artist IDs: 515,896 exact canonical names, 36,387
metadata-missing abstentions, and zero ambiguous-name abstentions.
