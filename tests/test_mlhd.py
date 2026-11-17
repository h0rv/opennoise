import io
import shutil
import subprocess

import numpy as np
import pytest
from scipy import sparse

from opennoise import mlhd, mlhd_downstream
from opennoise.graph import normalize
from opennoise.mlhd import MEMBER_COMMAND, aggregate, partition_users, similarities, weighted_rows


def test_mlhd_is_disabled_by_default(tmp_path, monkeypatch, capsys):
    run = tmp_path / "disabled"
    monkeypatch.setattr("sys.argv", ["mlhd", "ingest", "--run", str(run)])
    with pytest.raises(SystemExit) as error:
        mlhd.main()
    assert error.value.code == 2
    assert "disabled by default" in capsys.readouterr().err
    assert not run.exists()


@pytest.mark.parametrize("complete", [False, True])
def test_mlhd_explicit_opt_in(tmp_path, monkeypatch, complete):
    calls = []
    args = ["mlhd", "ingest", "--enable", "--run", str(tmp_path)]
    monkeypatch.setattr("sys.argv", args + (["--complete"] if complete else []))
    monkeypatch.setattr(mlhd, "ingest", lambda *args: calls.append(args))
    mlhd.main()
    assert len(calls) == 1
    assert calls[0][1:] == (tmp_path, "0", complete)


def test_downstream_requires_opt_in(monkeypatch):
    monkeypatch.setattr("sys.argv", ["mlhd_downstream", "baseline"])
    with pytest.raises(SystemExit) as error:
        mlhd_downstream.main()
    assert error.value.code == 2


@pytest.mark.parametrize(
    ("winner", "expected"), [("0", [0.01]), ("0.1", [0.01]), ("1", []), ("3", [30])]
)
def test_weight_extension_uses_validation_only(winner, expected):
    metrics = {key: {"ndcg@50": float(key == winner)} for key in ["0", "0.1", "0.3", "1", "3"]}
    assert mlhd.boundary_weights(metrics, [0.1, 0.3, 1, 3]) == expected


def test_aggregate():
    stream = io.BytesIO(
        b"@mlhd-user\t00/one.txt.zst\n1\ta\t\t\n2\ta\tr\ts\n3\tb\t\t\n4\tx\t\t\n"
        b"\n@mlhd-user\t00/two.txt.zst\n5\tb\t\t\n"
        b"@mlhd-user\t00/empty.txt.zst\n6\tx\t\t\n"
    )
    matrix, users, stats = aggregate(stream, {b"a": 0, b"b": 1})
    np.testing.assert_array_equal(matrix.toarray(), [[2, 1], [0, 1]])
    assert users == ["one", "two"]
    assert stats == {
        "users_processed": 3,
        "users_retained": 2,
        "listens_processed": 6,
        "matched_listens": 4,
        "multi_artist_listens": 0,
        "interactions": 3,
    }


def test_aggregate_multiple_artist_credits():
    stream = io.BytesIO(
        b"@mlhd-user\tone.txt.zst\n1\ta,b\t\t\n2\tB,a,a,x\t\t\n3\tx, y\t\t\n"
        b"4\ta\t\t\n5\t\t\t\n6\tb, x\t\t\n@mlhd-user\tempty.txt.zst\n7\tx,y\t\t\n"
    )
    matrix, users, stats = aggregate(stream, {b"a": 0, b"b": 1})
    np.testing.assert_array_equal(matrix.toarray(), [[3, 3]])
    assert users == ["one"]
    assert stats == {
        "users_processed": 2,
        "users_retained": 1,
        "listens_processed": 7,
        "matched_listens": 4,
        "multi_artist_listens": 5,
        "interactions": 2,
    }


def test_empty_aggregate():
    matrix, users, stats = aggregate(io.BytesIO(), {b"a": 0})
    assert matrix.shape == (0, 1)
    assert users == []
    assert stats["listens_processed"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        b"1\ta\t\t\n",
        b"@mlhd-user\tu.txt.zst\ninvalid\n",
        b"@mlhd-user\tu.txt.zst\n@mlhd-user\tu.txt.zst\n",
    ],
)
def test_rejects_invalid_aggregate(payload):
    with pytest.raises(ValueError):
        aggregate(io.BytesIO(payload), {b"a": 0})


@pytest.mark.skipif(shutil.which("zstd") is None, reason="MLHD ingestion requires the zstd CLI")
def test_tar_member_command(tmp_path):
    payload = b"123\ta\t\t\n"
    compressed = subprocess.run(
        ["zstd", "-c"], input=payload, capture_output=True, check=True
    ).stdout
    (tmp_path / "user.txt.zst").write_bytes(compressed)
    archive = subprocess.run(
        ["tar", "-cf", "-", "user.txt.zst"], cwd=tmp_path, capture_output=True, check=True
    ).stdout
    result = subprocess.run(
        ["tar", "-xf", "-", "--to-command", MEMBER_COMMAND],
        input=archive,
        capture_output=True,
        check=True,
    )
    matrix, users, _ = aggregate(io.BytesIO(result.stdout), {b"a": 0})
    assert users == ["user"]
    assert matrix[0, 0] == 1
    (tmp_path / "user.txt.zst").write_bytes(b"not zstd")
    archive = subprocess.run(
        ["tar", "-cf", "-", "user.txt.zst"], cwd=tmp_path, capture_output=True, check=True
    ).stdout
    failed = subprocess.run(
        ["tar", "-xf", "-", "--to-command", MEMBER_COMMAND], input=archive, capture_output=True
    )
    assert failed.returncode != 0


def test_weighted_similarity_matches_extra_user_rows():
    lb = sparse.csr_matrix(np.array([[1, 2, 0, 1], [0, 1, 4, 0]], dtype=np.float32))
    mlhd = sparse.csr_matrix(np.array([[0, 3, 1, 2], [2, 0, 0, 5]], dtype=np.float32))
    outputs = similarities(lb, mlhd, [0, 0.3, 3], 3)
    for weight, (ids, scores) in outputs.items():
        rows = sparse.vstack([weighted_rows(lb), np.sqrt(weight) * weighted_rows(mlhd)])
        vectors = normalize(rows.T.tocsr())
        expected = (vectors @ vectors.T).toarray()
        np.fill_diagonal(expected, -np.inf)
        for item in range(4):
            assert item not in ids[item]
            np.testing.assert_allclose(scores[item], expected[item, ids[item]], atol=1e-6)
            np.testing.assert_allclose(scores[item], np.sort(expected[item])[-3:][::-1], atol=1e-6)
    empty = sparse.csr_matrix((0, 4), dtype=np.float32)
    ids, scores = similarities(lb, empty, [1], 3)[1]
    np.testing.assert_allclose(scores, outputs[0][1], atol=1e-6)


@pytest.mark.parametrize("weight", [-1, np.nan, np.inf])
def test_rejects_invalid_weight(weight):
    matrix = sparse.eye(3, format="csr", dtype=np.float32)
    with pytest.raises(ValueError, match="weights"):
        similarities(matrix, matrix, [weight], 1)


def test_partition_is_disjoint_and_repeatable():
    validation, test = partition_users(9, 42)
    assert len(validation) == 4
    assert len(test) == 5
    assert set(validation).isdisjoint(test)
    assert set(validation) | set(test) == set(range(9))
    np.testing.assert_array_equal(validation, partition_users(9, 42)[0])
    with pytest.raises(ValueError):
        partition_users(1, 42)
