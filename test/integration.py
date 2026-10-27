#!/usr/bin/env python3
"""Exercise the host launcher with Docker or Podman and retain per-case evidence."""

import argparse
import os
import subprocess
import time
from pathlib import Path

from support import available_backends, collect_artifacts, renderer_command, wait_ready
from support import run as command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=os.environ.get("IMAGE_TAG", "plasma6:local"))
    parser.add_argument("--runtime", default=os.environ.get("RUNTIME", "docker"))
    parser.add_argument("--skip-nested", action="store_true")
    parser.add_argument("--backends", nargs="+", choices=("wayland", "x11"))
    parser.add_argument(
        "--capture",
        action="store_true",
        help="Use uv to authenticate VNC/WebSocket sessions and save screenshots",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("headless", "vnc", "web", "nested"),
        default=("headless", "vnc", "web", "nested"),
    )
    parser.add_argument(
        "--host-backend", choices=("auto", "wayland", "x11"), default="auto"
    )
    parser.add_argument(
        "--userns",
        help="Override the launcher's namespace for mapping regression checks",
    )
    parser.add_argument("--gpus", help="Pass a Docker GPU request, for example all")
    parser.add_argument("--expect-renderer", choices=("gpu", "software"))
    options = parser.parse_args()
    runtime = options.runtime
    if options.gpus and Path(runtime).name != "docker":
        parser.error("--gpus requires Docker")
    artifacts = (
        Path(__file__).resolve().parent
        / ".artifacts"
        / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    )
    artifacts.mkdir(parents=True)
    failed = []
    backends = options.backends
    if backends is None:
        backends = available_backends(runtime, options.image)
    for backend in backends:
        for mode in options.modes:
            if mode == "nested" and options.skip_nested:
                continue
            label = f"{backend}-{mode}"
            name = f"plasma6-test-{os.getpid()}-{label}"
            case = artifacts / label
            case.mkdir()
            environment = {
                **os.environ,
                "RUNTIME": runtime,
                "IMAGE_TAG": options.image,
                "CONTAINER_NAME": name,
                "DISPLAY_BACKEND": backend,
                "DISPLAY_MODE": mode,
                "DISPLAY_WIDTH": "1024",
                "DISPLAY_HEIGHT": "768",
                "VNC_PASSWORD": "testpass",
                "HOST_DISPLAY_BACKEND": options.host_backend,
                "VNC_PORT": "0",
                "WEB_PORT": "0",
            }
            environment.pop("VNC_PASSWORD_FILE", None)
            launcher = Path(__file__).resolve().parents[1] / "bin/plasma6-run"
            try:
                run_options = ["-d", "--rm=false"]
                if options.userns:
                    run_options.append(f"--userns={options.userns}")
                if options.gpus:
                    run_options += ["--gpus", options.gpus]
                result = command(str(launcher), *run_options, env=environment)
                (case / "run.log").write_text(result.stdout + result.stderr)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                wait_ready(runtime, name)
                if options.expect_renderer:
                    renderer = command(runtime, *renderer_command(name))
                    assert renderer.returncode == 0, renderer.stderr
                    rendering = "\n".join(
                        line.lower()
                        for line in renderer.stdout.splitlines()
                        if line.startswith(
                            ("Compositing Type:", "OpenGL renderer string:")
                        )
                    )
                    software = any(
                        name in rendering
                        for name in (
                            "qpainter",
                            "llvmpipe",
                            "softpipe",
                            "swrast",
                            "swiftshader",
                        )
                    )
                    assert software == (options.expect_renderer == "software"), (
                        rendering
                    )
                    if options.expect_renderer == "gpu":
                        assert "opengl renderer string:" in rendering, rendering
                masked = command(
                    runtime,
                    "exec",
                    name,
                    "systemctl",
                    "is-enabled",
                    "NetworkManager.service",
                )
                assert masked.stdout.strip() == "masked", masked.stdout + masked.stderr
                active = command(
                    runtime,
                    "exec",
                    name,
                    "systemctl",
                    "is-active",
                    "NetworkManager.service",
                )
                assert active.stdout.strip() == "inactive", (
                    active.stdout + active.stderr
                )
                start = command(
                    runtime,
                    "exec",
                    name,
                    "systemctl",
                    "start",
                    "NetworkManager.service",
                )
                (case / "networkmanager.log").write_text(
                    masked.stdout + active.stdout + start.stdout + start.stderr
                )
                assert start.returncode != 0 and "masked" in start.stderr, start.stderr
                # Assert both the selected default target and absence of remote listeners in local modes.
                target = command(
                    runtime,
                    "exec",
                    name,
                    "readlink",
                    "-f",
                    "/etc/systemd/system/default.target",
                )
                assert target.stdout.strip().endswith(f"/plasma-{label}.target"), (
                    target.stdout
                )
                if mode == "nested":
                    for flag, expected in (
                        ("-u", environment.get("PLASMA_UID", str(os.getuid()))),
                        ("-g", environment.get("PLASMA_GID", str(os.getgid()))),
                    ):
                        identity = command(runtime, "exec", name, "id", flag, "plasma")
                        assert identity.stdout.strip() == expected, (
                            identity.stdout + identity.stderr
                        )
                if Path(runtime).name == "podman":
                    check = command(runtime, "healthcheck", "run", name)
                    assert check.returncode == 0, check.stdout + check.stderr
                if backend == "wayland":
                    descriptors = (
                        ["pid", "args"]
                        if Path(runtime).name == "podman"
                        else ["-eo", "pid,args"]
                    )
                    process_list = command(runtime, "top", name, *descriptors)
                    assert process_list.returncode == 0, process_list.stderr
                    processes = [
                        line.split(None, 1)[-1]
                        for line in process_list.stdout.splitlines()
                    ]
                    compositors = [
                        line
                        for line in processes
                        if line.startswith("/usr/bin/kwin_wayland ")
                    ]
                    assert len(compositors) == 1, (
                        f"Expected one compositor, found: {compositors}"
                    )
                for service in ("plasma-vnc.service", "plasma-web.service"):
                    active = command(
                        runtime, "exec", name, "systemctl", "is-active", service
                    ).stdout.strip()
                    expected = (
                        mode in ("vnc", "web")
                        if service == "plasma-vnc.service"
                        else mode == "web"
                    )
                    assert (active == "active") == expected, (service, active)
                if options.capture and mode in ("vnc", "web"):
                    port = 5900 if mode == "vnc" else 6080
                    address = command(
                        runtime, "port", name, f"{port}/tcp"
                    ).stdout.strip()
                    capture = [
                        "uv",
                        "run",
                        str(Path(__file__).with_name("capture-vnc.py")),
                        "--port",
                        address.rsplit(":", 1)[1],
                        "--output",
                        str(case / "desktop.png"),
                    ]
                    if mode == "web":
                        capture.append("--web")
                    result = command(*capture)
                    (case / "capture.log").write_text(result.stdout + result.stderr)
                    if result.returncode:
                        raise RuntimeError(result.stdout + result.stderr)
                print(f"PASS {label}", flush=True)
            except (
                RuntimeError,
                AssertionError,
                OSError,
                subprocess.SubprocessError,
            ) as error:
                failed.append(label)
                (case / "failure.log").write_text(str(error))
                print(f"FAIL {label}: {error}", flush=True)
            finally:
                collect_artifacts(
                    runtime,
                    name,
                    case,
                    extra=[
                        (
                            "units.log",
                            [
                                "exec",
                                name,
                                "systemctl",
                                "--no-pager",
                                "--all",
                                "--failed",
                            ],
                        ),
                        ("identity.log", ["exec", name, "id", "plasma"]),
                        (
                            "uid-map.log",
                            ["exec", name, "cat", "/proc/1/uid_map", "/proc/1/gid_map"],
                        ),
                    ],
                )
    print(f"Artifacts: {artifacts}", flush=True)
    if failed:
        raise SystemExit(f"Failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
