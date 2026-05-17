"""Search -> Reader -> Relevance -> Writer -> Visualization 연결 실행."""

from __future__ import annotations

from agents.reader_agent import run_reader
from agents.relevance_agent import run_relevance
from agents.visualization_agent import run_visualization_pipeline
from agents.write_agent import run_writer_draft_generation, run_writer_output_test
from services.search_service import run_search


DEFAULT_TOPIC = "AI code review"


def main() -> None:
    topic = input(f"검색 주제를 입력하세요 (기본값: {DEFAULT_TOPIC}): ").strip()
    if not topic:
        topic = DEFAULT_TOPIC

    search_results = run_search(topic)
    if not search_results:
        print("\nSearch 단계에서 검색 결과가 없어 파이프라인을 종료합니다.")
        return

    summary_results = run_reader()
    if not summary_results:
        print("\nReader 단계에서 요약 결과가 없어 파이프라인을 종료합니다.")
        return

    relevance_results = run_relevance(topic)
    if not relevance_results:
        print("\nRelevance 단계에서 통과한 논문이 없어 파이프라인을 종료합니다.")
        return

    writer_output = run_writer_draft_generation(topic=topic)
    if not writer_output:
        print("\nWriter 단계에서 논문 초안 생성에 실패해 파이프라인을 종료합니다.")
        return

    run_writer_output_test(writer_output, topic=topic)

    visualization_result = run_visualization_pipeline(topic=topic)
    if not visualization_result.get("is_valid"):
        print("\nVisualization 단계에서 일부 결과를 확인할 필요가 있습니다.")


if __name__ == "__main__":
    main()
