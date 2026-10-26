#!/usr/bin/bash

module_plasma_enabled() { return 0; }

plasma_write_env() {
	local key=$1 value=$2
	[[ $value != *$'\n'* && $value != *$'\r'* ]] || die "$key must be a single line"
	value=${value//\\/\\\\}
	value=${value//\"/\\\"}
	printf '%s="%s"\n' "$key" "$value"
}

module_plasma_run() {
	[[ $(id -u) == 0 ]] || die 'Run PID 1 as root; desktop services run as plasma'
	local mode=${DISPLAY_MODE:-headless} backend=${DISPLAY_BACKEND:-auto}
	local host_wayland='' host_x11='' number candidate
	local host_runtime=${HOST_XDG_RUNTIME_DIR:-${XDG_RUNTIME_DIR:-/run/host/runtime}}
	local host_wayland_name=${HOST_WAYLAND_DISPLAY:-${WAYLAND_DISPLAY:-}}
	local host_display=${HOST_DISPLAY:-${DISPLAY:-}}
	local host_xauthority=${HOST_XAUTHORITY:-${XAUTHORITY:-}}

	case $mode in headless | vnc | nested | web) ;; *) die "Invalid DISPLAY_MODE '$mode'" ;; esac
	case $backend in auto | wayland | x11) ;; *) die "Invalid DISPLAY_BACKEND '$backend'" ;; esac
	if [[ -n ${TARGET_APP:-} ]]; then
		runuser -u plasma -- /usr/local/libexec/plasma-target-app --validate || die 'Invalid TARGET_APP'
	fi
	[[ ${VNC_MAX_FPS:-60} =~ ^([1-9]|[1-5][0-9]|60)$ ]] || die 'VNC_MAX_FPS must be an integer between 1 and 60'
	local software=${LIBGL_ALWAYS_SOFTWARE:-0}
	[[ $software == 0 || $software == 1 ]] || die 'LIBGL_ALWAYS_SOFTWARE must be 0 or 1'
	for number in "${DISPLAY_WIDTH:-1920}" "${DISPLAY_HEIGHT:-1080}"; do
		[[ $number =~ ^[1-9][0-9]{1,3}$ ]] || die 'Display dimensions must be between 10 and 9999'
	done

	if [[ -n $host_wayland_name ]]; then
		if [[ $host_wayland_name == /* ]]; then
			[[ -S $host_wayland_name ]] && host_wayland=$host_wayland_name
		else
			for candidate in "$host_runtime/$host_wayland_name" "/run/host/runtime/$host_wayland_name"; do
				if [[ -S $candidate ]]; then
					host_wayland=$candidate
					break
				fi
			done
		fi
	else
		for candidate in /run/host/wayland "$host_runtime"/wayland-*; do
			if [[ -S $candidate ]]; then
				host_wayland=$candidate
				break
			fi
		done
	fi
	if [[ -n ${HOST_WAYLAND_DISPLAY:-} && -z $host_wayland ]]; then
		die "HOST_WAYLAND_DISPLAY is not a mounted socket: $HOST_WAYLAND_DISPLAY"
	fi

	if [[ -n $host_display ]]; then
		if [[ $host_display =~ ^(unix)?:([0-9]+)(\.[0-9]+)?$ ]]; then
			number=${BASH_REMATCH[2]}
			if [[ -S /run/host/X11/X$number || -S /tmp/.X11-unix/X$number ]]; then
				host_x11=:$number
			fi
		fi
	else
		for candidate in /run/host/X11/X[0-9]*; do
			if [[ -S $candidate && ${candidate##*/X} =~ ^[0-9]+$ ]]; then
				host_x11=:${candidate##*/X}
				break
			fi
		done
	fi
	[[ -z ${HOST_DISPLAY:-} || -n $host_x11 ]] || die 'HOST_DISPLAY must identify a mounted local X11 socket'

	local host_backend=none
	if [[ -n $host_wayland ]]; then
		host_backend=wayland
	elif [[ -n $host_x11 ]]; then host_backend=x11; fi
	if [[ $backend == auto ]]; then
		backend=$host_backend
		[[ $backend != none ]] || backend=wayland
		if [[ $backend == x11 ]] && ! command -v startplasma-x11 >/dev/null; then backend=wayland; fi
	fi
	if [[ $backend == x11 ]] && { ! command -v startplasma-x11 >/dev/null || ! command -v kwin_x11 >/dev/null; }; then
		die 'This image has no Plasma X11 session; use DISPLAY_BACKEND=wayland'
	fi
	[[ $mode != nested || $host_backend != none ]] || die 'nested mode requires a mounted host Wayland or X11 socket'
	info "Plasma: $backend:$mode (host transport: $host_backend)"

	# Docker recreates device nodes without host ACLs; grant the local device group.
	if [[ -f /etc/plasma/opengl-software-capture && -c /dev/udmabuf ]]; then
		local buffer_gid
		buffer_gid=$(stat -c %g /dev/udmabuf)
		if ! getent group "$buffer_gid" >/dev/null; then
			groupadd --gid "$buffer_gid" plasma-udmabuf
		fi
		usermod --append --groups "$buffer_gid" plasma
	fi

	# Check access as the service user: root's device access is not sufficient.
	# An unavailable GPU also needs a software Qt Quick backend, so portal and
	# desktop applications can start without attempting an unusable EGL display.
	if [[ $software == 0 ]] && ! runuser -u plasma -- /usr/bin/python3 - <<'PY'
import os
from pathlib import Path
import sys

for device in Path('/dev/dri').glob('renderD*'):
    try:
        descriptor = os.open(device, os.O_RDWR | os.O_CLOEXEC)
    except OSError:
        continue
    os.close(descriptor)
    sys.exit(0)
sys.exit(1)
PY
	then
		software=1
		info 'Plasma: no accessible GPU render node; using software fallback'
	fi

	install -d /etc/plasma /tmp/.X11-unix
	chmod 1777 /tmp/.X11-unix
	# Copy host cookies without binding them to the host's hostname.
	if [[ -n $host_x11 && -n $host_xauthority && -r $host_xauthority ]]; then
		# Hostname-scoped host cookies must also match the container hostname.
		rm -f /etc/plasma/host-Xauthority
		touch /etc/plasma/host-Xauthority
		xauth -f "$host_xauthority" nlist | sed 's/^..../ffff/' |
			xauth -f /etc/plasma/host-Xauthority nmerge -
		chown plasma: /etc/plasma/host-Xauthority
		chmod 600 /etc/plasma/host-Xauthority
		host_xauthority=/etc/plasma/host-Xauthority
	fi
	local desktop_display=:100
	[[ $host_x11 != :100 ]] || desktop_display=:101
	local software_display=:110 software_capture=0
	[[ $host_x11 != :110 ]] || software_display=:111
	if [[ $backend == wayland && $software == 1 && ($mode == vnc || $mode == web) && ! -f /etc/plasma/opengl-software-capture ]]; then
		software_capture=1
	fi
	rm -f /etc/plasma/Xauthority
	touch /etc/plasma/Xauthority
	xauth -f /etc/plasma/Xauthority add "$desktop_display" . "$(mcookie)"
	xauth -f /etc/plasma/Xauthority add "$software_display" . "$(mcookie)"
	chown plasma: /etc/plasma/Xauthority
	chmod 600 /etc/plasma/Xauthority

	rm -f /etc/plasma/vnc-password /etc/plasma/vnc-auth
	if [[ $mode == vnc || $mode == web ]]; then
		local password=${VNC_PASSWORD:-}
		if [[ -n ${VNC_PASSWORD_FILE:-} ]]; then
			[[ -r $VNC_PASSWORD_FILE ]] || die 'VNC_PASSWORD_FILE is not readable'
			password=$(cat "$VNC_PASSWORD_FILE")
		fi
		[[ -n $password && ${#password} -le 8 && $password != *[!\ -~]* ]] ||
			die 'Set VNC_PASSWORD or VNC_PASSWORD_FILE to 1-8 printable ASCII characters (VNC protocol limit)'
		(
			umask 077
			printf '%s' "$password" >/etc/plasma/vnc-password
		)
		x11vnc -storepasswd "$password" /etc/plasma/vnc-auth >/dev/null 2>&1
		chown plasma: /etc/plasma/vnc-password /etc/plasma/vnc-auth
		chmod 600 /etc/plasma/vnc-password /etc/plasma/vnc-auth
	fi
	unset VNC_PASSWORD

	{
		plasma_write_env DISPLAY_MODE "$mode"
		plasma_write_env DISPLAY_BACKEND "$backend"
		plasma_write_env TARGET_APP "${TARGET_APP:-}"
		if [[ -n ${TARGET_APP:-} ]]; then
			plasma_write_env XDG_CONFIG_HOME /home/plasma/.config/plasma-kiosk
		fi
		plasma_write_env DISPLAY_WIDTH "${DISPLAY_WIDTH:-1920}"
		plasma_write_env DISPLAY_HEIGHT "${DISPLAY_HEIGHT:-1080}"
		plasma_write_env VNC_MAX_FPS "${VNC_MAX_FPS:-60}"
		plasma_write_env HOST_DISPLAY_BACKEND "$host_backend"
		plasma_write_env HOST_WAYLAND_DISPLAY "$host_wayland"
		plasma_write_env HOST_DISPLAY "$host_x11"
		plasma_write_env HOST_XAUTHORITY "$host_xauthority"
		plasma_write_env XDG_RUNTIME_DIR /run/plasma
		plasma_write_env DBUS_SESSION_BUS_ADDRESS unix:path=/run/plasma/bus
		plasma_write_env XDG_SESSION_TYPE "$backend"
		plasma_write_env XDG_CURRENT_DESKTOP KDE
		plasma_write_env XDG_MENU_PREFIX plasma-
		plasma_write_env XDG_SESSION_DESKTOP KDE
		plasma_write_env KDE_FULL_SESSION true
		plasma_write_env KDE_SESSION_VERSION 6
		plasma_write_env HOME /home/plasma
		plasma_write_env USER plasma
		plasma_write_env LOGNAME plasma
		plasma_write_env XAUTHORITY /etc/plasma/Xauthority
		plasma_write_env PLASMA_X11_DISPLAY "$desktop_display"
		plasma_write_env PLASMA_SOFTWARE_CAPTURE "$software_capture"
		plasma_write_env PLASMA_SOFTWARE_DISPLAY "$software_display"
		if [[ -f /etc/plasma/vnc-existing-output ]]; then
			plasma_write_env PLASMA_VNC_EXISTING_OUTPUT 1
		fi
		if [[ $backend == x11 ]]; then
			plasma_write_env DISPLAY "$desktop_display"
			plasma_write_env QT_QPA_PLATFORM xcb
		else
			plasma_write_env WAYLAND_DISPLAY wayland-0
			plasma_write_env QT_QPA_PLATFORM wayland
		fi
		plasma_write_env LIBGL_ALWAYS_SOFTWARE "$software"
		if [[ $software == 1 ]]; then
			plasma_write_env QT_QUICK_BACKEND software
		fi
		plasma_write_env LANG "${LANG:-C.UTF-8}"
	} >/etc/plasma/session.env
	chmod 644 /etc/plasma/session.env

	# 501-systemd replaces default.target; 999-exec starts PID 1.
	export MODULE_SYSTEMD_ENABLED=true
	export SYSTEMD_INIT_TARGET="plasma-$backend-$mode.target"
}
