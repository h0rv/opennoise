import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

NAMES = json.loads(Path(__file__).with_name("names.json").read_text())


def key(text):
    text = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    return "".join(
        re.findall(r"[a-z0-9]+", "".join(c for c in text if not unicodedata.combining(c)))
    )


def canonical(name, names=NAMES):
    words, out, i = name.casefold().split(), [], 0
    while i < len(words):
        for j in range(min(len(words), i + 6), i, -1):
            if target := names.get(key(" ".join(words[i:j]))):
                out.append(target)
                i = j
                break
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


def clean(genres, members, names=NAMES):
    rows = {g["id"]: g for g in genres}
    old = {i: g["name"] for i, g in rows.items()}
    bases = {}
    for i, g in rows.items():
        base, _, suffix = g["name"].partition(" · ")
        bases[i] = canonical(base, names)
        g["name"] = bases[i] + (" · " + suffix if suffix else "")
    top = defaultdict(list)
    for i, g in rows.items():
        if g["parent_id"] is None:
            top[key(bases[i]).removesuffix("music")].append(g)
    anchors, merged, extra = {}, 0, defaultdict(set)
    for k, group in top.items():
        anchor = anchors[k] = max(group, key=lambda g: (g["member_count"], g["id"]))
        for g in group:
            if g is not anchor:
                for child in rows.values():
                    if child["parent_id"] == g["id"]:
                        child["parent_id"] = anchor["id"]
                g["parent_id"] = anchor["id"]
                extra[anchor["id"]].update([old[g["id"]], *g["aliases"]])
                merged += 1
    for i, g in rows.items():
        if anchor := anchors.get(key(bases[i]).removesuffix("music")):
            g["name"] = g["name"].replace(bases[i], anchor["name"], 1)
    siblings = defaultdict(list)
    for g in rows.values():
        siblings[g["parent_id"]].append(g)
    for parent, group in siblings.items():
        used = {rows[parent]["name"]} if parent else set()
        for g in sorted(group, key=lambda g: (g["name"] in used, -g["member_count"], g["id"])):
            if g["name"] in used:
                base = g["name"].partition(" · ")[0]
                options = [base + " · " + m for m in members.get(g["id"], [])]
                options += [f"{base} ({n})" for n in range(2, len(group) + 3)]
                g["name"] = next(o for o in options if o not in used)
            used.add(g["name"])
    for i, g in rows.items():
        if " · " not in old[i]:
            extra[i].add(old[i])
        g["aliases"] = sorted((set(g["aliases"]) | extra[i]) - {g["name"]})
    return {"renamed": sum(g["name"] != old[i] for i, g in rows.items()), "merged": merged}


def release(root, release_id):
    manifest = json.loads((root / "manifest.json").read_text())
    genres = json.loads((root / manifest["genres"]).read_text())
    details = {
        g["id"]: json.loads((root / "genres" / f"{g['id']}.json").read_text()) for g in genres
    }
    members = {i: [m["artist"]["name"] for m in d["members"]] for i, d in details.items()}
    report = clean(genres, members)
    by_id = {g["id"]: g for g in genres}
    search = json.loads((root / manifest["search"]).read_text())
    for entry in search:
        if entry["kind"] == "genre":
            entry["name"], entry["aliases"] = (
                by_id[entry["id"]]["name"],
                by_id[entry["id"]]["aliases"],
            )
    for i, detail in details.items():
        detail["genre"] = by_id[i]
        write(root / "genres" / f"{i}.json", detail)
    manifest["release_id"] = release_id
    for name, value in [
        (manifest["genres"], genres),
        (manifest["search"], search),
        ("manifest.json", manifest),
    ]:
        write(root / name, value)
    return report


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    parser.add_argument("release_id")
    args = parser.parse_args()
    print(json.dumps(release(args.release, args.release_id)))


if __name__ == "__main__":
    main()
