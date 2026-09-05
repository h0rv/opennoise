# Metadata representative release-group and recording slice

`metadata_representatives.py` builds a bounded, deterministic, read-only export of the selected
public-model release-group and recording representatives. It does not re-rank raw source evidence:
it reuses `ml.repository._metadata_candidates`, verifies every selected entry still exists in that
canonical loader with identical evidence references, then exposes the selected public model run and
its persisted input provenance. This prevents a second drifting album/track selection policy.

Every item remains labelled `metadata_example`: direct source metadata can demonstrate a genre
association but does not establish a quintessential album/track, popularity, quality, audience
consensus, or influence. The export has no adapter fetches and does not read audio, previews, media
assets, edition rows, catalog track rows, listener data, or historical coordinates. MusicBrainz
recordings are explicitly labelled as the track-level metadata proxy for this MVP: the current release
database has no `tracks` rows.

Against the release-certified public cache at
`/home/h0rv/projects/musix/.worktrees/final-integration/.cache/release-certify/public.sqlite`, the
selected public-model run `1` with output SHA-256
`e327045074fc6bb4e3b2e1c14410b3f337b6822e048c6038aa18703a11d2108b`. It exported 871 release-group
examples across 246 genres (569 distinct release groups) and 498 recording-proxy examples across 140
genres (395 distinct recordings). The selected run records 37,017 input provenance links. The source
cache itself contains 787 release groups, 623 recordings, 1,550 displayable album memberships, 833
recording memberships, and no releases or tracks.

The command is `poe build-metadata-representatives`, with `MUSIX_PUBLIC_DATABASE` and
`MUSIX_METADATA_REPRESENTATIVES_OUTPUT` set by the caller. The artifact is an export/verification gate
over the existing release evidence path; it does not mutate the source cache or assert that absent
releases/tracks exist.
