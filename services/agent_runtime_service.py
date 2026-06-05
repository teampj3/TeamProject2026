"""Shared runtime context and tracing helpers for the pipeline."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.export_docx_agent import resolve_report_path, run_docx_export_pipeline
from services.archive_service import archive_pipeline_results, slugify_topic


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_CONTEXT_PATH = PROJECT_ROOT / "data" / "processed" / "agent_runtime_context.json"
TRACE_LOG_DIR = PROJECT_ROOT / "outputs" / "logs"
REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"
DEFAULT_REVIEW_RESULT_PATH = PROJECT_ROOT / "data" / "processed" / "review_result.json"


@dataclass
# 파이프라인 전체가 공유하는 공통 상태 객체.
# 각 Agent는 이 context를 읽고 필요한 경로와 상태를 갱신한다.
class PipelineContext:
    """파이프라인 전체 단계가 공유하는 공통 상태 객체다."""

    topic: str
    input_topic: str = ""
    search_result_path: str = ""
    summary_result_path: str = ""
    relevance_result_path: str = ""
    draft_path: str = ""
    review_result_path: str = ""
    visual_plan_path: str = ""
    visualized_report_path: str = ""
    archive_path: str = ""
    archive_manifest_path: str = ""
    docx_path: str = ""
    loop_log_path: str = ""
    trace_path: str = ""
    status: str = "initialized"
    started_at: str = ""
    updated_at: str = ""
    step_count: int = 8
    traces: list[dict[str, Any]] = field(default_factory=list)
    runtime_data: dict[str, Any] = field(default_factory=dict, repr=False)


# 새 파이프라인 실행에 사용할 context를 초기화한다.
# 파이프라인 실행 시작 시 공통 context를 초기화한다.
def create_pipeline_context(topic: str, step_count: int = 8, input_topic: str = "") -> PipelineContext:
    now = datetime.now().isoformat(timespec="seconds")
    return PipelineContext(
        topic=topic,
        input_topic=input_topic or topic,
        started_at=now,
        updated_at=now,
        step_count=step_count,
    )


# runtime_data를 제외한 직렬화 가능한 context 사본을 만든다.
# 내부 캐시(runtime_data)를 제외하고 저장 가능한 context 딕셔너리만 만든다.
def context_to_dict(context: PipelineContext) -> dict[str, Any]:
    payload = asdict(context)
    payload.pop("runtime_data", None)
    return payload


# 현재 context를 파일로 저장해 외부 단계에서도 상태를 읽을 수 있게 한다.
# 현재 context를 파일로 저장해 다음 step과 로그가 같은 상태를 참조하게 한다.
def save_pipeline_context(context: PipelineContext, path: Path = RUNTIME_CONTEXT_PATH) -> Path:
    context.updated_at = datetime.now().isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context_to_dict(context), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# step 실행 결과를 trace로 남겨 long-running workflow 추적에 활용한다.
# step 하나가 끝날 때마다 실행 상태를 trace로 남긴다.
# 발표 시 "어느 단계가 언제 끝났고 무엇을 만들었는지" 보여주는 핵심 기록이다.
def record_step_trace(
    context: PipelineContext,
    step_name: str,
    started_at: str,
    ended_at: str,
    status: str,
    input_paths: list[str] | None = None,
    output_paths: list[str] | None = None,
    verdict: str = "",
    average_score: float | None = None,
    rewrite_requested: bool | None = None,
    note: str = "",
) -> dict[str, Any]:
    trace = {
        "step_name": step_name,
        "started_at": started_at,
        "ended_at": ended_at,
        "status": status,
        "input_paths": input_paths or [],
        "output_paths": output_paths or [],
        "verdict": verdict,
        "average_score": average_score,
        "rewrite_requested": rewrite_requested,
        "note": note,
    }
    context.traces.append(trace)
    context.updated_at = ended_at
    return trace


# step trace를 별도 JSON 파일로 저장해 실행 이력을 남긴다.
# 누적된 trace를 별도 JSON 파일로 저장한다.
def save_runtime_trace(context: PipelineContext) -> Path:
    TRACE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    if context.trace_path:
        trace_path = Path(context.trace_path)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        trace_path = TRACE_LOG_DIR / f"{slugify_topic(context.topic)}_agent_runtime_trace_{timestamp}.json"
    payload = {
        "topic": context.topic,
        "input_topic": context.input_topic,
        "started_at": context.started_at,
        "updated_at": context.updated_at,
        "status": context.status,
        "steps": context.traces,
    }
    trace_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    context.trace_path = str(trace_path)
    return trace_path


# 최신 Writer 초안을 읽는 도구처럼 쓰기 위한 래퍼 함수다.
# 최신 보고서를 가져오는 wrapper.
def load_latest_report(topic: str | None = None) -> Path | None:
    return resolve_report_path(topic=topic)


# 최신 review 결과나 지정된 review 결과 파일을 읽어오는 도구 래퍼다.
# review 결과 파일을 읽는 wrapper.
def read_review_result(review_path: str | Path | None = None) -> dict[str, Any]:
    target = Path(review_path) if review_path else DEFAULT_REVIEW_RESULT_PATH
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


# Archive 단계를 tool처럼 호출하기 위한 래퍼 함수다.
# 아카이브 단계를 함수 호출처럼 감싸는 wrapper.
def archive_results(
    context: PipelineContext,
    report_files: list[str | Path],
    visualization_files: list[str | Path],
    processed_files: list[str | Path],
    log_files: list[str | Path],
) -> dict[str, Any]:
    manifest = archive_pipeline_results(
        topic=context.topic,
        report_files=report_files,
        visualization_files=visualization_files,
        processed_files=processed_files,
        log_files=log_files,
    )
    context.archive_path = str(manifest.get("archive_dir", ""))
    context.archive_manifest_path = str(manifest.get("manifest_path", ""))
    return manifest


# DOCX 내보내기를 tool처럼 호출하기 위한 래퍼 함수다.
# DOCX 내보내기를 함수 호출처럼 감싸는 wrapper.
def export_docx(context: PipelineContext, report_path: str | Path | None = None) -> dict[str, Any]:
    result = run_docx_export_pipeline(topic=context.topic, report_path=report_path)
    context.docx_path = str(result.get("docx_path", ""))
    return result
