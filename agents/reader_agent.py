"""Reader Agent that summarizes papers from raw search results."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from collections.abc import Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.llm_client import LLMClient
from services.output_service import get_run_output_dir, write_json

llm = LLMClient()

# 초록 최소 길이 기준
MIN_ABSTRACT_LENGTH = 50


def log_reader(message: str) -> None:
    print(f"[Reader] {message}")


def load_search_results(path: str = "data/raw/search_result.json") -> list[dict]:
    if not os.path.exists(path):
        log_reader(f"파일 없음: {path}")
        return []
    with open(path, "r", encoding="utf-8") as file:
        papers = json.load(file)
    log_reader(f"논문 {len(papers)}편 불러옴")
    return papers


def validate_abstract(title: str, abstract: str) -> str | None:
    """초록이 없거나 너무 짧으면 None 반환."""
    if not abstract or not abstract.strip():
        log_reader(f"건너뜀 - 초록 없음: {title[:50]}")
        return None
    if len(abstract.strip()) < MIN_ABSTRACT_LENGTH:
        log_reader(f"건너뜀 - 초록 너무 짧음 ({len(abstract.strip())}자): {title[:50]}")
        return None
    return abstract.strip()


def build_prompt(title: str, abstract: str) -> str:
    return f"""다음 논문의 초록을 읽고 아래 4가지 항목을 JSON 형식으로만 출력하세요.

[중요 규칙]
- 반드시 초록에 명시된 내용만 사용하세요. 초록에 없는 내용은 절대 추론하거나 추가하지 마세요.
- 초록에서 해당 항목을 찾을 수 없으면 "초록에 명시되지 않음"이라고 적으세요.
- 각 항목은 1~3문장으로 작성하세요.
- 문체는 간결하고 객관적인 서술체로 통일하세요.
- 마크다운, 코드블록, 추가 설명 없이 JSON만 출력하세요.

논문 제목: {title}
초록: {abstract}

출력 형식:
{{
  "purpose": "이 논문이 해결하려는 문제 또는 목적 (1~3문장)",
  "method": "사용한 방법 또는 접근법 (1~3문장)",
  "result": "주요 결과 또는 성과 (1~3문장)",
  "limitation": "한계점 또는 향후 과제 (1~3문장)"
}}"""


def parse_response(response_text: str, title: str) -> dict:
    """Claude 응답에서 JSON을 안정적으로 추출한다."""
    clean = response_text.strip()

    if "```json" in clean:
        clean = clean.split("```json")[1].split("```")[0].strip()
    elif "```" in clean:
        clean = clean.split("```")[1].split("```")[0].strip()

    if not clean.startswith("{"):
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start != -1 and end > start:
            clean = clean[start:end]

    try:
        summary = json.loads(clean)
    except json.JSONDecodeError:
        log_reader(f"JSON 파싱 실패, 기본값으로 대체: {title[:50]}")
        summary = {
            "purpose": "초록에 명시되지 않음",
            "method": "초록에 명시되지 않음",
            "result": "초록에 명시되지 않음",
            "limitation": "초록에 명시되지 않음",
        }

    for field in ["purpose", "method", "result", "limitation"]:
        if not summary.get(field) or not str(summary[field]).strip():
            summary[field] = "초록에 명시되지 않음"

    return summary


def summarize_paper(
    title: str,
    abstract: str,
    *,
    progress_callback: Callable[[str], None] | None = None,
) -> dict | None:
    abstract = validate_abstract(title, abstract)
    if abstract is None:
        return None

    prompt = build_prompt(title, abstract)
    if progress_callback:
        progress_callback(f"Claude 호출 직전: {title[:80]}")
    log_reader(f"Claude 호출 시작: {title[:80]}")

    try:
        response_text = llm.ask(prompt, max_tokens=1024)
    except Exception as error:
        log_reader(f"Claude 호출 실패: {title[:80]} / {error!r}")
        return None

    log_reader(f"Claude 응답 수신 완료: {title[:80]} / {len(response_text)} chars")
    if progress_callback:
        progress_callback(f"Claude 응답 수신 직후: {title[:80]}")
    log_reader(f"응답 파싱 시작: {title[:80]}")
    return parse_response(response_text, title)


def save_summary_results(
    results: list[dict],
    path: str = "data/processed/summary_result.json"
) -> None:
    log_reader(f"summary_result 저장 시작: {path}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)
    log_reader(f"summary_result 저장 완료: {path}")

    required_fields = {"title", "authors", "year", "url", "source",
                       "purpose", "method", "result", "limitation"}
    for i, paper in enumerate(results, 1):
        missing = required_fields - set(paper.keys())
        if missing:
            log_reader(f"{i}번 논문 누락 필드: {missing}")
    log_reader(f"저장 검증 완료: {len(results)}편")


def save_run_reader_results(results: list[dict], run_id: str) -> None:
    run_dir = get_run_output_dir(run_id)
    payload = [
        {
            "id": result.get("id", ""),
            "summary": " ".join(
                filter(
                    None,
                    [
                        result.get("purpose", "").strip(),
                        result.get("method", "").strip(),
                        result.get("result", "").strip(),
                        result.get("limitation", "").strip(),
                    ],
                )
            ),
        }
        for result in results
    ]
    log_reader(f"reader_results.json 저장 시작: {run_dir / 'reader_results.json'}")
    write_json(run_dir / "reader_results.json", payload)
    log_reader(f"reader_results.json 저장 완료: {run_dir / 'reader_results.json'}")


def run_reader(
    max_papers: int | None = None,
    run_id: str | None = None,
    progress_callback: Callable[[str, int], None] | None = None,
) -> list[dict]:
    papers = load_search_results()
    if not papers:
        return []

    if progress_callback:
        progress_callback("Reader stage started.", 0)
    log_reader("Reader stage started")

    if max_papers is not None:
        papers = papers[:max_papers]
        log_reader(f"상위 {len(papers)}편 요약 시작")
    else:
        log_reader(f"전체 {len(papers)}편 요약 시작")

    summarized: list[dict] = []
    skipped = 0

    for index, paper in enumerate(papers, 1):
        title = paper.get("title", "")
        abstract = paper.get("abstract", "")
        log_reader(f"[{index}/{len(papers)}] 처리 시작: {title[:80]}")
        if progress_callback:
            progress_callback(f"Processing paper {index}/{len(papers)}: {title[:80]}", len(summarized))

        summary = summarize_paper(
            title,
            abstract,
            progress_callback=(
                (lambda message, idx=index: progress_callback(f"{message} ({idx}/{len(papers)})", len(summarized)))
                if progress_callback
                else None
            ),
        )
        if summary is None:
            skipped += 1
            log_reader(f"[{index}/{len(papers)}] 건너뜀 완료: {title[:80]}")
            continue

        log_reader(f"응답 파싱 완료: {title[:80]}")
        if progress_callback:
            progress_callback(f"Response parsed: {title[:80]}", len(summarized))

        result = {
            "id": paper.get("id", ""),
            "title": title,
            "abstract": abstract,
            "authors": paper.get("authors", []),
            "year": paper.get("year", ""),
            "url": paper.get("url", ""),
            "source": paper.get("source", ""),
            "categories": paper.get("categories", []),
            "purpose":    summary.get("purpose", ""),
            "method":     summary.get("method", ""),
            "result":     summary.get("result", ""),
            "limitation": summary.get("limitation", ""),
        }
        summarized.append(result)

        log_reader(f"[{index}/{len(papers)}] 요약 완료: {title[:80]}")
        log_reader(f"  목적: {result['purpose'][:80]}")
        log_reader(f"  방법: {result['method'][:80]}")
        log_reader(f"  결과: {result['result'][:80]}")
        log_reader(f"  한계: {result['limitation'][:80]}")
        if progress_callback:
            progress_callback(f"Paper summarized: {title[:80]}", len(summarized))

    log_reader(f"요약 완료: {len(summarized)}편 성공 / {skipped}편 건너뜀")
    if progress_callback:
        progress_callback("reader_results.json 저장 직전", len(summarized))
    save_summary_results(summarized)
    if run_id:
        save_run_reader_results(summarized, run_id)
    if progress_callback:
        progress_callback("reader_results.json 저장 직후", len(summarized))
    return summarized


if __name__ == "__main__":
    run_reader()
