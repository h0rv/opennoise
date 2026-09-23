# MusicBrainz release-group native census abstention

The aggregate-only census adapter is prepared for the pinned 1,159,485,640-byte
release-group archive. Before it reads records it requires the pinned archive,
source-cache receipt, immutable 6,291-name reconciliation byte hash
`a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0`, and
the 3,346-unplaced-seed v3 layout byte hash
`e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972`.

It retains only aggregate native genre UUID/name/vote-sign counts, aggregate
credited artist-component counts, primary-type counts, and exact normalized
seed and unplaced-seed overlap counts. It never writes a release-group ID,
title, record hash, artist ID, artist membership, or a direct genre claim.

The full streaming invocation was stopped by the local 30-second execution
boundary before it could create its required create-only ignored-cache report.
There are consequently no full-corpus counts, overlap counts, runtime claim,
or extrapolation. The fixed first-10,000-record observation remains separate
and is not used as a census substitute.
