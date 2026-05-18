# TeamProject2026 개발 가이드

이 문서는 현재 프로젝트 구조에서 각 파일이 어떤 역할을 맡고, 앞으로 무엇을 개발해야 하는지 한국어로 정리한 문서입니다.

## 1. 전체 목표

이 프로젝트의 목표는 컴퓨터 분야 논문이나 기술 자료를 입력받아 다음 과정을 자동화하는 것입니다.

1. 자료 검색
2. 자료 요약
3. 관련성 판단
4. 보고서 초안 작성
5. 시각화 생성
6. 결과 검토
7. 최종 저장

즉, 하나의 Claude 호출로 끝나는 프로그램이 아니라 여러 역할을 가진 에이전트가 순서대로 협력하는 구조를 만드는 것이 핵심입니다.

## 2. 폴더별 역할

### `agents/`

각 단계별 에이전트 로직을 작성하는 폴더입니다.  
프로젝트의 핵심 기능이 들어갈 곳입니다.

### `services/`

에이전트들이 공통으로 사용하는 기능을 모아두는 폴더입니다.  
예를 들면 Claude API 호출, 논문 검색 API 호출, 시각화 생성 같은 공용 기능이 들어갑니다.

### `config/`

프로젝트 전체 설정값을 관리하는 폴더입니다.  
파이프라인 순서, 지원 주제 범위 같은 설정을 여기에 둡니다.

### `schemas/`

에이전트끼리 주고받는 데이터 형식을 정의하는 폴더입니다.  
논문 정보, 보고서 초안, 검토 결과 같은 구조를 정리합니다.

### `prompts/`

각 에이전트가 Claude에게 어떤 식으로 요청할지 프롬프트 초안을 저장하는 폴더입니다.

### `data/`

중간 데이터 저장용 폴더입니다.

- `raw/`: 검색 결과 원본 데이터
- `processed/`: 요약, 점수화 등 가공된 데이터
- `archive/`: 최종 보고서와 기록용 데이터

### `outputs/`

실행 결과물을 저장하는 폴더입니다.

- `reports/`: 최종 보고서 파일
- `visualizations/`: 차트, 표 이미지
- `logs/`: 실행 로그

## 3. 루트 파일 설명

### [README.md](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/README.md)

프로젝트 소개와 실행 방법을 적는 문서입니다.

앞으로 개발할 내용:

- 프로젝트 목적 간단 설명
- 실행 방법
- 폴더 구조 설명
- 각 에이전트 역할 요약

### [WINDOWS_SETUP_LOCAL.md](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/WINDOWS_SETUP_LOCAL.md)

윈도우 환경에서 실행할 때 필요한 설정 문서입니다.

앞으로 개발할 내용:

- `.venv` 활성화 방법
- `.env` 작성 방법
- 실행 명령어 정리
- 자주 나는 오류와 해결 방법

### [requirements.txt](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/requirements.txt)

필요한 파이썬 패키지 목록입니다.

앞으로 개발할 내용:

- 현재는 `anthropic`, `python-dotenv` 위주
- 나중에 필요하면 `requests`, `matplotlib`, `python-docx` 등을 추가

### [test_api.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/test_api.py)

Claude API 연결이 되는지 테스트하는 파일입니다.

앞으로 개발할 내용:

- 현재처럼 키 로드와 기본 호출 테스트 유지
- 필요하면 모델명, 응답 시간, 예외 메시지까지 출력하도록 보완

### [run_pipeline.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/run_pipeline.py)

전체 파이프라인을 시작하는 진입점 파일입니다.

앞으로 개발할 내용:

- 에이전트들을 순서대로 실행
- 단계별 입력과 출력 연결
- 실패한 단계에서 에러 처리
- 마지막 결과 저장

## 4. `agents/` 파일별 설명

### [agents/search_agent.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/agents/search_agent.py)

주제에 맞는 논문이나 기술 자료를 찾는 에이전트입니다.

개발해야 할 것:

- 사용자 주제를 검색 키워드로 변환
- Semantic Scholar 같은 소스에서 자료 검색
- 제목, 초록, 저자, 링크 등을 정리
- 결과를 JSON 형태로 반환

예상 출력 예시:

```python
[
    {
        "title": "Paper title",
        "abstract": "summary...",
        "authors": ["A", "B"],
        "source": "Semantic Scholar",
        "url": "..."
    }
]
```

### [agents/reader_agent.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/agents/reader_agent.py)

검색된 논문 내용을 읽고 핵심 정보를 구조화하는 에이전트입니다.

개발해야 할 것:

- 논문 초록 또는 본문 입력 받기
- Claude를 이용해 목적, 방법, 결과, 한계 추출
- 형식을 통일한 요약 JSON 만들기

예상 출력 예시:

```python
{
    "purpose": "...",
    "method": "...",
    "result": "...",
    "limitation": "..."
}
```

### [agents/relevance_agent.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/agents/relevance_agent.py)

논문이 현재 주제와 얼마나 관련 있는지 점수화하는 에이전트입니다.

개발해야 할 것:

- 주제와 논문 요약 비교
- 키워드 유사도 계산
- 관련성 점수 산출
- 점수 기준으로 논문 선별

예상 출력 예시:

```python
{
    "title": "Paper title",
    "score": 86,
    "reason": "테스트 자동화와 관련 키워드가 많이 일치함"
}
```

### [agents/write_agent.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/agents/write_agent.py)

선별된 자료를 바탕으로 한국어 보고서 초안을 작성하는 에이전트입니다.

개발해야 할 것:

- 여러 논문 요약을 입력으로 받기
- 보고서 목차 구조 만들기
- 서론, 본론, 결론 형태의 초안 작성
- Markdown 또는 텍스트 형태의 초안 생성

### [agents/review_agent.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/agents/review_agent.py)

작성된 보고서를 검토하고 수정 요청을 만드는 에이전트입니다.

개발해야 할 것:

- 논리성 점검
- 중복 표현 확인
- 누락된 섹션 확인
- 기준 점수 미달 시 수정 요청 JSON 생성

예상 출력 예시:

```python
{
    "score": 72,
    "needs_revision": true,
    "feedback": [
        "결과 비교 문단이 부족함",
        "방법 설명이 두 논문에만 치우쳐 있음"
    ]
}
```

### [agents/visualization_agent.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/agents/visualization_agent.py)

논문 비교 결과를 표나 그래프로 만드는 에이전트입니다.

개발해야 할 것:

- 어떤 시각화가 적절한지 결정
- 표, 막대그래프, 비교 차트 생성
- 결과 이미지를 `outputs/visualizations/`에 저장

### [agents/ArchiveManager_Agent.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/agents/ArchiveManager_Agent.py)

최종 결과와 중간 산출물을 저장하는 에이전트입니다.

개발해야 할 것:

- 최종 보고서 저장
- 논문 요약 JSON 저장
- 시각화 파일 경로 기록
- 실행 로그와 메타데이터 관리

## 5. `services/` 파일별 설명

### [services/llm_client.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/services/llm_client.py)

Claude API를 공통으로 호출하는 파일입니다.

개발해야 할 것:

- 프롬프트 전달 함수
- 모델명과 토큰 수 조절 옵션
- 예외 처리
- 응답 텍스트 추출 공통화

이 파일은 에이전트가 아니라 공용 도구입니다.

### [services/search_service.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/services/search_service.py)

논문 검색 API 호출을 담당하는 공용 서비스 파일입니다.

개발해야 할 것:

- Semantic Scholar API 요청
- Semantic Scholar API 요청
- 응답 데이터 정리
- 실패 시 재시도 또는 예외 처리

### [services/visualization_service.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/services/visualization_service.py)

시각화 생성 로직을 모아두는 파일입니다.

개발해야 할 것:

- 표 생성 함수
- 막대그래프 생성 함수
- 비교 차트 생성 함수
- 이미지 파일 저장 함수

### [services/archive_service.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/services/archive_service.py)

파일 저장과 아카이브 관리를 공통 처리하는 파일입니다.

개발해야 할 것:

- JSON 저장
- 텍스트 저장
- 이미지 저장 경로 관리
- 실행 날짜별 폴더 분리

## 6. `config/` 파일별 설명

### [config/pipeline.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/config/pipeline.py)

전체 처리 단계를 순서대로 정의하는 파일입니다.

개발해야 할 것:

- 실제 실행 순서 유지
- 필요하면 재시도 단계나 조건부 분기 추가

### [config/topics.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/config/topics.py)

초기 주제 범위를 제한하는 파일입니다.

개발해야 할 것:

- 현재는 소프트웨어 공학, 생성형 AI 응용, 코드 자동화 중심
- 나중에 보안, 네트워크, 데이터베이스 등으로 확장

## 7. `schemas/` 파일별 설명

### [schemas/paper_schema.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/schemas/paper_schema.py)

논문 메타데이터 구조를 정의하는 파일입니다.

개발해야 할 것:

- 제목
- 초록
- 저자
- 출처
- 링크
- 발행 연도

### [schemas/report_schema.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/schemas/report_schema.py)

보고서 초안 구조를 정의하는 파일입니다.

개발해야 할 것:

- 주제
- 섹션 목록
- 본문 내용
- 참고한 논문 목록

### [schemas/review_schema.py](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/schemas/review_schema.py)

검토 결과 구조를 정의하는 파일입니다.

개발해야 할 것:

- 점수
- 수정 필요 여부
- 피드백 목록

## 8. `prompts/` 파일별 설명

### [prompts/search_agent.md](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/prompts/search_agent.md)

Search Agent가 사용할 검색 기준 프롬프트를 정리합니다.

개발해야 할 것:

- 어떤 주제를 어떤 키워드로 바꿀지
- 어떤 자료를 우선 검색할지
- 어떤 결과를 제외할지

### [prompts/reader_agent.md](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/prompts/reader_agent.md)

Reader Agent의 요약 프롬프트를 정리합니다.

개발해야 할 것:

- 목적, 방법, 결과, 한계를 같은 형식으로 뽑는 지시문
- 너무 긴 출력 방지 규칙

### [prompts/relevance_agent.md](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/prompts/relevance_agent.md)

Relevance Agent의 판단 기준을 정리합니다.

개발해야 할 것:

- 관련성 판단 기준
- 점수 범위
- 점수 이유 설명 방식

### [prompts/visualization_agent.md](C:/Users/s6151/OneDrive/문서/New%20project/TeamProject2026/prompts/visualization_agent.md)

Visualization Agent의 시각화 추천 기준을 정리합니다.

개발해야 할 것:

- 어떤 데이터에 어떤 차트를 쓸지
- 표와 그래프 선택 기준

## 9. 우선 개발 순서 추천

현재는 아래 순서로 개발하는 것이 가장 자연스럽습니다.

1. `services/llm_client.py`
2. `test_api.py`
3. `services/search_service.py`
4. `agents/search_agent.py`
5. `agents/reader_agent.py`
6. `agents/relevance_agent.py`
7. `agents/write_agent.py`
8. `agents/review_agent.py`
9. `agents/visualization_agent.py`
10. `agents/ArchiveManager_Agent.py`
11. `run_pipeline.py`

## 10. 지금 기준으로 꼭 기억할 점

- 지금 구조는 완성본이 아니라 뼈대입니다.
- 각 `agent`는 자기 단계의 판단과 변환만 담당하게 만드는 것이 좋습니다.
- 실제 API 호출, 파일 저장, 차트 생성 같은 공통 기능은 `services/`에 두는 것이 구조상 깔끔합니다.
- 에이전트끼리 주고받는 데이터 형식은 초반부터 `schemas/` 기준으로 맞추는 것이 중요합니다.
