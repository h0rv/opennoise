# Current milestone: open data pipeline and reusable models

The user's 2026-10-03 priority change defers additional site features, polish and
broad site-parity work. Keep only a minimal inspection/demo interface and its
necessary checks. The larger Every Noise reproduction remains a future goal;
this milestone cannot complete it. The original twelve-gate acceptance contract
and historical results remain unchanged. Deferred site gates are not passes.

## Deliverables and acceptance evidence

| Deliverable | Required evidence | Current decision and next work |
| --- | --- | --- |
| Licensed reproducible ingestion | Frozen source URLs, allowed fields and grants; native response custody, checksums, bounded failure handling and independent replay | MusicBrainz and Wikidata packs are replayed. Complete the reviewed pure ListenBrainz safeguards before its first request. Discogs currently has an incomplete prefix, not a complete source. Verify its schema and official checksum before a separately bounded full-stream capture. Exclude blended MLHD counts and unapproved audio. |
| Exact identities and normalized datasets | Native exact identifiers, collision quarantine, explicit unknowns, complete declared denominators and reusable schema | The frozen 150-artist catalog is exported and independently replayed: 161,339 artist/recording observations and 1,864 captures, with 147 complete observed pagination windows, three count-drift states and nine zero-recording artists. This is not an atomic snapshot or a global unique-recording census. Exact native MusicBrainz URL relationships independently verify Discogs artist 45 for Aphex Twin and 3543 for Four Tet. Validate the strict 69+2 bridge dataset and enrich recording identities using concordant native credits. |
| Musical representations and overlapping memberships | Training-only fitted features and vocabularies; source and acoustic representations kept distinct; support, missingness and reusable model artifacts | Retain acoustic baseline failures and source-positive selection bias. Broaden licensed release-style context without treating releases as exact recording labels. Evaluate overlapping candidate sets against explicit baselines; inferred memberships remain distinct from native facts. |
| Calibration and abstention | Calibration selection inside training only, complete cold/unlabelled/out-of-vocabulary denominators, risk/coverage and proper probabilistic metrics on an honestly named task | Training-only source-recovery fit, calibration and development artifacts completed and independently replayed. The fixed policy emits 101 of 1,176 development queries, with 93 recovering a masked observed source positive; 708 no-seed queries and unsupported cases remain in the denominator. The selected source-positive cohort has no source-missing queries, so broader unlabelled evaluation remains unmet. Previously inspected outer folds cannot become fresh confirmation. Source-event confidence is not individual membership or musical-fit probability. |
| Leak-safe evaluation and reusable artifacts | Provenance-bound folds, training-only fitting, source/code/parameter/output hashes, independent full replay and runnable export/load contract | Existing held-out source reconstruction has a scoped engineering review. Freeze new experiments before outcomes; retain unsuccessful runs. Bind fresh checks to exact new outputs. Do not promote candidates solely because they outperform a weak baseline. |
| Musical validation preparation | Frozen cohorts, permitted exact listening items, blank blinded forms, access failures and predefined judgment aggregation | Eight lawful clips and existing frozen packets are available. Broaden permitted coverage where native rights allow. Actual independent listener judgments remain absent; no invented reviewers or votes. |

Discovery behavior, genre/artist maps, the full accessible interface and broad
site-parity certification are deferred in this milestone. Genre naming,
representative recordings and listening judgments remain important data/model
validation questions; a minimal demo does not establish them. Browser work is
not on the critical path for the normalized dataset or model exports.

## Dependencies and limits

Real independent listeners are required to assess musical membership, sonic and
cultural relevance, useful sub/microgenre boundaries and representative tracks.
API availability and provider permission/access constrain new native evidence
and listening. A metadata grant never grants artwork or audio rights. Musical
confidence cannot be validated from source-positive metadata alone.

Local capacity is an engineering constraint, not a licensing or human dependency.
The executor is near its 16 GiB cgroup limit and its overlay is full. All jobs
must be serialized, stream bounded chunks, preserve rejected attempts and check
actual headroom before starting. Deletion approval for the 443 redundant recovery
transfer files remains pending; this priority change grants no deletion. Original
archives, metadata, source packs and new work remain preserved.

The two absent sealed legacy inputs only block restoration of that old release.
The separately named full-input reconstruction remains the authorized route for
recoverable engineering gaps. Neither identity count nor source reconstruction
is evidence of complete Every Noise parity.

Use the separately named scope `reproducible-data-and-model-research-v1` for this
milestone's future evidence and decisions. The original full-foundation dossier
must not be repurposed as a narrowed milestone checker. Artifact presence alone
cannot pass this milestone: each deliverable needs reviewed executable evidence.
The original checker was run on 2026-10-03 at 08:54:51 UTC: 44 bindings verified,
three recorded engineering passes, nine unmet gates, exit 1. Its complete result
and exact dossier/checker bindings are retained under `evidence/`.
