"""Search -> Reader -> Relevance -> Writer -> Review loop -> Visualization -> Archive pipeline."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from agents.ArchiveManager_Agent import run_archive_pipeline
from agents.export_docx_agent import run_docx_export_pipeline
from agents.reader_agent import run_reader
from agents.relevance_agent import run_relevance_limited
from agents.review_agent import run_review_pipeline
from agents.visualization_agent import run_visualization_pipeline
from agents.write_agent import (
    run_writer_draft_generation_bundle,
    run_writer_output_test,
    save_run_writer_outputs,
)
from services.output_service import update_status
from services.search_service import SearchStageError, run_search


DEFAULT_TOPIC = "AI code review"
MAX_REWRITE_ROUNDS = 2
REWRITE_SCORE_THRESHOLD = 3.5
MAX_AWKWARD_EXPRESSIONS = 5
LOOP_LOG_DIR = Path("outputs/logs")
SEOUL_TZ = ZoneInfo("Asia/Seoul")


def print_stage(stage_number: int, stage_name: str) -> None:
    print(f"\n[{stage_number}/7] {stage_name}")


def now_iso() -> str:
    return datetime.now(SEOUL_TZ).isoformat()


def get_positive_int_env(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"[경고] {name} 값이 정수가 아니어서 무시합니다: {raw}")
        return default
    if value <= 0:
        print(f"[경고] {name} 값이 1 이상이 아니어서 무시합니다: {raw}")
        return default
    return value


def write_processing_status(
    run_id: str,
    *,
    current_stage: str,
    message: str,
    search_count: int = 0,
    summary_count: int = 0,
    relevance_count: int = 0,
    started_at: str,
    error_code: str | None = None,
) -> None:
    update_status(
        run_id,
        status="PROCESSING",
        current_stage=current_stage,
        message=message,
        error_code=error_code,
        search_count=search_count,
        summary_count=summary_count,
        relevance_count=relevance_count,
        started_at=started_at,
    )


def write_failed_status(
    run_id: str,
    *,
    current_stage: str,
    message: str,
    error_code: str,
    search_count: int = 0,
    summary_count: int = 0,
    relevance_count: int = 0,
    started_at: str,
) -> None:
    update_status(
        run_id,
        status="FAILED",
        current_stage=current_stage,
        message=message,
        error_code=error_code,
        search_count=search_count,
        summary_count=summary_count,
        relevance_count=relevance_count,
        started_at=started_at,
        finished_at=now_iso(),
        failed_stage=current_stage,
        error_message=message,
    )


def build_search_status_callback(
    run_id: str,
    *,
    started_at: str,
) -> Callable[[str, str | None], None]:
    def callback(message: str, error_code: str | None) -> None:
        update_status(
            run_id,
            status="PROCESSING",
            current_stage="search",
            message=message,
            error_code=error_code,
            started_at=started_at,
        )

    return callback


def build_reader_status_callback(
    run_id: str,
    *,
    started_at: str,
    search_count: int,
) -> Callable[[str, int], None]:
    def callback(message: str, summary_count: int) -> None:
        update_status(
            run_id,
            status="PROCESSING",
            current_stage="reader",
            message=message,
            search_count=search_count,
            summary_count=summary_count,
            started_at=started_at,
        )

    return callback


def should_request_revision(review_payload: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    average_score = float(review_payload.get("average_score", 0.0) or 0.0)
    missing_sections = review_payload.get("missing_sections", []) or []
    incomplete_sentences = review_payload.get("incomplete_sentences", []) or []
    awkward_expressions = review_payload.get("awkward_expressions", []) or []

    if average_score < REWRITE_SCORE_THRESHOLD:
        reasons.append(f"평균 점수가 기준({REWRITE_SCORE_THRESHOLD:.1f}) 미만")
    if missing_sections:
        reasons.append(f"누락 섹션 존재: {', '.join(missing_sections)}")
    if incomplete_sentences:
        reasons.append(f"미완성 문장 {len(incomplete_sentences)}개 존재")
    if len(awkward_expressions) > MAX_AWKWARD_EXPRESSIONS:
        reasons.append(f"어색한 표현이 {MAX_AWKWARD_EXPRESSIONS}개 초과")

    return bool(reasons), reasons


def build_revision_context(review_payload: dict, reasons: list[str], revision_round: int) -> dict:
    return {
        "revision_round": revision_round,
        "reason_summary": "; ".join(reasons),
        "feedback_summary": review_payload.get("feedback_summary", ""),
        "missing_sections": review_payload.get("missing_sections", []) or [],
        "incomplete_sentences": review_payload.get("incomplete_sentences", []) or [],
        "awkward_expressions": review_payload.get("awkward_expressions", []) or [],
    }


def save_review_writer_loop_log(topic: str, loop_entries: list[dict]) -> Path:
    LOOP_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = LOOP_LOG_DIR / f"{topic.lower().replace(' ', '_')}_review_writer_loop_{timestamp}.json"
    payload = {
        "topic": topic,
        "max_rewrite_rounds": MAX_REWRITE_ROUNDS,
        "rewrite_score_threshold": REWRITE_SCORE_THRESHOLD,
        "entries": loop_entries,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_review_writer_loop(topic: str, *, run_id: str | None = None) -> dict:
    loop_entries: list[dict] = []
    writer_bundle = run_writer_draft_generation_bundle(topic=topic, revision_round=0, run_id=run_id)
    if not writer_bundle:
        return {"is_valid": False, "loop_entries": [], "log_path": ""}

    final_writer_bundle = writer_bundle
    final_review_result: dict = {}

    for round_index in range(MAX_REWRITE_ROUNDS + 1):
        draft_text = str(writer_bundle.get("draft", ""))
        saved_path = writer_bundle.get("saved_path")
        run_writer_output_test(draft_text, topic=topic)

        review_result = run_review_pipeline(draft_path=saved_path)
        final_writer_bundle = writer_bundle
        final_review_result = review_result

        if not review_result.get("is_valid"):
            loop_entries.append(
                {
                    "round": round_index,
                    "draft_path": str(saved_path) if saved_path else "",
                    "review_path": review_result.get("review_path", ""),
                    "average_score": 0.0,
                    "rewrite_requested": False,
                    "rewrite_reasons": ["Review 실행 실패"],
                }
            )
            break

        review_payload = review_result.get("review", {}) or {}
        should_rewrite, reasons = should_request_revision(review_payload)
        loop_entries.append(
            {
                "round": round_index,
                "draft_path": str(saved_path) if saved_path else "",
                "review_path": review_result.get("review_path", ""),
                "average_score": review_payload.get("average_score", 0.0),
                "rewrite_requested": should_rewrite and round_index < MAX_REWRITE_ROUNDS,
                "rewrite_reasons": reasons,
                "overall_verdict": review_payload.get("overall_verdict", review_result.get("verdict", "")),
            }
        )

        if not should_rewrite or round_index >= MAX_REWRITE_ROUNDS:
            break

        revision_context = build_revision_context(
            review_payload=review_payload,
            reasons=reasons,
            revision_round=round_index + 1,
        )
        print(f"\nReview-Writer 피드백 루프: {round_index + 1}차 재작성 시작")
        writer_bundle = run_writer_draft_generation_bundle(
            topic=topic,
            revision_context=revision_context,
            revision_round=round_index + 1,
            run_id=run_id,
        )
        if not writer_bundle:
            break

        log_path = save_review_writer_loop_log(topic, loop_entries)
        if run_id:
            run_loop_path = Path("outputs") / "runs" / run_id / "review_writer_loop.json"
            run_loop_path.parent.mkdir(parents=True, exist_ok=True)
            run_loop_path.write_text(
                json.dumps(
                    {
                        "topic": topic,
                        "max_rewrite_rounds": MAX_REWRITE_ROUNDS,
                        "rewrite_score_threshold": REWRITE_SCORE_THRESHOLD,
                        "entries": loop_entries,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        print(f"\nReview-Writer 피드백 루프 로그 저장 완료: {log_path}")
        print("Review-Writer 피드백 루프 완료")
        return {
        "is_valid": bool(final_writer_bundle),
        "final_writer_bundle": final_writer_bundle,
        "final_review_result": final_review_result,
        "loop_entries": loop_entries,
        "log_path": str(log_path),
    }


def main() -> None:
    topic = input(f"검색 주제를 입력하세요 (기본값: {DEFAULT_TOPIC}): ").strip()
    if not topic:
        topic = DEFAULT_TOPIC

    run_id = str(uuid4())
    started_at = now_iso()
    max_search_results = get_positive_int_env("TEAMPROJECT_MAX_SEARCH_RESULTS")
    max_reader_papers = get_positive_int_env("TEAMPROJECT_MAX_READER_PAPERS")
    max_relevance_results = get_positive_int_env("TEAMPROJECT_MAX_RELEVANCE_RESULTS")

    print("\n멀티 에이전트 파이프라인 실행")
    print(f"주제: {topic}")
    print(f"runId: {run_id}")
    print("흐름: Search -> Reader -> Relevance -> Writer -> Review -> Visualization -> Archive")
    if max_search_results is not None:
        print(f"Search 결과 제한: {max_search_results}")
    if max_reader_papers is not None:
        print(f"Reader 처리 논문 제한: {max_reader_papers}")
    if max_relevance_results is not None:
        print(f"Relevance 결과 제한: {max_relevance_results}")
    update_status(
        run_id,
        status="PENDING",
        current_stage="started",
        message="Pipeline accepted and waiting to start.",
        started_at=started_at,
    )

    print_stage(1, "Search Agent")
    write_processing_status(
        run_id,
        current_stage="search",
        message="Search stage is running.",
        started_at=started_at,
    )
    try:
        search_results = run_search(
            topic,
            run_id=run_id,
            max_results=max_search_results or 20,
            status_callback=build_search_status_callback(run_id, started_at=started_at),
        )
    except SearchStageError as error:
        write_failed_status(
            run_id,
            current_stage="search",
            message=error.message,
            error_code=error.error_code,
            started_at=started_at,
        )
        print(f"\n파이프라인 중단: Search 단계 실패 - {error.message}")
        return
    except Exception as error:
        write_failed_status(
            run_id,
            current_stage="search",
            message=str(error),
            error_code="SEARCH_API_ERROR",
            started_at=started_at,
        )
        print(f"\n파이프라인 중단: Search 단계 예외 - {error}")
        return

    print(f"Search 완료: {len(search_results)}편 수집 및 저장")
    if not search_results:
        update_status(
            run_id,
            status="COMPLETED",
            current_stage="search",
            message="Search completed with 0 results.",
            error_code="SEARCH_EMPTY_RESULT",
            search_count=0,
            started_at=started_at,
            finished_at=now_iso(),
            failed_stage=None,
            error_message=None,
        )
        print("\n파이프라인 중단: Search 단계에서 결과가 없어 다음 단계로 진행하지 않습니다.")
        return

    print_stage(2, "Reader Agent")
    write_processing_status(
        run_id,
        current_stage="reader",
        message="Reader stage is running.",
        search_count=len(search_results),
        started_at=started_at,
    )
    try:
        summary_results = run_reader(
            max_papers=max_reader_papers,
            run_id=run_id,
            progress_callback=build_reader_status_callback(
                run_id,
                started_at=started_at,
                search_count=len(search_results),
            ),
        )
    except Exception as error:
        write_failed_status(
            run_id,
            current_stage="reader",
            message=str(error),
            error_code="READER_FAILURE",
            search_count=len(search_results),
            started_at=started_at,
        )
        print(f"\n파이프라인 중단: Reader 단계 예외 - {error}")
        return

    print(f"Reader 완료: {len(summary_results)}편 요약 및 저장")
    if not summary_results:
        write_failed_status(
            run_id,
            current_stage="reader",
            message="Reader produced no summaries.",
            error_code="READER_FAILURE",
            search_count=len(search_results),
            summary_count=0,
            started_at=started_at,
        )
        print("\n파이프라인 중단: Reader 단계에서 요약 결과가 없어 다음 단계로 진행하지 않습니다.")
        return

    print_stage(3, "Relevance Agent")
    write_processing_status(
        run_id,
        current_stage="relevance",
        message="Relevance stage is running.",
        search_count=len(search_results),
        summary_count=len(summary_results),
        started_at=started_at,
    )
    try:
        relevance_results = run_relevance_limited(
            topic,
            run_id=run_id,
            max_results=max_relevance_results,
        )
    except Exception as error:
        write_failed_status(
            run_id,
            current_stage="relevance",
            message=str(error),
            error_code="RELEVANCE_FAILURE",
            search_count=len(search_results),
            summary_count=len(summary_results),
            started_at=started_at,
        )
        print(f"\n파이프라인 중단: Relevance 단계 예외 - {error}")
        return

    print(f"Relevance 완료: {len(relevance_results)}편 점수화 및 저장")
    if not relevance_results:
        write_failed_status(
            run_id,
            current_stage="relevance",
            message="Relevance produced no results.",
            error_code="RELEVANCE_FAILURE",
            search_count=len(search_results),
            summary_count=len(summary_results),
            relevance_count=0,
            started_at=started_at,
        )
        print("\n파이프라인 중단: Relevance 단계에서 선별 결과가 없어 Writer 단계로 진행하지 않습니다.")
        return

    print_stage(4, "Writer Agent")
    write_processing_status(
        run_id,
        current_stage="writer",
        message="Writer stage is running.",
        search_count=len(search_results),
        summary_count=len(summary_results),
        relevance_count=len(relevance_results),
        started_at=started_at,
    )
    try:
        loop_result = run_review_writer_loop(topic, run_id=run_id)
    except Exception as error:
        write_failed_status(
            run_id,
            current_stage="writer",
            message=str(error),
            error_code="WRITER_FAILURE",
            search_count=len(search_results),
            summary_count=len(summary_results),
            relevance_count=len(relevance_results),
            started_at=started_at,
        )
        print(f"\n파이프라인 중단: Writer/Review 단계 예외 - {error}")
        return

    if not loop_result.get("is_valid"):
        write_failed_status(
            run_id,
            current_stage="writer",
            message="Writer-Review loop failed to produce a draft.",
            error_code="WRITER_FAILURE",
            search_count=len(search_results),
            summary_count=len(summary_results),
            relevance_count=len(relevance_results),
            started_at=started_at,
        )
        print("\nWriter-Review 루프에서 초안 확정에 실패했습니다.")
        return
      
    final_writer_bundle = loop_result.get("final_writer_bundle", {}) or {}
    final_review_result = loop_result.get("final_review_result", {}) or {}
    draft_text = str(final_writer_bundle.get("draft", ""))

    review_payload = final_review_result.get("review", {}) or {}
    review_text_parts = []

    if review_payload:
        review_text_parts.append(f"판정: {review_payload.get('overall_verdict', '')}")
        review_text_parts.append(f"평균 점수: {review_payload.get('average_score', '')}")
        review_text_parts.append(f"논리성: {review_payload.get('logic_score', '')}")
        review_text_parts.append(f"중복도: {review_payload.get('duplication_score', '')}")
        review_text_parts.append(f"구조 적절성: {review_payload.get('structure_score', '')}")

        missing_sections = review_payload.get("missing_sections", []) or []
        if missing_sections:
            review_text_parts.append("\n누락 섹션:")
            review_text_parts.extend([f"- {item}" for item in missing_sections])

        awkward_expressions = review_payload.get("awkward_expressions", []) or []
        if awkward_expressions:
            review_text_parts.append("\n어색한 표현:")
            review_text_parts.extend([f"- {item}" for item in awkward_expressions])

        incomplete_sentences = review_payload.get("incomplete_sentences", []) or []
        if incomplete_sentences:
            review_text_parts.append("\n미완성 문장:")
            review_text_parts.extend([f"- {item}" for item in incomplete_sentences])

        feedback_summary = review_payload.get("feedback_summary", "")
        if feedback_summary:
            review_text_parts.append("\n종합 피드백:")
            review_text_parts.append(feedback_summary)

    print("\n====================")
    print("DEBUG REVIEW")
    print(final_review_result)
    print("====================\n")
    
    review_text = "\n".join(review_text_parts)

    save_run_writer_outputs(
        run_id=run_id,
        draft=draft_text,
        report_path=final_writer_bundle.get("saved_path"),
        review_result=review_text,
    )
    
    if not draft_text.strip():
        write_failed_status(
            run_id,
            current_stage="writer",
            message="Writer produced an empty draft.",
            error_code="WRITER_FAILURE",
            search_count=len(search_results),
            summary_count=len(summary_results),
            relevance_count=len(relevance_results),
            started_at=started_at,
        )
        print("Writer 실패: 보고서 초안을 생성하지 못했습니다.")
        return

    print("Writer 완료: 보고서 초안 생성 및 저장")
    run_writer_output_test(draft_text, topic=topic)
    update_status(
        run_id,
        status="COMPLETED",
        current_stage="writer",
        message="Writer completed successfully. Post-processing artifacts are being generated.",
        search_count=len(search_results),
        summary_count=len(summary_results),
        relevance_count=len(relevance_results),
        started_at=started_at,
        finished_at=now_iso(),
    )

    print_stage(5, "Visualization Agent")
    visualization_result: dict = {}
    try:
        visualization_result = run_visualization_pipeline(topic=topic)
        if not visualization_result.get("is_valid"):
            print("\nVisualization 단계에서 일부 결과를 확인할 필요가 있습니다.")
    except Exception as error:
        print(f"\nVisualization 단계 예외: {error}")

    try:
        run_archive_pipeline(...)
    except Exception as error:
        print(f"\nArchive 단계 예외: {error}")

    try:
        run_docx_export_pipeline(...)
    except Exception as error:
        print(f"\nDOCX Export 단계 예외: {error}")

    update_status(
        run_id,
        status="COMPLETED",
        current_stage="completed",
        message="Pipeline completed successfully.",
        search_count=len(search_results),
        summary_count=len(summary_results),
        relevance_count=len(relevance_results),
        started_at=started_at,
        finished_at=now_iso(),
    )

    print_stage(6, "Archive Agent")
    try:
        run_archive_pipeline(
            topic=topic,
            report_files=[
                final_writer_bundle.get("saved_path"),
                visualization_result.get("visualized_report"),
            ],
            visualization_files=list((visualization_result.get("assets", {}) or {}).values()),
            processed_files=[
                final_review_result.get("review_path"),
                visualization_result.get("plan_path"),
                visualization_result.get("asset_map_path"),
                visualization_result.get("manifest_path"),
            ],
            log_files=[loop_result.get("log_path")],
        )
    except Exception as error:
        print(f"\nArchive 단계 예외: {error}")

    print_stage(7, "DOCX Export Agent")
    try:
        run_docx_export_pipeline(
            topic=topic,
            report_path=visualization_result.get("visualized_report") or final_writer_bundle.get("saved_path"),
        )
    except Exception as error:
        print(f"\nDOCX Export 단계 예외: {error}")


if __name__ == "__main__":
    main()
