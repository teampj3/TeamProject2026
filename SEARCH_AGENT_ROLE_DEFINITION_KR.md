# Search Agent 역할 정의

Search Agent는 사용자가 입력한 주제에 맞는 논문 메타데이터를 수집하고, 다음 단계에서 바로 활용할 수 있도록 1차 품질 정제까지 수행하는 역할을 담당한다.

## 주요 책임

- 사용자가 입력한 주제를 검색 키워드로 변환한다.
- Semantic Scholar에서 논문 메타데이터를 수집한다.
- 제목, 초록, 저자, 연도, 링크, 출처를 공통 구조로 정리한다.
- 메타데이터 완전성, 초록 품질, 주제 적합성을 기준으로 1차 필터링을 수행한다.
- URL, 제목+연도, 제목 유사도 기준으로 중복 논문을 제거한다.
- Reader Agent가 바로 사용할 수 있도록 `data/raw/search_result.json`으로 저장한다.

## 품질 기준

- 필수 메타데이터가 모두 존재해야 한다.
- 초록은 비어 있지 않고 최소 길이 기준을 만족해야 한다.
- 주제 핵심 키워드가 제목 또는 초록에 포함되어야 한다.
- 중복 논문은 URL, 제목/연도, 제목 유사도 기준으로 제거한다.

## 출력 데이터

Search Agent의 결과는 `data/raw/search_result.json`에 저장되며, 이후 Reader Agent가 동일한 JSON 구조를 입력으로 사용한다.

예상 출력 예시:

```json
[
  {
    "title": "Paper title",
    "abstract": "summary...",
    "authors": ["A", "B"],
    "source": "Semantic Scholar",
    "url": "https://..."
  }
]
```
