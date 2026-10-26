# /// script
# requires-python = ">=3.10"
# dependencies = ["pycryptodome>=3.20,<4", "pillow>=11,<13", "websocket-client>=1.8,<2"]
# ///
"""Validate TARGET_APP, fullscreen UI, input, restart and absence of Plasma shell."""

import argparse
import json
import os
import shlex
import struct
import subprocess
import time
import traceback
from pathlib import Path

import websocket
from rfb import RFBClient
from support import (
    available_backends,
    collect_artifacts,
    launch,
    renderer_command,
    run,
    software_options,
    wait_ready,
)
from ui import EXPECTED, banner_box

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Chromium kiosk test</title>
<style>html,body{margin:0;width:100%;height:100%;background:rgb(18,210,178);font:28px sans-serif}
h1{position:absolute;top:15%;width:100%;text-align:center}
input{position:absolute;left:15%;top:40%;width:70%;height:60px;box-sizing:border-box;font:28px sans-serif}
#status{position:absolute;left:20%;top:65%;width:60%;height:60px;background:rgb(90,90,90)}</style></head>
<body><h1>Chromium kiosk test</h1><input autofocus aria-label="Kiosk input"><div id="status"></div>
<script>document.querySelector('input').oninput=e=>document.querySelector('#status').style.background=
e.target.value==='Kiosk AaZz 0123!?'?'rgb(35,180,95)':'rgb(90,90,90)';</script></body></html>"""


def state(runtime, name):
    result = run(runtime, "exec", name, "cat", "/run/plasma/target-app.json")
    return json.loads(result.stdout) if result.returncode == 0 else {}


def processes(runtime, name):
    result = run(
        runtime,
        "exec",
        name,
        "python3",
        "-c",
        "from pathlib import Path; import json; "
        "print(json.dumps([(p.name,(p/'comm').read_text().strip()) for p in Path('/proc').glob('[0-9]*') "
        "if (p/'comm').exists()]))",
    )
    return [tuple(item) for item in json.loads(result.stdout)]


def near(actual, expected):
    return max(abs(a - b) for a, b in zip(actual, expected)) <= 8


def browser_visible(image):
    return all(
        near(image.getpixel(point), (18, 210, 178))
        for point in [
            (8, 8),
            (image.width - 9, 8),
            (8, image.height - 9),
            (image.width - 9, image.height - 9),
        ]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=("docker", "podman"), default="docker")
    parser.add_argument("--image", default="plasma6:ui-test")
    parser.add_argument(
        "--apps",
        nargs="+",
        choices=("fixture", "chromium"),
        default=("fixture", "chromium"),
    )
    parser.add_argument("--backends", nargs="+", choices=("wayland", "x11"))
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("headless", "nested", "vnc", "web"),
        default=("headless", "nested", "vnc", "web"),
    )
    parser.add_argument("--no-gpu", action="store_true")
    options = parser.parse_args()
    runtime = options.runtime
    if options.backends is None:
        options.backends = available_backends(runtime, options.image)
    root = Path(__file__).resolve().parents[1]
    artifacts = (
        root
        / "test/.artifacts"
        / f"kiosk-{runtime}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    )
    artifacts.mkdir(parents=True)
    failures = []
    for app in options.apps:
        for backend in options.backends:
            for mode in options.modes:
                label = f"{app}-{backend}-{mode}"
                case = artifacts / label
                shared = case / "host-files"
                shared.mkdir(parents=True, mode=0o700)
                output = shared / "typed.txt"
                output.touch(mode=0o600)
                page = shared / "page.html"
                page.write_text(PAGE)
                page.chmod(0o644)
                name = f"plasma6-kiosk-{os.getpid()}-{label}"
                target = (
                    "plasma-ui-fixture /e2e-output/typed.txt"
                    if app == "fixture"
                    else shlex.join(
                        [
                            "chromium",
                            "--password-store=basic",
                            "file:///kiosk-test/page.html",
                        ]
                    )
                )
                arguments = [
                    "--mount",
                    f"type=bind,source={output},target=/e2e-output/typed.txt",
                    "--mount",
                    f"type=bind,source={page},target=/kiosk-test/page.html,readonly",
                ]
                if options.no_gpu:
                    arguments += software_options(runtime)
                report = {
                    "app": app,
                    "backend": backend,
                    "mode": mode,
                    "gpu_hidden": options.no_gpu,
                    "checks": {},
                }
                client = None
                try:
                    result = launch(
                        runtime,
                        options.image,
                        name,
                        backend,
                        mode,
                        *arguments,
                        TARGET_APP=target,
                    )
                    (case / "run.log").write_text(result.stdout + result.stderr)
                    if result.returncode:
                        raise RuntimeError(result.stderr)
                    wait_ready(runtime, name, timeout=90)
                    renderer = run(runtime, *renderer_command(name))
                    (case / "renderer.log").write_text(
                        renderer.stdout + renderer.stderr
                    )
                    if options.no_gpu:
                        report["checks"]["software_renderer"] = (
                            renderer.returncode == 0
                            and any(
                                value in renderer.stdout.lower()
                                for value in (
                                    "qpainter",
                                    "llvmpipe",
                                    "softpipe",
                                    "swrast",
                                )
                            )
                        )
                    initial_state = state(runtime, name)
                    initial_processes = processes(runtime, name)
                    forbidden = {
                        "plasmashell",
                        "plasma_session",
                        "ksmserver",
                        "startplasma-way",
                        "startplasma-x11",
                    }
                    report["checks"]["no_plasma_session"] = not any(
                        comm in forbidden for _, comm in initial_processes
                    )
                    compositor = [
                        (pid, comm)
                        for pid, comm in initial_processes
                        if comm == f"kwin_{backend}"
                    ]
                    report["checks"]["one_compositor"] = len(compositor) == 1
                    report["checks"]["target_running"] = str(
                        initial_state["pid"]
                    ) in dict(initial_processes)
                    report["initial_app_state"] = initial_state
                    if mode in ("vnc", "web"):
                        port = 5900 if mode == "vnc" else 6080
                        address = run(
                            runtime, "port", name, f"{port}/tcp"
                        ).stdout.strip()
                        client = RFBClient(
                            int(address.rsplit(":", 1)[1]), web=mode == "web"
                        )
                        deadline = time.monotonic() + 30
                        while True:
                            image = client.screenshot()
                            box = banner_box(image) if app == "fixture" else None
                            visible = (
                                bool(box)
                                if app == "fixture"
                                else browser_visible(image)
                            )
                            if visible:
                                break
                            if time.monotonic() >= deadline:
                                image.save(case / "failure.png")
                                raise RuntimeError(
                                    "Fullscreen target application did not appear"
                                )
                            time.sleep(0.25)
                        image.save(case / "01-fullscreen.png")
                        if app == "fixture":
                            report["checks"]["fullscreen"] = (
                                abs(box[0] - 12) <= 2
                                and abs(box[1] - 12) <= 2
                                and abs(box[2] - (image.width - 12)) <= 2
                            )
                            client.click(box[0] + 100, box[3] + 70)
                            client.text(EXPECTED)
                            client.chord(0xFFE3, ord("s"))
                            deadline = time.monotonic() + 8
                            while (
                                output.read_text() != EXPECTED
                                and time.monotonic() < deadline
                            ):
                                time.sleep(0.1)
                            report["checks"]["input_and_host_save"] = (
                                output.read_text() == EXPECTED
                            )
                        else:
                            report["checks"]["fullscreen"] = browser_visible(image)
                            client.click(image.width // 2, int(image.height * 0.4 + 30))
                            client.text("Kiosk AaZz 0123!?")
                            deadline = time.monotonic() + 8
                            while True:
                                image = client.screenshot()
                                correct = near(
                                    image.getpixel(
                                        (
                                            image.width // 2,
                                            int(image.height * 0.65 + 30),
                                        )
                                    ),
                                    (35, 180, 95),
                                )
                                if correct or time.monotonic() >= deadline:
                                    break
                                time.sleep(0.2)
                            report["checks"]["browser_input"] = correct
                        client.screenshot().save(case / "02-after-input.png")
                        # A crashed application must restart without replacing KWin or the VNC connection.
                        run(
                            runtime,
                            "exec",
                            name,
                            "kill",
                            "-KILL",
                            str(initial_state["pid"]),
                        )
                        deadline = time.monotonic() + 15
                        while True:
                            current = state(runtime, name)
                            if (
                                current
                                and current["pid"] != initial_state["pid"]
                                and run(
                                    runtime, "exec", name, "plasma-healthcheck"
                                ).returncode
                                == 0
                            ):
                                break
                            if time.monotonic() >= deadline:
                                raise RuntimeError("Target application did not restart")
                            time.sleep(0.25)
                        report["restart_app_state"] = current
                        report["checks"]["app_restart"] = (
                            current["supervisor"] == initial_state["supervisor"]
                        )
                        report["checks"]["compositor_preserved"] = all(
                            (pid, comm) in processes(runtime, name)
                            for pid, comm in compositor
                        )
                        deadline = time.monotonic() + 20
                        while True:
                            image = client.screenshot()
                            visible = (
                                bool(banner_box(image))
                                if app == "fixture"
                                else browser_visible(image)
                            )
                            if visible or time.monotonic() >= deadline:
                                break
                            time.sleep(0.25)
                        image.save(case / "03-after-restart.png")
                        report["checks"]["visible_after_restart"] = visible
                    if not all(report["checks"].values()):
                        raise AssertionError(report["checks"])
                    print(f"PASS {label}: {report['checks']}", flush=True)
                except (
                    AssertionError,
                    OSError,
                    RuntimeError,
                    ValueError,
                    subprocess.SubprocessError,
                    struct.error,
                    websocket.WebSocketException,
                ) as error:
                    failures.append(label)
                    report["error"] = str(error)
                    (case / "failure.log").write_text(traceback.format_exc())
                    print(f"FAIL {label}: {error}", flush=True)
                finally:
                    if client:
                        try:
                            client.close()
                        except (OSError, RuntimeError, websocket.WebSocketException):
                            (case / "cleanup.log").write_text(traceback.format_exc())
                    (case / "result.json").write_text(
                        json.dumps(report, indent=2) + "\n"
                    )
                    collect_artifacts(runtime, name, case, services=("session",))
    print(f"Artifacts: {artifacts}", flush=True)
    if failures:
        raise SystemExit(f"Failed kiosk cases: {', '.join(failures)}")


if __name__ == "__main__":
    main()
