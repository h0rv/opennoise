# Independent bulk discovery correctness review — 2026-09-30

Status: implementation audit, fresh nested metric replay, training-byte checks, and final composition boundary review complete. The fine model does not meet the evidence threshold to replace frozen enrichment. This checkpoint is a read-only review of model/export implementations; only this document is owned by the reviewer.

## Evaluation boundary

The reviewed split joins exact normalized artist/value observations and every shared release-group evidence key using connected components. All facets of a held artist/value are removed before fitting. Release groups connect across artists, values, and repeated credits; nested partitioning removes additional complete components from the outer training file. Canonical identity means NFC, case folding, and whitespace normalization; punctuation-shaped variants are conservatively suppressed as proposals, not claimed to be universal aliases.

The fine model fits target vocabulary, artist-tag support, rarity gates, proper-genre anchors, cue associations, and specificity from training rows only. Outer training is never supplied to inner fitting. Each candidate is ranked before inner target-role scoring; the selected candidate is written before outer fitting/scoring. The outer test is used once. Full-source proper-genre vocabulary is used only to define post-ranking evaluation strata. It does not feed model eligibility or anchors. Prior corpus and other-fold exploration is explicitly disclosed, so this is a fresh nested within-corpus test, not untouched external validation.

Every model receives the same retained outer evidence and the same positive pairs for scoring. Candidate universes and abstention policies differ deliberately: fine-style targets are a train-gated subset, while broad enrichment and frequency/conditional baselines can propose a wider vocabulary. Thus a fine-style result compares complete prespecified systems, not an isolated proof that authority weighting alone helps. Cold, zero-support, and otherwise unproposable positives remain in denominators; missing rankings contribute zero. Unobserved metadata is never treated as a verified negative.

## Fine model mathematics

Training uses binary distinct-artist counts and maximum source authority per normalized musical value. Artist genre/tag and release genre/tag roles remain separate for target eligibility and query authority. Targets require direct artist-tag support, low corpus prevalence, and a train-only proper-genre anchor with coverage and lift thresholds. Release context supplies auxiliary cues and never creates a target or a native artist genre fact.

Association scores use smoothed conditional lift over the training target prior, discounted by joint support. Degree correction reduces the influence of heavily annotated training artists. Query scoring applies source authority and cue specificity, then sums only one or two strongest cues per target. These are bounded ranking heuristics, not calibrated probabilities. Artists with no retained primary artist values abstain even when release context remains. Known duplicate signatures cannot be proposed again.

Two issues identified during review were corrected before the fresh run: proper-genre duplicate-signature exclusion now matches the declared fine target stratum, and the release-tag authority fixture now matches the declared authority contract. The allowed-setting edge case at association lift exactly one was also fixed before freezing: association lift must exceed one, avoiding zero-score proposals that the saved-model loader would reject. The implementation owner reports nine targeted tests plus lint/type checks passing; the reviewer inspected the tests covering target support/share/anchor gates, transitive release components, duplicate suppression, zero-support denominators, and outcome replay.

## Independent replay of existing paired bulk experiment

The reviewer independently streamed both frozen ranking artifacts in `.cache/paired-bulk-source-increment-20260930-v1`, verified their SHA-256 values, and recomputed all-positive hits and reciprocal ranks against the same 110,027 held pairs. Every scorer matched the report exactly. No model was refitted.

| Scorer | Old all-positive hits | Augmented all-positive hits | Augmented recall@10 |
| --- | ---: | ---: | ---: |
| Adaptive topics | 33,282 | 39,835 | 36.20% |
| Feature enrichment | 43,861 | 51,779 | 47.06% |
| Global frequency | 24,817 | 25,226 | 22.93% |
| Proper-genre conditional | 53,444 | 55,095 | 50.07% |

The report separately records tag-only recall of 35.03% for enrichment versus 28.10% for the conditional baseline. This supports a narrower source-tag recovery benefit. It does not reverse the all-positive comparison, where the conditional baseline wins, and does not establish Every Noise relevance, sonic similarity, genre identity, useful discovery, or calibrated confidence.

Paired report identity: `e62b92d6c6324b7256d79a1a274c5a0ee20b3da35170a57f1e342a7ba0c8bd33`.

## Source-only artist maps

The reviewed geometry is mathematically cosine similarity on binary profile vectors weighted by square-root IDF: `sum(shared_idf) / sqrt(sum(left_idf) * sum(right_idf))`. IDF uses complete source-corpus distinct-artist support. Singleton values are removed, at least two shared values are required, and identical usable profiles abstain across the complete corpus even if the duplicate lies outside a displayed cohort.

Cohorts admit only observed artist-feature and credited-release-context memberships. Inferred proposals are excluded before graph construction. Names attach after coordinates are computed. Selection is bounded at 200 artists per style, ordered by informative source degree and exact MBID; directed neighbor lists are capped at ten. The symmetrized graph can have higher undirected degree. Spectral placement and rectangular packing remain inferred visual geometry with unevaluated discovery quality. The map payload’s `source_model_sha256` is an enrichment-lineage binding only; the graph itself uses source features, not that model’s scores or proposals.

## Fresh nested fine-model result and independent replay

The fresh `.cache/authority-aware-style-nested-v1` run selected the default candidate using only inner rare artist-tag recall: 7.5901% versus 5.8136% for moderate and 3.5376% for strong. Independent replay reproduced that selection over 87,561 inner positive pairs. The selected model has 1,329 eligible targets and 3,428 associations, and proposes at least one target for 60,161 of 198,409 source artists.

The outer test contains 110,431 positive pairs; the prespecified rare artist-tag slice contains 24,566, including 5,025 zero-training-artist-tag-support and 858 primary-cold positives. All remain in the denominator.

| Scorer | Rare artist-tag hits | Rare recall@10 | Rare MRR@10 | All-positive recall@10 |
| --- | ---: | ---: | ---: | ---: |
| Authority-aware fine style | 3,485 | 14.19% | 0.11366 | 3.16% |
| Frozen enrichment | 5,573 | 22.69% | 0.12200 | 47.28% |
| Proper-genre conditional | 3,235 | 13.17% | 0.06462 | 49.88% |
| Global frequency | 0 | 0.00% | 0.00000 | 22.78% |

The targeted fine model narrowly exceeds the conditional baseline on rare-tag recovery but loses to frozen enrichment on both its prespecified rare recall and MRR. It should remain a recorded research result and must not replace enrichment on this evidence. The restricted fine candidate universe explains its small all-positive score but does not excuse the loss on the target slice selected in advance. No outer-test reselection or tuning was performed. A separately checked, post hoc descriptive diagnostic also leaves fine style behind enrichment within its own eligible target pool: 3,485 versus 3,736 hits among 8,362 rare positives (conditional: 2,482). This diagnostic did not change selection or the prespecified denominator.

The reviewer independently aggregated frozen gzip outcomes using Python standard-library code, without calling the evaluator scorer or refitting models. All 33 inner and 44 outer scorer/stratum cells matched reported positive counts, hits, recall, reciprocal-rank means, zero-tag-support counts, and primary-cold counts. Maximum difference across all 154 floating recall/MRR values was exactly zero. The outer positive-pair hash matched the frozen pair receipt. Report self-identity, all top-level artifact hashes, selected-model files, model receipt identity, and current/frozen implementation hashes were verified. This verifies rank-outcome arithmetic and bindings; it does not independently reconstruct full rankings from the hash-only ranking receipts.

Independent receipt: `.cache/authority-aware-style-nested-v1-independent-audit.json`, SHA-256 `d8180b0a3575510e1701fb5a1b43b1c467da2a3ea920c9612034d81cef4c0f08`. Fresh report output identity: `dc0d76437c3eb8b49893a208c6cb36fd362ec8578b0f65cd34abfa033a7770b6`. Selected-model output identity: `9312d7f33d0e7817ae859a1eb984d0cbeca50cc9d94f694eab6546a4c4d585b6`.

Reviewed frozen fine-model code: `8e07bc8cc27402645af8ae40062f6209d4ff341df7fcb7927a8e62b4ac18dd5a`; evaluator: `c15913361b9b4a103d78e87e4f5026351f1f29fb8245a9b18f446bc4adbe84f1`.

## Initial sealed atlas and product v1 boundary (preserved history)

The expected current feature digest is `2b6179b4c969588f1268c9837b410c9da7b16d54c094850eb13ba00514b6f252` from `microgenre-features-primary-v4`. The expected enrichment prediction identity is `70ea84650de3f95054f5fda34c4bcbb286365bfa5fc8d4f69b8b4bb54d3c4d13`; its model identity is `650cc9dbead293cea81d214e7cdd0ddf6b99639ac9b503ddca4a68727fd45877`. The prediction identity is not the feature digest.

The composition implementation verifies both parent receipts, exact feature and feature-receipt identity, source-preview identity, local scope, no public export, no serving authorization, and zero native genre additions. It binds each unchanged parent artifact, preserves parent receipts separately, and atomically replaces only three navigation HTML files. The finished product consumes the verified current primary-v4 enrichment artifact. The unsuccessful authority-aware fine model remains a separate research result and is not substituted into the product.


The reviewer also independently streamed both frozen training files. Every held target was absent from retained musical values, and every outcome row’s music/tag artist support and primary/all profile degree matched independently recomputed training counts: 87,561 inner and 110,431 outer positives, over 198,409 artists in each partition. This additional training-byte check is recorded here; the already frozen compact metric-audit receipt was left unchanged.

The sealed atlas `.cache/named-style-atlas-bulk-20260930-v1/receipt.json` has output identity `7c107a144235ff7a91efff4ffbc37d3b9159b4a4b99d985d077a0da74cff6663`. Its source feature, feature-receipt, preview, enrichment prediction, and model bindings match the expected current artifacts. The reviewer verified receipt self-identity, current backend/map code bindings, and 17 deterministic source-map samples for exact file hashes, source-only roles, feature/model lineage, bounds, and explicit abstention. Map totals are 3,505 cohorts, 152,741 selected artist appearances, 114,674 positioned, 38,067 abstained, and 746,272 graph edges. Artist appearances across cohorts are not unique artists.

Final map implementation SHA-256: `ccf0d9542dc4248d3edb0aae6a10fdb38662d3dcaa09e4c3de443a6de012324e`. The implementation sorts a copy of valid CSR indices before its canonicality check; actual duplicate entries remain rejected. Atlas backend SHA-256: `866a8bd7d448902c1970c0282aa81deaec543b9cdf7037fdaeb2841c66165bfb`.

The composed product `.cache/opennoise-discovery-bulk-20260930-v1/receipt.json` has output identity `0cb77946fc23b02acc2bf356f8efe2df86fff6f8500fb0ab641966922c7a03a5`; receipt file SHA-256 `bc75c97dc93cc9343feaafaea91abdfd405ac7361b208e53a5944dcd4c2f0e61`. The reviewer verified its self-identity, exact copied parent receipt bytes and self-identities, feature/feature-receipt/source-preview equality, current builder hash, local/no-export/no-serving/native-zero flags, all 97,467 unchanged parent manifest bindings, and exact hashes for the three changed HTML files and both main data files. This is an independent manifest and targeted byte check; the builders perform the complete artifact-byte verification.

Only `index.html`, `communities/index.html`, and `communities/source-explorer.html` differ from their parents. The fixed community parent identity is `3ca8632e4837ad8a01c08d9a8da0fdebf60eedba06f388ec23d1b997e4146c86`, with community model `8bc5488c8861aaa89e88ea05513b9a9b6beb94b0ba63969ddb04d70d861d9556`. It contains no enrichment projection, so its null enrichment identity is appropriate. The atlas parent uses the expected `70ea8465…` enrichment prediction. Composer SHA-256: `5af42487cb2332ab58c99c4839b07692c50154e7e52f10e07683759d85d82e69`.

No unresolved correctness blocker was found in the reviewed split, scoring, source-map, or initial composition boundary. The blocking issue for fine-model promotion is measured performance, not an uncompleted evaluation. None of these within-source measurements establishes Every Noise relevance or independent genre truth.


## Final display refresh and product v2

The final atlas is `.cache/named-style-atlas-bulk-20260930-final`, output identity `7f91c5db7198716c9fd4f2ccdfb14d3497becf74c02ffb4b7e1d03f8a94fdb95`. This is a presentation-only refresh of the sealed atlas above. The independent audit compared every manifest entry: only `data.json` and 31,864 style detail JSON files differ. All 51,228 other file bindings are unchanged, including source profiles, proposal-bearing profiles, source cohorts, maps, geometry, and UI assets. The reviewer also compared all 31,864 style rows: only evidence tier, default visibility, display recipe revision, and suppression reason may differ; all source support, memberships, geometry, and dictionary IDs remain equal. Twenty-five deterministic detail samples, including every newly hidden label, passed exact hash checks and content equality outside those four display fields.

The nine labels removed from the default view are `composers`, `death by cancer`, `death by covid-19`, `death by plane crash`, `guitarists`, `jazz musicians`, `organist`, `pianists`, and `records`. These are meaningful exclusions of occupations, biographical metadata, and a generic catalog term; the underlying source observations remain available. Default visibility changes from 3,929 to 3,920 and default positioned styles from 3,618 to 3,610. Dictionary-backed style count remains 1,593. Actual corpus entries for `death metal`, `deathcore`, `festival trap`, `comfy synth`, `denpa`, and `soft visual` remain visible and dictionary-backed. The narrow death-cause prefix rule avoids suppressing death-related musical genres.

The original builder hash recorded above is historical, not a claim about current source. Its complete original implementation is preserved in `.cache/named-style-atlas-codefreeze-bulk-20260930-v1`, receipt identity `e75ef57c326e85c282e52692d4f74c35c1774c3b04dd4a2be67c2fc7cb64c43d`. The reviewer verified all ten frozen files against their byte counts/hashes, the codefreeze self-identity, original atlas identity, and every original code binding. The current display refresh builder SHA-256 is `8a7277639ea9359581ed5902481ef998dc74763978cca7b4cbf72883c9da3b59`; the final receipt retains the original source-atlas builder and code bindings separately.

The final product is `.cache/opennoise-discovery-bulk-20260930-v2`, output identity `50d5d8e1d0f3a8ca84308aa06afa7556d2154de754d83472c7e189cd33d22216`, receipt SHA-256 `7d6127ef5a19ac38bc367f5527881cb4e8ab2b1e0690a5e837e1963d1bda3716`. Current composer SHA-256 is `96b8c757327be7db529196b2bb30a3f8b08ed5e154d323000c5859978444092a`. The independent reviewer verified this current builder binding, product/parent receipt identities and copied receipt bytes, exact source/feature/feature-receipt lineage, current enrichment identity, and all 97,467 unchanged parent manifest bindings. Exact hashes for the three modified HTML files and both main data files match. All three HTML pages include the inline favicon, avoiding an implicit unbound favicon request. The product retains 97,472 bound files and the same fixed community parent. Both earlier sealed v1 artifacts remain preserved.

No model fitting, ranking, fine-model metric replay, or source evidence mutation was needed for this follow-up. The independent fine-model audit JSON remains unchanged. The final static boundary review passes; browser certification is recorded separately in `LOCAL_DISCOVERY_PRODUCT_20260930.md`. The fine-model non-promotion conclusion and the limit on same-source recovery claims remain unchanged.
