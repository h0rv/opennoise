"""Conservative source-tag style proposals with bounded, authority-aware cue scoring.

These hypotheses recover source metadata. They do not establish sonic similarity,
genre identity, native artist facts, or calibrated confidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from pydantic import TypeAdapter
from scipy import sparse

from opennoise.analysis.emergent_topic_holdout import musical_value
from opennoise.catalog.musicbrainz_candidate import require_local_candidate_destination
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ml.artist_feature_enrichment import (
    MAX_ARTISTS,
    MAX_ASSOCIATIONS,
    MAX_BATCH,
    MAX_FEATURES,
    MAX_OBSERVATIONS,
    MAX_PAIR_OBSERVATIONS,
    MAX_RANK,
    MAX_ROW_FEATURES,
    _matrix,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REVISION = "authority-aware-source-style-associations-v1"
AUTHORITY = {"artist_genre": 1.0, "artist_tag": 0.8, "release_genre": 0.2, "release_tag": 0.2}
NEIGHBORS = 64
CONFIDENCE_SUPPORT = 8
REFERENCE_LIMIT = 8
SETTING_BOUND = 1000
MAXIMUM_TARGET_SHARE = 0.1


@dataclass(frozen=True)
class FineStyleSettings:
    """Prespecified source-support and association gates, never a genre-quality claim."""

    smoothing: float = 16
    minimum_target_support: int = 5
    maximum_target_share: float = 0.005
    minimum_joint_support: int = 3
    minimum_anchor_coverage: float = 0.5
    minimum_anchor_lift: float = 2
    minimum_association_lift: float = 2
    minimum_conditional_fraction: float = 0.05
    strongest_cues: int = 2

    def __post_init__(self) -> None:
        """Reject unbounded or nonfinite experimental settings."""
        if not all(np.isfinite(value) for value in asdict(self).values()):
            raise ValueError("fine-style settings must be finite")
        if (
            not 0 < self.smoothing <= SETTING_BOUND
            or not 0 < self.maximum_target_share <= MAXIMUM_TARGET_SHARE
        ):
            raise ValueError("fine-style regularization or target share differs")
        if (
            not 1 <= self.minimum_target_support <= SETTING_BOUND
            or not 1 <= self.minimum_joint_support <= SETTING_BOUND
        ):
            raise ValueError("fine-style source support bounds differ")
        if (
            not 0 < self.minimum_anchor_coverage <= 1
            or not 0 < self.minimum_conditional_fraction <= 1
        ):
            raise ValueError("fine-style coverage/fraction must be between zero and one")
        if (
            not 1 <= self.minimum_anchor_lift <= SETTING_BOUND
            or not 1 < self.minimum_association_lift <= SETTING_BOUND
        ):
            raise ValueError("fine-style lift bounds differ")
        if self.strongest_cues not in (1, 2):
            raise ValueError("fine-style scoring uses one or two strongest distinct cues")


@dataclass(frozen=True)
class StyleProfiles:
    """Exact source facet roles with one musical value identity per artist."""

    music: dict[str, tuple[str, ...]]
    artist_music: dict[str, tuple[str, ...]]
    artist_tags: dict[str, tuple[str, ...]]
    proper: dict[str, tuple[str, ...]]
    authority: dict[str, dict[str, float]]
    input_sha256: str


def duplicate_signature(value: str) -> str:
    """Suppress punctuation/spacing-shaped duplicates without claiming alias identity."""
    return "".join(character for character in value if character.isalnum())


def read_style_profiles(path: Path) -> StyleProfiles:  # noqa: C901 - audited source facet boundary.
    """Keep release context auxiliary and artist tags separate from native genre facts."""
    music, artist_music, artist_tags, proper, authority = {}, {}, {}, {}, {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = TypeAdapter(dict[str, object]).validate_json(line)
            artist = str(row["artist_mbid"])
            if not artist or artist in music:
                raise ValueError("style profile artists must be unique and nonempty")
            values: set[str] = set()
            primary: set[str] = set()
            tags: set[str] = set()
            genres: set[str] = set()
            weights: dict[str, float] = {}
            for feature in TypeAdapter(list[dict[str, object]]).validate_python(row["features"]):
                weight = float(cast("float", feature.get("weight", 1)))
                if not np.isfinite(weight) or weight <= 0 or not feature.get("evidence_refs"):
                    raise ValueError(
                        "style evidence requires positive weights and exact references"
                    )
                if (value := musical_value(feature)) is None:
                    continue
                namespace = str(feature["namespace"])
                values.add(value)
                weights[value] = max(weights.get(value, 0), AUTHORITY[namespace])
                if namespace.startswith("artist_"):
                    primary.add(value)
                if namespace == "artist_tag":
                    tags.add(value)
                if namespace == "artist_genre":
                    genres.add(value)
            if len(values) > MAX_ROW_FEATURES:
                raise ValueError("style artist evidence exceeds the row bound")
            music[artist] = tuple(sorted(values))
            artist_music[artist] = tuple(sorted(primary))
            artist_tags[artist] = tuple(sorted(tags))
            proper[artist] = tuple(sorted(genres))
            authority[artist] = weights
    if len(music) > MAX_ARTISTS:
        raise ValueError("style profile artist bound exceeded")
    return StyleProfiles(music, artist_music, artist_tags, proper, authority, sha256_file(path)[0])


def _weighted_cues(
    profiles: StyleProfiles, artists: Sequence[str], vocabulary: Sequence[str]
) -> sparse.csr_matrix:
    matrix = _matrix(artists, profiles.music, vocabulary)
    for row, artist in enumerate(artists):
        start, end = matrix.indptr[row : row + 2]
        for position in range(start, end):
            matrix.data[position] = profiles.authority[artist][vocabulary[matrix.indices[position]]]
    return matrix


@dataclass
class StyleAssociationModel:
    """Source-artist-tag target pool, train-only anchors, and sparse cue associations."""

    settings: FineStyleSettings
    cues: tuple[str, ...]
    targets: tuple[str, ...]
    associations: sparse.csr_matrix
    joint_support: sparse.csr_matrix
    cue_support: np.ndarray
    target_support: np.ndarray
    anchors: tuple[dict[str, object], ...]
    training_sha256: str
    training_artist_count: int

    def rank_batch(
        self, profiles: StyleProfiles, artists: Sequence[str], *, limit: int = 10
    ) -> dict[str, tuple[str, ...]]:
        """Aggregate only the strongest distinct source cues; artist-cold profiles abstain."""
        if len(artists) > MAX_BATCH or not 1 <= limit <= MAX_RANK:
            raise ValueError("style prediction exceeds the explicit batch/rank limit")
        known_cues = _weighted_cues(profiles, artists, self.cues)
        specificity = np.sqrt(1 + np.log((self.training_artist_count + 1) / (self.cue_support + 1)))
        result: dict[str, tuple[str, ...]] = {}
        for row, artist in enumerate(artists):
            if not profiles.artist_music[artist]:
                result[artist] = ()
                continue
            target_chunks, score_chunks = [], []
            start, end = known_cues.indptr[row : row + 2]
            for position in range(start, end):
                cue = known_cues.indices[position]
                left, right = self.associations.indptr[cue : cue + 2]
                target_chunks.append(self.associations.indices[left:right])
                score_chunks.append(
                    self.associations.data[left:right]
                    * known_cues.data[position]
                    * specificity[cue]
                )
            if not target_chunks:
                result[artist] = ()
                continue
            columns = np.concatenate(target_chunks)
            values = np.concatenate(score_chunks)
            if not len(columns):
                result[artist] = ()
                continue
            order = np.lexsort((-values, columns))
            columns, values = columns[order], values[order]
            starts = np.r_[0, np.flatnonzero(np.diff(columns)) + 1]
            within = np.arange(len(columns)) - np.repeat(
                starts, np.diff(np.r_[starts, len(columns)])
            )
            values[within >= self.settings.strongest_cues] = 0
            candidates = columns[starts]
            scores = np.add.reduceat(values, starts)
            known = {duplicate_signature(value) for value in profiles.music[artist]}
            eligible = np.array(
                [
                    i
                    for i, column in enumerate(candidates)
                    if duplicate_signature(self.targets[column]) not in known
                ],
                dtype=np.int64,
            )
            selected = eligible[np.lexsort((candidates[eligible], -scores[eligible]))[:limit]]
            result[artist] = tuple(self.targets[candidates[i]] for i in selected)
        return result

    def proposals(
        self, row: Mapping[str, object], profiles: StyleProfiles, *, limit: int = 3
    ) -> list[dict[str, object]]:
        """Expose direct source cues, source tag support, and anchor coverage as hypotheses."""
        artist = str(row["artist_mbid"])
        ranked = self.rank_batch(profiles, [artist], limit=limit)[artist]
        cue_index = {value: i for i, value in enumerate(self.cues)}
        target_index = {value: i for i, value in enumerate(self.targets)}
        evidence: dict[str, list[dict[str, object]]] = {}
        for feature in TypeAdapter(list[dict[str, object]]).validate_python(row["features"]):
            if (value := musical_value(feature)) is not None:
                evidence.setdefault(value, []).append(feature)
        result: list[dict[str, object]] = []
        for value in ranked:
            target = target_index[value]
            contributions = []
            for cue_value, authority in profiles.authority[artist].items():
                if (cue := cue_index.get(cue_value)) is None:
                    continue
                association = float(self.associations[cue, target])
                if association <= 0:
                    continue
                specificity = float(
                    np.sqrt(
                        1 + np.log((self.training_artist_count + 1) / (self.cue_support[cue] + 1))
                    )
                )
                refs = sorted(
                    {
                        ref
                        for item in evidence[cue_value]
                        for ref in TypeAdapter(list[str]).validate_python(item["evidence_refs"])
                    }
                )
                contributions.append(
                    {
                        "value": cue_value,
                        "source_namespaces": sorted(
                            {str(item["namespace"]) for item in evidence[cue_value]}
                        ),
                        "source_authority_weight": authority,
                        "query_evidence_refs": refs[:REFERENCE_LIMIT],
                        "query_evidence_ref_count": len(refs),
                        "training_joint_artist_tag_support": int(self.joint_support[cue, target]),
                        "training_cue_artist_support": int(self.cue_support[cue]),
                        "score_contribution": association * authority * specificity,
                    }
                )
            contributions.sort(
                key=lambda item: (
                    -float(cast("float", item["score_contribution"])),
                    str(item["value"]),
                )
            )
            leading = contributions[: self.settings.strongest_cues]
            result.append(
                {
                    "value": value,
                    "role": "inferred_feature_proposal",
                    "target_scope": "source_artist_tag_style_candidate",
                    "native_fact": False,
                    "score_calibrated": False,
                    "genre_identity_validated": False,
                    "score": sum(
                        float(cast("float", item["score_contribution"])) for item in leading
                    ),
                    "training_artist_tag_support": int(self.target_support[target]),
                    "source_genre_anchor": self.anchors[target],
                    "training_sha256": self.training_sha256,
                    "evidence": leading,
                }
            )
        return result


def fit_style_associations(  # noqa: PLR0915 - one sparse source-count and regularization boundary.
    profiles: StyleProfiles, settings: FineStyleSettings | None = None
) -> StyleAssociationModel:
    """Fit artist-tag targets; release-credit context can only supply weighted cue evidence."""
    resolved = settings or FineStyleSettings()
    artists = tuple(sorted(profiles.music))
    cues = tuple(sorted({value for values in profiles.music.values() for value in values}))
    genres = tuple(sorted({value for values in profiles.proper.values() for value in values}))
    signatures = {duplicate_signature(value) for value in genres}
    all_tags = tuple(
        sorted({value for values in profiles.artist_tags.values() for value in values})
    )
    if len(cues) > MAX_FEATURES or len(artists) > MAX_ARTISTS:
        raise ValueError("style training identity bound exceeded")
    raw_cues = _matrix(artists, profiles.music, cues)
    tags = _matrix(artists, profiles.artist_tags, all_tags)
    if raw_cues.nnz > MAX_OBSERVATIONS:
        raise ValueError("style observation bound exceeded")
    if (
        np.sum(np.asarray(raw_cues.sum(axis=1)).ravel() * np.asarray(tags.sum(axis=1)).ravel())
        > MAX_PAIR_OBSERVATIONS
    ):
        raise ValueError("style pair-work bound exceeded before sparse multiplication")
    tag_support = np.asarray(tags.sum(axis=0)).ravel()
    native = _matrix(artists, profiles.proper, genres)
    genre_support = np.asarray(native.sum(axis=0)).ravel()
    anchor_counts = (tags.T @ native).tocsr()
    selected, anchors = [], []
    for target, value in enumerate(all_tags):
        support = tag_support[target]
        if (
            support < resolved.minimum_target_support
            or support > resolved.maximum_target_share * len(artists)
            or duplicate_signature(value) in signatures
        ):
            continue
        start, end = anchor_counts.indptr[target : target + 2]
        columns, counts = anchor_counts.indices[start:end], anchor_counts.data[start:end]
        coverage = counts / support
        lift = coverage / np.maximum(
            genre_support[columns] / max(1, len(artists)), 1 / max(1, len(artists))
        )
        eligible = np.flatnonzero(
            (coverage >= resolved.minimum_anchor_coverage) & (lift >= resolved.minimum_anchor_lift)
        )
        if not len(eligible):
            continue
        anchor = eligible[np.lexsort((columns[eligible], -coverage[eligible], -lift[eligible]))[0]]
        selected.append(target)
        anchors.append(
            {
                "value": genres[columns[anchor]],
                "joint_artist_support": int(counts[anchor]),
                "target_artist_support": int(support),
                "coverage": float(coverage[anchor]),
                "lift": float(lift[anchor]),
                "role": "train_only_source_genre_anchor_not_taxonomy_parent",
            }
        )
    targets = tuple(all_tags[target] for target in selected)
    target_matrix = tags[:, selected].tocsr()
    target_support = tag_support[selected]
    weighted_cues = _weighted_cues(profiles, artists, cues)
    primary_degree = np.array([len(profiles.artist_music[artist]) for artist in artists])
    correction = 1 / np.sqrt(np.maximum(1, primary_degree))
    mass = (weighted_cues.T @ sparse.diags(correction) @ target_matrix).tocsr()
    joints = (raw_cues.T @ target_matrix).tocsr()
    cue_support = np.asarray(raw_cues.sum(axis=0)).ravel()
    cue_mass = np.asarray(weighted_cues.T @ correction).ravel()
    prior = target_support / max(1, len(artists))
    rows, columns, scores, supports = [], [], [], []
    for cue in range(len(cues)):
        start, end = mass.indptr[cue : cue + 2]
        candidates, cooccurrence = mass.indices[start:end], mass.data[start:end]
        joint = joints[cue, candidates].toarray().ravel()
        conditional = (cooccurrence + resolved.smoothing * prior[candidates]) / (
            cue_mass[cue] + resolved.smoothing
        )
        lift = conditional / np.maximum(prior[candidates], 1 / max(1, len(artists)))
        keep = (
            (joint >= resolved.minimum_joint_support)
            & (lift >= resolved.minimum_association_lift)
            & (joint / max(1, cue_support[cue]) >= resolved.minimum_conditional_fraction)
        )
        candidates, joint, lift = candidates[keep], joint[keep], lift[keep]
        values = np.log(lift) * joint / (joint + CONFIDENCE_SUPPORT)
        chosen = np.lexsort((candidates, -values))[:NEIGHBORS]
        for position in chosen:
            rows.append(cue)
            columns.append(int(candidates[position]))
            scores.append(float(values[position]))
            supports.append(float(joint[position]))
    if len(rows) > MAX_ASSOCIATIONS:
        raise ValueError("style sparse association bound exceeded")
    shape = (len(cues), len(targets))
    return StyleAssociationModel(
        resolved,
        cues,
        targets,
        sparse.csr_matrix((scores, (rows, columns)), shape=shape),
        sparse.csr_matrix((supports, (rows, columns)), shape=shape),
        cue_support,
        target_support,
        tuple(anchors),
        profiles.input_sha256,
        len(artists),
    )


def save_style_model(model: StyleAssociationModel, output: Path) -> dict[str, object]:
    """Serialize one local research model with complete source, method, and role bindings."""
    require_local_candidate_destination(output)
    if output.exists():
        raise FileExistsError("refusing to replace a frozen style model")
    output.mkdir(parents=True)
    sparse.save_npz(output / "associations.npz", model.associations)
    sparse.save_npz(output / "joint-support.npz", model.joint_support)
    metadata = {
        "revision": REVISION,
        "settings": asdict(model.settings),
        "cues": model.cues,
        "targets": model.targets,
        "cue_support": model.cue_support.tolist(),
        "target_support": model.target_support.tolist(),
        "anchors": model.anchors,
        "training_sha256": model.training_sha256,
        "training_artist_count": model.training_artist_count,
    }
    (output / "model.json").write_bytes(canonical_json(metadata) + b"\n")
    code = output / "frozen-code"
    code.mkdir()
    project = Path(__file__).resolve().parents[3]
    bindings = {}
    for source in (
        Path(__file__),
        project / "src/opennoise/ml/artist_feature_enrichment.py",
        project / "src/opennoise/ml/emergent_topics.py",
        project / "src/opennoise/analysis/emergent_topic_holdout.py",
    ):
        snapshot = code / source.name
        snapshot.write_bytes(source.read_bytes())
        bindings[str(source.relative_to(project))] = {
            "sha256": sha256_file(snapshot)[0],
            "snapshot": str(snapshot.relative_to(output)),
        }
    receipt: dict[str, object] = {
        "revision": REVISION,
        "scope": "local_research_only",
        "public_export_authorized": False,
        "native_fact": False,
        "scores_calibrated": False,
        "historical_inputs_used": False,
        "audio_used": False,
        "role": "inferred_source_artist_tag_style_proposals",
        "settings": asdict(model.settings),
        "cue_authority": AUTHORITY,
        "strongest_cue_aggregation": model.settings.strongest_cues,
        "training_sha256": model.training_sha256,
        "target_count": len(model.targets),
        "association_count": model.associations.nnz,
        "code_sha256": sha256_file(Path(__file__))[0],
        "implementation_bindings": bindings,
        "files": {
            name: sha256_file(output / name)[0]
            for name in ("model.json", "associations.npz", "joint-support.npz")
        },
    }
    receipt["output_sha256"] = sha256_json(receipt)
    (output / "receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return receipt


def load_style_model(directory: Path) -> StyleAssociationModel:
    """Verify source-model identities and frozen implementation bytes before prediction."""
    receipt = TypeAdapter(dict[str, object]).validate_json(
        (directory / "receipt.json").read_bytes()
    )
    if receipt.get("output_sha256") != sha256_json(
        {key: value for key, value in receipt.items() if key != "output_sha256"}
    ):
        raise ValueError("style receipt self identity mismatch")
    contract = {
        "revision": REVISION,
        "scope": "local_research_only",
        "public_export_authorized": False,
        "native_fact": False,
        "scores_calibrated": False,
        "historical_inputs_used": False,
        "audio_used": False,
        "role": "inferred_source_artist_tag_style_proposals",
    }
    if any(receipt.get(key) != value for key, value in contract.items()):
        raise ValueError("style model source role contract differs")
    files = TypeAdapter(dict[str, str]).validate_python(receipt["files"])
    if set(files) != {"model.json", "associations.npz", "joint-support.npz"} or any(
        sha256_file(directory / name)[0] != digest for name, digest in files.items()
    ):
        raise ValueError("style model file hash mismatch")
    bindings = TypeAdapter(dict[str, dict[str, str]]).validate_python(
        receipt["implementation_bindings"]
    )
    if not bindings or any(
        Path(value["snapshot"]).is_absolute()
        or ".." in Path(value["snapshot"]).parts
        or sha256_file(directory / value["snapshot"])[0] != value["sha256"]
        for value in bindings.values()
    ):
        raise ValueError("style frozen implementation hash mismatch")
    raw = TypeAdapter(dict[str, object]).validate_json((directory / "model.json").read_bytes())
    if any(raw.get(key) != receipt.get(key) for key in ("revision", "settings", "training_sha256")):
        raise ValueError("style receipt/model settings or source differ")
    model = StyleAssociationModel(
        TypeAdapter(FineStyleSettings).validate_python(raw["settings"]),
        tuple(TypeAdapter(list[str]).validate_python(raw["cues"])),
        tuple(TypeAdapter(list[str]).validate_python(raw["targets"])),
        sparse.load_npz(directory / "associations.npz").tocsr(),
        sparse.load_npz(directory / "joint-support.npz").tocsr(),
        np.asarray(raw["cue_support"]),
        np.asarray(raw["target_support"]),
        tuple(TypeAdapter(list[dict[str, object]]).validate_python(raw["anchors"])),
        str(raw["training_sha256"]),
        int(cast("int", raw["training_artist_count"])),
    )
    if (
        len(model.cues) > MAX_FEATURES
        or len(model.targets) > MAX_FEATURES
        or model.associations.nnz > MAX_ASSOCIATIONS
        or model.associations.shape != (len(model.cues), len(model.targets))
        or model.joint_support.shape != model.associations.shape
        or model.cues != tuple(sorted(set(model.cues)))
        or model.targets != tuple(sorted(set(model.targets)))
        or len(model.anchors) != len(model.targets)
        or model.cue_support.shape != (len(model.cues),)
        or model.target_support.shape != (len(model.targets),)
        or not np.all(np.isfinite(model.associations.data))
        or np.any(model.associations.data <= 0)
        or not np.array_equal(model.associations.indices, model.joint_support.indices)
        or not np.array_equal(model.associations.indptr, model.joint_support.indptr)
    ):
        raise ValueError("style model sparse bounds or support alignment differ")
    return model
