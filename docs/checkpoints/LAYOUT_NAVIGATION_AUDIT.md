# Layout navigation audit

This checkpoint records a read only audit of the current static semantic atlas.
It does not approve a new layout.

## Baseline

The audited artifact is the v2 atlas at
`.cache/semantic-map-layout-v2/artifact.json`. The published browser asset is
`dist/assets/semantic-atlas.18346e3e05f40c2dd045fd41dff847f4f096ada33d7f8d097ec13d2151620366.json`.
The artifact output hash is
`e98c0c0dbac43f4f8726686f67713caae44b693a669475d1afebd7524889c00a`.

The atlas has 2,945 placed nodes, 3,346 unplaced nodes, and 34,937 structural
edges. It has no exact coordinate collisions. The initial browser view at 1440
by 900 shows 23 points and 23 labels, with no edges. Its occupied width is
87.96 percent of the view and its occupied height is 70.68 percent.

The existing browser report at `artifacts/semantic-map/browser.json` has all
boolean checks set to true. It covers pan, equivalent zoom paths, fixed center
zoom, deep label selection, structural focus, artist discovery, dark mode, and
mobile pinch. The measured renderer p95 is 3.3 milliseconds.

## Labels that need extreme zoom

The browser cap is finite at scale `1,117,555,286,766.867`. Every label is
admitted by that cap, but this does not mean that a person can reach each label
with ordinary zoom steps.

The label atlas has these reveal scale counts.

- 117 labels require a scale above `1e6`.
- 54 labels require a scale above `1e7`.
- 40 labels require a scale above `1e9`.
- 21 labels require a scale above `1e10`.
- 9 labels require a scale above `1e11`.
- 1 label requires a scale above `1e12`.

The most delayed label is `norwegian hip hop`, with a reveal scale of
`1,064,338,368,349.397`. The current selected label route can reach it because
the detail view centers the world coordinate and jumps to the finite cap. The
ordinary overview and repeated plus control do not show that route to a user.
This is the current human reachability gap.

## Coordinate pileups

The atlas has no exact collisions after its deterministic separation step. Near
coincidence remains common. I measured Euclidean distance between placed node
coordinates in the normalized world space.

- 83 nodes have a nearest neighbor at or below `1e-5`, in 27 connected groups.
- 262 nodes have a nearest neighbor at or below `1e-4`, in 79 connected groups.
- 1,620 nodes belong to groups connected at or below `1e-3`, in 273 groups.
- The largest group at the `1e-3` threshold has 780 nodes.

These measurements describe the published coordinates. They do not claim that
the source evidence contains duplicate records. They show that a layout can
pass exact collision checks while still requiring very large zoom to separate
many labels.

## Offline candidate gate

The next layout experiment can use the existing sealed evidence graph and a
deterministic, offline builder. The candidate may borrow the useful Hackerverse
selection idea described in `docs/serving/VISUALIZATION_RESEARCH.md`: each
zoom tier should retain earlier landmarks and admit candidates in a round robin
over occupied spatial cells. The candidate must not copy the Hackerverse
embedding or terrain process.

The candidate gate should run against the same fixed node and edge inputs.
It should record the builder revision, settings, input hash, output hash, and
the following checks.

1. Every public node has one stable coordinate or an explicit unplaced reason.
2. No exact coordinate collisions remain, and the count of nodes in groups at
   or below `1e-4` is lower than the current 262 node baseline.
3. Every zoom tier retains its previous landmarks. A later tier may add nodes,
   but it may not remove an admitted landmark from the same camera path.
4. A fixed 1440 by 900 overview shows between 1 and 50 points and between 1
   and 35 labels, with no edges and at least 75 percent width occupancy and 70
   percent height occupancy.
5. A fixed center path using the existing plus control records label admission
   and exit at each step. Each label exit must have a visible point exit at the
   same or an earlier step, or the gate fails.
6. The gate tests the deepest ten reveal scales and a fixed sample of the ten
   densest coordinate groups. Each selected label must be reachable by the
   ordinary zoom path at a scale no greater than `1e6`, or the candidate must
   provide a visible search or focus route and record that route in the report.
7. The focused view keeps the selected node and its structural neighbors in
   view, has no unrelated point leakage, and keeps label boxes inside the
   viewport without overlap.
8. The candidate passes the current desktop and mobile browser checks, including
   one pixel pan anchoring, equivalent zoom paths, dark mode, Back behavior, and
   mobile pinch.

These checks are evaluation rules for a future experiment. They do not select
the candidate for publication. A layout can replace the current atlas only
after its report, screenshots, and source hash pass review.

## Current decision

The current atlas remains the published layout for this audit. The measured
extreme reveal scales and near coordinate groups are open layout debt. No new
layout was built, selected, or approved by this checkpoint.
