"""CI and kiosk failures must reach the exit status and every case receipt."""

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/build-and-publish.yml"
KIOSK = ROOT / "test/kiosk.py"


class FailureReportingTests(unittest.TestCase):
    def test_actual_piped_workflow_suites_propagate_failures(self):
        workflow = WORKFLOW.read_text()
        explicit_bash = re.search(
            r"(?m)^defaults:\n  run:\n    shell: bash\s*$", workflow
        )
        for name, suite in (
            (
                "Verify remote mouse, typing, screenshots and Chromium kiosk",
                "test/kiosk.py",
            ),
            (
                "Verify desktop and kiosk nested clipboard and GUI copy-paste",
                "test/clipboard.py",
            ),
        ):
            with self.subTest(suite=suite), tempfile.TemporaryDirectory() as directory:
                block = workflow.split("      - name: " + name + "\n", 1)[1]
                script = textwrap.dedent(
                    block.split("        run: |\n", 1)[1].split("\n      - ", 1)[0]
                )
                self.assertIn(suite, script)
                self.assertIn("| tee", script)
                path = Path(directory)
                (path / "test/.artifacts").mkdir(parents=True)
                step = path / "step.sh"
                step.write_text(
                    'uv() { if [[ "$*" == *"$FAIL_SUITE"* ]]; then echo intentional-suite-failure; return 23; fi; echo passing-suite; }\n'
                    + script
                )
                environment = {
                    **os.environ,
                    "UI_IMAGE": "unused",
                    "TEST_BACKENDS": "wayland",
                    "KIOSK_BACKENDS": "wayland x11",
                    "FAIL_SUITE": suite,
                }
                environment.pop("BASH_ENV", None)
                command = ["/bin/bash", "--noprofile", "--norc", "-e"]
                # Explicit GitHub Actions bash adds pipefail; its implicit bash does not.
                if explicit_bash:
                    command += ["-o", "pipefail"]
                result = subprocess.run(
                    [*command, str(step)],
                    cwd=path,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertIn("intentional-suite-failure", result.stdout)
                self.assertEqual(
                    result.returncode, 23, "tee masked a failed acceptance suite"
                )
        self.assertIsNotNone(explicit_bash)

    def test_missing_pid_reports_and_cleans_up_every_kiosk_case(self):
        spec = importlib.util.spec_from_file_location("case_reporting_kiosk", KIOSK)
        kiosk = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kiosk)
        labels = {
            f"{app}-{backend}-{mode}"
            for app in ("fixture", "chromium")
            for backend in ("wayland", "x11")
            for mode in ("headless", "vnc", "web")
        }
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            launch = Mock(
                return_value=subprocess.CompletedProcess([], 0, "container", "")
            )
            with (
                patch.object(kiosk, "__file__", str(Path(directory) / "test/kiosk.py")),
                patch.object(
                    sys,
                    "argv",
                    [
                        "kiosk",
                        "--backends",
                        "wayland",
                        "x11",
                        "--modes",
                        "headless",
                        "vnc",
                        "web",
                    ],
                ),
                patch.object(kiosk, "launch", launch),
                patch.object(kiosk, "wait_ready"),
                patch.object(
                    kiosk, "state", return_value={"supervisor": 7, "last_exit": -6}
                ),
                patch.object(kiosk, "processes", return_value=[]),
                patch.object(
                    kiosk,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0, "software", ""),
                ),
                patch.object(kiosk, "RFBClient") as client,
                patch.object(kiosk, "collect_artifacts") as collect,
                contextlib.redirect_stdout(output),
                self.assertRaises(SystemExit) as status,
            ):
                kiosk.main()
            self.assertEqual(
                set(
                    str(status.exception)
                    .removeprefix("Failed kiosk cases: ")
                    .split(", ")
                ),
                labels,
            )
            self.assertEqual(launch.call_count, len(labels))
            self.assertEqual(collect.call_count, len(labels))
            self.assertEqual(
                {call.args[2] for call in launch.call_args_list},
                {call.args[1] for call in collect.call_args_list},
            )
            client.assert_not_called()
            receipts = list(
                Path(directory).glob("test/.artifacts/kiosk-*/*/result.json")
            )
            self.assertEqual({path.parent.name for path in receipts}, labels)
            for path in receipts:
                report = json.loads(path.read_text())
                self.assertIn("running PID", report["error"])
                self.assertEqual(
                    report["initial_app_state"], {"supervisor": 7, "last_exit": -6}
                )
            self.assertEqual(output.getvalue().count("FAIL "), len(labels))
            self.assertNotIn("PASS ", output.getvalue())

    def test_partial_restart_state_waits_for_a_live_pid(self):
        spec = importlib.util.spec_from_file_location("restart_reporting_kiosk", KIOSK)
        kiosk = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kiosk)
        client = Mock()
        client.screenshot.return_value = Mock(width=1024, height=768)
        initial = {"pid": 123, "supervisor": 7}
        restarted = {"pid": 124, "supervisor": 7}
        with tempfile.TemporaryDirectory() as directory:

            def typed(_text):
                output = next(
                    Path(directory).glob(
                        "test/.artifacts/kiosk-*/*/host-files/typed.txt"
                    )
                )
                output.write_text(kiosk.EXPECTED)

            client.text.side_effect = typed
            with (
                patch.object(kiosk, "__file__", str(Path(directory) / "test/kiosk.py")),
                patch.object(
                    sys,
                    "argv",
                    [
                        "kiosk",
                        "--apps",
                        "fixture",
                        "--backends",
                        "wayland",
                        "--modes",
                        "vnc",
                    ],
                ),
                patch.object(
                    kiosk,
                    "launch",
                    return_value=subprocess.CompletedProcess([], 0, "container", ""),
                ),
                patch.object(kiosk, "wait_ready"),
                patch.object(
                    kiosk,
                    "state",
                    side_effect=[initial, {}, {"last_exit": -6}, restarted],
                ),
                patch.object(
                    kiosk,
                    "processes",
                    return_value=[("11", "kwin_wayland"), ("123", "fixture")],
                ),
                patch.object(
                    kiosk,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        [], 0, "127.0.0.1:5900", ""
                    ),
                ),
                patch.object(kiosk, "RFBClient", return_value=client),
                patch.object(kiosk, "banner_box", return_value=(12, 12, 1012, 56)),
                patch.object(kiosk.time, "sleep"),
                patch.object(kiosk, "collect_artifacts") as collect,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                kiosk.main()
            collect.assert_called_once()
            client.close.assert_called_once()
            report = json.loads(
                next(
                    Path(directory).glob("test/.artifacts/kiosk-*/*/result.json")
                ).read_text()
            )
            self.assertNotIn("error", report)
            self.assertTrue(all(report["checks"].values()))
            self.assertEqual(report["restart_app_state"], restarted)


if __name__ == "__main__":
    unittest.main()
