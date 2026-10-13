# Eight additional licensed FMA excerpts

This separately approved capture adds eight recordings to the reconstructed 92,
using the retained official `fma_large.zip` directory. The exact proposed roster
and authorization limits are in `proposal.json`: 16 serial requests, at most
5,627,304 response bytes and 5,288,795 decoded MP3 bytes, with no retries,
substitutions, redirects or alternate sources. Source-declared licenses are
CC-BY 3.0 or 4.0; this is not an independent rights adjudication.

All sixteen requests succeeded with exact 206 ranges and the retained strong
ETag. Actual transfer was 5,103,024 bytes. All eight native ZIP members passed
header, filename, bounded decompression and CRC checks. Their 5,288,795 MP3 bytes
passed full ffmpeg decoding and ffprobe durations of approximately 30 seconds.
The pre-capture pass checked the complete native track CSV, all eight exact
credits/licenses/artist/genre fields and their archive members. All eight native
mean44 feature rows are present and finite. No full-archive SHA is claimed.

The original capture script hit an offline finalization error after all eight
successful downloads and decodes: the legacy range replay helper assumes its
first request is a directory suffix. This audio-only acquisition reused the
verified directory, so the first request was an explicit member header. The
separate offline finalizer validates exact explicit ranges and every retained
attempt without changing requests or weakening checks. Both executed scripts
are preserved verbatim as `.py.source`; their fixed local paths document this
capture, not a generic re-acquisition command. Do not rerun the capture script.

The new `fma-local-eight-extension-v2` playback protocol pins canonical hashes of
both `parent-playback-manifest.json` and `eight-capture.json`. It reconstructs
all playback records from these immutable receipts, retaining the original 32
added clips plus the new eight, and the first 24 original selections. The
expanded collection still has at most 64 clips and 64 MB; the original 60-clip
collection is preserved. The union is 100 unique recordings, not 124 (the sum
of both views). This protocol does not broaden the old collection validator.

For offline replay, set `ROOT` to the retained reconstruction directory:

```sh
.venv/bin/python scripts/build_fma_eight_extension.py --parent-audio "$ROOT/site/expanded/audio" --capture "$ROOT/listening8" --output "$ROOT/new-site/expanded/audio"
```

Copy the unchanged original collection from `$ROOT/site/original`. Then use the
existing `build_fma_reconstructed_neighbors.py` freeze/build/verify stages for
the expanded audio, keeping the original mean44 model and native declaration.
Build its static catalog with `build_fma_static_catalog.py`, then run
`build_fma_listening_home.py` and `build_fma_genre_discovery.py` on the new root.
The earlier reconstruction recipe documents exact shared arguments and browser
contracts. All destinations must be fresh. The old site and audition packets
remain intact; this expansion does not silently revise their listener tasks.

Native genre coverage is not musical quality or a 70% product score. No new fit,
public deployment, Library transfer, or listener judgment is implied.

Actual final coverage is 100 unique clips from 99 native artists and 132 of 164
direct genres. All 64 expanded clips passed actual browser playback; all four
genre discovery browser contracts passed without skips. Expanded neighbors
support all 64 queries and independently replay all 384 edges. See `result.json`
for archive hashes and the exact evidence log hashes.
