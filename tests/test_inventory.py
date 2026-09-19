import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from provenance_inventory.inventory import InventoryError, PROJECT_ROOT, scan


class InventoryTests(unittest.TestCase):
    def write_config(self, folder: Path, source: Path) -> Path:
        config = folder / "sources.json"
        config.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sources": [
                        {
                            "id": "fixture",
                            "label": "Fixture",
                            "path": str(source),
                            "include_hidden": True,
                            "exclude_globs": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return config

    def local_output(self) -> Path:
        output = PROJECT_ROOT / "data" / f"test-inventory-{uuid.uuid4().hex}"
        self.addCleanup(shutil.rmtree, output, True)
        return output

    def test_inventory_is_read_only_and_groups_exact_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            sandbox = Path(temporary)
            source = sandbox / "source"
            source.mkdir()
            original = source / "thought.txt"
            duplicate = source / "thought-copy.txt"
            project = source / "project"
            project.mkdir()
            marker = project / "pyproject.toml"
            original.write_text("A living idea.\n", encoding="utf-8")
            duplicate.write_text("A living idea.\n", encoding="utf-8")
            marker.write_text("[project]\nname='fixture'\n", encoding="utf-8")
            before = {
                path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in (original, duplicate, marker)
            }

            run_dir = scan(self.write_config(sandbox, source), self.local_output())
            summary = json.loads((run_dir / "summary.json").read_text("utf-8"))
            duplicates = json.loads(
                (run_dir / "duplicates.json").read_text("utf-8")
            )

            self.assertEqual(summary["file_count"], 3)
            self.assertEqual(summary["media_counts"]["text"], 3)
            self.assertEqual(summary["project_marker_count"], 1)
            self.assertEqual(summary["duplicate_group_count"], 1)
            self.assertEqual(duplicates[0]["count"], 2)
            for path, (content, modified) in before.items():
                self.assertEqual(path.read_bytes(), content)
                self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_allows_a_dedicated_output_outside_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            sandbox = Path(temporary)
            source = sandbox / "source"
            source.mkdir()
            config = self.write_config(sandbox, source)
            output = sandbox / "output"
            run_dir = scan(config, output)
            self.assertTrue((run_dir / "summary.json").exists())

    def test_refuses_drive_root_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            sandbox = Path(temporary)
            source = sandbox / "source"
            source.mkdir()
            config = self.write_config(sandbox, source)
            with self.assertRaises(InventoryError):
                scan(config, Path(Path.cwd().anchor))

    def test_refuses_source_that_contains_dashboard_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            sandbox = Path(temporary)
            config = self.write_config(sandbox, PROJECT_ROOT.parent)
            with self.assertRaises(InventoryError):
                scan(config, self.local_output())

    def test_refuses_output_nested_in_a_source(self):
        source = PROJECT_ROOT / "data"
        source.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory() as temporary:
            sandbox = Path(temporary)
            config = self.write_config(sandbox, source)
            with self.assertRaises(InventoryError):
                scan(config, source / "inventory")

    def test_hidden_and_excluded_files_can_be_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            sandbox = Path(temporary)
            source = sandbox / "source"
            source.mkdir()
            (source / "keep.txt").write_text("keep", encoding="utf-8")
            (source / ".hidden.txt").write_text("hidden", encoding="utf-8")
            (source / "skip.log").write_text("skip", encoding="utf-8")
            config = sandbox / "sources.json"
            config.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "sources": [
                            {
                                "id": "fixture",
                                "label": "Fixture",
                                "path": str(source),
                                "include_hidden": False,
                                "exclude_globs": ["*.log"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            run_dir = scan(config, sandbox / "output")
            lines = (run_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
            records = [json.loads(line) for line in lines]
            self.assertEqual([record["relative_path"] for record in records], ["keep.txt"])

    def test_symlink_is_not_followed_when_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            sandbox = Path(temporary)
            source = sandbox / "source"
            outside = sandbox / "outside"
            source.mkdir()
            outside.mkdir()
            (outside / "private.txt").write_text("outside", encoding="utf-8")
            link = source / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            run_dir = scan(self.write_config(sandbox, source), sandbox / "output")
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["file_count"], 0)


if __name__ == "__main__":
    unittest.main()
