"""Fail before a release task can mix public and local-research catalogs."""

import argparse
from pathlib import Path


def main() -> int:
    """Require the release database path to be absent."""
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    database = parser.parse_args().database
    if database.exists():
        raise FileExistsError(f"public release database already exists: {database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
