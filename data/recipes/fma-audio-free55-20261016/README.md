# Audio-free recording-profile discovery

The reviewed 55-recording profile explorer previously required and copied every MP3 even when only its saved numerical descriptors were needed. This separate export accepts the pinned manifest file and saved waveform/profile packs. All tracks, artists, supplied tags, maps and suggestions remain browsable without audio. It shows “No excerpt available” and exposes recording credits without requiring Play.

The existing playback export, template and validators remain unchanged. The new page is derived through checked substitutions from the exact original template hash, rather than another UI implementation. A changed base template fails validation until its derivation is reviewed. The export has its own revision, closed inventory and `audio_available: false` receipt. It does not authorize deployment.

## Existing data flow and limits

Artist profiles already average the saved training-standardized 52-dimensional recording descriptors and use the frozen projection. Suggested artists derive from those profiles, with original component exclusions. The 13 supported genre positions also come from the frozen waveform model. Direct genre-to-genre links are observed co-tags on the same recordings, not descriptor-derived musical similarity. All 93 genres remain reachable, including those without map positions or connections.

Whole-pack feature/model reuse, provenance and numerical replay were already implemented. This export uses those checks unchanged; validation recomputes the frozen fit and derived values to verify saved outputs. It never decodes audio or runs a new training experiment. A per-recording incremental extraction cache is not implemented: rerunning the original extraction command still decodes all 55 recordings. Such a cache is not required to browse these existing packs, so this change does not introduce one.

The independent 44-feature ridge experiment is not used here. Its fold-specific encoders are not stitched into a global map or promoted to serving. This product continues to use its distinct, previously reviewed 52-feature waveform pack. Most artist profiles represent one excerpt, not the artist's entire style.

## Bounded acceptance

- The exact 55 tracks, 53 native artists and 93 source genres remain accessible through lists, search and native-ID routes.
- Maps, inferred artist suggestions and observed genre co-tags retain their saved numerical/data bindings.
- Playback is unavailable throughout this export: no player, Play buttons, audio files, decoding or media requests.
- Attribution, license links, known/unknown native source URLs and required notices remain visible on track pages.
- Missing layout/discovery data and unsupported coordinates preserve list and identity access rather than inventing features or links.
- Keyboard navigation, browser history, deep-link reload and narrow mobile layouts remain functional.
- Wrong input pins, changed files, extra files and symlinks fail validation. No weaker audio gate or alternative data source is introduced.

This establishes a functional audio-free discovery path for this fixed subset, not full Every Noise parity or recommendation quality. Broader identities are not silently added from the numeric corpus, which cannot supply reviewed display names. Playback remains available only in the separate existing audio export.

## Actual export

The local build contains 16 files totaling **471,370 bytes**, including a 35,599-byte HTML page and zero audio files. It preserves 53 positioned artist profiles, 13 supported genre anchors, 318 directed artist suggestions and 432 directed genre co-tag links (216 undirected pairs). The original numerical packs are byte-identical. A second fresh build reproduced every file, including the site receipt.

The site-receipt SHA-256 is `f42b11fbd5990104a5a573095907a9fed7fbb9820fc242822af62b6096d0eaac`. Both builds used an isolated directory containing only the manifest. An audit guard rejected audio-file opens, network connections and subprocess execution; no forbidden attempt occurred. Existing 120-second CPU/wall, 1 GB address-space and export-size limits remain unchanged.

Focused validation includes three Python and three Chromium contracts. Independent actual Chromium verification passed all 55 track details, 53 artist memberships and suggestions, 93 genre memberships and 432 directed co-tag routes in 53.546 seconds. Desktop 1100px and mobile 390/320px navigation, maps, credits, keyboard access, history and reload passed with zero media requests, external requests or JavaScript exceptions. Intercepted 404 responses for layout and discovery separately preserved all track access. Close map points still cluster at the narrow overview; existing zoom controls and complete lists remain available. Full repository validation is recorded in the completion evidence accompanying the export.

## Reproduction

Use the reviewed input pins:

| Input | SHA-256 |
| --- | --- |
| Manifest | `242505b6c393185bdca4925b3ee97eb579fac93746091e8b0675809c8c0286cf` |
| Waveform inventory | `829f3f80308149fe03adfd582c45a50168b67eb61fe5ce82e2556e5ce208f729` |
| Profile inventory | `3304948deab27e124d3e1f9c69ddd2dbdc25ac85f0894b30944ac9112feda9b8` |

After `poe sync`, invoke the script directly as permitted by AGENTS.md:

```sh
PYTHONPATH=src .venv/bin/python scripts/build_fma_audio_free_site.py build \
  --manifest /path/to/isolated/manifest.json \
  --model /path/to/waveform-pack --discovery /path/to/profile-pack \
  --model-inventory-sha256 829f3f80308149fe03adfd582c45a50168b67eb61fe5ce82e2556e5ce208f729 \
  --discovery-inventory-sha256 3304948deab27e124d3e1f9c69ddd2dbdc25ac85f0894b30944ac9112feda9b8 \
  --output /path/to/fresh-site
```

The `verify` command takes `--site` and the same two inventory pins. No audio directory is needed. Serve the resulting directory over loopback; do not open the HTML directly with `file://`, because its JSON requests require HTTP. No public deployment is authorized.

## Remaining quality acceptance

The implementation does not fill the outstanding listening pilot: all 12 human judgments across its two six-query slots remain unprovided. Those judgments require real listeners and the existing blinded pilot artifacts, not fabricated model answers. Reliable predictive-quality claims additionally need a prospectively fixed evaluation on genuinely unexamined independent components, with native recording/artist identities, source annotations and descriptors produced under one declared feature specification. Already inspected splits are not untouched confirmation. No new data acquisition, costs, upload retry or model tuning was performed for this export.
