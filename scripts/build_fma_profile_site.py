"""Build or verify a local permitted55 artist-recording discovery site."""

import argparse
import json
import os
import resource
import signal
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
signal.alarm(120)
from opennoise.deployment.fma_profile_site import (  # noqa: E402
    build_profile_site,
    validate_profile_site,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--candidate", type=Path, required=True)
    build.add_argument("--model", type=Path, required=True)
    build.add_argument("--discovery", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--site", type=Path, required=True)
    build.add_argument("--model-inventory-sha256", required=True)
    verify.add_argument("--model-inventory-sha256", required=True)
    build.add_argument("--discovery-inventory-sha256", required=True)
    verify.add_argument("--discovery-inventory-sha256", required=True)
    args = parser.parse_args()
    result = (
        build_profile_site(
            args.candidate,
            args.model,
            args.discovery,
            args.output,
            args.model_inventory_sha256,
            args.discovery_inventory_sha256,
        )
        if args.command == "build"
        else validate_profile_site(
            args.site, args.model_inventory_sha256, args.discovery_inventory_sha256
        )
    )
    print(json.dumps({"revision": result["revision"], "files": len(result["files"])}))  # noqa: T201
