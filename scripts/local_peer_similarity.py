"""Build and query a receipt-bound, non-exportable local peer index."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import ijson

_MAX_NEIGHBORS = 100


def build_index(
    *, artifact: Path, gate: Path, historical_receipt: Path, reconciliation: Path, output: Path
) -> None:
    """Stream canonical peer candidates into a local-only SQLite index."""
    gate_data = json.loads(gate.read_text(encoding="utf-8"))
    if not gate_data.get("passed"):
        raise ValueError("peer similarity gate did not pass")
    if gate_data.get("all_inputs_export_allowed") is not False:
        raise ValueError("local index requires the expected non-exportable research artifact")
    receipt_data = json.loads(historical_receipt.read_text(encoding="utf-8"))
    if receipt_data.get("candidate_output_sha256") != gate_data.get("artifact_output_sha256"):
        raise ValueError("historical receipt does not bind this peer similarity artifact")
    if receipt_data.get("historical_inputs_used_for_construction") is not False:
        raise ValueError("historical receipt reports construction input usage")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite local peer index: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(f"{output.suffix}.tmp")
    if temporary_output.exists():
        raise FileExistsError(
            f"refusing to overwrite incomplete local peer index: {temporary_output}"
        )
    with closing(sqlite3.connect(temporary_output)) as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
            CREATE TABLE seed (
              source_item_id TEXT PRIMARY KEY, source_external_id TEXT NOT NULL,
              seed_name TEXT NOT NULL, disposition TEXT NOT NULL
            ) STRICT;
            CREATE TABLE peer_edge (
              source_genre_id TEXT NOT NULL, target_genre_id TEXT NOT NULL,
              score REAL NOT NULL, direct_score REAL NOT NULL, aggregate_score REAL NOT NULL,
              shared_direct_artist_count INTEGER NOT NULL,
              aggregate_listener_day_support INTEGER NOT NULL,
              aggregate_supporting_windows INTEGER NOT NULL, sufficiency TEXT NOT NULL,
              evidence_ref_count INTEGER NOT NULL, component_kinds_json TEXT NOT NULL,
              PRIMARY KEY (source_genre_id, target_genre_id)
            ) STRICT;
            CREATE INDEX peer_edge_target
              ON peer_edge(target_genre_id, score DESC, source_genre_id);
            """
        )
        metadata = {
            "artifact_path": str(artifact),
            "gate_path": str(gate),
            "historical_receipt_path": str(historical_receipt),
            "artifact_output_sha256": gate_data["artifact_output_sha256"],
            "historical_receipt_candidate_output_sha256": receipt_data["candidate_output_sha256"],
            "gate_revision": gate_data["revision"],
            "non_production_candidate": "true",
            "all_inputs_export_allowed": "false",
        }
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
        seeds = json.loads(reconciliation.read_text(encoding="utf-8"))["dispositions"]
        connection.executemany(
            "INSERT INTO seed VALUES (?, ?, ?, ?)",
            (
                (
                    item["source_item_id"],
                    item["source_external_id"],
                    item["seed_name"],
                    item["disposition"],
                )
                for item in seeds
            ),
        )
        with artifact.open("rb") as stream:
            rows = (
                (
                    item["source_genre_id"],
                    item["target_genre_id"],
                    float(item["score"]),
                    float(item["direct_score"]),
                    float(item["aggregate_score"]),
                    item["shared_direct_artist_count"],
                    item["aggregate_listener_day_support"],
                    item["aggregate_supporting_windows"],
                    item["sufficiency"],
                    len(item["evidence_refs"]),
                    json.dumps(
                        sorted({component["component_kind"] for component in item["components"]}),
                        separators=(",", ":"),
                    ),
                )
                for item in ijson.items(stream, "candidates.item")
            )
            connection.executemany(
                "INSERT INTO peer_edge VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
        count = connection.execute("SELECT count(*) FROM peer_edge").fetchone()[0]
        if count != gate_data["candidate_pair_count"]:
            raise ValueError("streamed candidate count does not match gate")
        connection.commit()
    temporary_output.replace(output)


def neighbors(index: Path, seed: str, limit: int) -> dict[str, object]:
    """Return a local-research JSON neighborhood or an explicit abstention."""
    with closing(sqlite3.connect(f"file:{index}?mode=ro", uri=True)) as connection:
        row = connection.execute(
            "SELECT source_item_id, source_external_id, seed_name, disposition "
            "FROM seed WHERE source_item_id = ?",
            (seed,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown stable seed")
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        edges = connection.execute(
            """SELECT source_genre_id, target_genre_id, score, direct_score, aggregate_score,
                      shared_direct_artist_count, aggregate_listener_day_support,
                      aggregate_supporting_windows, sufficiency, evidence_ref_count,
                      component_kinds_json
                 FROM peer_edge WHERE source_genre_id = ? OR target_genre_id = ?
                 ORDER BY score DESC,
                   CASE WHEN source_genre_id = ? THEN target_genre_id ELSE source_genre_id END
                 LIMIT ?""",
            (seed, seed, seed, limit),
        ).fetchall()
    values = [
        {
            "target_seed_id": right if left == seed else left,
            "score": score,
            "direct_score": direct,
            "aggregate_score": aggregate,
            "method": "receipt_bound_peer_weighted_score",
            "shared_direct_artist_count": shared,
            "aggregate_listener_day_support": support,
            "aggregate_supporting_windows": windows,
            "sufficiency": sufficiency,
            "source_evidence_ref_count": evidence_ref_count,
            "component_kinds": json.loads(component_kinds),
        }
        for (
            left,
            right,
            score,
            direct,
            aggregate,
            shared,
            support,
            windows,
            sufficiency,
            evidence_ref_count,
            component_kinds,
        ) in edges
    ]
    return {
        "scope": "local_research_non_production",
        "non_production_candidate": True,
        "all_inputs_export_allowed": False,
        "artifact_output_sha256": metadata["artifact_output_sha256"],
        "seed": {
            "source_item_id": row[0],
            "source_external_id": row[1],
            "name": row[2],
            "disposition": row[3],
        },
        "neighbors": values,
        "abstained": not values,
    }


def main() -> None:
    """Run one explicit local index build or bounded JSON lookup."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--artifact", type=Path, required=True)
    build.add_argument("--gate", type=Path, required=True)
    build.add_argument("--historical-receipt", type=Path, required=True)
    build.add_argument("--reconciliation", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    query = commands.add_parser("neighbors")
    query.add_argument("--index", type=Path, required=True)
    query.add_argument("--seed", required=True)
    query.add_argument("--limit", type=int, default=25)
    arguments = parser.parse_args()
    if arguments.command == "build":
        build_index(
            artifact=arguments.artifact,
            gate=arguments.gate,
            historical_receipt=arguments.historical_receipt,
            reconciliation=arguments.reconciliation,
            output=arguments.output,
        )
    else:
        if not 1 <= arguments.limit <= _MAX_NEIGHBORS:
            raise ValueError(f"limit must be between 1 and {_MAX_NEIGHBORS}")
        sys.stdout.write(
            json.dumps(
                neighbors(arguments.index, arguments.seed, arguments.limit), ensure_ascii=False
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
