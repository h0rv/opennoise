# Cold label alignment

This checkpoint turns immutable target names into conservative links to open
genre/tag labels. It is a vocabulary bridge, not a membership, peer, layout,
or taxonomy model. It never promotes an identity or creates an artist edge.

## Construction boundary

The projected run reads three sealed inputs: the evidence-graph database and
receipt, plus the complete seed reconciliation artifact. Target-side matching
uses only each immutable seed name. Reconciliation's already-known open
identities are emitted as `existing_open_identity` for accounting, never as
incremental lift. The sealed artifact also carries every reconciliation seed
row and checks each output row against that partition and its stable identity
hash, so a rehashed row swap cannot cross the boundary.

The matcher permits only:

- unique Unicode/token-normalized exact labels;
- same-head, token-overlap compositional candidates for review; and
- a unique seed-side initialism to a unique compact open label, also review.

It does not use edit distance, coordinates, historical memberships, historical
peers, or Every Noise taxonomy. `music`, `popular music`, and other generic
roots abstain. Duplicate normalized target names abstain instead of silently
collapsing onto one open cluster. Review records retain every score and signal;
they are not graph edges.

The deterministic masked evaluation hides a stable 20% split of trusted open
reconciliation identities, then reruns the same cold matcher. Held-out edges
are evaluation truth only. The acronym precision field is separate; `null`
means the masked split happened to contain no safe acronym prediction.

## Measured projected baseline

The sealed projected-only artifact is
`063d9b4b94d8800e1170579ba5e1db49200090146d9f8ab18d6eec93094614af` in
the shared `.cache/cold-label-alignment-v1/sha256/` custody root. It binds the
3,057,729,536-byte evidence graph, its 2,736-byte receipt, and the
3,509,380-byte reconciliation artifact.

It accounts for all 6,291 seeds without collapsing reconciliation states:

| State | Seeds |
| --- | ---: |
| reconciled | 359 |
| public only | 82 |
| MusicBrainz only | 704 |
| review only | 2,037 |
| ambiguous | 37 |
| unresolved | 3,072 |

The graph-projected vocabulary contains 2,261 identities in 1,222 normalized
label clusters. The result has 1,072 existing open-identity accepts, **73
net-new exact-normalized accepts**, 172 review seeds, and 4,974 abstentions.
Review breakdown is 133 compositional, 2 acronym, and 37 pre-existing
ambiguous identity groups.
The deterministic mask contains 240 of 1,145 eligible trusted mappings: top-1
and top-k recall are 0.9417, with 226 accepted predictions at 1.0 precision.
No acronym prediction occurred in that held-out split, so acronym precision is
not estimated.

## Bounded supplemental vocabulary

`uv run poe build-release-group-label-vocabulary` performs an explicitly
bounded streaming scan of the canonically custodied MusicBrainz release-group
archive. It validates the source-cache admission receipt and archive bytes,
reads only top-level release-group `genres` and `tags`, and stores only
distinct labels plus bounded per-kind observation counts. It never stores raw
release rows, artist aliases, or nested artist metadata.

The current supplemental sidecar is deliberately **partial**:

- archive: `6f153846…d7a43`, admitted by
  `.cache/musicbrainz-release-group-source-receipt.json`;
- exactly 200,000 rows, not the 18.1 GB member in full;
- 6,228 normalized labels / 7,229 source-kind references;
- 42.868 seconds and 102,192 KiB peak RSS;
- sidecar logical hash:
  `2fb784684c3e32180f19c126cc68c1cdbf7f994e86011ce7198bfa0a61d3e3f1`.

It must not be described as the full MusicBrainz vocabulary. The task accepts
an explicit larger bound for a later measured run.

Partial supplemental vocabulary is now an explicit experimental mode. The
alignment builder defaults to `complete_only` selection and rejects a sidecar
whose `completed_source_member` is false. The CLI requires
`--allow-partial-supplemental-vocabulary` to replay this 200,000-row prefix.

When that sidecar is supplied to the alignment task, the receipt-bound artifact
`c72436db6bca581de16cd8b3e25def3d9865bda062c0d5ec9e63e98dec06ae01`
binds the exact 701,718-byte sidecar and its 388-byte receipt. It reports
2,261 projected + 7,229 supplemental identities, 240 net-new exact accepts,
786 review seeds, and 4,193 abstentions. The 167 extra accepts over the
projected baseline are a partial-vocabulary lift, not a claim of a complete
corpus scan. Its masked accepted precision is 0.9956 (227 predictions); no
masked acronym example occurred, so acronym precision remains unestimated.

Observed exact candidates span cultures and eras, including `forró`/`forro`,
`qawwali`, `mpb`, `maloya`, `ethio-jazz`, `danzón`/`danzon`, and `j-rock`.
Compositional candidates such as `thai indie pop → indie pop` and `russian
post-punk → post punk` remain review-only. Generic-root and acronym-collision
negatives are enforced by unit tests; no unsafe acronym is accepted.

The terminal historical diagnostic is separately sealed as
`90d5f09cbfe1c6224d1ed9d94bd54e60f9f759c0c3d66e3dd0dcbaf23e373ff0`.
It runs only after alignment sealing and accesses only historical membership
counts and peer endpoints: accepted 1,312/1,303 membership-positive/peer
endpoint seeds, review 786/773, abstentions 4,191/4,067. It does not access
coordinates, communities, labels, or use history in construction.

`item1` is the single immutable `pop` seed. Its reconciliation is ambiguous:
exact MusicBrainz `pop` plus Wikidata `pop music` and `popular music`. The
artifact keeps all three open identity clusters as `ambiguous_existing_identity`
review candidates. It does not choose a Wikidata alias or create a hierarchy
edge from that ambiguity.

## Complete release-group vocabulary checkpoint

The complete archive-member scan is sealed separately from the old prefix so
the earlier sample remains reproducible. It binds the same admitted archive
(`6f153846\u2026d7a43`) and exhausted its release-group member:

| Measure | Partial 200k prefix | Complete member |
| --- | ---: | ---: |
| release-group records | 200,000 | 4,499,326 |
| normalized labels | 6,228 | 37,090 |
| elapsed time | 42.868 s | 843.916 s |
| peak RSS | 102,192 KiB | 166,900 KiB |
| `completed_source_member` | false | true |

The complete vocabulary logical hash is
`20773899d2b817464b3fcda405c744917e5a2f9366010bab9cecdf733db94fbd`; its
artifact-byte hash is
`a52655d402303ecb607d6eccc77a3244a4a0c2fb9d8ed08f12c47a1e3c918f3d`.

The corresponding alignment is in the new
`.cache/cold-label-alignment-v1-full-vocabulary-20260920/` custody root. Its
logical hash is
`b7482d6e3a9805bf62b484df4ce65b05480761a7661b7ffbf19491ce167f32b9`, and
its artifact-byte hash is
`cdc5040bb8b78a232e876c058f26375221a99916aaf763057087e6949e03f9ce`.
It binds the graph database and receipt, full reconciliation, complete
vocabulary artifact, and vocabulary receipt by both byte and logical hashes.

| Alignment measure | Partial prefix | Complete vocabulary | Delta |
| --- | ---: | ---: | ---: |
| open identities | 9,490 | 41,037 | +31,547 |
| accepted seed mappings | 1,312 | 2,032 | +720 |
| net-new exact-normalized accepts | 240 | 960 | +720 |
| review seeds | 786 | 834 | +48 |
| abstentions | 4,193 | 3,425 | -768 |

The complete run has 906 compositional review rows, 37 acronym review rows,
and 88 ambiguous-existing-identity rows; its remaining abstentions are 2,560
weak/ambiguous compositions and 865 labels with no open candidate. The masked
evaluation keeps the same 240 held-out trusted mappings and 0.9417 top-1/top-k
recall. Its accepted precision is **98.26%** (230 predictions), down from the
partial prefix's 99.56% (227 predictions). This is a measured tradeoff, not a
promotion gate: the sidecar remains a vocabulary bridge, creates no artist
memberships, promotes no identities, and reads no historical input.

## Run

```sh
uv run poe build-cold-label-alignment
uv run poe build-release-group-label-vocabulary
uv run poe build-cold-label-alignment \
  --supplemental-vocabulary .cache/release-group-label-vocabulary-v1/sha256/<hash>.json \
  --supplemental-vocabulary-receipt .cache/release-group-label-vocabulary-v1/sha256/<hash>.receipt.json
uv run poe audit-cold-label-alignment-historical \
  .cache/cold-label-alignment-v1/sha256/<alignment-hash>.json
```

The artifact and receipt live under a shared main-checkout content-addressed
cache even when the task is called from a linked worktree. Re-running identical
inputs and settings reuses the same logical object hash.
