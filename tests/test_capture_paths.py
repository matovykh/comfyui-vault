import errno
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


HELPER = Path(__file__).parents[1] / "custom_nodes/comfyui_vault/capture.py"
spec = importlib.util.spec_from_file_location("vault_capture_paths", HELPER)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CapturePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name in ("input", "output", "temp", "extra"):
            (self.root / name).mkdir()
        root = self.root

        class Folders:
            folder_names_and_paths = {}

            @staticmethod
            def get_annotated_filepath(value):
                for label in ("input", "output", "temp"):
                    annotation = f" [{label}]"
                    if value.endswith(annotation):
                        return str(root / label / value[:-len(annotation)])
                return str(root / "input" / value)

            @staticmethod
            def get_input_directory(): return str(root / "input")

            @staticmethod
            def get_output_directory(): return str(root / "output")

            @staticmethod
            def get_temp_directory(): return str(root / "temp")

        self.folders = Folders
        self.settings = {"hash_models": False, "extra_input_roots": [str(root / "extra")]}

    def test_snapshot_removes_only_runtime_fingerprints_without_mutating_graph(self):
        graph = {
            "1": {"class_type": "KSampler", "inputs": {"seed": 18446744073709551615,
                  "cfg": 6.5, "is_changed": "an actual input"}, "is_changed": [float("nan")]},
            "2": {"class_type": "LoadImage", "inputs": {}, "is_changed": float("nan")},
        }
        saved = capture.snapshot_prompt(graph)
        json.dumps(saved, allow_nan=False)
        self.assertNotIn("is_changed", saved["1"])
        self.assertNotIn("is_changed", saved["2"])
        self.assertEqual(saved["1"]["inputs"], graph["1"]["inputs"])
        self.assertTrue(math.isnan(graph["1"]["is_changed"][0]))
        self.assertTrue(math.isnan(graph["2"]["is_changed"]))

    def test_snapshot_does_not_silently_replace_invalid_generation_parameters(self):
        graph = {"1": {"class_type": "KSampler", "inputs": {"cfg": float("nan")}}}
        with self.assertRaises(ValueError):
            json.dumps(capture.snapshot_prompt(graph), allow_nan=False)

    def test_long_prompt_and_reference_can_be_archived_together(self):
        text = "# CHARACTER SHEET\n\n" + "Preserve facial identity. " * 200
        reference = self.root / "input" / "reference.png"
        reference.write_bytes(b"reference bytes")
        graph = {
            "1": {"class_type": "CLIPTextEncode", "inputs": {"text": text}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "reference.png"}},
            "3": {"class_type": "ComfyVaultArchiveImages",
                  "inputs": {"images": ["2", 0], "metadata": ["1", 0]}},
        }
        refs, models, warnings, used = capture.collect(graph, "3", self.folders, self.settings)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["source"], reference)
        self.assertEqual(refs[0]["comfy_path"], "input/reference.png")
        self.assertEqual(used, {"1", "2", "3"})
        archive_path = self.root / "capture.zip"
        capture.build_archive(archive_path, {"prompt": graph}, [{**refs[0], "role": "input"}])
        with zipfile.ZipFile(archive_path) as archive:
            payload = json.loads(archive.read("capture.json"))
            self.assertEqual(payload["prompt"]["1"]["inputs"]["text"], text)
            self.assertEqual(archive.read(payload["files"][0]["path"]), b"reference bytes")

    def test_non_paths_return_none(self):
        for value in ("x" * 10000, "long prompt\n" * 500, "bad\x00name", "missing.png", "", None, 42):
            with self.subTest(value=repr(value)[:50]):
                self.assertIsNone(capture.resolve_input(value, self.folders, self.settings))

    def test_path_errors_during_resolution_and_stat_return_none(self):
        for error in (OSError(errno.ENAMETOOLONG, "too long"), PermissionError("denied"),
                      ValueError("invalid path"), RuntimeError("symlink loop")):
            for operation in ("resolve", "is_file"):
                with self.subTest(error=type(error).__name__, operation=operation):
                    with patch.object(Path, operation, side_effect=error):
                        self.assertIsNone(capture.resolve_input("reference.png", self.folders, self.settings))
        with patch.object(self.folders, "get_annotated_filepath", side_effect=OSError("invalid path")):
            self.assertIsNone(capture.resolve_input("reference.png", self.folders, self.settings))

    def test_allowed_files_and_annotations_still_resolve(self):
        for label in ("input", "output", "temp", "extra"):
            path = self.root / label / "Референс с пробелами.png"
            path.write_bytes(b"ref")
            values = [str(path)]
            if label != "extra":
                values.append(f"{path.name} [{label}]")
            if label == "input":
                values.append(path.name)
            for value in values:
                with self.subTest(value=value):
                    self.assertEqual(capture.resolve_input(value, self.folders, self.settings), path)

    def test_weights_and_paths_outside_allowed_roots_are_rejected(self):
        paths = [self.root / "outside.png", self.root / "input" / "model.safetensors"]
        for path in paths:
            path.write_bytes(b"file")
            self.assertIsNone(capture.resolve_input(str(path), self.folders, self.settings))
        link = self.root / "input" / "linked.png"
        link.symlink_to(paths[0])
        self.assertIsNone(capture.resolve_input(link.name, self.folders, self.settings))


if __name__ == "__main__":
    unittest.main()
