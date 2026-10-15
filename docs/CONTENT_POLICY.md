# Metadata-adapter content policy

This policy applies to the original metadata source adapters and their object
store, not every separately approved research pipeline in the repository.
The bounded FMA listening pipeline now retains licensed audio excerpts under
its own source, license, byte, hash and decode checks; see
[local listening](serving/LOCAL_LISTENING.md) and the
[current architecture](serving/architecture.html). Its numeric model uses
FMA-authored feature summaries. These exceptions do not authorize metadata
adapters to fetch audio or turn a local listening export into a public release.

The metadata adapters never download, store, parse, serve, embed, or train on
audio or music bytes. Their source artifacts must declare `content_kind = "metadata"`.
Download URLs, response media types, local files, and archive members are
checked before their contents enter a parser or immutable object store. Known
audio, media, preview, playlist, and stream suffixes and container signatures
fail closed and quarantine the source attempt.

Track names, release titles, recording identifiers, preview state, and outbound
HTTP links are metadata. They may be retained when their source policy permits
it. OpenNoise does not follow preview or stream links. ListenBrainz parsing discards
submitted track and artist text and retains only MusicBrainz artist identifiers
needed for privacy-thresholded aggregate evidence.

The initial metadata schema contains dormant tables named `audio_feature_*`. They store
only typed numeric or textual observations and have no blob column, downloader,
decoder, extractor, model, dependency, or application writer. They are not an
audio implementation. Any future use would be limited to already-published
metadata values and would require a separate reviewed change. Raw media bytes
remain forbidden in that metadata-adapter boundary.

The invariant is exercised by `tests/test_content_policy.py` and by source
adapter tests. The test suite also rejects the introduction of common audio
processing dependencies.
