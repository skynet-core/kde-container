"""Host-only regressions for shared test setup and kiosk process cleanup."""

import importlib.machinery
import importlib.util
import json
import os
import pwd
import runpy
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, call, mock_open, patch

import support


class SupportTests(unittest.TestCase):
    def test_health_requires_every_selected_unit(self):
        for mode in ("headless", "vnc", "web"):
            units = [f"plasma-wayland-{mode}.target", "plasma-session.service"]
            if mode in ("vnc", "web"):
                units.append("plasma-vnc.service")
            if mode == "web":
                units.append("plasma-web.service")
            for failed in (None, *units):

                def execute(command, failed=failed, **settings):
                    if command[0] == "systemctl" and not any(
                        unit != failed for unit in command[3:]
                    ):
                        raise subprocess.CalledProcessError(3, command)
                    return subprocess.CompletedProcess(command, 0)

                expected = (
                    self.assertRaises(subprocess.CalledProcessError)
                    if failed
                    else nullcontext()
                )
                with (
                    self.subTest(mode=mode, failed=failed),
                    patch(
                        "builtins.open",
                        mock_open(
                            read_data=f'DISPLAY_BACKEND="wayland"\nDISPLAY_MODE="{mode}"\n'
                        ),
                    ),
                    patch("pwd.getpwnam", return_value=pwd.getpwuid(os.getuid())),
                    patch("subprocess.run", side_effect=execute),
                    expected,
                ):
                    runpy.run_path(str(support.ROOT / "bin/plasma-healthcheck"))

    def test_run_preserves_failure_output(self):
        result = support.run(
            sys.executable,
            "-c",
            "import sys; print('failure', file=sys.stderr); sys.exit(7)",
        )
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stderr, "failure\n")

    def test_backend_detection(self):
        for code, expected in ((0, ("wayland", "x11")), (1, ("wayland",))):
            with (
                self.subTest(code=code),
                patch.object(
                    support, "run", return_value=subprocess.CompletedProcess([], code)
                ),
            ):
                self.assertEqual(
                    support.available_backends("docker", "image"), expected
                )

    def test_launcher_modes_and_namespaces(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            socket.socket(socket.AF_UNIX) as display,
        ):
            directory = Path(temporary)
            display.bind(str(directory / "wayland-0"))
            for runtime in ("docker", "podman"):
                engine = directory / runtime
                engine.write_text(
                    "#!/usr/bin/python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n"
                )
                engine.chmod(0o755)
            environment = {
                "PATH": f"{directory}:{os.environ['PATH']}",
                "HOME": os.environ["HOME"],
                "XDG_RUNTIME_DIR": str(directory),
                "WAYLAND_DISPLAY": "wayland-0",
                "TARGET_APP": "unexpected-host-app",
                "VNC_PASSWORD_FILE": "/not/a/test/secret",
                "BIND_ADDRESS": "0.0.0.0",
            }
            for runtime in ("docker", "podman"):
                for mode in ("headless", "nested", "vnc", "web"):
                    with (
                        self.subTest(runtime=runtime, mode=mode),
                        patch.dict(os.environ, environment, clear=True),
                    ):
                        result = support.launch(
                            runtime,
                            "image",
                            "fixture",
                            "wayland",
                            mode,
                            DISPLAY_WIDTH="800",
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        arguments = json.loads(result.stdout)
                        self.assertEqual(arguments[-1], "image")
                        namespace = (
                            "--userns=keep-id"
                            if runtime == "podman"
                            else "--userns=host"
                        )
                        self.assertEqual(arguments.count(namespace), 1)
                        self.assertIn(f"PLASMA_UID={os.getuid()}", arguments)
                        self.assertIn(f"PLASMA_GID={os.getgid()}", arguments)
                        self.assertIn("DISPLAY_WIDTH=800", arguments)
                        self.assertNotIn("TARGET_APP=unexpected-host-app", arguments)
                        if mode == "nested":
                            self.assertIn(
                                "HOST_WAYLAND_DISPLAY=/run/host/wayland", arguments
                            )
                        if mode in ("vnc", "web"):
                            port = 5900 if mode == "vnc" else 6080
                            self.assertIn(f"127.0.0.1::{port}", arguments)
                            self.assertIn("VNC_PASSWORD", arguments)
                        else:
                            self.assertNotIn("-p", arguments)
                        if runtime == "podman":
                            self.assertIn("--systemd=always", arguments)

    def test_software_device_options(self):
        for present in (False, True):
            with (
                self.subTest(udmabuf=present),
                patch.object(Path, "exists", return_value=present),
            ):
                docker = support.software_options("docker")
                podman = support.software_options("podman")
                self.assertIn("/dev/dri:mode=0755", docker)
                self.assertNotIn("--privileged=false", docker)
                self.assertIn("--privileged=false", podman)
                self.assertIn("--cap-add=all", podman)
                self.assertEqual("/dev/udmabuf" in podman, present)

    def test_readiness_retry_exit_and_timeout(self):
        failed = subprocess.CompletedProcess([], 1, "", "probe failed")
        ready = subprocess.CompletedProcess([], 0, "", "")
        running = subprocess.CompletedProcess([], 0, "true\n", "")
        with (
            patch.object(support, "run", side_effect=[failed, running, ready]),
            patch.object(support.time, "sleep") as sleep,
        ):
            support.wait_ready("docker", "fixture")
            sleep.assert_called_once()
        with (
            patch.object(support, "run", side_effect=[failed, failed, failed]),
            self.assertRaisesRegex(RuntimeError, "exited.*probe failed"),
        ):
            support.wait_ready("docker", "fixture")
        with (
            patch.object(support, "run", side_effect=[failed, running]),
            patch.object(support.time, "monotonic", side_effect=[0, 2]),
            self.assertRaisesRegex(RuntimeError, "ready.*probe failed"),
        ):
            support.wait_ready("docker", "fixture", timeout=1)

    def test_evidence_survives_command_failure_and_teardown(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            completed = subprocess.CompletedProcess([], 1, "stdout\n", "stderr\n")
            results = [subprocess.TimeoutExpired("logs", 180), *([completed] * 6)]
            with patch.object(support, "run", side_effect=results) as run:
                support.collect_artifacts(
                    "docker", "fixture", directory, services=("vnc",)
                )
            run.assert_called_with("docker", "rm", "-f", "fixture")
            self.assertIn("timed out", (directory / "container.log").read_text())
            for filename in (
                "journal.log",
                "processes.log",
                "session.env",
                "renderer.log",
                "vnc.log",
            ):
                self.assertEqual((directory / filename).read_text(), "stdout\nstderr\n")


class KioskTests(unittest.TestCase):
    def test_restart_and_shutdown_cleanup(self):
        loader = importlib.machinery.SourceFileLoader(
            "target_app", str(support.ROOT / "libexec/plasma-target-app")
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        target_app = importlib.util.module_from_spec(spec)
        loader.exec_module(target_app)
        handlers = {}
        for restart, force in ((False, False), (False, True), (True, False)):
            with (
                self.subTest(restart=restart, force=force),
                tempfile.TemporaryDirectory() as temporary,
            ):
                child = Mock(pid=4321)
                child.poll.return_value = None
                if force:
                    child.wait.side_effect = [
                        subprocess.TimeoutExpired("fixture", 10),
                        0,
                    ]
                previous = Mock(pid=1234, returncode=0)
                previous.poll.return_value = 0
                handlers.clear()

                def sleep(duration):
                    if duration == 0.1:
                        handlers[signal.SIGTERM](signal.SIGTERM, None)

                with (
                    patch.dict(os.environ, DISPLAY_MODE="headless"),
                    patch.object(sys, "argv", ["plasma-target-app"]),
                    patch.object(
                        target_app, "STATE", Path(temporary) / "target-app.json"
                    ),
                    patch.object(target_app, "command", return_value=["fixture"]),
                    patch.object(target_app, "start_time", return_value="123"),
                    patch.object(target_app.subprocess, "run"),
                    patch.object(
                        target_app.subprocess,
                        "Popen",
                        side_effect=[previous, child] if restart else [child],
                    ) as spawn,
                    patch.object(
                        target_app.signal,
                        "signal",
                        side_effect=lambda number, handler: handlers.update(
                            {number: handler}
                        ),
                    ),
                    patch.object(target_app.os, "killpg") as kill,
                    patch.object(target_app.time, "sleep", side_effect=sleep),
                ):
                    self.assertEqual(target_app.main(), 0)
                    self.assertEqual(spawn.call_count, 2 if restart else 1)
                    child.wait.assert_any_call(timeout=10)
                    kill.assert_any_call(child.pid, signal.SIGTERM)
                    if restart:
                        kill.assert_any_call(previous.pid, signal.SIGTERM)
                    self.assertEqual(
                        call(child.pid, signal.SIGKILL) in kill.call_args_list, force
                    )
                    self.assertFalse(target_app.STATE.exists())


if __name__ == "__main__":
    unittest.main()
