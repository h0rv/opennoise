# ListenBrainz popularity ranking probe

Added a local-only probe for ListenBrainz's top-recording and top-release-group
routes. It accepts one to twenty explicit artist MBIDs and retains the first
ten rows from each route's listen-count order. The documented routes do not
accept a result-count parameter, so the probe reads a response capped at 2 MiB
and projects only the first ten rows. Recording and release-group rankings remain separate.
Each ranking stores the exact request URL, retrieval time, response SHA-256,
and bounded raw response bytes, so strict parsing can be replayed offline.

When given the retained MusicBrainz album context packet, the report compares
only exact artist and release-group MBIDs. It reports candidate overlap,
abstentions, and matched positions in the per-artist ListenBrainz ranking.
This packet contains sampled release-group evidence, not a complete album
catalog. Recording results can likewise be measured against an explicitly
provided exact recording-ID set. Neither comparison uses names, titles, tags,
or rank as genre evidence. ListenBrainz listener counts are popularity within
the ListenBrainz population, not factual membership or independent genre gold.

The report and embedded raw responses are marked local-only, non-exportable,
non-serving, and ineligible as model input. The probe does not modify the
existing aggregate, evidence graph, or static export.

No real response was retained in this run: the one-artist API request attempt
could not resolve `api.listenbrainz.org` in the execution environment. This
leaves live response shape, catalog overlap, and per-seed ranks unmeasured.
The official documentation describes the two ranking routes. The server route
implementation returns the ordered result array without a count parameter.

To run a small local pilot after network access is available:

```sh
.venv/bin/python scripts/probe_listenbrainz_popularity.py \
  --artist-mbid b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d \
  --album-packet .cache/musicbrainz-album-context-review-v2/packet.json \
  --output .cache/listenbrainz-popularity-probe/report.json
```

Source: [ListenBrainz popularity API documentation](https://listenbrainz.readthedocs.io/en/latest/users/api/popularity.html).
