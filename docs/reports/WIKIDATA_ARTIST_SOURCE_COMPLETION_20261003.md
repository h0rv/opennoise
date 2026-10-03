# Frozen exact-artist source completion

This is an implemented CC0 source-label completion experiment, not an accepted
musical membership model. The exact output report is
`WIKIDATA_ARTIST_SOURCE_COMPLETION_20261003.json`; implementation and replay
contracts are in `docs/research/wikidata-artist-completion.md`.

The sealed source packs contain 9,992 exact MusicBrainz artist UUIDs and 18,750
native artist/P136 label pairs. Eight nonunique P434 identities are excluded and
explicitly counted. A source-selected roster is not representative of all music:
it has no unlabelled exact artists. Unlabelled denominator behavior is tested,
but there is no empirical unlabelled coverage claim. The original selected-150
foundation remains necessary for named anchors, including Aphex Twin and Four Tet,
which are absent from this randomly hash-selected broader roster.

Exact artist hashes assign 5,976 training, 2,025 calibration and 1,991 confirmation
artists before target counting. Training alone yields 238 labels supported by at
least five artists. Every confirmation artist contributes one masked observed
target; 1,248 have only one observed positive and cannot supply a seed.

| Frozen arm | Confirmation recall at 1 | Recall at 5 | Recall at 10 |
| --- | ---: | ---: | ---: |
| Seed-conditioned training popularity (frozen v2) | 2.41% | 6.43% | 10.25% |
| Training co-observation | 10.80% | 18.68% | 22.55% |
| Literal typed parent | 3.06% | 4.17% | 4.17% |
| Fixed combined arm | 9.94% | 18.08% | 22.05% |

The frozen popularity arm also abstains without supported seeds. Consequently
22.05% versus 10.25% compares a seed-conditioned prior and does not demonstrate
improvement over a meaningful unconditional prior. A separately named, untuned
post-inspection diagnostic uses the same training vocabulary/counts and existing
masked targets, excluding observed seeds while requiring none. On all 1,991
confirmation queries it obtains 15.47% at one, 49.62% at five and **58.61% at ten**.
The combined model underperforms this unconditional baseline. Its rare/unseen
target recovery is still zero. This diagnostic is not fresh confirmation, does
not select an arm, and leaves every v2 artifact unchanged. Exact diagnostic
evidence is `WIKIDATA_UNCONDITIONAL_SOURCE_PRIOR_20261003.json`; its new output
receipt SHA256 is
`8bce134521a0f82128a54314ec62367eca0c92cc411bdd2d69af46705d29f957`.

The combined arm also underperforms co-observation. It remains the predeclared
proposal arm; no confirmation-driven winner selection or tuning occurred.
The 157 rare-target queries recover 3.82% at ten under the combined arm, versus
4.46% under co-observation. All 25 unseen-target queries remain in denominators
and recover zero. Another 86 targets are observed in training but fall below the
minimum support; these are reported separately from genuinely unseen targets.

Combined masked-source top1 calibration has 678 confirmation events in bins
supported by at least twenty calibration events. Its Brier error is 0.18218,
versus 0.20045 for the calibration-cohort constant recovery baseline evaluated on
the same events. Bin reliability and Wilson intervals are retained, including
poor transport in some bins. This probability concerns recovery of a masked
native statement only. Full-seed proposal probabilities and musical membership
probabilities are null; a masked-task bin reference is not a calibrated
full-observation proposal. Missing source statements never become negative
musical annotations.

The final output is `/dev/shm/opennoise-wikidata-artist-completion-v2`, containing
1,836,859 bytes including source-pinned reports, every frozen fold/masked target,
all four confirmation ranked lists, fitted training counts, proposals, and the
exact implementation snapshot. Strict replay verifies source CC0 role/revision,
closed bytes, full request parameters and requested identities, frozen roster
completeness, unique native P434 UUIDs, P136 values and typed P279 values. The
genre pack is bound to the exact artist source receipt. The run took 15.14 seconds
with 46,612 KiB peak RSS. Ten focused tests, Ruff and targeted type checks pass.

The first prototype remains preserved under the separately named `v1` directory.
Provenance guards and evidence attribution were corrected in `v2`; frozen policy,
fitted counts, fold/target rows and all four confirmation lists are byte-identical
between both versions. No parameter, split, arm, target or rank changed.

Exact final receipt SHA256:
`5571f22953cfdc0c4003d855139bb4bbf1aadd97cbf2d3428495062eacaa0b6a`.
Exact report SHA256:
`bdd56463d9a1365b523b1a99c408a2745fb76470d8b2b66a7917536a8aed3b76`.
Preserved implementation SHA256:
`b535aa22a55007a89f3cc2bb7b6e18288cb59eff9c3ae36e08b92982cd093786`.

An independent saved-output audit reproduces all native observations, folds,
training counts, vocabularies, four-arm ranks, bins and metrics, retaining the
conditional-prior limitation above. Musical genre validity, calibration
against independent listening judgments, broad microgenre coverage, and any
Spotify taxonomy parity remain unassessed. Source reconstruction metrics cannot
substitute for those acceptance criteria. The optional source-completion
namespace must remain distinct from native observations and default promotion.
