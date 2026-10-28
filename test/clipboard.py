# /// script
# dependencies = ["pycryptodome>=3.20,<4", "pillow>=11,<13", "websocket-client>=1.8,<2"]
# ///
"""Exercise clipboard sharing against isolated host desktops, never the user's clipboard."""

import argparse
import base64
import contextlib
import io
import json
import os
import queue
import subprocess
import threading
import time
import traceback
from pathlib import Path

from PIL import Image, ImageDraw
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
from ui import banner_box


class NestedClient(RFBClient):
    def key(self, keysym, down):
        super().key(keysym, down)
        # Let both nested event queues process each physical key transition.
        time.sleep(0.04)


def configuration(runtime, name):
    result = run(
        runtime,
        "exec",
        name,
        "python3",
        "-c",
        "import json,shlex; print(json.dumps(dict(shlex.split(line)[0].split('=',1) for line in open('/etc/plasma/session.env'))))",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def display_environment(config):
    # docker/podman exec does not inherit systemd's EnvironmentFile. Match the
    # actual desktop, including its software fallback and application identity.
    return [f"{key}={value}" for key, value in config.items()]


class Probe:
    def __init__(self, runtime, name, config, log):
        self.messages = queue.Queue()
        self.latest = {}
        self.log = log.open("w")
        self.process = subprocess.Popen(
            [
                runtime,
                "exec",
                "-i",
                "--user=plasma",
                name,
                "env",
                *display_environment(config),
                "/usr/local/libexec/plasma-clipboard",
                "--endpoint",
                config["DISPLAY_BACKEND"],
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
        )
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self):
        for line in self.process.stdout:
            message = json.loads(line)
            self.latest[message["mode"]] = message
            self.messages.put(message)

    def set(self, formats, mode=0):
        self.drain()
        self.process.stdin.write(
            json.dumps(
                {
                    "mode": mode,
                    "data": {
                        key: base64.b64encode(value).decode()
                        for key, value in formats.items()
                    },
                }
            )
            + "\n"
        )
        self.process.stdin.flush()

    def drain(self):
        count = 0
        while True:
            try:
                self.messages.get_nowait()
                count += 1
            except queue.Empty:
                return count

    def wait(self, formats, mode=0):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=0.25)
            except queue.Empty:
                assert self.process.poll() is None, "Clipboard probe exited"
                continue
            actual = {
                key: base64.b64decode(value) for key, value in message["data"].items()
            }
            if message["mode"] == mode and all(
                actual.get(key) == value for key, value in formats.items()
            ):
                return
        latest = self.latest.get(mode, {}).get("data", {})
        text = base64.b64decode(latest.get("text/plain", "")).decode(
            "utf-8", errors="replace"
        )[:500]
        raise AssertionError(
            f"Clipboard did not receive mode {mode}, formats {list(formats)}; "
            f"latest formats {list(latest)}, test text {text!r}"
        )

    def wait_image(self, expected):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=0.25)
            except queue.Empty:
                assert self.process.poll() is None, "Clipboard image probe exited"
                continue
            if message["mode"] != 0 or "image/png" not in message["data"]:
                continue
            png = base64.b64decode(message["data"]["image/png"])
            actual = Image.open(io.BytesIO(png)).convert("RGBA")
            if actual.size == expected.size and actual.tobytes() == expected.tobytes():
                assert not any(
                    key.startswith("image/")
                    and key not in ("image/png", "image/svg+xml")
                    for key in message["data"]
                ), "Redundant raster encodings were transferred"
                assert "application/x-qt-image" not in message["data"]
                return png
        raise AssertionError("Clipboard did not receive the complete 4K Qt image")

    def close(self):
        with contextlib.suppress(BrokenPipeError):
            self.process.stdin.close()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.log.close()


def clipboard_payload(label):
    png = io.BytesIO()
    Image.new("RGB", (37, 19), (18, 210, 178)).save(png, format="PNG")
    return {
        "text/plain": f"{label}: Καλημέρα 🌍\n".encode(),
        "text/html": f"<p><b>{label}</b> Καλημέρα 🌍</p>".encode(),
        "image/png": png.getvalue(),
        "text/uri-list": b"file:///shared/Clipboard%20test.txt\r\n",
        "application/x-plasma6-test-binary": bytes(range(256)) * 4096,
        "application/x-plasma6-test-empty": b"",
    }


def expected_image(publisher=False):
    image = Image.new("RGBA", (3840, 2160))
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (0, 0, 1919, 1079),
        fill=(210, 100, 180, 255) if publisher else (220, 40, 70, 255),
    )
    draw.rectangle((1920, 0, 3839, 1079), fill=(20, 180, 90, 255))
    draw.rectangle((0, 1080, 1919, 2159), fill=(40, 90, 220, 255))
    draw.rectangle((1920, 1080, 3839, 2159), fill=(0, 0, 0, 128))
    return image


def image_checks(
    runtime,
    outer,
    inner,
    host_config,
    config,
    case,
    client,
    parent_client,
    host_probe,
    inner_probe,
):
    for name, settings, arguments in (
        (inner, config, ("/e2e-images/pasted.png", "--images")),
        (outer, host_config, ("/dev/null", "--publish-image")),
    ):
        result = run(
            runtime,
            "exec",
            "-d",
            "--user=plasma",
            name,
            "env",
            *display_environment(settings),
            "plasma-ui-fixture",
            *arguments,
        )
        assert result.returncode == 0, result.stderr
        time.sleep(0.5)
    # A real click and Copy action provide the source Qt Wayland client with
    # keyboard focus and a valid input serial, just like copying in Spectacle.
    deadline = time.monotonic() + 15
    while True:
        screenshot = parent_client.screenshot()
        box = banner_box(screenshot, color=(215, 120, 30))
        if box:
            break
        assert time.monotonic() < deadline, "Qt image owner did not appear"
        time.sleep(0.25)
    screenshot.save(case / "04-qt-image-source.png")
    parent_client.click(box[0] + 100, box[1] + 20)
    parent_client.chord(0xFFE3, ord("c"))
    expected = expected_image(publisher=True)
    png = host_probe.wait_image(expected)
    (case / "images" / "host-qt.png").write_bytes(png)
    inner_probe.wait_image(expected)
    # Cache the real Qt offer before closing its producer, leaving only the
    # nested editor visible for the subsequent paste.
    payload = {
        "image/png": png,
        "application/x-kde-suggestedfilename": b"Dolphin screenshot.png",
    }
    host_probe.set(payload)
    stopped = run(
        runtime,
        "exec",
        "--user=plasma",
        outer,
        "python3",
        "-c",
        """
from pathlib import Path
import os, signal
for path in Path('/proc').glob('[0-9]*'):
    try:
        args = (path / 'cmdline').read_bytes().split(bytes([0]))
        if args[0].split(b' ', 1)[0].rsplit(b'/', 1)[-1] == b'plasma-ui-fixture' and b'--publish-image' in args:
            os.kill(int(path.name), signal.SIGTERM)
    except (FileNotFoundError, ProcessLookupError):
        pass
""",
    )
    assert stopped.returncode == 0, stopped.stderr
    # Wait for a fresh frame after the producer exits.
    deadline = time.monotonic() + 15
    while True:
        screenshot = client.screenshot()
        box = banner_box(screenshot)
        if box:
            break
        assert time.monotonic() < deadline, "Image paste fixture did not appear"
        time.sleep(0.25)
    client.click(box[0] + 100, box[3] + 70)
    client.chord(0xFFE3, ord("v"))
    client.chord(0xFFE3, ord("s"))
    output = case / "images" / "pasted.png"
    deadline = time.monotonic() + 10
    while True:
        try:
            actual = Image.open(output).convert("RGBA")
            if actual.size == expected.size and actual.tobytes() == expected.tobytes():
                break
        except (OSError, ValueError):
            pass
        assert time.monotonic() < deadline, (
            "Qt GUI did not paste and save the complete image"
        )
        time.sleep(0.1)
    client.screenshot().save(case / "04-qt-image-pasted.png")
    host_probe.drain()
    client.chord(0xFFE3, ord("c"))
    (case / "images" / "container-qt.png").write_bytes(
        host_probe.wait_image(expected_image())
    )


def browser_image_check(runtime, inner, config, case, client, host_probe, inner_probe):
    result = run(
        runtime,
        "exec",
        "-d",
        "--user=plasma",
        inner,
        "python3",
        "/e2e-clipboard-browser.py",
        "/e2e-images/browser.png",
    )
    assert result.returncode == 0, result.stderr
    # Wait for the local page before launching Chromium; a cold Python HTTP
    # import can otherwise lose the race on a busy CI worker.
    ready = run(
        runtime,
        "exec",
        inner,
        "python3",
        "-c",
        """
import time, urllib.request
for attempt in range(100):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8790', timeout=1) as response:
            assert response.status == 200
        break
    except OSError:
        time.sleep(0.1)
else:
    raise SystemExit('Clipboard test HTTP server did not become ready')
""",
    )
    assert ready.returncode == 0, ready.stderr
    binary = run(
        runtime,
        "exec",
        inner,
        "sh",
        "-c",
        "command -v chromium || command -v chromium-browser",
    ).stdout.strip()
    assert binary, "Chromium is required in the UI-test image"
    result = run(
        runtime,
        "exec",
        "-d",
        "--user=plasma",
        inner,
        "/bin/bash",
        "-c",
        'exec "$@" > /e2e-images/browser.log 2>&1',
        "clipboard-browser",
        "env",
        *display_environment(config),
        binary,
        "--no-first-run",
        "--no-default-browser-check",
        "--password-store=basic",
        "--user-data-dir=/run/plasma/clipboard-browser",
        "--ozone-platform=" + config["DISPLAY_BACKEND"],
        "--app=http://127.0.0.1:8790",
    )
    assert result.returncode == 0, result.stderr
    deadline = time.monotonic() + 20
    while True:
        screenshot = client.screenshot()
        box = banner_box(screenshot, color=(48, 140, 230))
        if box:
            break
        if time.monotonic() >= deadline:
            screenshot.save(case / "browser-start-failure.png")
            raise AssertionError("Chromium paste page did not appear")
        time.sleep(0.25)
    png = (case / "images" / "host-qt.png").read_bytes()
    host_probe.set({"image/png": png})
    inner_probe.wait({"image/png": png})
    client.click(box[0] + 100, box[1] + 20)
    client.chord(0xFFE3, ord("v"))
    expected = expected_image(publisher=True)
    output = case / "images" / "browser.png"
    deadline = time.monotonic() + 10
    while True:
        try:
            actual = Image.open(output).convert("RGBA")
            if actual.size == expected.size and actual.tobytes() == expected.tobytes():
                break
        except (OSError, ValueError):
            pass
        assert time.monotonic() < deadline, "Chromium did not paste the complete image"
        time.sleep(0.1)
    client.screenshot().save(case / "05-chromium-image-pasted.png")


def dolphin_image_check(runtime, inner, config, case, client, host_probe, inner_probe):
    # Close only our image-bearing apps; host Alt+F4 can close nested KWin.
    stopped = run(
        runtime,
        "exec",
        "--user=plasma",
        inner,
        "python3",
        "-c",
        """
from pathlib import Path
import os, signal, time
targets = []
for path in Path('/proc').glob('[0-9]*'):
    try:
        raw = (path / 'cmdline').read_bytes()
        args = raw.split(bytes([0]))
    except (FileNotFoundError, ProcessLookupError):
        continue
    program = args[0].split(b' ', 1)[0].rsplit(b'/', 1)[-1]
    # Chromium may rewrite argv into one process-title string.
    browser = program in (b'chromium', b'chromium-browser') and b'--user-data-dir=/run/plasma/clipboard-browser' in raw and b'--type=' not in raw
    image_editor = program == b'plasma-ui-fixture' and b'/e2e-images/pasted.png' in raw
    if browser or image_editor:
        try:
            os.kill(int(path.name), signal.SIGTERM)
            targets.append(path)
        except ProcessLookupError:
            pass
for attempt in range(50):
    live = []
    for path in targets:
        try:
            state = (path / 'stat').read_text().rsplit(')', 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            continue
        if state != 'Z':
            live.append(path)
    if not live:
        break
    time.sleep(0.1)
else:
    raise SystemExit('Test image applications did not stop')
""",
    )
    assert stopped.returncode == 0, stopped.stderr
    destination = case / "images" / "dolphin"
    destination.mkdir()
    payload = {
        "image/png": (case / "images" / "host-qt.png").read_bytes(),
        "application/x-kde-suggestedfilename": b"Dolphin screenshot.png",
    }
    result = run(
        runtime,
        "exec",
        "-d",
        "--user=plasma",
        inner,
        "env",
        *display_environment(config),
        "dolphin",
        "--new-window",
        "/e2e-images/dolphin",
    )
    assert result.returncode == 0, result.stderr
    time.sleep(2)
    client.click(client.width // 2, client.height // 2)
    # Copy after app startup/cleanup so a previous selection owner cannot race
    # this paste; restored history can still include the retired ownership MIME.
    host_probe.set(
        {**payload, "application/x-plasma6-clipboard-owner": b"retired-owner"}
    )
    inner_probe.wait(payload)
    client.chord(0xFFE3, ord("v"))
    time.sleep(1)
    client.screenshot().save(case / "06-dolphin-paste-dialog.png")
    # Accept the suggested name and default format, just like a normal paste.
    # Editing the extension can change KIO's selected format and hide this bug.
    client.key(0xFF0D, True)
    client.key(0xFF0D, False)
    deadline = time.monotonic() + 10
    while not any(
        path.is_file() and not path.name.startswith(".")
        for path in destination.iterdir()
    ):
        assert time.monotonic() < deadline, "Dolphin did not create the pasted file"
        time.sleep(0.1)
    output = next(
        path
        for path in destination.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )
    assert output.name == "Dolphin screenshot.png", output.name
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), (
        f"Dolphin saved {output.stat().st_size} bytes of non-PNG clipboard data"
    )
    with Image.open(output) as image:
        image.verify()
    actual = Image.open(output).convert("RGBA")
    expected = expected_image(publisher=True)
    assert actual.size == expected.size and actual.tobytes() == expected.tobytes(), (
        "Dolphin changed the image pixels or alpha"
    )
    client.screenshot().save(case / "07-dolphin-pasted-file.png")
    result = run(
        runtime,
        "exec",
        "-d",
        "--user=plasma",
        inner,
        "/bin/bash",
        "-c",
        'exec "$@" > /e2e-images/gwenview.log 2>&1',
        "clipboard-gwenview",
        "env",
        *display_environment(config),
        "gwenview",
        "--fullscreen",
        "/e2e-images/dolphin/Dolphin screenshot.png",
    )
    assert result.returncode == 0, result.stderr
    colors = ((210, 100, 180), (20, 180, 90), (40, 90, 220))
    deadline = time.monotonic() + 20
    while True:
        screenshot = client.screenshot()
        samples = screenshot.resize((160, 100), Image.Resampling.NEAREST).getcolors(
            16000
        )
        assert samples is not None
        counts = [
            sum(
                count
                for count, pixel in samples
                if max(abs(a - b) for a, b in zip(pixel, color)) <= 10
            )
            for color in colors
        ]
        if min(counts) >= 300:
            break
        assert time.monotonic() < deadline, (
            f"Gwenview did not display the pasted image: {counts}"
        )
        time.sleep(0.25)
    screenshot.save(case / "08-gwenview-opened-image.png")
    (case / "dolphin-image.json").write_text(
        json.dumps(
            {
                "filename": output.name,
                "bytes": output.stat().st_size,
                "dimensions": list(actual.size),
                "pixels_and_alpha_equal": True,
                "gwenview_color_samples": counts,
            },
            indent=2,
        )
        + "\n"
    )


def launch_checked(case, label, *arguments, **settings):
    result = launch(*arguments, **settings)
    (case / f"{label}-run.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr
    wait_ready(arguments[0], arguments[2])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="plasma6:ui-test")
    parser.add_argument(
        "--host-image", help="Use a separate UI-test image for the isolated parent"
    )
    parser.add_argument("--runtime", choices=("docker", "podman"), default="docker")
    parser.add_argument("--backends", nargs="+", choices=("wayland", "x11"))
    parser.add_argument("--host-backends", nargs="+", choices=("wayland", "x11"))
    parser.add_argument("--kiosk", action="store_true")
    parser.add_argument(
        "--no-gpu",
        action="store_true",
        help="Exercise software rendering as on CI runners",
    )
    options = parser.parse_args()
    runtime = options.runtime
    supported = available_backends(runtime, options.image)
    backends = options.backends or supported
    host_image = options.host_image or options.image
    hosts = options.host_backends or ("wayland", "x11")
    artifacts = (
        Path(__file__).resolve().parent
        / ".artifacts"
        / f"clipboard-{runtime}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    )
    artifacts.mkdir(parents=True)
    failures = []
    for host in hosts:
        for backend in backends:
            label = f"{backend}-on-{host}" + ("-kiosk" if options.kiosk else "")
            case = artifacts / label
            case.mkdir()
            outer = f"plasma6-clip-host-{os.getpid()}-{label}"
            inner = f"plasma6-clip-inner-{os.getpid()}-{label}"
            probes = []
            client = None
            parent_client = None
            report = {
                "runtime": runtime,
                "image": options.image,
                "host_image": host_image,
                "gpu_hidden": options.no_gpu,
                "backend": backend,
                "host": host,
                "checks": {},
            }
            try:
                host_runtime, host_x11 = case / "runtime", case / "x11"
                host_runtime.mkdir(mode=0o700)
                host_x11.mkdir(mode=0o1777)
                output = case / "typed.txt"
                output.touch(mode=0o600)
                (case / "images").mkdir(mode=0o700)
                common = [
                    "-e",
                    "SYSTEMD_MASKED=NetworkManager.service,systemd-udev-trigger.service",
                ]
                if options.no_gpu:
                    common += software_options(runtime)
                launch_checked(
                    case,
                    "host",
                    runtime,
                    host_image,
                    outer,
                    "wayland",
                    "vnc",
                    *common,
                    "--mount",
                    f"type=bind,source={host_runtime},target=/run/plasma",
                    "--mount",
                    f"type=bind,source={host_x11},target=/tmp/.X11-unix",
                    DISPLAY_WIDTH="1280",
                    DISPLAY_HEIGHT="900",
                )
                # KRFB creates the virtual parent output when a client connects.
                # Keep it alive even when UI screenshots use the child's X11.
                address = run(runtime, "port", outer, "5900/tcp").stdout.strip()
                deadline = time.monotonic() + 30
                while parent_client is None:
                    try:
                        parent_client = NestedClient(int(address.rsplit(":", 1)[1]))
                    except (OSError, RuntimeError):
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.25)
                host_config = configuration(runtime, outer)
                if host == "x11":
                    # Use a real Xwayland parent with DRI3, not Xvfb's limited
                    # EGL capabilities; Arch's KWin requires OpenGL here.
                    query = (
                        "from pathlib import Path; import json; "
                        + "\nfor p in Path('/proc').glob('[0-9]*'):\n try:\n  if (p/'comm').read_text().strip() == 'Xwayland':\n   args=(p/'cmdline').read_bytes().decode().split('\\0'); print(json.dumps({'DISPLAY': next(a for a in args if a.startswith(':')), 'XAUTHORITY': args[args.index('-auth')+1]})); break\n except FileNotFoundError: pass"
                    )
                    result = run(runtime, "exec", outer, "python3", "-c", query)
                    assert result.returncode == 0, result.stderr
                    host_config.update(json.loads(result.stdout))
                    host_config.update(DISPLAY_BACKEND="x11", QT_QPA_PLATFORM="xcb")
                mounts = []
                if host == "wayland":
                    mounts += [
                        "--mount",
                        f"type=bind,source={host_runtime}/wayland-0,target=/run/host/wayland,readonly",
                        "-e",
                        "HOST_WAYLAND_DISPLAY=/run/host/wayland",
                    ]
                else:
                    cookie = subprocess.run(
                        [runtime, "exec", outer, "cat", host_config["XAUTHORITY"]],
                        capture_output=True,
                        check=True,
                    ).stdout
                    auth = case / "Xauthority"
                    auth.write_bytes(cookie)
                    auth.chmod(0o600)
                    mounts += [
                        "--mount",
                        f"type=bind,source={host_x11},target=/run/host/X11,readonly",
                        "--mount",
                        f"type=bind,source={auth},target=/run/host/Xauthority,readonly",
                        "-e",
                        f"HOST_DISPLAY={host_config['DISPLAY']}",
                        "-e",
                        "HOST_XAUTHORITY=/run/host/Xauthority",
                    ]
                private_capture = backend == "x11" and host == "wayland"
                capture_options = ["-p", "127.0.0.1::5900"] if private_capture else []
                # Explicit mounts point at this test's desktop, excluding the real host.
                launch_checked(
                    case,
                    "inner",
                    runtime,
                    options.image,
                    inner,
                    backend,
                    "nested",
                    *common,
                    *mounts,
                    *capture_options,
                    "--mount",
                    f"type=bind,source={output},target=/e2e-output/typed.txt",
                    "--mount",
                    f"type=bind,source={case / 'images'},target=/e2e-images",
                    "--mount",
                    f"type=bind,source={Path(__file__).with_name('clipboard-browser.py')},target=/e2e-clipboard-browser.py,readonly",
                    HOST_DISPLAY_BACKEND="wayland",
                    WAYLAND_DISPLAY="/nonexistent-clipboard-test-socket",
                    TARGET_APP="plasma-ui-fixture /e2e-output/typed.txt"
                    if options.kiosk
                    else "",
                )
                config = configuration(runtime, inner)
                for name in (outer, inner):
                    run(runtime, "exec", name, "pkill", "-x", "plasma-welcome")
                assert config["CLIPBOARD_SYNC"] == "1", config
                host_probe = Probe(runtime, outer, host_config, case / "host-probe.log")
                inner_probe = Probe(runtime, inner, config, case / "inner-probe.log")
                probes += [host_probe, inner_probe]
                time.sleep(1)
                for source, destination, direction in (
                    (host_probe, inner_probe, "host-to-container"),
                    (inner_probe, host_probe, "container-to-host"),
                ):
                    destination.drain()
                    payload = clipboard_payload(direction + " " + label)
                    source.set(payload)
                    destination.wait(payload)
                    report["checks"][direction] = True
                    payload = {"text/plain": f"primary {direction} {label}".encode()}
                    source.set(payload, mode=1)
                    destination.wait(payload, mode=1)
                    report["checks"]["primary-" + direction] = True
                restarted = run(
                    runtime,
                    "exec",
                    inner,
                    "systemctl",
                    "restart",
                    "plasma-clipboard.service",
                )
                assert restarted.returncode == 0, restarted.stderr
                time.sleep(1)
                payload = {"text/plain": f"After restart {label}".encode()}
                host_probe.set(payload)
                inner_probe.wait(payload)
                report["checks"]["service-restart"] = True
                if not options.kiosk:
                    result = run(
                        runtime,
                        "exec",
                        "-d",
                        "--user=plasma",
                        inner,
                        "env",
                        *display_environment(config),
                        "plasma-ui-fixture",
                        "/e2e-output/typed.txt",
                    )
                    assert result.returncode == 0, result.stderr
                capture = outer
                if private_capture:
                    # Rootful Xwayland can outgrow the synthetic parent's view.
                    # Its private X11 capture still exercises the actual Qt UI.
                    command = [
                        "systemd-run",
                        "--quiet",
                        "--unit=clipboard-test-vnc",
                        "--property=User=plasma",
                        "--property=EnvironmentFile=/etc/plasma/session.env",
                        "/usr/bin/x11vnc",
                        "-display",
                        config["DISPLAY"],
                        "-auth",
                        config["XAUTHORITY"],
                        "-rfbport",
                        "5900",
                        "-passwd",
                        "testpass",
                        "-forever",
                        "-shared",
                        # This server captures input/frames, not clipboard data.
                        "-nosel",
                        "-noxdamage",
                    ]
                    result = run(runtime, "exec", inner, *command)
                    assert result.returncode == 0, result.stderr
                    capture = inner
                report["capture"] = (
                    "private-x11" if private_capture else "parent-window"
                )
                if not private_capture:
                    client = parent_client
                address = run(runtime, "port", capture, "5900/tcp").stdout.strip()
                deadline = time.monotonic() + 30
                while client is None:
                    try:
                        client = NestedClient(int(address.rsplit(":", 1)[1]))
                    except (OSError, RuntimeError):
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.25)
                while True:
                    screenshot = client.screenshot()
                    box = banner_box(screenshot)
                    if box:
                        break
                    if time.monotonic() >= deadline:
                        screenshot.save(case / "setup-failure.png")
                        raise AssertionError("Clipboard UI fixture did not appear")
                    time.sleep(0.25)
                time.sleep(0.5)
                screenshot.save(case / "01-before-paste.png")
                expected = "Host clipboard → container UI: Καλημέρα 🌍\n"
                payload = {"text/plain": expected.encode()}
                host_probe.set(payload)
                inner_probe.wait(payload)
                client.click(box[0] + 35, box[3] + 35)
                time.sleep(0.25)
                client.chord(0xFFE3, ord("v"))
                client.chord(0xFFE3, ord("s"))
                deadline = time.monotonic() + 10
                while output.read_text() != expected:
                    assert time.monotonic() < deadline, output.read_text()
                    time.sleep(0.1)
                client.screenshot().save(case / "02-pasted-and-saved.png")
                report["checks"]["gui-paste-and-host-file-save"] = True
                # Mixed-case keyboard input is covered by ui.py; this checks copying.
                expected = f"container gui copy to host {label} az09 0123"
                client.chord(0xFFE3, ord("a"))
                client.text(expected)
                host_probe.drain()
                client.chord(0xFFE3, ord("a"))
                client.chord(0xFFE3, ord("c"))
                host_probe.wait({"text/plain": expected.encode()})
                client.screenshot().save(case / "03-copied-to-host.png")
                report["checks"]["gui-copy-to-host"] = True
                image_checks(
                    runtime,
                    outer,
                    inner,
                    host_config,
                    config,
                    case,
                    client,
                    parent_client,
                    host_probe,
                    inner_probe,
                )
                report["checks"]["qt-4k-image-both-directions"] = True
                report["checks"]["gui-image-paste-and-host-file-save"] = True
                browser_image_check(
                    runtime, inner, config, case, client, host_probe, inner_probe
                )
                report["checks"]["chromium-image-paste-and-host-file-save"] = True
                dolphin_image_check(
                    runtime, inner, config, case, client, host_probe, inner_probe
                )
                report["checks"]["dolphin-png-file-and-filename"] = True
                report["checks"]["gwenview-opens-pasted-image"] = True
                restored = {
                    "text/plain": f"Restored clipboard history: {label}".encode(),
                    "application/x-plasma6-clipboard-owner": b"retired-owner",
                    "application/x-kde-onlyReplaceEmpty": b"1",
                }
                host_probe.set(restored)
                inner_probe.wait({"text/plain": restored["text/plain"]})
                assert (
                    "application/x-plasma6-clipboard-owner"
                    not in inner_probe.latest[0]["data"]
                )
                report["checks"]["clipboard-history-restore"] = True
                time.sleep(0.5)
                assert host_probe.drain() < 10 and inner_probe.drain() < 10, (
                    "Clipboard feedback loop"
                )
                report["checks"]["no-feedback-loop"] = True
                # Disconnecting the parent's last VNC client can remove its
                # virtual output; record the live renderer before teardown.
                renderer = run(runtime, *renderer_command(inner))
                (case / "renderer-active.log").write_text(
                    renderer.stdout + renderer.stderr
                )
                assert renderer.returncode == 0, renderer.stderr
                report["renderer"] = [
                    line
                    for line in renderer.stdout.splitlines()
                    if line.startswith(("Compositing Type:", "OpenGL renderer string:"))
                ]
                health = run(runtime, "exec", inner, "plasma-healthcheck")
                assert health.returncode == 0, health.stdout + health.stderr
                report["checks"]["healthy-after-clipboard-actions"] = True
                print(f"PASS {label}: {report['checks']}", flush=True)
            except (
                AssertionError,
                RuntimeError,
                OSError,
                ValueError,
                KeyError,
                subprocess.SubprocessError,
            ):
                failures.append(label)
                report["failure"] = traceback.format_exc()
                if client:
                    with contextlib.suppress(OSError, RuntimeError):
                        client.screenshot().save(case / "failure.png")
                print(f"FAIL {label}: {report['failure']}", flush=True)
            finally:
                if client:
                    client.close()
                if parent_client and parent_client is not client:
                    parent_client.close()
                for probe in probes:
                    probe.close()
                (case / "result.json").write_text(json.dumps(report, indent=2))
                for name, directory in ((inner, "container"), (outer, "host")):
                    destination = case / directory
                    destination.mkdir()
                    collect_artifacts(
                        runtime,
                        name,
                        destination,
                        services=("clipboard", "session", "vnc"),
                    )
    print(f"Artifacts: {artifacts}", flush=True)
    if failures:
        raise SystemExit("Failed: " + ", ".join(failures))


if __name__ == "__main__":
    main()
