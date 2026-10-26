"""Shared container setup, readiness and evidence collection for host tests."""

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments, timeout=180, **settings):
    return subprocess.run(
        arguments,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        **settings,
    )


def available_backends(runtime, image):
    result = run(
        runtime,
        "run",
        "--rm",
        "--entrypoint",
        "/usr/bin/test",
        image,
        "-x",
        "/usr/bin/kwin_x11",
    )
    return ("wayland", "x11") if result.returncode == 0 else ("wayland",)


def software_options(runtime):
    options = ["--tmpfs", "/dev/dri:mode=0755"]
    if runtime == "podman":
        # Privileged rootless Podman imports GPU devices after mounting tmpfs.
        options += [
            "--privileged=false",
            "--cap-add=all",
            "--security-opt=seccomp=unconfined",
        ]
        if Path("/dev/udmabuf").exists():
            options += ["--device", "/dev/udmabuf"]
    return options


def launch(runtime, image, name, backend, mode, *options, **settings):
    environment = {
        **os.environ,
        "RUNTIME": runtime,
        "IMAGE_TAG": image,
        "CONTAINER_NAME": name,
        "DISPLAY_BACKEND": backend,
        "DISPLAY_MODE": mode,
        "DISPLAY_WIDTH": "1024",
        "DISPLAY_HEIGHT": "768",
        "VNC_PASSWORD": "testpass",
        "VNC_MAX_FPS": "60",
        "VNC_PORT": "0",
        "WEB_PORT": "0",
        "BIND_ADDRESS": "127.0.0.1",
        "TARGET_APP": "",
        "PLASMA_UID": str(os.getuid()),
        "PLASMA_GID": str(os.getgid()),
        **settings,
    }
    environment.pop("VNC_PASSWORD_FILE", None)
    for setting in ("PLASMA_PASSWORD", "PLASMA_PASSWORD_FILE", "PLASMA_SUDO_NOPASSWD"):
        if setting not in settings:
            environment.pop(setting, None)
    return run(
        str(ROOT / "bin/plasma6-run"),
        "-d",
        "--rm=false",
        *(["--userns=host"] if runtime == "docker" and mode != "nested" else []),
        *options,
        env=environment,
    )


def wait_ready(runtime, name, timeout=120):
    deadline = time.monotonic() + timeout
    while True:
        check = run(runtime, "exec", name, "plasma-healthcheck")
        if check.returncode == 0:
            return
        state = run(runtime, "inspect", "--format", "{{.State.Running}}", name)
        if state.stdout.strip() != "true":
            logs = run(runtime, "logs", name)
            raise RuntimeError(
                "Container exited before desktop readiness: "
                + logs.stdout
                + logs.stderr
            )
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Desktop failed to become ready: " + check.stdout + check.stderr
            )
        time.sleep(1)


def renderer_command(name):
    return [
        "exec",
        "--user=plasma",
        name,
        "env",
        "XDG_RUNTIME_DIR=/run/plasma",
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/plasma/bus",
        "qdbus-qt6",
        "org.kde.KWin",
        "/KWin",
        "supportInformation",
    ]


def collect_artifacts(runtime, name, directory, services=(), extra=()):
    commands = [
        ("container.log", ["logs", name]),
        ("journal.log", ["exec", name, "journalctl", "-b", "--no-pager"]),
        ("processes.log", ["top", name]),
        ("session.env", ["exec", name, "cat", "/etc/plasma/session.env"]),
        ("renderer.log", renderer_command(name)),
        *[
            (
                f"{service}.log",
                [
                    "exec",
                    name,
                    "journalctl",
                    "-b",
                    "-u",
                    f"plasma-{service}",
                    "--no-pager",
                ],
            )
            for service in services
        ],
        *extra,
    ]
    try:
        for filename, arguments in commands:
            try:
                result = run(runtime, *arguments)
                output = result.stdout + result.stderr
            except (OSError, subprocess.TimeoutExpired) as error:
                output = str(error)
            (directory / filename).write_text(output)
    finally:
        run(runtime, "rm", "-f", name)
