"""Resume fixed FMA stages without refitting completed stages or rewriting seals.

Relocation is verification-only: the underlying experiment seal retains its
original absolute paths. Checkpoint hashes are external trust anchors.
"""

import hashlib
import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ARMS = ("linear44", "rff44", "linear518", "rff518")
REVISION = "fma-offline-backend-v1"
MODEL_LIMIT = 100_000_000
BANK_LIMIT = 240_000_000
LOG_LIMIT = 1_000_000


def digest(path: Path) -> str:
    """Hash bytes without loading a feature matrix into memory."""
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inventory(root: Path) -> dict[str, Any]:
    """Bind every regular file, rejecting links and special entries."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Inventory root must be a real directory")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir() and not any(path.iterdir()):
            raise ValueError("Empty directories are not committed stage outputs")
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("Links and special files are not portable inputs")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {
                "sha256": digest(path),
                "bytes": path.stat().st_size,
            }
    return result


def write(path: Path, value: dict[str, Any]) -> str:
    """Write an exclusive bounded JSON receipt."""
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    if len(data) > LOG_LIMIT:
        raise ValueError("Pipeline receipt exceeds 1 MB")
    with path.open("xb") as stream:
        stream.write(data)
    return digest(path)


def stages() -> list[str]:
    """Keep all four fits before a fold's shared-candidate scoring."""
    result = ["project", "freeze"]
    for fold in range(5):
        for phase in ("fit", "score"):
            result.extend(f"{phase}-{fold}-{arm}" for arm in ARMS)
    return [*result, "summary"]


def code_inventory(repo: Path) -> dict[str, Any]:
    """Bind the executable Python tree and the two stage entry points."""
    result = {}
    for path in sorted((repo / "src").rglob("*.py")):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Executable source must be regular files")
        result[path.relative_to(repo).as_posix()] = {
            "sha256": digest(path),
            "bytes": path.stat().st_size,
        }
    for name in ("project_fma_native_bank.py", "run_fma_fixed_nonlinear.py", "run_fma_backend.py"):
        path = repo / "scripts" / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Stage entry points must be regular files")
        result[f"scripts/{name}"] = {"sha256": digest(path), "bytes": path.stat().st_size}
    return result


def validate_repo(repo: Path) -> None:
    """Reject shared editable environments resolving validators from another checkout."""
    expected = repo.resolve() / "src/opennoise"
    if Path(__file__).resolve() != expected / "pipeline/fma_backend.py":
        raise ValueError("Running pipeline module differs from selected repository")
    from opennoise.ingest import fma_native_bank  # noqa: PLC0415
    from opennoise.ml import fma_nonlinear_experiment  # noqa: PLC0415

    for module, relative in (
        (fma_native_bank, "ingest/fma_native_bank.py"),
        (fma_nonlinear_experiment, "ml/fma_nonlinear_experiment.py"),
    ):
        if Path(module.__file__).resolve() != expected / relative:
            raise ValueError("Running stage validator differs from selected repository")


def input_inventory(inputs: Path, roles: dict[str, str]) -> dict[str, Any]:
    """Bind only explicit role subtrees, never unrelated retained workspace data."""
    result = {}
    for role, relative in roles.items():
        path = inputs / relative
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError("Input role paths must not traverse symlinks")
        if path.is_dir():
            result[role] = {"kind": "directory", "files": inventory(path)}
        elif path.is_file():
            result[role] = {"kind": "file", "sha256": digest(path), "bytes": path.stat().st_size}
        else:
            raise ValueError("Missing input role")
    return result


def prepare(inputs: Path, repo: Path, output: Path, roles: dict[str, str]) -> str:
    """Seal explicit input roles before any new projection or model stage."""
    validate_repo(repo)
    required = {"source", "native", "declaration", "protocol"}
    if set(roles) not in (required, required | {"bank"}):
        raise ValueError("Exactly source, native, declaration and protocol roles are required")
    for relative in roles.values():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Input roles must remain within the input root")
    for role, relative in roles.items():
        target = inputs / relative
        if target.is_dir() and output.resolve().is_relative_to(target.resolve()):
            raise ValueError("Output must be outside every closed input role")
        if role in {"declaration", "protocol"} and not target.is_file():
            raise ValueError("Declaration and protocol must be regular files")
        if role not in {"declaration", "protocol"} and not target.is_dir():
            raise ValueError("Source and bank roles must be directories")
    bound = input_inventory(inputs, roles)
    plan = {
        "revision": REVISION,
        "inputs": bound,
        "roles": roles,
        "code": code_inventory(repo),
        "python": sys.version,
        "original_inputs": str(inputs.resolve()),
        "original_output": str(output.resolve()),
        "stages": stages(),
        "relocated_execution_supported": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    return write(output / "pipeline.json", plan)


def load(output: Path, plan_sha256: str, inputs: Path) -> dict[str, Any]:
    """Verify externally pinned plan and all retained input bytes after relocation."""
    if digest(output / "pipeline.json") != plan_sha256:
        raise ValueError("Pipeline plan hash differs")
    plan = json.loads((output / "pipeline.json").read_text())
    if plan["revision"] != REVISION or plan["stages"] != stages():
        raise ValueError("Unsupported pipeline")
    if input_inventory(inputs, plan["roles"]) != plan["inputs"]:
        raise ValueError("Retained inputs changed")
    return plan


def payload(output: Path) -> dict[str, Any]:
    """Inventory stage data; immutable numbered checkpoints are separate."""
    files = inventory(output)
    for prefix, limit in (("bank/", BANK_LIMIT), ("experiment/", MODEL_LIMIT)):
        total = sum(row["bytes"] for name, row in files.items() if name.startswith(prefix))
        if total > limit:
            raise ValueError(f"{prefix} exceeds its unchanged output guard")
    return files


def checkpoint(output: Path, completed: list[str]) -> str:
    """Commit completion only after a successful child and output validation."""
    return write(
        output / f"checkpoint-{len(completed):02d}.json",
        {
            "completed": completed,
            "files": payload(output),
        },
    )


def verify(
    output: Path, inputs: Path, plan_sha256: str, checkpoint_sha256: str | None = None
) -> dict[str, Any]:
    """Verify a closed portable snapshot; never rewrite original child seals."""
    load(output, plan_sha256, inputs)
    checkpoints = sorted(output.glob("checkpoint-*.json"))
    if not checkpoints:
        if set(inventory(output)) != {"pipeline.json"} or checkpoint_sha256 is not None:
            raise ValueError("Uncommitted or partial pipeline output")
        completed = []
    else:
        if checkpoint_sha256 is None or digest(checkpoints[-1]) != checkpoint_sha256:
            raise ValueError("Latest checkpoint requires its external SHA256")
        row = json.loads(checkpoints[-1].read_text())
        completed = row["completed"]
        if completed != stages()[: len(completed)] or not completed:
            raise ValueError("Nonsequential completed stages")
        expected = [f"checkpoint-{i:02d}.json" for i in range(1, len(completed) + 1)]
        current = payload(output)
        del current[checkpoints[-1].name]
        if [p.name for p in checkpoints] != expected or current != row["files"]:
            raise ValueError("Partial, extra, or changed pipeline output")
    return {
        "completed": completed,
        "ready": len(completed) == len(stages()),
        "next_stage": None if len(completed) == len(stages()) else stages()[len(completed)],
        "relocated_execution_supported": False,
    }


def command(
    stage: str, repo: Path, inputs: Path, output: Path, plan: dict[str, Any]
) -> tuple[list[str], int]:
    """Construct only fixed, reviewed script calls; never execute manifest commands."""
    roles = {key: inputs / value for key, value in plan["roles"].items()}
    if stage == "project":
        return [
            sys.executable,
            str(repo / "scripts/project_fma_native_bank.py"),
            "--source",
            str(roles["native"]),
            "--output",
            str(output / "bank"),
            "--declaration",
            str(roles["declaration"]),
            "--declaration-sha256",
            digest(roles["declaration"]),
        ], 360
    args = [sys.executable, str(repo / "scripts/run_fma_fixed_nonlinear.py")]
    if stage == "freeze":
        return [
            *args,
            "freeze",
            "--protocol",
            str(roles["protocol"]),
            "--source",
            str(roles["source"]),
            "--bank",
            str(roles.get("bank", output / "bank")),
            "--output",
            str(output / "model-seal.json"),
        ], 120
    phase = stage.split("-", 1)[0]
    args.extend(
        [phase, "--seal", str(output / "model-seal.json"), "--output", str(output / "experiment")]
    )
    if phase != "summary":
        _, fold, arm = stage.split("-", 2)
        args.extend(["--fold", fold, "--arm", arm])
    return args, 120


def run(  # noqa: PLR0913 - explicit pinned roots and bounded resume options
    output: Path,
    inputs: Path,
    repo: Path,
    plan_sha256: str,
    checkpoint_sha256: str | None = None,
    *,
    max_stages: int = 43,
) -> dict[str, Any]:
    """Run pending stages serially, stopping permanently at any partial failure."""
    validate_repo(repo)
    if not 1 <= max_stages <= len(stages()):
        raise ValueError("Stage count must be between 1 and 43")
    state = verify(output, inputs, plan_sha256, checkpoint_sha256)
    plan = load(output, plan_sha256, inputs)
    if (
        str(inputs.resolve()) != plan["original_inputs"]
        or str(output.resolve()) != plan["original_output"]
    ):
        raise ValueError("Relocated snapshots support verification, not execution resume")
    if code_inventory(repo) != plan["code"] or sys.version != plan["python"]:
        raise ValueError("Executable code or Python runtime changed")
    completed = state["completed"]
    environment = {
        **os.environ,
        "PYTHONPATH": str(repo / "src"),
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }
    for stage in stages()[len(completed) : len(completed) + max_stages]:
        args, timeout = command(stage, repo, inputs, output, plan)
        log = output / f"{stage}.log"
        started = time.monotonic()
        # Child CLIs enforce CPU/address limits before model work. The parent
        # adds a wall deadline and bounded log file; no retry or partial reuse.
        if stage == "project" and "bank" in plan["roles"]:
            from opennoise.ingest.fma_native_bank import verify_native_bank  # noqa: PLC0415

            bank = inputs / plan["roles"]["bank"]
            declaration = inputs / plan["roles"]["declaration"]
            native = inputs / plan["roles"]["native"]
            if digest(bank / "bank-declaration.json") != digest(declaration):
                raise ValueError("Retained bank does not match the selected declaration")
            declared = json.loads(declaration.read_text())
            if declared["source_receipt_sha256"] != digest(native / "source-receipt.json"):
                raise ValueError("Retained bank does not match the selected native source")
            verify_native_bank(bank)
            with log.open("x") as stream:
                stream.write("Verified explicit retained bank; no projection rerun.\n")
            returncode = 0
        else:
            returncode = execute(args, repo, environment, log, timeout)
        if returncode != 0:
            raise ValueError(f"Stage {stage} failed; preserve this partial output")
        if stage != "project" or "bank" not in plan["roles"]:
            validate_stage(stage, output)
        write(
            output / f"{stage}.execution.json",
            {
                "stage": stage,
                "elapsed_seconds": time.monotonic() - started,
                "success": True,
                "wall_limit_seconds": timeout,
            },
        )
        completed.append(stage)
        checkpoint_sha256 = checkpoint(output, completed)
    return {
        "completed": completed,
        "checkpoint_sha256": checkpoint_sha256,
        "ready": len(completed) == len(stages()),
    }


# Fixed command construction is private to this module; no manifest command strings.
def execute(
    args: list[str], repo: Path, environment: dict[str, str], log: Path, timeout: int
) -> int:
    """Drain bounded child output with a wall deadline; kill on overflow."""
    deadline = time.monotonic() + timeout
    with (
        log.open("xb") as stream,
        subprocess.Popen(  # noqa: S603
            args,
            cwd=repo,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ) as child,
    ):
        try:
            if child.stdout is None:
                raise ValueError("Missing child output pipe")  # noqa: TRY301
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                total = 0
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Stage wall deadline exceeded")  # noqa: TRY301
                    for key, _ in selector.select(min(remaining, 1)):
                        block = os.read(key.fd, 65536)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(block)
                        if total > LOG_LIMIT:
                            raise ValueError("Stage log exceeds 1 MB")  # noqa: TRY301
                        stream.write(block)
                return child.wait(timeout=max(0.001, deadline - time.monotonic()))
        except BaseException:
            child.kill()
            child.wait()
            raise


def validate_stage(stage: str, output: Path) -> None:
    """Use each producer's closed receipt validator before recording completion."""
    from opennoise.ingest.fma_native_bank import verify_native_bank  # noqa: PLC0415
    from opennoise.ml.fma_nonlinear_experiment import verify_seal, verify_stage  # noqa: PLC0415

    if stage == "project":
        verify_native_bank(output / "bank")
    elif stage == "freeze":
        verify_seal(output / "model-seal.json")
    elif stage == "summary":
        folder = output / "experiment/summary"
        receipt = json.loads((folder / "receipt.json").read_text())
        if set(inventory(folder)) != {"results.json", "receipt.json"}:
            raise ValueError("Summary inventory differs")
        if receipt["seal_sha256"] != digest(output / "model-seal.json"):
            raise ValueError("Summary seal differs")
        if receipt["files"] != {"results.json": inventory(folder)["results.json"]}:
            raise ValueError("Summary result hash differs")
    else:
        phase, fold, arm = stage.split("-", 2)
        verify_stage(output / "experiment", output / "model-seal.json", int(fold), arm, phase)
