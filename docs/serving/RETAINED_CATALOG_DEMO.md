# Retained catalog demonstration

This local provisional export reuses the full-foundation app. It includes the complete
retained public CC0 metadata catalog: 433 artists and 1,031 recording identities. The
union with the separately credited acoustic source contains 440 artists and 1,086
recordings. All artists remain reachable through search and the complete directory.

Source relationships connect artists sharing directly observed Wikidata genre claims.
Only 72 artists have such links; missing relationships remain unknown. Graph drawing
arranges those links and does not represent acoustic distance.

The separate acoustic layer retains 100 predeclared recording nominations: 55 descriptor
recordings credited to 17 artists, 34 extractor-compatible recordings credited to 13
artists, and 11 held-out queries from six artists that emit suggestions. It replays the
unchanged, hash-pinned AB178 crossfit recipe, preserves abstentions, keeps extractor
frames separate and joins through exact recording credits. This subset is heavily
electronic/ambient. It establishes neither musical relevance nor EveryNoise parity.
No playback or preview availability is claimed.

Run from the checkout after `poe sync`:

```sh
.venv/bin/python scripts/build_retained_catalog_demo.py --output .cache/my-fresh-demo
poe dev --directory .cache/my-fresh-demo/site --port 3001
node scripts/capture_retained_catalog_demo.mjs http://127.0.0.1:3001 .cache/my-browser-check
node scripts/capture_retained_catalog_demo.mjs file://$PWD/.cache/my-fresh-demo/site/OpenNoise.html .cache/my-offline-check
poe check
```

The builder accepts only fresh paths under this checkout's `.cache`, makes no network
requests, verifies existing public source packs and the frozen acoustic output, and
records source, implementation and exported-file hashes in `site/receipt.json`.
`site/OpenNoise.html` embeds the same app and JSON for opening without a server. Its
final SHA-256 is returned separately to avoid a cyclic embedded receipt. Source JSON
links work through local Blob URLs. External MusicBrainz/Wikidata/AcousticBrainz links
require a connection when deliberately opened.

The standalone HTML and screenshots can be delivered privately through supported
Library file upload. Downloading and opening HTML in a browser is distinct from an
interactive Library preview; Android device execution must not be claimed solely from
desktop Chromium mobile emulation. No public hosting or upload is performed by this
builder. New derivatives stay local unless private delivery is separately authorized.
Private annotations, benchmark results, protected folds and unretained FMA artifacts
are not inputs. The default full-foundation profile remains unchanged.

The October 22 executor's managed Chromium denies `file://` navigation with
`net::ERR_BLOCKED_BY_ADMINISTRATOR`. That route was stopped. The served app, mobile
layout and touch/keyboard navigation can be checked normally; direct file opening on
Android remains unverified. Do not change browser policy to bypass this restriction.
