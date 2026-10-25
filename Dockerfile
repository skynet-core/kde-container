# syntax=docker/dockerfile:1
ARG BASE_IMAGE=ghcr.io/skynet-core/systemd:fedora-44
FROM ${BASE_IMAGE} AS desktop-packages

ARG PLASMA_UID=1000
ARG PLASMA_GID=1000
ARG NOVNC_VERSION=1.7.0
ARG NOVNC_SHA256=b1003a11b6e6e8d8f7f5e5586daae7f8ca651d8aee0aa155ff9ac841c48f52c6

USER root
RUN dnf install -y \
        plasma-desktop plasma-workspace plasma-workspace-x11 kwin kwin-x11 \
        konsole dolphin breeze-icon-theme google-noto-sans-fonts \
        mesa-dri-drivers mesa-libEGL mesa-libGL mesa-libgbm \
        qt6-qtwayland xorg-x11-server-Xwayland xorg-x11-server-Xephyr \
        xorg-x11-server-Xvfb xdpyinfo xorg-x11-xauth \
        krfb x11vnc pipewire wireplumber xdg-desktop-portal-kde \
        python3 python3-websockify dbus-tools util-linux shadow-utils \
        curl ca-certificates tar gzip \
    && dnf clean all \
    && groupadd --gid "${PLASMA_GID}" plasma \
    && useradd --uid "${PLASMA_UID}" \
        --gid plasma --create-home \
        --shell /bin/bash plasma \
    && install -d -m 1777 /tmp/.X11-unix \
    && install -d /etc/plasma /opt/noVNC \
    && curl --fail --location --retry 3 \
        "https://codeload.github.com/novnc/noVNC/tar.gz/refs/tags/v${NOVNC_VERSION}" \
        --output /tmp/novnc.tar.gz \
    && echo "${NOVNC_SHA256}  /tmp/novnc.tar.gz" | sha256sum --check - \
    && tar -xzf /tmp/novnc.tar.gz --strip-components=1 -C /opt/noVNC \
    && ln -s vnc.html /opt/noVNC/index.html \
    && rm /tmp/novnc.tar.gz

FROM desktop-packages AS desktop
# Extend the inherited /init.d/init.sh; 400 runs before 501-systemd and 999-exec.
COPY init.d/modules/ /init.d/modules/
COPY bin/ /usr/local/bin/
COPY libexec/ /usr/local/libexec/
COPY systemd/system/ /etc/systemd/system/
COPY config/ /etc/xdg/
RUN chmod +x /init.d/modules/*.sh /usr/local/bin/* /usr/local/libexec/* \
        /usr/local/libexec/plasma-backend/kwin_wayland \
    && command -v kscreen-doctor \
    && systemctl mask getty.target console-getty.service systemd-udevd.service

ENV MODULE_SYSTEMD_ENABLED=true \
    DISPLAY_BACKEND=auto \
    DISPLAY_MODE=headless \
    DISPLAY_WIDTH=1920 \
    DISPLAY_HEIGHT=1080

EXPOSE 5900 6080
HEALTHCHECK --interval=10s --timeout=5s --start-period=90s --retries=6 \
    CMD ["/usr/local/bin/plasma-healthcheck"]

# PID 1 must remain root. The desktop and remote services use User=plasma.
STOPSIGNAL SIGRTMIN+3
ENTRYPOINT ["/init.d/init.sh"]
CMD ["/usr/sbin/init", "--system"]

# KRFB's virtual monitor has no portal session. Build its KWin input plugin
# against the same private library as the runtime, leaving compilers out of it.
FROM desktop-packages AS input-build
ARG KRFB_SOURCE_VERSION=26.08.1
ARG KRFB_SOURCE_SHA256=fb2e89fb9defdf5d3acd1cac172863b0adc45793961210c152ef3872fb875f5d
RUN dnf install -y cmake ninja-build gcc-c++ qt6-qtbase-devel \
        kf6-kcoreaddons-devel wayland-devel libvncserver-devel \
    && dnf clean all \
    && curl --fail --location --retry 3 \
        "https://codeload.github.com/KDE/krfb/tar.gz/refs/tags/v${KRFB_SOURCE_VERSION}" \
        --output /tmp/krfb.tar.gz \
    && echo "${KRFB_SOURCE_SHA256}  /tmp/krfb.tar.gz" | sha256sum --check - \
    && mkdir /krfb-source \
    && tar -xzf /tmp/krfb.tar.gz --strip-components=1 -C /krfb-source
COPY native/ /src/
RUN cmake -S /src -B /build -G Ninja -DKRFB_SOURCE_DIR=/krfb-source \
    && cmake --build /build

# Baseline target intentionally retains stock KRFB, for reproducing the regression.
FROM desktop AS ui-baseline
COPY --from=input-build /build/plasma-ui-fixture /usr/local/bin/plasma-ui-fixture

FROM desktop AS input-runtime
COPY --from=input-build /build/kwin.so /usr/lib64/qt6/plugins/krfb/events/kwin.so
RUN sed -i '/^X-KDE-Wayland-Interfaces=/s/$/,org_kde_kwin_fake_input/' \
        /usr/share/applications/org.kde.krfb.virtualmonitor.desktop

# Keep a working-input image with Fedora's unmodified KRFB for A/B benchmarks.
FROM input-runtime AS ui-perf-baseline
COPY --from=input-build /build/plasma-vnc-benchmark /usr/local/bin/plasma-vnc-benchmark

# Rebuild upstream's virtual monitor and capture plugin with small latency fixes.
# Event plugins and libkrfbprivate remain the Fedora packages.
FROM input-build AS vnc-build
RUN dnf install -y patch extra-cmake-modules qt6-qtbase-private-devel \
        kf6-kconfig-devel kf6-ki18n-devel kf6-kdbusaddons-devel kf6-kdnssd-devel \
        kf6-kdoctools-devel kf6-knotifications-devel kf6-kwallet-devel \
        kf6-kwidgetsaddons-devel kf6-kwindowsystem-devel kf6-kxmlgui-devel \
        kf6-kstatusnotifieritem-devel kf6-kcrash-devel \
        libxcb-devel xcb-util-image-devel libXdamage-devel libXtst-devel \
    && dnf clean all
RUN dnf install -y lzo-devel libjpeg-turbo-devel libpng-devel libgcrypt-devel \
        gnutls-devel openssl-devel systemd-devel zlib-devel kpipewire-devel pipewire-devel \
        plasma-wayland-protocols-devel kwayland-devel qt6-qtwayland-devel \
    && dnf clean all
COPY patches/krfb-low-latency.patch /tmp/krfb-low-latency.patch
RUN patch --batch --fuzz=0 -d /krfb-source -p1 < /tmp/krfb-low-latency.patch \
    && cmake -S /krfb-source -B /krfb-build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    && cmake --build /krfb-build --target krfb-virtualmonitor krfb_framebuffer_pw

FROM input-runtime AS runtime
COPY --from=vnc-build /krfb-build/bin/krfb-virtualmonitor /usr/bin/krfb-virtualmonitor
COPY --from=vnc-build /krfb-build/bin/pw.so /usr/lib64/qt6/plugins/krfb/framebuffer/pw.so

FROM runtime AS ui-test
COPY --from=input-build /build/plasma-ui-fixture /usr/local/bin/plasma-ui-fixture
COPY --from=input-build /build/plasma-vnc-benchmark /usr/local/bin/plasma-vnc-benchmark

FROM runtime AS plasma6
