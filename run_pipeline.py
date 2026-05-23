"""Search -> Reader -> Relevance -> Writer -> Review loop -> Visualization pipeline."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agents.reader_agent import run_reader
from agents.relevance_agent import run_relevance
from agents.review_agent import run_review_pipeline
from agents.visualization_agent import run_visualization_pipeline
from agents.write_agent import run_writer_draft_generation_bundle, run_writer_output_test
from services.search_service import run_search


DEFAULT_TOPIC = "AI code review"
MAX_REWRITE_ROUNDS = 2
REWRITE_SCORE_THRESHOLD = 3.5
MAX_AWKWARD_EXPRESSIONS = 5
LOOP_LOG_DIR = Path("outputs/logs")


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


def run_review_writer_loop(topic: str) -> dict:
    loop_entries: list[dict] = []
    writer_bundle = run_writer_draft_generation_bundle(topic=topic, revision_round=0)
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

        if not should_rewrite:
            break

        if round_index >= MAX_REWRITE_ROUNDS:
            break

        revision_context = build_revision_context(
            review_payload=review_payload,
            reasons=reasons,
            revision_round=round_index + 1,
        )
        print(f"\nReview-Writer 재작성 루프: {round_index + 1}회차 재작성 시작")
        writer_bundle = run_writer_draft_generation_bundle(
            topic=topic,
            revision_context=revision_context,
            revision_round=round_index + 1,
        )
        if not writer_bundle:
            break

    log_path = save_review_writer_loop_log(topic, loop_entries)
    print(f"\nReview-Writer 피드백 루프 로그 저장 완료: {log_path}")
    print("Review-Writer 피드백 루프 완료")
    return {
        "is_valid": True,
        "final_writer_bundle": final_writer_bundle,
        "final_review_result": final_review_result,
        "loop_entries": loop_entries,
        "log_path": str(log_path),
    }


def main() -> None:
    topic = input(f"검색 주제를 입력하세요 (기본값: {DEFAULT_TOPIC}): ").strip()
    if not topic:
        topic = DEFAULT_TOPIC

    print(f"\n입력 주제: {topic}")

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

    loop_result = run_review_writer_loop(topic)
    if not loop_result.get("is_valid"):
        print("\nWriter-Review 루프에서 초안 확정에 실패했습니다.")
        return

    visualization_result = run_visualization_pipeline(topic=topic)
    if not visualization_result.get("is_valid"):
        print("\nVisualization 단계에서 일부 결과를 확인할 필요가 있습니다.")


if __name__ == "__main__":
    main()
