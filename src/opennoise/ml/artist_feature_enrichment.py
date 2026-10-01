"""Sparse source associations proposing inferred artist features, never native facts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from pydantic import TypeAdapter
from scipy import sparse

from opennoise.analysis.emergent_topic_holdout import musical_value
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REVISION = "source-artist-feature-enrichment-v1"
MAX_ARTISTS = 250_000
MAX_FEATURES = 30_000
MAX_OBSERVATIONS = 5_000_000
MAX_ROW_FEATURES = 512
MAX_BATCH = 256
MAX_RANK = 100
MAX_ASSOCIATIONS = 4_000_000
MAX_PAIR_OBSERVATIONS = 50_000_000
MAX_SMOOTHING = 1000
MAX_GENRE_BOOST = 10
MAX_NEIGHBORS = 256
EXPLANATION_CUE_LIMIT = 5
EXPLANATION_REFERENCE_LIMIT = 16


@dataclass(frozen=True)
class EnrichmentSettings:
    """Prespecified regularization, source degree, and sparse neighbor bounds."""

    smoothing: float = 16
    rarity_power: float = 0.15
    degree_power: float = 0.5
    genre_boost: float = 2
    minimum_joint_support: int = 2
    neighbors_per_cue: int = 128

    def __post_init__(self) -> None:
        """Reject nonfinite or unbounded research settings."""
        numbers = (self.smoothing, self.rarity_power, self.degree_power, self.genre_boost)
        if not all(np.isfinite(number) for number in numbers):
            raise ValueError("enrichment settings must be finite")
        if not 0 < self.smoothing <= MAX_SMOOTHING or not 0 <= self.rarity_power <= 1:
            raise ValueError("invalid smoothing or rarity correction")
        if not 0 <= self.degree_power <= 1 or not 0 < self.genre_boost <= MAX_GENRE_BOOST:
            raise ValueError("invalid degree correction or genre cue boost")
        if (
            not 1 <= self.minimum_joint_support <= MAX_SMOOTHING
            or not 1 <= self.neighbors_per_cue <= MAX_NEIGHBORS
        ):
            raise ValueError("association support or neighbor bound exceeded")


def read_profiles(path: Path) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Collapse all source facets/votes to canonical music values before fitting."""
    profiles: dict[str, tuple[str, ...]] = {}
    proper: dict[str, tuple[str, ...]] = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = TypeAdapter(dict[str, object]).validate_json(line)
            artist = str(row["artist_mbid"])
            if not artist or artist in profiles:
                raise ValueError("artist feature identities must be unique and nonempty")
            values: set[str] = set()
            genres: set[str] = set()
            for feature in TypeAdapter(list[dict[str, object]]).validate_python(row["features"]):
                weight = float(cast("float", feature.get("weight", 1)))
                if not np.isfinite(weight) or weight <= 0 or not feature.get("evidence_refs"):
                    raise ValueError(
                        "features require positive finite weight and source references"
                    )
                value = musical_value(feature)
                if value is not None:
                    values.add(value)
                    if feature["namespace"] == "artist_genre":
                        genres.add(value)
            profiles[artist] = tuple(sorted(values))
            proper[artist] = tuple(sorted(genres))
    return profiles, proper


def _matrix(
    artists: Sequence[str], profiles: Mapping[str, Sequence[str]], vocabulary: Sequence[str]
) -> sparse.csr_matrix:
    index = {value: column for column, value in enumerate(vocabulary)}
    rows, columns = [], []
    for row, artist in enumerate(artists):
        values = set(profiles.get(artist, ()))
        if len(values) > MAX_ROW_FEATURES:
            raise ValueError("artist profile exceeds the explicit feature bound")
        for value in sorted(values):
            if value in index:
                rows.append(row)
                columns.append(index[value])
    return sparse.csr_matrix(
        (np.ones(len(rows)), (rows, columns)), shape=(len(artists), len(vocabulary))
    )


@dataclass
class EnrichmentModel:
    """Train-only bounded associations with aligned support counts and source binding."""

    settings: EnrichmentSettings
    vocabulary: tuple[str, ...]
    genres: tuple[str, ...]
    associations: sparse.csr_matrix
    joint_support: sparse.csr_matrix
    cue_support: np.ndarray
    target_support: np.ndarray
    training_sha256: str
    training_artist_count: int
    model_sha256: str = ""

    @cached_property
    def value_index(self) -> dict[str, int]:
        """Cache the immutable model vocabulary for explanation lookup."""
        return {value: column for column, value in enumerate(self.vocabulary)}

    @cached_property
    def cue_index(self) -> dict[tuple[str, str], int]:
        """Cache canonical musical and distinct proper-genre cue positions."""
        return {
            **{("music", value): column for column, value in enumerate(self.vocabulary)},
            **{
                ("proper_genre", value): len(self.vocabulary) + column
                for column, value in enumerate(self.genres)
            },
        }

    def rank_batch(
        self,
        profiles: Mapping[str, Sequence[str]],
        proper: Mapping[str, Sequence[str]],
        *,
        limit: int = 10,
    ) -> dict[str, tuple[str, ...]]:
        """Rank at most 256 profiles, exclude every observed value, and abstain when cold."""
        if len(profiles) > MAX_BATCH or not 1 <= limit <= MAX_RANK:
            raise ValueError("prediction batch or rank limit exceeded")
        if any(set(proper.get(artist, ())) - set(values) for artist, values in profiles.items()):
            raise ValueError("prediction genre cues must be observed musical values")
        artists = tuple(sorted(profiles))
        observed = _matrix(artists, profiles, self.vocabulary)
        cues = sparse.hstack(
            (observed, self.settings.genre_boost * _matrix(artists, proper, self.genres)),
            format="csr",
        )
        scores = (cues @ self.associations).tocsr()
        rankings: dict[str, tuple[str, ...]] = {}
        for row, artist in enumerate(artists):
            start, end = scores.indptr[row : row + 2]
            columns, values = scores.indices[start:end], scores.data[start:end]
            known = set(profiles[artist])
            eligible = np.array(
                [i for i, column in enumerate(columns) if self.vocabulary[column] not in known],
                dtype=np.int64,
            )
            if len(eligible) > limit:
                cutoff = np.partition(values[eligible], -limit)[-limit]
                eligible = eligible[values[eligible] >= cutoff]
            selected = eligible[np.lexsort((columns[eligible], -values[eligible]))[:limit]]
            rankings[artist] = tuple(self.vocabulary[columns[i]] for i in selected)
        return rankings

    def proposals(self, row: Mapping[str, object], *, limit: int = 10) -> list[dict[str, object]]:
        """Explain each inferred proposal using observed source cues and train-only counts."""
        return self.proposal_batch([row], limit=limit)[str(row["artist_mbid"])]

    def proposal_batch(
        self, rows: Sequence[Mapping[str, object]], *, limit: int = 10
    ) -> dict[str, list[dict[str, object]]]:
        """Rank one bounded batch and explain only each profile's observed sparse cues."""
        if len(rows) > MAX_BATCH:
            raise ValueError("proposal batch exceeds the explicit artist bound")
        parsed = {str(row["artist_mbid"]): self._query_cues(row) for row in rows}
        if len(parsed) != len(rows):
            raise ValueError("proposal batch repeats an artist identity")
        ranked = self.rank_batch(
            {artist: tuple(refs) for artist, (refs, _) in parsed.items()},
            {artist: tuple(genres) for artist, (_, genres) in parsed.items()},
            limit=limit,
        )
        return {
            artist: self._explain(refs, genres, ranked[artist])
            for artist, (refs, genres) in parsed.items()
        }

    @staticmethod
    def _query_cues(row: Mapping[str, object]) -> tuple[dict[str, set[str]], set[str]]:
        features = TypeAdapter(list[dict[str, object]]).validate_python(row["features"])
        references: dict[str, set[str]] = {}
        genres: set[str] = set()
        for feature in features:
            if (value := musical_value(feature)) is not None:
                references.setdefault(value, set()).update(
                    TypeAdapter(list[str]).validate_python(feature["evidence_refs"])
                )
                if feature["namespace"] == "artist_genre":
                    genres.add(value)
        return references, genres

    def _explain(
        self, references: dict[str, set[str]], genres: set[str], ranked: Sequence[str]
    ) -> list[dict[str, object]]:
        cue_values = [("music", value) for value in sorted(references)] + [
            ("proper_genre", value) for value in sorted(genres)
        ]
        result: list[dict[str, object]] = []
        for value in ranked:
            column = self.value_index[value]
            evidence = []
            for kind, known in cue_values:
                cue = self.cue_index.get((kind, known))
                if cue is None:
                    continue
                score = float(self.associations[cue, column])
                if score > 0:
                    contribution = score * (
                        self.settings.genre_boost if kind == "proper_genre" else 1
                    )
                    evidence.append(
                        {
                            "cue_role": kind,
                            "value": known,
                            "query_evidence_refs": sorted(references[known])[
                                :EXPLANATION_REFERENCE_LIMIT
                            ],
                            "query_evidence_ref_count": len(references[known]),
                            "training_joint_artist_support": int(self.joint_support[cue, column]),
                            "training_cue_artist_support": int(self.cue_support[cue]),
                            "score_contribution": contribution,
                        }
                    )
            evidence.sort(key=lambda entry: -float(cast("float", entry["score_contribution"])))
            result.append(
                {
                    "feature_id": f"music:{value}",
                    "value": value,
                    "role": "inferred_feature_proposal",
                    "score_calibrated": False,
                    "native_fact": False,
                    "score": sum(
                        float(cast("float", item["score_contribution"])) for item in evidence
                    ),
                    "training_target_artist_support": int(self.target_support[column]),
                    "training_source_sha256": self.training_sha256,
                    "training_input_sha256": self.training_sha256,
                    "source_model_sha256": self.model_sha256,
                    "contributing_cue_count": len(evidence),
                    "explanation_cue_limit": EXPLANATION_CUE_LIMIT,
                    "evidence": evidence[:EXPLANATION_CUE_LIMIT],
                }
            )
        return result


def fit_enrichment(
    profiles: Mapping[str, Sequence[str]],
    proper: Mapping[str, Sequence[str]],
    *,
    settings: EnrichmentSettings | None = None,
    training_sha256: str = "in-memory-research-fixture",
) -> EnrichmentModel:
    """Fit degree-normalized, shrunk conditional associations using training facts only."""
    resolved = settings or EnrichmentSettings()
    artists = tuple(sorted(profiles))
    vocabulary = tuple(sorted({value for values in profiles.values() for value in values}))
    genres = tuple(sorted({value for values in proper.values() for value in values}))
    if len(artists) > MAX_ARTISTS or len(vocabulary) > MAX_FEATURES:
        raise ValueError("enrichment training identity bound exceeded")
    if set(proper) - set(profiles) or any(
        set(proper.get(a, ())) - set(profiles[a]) for a in artists
    ):
        raise ValueError("proper genre cues must be a subset of retained musical observations")
    observed = _matrix(artists, profiles, vocabulary)
    if observed.nnz > MAX_OBSERVATIONS:
        raise ValueError("enrichment training observation bound exceeded")
    cues = sparse.hstack((observed, _matrix(artists, proper, genres)), format="csr")
    degree = np.asarray(observed.sum(axis=1)).ravel()
    if np.sum(degree * np.asarray(cues.sum(axis=1)).ravel()) > MAX_PAIR_OBSERVATIONS:
        raise ValueError("enrichment pair-count work bound exceeded before sparse multiplication")
    correction = 1 / np.maximum(1, degree) ** resolved.degree_power
    weighted = (cues.T @ sparse.diags(correction) @ observed).tocsr()
    joints = (cues.T @ observed).tocsr()
    cue_support = np.asarray(cues.sum(axis=0)).ravel()
    cue_mass = np.asarray(cues.T @ correction).ravel()
    support = np.asarray(observed.sum(axis=0)).ravel()
    prior = support / max(1, len(artists))
    rows, columns, scores, counts = [], [], [], []
    for cue in range(cues.shape[1]):
        start, end = weighted.indptr[cue : cue + 2]
        candidates = weighted.indices[start:end]
        raw = weighted.data[start:end]
        joint = np.asarray(joints[cue, candidates].toarray()).ravel()
        keep = joint >= resolved.minimum_joint_support
        candidates, raw, joint = candidates[keep], raw[keep], joint[keep]
        # The prior only regularizes observed associations; it never invents a dense edge.
        values = (
            (raw + resolved.smoothing * prior[candidates])
            / (cue_mass[cue] + resolved.smoothing)
            / np.maximum(prior[candidates], 1 / max(1, len(artists))) ** resolved.rarity_power
        )
        selected = np.lexsort((candidates, -values))[: resolved.neighbors_per_cue]
        for position in selected:
            rows.append(cue)
            columns.append(int(candidates[position]))
            scores.append(float(values[position]))
            counts.append(float(joint[position]))
    if len(rows) > MAX_ASSOCIATIONS:
        raise ValueError("enrichment sparse association bound exceeded")
    shape = (len(vocabulary) + len(genres), len(vocabulary))
    return EnrichmentModel(
        resolved,
        vocabulary,
        genres,
        sparse.csr_matrix((scores, (rows, columns)), shape=shape),
        sparse.csr_matrix((counts, (rows, columns)), shape=shape),
        cue_support,
        support,
        training_sha256,
        len(artists),
    )


def save_enrichment(model: EnrichmentModel, output: Path) -> dict[str, object]:
    """Save a hash-bound sparse model inside the research cache without overwriting."""
    require_local_candidate_destination(output)
    if output.exists():
        raise FileExistsError("refusing to replace a frozen enrichment model")
    output.mkdir(parents=True)
    sparse.save_npz(output / "associations.npz", model.associations)
    sparse.save_npz(output / "joint-support.npz", model.joint_support)
    metadata = {
        "revision": REVISION,
        "settings": asdict(model.settings),
        "vocabulary": model.vocabulary,
        "genres": model.genres,
        "cue_support": model.cue_support.tolist(),
        "target_support": model.target_support.tolist(),
        "training_sha256": model.training_sha256,
        "training_artist_count": model.training_artist_count,
    }
    (output / "model.json").write_bytes(canonical_json(metadata) + b"\n")
    frozen = output / "frozen-code"
    frozen.mkdir()
    project = Path(__file__).resolve().parents[3]
    bindings = {}
    for source in (
        Path(__file__),
        project / "src/opennoise/ml/emergent_topics.py",
        project / "src/opennoise/analysis/emergent_topic_holdout.py",
        project / "src/opennoise/analysis/emergent_community_evaluation.py",
    ):
        snapshot = frozen / source.name
        snapshot.write_bytes(source.read_bytes())
        bindings[str(source.relative_to(project))] = {
            "sha256": sha256_file(snapshot)[0],
            "snapshot": str(snapshot.relative_to(output)),
        }
    receipt = {
        "revision": REVISION,
        "receipt_schema": 2,
        "scope": "local_research_only",
        "public_export_authorized": False,
        "historical_inputs_used": False,
        "audio_used": False,
        "scores_calibrated": False,
        "feature_role": "inferred_feature_proposal",
        "settings": asdict(model.settings),
        "training_sha256": model.training_sha256,
        "training_input_sha256": model.training_sha256,
        "training_artist_count": model.training_artist_count,
        "target_count": len(model.vocabulary),
        "association_count": model.associations.nnz,
        "code_sha256": sha256_file(Path(__file__))[0],
        "implementation_bindings": bindings,
        "model_sha256": sha256_file(output / "model.json")[0],
        "files": {
            name: sha256_file(output / name)[0]
            for name in ("model.json", "associations.npz", "joint-support.npz")
        },
    }
    receipt["output_sha256"] = sha256_json(receipt)
    (output / "receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return receipt


def load_enrichment(directory: Path) -> EnrichmentModel:
    """Verify all serialized model bytes before bounded offline prediction."""
    receipt = TypeAdapter(dict[str, object]).validate_json(
        (directory / "receipt.json").read_bytes()
    )
    if receipt.get("output_sha256") != sha256_json(
        {key: value for key, value in receipt.items() if key != "output_sha256"}
    ):
        raise ValueError("enrichment receipt self identity mismatch")
    expected = {
        "revision": REVISION,
        "receipt_schema": 2,
        "scope": "local_research_only",
        "public_export_authorized": False,
        "historical_inputs_used": False,
        "audio_used": False,
        "scores_calibrated": False,
        "feature_role": "inferred_feature_proposal",
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("enrichment receipt role contract differs")
    files = TypeAdapter(dict[str, str]).validate_python(receipt["files"])
    if set(files) != {"model.json", "associations.npz", "joint-support.npz"}:
        raise ValueError("enrichment receipt file contract differs")
    if any(sha256_file(directory / name)[0] != digest for name, digest in files.items()):
        raise ValueError("serialized enrichment model hash mismatch")
    raw = json.loads((directory / "model.json").read_text())
    if (
        receipt.get("model_sha256") != files["model.json"]
        or receipt.get("training_input_sha256") != raw["training_sha256"]
    ):
        raise ValueError("mandatory enrichment model or training binding differs")
    if any(
        receipt.get(key) != raw[key]
        for key in ("settings", "training_sha256", "training_artist_count", "revision")
    ):
        raise ValueError("enrichment receipt/model settings or identity differ")
    bindings = TypeAdapter(dict[str, dict[str, str]]).validate_python(
        receipt["implementation_bindings"]
    )
    expected_bindings = {
        "src/opennoise/ml/artist_feature_enrichment.py",
        "src/opennoise/ml/emergent_topics.py",
        "src/opennoise/analysis/emergent_topic_holdout.py",
        "src/opennoise/analysis/emergent_community_evaluation.py",
    }
    if (
        set(bindings) != expected_bindings
        or receipt.get("code_sha256")
        != bindings["src/opennoise/ml/artist_feature_enrichment.py"]["sha256"]
    ):
        raise ValueError("enrichment mandatory implementation identities differ")
    if not bindings or not all(
        Path(binding["snapshot"]).parts[0] == "frozen-code"
        and not Path(binding["snapshot"]).is_absolute()
        and ".." not in Path(binding["snapshot"]).parts
        and sha256_file(directory / binding["snapshot"])[0] == binding["sha256"]
        for binding in bindings.values()
    ):
        raise ValueError("enrichment frozen implementation binding differs")
    model = EnrichmentModel(
        EnrichmentSettings(**raw["settings"]),
        tuple(raw["vocabulary"]),
        tuple(raw["genres"]),
        sparse.load_npz(directory / "associations.npz").tocsr(),
        sparse.load_npz(directory / "joint-support.npz").tocsr(),
        np.asarray(raw["cue_support"]),
        np.asarray(raw["target_support"]),
        raw["training_sha256"],
        raw["training_artist_count"],
        files["model.json"],
    )
    if (
        model.associations.nnz > MAX_ASSOCIATIONS
        or len(model.vocabulary) > MAX_FEATURES
        or model.associations.shape
        != (len(model.vocabulary) + len(model.genres), len(model.vocabulary))
        or model.joint_support.shape != model.associations.shape
        or not np.all(np.isfinite(model.associations.data))
        or np.any(model.associations.data <= 0)
        or model.vocabulary != tuple(sorted(set(model.vocabulary)))
        or model.genres != tuple(sorted(set(model.genres)))
        or model.cue_support.shape != (model.associations.shape[0],)
        or model.target_support.shape != (len(model.vocabulary),)
        or receipt["target_count"] != len(model.vocabulary)
        or receipt["association_count"] != model.associations.nnz
        or not set(model.genres).issubset(model.vocabulary)
        or not np.all(np.isfinite(model.cue_support))
        or not np.all(np.isfinite(model.target_support))
        or np.any(model.cue_support < 0)
        or np.any(model.target_support < 0)
        or np.any(model.cue_support > model.training_artist_count)
        or np.any(model.target_support > model.training_artist_count)
        or not np.array_equal(model.joint_support.indices, model.associations.indices)
        or not np.array_equal(model.joint_support.indptr, model.associations.indptr)
        or not np.all(np.isfinite(model.joint_support.data))
        or np.any(model.joint_support.data < model.settings.minimum_joint_support)
    ):
        raise ValueError("serialized enrichment model violates sparse prediction bounds")
    return model
