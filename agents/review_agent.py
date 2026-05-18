"""Review Agent - 논문 초안 품질 검토 에이전트"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (agents/ 폴더 기준으로 상위 디렉토리)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.llm_client import LLMClient

# ── 경로 설정 ───────────────────────────────────────────────
INPUT_PATH  = PROJECT_ROOT / "data" / "processed" / "summary_result.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "review_result.json"

# 논문 초안에 반드시 포함되어야 하는 필수 섹션 (purpose/method/result는 필수)
REQUIRED_FIELDS = ["title", "purpose", "method", "result"]

# ── 검토 기준 프롬프트 ──────────────────────────────────────
REVIEW_PROMPT_TEMPLATE = """
당신은 학술 논문 초안을 검토하는 전문 리뷰어입니다.
아래 논문 초안 데이터를 분석하고 품질을 평가해주세요.

[논문 정보]
제목: {title}
목적(purpose): {purpose}
방법(method): {method}
결과(result): {result}
한계(limitation): {limitation}

다음 기준으로 검토하고, 반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):

{{
  "logic_score": <1~5 정수, 논리성: 목적-방법-결과의 흐름이 일관되는가>,
  "duplication_score": <1~5 정수, 중복도: 낮을수록 중복 표현이 적음>,
  "structure_score": <1~5 정수, 구조 적절성: 섹션 구성이 논문답게 적절한가>,
  "awkward_expressions": [<어색하거나 중복된 표현 문장 목록, 없으면 빈 배열>],
  "incomplete_sentences": [<미완성이거나 불명확한 문장 목록, 없으면 빈 배열>],
  "overall_verdict": "<PASS 또는 FAIL>",
  "feedback_summary": "<한국어로 2~3문장 요약 피드백>"
}}
"""

# ── 유틸 함수 ───────────────────────────────────────────────

def load_draft(path: Path) -> list[dict]:
    """논문 초안 JSON 로드"""
    if not path.exists():
        print(f"[오류] 초안 파일을 찾을 수 없습니다: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    print(f"[✓] 초안 로드 완료: {len(data)}개 논문")
    return data


def check_missing_fields(paper: dict) -> list[str]:
    """필수 섹션 누락 여부 확인"""
    missing = []
    for field in REQUIRED_FIELDS:
        value = paper.get(field, "")
        if not value or value.strip() in ("", "초록에 명시되지 않음", "없음"):
            missing.append(field)
    return missing


def parse_llm_response(raw: str) -> dict:
    """LLM 응답에서 JSON 파싱 (방어적 처리)"""
    # ```json ... ``` 블록 제거
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # JSON 파싱 실패 시 기본값 반환
        return {
            "logic_score": 0,
            "duplication_score": 0,
            "structure_score": 0,
            "awkward_expressions": [],
            "incomplete_sentences": [],
            "overall_verdict": "FAIL",
            "feedback_summary": "LLM 응답 파싱 오류 - 수동 검토 필요",
        }


def review_paper(paper: dict, client: LLMClient) -> dict:
    """논문 1편 검토 수행"""
    title       = paper.get("title", "제목 없음")
    purpose     = paper.get("purpose", "")
    method      = paper.get("method", "")
    result      = paper.get("result", "")
    limitation  = paper.get("limitation", "초록에 명시되지 않음")

    # 1) 필수 섹션 누락 확인
    missing_fields = check_missing_fields(paper)

    # 2) LLM 품질 검토
    prompt = REVIEW_PROMPT_TEMPLATE.format(
        title=title,
        purpose=purpose or "(없음)",
        method=method or "(없음)",
        result=result or "(없음)",
        limitation=limitation or "(없음)",
    )
    raw_response = client.ask(prompt, max_tokens=1000)
    review       = parse_llm_response(raw_response)

    # 3) 누락 섹션이 있으면 FAIL 강제
    if missing_fields:
        review["overall_verdict"] = "FAIL"
        review["missing_fields"]  = missing_fields
    else:
        review["missing_fields"] = []

    # 4) 최종 점수 계산 (3개 항목 평균)
    scores = [
        review.get("logic_score", 0),
        review.get("duplication_score", 0),
        review.get("structure_score", 0),
    ]
    valid_scores = [s for s in scores if isinstance(s, (int, float)) and s > 0]
    review["average_score"] = round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else 0.0

    review["title"] = title
    review["reviewed_at"] = datetime.now().isoformat(timespec="seconds")

    return review


def print_feedback(review: dict, index: int) -> None:
    """검토 결과를 터미널에 출력"""
    verdict_icon = "✅" if review["overall_verdict"] == "PASS" else "❌"
    print(f"\n{'='*60}")
    print(f"[{index}] {review['title']}")
    print(f"{'='*60}")
    print(f"  판정: {verdict_icon} {review['overall_verdict']}")
    print(f"  평균 점수: {review['average_score']} / 5.0")
    print(f"  논리성:    {review.get('logic_score', 'N/A')} / 5")
    print(f"  중복도:    {review.get('duplication_score', 'N/A')} / 5")
    print(f"  구조 적절성: {review.get('structure_score', 'N/A')} / 5")

    if review["missing_fields"]:
        print(f"  ⚠️  누락 섹션: {', '.join(review['missing_fields'])}")

    if review.get("awkward_expressions"):
        print(f"  🔸 어색한 표현:")
        for expr in review["awkward_expressions"]:
            print(f"     - {expr}")

    if review.get("incomplete_sentences"):
        print(f"  🔸 미완성 문장:")
        for sent in review["incomplete_sentences"]:
            print(f"     - {sent}")

    print(f"  💬 피드백: {review.get('feedback_summary', '')}")


# ── 메인 ────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  Review Agent 시작 - 논문 초안 품질 검토")
    print("=" * 60)

    # 초안 로드
    papers = load_draft(INPUT_PATH)

    # LLM 클라이언트 초기화
    client = LLMClient()

    # 각 논문 검토
    results = []
    total   = len(papers)
    passed  = 0

    for i, paper in enumerate(papers, start=1):
        title = paper.get("title", f"논문 #{i}")
        print(f"\n[{i}/{total}] 검토 중: {title[:50]}...")
        review = review_paper(paper, client)
        results.append(review)

        if review["overall_verdict"] == "PASS":
            passed += 1

        print_feedback(review, i)

    # 결과 저장
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 최종 요약 출력
    print(f"\n{'='*60}")
    print(f"  검토 완료!")
    print(f"  전체: {total}편  |  통과: {passed}편  |  탈락: {total - passed}편")
    print(f"  결과 저장: {OUTPUT_PATH}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()