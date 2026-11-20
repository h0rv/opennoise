import json
import shutil
from pathlib import Path

import pytest

from opennoise.named import release
from opennoise.names import write


@pytest.fixture
def catalog(tmp_path):
    root = tmp_path / "catalog"
    shutil.copytree(Path(__file__).parent / "fixtures" / "catalog", root)
    return root


def read(root, path):
    return json.loads((root / path).read_text())


def test_fold_and_merge(catalog):
    genres = read(catalog, "genres.json")
    by = {g["id"]: g for g in genres}
    by["electronic"]["name"] = "reggaetón"
    by["techno"]["name"] = "reguetón"
    by["house"]["name"] = "reggaetón · Artist"
    by["house"]["parent_id"] = "techno"
    by["shoegaze"]["name"] = "rock (10)"
    by["post-rock"]["parent_id"] = "house"
    write(catalog / "genres.json", genres)
    before = {
        p.stem: read(catalog, p.relative_to(catalog))["genres"]
        for p in (catalog / "artists").glob("*.json")
    }
    report = release(catalog, "named")
    by = {g["id"]: g for g in read(catalog, "genres.json")}
    assert report["clusters"] == 2
    assert report["variants"] == [["reguetón", "reggaetón"]]
    assert {"house", "techno", "shoegaze"}.isdisjoint(by)
    assert by["post-rock"]["parent_id"] == "electronic"
    assert "reguetón" in by["electronic"]["aliases"]
    assert read(catalog, "manifest.json")["release_id"] == "named"
    expected = {i: {} for i in by}
    mapping = {"house": "electronic", "techno": "electronic", "shoegaze": "rock"}
    for artist, memberships in before.items():
        merged = {}
        for m in memberships:
            i = mapping.get(m["id"], m["id"])
            merged[i] = max(merged.get(i, 0), m["score"])
        assert read(catalog, f"artists/{artist}.json")["genres"] == sorted(
            ({"id": i, "score": score} for i, score in merged.items()),
            key=lambda g: (-g["score"], g["id"]),
        )
        for i, score in merged.items():
            expected[i][artist] = score
    for i in by:
        detail = read(catalog, f"genres/{i}.json")
        assert detail["genre"] == by[i]
        assert by[i]["member_count"] == len(expected[i])
        assert [(m["artist"]["id"], m["score"]) for m in detail["members"]] == sorted(
            expected[i].items(), key=lambda m: (-m[1], m[0])
        )
        assert all(r["id"] in by for r in detail["related"] or [])
    assert {p.stem for p in (catalog / "genres").glob("*.json")} == by.keys()
    assert {e["id"] for e in read(catalog, "search.json") if e["kind"] == "genre"} == by.keys()


def test_empty_memberships(catalog):
    manifest = read(catalog, "manifest.json")
    manifest["membership"] = None
    write(catalog / "manifest.json", manifest)
    for path in (catalog / "genres").glob("*.json"):
        detail = json.loads(path.read_text())
        detail["members"] = None
        write(path, detail)
    report = release(catalog, "empty")
    assert report["variants"] == []
    assert all(g["member_count"] is None for g in read(catalog, "genres.json"))
    for path in (catalog / "artists").glob("*.json"):
        assert json.loads(path.read_text())["genres"] is None


@pytest.mark.parametrize("parent", [None, "house"])
def test_invalid_cluster_ancestor(catalog, parent):
    genres = read(catalog, "genres.json")
    house = next(g for g in genres if g["id"] == "house")
    house.update(name="house · Artist", parent_id=parent)
    write(catalog / "genres.json", genres)
    original = (catalog / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="ancestor|Cyclic"):
        release(catalog, "invalid")
    assert (catalog / "manifest.json").read_bytes() == original
