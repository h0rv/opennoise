"""Launch one reviewed frozen recipe detached from tool pipes; no persistent Python monitor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    """Create exclusive sibling logs/proofs, then detach a tiny shell wrapper."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invocation", type=Path, required=True)
    parser.add_argument("--invocation-sha256", required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    raw = args.invocation.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.invocation_sha256:
        raise ValueError("reviewed invocation bytes changed")
    recipe = json.loads(raw)
    prefix = args.prefix
    output = Path(recipe["output_directory"])
    resolved_prefix, resolved_output = prefix.resolve(), output.resolve()
    if resolved_prefix.parent == resolved_output or resolved_output in resolved_prefix.parents:
        raise ValueError("launch logs/proofs must remain outside sealed source pack")
    stdout = prefix.with_name(prefix.name + "-stdout.log")
    stderr = prefix.with_name(prefix.name + "-stderr.log")
    wrapper = prefix.with_name(prefix.name + "-detached-wrapper.sh")
    requested = prefix.with_name(prefix.name + "-launch-requested.json")
    spawned = prefix.with_name(prefix.name + "-launch-spawned.json")
    spawned_temporary = prefix.with_name(prefix.name + "-launch-spawned-temporary.json")
    finished = prefix.with_name(prefix.name + "-launch-finished.json")
    finished_temporary = prefix.with_name(prefix.name + "-launch-finished-temporary.json")
    for artifact in [
        stdout,
        stderr,
        wrapper,
        requested,
        spawned,
        spawned_temporary,
        finished,
        finished_temporary,
    ]:
        if artifact.exists() or artifact.is_symlink():
            raise FileExistsError(f"earlier launch artifact exists: {artifact}")
    env = {**os.environ, **recipe["environment"]}
    command = shlex.join(recipe["argv"])
    # noclobber and exclusive Python opens preserve every earlier launch artifact.
    shell = (
        "#!/bin/bash\nset -u\nset -C\numask 077\n"
        "launch_wait=0\nwhile [ ! -f "
        + shlex.quote(str(spawned))
        + " ]; do\n"
        + '  if [ "$launch_wait" -ge 100 ]; then exit 125; fi\n'
        + "  sleep 0.05\n  launch_wait=$((launch_wait + 1))\ndone\n"
        + command
        + " </dev/null\n"
        + "capture_rc=$?\n"
        + 'printf \'{"returncode":%s,"finished_at":"%s"}\' "$capture_rc" '
        + '"$(date -u +%Y-%m-%dT%H:%M:%SZ)" > '
        + shlex.quote(str(finished_temporary))
        + "\n"
        + "sync -f "
        + shlex.quote(str(finished_temporary))
        + " || exit 125\n"
        + "ln "
        + shlex.quote(str(finished_temporary))
        + " "
        + shlex.quote(str(finished))
        + " || exit 125\n"
        + "sync -f "
        + shlex.quote(str(finished.parent))
        + " || exit 125\n"
        + 'exit "$capture_rc"\n'
    )
    with wrapper.open("x") as stream:
        stream.write(shell)
    proof = {
        "phase": "launch_requested",
        "requested_at": datetime.now(UTC).isoformat(),
        "capture_argv": recipe["argv"],
        "declared_environment": recipe["environment"],
        "invocation_sha256": args.invocation_sha256,
        "wrapper_sha256": hashlib.sha256(shell.encode()).hexdigest(),
        "stdout": str(stdout),
        "stderr": str(stderr),
        "start_new_session": True,
        "stdin": "DEVNULL",
        "pty": False,
    }
    with requested.open("x") as stream:
        json.dump(proof, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    with stdout.open("xb", buffering=0) as out, stderr.open("xb", buffering=0) as err:
        process = subprocess.Popen(  # noqa: S603 - exact reviewed command and fixed shell wrapper.
            ["/bin/bash", str(wrapper)],
            env=env,
            cwd=recipe["working_directory"],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )
    with spawned_temporary.open("x") as stream:
        json.dump(
            {
                "phase": "spawned",
                "pid": process.pid,
                "session_id": os.getsid(process.pid),
                "spawned_at": datetime.now(UTC).isoformat(),
                "wrapper_argv": ["/bin/bash", str(wrapper)],
            },
            stream,
            sort_keys=True,
        )
        stream.flush()
        os.fsync(stream.fileno())
    os.link(spawned_temporary, spawned)
    directory_fd = os.open(spawned.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print(json.dumps({"spawned_pid": process.pid, "stdout": str(stdout), "stderr": str(stderr)}))  # noqa: T201 - launch receipt only.


if __name__ == "__main__":
    main()
