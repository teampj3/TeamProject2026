"""VectorDB Service - ChromaDB 기반 논문 저장 및 RAG 검색."""

from __future__ import annotations

import json
from pathlib import Path

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ModuleNotFoundError:
    chromadb = None
    embedding_functions = None

# ChromaDB 저장 경로
VECTORDB_PATH = Path("data/vectordb")
COLLECTION_NAME = "paper_summaries"
SUMMARY_PATH = Path("data/processed/summary_result.json")

# 기본 임베딩 함수 (sentence-transformers 자동 다운로드)
DEFAULT_EF = embedding_functions.DefaultEmbeddingFunction() if embedding_functions else None


def get_collection():
    """ChromaDB 클라이언트와 컬렉션을 반환한다."""
    if chromadb is None or DEFAULT_EF is None:
        raise RuntimeError("ChromaDB is not installed.")
    VECTORDB_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(VECTORDB_PATH))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=DEFAULT_EF,
    )
    return collection


def build_document_text(paper: dict) -> str:
    """논문의 purpose, method, result, limitation을 하나의 텍스트로 합친다."""
    parts = [
        paper.get("title", ""),
        paper.get("purpose", ""),
        paper.get("method", ""),
        paper.get("result", ""),
        paper.get("limitation", ""),
    ]
    return " ".join(part for part in parts if part.strip())


def index_papers(papers: list[dict]) -> int:
    """
    논문 목록을 ChromaDB에 저장한다.
    이미 존재하는 논문은 업데이트하고, 새 논문은 추가한다.
    반환값: 저장된 논문 수
    """
    if not papers:
        print("[VectorDB] 저장할 논문이 없습니다.")
        return 0

    if chromadb is None or DEFAULT_EF is None:
        print("[VectorDB] ChromaDB가 설치되지 않아 인덱싱을 건너뜁니다.")
        return 0

    collection = get_collection()

    documents: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []

    for paper in papers:
        title = paper.get("title", "").strip()
        if not title:
            continue

        doc_text = build_document_text(paper)
        if not doc_text.strip():
            continue

        documents.append(doc_text)
        metadatas.append({
            "title": title,
            "year": str(paper.get("year", "")),
            "authors": ", ".join(paper.get("authors", [])),
            "url": paper.get("url", ""),
            "source": paper.get("source", ""),
            "purpose": paper.get("purpose", ""),
            "method": paper.get("method", ""),
            "result": paper.get("result", ""),
            "limitation": paper.get("limitation", ""),
        })
        # title을 ID로 사용 (특수문자 제거)
        safe_id = "".join(c if c.isalnum() or c in "_- " else "_" for c in title)[:100]
        ids.append(safe_id)

    if not documents:
        print("[VectorDB] 유효한 논문 데이터가 없습니다.")
        return 0

    # upsert: 있으면 업데이트, 없으면 추가
    collection.upsert(
        documents=documents,
        metadatas=metadatas,
        ids=ids,
    )

    print(f"[VectorDB] {len(documents)}편 저장 완료 (경로: {VECTORDB_PATH})")
    return len(documents)


def search_papers(query: str, n_results: int = 3) -> list[dict]:
    """
    쿼리 텍스트와 가장 관련된 논문을 검색한다.
    반환값: 관련도 높은 순으로 정렬된 논문 목록
    """
    if chromadb is None or DEFAULT_EF is None:
        print("[VectorDB] ChromaDB가 설치되지 않아 유사 논문 검색을 건너뜁니다.")
        return []

    collection = get_collection()

    count = collection.count()
    if count == 0:
        print("[VectorDB] 저장된 논문이 없습니다. index_papers()를 먼저 실행하세요.")
        return []

    # 저장된 논문 수보다 많이 요청하면 조정
    actual_n = min(n_results, count)

    results = collection.query(
        query_texts=[query],
        n_results=actual_n,
    )

    papers: list[dict] = []
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for metadata, distance in zip(metadatas, distances):
        paper = {
            "title": metadata.get("title", ""),
            "purpose": metadata.get("purpose", ""),
            "method": metadata.get("method", ""),
            "result": metadata.get("result", ""),
            "limitation": metadata.get("limitation", ""),
            "authors": metadata.get("authors", "").split(", ") if metadata.get("authors") else [],
            "year": metadata.get("year", ""),
            "url": metadata.get("url", ""),
            "source": metadata.get("source", ""),
            "relevance_distance": round(distance, 4),  # 낮을수록 관련도 높음
        }
        papers.append(paper)

    return papers


def load_and_index_from_summary(path: Path = SUMMARY_PATH) -> int:
    """
    summary_result.json을 읽어서 ChromaDB에 인덱싱한다.
    파이프라인에서 reader_agent 실행 후 호출하면 된다.
    """
    if not path.exists():
        print(f"[VectorDB] 파일 없음: {path}")
        return 0

    try:
        papers = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"[VectorDB] JSON 파싱 실패: {path}")
        return 0

    if not isinstance(papers, list):
        print(f"[VectorDB] 목록 형식이 아님: {path}")
        return 0

    print(f"[VectorDB] {len(papers)}편 인덱싱 시작...")
    return index_papers(papers)


if __name__ == "__main__":
    # 단독 실행 시 summary_result.json 인덱싱 테스트
    count = load_and_index_from_summary()
    if count > 0:
        print("\n검색 테스트: '서론 연구 배경'")
        results = search_papers("서론 연구 배경", n_results=2)
        for i, paper in enumerate(results, 1):
            print(f"\n[{i}] {paper['title']}")
            print(f"  거리: {paper['relevance_distance']}")
            print(f"  목적: {paper['purpose'][:80]}")
