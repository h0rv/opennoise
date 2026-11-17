import json
import subprocess
import time
import tomllib
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import polars as pl
from joblib import Parallel, delayed
from scipy import sparse
from scipy.sparse import linalg
from sklearn.ensemble import HistGradientBoostingClassifier

from opennoise import tags
from opennoise.genres import graph_matrix, split_labels
from opennoise.metrics import normalized_name, sealed
from opennoise.reference import table

GEO = ["area", "area_alias", "iso_3166_1", "l_area_area"]
DEMONYMS = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT DISTINCT ?iso ?name WHERE { ?c wdt:P297 ?iso; wdt:P1549 ?name FILTER(LANG(?name)="en") }"""


def settings(config):
    return tomllib.loads(Path(config["m2_config"]).read_text())


def ingest(config, run):
    root = Path(config["cache"])
    root.mkdir(parents=True, exist_ok=True)
    if not all((root / "mbdump" / name).exists() for name in GEO):
        sources = tomllib.loads(Path("sources.toml").read_text())["sources"]
        source = next(row for row in sources if row["url"].endswith("/mbdump.tar.bz2"))
        members = " ".join(f"mbdump/{name}" for name in GEO)
        subprocess.run(
            [
                "bash",
                "-c",
                f"set -o pipefail; curl -fL '{source['url']}' | "
                f"bzip2 -dc | tar -xf - -C '{root}' {members}",
            ],
            check=True,
        )
    if not (root / "demonyms.tsv").exists():
        params = urllib.parse.urlencode({"query": DEMONYMS})
        request = urllib.request.Request(
            config["endpoint"] + "?" + params, headers={"Accept": "text/tab-separated-values"}
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            (root / "demonyms.tsv").write_bytes(response.read())


def geo_table(config, name, columns, names):
    data = pl.read_csv(
        Path(config["cache"]) / "mbdump" / name,
        separator="\t",
        has_header=False,
        quote_char=None,
        infer_schema=False,
        columns=columns,
        null_values="\\N",
    )
    return data.rename(dict(zip(data.columns, names, strict=True)))


def places(config, artists):
    home = table("artist", [1, 11, 17], ["artist_mbid", "area", "begin"]).join(
        artists.select("artist_mbid", "item"), on="artist_mbid"
    )
    parents = defaultdict(list)
    for parent, child in geo_table(config, "l_area_area", [2, 3], ["parent", "child"]).iter_rows():
        parents[child].append(parent)
    pairs = {}
    for item, area, begin in home.select("item", "area", "begin").iter_rows():
        frontier = [x for x in (area, begin) if x]
        depth = 0
        while frontier and depth < 6:
            for place in frontier:
                pairs.setdefault((item, place), depth)
            frontier = [p for place in frontier for p in parents[place]]
            depth += 1
    areas = sorted({place for _, place in pairs})
    index = {place: i for i, place in enumerate(areas)}
    rows = np.array([item for item, _ in pairs])
    columns = np.array([index[place] for _, place in pairs])
    depth = sparse.csr_matrix(
        (np.array(list(pairs.values())) + 1.0, (rows, columns)), shape=(len(artists), len(areas))
    )
    return depth, areas


def lexicon(config, areas, sizes):
    position = {area: i for i, area in enumerate(areas)}
    words = defaultdict(dict)
    names = geo_table(config, "area", [0, 2], ["area", "name"])
    aliases = geo_table(config, "area_alias", [1, 2, 3], ["area", "name", "locale"]).filter(
        pl.col("locale") == "en"
    )
    codes = dict(
        geo_table(config, "iso_3166_1", [0, 1], ["area", "code"]).select("code", "area").iter_rows()
    )
    demonyms = [
        (codes[iso.strip('"')], name.rsplit("@", 1)[0].strip('"'))
        for iso, name in (
            line.split("\t")
            for line in (Path(config["cache"]) / "demonyms.tsv").read_text().splitlines()[1:]
        )
        if iso.strip('"') in codes
    ]
    countries = set(codes.values())
    for area, name in [*names.iter_rows(), *aliases.select("area", "name").iter_rows(), *demonyms]:
        word = normalized_name(name)
        if area in position and word and sizes[position[area]] >= config["min_place_artists"]:
            words[word][position[area]] = sizes[position[area]] * (10 if area in countries else 1)
    return {word: max(options, key=options.get) for word, options in words.items()}


def split_name(name, words, styles=None):
    tokens = normalized_name(name).split()
    for cut in (2, 1):
        head, rest = " ".join(tokens[:cut]), " ".join(tokens[cut:])
        if head in words and rest and (styles is None or rest in styles):
            return words[head], head, rest
    return None


def learned_words(train, depth, words, vocabulary):
    present = depth.copy()
    present.data[:] = 1
    base = np.asarray(present.mean(axis=0)).ravel()
    heads = defaultdict(list)
    for name in train:
        tokens = normalized_name(name).split()
        if len(tokens) > 1 and " ".join(tokens[1:]) in vocabulary:
            heads[tokens[0]].append(name)
    learned, rejected = {}, set()
    for head, names in heads.items():
        if len(names) < 2:
            continue
        members = np.unique(np.concatenate([train[name] for name in names]))
        share = np.asarray(present[members].mean(axis=0)).ravel()
        place = int(np.argmax(share - base))
        if head in words:
            if share[words[head]] < 0.3:
                rejected.add(head)
        elif share[place] >= 0.5 and share[place] >= 5 * base[place]:
            learned[head] = place
    return learned, rejected


def style_evidence(config, artists, train, words):
    n = len(artists)
    root = Path(config["m2c"])
    vocabulary = pl.read_parquet(root / "vocabulary.parquet")
    links = (
        pl.read_parquet(root / "artist_genres.parquet")
        .filter(~pl.col("artist_mbid").map_elements(sealed, return_dtype=pl.Boolean))
        .join(artists.select("artist_mbid", "item"), on="artist_mbid")
    )
    links = links.join(vocabulary.select("qid", "normalized").unique(), on="qid")
    discogs = pl.read_parquet(Path(config["tags_run"]) / "discogs.parquet").join(
        artists.select("artist_mbid", "item"), on="artist_mbid"
    )
    discogs = discogs.with_columns(
        (pl.col("weight").log1p() / pl.col("weight").log1p().sum().over("item")).alias("share"),
        pl.col("tag").map_elements(normalized_name, return_dtype=pl.String).alias("normalized"),
    )
    owners = defaultdict(list)
    for name in train:
        tokens = normalized_name(name).split()
        for start in range(len(tokens)):
            owners[" ".join(tokens[start:])].append(name)
    styles = sorted(set(owners) | set(links["normalized"]) | set(discogs["normalized"]))
    styles = [style for style in styles if style and style not in words]
    column = {style: i for i, style in enumerate(styles)}
    order = {name: i for i, name in enumerate(sorted(train))}
    member = sparse.csr_matrix(
        (
            np.ones(sum(len(x) for x in train.values())),
            (
                np.concatenate([train[name] for name in order]),
                np.repeat(np.arange(len(order)), [len(train[name]) for name in order]),
            ),
        ),
        shape=(n, len(order)),
    )
    pairs = [
        (order[name], column[style])
        for style, names in owners.items()
        if style in column
        for name in names
    ]
    suffix = sparse.csr_matrix(
        (np.ones(len(pairs)), tuple(np.array(pairs).T)), shape=(len(order), len(styles))
    )

    def matrix(frame, values):
        frame = frame.filter(pl.col("normalized").is_in(styles))
        return sparse.csr_matrix(
            (values(frame), (frame["item"].to_numpy(), [column[x] for x in frame["normalized"]])),
            shape=(n, len(styles)),
        )

    wikidata = matrix(links.unique(["item", "normalized"]), lambda f: np.ones(len(f)))
    styled = matrix(
        discogs.group_by("item", "normalized").agg(pl.col("share").sum()),
        lambda f: f["share"].to_numpy(),
    )
    return styles, column, order, member, suffix, wikidata, styled


def at(matrix, items, places, default):
    out = np.full(len(items), default, dtype=np.float64)
    local = places >= 0
    out[local] = np.asarray(matrix[items[local], places[local]]).ravel()
    return out


def rows_for(items, places, style, state, enao, near):
    return np.column_stack(
        [
            enao[items],
            state["wikidata"][:, style].toarray().ravel()[items],
            state["discogs"][:, style].toarray().ravel()[items],
            near[items],
            at(state["near_place"], items, places, 1.0),
            state["listeners"][items],
            at(state["depth"], items, places, 0.0),
            np.full(len(items), np.log1p(np.count_nonzero(near))),
        ]
    )


def nearby(state, style, enao):
    seeded = enao + state["wikidata"][:, style].toarray().ravel() > 0
    return state["transition"] @ seeded.astype(np.float32)


def prepare(config):
    artists = pl.read_parquet(Path(config["m1"]) / "artists.parquet")
    _, transition = graph_matrix(config, {"k": config["k"]})
    depth, areas = places(config, artists)
    scope = artists["listeners"].to_numpy() >= config["min_listeners"]
    depth = (sparse.diags(scope.astype(float)) @ depth).tocsr()
    depth.eliminate_zeros()
    present = depth.copy()
    present.data[:] = 1
    return {
        "artists": artists,
        "transition": transition.tocsr(),
        "depth": depth,
        "pools": present.tocsc(),
        "near_place": (transition @ present).tocsr(),
        "listeners": np.log1p(artists["listeners"].to_numpy()),
        "areas": areas,
        "lexicon": lexicon(config, areas, np.asarray(present.sum(axis=0)).ravel()),
    }


def fitted(config, base, train):
    words = base["lexicon"]
    styles, column, order, member, suffix, wikidata, discogs = style_evidence(
        config, base["artists"], train, words
    )
    learned, rejected = learned_words(train, base["depth"], words, set(column))
    return base | {
        "wikidata": wikidata.tocsc(),
        "discogs": discogs.tocsc(),
        "member": member.tocsc(),
        "suffix": suffix.tocsc(),
        "styles": styles,
        "column": column,
        "order": order,
        "words": {w: p for w, p in {**words, **learned}.items() if w not in rejected},
    }


def enao_seed(state, style, without=None):
    owners = state["suffix"][:, style].indices
    if without is not None:
        owners = owners[owners != without]
    return np.asarray(state["member"][:, owners].sum(axis=1)).ravel().clip(0, 3)


def candidates(state, style, enao, near):
    found = (near > 0) | (enao > 0)
    for source in ("wikidata", "discogs"):
        found[state[source][:, style].indices] = True
    return found


def training_rows(config, state, train):
    rng = np.random.default_rng(config["seed"])
    x, y, weights, groups = [], [], [], []
    for name, members in train.items():
        parts = split_name(name, state["words"], state["column"])
        normal = normalized_name(name)
        if parts:
            place, style = parts[0], state["column"][parts[2]]
        elif normal in state["column"] and (
            state["wikidata"][:, state["column"][normal]].nnz
            or state["discogs"][:, state["column"][normal]].nnz
        ):
            place, style = -1, state["column"][normal]
        else:
            continue
        enao = enao_seed(state, style, state["order"][name])
        near = nearby(state, style, enao)
        pool = candidates(state, style, enao, near)
        if place >= 0:
            local = np.zeros(len(pool), dtype=bool)
            local[state["pools"][:, place].indices] = True
            pool &= local
        pool = np.flatnonzero(pool)
        positives = np.intersect1d(members, pool)
        negatives = np.setdiff1d(pool, members)
        take = min(len(negatives), max(config["negatives"], 5 * len(positives)))
        items = np.concatenate([positives, rng.choice(negatives, take, replace=False)])
        if not len(positives) or not take:
            continue
        x.append(rows_for(items, np.full(len(items), place), style, state, enao, near))
        y.append(np.isin(items, members))
        weight = min(len(negatives) / take, config["negative_weight"])
        weights.append(np.where(y[-1], 1.0, weight))
        groups.append(np.full(len(items), len(groups)))
    return np.vstack(x), np.concatenate(y), np.concatenate(weights), np.concatenate(groups)


def propose(config, state, model, train):
    taken = {normalized_name(name) for name in train}
    surface = defaultdict(list)
    for word, place in state["words"].items():
        surface[place].append(word)
    used = Counter(
        parts[1] for name in train if (parts := split_name(name, state["words"], state["column"]))
    )
    word = {place: min(forms, key=lambda w: (-used[w], len(w))) for place, forms in surface.items()}
    wd, dc = state["wikidata"], state["discogs"]
    evidence = ((wd > 0) + (dc > 0) + ((state["member"] @ state["suffix"]) > 0)).astype(np.float32)
    pools = state["pools"]
    counts = (pools.T @ evidence).tocsc()
    evidence = evidence.tocsc()
    floor, least = config["threshold"], config["min_members"]
    transition = state["transition"]
    proposals, facts = [], []
    for style, label in enumerate(state["styles"]):
        local = counts[:, style]
        support = dict(zip(local.indices, local.data, strict=True))
        places = [p for p, c in support.items() if c >= least and p in word]
        seen = [wd[:, style].nnz, dc[:, style].nnz, evidence[:, style].nnz]
        open_style = bool(seen[0] or seen[1]) and label not in taken
        if not places and not open_style:
            continue
        enao = enao_seed(state, style)
        near = nearby(state, style, enao)
        candidate = candidates(state, style, enao, near)
        groups = [(-1, np.flatnonzero(candidate))] if open_style else []
        for place in places:
            if f"{word[place]} {label}" not in taken:
                pool = pools[:, place].indices
                groups.append((place, pool[candidate[pool]]))
        groups = [(place, items) for place, items in groups if len(items) >= least]
        if not groups:
            continue
        items = np.concatenate([items for _, items in groups])
        tags = np.concatenate([np.full(len(items), place) for place, items in groups])
        x = rows_for(items, tags, style, state, enao, near)
        scores = model.predict_proba(x)[:, 1]
        start = 0
        for place, members in groups:
            rows = slice(start, start + len(members))
            start += len(members)
            keep = scores[rows] >= floor
            if keep.sum() < least:
                continue
            chosen, values = members[keep], scores[rows][keep]
            inside = np.zeros(len(near), dtype=np.float32)
            inside[chosen] = 1
            pool = pools[:, place].nnz if place >= 0 else len(near)
            proposals.append(
                (
                    f"{word[place]} {label}" if place >= 0 else label,
                    int(place),
                    style,
                    chosen,
                    values,
                )
            )
            facts.append(
                [
                    len(chosen),
                    values.mean(),
                    np.sort(values)[-least:].mean(),
                    (transition[chosen] @ inside).mean(),
                    *x[rows][keep][:, :3].astype(bool).mean(axis=0),
                    np.log(pool),
                    len(chosen) / pool,
                    support.get(place, seen[2]) / pool,
                    np.log1p(seen[2]),
                    state["suffix"][:, style].nnz,
                    used[word[place]] if place >= 0 else -1,
                    len(label.split()),
                    bool(seen[0]),
                    bool(seen[1]),
                ]
            )
    return proposals, np.array(facts, dtype=np.float64)


def member_model(config, state, train):
    x, y, weights, groups = training_rows(config, state, train)
    model = HistGradientBoostingClassifier(max_iter=200, random_state=config["seed"])
    return model.fit(x, y, sample_weight=weights), groups.max() + 1, len(y)


def crossfit(config, base, train, fold, folds):
    names = sorted(train)
    order = np.random.default_rng(config["seed"]).permutation(len(names)) % folds
    visible = {name: train[name] for name, f in zip(names, order, strict=True) if f != fold}
    hidden = {normalized_name(n): n for n, f in zip(names, order, strict=True) if f == fold}
    state = fitted(config, base, visible)
    proposals, facts = propose(config, state, member_model(config, state, visible)[0], visible)
    found = {p[0]: jaccard(p[3], train[hidden[p[0]]]) for p in proposals if p[0] in hidden}
    real = np.array([p[0] in hidden for p in proposals])
    return facts, real, len(hidden), sum(x >= 0.2 for x in found.values())


def jaccard(a, b):
    return len(np.intersect1d(a, b)) / max(len(np.union1d(a, b)), 1)


def overlaps(proposals, heldout, n):
    sizes = np.array([len(p[3]) for p in proposals])
    matrix = sparse.csr_matrix(
        (
            np.ones(sizes.sum(), dtype=np.float32),
            (
                np.repeat(np.arange(len(proposals)), sizes),
                np.concatenate([p[3] for p in proposals]),
            ),
        ),
        shape=(len(proposals), n),
    )
    best = {}
    for name, members in heldout.items():
        truth = np.zeros(n, dtype=np.float32)
        truth[members] = 1
        shared = matrix @ truth
        best[name] = float((shared / (sizes + len(members) - shared)).max())
    return best


def score(proposals, heldout, reference, n):
    named = {normalized_name(p[0]): p[3] for p in proposals}
    exact = [name for name in heldout if normalized_name(name) in named]
    both = [n for n in exact if jaccard(named[normalized_name(n)], heldout[n]) >= 0.2]
    best = overlaps(proposals, heldout, n)
    return {
        "genres": len(proposals),
        "real_name_share": sum(name in reference for name in named) / len(named),
        "heldout_named": len(exact) / len(heldout),
        "heldout_named_matched": len(both) / len(heldout),
        "genre_match": sum(x >= 0.2 for x in best.values()) / len(heldout),
        "median_jaccard": float(np.median(list(best.values()))),
    }


def related(proposals, transition, k=10):
    sizes = np.array([len(p[3]) for p in proposals])
    matrix = sparse.csr_matrix(
        (
            np.concatenate([p[4] for p in proposals]),
            (
                np.repeat(np.arange(len(proposals)), sizes),
                np.concatenate([p[3] for p in proposals]),
            ),
        ),
        shape=(len(proposals), transition.shape[0]),
    )
    matrix = sparse.diags(1 / linalg.norm(matrix, axis=1)) @ matrix
    spread = matrix @ transition
    spread = sparse.diags(1 / linalg.norm(spread, axis=1)) @ spread
    rows = []
    for start in range(0, len(proposals), 500):
        block = (spread[start : start + 500] @ spread.T).toarray()
        block[np.arange(block.shape[0]), np.arange(start, start + block.shape[0])] = 0
        top = np.argsort(-block, axis=1)[:, :k]
        for i, j in np.argwhere(np.take_along_axis(block, top, axis=1) > 0):
            rows.append((start + int(i), int(top[i, j]), float(block[i, top[i, j]])))
    return pl.DataFrame(rows, schema=["genre", "neighbor", "score"], orient="row")


def ranked(config, base, train):
    folds = config["folds"]
    parts = Parallel(n_jobs=folds)(
        delayed(crossfit)(config, base, train, fold, folds) for fold in range(folds)
    )
    params = {"max_iter": 300, "class_weight": "balanced", "random_state": config["seed"]}
    judge = HistGradientBoostingClassifier(**params).fit(
        np.vstack([p[0] for p in parts]), np.concatenate([p[1] for p in parts])
    )
    state = fitted(config, base, train)
    model, training_genres, training_rows_ = member_model(config, state, train)
    proposals, facts = propose(config, state, model, train)
    real = judge.predict_proba(facts)[:, 1]
    order = np.argsort(-real)
    return [proposals[i] for i in order], real[order], state, parts, training_genres, training_rows_


def trial(config, base, fit, valid, reference):
    kept = ranked(config, base, fit)[0][: config["keep"]]
    return score(kept, valid, reference, len(base["artists"]))


def tune(config, run):
    train = split_labels(settings(config))[0]
    names = sorted(train)
    held = set(np.random.default_rng(config["seed"]).choice(names, len(names) // 5, replace=False))
    fit = {name: train[name] for name in names if name not in held}
    valid = {name: train[name] for name in held}
    base = prepare(config)
    reference = {normalized_name(x) for x in pl.read_parquet("data/m2/map.parquet")["genre"]}
    grid = [
        {"threshold": t, "negative_weight": w}
        for t in config["grid"]["threshold"]
        for w in config["grid"]["negative_weight"]
    ]
    scores = Parallel(n_jobs=3)(
        delayed(trial)(config | point, base, fit, valid, reference) for point in grid
    )
    rows = [point | result for point, result in zip(grid, scores, strict=True)]
    rows.sort(key=lambda row: -row["heldout_named_matched"])
    (run / "tune.json").write_text(json.dumps(rows, indent=2))
    for row in rows:
        print(json.dumps(row), flush=True)


def build(config, run):
    start = time.monotonic()
    train, _, heldout, _ = split_labels(settings(config))
    base = prepare(config)
    proposals, real, state, parts, training_genres, training_rows_ = ranked(config, base, train)
    n = len(base["artists"])
    reference = {normalized_name(x) for x in pl.read_parquet("data/m2/map.parquet")["genre"]}
    sweep = {str(size): score(proposals[:size], heldout, reference, n) for size in config["sizes"]}
    kept = proposals[: config["keep"]]
    mbids = base["artists"]["artist_mbid"].to_numpy()
    sizes = [len(p[3]) for p in kept]
    pl.DataFrame(
        {
            "id": np.arange(len(kept)),
            "name": [p[0] for p in kept],
            "place": [base["areas"][p[1]] if p[1] >= 0 else None for p in kept],
            "style": [state["styles"][p[2]] for p in kept],
            "size": sizes,
            "real": real[: len(kept)],
            "heldout": [
                normalized_name(p[0]) in {normalized_name(x) for x in heldout} for p in kept
            ],
        }
    ).write_parquet(run / "genres.parquet")
    pl.DataFrame(
        {
            "genre": np.repeat(np.arange(len(kept)), sizes),
            "artist_mbid": mbids[np.concatenate([p[3] for p in kept])],
            "score": np.concatenate([p[4] for p in kept]),
        }
    ).write_parquet(run / "memberships.parquet")
    related(kept, state["transition"]).write_parquet(run / "related.parquet")
    metrics = {
        "training_genres": int(training_genres),
        "training_rows": training_rows_,
        "crossfit_proposals": sum(len(p[1]) for p in parts),
        "crossfit_named": int(sum(p[1].sum() for p in parts)) / sum(p[2] for p in parts),
        "crossfit_named_matched": sum(p[3] for p in parts) / sum(p[2] for p in parts),
        "proposals": len(proposals),
        "places": len(set(state["words"].values())),
        "styles": len(state["styles"]),
        "heldout_genres": len(heldout),
        "sweep": sweep,
        "seconds": time.monotonic() - start,
    }
    (run / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2), flush=True)


def release(run, genres, memberships):
    known = {
        normalized_name(name): i
        for i, name in genres.filter(pl.col("level") == -1).select("id", "name").iter_rows()
    }
    offset = genres["id"].max() + 1
    edges = pl.read_parquet(run / "memberships.parquet")
    aliases = edges.group_by("genre").agg(pl.col("artist_mbid").sort()).sort("genre")
    micro = pl.read_parquet(run / "genres.parquet").filter(
        ~pl.col("name").map_elements(normalized_name, return_dtype=pl.String).is_in(list(known))
        & pl.col("id").is_in(aliases.unique("artist_mbid", keep="first")["genre"].to_list())
    )
    added = micro.select(
        pl.col("id") + offset,
        "name",
        level=pl.lit(genres["level"].max() + 1),
        parent=pl.col("style").replace_strict(known, default=None, return_dtype=pl.Int64),
        size="size",
    ).cast(genres.schema)
    edges = (
        edges.filter(pl.col("genre").is_in(micro["id"].to_list()))
        .select(artist="artist_mbid", genre=pl.col("genre") + offset, score="score")
        .cast(memberships.schema)
    )
    return pl.concat([genres, added]), pl.concat([memberships, edges])


def execute(stage, config, run):
    if stage == "ingest":
        ingest(config, run)
    elif stage == "tune":
        tune(config, run)
    elif stage == "build":
        build(config, run)
    else:
        metrics = json.loads((run / "metrics.json").read_text())
        selected = metrics["sweep"][str(config["keep"])] | {
            "heldout_genres": metrics["heldout_genres"]
        }
        tags.log(
            run,
            "m3_place_style",
            selected,
            kept=True,
            note="unchanged 868-genre split; names composed from place plus style; "
            "membership and real-genre models trained on visible genres only; "
            "threshold and negative_weight tuned on a validation fifth of visible genres",
        )
