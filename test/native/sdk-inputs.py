"""Refuse a native test SDK whose compiled-source inputs differ from this checkout."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

DIRECTORIES = ("native", "compat", "patches", "test/native", "build/packages/fedora")
FILES = (
    ".clangd",
    ".clang-tidy",
    "Dockerfile.fedora-44",
    "native/CMakeLists.txt",
    "test/native/CMakeLists.txt",
    "test/egl-fence-stub.cpp",
    "test/egl-fence-test.cpp",
    "build/install-packages",
    "build/create-user",
    "build/normalize-runtime",
    "build/collect-artifacts",
    "build/tigervnc-viewer",
    "build/websockify-requirements.txt",
)


def manifest(root):
    paths = {root / name for name in FILES}
    for name in DIRECTORIES:
        directory = root / name
        if not directory.is_dir():
            raise FileNotFoundError(f"Missing native SDK input directory: {name}")
        paths.update(
            path
            for path in directory.rglob("*")
            if path.is_file() and "__pycache__" not in path.relative_to(root).parts
        )
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def verify(root, expected):
    actual = manifest(root)
    if not isinstance(expected, dict) or actual != expected:
        raise ValueError(
            "Native SDK inputs differ from this checkout; rebuild the native-tests image"
        )


def main():
    root = Path.cwd()
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        verify(root, json.load(sys.stdin))
        os.execv(
            "/bin/bash",
            [
                "bash",
                str(root / "test/native/compiler-lint.sh"),
                "/results",
                *sys.argv[2:],
            ],
        )
    if len(sys.argv) < 3 or sys.argv[1].startswith("-"):
        raise SystemExit("usage: sdk-inputs.py IMAGE OUTPUT_DIRECTORY [CPP_FILES...]")
    image, output = sys.argv[1], Path(sys.argv[2]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    expected = manifest(root)
    payload = json.dumps(expected, indent=2) + "\n"
    (output / "native-sdk-inputs.json").write_text(payload)
    # Mount the checkout's verifier, so an old image cannot bypass a new check.
    command = [
        os.environ.get("RUNTIME", "docker"),
        "run",
        "--rm",
        "--network",
        "none",
        "-i",
        "--workdir",
        "/source",
        "--mount",
        f"type=bind,source={root / 'test/native/sdk-inputs.py'},target=/verify-native-sdk.py,readonly",
        "--mount",
        f"type=bind,source={output},target=/results",
        "--entrypoint",
        "/usr/bin/python3",
        image,
        "/verify-native-sdk.py",
        "--check",
        *sys.argv[3:],
    ]
    return subprocess.run(command, input=payload.encode(), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
