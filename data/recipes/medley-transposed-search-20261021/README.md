# Optional bounded pitch-offset melody alignment

The separate `transposed_melody.search_contour` API accepts new caller time/f0
coordinates and searches native annotation windows with a bounded pitch offset.
The original [absolute-pitch API, CLI and source loader](../medley-melody-search-20261021/README.md)
remain byte-identical. Existing source manifests still load without rebuilding
annotations, changing their declaration or replacing source receipts.

This adds a query capability rather than saved-score lookup. It is not an audio
pitch extractor, unrestricted transposition invariance, tempo warping, artist or
recording identification, genre inference or a musical-relevance model. All real
annotations, transformed queries and derived results stay outside the public
repository under local CC BY-NC-SA 4.0 research custody. The public changes are
MIT code, generated synthetic fixtures, the frozen decision record and aggregate
evidence only. No source requests, supervised fits, new cost or deployment occur.

## Frozen metric

The declaration in this directory was sealed before new query outcomes:
SHA-256 `f3c652f69c03f05f88b178eb08daccce345536c05089929ec08e21edbc7da367`.
The result references that decision record as `metric_declaration_sha256`; its
separate source-manifest binding identifies the actual input pack.

For each candidate window, calculate source MIDI minus query MIDI on **jointly
voiced frames only**, sum in float64 and divide by joint count. Clip that mean
to [-12,+12] semitones. The reported `source_minus_query_semitones` is added to
query MIDI to align it to source. This deterministic nuisance alignment is not
supervised fitting. For a query shifted up three semitones relative to source,
the matching offset is approximately minus three.

After clipping, directly sum nonnegative per-frame costs: squared
`sourceMIDI-queryMIDI-offset` for joint voicing, 144 for voiced/unvoiced mismatch,
and zero for joint silence. Divide the float64 sum by **all query frames**. Do
not use cancellation-based variance arithmetic, FFT, learned normalization or a
parameter sweep. Offsets beyond one octave leave residual error; input f0 is
never clipped or changed to make a query fit.

All original support rules remain: query voiced fraction at least 25%, candidate
joint count at least 75% of query voiced count, evaluated with integer comparisons.
Source clocks are absolute `i*256/44100`, query clocks relative to their finite
nonnegative origin, within five microseconds. The original finite 0–20,000 Hz
contract, explicit zero/unvoiced handling and separate-log MIDI conversion remain.
There is no resampling, interpolation, per-frame octave correction or tempo change.

Rank by ties-to-even nearest integer `1e-8` semitone-squared ticks. Within a track,
the earliest equal-tick window wins; global order is ticks, native ID, frame.
**Offset and unrounded distance do not break ties.** The result retains the raw
cost, offset, voicing support, frame range and first/last observed source sample
times. The new result revision is `medley-bounded-transposition-search-v1`, with
original source/input pins, semantic query hash and separate scorer/CLI/runtime
pins. List and ndarray requests have identical semantic hashes; neither is
mutated. Unsupported queries and unavailable source nominations remain explicit.

## Existing source custody and standalone query

Reuse the original externally pinned local source pack. Its frozen usable pool
has 18 annotations and 473,373 frames among 24 nominees; three were absent from
the official directory and three exceeded the per-file cap before capture.
These are not 24 attempted downloads or three HTTP 404 observations. The source
commit, roster, pre-coordinate selection and byte/Git-blob custody remain exactly
those recorded by the original recipe. The MedleyDB
[author notice](https://medleydb.weebly.com/downloads.html) and
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) apply to data
and annotations, independently of MIT implementation code. Attribution: Rachel
Bittner, Justin Salamon, Mike Tierney, Matthias Mauch, Chris Cannam and Juan P.
Bello; MedleyDB 2014/2016.

```sh
PYTHONPATH=src .venv/bin/poe sync
PYTHONPATH=src .venv/bin/python scripts/query_transposed_melody_contour.py \
  --source /LOCAL/existing-source-pack --source-sha256 SOURCE_MANIFEST_SHA256 \
  --query /LOCAL/new-caller-contour.json --query-sha256 QUERY_FILE_SHA256 \
  --limit 24 --output /LOCAL/fresh-offset-result.json
PYTHONPATH=src .venv/bin/python -m unittest tests.test_transposed_melody
PYTHONPATH=src .venv/bin/poe check
```

The query JSON contains exactly `times_seconds` and `f0_hz`. Python callers use
`medley_melody.load_source(path, pin)` then
`transposed_melody.search_contour(source, request, limit=24)`. The new module
checks the original loader and CLI hashes; it neither alters their contracts
nor silently repins an incompatible source pack. Missing approved input custody
is a blocked query, not permission to substitute source data or retry a denied
route. `/LOCAL` paths are examples, not checked-in data or a promise of future
container availability. Original source rebuilding, when legitimately needed,
belongs to its unchanged recipe and truthful source receipts.

The CLI requires externally pinned query bytes and the original closed source
inventory. It enforces 120-second CPU/wall bounds, 1 GB address space, one-thread
numeric settings, a 1 MB query/result JSON cap and up to 24 returned tracks.
Source limits remain 24 nominations, 2 MB/file, 25 MB raw, 100,000 frames/track and
1.8 million total frames; queries have 173–1,723 frames. Direct computation uses
128-window chunks without materializing a full source-by-query cost matrix.
Fresh local output is atomic and cannot replace an existing result; source/query
overlap is rejected. Without `--output`, local research JSON goes to stdout.
Keep either form under the same NC research handling; no public serving route or
default changes.

## Engineering evidence and limits

Nine generated synthetic tests cover shifts [-13,-12,-3,0,3,12,13], scalar
positive-cost/offset arithmetic, clipped signs, exact voicing boundaries,
all-frame denominator, ambiguous constant contours, offset-independent ties,
an earlier tiny positive cost tied with later exact zero, strict schemas,
ndarray parity/no mutation, new caller values, tiny positive/upper-bound f0,
physical pins, fresh CLI output and byte-identical original behavior.

The new standalone CLI reused the existing explicitly synthetic maximum-cap
pack without rebuilding it: 18 generated constant contours of 100,000 frames
(1.8 million total), 24 nomination outcomes and a 1,723-frame query. It completed
with exit zero in 16.480 seconds wall / 16.468 seconds CPU and 101,228 KiB peak
RSS, measured per child with Linux `wait4`, inside the unchanged 120-second/1 GB
limits. Existing source/query pins stayed unchanged. This resource guard is not
a speedup comparison with a different historical absolute-pitch run.

For the retained validation, all 18 existing fixed 862-frame center queries have
three declared transformations [-3,0,+3]. Timestamps stay unchanged; zero f0 stays
zero and positive f0 is multiplied by `2**(shift/12)`. All 54 transformed queries
satisfy the original f0 bounds; no replacement, interpolation or clipping is
allowed. This source-fragment exercise checks function only, not independent
humming robustness or musical quality. Longer tracks offer more candidate
windows and therefore more chances for a low minimum; that bias is unchanged.

An independent oracle was sealed before implementation query outcomes. It uses
no project scorer imports, streams frame contributions across candidate starts,
then checks every roundoff-near-minimum with scalar positive costs and `math.fsum`.
Nine fixed transformed queries against 18 sources define 162 track outcomes.
The development comparison matched all 162 native frame/tick/support/order
outcomes exactly, with offsets and raw costs within the predeclared tolerances
(absolute 1e-10 for offsets; absolute 1e-10 / relative 1e-12 for costs).
That comparison preceded the final commit; final-head/all-54/original-18/default
CLI replay and CI are tracked by the source pull request. Local real results are
not embedded here. `results.json` records aggregate evidence and physical pins.
The stopped style study, reserved style fold and all denied-source boundaries
remain unchanged.

The final `poe check` exited zero: 2,463 Python tests in 308.142 seconds
(36 skipped), and 122 Node tests passed (44 skipped, zero failures). Formatting,
lint and type checks passed. The durable exit receipt and full-log hash are
recorded in `results.json`.
