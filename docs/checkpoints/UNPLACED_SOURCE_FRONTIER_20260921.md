# Unplaced genre source frontier

The current map has 2,945 placed names and 3,346 unplaced names. Every
unplaced row says `no_supported_structural_relation`. More spacing or a
different drawing library will not place these names because the layout has
no accepted edge for them.

I compared the unplaced IDs in the v3 layout with two existing, separate
review artifacts. The genre hierarchy candidate artifact has 492 unplaced
names with at least one review edge and no unplaced name with an accepted
edge. The open label graph has 219 unplaced names with a proposed label.
The two groups do not overlap. The remaining 2,635 unplaced names have no
proposal in either artifact.

| State among 3,346 unplaced names | Count | Meaning |
| --- | ---: | --- |
| Hierarchy review edge | 492 | A proposed relation still needs a music-domain decision. |
| Open label proposal | 219 | A proposed name match is not a structural edge or artist membership. |
| Neither proposal | 2,635 | These artifacts provide no path toward a supported placement. |

The comparison used the complete seed partition in
`.cache/semantic-map-layout-v3/artifact.json`, whose logical hash is
`469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38`.
The hierarchy receipt binds logical hash
`fc224da42842cdd0a4a9b5628d015cf83d60266b609857dcdff96abe01f7f02a`.
The open label graph logical hash is
`5ab075325adeed7a778820389d41a7de3b14199abfbeb3064b20cc433e7fc6a8`.
The counts come from exact seed IDs, not name matching.

The 484 generated genre candidates in the separate review queue cannot, on
their own, solve the map coverage gap. The open label graph yields those
candidates for 358 distinct names, but only 219 of those names are unplaced.
Even a reviewed name match would still need a justified graph relation before
it could supply a map coordinate.

The next coverage step must add open artist, release, tag, or taxonomy evidence
for the names without proposals. Keep source claims and generated suggestions
separate. Measure new accepted structural edges and newly placed names against
this exact frontier, rather than reporting more candidate rows as map coverage.
