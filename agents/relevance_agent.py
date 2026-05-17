"""Relevance Agent - score and select papers for the Writer Agent."""

from __future__ import annotations

import json
import os
import re
from collections import Counter

from services.output_service import get_run_output_dir, write_json


STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "in",
    "on",
    "for",
    "to",
    "with",
    "using",
    "based",
    "via",
    "is",
    "are",
    "be",
    "this",
    "that",
    "we",
    "our",
    "was",
    "were",
    "has",
    "have",
    "it",
    "its",
    "by",
    "as",
    "at",
    "from",
    "also",
    "can",
    "which",
    "into",
    "than",
    "their",
    "they",
    "will",
    "would",
    "been",
    "being",
    "through",
    "about",
    "such",
}

CORE_CS_TERMS = [
    "ai",
    "review",
    "automation",
    "software",
    "code",
    "programming",
    "system",
    "model",
    "analysis",
    "network",
    "testing",
    "test",
]

TOPIC_EXPANSIONS = {
    "ai": ["artificial", "intelligence", "llm", "model"],
    "review": ["reviews", "reviewer", "feedback"],
    "automation": ["automated", "automatic", "workflow"],
    "software": ["system", "application", "programming"],
    "code": ["coding", "program", "java", "scratch"],
    "test": ["testing", "tests", "generation"],
}

SELECTION_THRESHOLD = 30.0
SUMMARY_PATH = "data/processed/summary_result.json"
RELEVANCE_PATH = "data/processed/relevance_result.json"
MIN_KEYWORD_COUNT = 3


def load_summary_results(path: str = SUMMARY_PATH) -> list[dict]:
    if not os.path.exists(path):
        print(f"파일 없음: {path}")
        return []

    with open(path, "r", encoding="utf-8") as file:
        papers = json.load(file)

    print(f"논문 요약 {len(papers)}편 불러옴")
    return papers


def save_relevance_results(results: list[dict], path: str = RELEVANCE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)
    print(f"\n저장 완료: {path}")
    print("이 JSON은 이후 Writer Agent 입력으로 사용될 예정입니다.")


def normalize_token(token: str) -> str:
    token = token.lower().strip()
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize_text(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z가-힣0-9+-]+", text.lower())
    return [normalize_token(token) for token in tokens if token not in STOPWORDS and len(token) > 1]


def extract_topic_keywords(topic: str) -> list[str]:
    base_keywords = set(tokenize_text(topic))
    expanded_keywords = set(base_keywords)
    for keyword in base_keywords:
        expanded_keywords.update(TOPIC_EXPANSIONS.get(keyword, []))
    keywords = sorted(expanded_keywords)
    print(f"주제 키워드: {keywords}")
    return keywords


def get_paper_text(paper: dict) -> str:
    return " ".join(
        [
            paper.get("abstract", ""),
            paper.get("purpose", ""),
            paper.get("method", ""),
            paper.get("result", ""),
        ]
    )


def extract_paper_keywords(paper: dict) -> list[str]:
    return sorted(set(tokenize_text(get_paper_text(paper))))


def has_usable_summary_data(paper: dict) -> bool:
    fields = [
        paper.get("abstract", "").strip(),
        paper.get("purpose", "").strip(),
        paper.get("method", "").strip(),
        paper.get("result", "").strip(),
    ]
    return any(fields)


def build_fallback_result(
    paper: dict,
    topic_keywords: list[str],
    message: str,
) -> dict:
    return {
        "id": paper.get("id", ""),
        "title": paper.get("title", ""),
        "score": 0.0,
        "reason": message,
        "keywords": [],
        "shared_keywords": [],
        "topic_keywords": topic_keywords,
        "term_counts": {term: 0 for term in CORE_CS_TERMS},
        "selection_result": "재분석 필요",
        "authors": paper.get("authors", []),
        "year": paper.get("year", ""),
        "url": paper.get("url", ""),
        "source": paper.get("source", ""),
    }


def calculate_jaccard_similarity(
    topic_keywords: list[str], paper_keywords: list[str]
) -> tuple[float, set[str]]:
    topic_set = set(topic_keywords)
    paper_set = set(paper_keywords)
    if not topic_set and not paper_set:
        return 0.0, set()

    intersection = topic_set & paper_set
    union = topic_set | paper_set
    score = len(intersection) / len(union) if union else 0.0
    return score, intersection


def calculate_overlap_ratio(
    topic_keywords: list[str], paper_keywords: list[str]
) -> tuple[float, set[str]]:
    topic_set = set(topic_keywords)
    paper_set = set(paper_keywords)
    if not topic_set:
        return 0.0, set()

    overlap = topic_set & paper_set
    score = len(overlap) / len(topic_set)
    return score, overlap


def calculate_title_overlap_score(topic_keywords: list[str], title: str) -> tuple[float, set[str]]:
    title_tokens = set(tokenize_text(title))
    shared = set(topic_keywords) & title_tokens
    if not topic_keywords:
        return 0.0, set()
    return len(shared) / len(set(topic_keywords)), shared


def calculate_term_frequency_score(
    paper: dict, core_terms: list[str]
) -> tuple[dict[str, int], int, float]:
    tokens = tokenize_text(get_paper_text(paper))
    counter = Counter(tokens)
    term_counts = {term: counter.get(term, 0) for term in core_terms}
    total_hits = sum(term_counts.values())
    return term_counts, total_hits, float(total_hits)


def normalize_frequency_scores(raw_scores: list[float]) -> list[float]:
    if not raw_scores:
        return []
    max_score = max(raw_scores)
    if max_score == 0:
        return [0.0 for _ in raw_scores]
    return [score / max_score for score in raw_scores]


def calculate_final_relevance_score(
    jaccard_score: float,
    overlap_score: float,
    frequency_score: float,
    title_overlap_score: float,
) -> float:
    combined_score = (
        (jaccard_score * 0.25)
        + (overlap_score * 0.35)
        + (frequency_score * 0.20)
        + (title_overlap_score * 0.20)
    )
    return round(combined_score * 100, 1)


def build_score_reason(
    shared_keywords: set[str], total_hits: int, final_score: float, title_overlap: set[str]
) -> str:
    reasons: list[str] = []

    if shared_keywords:
        reasons.append(f"주제와 겹치는 키워드가 {len(shared_keywords)}개 있음")
    else:
        reasons.append("주제와 직접 겹치는 키워드는 없음")

    if total_hits > 0:
        reasons.append(f"컴퓨터 분야 핵심 용어가 총 {total_hits}회 등장함")
    else:
        reasons.append("컴퓨터 분야 핵심 용어 등장 빈도는 낮음")

    if title_overlap:
        reasons.append(f"제목에서 관련 키워드 {sorted(title_overlap)}가 확인됨")

    if final_score >= SELECTION_THRESHOLD:
        reasons.append("선별 기준 이상으로 관련 논문 후보로 볼 수 있음")
    else:
        reasons.append("선별 기준 미만으로 우선순위는 낮음")

    return ", ".join(reasons)


def print_selected_papers(sorted_rows: list[dict]) -> None:
    selected_rows = [row for row in sorted_rows if row["score"] >= SELECTION_THRESHOLD]

    print("\n관련성 점수 정렬 결과:")
    for rank, row in enumerate(sorted_rows, 1):
        print(f"  {rank}. {row['title'][:60]} - {row['score']:.1f}/100 ({row['selection_result']})")

    print(f"\n선별 기준 점수: {SELECTION_THRESHOLD:.1f}점 이상")
    if selected_rows:
        print("선별된 논문 목록:")
        for rank, row in enumerate(selected_rows, 1):
            print(f"  {rank}. {row['title'][:60]} - {row['score']:.1f}/100")
    else:
        print("선별된 논문이 없습니다.")

    print("\n이후 Writer Agent에는 이 선별 결과만 전달될 예정입니다.")


def build_relevance_result(
    paper: dict,
    topic_keywords: list[str],
    frequency_score: float,
    raw_data: dict,
) -> dict:
    final_score = calculate_final_relevance_score(
        jaccard_score=raw_data["jaccard_score"],
        overlap_score=raw_data["overlap_score"],
        frequency_score=frequency_score,
        title_overlap_score=raw_data["title_overlap_score"],
    )
    selection_result = "선별 통과" if final_score >= SELECTION_THRESHOLD else "선별 제외"
    reason = build_score_reason(
        raw_data["shared_keywords"],
        raw_data["total_hits"],
        final_score,
        raw_data["title_overlap"],
    )

    return {
        "id": paper.get("id", ""),
        "title": paper.get("title", ""),
        "score": final_score,
        "reason": reason,
        "keywords": raw_data["paper_keywords"][:15],
        "shared_keywords": sorted(raw_data["shared_keywords"]),
        "topic_keywords": topic_keywords,
        "term_counts": raw_data["term_counts"],
        "selection_result": selection_result,
        "authors": paper.get("authors", []),
        "year": paper.get("year", ""),
        "url": paper.get("url", ""),
        "source": paper.get("source", ""),
    }


def save_run_relevance_results(results: list[dict], run_id: str) -> None:
    run_dir = get_run_output_dir(run_id)
    payload = [
        {
            "id": result.get("id", ""),
            "relevance_score": result.get("score", 0.0),
            "selected": result.get("selection_result") == "선별 통과",
            "reason": result.get("reason", ""),
        }
        for result in results
    ]
    write_json(run_dir / "relevance_results.json", payload)


def run_relevance(topic: str, run_id: str | None = None) -> list[dict]:
    papers = load_summary_results()
    if not papers:
        return []

    topic_keywords = extract_topic_keywords(topic)

    print("\n논문별 최종 관련성 점수 계산:")
    print("최종 점수 = 키워드 유사도 25% + 키워드 겹침 비율 35% + 핵심 용어 빈도 점수 20% + 제목 일치도 20%")
    print(f"컴퓨터 분야 핵심 용어 기준: {CORE_CS_TERMS}")
    print(f"Relevance Agent 선별 기준: 최종 관련성 점수 {SELECTION_THRESHOLD}점 이상")

    raw_rows: list[dict] = []
    raw_frequency_scores: list[float] = []
    skipped_results: list[dict] = []

    for paper in papers:
        if not has_usable_summary_data(paper):
            message = "요약 데이터가 부족해 점수 계산이 어려워 기본값 0점으로 처리함"
            print(f"\n[건너뜀] {paper.get('title', '')[:60]}")
            print(f"  예외 처리: {message}")
            skipped_results.append(build_fallback_result(paper, topic_keywords, message))
            continue

        paper_keywords = extract_paper_keywords(paper)
        if len(paper_keywords) < MIN_KEYWORD_COUNT:
            message = f"추출 키워드가 {len(paper_keywords)}개로 부족해 기본값 0점으로 처리함"
            print(f"\n[건너뜀] {paper.get('title', '')[:60]}")
            print(f"  예외 처리: {message}")
            skipped_results.append(build_fallback_result(paper, topic_keywords, message))
            continue

        jaccard_score, shared_keywords = calculate_jaccard_similarity(topic_keywords, paper_keywords)
        overlap_score, shared_overlap = calculate_overlap_ratio(topic_keywords, paper_keywords)
        title_overlap_score, title_overlap = calculate_title_overlap_score(topic_keywords, paper["title"])
        term_counts, total_hits, raw_frequency_score = calculate_term_frequency_score(paper, CORE_CS_TERMS)

        raw_rows.append(
            {
                "paper": paper,
                "paper_keywords": paper_keywords,
                "jaccard_score": jaccard_score,
                "shared_keywords": shared_keywords,
                "overlap_score": overlap_score,
                "shared_overlap": shared_overlap,
                "title_overlap_score": title_overlap_score,
                "title_overlap": title_overlap,
                "term_counts": term_counts,
                "total_hits": total_hits,
            }
        )
        raw_frequency_scores.append(raw_frequency_score)

    normalized_frequency_scores = normalize_frequency_scores(raw_frequency_scores)

    relevance_results: list[dict] = []
    for index, row in enumerate(raw_rows, 1):
        paper = row["paper"]
        frequency_score = normalized_frequency_scores[index - 1]
        result = build_relevance_result(paper, topic_keywords, frequency_score, row)

        print(f"\n[{index}] {result['title'][:60]}")
        print(f"  논문 키워드(상위 10개): {row['paper_keywords'][:10]}")
        print(f"  공통 키워드: {result['shared_keywords'] if result['shared_keywords'] else '없음'}")
        print(f"  Jaccard 유사도: {row['jaccard_score']:.3f}")
        print(f"  겹침 비율: {row['overlap_score']:.3f} ({len(row['shared_overlap'])}/{len(set(topic_keywords))})")
        print(f"  제목 일치도: {row['title_overlap_score']:.3f}")
        print(f"  핵심 용어 빈도: {row['term_counts']}")
        print(f"  빈도 기반 점수: {frequency_score:.3f}")
        print(f"  최종 관련성 점수: {result['score']:.1f}/100")
        print(f"  판정: {result['selection_result']}")
        print(f"  이유: {result['reason']}")

        relevance_results.append(result)

    relevance_results.extend(skipped_results)
    sorted_results = sorted(relevance_results, key=lambda item: item["score"], reverse=True)
    print_selected_papers(sorted_results)
    save_relevance_results(sorted_results)
    if run_id:
        save_run_relevance_results(sorted_results, run_id)
    return sorted_results


if __name__ == "__main__":
    topic = input("\n관련성을 평가할 주제를 입력하세요 (예: AI code review): ").strip()
    if not topic:
        topic = "AI code review"
    results = run_relevance(topic)
    if not results:
        raise SystemExit(1)
