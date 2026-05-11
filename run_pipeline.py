"""Run the Search -> Reader -> Relevance -> Writer pipeline."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4

from agents.reader_agent import run_reader
from agents.relevance_agent import run_relevance
from agents.write_agent import run_writer_draft_generation, run_writer_output_test
from services.output_service import update_status
from services.search_service import SearchStageError, run_search


DEFAULT_TOPIC = "AI code review"
SEOUL_TZ = ZoneInfo("Asia/Seoul")


def print_stage(stage_number: int, stage_name: str) -> None:
    print(f"\n[{stage_number}/4] {stage_name}")


def now_iso() -> str:
    return datetime.now(SEOUL_TZ).isoformat()


def write_processing_status(
    run_id: str,
    *,
    current_stage: str,
    message: str,
    search_count: int = 0,
    summary_count: int = 0,
    relevance_count: int = 0,
    started_at: str,
) -> None:
    update_status(
        run_id,
        status="PROCESSING",
        current_stage=current_stage,
        message=message,
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


def main() -> None:
    topic = input("연구 주제를 입력하세요 (예: AI code review): ").strip()
    if not topic:
        topic = DEFAULT_TOPIC
    run_id = str(uuid4())
    started_at = now_iso()

    print("\n멀티 에이전트 파이프라인 실행")
    print(f"주제: {topic}")
    print(f"runId: {run_id}")
    print("흐름: Search -> Reader -> Relevance -> Writer")
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
        search_results = run_search(topic, run_id=run_id)
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
        summary_results = run_reader(run_id=run_id)
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
        relevance_results = run_relevance(topic, run_id=run_id)
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
        writer_output = run_writer_draft_generation(topic=topic, run_id=run_id)
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
        print(f"\n파이프라인 중단: Writer 단계 예외 - {error}")
        return
    if writer_output:
        print("Writer 완료: 보고서 초안 생성 및 저장")
        run_writer_output_test(writer_output, topic=topic)
        update_status(
            run_id,
            status="COMPLETED",
            current_stage="writer",
            message="Pipeline completed successfully.",
            search_count=len(search_results),
            summary_count=len(summary_results),
            relevance_count=len(relevance_results),
            started_at=started_at,
            finished_at=now_iso(),
        )
    else:
        print("Writer 실패: 보고서 초안을 생성하지 못했습니다.")
        write_failed_status(
            run_id,
            current_stage="writer",
            message="Writer failed to generate a draft.",
            error_code="WRITER_FAILURE",
            search_count=len(search_results),
            summary_count=len(summary_results),
            relevance_count=len(relevance_results),
            started_at=started_at,
        )

    print("\n전체 파이프라인 실행 완료")


if __name__ == "__main__":
    main()
