# Local native melody-contour subsequence search

A caller can supply new time/f0 coordinates and retrieve the best fixed-tempo,
absolute-pitch alignment in each retained native Melody2 annotation. Results give
native track IDs, frame bounds, observed sample timestamps, distance ticks and
voicing support. This is a new temporal numeric query capability; it does not
look up saved ranks, extract pitch from audio, identify a MusicBrainz recording,
classify genres or establish musical relevance. Existing scalar descriptor paths
cannot represent this alignment task.

The implementation and generated synthetic fixtures are MIT code. MedleyDB data,
annotation-derived packs, queries and results remain **local research only under
CC BY-NC-SA 4.0**. No audio, metadata YAML, artist/genre labels, third-party download
helpers, credential files or MedleyDB Python code are consumed. No raw annotation,
real track ID, pitch sequence or per-track result is checked into this recipe.

## Frozen source boundary

The official source repository is [marl/medleydb](https://github.com/marl/medleydb)
at commit `537bb7bad0601fc58e4fff8404f71658b86ef60e`. The pinned V1 roster has Git
blob `80c7a072beea9522a0ae77dfce497cdde307fafd` and SHA-256
`62ad6904fbdeaa0157465241bc8ad01a0d2201ec6a8959db4709687ee5217fe6`.
The declaration was sealed before coordinates, file availability or outcomes:
SHA-256 `8b2e163e5d37b72ae0bc894c6583ed4b2da1913bc909066dc5afe0e2c03d36b9`.
Select the first 24 V1 native IDs ordered by
`SHA256(UTF8("opennoise-medley-melody2-pilot-v1" + NUL + nativeID))`, then native ID.
Only the corresponding `medleydb/data/Annotations/Melody/Melody2/<nativeID>_MELODY2.csv` annotation
representation is permitted. Missing, malformed or over-cap nominations are not
replaced by another track.

The pre-coordinate size allocation preserves nomination order: exclude files over
2 MB, then stop otherwise eligible captures after the first file that would
exceed the remaining 25 MB budget. Later eligible files remain explicitly
`not_attempted_total_cap`, even if individually smaller. The frozen preflight is
`e58a9d00f624d6672550e70c1653a3db501eadc0e9db7ad8aa820245b48d1535`.
The retained capture has **18 usable files out of 24 nominations**, 15,186,966
bytes and 473,373 frames. Three nominees were absent from the pinned official
Melody2 directory listing; these are not observed HTTP 404s. Three others exceeded
the per-file cap before capture. Eighteen files were fetched and validated, not
24 attempted downloads. The sealed source census SHA-256 is
`480d0707afee0d38d47ef204c7f1987c80d65044abdbb9fd8db30a25dc61e5c6`.

[MedleyDB's author download notice](https://medleydb.weebly.com/downloads.html)
grants [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) for
the data/annotations, separately from its code license. Attribution: Rachel
Bittner, Justin Salamon, Mike Tierney, Matthias Mauch, Chris Cannam and Juan P.
Bello; MedleyDB 2014/2016. The numeric input is a human-reviewed melody annotation,
not an automatically computed acoustic descriptor or a relevance judgment.

## Exact numerical contract

Source timestamps must follow `i*256/44100` seconds within 5 microseconds. Query
timestamps have a finite nonnegative origin and the same relative grid. No
resampling, interpolation, transposition, tempo warping or octave correction is
performed. f0 must be finite in 0–20,000 Hz; zero means unvoiced. Voiced MIDI is
computed in float64 as `69 + 12*(log2(f0)-log2(440))`, avoiding division underflow
for positive subnormal inputs. Unvoiced pitch values are masked.

For every fixed-length candidate window, each jointly voiced frame contributes
squared MIDI difference, each voiced/unvoiced disagreement contributes 144, and
each jointly unvoiced frame contributes zero. Divide the float64 `np.sum` of all
frame costs by **all query frames**. A query needs at least 25% voiced frames;
a candidate needs joint voicing on at least 75% of the query's voiced frames.
Insufficient voicing returns explicit outcomes, not forced neighbors.

Quantize the mean distance to nearest `1e-8` semitone-squared ticks, ties to even
(`np.rint(distance / 1e-8)`, equivalent to `round` on these finite scalar values).
Pick the earliest source frame among equal ticks within each track, then sort
tracks by tick, native ID and frame. An earlier tiny positive distance can beat
a later exact zero when both quantize to zero. Report the unrounded cost and
voicing counts for the selected alignment. Query hashing canonicalizes validated
float arrays to JSON lists; list and ndarray callers have the same semantic hash,
and caller arrays are never made read-only or mutated.

The scorer directly evaluates nonnegative per-frame costs in chunks of 128
windows; no FFT cancellation, learned normalization, fitting or parameter sweep
is used. Longer tracks have more candidate windows and thus more opportunities
for a low minimum; no correction for this minimum-selection bias is claimed.
Exact source-fragment retrieval tests correctness only, not independent musical
quality or real-world humming robustness.

## Standalone local use

The paths and pins below describe existing local custody, not checked-in inputs
or a promise that another container has the files. A permitted future capture
must truthfully reconstruct the fixed official cohort and its own externally
pinned declaration, preflight and census. Runtime has no acquisition path. If the
required approved bytes are missing, report the source dependency; do not invent
custody, substitute another dataset or retry a denied route.

```sh
PYTHONPATH=src .venv/bin/poe sync
PYTHONPATH=src .venv/bin/python scripts/query_melody_contour.py build \
  --raw /LOCAL/raw \
  --pilot /LOCAL/pilot-declaration.json --pilot-sha256 PILOT_SHA256 \
  --preflight /LOCAL/preflight.json --preflight-sha256 PREFLIGHT_SHA256 \
  --census /LOCAL/source-census.json --census-sha256 CENSUS_SHA256 \
  --output /LOCAL/fresh-source-pack
PYTHONPATH=src .venv/bin/python scripts/query_melody_contour.py query \
  --source /LOCAL/fresh-source-pack --source-sha256 PRINTED_MANIFEST_SHA256 \
  --query /LOCAL/caller-contour.json --query-sha256 QUERY_FILE_SHA256 \
  --limit 24 --output /LOCAL/fresh-result.json
PYTHONPATH=src .venv/bin/python -m unittest tests.test_medley_melody
PYTHONPATH=src .venv/bin/poe check
```

The query JSON has exactly `times_seconds` and `f0_hz`, arrays of 173–1,723 samples.
The Python API is `load_source(path, manifest_pin)` then
`search_contour(source, request, limit=24)`. Every nomination remains in the
response ledger, including unavailable sources, shorter tracks and insufficient
support. A result contains one best alignment per matched track, with
`end_frame_exclusive` and first/last **observed** sample timestamps. It does not
invent an observed time after the last sample. Optional `--output` writes a
fresh file atomically without replacing one already created; without it the
research result goes to stdout. Keep stdout, local packs and result files under
the same NC research handling; neither option deploys or publishes them.

A pack contains only its closed manifest, pilot/preflight/census and nominated
CSV files. Physical SHA-256, byte counts, Git blob SHA-1, declaration associations,
allocation, native grids and frame census are replayed. Unexpected files,
sidecars, nested manifests, symlinks, duplicate JSON keys, changed bytes, malformed
CSV and mixed rights/runtime contracts abort before a usable pack/result is
returned. A corrupted usable capture does not silently become an absence.
Source bounds: 24 nominations, 2 MB/file, 25 MB raw, 100,000 frames/track and
1.8 million total frames. Artifact metadata and results each have a 1 MB cap;
source packs have a 30 MB combined cap. Each CLI invocation enforces 120 seconds,
1 GB address space and single-thread numeric settings.

## Verification

Nine synthetic tests cover independent direct arithmetic, tick-first ties,
voicing gates/all-frame denominator, newly changed caller input, ndarray parity,
subnormal f0, exact timestamp-audit arithmetic, strict schemas, custody corruption,
rights/runtime mismatches, allocation, fresh atomic failure and actual CLI output.
Generated constant/random fixtures are explicitly synthetic, not copied melody
annotations or fabricated upstream observations.

The final synthetic maximum-cap standalone test used 18 generated constant
contours of 100,000 frames each (1.8 million total), 24 nomination outcomes and a
1,723-frame query. Source build completed in 3.434 seconds / 101,248 KiB peak RSS;
query completed in 19.937 seconds / 101,240 KiB. Both exited zero inside the fixed
120-second/1 GB bounds. Per-child Linux `wait4` measures these runs; timings are
local descriptive measurements, not universal latency claims. Final receipts
bind the final runtime hashes.

The independent numerical oracle uses no project imports: its candidate
proposals use correlation arithmetic, and positive per-frame `math.fsum` verifies
all candidate minima within its roundoff envelope. It compares native alignment,
integer ticks and support; raw float costs may differ by float64 rounding. The
first three eligible source queries in frozen nomination order are used for
that check, never chosen by outcomes. The fixed center query starts at
`floor((N-862)/2)` for each sufficiently long source. Shorter sources retain `insufficient_length`; low-voiced windows
retain `insufficient_voicing`, without moving the window or replacing the source.
All 18 actual fixed 862-frame center queries are eligible and remain in the
validation roster.
See `results.json` and its locally retained evidence pins for aggregate checks.
No artist/genre claim, independent relevance score, supervised fit or new external
cost is produced. The stopped Jamendo study and reserved style fold are unchanged.

The final full `poe check` completed with all formatting, linting and type checks
passing, 2,454 Python tests (36 skips, 291.511 seconds), and 122 Node tests
(44 skips, zero failures). The completed terminal log is pinned in `results.json`;
the execution session itself was not retained after an environment transition.
No checks were repeated or runtime code changed after that completed run.
