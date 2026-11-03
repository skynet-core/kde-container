"""Keep actual outer-SSD and cold-scale failures ahead of GUI input."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

SOURCE = Path(__file__).with_name("clipboard.py")


class NestedWindowTests(unittest.TestCase):
    def exercise(
        self,
        *,
        ssd=True,
        lost_scale=False,
        lost_app_scale=False,
        lost_entry_scale=False,
        lost_motion_precision=False,
        software_child=False,
        no_gpu=False,
        unrelated_parent_windows=False,
        duplicate_frontend=False,
        missing_frontend=False,
        frontend_pixel_loss=0,
        additional_guest_offset=False,
        missing_pointer_query=False,
        client_origin_epsilon=0,
        offgrid_pixel_loss=0,
        offgrid_guest_offset=False,
        initial_frames=None,
        requested_size=(1024, 768),
        stop_after_initial=False,
    ):
        spec = importlib.util.spec_from_file_location("nested_clipboard", SOURCE)
        clipboard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(clipboard)
        scale, now = 1.0, 0.0
        frame = {}
        active = None
        output = None
        started = []
        renderer_children = []
        client = Mock()
        parent_cursor = {"x": 0, "y": 0}
        child_cursor = {"x": 0, "y": 0}
        inside_moves = 0
        setups = []

        def sleep(seconds):
            nonlocal now
            now += seconds

        def launch(case, label, _runtime, _image, name, *_args, **_settings):
            nonlocal frame, active, output, child_cursor, inside_moves
            started.append((label, name, scale))
            if label == "inner":
                active = name
                output = case / "typed.txt"
                frame = {"x": 0, "y": 0, "width": 1024, "height": 804 if ssd else 768}
                frame.update((initial_frames or {}).get(scale, {}))
                child_cursor = {"x": 0, "y": 0}
                inside_moves = 0

        def execute(*arguments, **_settings):
            nonlocal scale
            stdout = "127.0.0.1:5900\n" if "port" in arguments else ""
            if "supportInformation" in arguments:
                renderer_children.append(arguments[3])
                renderer = "llvmpipe" if software_child else "NVIDIA GeForce RTX 3090"
                stdout = (
                    f"Compositing Type: OpenGL\nOpenGL renderer string: {renderer}\n"
                )
            if "/etc/plasma/gpu.json" in arguments:
                stdout = json.dumps(
                    {
                        "devices": [],
                        "selected": None
                        if software_child
                        else {"hardware": True, "vendor": "NVIDIA Corporation"},
                    }
                )
            if any("XQueryPointer" in argument for argument in arguments):
                if missing_pointer_query:
                    return subprocess.CompletedProcess(
                        arguments, 1, "", "XQueryPointer unavailable"
                    )
                position = [
                    round((parent_cursor["x"] - frame["x"]) * scale),
                    round((parent_cursor["y"] - frame["y"] - 36) * scale),
                ]
                if scale == 1.25 and inside_moves == 1:
                    position[0] -= frontend_pixel_loss
                if scale == 1.25 and inside_moves == 2:
                    position[0] -= offgrid_pixel_loss
                stdout = json.dumps(
                    {
                        "position": position,
                        "pixels": [round(1024 * scale), round(768 * scale)],
                    }
                )
            for argument in arguments:
                if argument.startswith("output.Virtual.scale."):
                    scale = float(argument.split(".scale.", 1)[1])
            return subprocess.CompletedProcess(arguments, 0, stdout, "")

        def state(_runtime, name, _config, _case, body=""):
            if body:
                setups.append((scale, body))
                assert not stop_after_initial, "Stopped after initial geometry"
            if "w.frameGeometry=" in body:
                frame.update(
                    json.JSONDecoder().raw_decode(body.split("w.frameGeometry=", 1)[1])[
                        0
                    ]
                )
            parent = "window-host" in name
            actual_scale = scale if parent or not lost_scale else 1
            geometry = {
                "x": 0,
                "y": 0,
                "width": 3840 / scale if parent else 1024,
                "height": 2160 / scale if parent else 768,
            }
            extra = []
            if parent and unrelated_parent_windows:
                extra = [
                    {"id": "welcome", "caption": "Welcome Center"},
                    {
                        "id": "bridge",
                        "caption": "Wayland to X Recording bridge — Xwayland Video Bridge",
                    },
                ]
            if parent and active and duplicate_frontend:
                extra.append({"id": "duplicate", "caption": "Xwayland on :110"})
            return {
                "cursor": {
                    axis: int(coordinate + (0.5 if coordinate >= 0 else -0.5))
                    for axis, coordinate in (
                        parent_cursor if parent else child_cursor
                    ).items()
                },
                "outputs": [
                    {"name": "Virtual", "scale": actual_scale, "geometry": geometry}
                ],
                "windows": extra
                + (
                    [
                        {
                            "id": active or "outer",
                            "caption": "Xwayland on :999"
                            if missing_frontend
                            else "Xwayland on :110",
                            "frame": dict(frame),
                            "client": {
                                **frame,
                                "x": frame.get("x", 0) + client_origin_epsilon,
                                "y": frame.get("y", 0) + (36 if ssd else 0),
                                "height": frame.get("height", 0) - (36 if ssd else 0),
                            },
                            "fullScreen": False,
                            "noBorder": False,
                        }
                    ]
                    if active
                    else []
                ),
            }

        def pointer(x, y):
            nonlocal inside_moves
            parent_cursor.update(x=x / scale, y=y / scale)
            if (
                frame["x"] <= parent_cursor["x"] < frame["x"] + frame["width"]
                and frame["y"] + 36 <= parent_cursor["y"] < frame["y"] + frame["height"]
            ):
                divisor = scale if lost_entry_scale else 1
                inside_moves += 1
                child_cursor.update(
                    x=(parent_cursor["x"] - frame["x"]) / divisor,
                    y=(parent_cursor["y"] - frame["y"] - 36) / divisor,
                )
                if scale == 1.25 and inside_moves == 1:
                    child_cursor["x"] -= frontend_pixel_loss / scale
                    if additional_guest_offset:
                        child_cursor["x"] += 1
                if scale == 1.25 and inside_moves == 2:
                    child_cursor["x"] -= offgrid_pixel_loss / scale
                    if offgrid_guest_offset:
                        child_cursor["x"] += 1
                if lost_motion_precision and inside_moves == 2:
                    child_cursor.update(
                        (axis, int(coordinate))
                        for axis, coordinate in child_cursor.items()
                    )

        def drag(x, y, dx, dy):
            resize = x > (frame["x"] + frame["width"]) * scale
            if resize:
                frame["width"] += dx / scale
                frame["height"] += dy / scale
            else:
                frame["x"] += dx / scale
                frame["y"] += dy / scale

        def screenshot():
            image = Image.new("RGB", (3840, 2160), "gray")
            draw = ImageDraw.Draw(image)
            left = frame["x"] + (frame["width"] - 1024) / 2
            top = frame["y"] + 36 + (frame["height"] - 36 - 768) / 2

            def box(x, y, width, height):
                return (
                    round((left + x) * scale),
                    round((top + y) * scale),
                    round((left + x + width) * scale) - 1,
                    round((top + y + height) * scale) - 1,
                )

            draw.rectangle(
                box(12, 12, 1000, 44 / scale if lost_app_scale else 44),
                fill=(18, 210, 178),
            )
            draw.rectangle(box(12, 680, 1000, 36), fill=(36, 88, 180))
            return image

        text = ""

        def type_text(value):
            nonlocal text
            text = value

        def chord(*_keys):
            output.write_text(text)

        client.drag.side_effect = drag
        client.pointer.side_effect = pointer
        client.screenshot.side_effect = screenshot
        client.text.side_effect = type_text
        client.chord.side_effect = chord
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory)
            with (
                patch.object(clipboard, "run", side_effect=execute),
                patch.object(clipboard, "launch_checked", side_effect=launch),
                patch.object(
                    clipboard,
                    "configuration",
                    return_value={
                        "PLASMA_SOFTWARE_CAPTURE": "0",
                        "PLASMA_SOFTWARE_NESTED": "1",
                        "PLASMA_SOFTWARE_DISPLAY": ":110",
                        "DISPLAY_WIDTH": str(requested_size[0]),
                        "DISPLAY_HEIGHT": str(requested_size[1]),
                    },
                ),
                patch.object(clipboard, "nested_kwin_state", side_effect=state),
                patch.object(clipboard, "NestedClient", return_value=client),
                patch.object(clipboard, "collect_artifacts") as cleanup,
                patch.object(clipboard.time, "monotonic", side_effect=lambda: now),
                patch.object(clipboard.time, "sleep", side_effect=sleep),
            ):
                error, reports = None, None
                try:
                    reports = clipboard.nested_window_phases(
                        "docker", "image", "parent", case, [], no_gpu=no_gpu
                    )
                except AssertionError as caught:
                    error = caught
                self.client, self.started, self.cleanup = (
                    client,
                    started,
                    cleanup.call_args_list,
                )
                self.renderer_children = renderer_children
                self.setups = setups
                self.phase_reports = [
                    json.loads(path.read_text())
                    for path in sorted(
                        (case / "outer-window").glob("scale-*/result.json")
                    )
                ]
                return error, reports

    def test_natural_offscreen_scale_two_rejects_before_placement_or_phase_input(self):
        error, reports = self.exercise(
            initial_frames={2: {"x": 512, "y": 384, "width": 1024, "height": 796}}
        )
        self.assertRegex(str(error), "initial frame is outside the host output")
        self.assertIsNone(reports)
        self.assertFalse(any(scale == 2 for scale, _body in self.setups))
        self.assertEqual(self.client.pointer.call_count, 6)
        self.assertEqual(self.client.drag.call_count, 4)
        self.assertEqual(self.client.click.call_count, 2)
        self.assertEqual(self.client.text.call_count, 2)
        self.assertEqual(len(self.cleanup), 4)

    def test_natural_frame_may_start_at_any_visible_position(self):
        error, reports = self.exercise(
            initial_frames={scale: {"x": 200, "y": 100} for scale in (1, 1.25, 2)}
        )
        self.assertIsNone(error)
        self.assertTrue(all(report["initial_frame_must_fit"] for report in reports))
        self.assertTrue(
            all(report["initial"]["frame"]["x"] == 200 for report in reports)
        )
        self.assertTrue(all(report["placed"]["frame"]["x"] == 80 for report in reports))
        self.assertEqual(self.client.pointer.call_count, 9)
        self.assertEqual(self.client.drag.call_count, 6)

    def test_each_edge_of_a_fitting_natural_frame_rejects_outside_before_input(self):
        for position in (
            {"x": -2},
            {"y": -2},
            {"x": 2818},
            {"y": 1358},
        ):
            with self.subTest(position=position):
                error, reports = self.exercise(initial_frames={1: position})
                self.assertRegex(str(error), "initial frame is outside the host output")
                self.assertIsNone(reports)
                self.assertEqual(self.setups, [])
                self.client.pointer.assert_not_called()
                self.client.drag.assert_not_called()
                self.client.text.assert_not_called()
                self.assertEqual(len(self.cleanup), 2)

    def test_oversized_configuration_does_not_impose_natural_containment(self):
        error, reports = self.exercise(
            initial_frames={1: {"width": 4096, "height": 2340}},
            requested_size=(4096, 2304),
            stop_after_initial=True,
        )
        self.assertRegex(str(error), "Stopped after initial geometry")
        self.assertIsNone(reports)
        self.assertFalse(self.phase_reports[0]["initial_frame_must_fit"])
        self.client.pointer.assert_not_called()
        self.client.drag.assert_not_called()

    def test_missing_actual_ssd_rejects_before_any_gui_input_and_cleans_both(self):
        error, reports = self.exercise(ssd=False)
        self.assertRegex(str(error), "no actual server decoration")
        self.assertIsNone(reports)
        for action in (
            self.client.pointer,
            self.client.drag,
            self.client.click,
            self.client.text,
            self.client.chord,
        ):
            action.assert_not_called()
        self.assertEqual(len(self.cleanup), 2)
        self.client.close.assert_called_once()

    def test_decorated_scale_one_does_not_hide_fractional_scale_loss(self):
        error, reports = self.exercise(lost_scale=True)
        self.assertRegex(str(error), "window/output did not acknowledge")
        self.assertIsNone(reports)
        self.assertEqual(
            [scale for label, _, scale in self.started if label == "inner"], [1, 1.25]
        )
        self.assertEqual(self.client.drag.call_count, 2)
        self.client.text.assert_called_once_with("Outer 1 AaZz 019!?")
        self.assertEqual(len(self.cleanup), 3)

    def test_correct_output_metadata_does_not_hide_wrong_rendered_app_scale(self):
        error, reports = self.exercise(lost_app_scale=True)
        self.assertRegex(str(error), "Scaled Qt fixture did not paint at 1.25")
        self.assertIsNone(reports)
        self.assertEqual(self.client.drag.call_count, 2)
        self.client.text.assert_called_once_with("Outer 1 AaZz 019!?")
        self.assertEqual(len(self.cleanup), 3)

    def test_first_entry_at_fractional_scale_rejects_before_any_corrective_motion(self):
        error, reports = self.exercise(lost_entry_scale=True)
        self.assertRegex(str(error), "first pointer entry did not acknowledge")
        self.assertIn("'x': 102", str(error))
        self.assertIn("'y': 77", str(error))
        self.assertIsNone(reports)
        # Scale 1 completed; scale 1.25 sent outside + exactly one entry event.
        self.assertEqual(self.client.pointer.call_count, 5)
        self.assertEqual(self.client.drag.call_count, 2)
        self.client.text.assert_called_once_with("Outer 1 AaZz 019!?")
        self.assertEqual(len(self.cleanup), 3)

    def test_offgrid_motion_rejects_small_truncation_after_aligned_entry_passes(self):
        error, reports = self.exercise(lost_motion_precision=True)
        self.assertRegex(str(error), "off-grid pointer did not acknowledge")
        self.assertIsNone(reports)
        self.assertEqual(self.client.pointer.call_count, 6)
        self.assertEqual(self.client.drag.call_count, 2)
        self.client.text.assert_called_once_with("Outer 1 AaZz 019!?")
        self.assertEqual(len(self.cleanup), 3)

    def test_three_cold_children_use_one_move_resize_input_save_per_scale(self):
        error, reports = self.exercise()
        self.assertIsNone(error)
        self.assertEqual([report["scale"] for report in reports], [1, 1.25, 2])
        self.assertTrue(all(report["passed"] for report in reports))
        self.assertTrue(all(report["nvidia_renderer"] for report in reports))
        self.assertTrue(
            all(report["gpu"]["selected"]["hardware"] for report in reports)
        )
        self.assertEqual(
            self.renderer_children,
            [name for label, name, _ in self.started if label == "inner"],
        )
        self.assertEqual(self.client.pointer.call_count, 9)
        for report in reports:
            self.assertEqual(report["pointer_entry"]["entry_events"], 1)
            self.assertEqual(
                report["pointer_entry"]["observed_child_logical"], {"x": 128, "y": 96}
            )
            self.assertEqual(report["pointer_offgrid"]["motion_events"], 1)
            self.assertEqual(
                report["pointer_offgrid"]["observed_child_logical"],
                report["pointer_offgrid"]["expected_child_logical_integer"],
            )
        self.assertEqual(self.client.drag.call_count, 6)
        self.assertEqual(self.client.click.call_count, 3)
        self.assertEqual(self.client.text.call_count, 3)
        self.assertEqual(self.client.chord.call_count, 3)
        self.assertEqual(
            len({name for label, name, _ in self.started if label == "inner"}), 3
        )
        self.assertEqual(len(self.cleanup), 4)
        self.client.close.assert_called_once()

    def test_cpu_phase_records_all_three_software_children_without_requiring_nvidia(
        self,
    ):
        error, reports = self.exercise(software_child=True, no_gpu=True)
        self.assertIsNone(error)
        self.assertEqual(len(reports), 3)
        self.assertTrue(all(report["software_renderer"] for report in reports))
        self.assertFalse(any(report["nvidia_renderer"] for report in reports))
        self.assertEqual(
            self.renderer_children,
            [name for label, name, _ in self.started if label == "inner"],
        )

    def test_gpu_phase_rejects_a_software_child_before_pointer_input(self):
        error, reports = self.exercise(software_child=True)
        self.assertRegex(str(error), "actual hardware renderer in the cold child")
        self.assertIsNone(reports)
        self.client.pointer.assert_not_called()
        self.client.drag.assert_not_called()
        self.assertEqual(len(self.renderer_children), 1)
        self.assertEqual(len(self.cleanup), 2)

    def test_unrelated_parent_desktop_windows_preserve_frontend_selection_and_all_input(
        self,
    ):
        error, reports = self.exercise(unrelated_parent_windows=True)
        self.assertIsNone(error)
        self.assertEqual(len(reports), 3)
        self.assertTrue(all(report["passed"] for report in reports))
        self.assertTrue(
            all(report["placed"]["caption"] == "Xwayland on :110" for report in reports)
        )
        self.assertEqual(self.client.pointer.call_count, 9)
        self.assertEqual(self.client.drag.call_count, 6)
        self.assertEqual(self.client.click.call_count, 3)
        self.assertEqual(self.client.text.call_count, 3)
        self.assertEqual(self.client.chord.call_count, 3)

    def test_duplicate_matching_private_frontends_reject_before_input(self):
        error, reports = self.exercise(duplicate_frontend=True)
        self.assertRegex(str(error), "window/output did not acknowledge")
        self.assertIsNone(reports)
        self.client.pointer.assert_not_called()
        self.client.drag.assert_not_called()
        self.assertEqual(len(self.cleanup), 2)

    def test_unrelated_single_window_cannot_replace_missing_private_frontend(self):
        error, reports = self.exercise(missing_frontend=True)
        self.assertRegex(str(error), "window/output did not acknowledge")
        self.assertIsNone(reports)
        self.client.pointer.assert_not_called()
        self.client.drag.assert_not_called()
        self.assertEqual(len(self.cleanup), 2)

    def test_one_physical_pixel_endpoint_error_keeps_exact_child_rounding(self):
        error, reports = self.exercise(frontend_pixel_loss=1)
        self.assertIsNone(error)
        phase = reports[1]["pointer_entry"]
        self.assertEqual(phase["requested_frontend_physical"], [160, 120])
        self.assertEqual(phase["observed_frontend"]["position"], [159, 120])
        self.assertEqual(phase["observed_child_logical"], {"x": 127, "y": 96})
        self.assertEqual(phase["expected_child_logical_integer"], {"x": 127, "y": 96})
        self.assertEqual(phase["physical_tolerance"], 1)
        self.assertEqual(self.client.pointer.call_count, 9)
        self.assertEqual(self.client.drag.call_count, 6)

    def test_two_physical_pixels_reject_even_when_guest_matches_endpoint(self):
        error, reports = self.exercise(frontend_pixel_loss=2)
        self.assertRegex(str(error), "first pointer entry did not acknowledge")
        self.assertIsNone(reports)
        self.assertEqual(self.client.pointer.call_count, 5)
        self.assertEqual(self.client.drag.call_count, 2)

    def test_additional_guest_offset_rejects_an_exact_frontend_endpoint(self):
        error, reports = self.exercise(additional_guest_offset=True)
        self.assertRegex(str(error), "first pointer entry did not acknowledge")
        self.assertIsNone(reports)
        self.assertEqual(self.client.pointer.call_count, 5)
        self.assertEqual(self.client.drag.call_count, 2)

    def test_missing_physical_query_fails_without_another_pointer_event(self):
        error, reports = self.exercise(missing_pointer_query=True)
        self.assertRegex(str(error), "XQueryPointer unavailable")
        self.assertIsNone(reports)
        self.assertEqual(self.client.pointer.call_count, 2)
        self.client.drag.assert_not_called()
        self.client.text.assert_not_called()
        self.assertEqual(len(self.cleanup), 2)

    def test_float_representation_of_one_pixel_boundary_is_accepted(self):
        error, reports = self.exercise(
            frontend_pixel_loss=1, client_origin_epsilon=-1e-12
        )
        self.assertIsNone(error)
        phase = reports[1]["pointer_entry"]
        difference = (
            phase["requested_frontend_physical"][0]
            - phase["observed_frontend"]["position"][0]
        )
        self.assertGreater(difference, 1)
        self.assertLess(difference, 1 + 1e-6)
        self.assertEqual(phase["observed_child_logical"], {"x": 127, "y": 96})
        self.assertEqual(phase["physical_tolerance"], 1)
        self.assertEqual(phase["arithmetic_epsilon"], 1e-6)

    def test_endpoint_beyond_arithmetic_epsilon_still_rejects(self):
        error, reports = self.exercise(
            frontend_pixel_loss=1, client_origin_epsilon=-2e-6
        )
        self.assertRegex(str(error), "first pointer entry did not acknowledge")
        self.assertIsNone(reports)
        self.assertEqual(self.client.pointer.call_count, 5)

    def test_one_physical_pixel_offgrid_error_keeps_exact_child_consistency(self):
        error, reports = self.exercise(offgrid_pixel_loss=1)
        self.assertIsNone(error)
        offgrid = reports[1]["pointer_offgrid"]
        self.assertEqual(offgrid["requested_frontend_physical"], [1151, 863])
        self.assertEqual(offgrid["observed_frontend"]["position"], [1150, 863])
        self.assertEqual(
            offgrid["requested_child_logical_integer"], {"x": 921, "y": 690}
        )
        self.assertEqual(
            offgrid["expected_child_logical_integer"], {"x": 920, "y": 690}
        )
        self.assertEqual(offgrid["observed_child_logical"], {"x": 920, "y": 690})
        self.assertEqual(offgrid["physical_tolerance"], 1)
        self.assertEqual(offgrid["motion_events"], 1)
        self.assertEqual(self.client.pointer.call_count, 9)
        self.assertEqual(self.client.drag.call_count, 6)

    def test_two_physical_pixel_offgrid_error_rejects_consistent_guest(self):
        error, reports = self.exercise(offgrid_pixel_loss=2)
        self.assertRegex(str(error), "off-grid pointer did not acknowledge")
        self.assertIsNone(reports)
        self.assertEqual(self.client.pointer.call_count, 6)
        self.assertEqual(self.client.drag.call_count, 2)

    def test_extra_guest_offgrid_offset_rejects_exact_frontend(self):
        error, reports = self.exercise(offgrid_guest_offset=True)
        self.assertRegex(str(error), "off-grid pointer did not acknowledge")
        self.assertIsNone(reports)
        self.assertEqual(self.client.pointer.call_count, 6)
        self.assertEqual(self.client.drag.call_count, 2)


if __name__ == "__main__":
    unittest.main()
