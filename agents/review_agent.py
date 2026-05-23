"""Review Agent for evaluating the generated draft quality."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schemas.review_schema import ReviewResult
from services.llm_client import LLMClient

REPORTS_DIR = PROJECT_ROOT / "outputs" / "reports"
OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "review_result.json"

REQUIRED_SECTIONS = ["제목", "초록", "서론", "논의", "결론", "참고문헌"]

REVIEW_PROMPT_TEMPLATE = """
당신은 한국어 학술 논문 초안을 검토하는 리뷰어이다.
아래 초안을 읽고 다음 기준으로 평가하라.

평가 기준:
1. 논리성: 연구 목적, 전개, 결론의 흐름이 자연스러운가
2. 중복도: 같은 의미의 표현이 과도하게 반복되는가
3. 구조 적절성: 논문 초안으로서 섹션 구성이 적절한가
4. 어색한 표현: 문장이 부자연스럽거나 번역투인 부분
5. 미완성 문장: 문장이 중간에 끊기거나 의미가 불분명한 부분

반드시 아래 JSON 형식으로만 답하라.

{{
  "logic_score": 1,
  "duplication_score": 1,
  "structure_score": 1,
  "awkward_expressions": ["예시"],
  "incomplete_sentences": ["예시"],
  "feedback_summary": "2~3문장 요약"
}}

[논문 초안]
{draft_content}
"""


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("cp949", errors="replace").decode("cp949"))


def find_latest_draft(reports_dir: Path) -> Path | None:
    candidates = [
        path
        for path in reports_dir.glob("*.md")
        if not path.name.endswith("_visualized.md")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_draft_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_sections(draft: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    blocks = re.split(r"\n---\n", draft)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        header_line = lines[0].strip()
        match = re.match(r"^#{1,3}\s+(.+)$", header_line)
        if not match:
            continue
        section_name = match.group(1).strip()
        content = "\n".join(lines[1:]).strip()
        sections[section_name] = content
    return sections


def check_missing_sections(sections: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for section_name in REQUIRED_SECTIONS:
        content = sections.get(section_name, "")
        if not content.strip():
            missing.append(section_name)
    return missing


def extract_json_block(text: str) -> str:
    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(text)):
        char = text[index]

        if escape:
            escape = False
            continue

        if char == "\\" and in_string:
            escape = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    return text[start:]


def parse_llm_response(raw: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[-1].strip() == "```":
            cleaned = "\n".join(lines[1:-1])
        else:
            cleaned = "\n".join(lines[1:])

    cleaned = cleaned.replace("```json", "").replace("```JSON", "").replace("```", "").strip()
    cleaned = extract_json_block(cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        normalized = re.sub(r"[\u201c\u201d]", '"', cleaned)
        normalized = re.sub(r"[\u2018\u2019]", "'", normalized)
        normalized = re.sub(r",\s*}", "}", normalized)
        normalized = re.sub(r",\s*]", "]", normalized)
        normalized = extract_json_block(normalized)
        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            return {
                "logic_score": 0,
                "duplication_score": 0,
                "structure_score": 0,
                "awkward_expressions": [],
                "incomplete_sentences": [],
                "feedback_summary": "LLM 응답 파싱 오류 - 수동 검토 필요",
                "raw_response": raw[:1000],
            }


def build_review_result(
    draft_content: str,
    draft_path: Path,
    sections: dict[str, str],
    parsed_review: dict,
    missing_sections: list[str],
) -> ReviewResult:
    logic_score = int(parsed_review.get("logic_score", 0) or 0)
    duplication_score = int(parsed_review.get("duplication_score", 0) or 0)
    structure_score = int(parsed_review.get("structure_score", 0) or 0)

    valid_scores = [score for score in [logic_score, duplication_score, structure_score] if score > 0]
    average_score = round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else 0.0

    overall_verdict = "PASS"
    if missing_sections or average_score < 3.0:
        overall_verdict = "FAIL"

    return ReviewResult(
        title=sections.get("제목", draft_path.stem),
        source_file=draft_path.name,
        reviewed_at=datetime.now().isoformat(timespec="seconds"),
        logic_score=logic_score,
        duplication_score=duplication_score,
        structure_score=structure_score,
        average_score=average_score,
        overall_verdict=overall_verdict,
        awkward_expressions=list(parsed_review.get("awkward_expressions", [])),
        incomplete_sentences=list(parsed_review.get("incomplete_sentences", [])),
        missing_sections=missing_sections,
        detected_sections=list(sections.keys()),
        feedback_summary=str(parsed_review.get("feedback_summary", "")).strip(),
    )


def review_draft(draft_content: str, draft_path: Path, client: LLMClient) -> ReviewResult:
    sections = parse_sections(draft_content)
    missing_sections = check_missing_sections(sections)

    content_for_review = draft_content[:6000] if len(draft_content) > 6000 else draft_content
    prompt = REVIEW_PROMPT_TEMPLATE.format(draft_content=content_for_review)

    raw_response = client.ask(prompt, max_tokens=1200)
    parsed_review = parse_llm_response(raw_response)
    return build_review_result(
        draft_content=draft_content,
        draft_path=draft_path,
        sections=sections,
        parsed_review=parsed_review,
        missing_sections=missing_sections,
    )


def print_feedback(review: ReviewResult) -> None:
    safe_print(f"\n{'=' * 60}")
    safe_print(f"초안 파일: {review.source_file}")
    safe_print(f"제목: {review.title}")
    safe_print(f"{'=' * 60}")
    safe_print(f"판정: {review.overall_verdict}")
    safe_print(f"평균 점수: {review.average_score} / 5.0")
    safe_print(f"논리성: {review.logic_score} / 5")
    safe_print(f"중복도: {review.duplication_score} / 5")
    safe_print(f"구조 적절성: {review.structure_score} / 5")
    safe_print(f"감지된 섹션: {', '.join(review.detected_sections) if review.detected_sections else '없음'}")

    if review.missing_sections:
        safe_print(f"누락 섹션: {', '.join(review.missing_sections)}")

    if review.awkward_expressions:
        safe_print("어색한 표현:")
        for expression in review.awkward_expressions:
            safe_print(f"- {expression}")

    if review.incomplete_sentences:
        safe_print("미완성 문장:")
        for sentence in review.incomplete_sentences:
            safe_print(f"- {sentence}")

    safe_print(f"피드백: {review.feedback_summary}")


def run_review_pipeline() -> dict:
    safe_print("=" * 60)
    safe_print("Review Agent 시작 - 논문 초안 품질 검토")
    safe_print("=" * 60)

    draft_path = find_latest_draft(REPORTS_DIR)
    if draft_path is None:
        safe_print(f"[오류] {REPORTS_DIR} 에 초안 파일(.md)이 없습니다.")
        safe_print("먼저 write_agent를 실행하여 초안을 생성해주세요.")
        return {"is_valid": False, "review_path": "", "verdict": "FAIL"}

    safe_print(f"[확인] 검토 대상 초안: {draft_path.name}")

    draft_content = load_draft_file(draft_path)
    safe_print(f"[확인] 초안 로드 완료 ({len(draft_content)}자)")

    sections = parse_sections(draft_content)
    safe_print(f"[확인] 감지된 섹션: {', '.join(sections.keys()) if sections else '없음'}")

    client = LLMClient()
    safe_print("\n[...] LLM 검토 중...")
    review = review_draft(draft_content, draft_path, client)

    print_feedback(review)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump([asdict(review)], file, ensure_ascii=False, indent=2)

    safe_print(f"\n{'=' * 60}")
    safe_print("검토 완료")
    safe_print(f"판정: {review.overall_verdict}")
    safe_print(f"결과 저장: {OUTPUT_PATH}")
    safe_print(f"{'=' * 60}")


    return {
        "is_valid": True,
        "review_path": str(OUTPUT_PATH),
        "verdict": review.overall_verdict,
        "source_file": review.source_file,
    }


def main() -> None:
    result = run_review_pipeline()
    if not result.get("is_valid"):
        sys.exit(1)


if __name__ == "__main__":
    main()
