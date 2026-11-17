import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

SCHEMA = json.loads(Path(__file__).with_name("catalog.schema.json").read_text())


def validate_release(root: Path) -> dict:
    validators = {
        name: Draft202012Validator(
            {"$defs": SCHEMA["$defs"], "$ref": f"#/$defs/{name}"},
            format_checker=FormatChecker(),
        )
        for name in ["Manifest", "Genres", "Search", "GenreDetail", "ArtistDetail"]
    }

    def read(relative, kind):
        path = root / relative
        try:
            value = json.loads(path.read_text(), parse_constant=reject_constant)
            validators[kind].validate(value)
        except (OSError, ValueError, ValidationError) as error:
            raise ValueError(f"{relative}: {error}") from error
        return value

    manifest = read("manifest.json", "Manifest")
    genres = index(read(manifest["genres"], "Genres"), lambda row: row["id"])
    search = index(read(manifest["search"], "Search"), lambda row: (row["kind"], row["id"]))
    artist_ids = {id_ for kind, id_ in search if kind == "artist"}
    if {id_ for kind, id_ in search if kind == "genre"} != genres.keys():
        raise ValueError("Search must contain every genre exactly once")

    summaries = {}
    memberships = {id_: {} for id_ in artist_ids}

    def artist_summary(artist):
        id_ = artist["id"]
        if id_ not in artist_ids or search["artist", id_]["name"] != artist["name"]:
            raise ValueError(f"Unknown or inconsistent artist: {id_}")
        if id_ in summaries and summaries[id_] != artist:
            raise ValueError(f"Inconsistent artist summary: {id_}")
        summaries[id_] = artist
        positions(artist)

    def positions(entity):
        for layout, point in entity["positions"].items():
            if point is not None and manifest["layouts"][layout] is None:
                raise ValueError(f"{entity['id']}: unavailable layout {layout}")

    def ranked(rows, target, feature, self_id=None, nested=False):
        if manifest[feature] is None and rows is not None:
            raise ValueError(f"{feature} is unavailable; expected null")
        if rows is None:
            return
        ids = [row["artist"]["id"] if nested else row["id"] for row in rows]
        if len(set(ids)) != len(ids) or any(id_ not in target or id_ == self_id for id_ in ids):
            raise ValueError(f"Invalid {feature} references")
        ordering = [(-row["score"], id_) for row, id_ in zip(rows, ids, strict=True)]
        if ordering != sorted(ordering):
            raise ValueError(f"{feature} must be score-descending, then ID-ascending")
        if nested:
            for row in rows:
                artist_summary(row["artist"])

    for id_, genre in genres.items():
        positions(genre)
        entry = search["genre", id_]
        if entry["name"] != genre["name"] or entry["aliases"] != genre["aliases"]:
            raise ValueError(f"Inconsistent genre search entry: {id_}")
        visited = {id_}
        parent = genre["parent_id"]
        while parent is not None:
            if parent not in genres or parent in visited:
                raise ValueError(f"Invalid hierarchy at {id_}")
            visited.add(parent)
            parent = genres[parent]["parent_id"]
        detail = read(f"genres/{id_}.json", "GenreDetail")
        if detail["genre"] != genre:
            raise ValueError(f"Inconsistent genre detail: {id_}")
        ranked(detail["members"], artist_ids, "membership", nested=True)
        for member in detail["members"] or []:
            memberships[member["artist"]["id"]][id_] = member["score"]
        ranked(detail["related"], genres, "genre_similarity", self_id=id_)
        count = None if detail["members"] is None else len(detail["members"])
        if genre["member_count"] != count:
            raise ValueError(f"Inconsistent member count: {id_}")

    for id_ in sorted(artist_ids):
        detail = read(f"artists/{id_}.json", "ArtistDetail")
        if detail["artist"]["id"] != id_:
            raise ValueError(f"Inconsistent artist detail: {id_}")
        artist_summary(detail["artist"])
        ranked(detail["genres"], genres, "membership")
        projected = {row["id"]: row["score"] for row in detail["genres"] or []}
        if projected != memberships[id_]:
            raise ValueError(f"Inconsistent membership directions: {id_}")
        ranked(detail["similar"], artist_ids, "similarity", self_id=id_, nested=True)
    return manifest


def reject_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def index(rows, key):
    result = {key(row): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate entity ID")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_release(args.release)))
