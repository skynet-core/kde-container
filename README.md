# Plasma 6 container

For a commented, diagram-led explanation of the project, read
**[How this project works: a beginner's technical guide](docs/README.md)**.
The guide covers Linux containers, image builds, boot and systemd, all display
paths, remote input, UID mapping, troubleshooting, and the UI regression tests.

Fedora 44 Plasma 6 desktop on
[`ghcr.io/skynet-core/systemd:fedora-44`](https://github.com/skynet-core/systemd).
Systemd runs as PID 1; the desktop, private D-Bus and remote-access services run as
`plasma`. Docker with a rootful daemon and rootless Podman on Linux/cgroup v2 are
supported. The commands below run containers directly, without a host launcher.

## Build

```bash
docker build -t plasma6:local .
# Or build into Podman's separate image store:
podman build --format docker --layers -t plasma6:local .
```

Podman's `--format docker` preserves the image health check. For an OCI import that
has lost its health metadata, add `--health-cmd=/usr/local/bin/plasma-healthcheck`.

## Display modes

| `DISPLAY_BACKEND` | `DISPLAY_MODE` | Default target | Display services |
| --- | --- | --- | --- |
| `wayland` | `nested` | `plasma-wayland-nested.target` | KWin in a host display window |
| `wayland` | `headless` | `plasma-wayland-headless.target` | KWin virtual framebuffer |
| `wayland` | `vnc` | `plasma-wayland-vnc.target` | KWin virtual monitor, PipeWire, WirePlumber, KRFB with KWin input |
| `wayland` | `web` | `plasma-wayland-web.target` | Wayland VNC services plus noVNC/websockify |
| `x11` | `nested` | `plasma-x11-nested.target` | Rootful Xwayland on a Wayland host, or Xephyr on an X11 host |
| `x11` | `headless` | `plasma-x11-headless.target` | Xvfb and KWin X11 |
| `x11` | `vnc` | `plasma-x11-vnc.target` | Xvfb, KWin X11 and x11vnc |
| `x11` | `web` | `plasma-x11-web.target` | X11 VNC services plus noVNC/websockify |

All modes start a full Plasma session and private session bus. Headless and nested
modes start no remote listener. Set `DISPLAY_BACKEND=x11` in any command below for
its X11 variant; the remote/headless examples use `wayland` explicitly.

`DISPLAY_BACKEND=auto` checks mounted Unix sockets, preferring Wayland over X11;
with neither it selects Wayland. Docker and Podman cannot mount host sockets from
inside the container, so nested mode needs the mounts shown below. If both host
socket types are mounted, Wayland has priority. Host transport and desktop backend
are independent: either desktop backend can nest on either host display.

## Docker commands

These commands keep PID 1 as root, use a private cgroup namespace, and allow enough
processes and shared memory for Plasma. Runtime `PLASMA_UID/GID` make the desktop
account match your user without rebuilding the image. Use a different container
name or stop the previous container before reusing a name.

### Headless

```bash
docker run -d --rm --name plasma6-headless \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=headless plasma6:local
```

### Nested on a Wayland host

The standard host variables `XDG_RUNTIME_DIR` and `WAYLAND_DISPLAY` identify the
socket. This example assumes `WAYLAND_DISPLAY` is a socket name such as `wayland-0`;
if it is an absolute path, use that path directly as the mount source.

```bash
docker run -d --rm --name plasma6-nested \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=auto -e DISPLAY_MODE=nested plasma6:local
```

Use `DISPLAY_BACKEND=x11` in the same command to nest a Plasma X11 session through
rootful Xwayland on the host's Wayland display.

### Nested on an X11 host

Mount the host socket directory and its authentication file. Set `XAUTHORITY` to
the active host cookie file if your session does not already export it.

```bash
docker run -d --rm --name plasma6-nested \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=auto -e DISPLAY_MODE=nested plasma6:local
```

Here `auto` selects X11. Set `DISPLAY_BACKEND=wayland` for KWin Wayland nested on
that X11 host. To expose both host transports for auto-detection, combine the
Wayland socket mount/environment with these X11 mounts/environment.

### VNC

First create `./vnc-password` containing your chosen 1–8 printable ASCII character
password and restrict its permissions with `chmod 600 ./vnc-password`. VNC has an
eight-character authentication limit; no default password is built into the image.

```bash
docker run -d --rm --name plasma6-vnc \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:local
```

Connect a VNC client to `127.0.0.1:5900`. Replace `DISPLAY_BACKEND=wayland` with
`DISPLAY_BACKEND=x11` for the X11 desktop. Mouse and keyboard control are supported
on both backends.

### Browser / noVNC

```bash
docker run -d --rm --name plasma6-web \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:local
```

Open `http://127.0.0.1:6080/vnc.html` and enter the VNC password. The browser sends
keyboard and pointer events through the same VNC input path. Only port 6080 needs
to be published for web mode. Use `DISPLAY_BACKEND=x11` for its X11 variant.

## Rootless Podman commands

Run these as your desktop user, without `sudo`. `--systemd=always` sets up systemd
mounts despite the shell entrypoint; `--user=0:0` keeps systemd as container root.
`--userns=keep-id` maps your host IDs into the container, and `--passwd=false`
prevents a synthetic host account from conflicting with the `plasma` account.

### Headless

```bash
podman run -d --rm --name plasma6-headless \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=headless plasma6:local
```

### Nested on a Wayland host

```bash
podman run -d --rm --name plasma6-nested \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=auto -e DISPLAY_MODE=nested plasma6:local
```

### Nested on an X11 host

```bash
podman run -d --rm --name plasma6-nested \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=auto -e DISPLAY_MODE=nested plasma6:local
```

As with Docker, either nested command accepts `DISPLAY_BACKEND=wayland|x11` to
choose the desktop backend independently of the host transport.

### VNC

```bash
podman run -d --rm --name plasma6-vnc \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:local
```

### Browser / noVNC

```bash
podman run -d --rm --name plasma6-web \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:local
```

The VNC endpoint is `127.0.0.1:5900`; the browser URL is
`http://127.0.0.1:6080/vnc.html`. Set `DISPLAY_BACKEND=x11` in either command for the
X11 variant.

## Host files, identities and operation

To edit host files, create a host directory and add a writable bind mount to any
run command, for example:

```bash
mkdir -p "$PWD/shared"
# Add this option before the image name:
# --mount "type=bind,source=$PWD/shared,target=/home/plasma/Shared"
```

The UID/GID and namespace options above let `plasma` write those files as your host
user. For a single existing host file, mount it directly at a container file path;
the UI regression suite uses a mode-0600 host file mounted at
`/e2e-output/typed.txt` and verifies its exact contents after a UI Save action.

Docker's [`--userns=host`](https://docs.docker.com/engine/security/userns-remap/)
disables namespace remapping but does not change numeric account IDs. Init uses
runtime `PLASMA_UID/GID` to adjust the desktop account and home before services
start. A requested UID belonging to another image account is rejected; an existing
primary group can be reused. Docker rootless uses different host ID mappings and is
not covered by these Docker commands.

Podman's [`keep-id`](https://docs.podman.io/en/latest/markdown/podman-run.1.html#userns-mode)
normally changes the initial process user, so the explicit `--user=0:0` matters.
Container root maps to a subordinate host ID; the desktop maps to your host user.
An alternative is `--userns=keep-id:uid=1000,gid=1000 --user=0:0 --passwd=false`
without runtime `PLASMA_UID/GID`: this maps your host user to the stock image's
unchanged desktop IDs. Use the image's actual IDs if they differ from 1000.

Inspect or stop a running container with the selected runtime:

```bash
docker exec plasma6-vnc plasma-healthcheck
docker exec plasma6-vnc journalctl -b -u plasma-vnc --no-pager
docker logs plasma6-vnc
docker stop plasma6-vnc
# Replace docker with podman for a Podman container.
```

Remote examples bind only to loopback and use plain VNC/HTTP. Use an SSH tunnel or
TLS reverse proxy for network access. KRFB virtualmonitor currently accepts its
password as a process argument; a password file avoids also recording it in the
container's configured environment.

## Configuration and implementation

| Variable | Default | Meaning |
| --- | --- | --- |
| `DISPLAY_MODE` | `headless` | `headless`, `nested`, `vnc`, `web` |
| `DISPLAY_BACKEND` | `auto` | `auto`, `wayland`, `x11` |
| `DISPLAY_WIDTH`, `DISPLAY_HEIGHT` | `1920`, `1080` | Initial dimensions, 10–9999 pixels |
| `PLASMA_UID`, `PLASMA_GID` | image account IDs | Optional runtime desktop identity |
| `HOST_WAYLAND_DISPLAY` | detected | Mounted socket path, or name relative to the host runtime mount |
| `HOST_XDG_RUNTIME_DIR` | `$XDG_RUNTIME_DIR` or `/run/host/runtime` | Host runtime socket search directory |
| `HOST_DISPLAY` | `$DISPLAY` or detected | Mounted local X11 display, e.g. `:0` |
| `HOST_XAUTHORITY` | `$XAUTHORITY` | Container path to the host X11 cookie file |
| `VNC_PASSWORD_FILE` | unset | Password file; takes precedence over `VNC_PASSWORD` |
| `VNC_PASSWORD` | unset | Password when no file is provided |
| `VNC_MAX_FPS` | `60` | Remote update rate, 1–60; lower it to reduce CPU/network use |
| `LIBGL_ALWAYS_SOFTWARE` | `0` | Prefer an accessible GPU; software fallback remains available |
| `INIT_LOG_LEVEL` | inherited (`2`) | Base framework logging level |

Build arguments: `BASE_IMAGE=ghcr.io/skynet-core/systemd:fedora-44`,
`PLASMA_UID=1000`, `PLASMA_GID=1000`, `NOVNC_VERSION=1.7.0`, `NOVNC_SHA256`,
`KRFB_SOURCE_VERSION=26.08.1`, `KRFB_SOURCE_SHA256`. For a locally built base use
`--build-arg BASE_IMAGE=systemd:fedora-44`. Update checksums together with source
versions. noVNC comes from its SHA-256 checked GitHub archive; websockify serves it
and forwards WebSocket traffic to VNC. Startup downloads nothing.

The inherited [systemd init framework](https://github.com/skynet-core/systemd/tree/6d2a500a094ced57306be10c5ef519d929b605d2)
loads `300-plasma-user.sh`, then `400-plasma.sh`. They prepare the desktop identity,
socket detection, X11 cookies and `/etc/plasma/session.env`, then set
`SYSTEMD_INIT_TARGET=plasma-<backend>-<mode>.target`. The inherited `501-systemd.sh`
replaces `default.target`; `999-exec.sh` executes `/usr/sbin/init --system`.

System services read the generated environment explicitly. Plasma uses classic
startup (`systemdBoot=false`) and KDE's `kwin_wayland_wrapper`; a private PATH
adapter adds backend arguments while preserving KDE's socket descriptors. Host
sockets remain separate from `/run/plasma`. Host X11 cookies are normalized for the
container hostname; socket aliases and display locks are prepared after tmpfiles
cleanup to prevent Xwayland claiming the host display number.

### Wayland remote input

Stock [KRFB's XDP event handler](https://github.com/KDE/krfb/blob/v26.08.1/events/xdp/xdpevents.cpp)
requires a portal session handle. `krfb-virtualmonitor` creates its output directly
through KWin's screencast protocol and has no such session, so that handler cannot
supply keyboard or mouse control.

`native/kwin-input.cpp` provides a KRFB event plugin for this service, using KWin's
fake-input protocol v6. It forwards keysyms, absolute pointer motion, button edges
and scrolling into the container's compositor. The virtual-monitor desktop entry
is granted that specific interface; global KWin permission checks remain enabled.
The plugin is selected only when the Wayland VNC service sets `PLASMA_KWIN_INPUT=1`.
Each connection owns an input device, which releases held inputs on disconnect.
The build stage contains development packages; the runtime contains only the plugin.

`plasma-remote-output` disables KWin's initial virtual output after KRFB's exported
monitor appears, then places the exported monitor at `(0, 0)`. The panel and windows
therefore appear on the remote desktop. X11 remote mode uses x11vnc.

### Rendering and VNC responsiveness

The default prefers GPU/OpenGL rendering when the container can open a compatible
GPU render node. With no usable GPU, KWin's virtual backend falls back to QPainter;
Mesa clients can use software rendering. The image includes Mesa drivers. The
privileged Docker commands above expose available devices; rootless Podman also
requires the host user to have permission to open them. A device mount alone does
not grant host permissions or install proprietary GPU drivers.

Inspect the actual compositor rather than inferring it from an environment value:

```bash
docker exec --user=plasma plasma6-web env \
  XDG_RUNTIME_DIR=/run/plasma DBUS_SESSION_BUS_ADDRESS=unix:path=/run/plasma/bus \
  qdbus-qt6 org.kde.KWin /KWin supportInformation
# Replace docker with podman and use your container's name.
# Look for Compositing Type and OpenGL renderer string.
```

Wayland remote mode builds the pinned upstream KRFB executable and PipeWire plugin
with [a small performance patch](patches/krfb-low-latency.patch): request changed
screen regions, remove an extra LibVNCServer frame delay, and replace the fixed
50 ms update timer with a precise timer controlled by `VNC_MAX_FPS` (default 60).
X11 mode uses the same setting for x11vnc polling and disables its extra frame
deferral. Actual frame rates depend on rendering, encoding, client and network.

For less CPU/bandwidth, add `-e VNC_MAX_FPS=30` or lower the initial dimensions with
`-e DISPLAY_WIDTH=1280 -e DISPLAY_HEIGHT=720` when creating the container. noVNC's
Quality and Compression controls tune image quality and encoding cost; higher
compression uses more server CPU. Settings are also accepted in the browser URL,
for example `http://127.0.0.1:6080/vnc.html?quality=6&compression=1`.

## Validation

Basic target, namespace, readiness and framebuffer checks:

```bash
bash test/test.sh --capture
RUNTIME=podman bash test/test.sh --capture
# Omit nested cases on machines without a host display:
bash test/test.sh --capture --skip-nested
# Exercise only an X11 host transport:
python3 test/integration.py --modes nested --host-backend x11
```

For full interactive validation, build the test-only Qt editor target and run the
UI suite. `uv` supplies the host-side RFB/WebSocket client and screenshot libraries:

```bash
docker build --target ui-test -t plasma6:ui-test .
uv run test/ui.py --runtime docker --image plasma6:ui-test

podman build --format docker --layers --target ui-test -t plasma6:ui-test .
uv run test/ui.py --runtime podman --image plasma6:ui-test
```

For each Wayland/X11 and VNC/web combination, the suite:

1. Boots the container with a single host file bind mount and a native Qt editor.
2. Captures a framebuffer, drags the window with RFB pointer/button events, captures
   it again, and measures the banner's translation from those screenshots.
3. Clicks the editor, types mixed case, punctuation, digits and newlines through
   RFB keyboard events, and presses Ctrl+S.
4. Reads the bind-mounted file on the host and compares its complete contents with
   the expected text; no host command writes that text into the file.

Each case retains before/after drag PNGs, a side-by-side comparison, a screenshot of
text after Save, the actual host file, JSON assertions, and service/container logs
under `test/.artifacts/`. The suite checks the same UI behavior over noVNC's actual
WebSocket proxy. Test windows and input go only to the container display.

The performance suite drives the real noVNC JavaScript client in Chromium at
1920×1080. It counts visible native-app animation changes, measures keyboard-event
to canvas feedback, and validates window dragging with screenshots:

```bash
docker build --target ui-test -t plasma6:ui-test .
uv run test/performance.py --image plasma6:ui-test --expect-renderer gpu
# Hide GPU nodes to test automatic software fallback, without forcing a renderer:
uv run test/performance.py --image plasma6:ui-test --no-gpu --expect-renderer software
# Rootless Podman uses its own image store:
uv run test/performance.py --runtime podman --image plasma6:ui-test

# Compare with unmodified Fedora KRFB, retaining the working input plugin:
docker build --target ui-perf-baseline -t plasma6:perf-before .
uv run test/performance.py --image plasma6:perf-before --measure-only
```

Install Chromium on the host first. `uv` supplies Playwright and Pillow; the test
uses the system `chromium` executable. Default thresholds are 25 visible fps and
150 ms keyboard p95 on local transport, and can be adjusted for slower CI hosts.
JSON timings, renderer information, logs and screenshots survive teardown under
`test/.artifacts/performance-*`. The production image excludes both test programs.

To reproduce the original Wayland failure, build `--target ui-baseline` and run
`test/ui.py --image plasma6:ui-baseline --backends wayland --modes vnc`. That target
contains the test editor and stock KRFB without the KWin input plugin; the drag and
text-save assertions are expected to fail.

`test/Dockerfile.uid-fixture` provides a separate account-mapping regression image
with UID/GID 2000. Run the nested integration cases against it to verify runtime
mapping on hosts with different caller IDs.

## Optional host launcher

`bin/plasma6-run` is a convenience alternative to the direct commands above:

```bash
DISPLAY_MODE=nested ./bin/plasma6-run
RUNTIME=podman DISPLAY_MODE=web VNC_PASSWORD_FILE="$PWD/vnc-password" ./bin/plasma6-run -d
```

It detects and mounts host sockets for nested mode, sets namespace/identity options,
and publishes only the selected remote mode's port. Options include
`IMAGE_TAG=plasma6:local`, `CONTAINER_NAME=plasma6`, `HOST_DISPLAY_BACKEND=auto|wayland|x11`,
`BIND_ADDRESS=127.0.0.1`, `VNC_PORT=5900`, `WEB_PORT=6080`. Port `0` requests an
available host port. Extra arguments are passed to the runtime before the image.
