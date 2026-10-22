"""Verify the newly deployed public release through its dedicated commit-bound marker."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from opennoise.deployment.public_catalog_release import promotion
from opennoise.pipeline.catalog_demo import read
from opennoise.pipeline.public_catalog_candidate import MAX_BYTES, MAX_FILES

ATTEMPTS = 10


def fetch(url: str, maximum: int) -> bytes:
    """Bound normal post-deployment verification; never fetch the old release manifest."""
    with urlopen(url, timeout=10) as response:  # noqa: S310 -- Fixed approved production host.
        data = bytes(response.read(maximum + 1))
    if len(data) > maximum:
        raise ValueError("Live release member exceeds its bound")
    return data


def wait_for_marker(base: str, commit: str) -> dict[str, Any]:
    """Allow propagation delays while stopping immediately for access denials."""
    marker = None
    for attempt in range(ATTEMPTS):
        try:
            current = json.loads(fetch(base + "/opennoise-release.json", 200_000))
            if current["build_commit"] == commit:
                marker = current
                break
        except HTTPError as error:
            if error.code != HTTPStatus.NOT_FOUND:
                raise
        if (
            attempt < ATTEMPTS - 1
        ):  # Allow only propagation/old-commit delays; access denials stop immediately.
            time.sleep(5)
    if marker is None:
        raise ValueError("Production did not expose the expected merged commit")
    return marker


def verify_files(base: str, files: dict[str, Any]) -> None:
    """Check the complete bounded inventory; stop at a failed batch without retries."""
    if (
        not files
        or len(files) > MAX_FILES
        or sum(v["bytes"] for v in files.values()) > MAX_BYTES
        or any(v["bytes"] < 0 for v in files.values())
        or any(PurePosixPath(k).is_absolute() or ".." in PurePosixPath(k).parts for k in files)
    ):
        raise ValueError("Live release inventory exceeds its bounds")

    def verify(name: str) -> None:
        expected = files[name]
        raw = fetch(base + "/" + quote(name, safe="/"), expected["bytes"])
        if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            raise ValueError(f"Live served bytes differ: {name}")

    names = sorted(files)
    workers = 8
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(names), workers):
            list(pool.map(verify, names[start : start + workers]))


def main() -> None:
    """Require the merged SHA and every actual served file in the promoted inventory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    approval = promotion(Path.cwd())
    expected_marker = read(Path("dist/opennoise-release.json"))
    if expected_marker["build_commit"] != args.commit:
        raise ValueError("Local certified release differs from the merged commit")
    base = approval["site_url"]
    marker = wait_for_marker(base, args.commit)
    if (
        marker != expected_marker
        or marker["input_contract_sha256"] != approval["input_contract_sha256"]
        or marker["data_inventory_sha256"] != approval["data_inventory_sha256"]
        or marker["counts"] != approval["counts"]
        or marker["publication_authorized"] is not True
    ):
        raise ValueError("Live public scope differs from the promoted release")
    verify_files(base, marker["files"])
    print(  # noqa: T201 -- Verified public URL and commit, no credentials.
        json.dumps(
            {
                "url": base,
                "build_commit": args.commit,
                "status": "verified",
                "counts": marker["counts"],
            }
        )
    )


if __name__ == "__main__":
    main()
