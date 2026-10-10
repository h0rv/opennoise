# Local FMA listening

The optional FMA explorer can attach a separately verified `audio` directory.
Serve its parent directory and open `/explorer/`. It remains a local research
export; public deployment is not authorized.

On 2026-10-09, the explicitly approved `fma-permitted-listening64-v1` workflow
captured 60 original FMA small excerpts from 60 native artists. Its fixed
selection covered 79 direct track genre labels. All selected licenses were
CC0, CC BY, or CC BY-SA. The conservative transfer budget selected fewer than
the maximum 64 clips.

- Official archive: `https://os.unil.cloud.switch.ch/fma/fma_small.zip`.
- 122 serial requests, 59,798,464 response bytes, 61,309,169 MP3 bytes.
- No retries, redirects, alternate hosts, transcoding, or full-track capture.
- Exact ranges, strong ETag, ZIP member headers, CRCs, hashes, frozen native
  license selection, and closed inventories passed verification.
- All 60 files passed full local MP3 decoding, with durations between
  29.988571 and 30.014694 seconds.
- Chromium started every genuine clip, verified attribution, one active player,
  keyboard playback, mobile width, and stopping media on navigation.

The whole archive checksum was not verified. Source metadata and licenses are
from the retained 2017 FMA snapshot. Source genre labels are incomplete and do
not classify artists or establish musical similarity.

## Interface behavior

The catalog embeds a small native track/artist/genre index for attached audio.
It can show excerpt availability without fetching the audio manifest at startup.
Genre and artist pages link to their available excerpts. Listen supports
title/artist filtering and an explicitly started sequential queue. Navigation
stops playback; the queue is local to the current page.

Track pages also link to up to six other attached excerpts sharing direct source
genre labels, excluding the same native artist. These links are ordered by
shared label count, then native track ID. They are separate from frozen numeric
descriptor suggestions and make no musical-similarity claim.

Genre families exposes every FMA definition using source parent links, including
unannotated, orphaned, or cyclic definitions. Position and nesting are not sonic
distance, and parent labels are not inherited by tracks.

## Reproduce verification

Use the repository's locked environment (`poe sync`) and normal `poe check`.
The capture and offline export entry points are
`scripts/capture_fma_listening64.py` and `scripts/export_fma_playback.py`.
Network stages require explicit prior approval; reusing this document does not
authorize another capture. Offline `verify` replays retained source custody.

After building a local export with `--playback <parent>/audio`, run:

```sh
OPENNOISE_FMA_GENUINE_SITE=<parent> node --test tests/static/fma_genuine_playback_contract.mjs
OPENNOISE_FMA_STATIC_ROOT=<parent>/explorer node --test tests/static/fma_catalog_contract.mjs
```

The genuine test refuses test-only manifests and is skipped when no explicit
genuine export is supplied. Synthetic queue tests remain separately labeled.
Successful decoding and browser playback do not measure musical relevance or
overall Every Noise reproduction parity.
