"""Writer Agent for building a Korean academic-style report draft."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import time

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.llm_client import LLMClient
from services.output_service import get_run_output_dir, write_json, write_markdown


RELEVANCE_PATH = Path("data/processed/relevance_result.json")
SUMMARY_PATH = Path("data/processed/summary_result.json")
REPORT_OUTPUT_DIR = Path("outputs/reports")

DEFAULT_WRITER_TOPIC = "AI code review"
DEFAULT_WRITER_SCORE_THRESHOLD = 30.0
DEFAULT_WRITER_MAX_TOKENS = 4200

REPORT_SECTION_TEMPLATE = [
    "제목",
    "서론",
    "관련 연구",
    "방법 분석",
    "결과 분석",
    "한계",
    "결론",
    "참고문헌",
]

REPORT_SECTION_ALIASES = {
    "제목": ["제목"],
    "서론": ["서론"],
    "관련 연구": ["관련 연구", "관련연구"],
    "방법 분석": ["방법 분석", "방법분석"],
    "결과 분석": ["결과 분석", "결과분석"],
    "한계": ["한계"],
    "결론": ["결론"],
    "참고문헌": ["참고문헌", "참고 문헌"],
}

SYNTHESIS_MARKERS = [
    "공통적으로",
    "반면",
    "차이점",
    "비교하면",
    "종합하면",
    "연구 흐름",
    "유사하게",
    "상반되게",
    "종합적으로",
    "요약하면",
]

REQUIRED_WRITER_FIELDS = [
    "title",
    "score",
    "reason",
    "purpose",
    "method",
    "result",
    "limitation",
]


def load_json_file(path: Path) -> list[dict]:
    if not path.exists():
        print(f"파일 없음: {path}")
        return []

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        print(f"목록 형식이 아님: {path}")
        return []

    return data


def merge_writer_inputs(relevance_rows: list[dict], summary_rows: list[dict]) -> list[dict]:
    # Relevance 결과와 Reader 요약 결과를 title 기준으로 병합한다.
    summary_by_title = {
        row.get("title", "").strip(): row
        for row in summary_rows
        if row.get("title", "").strip()
    }

    merged: list[dict] = []
    for relevance in relevance_rows:
        title = relevance.get("title", "").strip()
        summary = summary_by_title.get(title, {})
        merged.append(
            {
                "id": relevance.get("id", summary.get("id", "")),
                "title": title,
                "score": relevance.get("score"),
                "reason": relevance.get("reason", ""),
                "purpose": summary.get("purpose", ""),
                "method": summary.get("method", ""),
                "result": summary.get("result", ""),
                "limitation": summary.get("limitation", ""),
                "authors": summary.get("authors", relevance.get("authors", [])),
                "year": summary.get("year", relevance.get("year", "")),
                "url": summary.get("url", relevance.get("url", "")),
                "source": summary.get("source", relevance.get("source", "")),
                "selection_result": relevance.get("selection_result", ""),
            }
        )
    return merged


def find_missing_fields(row: dict, required_fields: list[str]) -> list[str]:
    missing: list[str] = []
    for field in required_fields:
        value = row.get(field)
        if value is None:
            missing.append(field)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field)
    return missing


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("cp949", errors="replace").decode("cp949"))


def print_writer_input_preview(rows: list[dict], preview_count: int = 3) -> None:
    print(f"Writer 입력 데이터 {len(rows)}편 확인")
    for index, row in enumerate(rows[:preview_count], 1):
        print(f"\n[{index}] {row.get('title', '')}")
        print(f"  관련성 점수: {row.get('score')}")
        print(f"  선정 이유: {row.get('reason', '')[:120]}")
        print(f"  목적: {row.get('purpose', '')}")
        print(f"  방법: {row.get('method', '')}")
        print(f"  결과: {row.get('result', '')}")
        print(f"  한계: {row.get('limitation', '')}")


def filter_writer_candidates(
    rows: list[dict],
    score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD,
) -> list[dict]:
    # Writer는 기준 점수 이상 논문만 입력으로 사용한다.
    return [row for row in rows if float(row.get("score", 0) or 0) >= score_threshold]


def print_writer_candidate_list(
    rows: list[dict],
    score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD,
) -> None:
    print(f"\nWriter 입력 대상 논문 목록 (기준 점수: {score_threshold:.1f} 이상)")
    if not rows:
        print("선별된 논문이 없습니다.")
        return

    for index, row in enumerate(rows, 1):
        print(f"[{index}] {row.get('title', '')}")
        print(f"  관련성 점수: {row.get('score')}")
        print(f"  선정 이유: {row.get('reason', '')[:120]}")


def build_report_outline(topic: str = DEFAULT_WRITER_TOPIC) -> dict:
    # 한국어 논문형 보고서의 기본 목차를 고정한다.
    return {
        "topic": topic,
        "sections": REPORT_SECTION_TEMPLATE.copy(),
    }


def print_report_outline(outline: dict) -> None:
    print("\n한국어 논문형 보고서 목차 템플릿")
    print(f"주제: {outline.get('topic', '')}")
    for index, section in enumerate(outline.get("sections", []), 1):
        print(f"{index}. {section}")


def build_writer_prompt(topic: str, selected_rows: list[dict], outline: dict) -> str:
    # 선별 논문 정보와 목차를 결합해 Claude용 Writer 프롬프트를 만든다.
    section_text = "\n".join(f"- {section}" for section in outline.get("sections", []))
    paper_blocks: list[str] = []

    for index, row in enumerate(selected_rows, 1):
        paper_blocks.append(
            "\n".join(
                [
                    f"[논문 {index}]",
                    f"제목: {row.get('title', '')}",
                    f"관련성 점수: {row.get('score')}",
                    f"선정 이유: {row.get('reason', '')}",
                    f"목적: {row.get('purpose', '')}",
                    f"방법: {row.get('method', '')}",
                    f"결과: {row.get('result', '')}",
                    f"한계: {row.get('limitation', '')}",
                    f"저자: {', '.join(row.get('authors', []))}",
                    f"연도: {row.get('year', '')}",
                    f"링크: {row.get('url', '')}",
                    f"출처: {row.get('source', '')}",
                ]
            )
        )

    paper_text = "\n\n".join(paper_blocks)
    return f"""당신은 한국어 학술 보고서 작성 보조 AI입니다.

주제: {topic}

아래 선별 논문 정보를 바탕으로 한국어 논문형 보고서 초안을 작성하시오.

[보고서 목차]
{section_text}

[출력 형식]
- 한국어 학술 보고서 문체를 사용할 것
- 위 목차 순서를 그대로 유지할 것
- 각 섹션 제목을 명확히 표시할 것
- 마지막에는 참고문헌 목록을 포함할 것

[금지사항]
- 입력 논문 정보에 없는 내용을 임의로 지어내지 말 것
- 논문 내용을 단순 나열만 하지 말 것
- 구어체, 감탄문, 불필요한 홍보성 표현을 쓰지 말 것

[작성 지침]
- 여러 논문의 공통점, 차이점, 연구 흐름을 종합적으로 서술할 것
- 선정 이유와 관련성 점수는 참고하되 본문에서 점수를 그대로 나열하지 말 것
- 방법 분석과 결과 분석 섹션에서는 논문 간 비교 내용을 포함할 것
- 한계 섹션에서는 각 논문의 제약과 향후 가능성을 정리할 것
- 각 주요 섹션에서 최소 두 번 이상 비교 또는 종합 문장을 사용할 것
- "공통적으로", "반면", "차이점", "종합하면" 같은 연결 표현을 적절히 사용할 것
- 관련 연구 섹션에서는 반드시 공통점과 차이점을 함께 서술할 것
- 방법 분석 섹션에서는 논문 간 방법론 차이를 직접 비교하는 문장을 포함할 것
- 결과 분석 섹션에서는 성과, 기여, 평가 방식의 공통점과 차이점을 함께 정리할 것
- 결론 섹션에서는 전체 연구 흐름을 요약하는 종합 문장을 포함할 것

[선별 논문 데이터]
{paper_text}
"""


def print_writer_prompt_preview(prompt: str, max_length: int = 3000) -> None:
    print("\nWriter 프롬프트 미리보기")
    safe_print(prompt[:max_length])
    if len(prompt) > max_length:
        print("\n... (이하 생략)")


def generate_report_draft(
    prompt: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = DEFAULT_WRITER_MAX_TOKENS,
) -> str:
    # 준비한 프롬프트를 Claude에 전달해 보고서 초안을 생성한다.
    client = LLMClient()
    return client.ask(prompt, model=model, max_tokens=max_tokens)


def print_report_draft_preview(draft: str) -> None:
    print("\n생성된 보고서 초안")
    safe_print(draft)


def check_synthesis_markers(draft: str) -> dict:
    # 비교·종합 표현이 충분히 들어갔는지 1차 확인한다.
    found_markers = [marker for marker in SYNTHESIS_MARKERS if marker in draft]
    required_sections = ["관련 연구", "방법 분석", "결과 분석", "결론"]
    section_hits = {section: (section in draft) for section in required_sections}
    return {
        "found_markers": found_markers,
        "section_hits": section_hits,
        "is_synthesis_visible": len(found_markers) >= 3,
    }


def print_synthesis_check(result: dict) -> None:
    print("\n종합 분석 반영 확인")
    print(f"비교·종합 표현 발견: {result.get('found_markers', [])}")
    print(f"주요 섹션 포함 여부: {result.get('section_hits', {})}")
    if result.get("is_synthesis_visible"):
        print("종합 분석 표현이 초안에 반영된 것으로 확인됨")
    else:
        print("종합 분석 표현이 충분하지 않을 수 있음")


def slugify_topic(topic: str) -> str:
    normalized = topic.strip().lower()
    normalized = re.sub(r"[^a-z0-9가-힣]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "report"


def save_report_draft(draft: str, topic: str) -> Path:
    # 생성된 초안을 markdown 파일로 저장한다.
    REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{slugify_topic(topic)}_{timestamp}.md"
    save_path = REPORT_OUTPUT_DIR / filename
    save_path.write_text(draft, encoding="utf-8")
    return save_path


def save_run_writer_outputs(
    *,
    run_id: str,
    draft: str,
    report_path: Path,
) -> None:
    run_dir = get_run_output_dir(run_id)
    writer_payload = {
        "gptDraft": "",
        "claudeDraft": draft,
        "commonHighlights": [],
        "differentHighlights": [],
        "reviewResult": "",
        "mergedReport": draft,
    }
    write_json(run_dir / "writer_output.json", writer_payload)
    write_markdown(run_dir / "report.md", draft)


def find_latest_report_file(topic: str) -> Path | None:
    topic_slug = slugify_topic(topic)
    candidates = sorted(REPORT_OUTPUT_DIR.glob(f"{topic_slug}_*.md"))
    if not candidates:
        return None
    return candidates[-1]


def check_report_sections(draft: str) -> dict:
    # 42번 테스트에서는 필수 섹션 포함 여부만 확인한다.
    section_hits: dict[str, bool] = {}
    for section, aliases in REPORT_SECTION_ALIASES.items():
        section_hits[section] = any(alias in draft for alias in aliases)
    return section_hits


def validate_writer_output(draft: str, saved_path: Path, synthesis_check: dict) -> dict:
    # 기능 테스트 관점에서 생성 여부, 섹션, 저장 성공 여부를 확인한다.
    section_hits = check_report_sections(draft)
    has_draft = bool(draft.strip())
    file_saved = saved_path.exists()
    sections_ok = all(section_hits.values())
    synthesis_ok = synthesis_check.get("is_synthesis_visible", False)
    is_valid = has_draft and file_saved and sections_ok and synthesis_ok
    return {
        "has_draft": has_draft,
        "file_saved": file_saved,
        "section_hits": section_hits,
        "sections_ok": sections_ok,
        "synthesis_ok": synthesis_ok,
        "is_valid": is_valid,
    }


def print_writer_validation_result(result: dict, saved_path: Path) -> None:
    print("\n42번 테스트/검증 결과")
    print(f"초안 생성 여부: {'정상' if result.get('has_draft') else '실패'}")
    print(f"저장 파일 여부: {'정상' if result.get('file_saved') else '실패'}")
    print(f"섹션 포함 여부: {result.get('section_hits', {})}")
    print(f"비교·종합 표현 반영 여부: {'정상' if result.get('synthesis_ok') else '보완 필요'}")
    print(f"저장 경로: {saved_path}")
    if result.get("is_valid"):
        print("Writer Agent 테스트 완료")
    else:
        print("Writer Agent 테스트 미통과: 일부 항목 보완 필요")


def run_writer_output_test(draft: str, topic: str = DEFAULT_WRITER_TOPIC) -> dict:
    # Review Agent가 아니라 기능 테스트 관점에서 Writer 결과를 검증한다.
    saved_path = find_latest_report_file(topic)
    if saved_path is None:
        result = {
            "has_draft": bool(draft.strip()),
            "file_saved": False,
            "section_hits": check_report_sections(draft),
            "sections_ok": False,
            "synthesis_ok": check_synthesis_markers(draft).get("is_synthesis_visible", False),
            "is_valid": False,
        }
        print_writer_validation_result(result, Path("없음"))
        return result

    synthesis_check = check_synthesis_markers(draft)
    result = validate_writer_output(draft, saved_path, synthesis_check)
    print_writer_validation_result(result, saved_path)
    return result


def validate_writer_input(rows: list[dict]) -> bool:
    is_valid = True
    for index, row in enumerate(rows, 1):
        missing = find_missing_fields(row, REQUIRED_WRITER_FIELDS)
        if missing:
            is_valid = False
            print(f"[경고] {index}번 논문 입력 누락 필드: {missing}")
    return is_valid


def load_writer_input_data() -> list[dict]:
    relevance_rows = load_json_file(RELEVANCE_PATH)
    summary_rows = load_json_file(SUMMARY_PATH)
    if not relevance_rows or not summary_rows:
        return []
    return merge_writer_inputs(relevance_rows, summary_rows)


def run_writer_input_check() -> list[dict]:
    rows = load_writer_input_data()
    if not rows:
        print("Writer 입력 데이터를 불러오지 못했습니다.")
        return []

    print_writer_input_preview(rows)
    if validate_writer_input(rows):
        print("\nWriter Agent 입력 필드 확인 완료")
    else:
        print("\nWriter Agent 입력 필드 일부 누락")
    return rows


def run_writer_input_build(
    score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD,
) -> list[dict]:
    rows = load_writer_input_data()
    if not rows:
        print("Writer 입력 데이터를 불러오지 못했습니다.")
        return []

    selected_rows = filter_writer_candidates(rows, score_threshold=score_threshold)
    print_writer_candidate_list(selected_rows, score_threshold=score_threshold)
    print(f"\nWriter 입력 구성 완료: {len(selected_rows)}편 선별")
    return selected_rows


def run_report_outline_demo(topic: str = DEFAULT_WRITER_TOPIC) -> dict:
    outline = build_report_outline(topic=topic)
    print_report_outline(outline)
    print("\n목차 템플릿 적용 완료")
    return outline


def run_writer_preparation_flow(
    topic: str = DEFAULT_WRITER_TOPIC,
    score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD,
) -> dict:
    print("Writer 준비 흐름 시작")

    all_rows = run_writer_input_check()
    if not all_rows:
        return {}

    selected_rows = filter_writer_candidates(all_rows, score_threshold=score_threshold)
    print_writer_candidate_list(selected_rows, score_threshold=score_threshold)
    print(f"\nWriter 입력 구성 완료: {len(selected_rows)}편 선별")

    outline = build_report_outline(topic=topic)
    print_report_outline(outline)
    print("\n목차 템플릿 적용 완료")

    prompt = build_writer_prompt(topic=topic, selected_rows=selected_rows, outline=outline)
    print_writer_prompt_preview(prompt)
    print("\n프롬프트 생성 완료")

    return {
        "topic": topic,
        "selected_rows": selected_rows,
        "outline": outline,
        "prompt": prompt,
    }


def run_writer_draft_generation(
    topic: str = DEFAULT_WRITER_TOPIC,
    score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD,
    run_id: str | None = None,
) -> str:
    preparation = run_writer_preparation_flow(
        topic=topic,
        score_threshold=score_threshold,
    )
    if not preparation:
        print("Writer 초안 생성 준비에 실패했습니다.")
        return ""

    print("\nClaude API로 보고서 초안 생성 중...")
    draft = generate_report_draft(preparation["prompt"])
    print_report_draft_preview(draft)
    synthesis_check = check_synthesis_markers(draft)
    print_synthesis_check(synthesis_check)
    saved_path = save_report_draft(draft, topic=topic)
    if run_id:
        save_run_writer_outputs(run_id=run_id, draft=draft, report_path=saved_path)
    print(f"\n초안 저장 완료: {saved_path}")
    print("\n보고서 초안 생성 완료")
    return draft


if __name__ == "__main__":
    run_writer_draft_generation()
