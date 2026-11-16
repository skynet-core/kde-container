# Private KWin 6.8.2 build

Debian 13 and Ubuntu 26.04 keep their original systemd bases and package
repositories. Their packaged Qt/KF versions do not meet [KWin 6.8.2's build
requirements](https://github.com/KDE/kwin/blob/v6.8.2/CMakeLists.txt). The
`kwin-*` Docker stages build its required stack into `/opt/kwin-6.8.2` using
Debian 13's older glibc. With the default `KWIN_VARIANT=source`, both final
images copy the same runtime payload. Only `TARGET_APP` kiosk sessions activate
it; full Plasma sessions retain their distribution compositor and desktop features.

`--build-arg KWIN_VARIANT=distro` selects an empty overlay stage instead. BuildKit
skips the entire Qt/KF/KWin source dependency graph and the image uses its distro
compositor. Debian's older NVIDIA remote compositor uses its software fallback
in that variant; the source 6.8.2 kiosk variant keeps normal GPU selection.

| Component | Version |
| --- | --- |
| KWin, KDecoration, KWayland, KNightTime, KScreen | 6.8.2 |
| Qt | 6.11.2 |
| KDE Frameworks | 6.30.0 |
| Wayland | 1.26.0 |
| wayland-protocols | 1.49 |
| plasma-wayland-protocols | 1.23.0 |
| libdrm | 2.4.127 |
| Vulkan headers | SDK 1.4.363.0 |

Source URLs and SHA-256 checksums are recorded in
[`kwin-6.8.2-sources.tsv`](kwin-6.8.2-sources.tsv) and
[`kwin-vulkan-sources.tsv`](kwin-vulkan-sources.tsv), and
[`kwin-client-sources.tsv`](kwin-client-sources.tsv). Every downloaded archive
is verified before extraction. KWin's source is compiled without patches.
The newer Vulkan C++ headers are build dependencies; the distro Vulkan loader
and GPU drivers remain runtime dependencies.

Qt builds only qtbase, qtsvg, qtshadertools, qtdeclarative, qttools,
qt5compat and qtpositioning. In Qt 6.11, qtbase supplies WaylandClient and its
scanner; a separate QtWaylandCompositor build is unnecessary. Qt uses bundled
JPEG and omits ICU to avoid Debian-only library SONAMEs on Ubuntu. KDE builds
the Frameworks required by KWin and KNightTime, plus PolkitQt. The KWin kiosk
build omits configuration modules, desktop overview, notifications, tabbox,
screen locker, activities, decorations and shortcut configuration.

The collector strips development headers, static libraries, SDK metadata and
documentation. A private copy of `libdisplay-info.so.2` preserves its ABI on
Ubuntu. Source license files are retained. KWin's file capability is removed
so its loader honors the private library paths in nested and remote modes.

Only the compositor and its cache builder use the private libraries, plugins
and QML paths. Its target application has the original environment restored.
The output selector uses the matching private `kscreen-doctor`, since KWin
6.8's new output-device registry cannot be discovered by older KScreen.
KRFB, clipboard helpers and other distro Qt clients run as separate processes
with their distro libraries. This keeps both Qt versions out of any single
process. Host regressions verify the compositor/application environment boundary;
the GUI suites record the actual compositor renderer. Installing the overlay
does not select its KScreen client or disable the older compositor's GPU
workaround in a full desktop session.

Build the payload alone with:

```sh
docker build --target kwin-artifacts -f Dockerfile.debian-13 .
```

Each source phase has its own cached stage. The final `plasma6` image copies only
the collected runtime tree; source archives, compilers and build tools stay
in the builder stages.

## CI artifact cache

CI exports all intermediate stages to GHCR with BuildKit's `mode=max`, including
compiled Qt, Frameworks, KWin, KRFB, TigerVNC and Xwayland layers. Later builds
pull matching layers and copy their artifacts into the runtime image. BuildKit
invalidates only stages affected by source, patch, command or base-image changes.

Tags are `ghcr.io/skynet-core/kde-container:buildcache-<distro>-<scope>`.
Main writes the shared `main` scope. Each same-repository PR writes its own
`pr-<number>` scope and reads both that and main; other manual/tag builds use
`sha-<commit>`. Fork and Dependabot PRs only read caches. Existing Actions caches
remain a read-only migration source, avoiding further large uploads to the
repository's Actions cache quota. Cache publication is independent of production
image publication; all existing runtime acceptance gates still run.
New runs queue behind the running workflow, keeping only the newest pending run,
so source compilation can finish exporting its cache before the next revision.
The native regression SDK has its own `native` cache and shares matching build
layers with the Fedora image job. Native containers use `--init` so Xvfb can
deliver its readiness signal to the test launcher below PID 1.
Its source dependency stage is exported before compiling the regression tests,
so test-build failures preserve the completed dependency cache.

Fedora and Arch retain their distribution Wayland compositor and build the
separate, namespaced KWin-X11 6.7.5 release with `build/arch-kwin-x11`. Arch no
longer packages X11 KWin, while Fedora's KWin 6.8 conflicts with its older X11
RPM. The shared builder verifies its pinned archive, derives `/usr/lib` or
`/usr/lib64` from the distro Qt SDK, and rejects output that replaces Wayland
KWin or its library. Only runtime artifacts and required runtime packages reach
the final image. Debian and Ubuntu continue using their packaged X11 compositor.
