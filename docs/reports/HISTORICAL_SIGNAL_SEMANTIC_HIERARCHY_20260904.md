# Historical signal semantic hierarchy candidate

The candidate is stored outside version control at
`.cache/historical-signal-semantic-candidate/historical-signal-semantic-v1.json`.
It covers all 6,291 retained genres from the sealed H3 membership database.

The lower hierarchy is graph-only: deterministic reciprocal-H3 modularity yields 220 natural
subcommunities, then reciprocal graph splitting yields 528 microgenres of at most 24 members.
The overview has 12 broad display regions.  It uses sparse, bounded TF-IDF name heads only after
the H3 communities have been fixed.  Names never affect the H3 kNN graph, edge weights, or layout.
Latin and Caribbean regional heads are kept under one broad source-supported display region; genres
without a repeated broad head are under one explicitly non-taxonomic `Other / unplaced` region.

The final in-process deterministic build reports complete hierarchy coverage, 12 umbrellas, 220
subcommunities, 528 microgenres, and weighted union-H3 edge retention of 0.840945571054,
0.807676691061, and 0.430915523398 respectively.  The largest microgenre has 24 members and each
overview region is no larger than 3,000 members.  The model build executes an independent rerun
before writing; the focused cross-hash-seed unit test also passes.

The coarse nodes use `graph_and_genre_name_derived` provenance.  Subcommunity and microgenre nodes
retain `graph_derived_h3_similarity` provenance.  The report is a display taxonomy evaluation, not
a claim that name families are musical ground truth.
