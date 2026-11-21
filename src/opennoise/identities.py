import hashlib
import json
import re
from collections import Counter, defaultdict


def stable_id(key: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "genre"
    return slug + "-" + hashlib.sha256(key.encode()).hexdigest()[:12]


def assign(path, records, threshold=0.8):
    state: dict = json.loads(path.read_text()) if path.exists() else {"version": 1, "genres": []}
    old = {r["id"]: r for r in state["genres"]}
    incoming = {r["key"]: r for r in records}
    if state["version"] != 1 or len(old) != len(state["genres"]) or len(incoming) != len(records):
        raise ValueError("Invalid identity registry or duplicate genre keys")
    active = {i: r for i, r in old.items() if r["active"]}
    exact = {r["key"]: i for i, r in active.items()}
    chosen = {k: exact[k] for k in incoming if k in exact}
    postings = defaultdict(set)
    for i, row in active.items():
        if row["scope"] != "supervised":
            for member in row["members"]:
                postings[row["scope"], member].add(i)
    overlaps, children, merges = {}, defaultdict(set), {}
    for key, row in incoming.items():
        if row["scope"] == "supervised":
            continue
        counts = Counter(i for m in row["members"] for i in postings[row["scope"], m])
        overlaps[key] = counts
        for i, count in counts.items():
            if count / len(row["members"]) >= threshold:
                children[i].add(key)
        covered = {
            i for i, count in counts.items() if count / len(active[i]["members"]) >= threshold
        }
        if len(covered) > 1 and sum(counts[i] for i in covered) >= threshold * len(row["members"]):
            merges[key] = covered
    splits = {i for i, keys in children.items() if len(keys) > 1}
    candidates = []
    for key, counts in overlaps.items():
        if key in chosen:
            continue
        for i, count in counts.items():
            jaccard = count / (len(incoming[key]["members"]) + len(active[i]["members"]) - count)
            if i not in splits and (jaccard >= threshold or i in merges.get(key, set())):
                candidates.append((-jaccard, i, key))
    used = set(chosen.values())
    for _, i, key in sorted(candidates):
        if key not in chosen and i not in used:
            chosen[key] = i
            used.add(i)
    for row in old.values():
        row["active"] = False
    result = {}
    for key, row in sorted(incoming.items()):
        i = chosen.get(key)
        if i is None:
            base = stable_id(key, row["name"])
            i, suffix = base, 1
            while i in old:
                suffix += 1
                i = f"{base}-{suffix}"
        previous = old.get(i, {})
        aliases = set(previous.get("aliases", []))
        if previous.get("name"):
            aliases.add(previous["name"])
        for retired in merges.get(key, set()) - used:
            aliases.add(old[retired]["name"])
            aliases.update(old[retired]["aliases"])
        aliases.discard(row["name"])
        old[i] = {**row, "id": i, "active": True, "aliases": sorted(aliases)}
        result[key] = old[i]
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_text(
        json.dumps(
            {"version": 1, "genres": [old[i] for i in sorted(old)]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    part.replace(path)
    return result
