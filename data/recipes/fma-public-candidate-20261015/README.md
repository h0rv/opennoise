# Separate matching-declaration candidate

Historical FMA playback receipts verify source associations, byte custody and
complete decoding. They did not compare embedded audio license notices against
the metadata. They must not be interpreted as public clearance.

The retained 133-recording audit found 59 conflicting supplied license URLs
(56 involving NC/ND notices), 19 without embedded CC URLs, and 55 with matching
supplied declarations. The conservative candidate excludes both the conflicting
and absent groups. The 55-recording selection has 53 artists, 93 native genre
labels and 53,715,457 original audio bytes. Matching declarations are evidence,
not a warranty of uploader authority. A passed source-evidence gate never sets
`public_deployment_authorized` true.

The new standalone exporter leaves all historical manifests, audio and guards
untouched. It validates parent playback exports and source-bound genre records,
checks the frozen review/audit hashes, and re-probes the selected actual MP3 tags.
Native and embedded license declarations must match, with an explicit per-track
review of credits, source URL, privacy and contrary notices. Missing embedded
license evidence is rejected. The candidate must remain within 64 clips, 64 MB
audio, 2 MB per clip and 200 KB projected metadata; the CLI retains 120 seconds
and decimal 1 GB memory limits. No network is used.

Metadata is allowlisted: native identity, artist/title, genre membership, audio
hash/size/duration, source/license URLs and supplied attribution. Required native
credits and embedded composer/copyright/artist notices remain separate. Supplied
curators and source URLs cannot be silently omitted. Unknown source URLs remain
blank rather than invented. Actual additional publisher, stream or comment
credits require explicit projection review. Literal source `null` is consistently
missing, not an attributed person's name.

No contact/payment fields, biographies, comments or lyrics are copied into JSON.
Contact/payment content found inside retained audio tags blocks export as well.
Original bytes are preserved: three selected MP3s contain embedded lyric text,
which is flagged and not displayed or duplicated. This does not independently
establish rights in that text. FMA dataset authorship, CC BY 4.0 metadata license,
source link and projection changes appear in both the manifest and page.

The candidate supplies a genre-first directory with distinct excerpt/artist counts,
searchable genre/artist/track directories, native-ID detail links and browser
Back/Forward. Explicit Play/Stop and source/license/credit display remain outside
route rendering, so playback survives navigation. Reloading any deep link is silent. It does not relabel the 133-recording
explorer as cleared or silently transplant its model recommendations.

## Local reproduction

Keep audit files and per-track decisions private. They are not repository or
public candidate payloads. The authorized retained decision snapshot SHA-256 is
`4e186ae9b9959415dfc789f94d5aa430c49ccef69b4c00f95d80da2a020eee48`.

```sh
PYTHONPATH=src .venv/bin/python scripts/build_fma_public_candidate.py \
  --site /workspace/opennoise-root-map-20261015/site133 \
  --audit-directory /workspace/opennoise-public-asset-audit-20261015 \
  --decisions /workspace/opennoise-public-candidate-20261015/decisions.json \
  --decision-sha256 4e186ae9b9959415dfc789f94d5aa430c49ccef69b4c00f95d80da2a020eee48 \
  --output /workspace/new-matching-declaration-candidate
```

Output must be fresh. Independently pin its manifest SHA-256, then call
`validate_candidate(directory, manifest_sha256)` to check exact metadata scope,
closed inventory, preserved audio hashes and the fixed page bytes. This explicit
artifact pin is required; self-resealed arbitrary manifests are not trusted.
No deployment, upload, acquisition or modification of original assets occurs.

## Rebuild the interface without historical captures

The reviewed 55-recording candidate is sufficient to rebuild the page. This path
does not load the historical 133-recording export, private review decisions, audit
tags, source metadata or model inputs. It requires the exact reviewed manifest
SHA-256 `242505b6c393185bdca4925b3ee97eb579fac93746091e8b0675809c8c0286cf`
and the original page SHA-256
`fd4d39166545daa0688276bea9c1fa21857c5cf38a2fca77d6b5f6527c41fde9`
(or the byte-exact current page). The general validator still accepts only the
current page; legacy acceptance exists only in the explicitly pinned migration.

```sh
PYTHONPATH=src .venv/bin/python scripts/rebuild_fma_public_candidate.py \
  --prior /workspace/opennoise-public-candidate-20261015/site55 \
  --manifest-sha256 242505b6c393185bdca4925b3ee97eb579fac93746091e8b0675809c8c0286cf \
  --output /workspace/new-genre-first-candidate
```

The migration verifies the complete prior closed inventory, copies manifest and
MP3 bytes unchanged into a fresh directory, writes the new page, then verifies the
new closed inventory. The result remains 57 files with the same 55 recordings,
53 artists and 93 represented genres. Only `index.html` changes. No audio/license
scope, original asset, metadata projection, model, upload or deployment changes.

Routes use native IDs: `#genre/ID`, `#artist/ID`, `#track/ID`. Directory search is
stored as `#genres?q=...`, `#artists?q=...` or `#tracks?q=...`, replacing the current
history entry while typing. Unknown/malformed IDs show Not found and do not play.
Counts describe this small subset, not the whole FMA taxonomy or Every Noise.

Committed browser contracts use explicitly synthetic metadata and stubbed media
operations. They test counts, keyboard links, special-character search, history,
invalid IDs, silent reload, one persistent player and retry/Stop. They do not
claim genuine audio decoding or musical validation. Separate retained-artifact
checks exercise real playback and compare every original audio/manifest byte.
