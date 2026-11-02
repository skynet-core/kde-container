# /// script
# requires-python = ">=3.10"
# dependencies = ["pycryptodome>=3.20,<4", "pillow>=11,<13", "websocket-client>=1.8,<2"]
# ///
"""Host regressions for the real launcher, graphics policy and protocol boundaries."""

import importlib.machinery
import importlib.util
import io
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

import integration
import support


class SupportTests(unittest.TestCase):
    def health_commands(self, environment, failed_command=None):
        commands = []

        def execute(command, **_settings):
            commands.append(command)
            if command == failed_command:
                raise subprocess.CalledProcessError(3, command)
            return subprocess.CompletedProcess(command, 0)

        with (
            patch(
                "builtins.open",
                mock_open(
                    read_data="".join(
                        f'{key}="{value}"\n' for key, value in environment.items()
                    )
                ),
            ),
            patch("pwd.getpwnam", return_value=pwd.getpwuid(os.getuid())),
            patch("subprocess.run", side_effect=execute),
        ):
            runpy.run_path(str(support.ROOT / "bin/plasma-healthcheck"))
        return commands

    def test_both_nested_relays_require_every_service_and_capture_probe(self):
        for backend, flag in (
            ("wayland", "PLASMA_SOFTWARE_NESTED"),
            ("x11", "PLASMA_NVIDIA_NESTED"),
        ):
            environment = {
                "DISPLAY_BACKEND": backend,
                "DISPLAY_MODE": "nested",
                flag: "1",
                "CLIPBOARD_SYNC": "1",
            }
            required = [
                ["systemctl", "is-active", "--quiet", unit]
                for unit in (
                    f"plasma-{backend}-nested.target",
                    "plasma-session.service",
                    "plasma-clipboard.service",
                    "plasma-nested-x11.service",
                    "plasma-vnc.service",
                )
            ] + [
                ["/usr/local/libexec/plasma-remote-output", "--check"],
                ["/usr/local/libexec/plasma-wait", "desktop"],
                ["/usr/local/libexec/plasma-wait", "vnc"],
            ]
            with self.subTest(backend=backend, failed=None):
                self.assertCountEqual(self.health_commands(environment), required)
            for failed in required:
                with (
                    self.subTest(backend=backend, failed=failed),
                    self.assertRaises(subprocess.CalledProcessError),
                ):
                    self.health_commands(environment, failed)

    def test_native_nesting_does_not_require_a_private_relay(self):
        for backend in ("wayland", "x11"):
            with self.subTest(backend=backend):
                commands = self.health_commands(
                    {
                        "DISPLAY_BACKEND": backend,
                        "DISPLAY_MODE": "nested",
                        "CLIPBOARD_SYNC": "1",
                        "PLASMA_SOFTWARE_NESTED": "0",
                        "PLASMA_NVIDIA_NESTED": "0",
                    }
                )
                self.assertCountEqual(
                    commands,
                    [
                        [
                            "systemctl",
                            "is-active",
                            "--quiet",
                            f"plasma-{backend}-nested.target",
                        ],
                        ["systemctl", "is-active", "--quiet", "plasma-session.service"],
                        [
                            "systemctl",
                            "is-active",
                            "--quiet",
                            "plasma-clipboard.service",
                        ],
                        ["/usr/local/libexec/plasma-wait", "desktop"],
                    ],
                )

    def test_native_sdk_manifest_matches_and_rejects_stale_or_missing_inputs(self):
        spec = importlib.util.spec_from_file_location(
            "native_sdk_inputs", support.ROOT / "test/native/sdk-inputs.py"
        )
        sdk = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sdk)
        for state in ("matching", "stale", "missing"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in sdk.DIRECTORIES:
                    (root / name).mkdir(parents=True, exist_ok=True)
                for name in sdk.FILES:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("same input")
                source = root / "native/test.cpp"
                source.write_text("original")
                expected = sdk.manifest(root)
                if state == "stale":
                    source.write_text("changed")
                elif state == "missing":
                    (root / ".clangd").unlink()
                if state == "matching":
                    sdk.verify(root, expected)
                else:
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        sdk.verify(root, expected)

    def test_health_requires_every_selected_unit(self):
        for mode in ("headless", "vnc", "web", "nested"):
            units = [f"plasma-wayland-{mode}.target", "plasma-session.service"]
            if mode in ("vnc", "web", "nested"):
                units.append("plasma-vnc.service")
            if mode == "web":
                units.append("plasma-web.service")
            if mode == "nested":
                units += ["plasma-clipboard.service", "plasma-nested-x11.service"]
            environment = {"DISPLAY_BACKEND": "wayland", "DISPLAY_MODE": mode}
            if mode == "nested":
                environment.update(CLIPBOARD_SYNC="1", PLASMA_SOFTWARE_NESTED="1")
            for failed in (None, *units):
                expected = (
                    self.assertRaises(subprocess.CalledProcessError)
                    if failed
                    else nullcontext()
                )
                with self.subTest(mode=mode, failed=failed), expected:
                    self.health_commands(
                        environment,
                        ["systemctl", "is-active", "--quiet", failed]
                        if failed
                        else None,
                    )

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

    def test_kiosk_and_full_desktop_require_different_x11_capabilities(self):
        for kiosk in (False, True):
            with (
                self.subTest(kiosk=kiosk),
                patch.object(
                    support, "run", return_value=subprocess.CompletedProcess([], 0)
                ) as run,
            ):
                self.assertEqual(
                    support.available_backends("docker", "image", kiosk=kiosk),
                    ("wayland", "x11"),
                )
                probe = run.call_args.args[-1]
                self.assertIn("command -v kwin_x11", probe)
                self.assertEqual("command -v startplasma-x11" in probe, not kiosk)

    def test_software_integration_rejects_conflicting_hardware_expectations(self):
        for arguments in (("--gpus", "all"), ("--expect-renderer", "gpu")):
            with (
                self.subTest(arguments=arguments),
                patch.object(sys, "argv", ["integration.py", "--no-gpu", *arguments]),
                patch("sys.stderr", new=io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                integration.main()
            self.assertEqual(error.exception.code, 2)

    def test_unavailable_full_desktop_x11_requires_the_expected_container_rejection(
        self,
    ):
        for exited, message, accepted in (
            (
                "1",
                "This image has no usable KWin X11 session; use DISPLAY_BACKEND=wayland",
                True,
            ),
            ("0", "This image has no usable KWin X11 session", False),
            ("1", "Unrelated startup error", False),
        ):
            with (
                self.subTest(exited=exited, message=message),
                tempfile.TemporaryDirectory() as directory,
            ):

                def command(
                    _runtime,
                    action,
                    *_arguments,
                    _exited=exited,
                    _message=message,
                    **_settings,
                ):
                    return subprocess.CompletedProcess(
                        [],
                        0,
                        _exited
                        if action == "wait"
                        else _message
                        if action == "logs"
                        else "sha256:fixture",
                        "",
                    )

                expectation = (
                    nullcontext() if accepted else self.assertRaises(AssertionError)
                )
                with (
                    patch.object(
                        integration,
                        "launch",
                        return_value=subprocess.CompletedProcess([], 0, "", ""),
                    ),
                    patch.object(integration, "command", side_effect=command),
                    patch.object(integration, "collect_artifacts") as cleanup,
                    patch("builtins.print"),
                    expectation,
                ):
                    integration.verify_unsupported_x11(
                        "docker", "fixture", Path(directory)
                    )
                report = json.loads(
                    (
                        Path(directory) / "x11-desktop-unavailable/results.json"
                    ).read_text()
                )
                self.assertEqual(report["passed"], accepted)
                cleanup.assert_called_once()

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
                "PLASMA_PASSWORD": "unexpected-host-password",
                "PLASMA_PASSWORD_FILE": "/not/a/test/account-secret",
                "PLASMA_SUDO_NOPASSWD": "true",
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
                        self.assertNotIn("PLASMA_PASSWORD", arguments)
                        self.assertNotIn("PLASMA_SUDO_NOPASSWD", arguments)
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

            for runtime in ("docker", "podman"):
                for use_file in (False, True):
                    password_file = directory / "account-password"
                    password_file.write_text("Test-account-password-42!")
                    settings = {
                        "PLASMA_PASSWORD": "Test-account-password-42!",
                        "PLASMA_SUDO_NOPASSWD": "true",
                    }
                    if use_file:
                        settings["PLASMA_PASSWORD_FILE"] = str(password_file)
                    with (
                        self.subTest(runtime=runtime, use_file=use_file),
                        patch.dict(os.environ, environment, clear=True),
                    ):
                        result = support.launch(
                            runtime,
                            "image",
                            "fixture",
                            "wayland",
                            "headless",
                            **settings,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        arguments = json.loads(result.stdout)
                        self.assertIn("PLASMA_SUDO_NOPASSWD", arguments)
                        self.assertNotIn(
                            "Test-account-password-42!", " ".join(arguments)
                        )
                        if use_file:
                            self.assertIn(
                                f"type=bind,source={password_file},target=/run/secrets/plasma-password,readonly",
                                arguments,
                            )
                            self.assertIn(
                                "PLASMA_PASSWORD_FILE=/run/secrets/plasma-password",
                                arguments,
                            )
                            self.assertNotIn("PLASMA_PASSWORD", arguments)
                        else:
                            self.assertIn("PLASMA_PASSWORD", arguments)

    def test_software_device_options(self):
        for present in (False, True):
            with (
                self.subTest(udmabuf=present),
                patch.object(Path, "exists", return_value=present),
            ):
                docker = support.software_options("docker")
                podman = support.software_options("podman")
                self.assertIn("/dev/dri:mode=0755", docker)
                self.assertIn("LIBGL_ALWAYS_SOFTWARE=1", docker)
                self.assertIn("LIBGL_ALWAYS_SOFTWARE=1", podman)
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
            results = [subprocess.TimeoutExpired("logs", 180), *([completed] * 7)]
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
                "gpu.json",
                "vnc.log",
            ):
                self.assertEqual((directory / filename).read_text(), "stdout\nstderr\n")


class GpuTests(unittest.TestCase):
    def test_probe_failure_does_not_hide_another_gpu(self):
        loader = importlib.machinery.SourceFileLoader(
            "gpu", str(support.ROOT / "libexec/plasma-gpu")
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        gpu = importlib.util.module_from_spec(spec)
        loader.exec_module(gpu)
        paths = [Path(f"/dev/dri/renderD{number}") for number in range(128, 133)]
        nvidia = {"device": str(paths[1]), "renderer": "NVIDIA GPU", "hardware": True}
        amd = {"device": str(paths[2]), "renderer": "AMD GPU", "hardware": True}
        software = {"device": str(paths[3]), "renderer": "llvmpipe", "hardware": False}
        with (
            patch.object(gpu.Path, "glob", return_value=paths),
            patch.object(gpu.Path, "is_char_device", return_value=True),
            patch.object(
                gpu.subprocess,
                "run",
                side_effect=[
                    subprocess.TimeoutExpired("probe", 8),
                    subprocess.CompletedProcess([], 0, json.dumps(nvidia)),
                    subprocess.CompletedProcess([], 0, json.dumps(amd)),
                    subprocess.CompletedProcess([], 0, json.dumps(software)),
                    subprocess.CompletedProcess([], -11, ""),
                ],
            ),
        ):
            devices = gpu.detect()
        self.assertIn("error", devices[0])
        self.assertEqual(devices[1:4], [nvidia, amd, software])
        self.assertIn("error", devices[4])


class KioskTests(unittest.TestCase):
    def test_chromium_window_policy_preserves_default_and_explicit_urls(self):
        loader = importlib.machinery.SourceFileLoader(
            "browser_target_app", str(support.ROOT / "libexec/plasma-target-app")
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        target_app = importlib.util.module_from_spec(spec)
        loader.exec_module(target_app)
        handlers = {}
        for browser in ("chromium", "chromium-browser"):
            for mode in ("fullscreen", "maximized"):
                for url in (None, "https://example.invalid/page"):
                    with (
                        self.subTest(browser=browser, mode=mode, url=url),
                        tempfile.TemporaryDirectory() as directory,
                    ):
                        handlers.clear()
                        child = Mock(pid=4321)
                        child.poll.return_value = None

                        def sleep(duration):
                            if duration == 0.1:
                                handlers[signal.SIGTERM](signal.SIGTERM, None)

                        with (
                            patch.dict(
                                os.environ,
                                {
                                    "DISPLAY_MODE": "headless",
                                    "DISPLAY_BACKEND": "wayland",
                                    "TARGET_APP_WINDOW_MODE": mode,
                                },
                                clear=True,
                            ),
                            patch.object(sys, "argv", ["plasma-target-app"]),
                            patch.object(
                                target_app, "STATE", Path(directory) / "state.json"
                            ),
                            patch.object(
                                target_app,
                                "command",
                                return_value=[
                                    "/usr/bin/" + browser,
                                    *([url] if url else []),
                                ],
                            ),
                            patch.object(target_app, "start_time", return_value="123"),
                            patch.object(target_app.subprocess, "run"),
                            patch.object(
                                target_app.subprocess, "Popen", return_value=child
                            ) as spawn,
                            patch.object(
                                target_app.signal,
                                "signal",
                                side_effect=lambda number, handler: handlers.update(
                                    {number: handler}
                                ),
                            ),
                            patch.object(target_app.os, "killpg"),
                            patch.object(target_app.time, "sleep", side_effect=sleep),
                        ):
                            self.assertEqual(target_app.main(), 0)
                            arguments = spawn.call_args.args[0]
                            self.assertEqual(
                                "--kiosk" in arguments, mode == "fullscreen"
                            )
                            self.assertEqual(arguments[-1], url or "about:blank")
                            self.assertEqual(arguments.count(url or "about:blank"), 1)
                            self.assertIn("--no-first-run", arguments)
                            self.assertIn("--ozone-platform=wayland", arguments)

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


def load_tests(loader, tests, _pattern):
    tests.addTests(loader.discover(str(Path(__file__).parent), pattern="test_*.py"))
    return tests


if __name__ == "__main__":
    unittest.main()
