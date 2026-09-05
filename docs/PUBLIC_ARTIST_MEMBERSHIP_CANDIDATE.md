# Public artist membership candidate

`musix.public_artist_membership` produces a bounded, non-serving candidate for
artist-to-genre evidence across all 6,291 retained names. Production callers
use `build_public_artist_membership_candidate_from_seed_artifact()`, which
loads the name universe with `load_name_universe()` and delegates to the
existing name-only seed parser. It reads only source ID/hash plus each name and
opaque identifier.
Coordinates, representatives, recordings, audio, artist assignments, rankings,
and neighbours are not accepted as construction inputs.

The artifact has three disjoint states.

- `directly_observed_memberships` are positive direct source claims. Each path
  retains one or more typed `musicbrainz_tag` or `wikidata_p136` evidence
  facets, so a union of sources merges without losing provenance. They are
  observations, not an inferred serving-model claim.
- `propagated_candidates` are exactly one-hop paths. Every path contains both a
  direct source/facet anchor and a privacy-safe aggregate co-listen facet;
  a co-listen edge by itself cannot create an artist-to-genre entry.
- `dispositions` has one ordered result for every retained name. It records
  direct evidence, an aggregate-only candidate, or an explicit abstention.

Only unique exact-normalized public genre identities are usable. Multiple
public identities for one retained name, or multiple retained names that
normalize to one public identity, are `ambiguous_public_genre_identity` and
produce no entries. There is no last-writer-wins mapping.

## Source and custody boundary

`ApprovedPublicMembershipInput` binds the normalized immutable public-model
rows to a SHA-256, declared row counts, a row-export-policy SHA-256, and the
exact certified SQLite database bytes. All artifacts must be exportable. The
certified release uses CC0/export-allowed Wikidata P136; MusicBrainz tags stay
policy-bound and are excluded when their source policy is not exportable.
Aggregate ListenBrainz
rows are rejected unless both row-level export and policy-level public/export
permission are explicit. The default policy disables aggregate candidates.

The source policy fixes maximum hops at one, bounds examined paths and per-genre
candidates, and fixes all historical artist-membership, external-gold, and
audio construction flags to `false`.

`write_public_artist_membership_candidate()` verifies the logical output hash
before writing canonical JSON, then stores the exact bytes at
`public-artist-membership-candidates/sha256/<logical-output-hash>.json`. The
receipt carries both logical and file SHA-256 values. Publication and promotion
also recompute the logical hash, so a parsed/tampered artifact cannot proceed.

Build through the executable path after an operator has prepared the approved
row file and policy documents:

```sh
uv run poe build-public-artist-membership-candidate
```

The task reads the sealed name artifact and an approved public-input JSON. The
input JSON includes `input_file_sha256`, the SHA-256 of the exact certified
SQLite database bytes. The adapter receipt repeats that hash and binds each
selected row to its provenance policy, snapshot, and artifact. It writes candidate JSON, an object-store receipt,
and a promotion report on every successful build. Supply `--independent-gold`
only when an independently sourced public gold document is available; add
`--require-promotion` only when a non-eligible report should fail the command.
The builder also requires the adapter receipt, adapter policy, and certified
database path. It re-hashes the database and checks the receipt's database,
normalized-row, export-policy, selector-policy, and row-count hashes before
construction. It replays the adapter and compares the derived approved input
and receipt, so an approved JSON wrapper or self-consistent forged receipt
alone is not accepted.

## Promotion gate

Candidates are not quality-qualified by construction. Calling
`evaluate_public_artist_membership_promotion()` without an
`IndependentPublicGoldSet` always returns `promotion_eligible=false` and the
quality claim `not_evaluated_without_independent_public_gold`.

Gold must declare an independently sourced public record set, explicitly
exclude MusicBrainz tag, ListenBrainz aggregate, and historical artist
membership inputs, be sorted by `(artist_id, genre_id)`, and bind its canonical
label bytes with SHA-256. Metrics compare candidate pairs against labeled
candidates for precision and against every positive gold label for recall.
Unlabeled candidate pairs are reported but are not silently treated as
negatives; true-negative/specificity quality is not claimed.
