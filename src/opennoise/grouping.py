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
