import io
import json
import shutil
import tarfile
from pathlib import Path

import polars as pl
import pytest

from opennoise.artist_identity import (
    canonicalize,
    cleanup_redirects,
    collaboration_table,
    extract_dump,
    identity_table,
    popularity_redirects,
    release,
)
from opennoise.contract import validate_release

FIXTURE = Path(__file__).parent / "fixtures/catalog"


def mbid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def tables(root, target="1"):
    (root / "mbdump").mkdir()
    rows = []
    for n, comment in [(1, "Canonical comment"), (3, "\\N")]:
        row = [str(n), mbid(n), f"Artist {n}", *["\\N"] * 10, comment]
        rows.append("\t".join(row))
    (root / "mbdump/artist").write_text("\n".join(rows) + "\n")
    (root / "mbdump/artist_gid_redirect").write_text(f"{mbid(2)}\t{target}\t2026-11-18\n")


def test_identity_table_and_listening_boundary(tmp_path):
    tables(tmp_path)
    identities = identity_table(tmp_path)
    assert identities.filter(pl.col("artist_mbid") == mbid(2))["canonical_mbid"].item() == mbid(1)
    assert identities.filter(pl.col("artist_mbid") == mbid(3))["disambiguation"].item() is None
    assert identity_table(tmp_path).equals(identities)
    data = pl.DataFrame(
        {
            "user": ["u"] * 4,
            "artist_mbid": [mbid(1), mbid(2), mbid(3), mbid(4)],
            "artist_name": ["Old"] * 4,
            "count": [2, 3, 4, 5],
        }
    )
    result = (
        canonicalize(data.lazy(), identities)
        .group_by("user", "artist_mbid")
        .agg(pl.col("count").sum(), pl.col("artist_name").first(), pl.col("disambiguation").first())
        .collect()
        .sort("artist_mbid")
    )
    assert result["artist_mbid"].to_list() == [mbid(1), mbid(3), mbid(4)]
    assert result["count"].to_list() == [5, 4, 5]
    assert result["artist_name"].to_list() == ["Artist 1", "Artist 3", "Old"]
    assert result["disambiguation"].to_list() == ["Canonical comment", None, None]
    assert canonicalize(data.head(0), identities).is_empty()


def test_unknown_redirect_target(tmp_path):
    tables(tmp_path, target="99")
    with pytest.raises(ValueError, match="Unknown MusicBrainz redirect target"):
        identity_table(tmp_path)
    assert not (tmp_path / "identities.parquet").exists()


def test_popularity_rule_normalizes_names_and_keeps_exact_threshold():
    artists = {
        mbid(1): {"name": " The  Beatles ", "listeners": 100},
        mbid(2): {"name": "ＴＨＥ beatles", "listeners": 9},
        mbid(3): {"name": "the\tbeatles", "listeners": 10},
        mbid(4): {"name": "Other", "listeners": None},
        mbid(5): {"name": "OTHER", "listeners": 0},
    }
    assert popularity_redirects(artists) == {mbid(2): mbid(1)}
    assert popularity_redirects({}) == {}


@pytest.mark.parametrize("listeners", [10, 11])
def test_boundary_popularity_uses_unique_listeners_after_redirect_folding(listeners):
    identities = pl.DataFrame(
        {
            "artist_mbid": [mbid(1), mbid(2), mbid(3)],
            "canonical_mbid": [mbid(1), mbid(1), mbid(3)],
            "canonical_name": ["Same"] * 3,
            "disambiguation": ["Main", "Main", "Other"],
        }
    )
    data = pl.DataFrame(
        {
            "user": list(range(listeners)) * 2 + [100],
            "artist_mbid": [mbid(1)] * listeners + [mbid(2)] * listeners + [mbid(3)],
            "artist_name": ["Same"] * (listeners * 2 + 1),
            "count": [1] * (listeners * 2 + 1),
        }
    )
    result = canonicalize(data, identities)
    assert set(result["artist_mbid"]) == ({mbid(1), mbid(3)} if listeners == 10 else {mbid(1)})
    assert result["count"].sum() == listeners * 2 + 1
    redirects = {
        source: target
        for source, target in result.select("source_mbid", "artist_mbid").iter_rows()
        if source != target
    }
    assert redirects == (
        {mbid(2): mbid(1)} if listeners == 10 else {mbid(2): mbid(1), mbid(3): mbid(1)}
    )
    if listeners == 11:
        assert result["disambiguation"].unique().to_list() == ["Main"]


def test_transform_popularity_repoints_members_neighbors_and_prior_redirects(tmp_path):
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    path = tmp_path / "artists" / f"{mbid(3)}.json"
    artist = json.loads(path.read_text())
    artist["artist"].update(name=" ＦＩＸＴＵＲＥ  artist 1 ", listeners=1)
    path.write_text(json.dumps(artist))
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["artist_redirects"] = {mbid(8): mbid(3)}
    path.write_text(json.dumps(manifest))
    identities = pl.DataFrame(
        schema={"artist_mbid": pl.String, "canonical_mbid": pl.String, "disambiguation": pl.String}
    )
    counts = release(tmp_path, "cleaned", identities)
    assert counts["popularity_dropped"] == 1
    assert counts["artists_after"] == 5
    manifest = validate_release(tmp_path)
    assert manifest["artist_redirects"] == {mbid(3): mbid(1), mbid(8): mbid(1)}
    assert not (tmp_path / "artists" / f"{mbid(3)}.json").exists()


def test_extract_dump(tmp_path, monkeypatch):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:bz2") as output:
        for name in ["artist", "artist_gid_redirect", "unused"]:
            member = tarfile.TarInfo(f"mbdump/{name}")
            member.size = 1
            output.addfile(member, io.BytesIO(b"x"))
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: io.BytesIO(archive.getvalue()))
    extract_dump(tmp_path, "https://example.com", {"artist", "artist_gid_redirect"})
    assert (tmp_path / "mbdump/artist").read_text() == "x"
    assert not (tmp_path / "mbdump/unused").exists()
    with pytest.raises(ValueError, match="MusicBrainz tables missing"):
        extract_dump(tmp_path, "https://example.com", {"absent"})


@pytest.mark.parametrize("rule", ["popularity", "collaboration"])
def test_transform_drops_folded_genres_but_keeps_other_references(tmp_path, rule):
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)

    def read(path):
        return json.loads((tmp_path / path).read_text())

    before = read(f"artists/{mbid(1)}.json")["genres"]
    path = tmp_path / "artists" / f"{mbid(3)}.json"
    donor = read(f"artists/{mbid(3)}.json")
    if rule == "popularity":
        donor["artist"].update(name="Fixture Artist 1", listeners=1)
        path.write_text(json.dumps(donor))
    identities = pl.DataFrame(
        {
            "artist_mbid": [mbid(2)],
            "canonical_mbid": [mbid(3)],
            "disambiguation": [None],
        },
        schema_overrides={"disambiguation": pl.String},
    )
    collaborations = (
        pl.DataFrame({"collaboration": [mbid(3)], "member": [mbid(1)]})
        if rule == "collaboration"
        else None
    )
    release(tmp_path, "cleaned", identities, collaborations)
    manifest = validate_release(tmp_path)
    assert manifest["artist_redirects"] == {mbid(2): mbid(1), mbid(3): mbid(1)}
    assert read(f"artists/{mbid(1)}.json")["genres"] == before
    for genre in ["house", "rock", "shoegaze"]:
        assert all(
            row["artist"]["id"] != mbid(1) for row in read(f"genres/{genre}.json")["members"]
        )
    assert read(f"artists/{mbid(4)}.json")["similar"][0]["artist"]["id"] == mbid(1)
    search = {e["id"]: e for e in read("search.json") if e["kind"] == "artist"}
    assert set(search[mbid(1)]["aliases"]) == {"Fixture Artist 2", "Fixture Artist 3"}


def test_transform_repoints_every_reference_and_preserves_ids(tmp_path):
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)

    def read(path):
        return json.loads((tmp_path / path).read_text())

    before = read("artists/" + mbid(1) + ".json")["artist"]
    genres = {g["id"] for g in read("genres.json")}
    identities = pl.DataFrame(
        {
            "artist_mbid": [mbid(1), mbid(2), mbid(3)],
            "canonical_mbid": [mbid(1), mbid(1), mbid(7)],
            "disambiguation": ["Comment", "Comment", None],
        }
    )
    counts = release(tmp_path, "canonical", identities)
    assert counts == {
        "artists_before": 6,
        "artists_after": 5,
        "redirects": 2,
        "genres": len(genres),
        "popularity_dropped": 0,
        "collaboration_folded": 0,
    }
    manifest = validate_release(tmp_path)
    assert manifest["artist_redirects"] == {mbid(2): mbid(1), mbid(3): mbid(7)}
    assert {g["id"] for g in read("genres.json")} == genres
    assert read("artists/" + mbid(1) + ".json")["artist"] == {**before, "disambiguation": "Comment"}
    assert read("artists/" + mbid(1) + ".json")["genres"] == [
        {"id": "house", "score": 0.95},
        {"id": "techno", "score": 0.95},
        {"id": "electronic", "score": 0.9},
    ]
    assert {p.stem for p in (tmp_path / "artists").glob("*.json")} == {
        mbid(i) for i in [1, 4, 5, 6, 7]
    }
    search = {e["id"]: e for e in read("search.json") if e["kind"] == "artist"}
    assert search[mbid(1)]["listeners"] == before["listeners"]
    assert search[mbid(1)]["disambiguation"] == "Comment"
    assert all("disambiguation" in e for e in search.values())
    assert "Fixture Artist 2" in search[mbid(1)]["aliases"]
    assert release(tmp_path, "again", identities)["artists_after"] == 5
    validate_release(tmp_path)


def test_empty_transform(tmp_path):
    (tmp_path / "artists").mkdir()
    (tmp_path / "genres").mkdir()
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    for name in ["genres.json", "search.json"]:
        (tmp_path / name).write_text("[]")
    identities = pl.DataFrame(
        schema={"artist_mbid": pl.String, "canonical_mbid": pl.String, "disambiguation": pl.String}
    )
    assert release(tmp_path, "empty", identities)["artists_after"] == 0
    validate_release(tmp_path)


def test_collaboration_table_uses_only_directed_collaboration_relationships(tmp_path):
    tables(tmp_path)
    (tmp_path / "mbdump/link_type").write_text(
        "7\t0\t0\tguid\tartist\tartist\tcollaboration\n"
        "8\t0\t0\tguid\tartist\tartist\tmember of band\n"
    )
    (tmp_path / "mbdump/link").write_text("10\t7\n11\t8\n")
    (tmp_path / "mbdump/l_artist_artist").write_text("1\t10\t1\t3\n2\t11\t3\t1\n")
    result = collaboration_table(tmp_path)
    assert result.to_dicts() == [{"collaboration": mbid(3), "member": mbid(1)}]
    assert collaboration_table(tmp_path).equals(result)


def test_collaborations_choose_most_listened_present_member_and_resolve_chains():
    artists = {
        mbid(i): {"name": str(i), "listeners": n} for i, n in [(1, 100), (2, 20), (3, 5), (4, 1)]
    }
    collaborations = pl.DataFrame(
        {
            "collaboration": [mbid(3), mbid(3), mbid(3), mbid(4)],
            "member": [mbid(1), mbid(2), mbid(99), mbid(3)],
        }
    )
    assert cleanup_redirects(artists, collaborations) == (
        {mbid(3): mbid(1), mbid(4): mbid(1)},
        0,
        2,
    )
    assert cleanup_redirects({}, collaborations) == ({}, 0, 0)
    assert cleanup_redirects({mbid(3): artists[mbid(3)]}, collaborations) == ({}, 0, 0)
    cycle = pl.DataFrame({"collaboration": [mbid(1), mbid(2)], "member": [mbid(2), mbid(1)]})
    with pytest.raises(ValueError, match="Cyclic MusicBrainz collaboration"):
        cleanup_redirects(artists, cycle)


def test_boundary_and_transform_share_collaboration_fold(tmp_path):
    tables(tmp_path)
    identities = identity_table(tmp_path)
    collaborations = pl.DataFrame({"collaboration": [mbid(3)], "member": [mbid(1)]})
    data = pl.DataFrame(
        {
            "user": [1, 2, 3],
            "artist_mbid": [mbid(1), mbid(2), mbid(3)],
            "artist_name": ["A", "Old A", "A + B"],
            "count": [1, 2, 3],
        }
    )
    result = canonicalize(data, identities, collaborations)
    assert set(result["artist_mbid"]) == {mbid(1)}
    assert set(result["artist_name"]) == {"Artist 1"}
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    counts = release(tmp_path, "collaboration", identities, collaborations)
    assert counts["collaboration_folded"] == 1
    manifest = validate_release(tmp_path)
    assert manifest["artist_redirects"] == {mbid(2): mbid(1), mbid(3): mbid(1)}


@pytest.mark.parametrize(
    "redirects", [{mbid(1): mbid(2)}, {mbid(7): mbid(8)}, {"invalid": mbid(1)}]
)
def test_contract_rejects_invalid_redirects(tmp_path, redirects):
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["artist_redirects"] = redirects
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        validate_release(tmp_path)
