# /// script
# requires-python = ">=3.10"
# dependencies = ["pycryptodome>=3.20,<4", "pillow>=11,<13", "websocket-client>=1.8,<2"]
# ///
"""Validate mouse dragging from RFB screenshots and text saved by the UI into a host mount."""

import argparse
import json
import os
import struct
import subprocess
import time
import traceback
from pathlib import Path

import websocket
from PIL import Image, ImageChops
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

EXPECTED = (
    "Plasma VNC UI test\nMouse drag + keyboard: AaZz 0123456789!?\nSaved from the UI.\n"
)
BANNER = (18, 210, 178)


def banner_box(image):
    difference = ImageChops.difference(image, Image.new("RGB", image.size, BANNER))
    red, green, blue = difference.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    mask = maximum.point(lambda value: 255 if value <= 3 else 0)
    box = mask.getbbox()
    if box and box[2] - box[0] >= 400 and box[3] - box[1] >= 35:
        return box
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime",
        choices=("docker", "podman"),
        default=os.environ.get("RUNTIME", "docker"),
    )
    parser.add_argument(
        "--image", default=os.environ.get("IMAGE_TAG", "plasma6:ui-test")
    )
    parser.add_argument("--backends", nargs="+", choices=("wayland", "x11"))
    parser.add_argument(
        "--modes", nargs="+", choices=("vnc", "web"), default=("vnc", "web")
    )
    parser.add_argument(
        "--no-gpu",
        action="store_true",
        help="Hide render nodes to test automatic software fallback",
    )
    options = parser.parse_args()
    runtime = options.runtime
    if options.backends is None:
        options.backends = available_backends(runtime, options.image)
    artifacts = (
        Path(__file__).resolve().parent
        / ".artifacts"
        / f"ui-{runtime}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    )
    artifacts.mkdir(parents=True)
    failures = []
    for backend in options.backends:
        for mode in options.modes:
            label = f"{backend}-{mode}"
            case = artifacts / label
            shared = case / "host-files"
            shared.mkdir(parents=True, mode=0o700)
            output = shared / "typed.txt"
            output.touch(mode=0o600)
            (case / "expected.txt").write_text(EXPECTED)
            name = f"plasma6-ui-{os.getpid()}-{label}"
            port = 5900 if mode == "vnc" else 6080
            args = [
                "--mount",
                f"type=bind,source={output},target=/e2e-output/typed.txt",
            ]
            if options.no_gpu:
                args += software_options(runtime)
            report = {
                "backend": backend,
                "mode": mode,
                "runtime": runtime,
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
                    *args,
                    DISPLAY_WIDTH="1280",
                    DISPLAY_HEIGHT="900",
                )
                (case / "run.log").write_text(result.stdout + result.stderr)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                wait_ready(runtime, name)
                renderer = run(runtime, *renderer_command(name))
                (case / "renderer.log").write_text(renderer.stdout + renderer.stderr)
                if options.no_gpu:
                    report["checks"]["software_renderer"] = (
                        renderer.returncode == 0
                        and any(
                            value in renderer.stdout.lower()
                            for value in ("qpainter", "llvmpipe", "softpipe", "swrast")
                        )
                    )
                # Launch a native Qt Wayland editor on Wayland, and an X11 editor on X11.
                # Every mouse and keyboard action after setup is sent exclusively over RFB.
                time.sleep(3)
                display = (
                    ["WAYLAND_DISPLAY=wayland-0", "QT_QPA_PLATFORM=wayland"]
                    if backend == "wayland"
                    else [
                        "DISPLAY=:100",
                        "QT_QPA_PLATFORM=xcb",
                        "XAUTHORITY=/etc/plasma/Xauthority",
                    ]
                )
                result = run(
                    runtime,
                    "exec",
                    "-d",
                    "--user=plasma",
                    name,
                    "env",
                    "XDG_RUNTIME_DIR=/run/plasma",
                    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/plasma/bus",
                    *display,
                    "plasma-ui-fixture",
                    "/e2e-output/typed.txt",
                )
                if result.returncode:
                    raise RuntimeError(result.stderr)
                address = run(runtime, "port", name, f"{port}/tcp").stdout.strip()
                client = RFBClient(int(address.rsplit(":", 1)[1]), web=mode == "web")
                deadline = time.monotonic() + 30
                while True:
                    before = client.screenshot()
                    original = banner_box(before)
                    if original:
                        break
                    if time.monotonic() >= deadline:
                        before.save(case / "setup-failure.png")
                        raise RuntimeError("The UI fixture did not appear")
                    time.sleep(0.25)
                before.save(case / "01-before-drag.png")
                x, y, right, bottom = original
                dx, dy = 150, 90
                client.drag((x + right) // 2, y - 25, dx, dy)
                time.sleep(0.5)
                after = client.screenshot()
                after.save(case / "02-after-drag.png")
                moved = banner_box(after)
                actual = (moved[0] - x, moved[1] - y) if moved else None
                report["drag"] = {
                    "before": original,
                    "after": moved,
                    "requested_delta": [dx, dy],
                    "measured_delta": actual,
                }
                report["checks"]["mouse_drag"] = bool(
                    actual and abs(actual[0] - dx) <= 8 and abs(actual[1] - dy) <= 8
                )
                comparison = Image.new("RGB", (before.width * 2, before.height))
                comparison.paste(before, (0, 0))
                comparison.paste(after, (before.width, 0))
                comparison.save(case / "drag-comparison.png")

                # Derive editor coordinates from the actual screenshot, even when dragging failed.
                x, y, right, bottom = moved or original
                client.click(x + 120, bottom + 70)
                client.text(EXPECTED)
                client.chord(
                    0xFFE3, ord("s")
                )  # Ctrl+S invokes the editor's Save UI action.
                deadline = time.monotonic() + 5
                while output.read_text() != EXPECTED and time.monotonic() < deadline:
                    time.sleep(0.1)
                time.sleep(0.25)
                client.screenshot().save(case / "03-after-typing-and-save.png")
                actual_text = output.read_text() if output.exists() else None
                report["actual_text"] = actual_text
                report["checks"]["keyboard_save_to_host"] = actual_text == EXPECTED
                report["checks"]["host_file_owner"] = (
                    output.exists() and output.stat().st_uid == os.getuid()
                )
                if not all(report["checks"].values()):
                    raise AssertionError(f"UI checks failed: {report['checks']}")
                print(
                    f"PASS {label}: drag={actual}, typed and saved {len(EXPECTED)} characters to {output}",
                    flush=True,
                )
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
                (case / "result.json").write_text(json.dumps(report, indent=2) + "\n")
                collect_artifacts(runtime, name, case, services=("vnc",))
    print(f"Artifacts: {artifacts}", flush=True)
    if failures:
        raise SystemExit(f"Failed UI cases: {', '.join(failures)}")


if __name__ == "__main__":
    main()
