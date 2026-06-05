# Search / Writer / Review 리팩토링 요약

## 개요
이번 리팩토링의 목표는 다음 두 가지였다.

1. 검색 단계에서 `논문 중심 근거 + 웹 보조 맥락`을 분리 수집한다.
2. Writer가 참고문헌 비교 보고서가 아니라 `본 연구 중심 논문 초안`을 생성하도록 구조를 바꾼다.

아울러 Review도 문장 품질 검사에서 더 나아가 `논문형 수사 구조 평가`까지 수행하도록 확장했다.

---

## 1. Search 리팩토링

### 이전 구조
- 사용자 주제를 바로 Semantic Scholar 검색어로 사용
- 논문 검색만 수행
- 검색 결과 스키마가 논문 전용
- 정렬 기준이 주제 적합성과 연도 중심

### 현재 구조
- `user_topic`은 그대로 유지하고, 검색 계획만 별도로 생성
- `query planning` 도입
  - `raw_topic`
  - `normalized_topic`
  - `core_keywords`
  - `english_support_query`(한국어 주제일 때)
- `2-layer search` 도입
  - `paper_search`: 핵심 근거 논문 수집
  - `web_support_search`: 공식 문서/기술 블로그/연구기관 자료 수집
- 검색 결과 스키마 확장
  - `source_type: paper | web`
  - `trust_level`
  - `citation_count`
  - `used_for: evidence | context`
- 논문 ranking 개선
  - 주제 적합성
  - `citation_count`
  - 최신성
  - 메타데이터 완전성

### 저장 파일
- `data/raw/search_result.json`
  - Reader가 바로 읽는 논문 결과
- `data/raw/search_web_result.json`
  - Writer가 최신 사례/실무 맥락 보조용으로 읽는 웹 자료
- `data/raw/search_plan.json`
  - query planning 결과

---

## 2. Writer 리팩토링

### 이전 구조
- 선별 논문 요약을 바로 섹션 프롬프트에 넣고 초안 생성
- 동적 목차는 있었지만, 본문이 쉽게 `문헌 비교/분석 보고서`처럼 흐를 수 있었음
- 참고 논문이 본문 중심이 되는 경향이 있었음

### 현재 구조
Writer는 이제 `자료 요약 -> 초안 생성`이 아니라,

`연구 스키마 생성 -> 논지 설계 -> 섹션 작성`

구조로 동작한다.

### 추가된 핵심 단계
#### 1. research framing step
- 사용자 주제를 바탕으로 `paper_type`을 먼저 정한다.
  - `proposal`
  - `analysis`
  - `review`

#### 2. structured schema generation
- 본문 생성 전에 아래 스키마를 먼저 만든다.
  - `research_problem`
  - `research_gap`
  - `research_question`
  - `analytic_framework`
  - `main_claims`
  - `contribution`
  - `thesis_statement`

#### 3. thesis-first writing
- 중심 논지를 먼저 고정하고, 각 섹션이 그 논지를 향해 쓰이도록 함

#### 4. discourse planning
- `paper_type`에 따라 본문 동적 섹션을 다르게 설계
- 예:
  - proposal형: 문제/공백 -> 분석 기준 -> 제안/활용
  - analysis형: 발전/개념 변화 -> 분석 틀 기반 해석 -> 주장/시사점
  - review형: 선행연구 동향/공백 -> 접근법 비교 -> 종합 평가

#### 5. citation-grounded generation
- 참고문헌은 근거 자료로만 사용
- 문장 주어를 가능한 한 `본 연구`, `본 논문` 중심으로 유지
- `A 논문은…, B 논문은…` 식 나열을 줄이는 방향으로 프롬프트 강화

#### 6. contribution output 강제
- 최소 하나 이상의 산출물이 드러나게 함
  - 분석 틀
  - 설계 원리
  - 분류 체계
  - 평가 기준
  - 프레임워크

### Writer가 추가로 읽는 자료
- `data/raw/search_web_result.json`
  - 논문은 핵심 근거
  - 웹 자료는 최신 사례/실무 맥락 보조

---

## 3. Review 리팩토링

### 이전 구조
- 주로 문장 품질과 기본 구조를 평가
- 핵심 평가 축:
  - `logic_score`
  - `structure_score`
  - `academic_style_score`
  - `research_focus_score`
  - `completeness_score`

### 현재 구조
Review는 이제 단순 문장 검사보다 더 넓게, `논문형 수사 구조`를 평가한다.

### 추가된 평가 축
- `contribution_clarity_score`
  - 본 연구의 기여와 산출물이 분명한가
- `thesis_consistency_score`
  - 중심 논지가 섹션 전반에 일관되게 이어지는가
- `literature_listing_risk`
  - 개별 문헌 나열 위험이 높은가

### PASS/FAIL 기준 강화
- 평균 점수 3.5 이상
- 필수 섹션 누락 없음
- 미완성 문장 없음
- `literature_listing_risk <= 3`

### 재작성 판단 반영
Review 결과에서 아래 항목도 재작성 조건으로 사용한다.
- 기여 명확성 부족
- 중심 논지 일관성 부족
- 문헌 나열 위험 과다

---

## 4. 파이프라인에서의 변화

### 이전 흐름
- Search
- Reader
- Relevance
- Writer
- Review

### 현재 흐름
- Search
  - paper/web 2-layer
  - query planning 포함
- Reader
- Relevance
- Writer
  - research schema 생성
  - thesis-first / discourse planning
- Review
  - 논문형 구조 rubric 평가
- Review-Writer loop
  - 논문형 문제를 기준으로 재작성 여부 판단

---

## 5. 핵심 효과

### Search
- 논문 중심 근거를 유지하면서 최신 사례를 보조적으로 확보할 수 있게 됨

### Writer
- 참고문헌을 분석하는 보고서보다 `본 연구 중심의 논문 초안`에 더 가까운 구조로 전환

### Review
- 단순 문장 품질뿐 아니라 `이 초안이 실제 논문형 구조를 갖추었는지`까지 평가 가능

---

## 6. 한 줄 요약

이번 리팩토링은

`Search를 논문+웹 보조 2층 구조로 바꾸고, Writer를 연구문제·공백·기여를 먼저 설계하는 논문형 생성기로 바꾸며, Review를 논문형 수사 구조 judge로 확장한 작업`

이다.
