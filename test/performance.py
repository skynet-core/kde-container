# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.55,<2", "pillow>=11,<13"]
# ///
"""Measure real noVNC canvas delivery, key-to-pixel latency and window dragging."""

import argparse
import base64
import io
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time
import traceback

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright


def run(*arguments):
    return subprocess.run(arguments, text=True, capture_output=True, timeout=180)


def banner_box(image):
    difference = ImageChops.difference(
        image, Image.new("RGB", image.size, (18, 210, 178))
    )
    red, green, blue = difference.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    box = maximum.point(lambda value: 255 if value <= 8 else 0).getbbox()
    return box if box and box[2] - box[0] >= 700 and box[3] - box[1] >= 35 else None


def screenshot(page):
    encoded = page.evaluate(
        "window.perfRfb._display._target.toDataURL('image/png').split(',')[1]"
    )
    return Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=("docker", "podman"), default="docker")
    parser.add_argument("--image", default="plasma6:ui-test")
    parser.add_argument("--backend", choices=("wayland", "x11"), default="wayland")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--duration", type=float, default=6)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--compression", type=int, default=2)
    parser.add_argument("--quality", type=int, default=6)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--min-fps", type=float, default=25)
    parser.add_argument("--max-latency-p95", type=float, default=150)
    parser.add_argument(
        "--measure-only",
        action="store_true",
        help="Record an older/slower image without enforcing speed thresholds",
    )
    parser.add_argument(
        "--no-gpu",
        action="store_true",
        help="Hide /dev/dri to exercise automatic software fallback",
    )
    parser.add_argument(
        "--expect-renderer", choices=("any", "gpu", "software"), default="any"
    )
    options = parser.parse_args()
    artifacts = (
        Path(__file__).resolve().parent
        / ".artifacts"
        / f"performance-{options.runtime}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    )
    artifacts.mkdir(parents=True)
    runtime = options.runtime
    name = f"plasma6-performance-{os.getpid()}"
    report = {"settings": vars(options), "checks": {}}
    args = [
        runtime,
        "run",
        "-d",
        "--name",
        name,
        "--privileged",
        "--user=0:0",
        "--cgroupns=private",
        "--pids-limit=8192",
        "--shm-size=512m",
        "--tmpfs",
        "/run",
        "--tmpfs",
        "/tmp:mode=1777",
        "-e",
        f"DISPLAY_BACKEND={options.backend}",
        "-e",
        "DISPLAY_MODE=web",
        "-e",
        f"DISPLAY_WIDTH={options.width}",
        "-e",
        f"DISPLAY_HEIGHT={options.height}",
        "-e",
        f"VNC_MAX_FPS={options.fps}",
        "-e",
        "VNC_PASSWORD=testpass",
        "-e",
        f"PLASMA_UID={os.getuid()}",
        "-e",
        f"PLASMA_GID={os.getgid()}",
        "-p",
        "127.0.0.1::6080",
    ]
    if runtime == "podman":
        args += ["--systemd=always", "--passwd=false", "--userns=keep-id"]
    else:
        args += ["--userns=host"]
    if options.no_gpu:
        args += ["--tmpfs", "/dev/dri:mode=0755"]
        if runtime == "podman":
            # Privileged rootless Podman bind-mounts host devices after tmpfs.
            # Keep systemd's capabilities without importing those GPU devices.
            args.remove("--privileged")
            args += ["--cap-add=all", "--security-opt=seccomp=unconfined"]
            if Path("/dev/udmabuf").exists():
                args += ["--device", "/dev/udmabuf"]
    try:
        result = run(*args, options.image)
        (artifacts / "run.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(result.stderr)
        deadline = time.monotonic() + 120
        while run(runtime, "exec", name, "plasma-healthcheck").returncode:
            if time.monotonic() >= deadline:
                raise RuntimeError("Desktop failed to become ready")
            time.sleep(1)
        renderer = run(
            runtime,
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
        )
        (artifacts / "renderer.log").write_text(renderer.stdout + renderer.stderr)
        software = any(
            value in renderer.stdout.lower()
            for value in ("qpainter", "llvmpipe", "softpipe", "swrast")
        )
        opengl = "Compositing Type: OpenGL" in renderer.stdout
        report["renderer"] = {
            "software": software,
            "opengl": opengl,
            "description": [
                line
                for line in renderer.stdout.splitlines()
                if line.startswith(("Compositing Type:", "OpenGL renderer string:"))
            ],
        }
        if options.expect_renderer != "any":
            report["checks"]["renderer"] = renderer.returncode == 0 and (
                software
                if options.expect_renderer == "software"
                else opengl and not software
            )
        display = (
            ["WAYLAND_DISPLAY=wayland-0", "QT_QPA_PLATFORM=wayland"]
            if options.backend == "wayland"
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
            "plasma-vnc-benchmark",
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        address = run(runtime, "port", name, "6080/tcp").stdout.strip()
        port = int(address.rsplit(":", 1)[1])
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=shutil.which("chromium"),
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                ],
            )
            page = browser.new_page(
                viewport={"width": options.width + 80, "height": options.height + 100}
            )
            console = []
            page.on(
                "console",
                lambda message: console.append(f"{message.type}: {message.text}"),
            )
            page.goto(
                f"http://127.0.0.1:{port}/vnc.html?autoconnect=1&password=testpass&resize=off"
                f"&quality={options.quality}&compression={options.compression}"
            )
            page.evaluate(
                "async () => { window.perfUI = (await import('/app/ui.js')).default; }"
            )
            page.wait_for_function(
                "window.perfUI.rfb?._rfbConnectionState === 'connected'", timeout=30000
            )
            page.evaluate("window.perfRfb = window.perfUI.rfb")
            deadline = time.monotonic() + 20
            while True:
                before = screenshot(page)
                box = banner_box(before)
                if box:
                    break
                if time.monotonic() >= deadline:
                    before.save(artifacts / "setup-failure.png")
                    raise RuntimeError("Benchmark window did not appear")
                time.sleep(0.25)
            before.save(artifacts / "01-before.png")
            x, y, right, bottom = box
            page.evaluate(
                """({frame, feedback}) => {
                const canvas = window.perfRfb._display._target;
                const context = canvas.getContext('2d');
                window.perfPixel = point => Array.from(context.getImageData(point[0], point[1], 1, 1).data).slice(0, 3);
                window.perfChanged = (a, b) => a.some((value, index) => Math.abs(value - b[index]) > 32);
                window.perfFrame = frame;
                window.perfFeedback = feedback;
            }""",
                {"frame": [x + 60, y + 118], "feedback": [x + 188, y + 118]},
            )
            # Count actual changes in a marker painted by the native desktop app.
            # Neither the browser's own animation rate nor empty RFB updates count.
            timestamps = page.evaluate(
                """duration => new Promise(resolve => {
                const start = performance.now();
                const timestamps = [];
                let previous = window.perfPixel(window.perfFrame);
                function sample(now) {
                    const current = window.perfPixel(window.perfFrame);
                    if (window.perfChanged(current, previous)) {
                        timestamps.push(now - start);
                        previous = current;
                    }
                    if (now - start >= duration) resolve(timestamps);
                    else requestAnimationFrame(sample);
                }
                requestAnimationFrame(sample);
            })""",
                options.duration * 1000,
            )
            report["animation"] = {
                "visible_changes": len(timestamps),
                "duration_seconds": options.duration,
                "fps": len(timestamps) / options.duration,
                "timestamps_ms": timestamps,
            }
            # Browser keyboard events travel through noVNC, WebSocket, VNC and KWin.
            # End timing only when the app's changed acknowledgement reaches the canvas.
            latencies = []
            canvas = page.locator("canvas").bounding_box()
            page.mouse.click(canvas["x"] + x + 350, canvas["y"] + y + 180)
            for _ in range(options.samples):
                page.evaluate(
                    "window.perfPrevious = window.perfPixel(window.perfFeedback); window.perfStart = performance.now()"
                )
                page.keyboard.press("a")
                page.wait_for_function(
                    "window.perfChanged(window.perfPixel(window.perfFeedback), window.perfPrevious)",
                    timeout=5000,
                )
                latencies.append(page.evaluate("performance.now() - window.perfStart"))
                time.sleep(0.03)
            ordered = sorted(latencies)
            report["keyboard_latency_ms"] = {
                "median": statistics.median(latencies),
                "p95": ordered[max(0, int(len(ordered) * 0.95 + 0.999) - 1)],
                "samples": latencies,
            }
            page.keyboard.press("p")  # Pause the animation before the drag screenshots.
            time.sleep(0.3)
            before = screenshot(page)
            before.save(artifacts / "02-before-drag.png")
            canvas = page.locator("canvas").bounding_box()
            start_x, start_y = canvas["x"] + (x + right) / 2, canvas["y"] + y - 25
            page.mouse.move(start_x, start_y)
            page.mouse.down()
            for step in range(1, 61):
                page.mouse.move(start_x + 150 * step / 60, start_y + 90 * step / 60)
                time.sleep(1 / 60)
            page.mouse.up()
            time.sleep(0.4)
            after = screenshot(page)
            after.save(artifacts / "03-after-drag.png")
            moved = banner_box(after)
            delta = [moved[0] - x, moved[1] - y] if moved else None
            report["drag_delta"] = delta
            comparison = Image.new("RGB", (before.width * 2, before.height))
            comparison.paste(before, (0, 0))
            comparison.paste(after, (before.width, 0))
            comparison.save(artifacts / "drag-comparison.png")
            report["checks"]["mouse_drag"] = bool(
                delta and abs(delta[0] - 150) <= 8 and abs(delta[1] - 90) <= 8
            )
            report["checks"]["frame_delivery"] = (
                report["animation"]["fps"] >= options.min_fps
            )
            report["checks"]["input_latency"] = (
                report["keyboard_latency_ms"]["p95"] <= options.max_latency_p95
            )
            (artifacts / "browser.log").write_text("\n".join(console) + "\n")
            browser.close()
        print(
            f"{options.image} ({runtime}/{options.backend}): {report['animation']['fps']:.1f} visible fps, "
            f"keyboard median={statistics.median(latencies):.1f} ms, p95={report['keyboard_latency_ms']['p95']:.1f} ms, drag={delta}",
            flush=True,
        )
        required = [
            value
            for key, value in report["checks"].items()
            if not options.measure_only
            or key not in ("frame_delivery", "input_latency")
        ]
        if not all(required):
            raise AssertionError(f"Performance checks failed: {report['checks']}")
    except Exception as error:
        report["error"] = str(error)
        (artifacts / "failure.log").write_text(traceback.format_exc())
        raise
    finally:
        (artifacts / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        for filename, arguments in [
            ("container.log", ["logs", name]),
            (
                "vnc.log",
                ["exec", name, "journalctl", "-b", "-u", "plasma-vnc", "--no-pager"],
            ),
            ("journal.log", ["exec", name, "journalctl", "-b", "--no-pager"]),
            ("session.env", ["exec", name, "cat", "/etc/plasma/session.env"]),
            (
                "renderer.log",
                [
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
                ],
            ),
        ]:
            result = run(runtime, *arguments)
            (artifacts / filename).write_text(result.stdout + result.stderr)
        run(runtime, "rm", "-f", name)
        print(f"Artifacts: {artifacts}", flush=True)


if __name__ == "__main__":
    main()
