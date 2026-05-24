"""Archive Agent for collecting final pipeline artifacts."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.archive_service import archive_pipeline_results

REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"
VISUALIZATION_DIR = PROJECT_ROOT / "outputs" / "visualizations"
REVIEW_RESULT_PATH = PROJECT_ROOT / "data" / "processed" / "review_result.json"
LOOP_LOG_DIR = PROJECT_ROOT / "outputs" / "logs"


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("cp949", errors="replace").decode("cp949"))


def find_latest_file(directory: Path, pattern: str) -> Path | None:
    candidates = list(directory.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def infer_topic_from_report(report_path: Path | None) -> str:
    if report_path is None:
        return "report"
    stem = report_path.stem.replace("_visualized", "")
    parts = stem.split("_")
    if len(parts) >= 3 and parts[-1].isdigit():
        parts = parts[:-2]
    return " ".join(parts) if parts else stem


def run_archive_pipeline(
    topic: str | None = None,
    report_files: list[str | Path] | None = None,
    visualization_files: list[str | Path] | None = None,
    processed_files: list[str | Path] | None = None,
    log_files: list[str | Path] | None = None,
) -> dict:
    safe_print("=" * 60)
    safe_print("Archive Agent 시작 - 최종 결과 저장")
    safe_print("=" * 60)

    latest_report = find_latest_file(REPORTS_DIR, "*.md")
    latest_visualized = find_latest_file(REPORTS_DIR, "*_visualized.md")
    latest_loop_log = find_latest_file(LOOP_LOG_DIR, "*review_writer_loop*.json")

    active_topic = topic or infer_topic_from_report(latest_visualized or latest_report)

    report_items = list(report_files or [])
    if not report_items:
        if latest_report:
            report_items.append(latest_report)
        if latest_visualized:
            report_items.append(latest_visualized)

    visualization_items = list(visualization_files or [])
    processed_items = list(processed_files or [])
    if not processed_items and REVIEW_RESULT_PATH.exists():
        processed_items.append(REVIEW_RESULT_PATH)

    log_items = list(log_files or [])
    if not log_items and latest_loop_log:
        log_items.append(latest_loop_log)

    manifest = archive_pipeline_results(
        topic=active_topic,
        report_files=report_items,
        visualization_files=visualization_items,
        processed_files=processed_items,
        log_files=log_items,
    )

    safe_print(f"저장 경로: {manifest['archive_dir']}")
    safe_print(f"보고서 저장: {manifest['saved']['reports']}")
    safe_print(f"시각 자료 저장: {manifest['saved']['visualizations']}")
    safe_print(f"검토 결과 저장: {manifest['saved']['processed']}")
    safe_print(f"로그 저장: {manifest['saved']['logs']}")

    missing_groups = [f"{key}: {value}" for key, value in manifest["missing"].items() if value]
    if missing_groups:
        safe_print("누락 파일:")
        for group in missing_groups:
            safe_print(f"- {group}")
    else:
        safe_print("누락된 파일이 없습니다.")

    safe_print(f"매니페스트 저장: {manifest['manifest_path']}")
    safe_print("통합 저장 성공")
    safe_print("Archive Agent 완료")
    return manifest


def main() -> None:
    run_archive_pipeline()


if __name__ == "__main__":
    main()
