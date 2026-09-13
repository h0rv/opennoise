# Representative catalog candidates

`opennoise build-representative-catalog-candidates` writes bounded, deterministic
release-group *representative candidates*. It does not identify definitive,
quintessential, popular, influential, or high-quality albums or tracks.

Eligibility requires at least one displayable direct album--genre observation.
Artist membership may add an explicitly labeled inferred component, but can
never make a candidate eligible. A genre with no direct evidence, or too few
direct source families for the configured threshold, is retained as an explicit
abstention.

The fixed score is the sum of four recorded components: direct evidence,
direct source-family diversity, inferred artist-membership strength, and
hydrated release/media/track metadata completeness. The final deterministic
tie-break is the release-group ID. Release and track rows only establish that
metadata is present and structurally complete; they never supply audio,
streams, listeners, playability, popularity, quality, or audience-consensus
signals.

The existing immutable `album_genre_ranking_runs`, `album_genre_ranking_items`,
and evidence-link tables store candidates. No separate track ranking table is
needed: tracks are not independently genre-qualified by this pipeline, and
their only use here is the bounded completeness component for a selected
release.

```sh
opennoise build-representative-catalog-candidates \
  --database data/public.sqlite \
  --run-ref local-representatives-20260904 \
  --policy-id 1 \
  --generated-at 2026-09-04T00:00:00+00:00 \
  --max-genres 20 --max-candidates-per-genre 10 \
  --output out/representative-candidates.json \
  --object-store out/objects --report out/representative-candidates-report.json
```

The JSON artifact is canonical and bounded to 8 MiB. It is published under a
content-addressed `representative-candidates/sha256/...` ObjectStore key. A
replay with the same per-genre run refs, configuration, public-safe inputs, and
policy returns the same artifact without inserting duplicate ranking rows.
