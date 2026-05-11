"""Helpers for run-scoped output persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RUNS_ROOT = Path("outputs/runs")


def get_run_output_dir(run_id: str) -> Path:
    run_dir = RUNS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def update_status(
    run_id: str,
    *,
    status: str,
    current_stage: str,
    message: str,
    error_code: str | None = None,
    search_count: int = 0,
    summary_count: int = 0,
    relevance_count: int = 0,
    started_at: str | None = None,
    finished_at: str | None = None,
    failed_stage: str | None = None,
    error_message: str | None = None,
) -> Path:
    status_payload = {
        "status": status,
        "current_stage": current_stage,
        "message": message,
        "error_code": error_code,
        "search_count": search_count,
        "summary_count": summary_count,
        "relevance_count": relevance_count,
        "started_at": started_at,
        "finished_at": finished_at,
        "failed_stage": failed_stage,
        "error_message": error_message,
    }
    path = get_run_output_dir(run_id) / "status.json"
    write_json(path, status_payload)
    return path
