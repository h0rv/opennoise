import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from opennoise.names import canonical, duplicates, key, rename, write


def release(root, release_id, *, duplicates_only=False, additions=None):
    manifest = json.loads((root / "manifest.json").read_text())
    genres = json.loads((root / manifest["genres"]).read_text())
    additions = additions or {}
    if additions.keys() & ({g["id"] for g in genres} | manifest.get("genre_redirects", {}).keys()):
        raise ValueError("New genre ID already in the catalog")
    genres.extend(detail["genre"] for detail in additions.values())
    rows = {g["id"]: g for g in genres}
    if duplicates_only:
        for genre in genres:
            rename(genre)
        targets, conflicts = duplicates(genres)
        return rewrite(root, release_id, manifest, rows, targets, additions=additions) | {
            "merged_groups": len(set(targets.values())),
            "conflicts": conflicts,
        }
    clusters = {
        i
        for i, g in rows.items()
        if " · " in g["name"] or re.search(r" \((?:[2-9]|[1-9][0-9]+)\)$", g["name"])
    }
    targets = {}
    for i in clusters:
        parent, seen = rows[i]["parent_id"], {i}
        while parent in clusters:
            if parent in seen:
                raise ValueError(f"Cyclic cluster hierarchy: {i}")
            seen.add(parent)
            parent = rows[parent]["parent_id"]
        if parent is None or parent not in rows:
            raise ValueError(f"Cluster has no named ancestor: {i}")
        targets[i] = parent
    groups = defaultdict(list)
    for i, g in rows.items():
        if i not in clusters:
            groups[key(canonical(g["name"]))].append(g)
    variants = []
    for group in groups.values():
        anchor = max(group, key=lambda g: (g["member_count"] or 0, g["id"]))
        aliases = set(anchor["aliases"])
        for g in group:
            aliases.update([g["name"], *g["aliases"]])
            if g is not anchor:
                targets[g["id"]] = anchor["id"]
                variants.append([g["name"], anchor["name"]])
        anchor["name"] = canonical(anchor["name"])
        anchor["aliases"] = sorted(aliases - {anchor["name"]})

    return rewrite(
        root, release_id, manifest, rows, targets, named_layout=True, additions=additions
    ) | {
        "clusters": len(clusters),
        "variants": sorted(variants),
    }


def rewrite(root, release_id, manifest, rows, targets, *, named_layout=False, additions=None):
    additions = additions or {}

    def target(i):
        while i in targets:
            i = targets[i]
        return i

    kept = {i: g for i, g in rows.items() if i not in targets}
    for i, g in kept.items():
        parent = g["parent_id"]
        seen = {i}
        while parent is not None and (parent in targets or parent in seen):
            if parent in seen and parent != i:
                raise ValueError(f"Cyclic genre hierarchy: {i}")
            seen.add(parent)
            resolved = target(parent)
            parent = rows[parent]["parent_id"] if resolved == i else resolved
        g["parent_id"] = parent
    members = {i: {} for i in kept}
    related = {i: {} for i in kept}
    details = {}
    for i in rows:
        detail = additions.get(i) or json.loads((root / "genres" / f"{i}.json").read_text())
        resolved = target(i)
        if i in kept:
            details[i] = detail
        for member in detail["members"] or []:
            group = members[resolved]
            artist = member["artist"]["id"]
            if artist not in group or member["score"] > group[artist]["score"]:
                group[artist] = member
        if not named_layout:
            for neighbor in detail["related"] or []:
                other = target(neighbor["id"])
                if other != resolved:
                    scores = related[resolved]
                    scores[other] = max(scores.get(other, 0), neighbor["score"])
    projected = defaultdict(list)
    for i, g in kept.items():
        detail = details[i]
        ranked = sorted(members[i].values(), key=lambda m: (-m["score"], m["artist"]["id"]))
        detail["members"] = ranked if manifest["membership"] is not None else None
        g["member_count"] = len(ranked) if manifest["membership"] is not None else None
        detail["genre"] = g
        if detail["related"] is not None:
            if named_layout:
                detail["related"] = [r for r in detail["related"] if r["id"] in kept]
            else:
                detail["related"] = [
                    {"id": other, "score": score}
                    for other, score in sorted(related[i].items(), key=lambda r: (-r[1], r[0]))[:10]
                ]
        for member in ranked:
            projected[member["artist"]["id"]].append({"id": i, "score": member["score"]})
    search = json.loads((root / manifest["search"]).read_text())
    search = [e for e in search if e["kind"] != "genre" or e["id"] in kept]
    search.extend(
        {"kind": "genre", "id": i, "name": kept[i]["name"], "aliases": kept[i]["aliases"]}
        for i in additions
        if i in kept
    )
    zero_before = zero_after = 0
    for entry in search:
        i = entry["id"]
        if entry["kind"] == "genre":
            entry.update(name=kept[i]["name"], aliases=kept[i]["aliases"])
            continue
        path = root / "artists" / f"{i}.json"
        detail = json.loads(path.read_text())
        zero_before += not detail["genres"]
        detail["genres"] = (
            sorted(projected[i], key=lambda g: (-g["score"], g["id"]))
            if manifest["membership"] is not None
            else None
        )
        zero_after += not detail["genres"]
        write(path, detail)
    for i, detail in details.items():
        write(root / "genres" / f"{i}.json", detail)
    for i in targets:
        if i not in additions:
            (root / "genres" / f"{i}.json").unlink()
    manifest["release_id"] = release_id
    redirects = {old: target(new) for old, new in manifest.get("genre_redirects", {}).items()}
    redirects.update({old: target(new) for old, new in targets.items() if old not in additions})
    manifest["genre_redirects"] = redirects
    if named_layout:
        manifest["layouts"]["axes"] = {
            "x_min": "rock",
            "x_max": "electronic",
            "y_min": "electric",
            "y_max": "acoustic",
        }
    write(root / manifest["genres"], list(kept.values()))
    write(root / manifest["search"], search)
    write(root / "manifest.json", manifest)
    return {
        "genres_before": len(rows),
        "genres_after": len(kept),
        "zero_before": zero_before,
        "zero_after": zero_after,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    parser.add_argument("release_id")
    parser.add_argument("--duplicates-only", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            release(args.release, args.release_id, duplicates_only=args.duplicates_only),
            ensure_ascii=False,
        )
    )
