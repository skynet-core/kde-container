# 5. File map, settings, tools and glossary

[Guide index](README.md) · [Previous: operation and testing](04-operation-and-testing.md)

This reference complements the step-by-step chapters. The checked-in files are the
source of truth for behavior; the tables describe their current roles.

## Repository map

```text
.
├── Dockerfile                     Build stages and image defaults
├── .dockerignore                  Files admitted to the build context
├── README.md                      Direct Docker/Podman run commands
├── docs/                          This guide and rendered/editable diagrams
├── config/                        Defaults installed under /etc/xdg
├── init.d/modules/                Child-image startup modules
├── systemd/system/                Profile targets and project services
├── libexec/                       Helpers called by the services
├── bin/                           Health command and optional host launcher
├── native/                        KRFB input plugin, protocol and Qt test editor
└── test/                          Init, boot, capture and interactive tests
```

### Image construction and defaults

| File | Responsibility |
| --- | --- |
| [Dockerfile](../Dockerfile) | Build packages/assets/plugin; assemble production and test targets |
| [.dockerignore](../.dockerignore) | Exclude unneeded context, including test artifacts and documentation assets |
| [config/startkderc](../config/startkderc) | Default Plasma `systemdBoot=false` for the supervised classic session path |
| [config/kscreenlockerrc](../config/kscreenlockerrc) | Disable automatic locking and locking on resume in the packaged defaults |
| [config/ksplashrc](../config/ksplashrc) | Set the packaged splash-engine default |

Per-user configuration in a persistent home can override system XDG defaults.
The defaults are not a guarantee that an old home directory has no different
settings.

### Init and units

| File/directory | Responsibility |
| --- | --- |
| [300-plasma-user.sh](../init.d/modules/300-plasma-user.sh) | Optional runtime UID/GID adjustment before services exist |
| [400-plasma.sh](../init.d/modules/400-plasma.sh) | Validate mode, detect sockets, create credentials/environment and choose target |
| [systemd/system/](../systemd/system/) | Eight profile targets and their service units |
| Image-only `/init.d/init.sh` | Inherited framework entrypoint |
| Image-only `/init.d/common/` | Inherited logging, module and unit helpers |
| Image-only `501-systemd.sh`, `999-exec.sh` | Inherited target-link preparation and PID 1 handoff |

The image-only framework files come from the
[systemd base project](https://github.com/skynet-core/systemd); they are not missing
local files in this checkout.

### Runtime helpers

| File | Responsibility |
| --- | --- |
| [plasma-host-display](../libexec/plasma-host-display) | Prepare host X11 alias and display lock after tmpfiles |
| [plasma-session](../libexec/plasma-session) | Start the correct Plasma session; put the KWin adapter on the Wayland session's PATH |
| [plasma-backend/kwin_wayland](../libexec/plasma-backend/kwin_wayland) | Add virtual/nested backend arguments and preserve wrapper descriptors |
| [plasma-xserver](../libexec/plasma-xserver) | Start Xvfb, rootful Xwayland or Xephyr |
| [plasma-vnc](../libexec/plasma-vnc) | Start KRFB virtualmonitor with its KWin input setting, or x11vnc |
| [plasma-remote-output](../libexec/plasma-remote-output) | Configure/check the sole exported Wayland output |
| [plasma-wait](../libexec/plasma-wait) | Bounded connection/readiness probes |
| [plasma-healthcheck](../bin/plasma-healthcheck) | Compose the target, desktop and transport checks for the selected profile |
| [plasma6-run](../bin/plasma6-run) | Optional host launcher: engine flags, mounts, identity and published ports |

### Native code and tests

| File | Responsibility |
| --- | --- |
| [kwin-input.cpp](../native/kwin-input.cpp) | KRFB input callbacks to KWin fake-input requests |
| [fake-input.xml](../native/fake-input.xml) | Vendored KDE Wayland protocol definition, including licensing and version 6 requests |
| [CMakeLists.txt](../native/CMakeLists.txt) | Locate libraries, generate protocol code, build plugin and test editor |
| [ui-fixture.cpp](../native/ui-fixture.cpp) | Test-only native Qt editor with a UI-triggered Save action |
| [vnc-benchmark.cpp](../native/vnc-benchmark.cpp) | Test-only native animation and keyboard acknowledgement markers |
| [krfb-low-latency.patch](../patches/krfb-low-latency.patch) | Upstream KRFB scheduling and changed-region capture fixes |
| [test.sh](../test/test.sh) | Run static, init, unit-definition and boot checks |
| [check-init.py](../test/check-init.py) | Test the real inherited init framework inside a disposable image instance |
| [integration.py](../test/integration.py) | Start the mode matrix through the host launcher and preserve evidence |
| [rfb.py](../test/rfb.py) | Shared RFB client with authentication, screenshots and input events |
| [capture-vnc.py](../test/capture-vnc.py) | Authenticate and capture substantial framebuffer content |
| [ui.py](../test/ui.py) | Measure dragging and verify UI text saved through a host file bind |
| [performance.py](../test/performance.py) | Drive Chromium/noVNC, measure visible frames and feedback, verify GPU/fallback |
| [Dockerfile.uid-fixture](../test/Dockerfile.uid-fixture) | Deliberately different account IDs for mapping regressions |

## Runtime environment settings

These are inputs recognized during container startup unless the table explicitly
says otherwise. A plain engine environment value does not automatically reach every
service; the init module selects the values written into `session.env`.

| Name | Default | Role |
| --- | --- | --- |
| `DISPLAY_MODE` | `headless` | One of `headless`, `nested`, `vnc`, `web` |
| `DISPLAY_BACKEND` | `auto` | One of `auto`, `wayland`, `x11` |
| `DISPLAY_WIDTH`, `DISPLAY_HEIGHT` | `1920`, `1080` | Initial dimensions; validated as 10–9999 |
| `PLASMA_UID`, `PLASMA_GID` | Current image account IDs | Optional account adjustment; supplied automatically by the nested launcher |
| `HOST_WAYLAND_DISPLAY` | Detected | Absolute mounted path or name relative to the host runtime mount |
| `HOST_XDG_RUNTIME_DIR` | Host hint from `XDG_RUNTIME_DIR`, otherwise `/run/host/runtime` | Search directory for host Wayland sockets |
| `HOST_DISPLAY` | Host hint from `DISPLAY`, otherwise detected | Local X11 display whose socket is mounted |
| `HOST_XAUTHORITY` | Host hint from `XAUTHORITY` | Mounted host cookie file to normalize into a private copy |
| `VNC_PASSWORD_FILE` | Unset | Password source file, taking precedence over `VNC_PASSWORD` |
| `VNC_PASSWORD` | Unset | Password source when no file is supplied |
| `VNC_MAX_FPS` | `60` | Remote update cadence, validated as an integer from 1 to 60 |
| `LIBGL_ALWAYS_SOFTWARE` | `0` | Permit preferred GPU rendering, with automatic software fallback |
| `LANG` | Supplied value or `C.UTF-8` fallback | Locale value written to the service environment |
| `INIT_LOG_LEVEL` | Base default `2` | Base-framework verbosity: errors through debug |

`PLASMA_UID/GID` are nonzero decimal IDs below 4294967295. Namespace coverage and
existing-account conflicts can still restrict which valid numbers are usable.
Host/socket hints are inputs to detection; the generated desktop environment is
private and does not reuse the host's runtime as its own.

### Generated or internal values

| Name | Meaning |
| --- | --- |
| `SYSTEMD_INIT_TARGET` | Set by the Plasma module to the selected profile, overriding an incoming target choice |
| `MODULE_SYSTEMD_ENABLED` | Enabled by the Plasma module so the base configures the default target |
| `SYSTEMD_INIT_TARGET_WANTS` | Optional inherited framework list of extra wanted units; not required for the normal profiles |
| `HOST_DISPLAY_BACKEND` in `session.env` | Detected host transport; this differs from the host launcher's input filter of the same name |
| `XDG_RUNTIME_DIR` in `session.env` | Set to `/run/plasma` for project services |
| `DBUS_SESSION_BUS_ADDRESS` | Private desktop bus at `unix:path=/run/plasma/bus` |
| `WAYLAND_DISPLAY` | `wayland-0` for the private Wayland service environment |
| `PLASMA_X11_DISPLAY` | Private X11 display, normally `:100` |
| `XDG_SESSION_TYPE` | The selected desktop backend |
| `QT_QPA_PLATFORM` | `wayland` or `xcb` for service clients |
| `PLASMA_KWIN_INPUT` | Set to `1` by the Wayland VNC helper to select the scoped plugin |
| `PLASMA_WAIT_TIMEOUT` | Helper-specific probe timeout, normally 60; health checking sets zero for its own probes |

Use `DISPLAY_MODE`/`DISPLAY_BACKEND` for ordinary profile selection. Setting the
base's target variable does not bypass the child image's startup policy. Changing
an internal helper environment variable on `docker run` also does not imply that
it is propagated through the generated service environment.

### Host-launcher options

These configure `bin/plasma6-run` on the host, not a desktop application inside the
container:

| Name | Default | Meaning |
| --- | --- | --- |
| `RUNTIME` | `docker` | Use Docker or Podman |
| `IMAGE_TAG` | `plasma6:local` | Runtime image reference |
| `CONTAINER_NAME` | `plasma6` | Name for the created container |
| `HOST_DISPLAY_BACKEND` | `auto` | Mount both available host transports, or restrict to `wayland`/`x11` |
| `BIND_ADDRESS` | `127.0.0.1` | Host address for a remote published port |
| `VNC_PORT` | `5900` | Host VNC port; `0` asks for an available host port |
| `WEB_PORT` | `6080` | Host web port; `0` asks for an available host port |

The launcher translates a requested host port `0` into the empty-host-port publish
syntax understood by both engines. These variables do not change the service's
internal port numbers. The launcher normally mounts host display sockets only in
nested mode, so other modes with backend `auto` normally choose Wayland.

## Important paths and ports

| Path/port | Role |
| --- | --- |
| `/init.d/` | Inherited init framework plus child modules |
| `/etc/systemd/system/default.target` | Symlink selecting the profile |
| `/etc/systemd/system/plasma-*.target` | Packaged mode profiles |
| `/etc/plasma/session.env` | Generated service environment; contains no VNC password value |
| `/etc/plasma/Xauthority` | Private X11 authorization cookie |
| `/etc/plasma/host-Xauthority` | Normalized private copy of host credentials when supplied |
| `/etc/plasma/vnc-password` | Private plaintext KRFB credential |
| `/etc/plasma/vnc-auth` | Private x11vnc password-file format |
| `/run/plasma/` | Desktop-owned private runtime directory |
| `/run/plasma/bus` | Private desktop D-Bus socket |
| `/run/plasma/wayland-0` | Normal private Wayland socket |
| `/run/host/wayland` | Optional bind-mounted host Wayland socket |
| `/run/host/runtime/` | Alternative mount/search location for a host runtime directory |
| `/run/host/X11/` | Optional read-only host X11 socket directory |
| `/tmp/.X11-unix/` | Container-writable X11 directory, with private sockets and any host alias |
| `/tmp/.X<number>-lock` | Display-number reservation/lock |
| `/opt/noVNC/` | Packaged browser assets, including `vnc.html` |
| `/usr/lib64/qt6/plugins/krfb/events/kwin.so` | Native KWin event plugin |
| `/e2e-output/typed.txt` | UI test's single-file host bind mount |
| TCP 5900 | VNC/RFB server inside the container |
| TCP 6080 | Websockify HTTP/WebSocket service inside the container |

The `/usr/lib64` plugin path is the path used by this Fedora image. It is not a
cross-distribution promise about where every Qt installation stores plugins.

## Tools and components by responsibility

| Component/tool | Job in this project |
| --- | --- |
| Docker / Podman | Build images, create isolation/mounts, start and inspect containers |
| OCI runtime | Engine-selected low-level process/container setup; the repository does not select a universal runtime implementation |
| DNF | Resolve and install Fedora packages |
| `curl`, `tar`, `sha256sum` | Download, verify and extract pinned source/assets |
| Bash | Init modules, argument construction and small service helpers |
| `getent`, `id` | Look up accounts/groups and numeric identity |
| `usermod`, `groupmod`, `chown`, `chgrp` | Prepare the requested desktop identity and ownership |
| `find`, `sort`, `ln`, `install`, `chmod` | Ordered discovery, symlinks, directories and permissions |
| `mcookie`, `xauth`, `sed` | Private X11 cookies and normalized host cookie matching |
| systemd / `systemctl` | Unit lifecycle, dependencies, service credentials and status |
| systemd-tmpfiles | Boot-time handling of temporary files/directories |
| journald / `journalctl` | Service diagnostics |
| D-Bus / `dbus-daemon` / `dbus-send` | Desktop message bus, names and readiness query |
| KDE Plasma | Desktop shell and session components |
| KWin Wayland / KWin X11 | Compositor/display server or X11 window management |
| `kwin_wayland_wrapper` | Reserve socket descriptors and publish the client environment |
| Xwayland | X11 compatibility or rootful nested X desktop |
| Xephyr | X11 server nested in an X11 host window |
| Xvfb / `xdpyinfo` | Off-screen X11 display and an X11 readiness probe |
| Mesa / Qt platform plugins | Rendering APIs/software support and toolkit display connections |
| PipeWire / WirePlumber | Wayland capture stream and its session support |
| `kscreen-doctor` | Inspect and configure enabled outputs |
| KRFB virtualmonitor | Create/export the Wayland virtual monitor through VNC |
| x11vnc | Export and control the private X11 display |
| noVNC / websockify | Browser VNC client, static files and WebSocket-to-TCP bridge |
| CMake / Ninja / GCC | Configure and compile the native code in the build stage |
| Qt MOC / KDE plugin factory | Qt metadata and KRFB plugin loading |
| `wayland-scanner` / libwayland | Generated protocol calls and Wayland connection handling |
| Python | Health/readiness/output helpers and host test harnesses |
| `uv` | Host test-script dependency environment |
| ShellCheck / `systemd-analyze verify` | Shell and unit-definition checks |
| Pillow / PyCryptodome / websocket-client | Screenshot analysis, VNC authentication and WebSocket test transport |
| `rg` | Host source/artifact search; not an explicitly installed container diagnostic tool |
| Mermaid CLI / Chromium | Documentation diagram generation only |

## Glossary

| Term | Definition in this guide |
| --- | --- |
| ABI | Binary interface that compiled code and its libraries must agree on |
| API | Interface a program uses to call another component |
| Backend | Here, either the desktop session type or a compositor's chosen output implementation; the chapter specifies which |
| Bind mount | Host storage exposed through a container path |
| Bitmask | Integer whose individual bits represent independent states, such as held mouse buttons |
| Capability | A Linux permission for a category of privileged operations |
| Cgroup | A process/task group used for accounting and resource management |
| Client | A participant using a service: an app can be a Wayland client; a viewer can be a VNC client |
| Compositor | Component combining application surfaces into displayed output |
| Container | Instance created from an image, with a particular writable layer and runtime setup |
| Cookie | In X11 here, an authorization value stored in an Xauthority file |
| D-Bus name | A bus identifier such as `org.kde.plasmashell`, with an owning connected process |
| Daemon | A background service process |
| Desktop portal | D-Bus interfaces mediating desktop requests such as screen sharing and remote control |
| Endianness | Byte ordering for multibyte values; message fields and pixel storage can have different choices |
| Environment variable | Named string passed to a program; not automatically a setting for every service |
| File descriptor | A process-local handle to an open resource such as a socket |
| Framebuffer | A screen-sized or rectangular collection of pixel data |
| GID | Numeric group identifier |
| Headless | Operating without a physical/host-window display while retaining a graphical session |
| Health check | A scheduled or explicit status probe; its scope depends on what it actually tests |
| Image layer | A filesystem change packaged as part of an image |
| Init | The initial userspace process role; systemd fills it after the entrypoint preparation |
| IPC | Communication between processes |
| Keysym | A symbolic key value used in protocols such as RFB, distinct from text bytes or a hardware scan code |
| MOC | Qt's metadata/code-generation tool used for Qt objects and plugins |
| Namespace | A Linux mechanism providing a particular view of system objects |
| Nested display | A desktop rendered inside a window on another desktop |
| OCI | Container image/runtime specifications used in the container ecosystem |
| PID | Process identifier in a PID namespace |
| QPA | Qt platform abstraction, selecting a display integration such as Wayland or XCB |
| RFB | Remote Framebuffer protocol used by VNC |
| Rootful / rootless engine | Engine operation with host-root privileges or within a normal host user's privileges |
| Rootful / rootless Xwayland | Full-root-window desktop presentation or individual-window integration; a different meaning from engine privileges |
| Runtime directory | Private temporary directory for a session's sockets and other state |
| Service unit | systemd definition supervising a process and its execution environment |
| Session bus | A D-Bus instance used by a desktop session, separate here from the system bus |
| Socket | A local or network communication endpoint |
| Subordinate ID | Host-allocated UID/GID range usable in a user's container mappings |
| Surface | An application's drawable content as represented to a compositor |
| Symlink | Filesystem entry referring to another path |
| Target unit | systemd grouping representing a desired collection of units |
| `tmpfs` | Temporary, memory-backed filesystem that can use swap |
| UID | Numeric user identifier |
| VNC | Remote desktop ecosystem whose core transport protocol is RFB |
| Wayland registry | The server's advertised set of protocol interfaces available to a client |
| WebSocket | A browser-compatible persistent message transport used here to carry RFB |
| XCB | A client-side X11 library/integration used by Qt's X11 platform |
| XDG | Desktop conventions used for configuration, runtime directories and session identity |

## Further primary references

Some upstream manuals use `latest` URLs. Check the image's installed versions
before adopting a newer option; the linked project source defines this image's
configuration.

The chapters link sources near the relevant explanations. These are useful starting
points when extending the implementation:

- [skynet-core/systemd init framework](https://github.com/skynet-core/systemd)
- [Docker container run behavior](https://docs.docker.com/engine/containers/run/)
- [Podman run reference](https://docs.podman.io/en/latest/markdown/podman-run.1.html)
- [Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [systemd unit reference](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html)
- [systemd service reference](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
- [Wayland architecture](https://wayland.freedesktop.org/architecture.html)
- [D-Bus tutorial](https://dbus.freedesktop.org/doc/dbus-tutorial.html)
- [RFB protocol, RFC 6143](https://www.rfc-editor.org/rfc/rfc6143.html)
- [WebSocket protocol, RFC 6455](https://www.rfc-editor.org/rfc/rfc6455.html)
- [noVNC](https://github.com/novnc/noVNC)
- [KRFB source at the header version used by the build](https://github.com/KDE/krfb/tree/v26.08.1)
- [KWin fake-input implementation for the Plasma 6.7 branch](https://github.com/KDE/kwin/blob/Plasma/6.7/src/backends/fakeinput/fakeinputbackend.cpp)
