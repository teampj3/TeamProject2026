"""Reader Agent that summarizes papers from raw search results."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.llm_client import LLMClient
from services.output_service import get_run_output_dir, write_json

llm = LLMClient()


def load_search_results(path: str = "data/raw/search_result.json") -> list[dict]:
    if not os.path.exists(path):
        print(f"파일 없음: {path}")
        return []

    with open(path, "r", encoding="utf-8") as file:
        papers = json.load(file)

    print(f"논문 {len(papers)}편 불러옴")
    return papers


def build_prompt(title: str, abstract: str) -> str:
    return f"""다음 논문의 초록을 읽고 아래 4가지 항목만 JSON 형식으로 출력하세요.
다른 설명이나 마크다운 없이 JSON만 출력하세요.

논문 제목: {title}
초록: {abstract}

출력 형식:
{{
  "purpose": "이 논문의 목적",
  "method": "사용한 방법 또는 접근법",
  "result": "주요 결과 또는 성과",
  "limitation": "한계점 또는 후속 과제"
}}"""


def summarize_paper(title: str, abstract: str) -> dict | None:
    if not abstract.strip():
        print(f"  초록 없음, 건너뜀: {title[:50]}")
        return None

    prompt = build_prompt(title, abstract)

    try:
        response_text = llm.ask(prompt, max_tokens=1024)
    except Exception as error:
        print(f"  Claude 호출 실패: {error}")
        return None

    try:
        clean = response_text.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        summary = json.loads(clean)
    except json.JSONDecodeError:
        print(f"  JSON 파싱 실패, 원문 저장: {title[:50]}")
        summary = {
            "purpose": "",
            "method": "",
            "result": "",
            "limitation": response_text,
        }

    return summary


def save_summary_results(results: list[dict], path: str = "data/processed/summary_result.json") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)
    print(f"\n저장 완료: {path}")


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
    write_json(run_dir / "reader_results.json", payload)


def run_reader(max_papers: int | None = None, run_id: str | None = None) -> list[dict]:
    papers = load_search_results()
    if not papers:
        return []

    if max_papers is not None:
        papers = papers[:max_papers]
        print(f"\n상위 {len(papers)}편 요약 시작...\n")
    else:
        print(f"\n전체 {len(papers)}편 요약 시작...\n")

    summarized: list[dict] = []
    for index, paper in enumerate(papers, 1):
        title = paper.get("title", "")
        abstract = paper.get("abstract", "")
        print(f"[{index}/{len(papers)}] {title[:60]}")

        summary = summarize_paper(title, abstract)
        if summary is None:
            continue

        result = {
            "id": paper.get("id", ""),
            "title": title,
            "abstract": abstract,
            "authors": paper.get("authors", []),
            "year": paper.get("year", ""),
            "url": paper.get("url", ""),
            "source": paper.get("source", ""),
            "categories": paper.get("categories", []),
            "purpose": summary.get("purpose", ""),
            "method": summary.get("method", ""),
            "result": summary.get("result", ""),
            "limitation": summary.get("limitation", ""),
        }
        summarized.append(result)

        print(f"  목적: {result['purpose'][:60]}")
        print(f"  방법: {result['method'][:60]}")
        print(f"  결과: {result['result'][:60]}")
        print(f"  한계: {result['limitation'][:60]}\n")

    save_summary_results(summarized)
    if run_id:
        save_run_reader_results(summarized, run_id)
    return summarized


if __name__ == "__main__":
    run_reader()
