from collections import defaultdict

import polars as pl

from opennoise.metrics import normalized_name


def siblings(rows, parents, memberships, public):
    buckets = defaultdict(list)
    for row in rows:
        buckets[parents[row["id"]], normalized_name(row["name"])].append(row)
    roots = sum(p is None for p in parents.values())
    plans, records, keys = [], [], {}
    next_id = max(parents, default=-1) + 1
    for (parent, name), children in sorted(buckets.items(), key=lambda pair: str(pair[0])):
        if len(children) < 2:
            continue
        broadest = min(r["level"] for r in children)
        anchors = [r for r in children if r["level"] == broadest]
        if len(anchors) == 1:
            anchor = anchors[0]
        else:
            anchor = {"id": next_id, "name": min(r["name"] for r in children), "level": -2}
            next_id += 1
            rows.append(anchor)
            parents[anchor["id"]] = parent
            key = "group:" + (public[parent] if parent is not None else "root") + ":" + name
            keys[anchor["id"]] = key
            records.append({"key": key, "scope": "group", "name": anchor["name"], "members": []})
        ids = [r["id"] for r in children if r["id"] != anchor["id"]]
        for i in ids:
            parents[i] = anchor["id"]
        plans.append((anchor["id"], ids))
    edges = {
        i: dict(group.select("artist", "score").iter_rows())
        for (i,), group in memberships.partition_by("genre", as_dict=True).items()
    }

    def depth(i):
        value = 0
        while parents[i] is not None:
            i = parents[i]
            value += 1
        return value

    for anchor, children in sorted(plans, key=lambda p: depth(p[0]), reverse=True):
        union = edges.setdefault(anchor, {})
        for child in children:
            for artist, score in edges.get(child, {}).items():
                union[artist] = max(union.get(artist, 0), score)
    anchors = [i for i, _ in plans]
    additions = pl.DataFrame(
        [(a, i, s) for i in anchors for a, s in edges[i].items()],
        schema=memberships.schema,
        orient="row",
    )
    memberships = pl.concat([memberships.filter(~pl.col("genre").is_in(anchors)), additions])
    names = {r["id"]: r["name"] for r in rows}
    report = {
        "roots_before": roots,
        "roots_after": sum(p is None for p in parents.values()),
        "minted": len(records),
        "existing_anchors": len(plans) - len(records),
        "largest": [
            {"local_id": i, "name": names[i], "children": len(c), "members": len(edges[i])}
            for i, c in sorted(plans, key=lambda p: (-len(p[1]), p[0]))[:15]
        ],
    }
    return memberships, records, keys, report


def readable(rows, parents, memberships, artists, public):
    names = {r["id"]: r["name"] for r in rows}

    def counts():
        buckets = defaultdict(int)
        for i, name in names.items():
            buckets[parents[i], normalized_name(name)] += 1
        return {
            "roots": sum(p is None for p in parents.values()),
            "same_name_parent_edges": sum(
                p is not None and normalized_name(names[i]) == normalized_name(names[p])
                for i, p in parents.items()
            ),
            "same_name_sibling_extras": sum(n - 1 for n in buckets.values()),
        }

    before = counts()
    lifted = 0
    for i in sorted(parents, key=lambda i: public[i]):
        parent = parents[i]
        while parent is not None and parents[parent] is not None:
            grandparent = parents[parent]
            if normalized_name(names[parent]) != normalized_name(names[grandparent]):
                break
            parent = grandparent
            lifted += 1
        parents[i] = parent
    buckets = defaultdict(list)
    for i, name in names.items():
        buckets[parents[i], normalized_name(name)].append(i)
    rename = {i for ids in buckets.values() if len(ids) > 1 for i in ids} | {
        i
        for i, p in parents.items()
        if p is not None and normalized_name(names[i]) == normalized_name(names[p])
    }
    candidates = {
        i: group["artist_name"].to_list()
        for (i,), group in memberships.join(
            artists.select("artist_mbid", "artist_name", "listeners"),
            left_on="artist",
            right_on="artist_mbid",
        )
        .sort(["score", "listeners", "artist"], descending=[True, True, False])
        .partition_by("genre", as_dict=True)
        .items()
    }
    used = defaultdict(set)
    for i, name in names.items():
        if i not in rename:
            used[parents[i]].add(normalized_name(name))
    fallback = 0

    def depth(i):
        value = 0
        while parents[i] is not None:
            i = parents[i]
            value += 1
        return value

    for i in sorted(names, key=lambda i: (depth(i), public[i])):
        parent_name = normalized_name(names[parents[i]]) if parents[i] is not None else ""
        if normalized_name(names[i]) == parent_name:
            rename.add(i)
        if i not in rename:
            continue
        options = candidates.get(i) or ["Artists unavailable"]
        for artist in options:
            label = names[i] + " · " + artist
            if (
                normalized_name(label) not in used[parents[i]]
                and normalized_name(label) != parent_name
            ):
                break
        else:
            n = 2
            while (
                normalized_name(label + f" ({n})") in used[parents[i]]
                or normalized_name(label + f" ({n})") == parent_name
            ):
                n += 1
            label += f" ({n})"
            fallback += 1
        names[i] = label
        used[parents[i]].add(normalized_name(label))
    for row in rows:
        row["name"] = names[row["id"]]
    if counts()["same_name_parent_edges"] or counts()["same_name_sibling_extras"]:
        raise ValueError("Ambiguous display names after cleanup")
    return {
        "before": before,
        "after": counts(),
        "lifted": lifted,
        "renamed": len(rename),
        "exhausted_member_names": fallback,
    }
