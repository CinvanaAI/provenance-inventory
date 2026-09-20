"""Read-only, append-only source census for Dashboard.

The scanner opens configured source files for reading and writes only beneath
the explicitly selected inventory-output directory.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import mimetypes
import os
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCANNER_VERSION = "0.1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = Path.cwd() / "inventory-output"
HASH_CHUNK_BYTES = 1024 * 1024

MEDIA_EXTENSIONS: dict[str, set[str]] = {
    "image": {
        ".avif", ".bmp", ".gif", ".heic", ".heif", ".jpeg", ".jpg",
        ".png", ".psd", ".raw", ".svg", ".tif", ".tiff", ".webp",
    },
    "audio": {
        ".aac", ".aiff", ".alac", ".flac", ".m4a", ".mp3", ".ogg",
        ".opus", ".wav", ".wma",
    },
    "video": {
        ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg",
        ".webm", ".wmv",
    },
    "pdf": {".pdf"},
    "document": {
        ".doc", ".docx", ".epub", ".odt", ".pages", ".ppt", ".pptx",
        ".rtf",
    },
    "spreadsheet": {
        ".csv", ".numbers", ".ods", ".tsv", ".xls", ".xlsb", ".xlsm",
        ".xlsx",
    },
    "notebook": {".ipynb"},
    "source_code": {
        ".c", ".cc", ".cpp", ".cs", ".css", ".dart", ".fs", ".go",
        ".h", ".hpp", ".html", ".java", ".js", ".jsx", ".kt", ".lua",
        ".m", ".php", ".pl", ".ps1", ".py", ".r", ".rb", ".rs", ".scss",
        ".sh", ".sql", ".swift", ".ts", ".tsx", ".vue",
    },
    "text": {
        ".ini", ".log", ".md", ".org", ".rst", ".text", ".toml", ".txt",
        ".yaml", ".yml",
    },
    "structured_data": {
        ".geojson", ".json", ".jsonl", ".ndjson", ".parquet", ".xml",
    },
    "archive": {
        ".7z", ".bz2", ".gz", ".rar", ".tar", ".tgz", ".xz", ".zip",
    },
}

PROJECT_MARKERS = {
    ".git",
    "cargo.toml",
    "composer.json",
    "environment.yml",
    "gemfile",
    "go.mod",
    "package.json",
    "pixi.toml",
    "poetry.lock",
    "pom.xml",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
}


class InventoryError(RuntimeError):
    """Raised when a safety invariant or configuration rule is violated."""


@dataclass(frozen=True)
class Source:
    source_id: str
    label: str
    path: Path
    include_hidden: bool
    exclude_globs: tuple[str, ...]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def ensure_output_is_local(output_root: Path) -> Path:
    resolved = output_root.expanduser().resolve()
    if resolved in {Path(resolved.anchor), Path.home().resolve()}:
        raise InventoryError(f"Refusing unsafe inventory output root: {resolved}")
    return resolved


def load_sources(config_path: Path) -> tuple[list[Source], str]:
    raw = config_path.read_bytes()
    config_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InventoryError(f"Invalid JSON in {config_path}: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("sources"), list):
        raise InventoryError("Source config must have version 1 and a sources list.")
    if not payload["sources"]:
        raise InventoryError("Source config contains no sources.")

    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    sources: list[Source] = []
    project = PROJECT_ROOT.resolve()

    for index, item in enumerate(payload["sources"]):
        if not isinstance(item, dict):
            raise InventoryError(f"Source {index} must be an object.")
        source_id = str(item.get("id", "")).strip()
        label = str(item.get("label", source_id)).strip()
        raw_path = str(item.get("path", "")).strip()
        if not source_id or not label or not raw_path:
            raise InventoryError(f"Source {index} requires id, label, and path.")
        if source_id in seen_ids:
            raise InventoryError(f"Duplicate source id: {source_id}")

        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise InventoryError(f"Source path must be absolute: {raw_path}")
        path = path.resolve()
        if not path.is_dir():
            raise InventoryError(f"Source folder does not exist: {path}")
        if path in seen_paths:
            raise InventoryError(f"Duplicate source path: {path}")
        if path == project or is_relative_to(project, path):
            raise InventoryError(
                "A source may not be the Dashboard root or contain it: "
                f"{path}"
            )

        exclude_globs = item.get("exclude_globs", [])
        include_hidden = item.get("include_hidden", True)
        if not isinstance(include_hidden, bool):
            raise InventoryError(f"include_hidden for {source_id} must be a boolean.")
        if not isinstance(exclude_globs, list) or not all(
            isinstance(value, str) for value in exclude_globs
        ):
            raise InventoryError(
                f"exclude_globs for {source_id} must be a list of strings."
            )

        sources.append(
            Source(
                source_id=source_id,
                label=label,
                path=path,
                include_hidden=include_hidden,
                exclude_globs=tuple(exclude_globs),
            )
        )
        seen_ids.add(source_id)
        seen_paths.add(path)

    return sources, config_sha256


def is_hidden(relative_path: Path) -> bool:
    return any(part.startswith(".") for part in relative_path.parts)


def is_excluded(relative_path: Path, patterns: tuple[str, ...]) -> bool:
    posix = relative_path.as_posix()
    return any(
        fnmatch.fnmatch(relative_path.name, pattern)
        or fnmatch.fnmatch(posix, pattern)
        for pattern in patterns
    )


def is_indirection(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def walk_files(source: Source) -> Iterator[tuple[Path, Path]]:
    pending = [source.path]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            ordered = sorted(entries, key=lambda entry: entry.name.casefold())
        child_directories: list[Path] = []
        for entry in ordered:
            path = Path(entry.path)
            relative = path.relative_to(source.path)
            if not source.include_hidden and is_hidden(relative):
                continue
            if is_excluded(relative, source.exclude_globs):
                continue
            if entry.is_symlink() or is_indirection(path):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    child_directories.append(path)
                elif entry.is_file(follow_symlinks=False):
                    yield path, relative
            except OSError:
                yield path, relative
        pending.extend(reversed(child_directories))


def classify(path: Path) -> str:
    suffix = path.suffix.lower()
    for medium, extensions in MEDIA_EXTENSIONS.items():
        if suffix in extensions:
            return medium
    return "other"


def hash_file(path: Path) -> tuple[str, os.stat_result]:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise InventoryError("File changed while it was being hashed.")
    return digest.hexdigest(), after


def record_for(
    source: Source,
    path: Path,
    relative: Path,
    run_id: str,
) -> dict[str, Any]:
    digest, stat = hash_file(path)
    guessed_mime, _ = mimetypes.guess_type(path.name)
    marker = path.name.casefold() in PROJECT_MARKERS
    return {
        "schema_version": 1,
        "run_id": run_id,
        "scanner_version": SCANNER_VERSION,
        "source_id": source.source_id,
        "source_label": source.label,
        "original_path": str(path),
        "relative_path": relative.as_posix(),
        "name": path.name,
        "extension": path.suffix.lower(),
        "media_kind": classify(path),
        "mime_hint": guessed_mime,
        "size_bytes": stat.st_size,
        "modified_time_ns": stat.st_mtime_ns,
        "created_or_changed_time_ns": stat.st_ctime_ns,
        "birth_time_ns": getattr(stat, "st_birthtime_ns", None),
        "sha256": digest,
        "hash_status": "full",
        "is_project_marker": marker,
    }


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def scan(config_path: Path, output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    output_root = ensure_output_is_local(output_root)
    sources, config_sha256 = load_sources(config_path)
    for source in sources:
        if output_root == source.path or is_relative_to(output_root, source.path):
            raise InventoryError(
                "Inventory output may not be inside a configured source root: "
                f"{source.path}"
            )
    output_root.mkdir(parents=True, exist_ok=True)

    started_at = utc_now()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    run_dir = output_root / run_id
    run_dir.mkdir()

    state = {
        "schema_version": 1,
        "run_id": run_id,
        "scanner_version": SCANNER_VERSION,
        "status": "scanning",
        "started_at": started_at,
        "config_sha256": config_sha256,
    }
    write_json(run_dir / "run.json", state)

    media_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    total_bytes = 0
    file_count = 0
    error_count = 0
    project_marker_count = 0
    hashes: dict[str, list[dict[str, str]]] = defaultdict(list)

    manifest_path = run_dir / "manifest.jsonl"
    errors_path = run_dir / "errors.jsonl"
    with (
        manifest_path.open("w", encoding="utf-8", newline="\n") as manifest,
        errors_path.open("w", encoding="utf-8", newline="\n") as errors,
    ):
        for source in sources:
            try:
                candidates = walk_files(source)
                for path, relative in candidates:
                    try:
                        record = record_for(source, path, relative, run_id)
                    except (OSError, InventoryError) as exc:
                        error_count += 1
                        errors.write(
                            json.dumps(
                                {
                                    "run_id": run_id,
                                    "source_id": source.source_id,
                                    "original_path": str(path),
                                    "relative_path": relative.as_posix(),
                                    "error_type": type(exc).__name__,
                                    "message": str(exc),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                        continue

                    manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
                    file_count += 1
                    total_bytes += record["size_bytes"]
                    media_counts[record["media_kind"]] += 1
                    source_counts[source.source_id] += 1
                    project_marker_count += int(record["is_project_marker"])
                    hashes[record["sha256"]].append(
                        {
                            "source_id": source.source_id,
                            "original_path": record["original_path"],
                            "relative_path": record["relative_path"],
                        }
                    )
            except OSError as exc:
                error_count += 1
                errors.write(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "source_id": source.source_id,
                            "original_path": str(source.path),
                            "relative_path": "",
                            "error_type": type(exc).__name__,
                            "message": str(exc),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    duplicate_groups = [
        {"sha256": digest, "count": len(items), "items": items}
        for digest, items in hashes.items()
        if len(items) > 1
    ]
    duplicate_groups.sort(key=lambda group: (-group["count"], group["sha256"]))
    write_json(run_dir / "duplicates.json", duplicate_groups)

    completed_at = utc_now()
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "scanner_version": SCANNER_VERSION,
        "status": "complete",
        "started_at": started_at,
        "completed_at": completed_at,
        "config_sha256": config_sha256,
        "source_count": len(sources),
        "sources": [
            {
                "source_id": source.source_id,
                "label": source.label,
                "path": str(source.path),
                "file_count": source_counts[source.source_id],
            }
            for source in sources
        ],
        "file_count": file_count,
        "total_bytes": total_bytes,
        "media_counts": dict(sorted(media_counts.items())),
        "project_marker_count": project_marker_count,
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_file_count": sum(group["count"] for group in duplicate_groups),
        "error_count": error_count,
    }
    write_json(run_dir / "summary.json", summary)
    write_json(run_dir / "run.json", summary)
    write_json(
        output_root / "latest.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "completed_at": completed_at,
            "summary": f"{run_id}/summary.json",
        },
    )
    return run_dir


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory allowlisted source folders without changing them."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.cwd() / "sources.json",
        help="Path to the local source allowlist.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Dedicated output folder; must not be a source, drive root, or home directory.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        run_dir = scan(args.config.resolve(), args.output.resolve())
    except (OSError, InventoryError) as exc:
        print(f"Inventory stopped: {exc}", file=sys.stderr)
        return 2
    print(f"Inventory complete: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
