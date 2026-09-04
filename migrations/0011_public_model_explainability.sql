PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

-- The sealed Phase 3 cache remains schema 10.  This serving-only projection is
-- deliberately a later migration: it persists the already-approved model's
-- explanations without mutating the cache that release-manifest verification
-- attests to.
CREATE TABLE public_genre_profile_memberships (
    model_run_id INTEGER NOT NULL REFERENCES public_model_runs(id) ON DELETE RESTRICT,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    profile_kind TEXT NOT NULL CHECK (profile_kind IN ('direct', 'one_hop')),
    source_artist_ref TEXT NOT NULL,
    score REAL NOT NULL CHECK (score > 0.0 AND score <= 1.0),
    evidence_refs_json TEXT NOT NULL
        CHECK (json_valid(evidence_refs_json) AND json_type(evidence_refs_json) = 'array'),
    components_json TEXT NOT NULL
        CHECK (json_valid(components_json) AND json_type(components_json) = 'array'),
    PRIMARY KEY (model_run_id, genre_id, profile_kind, source_artist_ref),
    CHECK (length(trim(source_artist_ref)) > 0)
) STRICT;

CREATE TABLE public_genre_neighbors (
    model_run_id INTEGER NOT NULL REFERENCES public_model_runs(id) ON DELETE RESTRICT,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    neighbor_genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    profile_kind TEXT NOT NULL CHECK (profile_kind IN ('direct', 'one_hop')),
    metric TEXT NOT NULL CHECK (metric IN ('weighted_jaccard', 'cosine')),
    score REAL NOT NULL CHECK (score > 0.0 AND score <= 1.0),
    shared_artist_count INTEGER NOT NULL CHECK (shared_artist_count > 0),
    rank INTEGER NOT NULL CHECK (rank > 0),
    PRIMARY KEY (model_run_id, genre_id, profile_kind, metric, rank),
    UNIQUE (model_run_id, genre_id, neighbor_genre_id, profile_kind, metric),
    CHECK (genre_id != neighbor_genre_id)
) STRICT;

CREATE INDEX public_genre_profile_memberships_genre_idx
    ON public_genre_profile_memberships(model_run_id, genre_id, profile_kind, score DESC);

CREATE INDEX public_genre_neighbors_genre_idx
    ON public_genre_neighbors(model_run_id, genre_id, profile_kind, metric, rank);

CREATE VIEW displayable_public_genre_profile_memberships AS
SELECT membership.*
FROM current_public_models AS current
JOIN servable_public_model_runs AS run ON run.id = current.model_run_id
JOIN public_genre_profile_memberships AS membership ON membership.model_run_id = run.id
WHERE current.model_key = 'public-graph'
  AND NOT EXISTS (
      SELECT 1 FROM active_suppressions AS suppression
      WHERE suppression.target_kind = 'entity'
        AND suppression.target_ref = CAST(membership.genre_id AS TEXT)
        AND suppression.use_kind IN ('all', 'display')
  );

CREATE VIEW displayable_public_genre_neighbors AS
SELECT neighbor.*
FROM current_public_models AS current
JOIN servable_public_model_runs AS run ON run.id = current.model_run_id
JOIN public_genre_neighbors AS neighbor ON neighbor.model_run_id = run.id
WHERE current.model_key = 'public-graph'
  AND NOT EXISTS (
      SELECT 1 FROM active_suppressions AS suppression
      WHERE suppression.target_kind = 'entity'
        AND suppression.target_ref IN (
            CAST(neighbor.genre_id AS TEXT), CAST(neighbor.neighbor_genre_id AS TEXT)
        )
        AND suppression.use_kind IN ('all', 'display')
  );

CREATE TRIGGER public_genre_profile_memberships_are_immutable
BEFORE UPDATE ON public_genre_profile_memberships
BEGIN SELECT RAISE(ABORT, 'public profile memberships are immutable'); END;

CREATE TRIGGER public_genre_profile_memberships_cannot_be_deleted
BEFORE DELETE ON public_genre_profile_memberships
BEGIN SELECT RAISE(ABORT, 'public profile memberships are immutable'); END;

CREATE TRIGGER public_genre_neighbors_are_immutable
BEFORE UPDATE ON public_genre_neighbors
BEGIN SELECT RAISE(ABORT, 'public genre neighbors are immutable'); END;

CREATE TRIGGER public_genre_neighbors_cannot_be_deleted
BEFORE DELETE ON public_genre_neighbors
BEGIN SELECT RAISE(ABORT, 'public genre neighbors are immutable'); END;

PRAGMA user_version = 11;

COMMIT;
