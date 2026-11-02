"""Exercise the real integration entrypoint's private nested transport checks."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import integration


class NestedIntegrationTests(unittest.TestCase):
    def run_case(self, flags, *, vnc=None, web="inactive", published=None):
        backend = "x11" if flags.get("PLASMA_NVIDIA_NESTED") == "1" else "wayland"
        relay = any(
            flags.get(key) == "1"
            for key in ("PLASMA_SOFTWARE_NESTED", "PLASMA_NVIDIA_NESTED")
        )
        gpu = flags.get("LIBGL_ALWAYS_SOFTWARE") == "0"
        commands = []

        def command(*arguments, **_settings):
            commands.append(arguments)
            code, output, error = 0, "", ""
            if "qdbus-qt6" in arguments:
                output = (
                    "Compositing Type: OpenGL\nOpenGL renderer string: NVIDIA\n"
                    if gpu
                    else "Compositing Type: QPainter\n"
                )
            elif arguments[-1] == "/etc/plasma/session.env":
                output = "".join(f'{key}="{value}"\n' for key, value in flags.items())
            elif arguments[1:2] == ("inspect",):
                output = json.dumps(published or {})
            elif "id" in arguments:
                key = "PLASMA_UID" if "-u" in arguments else "PLASMA_GID"
                output = os.environ.get(
                    key, str(os.getuid() if "-u" in arguments else os.getgid())
                )
            elif "readlink" in arguments:
                output = f"/etc/systemd/system/plasma-{backend}-nested.target\n"
            elif "top" in arguments:
                output = "PID COMMAND\n123 /usr/bin/kwin_wayland --xwayland\n"
            elif "is-enabled" in arguments:
                output = "masked\n"
            elif "start" in arguments:
                code, error = 1, "Unit is masked"
            elif "is-active" in arguments:
                unit = arguments[-1]
                output = {
                    "NetworkManager.service": "inactive",
                    "plasma-vnc.service": vnc or ("active" if relay else "inactive"),
                    "plasma-web.service": web,
                }[unit] + "\n"
            return subprocess.CompletedProcess(arguments, code, output, error)

        with tempfile.TemporaryDirectory() as directory:
            entrypoint = Path(directory) / "test/integration.py"
            output = io.StringIO()
            with (
                patch.object(integration, "__file__", str(entrypoint)),
                patch.object(
                    integration, "available_backends", return_value=("wayland", "x11")
                ),
                patch.object(integration, "wait_ready") as ready,
                patch.object(integration, "collect_artifacts") as collect,
                patch.object(integration, "command", side_effect=command),
                patch.object(
                    sys,
                    "argv",
                    [
                        str(entrypoint),
                        "--image",
                        "unused",
                        "--runtime",
                        "docker",
                        "--backends",
                        backend,
                        "--modes",
                        "nested",
                        "--expect-renderer",
                        "gpu" if gpu else "software",
                    ],
                ),
                contextlib.redirect_stdout(output),
            ):
                try:
                    integration.main()
                    passed = True
                except SystemExit:
                    passed = False
            ready.assert_called_once()
            collect.assert_called_once()
            return passed, commands, output.getvalue()

    def test_actual_relay_flags_select_private_vnc_without_a_web_service(self):
        for name, flags in (
            (
                "native",
                {
                    "PLASMA_SOFTWARE_NESTED": "0",
                    "PLASMA_NVIDIA_NESTED": "0",
                    "LIBGL_ALWAYS_SOFTWARE": "0",
                },
            ),
            (
                "modern",
                {
                    "PLASMA_SOFTWARE_NESTED": "1",
                    "PLASMA_SOFTWARE_CAPTURE": "0",
                    "LIBGL_ALWAYS_SOFTWARE": "1",
                },
            ),
            (
                "legacy",
                {
                    "PLASMA_SOFTWARE_NESTED": "1",
                    "PLASMA_SOFTWARE_CAPTURE": "1",
                    "LIBGL_ALWAYS_SOFTWARE": "1",
                },
            ),
            (
                "nvidia",
                {
                    "PLASMA_NVIDIA_NESTED": "1",
                    "PLASMA_SOFTWARE_NESTED": "0",
                    "LIBGL_ALWAYS_SOFTWARE": "0",
                },
            ),
        ):
            with self.subTest(path=name):
                passed, commands, output = self.run_case(flags)
                self.assertTrue(passed, output)
                self.assertTrue(
                    any(args[-1] == "/etc/plasma/session.env" for args in commands)
                )
                self.assertTrue(
                    any("{{json .NetworkSettings.Ports}}" in args for args in commands)
                )
                self.assertTrue(any("qdbus-qt6" in args for args in commands))
                self.assertTrue(
                    any(args[-1] == "plasma-web.service" for args in commands)
                )

    def test_missing_private_vnc_unexpected_web_or_published_ports_fail(self):
        native = {
            "PLASMA_SOFTWARE_NESTED": "0",
            "PLASMA_NVIDIA_NESTED": "0",
            "LIBGL_ALWAYS_SOFTWARE": "1",
        }
        relay = {
            **native,
            "PLASMA_SOFTWARE_NESTED": "1",
            "PLASMA_SOFTWARE_CAPTURE": "1",
        }
        for flags, settings in (
            (native, {"vnc": "active"}),
            (relay, {"vnc": "inactive"}),
            (native, {"web": "active"}),
            (native, {"published": {"5900/tcp": [{"HostPort": "5900"}]}}),
            (native, {"published": {"6080/tcp": [{"HostPort": "6080"}]}}),
        ):
            with self.subTest(settings=settings):
                passed, _commands, output = self.run_case(flags, **settings)
                self.assertFalse(passed, output)
                self.assertIn("FAIL ", output)


if __name__ == "__main__":
    unittest.main()
