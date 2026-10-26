#!/usr/bin/python3
"""Run inside a disposable image: exercise the actual inherited init framework."""

import os
from pathlib import Path
import shlex
import socket
import subprocess
import unittest

BACKENDS = ("wayland", "x11") if Path("/usr/bin/kwin_x11").exists() else ("wayland",)


class InitTests(unittest.TestCase):
    def boot(self, expected=0, **settings):
        environment = {
            "PATH": os.environ["PATH"],
            "DISPLAY_MODE": "headless",
            "DISPLAY_BACKEND": "auto",
            "VNC_PASSWORD": "testpass",
            **settings,
        }
        result = subprocess.run(
            ["/init.d/init.sh", "/usr/bin/true"],
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        if expected:
            return result.stderr
        config = dict(
            shlex.split(line)[0].split("=", 1)
            for line in Path("/etc/plasma/session.env").read_text().splitlines()
        )
        target = Path("/etc/systemd/system/default.target").resolve().name
        self.assertEqual(
            target,
            f"plasma-{config['DISPLAY_BACKEND']}-{config['DISPLAY_MODE']}.target",
        )
        return config

    def test_all_supported_targets(self):
        for backend in BACKENDS:
            for mode in ("headless", "vnc", "web", "nested"):
                with (
                    self.subTest(backend=backend, mode=mode),
                    socket.socket(socket.AF_UNIX) as fixture,
                ):
                    path = "/tmp/plasma-test-wayland"
                    Path(path).unlink(missing_ok=True)
                    fixture.bind(path)
                    config = self.boot(
                        DISPLAY_BACKEND=backend,
                        DISPLAY_MODE=mode,
                        HOST_WAYLAND_DISPLAY=path,
                    )
                    self.assertEqual(config["DISPLAY_BACKEND"], backend)
                    self.assertEqual(config["DISPLAY_MODE"], mode)
                    if mode in ("headless", "nested"):
                        self.assertFalse(Path("/etc/plasma/vnc-password").exists())
                    else:
                        self.assertEqual(
                            Path("/etc/plasma/vnc-password").stat().st_mode & 0o777,
                            0o600,
                        )
                    Path(path).unlink()

    def test_no_host_defaults_to_wayland(self):
        self.assertEqual(self.boot()["DISPLAY_BACKEND"], "wayland")

    def test_target_app_selection_and_validation(self):
        self.assertEqual(self.boot()["TARGET_APP"], "")
        self.assertNotIn("XDG_CONFIG_HOME", self.boot())
        value = 'konsole --title "Kiosk with spaces; $literal `literal`"'
        config = self.boot(TARGET_APP=value)
        self.assertEqual(config["TARGET_APP"], value)
        self.assertEqual(config["XDG_CONFIG_HOME"], "/home/plasma/.config/plasma-kiosk")
        self.assertEqual(self.boot(TARGET_APP="chromium")["TARGET_APP"], "chromium")
        for command in (
            "not-an-installed-application",
            "konsole '",
            " ",
            "konsole\ntrue",
        ):
            with self.subTest(command=command):
                self.assertIn("TARGET_APP", self.boot(expected=1, TARGET_APP=command))

    def test_vnc_frame_rate(self):
        self.assertEqual(self.boot()["VNC_MAX_FPS"], "60")
        self.assertEqual(self.boot(VNC_MAX_FPS="30")["VNC_MAX_FPS"], "30")
        for value in ("0", "61", "-1", "1.5", "oops"):
            with self.subTest(value=value):
                self.assertIn("VNC_MAX_FPS", self.boot(expected=1, VNC_MAX_FPS=value))

    def test_gpu_preference_and_software_override(self):
        automatic = self.boot()
        self.assertIn(automatic["LIBGL_ALWAYS_SOFTWARE"], ("0", "1"))
        software = self.boot(LIBGL_ALWAYS_SOFTWARE="1")
        self.assertEqual(software["LIBGL_ALWAYS_SOFTWARE"], "1")
        self.assertEqual(software["QT_QUICK_BACKEND"], "software")
        self.assertEqual(software["PLASMA_SOFTWARE_CAPTURE"], "0")
        remote = self.boot(
            DISPLAY_BACKEND="wayland", DISPLAY_MODE="web", LIBGL_ALWAYS_SOFTWARE="1"
        )
        self.assertEqual(
            remote["PLASMA_SOFTWARE_CAPTURE"],
            "0" if Path("/etc/plasma/opengl-software-capture").exists() else "1",
        )
        self.assertEqual(remote["PLASMA_SOFTWARE_DISPLAY"], ":110")
        if "x11" in BACKENDS:
            x11 = self.boot(
                DISPLAY_BACKEND="x11", DISPLAY_MODE="vnc", LIBGL_ALWAYS_SOFTWARE="1"
            )
            self.assertEqual(x11["PLASMA_SOFTWARE_CAPTURE"], "0")
        else:
            self.assertIn(
                "no Plasma X11 session", self.boot(expected=1, DISPLAY_BACKEND="x11")
            )
        self.assertIn(
            "LIBGL_ALWAYS_SOFTWARE",
            self.boot(expected=1, LIBGL_ALWAYS_SOFTWARE="invalid"),
        )

    def test_wayland_priority_and_x11_fallback(self):
        Path("/run/host/X11").mkdir(parents=True, exist_ok=True)
        with (
            socket.socket(socket.AF_UNIX) as wayland,
            socket.socket(socket.AF_UNIX) as x11,
        ):
            wayland.bind("/run/host/wayland")
            x11.bind("/run/host/X11/X0")
            self.assertEqual(self.boot()["DISPLAY_BACKEND"], "wayland")
            Path("/run/host/wayland").unlink()
            config = self.boot(DISPLAY_MODE="nested")
            self.assertEqual(
                config["DISPLAY_BACKEND"], "x11" if "x11" in BACKENDS else "wayland"
            )
            self.assertEqual(config["HOST_DISPLAY"], ":0")
            Path("/run/host/X11/X0").unlink()

    def test_regular_file_is_not_a_display_socket(self):
        Path("/run/host").mkdir(exist_ok=True)
        Path("/run/host/wayland").touch()
        try:
            self.assertEqual(self.boot()["HOST_DISPLAY_BACKEND"], "none")
        finally:
            Path("/run/host/wayland").unlink()

    def test_invalid_inputs_fail_before_systemd(self):
        for settings, message in [
            ({"DISPLAY_MODE": "bogus"}, "Invalid DISPLAY_MODE"),
            ({"DISPLAY_BACKEND": "bogus"}, "Invalid DISPLAY_BACKEND"),
            ({"DISPLAY_MODE": "nested"}, "requires a mounted host"),
            ({"DISPLAY_WIDTH": "0"}, "dimensions"),
            ({"DISPLAY_MODE": "web", "VNC_PASSWORD": ""}, "Set VNC_PASSWORD"),
            (
                {"DISPLAY_MODE": "vnc", "VNC_PASSWORD": "too-long-password"},
                "VNC protocol limit",
            ),
            ({"HOST_WAYLAND_DISPLAY": "/does/not/exist"}, "not a mounted socket"),
            ({"PLASMA_UID": "0"}, "nonzero numeric IDs"),
            ({"PLASMA_GID": "bad"}, "nonzero numeric IDs"),
            ({"PLASMA_UID": "4294967295"}, "nonzero numeric IDs"),
            ({"PLASMA_UID": "1"}, "already belongs"),
        ]:
            with self.subTest(settings=settings):
                self.assertIn(message, self.boot(expected=1, **settings))

    def test_runtime_identity_and_home_ownership(self):
        uid = subprocess.check_output(["id", "-u", "plasma"], text=True).strip()
        gid = subprocess.check_output(["id", "-g", "plasma"], text=True).strip()
        home_file = Path("/home/plasma/identity-test")
        home_file.write_text("desktop state")
        os.chown(home_file, int(uid), int(gid))
        try:
            self.boot(PLASMA_UID="23000", PLASMA_GID="23001")
            self.assertEqual(
                subprocess.check_output(["id", "-u", "plasma"], text=True).strip(),
                "23000",
            )
            self.assertEqual(
                subprocess.check_output(["id", "-g", "plasma"], text=True).strip(),
                "23001",
            )
            self.assertEqual(
                (home_file.stat().st_uid, home_file.stat().st_gid), (23000, 23001)
            )
            # Reuse an existing group without altering its other members.
            before = subprocess.check_output(["getent", "passwd", "daemon"], text=True)
            self.boot(PLASMA_UID="23000", PLASMA_GID="2")
            self.assertEqual(
                subprocess.check_output(["id", "-g", "plasma"], text=True).strip(), "2"
            )
            self.assertEqual(
                subprocess.check_output(["getent", "passwd", "daemon"], text=True),
                before,
            )
        finally:
            self.boot(PLASMA_UID=uid, PLASMA_GID=gid)
            home_file.unlink(missing_ok=True)

    def test_password_file_and_safe_environment_quoting(self):
        Path("/tmp/plasma-test-password").write_text("filepass\n")
        self.boot(DISPLAY_MODE="web", VNC_PASSWORD_FILE="/tmp/plasma-test-password")
        self.assertEqual(Path("/etc/plasma/vnc-password").read_text(), "filepass")
        value = 'C.UTF-8$literal`literal`"\\'
        self.assertEqual(self.boot(LANG=value)["LANG"], value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
