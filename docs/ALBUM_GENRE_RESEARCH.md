# Album genre evidence and ranking research

Status: research proposal as of 2026-08-30. No model is implemented here.

## Recommendation

Musix should treat album membership and album ranking as two different questions.
Membership asks whether a release group belongs to a genre. Ranking asks which
eligible release groups are the best examples of that genre. A popular album can
rank highly only after it has enough membership evidence.

The MusicBrainz release group should be the album identity. A MusicBrainz release
should represent one edition, territory, format, or reissue. MusicBrainz defines a
release group as the album concept and requires every release to belong to exactly
one group. Its release records hold details such as date, country, label, barcode,
and packaging. See the [MusicBrainz release group documentation](https://musicbrainz.org/doc/Release_Group)
and [release documentation](https://musicbrainz.org/doc/Release).

The first version should use direct MusicBrainz and Wikidata genre claims for
membership. It should use ListenBrainz only for audience evidence. Artist genre
propagation should find candidates, but it should not prove membership on its own.
The first ranking should show separate evidence facets. A single score can be an
optional view after the user chooses and approves its weights.

## What quintessential means

The word can refer to several different qualities. Musix should keep them visible
instead of hiding them in one unexplained number.

1. Genre specificity measures how directly and consistently an album is tagged
   with the genre.
2. Historical importance measures early participation and documented influence.
3. Community consensus measures ratings, reviews, awards, and source agreement.
4. Audience adoption measures whether genre listeners return to the album, while
   controlling for general popularity.

A result can be a strong example without being early, popular, or influential.
Young genres such as hyperpop also change while people argue about their names and
boundaries. Research on Wikipedia's hyperpop debates shows that online genre
formation involves contested definitions and exclusion. See
[Assembling Hyperpop: Genre Formation on Wikipedia](https://academicworks.cuny.edu/gc_pubs/1137/).
Musix should therefore preserve the source, date, and method behind each claim.

## Source and rights review

| Source | Useful fields | Rights and access | MVP decision |
| --- | --- | --- | --- |
| MusicBrainz core dump | Release groups, releases, artist credits, release events, relationships, series, and identifiers | Core data is CC0. The current dump page lists the main database dump as CC0. See [data license](https://musicbrainz.org/doc/About/Data_License) and [download licenses](https://musicbrainz.org/doc/MusicBrainz_Database/Download). | Use first. Store the exact dump name and hash. |
| MusicBrainz supplementary dump or API | Release group genres, free tags, aggregate ratings, tag counts, and rating counts | Supplementary data is CC BY-NC-SA 3.0. Raw editor tags and ratings are excluded from public dumps for privacy. See the [database schema](https://musicbrainz.org/doc/MusicBrainz_Database/Schema) and [API](https://musicbrainz.org/doc/MusicBrainz_API). | Use under a separate noncommercial policy. Never mix its provenance with CC0 core data. |
| Wikidata | Album genre property P136, MusicBrainz release group ID P436, publication date P577, performer P175, statement rank, qualifiers, and references | Structured data in the main and property namespaces is CC0. See [Wikidata licensing](https://www.wikidata.org/wiki/Wikidata:Licensing), [P136](https://www.wikidata.org/wiki/Property:P136), and [P436](https://www.wikidata.org/wiki/Property:P436). | Use first. Missing claims mean unknown, not false. |
| ListenBrainz | Release group listen count, unique listener count, time windows, and mapped release group MBIDs | User listen data and text is CC0. See the [terms](https://listenbrainz.org/terms-of-service/), [data dumps](https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html), and [popularity API](https://listenbrainz.readthedocs.io/en/latest/users/api/popularity.html). | Use for audience features after the direct membership import works. Keep user names transient. |
| CritiqueBrainz | Reviews and ratings linked to MusicBrainz entities | MetaBrainz publishes separate CC BY-SA 3.0 and CC BY-NC-SA 3.0 archives. See the [dataset description](https://metabrainz.org/datasets) and [JSON archive index](https://data.metabrainz.org/pub/musicbrainz/critiquebrainz/json/). | Optional second phase. Keep the two license groups separate. Review counts and ratings are enough for ranking. Review text is not needed. |
| Discogs | Master and release grouping, editions, formats, credits, and catalogue terms such as genre and style | The API mixes CC0 catalogue fields with restricted user, marketplace, and image data. It also limits caching and requires attribution for API display. See the [Discogs API terms](https://support.discogs.com/hc/en-us/articles/360009334593-API-Terms-of-Use). The dump site denied automated inspection during this review. | Defer. Approve each field and exact dump license before import. Do not ingest marketplace, collection, want list, price, sales, or image data. |
| Rate Your Music | Community genre labels, charts, lists, and ratings | No public developer API or open bulk dataset was found. The official terms page blocked automated access during this review. | Do not scrape or ingest. People may use the site when forming their own Musix judgments, but copied charts and ratings must not become source data. |
| Open awards and lists | Award membership, dated list placement, and critic selections | Rights vary by publisher. MusicBrainz supports release group award series as open structured data. See the [MusicBrainz series documentation](https://musicbrainz.org/doc/Series). | Use MusicBrainz series first. Add another list only after its license and exact version are recorded. Do not copy review text. |

Discogs deserves a strict boundary. Its terms name many catalogue fields as CC0,
but genre and style are not separately named in the current CC0 field list. Musix
should not infer that every API field is CC0. It should admit an exact dump only
after a manifest records its license and approved fields.

Rate Your Music is not an MVP source. A missing license is not enough when a site
also restricts automated access. Musix can ask the user for pairwise judgments
that reflect their own knowledge, without copying the site's charts or values.

## Membership evidence

Musix should keep each observation append only. A later snapshot can add or revoke
a claim without rewriting history.

### Direct evidence

MusicBrainz release group genres and positive release group tag counts are direct
community claims. The API exposes genres as tags that match the official genre
list, while broader tags remain available separately. The database dump stores
aggregate tag count and update time, but it does not publish each editor's raw
vote. Musix should retain the raw count, update time, and whether the value came
from the official genre list.

Wikidata P136 on an album is another direct claim. Musix should join the item to a
MusicBrainz release group through P436. It should retain statement rank,
qualifiers, references, and retrieval time. P436 declares that coverage is always
incomplete, so the lack of a join cannot reject an album.

Track or recording genre claims can support a release group when enough of its
track list agrees. The derived observation must include the fraction of eligible
tracks that supplied evidence. One tagged single track should not label a long
album.

### Inferred evidence

Artist genre propagation can find albums that direct sources missed. The method
must consider the credited artist, release date, collaboration role, and whether
the artist changed style over time. Artist membership alone must not establish
album membership.

ListenBrainz can identify albums that a high confidence genre audience listens to
more often than the site average. The method should use unique listeners, cap each
person's contribution, and require a minimum cohort. A release group MBID is
available in mapped listens, and the public API returns total listens and unique
listeners for a release group. See the [ListenBrainz JSON format](https://listenbrainz.readthedocs.io/en/latest/users/json.html).

An eligible album should have one direct release group claim, or agreement from at
least two independent inferred source families. The second rule should remain
conservative until a labeled evaluation set exists. Evidence derived from one
source cannot confirm another result derived from that same source.

## Ranking evidence

Ranking should run only over eligible release groups. Each feature should retain a
raw value and a bounded value used by a ranking view.

| Facet | Explainable features | Main cautions |
| --- | --- | --- |
| Genre specificity | MusicBrainz genre vote count, genre share among all genre tags, direct Wikidata claim, track coverage, and independent source count | A broad tag may be true but not specific. Tagging volume differs by genre. |
| Historical importance | Earliest official release date, distance from the first documented genre use, later cover and remix links, later release group relations, and award series | Early does not mean best. Old work has more time to collect links. Retroactive genre labels can be valid. |
| Community consensus | Bayesian adjusted MusicBrainz rating, rating count, CritiqueBrainz rating and review count, and open award or list placements | Small groups can coordinate votes. Rating cultures differ. Review coverage is sparse and often English centered. |
| Audience adoption | Unique listeners, repeat listener rate, genre cohort lift over global share, and listener diversity | Raw plays favor famous artists and heavy users. ListenBrainz users do not represent all listeners or regions. |

Influence needs a narrow definition. MusicBrainz release group relations cover
remixes, covers, live versions, re-recordings, and inclusion. See the
[release group relationship guide](https://musicbrainz.org/doc/Artist_Relationship_Guide_for_Artists).
Musix can also count later linked works or artists, but every count needs age and
popularity controls. A general graph connection is not proof of musical influence.

No run should silently rescale around missing data. Each result should show which
features were absent and its evidence coverage. The UI can say, for example,
"direct tags and audience evidence are present, but no review evidence is
available."

## Edition and reissue rules

Musix should rank a release group once. It should choose a representative release
for display, based on official status, completeness, territory preference, and
cover availability. MusicBrainz also publishes a CC0 canonical release mapping,
which can supply a reproducible default. See the
[canonical MusicBrainz data documentation](https://musicbrainz.org/doc/Canonical_MusicBrainz_data).

Deluxe editions, remasters, bonus editions, and format changes normally stay in
the same release group. Remix albums, covers, live albums, and studio
re-recordings can be separate groups. The [MusicBrainz release group style guide](https://musicbrainz.org/doc/Style/Release_Group)
defines these cases. Musix should keep their relations and allow a view to include
or exclude each type.

Compilations need an explicit rule. Artist album views should exclude compilations
by default. A genre view can include a compilation when it has direct genre
evidence, because a compilation can document a scene. The result must display its
type.

The historical date should be the earliest official release event known for the
group, with its date precision and territory. A reissue date must not replace the
original date. Redirected or merged MusicBrainz IDs must resolve before feature
calculation.

## Bias and failure risks

Popularity is the largest scoring risk. Raw listen count, rating count, link
degree, and review count all rise with fame. Musix should use logarithms or bounded
percentiles, compare audience share within a genre cohort, and keep popularity as
a visible component. Research has found popularity and exposure bias in music
recommendation. See [Unfair Exposure of Artists in Music Recommendation](https://arxiv.org/abs/2003.11634)
and [Exploring Artist Gender Bias in Music Recommendation](https://arxiv.org/abs/2009.01715).

Regional and language coverage is another risk. English names, Western press,
MusicBrainz editing activity, Wikidata coverage, and ListenBrainz adoption vary by
region. Evaluation must report results by region, language, script, and evidence
volume. Missing coverage must not become a negative feature.

Recency can work in both directions. New albums lack long term links and reviews,
while current streaming can favor them. Every ranking should offer a time window
and an as of date. Young internet genres need a recent window and a separate all
time view.

Gaming is possible in tags, ratings, and listens. Musix should use minimum support,
unique contributors where available, per user caps for listening aggregates, and
snapshot comparisons for sudden changes. The public MusicBrainz dump does not
include raw voters, so strong anti gaming claims are not possible there.

Circularity can create false confidence. For example, an artist genre tag can
generate album candidates, and a listener cohort made from those same albums can
then appear to confirm them. Musix must record each feature's source family and
candidate generation path. Evaluation labels must not come from a source used as
an input feature.

Cold start affects new and regional albums. Direct creator or editor claims can
admit an album before it has many listens or reviews. A ranking can show an
"emerging" facet based on direct evidence and recent audience lift, without
pretending that it has measured long term influence.

## Ranked MVP approach

1. Import MusicBrainz core release groups, releases, artist credits, release
   events, types, identifiers, redirects, and release group relationships. Import
   supplementary release group genres, tags, and aggregate ratings under their
   separate license policy.
2. Import Wikidata album P136 claims joined through P436. Preserve statement rank,
   references, and time. Resolve genre aliases through reviewed source identifiers,
   not a name match alone.
3. Publish membership observations. Admit a candidate through one direct album
   claim. Put artist propagation and track aggregation in a review queue until
   their thresholds have been evaluated.
4. Add bounded ListenBrainz release group features from exact full snapshots. Use
   unique listener counts first. Delay user level collaborative features until the
   privacy, support, and evaluation rules are fixed.
5. Show four facet scores and evidence coverage. Add an optional weighted rank only
   after the user approves the weights. Freeze the method version, configuration,
   source hashes, and membership snapshot for every published run.

The first weighted baseline can use the following review parameters if the user
wants one list. Genre specificity gets 30 percent. Independent source agreement
gets 20 percent. Audience adoption gets 20 percent. Community consensus gets 15
percent. Historical influence gets 15 percent. The values are starting settings,
not learned truth. Missing values should contribute zero and reduce coverage,
rather than causing the remaining values to be silently rescaled.

## Candidate data contract

The existing provenance and rights tables remain authoritative. Migration 0002
implements the smaller working contract described in `docs/EXPERIMENTS.md`. The
SQL below is the earlier research sketch, so it is not the authoritative schema.

```sql
CREATE TABLE genre_membership_observations (
    id INTEGER PRIMARY KEY,
    release_group_id INTEGER NOT NULL REFERENCES release_groups(id),
    genre_id INTEGER NOT NULL REFERENCES genres(id),
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN (
        'direct_release_group_tag',
        'direct_wikidata',
        'derived_track_coverage',
        'inferred_artist',
        'inferred_listening'
    )),
    source_family TEXT NOT NULL,
    raw_support REAL,
    raw_total REAL,
    confidence REAL CHECK (confidence BETWEEN 0.0 AND 1.0),
    method_key TEXT NOT NULL,
    method_version TEXT NOT NULL,
    config_sha256 TEXT NOT NULL CHECK (length(config_sha256) = 64),
    observed_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    provenance_id INTEGER NOT NULL REFERENCES provenance_records(id),
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id),
    record_fingerprint TEXT NOT NULL UNIQUE CHECK (length(record_fingerprint) = 64)
) STRICT;

CREATE TABLE album_genre_ranking_runs (
    id INTEGER PRIMARY KEY,
    run_ref TEXT NOT NULL UNIQUE,
    method_key TEXT NOT NULL,
    method_version TEXT NOT NULL,
    config_json TEXT NOT NULL CHECK (json_valid(config_json)),
    config_sha256 TEXT NOT NULL CHECK (length(config_sha256) = 64),
    input_fingerprint TEXT NOT NULL CHECK (length(input_fingerprint) = 64),
    membership_snapshot_fingerprint TEXT NOT NULL
        CHECK (length(membership_snapshot_fingerprint) = 64),
    policy_id INTEGER NOT NULL REFERENCES rights_policies(id),
    status TEXT NOT NULL CHECK (status IN ('running', 'published', 'failed')),
    created_at TEXT NOT NULL,
    published_at TEXT
) STRICT;

CREATE TABLE album_genre_rankings (
    run_id INTEGER NOT NULL REFERENCES album_genre_ranking_runs(id),
    genre_id INTEGER NOT NULL REFERENCES genres(id),
    release_group_id INTEGER NOT NULL REFERENCES release_groups(id),
    rank INTEGER NOT NULL CHECK (rank > 0),
    score REAL NOT NULL CHECK (score BETWEEN 0.0 AND 1.0),
    membership_confidence REAL NOT NULL
        CHECK (membership_confidence BETWEEN 0.0 AND 1.0),
    evidence_coverage REAL NOT NULL CHECK (evidence_coverage BETWEEN 0.0 AND 1.0),
    components_json TEXT NOT NULL CHECK (json_valid(components_json)),
    explanation_json TEXT NOT NULL CHECK (json_valid(explanation_json)),
    PRIMARY KEY (run_id, genre_id, release_group_id),
    UNIQUE (run_id, genre_id, rank)
) STRICT;

CREATE TABLE album_genre_feature_values (
    run_id INTEGER NOT NULL REFERENCES album_genre_ranking_runs(id),
    genre_id INTEGER NOT NULL REFERENCES genres(id),
    release_group_id INTEGER NOT NULL REFERENCES release_groups(id),
    feature_key TEXT NOT NULL,
    raw_value REAL,
    bounded_value REAL CHECK (bounded_value BETWEEN 0.0 AND 1.0),
    is_missing INTEGER NOT NULL CHECK (is_missing IN (0, 1)),
    evidence_ids_json TEXT NOT NULL CHECK (json_valid(evidence_ids_json)),
    PRIMARY KEY (run_id, genre_id, release_group_id, feature_key),
    CHECK ((raw_value IS NULL) = (is_missing = 1))
) STRICT;
```

Feature values need a pair key because the value describes an album in a genre,
not an album alone. A narrow table can store one value per run, genre, release
group, and feature key. The ranking row should point to evidence record IDs in its
explanation JSON. It should never contain copied review text.

The migration should add update and delete rejection triggers to membership
observations, runs, results, and feature values after a run is published. A failed
run should remain available for audit, while the public query reads published runs
only.

An API or JSONL result should follow this shape:

```json
{
  "genre_id": 42,
  "release_group_id": 9102,
  "rank": 3,
  "score": 0.78,
  "membership_confidence": 0.92,
  "evidence_coverage": 0.75,
  "components": {
    "specificity": 0.91,
    "source_agreement": 0.80,
    "audience": 0.62,
    "consensus": 0.71,
    "influence": 0.69
  },
  "explanation": {
    "summary": "Two direct genre sources agree. Genre listeners return to this album more often than the site average.",
    "evidence_ids": [1201, 1204, 1308],
    "missing_features": ["open_award_count"]
  },
  "run_ref": "album_genre_rank:facets_v1:2026-08-30",
  "config_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "input_fingerprint": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "policy_id": 7
}
```

## Current schema and adapter gaps

The initial schema has useful foundations. It already separates release groups and
releases, stores partial release dates by territory, keeps append only provenance,
and applies rights policies. It also has generic descriptor observations, metrics,
collections, relations, and derived outputs.

The following gaps block this feature:

1. The MusicBrainz adapter imports artists and artist genres only. It does not
   import release groups, releases, release events, artist credits, redirects,
   release group tags, ratings, types, series, or release group relations.
2. The Wikidata adapter imports genre items and hierarchy only. It does not parse
   album P136, P436, P577, P175, statement references, or qualifiers.
3. The ListenBrainz adapter aggregates artist cooccurrence only. It discards
   recording, release, and release group MBIDs. It has no release group listener
   counts, genre cohort aggregates, or per person contribution cap for albums.
4. `descriptor_observations` stores a normalized weight and rank, but it cannot
   clearly store raw support, a denominator, direct versus inferred evidence, a
   source family, or a method version. `metric_observations` is keyed to one
   entity, so it cannot represent a release group and genre pair.
5. No relation type links release groups to genres. The generic relation table can
   hold one after a new type is defined, but properties JSON is too loose for the
   evidence contract. No release group influence relations are seeded either.
6. `derived_outputs` can identify a produced file or object, but there are no
   structured ranking run, feature value, or ranking result rows. There is also no
   user judgment or evaluation set table.
7. The schema has no reviewed crosswalk confidence between Every Noise genres,
   MusicBrainz genre tags, and Wikidata genre items. Name or slug equality must not
   create a cross source identity claim by itself.
8. There is no stored representative release choice for a release group.
   `catalog_availability` correctly applies to concrete releases and recordings,
   but a ranking result still needs a stable display release.

Collections can represent open charts, awards, and lists, while collection items
can preserve their position. Their provenance must identify the exact publication
date and license. The generic tables should not be used to hide a source whose
terms do not allow ingestion.

## Evaluation plan

Membership and ranking require separate evaluation sets. Membership labels should
be `yes`, `no`, `uncertain`, or `mixed`. Ranking labels should use tiers or pairwise
preferences, because people rarely agree on an exact order.

The coverage set should contain at least 96 genres across 16 broad families. It
should include old and new genres, large and small catalogues, several scripts,
and several regions. At least 24 genres should be internet or post 2015 genres,
and at least 24 should be regional or mainly non English genres. Hyperpop,
digicore, dariacore, pluggnb, rage, and drift phonk are candidate young genres,
but the final list should follow a source coverage audit rather than current name
recognition.

Each genre should have 20 to 40 candidates. Hard negatives should include a famous
album by the same artist in another style, an adjacent genre album, a popular but
nonspecific album, a compilation, and a reissue. Two reviewers should label a
smaller gold subset. The user can start with 32 genres and 12 albums per genre,
then add difficult cases as disagreements appear.

Membership reports should include macro precision, recall, F1, abstention, and
coverage. Ranking reports should include pairwise accuracy, normalized discounted
cumulative gain at 10, top tier recall at 10, and stability between source
snapshots. Every report should split results by era, region, language or script,
evidence volume, popularity band, and young genre status.

The test split must keep all editions of a release group together. It should also
hold out artists, so albums by the same artist cannot leak across training and
test. A second split should hold out whole genres to test whether a learned method
works outside the genres used for training. A time split is useful only when input
snapshots preserve historical state. Current aggregate tag dumps cannot recreate
past votes without archived snapshots.

Reviewers should see evidence cards before they see the system order. This reduces
anchoring. Rate Your Music and any other ranking source used as a feature must not
also supply evaluation labels.

## Decisions for the user

### Option 1: Evidence facets only

Musix shows eligible albums with genre specificity, history, consensus, audience,
and coverage. The user sorts by a facet and sees the evidence. There is no single
claim about the definitive order. This option is the safest first release.

### Option 2: Transparent weighted rank

Musix publishes one default order from the five visible components. The user
reviews the proposed 30, 20, 20, 15, and 15 percent weights before they become a
versioned configuration. The UI can offer saved weight presets without changing
the raw evidence. This option is the recommended MVP when the product needs a
ranked list.

### Option 3: User trained pairwise rank

The user compares two eligible albums at a time. Musix later fits a small linear
or pairwise ranking model on the laptop and shows its coefficients. Whole genres
and artists remain held out for evaluation. This option directly supports learning
about ranking models, but it should follow the evidence baseline and evaluation
set. Neural embeddings are not required for this task.

## Next decision

The user should choose whether the first product view has no combined score or a
transparent weighted score. Data ingestion can start before that choice because
the membership observations, raw features, provenance, and evaluation labels are
shared by all three options.
