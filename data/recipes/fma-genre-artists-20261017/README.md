# Native genre–artist recording evidence

Genre pages now lead to a complete directory of artists on their tagged source
recordings. Each row opens the exact intersection of that native artist ID and
the selected direct track genre. This closes the reverse-navigation gap between
source genres, artists and recordings; it does not classify artists by genre.

The retained 2017 FMA metadata contains 47,341 genre–artist pairs and 260,586
recording memberships. Of these, 661 pairs and 2,075 memberships reference
missing artist records. Track-supplied display names retain their missing-record
flags. Native IDs remain separate even when names coincide. No parent genre is
inherited, and duplicate annotations on a recording count once.

Directories contain 100 artist groups per page, ordered by direct recording
count descending and native ID ascending. This ordering is source support, not
artist importance or musical relevance. The largest directory has 5,156 groups.
The largest artist–genre intersection contains 771 recordings; 51 intersections
require more than one 200-recording page.

Intersection navigation reuses existing artist track IDs and track annotation
shards. It loads bounded batches, verifies the complete intersection against the
saved direct count, then paginates it. Failed or obsolete loads cannot display a
partial cohort. No duplicated per-pair track corpus is exported: independent
measurement found that such an approach would add at least 4,882,564 JSON bytes
before inventory overhead and exceed the available export budget.

## Retained inputs and limits

- Source receipt: `cd46d53488e6892eed78b742814ef95e6531b18b6d69c8eb95688da075e6df99`.
- Corpus receipt: `088588f58ca80662f47e809d054de88eb320b402f110d6637d318f00edbff1ed`.
- Source metadata: CC BY 4.0 with existing attribution. No audio, new acquisition,
  contacts, biographies, lyrics, or identity reconciliation is added.
- Existing limits remain 200,000 bytes per JSON shard, 40,000,000 bytes per
  export and the separate 2 MB artist-index limit. The actual offline build uses
  the same 120-second CPU/wall and 1 GiB address-space wrapper as prior exports.

The separately verified existing descriptor map can be attached to the combined
catalog. Its source and metadata receipts match this reconstruction. Strict
numerical replay preserves every coordinate and sensitivity result; no new
model is fitted or selected. It positions 16,109 of 16,916 source-known artists
and 158 of 164 genres. The remaining 807 artists and six genres retain missing
positions; 250 IDs lacking source artist records remain outside map scope.
Artist means summarize available associated descriptors, while axes and genre
centroids use the frozen original-training inputs. These coordinates do not
establish musical similarity or Every Noise parity.

## Reproduce

After `poe sync`, use a fresh output directory and the existing offline builder:

```sh
PYTHONPATH=src .venv/bin/python scripts/build_fma_static_catalog.py \
  --source /workspace/opennoise-rebuild-20261013/metadata-source \
  --projected /workspace/opennoise-rebuild-20261013/metadata \
  --descriptor-map /workspace/fma-descriptor-restore-20261015/map \
  --output /workspace/new-genre-artist-catalog
```

Use the existing guarded wrapper for bounded execution. The builder verifies
retained native compressed-member hashes, full member CRCs and projected rows;
this is not verification of a complete downloaded ZIP archive. Preserve prior
captures, declarations and outputs. The new catalog is local-only and does not
authorize public deployment.

Independent expected pairs and source bindings are retained under
`/workspace/opennoise-genre-artists-independent-20261017`. Map replay and scope
evidence are under `/workspace/opennoise-genre-artists-map-review-20261017`.
The data remains historical and incompletely annotated: 2,609 tracks have no
genre annotations, and missing tags are not verified negative memberships.

## Actual combined export

The guarded build completed in 14.136 seconds with 371,781,632 peak RSS bytes.
The receipt accounts for 37,650,707 bytes and 7,559 inventory entries. The
largest bounded JSON shard remains 199,999 bytes. The new directory occupies
490,325 bytes across 570 pages; the existing frozen map adds 1,075,332 bytes
across 13 files.

Independent replay matched all 47,341 directory pairs and 260,586 exact
profile/recording intersections. All 6,961 prior JSON data files remain
byte-identical. The closed inventory, every file hash, native IDs, annotation
counts and source receipt bindings passed verification.

- Static receipt SHA256: `2758985e901d9c4ad2a8427b521bf0882e93d9b699e655a3f96d04940b9563b7`.
- Files manifest SHA256: `2151f7c8c7057aa19a4009952998aa48a841fcb33f10838a251b156d5cd3da7e`.
- Frozen map receipt SHA256: `27eae07b440cb228aed0b16d6889a036f3120ba14d2eaea6ec999f3f5fec3a68`.

The actual build, resource measurements and subsequent browser/check evidence
are retained under `/workspace/opennoise-genre-artists-run-20261017`. The
integrated descriptor-map view is distinct from the older standalone sonic-map
page; the latter's browser contract expects a root `coordinates.json` and is
not applicable to this integrated export.
