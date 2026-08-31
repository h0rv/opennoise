"""Prepare bounded structural qualification queries for observed genre QIDs."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Literal

from musix.models import FrozenModel
from scripts.prepare_phase3_genre_enrichment import GenreTarget, load_targets

MUSIC_GENRE_ROOT_QID = "Q188451"
EXCLUDED_DIRECT_PARENT_QIDS = ("Q25379",)
EXCLUSION_PROFILE = ",".join(
    f"P279:{qid}" for qid in EXCLUDED_DIRECT_PARENT_QIDS
)
MAX_ANCESTRY_DEPTH = 1
QUALIFICATION_SHARD_SIZE = 100


class MusicGenreQualificationSelection(FrozenModel):
    """Freeze the exact subjects, root, depth, and contributing artifacts."""

    schema_version: Literal[1] = 1
    root_qids: tuple[str, ...] = (MUSIC_GENRE_ROOT_QID,)
    excluded_direct_parent_qids: tuple[str, ...] = EXCLUDED_DIRECT_PARENT_QIDS
    max_ancestry_depth: int = MAX_ANCESTRY_DEPTH
    input_artifacts: tuple[str, ...]
    targets: tuple[GenreTarget, ...]
    shard_size: int = QUALIFICATION_SHARD_SIZE


def render_qualification_query(targets: tuple[GenreTarget, ...]) -> str:
    """Render the canonical Wikidata music-genre P31 qualification."""
    qids = " ".join(f"wd:{target.qid}" for target in targets)
    excluded_parents = " ".join(
        f"wd:{qid}" for qid in EXCLUDED_DIRECT_PARENT_QIDS
    )
    branches = [
        f"""{{ ?entity wdt:P31 wd:{MUSIC_GENRE_ROOT_QID}.
      FILTER NOT EXISTS {{
        VALUES ?excludedParent {{ {excluded_parents} }}
        ?entity wdt:P279 ?excludedParent.
      }}
      BIND("{MUSIC_GENRE_ROOT_QID}|1|P31|{EXCLUSION_PROFILE}" AS ?musicGenreQualification)
    }}"""
    ]
    union = "\n    UNION\n    ".join(branches)
    return f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT DISTINCT ?entity ?entityKind ?musicGenreQualification
WHERE {{
  VALUES ?entity {{ {qids} }}
  BIND("genre" AS ?entityKind)
  {{
    {union}
  }}
}}
ORDER BY ?entity ?musicGenreQualification
LIMIT 20000
"""


def _write(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def prepare(database: Path, output: Path) -> dict[str, object]:
    """Write the frozen qualification manifest and exact query shards."""
    source = load_targets(database, "labels_only")
    selection = MusicGenreQualificationSelection(
        input_artifacts=source.input_artifacts,
        targets=source.targets,
    )
    manifest_sha256 = _write(
        output / "music-genre-qualification-selection.json",
        selection.model_dump_json(indent=2).encode(),
    )
    hashes: dict[str, str] = {}
    for offset in range(0, len(selection.targets), selection.shard_size):
        ordinal = offset // selection.shard_size
        path = output / f"music-genres-{ordinal:02d}.rq"
        query = render_qualification_query(
            selection.targets[offset : offset + selection.shard_size]
        )
        hashes[path.name] = _write(path, query.encode())
    return {
        "input_artifacts": len(selection.input_artifacts),
        "manifest_sha256": manifest_sha256,
        "max_ancestry_depth": selection.max_ancestry_depth,
        "excluded_direct_parent_qids": selection.excluded_direct_parent_qids,
        "query_files": len(hashes),
        "query_sha256": hashes,
        "root_qids": selection.root_qids,
        "targets": len(selection.targets),
    }


def main() -> int:
    """Generate bounded qualification artifacts from the exact catalog QIDs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.stdout.write(f"{json.dumps(prepare(args.database, args.output), indent=2)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
