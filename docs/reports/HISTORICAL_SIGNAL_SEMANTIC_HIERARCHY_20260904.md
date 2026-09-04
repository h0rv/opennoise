# Historical signal semantic hierarchy candidate

The candidate is stored outside version control at
`.cache/historical-signal-semantic-candidate/historical-signal-semantic-v1.json`.
It covers all 6,291 retained genres from the sealed H3 membership database.

Broad-family seeds are assigned from each genre's own explicit lexical head.  Only unseeded genres
propagate a family over weighted H3 neighbors when one family has at least 60% of available support;
the rest remain explicitly `Other / unplaced`.  The lower hierarchy is then graph-only inside each
family: induced H3 graph regions are bounded to 64 members, then split to microgenres of at most 24.
Names never affect the H3 kNN graph, edge weights, layout, or lower-level clustering.

The final in-process deterministic build reports complete hierarchy coverage, 13 umbrellas, 132
subcommunities, and 496 microgenres.  Weighted union-H3 edge retention at those levels is
0.690000147561, 0.390932068948, and 0.283401074343 respectively.  Every family with more than 64
members has at least two level-one drill-down cohorts.  The largest microgenre has 24 members and each
overview region is no larger than 3,000 members.  Level-one labels prefer an explicit lexical seed that
matches their display-family parent whenever that cohort contains one, before applying deterministic
H3-centrality and genre-ID tie-breaking.  The model build executes an independent rerun before writing;
the focused cross-hash-seed unit test also passes.

The coarse nodes use `graph_and_genre_name_derived` provenance.  Subcommunity and microgenre nodes
retain `graph_derived_h3_similarity` provenance, conditioned on their already-selected display
family.  The report is a display taxonomy evaluation, not a claim that name families are musical
ground truth.
