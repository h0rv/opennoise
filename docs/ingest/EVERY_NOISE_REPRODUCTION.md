# Every Noise reproduction plan

Research date: 2026-08-31

## Goal

OpenNoise should support two separate results.

The historical result reproduces what Every Noise at Once published. It preserves the final map, artist pages, examples, links, ranks, and playlists as dated observations. It does not claim to recreate Spotify's private calculations.

The open result rebuilds the system from public metadata. It starts with open music identities,
tags, relationships, and privacy-safe public listening aggregates. OpenNoise does not ingest audio or
audio-derived feature data. Every stage records its inputs, method, version, and output. The open
result can be measured against the historical result, but it remains a different map.

An exact reproduction of the private model is not possible from the public record. Glenn McDonald disclosed several inputs and design choices, but he did not publish the source code, complete feature vectors, thresholds, weights, or the final layout transform. OpenNoise should show the difference between a disclosed fact and a fitted approximation.

## Current open construction contract

The immutable 6,291 seed IDs are the join boundary. An explicit bridge maps each seed to public identities and separate MusicBrainz genre or tag identities. Direct artist sets produce canonical symmetric peer candidates and a directional top-k view. Public taxonomy supplies directed containment candidates. Every output is versioned, hashed, evidence-backed, and able to abstain. H3 data is evaluation-only. OpenNoise stores metadata, never audio or music files.

## Claim labels

The known and unknown matrix uses four labels.

1. **Disclosed** means McDonald, the Echo Nest, or Spotify described the method.
2. **Observed** means the value or behavior appears in a dated public artifact.
3. **Inferable** means an experiment can test a likely transformation, but the result cannot establish the original method.
4. **Unknown** means the public record does not identify the method or value.

## Main findings

Every Noise was a genre radio system before it was a map. The Echo Nest needed to answer requests for a genre such as rock without returning every artist who had ever been described with the word. McDonald described the later system as a way to find music communities. A genre could represent sound, place, language, time, social group, purpose, politics, instrumentation, or several of those at once. Genres could overlap, and an artist could belong to several genres. Sources: [How We Understand Music Genres](https://furia.com/everynoise_public/EverynoiseIntro.pdf), [McDonald interview from 2024](https://www.cantgetmuchhigher.com/p/spotifys-former-data-guru-sets-the), and [Spotify for Artists interview](https://artists.spotify.com/blog/how-spotify-discovers-the-genres-of-tomorrow).

The final public map contains 6,291 genres and says that its data runs through 2023-11-19. The local pinned HTML has SHA256 `1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180`. Each of its 6,291 rows contains a source item number, genre name, position, color, font size, Spotify recording ID, preview URL, representative artist and track text, and artist map URL. The positions span x values from 0 to 1500 and y values from 0 to 22,648. Source: [final public map](https://furia.com/everynoise_public/engenremap.html) and the pinned local artifact.

The main map used bounciness from left to right and organism on the vertical axis. McDonald defined organism as a combination of acoustic instrumentation and flexible human timing. He defined bounciness as spikiness and dynamic variation against atmospheric density. The public page explains the same result in less technical words. Down is more organic, up is more mechanical and electric, left is denser and more atmospheric, and right is spikier and bouncier. The exact scaling and direction of the raw organism value are not public. Sources: [McDonald's 2014 technical log](https://www.furia.com/page.cgi?skip=96&type=log), [McDonald's 2013 audio metrics note](https://furia.com/page.cgi?skip=90&tag=listen&type=log), and the [final public map](https://furia.com/everynoise_public/engenremap.html).

The axes and orientations changed during the site's life. In April 2013, McDonald described an earlier map as electric on the left, acoustic on the right, dense or uniform at the top, and sparse or spiky at the bottom. He also said that artist maps were normalized within each genre and had less data, so their positions were less precise and were not globally comparable. The intro says that he had already flipped the map once and might do so again. Reproduction must therefore attach coordinates to a dated layout revision. Source: [McDonald's 2013 Maps Within Maps notes](https://furia.com/page.cgi?skip=90&tag=tech&type=log) and [How We Understand Music Genres](https://furia.com/everynoise_public/EverynoiseIntro.pdf).

The map was not a direct two value plot. McDonald called it an algorithmically generated and readability adjusted scatter plot. He also said that the genre system used ten internal dimensions and two independent similarity measures. A separate 2013 analysis used twelve audio metrics. The twelve were danceability, energy, tempo, loudness, acousticness, valence, dynamic range, spectral flatness, beat strength, mechanism, organism, and bounciness. The ten dimension statement and the twelve metric analysis may refer to different revisions or different tasks. The public record does not resolve the difference. Sources: [How We Understand Music Genres](https://furia.com/everynoise_public/EverynoiseIntro.pdf) and [Every Number at Once](https://furia.com/page.cgi?skip=90&tag=listen&type=log).

The system joined acoustic and cultural evidence. In 2016, McDonald wrote that a genre playlist ranked tracks by a combination of cultural and acoustic relevance. Its first track became the representative sample on the main map. The Sound of playlist moved from the center toward less central tracks. The exact score and weights were not published. Source: [How to Write a Bug](https://www.furia.com/page.cgi?skip=57&type=log).

Listening data became more important as the system moved into Spotify. McDonald described tools that found unlabeled groups whose artists or songs often shared listeners. A person then listened to the group and decided whether it was a music community, a soundtrack effect, or another false cluster. Some genres instead started from lyrics, place, history, an existing term, or a hand built seed list. Source: [McDonald interview from 2024](https://www.cantgetmuchhigher.com/p/spotifys-former-data-guru-sets-the).

Human review was part of the method. People resolved name variants, decided whether the data was large and distinct enough, seeded some genres, rejected false groups, named some new groups, checked playlist results, and changed rules when the result did not make musical sense. The memberships and ranks then changed automatically as the source data changed. Sources: [How We Understand Music Genres](https://furia.com/everynoise_public/EverynoiseIntro.pdf) and [Spotify for Artists interview](https://artists.spotify.com/blog/how-spotify-discovers-the-genres-of-tomorrow).

## Known and unknown matrix

### Genre definition and creation

Status: disclosed in broad form, with thresholds unknown.

Genres were overlapping sets rather than a strict taxonomy. A genre could begin with an established descriptive term, an artist seed set, an unlabeled listening cluster, a place, a language, a historical group, lyrical content, or another cultural distinction. McDonald and other contributors reviewed the result and supplied or normalized names. A candidate needed enough data to produce a substantial and distinct body of music. The minimum artist count, listener count, density rule, distinctness score, split rule, merge rule, and retirement rule are unknown.

### Artist membership

Status: disclosed in behavior, with the score unknown.

Artists could belong to any number of genres. Membership changed as artists moved into or out of prominence or relevance. Central genres received more artists, while peripheral genres received fewer. The scale depended on data density and artist interrelation. The exact membership features, score, cutoff, maximum size, decay, and refresh rule are unknown.

### Similarity and related edges

Status: partly disclosed, partly observed, and partly unknown.

McDonald said that the system used two independent measures of genre similarity. He described related genre insets as containing direct relations from overlapping artists and weaker relations from audio similarity. Smaller names indicated a more distant or doubtful relation. The Echo Nest also had a broader artist similarity system that combined cultural descriptions and acoustic features, but no public source says that Every Noise used the patent's exact formula. The historical pages expose nearby genres and positions. The score normalization, combination rule, number of neighbors, and tie rule are unknown. Source: [Maps Within Maps](https://furia.com/page.cgi?skip=90&tag=tech&type=log).

The Echo Nest patent is useful background only. It describes independent acoustic and cultural comparisons, normalizes their scores, and then combines them. Cultural vectors could represent the probability that a phrase describes a track or artist. Acoustic comparisons could include tempo and timbral signatures. The patent describes a family of methods and does not disclose the Every Noise implementation. Source: [US8073854B2](https://patents.google.com/patent/US8073854B2/en).

### Coordinates and axes

Status: the intended axes are disclosed, while the transform is unknown.

The horizontal direction is bounciness. The vertical direction is organism, displayed so that organic music is lower and mechanical music is higher. The final output coordinates are directly observed. The raw feature aggregation, clipping, winsorization, standardization, nonlinear scaling, margins, axis reversal, and conversion to page pixels are unknown.

### Color

Status: directly observed as output and otherwise unknown.

Every genre has a hexadecimal color. The color varies smoothly enough to suggest that it represents one or more analytical values, but the input, color space, transform, and purpose were not found in a primary source. OpenNoise must not describe color as a third axis unless an experiment supports that wording, and even then it must be labeled as an approximation.

### Audio features

Status: twelve analytical metrics are disclosed for a 2013 system, but their later use is unknown.

McDonald published the twelve metrics listed above. He calculated a mean and standard deviation from a few thousand tracks for each genre. He also published a discrimination measure. The measure divided the standard deviation of the group means by the average within group standard deviation. The metric set was useful for comparing genres, years, popularity groups, countries, and random controls. The source track selection, minimum track count, outlier handling, recording version handling, and later Spotify feature revisions are unknown.

### Artist overlap

Status: disclosed as one similarity signal, with the formula unknown.

Public descriptions identify artist overlap as one genre relation. The intro also says that genre size depends on artist interrelation. The system may have weighted artists by rank, popularity, centrality, or membership strength, but the public record does not state the formula.

### Clustering

Status: human use of computed groups is disclosed, while the clustering method is unknown.

Spotify tools surfaced unlabeled groups based in part on common listeners. McDonald listened to each candidate and rejected groups that reflected a soundtrack or another incidental cause. No public source names k means, hierarchical clustering, community detection, density clustering, an embedding model, or exact parameters for the production genre finder.

### Layout and label movement

Status: readability adjustment is disclosed, while the algorithm is unknown.

The published positions include what McDonald called aggressive rearranging for readable labels. No public source identifies the initial layout, collision solver, displacement cost, ordering, iteration count, or whether labels could move on one axis or both. Page positions therefore cannot be treated as raw feature coordinates. Artist maps were normalized within each genre and were less precise because they had less data. Source: [McDonald's 2013 technical notes](https://furia.com/page.cgi?skip=90&tag=tech&type=log).

### Representative samples

Status: the source and broad ranking are disclosed, while the score is unknown.

The first track in the genre playlist became the map sample. The playlist tried to order tracks by cultural and acoustic relevance, with central tracks first. McDonald manually checked surprising changes and changed rules. The final HTML directly records one sample track, artist text, Spotify recording ID, and preview URL for every genre. The exact cultural score, acoustic score, weights, diversity rule, availability rule, and replacement rule are unknown.

### Genre and artist ordering

Status: output rank is observed, while most semantics are unknown.

The final map HTML orders items from 1 to 6,291 and gives every item a font size from 100 to 160 percent. Popular genres appear early and receive larger type, but no primary source found in this review defines the item order or font scale. The one dimensional page separately supports popularity, emergence, modernity, youth, femininity, engagement, background, tempo, duration, color, name, and added date. It can also sort by similarity to a selected genre. The formulas for most ranks are unknown. Source: [one dimensional public view](https://furia.com/everynoise_public/everynoise1d.html).

### Playlists

Status: playlist purposes and broad inputs are disclosed, while exact scores are unknown.

The Sound of genre was a central and faintly canonical introduction. The Pulse of genre found listeners who knew the genre well, then ranked their distinctive current listening. The Edge of genre used the same audience idea but restricted the result toward new and mostly unknown music. Annual and place playlists often compared a group's listening with global totals and ranked songs that were played disproportionately by the group. The audience qualification, time windows, minimum support, popularity cutoff, newness cutoff, score, and deduplication rules are unknown. Sources: [Deeper Noises at Once](https://www.furia.com/page.cgi?skip=60&type=log) and [McDonald's 2024 notes on community listening](https://www.furia.com/page.cgi?skip=27&type=log).

### Time and updates

Status: update behavior is disclosed, with several schedules observed.

Artist memberships could change automatically. Rankings could change daily. Genre pages and maps sometimes changed after larger migrations. The Sound of playlists updated weekly for long periods. The final public genre data stops at 2023-11-19 because McDonald lost the internal access needed to update it. The feature computation window, decay, backfill, and exact production schedule are unknown.

### Thresholds and weights

Status: unknown.

No public source gives production thresholds or weights for membership, similarity, candidate genres, layout, color, representative tracks, Pulse, Edge, or retirement. A patent, a public rank, or a close visual match cannot fill this gap.

### Human editorial decisions

Status: disclosed in role, but not available as a complete log.

People normalized names, decided whether candidates were meaningful, named some groups, rejected incidental clusters, reviewed samples and playlists, and adjusted rules. The full decision log, reviewer list, rejected candidates, and revision history are not public.

## Historical output reproduction

Historical reproduction should preserve dated outputs without mixing them with the open model.

### Stage H1: source manifest

Inputs are the final map HTML, the public mirror, selected Internet Archive captures, the intro PDF, one dimensional lists, genre artist pages, artist pages, and linked playlist identifiers.

The output is a source manifest. Each artifact records its original URL, archive URL when present, capture time, claimed data time, byte length, hash, content type, acquisition method, access result, rights policy, and parser version.

Acceptance requires exact byte hashes and no unrecorded live fetch during a normal application request.

### Stage H2: main genre map

The parser emits one genre observation for every HTML row. It preserves source item ID, source name, source artist map slug, x, y, color, font size, source order, representative artist text, representative track text, Spotify recording ID, preview URL, and source hash.

The output must contain exactly 6,291 unique source item IDs. The parser must not assume that item order means popularity or that color means a named metric.

### Stage H3: genre artist pages

The parser emits genre to artist membership observations, artist display positions, artist source order, sample metadata, external artist links, page date, and the related genre blocks shown on the page. It preserves whether each related genre was shown through artist overlap or audio similarity when the page exposes that distinction.

Each membership remains an observation from one page. McDonald said that these pages showed only a couple hundred representative artists, so absence from a page is not negative membership evidence. OpenNoise must not convert presence into an unqualified canonical fact. If two dated pages disagree, both observations remain available. Artist display coordinates belong to that genre page's local normalized coordinate system.

### Stage H4: artist pages and recordings

Where an archived artist page exists, the parser records its tracks, samples, external links, and genre list. It resolves Spotify IDs only as source identifiers. A MusicBrainz match is a separate entity resolution decision with evidence and confidence.

### Stage H5: lists and playlists

The parser records each public rank under its own metric key. Playlist identifiers and observed track order are versioned collection observations. A missing or changed Spotify playlist does not erase the historical observation.

### Stage H6: compatibility view

The historical lens reproduces the final map and its discovery path. It uses the archived output fields and says which fields came from the source. The compatibility view does not call its coordinates an embedding and does not present stale preview availability as guaranteed.

## Open reconstruction pipeline

The open pipeline uses independent stages so that metadata, listening, audio, scoring, and layout can change separately.

### Stage O1: identities and catalog

Primary inputs are the MusicBrainz core dump and Wikidata structured data. MusicBrainz core data is CC0. MusicBrainz user tags and ratings are supplementary data under CC BY NC SA 3.0, so their claims need a separate policy. Wikidata structured data is CC0.

The output contains artists, artist credits, release groups, releases, recordings, works, labels, dates, places, URLs, identifiers, names, and aliases. A release group is the album level entity. A release is one edition. Sources: [MusicBrainz download documentation](https://musicbrainz.org/doc/MusicBrainz_Database/Download), [MusicBrainz data license](https://musicbrainz.org/doc/About/Data_License), and [Wikidata data access](https://www.wikidata.org/wiki/Help%3AData_access).

### Stage O2: genre evidence

Inputs are MusicBrainz genre tags and counts, other approved MusicBrainz tags, Wikidata genre and subclass statements, place and date facts, and the Every Noise names used only as seed labels or evaluation references.

The output is append only evidence. Each row names the subject, proposed genre, source record, evidence kind, source count when present, observed time, source snapshot, and rights policy. Alias resolution and canonical genre selection are separate decisions.

### Stage O3: public listening graph

ListenBrainz public listens are CC0 and can supply listener to recording events. The importer maps recordings and artists to MusicBrainz IDs when available, drops or hashes user identifiers before graph materialization, and keeps raw listens outside the catalog. Public output requires a minimum support count and a privacy review. Sources: [ListenBrainz terms](https://listenbrainz.org/terms-of-service/) and [ListenBrainz dump documentation](https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html).

The first graph should contain artist audience counts, artist pair co-listener counts, sequential transition counts, and time bounded genre audience counts. Each aggregate records its population, time window, minimum support, and whether repeat listens were capped per user.

### Stage O4: genre candidates

The first candidate method starts from approved genre labels. It builds artist evidence from direct tags, Wikidata claims, and listener enrichment. A second experiment can find unlabeled communities from the artist co-listener graph.

Every candidate has a review state. A reviewer can accept, reject, merge, split, or rename it. The review record includes reasons and supporting artists. No automatic cluster becomes a published genre without a recorded rule or review.

### Stage O5: artist membership

The baseline keeps source facets separate. It reports direct tag evidence, hierarchy evidence,
listener enrichment, and graph proximity. It does not hide them in one score.

A later scored run can combine normalized facets. The run records all weights and missing value behavior. It publishes both the total and every component. An artist can belong to several genres.

### Stage O6: genre similarity

OpenNoise should publish two independent neighbor lists before it publishes a blend.

The cultural list uses weighted artist membership and listener overlap. Candidate measures are weighted cosine, weighted Jaccard, and positive pointwise mutual information with support shrinkage. The acoustic list uses standardized genre feature distributions rather than only a mean. Candidate distances are cosine over means, Wasserstein distance per feature, and a regularized covariance distance.

A blended list is a separate run. Its weights are explicit and reviewable.

### Stage O8: layout

The first axis layout uses open estimates of bounciness and organism because those axes reproduce the disclosed design. The feature definitions must be versioned. If open features cannot reproduce the Echo Nest metrics, the field names must say `bounciness_estimate` and `organism_estimate`.

Other layouts are separate lenses. Useful candidates are principal component analysis over standardized features, multidimensional scaling over the combined distance matrix, UMAP over genre vectors, a force layout over the neighbor graph, and a hyperbolic view for hierarchy. No layout replaces the evidence graph.

The label solver runs after semantic coordinates are fixed. It minimizes overlap and displacement, then records both semantic and display coordinates.

### Stage O9: representative artists, albums, and tracks

The genre page needs several lists with different purposes.

The central artist list ranks strong membership with a diversity cap. The defining album list ranks release groups using direct genre evidence, artist membership, audience distinctiveness, historical importance evidence when available, and reviewer judgments. The central track list ranks recordings by artist membership, direct tags, audience distinctiveness, and optional acoustic fit.

No popularity field can silently stand in for genre fit. Each list has its own versioned run and evidence links.

### Stage O10: sample and link resolution

The application stores links separately from playable media. MusicBrainz URL relationships can provide official sites, purchase pages, streaming pages, Bandcamp, SoundCloud, and other entity specific destinations. ListenBrainz can expose resolved recording metadata and external origins. Jamendo can supply licensed streams for tracks whose license permits the requested use. FMA can supply evaluation audio under each track's license.

OpenNoise should not proxy a third party preview unless its policy permits that use. A sample control should prefer an approved playable asset, then an approved embed, then an external link. It should always name the source and availability time.

### Stage O11: publication

Each published run records source snapshot IDs, code revision, parameters, random seed, content hash, point count, bounds, evaluation metrics, and review state. Historical and open runs use different layout keys and different UI lenses.

## Experiments for unknown transformations

Experiments can narrow the unknowns without claiming to recover private code.

### Coordinate experiment

Crosswalk historical genres to open metadata evidence, then fit only on a training split and
predict historical x and y on held out genres. The experiment may use metadata graph features but
must not add audio or audio-derived inputs.

Compare monotonic linear regression, spline regression, partial least squares, random forest regression, and a small regularized neural model. Report R squared, mean absolute pixel error, rank correlation for each axis, and neighborhood preservation. A strong result shows that the open features explain the output. It does not prove the original formula.

### Readability experiment

Fit a smooth coordinate model and treat the residual from the historical position as possible label movement. Test whether the residual magnitude grows with text width, local density, font size, and page boundary proximity. Then compare greedy collision removal, simulated annealing, and constrained force adjustment.

Measure overlap count, median displacement, maximum displacement, and preserved neighbor order. Keep the smallest method that explains the observed residual pattern.

### Color experiment

Convert the historical RGB value to perceptual Lab and HSV values. Regress each channel against x,
y, font size, source order, and one dimensional public ranks. Use held out error and permutation
importance. A smooth third variable may explain color, but the UI must label it as fitted until a
primary source identifies it.

### Membership experiment

For genres with archived artist pages, fit candidate membership rules from direct tag counts, tag
specificity, listener enrichment, and artist graph proximity. Evaluate artist recall at the
historical page size, precision from reviewed samples, rank correlation when rank is available,
and stability across source snapshots.

Test cutoffs by genre density rather than one global item count. Compare fixed count, fixed score, score gap, and expected false discovery rate rules.

### Similarity experiment

Rebuild artist-overlap and listening-cooccurrence neighbor lists independently. Compare each list
with historical related genre blocks and local map neighbors. Then search a small grid of blend
weights.

Report recall at 10, normalized discounted cumulative gain, shared neighbor overlap, and performance by broad family, region, era, and evidence volume. Do not optimize only for the global average.

### Representative track experiment

Use the 6,291 observed representative tracks as a historical target. Candidate components are artist membership, track tag fit, audience distinctiveness, acoustic centrality, popularity, availability, age, and duplicate artist penalty.

Evaluate exact top 1 match, top 10 retrieval, artist match, genre reviewer preference, and coverage. The goal is to find a transparent open rule that gives useful samples, not to copy every old choice.

### Playlist experiment

For The Sound baseline, rank tracks by genre fit and acoustic centrality. For Pulse, identify users whose share of listening to the genre is unusually high, then compare their recent track distribution with the global distribution. For Edge, apply a time and popularity eligibility filter before the same distinctiveness score.

Test log odds with an informative prior, positive pointwise mutual information with support shrinkage, and a simple rate ratio with confidence bounds. Record the audience definition, time window, global reference, support floor, and newness rule.

## Candidate baseline formulas

These formulas are experiments, not claims about Every Noise.

For artist `a` and genre `g`, direct tag evidence can be:

```text
tag_fit(a, g) = log(1 + tag_count(a, g)) * inverse_genre_frequency(g)
```

Listener enrichment can be:

```text
listener_fit(a, g) = log_odds(listeners_of_a_in_g, all_listeners_of_a,
                              listeners_in_g, all_listeners)
```

Weighted artist overlap between genres can be:

```text
overlap(g1, g2) = sum_a min(w(a, g1), w(a, g2))
                  / sum_a max(w(a, g1), w(a, g2))
```

A first transparent membership score can test the following weight grid:

```text
membership = wt * tag_fit
           + wl * listener_fit
           + wg * graph_fit
           + wa * audio_fit
```

Test `wt` from 0.4 to 0.8, `wl` from 0.0 to 0.4, `wg` from 0.0 to 0.3, and `wa` from 0.0 to 0.3. Require the weights to sum to one. Include metadata only runs where `wa` is zero and listener free runs where `wl` is zero. Choose no production weights until the review set and held out results exist.

## Evaluation protocol

The historical map is one benchmark, not the definition of truth.

Freeze genre identity groups before splitting. Keep aliases for the same genre in one split. Stratify by broad family, region, era, script, source coverage, historical popularity, and map density. Keep at least 20 percent of crosswalked genres held out until the method is fixed.

Evaluate the following outputs separately:

1. Catalog coverage measures artists, release groups, recordings, links, playable samples, and source diversity per genre.
2. Membership measures historical recall, reviewed precision, calibration, and stability over time.
3. Neighbors measure recall, rank quality, evidence coverage, and reviewer agreement.
4. Layout measures axis correlation, trustworthiness, neighborhood preservation, label overlap, displacement, and repeatability.
5. Discovery measures the share of genres that support the full path from genre to artist to album or track to sample or link to a neighboring genre.

The first user review set should contain 80 genres. It should include major genres, regional forms, older styles, current internet styles, non English names, non Latin scripts, low evidence genres, and dense map regions. For each genre, show the historical output and every open evidence facet without revealing a proposed blended score first. Record pairwise judgments for artist fit, neighbor fit, defining album fit, and representative track fit.

## Data requirements

The current catalog schema already covers many identity, relation, provenance, collection, metric,
and layout needs. The following records still need first class query support or focused tables.

### Genre artist membership observations

Store genre ID, artist ID, source family, source record ID, evidence kind, source count, raw value, normalized value, observed time, provenance ID, policy ID, and optional source rank. Membership observations are append only.

### Scored membership runs

Store method key, method revision, parameters, input hash, source snapshots, seed, status, and review state. Each item stores total score, component scores, rank, cutoff reason, and links to its evidence rows.

### Genre neighbor runs

Store cultural, acoustic, blended, and historical lists as separate methods. Each edge stores direction, score, rank, components, shared support count, source coverage, and evidence links.

### Representative item runs

Store separate runs for artists, release groups, recordings, The Sound, Pulse, and Edge. Each item stores rank, score components, eligibility decision, diversity decision, and evidence links.

### External links and playable assets

Store target entity, relation type, provider, canonical URL, provider ID, territory, observed time, availability status, embed permission, playback permission, expiry when known, provenance, and policy. Do not store a link and an audio asset as the same fact.

### Historical artifact observations

Preserve Every Noise source item ID, source page, page date, source order, display position, color, font size, example text, Spotify IDs, preview URL, and source hash. Keep historical values out of open model fields.

## Required discovery flow

Selecting a genre should not rebuild or replace the map. It should update one stable detail region and keep the selected point visible.

The detail region follows this order:

1. The genre row shows the name, one sample or external play link, and the active historical or open lens.
2. The artist row shows representative and edge artists, with the evidence for each membership available on request.
3. The album row shows defining release groups. Selecting one shows its editions and recordings.
4. The track row shows representative recordings and playable or external links.
5. The neighbor row shows artist-overlap and listening-cooccurrence neighbors separately, with an
   optional explicit blend.

The browser history stores the selected genre URL. A close action restores the prior viewport. Loading, selected, unavailable media, and stale source states must be visible. HTML links complete the path without JavaScript. HTMX can replace named regions and update browser history, but a detail click must not rerender all map points.

## Prioritized implementation backlog

### Priority 0: finish historical preservation

1. Extend the existing Every Noise parser to retain all 6,291 representative track observations and external links from the pinned HTML.
2. Add a bounded archived page fetch manifest for selected genre artist pages, then parse memberships, artist samples, related genres, and playlist IDs.
3. Publish separate historical API responses for genre detail, artists, tracks, links, neighbors, and source evidence.

Stable genre URLs, selection, reset, and browser history were completed in `b905f6d`. The current workspace swap still renders all map points again, so a later detail region must remove that extra work.

### Priority 1: build the open metadata path

1. Import a bounded MusicBrainz catalog slice for the 80 genre review set, including artists, release groups, releases, recordings, URLs, and supplementary tag claims under their own policy.
2. Import Wikidata genre aliases, hierarchy, place, dates, and MusicBrainz crosswalks.
3. Publish direct evidence artist and album lists without a blended score.
4. Resolve legal external play links and report coverage.

### Priority 2: reproduce the first open map

1. Build weighted artist overlap neighbors from direct evidence.
2. Add a small ListenBrainz sample and privacy safe audience aggregates.
3. Estimate bounciness and organism from AcousticBrainz where coverage exists.
4. Generate a versioned axis layout, then apply a separate deterministic label solver.
5. Evaluate the open map against held out historical positions and neighbors.

### Priority 3: add representative music

1. Rank central artists and recordings with visible score components.
2. Rank defining albums at the release group level, with editions kept separate.
3. Build The Sound, Pulse, and Edge approximations as separate collection runs.
4. Add review controls for pairwise artist, album, track, and neighbor judgments.

### Priority 4: find new genres

1. Build an artist graph from public co listening with support and privacy thresholds.
2. Run several fixed community detection baselines and compare their stability.
3. Surface unlabeled candidates with supporting artists and audience evidence.
4. Require recorded human acceptance, rejection, merge, split, and naming decisions.

## Source notes

McDonald's own pages and interviews are the primary record for Every Noise behavior. The Echo Nest patent and research explain methods available to the company, but they do not prove which method a production Every Noise revision used. Later academic and hobby recreations are useful experiment designs, but they are not evidence of the private formula.

The most useful primary sources are:

1. [How We Understand Music Genres](https://furia.com/everynoise_public/EverynoiseIntro.pdf).
2. [Final Every Noise public map](https://furia.com/everynoise_public/engenremap.html).
3. [Every Number at Once and the twelve metrics](https://furia.com/page.cgi?skip=90&tag=listen&type=log).
4. [How to Write a Bug and Deeper Noises at Once](https://www.furia.com/page.cgi?skip=60&type=log).
5. [Spotify for Artists interview](https://artists.spotify.com/blog/how-spotify-discovers-the-genres-of-tomorrow).
6. [McDonald interview on unlabeled listener clusters](https://www.cantgetmuchhigher.com/p/spotifys-former-data-guru-sets-the).
7. [Echo Nest cultural and acoustic similarity patent](https://patents.google.com/patent/US8073854B2/en).
8. [MusicBrainz](https://musicbrainz.org/doc/MusicBrainz_Database/Download), [Wikidata](https://www.wikidata.org/wiki/Help%3AData_access), [ListenBrainz](https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html), and [AcousticBrainz](https://acousticbrainz.org/download) official data documentation.
