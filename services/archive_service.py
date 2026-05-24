"""Archive service for collecting final pipeline artifacts."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_ROOT = PROJECT_ROOT / "data" / "archive"


def slugify_topic(topic: str) -> str:
    compact = "_".join((topic or "").strip().lower().split())
    safe = "".join(char if char.isalnum() or char == "_" else "_" for char in compact)
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "report"


def ensure_archive_dirs(topic: str) -> dict[str, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = ARCHIVE_ROOT / f"{slugify_topic(topic)}_{timestamp}"
    dirs = {
        "base": base_dir,
        "reports": base_dir / "reports",
        "visualizations": base_dir / "visualizations",
        "processed": base_dir / "processed",
        "logs": base_dir / "logs",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def copy_if_exists(source: str | Path | None, destination_dir: Path) -> str:
    if not source:
        return ""
    source_path = Path(source)
    if not source_path.exists() or not source_path.is_file():
        return ""
    destination = destination_dir / source_path.name
    shutil.copy2(source_path, destination)
    return str(destination)


def archive_pipeline_results(
    topic: str,
    report_files: list[str | Path],
    visualization_files: list[str | Path],
    processed_files: list[str | Path],
    log_files: list[str | Path],
) -> dict:
    dirs = ensure_archive_dirs(topic)

    saved_reports = [path for path in (copy_if_exists(item, dirs["reports"]) for item in report_files) if path]
    saved_visualizations = [
        path for path in (copy_if_exists(item, dirs["visualizations"]) for item in visualization_files) if path
    ]
    saved_processed = [path for path in (copy_if_exists(item, dirs["processed"]) for item in processed_files) if path]
    saved_logs = [path for path in (copy_if_exists(item, dirs["logs"]) for item in log_files) if path]

    requested = {
        "reports": [str(item) for item in report_files if item],
        "visualizations": [str(item) for item in visualization_files if item],
        "processed": [str(item) for item in processed_files if item],
        "logs": [str(item) for item in log_files if item],
    }
    saved = {
        "reports": saved_reports,
        "visualizations": saved_visualizations,
        "processed": saved_processed,
        "logs": saved_logs,
    }
    missing = {
        key: [path for path in requested[key] if Path(path).name not in {Path(saved_path).name for saved_path in saved[key]}]
        for key in requested
    }

    manifest = {
        "topic": topic,
        "archived_at": datetime.now().isoformat(timespec="seconds"),
        "archive_dir": str(dirs["base"]),
        "saved": saved,
        "missing": missing,
    }
    manifest_path = dirs["base"] / "archive_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest["manifest_path"] = str(manifest_path)
    manifest["is_complete"] = not any(missing.values())
    return manifest
