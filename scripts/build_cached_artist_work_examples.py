"""Build local credited music examples from captured MusicBrainz searches."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from opennoise.serving.metadata.artist_works import CreditedMusicCandidate, rank_artist_works

HTTP_OK = 200


def main() -> int:  # noqa: C901, PLR0915, PLR0912 — bounded capture replay keeps credit custody together.
    """Verify source captures and emit a bounded metadata-only navigation artifact."""
    parser = argparse.ArgumentParser()
    parser.add_argument("cache", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError("representative output already exists")
    receipt = json.loads((arguments.cache / "receipt.json").read_text())
    for filename in ("source-captures.json", "query-manifest.json"):
        body = (arguments.cache / filename).read_bytes()
        if hashlib.sha256(body).hexdigest() != receipt["files"][filename]:
            raise ValueError("capture manifest differs from its source receipt")
    captures = json.loads((arguments.cache / "source-captures.json").read_text())
    manifest = json.loads((arguments.cache / "query-manifest.json").read_text())
    names = {item["artist_mbid"]: item["name"] for item in manifest["artists"]}
    artists = []
    for capture in captures:
        if capture["kind"] != "search" or capture["status_code"] != HTTP_OK:
            continue
        source_path = (arguments.cache / capture["payload_path"]).resolve()
        if not source_path.is_relative_to(arguments.cache.resolve()):
            raise ValueError("capture path escapes source cache")
        body = source_path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != capture["payload_sha256"]:
            raise ValueError("captured MusicBrainz body checksum differs")
        artist = capture["artist_mbid"]
        evidence = (f"sha256:{digest}", capture["requested_url"])
        recordings, groups = [], []
        for recording in json.loads(body).get("recordings", [])[:100]:
            artist_ids = tuple(
                item["artist"]["id"]
                for item in recording.get("artist-credit", [])
                if isinstance(item, dict)
            )
            if artist not in artist_ids:
                continue
            release_ids = []
            album = False
            for release in recording.get("releases", []):
                group = release.get("release-group", {})
                if not group.get("id"):
                    continue
                group_ref = f"musicbrainz:release-group:{group['id']}"
                release_ids.append(group_ref)
                release_credits = tuple(
                    item["artist"]["id"]
                    for item in release.get("artist-credit", [])
                    if isinstance(item, dict)
                )
                original = (
                    group.get("primary-type") == "Album"
                    and not group.get("secondary-types")
                    and artist in release_credits
                )
                album |= original
                if artist in release_credits:
                    groups.append(
                        CreditedMusicCandidate(
                            entity_kind="release_group",
                            entity_id=group_ref,
                            title=group.get("title", release["title"]),
                            credited_artist_mbids=release_credits,
                            evidence_refs=evidence,
                            release_group_ids=(group_ref,),
                            first_release_date=release.get("date", ""),
                            original_album=original,
                        )
                    )
            title = recording["title"]
            recordings.append(
                CreditedMusicCandidate(
                    entity_kind="recording",
                    entity_id=f"musicbrainz:recording:{recording['id']}",
                    title=title,
                    credited_artist_mbids=artist_ids,
                    evidence_refs=evidence,
                    release_group_ids=tuple(sorted(set(release_ids))),
                    first_release_date=recording.get("first-release-date", ""),
                    original_album=album,
                    variant=any(word in title.casefold() for word in ("remix", "live", "mix)"))
                    or bool(recording.get("disambiguation")),
                )
            )

        # Multiple edition credits can describe the same contextual group link.
        # Choose one edition deterministically rather than claim merged group credits.
        context_groups: dict[str, CreditedMusicCandidate] = {}
        for group_candidate in sorted(groups, key=lambda item: item.model_dump_json()):
            context_groups.setdefault(group_candidate.entity_id, group_candidate)
        groups = list(context_groups.values())

        def rows(
            candidates: list[CreditedMusicCandidate], artist_id: str
        ) -> list[dict[str, object]]:
            result: list[dict[str, object]] = []
            for ranked in rank_artist_works(artist_id, tuple(candidates)):
                row = ranked.candidate.model_dump(mode="json")
                row.update(ranked.model_dump(mode="json", exclude={"candidate"}))
                result.append(row)
            return result

        artists.append(
            {
                "artist_mbid": artist,
                "name": names[artist],
                "recordings": rows(recordings, artist),
                "release_groups": rows(groups, artist),
                "sample_recording_count": len(recordings),
            }
        )
    artifact = {
        "revision": "credited-music-examples-v1",
        "publication_status": "local_candidate",
        "method": "exact credits; album context; nonvariant; release and title diversity",
        "limitations": "Bounded search sample, not defining quality, popularity or genre truth.",
        "rights": "MusicBrainz core metadata CC0; no audio or media assets acquired or embedded.",
        "artists": sorted(artists, key=lambda item: item["artist_mbid"]),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x") as stream:
        stream.write(json.dumps(artifact, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
