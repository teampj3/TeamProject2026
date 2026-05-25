"""Search service for Semantic Scholar paper metadata."""

from __future__ import annotations

import json
import os
import re
import socket
import time
import hashlib
from collections.abc import Callable
from datetime import datetime
from difflib import SequenceMatcher
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()


SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
REQUEST_USER_AGENT = "TeamProject2026/1.0 (educational project)"
SEMANTIC_SCHOLAR_API_KEY = (
    os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    or os.getenv("S2_API_KEY", "")
)

DEFAULT_MAX_RESULTS = 20
MIN_ABSTRACT_WORDS = 40
MIN_TOPIC_MATCH_COUNT = 1
PIPELINE_CONTEXT_PATH = "data/processed/pipeline_context.json"
SEARCH_CACHE_META_PATH = "data/raw/search_result_meta.json"
MIN_METADATA_AUTHORS = 1
TITLE_SIMILARITY_THRESHOLD = 0.92
TITLE_TOKEN_OVERLAP_THRESHOLD = 0.8
SEMANTIC_SCHOLAR_RETRY_ATTEMPTS = 2
SEMANTIC_SCHOLAR_BACKOFF_SECONDS = [3, 6]

TOPIC_EXPANSIONS = {
    "ai": ["artificial", "intelligence", "llm", "model"],
    "review": ["reviewer", "feedback", "comment"],
    "code": ["coding", "software", "programming", "repository"],
    "automation": ["automated", "workflow", "agent"],
    "test": ["testing", "tests"],
}


class SearchStageError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def normalize_topic(topic: str) -> str:
    return re.sub(r"\s+", " ", topic.strip().lower())


def parse_to_paper_schema(raw: dict, source: str) -> dict:
    paper_id_seed = "|".join(
        [
            raw.get("url", ""),
            raw.get("title", ""),
            str(raw.get("year", "")),
            source,
        ]
    )
    return {
        "id": hashlib.sha1(paper_id_seed.encode("utf-8")).hexdigest()[:12],
        "title": raw.get("title", ""),
        "abstract": raw.get("abstract", ""),
        "authors": raw.get("authors", []),
        "source": source,
        "url": raw.get("url", ""),
        "year": raw.get("year", ""),
        "categories": raw.get("categories", []),
    }


def normalize_token(token: str) -> str:
    token = token.lower().strip()
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize_text(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z가-힣0-9+-]+", text.lower())
    return [normalize_token(token) for token in tokens if len(token) > 1]


def extract_topic_keywords(topic: str) -> set[str]:
    base_keywords = set(tokenize_text(topic))
    expanded_keywords = set(base_keywords)
    for keyword in base_keywords:
        expanded_keywords.update(TOPIC_EXPANSIONS.get(keyword, []))
    return expanded_keywords


def has_required_metadata(paper: dict) -> bool:
    return all(
        [
            paper.get("title", "").strip(),
            paper.get("abstract", "").strip(),
            paper.get("url", "").strip(),
            paper.get("source", "").strip(),
            len(paper.get("authors", [])) >= MIN_METADATA_AUTHORS,
        ]
    )


def has_sufficient_abstract(paper: dict) -> bool:
    return len(tokenize_text(paper.get("abstract", ""))) >= MIN_ABSTRACT_WORDS


def count_topic_matches(paper: dict, topic_keywords: set[str]) -> int:
    paper_tokens = set(tokenize_text(" ".join([paper.get("title", ""), paper.get("abstract", "")])))
    return len(topic_keywords & paper_tokens)


def normalize_title_for_dedup(title: str) -> str:
    normalized = title.lower().strip()
    normalized = re.sub(r"[-–—:/,.;()\[\]{}]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def is_similar_title(left: str, right: str) -> bool:
    left_normalized = normalize_title_for_dedup(left)
    right_normalized = normalize_title_for_dedup(right)

    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    if left_normalized in right_normalized or right_normalized in left_normalized:
        return True

    similarity = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    if similarity >= TITLE_SIMILARITY_THRESHOLD:
        return True

    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    if not left_tokens or not right_tokens:
        return False

    overlap_ratio = len(left_tokens & right_tokens) / max(min(len(left_tokens), len(right_tokens)), 1)
    return overlap_ratio >= TITLE_TOKEN_OVERLAP_THRESHOLD


def deduplicate_papers(papers: list[dict]) -> list[dict]:
    seen_urls: set[str] = set()
    seen_title_year: set[tuple[str, str]] = set()
    deduped: list[dict] = []

    for paper in papers:
        normalized_url = paper.get("url", "").strip().lower().rstrip("/")
        normalized_title = normalize_title_for_dedup(paper.get("title", ""))
        title_year_key = (normalized_title, str(paper.get("year", "")).strip())

        if normalized_url and normalized_url in seen_urls:
            continue
        if title_year_key in seen_title_year:
            continue
        if any(
            existing_year == title_year_key[1]
            and is_similar_title(existing_title, normalized_title)
            for existing_title, existing_year in seen_title_year
        ):
            continue

        if normalized_url:
            seen_urls.add(normalized_url)
        seen_title_year.add(title_year_key)
        deduped.append(paper)

    return deduped


def filter_papers_by_quality(papers: list[dict], topic: str) -> list[dict]:
    topic_keywords = extract_topic_keywords(topic)
    filtered: list[dict] = []

    removed_metadata = 0
    removed_abstract = 0
    removed_topic = 0

    for paper in papers:
        if not has_required_metadata(paper):
            removed_metadata += 1
            continue
        if not has_sufficient_abstract(paper):
            removed_abstract += 1
            continue
        if count_topic_matches(paper, topic_keywords) < MIN_TOPIC_MATCH_COUNT:
            removed_topic += 1
            continue
        filtered.append(paper)

    if removed_metadata:
        print(f"메타데이터가 부족한 논문 {removed_metadata}편 제외")
    if removed_abstract:
        print(f"초록이 너무 짧거나 비어 있는 논문 {removed_abstract}편 제외")
    if removed_topic:
        print(f"주제 적합성이 낮은 논문 {removed_topic}편 제외")

    return filtered


def search_semantic_scholar(
    query: str,
    limit: int = DEFAULT_MAX_RESULTS,
    status_callback: Callable[[str, str | None], None] | None = None,
) -> list[dict]:
    """Fetch paper metadata from Semantic Scholar."""
    params = {
        "query": query,
        "limit": limit,
        "fields": "title,abstract,authors,year,url,paperId",
    }
    url = f"{SEMANTIC_SCHOLAR_API_URL}?{urlencode(params)}"
    headers = {
        "User-Agent": REQUEST_USER_AGENT,
        "Accept": "application/json",
    }
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    else:
        print("Semantic Scholar API 키가 .env에 없어 공개 요청으로 진행합니다.")
        if status_callback:
            status_callback(
                "Semantic Scholar API key is missing. Falling back to public request mode.",
                None,
            )

    request = Request(url, headers=headers)

    data: dict = {}
    for attempt in range(SEMANTIC_SCHOLAR_RETRY_ATTEMPTS):
        try:
            with urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as error:
            if error.code == 429 and attempt < (SEMANTIC_SCHOLAR_RETRY_ATTEMPTS - 1):
                wait_seconds = SEMANTIC_SCHOLAR_BACKOFF_SECONDS[
                    min(attempt, len(SEMANTIC_SCHOLAR_BACKOFF_SECONDS) - 1)
                ]
                print(f"Semantic Scholar 요청 제한으로 {wait_seconds}초 후 재시도합니다.")
                if status_callback:
                    status_callback(
                        f"Retrying Semantic Scholar after rate limit (attempt {attempt + 1}/{SEMANTIC_SCHOLAR_RETRY_ATTEMPTS - 1})",
                        "SEARCH_RATE_LIMIT",
                    )
                time.sleep(wait_seconds)
                continue
            if error.code == 429:
                raise SearchStageError(
                    "SEARCH_RATE_LIMIT",
                    "Semantic Scholar rate limit exceeded",
                ) from error
            print(f"Semantic Scholar API 요청 실패: HTTP {error.code}")
            raise SearchStageError(
                "SEARCH_API_ERROR",
                f"Semantic Scholar API request failed with HTTP {error.code}",
            ) from error
        except URLError as error:
            print(f"Semantic Scholar API 연결 실패: {error.reason}")
            raise SearchStageError(
                "SEARCH_API_ERROR",
                f"Semantic Scholar API connection failed: {error.reason}",
            ) from error
        except (TimeoutError, socket.timeout):
            if attempt < (SEMANTIC_SCHOLAR_RETRY_ATTEMPTS - 1):
                wait_seconds = SEMANTIC_SCHOLAR_BACKOFF_SECONDS[
                    min(attempt, len(SEMANTIC_SCHOLAR_BACKOFF_SECONDS) - 1)
                ]
                print(f"Semantic Scholar 응답 지연으로 {wait_seconds}초 후 재시도합니다.")
                time.sleep(wait_seconds)
                continue
            print("Semantic Scholar API 응답 대기 시간이 초과되었습니다.")
            raise SearchStageError(
                "SEARCH_API_ERROR",
                "Semantic Scholar API timed out",
            )

    results = []
    for paper in data.get("data", []):
        raw = {
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", "") or "",
            "authors": [a.get("name", "") for a in paper.get("authors", []) if a.get("name")],
            "year": str(paper.get("year", "") or ""),
            "url": paper.get("url", "") or (
                f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}"
                if paper.get("paperId")
                else ""
            ),
            "categories": [],
        }
        results.append(parse_to_paper_schema(raw, source="Semantic Scholar"))

    return results


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("cp949", errors="replace").decode("cp949"))


def display_results(papers: list[dict]) -> None:
    if not papers:
        safe_print("검색 결과 없음")
        return

    safe_print("\n정제된 검색 결과 요약:")
    for index, paper in enumerate(papers, 1):
        authors = ", ".join(paper.get("authors", [])[:3])
        if len(paper.get("authors", [])) > 3:
            authors += " 외"
        abstract_preview = " ".join(paper.get("abstract", "").split())[:180]

        safe_print(f"[{index}] {paper.get('title', '')}")
        safe_print(f"  저자: {authors}")
        safe_print(f"  연도: {paper.get('year', '')} | 출처: {paper.get('source', '')}")
        safe_print(f"  초록 미리보기: {abstract_preview}")
        safe_print(f"  링크: {paper.get('url', '')}\n")

    safe_print(f"총 {len(papers)}편이 동일한 구조로 정제되었습니다.")


def validate_search_results(papers: list[dict]) -> bool:
    required_fields = {"id", "title", "abstract", "authors", "year", "url", "source"}
    return all(required_fields.issubset(paper.keys()) for paper in papers)


def save_search_result(papers: list[dict], topic: str | None = None) -> None:
    os.makedirs("data/raw", exist_ok=True)
    save_path = "data/raw/search_result.json"
    with open(save_path, "w", encoding="utf-8") as file:
        json.dump(papers, file, ensure_ascii=False, indent=2)

    if topic is not None:
        meta_payload = {
            "topic": topic,
            "normalized_topic": normalize_topic(topic),
            "saved_at": datetime.now().isoformat(),
            "count": len(papers),
        }
        with open(SEARCH_CACHE_META_PATH, "w", encoding="utf-8") as file:
            json.dump(meta_payload, file, ensure_ascii=False, indent=2)

    if validate_search_results(papers):
        print(f"\n저장 완료: {save_path}")
    else:
        print(f"\n저장 경고: {save_path} 파일 구조를 다시 확인하세요.")


def save_pipeline_topic(topic: str) -> None:
    os.makedirs("data/processed", exist_ok=True)
    with open(PIPELINE_CONTEXT_PATH, "w", encoding="utf-8") as file:
        json.dump({"topic": topic}, file, ensure_ascii=False, indent=2)


def save_run_search_result(papers: list[dict], run_id: str) -> None:
    from services.output_service import get_run_output_dir, write_json

    run_dir = get_run_output_dir(run_id)
    payload = [
        {
            "id": paper.get("id", ""),
            "title": paper.get("title", ""),
            "authors": paper.get("authors", []),
            "year": paper.get("year", ""),
            "source": paper.get("source", ""),
            "abstract": paper.get("abstract", ""),
            "snippet": " ".join(paper.get("abstract", "").split())[:280],
        }
        for paper in papers
    ]
    write_json(run_dir / "search_results.json", payload)


def load_cached_search_results(topic: str) -> list[dict]:
    search_path = "data/raw/search_result.json"
    if not os.path.exists(search_path) or not os.path.exists(SEARCH_CACHE_META_PATH):
        return []

    try:
        with open(SEARCH_CACHE_META_PATH, "r", encoding="utf-8") as file:
            meta = json.load(file)
        with open(search_path, "r", encoding="utf-8") as file:
            cached = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []

    cached_topic = normalize_topic(str(meta.get("topic", "")))
    requested_topic = normalize_topic(topic)
    if not cached_topic or not requested_topic:
        return []

    topic_similarity = SequenceMatcher(None, cached_topic, requested_topic).ratio()
    cached_keywords = extract_topic_keywords(cached_topic)
    requested_keywords = extract_topic_keywords(requested_topic)
    keyword_overlap = len(cached_keywords & requested_keywords)

    if topic_similarity < 0.7 and keyword_overlap < 2:
        return []

    if not isinstance(cached, list):
        return []

    return filter_papers_by_quality(cached, topic)


def run_search(
    topic: str,
    run_id: str | None = None,
    status_callback: Callable[[str, str | None], None] | None = None,
) -> list[dict]:
    """Integrated search flow for Search Agent."""
    if not topic.strip():
        raise SearchStageError("SEARCH_API_ERROR", "검색어가 비어 있습니다.")

    source_errors: list[SearchStageError] = []

    print(f"\n[Semantic Scholar 검색 중...] '{topic}'")
    try:
        semantic_results = search_semantic_scholar(topic, status_callback=status_callback)
    except SearchStageError as error:
        print(f"Semantic Scholar 검색 실패: {error.message}")
        source_errors.append(error)
        semantic_results = []

    if not semantic_results and source_errors:
        if status_callback:
            status_callback(
                "Semantic Scholar is unavailable. Checking cached search results.",
                "SEARCH_RATE_LIMIT",
            )

        cached_results = load_cached_search_results(topic)
        if cached_results:
            print("외부 API 제한으로 캐시된 검색 결과를 재사용합니다.")
            if status_callback:
                status_callback(
                    f"Using cached search results due to external API limits ({len(cached_results)} papers).",
                    "SEARCH_RATE_LIMIT",
                )
            if run_id:
                save_run_search_result(cached_results, run_id)
            save_pipeline_topic(topic)
            return cached_results

        error_codes = {error.error_code for error in source_errors}
        if "SEARCH_RATE_LIMIT" in error_codes:
            raise SearchStageError(
                "SEARCH_RATE_LIMIT",
                "Semantic Scholar rate limit exceeded",
            )
        messages = "; ".join(error.message for error in source_errors)
        raise SearchStageError("SEARCH_API_ERROR", messages)

    results = deduplicate_papers(semantic_results)
    results = filter_papers_by_quality(results, topic)
    if not results:
        print("품질 기준에 맞는 검색 결과가 없습니다. 다른 키워드를 시도해보세요.")
        if run_id:
            save_run_search_result(results, run_id)
        return []

    display_results(results)
    save_search_result(results, topic=topic)
    if run_id:
        save_run_search_result(results, run_id)
    save_pipeline_topic(topic)
    return results


if __name__ == "__main__":
    topic = input("검색할 주제를 입력하세요: ").strip()
    run_search(topic)
