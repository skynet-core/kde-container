"""Dispatch the real Dolphin paste only to its ready application window."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SOURCE = Path(__file__).with_name("clipboard.py")


class DolphinReadinessTests(unittest.TestCase):
    def exercise(self, *, ready_at=5, invalid=None):
        spec = importlib.util.spec_from_file_location("dolphin_clipboard", SOURCE)
        clipboard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(clipboard)
        now = 0.0
        events, commands = [], []
        tag = None
        payload = {}
        dialog = False

        def sleep(seconds):
            nonlocal now
            now += seconds

        def window():
            result = {
                "pid": 22 if now >= ready_at else 11,
                "normal": True,
                "active": True,
                "minimized": False,
                "hidden": False,
                "frame": {"x": 0, "y": 0, "width": 1024, "height": 768},
            }
            if invalid in ("normal", "active"):
                result[invalid] = False
            elif invalid in ("hidden", "minimized"):
                result[invalid] = True
            elif invalid == "frame":
                result["frame"]["width"] = 0
            return result

        def execute(*arguments, **_settings):
            nonlocal tag
            commands.append(arguments)
            stdout, status = "", 0
            if "loadScript" in arguments:
                tag = arguments[-1]
                stdout = "7\n"
            elif "journalctl" in arguments:
                stdout = tag + " " + json.dumps(window()) + "\n"
            elif "python3" in arguments and arguments[-1] in ("11", "22"):
                pid = arguments[-1]
                if invalid == "dead-pid":
                    status = 1
                else:
                    argv = (
                        ["/usr/bin/dolphin", "--new-window", "/e2e-images/dolphin"]
                        if pid == "22"
                        else ["plasma-ui-fixture", "/e2e-output/typed.txt"]
                    )
                    if invalid == "wrong-url":
                        argv[-1] = "/unrelated-directory"
                    stdout = json.dumps({"argv": argv, "state": "S"})
            return subprocess.CompletedProcess(arguments, status, stdout, "")

        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory)
            (case / "images").mkdir()
            expected = clipboard.expected_image(publisher=True)
            expected.save(case / "images/host-qt.png")

            def click(x, y):
                events.append(("click", now >= ready_at, x, y))

            def chord(*keys):
                nonlocal dialog
                events.append(("chord", now >= ready_at, *keys))
                dialog = now >= ready_at

            def key(symbol, down):
                events.append(("key", now >= ready_at, symbol, down))
                if symbol == 0xFF0D and down and dialog:
                    (case / "images/dolphin/Dolphin screenshot.png").write_bytes(
                        payload["image/png"]
                    )

            client = Mock(width=1024, height=768)
            client.click.side_effect = click
            client.chord.side_effect = chord
            client.key.side_effect = key
            client.screenshot.side_effect = lambda: expected.convert("RGB").resize(
                (1024, 768)
            )
            host_probe = Mock()
            host_probe.set.side_effect = payload.update
            inner_probe = Mock()
            with (
                patch.object(clipboard, "run", side_effect=execute),
                patch.object(clipboard.time, "sleep", side_effect=sleep),
                patch.object(clipboard.time, "monotonic", side_effect=lambda: now),
            ):
                try:
                    clipboard.dolphin_image_check(
                        "docker", "owned", {}, case, client, host_probe, inner_probe
                    )
                finally:
                    self.events, self.commands = events, commands
                    self.elapsed = now
            inner_probe.wait.assert_called_once()
            self.assertTrue((case / "dolphin-image.json").exists())

    def assert_cleaned_up(self):
        self.assertEqual(sum("unloadScript" in command for command in self.commands), 1)
        self.assertEqual(
            sum(command[-3:-1] == ("rm", "-f") for command in self.commands), 1
        )

    def test_delayed_window_receives_one_unchanged_paste_sequence(self):
        self.exercise()
        self.assertEqual(
            self.events,
            [
                ("click", True, 512, 384),
                ("chord", True, 0xFFE3, ord("v")),
                ("key", True, 0xFF0D, True),
                ("key", True, 0xFF0D, False),
            ],
        )
        self.assert_cleaned_up()

    def test_unready_or_unrelated_window_times_out_without_input_and_cleans_up(self):
        for invalid in (
            "never-mapped",
            "dead-pid",
            "wrong-url",
            "normal",
            "active",
            "minimized",
            "hidden",
            "frame",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    AssertionError,
                    "Dolphin did not become the active application window",
                ):
                    self.exercise(
                        ready_at=float("inf") if invalid == "never-mapped" else 0,
                        invalid=invalid,
                    )
                self.assertEqual(self.events, [])
                self.assertGreaterEqual(self.elapsed, 20)
                self.assertLess(self.elapsed, 20.2)
                self.assert_cleaned_up()


if __name__ == "__main__":
    unittest.main()
