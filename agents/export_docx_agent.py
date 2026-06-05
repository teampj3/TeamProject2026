"""DOCX export agent for final paper-style documents."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"
DOCX_EXPORT_SCRIPT = PROJECT_ROOT / "services" / "docx_export_service.py"


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("cp949", errors="replace").decode("cp949"))


def slugify_topic(topic: str) -> str:
    compact = "_".join((topic or "").strip().lower().split())
    safe = "".join(char if char.isalnum() or char == "_" else "_" for char in compact)
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "report"


def find_latest_report(directory: Path, pattern: str, topic: str | None = None) -> Path | None:
    candidates = list(directory.glob(pattern))
    if topic:
        prefix = f"{slugify_topic(topic)}_"
        candidates = [path for path in candidates if path.name.startswith(prefix)]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def resolve_report_path(topic: str | None = None, report_path: str | Path | None = None) -> Path | None:
    if report_path:
        candidate = Path(report_path)
        return candidate if candidate.exists() else None

    latest_visualized = find_latest_report(REPORTS_DIR, "*_visualized.md", topic=topic)
    if latest_visualized:
        return latest_visualized

    return find_latest_report(REPORTS_DIR, "*.md", topic=topic)


def find_bundled_python() -> Path | None:
    current_python = Path(sys.executable)
    if current_python.exists():
        return current_python

    home = Path.home()
    candidates = sorted(
        home.glob(".cache/codex-runtimes/*/dependencies/python/python.exe"),
        reverse=True,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run_docx_export_pipeline(topic: str | None = None, report_path: str | Path | None = None) -> dict:
    safe_print("=" * 60)
    safe_print("DOCX Export Agent 시작 - 논문형 문서 내보내기")
    safe_print("=" * 60)

    source_report_path = resolve_report_path(topic=topic, report_path=report_path)
    if source_report_path is None:
        safe_print("DOCX 생성 실패: 내보낼 최종 초안 파일을 찾지 못했습니다.")
        return {"is_valid": False, "report_path": "", "docx_path": ""}

    bundled_python = find_bundled_python()
    if bundled_python is None:
        safe_print("DOCX 생성 실패: 번들 Python 런타임을 찾지 못했습니다.")
        return {"is_valid": False, "report_path": str(source_report_path), "docx_path": ""}

    safe_print(f"내보내기 대상 초안: {source_report_path}")

    command = [str(bundled_python), str(DOCX_EXPORT_SCRIPT), str(source_report_path)]
    if topic:
        command.extend(["--topic", topic])

    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if result.returncode != 0:
        safe_print("DOCX 생성 실패: export script 실행 중 오류가 발생했습니다.")
        if result.stderr.strip():
            safe_print(result.stderr.strip())
        return {"is_valid": False, "report_path": str(source_report_path), "docx_path": ""}

    docx_path = ""
    for line in result.stdout.splitlines():
        if line.startswith("DOCX_PATH="):
            docx_path = line.split("=", 1)[1].strip()
            break

    if not docx_path:
        safe_print("DOCX 생성 실패: 출력 경로를 확인하지 못했습니다.")
        return {"is_valid": False, "report_path": str(source_report_path), "docx_path": ""}

    safe_print(f"DOCX 생성 완료: {docx_path}")
    safe_print("DOCX Export Agent 완료")
    return {
        "is_valid": True,
        "report_path": str(source_report_path),
        "docx_path": docx_path,
    }


def main() -> None:
    run_docx_export_pipeline()


if __name__ == "__main__":
    main()
