# Four new artists; twelve paired genres

The exact approved CC-BY roster is `proposal.json`. Capture used eight serial
requests to the retained official FMA archive: 2,845,999 response bytes and
3,004,625 MP3 bytes, within caps of 3,108,139 and 3,004,625. No retries, redirects,
substitutions or new archive-directory requests occurred.

The complete native track CSV and source/member identities were checked before
acquisition. Every local ZIP header, payload range, attempt receipt, compressed
member CRC and MP3 SHA was verified. All four excerpts fully decoded to about
30 seconds. Exact native mean44 rows are finite; all four artists and split
components are absent from the prior 100 clips. Source-declared CC-BY licenses
are historical metadata claims, not an independent rights adjudication.

`capture.json` retains exact bytes, offsets, attempts, hashes, credits and
component/feature bindings. `capture-four.py.source` preserves the executed
bounded script; its local paths describe this capture, not permission to fetch
again. The retained source archive includes all original attempt/range bytes.

The compact `fma-local-four-artist-extension-v3` export pins all four source
inputs and its complete canonical playback manifest. It retains 44 added clips
and 20 originals, including all twelve paired-example counterparts, within the
existing 64-clip/64MB view. No recursive history or increased manifest limits are
needed. Historical protocols and artifacts remain unchanged.

Offline reproduction uses fresh destinations and the existing environment:

```sh
.venv/bin/python scripts/build_fma_four_artist_extension.py --original-audio "$ROOT/site100/original/audio" --parent-audio "$ROOT/site100/expanded/audio" --capture "$ROOT/listening4" --proposal "$ROOT/next-four-artist-proposal.json" --output "$ROOT/new-site/expanded/audio"
```

Copy the preserved original view. Use the existing reconstructed-neighbor
freeze/build/verify stages with unchanged baseline44 model/features/declaration,
then static catalog, listening-home and genre-discovery builders, as documented
in the previous reconstruction recipe. Browser verification uses:

```sh
OPENNOISE_FMA_GENUINE_SITE="$ROOT/new-site/expanded" node --test tests/static/fma_genuine_playback_contract.mjs
OPENNOISE_FMA_DISCOVERY_SITE="$ROOT/new-site" OPENNOISE_FMA_PAIR_PROPOSAL="$ROOT/next-four-artist-proposal.json" node --test tests/static/fma_genre_discovery_contract.mjs
```

The paired-route test plays both examples on each of the twelve actual genre
routes and checks distinct native artists and exclusive audio. No model fitting,
feature tuning, musical-quality acceptance, public deployment or Library retry
is part of this change. Earlier listener packets remain frozen; agents are not
independent human listeners.

Actual result: 104 clips, 103 artists, 132/164 direct genres; single-artist
genres fell from 86 to 74. All twelve paired routes passed both-example browser
playback; the expanded view passed all 64 actual playback starts and all 384
neighbor edges replayed independently. `result.json` retains hashes and evidence.
