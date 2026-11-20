import json
import shutil
from pathlib import Path

from opennoise.contract import validate_release
from opennoise.names import canonical, clean, release, write


def genre(id_, name, count, parent=None):
    return {"id": id_, "name": name, "aliases": [], "parent_id": parent, "member_count": count}


def test_canonical_expands_acronyms_and_spellings():
    assert canonical("Polish IDM") == "polish intelligent dance music"
    assert canonical("uk r&b") == "uk rhythm and blues"
    assert canonical("drum n bass") == "drum and bass"
    assert canonical("christian hip-hop") == "christian hip hop"
    assert canonical("forro") == "forró"


def test_canonical_resolves_overlap_without_changing_established_names():
    assert canonical("uk uk garage") == "uk garage"
    assert canonical("uk ukg revival") == "uk garage revival"
    assert canonical("rhythm and rhythm and blues") == "rhythm and blues"
    assert canonical("french french house") == "french house"
    assert canonical("cha cha") == "cha cha"
    assert canonical("deep deep house") == "deep deep house"
    assert canonical("neue neue deutsche welle") == "neue neue deutsche welle"


def test_canonical_restores_fragments_and_spellings():
    assert canonical("chicago b") == "chicago rhythm and blues"
    assert canonical("pinoy b") == "pinoy rhythm and blues"
    assert canonical("atlanta hop") == "atlanta hip hop"
    assert canonical("pinoy hop") == "pinoy hip hop"
    assert canonical("french roll") == "french rock and roll"
    assert canonical("french trip hop") == "french trip hop"
    assert canonical("street hop") == "street hop"
    assert canonical("black 'n' roll") == "black 'n' roll"
    assert canonical("australian s music") == "australian children's music"
    assert canonical("plugg b") == "pluggnb"
    assert canonical("provence alpes co te d azur hip hop") == "provence alpes côte d'azur hip hop"
    assert canonical("rif") == "rock indépendant français"


def test_clean_merges_duplicates_and_keeps_aliases():
    genres = [
        genre("a", "idm", 5),
        genre("b", "intelligent dance music", 9),
        genre("c", "pop music", 2),
        genre("d", "pop", 7),
        genre("e", "idm · Aphex Twin", 1, "a"),
    ]
    report = clean(genres, {"a": ["Autechre"], "c": ["Madonna"]})
    by = {g["id"]: g for g in genres}
    assert report == {"renamed": 3, "merged": 2}
    assert by["a"]["parent_id"] == "b" and by["a"]["name"] == "intelligent dance music · Autechre"
    assert by["e"]["parent_id"] == "b" and by["e"]["name"] == "intelligent dance music · Aphex Twin"
    assert by["c"]["name"] == "pop · Madonna"
    assert "idm" in by["b"]["aliases"] and "pop music" in by["d"]["aliases"]
    assert "idm · Aphex Twin" in by["e"]["aliases"]


def test_release_renames_without_merging_or_changing_memberships(tmp_path):
    root = tmp_path / "release"
    shutil.copytree(Path(__file__).parent / "fixtures" / "catalog", root)
    genres = json.loads((root / "genres.json").read_text())
    by_id = {g["id"]: g for g in genres}
    by_id["electronic"]["name"] = "uk garage"
    by_id["rock"]["name"] = "uk uk garage"
    old_rock = by_id["rock"].copy()
    write(root / "genres.json", genres)
    search = json.loads((root / "search.json").read_text())
    for entry in search:
        if entry["kind"] == "genre":
            entry["name"] = by_id[entry["id"]]["name"]
    write(root / "search.json", search)
    for id_ in ("rock", "electronic"):
        path = root / "genres" / f"{id_}.json"
        write(path, json.loads(path.read_text()) | {"genre": by_id[id_]})
    path = root / "genres" / "rock.json"
    detail = json.loads(path.read_text())
    untouched = (root / "genres" / "electronic.json").read_bytes()

    assert release(root, "repaired") == {"renamed": 1}
    repaired = {g["id"]: g for g in json.loads((root / "genres.json").read_text())}
    assert repaired.keys() == by_id.keys()
    assert repaired["electronic"]["name"] == repaired["rock"]["name"] == "uk garage"
    assert (root / "genres" / "electronic.json").read_bytes() == untouched
    assert repaired["rock"] == old_rock | {
        "name": "uk garage",
        "aliases": sorted(set(old_rock["aliases"]) | {"uk uk garage"}),
    }
    assert json.loads(path.read_text()) == detail | {"genre": repaired["rock"]}
    entry = next(e for e in json.loads((root / "search.json").read_text()) if e["id"] == "rock")
    assert entry["name"] == repaired["rock"]["name"]
    assert entry["aliases"] == repaired["rock"]["aliases"]
    assert validate_release(root)["release_id"] == "repaired"
