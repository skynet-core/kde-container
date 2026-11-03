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
import uuid
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw
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


def wait_dolphin(runtime, inner, config, case):
    # Detached exec acknowledges process launch, not its active application window.
    tag = "CLIPBOARD_DOLPHIN_" + uuid.uuid4().hex
    script = "/run/plasma/" + tag + ".js"
    body = """function snapshot() {
    const w = workspace.activeWindow;
    console.warn(TAG + ' ' + JSON.stringify(w ? {
        pid:w.pid, normal:w.normalWindow, active:w.active,
        minimized:w.minimized, hidden:w.hidden,
        frame:{x:w.frameGeometry.x,y:w.frameGeometry.y,
               width:w.frameGeometry.width,height:w.frameGeometry.height}
    } : null));
}
function watch(w) {
    w.frameGeometryChanged.connect(snapshot);
    w.minimizedChanged.connect(snapshot);
    w.hiddenChanged.connect(snapshot);
}
workspace.stackingOrder.forEach(watch);
workspace.windowAdded.connect(function(w) { watch(w); snapshot(); });
workspace.windowActivated.connect(snapshot);
snapshot();
""".replace("TAG", json.dumps(tag))

    def command(*arguments):
        result = run(runtime, "exec", inner, *arguments, timeout=5)
        assert result.returncode == 0, result.stderr
        return result.stdout

    def dbus(*arguments):
        result = run(
            runtime,
            "exec",
            "--user=plasma",
            inner,
            "env",
            *display_environment(config),
            "QT_QPA_PLATFORM=offscreen",
            "qdbus-qt6",
            "org.kde.KWin",
            *arguments,
            timeout=5,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    command(
        "python3",
        "-c",
        "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])",
        script,
        body,
    )
    deadline = time.monotonic() + 20
    try:
        identifier = int(dbus("/Scripting", "loadScript", script, tag).strip())
        assert identifier >= 0, "Dolphin readiness script failed to load"
        dbus(f"/Scripting/Script{identifier}", "run")
        while True:
            journal = run(
                runtime,
                "exec",
                inner,
                "journalctl",
                "-u",
                "plasma-session.service",
                "--no-pager",
                "-o",
                "cat",
                "-g",
                tag,
                timeout=5,
            )
            assert journal.returncode == 0 or (
                journal.returncode == 1 and not journal.stdout and not journal.stderr
            ), journal.stderr
            lines = [
                line.split(tag + " ", 1)[1]
                for line in journal.stdout.splitlines()
                if tag + " " in line
            ]
            window = json.loads(lines[-1]) if lines else None
            if (
                window
                and window["normal"] is True
                and window["active"] is True
                and window["minimized"] is False
                and window["hidden"] is False
                and window["frame"]["width"] > 0
                and window["frame"]["height"] > 0
                and type(window["pid"]) is int
                and window["pid"] > 0
            ):
                process = run(
                    runtime,
                    "exec",
                    inner,
                    "python3",
                    "-c",
                    "from pathlib import Path; import json,sys; p=Path('/proc')/sys.argv[1]; "
                    "print(json.dumps({'argv':p.joinpath('cmdline').read_bytes().decode().split(chr(0))[:-1],"
                    "'state':p.joinpath('stat').read_text().rsplit(')',1)[1].split()[0]}))",
                    str(window["pid"]),
                    timeout=5,
                )
                if process.returncode == 0:
                    identity = json.loads(process.stdout)
                    argv = identity["argv"]
                    if (
                        identity["state"] != "Z"
                        and argv
                        and Path(argv[0]).name == "dolphin"
                        and "--new-window" in argv
                        and "/e2e-images/dolphin" in argv
                    ):
                        (case / "dolphin-ready.json").write_text(
                            json.dumps(
                                {"window": window, "process": identity}, indent=2
                            )
                            + "\n"
                        )
                        return
            assert time.monotonic() < deadline, (
                f"Dolphin did not become the active application window: {window}"
            )
            time.sleep(0.1)
    finally:
        try:
            dbus("/Scripting", "unloadScript", tag)
        finally:
            command("rm", "-f", script)


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
    wait_dolphin(runtime, inner, config, case)
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


def nested_kwin_state(runtime, name, config, case, body=""):
    """Observe only a disposable compositor; mutations are explicit setup scripts."""
    tag = "NESTED_WINDOW_" + uuid.uuid4().hex
    script = "/run/plasma/" + tag + ".js"
    source = """function rect(r) { return {x:r.x,y:r.y,width:r.width,height:r.height}; }
const windows = workspace.stackingOrder.filter(w => w.normalWindow);
BODY
console.warn(TAG + ' ' + JSON.stringify({
    outputs:workspace.screens.map(o=>({name:o.name,scale:o.devicePixelRatio,geometry:rect(o.geometry)})),
    cursor:{x:workspace.cursorPos.x,y:workspace.cursorPos.y},
    windows:windows.map(w=>({id:w.internalId.toString(),caption:w.caption,
        frame:rect(w.frameGeometry),client:rect(w.clientGeometry),
        fullScreen:w.fullScreen,noBorder:w.noBorder}))
}));
""".replace("BODY", body).replace("TAG", json.dumps(tag))

    def dbus(*arguments):
        result = run(
            runtime,
            "exec",
            "--user=plasma",
            name,
            "env",
            *display_environment(config),
            "QT_QPA_PLATFORM=offscreen",
            "qdbus-qt6",
            "org.kde.KWin",
            *arguments,
            timeout=5,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    result = run(
        runtime,
        "exec",
        name,
        "python3",
        "-c",
        "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])",
        script,
        source,
    )
    assert result.returncode == 0, result.stderr
    try:
        identifier = int(dbus("/Scripting", "loadScript", script, tag).strip())
        assert identifier >= 0, "Nested window script did not load"
        dbus(f"/Scripting/Script{identifier}", "run")
        deadline = time.monotonic() + 5
        while True:
            result = run(
                runtime,
                "exec",
                name,
                "journalctl",
                "-u",
                "plasma-session.service",
                "--no-pager",
                "-o",
                "cat",
                "-g",
                tag,
                timeout=5,
            )
            lines = [
                line.split(tag + " ", 1)[1]
                for line in result.stdout.splitlines()
                if tag + " " in line
            ]
            if lines:
                state = json.loads(lines[-1])
                with (case / "kwin-state.jsonl").open("a") as log:
                    log.write(
                        json.dumps({"container": name, "setup": body, **state}) + "\n"
                    )
                return state
            assert time.monotonic() < deadline, (
                "Nested compositor did not report its window/output state"
            )
            time.sleep(0.1)
    finally:
        try:
            dbus("/Scripting", "unloadScript", tag)
        finally:
            run(runtime, "exec", name, "rm", "-f", script)


def frontend_pointer(runtime, name, config):
    """Read the private frontend's physical endpoint without generating input."""
    source = """import ctypes as c,json
x=c.CDLL('libX11.so.6');p=c.c_void_p;u=c.c_ulong;i=c.c_int
x.XOpenDisplay.argtypes=[c.c_char_p];x.XOpenDisplay.restype=p
x.XDefaultRootWindow.argtypes=[p];x.XDefaultRootWindow.restype=u
x.XDefaultScreen.argtypes=[p];x.XDefaultScreen.restype=i
x.XQueryPointer.argtypes=[p,u]+[c.POINTER(u)]*2+[c.POINTER(i)]*4+[c.POINTER(c.c_uint)]
x.XDisplayWidth.argtypes=[p,i];x.XDisplayHeight.argtypes=[p,i]
x.XCloseDisplay.argtypes=[p]
d=x.XOpenDisplay(None);assert d,'Private frontend display is unavailable'
try:
 root=x.XDefaultRootWindow(d);screen=x.XDefaultScreen(d)
 r,child=u(),u();rx,ry,wx,wy=i(),i(),i(),i();mask=c.c_uint()
 assert x.XQueryPointer(d,root,c.byref(r),c.byref(child),c.byref(rx),c.byref(ry),c.byref(wx),c.byref(wy),c.byref(mask)),'Private frontend pointer is unavailable'
 print(json.dumps({'position':[rx.value,ry.value],'pixels':[x.XDisplayWidth(d,screen),x.XDisplayHeight(d,screen)]}))
finally:x.XCloseDisplay(d)
"""
    result = run(
        runtime,
        "exec",
        "--user=plasma",
        name,
        "env",
        "DISPLAY=" + config["PLASMA_SOFTWARE_DISPLAY"],
        "XAUTHORITY=/etc/plasma/Xauthority",
        "python3",
        "-c",
        source,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def nested_window_phases(runtime, image, host_image, case, common, *, no_gpu=False):
    """Cold scale, SSD and real drag/resize/input through the outer host window."""
    directory = case / "outer-window"
    directory.mkdir()
    host_runtime = directory / "runtime"
    host_runtime.mkdir(mode=0o700)
    host_x11 = directory / "x11"
    host_x11.mkdir(mode=0o1777)
    parent = f"plasma6-window-host-{os.getpid()}"
    client = None
    reports = []
    try:
        launch_checked(
            directory,
            "host",
            runtime,
            host_image,
            parent,
            "wayland",
            "vnc",
            *common,
            "--mount",
            f"type=bind,source={host_runtime},target=/run/plasma",
            "--mount",
            f"type=bind,source={host_x11},target=/tmp/.X11-unix",
            DISPLAY_WIDTH="3840",
            DISPLAY_HEIGHT="2160",
        )
        address = run(runtime, "port", parent, "5900/tcp").stdout.strip()
        deadline = time.monotonic() + 30
        while client is None:
            try:
                client = NestedClient(int(address.rsplit(":", 1)[1]))
            except (OSError, RuntimeError):
                assert time.monotonic() < deadline, (
                    "Nested parent RFB did not become ready"
                )
                time.sleep(0.25)
        host_config = configuration(runtime, parent)

        def observe(name, config, phase, predicate, *, description="window/output"):
            deadline = time.monotonic() + 20
            while True:
                state = nested_kwin_state(runtime, name, config, phase)
                if predicate(state):
                    return state
                assert time.monotonic() < deadline, (
                    f"Nested {description} did not acknowledge state: {state}"
                )
                time.sleep(0.1)

        def frontend_windows(state):
            caption = "Xwayland on " + config["PLASMA_SOFTWARE_DISPLAY"]
            return [
                window for window in state["windows"] if window["caption"] == caption
            ]

        def only_window(state):
            windows = frontend_windows(state)
            assert len(windows) == 1, "Expected one matching private nested frontend"
            return windows[0]

        def only_output(state):
            assert len(state["outputs"]) == 1, "Expected one active output"
            return state["outputs"][0]

        def screenshot(phase, label, scale, window):
            deadline = time.monotonic() + 20
            while True:
                picture = client.screenshot()
                origin = only_output(parent_state)["geometry"]
                area = window["client"]
                left = round((area["x"] - origin["x"]) * scale)
                top = round((area["y"] - origin["y"]) * scale)
                image = picture.crop(
                    (
                        left,
                        top,
                        left + round(area["width"] * scale),
                        top + round(area["height"] * scale),
                    )
                )
                banner = banner_box(image)
                difference = ImageChops.difference(
                    image, Image.new("RGB", image.size, (36, 88, 180))
                )
                red, green, blue = difference.split()
                maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
                save = maximum.point(lambda value: 255 if value <= 3 else 0).getbbox()
                if banner and save and abs(banner[3] - banner[1] - 44 * scale) <= 1:
                    picture.save(phase / (label + ".png"))

                    def absolute(box, left=left, top=top):
                        return (
                            box[0] + left,
                            box[1] + top,
                            box[2] + left,
                            box[3] + top,
                        )

                    return picture, absolute(banner), absolute(save)
                assert time.monotonic() < deadline, (
                    f"Scaled Qt fixture did not paint at {scale}: banner={banner}, save={save}"
                )
                time.sleep(0.1)

        for scale in (1, 1.25, 2):
            phase = directory / f"scale-{scale * 100:g}"
            phase.mkdir()
            output = phase / "typed.txt"
            output.touch(mode=0o600)
            inner = f"plasma6-window-inner-{os.getpid()}-{scale * 100:g}"
            report = {"scale": scale, "passed": False}
            try:
                parent_state = nested_kwin_state(runtime, parent, host_config, phase)
                output_name = only_output(parent_state)["name"]
                result = run(
                    runtime,
                    "exec",
                    "--user=plasma",
                    parent,
                    "env",
                    *display_environment(host_config),
                    "kscreen-doctor",
                    f"output.{output_name}.scale.{scale:g}",
                )
                assert result.returncode == 0, result.stderr
                parent_state = observe(
                    parent,
                    host_config,
                    phase,
                    lambda state, scale=scale: (
                        abs(only_output(state)["scale"] - scale) < 1e-6
                    ),
                )
                report["parent_output"] = only_output(parent_state)
                launch_checked(
                    phase,
                    "inner",
                    runtime,
                    image,
                    inner,
                    "wayland",
                    "nested",
                    *common,
                    "--mount",
                    f"type=bind,source={host_runtime}/wayland-0,target=/run/host/wayland,readonly",
                    "-e",
                    "HOST_WAYLAND_DISPLAY=/run/host/wayland",
                    "--mount",
                    f"type=bind,source={output},target=/e2e-output/typed.txt",
                    HOST_DISPLAY_BACKEND="wayland",
                    WAYLAND_DISPLAY="/nonexistent-window-test-socket",
                    TARGET_APP="plasma-ui-fixture /e2e-output/typed.txt",
                )
                config = configuration(runtime, inner)
                # This regression targets the modern virtual-output kiosk relay.
                assert config.get("PLASMA_SOFTWARE_CAPTURE") == "0", (
                    "Expected the modern kiosk output path"
                )
                renderer = run(runtime, *renderer_command(inner))
                (phase / "renderer-active.log").write_text(
                    renderer.stdout + renderer.stderr
                )
                assert renderer.returncode == 0, renderer.stderr
                report["renderer"] = [
                    line
                    for line in renderer.stdout.splitlines()
                    if line.startswith(("Compositing Type:", "OpenGL renderer string:"))
                ]
                gpu = run(runtime, "exec", inner, "cat", "/etc/plasma/gpu.json")
                assert gpu.returncode == 0, gpu.stderr
                report["gpu"] = json.loads(gpu.stdout)
                selected = report["gpu"].get("selected") or {}
                software_renderer = any(
                    name in "\n".join(report["renderer"]).lower()
                    for name in (
                        "qpainter",
                        "llvmpipe",
                        "softpipe",
                        "swrast",
                        "swiftshader",
                    )
                )
                report["nvidia_renderer"] = any(
                    line.startswith("OpenGL renderer string:")
                    and "NVIDIA" in line.upper()
                    for line in report["renderer"]
                )
                if no_gpu:
                    assert software_renderer, report["renderer"]
                    report["software_renderer"] = True
                else:
                    assert (
                        selected.get("hardware") is True
                        and not software_renderer
                        and any(
                            line.startswith("OpenGL renderer string:")
                            and line.partition(":")[2].strip()
                            for line in report["renderer"]
                        )
                    ), (
                        f"Expected an actual hardware renderer in the cold child: {report['renderer']}"
                    )
                    if selected.get("vendor", "").startswith("NVIDIA"):
                        assert report["nvidia_renderer"], report["renderer"]
                state = observe(
                    parent,
                    host_config,
                    phase,
                    lambda value: len(frontend_windows(value)) == 1,
                )
                initial = only_window(state)
                report["initial"] = initial
                report["initial_parent_output"] = only_output(state)
                frame, client_area = initial["frame"], initial["client"]
                host = report["initial_parent_output"]["geometry"]
                tolerance = 1 / scale + 1e-6
                report["initial_frame_must_fit"] = all(
                    int(config[setting]) + frame[extent] - client_area[extent]
                    <= host[extent] + tolerance
                    for setting, extent in (
                        ("DISPLAY_WIDTH", "width"),
                        ("DISPLAY_HEIGHT", "height"),
                    )
                )
                if report["initial_frame_must_fit"]:
                    assert all(
                        host[axis] - tolerance <= frame[axis]
                        and frame[axis] + frame[extent]
                        <= host[axis] + host[extent] + tolerance
                        for axis, extent in (("x", "width"), ("y", "height"))
                    ), (
                        f"Cold nested initial frame is outside the host output: {initial}"
                    )
                identifier = only_window(state)["id"]
                select = (
                    "const w=windows.find(w=>w.internalId.toString()==="
                    + json.dumps(identifier)
                    + ");if(!w)throw Error('Nested frontend changed');"
                )
                nested_kwin_state(
                    runtime,
                    parent,
                    host_config,
                    phase,
                    select
                    + "w.fullScreen=false;w.setMaximize(false,false);w.noBorder=false;",
                )
                state = observe(
                    parent,
                    host_config,
                    phase,
                    lambda value: (
                        not only_window(value)["fullScreen"]
                        and not only_window(value)["noBorder"]
                    ),
                )
                frame = {**only_window(state)["frame"], "x": 80, "y": 60}
                nested_kwin_state(
                    runtime,
                    parent,
                    host_config,
                    phase,
                    select
                    + "w.frameGeometry="
                    + json.dumps(frame)
                    + ";workspace.activeWindow=w;",
                )

                def frame_is(
                    state, expected, identifier=identifier, tolerance=tolerance
                ):
                    window = only_window(state)
                    assert window["id"] == identifier, (
                        "Nested frontend changed during gesture"
                    )
                    return all(
                        abs(window["frame"][key] - value) <= tolerance
                        for key, value in expected.items()
                    )

                state = observe(
                    parent,
                    host_config,
                    phase,
                    lambda value, frame=frame: frame_is(value, frame),
                )
                window = only_window(state)
                assert (
                    window["client"]["y"] > window["frame"]["y"]
                    and window["frame"]["height"] > window["client"]["height"]
                ), "Nested frontend has no actual server decoration"
                report["placed"] = window
                child_state = observe(
                    inner,
                    config,
                    phase,
                    lambda value, scale=scale: (
                        abs(only_output(value)["scale"] - scale) < 1e-6
                    ),
                )
                child_output = only_output(child_state)
                assert (
                    abs(child_output["geometry"]["width"] - 1024) <= tolerance
                    and abs(child_output["geometry"]["height"] - 768) <= tolerance
                ), "Cold child logical output changed its configured size"
                report["child_output_before"] = child_output
                _, before, _ = screenshot(phase, "01-placed", scale, window)
                origin = only_output(parent_state)["geometry"]

                def physical(x, y, origin=origin, scale=scale):
                    return (
                        round((x - origin["x"]) * scale),
                        round((y - origin["y"]) * scale),
                    )

                # A fresh surface enter must already use the known host scale.
                # A second in-surface motion would hide the enter-only regression.
                outside = physical(frame["x"] - 20, frame["y"] - 20)
                client.pointer(*outside)
                observe(
                    parent,
                    host_config,
                    phase,
                    lambda value, frame=frame, tolerance=tolerance: all(
                        abs(value["cursor"][axis] - (frame[axis] - 20)) <= tolerance
                        for axis in ("x", "y")
                    ),
                    description="outside pointer",
                )
                target = {
                    "x": child_output["geometry"]["x"] + 128,
                    "y": child_output["geometry"]["y"] + 96,
                }
                entry = physical(
                    window["client"]["x"] + 128, window["client"]["y"] + 96
                )
                report["pointer_entry"] = {
                    "outside_parent_physical": outside,
                    "entry_parent_physical": entry,
                    "expected_child_logical": target,
                    "physical_tolerance": 1,
                    "arithmetic_epsilon": 1e-6,
                    "entry_events": 1,
                }
                requested_frontend = [
                    entry[index] - (window["client"][axis] - origin[axis]) * scale
                    for index, axis in enumerate(("x", "y"))
                ]
                report["pointer_entry"]["requested_frontend_physical"] = (
                    requested_frontend
                )
                client.pointer(*entry)

                def endpoint_reached(
                    value,
                    point_report=report["pointer_entry"],
                    inner=inner,
                    config=config,
                    child_output=child_output,
                    scale=scale,
                    requested_frontend=requested_frontend,
                ):
                    point_report["observed_child_logical"] = value["cursor"]
                    frontend = frontend_pointer(runtime, inner, config)
                    point_report["observed_frontend"] = frontend
                    assert frontend["pixels"] == [
                        round(child_output["geometry"][axis] * scale)
                        for axis in ("width", "height")
                    ], "Private frontend pixel dimensions changed"
                    # The frontend has integer physical coordinates; the child
                    # observer is QPoint, rounded from logical QPointF. Check
                    # each API in its own coordinate space without adding its
                    # rounding error to the one-physical-pixel transport limit.
                    expected_child = {}
                    for index, axis in enumerate(("x", "y")):
                        coordinate = (
                            child_output["geometry"][axis]
                            + frontend["position"][index] / scale
                        )
                        expected_child[axis] = int(
                            coordinate + (0.5 if coordinate >= 0 else -0.5)
                        )
                    point_report["expected_child_logical_integer"] = expected_child
                    return (
                        all(
                            abs(actual - requested) <= 1 + 1e-6
                            for actual, requested in zip(
                                frontend["position"], requested_frontend, strict=True
                            )
                        )
                        and value["cursor"] == expected_child
                    )

                observe(
                    inner,
                    config,
                    phase,
                    endpoint_reached,
                    description="first pointer entry",
                )
                # Probe a second, off-grid point without altering the strict
                # first-entry result. Expected values use requested pixels and
                # geometry, never the observed pointer or a fitted offset.
                pixels = (
                    round(child_output["geometry"]["width"] * scale),
                    round(child_output["geometry"]["height"] * scale),
                )
                offgrid_pixels = tuple(round(0.9 * (extent - 1)) for extent in pixels)
                offgrid = physical(
                    window["client"]["x"] + offgrid_pixels[0] / scale,
                    window["client"]["y"] + offgrid_pixels[1] / scale,
                )
                # Workspace::cursorPos is QPoint, backed by QPointF::toPoint().
                # Its nearest-integer conversion is part of the observer API.
                offgrid_expected = {}
                for index, axis in enumerate(("x", "y")):
                    coordinate = (
                        child_output["geometry"][axis]
                        + offgrid[index] / scale
                        + origin[axis]
                        - window["client"][axis]
                    )
                    offgrid_expected[axis] = int(
                        coordinate + (0.5 if coordinate >= 0 else -0.5)
                    )
                report["pointer_offgrid"] = {
                    "framebuffer_pixels": pixels,
                    "requested_local_pixels": offgrid_pixels,
                    "parent_physical": offgrid,
                    "requested_child_logical_integer": offgrid_expected,
                    "physical_tolerance": 1,
                    "arithmetic_epsilon": 1e-6,
                    "motion_events": 1,
                }
                offgrid_frontend = [
                    offgrid[index] - (window["client"][axis] - origin[axis]) * scale
                    for index, axis in enumerate(("x", "y"))
                ]
                report["pointer_offgrid"]["requested_frontend_physical"] = (
                    offgrid_frontend
                )
                client.pointer(*offgrid)

                def offgrid_reached(
                    value,
                    reached=endpoint_reached,
                    report=report,
                    requested_frontend=offgrid_frontend,
                ):
                    return reached(
                        value,
                        point_report=report["pointer_offgrid"],
                        requested_frontend=requested_frontend,
                    )

                observe(
                    inner,
                    config,
                    phase,
                    offgrid_reached,
                    description="off-grid pointer",
                )
                title = physical(
                    frame["x"] + frame["width"] / 2,
                    (frame["y"] + window["client"]["y"]) / 2,
                )
                client.drag(*title, round(40 * scale), round(20 * scale))
                moved = {**frame, "x": frame["x"] + 40, "y": frame["y"] + 20}
                state = observe(
                    parent,
                    host_config,
                    phase,
                    lambda value, moved=moved: frame_is(value, moved),
                )
                _, moved_banner, _ = screenshot(
                    phase, "02-moved", scale, only_window(state)
                )
                assert (
                    abs(moved_banner[0] - before[0] - 40 * scale) <= 2
                    and abs(moved_banner[1] - before[1] - 20 * scale) <= 2
                ), "Outer move did not move the rendered child"
                # Breeze resize-only input borders sit outside frameGeometry.
                edge = physical(
                    moved["x"] + moved["width"] + 1, moved["y"] + moved["height"] + 1
                )
                client.drag(*edge, round(60 * scale), round(30 * scale))
                resized = {
                    **moved,
                    "width": moved["width"] + 60,
                    "height": moved["height"] + 30,
                }
                state = observe(
                    parent,
                    host_config,
                    phase,
                    lambda value, resized=resized: frame_is(value, resized),
                )
                report["resized"] = only_window(state)
                after_output = only_output(
                    nested_kwin_state(runtime, inner, config, phase)
                )
                if config.get("PLASMA_SOFTWARE_NESTED") == "1":
                    assert child_output == after_output, (
                        "RemoteResize=0 relay unexpectedly resized the child output"
                    )
                else:
                    assert abs(after_output["scale"] - scale) < 1e-6
                    assert after_output["geometry"] != child_output["geometry"], (
                        "Native nested output did not follow the outer resize"
                    )
                report["child_output_after"] = after_output
                _, banner, save = screenshot(
                    phase, "03-resized", scale, only_window(state)
                )
                client.click((banner[0] + banner[2]) // 2, (banner[3] + save[1]) // 2)
                client.text(f"Outer {scale:g} AaZz 019!?")
                client.chord(0xFFE3, ord("s"))
                expected = f"Outer {scale:g} AaZz 019!?"
                deadline = time.monotonic() + 10
                while output.read_text() != expected:
                    assert time.monotonic() < deadline, (
                        "Resized Qt input/save did not reach its host file"
                    )
                    time.sleep(0.1)
                client.screenshot().save(phase / "04-input-saved.png")
                report.update(
                    passed=True,
                    application_scale=(banner[3] - banner[1]) / 44,
                    expected=expected,
                )
            except Exception:
                (phase / "failure.log").write_text(traceback.format_exc())
                raise
            finally:
                (phase / "result.json").write_text(json.dumps(report, indent=2) + "\n")
                collect_artifacts(
                    runtime, inner, phase, services=("session", "vnc", "nested-x11")
                )
            reports.append(report)
        return reports
    finally:
        try:
            if client:
                client.close()
        finally:
            collect_artifacts(runtime, parent, directory, services=("session", "vnc"))


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
    supported = available_backends(runtime, options.image, kiosk=options.kiosk)
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
                if options.kiosk and backend == "wayland" and host == "wayland":
                    report["outer_window"] = nested_window_phases(
                        runtime,
                        options.image,
                        host_image,
                        case,
                        common,
                        no_gpu=options.no_gpu,
                    )
                    assert len(report["outer_window"]) == 3
                    report["checks"]["cold-scale-ssd-resize-input"] = all(
                        phase["passed"] for phase in report["outer_window"]
                    )
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
                # The presenter's private relay already uses loopback port 5900.
                capture_options = ["-p", "127.0.0.1::5901"] if private_capture else []
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
                    HOST_DISPLAY_BACKEND=host,
                    WAYLAND_DISPLAY="/nonexistent-clipboard-test-socket",
                    TARGET_APP="plasma-ui-fixture /e2e-output/typed.txt"
                    if options.kiosk
                    else "",
                )
                config = configuration(runtime, inner)
                if config.get("PLASMA_SOFTWARE_NESTED") == "1":
                    listeners = run(
                        runtime,
                        "exec",
                        inner,
                        "python3",
                        "-c",
                        "import json; from pathlib import Path; "
                        "rows=[line.split() for name in ('tcp','tcp6') for line in Path('/proc/net',name).read_text().splitlines()[1:]]; "
                        "print(json.dumps([row[1].upper() for row in rows if row[3]=='0A' and row[1].split(':')[1].upper()=='170C']))",
                    )
                    (case / "software-relay-listeners.json").write_text(
                        listeners.stdout
                    )
                    assert listeners.returncode == 0, listeners.stderr
                    assert json.loads(listeners.stdout) == ["0100007F:170C"], (
                        listeners.stdout
                    )
                    assert not run(runtime, "port", inner, "5900/tcp").stdout.strip()
                    report["checks"]["software-relay-is-loopback-only"] = True
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
                        "5901",
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
                address = run(
                    runtime,
                    "port",
                    capture,
                    "5901/tcp" if private_capture else "5900/tcp",
                ).stdout.strip()
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
                if options.no_gpu:
                    assert any(
                        name in "\n".join(report["renderer"]).lower()
                        for name in (
                            "qpainter",
                            "llvmpipe",
                            "softpipe",
                            "swrast",
                            "swiftshader",
                        )
                    ), report["renderer"]
                    report["checks"]["software-renderer"] = True
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
