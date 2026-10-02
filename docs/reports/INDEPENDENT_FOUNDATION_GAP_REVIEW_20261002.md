# Independent foundation gap review, 2026-10-02

This review distinguishes the retained research export, a clean checkout and the
new portable core-only recovery product. It does not certify Every Noise parity.
Scope: `docs/IDEA.md`, foundation goal/inventory, design, parity and 2026-10-01
checkpoints; source-role boundaries in the direct-custody/discovery builders;
portable credit examples; retained native credit source captures; official core
artist source licensing.

## Priorities

1. **Keep the release boundaries intact.** The retained v7 research product at
   `/workspace/opennoise/.cache/opennoise-discovery-minimal-20261001-v7/` has
   198,409 artists, but its receipt declares both `public_export_authorized` and
   `serving_authorized` false, and binds CC-BY-NC-SA tag obligations. Its successful
   navigation and browser certificates do not authorize public promotion. Open
   code does not make the tag-derived corpus unrestricted.
2. **Report recovery custody accurately.** `data/public.sqlite` and the canonical
   layout-v3 artifact are absent in the retained root checkout. The historical
   snapshot was recovered; it is an evaluation reference. Recovery does not
   establish custody of the separately described 62-object CC0 source vault.
   A bounded portable core-only product is a new output, not the restored sealed
   canonical database or a certified replacement for it.
3. **Verify native facts where feasible.** The original portable work verifier
   checked local projection hashes, safe URLs and internal credit consistency,
   but did not independently replay native recording bytes. It also accepted
   extra fields. This change rejects supplementary/raw fields at projection,
   artist, work and ranking scopes, and adds a separate native core-only recording
   pack with offline replay. It leaves the older projection's source-custody
   limitation explicit.
4. **Do not count names or source recovery as musical validity.** The recorded
   2,112 historical-name matches, 6,513 active source-style neighborhoods and rare
   source-tag recovery gains measure different criteria. They establish neither
   reviewed fine genres nor independent sonic/cultural recommendation quality.
   Cold and missing identities must remain in denominators. Community proposals,
   direct observations, cultural context and recording/release credits require
   visibly different relationship roles.
5. **Complete the actual discovery tasks on the new output.** Search, full-list
   access, browser history/reload, keyboard/mobile use, missing-position access
   and exact benchmark artist navigation need evidence from the portable export
   itself. A ten-artist recording pack cannot establish representative music,
   playlist, listening or full-corpus discovery coverage. Outbound provider links
   are useful but do not prove track availability or a playable provider route.

## Native credit evidence

The optional original source cache is
`/workspace/opennoise/.cache/acousticbrainz-benchmark-metadata-20260930-v1/`.
Its `source-captures.json` hash is
`dc6fc8f755617909fb72ebec6cebcf4eb28912ca182bc706d7ea63f89d65135b`,
matching the portable credit receipt's `source_capture_receipt_sha256` field.
That field actually identifies the source-capture manifest, not the whole
receipt (whose hash is
`6ff37df93cccfdf4b4ea0e9bbac83f4accb63fb04f721053a930d891cf0603b1`).
Offline `build_cached_artist_work_examples.py` replay verifies the manifest and
body bindings and reproduces all ten artist records, 60 recording examples and
60 separately credited release contexts exactly. Only the top-level limitations
text differs from the checked-in projection. Replay output SHA-256:
`d04f356ea9c1054c7e7da6a24abaac82f1dc045f058b85734372f2f81c119856`.

All ten original recording-search responses contain supplementary `tags`
(5–20 occurrences per response), scores and aliases. They are mixed source
responses and cannot be redistributed as wholly CC0. No such raw bytes were
copied or relabeled.

The new `data/examples/recording-facts/` pack uses exact UUID lookups with
`inc=artist-credits`, fresh capture dates, core field allowlists and independent
native-byte replay. The frozen 36 requests accepted all 36 responses and retained
16,511 bytes. Every benchmark has three recordings; Aphex Twin and Four Tet have
six each. One preliminary exact lookup preceded the frozen capture; total session
network requests for this acquisition were 37. Fresh facts do not reproduce
historical search ranks, release edition credits or independent musical fit.

## Independent identity projection boundary

The retained official bulk-source receipt separately identifies
`core_metadata_license=CC0-1.0` and `tag_associations_license=CC-BY-NC-SA-3.0`.
The official license capture hash is
`5b37894260af675ff117f6921f62bd21963081f22893cf10717991dd930ff2f8`.
It states that core data may be used without restrictions. The verified core
prefix contains native `mbdump/artist` rows; an independent identity/name-only
projection of all such rows can retain that core license. It must bind the
prefix, member and schema, exclude derivative tag inputs and tag-derived cohort
selection, and retain `core_archive_sha256_verified=false`: only the prefix/member
custody was verified, not the full 7.6 GB archive. The optional tag artifact's
deny flags do not themselves relicense the native core artist table.

## Targeted validation and limits

Thirteen focused unittest cases pass, including native pack replay, exact-credit
exclusion, missing durations and failed-request denominators, source/projection
mutation, and supplementary-field rejection even with matching new hashes.
Ruff formatting/lint and ty pass for the changed modules/scripts/tests. The pack's
offline verification reports ten artists, 36 recordings and zero missing facts.

No canonical release build, full-corpus replay, new browser certificate,
independent music judgment or deployment is claimed by this review. The broader
recovery/product workstreams own their own final acceptance evidence.
