# Public genre-seed taxonomy anchors

This artifact expands the 6,291 legacy genre *name* seeds using only a
CC0/public-domain catalog snapshot and public taxonomy edges. It reads the
same intentionally name-only H2 projection as the seed-universe bridge. H2/H3
coordinates, artist assignments, and neighbor lists are not construction inputs.
The local CC-BY-NC-SA MusicBrainz research graph is also excluded.

Unique exact public names and aliases remain the only canonical memberships.
For a non-exact seed such as `canadian rock`, a unique exact suffix head such
as `rock music` becomes an `anchored_compositional` review anchor. Its modifier,
anchor identity, and bounded observed public ancestors are explicit. This is a
navigation and review hypothesis: it never creates a genre identity, an artist
membership, or a public graph edge.

If several exact identities share a name, or several unique suffix anchors
disagree, the artifact abstains and records the reason. The coverage report
therefore distinguishes canonical membership coverage from broader
review-anchor coverage and fixes inferred membership count at zero.

Confidence is a structural review priority, not a membership probability. It is
calibrated only against exact legacy names whose exact public target has a
bounded observed public taxonomy path to its own unique suffix head. When the
sample is too small, the report says so and uses a neutral calibration component.
Every catalog source license must start with `CC0-1.0`; any other catalog fails
closed.

```sh
uv run poe build-genre-seed-public-taxonomy
```
