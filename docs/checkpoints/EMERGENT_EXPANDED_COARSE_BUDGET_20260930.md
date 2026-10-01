# Adaptive coarse safety-budget construction experiment

The full bulk fit exhausted its 128-node coarse safety budget before 54 broad
groups met the declared construction gates. Those groups contained 98,277 core
artists. This separately declared experiment raises only that stopping budget
to 1,024 inside one research subprocess. It asks whether the existing gates can
resolve that structural limit; 1,024 is not a target community count.

The run uses exactly the frozen primary-v4 source, feature SHA-256
`2b6179b4c969588f1268c9837b410c9da7b16d54c094850eb13ba00514b6f252`,
with the same feature policies, lexical weights, fine split gains, twenty-artist
minimum support, identical-profile grouping, ancestry, and membership gates.
No names, historical memberships, coordinates, or audio enter fitting. No new
method selection follows predictive evaluation. The budget was prescribed from
the default fit's structural stopping failure, before its paired scores arrived.

## Isolation and artifact identity

The research runner is
`.cache/emergent-topics/build_adaptive_bulk_expanded.py`. It imports the unchanged
adaptive module, checks its default is 128, then changes only the process-local
`MAXIMUM_BROAD_COMMUNITIES` to 1,024. The module's on-disk default remains 128.
A fresh-process boundary test verifies this isolation and that forty artists
with one identical musical profile still produce one broad community, rather
than a forced count. Its receipt is
`.cache/emergent-topics/expanded-cap-boundary-test-v1.json`, identity
`c2b086c275aedde85ec051db723b896c40ea5cbf68cdd67df34575d7f6d93e5b`.

The completed artifact directory is
`.cache/emergent-topics/adaptive-lexical-bulk-expanded-20260930-v1`.
Model identity:
`601d5a2bd0855441fdd5b9e01367ef6768abefb379c75bf9342f020419f622e2`.
Report bytes SHA-256:
`bbd7b7233ad9e7da303dccf108705e7d5b223de95ae0102c4d588f8aee3a4400`.
The revision is `emergent-adaptive-lexical-coarse-topics-expanded-budget-v1`.
Its receipt records `runtime_overrides`, the original module hashes, the source
receipt, zero native membership additions, and
`predictive_evaluation_for_this_variant: not_run_construction_only_experiment`.
All seven output bindings were reverified after fitting. All four shared model
source hashes remain unchanged, and a new import still reads a 128-node default.

The maintained CLI now exposes this same isolated preset. To reproduce the
construction experiment in a **new** local directory, run from the repository
root:

```sh
.venv/bin/python scripts/build_emergent_adaptive_topics.py \
  --features .cache/microgenre-features-primary-v4/artist-features.jsonl \
  --output .cache/emergent-topics/adaptive-lexical-bulk-expanded-cli-reproduction \
  --expanded-coarse-budget
```

Omit `--expanded-coarse-budget` to retain the 128 default. The preset changes
only the coarse safety budget during fitting, restores it even after a failure,
and retains local-cache destination and overwrite protection. Its report binds
the CLI builder, all four algorithm modules, input features, and the adjacent
source receipt when present. Expanded outputs carry the variant revision and
explicit runtime override, with no inherited predictive score or authorization
to publish. The forty-artist identical-profile subprocess test produces one
natural group under both budgets, checks identical assignments, and verifies
that a fresh process still imports 128 and that source files remain unchanged.

The original cache-runner artifacts above are immutable. This maintained CLI
has a different builder hash and additional provenance metadata, so a future
reproduction has a new report identity even if statistical outputs agree. It
must not overwrite or impersonate the original cache-runner receipt.

## Construction comparison on identical source features

| Measure | Default 128 safety budget | Expanded 1,024 safety budget |
| --- | ---: | ---: |
| Actual broad / sub / micro nodes | 128 / 157 / 1,048 | 237 / 26 / 1,020 |
| Artists assigned broad | 198,409 | 198,409 |
| Artists assigned sub | 86,453 | 41,122 |
| Artists assigned micro | 98,531 | 100,365 |
| Broad nodes meeting construction gates | 74 | 218 |
| Unsupported broad nodes | 54 | 19 |
| Unsupported broad core artists | 98,277 | 6,134 |
| Unsupported broad overlapping membership occurrences | 183,672 | 15,023 |
| Source-core cosine, broad / sub / micro | 0.598 / 0.737 / 0.791 | 0.638 / 0.746 / 0.819 |

The expanded fit stops at 237 broad nodes, well below its safety budget. Every
remaining coarse leaf either meets the construction gates or lacks a supported
split. All nineteen unsupported groups retain
`abstained_no_supported_coarse_split`; none reports budget exhaustion. The
largest is classical / orchestra / symphony orchestra, with 3,645 core artists.
Construction cosine is an in-sample source diagnostic, not musical relevance.

Promoting smaller source-supported groups into the coarse frontier can remove
their former fine-level labels. The sub frontier still has its unchanged
256-node safety budget; after 237 coarse roots, only a limited number of extra
splits fit beneath it. Levels can legitimately be skipped, and terminal groups
are not duplicated to fabricate a three-level hierarchy.

## Benchmark and descriptor limitations

All ten benchmark identities remain covered. Seven have a micro membership.
Aphex Twin and Boards of Canada now have terminal broad-only warp / idm /
moogsploitation memberships; Jon Hopkins has a terminal broad-only chillout /
ambient / idm membership. Four Tet has broad and micro memberships, including
breaks / breakbeat / electronica and house-related candidates, but no sub
membership. These are regressions in named-level navigation relative to the
default fit, despite the better coarse gate coverage. Names were joined after
fitting and did not determine any split or descriptor.

The default bulk fit remains the selected input for the next community
explorer. This expanded variant is a separate construction experiment, with an
optional separate view; it does not silently replace the selected hierarchy.
Its 237 naturally stopped coarse groups demonstrate the same-source budget
boundary, not a predictive model-selection victory. Terminal broad candidates
must not be presented as fabricated sub or micro memberships to hide the three
benchmark regressions.

The post-fit audit is
`.cache/emergent-topics/bulk-expanded-construction-audit-20260930-v1.json`, identity
`57497d88674afde7310647f28b57da6b4d3d666587c424c60b2f4cf3b8851bfd`.
The known metadata filter matches zero published descriptor occurrences, but
the broader review queue still contains 39 role/ensemble occurrences across
30 values and four publisher-like occurrences. An unsupported dance-pop group
even includes hong kong actor in its derived label. These queues are review
evidence, not a claim that source tags are uniformly musical or a post-hoc
training filter. No data correction or further refit follows this inspection.

The independent source-increment evaluation applies to the default 128-budget
method only. The expanded variant has no predictive evaluation and cannot
inherit those scores. Neither fit establishes Every Noise taxonomy, artist
placement, listening relevance, or 100% parity. Both remain local research
candidates; all prior artifacts and evaluation receipts are retained.
