"""Adapt one certified public SQLite release into approved candidate input."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import signal
import sys
import tempfile
from pathlib import Path

MAX_OUTPUT_BYTES = 32_000_000


def _bound_process() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    signal.alarm(120)


def _pinned(path: Path, expected: str | None) -> None:
    if expected is None:
        return
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("adapter input does not match external SHA256 pin")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--database-sha256")
    parser.add_argument("--policy-sha256")
    parser.add_argument("--output", type=Path, help="Fresh directory, published atomically")
    parser.add_argument("--approved-input", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.output is not None:
        if args.approved_input is not None or args.receipt is not None:
            parser.error("--output cannot be combined with individual output paths")
        if args.database_sha256 is None or args.policy_sha256 is None:
            parser.error("--output requires external database and policy SHA256 pins")
        args.approved_input = args.output / "approved-input.json"
        args.receipt = args.output / "receipt.json"
    elif args.approved_input is None or args.receipt is None:
        parser.error("provide --output or both --approved-input and --receipt")
    inputs = {args.database.resolve(), args.policy.resolve()}
    outputs = {args.approved_input.resolve(), args.receipt.resolve()}
    if args.approved_input.resolve() == args.receipt.resolve() or inputs & outputs:
        parser.error("adapter inputs and outputs must be distinct")
    if args.output is not None and (args.output.exists() or args.output.is_symlink()):
        parser.error("adapter output directory must be fresh")
    if any(path.exists() or path.is_symlink() for path in (args.approved_input, args.receipt)):
        parser.error("adapter output files must be fresh")
    return args


def _publish(args: argparse.Namespace, approved: bytes, receipt: bytes) -> None:
    if len(approved) + len(receipt) > MAX_OUTPUT_BYTES:
        raise ValueError("adapter output exceeds 32MB combined bound")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".membership-export-", dir=args.output.parent))
        try:
            (stage / "approved-input.json").write_bytes(approved)
            (stage / "receipt.json").write_bytes(receipt)
            if args.output.exists() or args.output.is_symlink():
                raise ValueError("adapter output directory must remain fresh")
            stage.rename(args.output)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    else:
        # Historical individual-path spelling stays supported. Exclusive creation
        # prevents replacement; the receipt validates both files before consumption.
        published: list[Path] = []
        try:
            for path, payload in ((args.approved_input, approved), (args.receipt, receipt)):
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    published.append(path)
                    stream.write(payload)
        except BaseException:
            for path in published:
                path.unlink(missing_ok=True)
            raise


def main() -> int:
    """Adapt certified rows and write the approved input plus replay receipt."""
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    _bound_process()
    from opennoise.serving.public.artist_membership_adapter import (  # noqa: PLC0415 -- Bound heavy imports before loading the API.
        CertifiedPublicMembershipAdapterPolicy,
        adapt_certified_public_membership_input,
    )

    args = _arguments()
    _pinned(args.database, args.database_sha256)
    _pinned(args.policy, args.policy_sha256)
    policy_bytes = args.policy.read_bytes()
    if (
        args.policy_sha256 is not None
        and hashlib.sha256(policy_bytes).hexdigest() != args.policy_sha256
    ):
        raise ValueError("adapter policy changed after external pin verification")
    policy = CertifiedPublicMembershipAdapterPolicy.model_validate_json(policy_bytes)
    adaptation = adapt_certified_public_membership_input(args.database, policy)
    if (
        args.database_sha256 is not None
        and adaptation.receipt.database_file_sha256 != args.database_sha256
    ):
        raise ValueError("adapter database changed after external pin verification")
    _publish(
        args,
        (adaptation.approved_input.model_dump_json(indent=2) + "\n").encode(),
        (adaptation.receipt.model_dump_json(indent=2) + "\n").encode(),
    )
    sys.stdout.write(
        json.dumps(
            {
                "database_file_sha256": adaptation.receipt.database_file_sha256,
                "approved_input_sha256": adaptation.receipt.approved_input_sha256,
                "adapter_receipt_sha256": adaptation.receipt.output_sha256,
                "direct_row_count": adaptation.receipt.direct_row_count,
                "aggregate_pair_count": adaptation.receipt.aggregate_pair_count,
                "aggregate_emitted_pairs": adaptation.receipt.aggregate_emitted_pairs,
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
