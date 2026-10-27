# Plasma 6 container

For a commented, diagram-led explanation of the project, read
**[How this project works: a beginner's technical guide](docs/README.md)**.
The guide covers Linux containers, image builds, boot and systemd, all display
paths, remote input, UID mapping, troubleshooting, and the UI regression tests.

Plasma 6 desktops on every distribution image from
[`skynet-core/systemd`](https://github.com/skynet-core/systemd), with Fedora 44 as the maintained build template.
Systemd runs as PID 1; the desktop, private D-Bus and remote-access services run as
`plasma`. Docker with a rootful daemon and rootless Podman on Linux/cgroup v2 are
supported. The commands below run containers directly, without a host launcher.

[Build](#build) · [Preparation](#before-running-the-examples) · [Fedora](#fedora-44) · [Debian](#debian-13) · [Ubuntu](#ubuntu-2604) · [Arch](#arch-linux) · [Validation](#validation)

## Build

| Dockerfile | Systemd base tag | Desktop backends |
| --- | --- | --- |
| `Dockerfile.fedora-44` | `fedora-44` | Wayland and X11 |
| `Dockerfile.debian-13` | `debian-13` | Wayland and X11 |
| `Dockerfile.ubuntu-26.04` | `ubuntu-26.04` | Wayland and X11 |
| `Dockerfile.archlinux` | `archlinux` | Wayland only; current rolling Arch has removed the Plasma X11 session |

Each base is `ghcr.io/skynet-core/systemd:<tag>`. All variants share the same init
modules, services, GPU preference, remote input fixes and optional kiosk session.
NetworkManager is masked in every production image; container networking is
provided by Docker or Podman. Chromium is installed only in the `ui-test` target.

Always select a Dockerfile with `-f Dockerfile.<distro>`. The maintained template
is `Dockerfile.fedora-44`; the Debian, Ubuntu and Arch Dockerfiles are generated
from it. There is no unqualified `Dockerfile`. Use `--pull` (Docker) or
`--pull=always` (Podman) when rebuilding to obtain the latest systemd init framework.

### Build with Docker

```bash
# Fedora 44
docker build --pull -f Dockerfile.fedora-44 -t plasma6:fedora-44 .
# Debian 13
docker build --pull -f Dockerfile.debian-13 -t plasma6:debian-13 .
# Ubuntu 26.04
docker build --pull -f Dockerfile.ubuntu-26.04 -t plasma6:ubuntu-26.04 .
# Arch Linux
docker build --pull -f Dockerfile.archlinux -t plasma6:archlinux .
```

### Build with Podman

```bash
# Fedora 44
podman build --pull=always --format docker --layers -f Dockerfile.fedora-44 -t plasma6:fedora-44 .
# Debian 13
podman build --pull=always --format docker --layers -f Dockerfile.debian-13 -t plasma6:debian-13 .
# Ubuntu 26.04
podman build --pull=always --format docker --layers -f Dockerfile.ubuntu-26.04 -t plasma6:ubuntu-26.04 .
# Arch Linux
podman build --pull=always --format docker --layers -f Dockerfile.archlinux -t plasma6:archlinux .
```

Choose the distribution you want to run. Each run example below uses its explicit
`plasma6:<distro>` tag. To give the Fedora image the default image name used by
the optional launcher:

```bash
docker tag plasma6:fedora-44 plasma6:local
podman tag plasma6:fedora-44 plasma6:local
```

Podman's `--format docker` preserves the image health check. For an OCI import that
has lost its health metadata, add `--health-cmd=/usr/local/bin/plasma-healthcheck`.

Ubuntu's native `chromium-browser` package is a Snap launcher. For the `ui-test`
target, its Dockerfile fetches Chromium, its common files, sandbox helper and JPEG
ABI package from Debian's signed APT archive in a separate stage. Remaining
dependencies come from Ubuntu; no Debian repository is added to the Ubuntu image.
The production build skips this browser stage. Arch uses native desktop
packages and a dedicated Python environment for checksum-pinned websockify.
Debian's older KWin streams its existing virtual monitor through PipeWire;
newer releases create the additional `Virtual-Plasma` monitor. Both support GPU
rendering and automatic software fallback.

### GitHub Actions and GHCR

[Build, test and publish](.github/workflows/build-and-publish.yml) builds all four
variants for `linux/amd64` on pushes to `main`, `v*` tags, pull requests and manual
runs. It checks init and systemd units, boots the supported headless/VNC/web modes,
then tests window dragging, text saved through a host mount, and Chromium kiosk
input/restart. Hosted runners have no desktop socket, so nested tests remain local.
Per-case journals, screenshots and output files are retained as workflow artifacts.

Successful pushes and manual runs with `publish=true` push the **tested production
image** to `ghcr.io/<owner>/<repository>` using `GITHUB_TOKEN` with `packages: write`.
Pull requests never publish. For this repository the destination is
`ghcr.io/skynet-core/kde-container`:

| Trigger | Published tags |
| --- | --- |
| `main` | `fedora-44`, `debian-13`, `ubuntu-26.04`, `archlinux`; `latest` aliases Fedora |
| Any publishing run | `sha-<full-commit-sha>-<distro>` |
| Version tag, for example `v1.0.0` | `v1.0.0-<distro>` |

After a successful publishing workflow, pull and give each image the local
tag used by the run examples. Use the engine you intend to run it with;
Docker and Podman have separate image stores.

```bash
# Docker: download published images; no local build is needed.
# Fedora 44
docker pull ghcr.io/skynet-core/kde-container:fedora-44
docker tag ghcr.io/skynet-core/kde-container:fedora-44 plasma6:fedora-44
# Debian 13
docker pull ghcr.io/skynet-core/kde-container:debian-13
docker tag ghcr.io/skynet-core/kde-container:debian-13 plasma6:debian-13
# Ubuntu 26.04
docker pull ghcr.io/skynet-core/kde-container:ubuntu-26.04
docker tag ghcr.io/skynet-core/kde-container:ubuntu-26.04 plasma6:ubuntu-26.04
# Arch Linux
docker pull ghcr.io/skynet-core/kde-container:archlinux
docker tag ghcr.io/skynet-core/kde-container:archlinux plasma6:archlinux
```

```bash
# Podman: download published images; no local build is needed.
# Fedora 44
podman pull ghcr.io/skynet-core/kde-container:fedora-44
podman tag ghcr.io/skynet-core/kde-container:fedora-44 plasma6:fedora-44
# Debian 13
podman pull ghcr.io/skynet-core/kde-container:debian-13
podman tag ghcr.io/skynet-core/kde-container:debian-13 plasma6:debian-13
# Ubuntu 26.04
podman pull ghcr.io/skynet-core/kde-container:ubuntu-26.04
podman tag ghcr.io/skynet-core/kde-container:ubuntu-26.04 plasma6:ubuntu-26.04
# Arch Linux
podman pull ghcr.io/skynet-core/kde-container:archlinux
podman tag ghcr.io/skynet-core/kde-container:archlinux plasma6:archlinux
```

```bash
# Maintainers: edit Dockerfile.fedora-44 and build/packages/<family>/*.txt, then regenerate.
python3 build/render-dockerfiles.py
python3 build/render-dockerfiles.py --check
```

See [the build and publishing guide](docs/02-build-and-boot.md#distribution-variants-and-publication)
for package phases, caching and the publication flow.

## Display modes

| `DISPLAY_BACKEND` | `DISPLAY_MODE` | Default target | Display services |
| --- | --- | --- | --- |
| `wayland` | `nested` | `plasma-wayland-nested.target` | KWin in a host display window |
| `wayland` | `headless` | `plasma-wayland-headless.target` | KWin virtual framebuffer |
| `wayland` | `vnc` | `plasma-wayland-vnc.target` | OpenGL: KWin output, PipeWire, KRFB; older KWin software: private Xvfb and x11vnc; Arch software: Mesa/udmabuf and KRFB |
| `wayland` | `web` | `plasma-wayland-web.target` | Wayland VNC services plus noVNC/websockify |
| `x11` | `nested` | `plasma-x11-nested.target` | Rootful Xwayland on a Wayland host, or Xephyr on an X11 host |
| `x11` | `headless` | `plasma-x11-headless.target` | Xvfb and KWin X11 |
| `x11` | `vnc` | `plasma-x11-vnc.target` | Xvfb, KWin X11 and x11vnc |
| `x11` | `web` | `plasma-x11-web.target` | X11 VNC services plus noVNC/websockify |

With `TARGET_APP` unset, all modes start a full Plasma session and private session bus. Headless and nested
modes start no remote listener. Set `DISPLAY_BACKEND=x11` in any command below for
its X11 variant on Fedora, Debian or Ubuntu; Arch supports the four Wayland rows.
The per-distribution examples spell out each supported backend.
Arch includes Xwayland for legacy applications within its Wayland session.

`DISPLAY_BACKEND=auto` checks mounted Unix sockets, preferring Wayland over X11;
with neither it selects Wayland. Docker and Podman cannot mount host sockets from
inside the container, so nested mode needs the mounts shown below. If both host
socket types are mounted, Wayland has priority. Host transport and desktop backend
are independent: either desktop backend can nest on either host display.
On Arch, `auto` always chooses a Wayland desktop, including when nesting through
an X11 host socket. An explicit `DISPLAY_BACKEND=x11` fails with a clear message.

## Before running the examples

Run these commands as your desktop user on a Linux host with cgroup v2. Docker
examples use a rootful daemon; Podman runs rootless. Choose one run command
at a time: VNC examples share host port `5900` and browser/kiosk examples share
`6080`. Stop the previous remote container before reusing its port, or change the
host side of `-p`, for example `127.0.0.1:6081:6080`.

### Password for VNC, web and web kiosk

Create the password file in the directory where you will run the commands.
Replace `changeit` with your chosen 1–8 printable ASCII character password; VNC
authentication has an eight-character limit.

```bash
# HOST: the run commands mount this file read-only into the container.
(umask 077; printf '%s\n' 'changeit' > ./vnc-password)
chmod 600 ./vnc-password
```

Connect a VNC viewer to `127.0.0.1:5900`, or open
`http://127.0.0.1:6080/vnc.html` for web/kiosk mode and enter this password.
Headless and nested modes need no password and start no remote listener.

### Host socket for nested mode

For a Wayland host, prepare the socket path used by every Wayland-host example:

```bash
# Most desktop sessions export a name such as wayland-0.
export HOST_WAYLAND_SOCKET="$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY"
test -S "$HOST_WAYLAND_SOCKET"
```

If `WAYLAND_DISPLAY` already contains an absolute path, use
`export HOST_WAYLAND_SOCKET="$WAYLAND_DISPLAY"` instead. For an X11 host, the
examples mount `/tmp/.X11-unix` and `${XAUTHORITY:-$HOME/.Xauthority}`; set
`XAUTHORITY` to your active cookie file if that default is not correct.

The commands select the container backend explicitly. `DISPLAY_BACKEND=auto`
instead follows the mounted host transport, preferring Wayland when both socket
types are mounted. Arch always selects a Wayland session. To expose both host
transports, combine the Wayland mount/environment with the X11 mounts/environment
from the nested examples.

### Arch on a host without a GPU

Before running Arch without an accessible GPU, prepare `/dev/udmabuf` using
[the software-rendering instructions](#rendering-and-vnc-responsiveness).
The privileged examples expose available host devices automatically. Podman's
desktop user must also have host permission to open them.

## Single application / kiosk

Set `TARGET_APP` to run one fullscreen application under KWin instead of starting
the Plasma desktop, panels, splash screen and desktop autostart programs. Leave
it unset or empty to retain the normal KDE Plasma session. This works with every
supported profile: eight on Fedora/Debian/Ubuntu and four Wayland profiles on
Arch, including GPU rendering and software fallback.

Production images include Konsole and Dolphin; use `TARGET_APP=konsole` to try
kiosk mode with an installed application. Chromium is available only in the
`ui-test` target. Build that target for the Chromium examples below.
`TARGET_APP=chromium` starts it with kiosk and first-run
suppression flags, using the selected Wayland/X11 backend. Without a URL it opens
`about:blank`. The kiosk examples open `https://example.org`; replace that URL
with the page you want to display.

Complete Chromium commands for Docker and Podman are included in each
distribution section: [Fedora](#fedora-44), [Debian](#debian-13),
[Ubuntu](#ubuntu-2604) and [Arch](#arch-linux). Add `-e TARGET_APP=chromium`
or `-e TARGET_APP=konsole` before the image name in any other mode example
to run that application there.

Open `http://127.0.0.1:6080/vnc.html` and authenticate. For another application,
supply an installed executable/foreground
launcher with quoted arguments. Command strings are split into arguments without
shell evaluation: pipes, redirects, `$VAR` and command substitutions are not
expanded. For a shell workflow, put it in an executable launcher script and use
`exec` for its foreground GUI process.

KWin rules make normal application windows fullscreen; application dialogs can
still appear. Chromium also receives its own `--kiosk` flag. The application
restarts after exit/crash, with a two-second delay; KWin and VNC remain running.
Kiosk settings and application profiles use `/home/plasma/.config/plasma-kiosk`,
separate from the ordinary desktop configuration. Health checks require KWin and
the live application process instead of waiting for `plasmashell`.

## Run examples for every distribution

Each command starts the full KDE Plasma desktop unless it includes
`TARGET_APP`. Container names include the distribution (Fedora keeps the
short default names). Run the [preparation steps](#before-running-the-examples)
first, then expand the engine you use.

| Distribution | Local image used below | Desktop profiles |
| --- | --- | --- |
| [Fedora 44](#fedora-44) | `plasma6:fedora-44` | Wayland and X11: nested, headless, VNC, web |
| [Debian 13](#debian-13) | `plasma6:debian-13` | Wayland and X11: nested, headless, VNC, web |
| [Ubuntu 26.04](#ubuntu-2604) | `plasma6:ubuntu-26.04` | Wayland and X11: nested, headless, VNC, web |
| [Arch Linux](#arch-linux) | `plasma6:archlinux` | Wayland: nested, headless, VNC, web |

### Fedora 44

<details>
<summary>Docker: Fedora 44 desktop and Chromium kiosk commands</summary>

**Wayland headless**

```bash
docker run -d --rm --name plasma6-headless \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=headless plasma6:fedora-44
```

**Wayland nested on a Wayland host**

```bash
docker run -d --rm --name plasma6-nested \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:fedora-44
```

**Wayland nested on an X11 host**

```bash
docker run -d --rm --name plasma6-wayland-on-x11 \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:fedora-44
```

**Wayland VNC**

```bash
docker run -d --rm --name plasma6-vnc \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:fedora-44
```

**Wayland browser / noVNC**

```bash
docker run -d --rm --name plasma6-web \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:fedora-44
```

**X11 headless**

```bash
docker run -d --rm --name plasma6-x11-headless \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=headless plasma6:fedora-44
```

**X11 nested on a Wayland host**

```bash
docker run -d --rm --name plasma6-x11-on-wayland \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:fedora-44
```

**X11 nested on an X11 host**

```bash
docker run -d --rm --name plasma6-x11-nested \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:fedora-44
```

**X11 VNC**

```bash
docker run -d --rm --name plasma6-x11-vnc \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:fedora-44
```

**X11 browser / noVNC**

```bash
docker run -d --rm --name plasma6-x11-web \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:fedora-44
```

**Chromium kiosk: Wayland, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
docker build --pull -f Dockerfile.fedora-44 --target ui-test -t plasma6:fedora-44-test .
docker run -d --rm --name plasma6-chromium-wayland \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:fedora-44-test
```

**Chromium kiosk: X11, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
docker build --pull -f Dockerfile.fedora-44 --target ui-test -t plasma6:fedora-44-test .
docker run -d --rm --name plasma6-chromium-x11 \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:fedora-44-test
```

</details>

<details>
<summary>Rootless Podman: Fedora 44 desktop and Chromium kiosk commands</summary>

**Wayland headless**

```bash
podman run -d --rm --name plasma6-headless \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=headless plasma6:fedora-44
```

**Wayland nested on a Wayland host**

```bash
podman run -d --rm --name plasma6-nested \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:fedora-44
```

**Wayland nested on an X11 host**

```bash
podman run -d --rm --name plasma6-wayland-on-x11 \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:fedora-44
```

**Wayland VNC**

```bash
podman run -d --rm --name plasma6-vnc \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:fedora-44
```

**Wayland browser / noVNC**

```bash
podman run -d --rm --name plasma6-web \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:fedora-44
```

**X11 headless**

```bash
podman run -d --rm --name plasma6-x11-headless \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=headless plasma6:fedora-44
```

**X11 nested on a Wayland host**

```bash
podman run -d --rm --name plasma6-x11-on-wayland \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:fedora-44
```

**X11 nested on an X11 host**

```bash
podman run -d --rm --name plasma6-x11-nested \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:fedora-44
```

**X11 VNC**

```bash
podman run -d --rm --name plasma6-x11-vnc \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:fedora-44
```

**X11 browser / noVNC**

```bash
podman run -d --rm --name plasma6-x11-web \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:fedora-44
```

**Chromium kiosk: Wayland, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
podman build --pull=always --format docker --layers -f Dockerfile.fedora-44 --target ui-test -t plasma6:fedora-44-test .
podman run -d --rm --name plasma6-chromium-wayland \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:fedora-44-test
```

**Chromium kiosk: X11, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
podman build --pull=always --format docker --layers -f Dockerfile.fedora-44 --target ui-test -t plasma6:fedora-44-test .
podman run -d --rm --name plasma6-chromium-x11 \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:fedora-44-test
```

</details>

### Debian 13

<details>
<summary>Docker: Debian 13 desktop and Chromium kiosk commands</summary>

**Wayland headless**

```bash
docker run -d --rm --name plasma6-debian-13-headless \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=headless plasma6:debian-13
```

**Wayland nested on a Wayland host**

```bash
docker run -d --rm --name plasma6-debian-13-nested \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:debian-13
```

**Wayland nested on an X11 host**

```bash
docker run -d --rm --name plasma6-debian-13-wayland-on-x11 \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:debian-13
```

**Wayland VNC**

```bash
docker run -d --rm --name plasma6-debian-13-vnc \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:debian-13
```

**Wayland browser / noVNC**

```bash
docker run -d --rm --name plasma6-debian-13-web \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:debian-13
```

**X11 headless**

```bash
docker run -d --rm --name plasma6-debian-13-x11-headless \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=headless plasma6:debian-13
```

**X11 nested on a Wayland host**

```bash
docker run -d --rm --name plasma6-debian-13-x11-on-wayland \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:debian-13
```

**X11 nested on an X11 host**

```bash
docker run -d --rm --name plasma6-debian-13-x11-nested \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:debian-13
```

**X11 VNC**

```bash
docker run -d --rm --name plasma6-debian-13-x11-vnc \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:debian-13
```

**X11 browser / noVNC**

```bash
docker run -d --rm --name plasma6-debian-13-x11-web \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:debian-13
```

**Chromium kiosk: Wayland, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
docker build --pull -f Dockerfile.debian-13 --target ui-test -t plasma6:debian-13-test .
docker run -d --rm --name plasma6-debian-13-chromium-wayland \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:debian-13-test
```

**Chromium kiosk: X11, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
docker build --pull -f Dockerfile.debian-13 --target ui-test -t plasma6:debian-13-test .
docker run -d --rm --name plasma6-debian-13-chromium-x11 \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:debian-13-test
```

</details>

<details>
<summary>Rootless Podman: Debian 13 desktop and Chromium kiosk commands</summary>

**Wayland headless**

```bash
podman run -d --rm --name plasma6-debian-13-headless \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=headless plasma6:debian-13
```

**Wayland nested on a Wayland host**

```bash
podman run -d --rm --name plasma6-debian-13-nested \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:debian-13
```

**Wayland nested on an X11 host**

```bash
podman run -d --rm --name plasma6-debian-13-wayland-on-x11 \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:debian-13
```

**Wayland VNC**

```bash
podman run -d --rm --name plasma6-debian-13-vnc \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:debian-13
```

**Wayland browser / noVNC**

```bash
podman run -d --rm --name plasma6-debian-13-web \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:debian-13
```

**X11 headless**

```bash
podman run -d --rm --name plasma6-debian-13-x11-headless \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=headless plasma6:debian-13
```

**X11 nested on a Wayland host**

```bash
podman run -d --rm --name plasma6-debian-13-x11-on-wayland \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:debian-13
```

**X11 nested on an X11 host**

```bash
podman run -d --rm --name plasma6-debian-13-x11-nested \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:debian-13
```

**X11 VNC**

```bash
podman run -d --rm --name plasma6-debian-13-x11-vnc \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:debian-13
```

**X11 browser / noVNC**

```bash
podman run -d --rm --name plasma6-debian-13-x11-web \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:debian-13
```

**Chromium kiosk: Wayland, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
podman build --pull=always --format docker --layers -f Dockerfile.debian-13 --target ui-test -t plasma6:debian-13-test .
podman run -d --rm --name plasma6-debian-13-chromium-wayland \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:debian-13-test
```

**Chromium kiosk: X11, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
podman build --pull=always --format docker --layers -f Dockerfile.debian-13 --target ui-test -t plasma6:debian-13-test .
podman run -d --rm --name plasma6-debian-13-chromium-x11 \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:debian-13-test
```

</details>

### Ubuntu 26.04

<details>
<summary>Docker: Ubuntu 26.04 desktop and Chromium kiosk commands</summary>

**Wayland headless**

```bash
docker run -d --rm --name plasma6-ubuntu-26.04-headless \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=headless plasma6:ubuntu-26.04
```

**Wayland nested on a Wayland host**

```bash
docker run -d --rm --name plasma6-ubuntu-26.04-nested \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:ubuntu-26.04
```

**Wayland nested on an X11 host**

```bash
docker run -d --rm --name plasma6-ubuntu-26.04-wayland-on-x11 \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:ubuntu-26.04
```

**Wayland VNC**

```bash
docker run -d --rm --name plasma6-ubuntu-26.04-vnc \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:ubuntu-26.04
```

**Wayland browser / noVNC**

```bash
docker run -d --rm --name plasma6-ubuntu-26.04-web \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:ubuntu-26.04
```

**X11 headless**

```bash
docker run -d --rm --name plasma6-ubuntu-26.04-x11-headless \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=headless plasma6:ubuntu-26.04
```

**X11 nested on a Wayland host**

```bash
docker run -d --rm --name plasma6-ubuntu-26.04-x11-on-wayland \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:ubuntu-26.04
```

**X11 nested on an X11 host**

```bash
docker run -d --rm --name plasma6-ubuntu-26.04-x11-nested \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:ubuntu-26.04
```

**X11 VNC**

```bash
docker run -d --rm --name plasma6-ubuntu-26.04-x11-vnc \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:ubuntu-26.04
```

**X11 browser / noVNC**

```bash
docker run -d --rm --name plasma6-ubuntu-26.04-x11-web \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:ubuntu-26.04
```

**Chromium kiosk: Wayland, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
docker build --pull -f Dockerfile.ubuntu-26.04 --target ui-test -t plasma6:ubuntu-26.04-test .
docker run -d --rm --name plasma6-ubuntu-26.04-chromium-wayland \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:ubuntu-26.04-test
```

**Chromium kiosk: X11, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
docker build --pull -f Dockerfile.ubuntu-26.04 --target ui-test -t plasma6:ubuntu-26.04-test .
docker run -d --rm --name plasma6-ubuntu-26.04-chromium-x11 \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:ubuntu-26.04-test
```

</details>

<details>
<summary>Rootless Podman: Ubuntu 26.04 desktop and Chromium kiosk commands</summary>

**Wayland headless**

```bash
podman run -d --rm --name plasma6-ubuntu-26.04-headless \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=headless plasma6:ubuntu-26.04
```

**Wayland nested on a Wayland host**

```bash
podman run -d --rm --name plasma6-ubuntu-26.04-nested \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:ubuntu-26.04
```

**Wayland nested on an X11 host**

```bash
podman run -d --rm --name plasma6-ubuntu-26.04-wayland-on-x11 \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:ubuntu-26.04
```

**Wayland VNC**

```bash
podman run -d --rm --name plasma6-ubuntu-26.04-vnc \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:ubuntu-26.04
```

**Wayland browser / noVNC**

```bash
podman run -d --rm --name plasma6-ubuntu-26.04-web \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:ubuntu-26.04
```

**X11 headless**

```bash
podman run -d --rm --name plasma6-ubuntu-26.04-x11-headless \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=headless plasma6:ubuntu-26.04
```

**X11 nested on a Wayland host**

```bash
podman run -d --rm --name plasma6-ubuntu-26.04-x11-on-wayland \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:ubuntu-26.04
```

**X11 nested on an X11 host**

```bash
podman run -d --rm --name plasma6-ubuntu-26.04-x11-nested \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=nested plasma6:ubuntu-26.04
```

**X11 VNC**

```bash
podman run -d --rm --name plasma6-ubuntu-26.04-x11-vnc \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:ubuntu-26.04
```

**X11 browser / noVNC**

```bash
podman run -d --rm --name plasma6-ubuntu-26.04-x11-web \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:ubuntu-26.04
```

**Chromium kiosk: Wayland, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
podman build --pull=always --format docker --layers -f Dockerfile.ubuntu-26.04 --target ui-test -t plasma6:ubuntu-26.04-test .
podman run -d --rm --name plasma6-ubuntu-26.04-chromium-wayland \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:ubuntu-26.04-test
```

**Chromium kiosk: X11, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
podman build --pull=always --format docker --layers -f Dockerfile.ubuntu-26.04 --target ui-test -t plasma6:ubuntu-26.04-test .
podman run -d --rm --name plasma6-ubuntu-26.04-chromium-x11 \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=x11 -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:ubuntu-26.04-test
```

</details>

### Arch Linux

This rolling image supports a Wayland desktop on either host transport.
`DISPLAY_BACKEND=x11` is unsupported. For a host without a GPU, prepare
[udmabuf](#arch-on-a-host-without-a-gpu) first.

<details>
<summary>Docker: Arch Linux desktop and Chromium kiosk commands</summary>

**Wayland headless**

```bash
docker run -d --rm --name plasma6-archlinux-headless \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=headless plasma6:archlinux
```

**Wayland nested on a Wayland host**

```bash
docker run -d --rm --name plasma6-archlinux-nested \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:archlinux
```

**Wayland nested on an X11 host**

```bash
docker run -d --rm --name plasma6-archlinux-wayland-on-x11 \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:archlinux
```

**Wayland VNC**

```bash
docker run -d --rm --name plasma6-archlinux-vnc \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:archlinux
```

**Wayland browser / noVNC**

```bash
docker run -d --rm --name plasma6-archlinux-web \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:archlinux
```

**Chromium kiosk: Wayland, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
docker build --pull -f Dockerfile.archlinux --target ui-test -t plasma6:archlinux-test .
docker run -d --rm --name plasma6-archlinux-chromium-wayland \
  --privileged --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:archlinux-test
```

</details>

<details>
<summary>Rootless Podman: Arch Linux desktop and Chromium kiosk commands</summary>

**Wayland headless**

```bash
podman run -d --rm --name plasma6-archlinux-headless \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=headless plasma6:archlinux
```

**Wayland nested on a Wayland host**

```bash
podman run -d --rm --name plasma6-archlinux-nested \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$HOST_WAYLAND_SOCKET,target=/run/host/wayland,readonly" \
  -e HOST_WAYLAND_DISPLAY=/run/host/wayland \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:archlinux
```

**Wayland nested on an X11 host**

```bash
podman run -d --rm --name plasma6-archlinux-wayland-on-x11 \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:archlinux
```

**Wayland VNC**

```bash
podman run -d --rm --name plasma6-archlinux-vnc \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=vnc \
  -p 127.0.0.1:5900:5900 plasma6:archlinux
```

**Wayland browser / noVNC**

```bash
podman run -d --rm --name plasma6-archlinux-web \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -p 127.0.0.1:6080:6080 plasma6:archlinux
```

**Chromium kiosk: Wayland, browser / noVNC**

```bash
# Build the test-only image containing Chromium.
podman build --pull=always --format docker --layers -f Dockerfile.archlinux --target ui-test -t plasma6:archlinux-test .
podman run -d --rm --name plasma6-archlinux-chromium-wayland \
  --privileged --systemd=always --user=0:0 --userns=keep-id --passwd=false \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount "type=bind,source=$PWD/vnc-password,target=/run/secrets/vnc-password,readonly" \
  -e VNC_PASSWORD_FILE=/run/secrets/vnc-password \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=web \
  -e TARGET_APP='chromium https://example.org' \
  -p 127.0.0.1:6080:6080 plasma6:archlinux-test
```

</details>

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

## Plasma account password and sudo

`PLASMA_PASSWORD` sets the Linux password for `plasma` at startup. Leaving it unset
preserves the existing account password; a fresh image has no password login until
you configure one. Normal `sudo` requires this password. Set
`PLASMA_SUDO_NOPASSWD=true` to allow `sudo` without a password, including when no
account password is configured. These options work with all four distributions
and every display mode. `VNC_PASSWORD` remains the separate remote-access password.

```bash
# Docker: configure the account and opt in to passwordless sudo.
# Replace the image tag with debian-13, ubuntu-26.04 or archlinux as needed.
docker run -d --name plasma6-account --privileged --user=0:0 \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e DISPLAY_MODE=headless -e PLASMA_PASSWORD='ChangeThisPassword42!' \
  -e PLASMA_SUDO_NOPASSWD=true plasma6:fedora-44
# The command runs as plasma, then sudo switches to container root (prints 0).
docker exec --user=plasma plasma6-account sudo -n id -u
```

```bash
# Rootless Podman: keep PID 1 as root while mapping the desktop to your host user.
podman run -d --name plasma6-account --privileged --systemd=always \
  --userns=keep-id --user=0:0 --passwd=false --cgroupns=private \
  --pids-limit=8192 --shm-size=512m --tmpfs /run --tmpfs /tmp:mode=1777 \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_MODE=headless -e PLASMA_PASSWORD='ChangeThisPassword42!' \
  -e PLASMA_SUDO_NOPASSWD=true plasma6:fedora-44
podman exec --user=plasma plasma6-account sudo -n id -u
```

Omit `PLASMA_SUDO_NOPASSWD` or set it to `false` for password-required sudo. From
a desktop terminal, run `sudo <command>` and enter the configured account password.
The managed, root-owned `/etc/sudoers.d/90-plasma` file is included by
`/etc/sudoers`; its contents are validated with `visudo` on every start. The
passwordless setting writes `plasma ALL=(ALL) NOPASSWD: ALL`. The file is replaced
on each start, so disabling the option removes that passwordless grant.

For a password outside the container's configured environment, create a host file
and use `PLASMA_PASSWORD_FILE`. A file takes precedence over `PLASMA_PASSWORD`:

```bash
# Prompt without echoing the password and restrict the host file to its owner.
python3 - <<'PY'
from getpass import getpass
from pathlib import Path

path = Path("plasma-password")
path.touch(mode=0o600)
path.chmod(0o600)
path.write_text(getpass("Password for the plasma account: "))
PY

# Docker: password-required sudo with a mounted account secret.
docker run -d --name plasma6-account-file --privileged --user=0:0 \
  --cgroupns=private --pids-limit=8192 --shm-size=512m \
  --tmpfs /run --tmpfs /tmp:mode=1777 -e DISPLAY_MODE=headless \
  --mount "type=bind,source=$PWD/plasma-password,target=/run/secrets/plasma-password,readonly" \
  -e PLASMA_PASSWORD_FILE=/run/secrets/plasma-password plasma6:fedora-44
docker exec -it --user=plasma plasma6-account-file sudo id -u
```

Passwords must be nonempty single lines, without carriage returns. A final newline
in a password file is accepted. Init hashes the password with `chpasswd` and
does not copy the value into `/etc/plasma/session.env`. The optional host launcher
forwards both options and mounts a host `PLASMA_PASSWORD_FILE` automatically.
Passwordless sudo grants full root privileges inside the container; under rootless
Podman, root remains limited to its user namespace.

## Configuration and implementation

| Variable | Default | Meaning |
| --- | --- | --- |
| `DISPLAY_MODE` | `headless` | `headless`, `nested`, `vnc`, `web` |
| `DISPLAY_BACKEND` | `auto` | `auto`, `wayland`, `x11` |
| `TARGET_APP` | unset | Optional executable and quoted arguments; selects a fullscreen application session |
| `DISPLAY_WIDTH`, `DISPLAY_HEIGHT` | `1920`, `1080` | Initial dimensions, 10–9999 pixels |
| `PLASMA_UID`, `PLASMA_GID` | image account IDs | Optional runtime desktop identity |
| `PLASMA_PASSWORD` | unset | Set the Linux account password; unset preserves it |
| `PLASMA_PASSWORD_FILE` | unset | Container password-file path; takes precedence over `PLASMA_PASSWORD` |
| `PLASMA_SUDO_NOPASSWD` | `false` | `true` permits passwordless sudo; `false` requires the account password |
| `HOST_WAYLAND_DISPLAY` | detected | Mounted socket path, or name relative to the host runtime mount |
| `HOST_XDG_RUNTIME_DIR` | `$XDG_RUNTIME_DIR` or `/run/host/runtime` | Host runtime socket search directory |
| `HOST_DISPLAY` | `$DISPLAY` or detected | Mounted local X11 display, e.g. `:0` |
| `HOST_XAUTHORITY` | `$XAUTHORITY` | Container path to the host X11 cookie file |
| `VNC_PASSWORD_FILE` | unset | Password file; takes precedence over `VNC_PASSWORD` |
| `VNC_PASSWORD` | unset | Password when no file is provided |
| `VNC_MAX_FPS` | `60` | Remote update rate, 1–60; lower it to reduce CPU/network use |
| `NVIDIA_DRIVER_CAPABILITIES` | `compute,utility,graphics,display` | NVIDIA toolkit capabilities requested before init; GPU devices still require `--gpus` |
| `LIBGL_ALWAYS_SOFTWARE` | `0` | Prefer an accessible GPU; software fallback remains available |
| `SYSTEMD_MASKED` | `NetworkManager.service` | Base init framework disables and masks these units before boot; comma/space-separated list |
| `INIT_LOG_LEVEL` | inherited (`2`) | Base framework logging level |

Build arguments: `BASE_IMAGE=ghcr.io/skynet-core/systemd:<distro>` (matching
the selected distribution Dockerfile),
`PLASMA_UID=1000`, `PLASMA_GID=1000`, `NOVNC_VERSION=1.7.0`, `NOVNC_SHA256`,
`KRFB_SOURCE_VERSION=26.08.2`, `KRFB_SOURCE_SHA256`. For a locally built base,
use the matching Dockerfile and base tag, for example
`docker build -f Dockerfile.debian-13 --build-arg BASE_IMAGE=systemd:debian-13 -t plasma6:debian-13 .`.
Update checksums together with source
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

Stock [KRFB's XDP event handler](https://github.com/KDE/krfb/blob/v26.08.2/events/xdp/xdpevents.cpp)
requires a portal session handle. `krfb-virtualmonitor` creates its output directly
through KWin's screencast protocol and has no such session, so that handler cannot
supply keyboard or mouse control.

`native/kwin-input.cpp` provides a KRFB event plugin for this service, using KWin's
fake-input protocol v5/v6. Newer KWin accepts keysyms directly; Debian's v5 uses
the compositor's keyboard map to send keycodes. It forwards absolute pointer motion, button edges
and scrolling into the container's compositor. The virtual-monitor desktop entry
is granted that specific interface; global KWin permission checks remain enabled.
The plugin is selected only when the Wayland VNC service sets `PLASMA_KWIN_INPUT=1`.
Each connection owns an input device, which releases held inputs on disconnect.
The build stage contains development packages; the runtime contains only the plugin.

`plasma-remote-output` disables KWin's initial virtual output after KRFB's exported
monitor appears, then places the exported monitor at `(0, 0)`. The panel and windows
therefore appear on the remote desktop. X11 remote mode uses x11vnc.

### Rendering and VNC responsiveness

Startup prefers working GPU/OpenGL rendering. It checks every visible render node
by creating a real GBM/EGL context as `plasma` and rejects software-only contexts.
KWin chooses a hardware device compatible with the selected display path. NVIDIA,
AMD and Intel devices keep their native drivers; there is no global vendor override.
If no hardware context works, init selects Mesa software rendering and Qt Quick's
software backend. Results are saved in `/etc/plasma/gpu.json`. The image includes
Mesa drivers. The
privileged Docker commands above expose available devices; rootless Podman also
requires the host user to have permission to open them. A device mount alone does
not grant host permissions or install proprietary GPU drivers.

KWin's screencast API requires OpenGL, so the Wayland VNC/web software fallback
runs KWin with QPainter inside a private Xvfb server and uses x11vnc to capture
that parent display. Applications and the Plasma session still use Wayland.
The software helper preserves raw modifier key events and loads a scoped XTest
compatibility library that spaces keyboard edges by at least 5 ms, preserving rapid
Shift/Ctrl combinations through KWin's nested input backend.
Headless and nested modes use their normal backends with software rendering.

For NVIDIA, use a host with the NVIDIA Container Toolkit and add `--gpus all`
to the Docker command. Images default
`NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display`, so older toolkit
versions also inject the graphics libraries. These libraries must match the host
kernel driver; installing an arbitrary NVIDIA driver inside the image is unnecessary.
Init makes injected NVIDIA GBM backends discoverable in the container's library
directory. This handles an Arch host using `/usr/lib/gbm` with a Fedora image using
`/usr/lib64/gbm`, which otherwise can produce a black nested window and llvmpipe.
AMD and Intel use the packaged Mesa drivers and exposed `/dev/dri` nodes.

Nested NVIDIA rendering also waits for the GPU's render fence before KWin hands
raw buffers to the host. This prevents completed window contents from blinking
or disappearing on the monitor while window recordings look correct. Rendering
stays on NVIDIA; no software renderer or different OpenGL API is forced. Init
enables this only for GPU-backed nested Wayland sessions with usable NVIDIA
hardware. The compatibility library loads into KWin alone, and restores the
application environment before Xwayland or session applications start.

For buffer formats, fences, video-capture limitations and diagnostic commands,
see [the graphics debugging guide](docs/06-graphics-debugging.md).

On the tested NVIDIA 615.78.08 driver, Debian 13's KWin 6.3.6 has a separate
virtual-output framebuffer failure in Wayland VNC/web mode. It also occurs in
the image before the nested synchronization fix. NVIDIA nested mode passes on
Debian; use the Fedora, Ubuntu or Arch image for the validated NVIDIA remote
path. Debian remote mode was validated with AMD/Mesa.

```bash
# NVIDIA: Wayland Plasma inside the host X11/Xwayland window.
docker run -d --rm --name plasma6-nvidia-nested \
  --privileged --gpus all --user=0:0 --userns=host --cgroupns=private \
  --pids-limit=8192 --shm-size=2g --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:fedora-44
# Inspect all startup probes and the actual compositor renderer.
docker exec plasma6-nvidia-nested cat /etc/plasma/gpu.json
docker exec --user=plasma plasma6-nvidia-nested \
  env XDG_RUNTIME_DIR=/run/plasma DBUS_SESSION_BUS_ADDRESS=unix:path=/run/plasma/bus \
  qdbus-qt6 org.kde.KWin /KWin supportInformation
```

For rootless Podman, use NVIDIA CDI (`nvidia-ctk cdi list` must list the GPU).
With `keep-id`, avoid combining CDI with privileged automatic device imports;
use the systemd capabilities explicitly to prevent duplicate `/dev/dri` mounts:

```bash
# Rootless Podman: NVIDIA-accelerated nested Wayland over the host X11 socket.
podman run -d --rm --name plasma6-nvidia-nested \
  --device=nvidia.com/gpu=all --cap-add=all --security-opt=seccomp=unconfined \
  --systemd=always --user=0:0 --userns=keep-id --passwd=false --cgroupns=private \
  --pids-limit=8192 --shm-size=2g --tmpfs /run --tmpfs /tmp:mode=1777 \
  --mount type=bind,source=/tmp/.X11-unix,target=/run/host/X11,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/run/host/Xauthority,readonly" \
  -e HOST_DISPLAY="$DISPLAY" -e HOST_XAUTHORITY=/run/host/Xauthority \
  -e PLASMA_UID="$(id -u)" -e PLASMA_GID="$(id -g)" \
  -e DISPLAY_BACKEND=wayland -e DISPLAY_MODE=nested plasma6:fedora-44
```

The GPU checks describe usable devices. The actual compositor renderer also
depends on its display backend; inspect KWin's support information. The X11
profiles retain their Xvfb/Xephyr/shared-memory Xwayland display paths.

`LIBGL_ALWAYS_SOFTWARE=1` explicitly selects the software path; the default `0`
means prefer GPU and select software if no hardware context can be created.

Current Arch uses Mesa software OpenGL and PipeWire instead: KWin 6.8 removed
QPainter. This requires the host's `/dev/udmabuf` device, which exports CPU memory
as DMA buffers without requiring a GPU. Prepare it before starting an Arch
container on a machine without a GPU:

```bash
# HOST: load the kernel driver if /dev/udmabuf is absent.
if [ ! -c /dev/udmabuf ]; then sudo modprobe udmabuf; fi
# Rootless Podman needs your host user to be allowed to open the device.
# This ACL lasts until the device is recreated; a udev rule can make it persistent.
sudo setfacl -m "u:$(id -u):rw" /dev/udmabuf
```

The privileged run commands expose it automatically. Init grants the container's
desktop account membership in the device's local group, preserving host device
permissions. For a restricted container, explicitly add `--device=/dev/udmabuf`.
The optional launcher uses Podman `keep-id` and your desktop UID/GID in every mode
so rootless device access and host file ownership follow the same mapping.

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

## Linting

Run the complete source checks with:

```bash
./test/lint.sh
```

Install ShellCheck, Ruff, Hadolint, actionlint, clang-format, clangd, clang-tidy,
`xmllint`, Git and ripgrep on the host. The native checks also need CMake, a C/C++
compiler, Qt 6 Widgets, KF6 CoreAddons, Wayland development tools, LibVNCServer,
xkbcommon and the KRFB private library. The distribution-specific development
package lists are in `build/packages/*/input-build.txt`; install `krfb` as well.
The Wayland development tools supply `/usr/share/wayland/wayland.dtd` for XML
validation.

Configure and build the native code once before linting. KRFB's public package
does not include the private plugin headers, so download the same verified source
archive used by the Dockerfiles:

```bash
mkdir -p test/.artifacts/lint/krfb-source
curl --fail --location --retry 3 \
  https://codeload.github.com/KDE/krfb/tar.gz/refs/tags/v26.08.2 \
  --output test/.artifacts/lint/krfb.tar.gz
printf '%s  %s\n' \
  4f613500a2308f5b16b109ee4f113a69ea597cd03bdb19f8b6abd16ab914593e \
  test/.artifacts/lint/krfb.tar.gz | sha256sum --check -
tar -xzf test/.artifacts/lint/krfb.tar.gz --strip-components=1 \
  -C test/.artifacts/lint/krfb-source
cmake -S native -B build \
  -DKRFB_SOURCE_DIR="$PWD/test/.artifacts/lint/krfb-source"
cmake --build build --parallel
./test/lint.sh
```

CMake exports `build/compile_commands.json`; `.clangd` uses it for the same include
paths and compiler flags in the editor. Rebuild after changing the native code or
Wayland XML. If KRFB's private library is outside the normal library search paths,
add `-DKRFB_PRIVATE=/absolute/path/to/libkrfbprivate.so.5` to the configure command.

The checks cover shell scripts, Python scripts (including executable files without
`.py` suffixes), Dockerfiles, GitHub Actions, C++ formatting and diagnostics,
Wayland XML, SVG and JSON. Ruff also checks and formats Python examples in Markdown.
Clangd logs remain in `test/.artifacts/lint/`. Generated build files and downloaded
dependencies are excluded. The few API-mandated C++ parameter warnings and the
root systemd Dockerfile policy have individual comments explaining their scope.

## Validation

Run the host regression checks without building an image:

```bash
python3 test/unit.py
```

These check launcher namespaces, nested socket mounts, test isolation, readiness
failures, retained diagnostics and kiosk shutdown/restart cleanup. The container
suites share their setup and evidence collection through `test/support.py` and
use `bin/plasma6-run` for engine flags and display mounts.

Run production-image init, systemd, boot and framebuffer checks for the
distribution you built. These suites use the optional host launcher internally
to check namespace and socket handling as well.

```bash
# Docker: choose the matching image.
RUNTIME=docker IMAGE_TAG=plasma6:fedora-44 bash test/test.sh --capture
RUNTIME=docker IMAGE_TAG=plasma6:debian-13 bash test/test.sh --capture
RUNTIME=docker IMAGE_TAG=plasma6:ubuntu-26.04 bash test/test.sh --capture
RUNTIME=docker IMAGE_TAG=plasma6:archlinux bash test/test.sh --capture
```

```bash
# Rootless Podman: choose the matching image.
RUNTIME=podman IMAGE_TAG=plasma6:fedora-44 bash test/test.sh --capture
RUNTIME=podman IMAGE_TAG=plasma6:debian-13 bash test/test.sh --capture
RUNTIME=podman IMAGE_TAG=plasma6:ubuntu-26.04 bash test/test.sh --capture
RUNTIME=podman IMAGE_TAG=plasma6:archlinux bash test/test.sh --capture
```

On a host without a graphical session, append `--skip-nested` to the boot
commands. For kiosk tests below, append `--modes headless vnc web`. The suites
detect Arch's Wayland-only support automatically.

The `ui-test` target adds Chromium, a Qt editor and benchmark to the runtime image.
These applications are excluded from the published production target. `uv`
supplies the host RFB/WebSocket and screenshot dependencies. Build and validate
the test image in the same engine's store:

<details>
<summary>Docker: UI and kiosk validation for all distributions</summary>

**Fedora 44**

```bash
docker build -f Dockerfile.fedora-44 --target ui-test -t plasma6:fedora-44-test .
uv run test/ui.py --runtime docker --image plasma6:fedora-44-test
uv run test/kiosk.py --runtime docker --image plasma6:fedora-44-test
```

**Debian 13**

```bash
docker build -f Dockerfile.debian-13 --target ui-test -t plasma6:debian-13-test .
uv run test/ui.py --runtime docker --image plasma6:debian-13-test
uv run test/kiosk.py --runtime docker --image plasma6:debian-13-test
```

**Ubuntu 26.04**

```bash
docker build -f Dockerfile.ubuntu-26.04 --target ui-test -t plasma6:ubuntu-26.04-test .
uv run test/ui.py --runtime docker --image plasma6:ubuntu-26.04-test
uv run test/kiosk.py --runtime docker --image plasma6:ubuntu-26.04-test
```

**Arch Linux**

```bash
docker build -f Dockerfile.archlinux --target ui-test -t plasma6:archlinux-test .
uv run test/ui.py --runtime docker --image plasma6:archlinux-test
uv run test/kiosk.py --runtime docker --image plasma6:archlinux-test
```

</details>

<details>
<summary>Rootless Podman: UI and kiosk validation for all distributions</summary>

**Fedora 44**

```bash
podman build --format docker --layers -f Dockerfile.fedora-44 --target ui-test -t plasma6:fedora-44-test .
uv run test/ui.py --runtime podman --image plasma6:fedora-44-test
uv run test/kiosk.py --runtime podman --image plasma6:fedora-44-test
```

**Debian 13**

```bash
podman build --format docker --layers -f Dockerfile.debian-13 --target ui-test -t plasma6:debian-13-test .
uv run test/ui.py --runtime podman --image plasma6:debian-13-test
uv run test/kiosk.py --runtime podman --image plasma6:debian-13-test
```

**Ubuntu 26.04**

```bash
podman build --format docker --layers -f Dockerfile.ubuntu-26.04 --target ui-test -t plasma6:ubuntu-26.04-test .
uv run test/ui.py --runtime podman --image plasma6:ubuntu-26.04-test
uv run test/kiosk.py --runtime podman --image plasma6:ubuntu-26.04-test
```

**Arch Linux**

```bash
podman build --format docker --layers -f Dockerfile.archlinux --target ui-test -t plasma6:archlinux-test .
uv run test/ui.py --runtime podman --image plasma6:archlinux-test
uv run test/kiosk.py --runtime podman --image plasma6:archlinux-test
```

</details>

For every supported Wayland/X11 and VNC/web combination, the UI suite:

1. Boots the container with a single host file bind mount and a native Qt editor.
2. Drags the window through RFB and measures its translation in before/after screenshots.
3. Types mixed case, punctuation, digits and newlines through RFB, then presses Ctrl+S.
4. Compares the UI-saved host file with the expected complete text and checks its owner.

Kiosk tests cover the Qt editor and actual Chromium, fullscreen display/input,
application restart with the same KWin process, and absence of Plasma shell.
Each case retains screenshots, JSON assertions, journals and host-file output
under `test/.artifacts/`. Web cases exercise the websockify proxy used by noVNC.

For the optional software and performance commands below, select the test
image you built and the same engine. Choose one image assignment:

```bash
# Choose one distribution:
export TEST_IMAGE=plasma6:fedora-44-test
# export TEST_IMAGE=plasma6:debian-13-test
# export TEST_IMAGE=plasma6:ubuntu-26.04-test
# export TEST_IMAGE=plasma6:archlinux-test
export RUNTIME=docker
# export RUNTIME=podman
```

The performance suite drives the real noVNC JavaScript client in Chromium at
1920×1080. It counts visible native-app animation changes, measures keyboard-event
to canvas feedback, and validates window dragging with screenshots:

```bash
# Uses TEST_IMAGE and RUNTIME selected above; the host needs Chromium.
uv run test/performance.py --runtime "$RUNTIME" --image "$TEST_IMAGE" --expect-renderer gpu
# Hide GPU nodes to verify automatic software fallback.
uv run test/performance.py --runtime "$RUNTIME" --image "$TEST_IMAGE" --no-gpu --expect-renderer software --min-fps 20
uv run test/ui.py --runtime "$RUNTIME" --image "$TEST_IMAGE" --no-gpu --backends wayland
uv run test/kiosk.py --runtime "$RUNTIME" --image "$TEST_IMAGE" --no-gpu --backends wayland --modes vnc web
```

Install Chromium on the host first. `uv` supplies Playwright and Pillow; the test
uses the system `chromium` executable. Default thresholds are 25 visible fps and
150 ms keyboard p95 on local transport. The software example uses a 20 fps budget;
thresholds can be adjusted for slower CI hosts.
JSON timings, renderer information, logs and screenshots survive teardown under
`test/.artifacts/performance-*`. The production image excludes both test programs.
For no-GPU testing, Docker masks `/dev/dri`; rootless Podman also omits privileged
device imports while keeping systemd's capabilities. The renderer assertion checks
that the test really exercised software rendering.

To verify NVIDIA acceleration in the nested regression suite:

```bash
# Select the image you rebuilt. --expect-renderer rejects llvmpipe/QPainter.
python3 test/integration.py --runtime docker --image plasma6:fedora-44 \
  --gpus all --expect-renderer gpu --modes nested --backends wayland \
  --host-backend x11
```

For an A/B performance comparison with Fedora's original KRFB, build its
baseline target in the selected engine:

```bash
"$RUNTIME" build -f Dockerfile.fedora-44 --target ui-perf-baseline -t plasma6:perf-before .
uv run test/performance.py --runtime "$RUNTIME" --image plasma6:perf-before --measure-only
```

To reproduce the original Wayland failure, build with `-f Dockerfile.fedora-44 --target ui-baseline` and run
`test/ui.py --image plasma6:ui-baseline --backends wayland --modes vnc`. That target
contains the test editor and stock KRFB without the KWin input plugin; the drag and
text-save assertions are expected to fail.

`test/Dockerfile.uid-fixture` provides a separate account-mapping regression image
with UID/GID 2000. Run the nested integration cases against it to verify runtime
mapping on hosts with different caller IDs.

## Optional host launcher

`bin/plasma6-run` is a convenience alternative to the direct commands above:

Run it from the host checkout; it is excluded from the container image. Runtime
images keep `plasma-healthcheck` and omit the package-installation build helpers.

```bash
# Docker nested desktop: choose the image you built.
RUNTIME=docker IMAGE_TAG=plasma6:fedora-44 DISPLAY_MODE=nested ./bin/plasma6-run -d
RUNTIME=docker IMAGE_TAG=plasma6:debian-13 DISPLAY_MODE=nested ./bin/plasma6-run -d
RUNTIME=docker IMAGE_TAG=plasma6:ubuntu-26.04 DISPLAY_MODE=nested ./bin/plasma6-run -d
RUNTIME=docker IMAGE_TAG=plasma6:archlinux DISPLAY_MODE=nested ./bin/plasma6-run -d

# Rootless Podman web desktop: choose the image you built.
RUNTIME=podman IMAGE_TAG=plasma6:fedora-44 DISPLAY_MODE=web VNC_PASSWORD_FILE="$PWD/vnc-password" ./bin/plasma6-run -d
RUNTIME=podman IMAGE_TAG=plasma6:debian-13 DISPLAY_MODE=web VNC_PASSWORD_FILE="$PWD/vnc-password" ./bin/plasma6-run -d
RUNTIME=podman IMAGE_TAG=plasma6:ubuntu-26.04 DISPLAY_MODE=web VNC_PASSWORD_FILE="$PWD/vnc-password" ./bin/plasma6-run -d
RUNTIME=podman IMAGE_TAG=plasma6:archlinux DISPLAY_MODE=web VNC_PASSWORD_FILE="$PWD/vnc-password" ./bin/plasma6-run -d
```

It detects and mounts host sockets for nested mode, sets namespace/identity options,
and publishes only the selected remote mode's port. Options include
`IMAGE_TAG=plasma6:local`, `CONTAINER_NAME=plasma6`, `HOST_DISPLAY_BACKEND=auto|wayland|x11`,
`BIND_ADDRESS=127.0.0.1`, `VNC_PORT=5900`, `WEB_PORT=6080`. Port `0` requests an
available host port. Extra arguments are passed to the runtime before the image.
