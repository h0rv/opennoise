"""Freeze exact-artist independent musical review without inventing judgments."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import secrets
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import ijson
import zstandard

from opennoise.ml.wikidata_artist_completion import ARMS, Model, check_files, sha, split
from opennoise.ml.wikidata_unconditional_prior import rank_prior
from opennoise.serving.metadata.recording_facts import verify_recording_fact_pack

if TYPE_CHECKING:
    from collections.abc import Iterator

REVISION = "exact-artist-independent-musical-review-v1"
SEED = "opennoise-independent-artist-listening-v1"
DEFAULT_MODEL_RECEIPT = "5571f22953cfdc0c4003d855139bb4bbf1aadd97cbf2d3428495062eacaa0b6a"
FIRST_BATCH = 1000
REVIEW_SLOTS = ("reviewer_slot_1", "reviewer_slot_2")
REVIEW_ARMS = (*ARMS, "unconditional_training_prior")
RARE_SUPPORT = 10
PILOT_CLIPS = 8
CONTEXT_PROPERTIES = ("P17", "P27", "P495", "P740", "P19", "P1412")
FORM_FIELDS = (
    "reviewer_slot",
    "query_id",
    "item_id",
    "artist_display_name",
    "genre_candidate_label",
    "artist_metadata_url",
    "exact_recording_metadata_urls",
    "listening_access_evidence",
    "familiarity_0_to_3",
    "conflict_or_recusal",
    "listening_reference_1",
    "listening_reference_2",
    "listening_reference_3",
    "permission_or_lawful_access_basis",
    "provider",
    "territory",
    "access_date",
    "access_status",
    "artist_identity_match",
    "representative_material_sufficient",
    "membership_fit_0_to_4",
    "uncertainty_0_to_3",
    "abstention_reason",
    "notes",
)


def write(path: Path, value: object) -> None:
    """Create readable immutable evidence."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


def rows(path: Path) -> Iterator[dict[str, Any]]:
    """Read compressed line records without materializing an entire pack."""
    with path.open("rb") as raw, zstandard.ZstdDecompressor().stream_reader(raw) as source:
        for line in io.TextIOWrapper(source):
            yield json.loads(line)


def frozen_roster(model: Path) -> list[dict[str, Any]]:
    """Keep every exact confirmation query, in identity-only hash ordering."""
    selected = []
    seen = set()
    for row in rows(model / "artist-fold-targets.jsonl.zst"):
        mbid = row["artist_mbid"]
        if str(UUID(mbid)) != mbid or mbid in seen or row["split"] != split(mbid):
            raise ValueError("frozen artist identity/split differs")
        seen.add(mbid)
        if row["split"] == "confirmation":
            selected.append(
                {
                    key: row[key]
                    for key in (
                        "artist_mbid",
                        "wikidata_qid",
                        "observed_genre_qids",
                        "masked_observed_target",
                    )
                }
            )
    selected.sort(key=lambda row: hashlib.sha256(f"{SEED}:{row['artist_mbid']}".encode()).digest())
    if len(selected) < FIRST_BATCH:
        raise ValueError("independent musical-review cohort needs at least 1000 exact queries")
    return selected


def verify_bindings(model: Path, artists: Path, genres: Path, expected_model_receipt: str) -> None:
    """Bind source and model bytes to a caller-prescribed frozen model receipt."""
    if sha(model / "receipt.json") != expected_model_receipt:
        raise ValueError("model receipt differs from prescribed frozen source experiment")
    check_files(model)
    report = json.loads((model / "report.json").read_bytes())
    for root, name in ((artists, "artist_replay"), (genres, "genre_replay")):
        if sha(root / "receipt.json") != report[name]["receipt_sha256"]:
            raise ValueError("native source receipt differs from frozen model binding")
        receipt = json.loads((root / "receipt.json").read_bytes())
        projection = root / "projection.json"
        if sha(projection) != receipt["files"]["projection.json"]["sha256"]:
            raise ValueError("native source projection bytes differ")
    if sha(model / "implementation.py") != report["preserved_implementation_sha256"]:
        raise ValueError("preserved source experiment implementation differs")


def artist_context(artists: Path, wanted: set[str]) -> dict[str, dict[str, Any]]:
    """Keep native artist names and literal context, never inferred geography."""
    result: dict[str, dict[str, Any]] = {}
    with (artists / "projection.json").open("rb") as source:
        for row in ijson.items(source, "artists.item"):
            mbid = row["artist_mbid"]
            if mbid in wanted:
                if mbid in result or row["status"] != "exact_identity":
                    raise ValueError("review artist is not a unique exact source identity")
                result[mbid] = {
                    "name": row["name"],
                    "wikidata_qid": row["wikidata_qid"],
                    "native_context": {
                        prop: sorted(
                            {
                                claim["datavalue"]["value"]["id"]
                                for claim in row.get("claims", {}).get(prop, [])
                                if claim.get("datavalue", {}).get("type") == "wikibase-entityid"
                            }
                        )
                        for prop in CONTEXT_PROPERTIES
                    },
                }
    if set(result) != wanted:
        raise ValueError("review roster has missing native exact identities")
    return result


def genre_names(genres: Path) -> dict[str, str]:
    """Display native label text without making genre fit a fact."""
    result: dict[str, str] = {}
    with (genres / "projection.json").open("rb") as source:
        for qid, row in ijson.kvitems(source, "entities"):
            labels = row.get("labels", {})
            result[qid] = labels.get("en", {}).get("value") or qid
    return result


def load_model(directory: Path) -> Model:
    """Reuse exact frozen training counts; never fit on musical-review queries."""
    saved = json.loads((directory / "fitted-model.json").read_bytes())
    return Model(
        Counter(saved["training_support"]),
        {key: Counter(value) for key, value in saved["training_pairs"].items()},
        tuple(saved["training_vocabulary"]),
        {key: tuple(value) for key, value in saved["native_typed_parents"].items()},
        saved["training_artists"],
    )


def opaque_id(secret: bytes, value: str) -> str:
    """Blind per-item method assignments with a coordinator-only secret."""
    return hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()[:24]


def blind_candidates(
    model: Model,
    seeds: tuple[str, ...],
    secret: bytes,
    query_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Compare all predeclared arms on identical full observed-seed inputs."""
    candidates: dict[str, list[str]] = {}
    abstentions = []
    for arm in REVIEW_ARMS:
        ranked = (
            rank_prior(model, seeds)
            if arm == "unconditional_training_prior"
            else model.rank(seeds, arm)
        )
        if not ranked:
            abstentions.append(arm)
        else:
            candidates.setdefault(ranked[0][0], []).append(arm)
    result = [
        {
            "item_id": opaque_id(secret, f"{query_id}:{qid}"),
            "genre_qid": qid,
            "coordinator_methods": arms,
        }
        for qid, arms in candidates.items()
    ]
    result.sort(key=lambda row: row["item_id"])
    return result, abstentions


def recording_links(directory: Path) -> dict[str, list[dict[str, Any]]]:
    """Admit only exact native credits, and only as metadata links."""
    projection = verify_recording_fact_pack(directory)
    result = {}
    for artist in projection["artists"]:
        links = []
        for row in artist["recordings"]:
            if artist["artist_mbid"] not in row["credited_artist_mbids"]:
                raise ValueError("recording lacks the exact native artist credit")
            links.append(
                {
                    "recording_mbid": row["recording_mbid"],
                    "title": row["title"],
                    "metadata_url": f"https://musicbrainz.org/recording/{row['recording_mbid']}",
                    "playback_or_permission_verified": False,
                }
            )
        result[artist["artist_mbid"]] = links
    return result


def public_item(query_id: str, candidate: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    """Whitelist blinded prompt fields; never leak scores or method assignments."""
    return {
        "query_id": query_id,
        "item_id": candidate["item_id"],
        "genre_candidate_qid": candidate["genre_qid"],
        "genre_candidate_label": names.get(candidate["genre_qid"], candidate["genre_qid"]),
        "candidate_is_truth": False,
        "musical_probability": None,
    }


def reviewer_slots() -> list[dict[str, Any]]:
    """Reserve two blank independent slots without creating fictional people."""
    return [
        {
            "slot": slot,
            "actual_reviewer_id": None,
            "consent": None,
            "declared_expertise": None,
            "independent_of_model_build": None,
        }
        for slot in REVIEW_SLOTS
    ]


def pilot_reference(pilot: Path) -> dict[str, Any]:
    """Bind the existing eight-clip workflow pilot without inventing an artist bridge."""
    manifest = json.loads((pilot / "manifest.json").read_bytes())
    for name, expected in manifest["sha256"].items():
        path = pilot / name
        if not path.resolve().is_relative_to(pilot.resolve()) or sha(path) != expected:
            raise ValueError("existing pilot public manifest differs")
    cohort = json.loads((pilot / "cohort.json").read_bytes())
    if len(cohort["items"]) != PILOT_CLIPS:
        raise ValueError("existing permitted-listening pilot does not contain eight clips")
    return {
        "existing_pilot": str(pilot),
        "manifest_sha256": sha(pilot / "manifest.json"),
        "eight_clip_pilot": True,
        "same_artist_identity_bridge_claim": False,
        "scope": (
            "separate permitted FMA excerpt workflow pilot; "
            "no artist-name joins or judgments transferred"
        ),
    }


def census(
    cohort: list[dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
    model: Model,
) -> dict[str, Any]:
    """Report observed-source strata and missing native context explicitly."""
    support = Counter()
    label_counts = Counter()
    context_counts = {prop: Counter() for prop in CONTEXT_PROPERTIES}
    missing = Counter()
    for row in cohort:
        labels = row["observed_genre_qids"]
        label_counts[
            "unlabelled"
            if not labels
            else "one_positive"
            if len(labels) == 1
            else "overlapping_positive"
        ] += 1
        n = model.support.get(row["masked_observed_target"], 0)
        support[
            "unlabelled_no_masked_target"
            if row["masked_observed_target"] is None
            else "unseen_target"
            if n == 0
            else "rare_target_1_to_10"
            if n <= RARE_SUPPORT
            else "common_target_over_10"
        ] += 1
        for prop, values in contexts[row["artist_mbid"]]["native_context"].items():
            context_counts[prop].update(values)
            missing[prop] += not bool(values)
    return {
        "all_exact_queries": len(cohort),
        "source_label_strata": dict(label_counts),
        "masked_source_target_support_strata": dict(support),
        "literal_native_context_value_counts": {
            prop: dict(counts) for prop, counts in context_counts.items()
        },
        "missing_native_context_queries": dict(missing),
        "context_scope": (
            "literal source properties only; "
            "not model features, musical styles or geography inference"
        ),
    }


def render_review(  # noqa: PLR0913, PLR0917 - preserve separate source/count/private-output custody.
    public: Path,
    private: Path,
    cohort: list[dict[str, Any]],
    roster: list[dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
    names: dict[str, str],
    model: Model,
    links: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Stream blinded prompts/forms/private keys without accumulating all items."""
    secret = secrets.token_bytes(32)
    totals = Counter()
    abstention_counts = Counter()
    with (
        (public / "queries.jsonl").open("x") as queries,
        (public / "items.jsonl").open("x") as items,
        (private / "method-assignments.jsonl").open("x") as assignments,
        (public / "review-form.csv").open("x", newline="") as forms,
    ):
        writer = csv.DictWriter(forms, fieldnames=FORM_FIELDS)
        writer.writeheader()
        for row, identity in zip(cohort, roster, strict=True):
            mbid = row["artist_mbid"]
            query_id = identity["query_id"]
            candidates, abstentions = blind_candidates(
                model, tuple(row["observed_genre_qids"]), secret, query_id
            )
            abstention_counts.update(abstentions)
            query = {
                **identity,
                "artist_display_name": contexts[mbid]["name"],
                "artist_metadata_url": f"https://musicbrainz.org/artist/{mbid}",
                "exact_recording_metadata_links": links.get(mbid, []),
                "exact_recording_links_missing": not bool(links.get(mbid)),
                "permitted_listening_references": [],
                "playback_verified": False,
                "candidate_items": [candidate["item_id"] for candidate in candidates],
                "all_methods_abstained": not bool(candidates),
            }
            queries.write(json.dumps(query, sort_keys=True, ensure_ascii=False) + "\n")
            assignments.write(
                json.dumps(
                    {
                        "query_id": query_id,
                        "artist_mbid": mbid,
                        "source_observed_labels_not_truth": row["observed_genre_qids"],
                        "masked_source_target_not_truth": row["masked_observed_target"],
                        "method_abstentions": abstentions,
                        "native_context": contexts[mbid]["native_context"],
                        "items": candidates,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            totals["queries"] += 1
            totals["items"] += len(candidates)
            totals["blank_review_rows"] += len(REVIEW_SLOTS) * max(1, len(candidates))
            totals["missing_recording"] += query["exact_recording_links_missing"]
            totals["all_abstained"] += query["all_methods_abstained"]
            for candidate in candidates or [None]:
                prompt = public_item(query_id, candidate, names) if candidate else None
                if prompt:
                    items.write(json.dumps(prompt, sort_keys=True, ensure_ascii=False) + "\n")
                for slot in REVIEW_SLOTS:
                    writer.writerow(
                        {
                            "reviewer_slot": slot,
                            "query_id": query_id,
                            "item_id": prompt["item_id"] if prompt else "",
                            "artist_display_name": query["artist_display_name"],
                            "genre_candidate_label": prompt["genre_candidate_label"]
                            if prompt
                            else "",
                            "artist_metadata_url": query["artist_metadata_url"],
                            "listening_access_evidence": (
                                "metadata only; no verified playback or listening permission"
                            ),
                            "exact_recording_metadata_urls": " | ".join(
                                link["metadata_url"]
                                for link in query["exact_recording_metadata_links"]
                            ),
                        }
                    )
    write(
        private / "method-key.json",
        {
            "revision": REVISION,
            "secret_hex": secret.hex(),
            "coordinator_only": True,
            "assignments_file": "method-assignments.jsonl",
        },
    )
    write(private / "reviewer-assignments.json", {"slots": reviewer_slots()})
    return {
        "revision": REVISION,
        "all_exact_queries": totals["queries"],
        "first_batch_queries": FIRST_BATCH,
        "distinct_candidate_items": totals["items"],
        "blank_review_rows": totals["blank_review_rows"],
        "missing_exact_recording_queries": totals["missing_recording"],
        "all_methods_abstained_queries": totals["all_abstained"],
        "method_abstentions": dict(abstention_counts),
        "permitted_cohort_listening_queries": 0,
        "human_judgments_received": 0,
        "real_reviewer_assignments": 0,
        "source_observations_are_not_truth": True,
        "coordinator_keys_public": False,
    }


def build_packet(  # noqa: PLR0913, PLR0917 - preserve independent source/artifact custody.
    model: Path,
    artists: Path,
    genres: Path,
    recordings: Path,
    pilot: Path,
    output: Path,
    *,
    core: Path,
    expected_model_receipt: str = DEFAULT_MODEL_RECEIPT,
) -> dict[str, Any]:
    """Freeze before rendering; retain private coordinator keys outside public paths."""
    verify_bindings(model, artists, genres, expected_model_receipt)
    artist_receipt = json.loads((artists / "receipt.json").read_bytes())
    core_receipt = json.loads((core / "receipt.json").read_bytes())
    if sha(core / "receipt.json") != artist_receipt["core"]["core_receipt_sha256"]:
        raise ValueError("core identity population receipt differs from native source roster")
    core_count = core_receipt["artist_count"]
    pilot_binding = pilot_reference(pilot)
    cohort = frozen_roster(model)
    output.mkdir(parents=True, exist_ok=False)
    public = output / "public"
    private = output / "coordinator-private"
    public.mkdir()
    private.mkdir(mode=0o700)
    roster = [
        {
            "query_id": hashlib.sha256(f"{SEED}:query:{row['artist_mbid']}".encode()).hexdigest()[
                :24
            ],
            "artist_mbid": row["artist_mbid"],
            "wikidata_qid": row["wikidata_qid"],
            "batch": "first_1000" if index < FIRST_BATCH else "remaining_991",
        }
        for index, row in enumerate(cohort)
    ]
    write(
        public / "frozen-roster.json",
        {
            "revision": REVISION,
            "seed": SEED,
            "selection": (
                "all confirmation UUIDs; identity-only hash order, no outcome/status filtering"
            ),
            "queries": roster,
        },
    )
    write(
        public / "freeze.json",
        {
            "revision": REVISION,
            "seed": SEED,
            "model_receipt_sha256": expected_model_receipt,
            "model_report_sha256": sha(model / "report.json"),
            "source_receipts": {
                "artists": sha(artists / "receipt.json"),
                "genres": sha(genres / "receipt.json"),
                "recording_facts": sha(recordings / "receipt.json"),
                "core_identity_population": sha(core / "receipt.json"),
                "existing_eight_clip_pilot": pilot_binding["manifest_sha256"],
            },
            "implementation_sha256": sha(Path(__file__)),
            "roster_sha256": sha(public / "frozen-roster.json"),
            "population_queries": len(cohort),
            "first_batch_queries": FIRST_BATCH,
            "timing": "after source-experiment inspection; before any musical judgments",
            "human_judgments_received": 0,
            "real_reviewer_assignments": 0,
            "protocol": (
                "four conditional frozen arms plus unconditional train prior; "
                "same full observed-seed inputs, distinct top1 candidates; no refit or tuning"
            ),
        },
    )
    # Freeze the exact identity roster before consulting metadata, scoring or blinding.
    contexts = artist_context(artists, {row["artist_mbid"] for row in cohort})
    names = genre_names(genres)
    frozen_model = load_model(model)
    links = recording_links(recordings)
    coverage = census(cohort, contexts, frozen_model)
    coverage.update(
        {
            "core_identity_population": core_count,
            "model_exact_artist_population": json.loads((model / "report.json").read_bytes())[
                "artist_replay"
            ]["exact_artists"],
            "source_query_scope": (
                "bounded source-selected roster; "
                "full core artists outside this model remain unknown, not genre-free"
            ),
        }
    )
    coverage["core_identities_outside_source_model"] = (
        core_count - coverage["model_exact_artist_population"]
    )
    write(public / "source-coverage.json", coverage)
    summary = render_review(public, private, cohort, roster, contexts, names, frozen_model, links)
    if sha(pilot / "manifest.json") != pilot_binding["manifest_sha256"]:
        raise ValueError("existing pilot changed during independent review rendering")
    write(public / "pilot-reference.json", pilot_binding)
    write(public / "summary.json", summary)
    write(
        public / "manifest.json",
        {
            "revision": REVISION,
            "files": {
                path.name: {"bytes": path.stat().st_size, "sha256": sha(path)}
                for path in sorted(public.iterdir())
            },
        },
    )
    write(
        private / "manifest.json",
        {
            "revision": REVISION,
            "public_manifest_sha256": sha(public / "manifest.json"),
            "files": {
                path.name: {"bytes": path.stat().st_size, "sha256": sha(path)}
                for path in sorted(private.iterdir())
            },
        },
    )
    return summary
