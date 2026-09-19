"""Hash three synthetic files, detect one exact duplicate pair, prove no source changes."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from provenance_inventory.inventory import scan

with tempfile.TemporaryDirectory(prefix="inventory-example-") as temporary:
    root = Path(temporary)
    if os.name == "nt":
        root = Path("\\\\?\\" + str(root.resolve()))
    source = root / "source"
    source.mkdir()
    (source / "one.txt").write_text("Synthetic note.", encoding="utf-8")
    (source / "copy.txt").write_text("Synthetic note.", encoding="utf-8")
    (source / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    def hashes():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    before = hashes()
    config = root / "sources.json"
    config.write_text(json.dumps({"version": 1, "sources": [{"id": "demo", "label": "Synthetic", "path": str(source), "include_hidden": True, "exclude_globs": []}]}), encoding="utf-8")
    run = scan(config, root / "out")
    summary = json.loads((run / "summary.json").read_text())
    manifest = [json.loads(line) for line in (run / "manifest.jsonl").read_text().splitlines()]
    assert before == hashes() and summary["duplicate_group_count"] == 1
    print(json.dumps({"source_unchanged": before == hashes(), "files": before, "summary": {key: summary[key] for key in ("status", "file_count", "project_marker_count", "duplicate_group_count", "duplicate_file_count", "error_count")}, "manifest_fields": sorted(manifest[0])}, indent=2))
