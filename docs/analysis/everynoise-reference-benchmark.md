# Every Noise independent reference benchmark

`scripts/evaluate_reference_benchmark.py` exports a verified, dated Every Noise
reference and evaluates a separately built candidate. Historical data is an
**evaluation oracle only**, never a training, construction, or serving input.
The pinned HTML hash is verified by the existing adapter before parsing.

Run directly with the project's Python environment (no new task runner):

```sh
.venv/bin/python scripts/evaluate_reference_benchmark.py \
  --reference data/vault/raw/sha256/1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180 \
  --atlas .cache/named-style-atlas-bulk-20260930-v1 \
  --output .cache/everynoise-northstar-benchmark-new.json
```

Output is cache-only and refuses replacement. It includes the reference source
hash, snapshot and data date, candidate data hash, and an output hash. The atlas
projection includes all named source labels, including raw candidates; its name
coverage is therefore an upper-bound diagnostic, not validated genre coverage.
Nearest display-coordinate neighbors are compared separately from names. They
are not editorial similarity labels. Missing candidate neighborhoods count as
misses against the full reference edge denominator.

Alternatively pass `--candidate candidate.json` with this independent schema:

```json
{
  "genres": ["pop", "rock"],
  "geometry_neighbors": {"pop": ["rock"]},
  "memberships": [{"genre_name": "pop", "artist_name": "Example Artist"}],
  "representatives": [{"genre_name": "pop", "artist_name": "Example Artist",
                       "recording_source_id": "1234567890123456789012"}]
}
```

Name comparisons use exact NFC/casefold/whitespace normalization. They are
name diagnostics, not an identity bridge. Artist and exact recording recovery
are separate criteria. Reference export retains track titles and recording IDs
but no playable media URLs. The atlas does not provide editorial representative
rankings; its empty representative projection must not be interpreted as proof
that an artist or recording is absent from the underlying source catalog.

Optional `--archive-manifest pages.json` accepts at most 100 locally retained
pages, each at most 2 MB. Entries contain `genre_name` and `path` relative to the
manifest directory; paths cannot escape it. The page parser accepts only visible
`scanme` artist names with explicit Spotify artist IDs in click metadata,
strips media fields, binds each page's hash, rejects duplicate IDs, and reports
bounded positive observations rather than complete genre membership. HTML
outside this narrow recognized structure may yield no observations. Document
order is never interpreted as representative rank.

The 6,291-genre pinned index is not a complete artist-membership census.
Membership recall remains unknown until independent archived observations are
supplied. An empty reference denominator never produces a score of 100%.
No composite parity percentage is emitted.

Live retrieval probes on 2026-10-01 failed: `everynoise.net` returned a proxy
tunnel 403; `everynoise.com/engenremap-pop.html` and both
`furia.com/everynoise_public/engenremap-idm.html` and
`engenremap-intelligentdancemusic.html` returned HTTP 403. No successful live
artist-page scrape or live-site parity is claimed. Reference tools do not fetch
or play audio.
