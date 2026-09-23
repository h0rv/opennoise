# Source and signal inventory

This inventory records the source families retained in the repository and
their current use. An adapter, manifest entry, or cache path does not mean
that its data feeds the public model. A source is marked sealed only when a
receipt or checked artifact binds the input used by a build or evaluation.

| Source family | Retained state | Genre graph and membership use | Layout or diagnostic use |
| --- | --- | --- | --- |
| Every Noise historical files | The fixed vocabulary has 6,291 names. Historical artist observations, coordinates, neighbors, ranks, and representatives are retained behind evaluation custody. | No construction use. It supplies the research name universe only. | Historical compatibility tests only. It cannot tune, select, or populate the graph or layout. |
| Wikidata | Sealed public database and replay receipts contain 746 genre QIDs, 1,331 artist QIDs, 787 release group QIDs, 623 recording QIDs, 853 catalog relations, and 4,948 P136 rows. | This is the current factual source for genre identity, P279 hierarchy candidates, direct artist to genre claims, and representative metadata. The public membership output exposes direct P136 claims only. | The qualified hierarchy and privacy safe similarity input feed the production map. |
| MusicBrainz artist and derived data | Receipt bound local research artifacts exist. The documented corpus processed 2,970,393 artist records and has 212,696 contextual tag rows for 88,328 artists. The separate portable direct proper-genre custody receipt contains 387,435 exact source observations across 697 seeds and 198,409 artist MBIDs. | It does not feed the current public factual membership graph. Proper-genre rows remain custody-only; contextual tags remain local research evidence. No membership construction or public export is authorized from the custody receipt. | Exact MBIDs support prior local peer candidates and metadata context. The peer index has 28,508 canonical edges across 1,580 supported seeds. A distinct custody-only source graph records 20,178 candidate pairs across the 697-seed receipt; it is non-serving local research. |
| MusicBrainz release groups and recordings | The 2026-09-05 release group candidate is receipt bound and has 4,499,326 records, 421,427 release-group direct-anchor pairs, and 1,546,265 release support pairs. Recording and release hydration are metadata only. A pinned local release-credit diagnostic found 87 release groups, 284 support claims, and 3,132 exact credit matches. A separate 24-ID exact recording-to-artist API pilot is custody-backed local research only. A guarded local renderer can project one selected artist's already-gated static credit metadata into `.cache`. A separate HTML wrapper checks a separately supplied typed approval declaration and the already-gated asset, but cannot recheck the candidate report or policy without the original database and report. | Release group labels, direct anchors, and the release-credit diagnostic are credited artist support, not direct artist membership. The candidate, diagnostic, pilot, and renderers are not consumed by the public model or API. | Local release support, representative metadata, peer evaluation, and the non-production exact-ID feasibility pilot. The renderers are local preview tools only; they do not approve public UI integration, static integration, browser certification, or deployment. |
| ListenBrainz aggregates and playlists | The qualified SQLite input is sealed at SHA-256 `282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866`. The run has 30,903 daily aggregate pairs and 13,175 normalized artist pairs. Separately, one receipt-bound ten-playlist JSPF bundle has 527 exact recordings. The service route identifies it only as one account's user-created listing, with all ten curator states `unknown` and no human/manual/editorial claim. Its 24-recording bridge has 23 exact MusicBrainz responses. A disjoint 50-recording selection is pinned at SHA-256 `2bac1641dad3201d77086344de5824f39f7f6ed6ae523dd91c043a9c32ee74f1`, but its first live request stalled and was interrupted with no response custody or artist-credit result. A JSPF extension parse has 603 valid source-claimed artist URIs over 557 tracks (344 IDs); the 23 checked claim sets agree with those exact responses, while all other claims remain unverified. Its 13,584 cross-track pair potentials and 171 repeat-across-playlist potentials are one-account-cohort descriptive counts only. A matched local holdout recovers 41 of those 171 repeated pairs against Last.fm, with Recall at 10 of 36 of 342 directed ranking events versus 6 of 342 for the seeded baseline. A bounded cross-account attempt retained no response body. | Privacy filtered co-listen evidence is retained as aggregate support. Playlists provide source-order recording co-occurrence only, never a genre claim or factual membership. JSPF identifiers remain source claims, not verified credits except for the separately checked 23 records. The 50-recording selection is dry-selection-only. One hop membership propagation remains a review candidate. | The production map may use only the privacy-safe aggregate similarity input. All playlist artifacts and the matched holdout are local-only diagnostics; none supplies independent curator/account support, a privacy floor, human curation, model input, or serving/public data. Raw listens, account identifiers, playlist titles, and curator inferences are not served. |
| Last.fm reverse tags | Adapter and tests exist, but no response cache or evidence receipt exists. | No current graph or membership use. | Review only after an approved API key, query manifest, exact MBID input, and response receipt. |
| Last.fm ArtistTags2007 literal candidates | A pinned local 2007 archive and the current 6,291-name seed vocabulary produced 192,614 literal candidates across 1,317 seeds. The result preserves source rows and counts, but it is a local candidate artifact. | No factual membership, gold, negative-label, model, quality, or release use. Literal tag-to-seed equality is candidate selection only. | The terminal public-v2 overlap report is coverage only and cannot add, remove, or rank candidates. |
| MSD and Last.fm offline files | The three required MSD SQLite inputs remain absent. The checksum-verified local-only Last.fm 360K archive has a completed streaming plays-member aggregate: 17,559,530 rows, 160,131 strict exact artist MBIDs, 782 overlaps with the 1,331-artist catalog, and 485,840 artist pairs retained at the >=5-user floor. Its ignored SQLite is local aggregate custody (exact artist and retained pair IDs, no user identifiers), hash-bound by a counts-only companion receipt; see [the source checkpoint](LASTFM_360K_SOURCE_FEASIBILITY_20260922.md) and [count-only direct-custody exact-ID coverage](LASTFM_DIRECT_CUSTODY_EXACT_COVERAGE_20260923.md). An ignored order receipt found no increases across 17,200,181 adjacent play-count comparisons within contiguous blocks, so the cap is the first ten unique valid exact MBIDs in non-increasing play-count order. It is not top ten overall rows when non-exact or malformed rows precede valid exact MBIDs. The observed 359,349 contiguous blocks and 160,131 strict UUIDs are not equated with the source page's 359,347 users and 186,642 MBID artists. Separately, the creator-attributed [Last.fm 1K Zenodo record](https://zenodo.org/records/6090214) makes a 672.7 MB timestamped archive available with 19,150,868 rows, 992 users, and exact MusicBrainz artist and track IDs. It is not retained. Any future use starts with a checksum-pinned, counts-only streaming audit; track IDs need a separate exact recording bridge. | No graph, membership, model, evaluation, or public use. The 360K result is not MSD evidence. Last.fm 1K is not yet an ingested source. | The source-order cap and all-time play semantics make the completed 360K aggregate unsuitable as full similarity or independent genre evidence. Last.fm 1K may support a small local identity feasibility audit after terms review, but user IDs, names, titles, individual listens, and unthresholded aggregates remain out of custody. |
| MusicBrainz to Spotify bridge and H3 | Receipt bound bridge and sealed H3 projection exist for historical compatibility. | Prohibited from construction and from public membership. | Evaluation only. H3 absence is unknown, not a negative label. |
| FMA, Discogs, and AcousticBrainz | No FMA or direct Discogs adapter/receipt exists. The ignored local AcousticBrainz Discogs validation TSV is checksum-pinned and has 71 recording-MBID overlaps, 64 release-group-consistent overlaps, and 63 single-primary-artist rows. Its existing source-isolation gate remains a no-go for artist gold and promotion because no retained prediction artifact/receipt proves exclusion of MusicBrainz tags, recording/release genres, and historical Every Noise. A separate diagnostic freezes 63 Wikidata-only recording predictions before parsing or using labels; after verification, its label pass finds three unique literal `jazz` positives and zero exact prediction overlaps. | No use. The diagnostic is positive-only recording coverage, not artist membership, artist gold, a quality estimate, or a negative-label result. | FMA and direct Discogs still lack documented exact model bridges. AcousticBrainz remains local research only and is not a promotion gate. |

The creator-attributed [Last.fm 1K Zenodo record](https://zenodo.org/records/6090214)
lists a 672.7 MB archive with 19,150,868 timestamped rows for 992 users and
exact MusicBrainz artist and track IDs. The archive is not retained. A future
local streaming audit can verify its MD5, record a local SHA-256, and report
exact-ID counts. The bounded adapter and receipt contract are documented in
[the Last.fm 1K streaming feasibility checkpoint](LASTFM_1K_STREAMING_FEASIBILITY_ADAPTER_20260923.md).
The track ID needs a separate exact recording bridge. The
audit must retain no user IDs, names, titles, individual listens, or aggregate
that does not meet a privacy threshold. It has no model, evaluation, or public
role.

A local [MusicBrainz and Last.fm corroboration audit](CROSS_SOURCE_ARTIST_GENRE_CORROBORATION_AUDIT.md)
found 20,498 exact artist-MBID and canonical-seed pairs shared by the
MusicBrainz proper-genre custody source and the Last.fm ArtistTags2007 literal
candidate. The result is coverage only. It does not turn either source into
factual membership, independent gold, a model input, or a promotion decision.

A local [ListenBrainz playlist signal audit](LISTENBRAINZ_PLAYLIST_SIGNAL_QUALITY_AUDIT_20260923.md)
found 26 exact-credit playlist occurrences, 29 distinct artist pairs, and five
pairs that overlap the retained Last.fm 360K aggregate at its privacy floor.
All ten playlists come from one account and have unknown curator state. The
result is a count comparison only. It is not a quality result, music claim, or
model input.

A receipt-checked local MusicBrainz source replay matched 139,268 direct rows
across 412 placed candidate-only seeds in both directions. The ignored
candidate is local-only and is not serving input; see the
[source replay checkpoint](MUSICBRAINZ_DIRECT_LOCAL_STATIC_SOURCE_REPLAY_20260923.md).
A separate Last.fm-supported review produced 109 proposed edges for 43
unplaced seeds. Forty-two overlap the existing review frontier and one is
outside it. These remain local review proposals, not membership or placement
claims; see the
[unplaced co-listen review](MUSICBRAINZ_UNPLACED_COLISTEN_REVIEW_EDGES_20260922.md).

## Signal boundaries

The current [open listening and playlist source research](OPEN_LISTENING_PLAYLIST_SOURCE_RESEARCH_20260923.md)
records the new-source decision. The existing privacy-filtered ListenBrainz
aggregate remains the priority because its source-isolated local holdout
retrieves 188 of 1,453 endpoint-conditioned positives at Recall at 20, versus
74 for direct-IDF peers. The result does not prove general coverage,
precision, musical similarity, or membership, and the compared candidate
capacities differ. Million Song Taste Profile has no verified exact
MusicBrainz bridge. Spotify's historical Million Playlist Dataset is currently
unavailable for download and unsuitable for the stated reconstruction purpose
under its terms. MusicBrainz public collections are exact-ID lists but not
playlists or curation evidence.

The current public genre graph uses Wikidata for catalog identity, factual
hierarchy, direct artist membership, and representative metadata. It uses the
privacy filtered ListenBrainz aggregate for a similarity input where the map
contract permits it. It does not use Every Noise observations, MusicBrainz
tags, MusicBrainz release group labels, H3 memberships, audio, or model
predictions as public factual membership.

The current public artist membership candidate combines direct Wikidata P136
rows with privacy filtered aggregate candidates, but it is not release
eligible because no independent public gold set has passed the evaluator. Its
direct candidate has 3,049 pairs, and its one hop candidate has 9,256 pairs.
These are candidate counts, not published factual coverage.

The public map has 603 hierarchy nodes, 712 direct taxonomy edges, and 3,274
similarity edges in the recorded qualified run. Historical coordinates are
not used for its positions. Local MusicBrainz peer layouts and historical H3
comparisons are separate diagnostics.

## Gaps

The retained source inventory has four practical gaps. First, the public P136
frontier is sparse, with 292 directly anchored names and 5,999 explicit
abstentions in the bounded membership candidate. Second, MusicBrainz release
and tag evidence is large but remains local and support only. Third, the MSD
SQLite inputs remain absent; the retained Last.fm 360K prefix diagnostic is
superseded by a completed full local aggregate, which remains intentionally
ineligible for model or evaluation input. Fourth, no
independent public artist and genre gold set is available, so no
precision or recall threshold can promote the membership candidate.

The next safe work is to preserve the existing source boundaries, then run
held out evaluations for direct, aggregate, release support, and local peer
signals separately. Any new source must provide a receipt, exact identity
joins, license scope, and a declared signal role before it enters a build.

## Source references

- [Data source audit](../ingest/DATA_SOURCE_AUDIT.md)
- [Source coverage audit](SOURCE_COVERAGE_AUDIT.md)
- [Open construction graph v2](../reports/OPEN_CONSTRUCTION_GRAPH_V2_20260904.md)
- [Public artist membership candidate](../reports/PUBLIC_ARTIST_MEMBERSHIP_REAL_INPUT_20260905.md)
- [Production map audit](../reports/PRODUCTION_MAP_20260831.md)
- [AcousticBrainz Genre Dataset evaluation audit](ACOUSTICBRAINZ_GENRE_DATASET_EVALUATION_AUDIT.md)
- [AcousticBrainz Discogs validation exact overlap](ACOUSTICBRAINZ_DISCOGS_VALIDATION_EXACT_OVERLAP_20260923.md)
- [AcousticBrainz recording-gold source isolation](ACOUSTICBRAINZ_RECORDING_GOLD_ISOLATION_20260922.md)
- [AcousticBrainz Wikidata recording diagnostic](ACOUSTICBRAINZ_WIKIDATA_RECORDING_DIAGNOSTIC_20260923.md)
- [Last.fm/direct-custody exact-ID coverage](LASTFM_DIRECT_CUSTODY_EXACT_COVERAGE_20260923.md)
- [ListenBrainz playlist exact artist-credit bridge](LISTENBRAINZ_PLAYLIST_MUSICBRAINZ_ARTIST_BRIDGE_20260923.md)
- [ListenBrainz playlist and Last.fm matched holdout](LISTENBRAINZ_PLAYLIST_LASTFM_360K_MATCHED_HOLDOUT_20260922.md)
- [ListenBrainz user-created route cohort](LISTENBRAINZ_USER_CREATED_PLAYLIST_COHORT_20260923.md)
- [ListenBrainz JSPF embedded artist identifiers](LISTENBRAINZ_PLAYLIST_JSPF_EMBEDDED_ARTIST_IDENTIFIERS_20260923.md)
- [ListenBrainz cross-account playlist feasibility](LISTENBRAINZ_CROSS_ACCOUNT_PLAYLIST_FEASIBILITY_20260923.md)
- [Open listening and playlist source research](OPEN_LISTENING_PLAYLIST_SOURCE_RESEARCH_20260922.md)
- [MusicBrainz credit artist-detail local render](MUSICBRAINZ_CREDIT_ARTIST_DETAIL_LOCAL_RENDER_20260922.md)
- [MusicBrainz credit artist-detail local HTML preview](MUSICBRAINZ_CREDIT_ARTIST_DETAIL_LOCAL_HTML_20260922.md)
- [Listening and playlist source priority](LISTENING_PLAYLIST_SOURCE_PRIORITY_20260923.md)
- [Direct custody peer graph checkpoint](MUSICBRAINZ_DIRECT_CUSTODY_PEER_GRAPH_20260922.md)
