"""Exercise compositor, viewer and application environment policies without a desktop."""

import configparser
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "libexec/plasma-target-app"
LOADER = importlib.machinery.SourceFileLoader("plasma_target_app", str(SOURCE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
APP = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(APP)
REMOTE_LOADER = importlib.machinery.SourceFileLoader(
    "plasma_remote_output", str(SOURCE.parent / "plasma-remote-output")
)
REMOTE_SPEC = importlib.util.spec_from_loader(REMOTE_LOADER.name, REMOTE_LOADER)
REMOTE = importlib.util.module_from_spec(REMOTE_SPEC)
with patch.dict(os.environ, {"DISPLAY_BACKEND": "x11"}):
    REMOTE_LOADER.exec_module(REMOTE)
GPU_LOADER = importlib.machinery.SourceFileLoader(
    "plasma_gpu", str(SOURCE.parent / "plasma-gpu")
)
GPU_SPEC = importlib.util.spec_from_loader(GPU_LOADER.name, GPU_LOADER)
GPU = importlib.util.module_from_spec(GPU_SPEC)
GPU_LOADER.exec_module(GPU)


def shell_calls(source, environment, executables, arguments=()):
    """Run the real shell flow with recorders only at executable boundaries."""
    with tempfile.TemporaryDirectory() as directory:
        for executable in executables:
            stub = Path(directory) / Path(executable).name
            stub.write_text(
                "#!/usr/bin/python3\nimport json, os, sys\n"
                'if sys.argv[1:] == ["--help"]: print("ShortcutModifiers"); sys.exit()\n'
                'print(json.dumps({"program": os.path.basename(sys.argv[0]), '
                '"argv": sys.argv[1:], "environment": {key: os.environ.get(key) '
                'for key in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", '
                '"LIBGL_ALWAYS_SOFTWARE", "XDG_SESSION_TYPE", "DBUS_SESSION_BUS_ADDRESS")}}), flush=True)\n'
            )
            stub.chmod(0o755)
            source = source.replace(executable, str(stub))
        result = subprocess.run(
            ["/bin/bash", "-c", source, "plasma-test", *arguments],
            env={**os.environ, **environment},
            text=True,
            capture_output=True,
            check=True,
        )
        return [json.loads(line) for line in result.stdout.splitlines()]


class RenderingPolicyTests(unittest.TestCase):
    def test_modern_frontend_cli_uses_private_precision_fixed_server_without_preload_changes(
        self,
    ):
        helper = SOURCE.parent / "plasma-nested-x11"
        program = '''exec() { printf '%s\\0' "$@" "PRELOAD=${LD_PRELOAD-}" "ORIGINAL=${PLASMA_KWIN_ORIGINAL_LD_PRELOAD-}"; exit 0; }; source "$1" "${@:2}"'''
        for original in ("", "libm.so.6"):
            with self.subTest(original=original):
                result = subprocess.run(
                    ["/bin/bash", "-c", program, "test", str(helper), "--display"],
                    env={
                        "HOST_WAYLAND_DISPLAY": "/run/host/wayland",
                        "PLASMA_SOFTWARE_DISPLAY": ":110",
                        "DISPLAY_WIDTH": "1280",
                        "DISPLAY_HEIGHT": "960",
                        "LD_PRELOAD": original,
                    },
                    capture_output=True,
                    check=True,
                )
                values = result.stdout.decode().split("\0")
                self.assertEqual(
                    values[:2], ["/usr/local/libexec/plasma-xwayland", ":110"]
                )
                self.assertIn("-hidpi", values)
                self.assertIn("-decorate", values)
                self.assertIn("ORIGINAL=", values)
                self.assertIn("PRELOAD=" + original, values)

    def test_scaled_frontend_requires_matching_guest_scale_and_physical_mode(self):
        environment = {
            "DISPLAY_BACKEND": "wayland",
            "DISPLAY_MODE": "nested",
            "HOST_DISPLAY_BACKEND": "wayland",
            "PLASMA_SOFTWARE_NESTED": "1",
            "PLASMA_SOFTWARE_CAPTURE": "0",
            "DISPLAY_WIDTH": "800",
            "DISPLAY_HEIGHT": "600",
        }
        for scale, width, height in (
            (1, 800, 600),
            (1.2, 960, 720),
            (1.25, 1000, 750),
            (4 / 3, 1067, 800),
            (2, 1600, 1200),
        ):
            current = {
                "enabled": True,
                "id": 3,
                "name": "Virtual-Plasma",
                "pos": {"x": 0, "y": 0},
                "scale": scale,
                "currentModeId": 2,
                "modes": [{"id": "2", "size": {"width": width, "height": height}}],
            }
            with (
                self.subTest(scale=scale),
                patch.dict(os.environ, environment, clear=True),
                patch.object(REMOTE, "frontend_scale", return_value=scale),
            ):
                self.assertTrue(REMOTE.configured([current]))
                self.assertFalse(
                    REMOTE.configured([{**current, "scale": scale + 0.25}])
                )
                self.assertFalse(REMOTE.configured([{**current, "currentModeId": 99}]))
                for dimensions in (
                    {"width": width + 1, "height": height},
                    {"width": width, "height": height + 1},
                ):
                    self.assertFalse(
                        REMOTE.configured(
                            [{**current, "modes": [{"id": "2", "size": dimensions}]}]
                        )
                    )

    def test_scaled_readiness_does_not_change_legacy_x11_or_public_output_contracts(
        self,
    ):
        base = {
            "DISPLAY_BACKEND": "wayland",
            "DISPLAY_MODE": "nested",
            "HOST_DISPLAY_BACKEND": "wayland",
            "PLASMA_SOFTWARE_NESTED": "1",
            "PLASMA_SOFTWARE_CAPTURE": "0",
        }
        for override, name in (
            ({"PLASMA_SOFTWARE_CAPTURE": "1"}, "X11-0"),
            ({"DISPLAY_BACKEND": "x11", "PLASMA_NVIDIA_NESTED": "1"}, "Virtual-Plasma"),
            ({"HOST_DISPLAY_BACKEND": "x11"}, "Virtual-Plasma"),
            ({"DISPLAY_MODE": "vnc"}, "Virtual-Plasma"),
            ({"PLASMA_SOFTWARE_NESTED": "0"}, "Virtual-Plasma"),
        ):
            with (
                self.subTest(override=override),
                patch.dict(os.environ, {**base, **override}, clear=True),
                patch.object(
                    REMOTE,
                    "frontend_scale",
                    side_effect=AssertionError(
                        "Legacy path must not inspect modern frontend"
                    ),
                ),
            ):
                self.assertTrue(
                    REMOTE.configured(
                        [{"enabled": True, "name": name, "pos": {"x": 0, "y": 0}}]
                    )
                )

    def application_readiness(self, snapshots, *, never=False):
        class Started(Exception):
            pass

        now, checks = 0.0, []
        current = None
        environment = {
            "TARGET_APP": "/bin/true",
            "DISPLAY_BACKEND": "wayland",
            "DISPLAY_MODE": "nested",
            "HOST_DISPLAY_BACKEND": "wayland",
            "PLASMA_SOFTWARE_NESTED": "1",
            "PLASMA_SOFTWARE_CAPTURE": "0",
            "DISPLAY_WIDTH": "800",
            "DISPLAY_HEIGHT": "600",
        }

        def sleep(seconds):
            nonlocal now
            now += seconds

        def frontend():
            if current[0] is None:
                raise ValueError("Frontend metadata is not available")
            return current[0]

        def command(arguments, **_settings):
            nonlocal current
            if arguments == ["/usr/local/libexec/plasma-wait", "compositor"]:
                return subprocess.CompletedProcess(arguments, 0)
            self.assertEqual(
                arguments, ["/usr/local/libexec/plasma-remote-output", "--check"]
            )
            current = snapshots[min(len(checks), len(snapshots) - 1)]
            _front, guest, width, height = current
            output = {
                "enabled": True,
                "name": "Virtual-Plasma",
                "pos": {"x": 0, "y": 0},
                "scale": guest,
                "currentModeId": 1,
                "modes": [{"id": "1", "size": {"width": width, "height": height}}],
            }
            try:
                agreed = REMOTE.configured([output])
            except ValueError:
                agreed = False
            checks.append(agreed)
            return subprocess.CompletedProcess(arguments, 0 if agreed else 1)

        def start(arguments, **settings):
            self.assertEqual(arguments, ["/bin/true"])
            self.assertEqual(checks, [False, False, False, False, True])
            self.assertEqual(REMOTE.frontend_scale(), 1.25)
            self.assertEqual(current, (1.25, 1.25, 1000, 750))
            self.assertEqual(settings["env"]["DISPLAY_WIDTH"], "800")
            self.assertEqual(settings["env"]["DISPLAY_HEIGHT"], "600")
            raise Started

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, environment, clear=True),
            patch.object(sys, "argv", [str(SOURCE)]),
            patch.object(APP, "STATE", Path(directory) / "state.json"),
            patch.object(APP.signal, "signal"),
            patch.object(APP.time, "monotonic", side_effect=lambda: now),
            patch.object(APP.time, "sleep", side_effect=sleep),
            patch.object(REMOTE, "frontend_scale", side_effect=frontend),
            patch.object(APP.subprocess, "run", side_effect=command),
            patch.object(APP.subprocess, "Popen", side_effect=start) as popen,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            if never:
                with self.assertRaisesRegex(
                    RuntimeError, "Kiosk output did not become ready"
                ):
                    APP.main()
                popen.assert_not_called()
                self.assertFalse(any(checks))
            else:
                with self.assertRaises(Started):
                    APP.main()
                popen.assert_called_once()
        return checks

    def test_application_waits_for_late_and_changed_frontend_metadata_before_popen(
        self,
    ):
        checks = self.application_readiness(
            [
                (None, 1, 800, 600),
                (1.25, 1, 1000, 750),
                (1.5, 1.25, 1000, 750),
                (1.25, 1.25, 1000, 749),
                (1.25, 1.25, 1000, 750),
            ]
        )
        self.assertEqual(checks, [False, False, False, False, True])

    def test_application_never_popens_without_matching_frontend_and_guest_output(self):
        for snapshot in ((None, 1.25, 1000, 750), (1.25, 1, 800, 600)):
            with self.subTest(snapshot=snapshot):
                self.application_readiness([snapshot], never=True)

    def test_window_policy_is_generic_and_applies_only_to_normal_windows(self):
        for mode in (None, "fullscreen", "maximized"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                environment = {"XDG_CONFIG_HOME": directory}
                if mode is not None:
                    environment["TARGET_APP_WINDOW_MODE"] = mode
                with patch.dict(os.environ, environment, clear=True):
                    APP.configure()
                config = configparser.ConfigParser()
                config.read(Path(directory) / "kwinrulesrc")
                rule = config["1"]
                self.assertEqual(rule["types"], "1")
                self.assertEqual(rule["noborder"], "true")
                self.assertEqual(rule["noborderrule"], "2")
                if mode == "maximized":
                    self.assertNotIn("fullscreen", rule)
                    for axis in ("horiz", "vert"):
                        self.assertEqual(rule[f"maximize{axis}"], "true")
                        self.assertEqual(rule[f"maximize{axis}rule"], "2")
                else:
                    self.assertEqual(rule["fullscreen"], "true")
                    self.assertEqual(rule["fullscreenrule"], "2")
                    self.assertNotIn("maximizehoriz", rule)
                    self.assertNotIn("maximizevert", rule)

    def test_invalid_window_policy_is_rejected_by_the_real_validation_entrypoint(self):
        for mode in ("borderless", "", "maximized\n"):
            with self.subTest(mode=mode):
                result = subprocess.run(
                    [str(SOURCE), "--validate"],
                    env={
                        **os.environ,
                        "TARGET_APP": "/bin/true",
                        "TARGET_APP_WINDOW_MODE": mode,
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("TARGET_APP_WINDOW_MODE", result.stderr)

    def test_x11_viewer_passes_shortcut_keys_through_old_and_new_versions(self):
        helper = SOURCE.parent / "plasma-nested-x11"
        with tempfile.TemporaryDirectory() as directory:
            viewer = Path(directory) / "viewer"
            viewer.write_text(
                '#!/bin/bash\nif [[ $1 == --help ]]; then printf "%s\\n" "$VIEWER_HELP"; '
                'else printf "%s\\n" "$@"; printf "DISPLAY=%s\\n" "$DISPLAY"; '
                'printf "SOFTWARE=%s\\n" "$LIBGL_ALWAYS_SOFTWARE"; fi\n'
            )
            viewer.chmod(0o755)
            for help_text, expected, software in (
                ("MenuKey", "-MenuKey=", "0"),
                ("MenuKey", "-MenuKey=", "1"),
                ("ShortcutModifiers", "-ShortcutModifiers=", "0"),
                ("ShortcutModifiers", "-ShortcutModifiers=", "1"),
            ):
                with self.subTest(version=help_text, software=software):
                    result = subprocess.run(
                        [
                            "/bin/bash",
                            "-c",
                            helper.read_text().replace(
                                "/usr/bin/vncviewer", str(viewer)
                            ),
                        ],
                        env={
                            **os.environ,
                            "VIEWER_HELP": help_text,
                            "LIBGL_ALWAYS_SOFTWARE": software,
                            "HOST_DISPLAY_BACKEND": "x11",
                            "HOST_DISPLAY": ":42",
                            "HOST_XAUTHORITY": "/tmp/host-auth",
                            "DISPLAY_WIDTH": "800",
                            "DISPLAY_HEIGHT": "600",
                        },
                        text=True,
                        capture_output=True,
                        check=True,
                    )
                    self.assertIn(expected, result.stdout.splitlines())
                    self.assertIn("DISPLAY=unix/:42", result.stdout.splitlines())
                    self.assertIn("SOFTWARE=" + software, result.stdout.splitlines())
                    self.assertIn("-AcceptClipboard=0", result.stdout.splitlines())
                    self.assertIn("127.0.0.1::5900", result.stdout.splitlines())

    def test_software_x11_relay_uses_virtual_kwin_without_changing_native_paths(self):
        adapter = SOURCE.parent / "plasma-backend/kwin_wayland"
        with tempfile.TemporaryDirectory() as directory:
            compositor = Path(directory) / "kwin"
            compositor.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
            compositor.chmod(0o755)
            for mode, host, relay, expected, absent in (
                ("nested", "x11", "1", "--virtual", "--x11-display"),
                ("nested", "x11", "0", "--x11-display", "--virtual"),
                ("nested", "wayland", "0", "--wayland-display", "--virtual"),
                ("nested", "wayland", "1", "--virtual", "--wayland-display"),
                ("headless", "none", "0", "--virtual", "--x11-display"),
            ):
                with self.subTest(mode=mode, host=host, relay=relay):
                    result = subprocess.run(
                        ["/bin/bash", str(adapter)],
                        env={
                            **os.environ,
                            "DISPLAY_MODE": mode,
                            "HOST_DISPLAY_BACKEND": host,
                            "PLASMA_SOFTWARE_NESTED": relay,
                            "PLASMA_SOFTWARE_CAPTURE": "0",
                            "PLASMA_NVIDIA_SYNC": "0",
                            "PLASMA_KWIN_BINARY": str(compositor),
                            "HOST_DISPLAY": ":42",
                            "HOST_XAUTHORITY": "/tmp/host-auth",
                            "HOST_WAYLAND_DISPLAY": "/tmp/host-wayland",
                            "DISPLAY_WIDTH": "800",
                            "DISPLAY_HEIGHT": "600",
                        },
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    self.assertIn(expected, result.stdout.splitlines())
                    self.assertNotIn(absent, result.stdout.splitlines())

    def test_nested_presentation_selects_legacy_capture_without_changing_renderer(
        self,
    ):
        module = (SOURCE.parents[1] / "init.d/modules/400-plasma.sh").read_text()
        start = module.index(
            "\tif [[ $backend == wayland", module.index("software_capture=1")
        )
        end = module.index("\tif [[ $backend == x11 && $mode == nested", start)
        for backend, software, mode, host, opengl, expected, capture in (
            ("wayland", "1", "nested", "wayland", "1", "1", "0"),
            ("wayland", "1", "nested", "x11", "1", "1", "0"),
            ("wayland", "0", "nested", "wayland", "1", "1", "0"),
            ("wayland", "0", "nested", "x11", "1", "1", "0"),
            ("wayland", "0", "nested", "wayland", "0", "0", "0"),
            ("wayland", "0", "nested", "x11", "0", "0", "0"),
            ("wayland", "1", "nested", "wayland", "0", "1", "1"),
            ("wayland", "1", "nested", "x11", "0", "0", "0"),
            ("wayland", "1", "headless", "none", "1", "0", "0"),
            ("wayland", "1", "vnc", "none", "1", "0", "0"),
            ("wayland", "1", "web", "none", "1", "0", "0"),
            ("x11", "1", "nested", "wayland", "1", "0", "0"),
        ):
            with self.subTest(
                backend=backend, software=software, mode=mode, host=host, opengl=opengl
            ):
                result = subprocess.run(
                    [
                        "/bin/bash",
                        "-c",
                        "set -euo pipefail\nsoftware_nested=0\nsoftware_capture=0\n"
                        + module[start:end]
                        + '\nprintf "%s\n" "$software_nested" "$software_capture" "$software" "$render_node"',
                    ],
                    env={
                        **os.environ,
                        "backend": backend,
                        "software": software,
                        "mode": mode,
                        "host_backend": host,
                        "opengl_software": opengl,
                        "render_node": "/dev/dri/renderD128" if software == "0" else "",
                    },
                    text=True,
                    capture_output=True,
                    check=True,
                )
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        expected,
                        capture,
                        software,
                        "/dev/dri/renderD128" if software == "0" else "",
                    ],
                )

    def test_modern_frontend_is_created_early_with_hidpi_then_reused(self):
        environment = {
            "DISPLAY_BACKEND": "wayland",
            "DISPLAY_MODE": "nested",
            "HOST_DISPLAY_BACKEND": "wayland",
            "HOST_WAYLAND_DISPLAY": "/private-host/wayland",
            "PLASMA_SOFTWARE_DISPLAY": ":110",
            "PLASMA_SOFTWARE_CAPTURE": "0",
            "PLASMA_SOFTWARE_NESTED": "1",
            "DISPLAY_WIDTH": "800",
            "DISPLAY_HEIGHT": "600",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/plasma/bus",
        }
        delegate = shell_calls(
            (SOURCE.parent / "plasma-software-display").read_text(),
            environment,
            ("/usr/local/libexec/plasma-nested-x11",),
        )[0]
        self.assertEqual(delegate["program"], "plasma-nested-x11")
        self.assertEqual(delegate["argv"], ["--display"])
        frontend = shell_calls(
            (SOURCE.parent / "plasma-nested-x11").read_text(),
            environment,
            ("/usr/local/libexec/plasma-xwayland",),
            arguments=("--display",),
        )[0]
        self.assertEqual(
            frontend["argv"][:3], [":110", "-auth", "/etc/plasma/Xauthority"]
        )
        for flag in ("-decorate", "-hidpi", "-shm", "-nolisten", "tcp"):
            self.assertIn(flag, frontend["argv"])
        self.assertEqual(
            frontend["environment"]["WAYLAND_DISPLAY"], "/private-host/wayland"
        )

        guest_bus = environment["DBUS_SESSION_BUS_ADDRESS"]
        self.assertEqual(delegate["environment"]["DBUS_SESSION_BUS_ADDRESS"], guest_bus)
        self.assertEqual(
            frontend["environment"]["DBUS_SESSION_BUS_ADDRESS"],
            "unix:path=/dev/null",
        )
        late = shell_calls(
            (SOURCE.parent / "plasma-nested-x11").read_text(),
            environment,
            (
                "/usr/local/libexec/plasma-wait",
                "/usr/bin/vncviewer",
                "dbus-run-session",
            ),
        )
        self.assertEqual(
            [call["program"] for call in late], ["plasma-wait", "dbus-run-session"]
        )
        for call in late:
            self.assertEqual(call["environment"]["DBUS_SESSION_BUS_ADDRESS"], guest_bus)
        guest = shell_calls(
            (SOURCE.parent / "plasma-session").read_text(),
            {**environment, "TARGET_APP": ""},
            ("/usr/bin/startplasma-wayland",),
        )[0]
        self.assertEqual(guest["program"], "startplasma-wayland")
        self.assertEqual(guest["environment"]["DBUS_SESSION_BUS_ADDRESS"], guest_bus)

    def test_legacy_backing_and_frontend_use_separate_authenticated_displays(self):
        helper = SOURCE.parent / "plasma-nested-x11"
        environment = {
            "DISPLAY_BACKEND": "wayland",
            "DISPLAY_MODE": "nested",
            "PLASMA_SOFTWARE_NESTED": "1",
            "HOST_DISPLAY_BACKEND": "wayland",
            "HOST_WAYLAND_DISPLAY": "/private-host/wayland",
            "PLASMA_X11_DISPLAY": ":100",
            "PLASMA_SOFTWARE_DISPLAY": ":110",
            "DISPLAY_WIDTH": "800",
            "DISPLAY_HEIGHT": "600",
        }
        for capture, software, frontend in (
            ("1", "1", ":100"),
            ("0", "1", ":110"),
            ("0", "0", ":110"),
        ):
            with self.subTest(capture=capture, software=software):
                records = shell_calls(
                    helper.read_text(),
                    {
                        **environment,
                        "PLASMA_SOFTWARE_CAPTURE": capture,
                        "LIBGL_ALWAYS_SOFTWARE": software,
                    },
                    (
                        "/usr/bin/Xwayland",
                        "/usr/local/libexec/plasma-wait",
                        "/usr/bin/vncviewer",
                        "dbus-run-session",
                    ),
                )
                calls = {row["program"]: row for row in records}
                if capture == "1":
                    self.assertEqual(calls["Xwayland"]["argv"][0], frontend)
                    self.assertEqual(
                        calls["Xwayland"]["argv"][1:3],
                        ["-auth", "/etc/plasma/Xauthority"],
                    )
                    self.assertIn("-decorate", calls["Xwayland"]["argv"])
                    self.assertNotIn("-hidpi", calls["Xwayland"]["argv"])
                else:
                    self.assertNotIn("Xwayland", calls)
                for name in ("plasma-wait", "dbus-run-session"):
                    self.assertEqual(calls[name]["environment"]["DISPLAY"], frontend)
                    self.assertEqual(
                        calls[name]["environment"]["XAUTHORITY"],
                        "/etc/plasma/Xauthority",
                    )
                    self.assertEqual(
                        calls[name]["environment"]["LIBGL_ALWAYS_SOFTWARE"], software
                    )
                viewer = calls["dbus-run-session"]["argv"]
                for argument in (
                    "-PasswordFile=/etc/plasma/vnc-auth",
                    "-FullColor=1",
                    "-NoJPEG=1",
                    "-AcceptClipboard=0",
                    "-SendClipboard=0",
                    "127.0.0.1::5900",
                ):
                    self.assertIn(argument, viewer)
        backing = shell_calls(
            (SOURCE.parent / "plasma-software-display").read_text(),
            {**environment, "PLASMA_SOFTWARE_CAPTURE": "1"},
            ("/usr/bin/Xvfb",),
        )[0]
        self.assertEqual(
            backing["argv"][0:3], [":110", "-auth", "/etc/plasma/Xauthority"]
        )
        adapter = (SOURCE.parent / "plasma-backend/kwin_wayland").read_text()
        records = shell_calls(
            adapter,
            {
                **environment,
                "DISPLAY_MODE": "nested",
                "PLASMA_SOFTWARE_NESTED": "1",
                "PLASMA_SOFTWARE_CAPTURE": "1",
                "PLASMA_NVIDIA_SYNC": "0",
                "PLASMA_KWIN_BINARY": "",
            },
            ("/usr/local/libexec/plasma-wait", "/usr/bin/kwin_wayland"),
        )
        calls = {row["program"]: row for row in records}
        self.assertEqual(calls["plasma-wait"]["environment"]["DISPLAY"], ":110")
        self.assertEqual(
            calls["plasma-wait"]["environment"]["XAUTHORITY"], "/etc/plasma/Xauthority"
        )
        args = calls["kwin_wayland"]["argv"]
        self.assertEqual(args[args.index("--x11-display") + 1], ":110")
        self.assertNotIn("--virtual", args)
        self.assertNotIn("--wayland-display", args)

    def test_private_x11_capture_flags_do_not_change_public_or_nvidia_servers(self):
        source = (SOURCE.parent / "plasma-vnc").read_text()
        for software_relay, nvidia, capture, backend in (
            ("1", "0", "1", "wayland"),
            ("0", "0", "1", "wayland"),
            ("0", "1", "0", "x11"),
        ):
            with self.subTest(software_relay=software_relay, nvidia=nvidia):
                call = shell_calls(
                    source,
                    {
                        "PLASMA_SOFTWARE_NESTED": software_relay,
                        "PLASMA_NVIDIA_NESTED": nvidia,
                        "PLASMA_SOFTWARE_CAPTURE": capture,
                        "DISPLAY_BACKEND": backend,
                        "DISPLAY": ":100",
                        "PLASMA_SOFTWARE_DISPLAY": ":110",
                        "XAUTHORITY": "/etc/plasma/Xauthority",
                        "VNC_MAX_FPS": "60",
                        "WAYLAND_DISPLAY": "wayland-0",
                    },
                    ("/usr/bin/x11vnc",),
                )[0]
                args = call["argv"]
                self.assertEqual(
                    "-localhost" in args, software_relay == "1" or nvidia == "1"
                )
                self.assertEqual("-no6" in args, software_relay == "1")
                self.assertEqual("-rfbportv6" in args, software_relay == "1")
                if software_relay == "1":
                    self.assertEqual(args[args.index("-rfbportv6") + 1], "-1")
                self.assertEqual(
                    args[args.index("-rfbauth") + 1], "/etc/plasma/vnc-auth"
                )
                self.assertEqual(
                    args[args.index("-display") + 1],
                    ":110" if capture == "1" else ":100",
                )
                if capture == "1":
                    self.assertIn("-nomodtweak", args)
                    self.assertIn("-noxkb", args)
                    self.assertIsNone(call["environment"]["WAYLAND_DISPLAY"])

    def test_nested_target_orders_conditional_backing_before_session(self):
        root = SOURCE.parents[1]

        def unit(name):
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read(root / "systemd/system" / name)
            return config

        target = unit("plasma-wayland-nested.target")
        backing = unit("plasma-software-display.service")
        session = unit("plasma-session.service")
        self.assertIn(
            "plasma-software-display.service", target["Unit"]["Requires"].split()
        )
        self.assertIn("plasma-session.service", backing["Unit"]["Before"].split())
        self.assertIn(
            "plasma-software-display.service", session["Unit"]["After"].split()
        )
        condition = backing["Service"]["ExecCondition"]
        self.assertEqual(
            condition, "/usr/local/libexec/plasma-software-display --check"
        )
        self.assertEqual(
            backing["Service"]["ExecStartPost"],
            "/usr/local/libexec/plasma-remote-output --prepare",
        )
        self.assertEqual(backing["Service"]["Restart"], "always")
        self.assertEqual(
            unit("plasma-nested-x11.service")["Service"]["Restart"], "always"
        )
        for backend, mode, host, capture, nested, expected in (
            ("wayland", "nested", "wayland", "0", "1", 0),
            ("wayland", "nested", "wayland", "1", "1", 0),
            ("wayland", "headless", "none", "1", "0", 0),
            ("wayland", "nested", "x11", "0", "1", 1),
            ("x11", "nested", "wayland", "0", "0", 1),
            ("wayland", "vnc", "none", "0", "0", 1),
            ("wayland", "headless", "none", "0", "0", 1),
        ):
            with self.subTest(backend=backend, mode=mode, host=host, capture=capture):
                result = subprocess.run(
                    [
                        "/bin/bash",
                        str(SOURCE.parent / "plasma-software-display"),
                        "--check",
                    ],
                    env={
                        "DISPLAY_BACKEND": backend,
                        "DISPLAY_MODE": mode,
                        "HOST_DISPLAY_BACKEND": host,
                        "PLASMA_SOFTWARE_CAPTURE": capture,
                        "PLASMA_SOFTWARE_NESTED": nested,
                    },
                    check=False,
                )
                self.assertEqual(result.returncode, expected)

    def test_debian_nvidia_remote_fallback_does_not_override_source_compositor(self):
        for overlay, backend, mode, distro, version, vendor, expected in (
            (False, "wayland", "vnc", "debian", "13", "NVIDIA Corporation", True),
            (False, "wayland", "web", "debian", "13", "NVIDIA Corporation", True),
            (True, "wayland", "vnc", "debian", "13", "NVIDIA Corporation", False),
            (False, "wayland", "headless", "debian", "13", "NVIDIA Corporation", False),
            (False, "wayland", "nested", "debian", "13", "NVIDIA Corporation", False),
            (False, "x11", "vnc", "debian", "13", "NVIDIA Corporation", False),
            (False, "wayland", "vnc", "ubuntu", "26.04", "NVIDIA Corporation", False),
            (False, "wayland", "vnc", "debian", "13", "AMD", False),
        ):
            with (
                self.subTest(
                    overlay=overlay,
                    backend=backend,
                    mode=mode,
                    distro=distro,
                    vendor=vendor,
                ),
                patch.dict(os.environ, {"TARGET_APP": "test-app"}),
                patch.object(GPU.Path, "is_file", return_value=overlay),
                patch.object(
                    GPU.platform,
                    "freedesktop_os_release",
                    return_value={"ID": distro, "VERSION_ID": version},
                ),
            ):
                self.assertEqual(
                    GPU.requires_software(
                        backend, mode, {"hardware": True, "vendor": vendor}
                    ),
                    expected,
                )

    def test_installed_overlay_does_not_disable_the_full_desktop_software_workaround(
        self,
    ):
        with (
            patch.dict(os.environ, {"TARGET_APP": ""}),
            patch.object(GPU.Path, "is_file", return_value=True),
            patch.object(
                GPU.platform,
                "freedesktop_os_release",
                return_value={"ID": "debian", "VERSION_ID": "13"},
            ),
        ):
            self.assertTrue(
                GPU.requires_software(
                    "wayland", "vnc", {"hardware": True, "vendor": "NVIDIA Corporation"}
                )
            )

    def test_capture_policy_cli_uses_the_selected_usable_gpu_from_json(self):
        nvidia = {
            "device": "/dev/dri/renderD128",
            "hardware": True,
            "vendor": "NVIDIA Corporation",
        }
        amd = {"device": "/dev/dri/renderD129", "hardware": True, "vendor": "AMD"}
        failed = {**nvidia, "hardware": False, "error": "EGL initialization failed"}
        for devices, expected in (
            ([amd, nvidia], 0),
            ([failed, amd], 1),
            ([failed], 1),
        ):
            selected = GPU.select_device(devices)
            for overlay, target, status in (
                (False, "", expected),
                (True, "", expected),
                (True, "fixture", 1),
            ):
                with (
                    self.subTest(devices=devices, overlay=overlay, target=target),
                    patch.dict(os.environ, {"TARGET_APP": target}),
                    patch.object(Path, "is_file", return_value=overlay),
                    patch(
                        "platform.freedesktop_os_release",
                        return_value={"ID": "debian", "VERSION_ID": "13"},
                    ),
                    patch.object(
                        sys,
                        "argv",
                        [
                            str(SOURCE.parent / "plasma-gpu"),
                            "--requires-software",
                            "wayland",
                            "vnc",
                        ],
                    ),
                    patch.object(
                        sys,
                        "stdin",
                        io.StringIO(
                            json.dumps({"devices": devices, "selected": selected})
                        ),
                    ),
                    self.assertRaises(SystemExit) as result,
                ):
                    runpy.run_path(
                        str(SOURCE.parent / "plasma-gpu"), run_name="__main__"
                    )
                self.assertEqual(result.exception.code, status)
        for malformed in ("", "broken", "{}", "[]", '{"selected": "NVIDIA"}'):
            with (
                self.subTest(malformed=malformed),
                patch.object(
                    sys,
                    "argv",
                    [
                        str(SOURCE.parent / "plasma-gpu"),
                        "--requires-software",
                        "wayland",
                        "vnc",
                    ],
                ),
                patch.object(sys, "stdin", io.StringIO(malformed)),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as result,
            ):
                runpy.run_path(str(SOURCE.parent / "plasma-gpu"), run_name="__main__")
            self.assertEqual(result.exception.code, 2)

    def test_init_probes_before_policy_and_propagates_policy_errors(self):
        module = (SOURCE.parents[1] / "init.d/modules/400-plasma.sh").read_text()
        start = module.index(
            "\tif [[ $software == 0 ]]", module.index("local kwin_overlay=0")
        )
        end = module.index("\tchmod 644 /etc/plasma/gpu.json", start)
        for forced, detected, policy, software, calls, status in (
            (0, 0, 0, 1, 2, 0),
            (0, 0, 1, 0, 2, 0),
            (0, 1, 0, 1, 1, 0),
            (1, 0, 0, 1, 0, 0),
            (0, 0, 2, None, 2, 7),
        ):
            with (
                self.subTest(forced=forced, detected=detected, policy=policy),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                report = root / "gpu.json"
                snapshot = (
                    json.dumps(
                        {
                            "devices": [{"hardware": True}],
                            "selected": {"hardware": True, "vendor": "AMD"},
                        }
                    )
                    + "\n"
                )
                (root / "snapshot").write_text(snapshot)
                script = (
                    module[start:end]
                    .replace("/usr/local/libexec/plasma-gpu", "gpu")
                    .replace("/etc/plasma/gpu.json", str(report))
                )
                result = subprocess.run(
                    [
                        "/bin/bash",
                        "-c",
                        'set -euo pipefail\nsoftware=$1; backend=wayland; mode=vnc\ninfo() { :; }\ndie() { exit 7; }\nrunuser() { shift 3; "$@"; }\ngpu() {\n    printf \'%s\\n\' "$*" >>"$QA_ROOT/calls"\n    if [[ $# == 0 ]]; then cat "$QA_ROOT/snapshot"; return "$QA_DETECTED"; fi\n    cmp -s "$QA_ROOT/snapshot" - || return 2\n    return "$QA_POLICY"\n}\n'
                        + "check_policy() {\n"
                        + script
                        + '\n}\ncheck_policy\nprintf "%s\n" "$software"',
                        "check",
                        str(forced),
                    ],
                    env={
                        **os.environ,
                        "QA_ROOT": directory,
                        "QA_DETECTED": str(detected),
                        "QA_POLICY": str(policy),
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(
                    len((root / "calls").read_text().splitlines())
                    if (root / "calls").exists()
                    else 0,
                    calls,
                )
                if software is not None:
                    self.assertEqual(result.stdout.strip(), str(software))
                    if forced:
                        self.assertEqual(
                            json.loads(report.read_text()),
                            {"devices": [], "forced_software": True},
                        )
                    else:
                        self.assertEqual(report.read_text(), snapshot)

    def test_matching_kscreen_uses_private_qt_without_changing_application_environment(
        self,
    ):
        environment = {
            "TARGET_APP": "test-app",
            "PATH": "/usr/bin",
            "LD_LIBRARY_PATH": "/vendor/lib",
            "QML2_IMPORT_PATH": "/usr/lib/qt6/qml",
            "WAYLAND_DISPLAY": "wayland-0",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(Path, "is_file", return_value=True),
            patch.object(REMOTE.subprocess, "run") as run,
        ):
            REMOTE.kscreen("-j", timeout=5)
            self.assertEqual(
                run.call_args.args[0], ["/opt/kwin-6.8.2/bin/kscreen-doctor", "-j"]
            )
            child = run.call_args.kwargs["env"]
            self.assertEqual(child["QT_PLUGIN_PATH"], "/opt/kwin-6.8.2/plugins")
            self.assertEqual(
                child["LD_LIBRARY_PATH"], "/opt/kwin-6.8.2/lib:/vendor/lib"
            )
            self.assertNotIn("QML2_IMPORT_PATH", child)
            self.assertEqual(dict(os.environ), environment)

    def test_full_desktop_keeps_distro_kscreen_when_private_stack_is_installed(self):
        environment = {
            "PATH": "/usr/bin",
            "TARGET_APP": "",
            "LD_LIBRARY_PATH": "/custom/lib",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(Path, "is_file", return_value=True),
            patch.object(REMOTE.subprocess, "run") as run,
        ):
            REMOTE.kscreen("-j", timeout=5)
            self.assertEqual(run.call_args.args[0], ["kscreen-doctor", "-j"])
            self.assertEqual(run.call_args.kwargs["env"], environment)

    def test_distro_kscreen_keeps_its_environment(self):
        with (
            patch.object(Path, "is_file", return_value=False),
            patch.object(REMOTE.subprocess, "run") as run,
        ):
            REMOTE.kscreen("-j", timeout=5)
            self.assertEqual(run.call_args.args[0], ["kscreen-doctor", "-j"])
            self.assertEqual(run.call_args.kwargs["env"], dict(os.environ))

    def test_kiosk_x11_does_not_require_plasma_desktop(self):
        module = SOURCE.parents[1] / "init.d/modules/400-plasma.sh"
        with tempfile.TemporaryDirectory() as directory:
            for kwin, desktop, kiosk, expected in (
                (True, False, True, 0),
                (True, False, False, 1),
                (True, True, False, 0),
                (False, True, True, 1),
            ):
                for name, enabled in (("kwin_x11", kwin), ("startplasma-x11", desktop)):
                    path = Path(directory) / name
                    if enabled:
                        path.touch(mode=0o755)
                    else:
                        path.unlink(missing_ok=True)
                result = subprocess.run(
                    [
                        "/bin/bash",
                        "-c",
                        'source "$1"; plasma_x11_available',
                        "check",
                        str(module),
                    ],
                    env={
                        **os.environ,
                        "PATH": directory,
                        "TARGET_APP": "wine" if kiosk else "",
                    },
                    check=False,
                )
                with self.subTest(kwin=kwin, desktop=desktop, kiosk=kiosk):
                    self.assertEqual(result.returncode, expected)

    def test_application_does_not_inherit_compositor_qt_stack(self):
        environment = {
            "PATH": "/opt/kwin-6.8.2/bin:/usr/bin",
            "PLASMA_APP_PATH": "/usr/bin",
            "LD_LIBRARY_PATH": "/opt/kwin-6.8.2/lib:/vendor/lib",
            "PLASMA_APP_LD_LIBRARY_PATH": "/vendor/lib",
            "QT_PLUGIN_PATH": "/opt/kwin-6.8.2/plugins",
            "PLASMA_APP_QT_PLUGIN_PATH": "",
            "QML_IMPORT_PATH": "/opt/kwin-6.8.2/qml",
            "PLASMA_APP_QML_IMPORT_PATH": "/custom/qml",
            "QML2_IMPORT_PATH": "/opt/kwin-6.8.2/qml",
            "PLASMA_APP_QML2_IMPORT_PATH": "",
            "XDG_CACHE_HOME": "/home/plasma/.cache/kwin-6.8.2",
            "PLASMA_APP_XDG_CACHE_HOME": "",
            "XDG_DATA_DIRS": "/opt/kwin-6.8.2/share:/usr/share",
            "PLASMA_APP_XDG_DATA_DIRS": "/usr/share",
            "PLASMA_KWIN_BINARY": "/opt/kwin-6.8.2/bin/kwin_wayland",
            "DISPLAY": ":100",
        }
        with patch.dict(os.environ, environment, clear=True):
            child = APP.application_environment()
            self.assertEqual(child["PATH"], "/usr/bin")
            self.assertEqual(child["LD_LIBRARY_PATH"], "/vendor/lib")
            self.assertEqual(child["QML_IMPORT_PATH"], "/custom/qml")
            self.assertEqual(child["XDG_DATA_DIRS"], "/usr/share")
            self.assertEqual(child["DISPLAY"], ":100")
            self.assertNotIn("QT_PLUGIN_PATH", child)
            self.assertNotIn("QML2_IMPORT_PATH", child)
            self.assertNotIn("XDG_CACHE_HOME", child)
            self.assertFalse(any(name.startswith("PLASMA_APP_") for name in child))
            self.assertNotIn("PLASMA_KWIN_BINARY", child)
            self.assertEqual(
                os.environ["LD_LIBRARY_PATH"], environment["LD_LIBRARY_PATH"]
            )

    def test_application_without_overlay_keeps_its_environment(self):
        with patch.dict(
            os.environ, {"PATH": "/usr/bin", "DISPLAY": ":100"}, clear=True
        ):
            self.assertEqual(APP.application_environment(), dict(os.environ))

    def test_application_is_resolved_in_original_path(self):
        with tempfile.TemporaryDirectory() as directory:
            native = Path(directory) / "native"
            overlay = Path(directory) / "overlay"
            native.mkdir()
            overlay.mkdir()
            for root in (native, overlay):
                (root / "test-app").touch(mode=0o755)
            with patch.dict(
                os.environ,
                {
                    "PATH": str(overlay),
                    "PLASMA_APP_PATH": str(native),
                    "TARGET_APP": "test-app",
                },
                clear=True,
            ):
                self.assertEqual(APP.command(), [str(native / "test-app")])

    def test_overlay_without_screenlocker_omits_unsupported_flag(self):
        adapter = SOURCE.parent / "plasma-backend/kwin_wayland"
        with tempfile.TemporaryDirectory() as directory:
            intercept = Path(directory) / "intercept-exec"
            intercept.write_text('exec() { printf "%s\\n" "$@"; }\n')
            for overlay in (False, True):
                environment = {
                    **os.environ,
                    "BASH_ENV": str(intercept),
                    "DISPLAY_MODE": "headless",
                    "DISPLAY_WIDTH": "800",
                    "DISPLAY_HEIGHT": "600",
                    "PLASMA_KWIN_BINARY": "/opt/kwin-6.8.2/bin/kwin_wayland"
                    if overlay
                    else "",
                    "PLASMA_SOFTWARE_CAPTURE": "0",
                    "PLASMA_NVIDIA_SYNC": "0",
                }
                result = subprocess.run(
                    ["/bin/bash", str(adapter)],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                arguments = result.stdout.splitlines()
                with self.subTest(overlay=overlay):
                    self.assertEqual("--no-lockscreen" in arguments, not overlay)
                    self.assertIn("--virtual", arguments)
                    self.assertEqual(
                        arguments[0],
                        environment["PLASMA_KWIN_BINARY"] or "/usr/bin/kwin_wayland",
                    )


if __name__ == "__main__":
    unittest.main()
